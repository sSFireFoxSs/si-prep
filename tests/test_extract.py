"""extract ① 항목 초안 — raw_fields·merged_fields·title·source_id·status·문서 버전·profile_source, ID 처리(ref_ids·id_pattern·duplicate_id). 이어지는 행은 10b.
"""


import pytest

from fixtures import expected as E
from si_prep import boundary, extract, hierarchy
from si_prep.config import load_project, load_profile, profile_source, sheet_profile
from si_prep.issues import Issues
from si_prep.layout import build_table, build_tables, select_sheets
from si_prep.reader import open_workbook
from si_prep.registry import Unimplemented
from si_prep.schema import DocVersion, Item
from conftest import SHOP, make_profile, write_book

PROFILES = SHOP.parent / "profiles"
FO = "가상몰_기능정의서_v1.2.xlsx"


def _profile(**over):
    return make_profile({"hierarchy": [{"header_contains": "분류"}], "title": {"header_contains": "기능명"},
                         "description": {"header_contains": "설명"}}, **{"approved": True, **over})


def _wb(tmp_path, rows, merges=(), name="t.xlsx", sheet="S", extra=None):
    return open_workbook(write_book(tmp_path / name, rows, merges, sheet=sheet, extra=extra), Issues())


def _drafts(wb, sheet, p, doc_type="fo", version=None, issues=None):
    issues = Issues() if issues is None else issues
    sp = sheet_profile(p, sheet)
    table = build_table(wb.sheet(sheet), sp, wb.file, issues)
    groups = boundary.REGISTRY.get(sp.item_boundary.method)(table, sp, issues)
    paths = hierarchy.REGISTRY.get(sp.hierarchy.method)(table, groups, sp, issues)
    return extract.make_items(table, groups, paths, doc_type, profile_source(True, p.approved),
                              version or DocVersion(), issues)


# ---------- raw_fields·merged_fields ----------

HEAD = ["분류", "기능명", "설명", "비고"]


def test_raw_fields_are_original_cells_only(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["회원", "A", "설명1", None], [None, "B", "설명2", "메모"]], merges=["A2:A3"])
    d = _drafts(wb, "S", _profile())[1]
    assert sorted(d.raw_fields) == ["B", "C", "D"]                 # 병합 복원 A3·빈칸은 없음
    assert d.raw_fields["D"].header == "비고" and d.raw_fields["D"].value == "메모"


def test_merged_fields_when_start_is_above(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["가", "A", "공유 설명", None], ["나", "B", None, None], ["다", "C", None, None]],
             merges=["C2:C4"])
    drafts = _drafts(wb, "S", _profile())
    assert drafts[0].merged_fields == {} and "C" in drafts[0].raw_fields      # 시작 칸이 항목 행 안 → raw만
    m = drafts[1].merged_fields["C"]
    assert (m.header, m.value, m.source_row) == ("설명", "공유 설명", 2)
    assert "C" not in drafts[1].raw_fields and drafts[1].status == "ok"       # 설명은 merged에서 → not_written 아님


def test_merged_fields_not_for_hierarchy_columns(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["가", "A", "x", None], [None, "B", "y", None]], merges=["A2:A3"])
    assert _drafts(wb, "S", _profile())[1].merged_fields == {}


def test_horizontal_merge_counted_once_at_start_column(tmp_path):
    wb = _wb(tmp_path, [HEAD + ["추가"], ["가", "A", "넓은 설명", None, None], ["나", "B", None, None, None]],
             merges=["C2:E3"])
    d = _drafts(wb, "S", _profile())[1]
    assert sorted(d.merged_fields) == ["C"]


def test_title_and_description_fall_back_to_merged(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["가", "묶음 이름", "x", None], ["나", None, "y", None]], merges=["B2:B3"])
    assert _drafts(wb, "S", _profile())[1].title == "묶음 이름"


def test_source_id_is_original_text(tmp_path):
    p = _profile(columns={"hierarchy": [{"header_contains": "분류"}], "id": {"header_contains": "ID"},
                          "title": {"header_contains": "기능명"}})
    wb = _wb(tmp_path, [["분류", "ID", "기능명"], ["가", " REQ-001 ", "A"], ["나", 7, "B"]])
    assert [d.source_id for d in _drafts(wb, "S", p)] == [" REQ-001 ", "7"]
    assert all(d.ref_ids == [] for d in _drafts(wb, "S", p))           # 참조 ID 열(ref_ids 역할)이 없으면 빈 목록


