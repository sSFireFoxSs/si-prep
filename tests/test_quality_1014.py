"""2026-10-14 품질 개선 3가지(평가용 출력 items·links·chunks는 그대로).

1. 머리글 위 칸: 표마다 머리글 행보다 위(앞 표가 끝난 다음 행부터)에 원문 값이 있는 칸을 세서 unsupported_layout 1건
   (위치 = 그 행 범위, 메시지 = 시트·행 범위·칸 수, 셀 값 없음). 표 제목·작성자 칸도 센다. 도구가 원래 읽지 않는 곳이라
   처리 보고서 0절 「알려진 한계」에만 보인다(「할 일」에 안 올림).
2. 콘솔 출력: 프로그램 시작 때 화면 출력의 인코딩은 그대로 두고 못 쓰는 글자만 ?로(cp949 콘솔에서 오류 없이 끝남, 한글은 그대로).
   PYTHONIOENCODING이 설정돼 있으면 그대로 따른다.
3. 처리 보고서 0절: 「할 일」(설정을 고치면 해결)과 「알려진 한계」(도구가 원래 못 하는 것, 설정으로는 못 고침)로 나눈다.
   한계: 머리글 위 칸, 머리글 없는 열의 값 덩어리, 숨긴 행·열에 값(hidden_content).
"""

import io
import os
import subprocess
import sys
from pathlib import Path


from si_prep import console, layout, report, run
from si_prep.config import Profile, sheet_profile
from si_prep.issues import Issues
from si_prep.reader import open_workbook
from conftest import SHOP, make_profile, write_book

ROOT = Path(__file__).resolve().parents[1]
HEAD = ["분류1", "기능명", "설명"]
TABLES = {"title_row": {"only_columns": ["A"]}, "header_row": {"offset": 1, "col": "A", "pattern": "^번호$"}}


def _profile(header_row=1, tables=None):
    return make_profile({"hierarchy": [{"header_contains": "분류1"}], "title": {"header_contains": "기능명"},
                         "description": {"header_contains": "설명"}},
                        header_rows=[header_row], data_start_row=header_row + 1,
                        **({"tables": tables} if tables is not None else {}))


def _above(tmp_path, rows, p, merges=(), hidden_rows=()):
    path = write_book(tmp_path / "w.xlsx", rows, merges, hidden_rows=hidden_rows)
    issues = Issues()
    tables = layout.build_tables(open_workbook(path, Issues()).sheet("S"), sheet_profile(p, "S"), "w.xlsx", issues)
    found = layout.above_header_warnings(tables, issues)
    return [i for i in issues if i.kind == "unsupported_layout"], found


# ---------- 1. 머리글 위 칸 ----------

def test_cells_above_header_one_warning_per_table(tmp_path):
    rows = [["가나다제목"], ["라마바", None, "사아자"], HEAD, ["가", "기능", "설명 글"]]
    [w], found = _above(tmp_path, rows, _profile(header_row=3))
    assert w.limit == "above_header"
    assert [(l.rows.start, l.rows.end, l.cols) for l in w.locations] == [(1, 2, None)]
    assert "3칸" in w.message and "1~2행" in w.message and "S" in w.message
    for v in ("가나다제목", "라마바", "사아자"):
        assert v not in w.message                      # 셀 값은 넣지 않음
    assert found == [("w.xlsx", "S", 1, 2, 3)]


def test_no_warning_when_header_on_first_row_or_rows_above_empty(tmp_path):
    assert _above(tmp_path, [HEAD, ["가", "기능", "설명"]], _profile())[0] == []
    assert _above(tmp_path, [[], [], HEAD, ["가", "기능", "설명"]], _profile(header_row=3))[0] == []


def test_merged_title_counts_once_and_hidden_rows_count(tmp_path):
    rows = [["병합 제목"], ["숨긴 메모"], HEAD, ["가", "기능", "설명"]]
    [w], found = _above(tmp_path, rows, _profile(header_row=3), merges=["A1:C1"], hidden_rows=[2])
    assert found == [("w.xlsx", "S", 1, 2, 2)]        # 병합은 시작 칸 하나, 숨긴 행도 셈
    assert "2칸" in w.message


