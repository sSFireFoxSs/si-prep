"""한 시트에 표 여러 개 — 프로필 tables를 설정한 시트만 표마다 나눠 읽는다.
표 시작 = 제목 행 신호(지정 열에만 원문 값) + 머리글 신호(제목 + offset 행의 지정 열이 정규식에 맞음) 둘 다.
제목은 경로에서 시트 이름 단계 다음·열 분류 단계 앞, basis table_title(스키마 1.4). 행 번호는 시트 원래 행.
"""

import pytest
from pydantic import ValidationError

from si_prep import boundary, hierarchy, layout
from si_prep.config import sheet_profile
from si_prep.issues import Issues
from si_prep.reader import open_workbook
from conftest import make_profile, write_book

TABLES = {"title_row": {"only_columns": ["A"]}, "header_row": {"offset": 1, "col": "A", "pattern": "^번호$"}}
HEAD = ["번호", "분류1", "기능명", "설명"]


def _profile(tables=TABLES, **over):
    return make_profile({"hierarchy": [{"header_contains": "분류1"}], "title": {"header_contains": "기능명"},
                         "description": {"header_contains": "설명"}},
                        **{**({"tables": tables} if tables is not None else {}), **over})


def _wb(tmp_path, rows, merges=()):
    return open_workbook(write_book(tmp_path / "t.xlsx", rows, merges), Issues()).sheet("S")


def _tables(grid, p, issues=None):
    issues = Issues() if issues is None else issues
    return layout.build_tables(grid, sheet_profile(p, "S"), "t.xlsx", issues), issues


def _paths(grid, p, issues=None):
    issues = Issues() if issues is None else issues
    sp = sheet_profile(p, "S")
    out = []
    for t in layout.build_tables(grid, sp, "t.xlsx", issues):
        groups = boundary.by_row(t, sp, issues)
        for g, steps in zip(groups, hierarchy.by_columns(t, groups, sp, issues)):
            out.append((g.start, [(s.value, s.basis, s.col) for s in steps]))
    return out


# 1행 제목(A1:D1 병합) / 2 머리글 / 3·4 데이터 / 5 빈 행 / 6 제목 / 7 머리글 / 8 데이터 / 9 「※」 끝 표시(A열만)
# 10 빈 행 / 11 A열만 있는 행(다음 행 A가 머리글 아님 → 표 시작 아님) / 12 데이터처럼 보이는 행
ROWS = [["주문 정책"], HEAD, [1, "주문", "주문 취소", "결제 전 취소"], [2, None, "주문 변경", "배송 전 변경"], [],
        ["배송 정책"], HEAD, [1, "배송", "배송 조회", "단계 표시"], ["※ 도서 산간 제외"], [],
        ["메모"], [None, "배송", "배송지 변경", "1회만"]]


# ---------- 설정 ----------

def test_tables_config_validates():
    assert _profile().tables.title_to == "path" and _profile().tables.header_row.offset == 1
    assert _profile(tables=None).tables is None
    for bad in ({"title_row": {"only_columns": []}, "header_row": TABLES["header_row"]},
                {"title_row": {"only_columns": ["a"]}, "header_row": TABLES["header_row"]},
                {"title_row": TABLES["title_row"], "header_row": {"col": "A", "pattern": "("}},
                {**TABLES, "title_to": "title"}):
        with pytest.raises(ValidationError):
            _profile(tables=bad)


def test_tables_per_sheet_override():
    p = _profile(tables=None, sheet_overrides=[{"sheets": ["S"], "tables": TABLES}])
    assert sheet_profile(p, "S").tables is not None and sheet_profile(p, "T").tables is None


# ---------- 표 나누기 ----------