# ---------- ID 처리 ----------

ID_HEAD = ["분류", "ID", "참조", "기능명"]


def _id_profile(ref_pattern=r"R-\d{2}", **over):
    return _profile(columns={"hierarchy": [{"header_contains": "분류"}], "id": {"header_contains": "ID"},
                             "ref_ids": {"header_contains": "참조", "pattern": ref_pattern},
                             "title": {"header_contains": "기능명"}}, **over)


def test_ref_ids_all_matches_in_order_without_duplicates(tmp_path):
    wb = _wb(tmp_path, [ID_HEAD, ["가", "A-1", "R-02, R-01 / R-02", "x"], ["나", "A-2", None, "y"]])
    drafts = _drafts(wb, "S", _id_profile())
    assert drafts[0].ref_ids == ["R-02", "R-01"] and drafts[0].status == "ok"
    assert drafts[1].ref_ids == [] and drafts[1].status == "ok"                 # 빈 참조 칸은 해석 실패 아님
    assert (drafts[0].ref_col, drafts[0].ref_row) == ("C", 2)


def test_ref_ids_pattern_group_uses_whole_match(tmp_path):
    wb = _wb(tmp_path, [ID_HEAD, ["가", "A-1", "R-01", "x"]])
    assert _drafts(wb, "S", _id_profile(ref_pattern=r"R-(\d{2})"))[0].ref_ids == ["R-01"]


def test_ref_cell_without_any_id_is_unparsed(tmp_path):
    wb = _wb(tmp_path, [ID_HEAD, ["가", "A-1", "미정", "x"]])
    issues = Issues()
    d = _drafts(wb, "S", _id_profile(), issues=issues)[0]
    assert d.ref_ids == [] and d.status == "unparsed"
    [w] = issues.by_kind("unparsed")
    assert [(l.rows.start, l.cols) for l in w.locations] == [(2, ["C"])]


def test_id_pattern_mismatch_is_unparsed_original_kept(tmp_path):
    wb = _wb(tmp_path, [ID_HEAD, ["가", " A-1 ", None, "x"], ["나", "B-1", None, "y"], ["다", None, None, "z"]])
    issues = Issues()
    drafts = _drafts(wb, "S", _id_profile(id_pattern=r"A-\d"), issues=issues)
    assert [d.status for d in drafts] == ["ok", "unparsed", "ok"]              # 앞뒤 공백은 빼고 비교, 빈 ID 칸은 검사 안 함
    assert drafts[0].source_id == " A-1 "                                       # 원문 그대로
    [w] = issues.by_kind("unparsed")
    assert [(l.rows.start, l.cols) for l in w.locations] == [(3, ["B"])]


def test_duplicate_ids_same_doc_type_spaces_ignored_case_kept(tmp_path):
    wb = _wb(tmp_path, [ID_HEAD, ["가", "A-1", None, "x"], ["나", " A-1", None, "y"], ["다", "a-1", None, "z"]])
    fo = _drafts(wb, "S", _id_profile())
    other = _drafts(wb, "S", _id_profile(), doc_type="bo")[:1]                 # 다른 문서 종류의 같은 ID는 중복 아님
    issues = Issues()
    extract.check_duplicate_ids(fo + other, issues)
    [w] = issues.items
    assert w.kind == "duplicate_id"
    assert [(l.sheet, l.rows.start, l.cols) for l in w.locations] == [("S", 2, ["B"]), ("S", 3, ["B"])]


# ---------- status ----------

def test_not_written_only_with_description_role(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["가", "A", None, None]])
    assert _drafts(wb, "S", _profile())[0].status == "not_written"
    p = _profile(columns={"hierarchy": [{"header_contains": "분류"}], "title": {"header_contains": "기능명"}})
    assert _drafts(wb, "S", p)[0].status == "ok"                       # 설명 역할이 없으면 판단 안 함


