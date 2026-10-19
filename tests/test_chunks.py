"""B1 청크 — 항목 하나 → 청크 하나.
rag_core와 같은 계약 예시(tests/fixtures/chunk_contract_examples.jsonl)와 글자까지 같아야 한다.
"""

import json
from pathlib import Path

import openpyxl
import pytest

from si_prep import boundary, chunks, extract, hierarchy
from si_prep.config import Profile, load_project, load_profile, profile_source, sheet_profile
from si_prep.issues import Issues
from si_prep.layout import build_table, select_sheets
from si_prep.reader import open_workbook
from si_prep.registry import Unimplemented
from si_prep.schema import SCHEMA_VERSION, Chunk, DocVersion
from conftest import SHOP

CONTRACT = Path(__file__).parent / "fixtures" / "chunk_contract_examples.jsonl"


def _shop_drafts():
    config = load_project(SHOP)
    out = []
    for doc in config.documents:
        profile = load_profile(config.profile_path(doc))
        for f in doc.files:
            wb = open_workbook(config.input_path / f, Issues())
            if wb is None:
                continue
            version = extract.read_doc_version(wb, profile, Issues())
            for grid in select_sheets(wb, profile, Issues()):
                sp = sheet_profile(profile, grid.name)
                try:
                    split = boundary.REGISTRY.get(sp.item_boundary.method)
                    make = hierarchy.REGISTRY.get(sp.hierarchy.method)
                except Unimplemented:
                    continue
                issues = Issues()
                table = build_table(grid, sp, f, issues)
                if table is None:
                    continue
                groups = split(table, sp, issues)
                out += extract.make_items(table, groups, make(table, groups, sp, issues), doc.doc_type,
                                         profile_source(config.approved, profile.approved), version, issues)
    return out


@pytest.fixture(scope="module")
def drafts():
    return _shop_drafts()


def _find(drafts, sheet, row):
    return next(d for d in drafts if d.sheet == sheet and d.rows[0] == row)


def test_matches_contract_example_exactly(drafts):
    example = next(json.loads(line) for line in CONTRACT.read_text(encoding="utf-8").splitlines()
                   if line.strip() and json.loads(line)["chunk_id"] == "B1-IT-000002")
    chunk = chunks.make_chunk(_find(drafts, "회원", 7), "IT-000002").model_dump(mode="json")
    # 2026-10-10 스키마 1.2: 공유 계약 예시는 1.1 그대로(여전히 유효) → 버전 칸만 지금 버전, 나머지는 글자까지 같음
    assert chunk.pop("schema_version") == SCHEMA_VERSION and example.pop("schema_version") == "1.1"
    assert chunk == example


def test_merged_field_line(drafts):
    chunk = chunks.make_chunk(_find(drafts, "내용병합", 3), "IT-000077")
    assert chunk.text.splitlines() == ["주문 › 결제 › 무통장 입금", "기능명: 입금 계좌 안내",
                                       "설명 (병합 F2): 결제는 PG사 창에서 진행"]


def test_hierarchy_and_excluded_columns_not_in_text(drafts):
    d = _find(drafts, "테스트케이스", 2)
    text = chunks.make_chunk(d, "IT-000043").text
    assert "결과(검수자1)" in {f.header for f in d.raw_fields.values()}         # raw_fields에는 있음
    assert "결과(검수자" not in text and "수행자" not in text                   # 본문에서는 뺌
    assert "메뉴:" not in text and "1단계:" not in text                         # 분류 열도 본문에서 뺌
    assert text.splitlines()[0] == "회원 › 로그인 › 일반 로그인 › 아이디 입력"


def test_meta_flat_strings(drafts):
    d = _find(drafts, "테스트케이스", 2)
    d.ref_ids = ["REQ-001", "REQ-002"]                    # 13b 전이라 직접 넣어 확인
    meta = chunks.make_chunk(d, "IT-000043").meta
    assert meta == {"item_id": "IT-000043", "doc_type": "test", "doc_file": "가상몰_테스트케이스.xlsx",
                    "sheet": "테스트케이스", "category_path_text": "회원 › 로그인 › 일반 로그인 › 아이디 입력",
                    "source_id": "TC-001", "ref_ids": "REQ-001, REQ-002"}
    d.ref_ids = []