def test_split_needs_title_and_header_signals(tmp_path):
    grid = _wb(tmp_path, ROWS, merges=["A1:D1"])
    tables, issues = _tables(grid, _profile(stop_markers=["※"]))
    assert [(t.title_row, t.table_title, t.header_rows, t.data_rows) for t in tables] == [
        (1, "주문 정책", [2], [3, 4, 5]),          # 병합된 제목 칸도 「A열에만 원문 값」
        (6, "배송 정책", [7], [8]),                # 9행 「※」 끝 표시(표마다), 11행 「메모」는 다음 행이 머리글 아님
    ]
    assert not issues.items


def test_same_header_tables_with_one_blank_row_stay_apart(tmp_path):
    rows = [["가입 정책"], HEAD, [1, "회원", "가입", "약관 동의"], [], ["탈퇴 정책"], HEAD, [1, "회원", "탈퇴", "사유 선택"]]
    tables, _ = _tables(_wb(tmp_path, rows), _profile())
    assert [(t.table_title, t.data_rows) for t in tables] == [("가입 정책", [3, 4]), ("탈퇴 정책", [7])]


def test_table_without_required_role_skipped_alone(tmp_path):
    rows = [["가 정책"], HEAD, [1, "주문", "a", "b"], [], ["나 정책"], ["번호", "기능명", "설명"], [1, "c", "d"], [],
            ["다 정책"], HEAD, [1, "회원", "e", "f"]]
    tables, issues = _tables(_wb(tmp_path, rows), _profile())
    assert [t.table_title for t in tables] == ["가 정책", "다 정책"]
    [w] = issues.by_kind("header_not_found")
    assert [(l.rows.start, l.rows.end) for l in w.locations] == [(6, 6)] and "표" in w.message


def test_values_above_first_table_warn(tmp_path):
    rows = [[None, "문서 제목"], [], ["가 정책"], HEAD, [1, "주문", "a", "b"]]
    tables, issues = _tables(_wb(tmp_path, rows), _profile())
    assert [t.table_title for t in tables] == ["가 정책"]
    [w] = issues.by_kind("unsupported_layout")
    assert [(l.rows.start, l.rows.end) for l in w.locations] == [(1, 2)]


def test_no_table_found_skips_sheet(tmp_path):
    tables, issues = _tables(_wb(tmp_path, [HEAD, [1, "주문", "a", "b"]]), _profile())
    assert tables == [] and [i.kind for i in issues] == ["header_not_found"]


def test_sheet_without_tables_unchanged(tmp_path):
    grid = _wb(tmp_path, [HEAD, [1, "주문", "a", "b"]])
    [t] = layout.build_tables(grid, sheet_profile(_profile(tables=None), "S"), "t.xlsx", Issues())
    assert (t.header_rows, t.data_rows, t.table_title) == ([1], [2], None)


# ---------- 경로·fill_down ----------

def test_title_step_after_sheet_root_before_columns(tmp_path):
    grid = _wb(tmp_path, ROWS, merges=["A1:D1"])
    paths = _paths(grid, _profile(stop_markers=["※"], sheet_as_root=True))
    assert paths[0] == (3, [("S", "sheet_name", None), ("주문 정책", "table_title", None), ("주문", "cell", "B")])


def test_title_to_none_keeps_path(tmp_path):
    grid = _wb(tmp_path, ROWS, merges=["A1:D1"])
    paths = _paths(grid, _profile(tables={**TABLES, "title_to": "none"}, stop_markers=["※"]))
    assert paths[0] == (3, [("주문", "cell", "B")])


def test_fill_down_restarts_per_table(tmp_path):
    # 둘째 표 첫 항목의 빈 분류 칸은 위 표의 값으로 채우지 않는다
    rows = [["가 정책"], HEAD, [1, "주문", "a", "b"], [2, None, "c", "d"], [], ["나 정책"], HEAD, [1, None, "e", "f"]]
    issues = Issues()
    paths = _paths(_wb(tmp_path, rows), _profile(hierarchy={"method": "columns", "fill_down": True}), issues)
    assert paths[1] == (4, [("가 정책", "table_title", None), ("주문", "filled_down", "B")])
    assert paths[2] == (8, [("나 정책", "table_title", None), (None, "empty", "B")])