def test_ambiguous_with_empty_or_filled_steps(tmp_path):
    p = _profile(columns={"hierarchy": [{"header_pattern": r"^분류\d$", "all": True}],
                          "title": {"header_contains": "기능명"}, "description": {"header_contains": "설명"}})
    wb = _wb(tmp_path, [["분류1", "분류2", "분류3", "기능명", "설명"], ["가", None, "다", "A", None]])
    d = _drafts(wb, "S", p)[0]
    assert d.status == "ambiguous"                                     # ambiguous > not_written
    assert d.category_path_text == "가 › (빈칸) › 다" and [x.level for x in d.category_path] == [1, 2, 3]


def test_error_value_is_unparsed_with_warning(tmp_path):
    p = _profile(columns={"hierarchy": [{"header_pattern": r"^분류\d$", "all": True}],
                          "title": {"header_contains": "기능명"}, "description": {"header_contains": "설명"}})
    wb = _wb(tmp_path, [["분류1", "분류2", "분류3", "기능명", "설명"], ["가", None, "다", "#REF!", "x"]])
    issues = Issues()
    d = _drafts(wb, "S", p, issues=issues)[0]
    assert d.status == "unparsed"                                      # unparsed > ambiguous
    [w] = issues.by_kind("unparsed")
    assert [(l.rows.start, l.cols) for l in w.locations] == [(2, ["D"])] and "#REF!" in w.message


def test_formula_without_value_warns(generated_dir):
    profile = load_profile(PROFILES / "variation.yaml")
    wb = open_workbook(generated_dir / "가상몰_변형.xlsx", Issues())
    issues = Issues()
    drafts = _drafts(wb, "숨김행수식", profile, "variation", issues=issues)
    [w] = issues.by_kind("formula_no_value")
    assert [(l.sheet, l.rows.start, l.cols) for l in w.locations] == [("숨김행수식", 5, ["G"])]
    assert "G" not in drafts[-1].raw_fields


def test_profile_source(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["가", "A", "x", None]])
    assert _drafts(wb, "S", _profile())[0].profile_source == "approved"
    assert _drafts(wb, "S", _profile(approved=False))[0].profile_source == "auto"


@pytest.mark.parametrize("project,profile,expected", [
    (True, True, "approved"), (False, True, "auto"), (True, False, "auto"), (False, False, "auto")])
def test_profile_source_needs_project_and_profile_approved(project, profile, expected):
    # 시험 실행(승인 전 설정) 결과가 승인된 결과처럼 보이지 않게
    assert profile_source(project, profile) == expected


def test_draft_becomes_valid_item(tmp_path):
    wb = _wb(tmp_path, [HEAD, ["가", "A", "x", "y"]])
    item = _drafts(wb, "S", _profile())[0].to_item("IT-000001")
    assert isinstance(item, Item) and item.doc_file == "t.xlsx"
    assert [(l.sheet, l.rows.start, l.rows.end, l.cols) for l in item.locations] == [("S", 2, 2, None)]


# ---------- 문서 버전 ----------

def test_doc_version_cover_and_filename(generated_dir):
    wb = open_workbook(generated_dir / FO, Issues())
    issues = Issues()
    v = extract.read_doc_version(wb, load_profile(PROFILES / "fo.yaml"), issues)
    assert (v.cover, v.filename) == ("v1.3", "1.2")
    [w] = issues.items
    assert w.kind == "version_mismatch" and (w.file, w.sheet) == (FO, "표지")
    assert [(l.sheet, l.rows.start, l.cols) for l in w.locations] == [("표지", 5, ["C"])]


def test_doc_version_compares_digits_only(tmp_path):
    def cover(wb):
        ws = wb.create_sheet("표지", 0)
        ws["B5"], ws["C5"] = "버전", "v1.2"
    wb = _wb(tmp_path, [HEAD], name="문서_v1.2.xlsx", extra=cover)
    p = _profile(version={"cover_sheet": "표지", "label_pattern": "버전", "filename_pattern": r"_v(\d+(?:\.\d+)*)"})
    issues = Issues()
    assert extract.read_doc_version(wb, p, issues) == DocVersion(cover="v1.2", filename="1.2")
    assert len(issues) == 0                                            # 「v1.2」 = 「1.2」


def test_doc_version_none_without_settings(tmp_path):
    wb = _wb(tmp_path, [HEAD])
    assert extract.read_doc_version(wb, _profile(), Issues()) == DocVersion()


# ---------- 합성 프로젝트: BEFORE_1008 항목 초안과 같음 ----------

