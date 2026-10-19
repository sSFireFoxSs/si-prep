"""처리 보고서(report.md) — --out 폴더에 4개 결과 파일과 함께, 화면에는 숫자만.
절마다 고정 문구 「고칠 곳:」, 4절은 용어집까지 적용한 최종 짝 없음 + 규칙별 용어집 초안 후보 수.
"""

import copy
import re
import shutil
from typing import get_args

import yaml

from si_prep import glossary_candidates as gc
from si_prep import report, run
from si_prep.schema import PathPart, Warning_
from conftest import SHOP



def _section(text, n):
    """「## n.」 절 본문(다음 절 앞까지)"""
    start = text.index(f"## {n}. ")
    end = text.find("\n## ", start + 1)
    return text[start:end if end != -1 else len(text)]


def _replace_path(result, sheet, row, steps, title=None):
    """index 안 항목 하나를 경로만 바꾼 복사본으로 바꾼다(링크는 그대로라 짝 없는 항목이 됨). 바꾼 항목의 ID"""
    for doc_type, entries in result.index._by_type.items():
        for n, (d, p) in enumerate(entries):
            if d.sheet == sheet and d.rows[0] == row:
                fake = copy.copy(d)
                fake.category_path = [PathPart(level=i, value=v, basis="cell") for i, v in enumerate(steps, start=1)]
                fake.category_path_text = " › ".join(steps)
                if title is not None:
                    fake.title = title
                entries[n] = (fake, p)
                result.ids[id(fake)] = result.ids[id(d)]
                return result.ids[id(d)]
    raise AssertionError("행 없음")


def _add_copy(result, sheet, row, new_row, title=None):
    """같은 시트에 같은 경로 항목을 하나 더 넣는다(행 번호만 다름)"""
    for doc_type, entries in result.index._by_type.items():
        for d, p in entries:
            if d.sheet == sheet and d.rows[0] == row:
                twin = copy.copy(d)
                twin.rows = (new_row, new_row)
                if title is not None:
                    twin.title = title
                entries.append((twin, p))
                result.ids[id(twin)] = "IT-999999"
                return d
    raise AssertionError("행 없음")


# ---------- 절·고정 문구 ----------

def test_every_section_has_fixed_fix_line():
    text = report.render(run.build(SHOP))
    assert len(report.SECTIONS) == 12   # 2026-10-13 12절 구조 진단(승인)
    for n, (title, fix) in enumerate(report.SECTIONS, start=1):
        lines = _section(text, n).splitlines()
        assert lines[0] == f"## {n}. {title}"
        assert lines[2] == report.EASY[n]                                       # C8: 제목 아래 쉬운 말 한 줄
        assert next(l for l in lines[3:] if l.strip()) == f"고칠 곳: {fix}"


def test_every_warning_kind_has_category():
    kinds = get_args(Warning_.model_fields["kind"].annotation)
    assert set(kinds) <= set(report.CATEGORY)


def test_warning_counts_by_kind():
    result = run.build(SHOP)
    sec = _section(report.render(result), 2)
    counts = {}
    for w in result.warnings:
        counts[w.kind] = counts.get(w.kind, 0) + 1
    for kind, n in counts.items():
        assert f"({kind}) | {report.CATEGORY[kind]} | {n} |" in sec           # C8: 경고 이름은 괄호 안


def test_header_has_priority_and_counts():
    result = run.build(SHOP)
    sec = _section(report.render(result), 1)
    assert "req > fo > policy" in sec
    assert f"항목 {len(result.items)} · 연결 {len(result.links)} · 경고 {len(result.warnings)} · 청크 {len(result.chunks)}" in sec


# ---------- 3절 시트별 표 ----------

def test_sheet_table_has_read_skip_reason_overview_and_counts():
    sec = _section(report.render(run.build(SHOP)), 3)
    assert "| fo | 가상몰_기능정의서_v1.2.xlsx | 표지 | 뺌 | 메타 시트(표지) |" in sec
    assert "| fo | 가상몰_기능정의서_v1.2.xlsx | 요약 | 읽음 |  | 예 | 2 |" in sec      # C8: 열 「요약 시트(overview)」


# ---------- 4절 규칙별 짝 없는 항목 ----------