def test_border_warning_once_per_table_with_label(tmp_path):
    # 리뷰 지적: tables + border_groups 시트에서 「테두리로 묶음을 구분할 수 없음」은 표마다 어느 표인지 + 위치
    rows = [["가 정책"], HEAD, [1, "주문", "a", "b"], [2, None, "c", "d"], [], ["나 정책"], HEAD, [1, "회원", "e", "f"]]
    hier = {"method": "columns", "fill_down": True, "blank_means_above": True, "border_groups": True}
    issues = Issues()
    _paths(_wb(tmp_path, rows), _profile(hierarchy=hier), issues)
    ws = [w for w in issues if "테두리로 묶음을 구분할 수 없" in w.message]
    assert len(ws) == 2 and len({w.message for w in ws}) == 2
    assert "표(제목 1행)" in ws[0].message and [(l.rows.start, l.cols) for l in ws[0].locations] == [(2, ["B"])]


def test_overlapping_or_empty_table_warns(tmp_path):
    # 리뷰 지적: 다음 표 제목이 앞 표 머리글 안에 걸리거나(머리글 2줄), 데이터 행이 없는 표는 조용히 넘기지 않고 경고
    rows = [["가 정책"], HEAD, ["나 정책"], HEAD, [1, "주문", "a", "b"], [2, "주문", "c", "d"]]
    tables, issues = _tables(_wb(tmp_path, rows), _profile(header_rows=[1, 2], data_start_row=3))
    assert [t.table_title for t in tables] == ["나 정책"]
    [w] = issues.by_kind("unsupported_layout")
    assert "가 정책" not in w.message and "제목 1행" in w.message and [(l.rows.start, l.rows.end) for l in w.locations] == [(1, 2)]


# ---------- 표마다 머리글 줄 수 — header_row.rows: merge ----------

MERGE_HEAD = {"title_row": {"only_columns": ["A"]},
              "header_row": {"col": "A", "pattern": "^번호$", "rows": "merge"}}
TOP = ["번호", "분류", "기능명", "설명"]
BOTTOM = [None, "분류1", None, None]


def test_header_rows_option_validates():
    assert _profile().tables.header_row.rows == "fixed"                      # 기본은 지금처럼 header_rows 줄 수
    assert _profile(tables=MERGE_HEAD).tables.header_row.rows == "merge"
    with pytest.raises(ValidationError):
        _profile(tables={**MERGE_HEAD, "header_row": {**MERGE_HEAD["header_row"], "rows": "auto"}})
    assert _profile().tables.first_without_title is False
    assert _profile(tables={**TABLES, "first_without_title": True}).tables.first_without_title is True


def test_merge_rows_per_table_from_signal_merge(tmp_path):
    # 표1: 신호 칸 A2:A3 세로 병합 → 머리글 2줄(분류 / 분류1로 폄), 표2: 병합 없음 → 1줄, 표3: 가로 병합만 → 1줄
    rows = [["가 정책"], TOP, BOTTOM, [1, "주문", "a", "b"], [],
            ["나 정책"], HEAD, [1, "회원", "c", "d"], [],
            ["다 정책"], ["번호", None, "분류1", "기능명", "설명"], [1, None, "배송", "e", "f"]]
    grid = _wb(tmp_path, rows, merges=["A2:A3", "C2:C3", "D2:D3", "A11:B11"])
    p = _profile(tables=MERGE_HEAD, columns={"hierarchy": [{"header_contains": "분류1"}],
                                             "title": {"header_contains": "기능명"}, "description": {"header_contains": "설명"}})
    tables, issues = _tables(grid, p)
    assert [(t.table_title, t.header_rows, t.data_rows) for t in tables] == [
        ("가 정책", [2, 3], [4, 5]), ("나 정책", [7], [8, 9]), ("다 정책", [11], [12])]
    assert tables[0].headers["B"] == "분류 / 분류1" and tables[0].roles["hierarchy"] == ["B"]   # 표마다 그 표 머리글로 선택자
    assert not issues.items