def test_shop_drafts_match_before_expected():
    config = load_project(SHOP)
    excluded = set(E.BEFORE_1008["excluded_sheets"])
    got, raw = [], {}
    for doc in config.documents:
        profile = load_profile(config.profile_path(doc))
        for f in doc.files:
            wb = open_workbook(config.input_path / f, Issues())
            if wb is None:
                continue
            version = extract.read_doc_version(wb, profile, Issues())
            for grid in select_sheets(wb, profile, Issues()):
                sp = sheet_profile(profile, grid.name)
                if (f, grid.name) in excluded:
                    continue
                try:
                    split = boundary.REGISTRY.get(sp.item_boundary.method)
                    make = hierarchy.REGISTRY.get(sp.hierarchy.method)
                except Unimplemented:
                    continue
                issues = Issues()
                for table in build_tables(grid, sp, f, issues):   # 한 시트 여러 표면 표마다
                    groups = split(table, sp, issues)
                    for d in extract.make_items(table, groups, make(table, groups, sp, issues), doc.doc_type,
                                                profile_source(config.approved, profile.approved), version, issues):
                        got.append({"file": d.doc_file, "sheet": d.sheet, "rows": d.rows, "path_text": d.category_path_text,
                                    "status": d.status, "title": d.title, "source_id": d.source_id, "ref_ids": d.ref_ids,
                                    "merged": {c: m.source_row for c, m in d.merged_fields.items()}})
                        raw[(d.doc_file, d.sheet, d.rows[0])] = sorted(d.raw_fields)
    key = lambda i: (i["file"], i["sheet"], i["rows"])
    assert sorted(got, key=key) == sorted(E.BEFORE_1008["items"], key=key)
    want_raw = {(i["file"], i["sheet"], i["rows"][0]): sorted(i["raw"]) for i in E.FINAL_ITEMS
                if (i["file"], i["sheet"], i["rows"][0]) in raw}
    assert raw == want_raw


def test_description_row_points_to_original_cell(tmp_path):
    # 설명을 merged에서 받으면 원문 칸(병합 시작 행), raw면 항목 행 — 내용 비교 경고 위치용
    wb = _wb(tmp_path, [HEAD, ["가", "A", "공유 설명", None], ["나", "B", None, None]], merges=["C2:C3"])
    drafts = _drafts(wb, "S", _profile())
    assert [(d.description_col, d.description_row) for d in drafts] == [("C", 2), ("C", 2)]


# ---------- 16c: 선언 시트의 채운 단계(form_filled)는 추정이 아님 ----------

def test_form_filled_item_is_ok_and_raw_fields_unchanged(tmp_path):
    p = _profile(columns={"hierarchy": [{"header_pattern": r"^분류\d$", "all": True}], "title": {"header_contains": "기능명"}},
                 hierarchy={"method": "columns", "fill_down": True, "blank_means_above": True})
    wb = _wb(tmp_path, [["분류1", "분류2", "기능명"], ["가", "나", "A"], [None, "다", "B"]])
    d = _drafts(wb, "S", p)[1]
    assert d.status == "ok" and [x.basis for x in d.category_path] == ["form_filled", "cell"]
    assert sorted(d.raw_fields) == ["B", "C"]                         # 채운 값은 raw_fields에 없음


# ---------- 병합된 참조 칸 unparsed는 항목마다 자기 행 위치로 1건 ----------

def test_merged_ref_cell_unparsed_once_per_item_at_own_row(tmp_path):
    # 참조 칸 C2:C3 병합(ID 없는 글자) → 두 항목 모두 unparsed. 경고는 항목마다 1건, 위치는 그 항목 행의 칸
    wb = _wb(tmp_path, [ID_HEAD, ["가", "A-1", "미정", "x"], ["나", "A-2", None, "y"]], merges=["C2:C3"])
    issues = Issues()
    drafts = _drafts(wb, "S", _id_profile(), issues=issues)
    assert [d.status for d in drafts] == ["unparsed", "unparsed"]
    ws = issues.by_kind("unparsed")
    assert [[(l.rows.start, l.rows.end, l.cols) for l in w.locations] for w in ws] == [[(2, 2, ["C"])], [(3, 3, ["C"])]]
    assert "C3" in ws[1].message and "C2" in ws[1].message                  # 병합 시작 칸(값이 있는 칸)도 알린다
    # 실행의 경고 번호 매기기에서 항목마다 자기 경고 하나
    from si_prep import run
    ids = {id(d): f"IT-{n:06d}" for n, d in enumerate(drafts, start=1)}
    out = run._number_warnings(issues, [(d, None) for d in drafts], ids, {wb.file: 0}, {(wb.file, "S"): 0})
    assert [w.item_ids for w in out if w.kind == "unparsed"] == [["IT-000001"], ["IT-000002"]]


