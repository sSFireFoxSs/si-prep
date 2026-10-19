"""용어 사전 초안 — 짝 없는 항목에서만, 코드 규칙으로(LLM 없음). 초안 파일은 --out(저장소 밖)에만,
화면에는 규칙별 후보 개수만.
"""

import copy
from pathlib import Path

import yaml

from si_prep import glossary_candidates as gc
from si_prep import run
from si_prep.config import Glossary
from si_prep.schema import PathPart
from conftest import SHOP



def _result_with_overview_row(steps):
    """요약 6행 경로를 바꿔 짝 없는 항목을 만든다(합성 데이터는 그대로)"""
    result = run.build(SHOP)
    entries = result.index._by_type["fo"]
    for n, (d, p) in enumerate(entries):
        if d.sheet == "요약" and d.rows[0] == 6:
            fake = copy.copy(d)
            fake.category_path = [PathPart(level=i, value=v, basis="cell") for i, v in enumerate(steps, start=1)]
            fake.category_path_text = " › ".join(steps)
            entries[n] = (fake, p)
    return result


def test_one_step_difference_becomes_candidate():
    result = _result_with_overview_row(("회원", "로그인하기", "일반 로그인", "아이디 입력"))
    cands = gc.candidates(result.config, result.index, result.made_by_rule)
    c = next(c for c in cands if c.rule_id == "fo_overview_detail")
    # 대표어 = 대상(상세·메뉴) 쪽 이름이 앞
    assert (c.rep, c.other, c.count, c.example) == ("로그인", "로그인하기", 1, ("요약", 6))


def _result_with_policy_sheet(name):
    """정책 「주문 - 결제」 2행을 시트 이름 한 단계(name)로 바꾸고 policy_fo(sheet_to_path) 연결을 다시 만든 결과"""
    from si_prep import link
    from si_prep.issues import Issues
    result = run.build(SHOP)
    entries = result.index._by_type["policy"]
    for n, (d, p) in enumerate(entries):
        if d.sheet == "주문 - 결제" and d.rows[0] == 2:
            fake = copy.copy(d)
            fake.category_path = [PathPart(level=1, value=name, basis="sheet_name")]
            entries[n] = (fake, p)
    rule = next(r for r in result.config.link_rules if r.id == "policy_fo")
    result.made_by_rule["policy_fo"] = link.REGISTRY.get("sheet_to_path")(rule, result.index, result.config, Issues())
    return result


def test_sheet_to_path_one_step_candidate_when_loose_keys_equal():
    # 2026-10-14: sheet_to_path는 한 단계 비교라 마지막 단계 제외의 예외 —
    # 괄호 부분·구분 기호·공백을 뺀 열쇠가 같은 쌍만 후보(강한 후보)
    result = _result_with_policy_sheet("주문(Order)")
    cands = [c for c in gc.candidates(result.config, result.index, result.made_by_rule) if c.rule_id == "policy_fo"]
    assert [(c.rep, c.other, c.count) for c in cands] == [("주문", "주문(Order)", 1)]   # 회원·고객센터는 후보 아님
    assert cands[0].rep_sources and cands[0].other_sources == (("가상몰_정책정의서.xlsx", "주문 - 결제", 2),)


def test_sheet_to_path_one_step_other_names_not_candidate():
    result = _result_with_policy_sheet("배송 안내")
    assert not any(c.rule_id == "policy_fo" for c in gc.candidates(result.config, result.index, result.made_by_rule))


def test_two_steps_different_is_not_candidate():
    result = _result_with_overview_row(("회원", "로그인하기", "보통 로그인", "아이디 입력"))
    assert not any(c.rule_id == "fo_overview_detail" for c in gc.candidates(result.config, result.index, result.made_by_rule))


def test_pairs_already_in_glossary_skipped():
    # shop 사전에는 [회원, 고객]이 있으므로 req 「고객 › 로그인」 ↔ fo 「회원 › 로그인」은 후보가 아님
    result = run.build(SHOP)
    assert not any({c.rep, c.other} == {"회원", "고객"} for c in gc.candidates(result.config, result.index, result.made_by_rule))