def test_fixed_rows_keep_profile_header_rows(tmp_path):
    # 기본(fixed)이면 병합이 있어도 프로필 header_rows 줄 수(1줄) — 지금 그대로
    rows = [["가 정책"], TOP, BOTTOM, [1, "주문", "a", "b"]]
    grid = _wb(tmp_path, rows, merges=["A2:A3"])
    tables, _ = _tables(grid, _profile(columns={"hierarchy": [{"header_contains": "분류"}],
                                                "title": {"header_contains": "기능명"}, "description": {"header_contains": "설명"}}))
    assert [(t.header_rows, t.data_rows) for t in tables] == [([2], [3, 4])]


def test_merge_height_counts_from_signal_row(tmp_path):
    # 신호 칸이 병합 범위 중간이면 신호 행부터 병합 끝 행까지
    grid = _wb(tmp_path, [["가"], [], [], [], []], merges=["A2:A5"])
    head = _profile(tables=MERGE_HEAD).tables.header_row
    assert layout.header_height(grid, head, 3, 1) == (3, "A2:A5")
    assert layout.header_height(grid, head, 1, 1) == (1, None)


def test_merge_taller_than_four_skips_that_table(tmp_path):
    rows = [["가 정책"], TOP, [], [], [], [], [1, "주문", "a", "b"], [],
            ["나 정책"], HEAD, [1, "회원", "c", "d"]]
    grid = _wb(tmp_path, rows, merges=["A2:A6"])
    tables, issues = _tables(grid, _profile(tables=MERGE_HEAD))
    assert [t.table_title for t in tables] == ["나 정책"]
    [w] = issues.by_kind("header_not_found")
    assert "A2:A6" in w.message and "5줄" in w.message and "제목 1행" in w.message
    assert [(l.rows.start, l.rows.end) for l in w.locations] == [(2, 6)]


# ---------- 제목 없는 첫 표 — tables.first_without_title ----------

UNTITLED = {**TABLES, "first_without_title": True}
TOP_ROWS = [HEAD, [1, "주문", "a", "b"], [2, "주문", "c", "d"], [], ["나 정책"], HEAD, [1, "회원", "e", "f"]]


def test_untitled_first_table_read_when_option_on(tmp_path):
    grid = _wb(tmp_path, TOP_ROWS)
    tables, issues = _tables(grid, _profile(tables=UNTITLED))
    assert [(t.table_title, t.title_row, t.header_rows, t.data_rows) for t in tables] == [
        (None, None, [1], [2, 3, 4]), ("나 정책", 5, [6], [7])]
    assert tables[0].untitled and not tables[1].untitled
    assert not issues.items
    assert layout.table_label(tables[0]) == "S [제목 없는 표, 머리글 1행]"
    assert layout.table_label(tables[1]) == "S [표 제목 5행]"
    assert layout.table_label(tables[0], header_lines=True) == "S [제목 없는 표, 머리글 1행부터 1줄]"   # 설정 검사 대조 줄
    assert layout.table_label(tables[1], header_lines=True) == "S [표 제목 5행 · 머리글 1줄]"


def test_untitled_table_has_no_title_step(tmp_path):
    paths = _paths(_wb(tmp_path, TOP_ROWS), _profile(tables=UNTITLED))
    assert paths[0] == (2, [("주문", "cell", "B")])                   # 제목 단계 없음(title_to: none과 같음)
    assert paths[-1] == (7, [("나 정책", "table_title", None), ("회원", "cell", "B")])


def test_untitled_table_off_by_default_warns_above(tmp_path):
    tables, issues = _tables(_wb(tmp_path, TOP_ROWS), _profile())
    assert [t.table_title for t in tables] == ["나 정책"]
    [w] = issues.by_kind("unsupported_layout")
    assert [(l.rows.start, l.rows.end) for l in w.locations] == [(1, 4)]