# ---------- B2 줄임 표기 ID 펼치기: columns.ref_ids.expand_short ----------

def _short_profile(pattern=r"[RS]-\d{4}", expand=True):
    ref = {"header_contains": "참조", "pattern": pattern}
    if expand is not None:
        ref["expand_short"] = expand
    return _profile(columns={"hierarchy": [{"header_contains": "분류"}], "id": {"header_contains": "ID"},
                             "ref_ids": ref, "title": {"header_contains": "기능명"}})


def _short(tmp_path, text, **kw):
    wb = _wb(tmp_path, [ID_HEAD, ["가", "A-1", text, "x"]])
    issues = Issues()
    [d] = _drafts(wb, "S", _short_profile(**kw), issues=issues)
    return d, issues


def test_expand_short_default_off_counts_leftover(tmp_path):
    d, issues = _short(tmp_path, "R-0101, 0103", expand=None)
    assert d.ref_ids == ["R-0101"] and d.expanded_refs == [] and d.short_left == 1
    assert d.status == "ok" and not issues.items


def test_expand_short_on_keeps_ref_ids_and_raw(tmp_path):
    d, issues = _short(tmp_path, "R-0101, 0103")
    assert d.ref_ids == ["R-0101"]                                   # 원문 글자 그대로
    assert d.raw_fields["C"].value == "R-0101, 0103"
    assert d.expanded_refs == [("R-0103", "0103", "R-0101")]          # (펼친 ID, 조각, 앞 ID) — 내부용
    assert d.short_left == 0 and d.status == "ok" and not issues.items


def test_expand_short_chain_and_groups(tmp_path):
    d, _ = _short(tmp_path, "R-0101, 0103 / 0105 · S-0201,0202 R-0101")
    assert d.ref_ids == ["R-0101", "S-0201"]
    assert [e[0] for e in d.expanded_refs] == ["R-0103", "R-0105", "S-0202"]


def test_expand_short_stops_at_other_words(tmp_path):
    # 조각은 앞 ID에서 나눔 기호(쉼표·빗금·가운뎃점·공백)로만 이어져야 한다. 다른 말이 끼면 끝
    d, issues = _short(tmp_path, "R-0101 참고 0103")
    assert d.expanded_refs == [] and d.short_left == 0 and not issues.items


@pytest.mark.parametrize("text,left", [
    ("R-0101, 3", 1),               # 길이 다른 조각
    ("R-0101~0105", 1),             # 범위 표기
    ("R-0101, 0103~0105", 1),       # 조각 뒤 범위
])
def test_expand_short_not_expanded_warns(tmp_path, text, left):
    d, issues = _short(tmp_path, text)
    assert d.expanded_refs == [] and d.short_left == left and d.status == "unparsed"
    [w] = issues.by_kind("unparsed")                                 # 항목당 1건
    assert "펼치지 못했" in w.message and [(l.rows.start, l.cols) for l in w.locations] == [(2, ["C"])]


def test_expand_short_result_must_match_pattern(tmp_path):
    d, issues = _short(tmp_path, "R-0101, 0299", pattern=r"R-01\d{2}")
    assert d.expanded_refs == [] and d.short_left == 1
    [w] = issues.by_kind("unparsed")
    assert "pattern" in w.message


def test_expand_short_config_strict_bool():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        _short_profile(expand="yes")
    assert _short_profile(expand=None).columns.ref_ids.expand_short is False


def test_expand_short_base_without_trailing_digits_reason(tmp_path):
    # 리뷰 지적: 앞 ID 끝이 숫자가 아니면 이유는 「끝이 숫자가 아님」(길이 다름이 아니라)
    d, issues = _short(tmp_path, "R-0101A, 0103", pattern=r"R-\d{4}A?")
    [w] = issues.by_kind("unparsed")
    assert "끝이 숫자가 아님" in w.message and d.expanded_refs == []