def test_unmatched_item_listed_with_candidate_count_and_fix():
    result = run.build(SHOP)
    item_id = _replace_path(result, "요약", 6, ("회원", "로그인하기", "일반 로그인", "아이디 입력"))
    files = report.render_all(result)
    sec = _section(files[report.REPORT_FILE], 4)
    block = sec[sec.index("### fo_overview_detail"):]
    block = block[:block.find("\n### ", 1) if "\n### " in block[1:] else len(block)]
    # C8: 짝 없는 항목 목록은 report_목록.md 4절에 전부, report.md에는 개수 + 앞 10개 + 안내
    full = _section(files[report.LIST_FILE], 4)
    full = full[full.index("### fo_overview_detail"):].split("\n### ")[0]
    assert item_id in full and "| 요약 | 6행 |" in full and "회원 › 로그인하기 › 일반 로그인 › 아이디 입력" in full
    n_rows = full.count("| fo 쪽")
    assert n_rows > report.SHOWN and block.count("| fo 쪽") == report.SHOWN
    assert sum(int(l.split("못 찾은 ")[1].split()[0]) for l in block.splitlines() if "못 찾은 " in l) == n_rows   # 개수(쪽별 합)
    assert f"전체 {n_rows}개는 {report.LIST_FILE} 4절 「fo_overview_detail」에 있습니다" in block
    n = sum(c.rule_id == "fo_overview_detail" for c in gc.candidates(result.config, result.index, result.made_by_rule))
    assert n >= 1 and f"용어집 초안 후보 {n}개" in block and "고칠 곳: glossary.yaml" in block


def test_rule_fix_line_follows_candidates():
    result = run.build(SHOP)
    text = report.render(result)
    sec = _section(text, 4)
    cands = gc.candidates(result.config, result.index, result.made_by_rule)
    for rule_id in ("fo_test", "bo_test"):
        block = sec[sec.index(f"### {rule_id}"):]
        block = block[:block.find("\n### ", 1) if "\n### " in block[1:] else len(block)]
        n = sum(c.rule_id == rule_id for c in cands)
        assert f"용어집 초안 후보 {n}개" in block
        assert ("고칠 곳: glossary.yaml" if n else "고칠 곳: project.yaml의 규칙 시트·문서(sheets·docs)") in block


def test_rule_sheets_scope_excludes_other_sheets():
    result = run.build(SHOP)
    sec = _section(report.render(result), 4)
    block = sec[sec.index("### bo_test"):]
    in_bo_sheet = sum(1 for i in result.items if i.doc_type == "test" and i.locations[0].sheet == "BO테스트케이스")
    assert f"test 쪽: 항목 {in_bo_sheet} ·" in block


def test_unsupported_rule_marked(tmp_path):
    # 2026-10-13: id_ref 구현으로 shop에 미구현 key 규칙이 없어 name_similarity 규칙을 더해 확인
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    data["link_rules"].append({"id": "req_fo_similar", "docs": ["req", "fo"], "key": "name_similarity"})
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sec = _section(report.render(run.build(project)), 4)
    block = sec[sec.index("### req_fo_similar"):]
    assert "지원하지 않아 건너뜀" in block.split("\n### ")[0]


def test_id_ref_rule_counts_and_unlinked_targets():
    result = run.build(SHOP)
    sec = _section(report.render(result), 4)
    block = sec[sec.index("### test_req"):]
    block = block.split("\n### ")[0]
    tests = [i for i in result.items if i.doc_type == "test"]
    reqs = [i for i in result.items if i.doc_type == "req"]
    linked = {x for l in result.links if l.rule_id == "test_req" for x in (l.item_a, l.item_b)}
    no_ref = sum(1 for i in tests if not i.ref_ids)
    unresolved = sum(1 for i in tests if i.ref_ids and i.item_id not in linked)
    assert (f"- test 쪽: 항목 {len(tests)} · 연결된 {sum(i.item_id in linked for i in tests)}"
            f" · 참조 ID 없는 항목 {no_ref} · 참조 ID를 못 찾은 항목 {unresolved}") in block
    assert (len(tests), no_ref, unresolved) == (8, 5, 1)
    missing = [i.item_id for i in reqs if i.item_id not in linked]
    assert f"- req 쪽: 항목 {len(reqs)} · 연결된 {len(reqs) - len(missing)} · 못 찾은 {len(missing)}" in block
    assert all(m in block for m in missing) and "고칠 곳:" in block


# ---------- 5절 어느 연결에도 없는 항목 ----------

