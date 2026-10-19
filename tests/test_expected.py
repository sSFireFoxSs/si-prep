"""항목 2-3: 기대값(expected.py) 두 벌이 생성된 엑셀·설계 문서와 맞는지 확인한다.

si_prep 코드는 쓰지 않는다. 기대값이 가리키는 칸을 생성된 엑셀에서 직접 읽어 대조한다.
"""

import re
from fnmatch import fnmatchcase
from pathlib import Path

import openpyxl
import pytest
import yaml

from fixtures import expected as E
from si_prep.schema import path_key, path_starts_with

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(__file__).parent / "fixtures" / "configs" / "shop"
SEP = " › "
EMPTY_STEP = "(빈칸)"
METHOD_GRADE = {"id_ref": "explicit", "path_exact": "structural", "path_normalized": "structural",
                "glossary": "structural", "name_similarity": "inferred"}


@pytest.fixture(scope="module")
def project():
    return yaml.safe_load((CONFIG_DIR / "project.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def books(generated_dir):
    """생성된 xlsx를 모두 연다. 일부러 옛 형식으로 만든 가짜 확장자 파일만 뺀다(열기 실패는 테스트 실패)."""
    out = {}
    for path in sorted(generated_dir.glob("*.xlsx")):
        if path.name == E.FAKE:
            continue
        out[path.name] = openpyxl.load_workbook(path, data_only=True)  # 수식은 저장된 계산값
    return out


@pytest.fixture(scope="module")
def formula_books(generated_dir):
    """수식 칸 확인용(계산값이 아니라 수식 자체를 읽음)"""
    return {p.name: openpyxl.load_workbook(p) for p in sorted(generated_dir.glob("*.xlsx")) if p.name != E.FAKE}


@pytest.fixture(scope="module")
def glossary():
    data = yaml.safe_load((CONFIG_DIR / "glossary.yaml").read_text(encoding="utf-8"))
    return {word: group[0] for group in data["groups"] for word in group}  # 단어 → 대표어


def _order(project):
    """파일 이름 → (문서 순서, 파일 순서), 파일 이름 → doc_type"""
    order, doc_of = {}, {}
    for d_i, doc in enumerate(project["documents"]):
        for f_i, name in enumerate(doc["files"]):
            order[name] = (d_i, f_i)
            doc_of[name] = doc["doc_type"]
    return order, doc_of


def _load_profiles():
    """파일 이름 → 프로필(dict). project.yaml documents에서 읽는다."""
    project = yaml.safe_load((CONFIG_DIR / "project.yaml").read_text(encoding="utf-8"))
    out = {}
    for doc in project["documents"]:
        profile = yaml.safe_load((CONFIG_DIR / doc["profile"]).read_text(encoding="utf-8"))
        for name in doc["files"]:
            out[name] = profile
    return out


PROFILES = _load_profiles()


def _sheet_matches(sheet, names):
    """시트 이름·`*`·`?` 패턴 목록(대소문자 구분)"""
    return any(fnmatchcase(sheet, n) for n in names)


def _profile_value(file, sheet, key):
    """프로필 최상위 키 값. 시트별 덮어쓰기(sheet_overrides)가 있으면 그 값 (최상위 키 단위)"""
    profile = PROFILES[file]
    value = profile.get(key)
    for over in profile.get("sheet_overrides", []):
        if key in over and _sheet_matches(sheet, over["sheets"]):
            value = over[key]
    return value


def _header_rows(file, sheet):
    return _profile_value(file, sheet, "header_rows")


def _title_row(ws, value, start):
    """표 제목 행: start 위에서 원문 값(병합 시작 칸만)이 value 하나뿐인 가장 가까운 행"""
    for r in range(start - 1, 0, -1):
        vals = [ws.cell(r, c).value for c in range(1, ws.max_column + 1)
                if ws.cell(r, c).value is not None and _merge_top(ws, r, c) in (None, (r, c))]
        if vals == [value]:
            return r
    return None


def _item_header_rows(i, ws):
    """그 항목 표의 머리글 행: tables 설정 시트면 제목 행 + offset부터 header_rows 줄 수만큼, 아니면 프로필 header_rows"""
    rows = _header_rows(i["file"], i["sheet"])
    tables = _profile_value(i["file"], i["sheet"], "tables")
    title = next((v for v, b, _ in i["path"] if b == "table_title"), None)
    if not tables or title is None:
        return rows
    first = _title_row(ws, title, i["rows"][0]) + tables["header_row"].get("offset", 1)
    return list(range(first, first + len(rows)))


def _merge_top(ws, row, col):
    """(row, col)이 병합 범위 안이면 시작 칸 (row, col), 아니면 None"""
    for rg in ws.merged_cells.ranges:
        if rg.min_row <= row <= rg.max_row and rg.min_col <= col <= rg.max_col:
            return rg.min_row, rg.min_col
    return None


def _header_cols(ws, header_rows):
    cols = set()
    for r in header_rows:
        for c in range(1, ws.max_column + 1):
            if ws.cell(r, c).value is not None:
                cols.add(c)
    for rg in ws.merged_cells.ranges:
        if rg.min_row in header_rows:
            cols |= set(range(rg.min_col, rg.max_col + 1))
    return cols


def _col(letter):
    return openpyxl.utils.column_index_from_string(letter)


def _path_text(path):
    parts = [EMPTY_STEP if v is None else v for v, _, _ in path]
    out = []
    for p in parts:
        if not out or out[-1] != p or p == EMPTY_STEP:
            out.append(p)
    return SEP.join(out)


# ---------- 항목 ----------

def test_final_item_ids_and_order(project, books):
    order, _ = _order(project)
    items = E.FINAL["items"]
    assert [i["item_id"] for i in items] == [f"IT-{n:06d}" for n in range(1, len(items) + 1)]
    keys = [(*order[i["file"]], books[i["file"]].sheetnames.index(i["sheet"]), i["rows"][0]) for i in items]
    assert keys == sorted(keys)


def test_final_item_doc_types(project):
    _, doc_of = _order(project)
    for i in E.FINAL["items"]:
        assert i["doc_type"] == doc_of[i["file"]], i["item_id"]


def test_final_path_text_matches_parts():
    for i in E.FINAL["items"]:
        assert i["path_text"] == _path_text(i["path"]), i["item_id"]


def test_final_items_match_generated_cells(books):
    for i in E.FINAL["items"]:
        ws = books[i["file"]][i["sheet"]]
        start, end = i["rows"]
        rows = range(start, end + 1)
        for value, basis, col in i["path"]:
            where = f'{i["item_id"]} {value} {basis}'
            c = _col(col) if col else None
            if basis == "cell":
                assert any(ws.cell(r, c).value == value for r in rows), where
            elif basis == "merge_restored":
                top = _merge_top(ws, start, c)
                assert ws.cell(start, c).value is None and top and top[0] < start, where
                assert ws.cell(*top).value == value, where
            elif basis == "filled_down":
                assert ws.cell(start, c).value is None and _merge_top(ws, start, c) is None, where
                above = [ws.cell(r, c).value for r in range(1, start) if ws.cell(r, c).value is not None]
                assert above and above[-1] == value, where
            elif basis == "empty":
                assert value is None, where
                if c:
                    assert ws.cell(start, c).value is None, where
            elif basis == "sheet_name":
                assert value in ws.title.split(" - "), where
            elif basis == "split_cell":
                assert value in str(ws.cell(start, c).value).split(" > "), where
            elif basis == "numbering":
                assert any(ws.cell(r, c).value == value for r in range(2, ws.max_row + 1)), where
            elif basis == "table_title":   # 위쪽 제목 행(원문 값이 이것 하나뿐)
                assert c is None and _title_row(ws, value, start) is not None, where
            else:
                pytest.fail(f"모르는 basis: {where}")

        header = _header_cols(ws, _item_header_rows(i, ws))
        own = {c for c in header for r in rows
               if ws.cell(r, c).value is not None and (_merge_top(ws, r, c) in (None, (r, c)))}
        assert {_col(x) for x in i["raw"]} == own, i["item_id"]

        for letter, src in i["merged"].items():
            c = _col(letter)
            assert src < start and _merge_top(ws, start, c) == (src, c), i["item_id"]
            assert ws.cell(src, c).value is not None and letter not in i["raw"], i["item_id"]

        if i["title"] is not None:
            joined = {"\n".join(str(ws.cell(r, c).value) for r in rows if ws.cell(r, c).value is not None)
                      for c in header}
            from_merge = {ws.cell(src, _col(l)).value for l, src in i["merged"].items()}
            assert i["title"] in joined | from_merge, i["item_id"]
        if i["source_id"] is not None:
            assert any(ws.cell(r, c).value == i["source_id"] for r in rows for c in header), i["item_id"]
        for ref in i["ref_ids"]:
            assert any(ref in str(ws.cell(r, c).value) for r in rows for c in header), i["item_id"]


# ---------- 연결 ----------

def _norm_key(path_text):
    """비교 열쇠 — schema.path_key와 같은 규칙(같은 함수 사용)"""
    return path_key(path_text.split(SEP))


def _steps(item):
    """기대값 항목의 경로 단계 값 (빈 단계는 None)"""
    return [v for v, _, _ in item["path"]]


def _sheets_ok(rule, side, item):
    """규칙의 sheets 칸(overview/detail/이름·패턴 목록/None)에 항목 시트가 드는지. overview는 프로필 overview_sheets"""
    sel = (rule.get("sheets") or [None, None])[side]
    overview = _sheet_matches(item["sheet"], PROFILES[item["file"]].get("overview_sheets") or [])
    if sel is None:
        return True
    if sel == "overview":
        return overview
    if sel == "detail":
        return not overview
    return _sheet_matches(item["sheet"], sel)


def _sheet_root(item):
    """시트 이름을 프로필 root_separators로 나눈 경로 (sheet_to_path의 찾는 쪽 단서)"""
    parts = [item["sheet"]]
    for sep in PROFILES[item["file"]].get("root_separators") or []:
        parts = [q for p in parts for q in p.split(sep)]
    return SEP.join(parts)


def test_final_links(project, glossary):
    items = {i["item_id"]: i for i in E.FINAL["items"]}
    rules = {r["id"]: r for r in project["link_rules"]}
    links = E.FINAL["links"]
    assert [l["link_id"] for l in links] == [f"LK-{n:06d}" for n in range(1, len(links) + 1)]
    rule_order = [r["id"] for r in project["link_rules"]]
    assert [rule_order.index(l["rule_id"]) for l in links] == sorted(rule_order.index(l["rule_id"]) for l in links)
    for l in links:
        lid, rule = l["link_id"], rules[l["rule_id"]]
        assert METHOD_GRADE[l["method"]] == l["grade"], lid
        if "item_a" in l:
            a, b = items[l["item_a"]], items[l["item_b"]]
            assert l["item_a"] < l["item_b"], lid
            # 규칙의 두 문서 종류·sheets 칸과 맞는 짝인지 (docs 순서는 의미 없음 → 양쪽 배치 중 하나)
            d0, d1 = rule["docs"]
            assert any(x["doc_type"] == d0 and y["doc_type"] == d1 and _sheets_ok(rule, 0, x) and _sheets_ok(rule, 1, y)
                       for x, y in ((a, b), (b, a))), lid
            assert "ambiguous" not in (a["status"], b["status"]) or l["method"] == "id_ref", lid
            if l["method"] == "path_exact":
                assert a["path_text"] == b["path_text"], lid
            elif l["method"] == "path_normalized":
                assert a["path_text"] != b["path_text"] and _norm_key(a["path_text"]) == _norm_key(b["path_text"]), lid
            elif l["method"] == "id_ref":
                assert a["source_id"] in b["ref_ids"] or b["source_id"] in a["ref_ids"], lid
            else:
                pytest.fail(f"항목↔항목에 나올 수 없는 method: {lid}")
        else:
            item = items[l["item"]]
            group_type, group_text = l["group"]
            assert {item["doc_type"], group_type} == set(rule["docs"]), lid
            assert _sheets_ok(rule, rule["docs"].index(item["doc_type"]), item), lid
            assert item["status"] != "ambiguous", lid
            # 묶음은 대상 쪽 문서 종류에 실제로 있는 경로의 단계 앞부분
            assert any(i["doc_type"] == group_type and path_starts_with(_steps(i), group_text)
                       for i in items.values()), lid
            if l["method"] == "path_normalized":  # sheet_to_path: 찾는 쪽 시트 이름(나눈 경로) = 묶음
                assert _norm_key(_sheet_root(item)) == _norm_key(group_text), lid
                assert path_starts_with(_steps(item), _sheet_root(item)), lid
            elif l["method"] == "glossary":       # 용어 사전 대표어로 바꾸면 묶음과 같고, 실제로 바꾼 단어가 있음
                swapped = SEP.join(glossary.get(p, p) for p in item["path_text"].split(SEP))
                assert swapped != item["path_text"] and _norm_key(swapped)[:len(_norm_key(group_text))] == _norm_key(group_text), lid
            else:
                pytest.fail(f"항목↔묶음에 나올 수 없는 method: {lid}")


# ---------- 경고 ----------

def _warning_key(w, order, books):
    d_i, f_i = order[w["file"]]
    if w["sheet"] is None:
        return (d_i, f_i, -1, 0, w["kind"], "")
    sheet_i = books[w["file"]].sheetnames.index(w["sheet"])
    if not w["locations"]:
        return (d_i, f_i, sheet_i, 0, w["kind"], "")
    first = w["locations"][0]
    return (d_i, f_i, sheet_i, first[1], w["kind"], (first[3] or [""])[0])


def test_final_warning_ids_follow_sort_rule(project, books):
    order, _ = _order(project)
    warnings = E.FINAL["warnings"]
    assert [w["warning_id"] for w in warnings] == [f"WN-{n:06d}" for n in range(1, len(warnings) + 1)]
    keys = [_warning_key(w, order, books) for w in warnings]
    assert keys == sorted(keys), "WN 번호가 정렬 규칙과 다름"


# 경고 위치의 칸에 무엇이 있어야 하는지 (kind별)
FILLED_KINDS = {"version_mismatch", "content_mismatch", "link_unconfirmed", "ref_unresolved",
                "unparsed", "duplicate_id", "header_not_found"}   # 가리킨 칸이 모두 값 있음
EMPTY_KINDS = {"merge_unrestored"}                                 # 가리킨 칸이 모두 빈칸(병합 아님)
ANY_FILLED_KINDS = {"unsupported_layout"}                          # 범위 안에 값 있는 칸이 하나 이상


def test_final_warning_cells_match_generated(books, formula_books):
    items = {i["item_id"]: i for i in E.FINAL["items"]}
    for w in E.FINAL["warnings"]:
        wid, kind = w["warning_id"], w["kind"]
        assert set(w["item_ids"]) <= set(items), wid
        if not w["locations"]:
            continue
        wb = books[w["file"]]
        values = []
        for sheet, start, end, cols in w["locations"]:
            ws = wb[sheet]
            assert 1 <= start <= end <= max(ws.max_row, 1), wid
            cells = [(r, _col(c)) for r in range(start, end + 1) for c in (cols or [])]
            got = [ws.cell(r, c).value for r, c in cells]
            values += got
            if kind in FILLED_KINDS:
                assert all(v is not None for v in got), wid
            elif kind in EMPTY_KINDS:
                assert got and all(v is None for v in got), wid
                assert all(_merge_top(ws, r, c) is None for r, c in cells), wid
            elif kind in ANY_FILLED_KINDS:
                assert any(v is not None for v in got), wid
            elif kind == "hidden_content":
                assert all(ws.row_dimensions[r].hidden for r in range(start, end + 1)), wid
            elif kind == "formula_no_value":
                fws = formula_books[w["file"]][sheet]
                assert all(fws.cell(r, c).data_type == "f" and v is None for (r, c), v in zip(cells, got)), wid
            else:
                pytest.fail(f"칸 대조 규칙이 없는 kind: {wid} {kind}")
        if kind == "duplicate_id":
            assert len(set(values)) == 1, wid             # 같은 ID가 두 번
        if kind == "content_mismatch":
            assert len(set(values)) == len(values), wid   # 양쪽 설명이 다름
        # 관련 항목의 행이 경고 위치와 겹치는지
        for iid in w["item_ids"]:
            it = items[iid]
            assert any(it["sheet"] == s and not (it["rows"][1] < a or b < it["rows"][0])
                       for s, a, b, _ in w["locations"]), wid


# ---------- 설계 문서 8.1 시나리오 표의 상황이 전부 들어 있는지 ----------

def _architecture_8_1_rows():
    text = (ROOT / "docs" / "DESIGN.md").read_text(encoding="utf-8")
    block = text.split("### 8.1 합성 시나리오")[1].split("**fill_down 케이스**")[0]
    rows = [l for l in block.splitlines() if l.startswith("| ")]
    return rows[2:]  # 머리 줄·구분 줄 제외


def test_scenarios_cover_architecture_8_1():
    assert len(E.SCENARIOS) == len(_architecture_8_1_rows())
    places = {(i["file"], i["sheet"]) for i in E.FINAL["items"]} | {(w["file"], w["sheet"]) for w in E.FINAL["warnings"]}
    for name, file, sheet in E.SCENARIOS:
        assert (file, sheet) in places, name


def test_every_generated_sheet_has_a_scenario(books):
    named = {(f, s) for _, f, s in E.SCENARIOS} | {(i["file"], i["sheet"]) for i in E.FINAL["items"]}
    meta = {"표지", "개정이력"}
    for file, wb in books.items():
        for sheet in wb.sheetnames:
            if sheet not in meta:
                assert (file, sheet) in named, (file, sheet)


# ---------- 개수 합계 ----------

def _count_kinds(warnings):
    out = {}
    for w in warnings:
        out[w["kind"]] = out.get(w["kind"], 0) + 1
    return out


@pytest.mark.parametrize("bundle", ["FINAL", "BEFORE_1008"])
def test_summary_counts(bundle):
    b = getattr(E, bundle)
    s = b["summary"]
    assert s["items"] == len(b["items"])
    assert s["links"] == len(b["links"])
    assert s["warnings"] == len(b["warnings"])
    assert s["warning_kinds"] == _count_kinds(b["warnings"])


# ---------- BEFORE_1008 ----------

def _key(i):
    return (i["file"], i["sheet"], tuple(i["rows"]))


def test_before_items_are_final_minus_out_of_scope_sheets():
    excluded = set(E.BEFORE_1008["excluded_sheets"]) | set(E.BEFORE_1008["unsupported_sheets"])
    expected_keys = {_key(i) for i in E.FINAL["items"] if (i["file"], i["sheet"]) not in excluded}
    assert {_key(i) for i in E.BEFORE_1008["items"]} == expected_keys


def test_before_items_have_no_ids():
    for i in E.BEFORE_1008["items"]:
        assert "item_id" not in i
    for w in E.BEFORE_1008["warnings"]:
        assert "warning_id" not in w


def test_before_excluded_sheets_not_compared():
    excluded = set(E.BEFORE_1008["excluded_sheets"])
    for w in E.BEFORE_1008["warnings"]:
        assert (w["file"], w["sheet"]) not in excluded
    for kind in E.BEFORE_1008["excluded_warning_kinds"]:
        assert kind not in _count_kinds(E.BEFORE_1008["warnings"])


def test_before_unsupported_rules_are_rule_level(project):
    rules = {r["id"]: r for r in project["link_rules"]}
    first_file = {d["doc_type"]: d["files"][0] for d in project["documents"]}
    rule_level = [w for w in E.BEFORE_1008["warnings"] if w["kind"] == "unsupported" and w.get("message_contains")]
    # 미구현 key를 쓰는 규칙마다 하나씩 (2026-10-10: sheet_to_path·path_prefix·glossary는 1부로 옮겨 구현,
    # 2026-10-13: id_ref 구현 → shop에 미구현 key 규칙이 남지 않음)
    assert sorted(w["message_contains"] for w in rule_level) == sorted(
        r["id"] for r in project["link_rules"] if r["key"] in ())
    for w in rule_level:
        rule = rules[w["message_contains"]]
        assert w["file"] == first_file[rule["docs"][0]] and w["sheet"] is None and not w["locations"]
