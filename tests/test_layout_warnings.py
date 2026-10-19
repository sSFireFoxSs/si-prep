"""표 배치 경고 — 읽는 방식은 그대로, 경고만 낸다.

R1 머리글 없는 열의 값 덩어리(어느 항목에도 안 들어감) → unsupported_layout 덩어리마다 1건(위치 = 그 덩어리)
R2 tables 설정 없는 시트에서 데이터 행이 머리글 행과 글자가 같음(반복 머리글) → unsupported_layout 1건(위치 = 그 행들)
R3 숨김 열에 값 → hidden_content 열마다 1건
"""



from fixtures import expected as E
from si_prep import layout, run
from si_prep.config import sheet_profile
from si_prep.issues import Issues
from si_prep.reader import open_workbook
from conftest import SHOP, make_profile, write_book

HEAD = ["분류1", "기능명", "설명"]


def _profile(**over):
    return make_profile({"hierarchy": [{"header_contains": "분류1"}], "title": {"header_contains": "기능명"},
                         "description": {"header_contains": "설명"}}, **over)


def _issues(tmp_path, rows, p=None, hidden_cols=(), merges=()):
    path = write_book(tmp_path / "w.xlsx", rows, merges, hidden_cols=hidden_cols)
    issues = Issues()
    p = p or _profile()
    sp = sheet_profile(p, "S")
    tables = layout.build_tables(open_workbook(path, Issues()).sheet("S"), sp, "w.xlsx", issues)
    for t in tables:
        layout.table_warnings(t, sp, issues)          # 실행(run)이 표마다 부른다
    return tables, issues


def _locs(w):
    return [(l.rows.start, l.rows.end, l.cols) for l in w.locations]


# ---------- R1 떨어진 값 덩어리 ----------

def test_headerless_value_blocks_warn_once_each(tmp_path):
    rows = [HEAD, ["가", "a", "b", None, "메모1"], ["나", "c", "d", None, "메모2"], ["다", "e", "f"],
            ["라", "g", "h", None, None, "x", "y"]]
    tables, issues = _issues(tmp_path, rows)
    assert len(tables[0].data_rows) == 4                      # 표는 그대로 읽음
    ws = issues.by_kind("unsupported_layout")
    assert [_locs(w) for w in ws] == [[(2, 3, ["E"])], [(5, 5, ["F", "G"])]]
    assert all("머리글 없는 열" in w.message for w in ws)


def test_header_column_values_are_not_blocks(tmp_path):
    # 머리글 있는 열(역할 없는 열 포함)의 값은 항목 raw_fields에 들어가므로 덩어리 아님
    tables, issues = _issues(tmp_path, [HEAD + ["비고"], ["가", "a", "b", "메모"]])
    assert not issues.by_kind("unsupported_layout")


def test_shop_blocks_match_final_warnings():
    # FINAL에 이미 적힌 오른쪽메모·대각선표·왼쪽덩어리 unsupported_layout 위치와 같음
    # 목록으로 비교(같은 경고가 두 번 나와도 잡히게, 리뷰 2026-10-13)
    got = [(w.sheet, tuple((l.sheet, l.rows.start, l.rows.end, "".join(l.cols or [])) for l in w.locations))
           for w in run.build(SHOP).warnings if w.kind == "unsupported_layout" and w.sheet in ("오른쪽메모", "대각선표", "왼쪽덩어리")]
    want = [(w["sheet"], tuple((s, a, b, "".join(c or [])) for s, a, b, c in w["locations"]))
            for w in E.FINAL_WARNINGS if w["kind"] == "unsupported_layout" and w["sheet"] in ("오른쪽메모", "대각선표", "왼쪽덩어리")]
    assert got == want and len(got) == 3


# ---------- R2 반복 머리글 ----------

def test_repeated_header_row_warns_items_kept(tmp_path):
    rows = [HEAD, ["가", "a", "b"], [], HEAD, ["나", "c", "d"], HEAD]
    tables, issues = _issues(tmp_path, rows)
    [w] = [w for w in issues.by_kind("unsupported_layout") if "반복 머리글" in w.message]
    assert _locs(w) == [(4, 4, None), (6, 6, None)]
    assert 4 in tables[0].data_rows                          # 항목은 그대로 만든다(읽는 방식 그대로)


def test_repeated_header_not_checked_with_tables(tmp_path):
    p = _profile(tables={"title_row": {"only_columns": ["A"]}, "header_row": {"col": "A", "pattern": "^분류1$"}})
    rows = [["가 정책"], HEAD, ["가", "a", "b"], [], ["나 정책"], HEAD, ["나", "c", "d"]]
    _, issues = _issues(tmp_path, rows, p)
    assert not [w for w in issues if "반복 머리글" in w.message]


def test_partial_header_like_row_not_repeated(tmp_path):
    # 칸 하나만 머리글 글자와 같으면 반복 머리글 아님
    _, issues = _issues(tmp_path, [HEAD, ["분류1", "a", "b"]])
    assert not [w for w in issues if "반복 머리글" in w.message]


# ---------- R3 숨김 열 ----------

def test_hidden_column_with_values_warns_per_column(tmp_path):
    rows = [HEAD + ["숨김1", "숨김2", "빈숨김"], ["가", "a", "b", "x", "y"], ["나", "c", "d", None, "z"]]
    tables, issues = _issues(tmp_path, rows, hidden_cols=("D", "E", "F"))
    ws = issues.by_kind("hidden_content")
    assert [_locs(w) for w in ws] == [[(2, 2, ["D"])], [(2, 3, ["E"])]]        # 값 없는 숨김 열 F는 경고 없음
    assert all("숨김 열" in w.message for w in ws)
    assert "D" in tables[0].headers                                           # 읽는 건 그대로


# ---------- 리뷰 지적 ----------

def test_hidden_headerless_column_only_hidden_content(tmp_path):
    # 머리글 없는 숨김 열의 값은 hidden_content(R3) 한 번만 — 떨어진 덩어리(R1)로 또 내지 않음
    _, issues = _issues(tmp_path, [HEAD, ["가", "a", "b", None, "x"]], hidden_cols=("E",))
    assert [k.kind for k in issues] == ["hidden_content"]


def test_merge_from_headerless_into_header_column_not_block(tmp_path):
    # 머리글 없는 D에서 시작한 가로 병합(D2:E2)이 머리글 있는 E까지 덮으면 값은 E의 merged_fields로 항목에 들어감 → 덩어리 아님
    rows = [HEAD + [None, "비고"], ["가", "a", "b", "메모"]]
    _, issues = _issues(tmp_path, rows, merges=["D2:E2"])
    assert not issues.by_kind("unsupported_layout")


def test_repeated_header_uses_merged_header_text(tmp_path):
    # 2줄 머리글에서 위 줄 세로 병합(A1:A2, B1:B2) + C2만 원문: 데이터 C열이 C2 글자와 같아도 A·B가 다르면 반복 머리글 아님
    rows = [["분류1", "기능명", "묶음"], [None, None, "설명"], ["가", "a", "설명"]]
    p = _profile(header_rows=[1, 2], data_start_row=3)
    _, issues = _issues(tmp_path, rows, p, merges=["A1:A2", "B1:B2"])
    assert not [w for w in issues if "반복 머리글" in w.message]
    # 머리글 전부(병합 복원 글자 포함)와 같은 데이터 행은 반복 머리글
    _, issues = _issues(tmp_path, rows + [["분류1", "기능명", "설명"]], p, merges=["A1:A2", "B1:B2"])
    assert [w for w in issues if "반복 머리글" in w.message]