def test_draft_yaml_shape():
    cands = [gc.Candidate("r1", "가", "나", 3, ("시트A", 7)), gc.Candidate("r1", "다", "라", 5, ("시트B", 2)),
             gc.Candidate("r2", "마", "바", 1, ("시트C", 9))]
    text = gc.draft_yaml(cands)
    assert text.startswith("#") and "두 이름이 같은 대상을 부르는 말일 때만 남긴다" in text and "아이디 찾기/비밀번호 찾기" in text
    data = yaml.safe_load(text)
    assert data["approved"] is False
    assert data["groups"] == [["다", "라"], ["가", "나"], ["마", "바"]]      # 규칙별, 횟수 많은 순
    Glossary.model_validate(data)                                            # 그대로 사전 모양
    line = next(l for l in text.splitlines() if '"다"' in l)
    assert "r1" in line and "5회" in line and "시트B 2행" in line


def test_cli_writes_only_to_out_and_prints_counts(tmp_path, capsys):
    assert gc.main(["--project", str(SHOP), "--out", str(tmp_path / "w")]) == 0
    printed = capsys.readouterr().out
    draft = tmp_path / "w" / gc.DRAFT_NAME
    assert draft.exists() and yaml.safe_load(draft.read_text(encoding="utf-8"))["approved"] is False
    assert "규칙별 후보 개수" in printed
    for c in gc.candidates(*(lambda r: (r.config, r.index, r.made_by_rule))(run.build(SHOP))):
        assert c.rep not in printed and c.other not in printed                # 단계 이름(셀 내용)은 화면에 안 나옴
    assert gc.main(["--project", str(SHOP)]) == 2


def test_draft_skips_reverse_pairs():
    text = gc.draft_yaml([gc.Candidate("r1", "가", "나", 3, ("A", 1)), gc.Candidate("r2", "나", "가", 2, ("B", 2))])
    assert yaml.safe_load(text)["groups"] == [["가", "나"]]


def test_cli_says_when_overwriting(tmp_path, capsys):
    gc.main(["--project", str(SHOP), "--out", str(tmp_path)])
    capsys.readouterr()
    gc.main(["--project", str(SHOP), "--out", str(tmp_path)])
    assert "덮어썼습니다" in capsys.readouterr().out


# ---------- 2026-10-10 결정: 마지막 단계 차이는 후보 아님, 저장소 안 --out은 오류, 단계 수 다른 짝 없음 수 ----------

def test_last_step_difference_not_candidate():
    # 마지막 단계(기능 이름)만 다른 쌍은 형제 기능일 수 있어 후보에서 뺀다
    result = _result_with_overview_row(("회원", "로그인", "일반 로그인", "아이디 입력하기"))
    assert not any(c.rule_id == "fo_overview_detail" for c in gc.candidates(result.config, result.index, result.made_by_rule))


def test_middle_step_difference_still_candidate():
    result = _result_with_overview_row(("회원", "로그인하기", "일반 로그인", "아이디 입력"))
    assert any(c.rule_id == "fo_overview_detail" and c.rep == "로그인" for c in gc.candidates(result.config, result.index, result.made_by_rule))


def test_out_inside_repo_is_error_and_writes_nothing(capsys):
    repo = Path(run.__file__).resolve().parents[2]
    import uuid
    inside = repo / "tests" / f"_tmp_draft_{uuid.uuid4().hex}"           # 실행마다 새 이름(만들어지면 안 됨)
    assert gc.main(["--project", str(SHOP), "--out", str(inside)]) == 1
    assert not inside.exists() and "저장소 안" in capsys.readouterr().out


def test_depth_mismatch_counts_shown(tmp_path, capsys):
    result = _result_with_overview_row(("회원", "로그인", "일반 로그인", "아이디 입력", "더 깊은 단계", "더 더 깊은 단계"))
    counts = gc.depth_mismatch_counts(result.config, result.index, result.made_by_rule)
    assert counts.get("fo_overview_detail") == 1                     # 같은 길이의 상세 경로가 없음
    gc.main(["--project", str(SHOP), "--out", str(tmp_path)])
    assert "단계 수가 달라서 비교 못 한 짝 없는 항목" in capsys.readouterr().out



def test_pairs_sharing_a_word_merged_into_one_line_with_pair_notes():
    # 2026-10-10: 같은 단어가 두 묶음에 들어가면 설정 오류 → 한 줄로 합치고, 주석에 원래 쌍마다 따로 적는다
    cands = [gc.Candidate("r1", "메뉴", "통합", 25, ("통합", 31)), gc.Candidate("r2", "메뉴", "화면", 3, ("기능 시험", 12)),
             gc.Candidate("r1", "다른", "것", 1, ("통합", 40))]
    text = gc.draft_yaml(cands)
    data = yaml.safe_load(text)
    assert data["groups"] == [["메뉴", "통합", "화면"], ["다른", "것"]]
    Glossary.model_validate(data)
    line = next(l for l in text.splitlines() if '"메뉴"' in l)
    assert "메뉴↔통합 r1 25회 예: 통합 31행" in line and "메뉴↔화면 r2 3회 예: 기능 시험 12행" in line