def test_doc_types_without_rules_one_line_only():
    result = run.build(SHOP)
    sec = _section(report.render(result), 5)
    n = sum(1 for i in result.items if i.doc_type == "variation")
    assert f"연결 규칙 없는 문서 종류: variation (항목 {n}개)" in sec
    variation_ids = [i.item_id for i in result.items if i.doc_type == "variation"]
    assert not any(v in sec for v in variation_ids)


def test_unlinked_items_listed():
    result = run.build(SHOP)
    files = report.render_all(result)
    sec = _section(files[report.LIST_FILE], 5)                               # C8: 전체는 report_목록.md 5절
    linked = {x for l in result.links for x in (l.item_a, l.item_b, l.item) if x}
    ruled = {t for r in result.config.link_rules for t in r.docs}
    unlinked = [i.item_id for i in result.items if i.doc_type in ruled and i.item_id not in linked]
    for item_id in unlinked:
        assert item_id in sec
    short = _section(files[report.REPORT_FILE], 5)                           # report.md: 개수 + 앞 10개 + 안내
    assert f"어느 연결에도 없는 항목: {len(unlinked)}" in short and short.count("| IT-") == report.SHOWN
    assert f"전체 {len(unlinked)}개는 {report.LIST_FILE} 5절에 있습니다" in short


# ---------- 6~10절 ----------

def test_inferred_items_listed():
    result = run.build(SHOP)
    files = report.render_all(result)
    n = sum(result.inferred_by_doc.values())
    assert _section(files[report.LIST_FILE], 6).count("| IT-") == n           # C8: 전체는 report_목록.md 6절
    short = _section(files[report.REPORT_FILE], 6)                           # report.md: 개수 + 앞 10개 + 안내
    assert n > report.SHOWN and f"추정 경로 항목: {n}" in short and short.count("| IT-") == report.SHOWN
    assert f"전체 {n}개는 {report.LIST_FILE} 6절에 있습니다" in short


def test_same_path_same_title_listed_others_counted():
    plain = _section(report.render(run.build(SHOP)), 8)
    before = int(plain.split("경로만 같고 제목(title)이 다른 묶음: ")[1].split()[0])
    result = run.build(SHOP)
    base = _add_copy(result, "회원", 6, 99)                      # 경로·title 같음 → 목록
    _add_copy(result, "주문", 6, 98, title="다른 제목")          # 경로만 같음 → 수만
    sec = _section(report.render(result), 8)
    assert f"| {base.doc_type} | {base.doc_file} | {base.sheet} | 6, 99 |" in sec
    assert f"경로만 같고 제목(title)이 다른 묶음: {before + 1}" in sec
    assert "98" not in sec


def test_version_and_roles_sections_from_result():
    result = run.build(SHOP)
    result.version_missing = [("가.xlsx", ["표지"])]
    result.roles_missing = [("fo", "가.xlsx", "시트1", "description")]
    text = report.render(result)
    assert "| 가.xlsx | 표지 |" in _section(text, 9)
    assert "| fo | 가.xlsx | 시트1 | description |" in _section(text, 10)


def test_glossary_section_has_words_in_file():
    result = run.build(SHOP)
    sec = _section(report.render(result), 11)
    line, g, n, r, m = result.glossary_effects[0]
    assert f"| {line} | groups[{g}] | 회원, 고객 | {n} |" in sec
    assert "용어집으로 해결된 항목" in sec


# ---------- 쓰기·화면 ----------

def test_report_written_with_outputs_and_screen_has_only_numbers(tmp_path, capsys):
    out = tmp_path / "o"
    assert run.main(["--project", str(SHOP), "--out", str(out)]) == 0
    screen = capsys.readouterr().out
    assert (out / report.REPORT_FILE).exists()
    assert f"처리 보고서: {out / report.REPORT_FILE}" in screen
    result = run.build(SHOP)
    for i in result.items:
        if " › " in (i.category_path_text or ""):
            assert i.category_path_text not in screen          # 경로(셀 내용)는 화면에 안 나옴


def test_report_deterministic(tmp_path):
    run.run(SHOP, tmp_path / "a")
    run.run(SHOP, tmp_path / "b")
    assert (tmp_path / "a" / report.REPORT_FILE).read_bytes() == (tmp_path / "b" / report.REPORT_FILE).read_bytes()
    assert b"\r\n" not in (tmp_path / "a" / report.REPORT_FILE).read_bytes()


