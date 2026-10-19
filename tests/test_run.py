"""run과 CLI — 합성 프로젝트 전체 실행, ID 순서, 결정성, 설정 오류, 미지원 파일, 출력 바꿔 넣기, 화면 요약.
"""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from fixtures import expected as E
from si_prep import chunks, run
from si_prep.config import ConfigError, load_project
from conftest import SHOP

OUTPUTS = ("items.jsonl", "links.jsonl", "warnings.jsonl", "chunks.jsonl")


@pytest.fixture(scope="module")
def shop_result():
    return run.build(SHOP)


def _where(result):
    """IT 번호 → (파일, 시트, 시작 행)"""
    return {i.item_id: (i.doc_file, i.locations[0].sheet, i.locations[0].rows.start) for i in result.items}


# ---------- 합성 프로젝트: BEFORE_1008과 같음 ----------

def test_items_match_before(shop_result):
    excluded = set(E.BEFORE_1008["excluded_sheets"])
    got = [{"file": i.doc_file, "sheet": i.locations[0].sheet, "rows": (i.locations[0].rows.start, i.locations[0].rows.end),
            "path_text": i.category_path_text, "status": i.status, "title": i.title, "source_id": i.source_id,
            "ref_ids": i.ref_ids, "merged": {c: m.source_row for c, m in i.merged_fields.items()}}
           for i in shop_result.items if (i.doc_file, i.locations[0].sheet) not in excluded]
    key = lambda x: (x["file"], x["sheet"], x["rows"])
    assert sorted(got, key=key) == sorted(E.BEFORE_1008["items"], key=key)


def test_links_match_before(shop_result):
    where = _where(shop_result)
    got = []
    for lk in shop_result.links:
        if lk.item_a:
            got.append((lk.rule_id, lk.method, frozenset({where[lk.item_a], where[lk.item_b]})))
        else:
            got.append((lk.rule_id, lk.method, where[lk.item], (lk.group.doc_type, lk.group.category_path_text)))
    want = [(l["rule_id"], l["method"], frozenset({l["a"], l["b"]})) if "a" in l
            else (l["rule_id"], l["method"], l["item"], l["group"]) for l in E.BEFORE_1008["links"]]
    assert sorted(got, key=str) == sorted(want, key=str)


def test_warnings_match_before(shop_result):
    excluded = set(E.BEFORE_1008["excluded_sheets"])
    got = [w for w in shop_result.warnings
           if (w.file, w.sheet) not in excluded and w.kind not in E.BEFORE_1008["excluded_warning_kinds"]]
    simple = sorted(((w.kind, w.file, w.sheet, tuple((l.sheet, l.rows.start, l.rows.end, tuple(l.cols) if l.cols else None)
                                                    for l in w.locations)) for w in got), key=str)
    want = sorted(((w["kind"], w["file"], w["sheet"], tuple((s, a, b, tuple(c) if c else None) for s, a, b, c in w["locations"]))
                   for w in E.BEFORE_1008["warnings"]), key=str)
    assert simple == want
    for w in E.BEFORE_1008["warnings"]:
        if "message_contains" in w:
            assert any(x.kind == w["kind"] and x.file == w["file"] and w["message_contains"] in x.message for x in got)


# ---------- 번호 ----------

def test_item_ids_in_document_order(shop_result):
    ids = [i.item_id for i in shop_result.items]
    assert ids == [f"IT-{n:06d}" for n in range(1, len(ids) + 1)]
    assert _where(shop_result)["IT-000001"] == ("가상몰_요구사항정의서.xlsx", "요구사항", 2)


def test_link_ids_by_rule_then_items(shop_result):
    rules = [r.id for r in load_project(SHOP).link_rules]
    order = [rules.index(lk.rule_id) for lk in shop_result.links]
    assert order == sorted(order) and [lk.link_id for lk in shop_result.links][0] == "LK-000001"
    pairs = [(lk.item_a, lk.item_b) for lk in shop_result.links if lk.rule_id == "fo_test"]
    assert pairs == sorted(pairs) and all(a < b for a, b in pairs)


def test_warnings_sorted_and_item_ids_filled(shop_result):
    ids = [w.warning_id for w in shop_result.warnings]
    assert ids == [f"WN-{n:06d}" for n in range(1, len(ids) + 1)]
    where = _where(shop_result)
    mu = next(w for w in shop_result.warnings if w.kind == "merge_unrestored" and w.sheet == "회원")
    assert [where[i] for i in mu.item_ids] == [("가상몰_기능정의서_v1.2.xlsx", "회원", 10)]
    cm = next(w for w in shop_result.warnings if w.kind == "content_mismatch")
    assert sorted(where[i][1:] for i in cm.item_ids) == [("요약", 7), ("주문", 6)]
    assert [l.sheet for l in cm.locations] == ["주문", "요약"]                    # 위치도 시트 순서로
    files = [w.file for w in shop_result.warnings]
    assert files.index("가상몰_기능정의서_v1.2.xlsx") < files.index("가상몰_정책정의서.xlsx")   # 문서 순서(16a 뒤 요구사항 파일 경고 없음)