def test_tables_title_cell_is_read_so_not_counted(tmp_path):
    """tables 설정 시트: 표마다 제목 행~머리글 위만 센다. 표 제목으로 읽히는 첫 칸은 빼고, 앞 표 데이터 뒤의 행(메모 등)은
    다음 표의 머리글 위가 아니다(앞 표 범위)"""
    rows = [["주문 정책"], ["번호"] + HEAD, [1, "주문", "주문 취소", "설명"], ["메모 글"],
            ["배송 정책"], ["번호"] + HEAD, [1, "배송", "배송 조회", "설명"]]
    ws, found = _above(tmp_path, rows, _profile(tables=TABLES))
    assert ws == [] and found == []


def test_tables_unread_cell_on_title_row_counted(tmp_path):
    two = {**TABLES, "title_row": {"only_columns": ["A", "B"]}}
    rows = [["주문 정책", "작성 칸"], ["번호"] + HEAD, [1, "주문", "주문 취소", "설명"], [],
            ["배송 정책"], ["번호"] + HEAD, [1, "배송", "배송 조회", "설명"]]
    [w], found = _above(tmp_path, rows, _profile(tables=two))
    assert found == [("w.xlsx", "S", 1, 1, 1)]      # B1만(A1은 표 제목으로 읽힘)
    assert w.limit == "above_header" and "1칸" in w.message


def test_headerless_block_is_limit_and_repeated_header_is_not(tmp_path):
    from test_layout_warnings import _issues, _profile as lw_profile   # noqa: F401
    _, issues = _issues(tmp_path, [HEAD, ["가", "기능", "설명", None, "메모"], ["나", "기능2", "설명2"]])
    [w] = issues.by_kind("unsupported_layout")
    assert w.limit == "headerless"
    _, issues = _issues(tmp_path, [HEAD, ["가", "기능", "설명"], HEAD, ["나", "기능2", "설명2"]])
    [w] = issues.by_kind("unsupported_layout")
    assert w.limit is None                             # 반복 머리글은 tables 설정으로 고치는 것(할 일)


def test_issue_limit_not_in_output():
    issues = Issues()
    i = issues.add("unsupported_layout", "m", file="f.xlsx", limit="above_header")
    assert "limit" not in i.to_warning("WN-000001").model_dump()


def test_shop_run_counts_above_header(tmp_path):
    result = run.build(SHOP)
    assert result.above_header == [x for x in result.above_header if x[4] > 0]
    tagged = [w for w in result.warnings if result.limit_ids.get(w.warning_id) == "above_header"]
    assert len(tagged) == len(result.above_header)
    assert all(w.kind == "unsupported_layout" and w.item_ids == [] for w in tagged)


# ---------- 2. 콘솔 출력 ----------

TEXT = "한글 경로 › 단계 ✓ 끝"   # ›·✓은 cp949에 없는 기호


def test_console_cp949_keeps_korean_and_replaces_symbols(monkeypatch):
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp949", errors="strict", newline="\n")
    console.replace_unencodable(stream)
    print(TEXT, file=stream)
    stream.flush()
    assert stream.encoding == "cp949" and stream.errors == "replace"     # 인코딩은 그대로, 못 쓰는 글자만 대체
    assert raw.getvalue().decode("cp949") == "한글 경로 ? 단계 ? 끝\n"


def test_console_follows_pythonioencoding(monkeypatch):
    monkeypatch.setenv("PYTHONIOENCODING", "cp949:strict")
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp949", errors="strict")
    console.replace_unencodable(stream)
    assert stream.errors == "strict"                                      # 사람이 정한 설정은 그대로 따름


def test_console_skips_streams_without_reconfigure(monkeypatch):
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)
    console.replace_unencodable(object())              # reconfigure가 없으면 그대로(오류 없음)


def _plain_env():
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    env.pop("PYTHONUTF8", None)
    env.pop("PYTHONIOENCODING", None)
    return env