def test_source_is_first_location(drafts):
    c = chunks.make_chunk(_find(drafts, "고객센터", 6), "IT-000013")
    assert (c.source.file, c.source.sheet, c.source.rows.start, c.source.rows.end) == ("가상몰_기능정의서_v1.2.xlsx", "고객센터", 6, 6)


def test_all_shop_chunks_valid_and_one_per_item(drafts):
    made = [chunks.make_chunk(d, f"IT-{n:06d}") for n, d in enumerate(drafts, start=1)]
    assert all(isinstance(c, Chunk) for c in made) and len(made) == len(drafts)
    assert len({c.chunk_id for c in made}) == len(made)


# ---------- 작은 표로 확인 (B·C·E) ----------

def _draft(tmp_path, rows, **over):
    data = {"id": "x", "approved": True, "header_rows": [1], "data_start_row": 2,
            "columns": {"hierarchy": [{"header_contains": "분류"}]},
            "hierarchy": {"method": "columns"}, "item_boundary": {"method": "row"}}
    data.update(over)
    p = Profile.model_validate(data)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "S"
    for r, row in enumerate(rows, start=1):
        for c, v in enumerate(row, start=1):
            if v is not None:
                ws.cell(r, c, v)
    path = tmp_path / "t.xlsx"
    wb.save(path)
    grid = open_workbook(path, Issues()).sheet("S")
    issues = Issues()
    table = build_table(grid, p, "t.xlsx", issues)
    groups = boundary.by_row(table, p, issues)
    return extract.make_items(table, groups, hierarchy.REGISTRY.get(p.hierarchy.method)(table, groups, p, issues),
                              "fo", "approved", DocVersion(), issues)[0]


def test_column_without_header_uses_letter(tmp_path):
    d = _draft(tmp_path, [["분류", None, "설명"], ["가", "메모", "x"]],
               columns={"hierarchy": [{"header_contains": "분류"}], "title": {"col": "B"}})
    assert chunks.make_chunk(d, "IT-000001").text.splitlines() == ["가", "B: 메모", "설명: x"]


def test_no_path_starts_with_fields(tmp_path):
    d = _draft(tmp_path, [["이름", "설명"], ["가", "x"]],
               columns={"title": {"header_contains": "이름"}}, hierarchy={"method": "none"})
    assert chunks.make_chunk(d, "IT-000001").text == "이름: 가\n설명: x"


def test_values_as_text_keep_newlines(tmp_path):
    d = _draft(tmp_path, [["분류", "개수", "설명"], ["가", 3, "첫 줄\n- 둘째 줄"]])
    assert chunks.make_chunk(d, "IT-000001").text == "가\n개수: 3\n설명: 첫 줄\n- 둘째 줄"


def test_column_order_beyond_z(tmp_path):
    row_head = ["분류"] + [None] * 25 + ["AA열"]
    row_data = ["가"] + [None] * 24 + ["Z값", "AA값"]
    row_head[25] = "Z열"
    d = _draft(tmp_path, [row_head, row_data])
    assert chunks.make_chunk(d, "IT-000001").text.splitlines()[1:] == ["Z열: Z값", "AA열: AA값"]


def test_empty_body_makes_no_chunk(tmp_path):
    # 2026-10-10 작성자 결정: 경로도 본문 줄도 없으면 청크를 만들지 않는다(항목은 그대로, 보고서 20에 「본문이 빈 항목」)
    d = _draft(tmp_path, [["이름", "결과"], [None, "통과"]],
               columns={"title": {"header_contains": "이름"}, "exclude_from_text": [{"header_contains": "결과"}]},
               hierarchy={"method": "none"})
    assert "B" in d.raw_fields
    assert chunks.make_chunk(d, "IT-000001") is None
