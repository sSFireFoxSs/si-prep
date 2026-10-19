"""boundary ① row — 데이터 행을 항목 단위(RowGroup)로 묶는다.
continuation은 10b 전까지 미구현(실행 때 시트 건너뜀 + unsupported), merged_block은 이름만.
"""


import pytest

from fixtures import expected as E
from si_prep import boundary
from si_prep.config import ITEM_BOUNDARY_METHODS, load_project, load_profile, sheet_profile
from si_prep.issues import Issues
from si_prep.layout import build_table, build_tables, select_sheets
from si_prep.reader import open_workbook
from si_prep.registry import Unimplemented
from conftest import SHOP, make_profile, write_book



def _profile(**over):
    return make_profile({"hierarchy": [{"header_contains": "분류"}], "title": {"header_contains": "기능명"}}, **over)


def _table(tmp_path, rows, profile, merges=()):
    grid = open_workbook(write_book(tmp_path / "t.xlsx", rows, merges), Issues()).sheet("S")
    return build_table(grid, profile, "t.xlsx", Issues())


def _rows(groups):
    return [(g.start, g.end) for g in groups]


# ---------- 등록표 ----------

def test_registry_known_names_come_from_config():
    assert sorted(ITEM_BOUNDARY_METHODS) == ["continuation", "merged_block", "row"]
    assert boundary.REGISTRY.implemented() == ["row"]
    assert boundary.REGISTRY.unimplemented() == ["continuation", "merged_block"]   # continuation은 10b


@pytest.mark.parametrize("name", ["continuation", "merged_block"])
def test_unimplemented_methods(name):
    with pytest.raises(Unimplemented):
        boundary.REGISTRY.get(name)


# ---------- row ----------

def test_one_row_one_item(tmp_path):
    p = _profile()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], ["나", "B"]], p)
    groups = boundary.REGISTRY.get("row")(table, p, Issues())
    assert _rows(groups) == [(2, 2), (3, 3)] and [g.rep for g in groups] == [2, 3]


def test_row_with_all_own_cells_empty_is_skipped(tmp_path):
    p = _profile()
    issues = Issues()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], [None, None], ["나", "B"]], p)
    assert _rows(boundary.by_row(table, p, issues)) == [(2, 2), (4, 4)] and len(issues) == 0


def test_row_with_only_merge_restored_values_is_skipped(tmp_path):
    # 병합으로 복원된 값만 있는 행은 원문 칸이 비어 있으므로 건너뜀
    p = _profile()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], [None, None]], p, merges=["A2:A3"])
    assert _rows(boundary.by_row(table, p, Issues())) == [(2, 2)]


def test_row_with_empty_hierarchy_is_separate_item(tmp_path):
    p = _profile()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], [None, "B"]], p)
    assert _rows(boundary.by_row(table, p, Issues())) == [(2, 2), (3, 3)]


def test_value_in_column_without_header_or_role_is_not_own_cell(tmp_path):
    # 머리글도 역할도 없는 열의 값만 있는 행은 자기 칸이 빈 행(떨어진 메모 등은 9b)
    p = _profile()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], [None, None, None, "메모"]], p)
    assert _rows(boundary.by_row(table, p, Issues())) == [(2, 2)]


# ---------- 합성 프로젝트: 한 행 항목 시트가 expected.py(BEFORE_1008)와 같은 행 ----------

def test_shop_row_sheets_match_expected_rows():
    config = load_project(SHOP)
    excluded = set(E.BEFORE_1008["excluded_sheets"]) | set(E.BEFORE_1008["unsupported_sheets"])
    got = {}
    for doc in config.documents:
        profile = load_profile(config.profile_path(doc))
        for f in doc.files:
            wb = open_workbook(config.input_path / f, Issues())
            if wb is None:
                continue
            for grid in select_sheets(wb, profile, Issues()):
                sp = sheet_profile(profile, grid.name)
                if (f, grid.name) in excluded or sp.item_boundary.method != "row":
                    continue
                for table in build_tables(grid, sp, f, Issues()):   # 한 시트 여러 표면 표마다
                    got.setdefault((f, grid.name), []).extend(_rows(boundary.by_row(table, sp, Issues())))
    want = {}
    for item in E.BEFORE_1008["items"]:
        want.setdefault((item["file"], item["sheet"]), []).append(tuple(item["rows"]))
    assert got == want


def test_row_with_only_formula_without_value_is_kept(tmp_path):
    # 계산값 없는 수식 칸은 값이 None이지만 내용이 있는 칸 → 행을 버리지 않는다(formula_no_value 경고가 사라지지 않게)
    p = _profile()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], [None, "=1+1"]], p)
    assert _rows(boundary.by_row(table, p, Issues())) == [(2, 2), (3, 3)]


def test_row_with_only_spaces_is_kept(tmp_path):
    # 공백만 있는 칸은 원문 값 → 행을 버리지 않는다
    p = _profile()
    table = _table(tmp_path, [["분류", "기능명"], ["가", "A"], [None, "  "]], p)
    assert _rows(boundary.by_row(table, p, Issues())) == [(2, 2), (3, 3)]