# ---------- 2026-10-10: 기존 사전이 깨졌거나 없어도 초안 도구는 돈다 ----------

def _shop_copy(tmp_path):
    import shutil
    shutil.copytree(SHOP.parent, tmp_path / "shop")
    project = tmp_path / "shop" / "project.yaml"
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["input_dir"] = str(SHOP.parent.parent.parent / "generated")
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return project


def test_broken_glossary_ignored_with_notice(tmp_path, capsys):
    project = _shop_copy(tmp_path)
    (project.parent / "glossary.yaml").write_text("groups:\n  - [가, 나]\n  - [나, 다]\n", encoding="utf-8")
    assert gc.main(["--project", str(project), "--out", str(tmp_path / "w")]) == 0
    out = capsys.readouterr().out
    assert "기존 사전에 오류가 있어 무시하고 새로 만들었어요" in out
    assert (tmp_path / "w" / gc.DRAFT_NAME).exists()
    assert "가" not in out.split("기존 사전")[0]                       # 화면에 단어 없음


def test_missing_glossary_file_ignored_with_notice(tmp_path, capsys):
    project = _shop_copy(tmp_path)
    (project.parent / "glossary.yaml").unlink()
    assert gc.main(["--project", str(project), "--out", str(tmp_path / "w")]) == 0
    assert "기존 사전에 오류가 있어 무시하고 새로 만들었어요" in capsys.readouterr().out


def test_other_config_errors_still_stop(tmp_path, capsys):
    project = _shop_copy(tmp_path)
    data = yaml.safe_load(project.read_text(encoding="utf-8"))
    data["documents"][0]["doc_type"] = "없는종류"
    project.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert gc.main(["--project", str(project), "--out", str(tmp_path / "w")]) == 1
    assert not (tmp_path / "w" / gc.DRAFT_NAME).exists()



# ---------- 2026-10-11: 대상 쪽 실제 이름이 2개 이상이면 합치지 않음(사슬 막기) ----------

def test_other_in_target_marked_when_seeker_name_exists_on_target_side():
    # 「간편 로그인」은 상세 쪽에도 실제 경로 단계로 있음 → 다른 메뉴 이름일 수 있음
    result = _result_with_overview_row(("회원", "로그인", "간편 로그인", "아이디 입력"))
    c = next(c for c in gc.candidates(result.config, result.index, result.made_by_rule) if c.rule_id == "fo_overview_detail")
    assert (c.rep, c.other, c.other_in_target) == ("일반 로그인", "간편 로그인", True)
    c = next(c for c in gc.candidates(*(lambda r: (r.config, r.index, r.made_by_rule))(
        _result_with_overview_row(("회원", "로그인하기", "일반 로그인", "아이디 입력")))) if c.rule_id == "fo_overview_detail")
    assert c.other_in_target is False


def test_two_target_names_keep_top_pair_and_note_dropped():
    cands = [gc.Candidate("r1", "가", "나", 5, ("시트A", 7)), gc.Candidate("r1", "다", "나", 2, ("시트B", 3))]
    text = gc.draft_yaml(cands)
    data = yaml.safe_load(text)
    assert data["groups"] == [["가", "나"]]                 # 대상 이름 가·다가 한 줄에 섞이지 않음
    Glossary.model_validate(data)
    assert "뺀 쌍: 다↔나 r1 2회 예: 시트B 3행 (대상 이름 겹침)" in text


def test_two_target_names_tie_drops_all_pairs_with_shared_word():
    cands = [gc.Candidate("r1", "가", "나", 3, ("시트A", 7)), gc.Candidate("r1", "다", "나", 3, ("시트B", 3)),
             gc.Candidate("r1", "마", "바", 1, ("시트C", 1))]
    text = gc.draft_yaml(cands)
    data = yaml.safe_load(text)
    assert data["groups"] == [["마", "바"]]
    assert "뺀 쌍: 가↔나 r1 3회 예: 시트A 7행 (대상 이름 겹침)" in text
    assert "뺀 쌍: 다↔나 r1 3회 예: 시트B 3행 (대상 이름 겹침)" in text