def test_one_chunk_per_item(shop_result):
    assert [c.chunk_id for c in shop_result.chunks] == [f"B1-{i.item_id}" for i in shop_result.items]


# ---------- 쓰기 ----------

def test_write_is_deterministic_bytes(tmp_path):
    run.run(SHOP, tmp_path / "a")
    run.run(SHOP, tmp_path / "b")
    for name in OUTPUTS:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_json_lines_format(tmp_path):
    run.run(SHOP, tmp_path / "o")
    raw = (tmp_path / "o" / "items.jsonl").read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert "회원".encode("utf-8") in raw and b"\\u" not in raw                       # 한글 그대로
    first = json.loads(raw.decode("utf-8").splitlines()[0])
    assert list(first)[:3] == ["schema_version", "item_id", "doc_type"]             # 모델 필드 순서


def test_config_error_writes_nothing(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("project: x\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        run.run(bad, tmp_path / "o")
    assert not (tmp_path / "o").exists()


def test_failure_keeps_previous_outputs_and_other_files(tmp_path, monkeypatch):
    out = tmp_path / "o"
    run.run(SHOP, out)
    (out / "note.txt").write_text("사람이 둔 파일", encoding="utf-8")
    before = {n: (out / n).read_bytes() for n in OUTPUTS}

    def boom(*a, **k):
        raise RuntimeError("중간 실패")
    monkeypatch.setattr(chunks, "make_chunk", boom)
    with pytest.raises(RuntimeError):
        run.run(SHOP, out)
    assert {n: (out / n).read_bytes() for n in OUTPUTS} == before                  # 전부 이전 실행
    assert (out / "note.txt").read_text(encoding="utf-8") == "사람이 둔 파일"
    assert sorted(p.name for p in out.iterdir()) == sorted(list(OUTPUTS) + ["report.md", "report_목록.md", "note.txt"])   # 임시 파일 안 남음


def test_unsupported_files_do_not_stop_others(shop_result):
    kinds = {(w.kind, w.file) for w in shop_result.warnings}
    assert ("unsupported", "가상몰_옛형식.xls") in kinds and ("unsupported", "가상몰_가짜확장자.xlsx") in kinds
    assert any(i.doc_file == "가상몰_변형.xlsx" for i in shop_result.items)


def test_trial_run_profile_source_auto(tmp_path):
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["approved"] = False
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = run.build(project)
    assert {i.profile_source for i in result.items} == {"auto"} and {l.profile_source for l in result.links} == {"auto"}


# ---------- --out 위치·CLI ----------

def test_out_location_rule_repo_out_ok_elsewhere_in_repo_error(tmp_path):
    # 2026-10-12: 저장소 밖·저장소 안 out 폴더 아래는 그대로, 저장소 안 그 밖의 곳은 오류. 진짜 저장소 대신 가짜 뿌리로
    repo = tmp_path / "repo"
    assert run.out_location_error(repo / "out" / "x", repo) is None
    assert run.out_location_error(tmp_path / "elsewhere", repo) is None
    assert run.out_location_error(repo / "tests" / "x", repo) is not None
    assert run.out_location_error(repo, repo) is not None
    assert run.out_location_error(repo / "outside", repo) is not None    # 이름만 out으로 시작하는 폴더는 아님
    real = Path(run.__file__).resolve().parents[2]
    assert run.out_location_error(real / "tests" / "x") is not None      # 기본값은 이 저장소


def test_cli_out_under_repo_out_runs_without_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path / "repo")
    out = tmp_path / "repo" / "out" / "o"
    assert run.main(["--project", str(SHOP), "--out", str(out)]) == 0
    assert "저장소 안" not in capsys.readouterr().out and (out / "items.jsonl").exists()


def test_cli_out_elsewhere_in_repo_is_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path / "repo")
    out = tmp_path / "repo" / "docs" / "o"
    assert run.main(["--project", str(SHOP), "--out", str(out)]) == 1
    assert not out.exists() and "저장소 안" in capsys.readouterr().out


def test_cli_out_outside_repo_runs_without_warning(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path / "repo")
    assert run.main(["--project", str(SHOP), "--out", str(tmp_path / "work" / "o")]) == 0
    assert "저장소 안" not in capsys.readouterr().out