def test_untitled_needs_empty_rows_above(tmp_path):
    # 머리글 신호 행 위에 값이 있는 행이 있으면 제목 없는 표로 읽지 않는다(지금처럼 첫 표 위의 값 경고)
    rows = [[None, "문서 제목"], []] + TOP_ROWS
    tables, issues = _tables(_wb(tmp_path, rows), _profile(tables=UNTITLED))
    assert [t.table_title for t in tables] == ["나 정책"]
    [w] = issues.by_kind("unsupported_layout")
    assert [(l.rows.start, l.rows.end) for l in w.locations] == [(1, 6)]


def test_untitled_after_blank_rows_and_only_one(tmp_path):
    # 위가 빈 행뿐이면 그 아래 신호 행부터. 시트당 1개 — 다음 제목 표 앞까지 한 표(둘째 머리글 행도 그 표 데이터)
    rows = [[], [], HEAD, [1, "주문", "a", "b"], [], HEAD, [1, "주문", "c", "d"], [], ["나 정책"], HEAD, [1, "회원", "e", "f"]]
    grid = _wb(tmp_path, rows)
    sp = sheet_profile(_profile(tables=UNTITLED), "S")
    issues = Issues()
    tables = layout.build_tables(grid, sp, "t.xlsx", issues)
    assert [(t.untitled, t.header_rows, t.data_rows) for t in tables] == [
        (True, [3], [4, 5, 6, 7, 8]), (False, [10], [11])]
    # 리뷰 지적: 표 안 데이터 행에서 머리글 신호가 다시 맞으면(둘째 머리글 행이 항목이 됨) 조용히 넘기지 않고 경고
    for t in tables:
        layout.table_warnings(t, sp, issues)
    [w] = [w for w in issues.by_kind("unsupported_layout") if "머리글 신호" in w.message]
    assert [(l.rows.start, l.rows.end) for l in w.locations] == [(6, 6)] and "제목 없는 표(머리글 3행)" in w.message


def test_header_signal_inside_titled_table_warns(tmp_path):
    # 제목 행 없이 머리글만 다시 나오면(제목 행 신호가 안 맞음) 앞 표의 데이터가 된다 → 경고, 항목은 그대로
    rows = [["가 정책"], HEAD, [1, "주문", "a", "b"], HEAD, [1, "회원", "c", "d"]]
    grid = _wb(tmp_path, rows)
    sp = sheet_profile(_profile(), "S")
    issues = Issues()
    [t] = layout.build_tables(grid, sp, "t.xlsx", issues)
    layout.table_warnings(t, sp, issues)
    [w] = issues.by_kind("unsupported_layout")
    assert t.data_rows == [3, 4, 5] and [(l.rows.start, l.rows.end) for l in w.locations] == [(4, 4)]
    assert "표(제목 1행)" in w.message


def test_untitled_only_table_on_sheet(tmp_path):
    tables, issues = _tables(_wb(tmp_path, [HEAD, [1, "주문", "a", "b"]]), _profile(tables=UNTITLED))
    assert [(t.untitled, t.data_rows) for t in tables] == [(True, [2])] and not issues.items


def test_untitled_uses_merge_rows(tmp_path):
    rows = [TOP, BOTTOM, [1, "주문", "a", "b"], [], ["나 정책"], HEAD, [1, "회원", "c", "d"]]
    p = _profile(tables={**MERGE_HEAD, "first_without_title": True},
                 columns={"hierarchy": [{"header_contains": "분류"}], "title": {"header_contains": "기능명"},
                          "description": {"header_contains": "설명"}})
    tables, _ = _tables(_wb(tmp_path, rows, merges=["A1:A2"]), p)
    assert [(t.untitled, t.header_rows, t.data_rows) for t in tables] == [(True, [1, 2], [3, 4]), (False, [6], [7])]