def test_other_name_on_target_side_counts_as_target_name():
    # 「화면」도 대상 쪽 실제 이름 → 메뉴·화면 두 대상 이름이 한 줄에 섞이면 안 됨
    cands = [gc.Candidate("r1", "메뉴", "통합", 25, ("통합", 31)),
             gc.Candidate("r2", "메뉴", "화면", 3, ("기능 시험", 12), other_in_target=True)]
    text = gc.draft_yaml(cands)
    assert yaml.safe_load(text)["groups"] == [["메뉴", "통합"]]
    assert "뺀 쌍: 메뉴↔화면 r2 3회 예: 기능 시험 12행 (대상 이름 겹침)" in text


def test_tie_all_dropped_still_valid_yaml():
    text = gc.draft_yaml([gc.Candidate("r1", "가", "나", 3, ("A", 1)), gc.Candidate("r1", "다", "나", 3, ("B", 2))])
    data = yaml.safe_load(text)
    assert data["groups"] == []
    Glossary.model_validate(data)


def test_pair_losing_to_a_dropped_pair_is_kept():
    # 가↔나(5)는 가↔마(9)에 져서 빠짐 → 나를 쓰는 남은 쌍이 없으므로 다↔나(3)는 남는다(연쇄로 잃지 않음)
    C = gc.Candidate
    data = yaml.safe_load(gc.draft_yaml([C("r1", "가", "나", 5, ("A", 1)), C("r1", "다", "나", 3, ("B", 1)),
                                         C("r1", "가", "마", 9, ("C", 1))]))
    assert sorted(data["groups"]) == [["가", "마"], ["다", "나"]]
    Glossary.model_validate(data)


def test_random_drafts_always_valid_glossary():
    import random
    rnd = random.Random(7)
    words = list("가나다라마바사아")
    for _ in range(500):
        cands = []
        for _ in range(rnd.randint(1, 7)):
            a, b = rnd.sample(words, 2)
            cands.append(gc.Candidate(rnd.choice(["r1", "r2"]), a, b, rnd.randint(1, 4), ("S", 1), rnd.random() < 0.3))
        Glossary.model_validate(yaml.safe_load(gc.draft_yaml(cands)))


# ---------- 2026-10-12 결정 1: 같은 깊이에서 두 단어 모두 대상 쪽 실제 이름이면 혼자여도 뺌 ----------

def test_single_pair_both_target_names_dropped_with_note():
    text = gc.draft_yaml([gc.Candidate("r1", "일반 로그인", "간편 로그인", 4, ("A", 1), other_in_target=True, level=2)])
    assert yaml.safe_load(text)["groups"] == []
    assert "뺀 쌍: 일반 로그인↔간편 로그인 r1 4회 예: A 1행 (대상 이름 겹침)" in text


def test_other_is_rep_of_another_rule_at_same_level_dropped():
    C = gc.Candidate
    text = gc.draft_yaml([C("r1", "가", "나", 5, ("A", 1), level=2), C("r2", "나", "다", 3, ("B", 1), level=2)])
    assert yaml.safe_load(text)["groups"] == [["나", "다"]]
    assert "뺀 쌍: 가↔나 r1 5회 예: A 1행 (대상 이름 겹침)" in text


def test_other_is_rep_at_different_level_not_judged():
    C = gc.Candidate
    text = gc.draft_yaml([C("r1", "가", "나", 5, ("A", 1), level=1), C("r2", "나", "다", 3, ("B", 1), level=2)])
    assert yaml.safe_load(text)["groups"] == [["가", "나"]]


def test_other_in_target_only_at_same_depth():
    # 「문의」는 상세 쪽에 2단계로만 있음 → 3단계 자리의 짝 없는 이름으로는 대상 이름 아님
    result = _result_with_overview_row(("회원", "로그인", "문의", "아이디 입력"))
    c = next(c for c in gc.candidates(result.config, result.index, result.made_by_rule) if c.rule_id == "fo_overview_detail" and c.other == "문의")
    assert (c.rep, c.other_in_target, c.level) == ("일반 로그인", False, 2)
    result = _result_with_overview_row(("회원", "로그인", "간편 로그인", "아이디 입력"))
    c = next(c for c in gc.candidates(result.config, result.index, result.made_by_rule) if c.rule_id == "fo_overview_detail")
    assert (c.other_in_target, c.level) == (True, 2)


# ---------- 2026-10-12 결정 2: 표기만 다른 같은 단어(비교용 열쇠가 같음)는 한 단어로 ----------

def test_draft_groups_by_step_key():
    C = gc.Candidate
    data = yaml.safe_load(gc.draft_yaml([C("r1", "로그인", "가", 4, ("A", 1)), C("r1", "로 그인", "나", 2, ("B", 1))]))
    assert data["groups"] == [["로그인", "가", "나"]]
    Glossary.model_validate(data)