def test_cli_exit_codes_and_summary(tmp_path, capsys):
    assert run.main(["--project", str(SHOP), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert "| 문서 | 파일 | 시트 | 항목 수 | 청크 수 | 서로 다른 경로 수 | 청크 평균 줄 수 |" in out
    assert "| fo | 가상몰_기능정의서_v1.2.xlsx | 회원 | 5 | 5 | 5 |" in out
    assert "추정 경로라 연결에서 빠진 항목" in out and "본문이 빈 항목: 0" in out
    bad = tmp_path / "bad.yaml"
    bad.write_text("project: x\n", encoding="utf-8")
    assert run.main(["--project", str(bad), "--out", str(tmp_path / "p")]) == 1
    assert run.main(["--project"]) == 2


def test_python_dash_m_entry(tmp_path):
    import os
    import subprocess
    import sys
    done = subprocess.run([sys.executable, "-m", "si_prep", "--project", str(SHOP), "--out", str(tmp_path / "o")],
                          capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == sorted(list(OUTPUTS) + ["report.md", "report_목록.md"])


def test_summary_mentions_config_check_warnings(shop_result):
    # 18 검토 L2: 설정 검사 경고 수를 보이고 따로 확인하라고 안내(shop은 미구현 방식·연결 key 경고가 있음)
    text = run.summary(shop_result)
    assert f"설정 검사 경고 {shop_result.config_warnings}개" in text and shop_result.config_warnings > 0
    assert "python -m si_prep.config" in text


def test_replace_failure_reports_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    # 2026-10-10 작성자 결정(M1 B): 바꿔 넣는 중 실패하면 섞일 수 있으므로 오류로 알리고 다시 실행하게 한다
    out = tmp_path / "o"
    run.run(SHOP, out)
    real = run.os.replace
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 2:
            raise PermissionError(13, "다른 프로그램이 파일을 열고 있음")
        return real(src, dst)
    monkeypatch.setattr(run.os, "replace", flaky)
    assert run.main(["--project", str(SHOP), "--out", str(out)]) == 3
    text = capsys.readouterr().out
    assert "바뀐 파일: items.jsonl" in text
    assert "안 바뀐 파일: links.jsonl, warnings.jsonl, chunks.jsonl" in text and "다시 실행하세요" in text
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".o.tmp-")]       # 임시 폴더 안 남음


def test_summary_unmatched_counts_per_path_rule(shop_result):
    text = run.summary(shop_result)
    assert "규칙별 짝 없는 항목(경고 없음, 추정 경로 제외):" in text
    assert "fo_test fo " in text and " · test " in text



def test_summary_glossary_line_effects(shop_result):
    # shop glossary.yaml: 1줄 approved, 2줄 groups:, 3줄 - [회원, 고객] → 줄 번호와 숫자만(단어 없음)
    text = run.summary(shop_result)
    assert "용어집 줄별 효과" in text
    assert "3줄(groups[0]): 연결 1 · 풀린 짝 없음 0 · 새 내용 차이 0" in text
    line = next(l for l in text.splitlines() if "용어집 줄별 효과" in l or "3줄(groups[0])" in l)
    assert "회원" not in line and "고객" not in line


def test_duplicate_id_warning_includes_id_ref_partner():
    # duplicate_id 경고의 item_ids에 그 중복 ID로 연결된 상대(찾는 쪽) 항목도 넣는다
    from si_prep import extract, link
    from si_prep.config import load_project, load_profile
    from si_prep.issues import Issues
    from si_prep.schema import DocVersion

    def draft(doc_type, row, sid=None, refs=()):
        return extract.ItemDraft(doc_type=doc_type, doc_file=f"{doc_type}.xlsx", sheet="S", rows=(row, row), category_path=[],
                                 category_path_text="", raw_fields={}, merged_fields={}, doc_version=DocVersion(),
                                 status="ok", profile_source="approved", source_id=sid, ref_ids=list(refs),
                                 id_col="A" if sid else None, ref_col="B" if refs else None, ref_row=row if refs else None)
    config = load_project(SHOP)
    prof = {d.doc_type: load_profile(config.profile_path(d)) for d in config.documents}
    seeker, r1, r2 = draft("test", 2, "T-1", ["R-1"]), draft("req", 2, "R-1"), draft("req", 3, "R-1")
    index = link.ItemIndex()
    index.add(seeker, prof["test"])
    for d in (r1, r2):
        index.add(d, prof["req"])
    issues = Issues()
    extract.check_duplicate_ids([seeker, r1, r2], issues)
    rule = next(r for r in config.link_rules if r.key == "id_ref")
    made = link.REGISTRY.get("id_ref")(rule, index, config, issues)
    ids = {id(seeker): "IT-000001", id(r1): "IT-000002", id(r2): "IT-000003"}
    run.attach_duplicate_partners(issues, made, ids)
    out = run._number_warnings(issues, [(d, None) for d in (seeker, r1, r2)], ids,
                               {"test.xlsx": (0, 0), "req.xlsx": (1, 0)}, {("test.xlsx", "S"): 0, ("req.xlsx", "S"): 0})
    [w] = [w for w in out if w.kind == "duplicate_id"]
    assert w.item_ids == ["IT-000001", "IT-000002", "IT-000003"]