def test_trial_run_still_writes_report(tmp_path):
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["approved"] = False
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    run.run(project, tmp_path / "o")
    text = (tmp_path / "o" / report.REPORT_FILE).read_text(encoding="utf-8")
    assert "**시험 실행**" in _section(text, 1)


def test_config_error_writes_no_report(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("project: x\n", encoding="utf-8")
    assert run.main(["--project", str(bad), "--out", str(tmp_path / "o")]) == 1
    assert not (tmp_path / "o" / report.REPORT_FILE).exists()


# ---------- 2026-10-12: 시험 실행은 연결의 profile_source도 본다(용어집만 미승인) ----------

def _shop_with_glossary_approved(tmp_path, approved):
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    g = tmp_path / "shop" / "glossary.yaml"
    gd = yaml.safe_load(g.read_text(encoding="utf-8"))
    gd["approved"] = approved
    g.write_text(yaml.safe_dump(gd, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return project


def test_trial_when_only_glossary_unapproved(tmp_path):
    result = run.build(_shop_with_glossary_approved(tmp_path, False))
    assert all(i.profile_source != "auto" for i in result.items)        # 프로필·프로젝트는 승인
    assert any(l.profile_source == "auto" for l in result.links)
    assert result.trial
    assert "시험 실행" in run.summary(result)
    assert "**시험 실행**" in _section(report.render(result), 1)


def test_no_trial_when_glossary_approved_too(tmp_path):
    result = run.build(_shop_with_glossary_approved(tmp_path, True))
    assert not result.trial
    assert "시험 실행" not in run.summary(result)
    assert "**시험 실행**" not in _section(report.render(result), 1)


# ---------- 2026-10-12: 11절 숫자 뜻 ----------

def test_glossary_section_explains_both_numbers_and_breaks_down_total():
    result = run.build(SHOP)
    sec = _section(report.render(result), 11)
    assert report.GLOSSARY_LINE_NOTE in sec and report.GLOSSARY_TOTAL_NOTE in sec
    total = int(sec.split("용어집으로 해결된 항목")[1].split(": ")[1].split()[0])
    table = sec[sec.index("| 규칙 | 문서 | 해결된 항목 |"):].split("\n\n")[0].splitlines()[2:]
    rows = [l for l in table if l.startswith("| ")]
    path_sides = [(r.id, k) for r in result.config.link_rules if r.key == "path" for k in range(2)]
    assert len(rows) == len(path_sides)
    assert sum(int(r.split("|")[3]) for r in rows) == total


# ---------- 2026-10-12 리뷰 R4: 화면과 보고서 4절이 같은 짝 없음 기준(link.unmatched) ----------

def test_report_unmatched_counts_equal_screen_counts():
    result = run.build(SHOP)
    sec = _section(report.render(result), 4)
    for rule_id, a, na, b, nb in result.unmatched:
        block = sec[sec.index(f"### {rule_id}\n"):].split("\n### ")[0]
        found = [int(l.split("못 찾은 ")[1].split()[0]) for l in block.splitlines() if "못 찾은 " in l]
        assert found == [na, nb], (rule_id, found, na, nb)


def test_whitespace_only_step_not_counted_as_unmatched():
    # 공백만 있는 단계는 경로 열쇠가 없어 연결에 쓰지 않는다 → 화면처럼 보고서도 짝 없음에 넣지 않는다
    from si_prep import link
    result = run.build(SHOP)
    item_id = _replace_path(result, "요약", 6, ("회원", " ", "일반 로그인", "아이디 입력"))
    sec = _section(report.render(result), 4)
    block = sec[sec.index("### fo_overview_detail\n"):].split("\n### ")[0]
    assert item_id not in block
    rule = next(r for r in result.config.link_rules if r.id == "fo_overview_detail")
    left, _ = link.unmatched(rule, result.index, result.made_by_rule[rule.id])
    assert f"못 찾은 {len(left)} ·" in block.splitlines()[3]


# ---------- R7: path 규칙과 같은 두 쪽인 glossary 규칙은 4절에서 path 규칙에 합쳐 센다 ----------

def _shop_with_folded_glossary_rule(tmp_path):
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    data["link_rules"].insert(1, {"id": "fo_overview_detail_glossary", "docs": ["fo", "fo"], "key": "glossary",
                                  "sheets": ["overview", "detail"], "options": {"match": "exact"}})
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return project


def test_folded_glossary_rule_counted_under_path_rule(tmp_path):
    result = run.build(_shop_with_folded_glossary_rule(tmp_path))
    text = report.render(result)
    sec = _section(text, 4)
    block = sec[sec.index("### fo_overview_detail_glossary\n"):].split("\n### ")[0]
    assert "경로 규칙 fo_overview_detail에 합쳐 셈" in block and "못 찾은" not in block
    rows = [l for l in _section(text, 11).splitlines() if l.startswith("| fo_overview_detail |")]
    assert len(rows) == 2


# ---------- R10: 보고서·초안 후보는 실행 결과(made_by_rule)를 쓰고 규칙을 다시 돌리지 않는다 ----------

def test_report_does_not_rerun_link_rules(monkeypatch):
    from si_prep import link
    result = run.build(SHOP)

    def boom(*a, **k):
        raise AssertionError("규칙을 다시 실행함")
    monkeypatch.setattr(link.REGISTRY, "get", boom)
    report.render(result)
    gc.candidates(result.config, result.index, result.made_by_rule)


# ---------- R18: 실행으로 생기는 「버전 못 찾음」·「본문이 빈 항목」 ----------

def _shop_copy_edit(tmp_path, profile, change):
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    p = tmp_path / "shop" / "profiles" / f"{profile}.yaml"
    pd = yaml.safe_load(p.read_text(encoding="utf-8"))
    change(pd)
    p.write_text(yaml.safe_dump(pd, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return project


def test_version_missing_from_run_reaches_screen_and_report(tmp_path):
    project = _shop_copy_edit(tmp_path, "fo", lambda d: d["version"].update(filename_pattern=r"_ver(\d+)"))
    result = run.build(project)
    assert result.version_missing == [("가상몰_기능정의서_v1.2.xlsx", ["파일 이름"])]
    assert "버전을 못 찾은 파일: 가상몰_기능정의서_v1.2.xlsx(파일 이름)" in run.summary(result)
    assert "| 가상몰_기능정의서_v1.2.xlsx | 파일 이름 |" in _section(report.render(result), 9)


def test_empty_body_from_run_reaches_screen_and_report(tmp_path):
    def change(d):
        d["hierarchy"] = {"method": "none"}
        d["columns"].pop("hierarchy")
        d["columns"]["exclude_from_text"] = [{"header_contains": h} for h in ("요구사항 ID", "대분류", "중분류", "요구사항명", "설명")]
    result = run.build(_shop_copy_edit(tmp_path, "req", change))
    reqs = [i for i in result.items if i.doc_type == "req"]
    assert reqs and len(result.empty_body) == len(reqs)
    assert not any(c.source.sheet == "요구사항" for c in result.chunks)
    assert f"본문이 빈 항목: {len(reqs)}" in run.summary(result)
    sec = _section(report.render(result), 7)
    assert sec.count("| req | 가상몰_요구사항정의서.xlsx | 요구사항 |") == len(reqs)


# ---------- 2026-10-13: 12절 구조 진단 (분류 칸 병합·빈칸 숫자, blank_means_above 검토) ----------

VAR = "가상몰_변형.xlsx"
FO = "가상몰_기능정의서_v1.2.xlsx"


def test_structure_counts_per_sheet():
    # 열: 문서 | 파일 | 시트 | 머리글 줄 | 항목 | 분류 열 | 병합 칸 | 병합 없는 빈칸 | 앞쪽 빈칸 | 앞쪽 빈칸 행 | 테두리 묶음 안 빈칸 | 전부 빈 행 | 비율 | fill_down | 확인
    sec = _section(report.render(run.build(SHOP)), 12)
    assert f"| variation | {VAR} | 빈칸채움 | 1 | 5 | 3 | 0 | 10 | 4 | 3 | 0 | 1 | 0.60 | 켬 | 검토 |" in sec
    assert f"| variation | {VAR} | 빈칸채움_끔 | 1 | 5 | 3 | 0 | 10 | 4 | 3 | 0 | 1 | 0.60 | 끔 | 검토 |" in sec
    assert f"| variation | {VAR} | 분류패턴_2단 | 1 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0.00 | 끔 |  |" in sec
    assert f"| fo | {FO} | 회원 | 2 | 5 | 3 | 3 | 2 | 0 | 0 | 0 | 0 | 0.00 | 끔 |  |" in sec   # 병합 시작 칸은 세지 않음
    assert report.BLANK_ROW_REVIEW_RATIO == 0.5


def test_structure_declared_sheet_marked(tmp_path):
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    prof = tmp_path / "shop" / "profiles" / "variation.yaml"
    p = yaml.safe_load(prof.read_text(encoding="utf-8"))
    for o in p["sheet_overrides"]:
        if o["sheets"] == ["빈칸채움"]:
            o["hierarchy"]["blank_means_above"] = True
            break
    else:
        raise AssertionError("빈칸채움 덮어쓰기 없음")
    prof.write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sec = _section(report.render(run.build(project)), 12)
    assert f"| variation | {VAR} | 빈칸채움 | 1 | 5 | 3 | 0 | 10 | 4 | 3 | 0 | 1 | 0.60 | 켬 | 선언됨 |" in sec


def test_plain_blank_rule_shared_with_hierarchy():
    from si_prep import hierarchy
    assert callable(hierarchy.plain_blank) and callable(hierarchy.fill_limit)


def test_structure_rows_equal_filled_items():
    # 선언 없는 fill_down 시트에서 앞쪽 빈칸 행 + 분류 칸 전부 빈 행 = filled_down 단계가 있는 항목 수
    # 한 시트 여러 표는 표마다 12절 줄(「시트 [표 제목 n행]」)이라 시트별로 합쳐 비교한다
    result = run.build(SHOP)
    rows = {}
    for doc_type, file, label, _, items, _, b, fill, declared in result.structure:
        if not fill or declared:
            continue
        key = (file, label.split(" [표 제목 ")[0])
        rows[key] = rows.get(key, 0) + b.front_rows + b.all_blank_rows
    for (file, sheet), counted in rows.items():
        mine = [i for i in result.items if i.doc_file == file and i.locations[0].sheet == sheet]
        filled = sum(any(p.basis == "filled_down" for p in i.category_path) for i in mine)
        assert counted == filled, sheet
    assert len(rows) >= 2


def test_id_ref_section_shows_leftover_short_fragments():
    # B2: 4절 id_ref 규칙에 「숫자 조각 남은 참조 칸」 줄(펼치기 끔이어도 보임 — 켤지 판단 근거)
    sec = _section(report.render(run.build(SHOP)), 4)
    assert "숫자 조각 남은 참조 칸 0" in sec


def test_id_ref_section_counts_expanded_ids():
    # 펼친 ID가 있으면 같은 줄에 「펼친 ID n(못 찾음 m)」 — 대상 쪽 자기 ID와 비교
    result = run.build(SHOP)
    rule = next(r for r in result.config.link_rules if r.key == "id_ref")
    seeker = next(d for d in result.index.side(rule.docs[0], (rule.sheets or [None, None])[0]) if d.ref_ids)
    target = next(t for t in result.index.side(rule.docs[1], (rule.sheets or [None, None])[1]) if t.source_id)
    seeker.expanded_refs = [(target.source_id, "1", "x"), ("없는-ID", "2", "x")]
    seeker.short_left = 1
    sec = _section(report.render(result), 4)
    assert "숫자 조각 남은 참조 칸 1 · 펼친 ID 2(못 찾음 1)" in sec


# ---------- 9b: 한 시트 여러 표 — tables 설정 시트만 3절에 표 수 ----------

def test_sheet_section_shows_table_counts_only_for_tables_sheets():
    sec = _section(report.render(run.build(SHOP)), 3)
    lines = [l for l in sec.splitlines() if "건너뛴 표" in l]
    assert lines == [f"- variation {VAR} 「표여러개」: 표 5개, 건너뛴 표 1개(tables 설정 — 건너뛴 표는 2절 header_not_found)"]


def test_structure_rows_per_table():
    sec = _section(report.render(run.build(SHOP)), 12)
    assert sum(f"| variation | {VAR} | 표여러개 [표 제목 " in l for l in sec.splitlines()) == 4


def test_rule_links_per_item_line():
    # 4절 규칙마다 「항목당 연결 수 최대·평균」(연결된 항목 기준)
    result = run.build(SHOP)
    sec = _section(report.render(result), 4)
    block = sec[sec.index("### test_req"):]
    block = block[:block.find("\n### ", 1)]
    # test_req: IT-1↔43, IT-1↔44, IT-2↔44 → 연결된 항목 4개(1, 2, 43, 44), 연결 수 2·1·1·2
    assert "- 항목당 연결 수: 최대 2 · 평균 1.50 (연결 3개, 연결된 항목 4개)" in block
    assert sec.count("- 항목당 연결 수:") == sum(1 for r in result.config.link_rules
                                                  if r.id in result.made_by_rule and r.id not in report._folded_glossary(result.config))


# ---------- 3절 표 수에 「제목 없는 표 n」(first_without_title을 켠 시트만) ----------

def test_sheet_section_counts_untitled_tables_when_option_on(tmp_path):
    def on(d):
        o = next(o for o in d["sheet_overrides"] if o["sheets"] == ["표여러개"])
        o["tables"]["first_without_title"] = True
    sec = _section(report.render(run.build(_shop_copy_edit(tmp_path, "variation", on))), 3)
    lines = [l for l in sec.splitlines() if "건너뛴 표" in l]
    assert lines == [f"- variation {VAR} 「표여러개」: 표 5개(제목 없는 표 0개), 건너뛴 표 1개"
                     "(tables 설정 — 건너뛴 표는 2절 header_not_found)"]


# ---------- path_prefix(묶음) 규칙도 「용어집으로 풀림」을 센다(4절·11절) ----------

def _shop_with_prefix_rule(tmp_path):
    # req_fo_glossary(glossary prefix, group fo)와 같은 두 쪽인 path_prefix 규칙을 더한다
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    data["link_rules"].append({"id": "req_fo_prefix", "docs": ["req", "fo"], "key": "path_prefix", "group": "fo"})
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return project


def test_path_prefix_rule_counts_glossary_resolved(tmp_path):
    from si_prep import link
    result = run.build(_shop_with_prefix_rule(tmp_path))
    rule = next(r for r in result.config.link_rules if r.id == "req_fo_prefix")
    left, _ = link.unmatched(rule, result.index, result.made_by_rule[rule.id])
    by_glossary = link.glossary_linked_for(rule, result.glossary_made)
    n = sum(id(d) in by_glossary for d in left)
    assert n >= 1                                                   # 합성 데이터에 용어집으로만 이어지는 요구사항이 있음
    text = report.render(result)
    block = _section(text, 4)
    block = block[block.index("### req_fo_prefix\n"):].split("\n### ")[0]
    assert f"못 찾은 {len(left) - n} · 용어집으로 풀림 {n} ·" in block
    rows = [l for l in _section(text, 11).splitlines() if l.startswith("| req_fo_prefix |")]
    assert rows == [f"| req_fo_prefix | req 쪽 | {n} | 아니오 |"]   # 묶음(fo) 쪽은 해당 없음이라 줄 없음
    # 같은 두 쪽 glossary 규칙은 path처럼 path_prefix 규칙에 합쳐 센다(따로 「못 찾은」을 세지 않음, 0절 할 일에도 없음)
    g = _section(text, 4)
    g = g[g.index("### req_fo_glossary\n"):].split("\n### ")[0]
    assert "경로 규칙 req_fo_prefix에 합쳐 셈" in g and "못 찾은" not in g
    assert "규칙 req_fo_glossary의" not in _section(text, 0)


# ---------- report 읽기 쉽게 — 0절 먼저 볼 것, 긴 목록은 report_목록.md, 절마다 쉬운 말, 용어 설명 ----------

def _all(result):
    return report.render_all(result)


def test_first_section_status_numbers_and_todos():
    result = run.build(SHOP)
    text = report.render(result)
    assert text.index("## 0. 먼저 볼 것") < text.index("## 1. ")
    sec = _section(text, 0)
    assert "- 상태: 공식 실행" in sec
    assert f"- 핵심 숫자: 항목 {len(result.items)} · 연결 {len(result.links)} · 경고 {len(result.warnings)}" in sec
    todos = [l for l in sec.splitlines() if l.startswith("- [ ] ")]
    assert todos and all(" — 근거: " in l and " — 볼 곳: " in l and "절" in l.split(" — 볼 곳: ")[1] for l in todos)
    n = sum(w.kind == "header_not_found" for w in result.warnings)
    assert any("처리 실패" in l and f"header_not_found {n}" in l and "2절" in l for l in todos)
    assert any("12절" in l and "검토 시트 2개" in l for l in todos)      # 빈칸채움·빈칸채움_끔


def test_todo_lines_empty_says_none():
    assert report._todo_lines([]) == ["- 할 일 없음"]


def test_trial_status_in_first_section(tmp_path):
    result = run.build(_shop_with_glossary_approved(tmp_path, False))
    sec = _section(report.render(result), 0)
    assert "- 상태: 시험 실행" in sec
    assert any(l.startswith("- [ ] ") and "approved" in l for l in sec.splitlines())


def test_every_section_has_easy_line_under_title():
    text = report.render(run.build(SHOP))
    for n in range(0, len(report.SECTIONS) + 1):
        lines = _section(text, n).splitlines()
        assert lines[1] == "" and lines[2] == report.EASY[n] and lines[2]
    assert text.rstrip().split("\n## ")[-1].startswith("용어 설명")


def test_long_item_lists_move_to_list_file(tmp_path):
    result = run.build(SHOP)
    files = _all(result)
    assert set(files) == {report.REPORT_FILE, report.LIST_FILE}
    sec5, full5 = _section(files[report.REPORT_FILE], 5), _section(files[report.LIST_FILE], 5)
    linked = {x for l in result.links for x in (l.item_a, l.item_b, l.item) if x}
    ruled = {t for r in result.config.link_rules for t in r.docs}
    unlinked = [i.item_id for i in result.items if i.doc_type in ruled and i.item_id not in linked]
    assert len(unlinked) > report.SHOWN
    assert sec5.count("| IT-") == report.SHOWN
    assert f"전체 {len(unlinked)}개는 {report.LIST_FILE} 5절에 있습니다" in sec5
    assert all(i in full5 for i in unlinked) and full5.count("| IT-") == len(unlinked)


def test_list_file_written_and_deterministic(tmp_path):
    run.run(SHOP, tmp_path / "a")
    run.run(SHOP, tmp_path / "b")
    a, b = (tmp_path / "a" / report.LIST_FILE).read_bytes(), (tmp_path / "b" / report.LIST_FILE).read_bytes()
    assert a == b and b"\r\n" not in a and a.startswith("# 처리 보고서 목록".encode("utf-8"))


def test_glossary_of_terms_table_one_term_per_line():
    text = report.render(run.build(SHOP))
    terms = text[text.index("## 용어 설명"):]
    rows = [l for l in terms.splitlines() if l.startswith("| ") and not l.startswith("| ---")][1:]
    names = [r.split(" | ")[0][2:] for r in rows]
    assert len(names) == len(set(names))
    for t in ("approved", "fill_down", "blank_means_above", "border_groups", "path", "path_prefix", "id_ref", "glossary"):
        assert t in names


def test_warning_kinds_have_meaning():
    kinds = get_args(Warning_.model_fields["kind"].annotation)
    assert set(kinds) <= set(report.WARNING_MEANING)


def test_structure_section_order_summary_todo_table_columns():
    # C4: ① 요약 한 줄(문서별) ② 할 일 ③ 표 ④ 열 설명. 설정 이름은 ④ 괄호 안에만
    result = run.build(SHOP)
    sec = _section(report.render(result), 12)
    lines = sec.splitlines()
    summary = next(i for i, l in enumerate(lines) if l.startswith("- 요약: "))
    todo = next(i for i, l in enumerate(lines) if l.startswith("- 할 일"))
    table = next(i for i, l in enumerate(lines) if l.startswith("| 문서 | 파일 | 시트 |"))
    cols = next(i for i, l in enumerate(lines) if l.startswith("| 열 | 뜻 |"))
    assert summary < todo < table < cols
    review = sum(1 for r in result.structure if r[0] == "variation" and not r[8] and r[4] and r[6].front_rows / r[4] >= 0.5)
    blank = sum(r[6].blank_all for r in result.structure if r[0] == "variation")
    assert f"variation 검토 {review} · 선언됨 0 · 병합 없는 빈칸 {blank}" in lines[summary]
    assert lines[todo] == ("- 할 일: 맨 오른쪽이 '검토'인 시트만 엑셀에서 빈칸을 눌러 보고, 위와 같은 뜻이면 "
                           f"'위와 같음'이라고 알려 주기(검토 시트 {review}개)")
    before = "\n".join(lines[:cols])
    for name in ("blank_means_above", "border_groups", "fill_down", "sheet_overrides"):
        assert name not in before
        assert all(name not in re.sub(r"\([^()]*\)", "", l) for l in lines[cols:])     # 괄호 밖에는 없음
    col_rows = [l for l in lines[cols + 2:] if l.startswith("| ")]
    assert [r.split(" | ")[0][2:] for r in col_rows] == [h.strip() for h in lines[table].strip("|").split("|")]