def test_random_drafts_valid_by_step_key():
    import random
    rnd = random.Random(11)
    words = ["가", "가 ", "나", "다 라", "다라", "마", "바"]
    for _ in range(500):
        cands = []
        for _ in range(rnd.randint(1, 6)):
            a, b = rnd.sample(words, 2)
            if a.replace(" ", "") == b.replace(" ", ""):
                continue
            cands.append(gc.Candidate(rnd.choice(["r1", "r2"]), a, b, rnd.randint(1, 3), ("S", 1),
                                      rnd.random() < 0.3, rnd.choice([1, 2])))
        Glossary.model_validate(yaml.safe_load(gc.draft_yaml(cands)))


# ---------- 2026-10-12: --out 위치 규칙(실행과 같음) ----------

def test_out_under_repo_out_allowed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path / "repo")
    out = tmp_path / "repo" / "out" / "o"
    assert gc.main(["--project", str(SHOP), "--out", str(out)]) == 0
    assert (out / gc.DRAFT_NAME).exists() and "저장소 안" not in capsys.readouterr().out


def test_out_elsewhere_in_repo_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path / "repo")
    out = tmp_path / "repo" / "configs" / "o"
    assert gc.main(["--project", str(SHOP), "--out", str(out)]) == 1
    assert not out.exists() and "저장소 안" in capsys.readouterr().out


def test_out_outside_repo_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path / "repo")
    assert gc.main(["--project", str(SHOP), "--out", str(tmp_path / "work")]) == 0


# ---------- 2026-10-12 리뷰 R2: 후보 계산은 run 없이 import된다 ----------

def test_import_does_not_load_run():
    import os
    import subprocess
    import sys
    code = "import sys, si_prep.glossary_candidates; print('si_prep.run' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert done.stdout.strip() == "False", done.stdout + done.stderr


# ---------- 후보마다 양쪽 이름이 나온 파일·시트·행 ----------

def test_candidate_has_sources_on_both_sides():
    result = _result_with_overview_row(("회원", "로그인하기", "일반 로그인", "아이디 입력"))
    c = next(c for c in gc.candidates(result.config, result.index, result.made_by_rule) if c.rule_id == "fo_overview_detail")
    fo = "가상몰_기능정의서_v1.2.xlsx"
    assert c.other_sources == ((fo, "요약", 6),)                         # 짝 없는 쪽(로그인하기)
    assert c.rep_sources and all(f == fo and s != "요약" for f, s, _ in c.rep_sources)   # 대상(상세) 쪽(로그인)
    assert len(c.rep_sources) <= gc.MAX_SOURCES


def test_sources_capped_and_written_under_each_pair():
    src = tuple(("f.xlsx", "시트A", r) for r in range(1, 3))
    many = tuple(("g.xlsx", "시트B", r) for r in range(10, 10 + gc.MAX_SOURCES))
    text = gc.draft_yaml([gc.Candidate("r1", "가", "나", 3, ("시트A", 1), rep_sources=many, other_sources=src)])
    lines = text.splitlines()
    i = next(n for n, l in enumerate(lines) if '"가"' in l)
    note = lines[i + 1]
    assert note.startswith("  #   출처 가↔나:")                          # 그 줄 바로 아래 주석
    assert "가 = g.xlsx 시트B 10행, g.xlsx 시트B 11행, g.xlsx 시트B 12행" in note
    assert "나 = f.xlsx 시트A 1행, f.xlsx 시트A 2행" in note
    assert yaml.safe_load(text)["groups"] == [["가", "나"]]


def test_sources_listed_for_dropped_pairs_too():
    C = gc.Candidate
    text = gc.draft_yaml([C("r1", "가", "나", 3, ("A", 1), rep_sources=(("f.xlsx", "A", 1),), other_sources=(("f.xlsx", "B", 2),)),
                          C("r1", "다", "나", 3, ("B", 2), rep_sources=(("f.xlsx", "C", 3),), other_sources=(("f.xlsx", "B", 2),))])
    assert "  #   출처 가↔나: 가 = f.xlsx A 1행 / 나 = f.xlsx B 2행" in text
    assert "  #   출처 다↔나: 다 = f.xlsx C 3행 / 나 = f.xlsx B 2행" in text


def test_every_candidate_has_source_note():
    result = _result_with_overview_row(("회원", "로그인하기", "일반 로그인", "아이디 입력"))
    cands = gc.candidates(result.config, result.index, result.made_by_rule)
    text = gc.draft_yaml(cands)
    assert text.count("  #   출처 ") == len(cands)