def test_run_main_under_locale_console(tmp_path):
    """환경 변수 없이(파이프 = 로캘 인코딩, 한국어 윈도는 cp949) 실행이 오류 없이 끝남"""
    r = subprocess.run([sys.executable, "-m", "si_prep", "--project", str(SHOP), "--out", str(tmp_path / "o")],
                       env=_plain_env(), capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert (tmp_path / "o" / "items.jsonl").exists()


def test_subprocess_output_keeps_korean():
    """환경 변수 없이 파이프로 받은 출력: 그 프로세스의 로캘 인코딩으로 읽으면 한글은 그대로, 바뀐 글자는 cp949에 없는 기호뿐"""
    code = ("import sys, locale; from si_prep.console import replace_unencodable; replace_unencodable(); "
            f"print(locale.getencoding(), file=sys.stderr); print({TEXT!r})")
    r = subprocess.run([sys.executable, "-c", code], env=_plain_env(), capture_output=True)
    assert r.returncode == 0, r.stderr
    out = r.stdout.decode(r.stderr.decode("ascii").strip()).rstrip("\r\n")
    assert len(out) == len(TEXT) and "한글 경로" in out and "단계" in out and "끝" in out
    assert all(a == b or (a == "?" and b in "›✓") for a, b in zip(out, TEXT))


# ---------- 3. 0절 할 일 / 알려진 한계 ----------

def _sec0(text):
    return text[text.index("## 0. "):text.index("## 1. ")]


def test_first_section_has_todo_and_known_limits():
    result = run.build(SHOP)
    sec = _sec0(report.render(result))
    assert sec.index("할 일:") < sec.index("알려진 한계(설정으로는 못 고침):")
    limits = sec[sec.index("알려진 한계(설정으로는 못 고침):"):]
    n_above = len(result.above_header)
    cells = sum(x[4] for x in result.above_header)
    if n_above:
        assert f"표 {n_above}개 · 칸 {cells}개" in limits
    headerless = sum(1 for v in result.limit_ids.values() if v == "headerless")
    if headerless:
        assert f"머리글 없는 열의 값 덩어리 {headerless}건" in limits
    hidden = sum(w.kind == "hidden_content" for w in result.warnings)
    if hidden:
        assert f"hidden_content {hidden}건" in limits


def test_limits_not_counted_in_todo():
    result = run.build(SHOP)
    sec = _sec0(report.render(result))
    todo = sec[sec.index("할 일:"):sec.index("알려진 한계(설정으로는 못 고침):")]
    limit_ids = set(result.limit_ids)
    n = sum(w.kind == "unsupported_layout" and w.warning_id not in limit_ids for w in result.warnings)
    line = next((l for l in todo.splitlines() if "지원 범위 밖" in l), "")
    if n:
        assert f"unsupported_layout {n}" in line
    else:
        assert "unsupported_layout" not in line


def test_limit_lines_empty_says_none():
    assert report._limit_lines([]) == ["- 없음"]


def test_headerless_limit_line_says_check_source():
    result = run.build(SHOP)
    sec = _sec0(report.render(result))
    line = next(l for l in sec.splitlines() if "머리글 없는 열의 값" in l)
    assert "중요한 내용이면 원본 확인" in line
    assert "설정으로는 고칠 수 없습니다" in report.EASY[0]


# ---------- 머리글 위 칸 중 다른 기능이 읽는 칸은 세지 않음 ----------

def _sheet_with(tmp_path, rows, p, merges=()):
    book = open_workbook(write_book(tmp_path / "v.xlsx", rows, merges), Issues())
    tables = layout.build_tables(book.sheet("S"), sheet_profile(p, "S"), "v.xlsx", Issues())
    return book, tables


def test_merge_from_above_into_header_is_read(tmp_path):
    """머리글 위에서 시작해 머리글 행까지 내려오는 세로 병합의 시작 칸은 머리글 글자로 복원돼 읽힌다 → 세지 않음"""
    rows = [["분류1", "메모값"], [], [None, "기능명", "설명"], ["가", "기능", "설명 글"]]
    _, tables = _sheet_with(tmp_path, rows, _profile(header_row=3), merges=["A1:A3"])
    issues = Issues()
    assert layout.above_header_warnings(tables, issues) == [("v.xlsx", "S", 1, 1, 1)]   # B1만


def test_version_cover_cells_are_read(tmp_path):
    """표지 버전 읽기(version.cover_sheet·label_pattern)가 읽는 라벨·값 칸은 세지 않음"""
    from si_prep import extract
    p = Profile.model_validate({**_profile(header_row=3).model_dump(exclude_none=True),
                                "version": {"cover_sheet": "S", "label_pattern": "버전"}})
    rows = [["버전", "1.0", "기타 글"], [], HEAD, ["가", "기능", "설명 글"]]
    book, tables = _sheet_with(tmp_path, rows, p)
    read = extract.cover_cells(book, p)
    assert read == {("S", 1, "A"), ("S", 1, "B")}
    assert layout.above_header_warnings(tables, Issues(), read) == [("v.xlsx", "S", 1, 1, 1)]   # C1만
