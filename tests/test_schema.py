"""출력 스키마 ① 위치(RowRange·Location·ChunkSource)와 청크(Chunk)."""

import pytest
from pydantic import ValidationError

from si_prep.schema import SCHEMA_VERSION, Chunk, ChunkSource, Location, RowRange

ROWS = {"start": 7, "end": 7}
SOURCE = {"file": "가상몰_기능정의서_v1.2.xlsx", "sheet": "회원", "rows": ROWS}


# ---------- RowRange ----------

def test_rowrange_ok():
    assert RowRange(start=3, end=5).end == 5
    assert RowRange(start=1, end=1).start == 1


@pytest.mark.parametrize("start,end", [(0, 1), (1, 0), (-1, 2), (5, 3)])
def test_rowrange_rejects_zero_and_reversed(start, end):
    with pytest.raises(ValidationError):
        RowRange(start=start, end=end)


def test_location_and_source_share_rowrange():
    # 한 곳 정의: 두 모델의 rows가 같은 RowRange 규칙을 쓴다
    with pytest.raises(ValidationError):
        Location(**{**SOURCE, "rows": {"start": 4, "end": 2}})
    with pytest.raises(ValidationError):
        ChunkSource(**{**SOURCE, "rows": {"start": 0, "end": 2}})


# ---------- Location ----------

def test_location_ok_with_and_without_cols():
    assert Location(**SOURCE).cols is None
    assert Location(**SOURCE, cols=["B", "AB", "XFD"]).cols == ["B", "AB", "XFD"]


@pytest.mark.parametrize("file", ["dir/가상몰.xlsx", "dir\\가상몰.xlsx", ""])
def test_location_file_must_be_name_only(file):
    with pytest.raises(ValidationError):
        Location(**{**SOURCE, "file": file})


def test_location_sheet_must_not_be_empty():
    with pytest.raises(ValidationError):
        Location(**{**SOURCE, "sheet": ""})


@pytest.mark.parametrize("cols", [["b"], ["AAAA"], ["B1"], [""], ["B", "B"]])
def test_location_cols_format_and_no_duplicates(cols):
    with pytest.raises(ValidationError):
        Location(**SOURCE, cols=cols)


def test_location_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Location(**SOURCE, note="x")


# ---------- ChunkSource ----------

def test_chunk_source_has_no_cols():
    assert ChunkSource(**SOURCE).file == SOURCE["file"]
    with pytest.raises(ValidationError):
        ChunkSource(**SOURCE, cols=["B"])  # rag_core 계약: cols 없음


@pytest.mark.parametrize("file", ["a/b.xlsx", "a\\b.xlsx"])
def test_chunk_source_file_must_be_name_only(file):
    with pytest.raises(ValidationError):
        ChunkSource(**{**SOURCE, "file": file})


# ---------- Chunk ----------

def _chunk(**over):
    data = {"chunk_id": "B1-IT-000002", "text": "회원 › 로그인\n기능명: 비밀번호 입력란", "source": SOURCE,
            "meta": {"item_id": "IT-000002"}}
    data.update(over)
    return Chunk(**data)


def test_chunk_schema_version_default():
    assert _chunk().schema_version == SCHEMA_VERSION == "1.4"   # 2026-10-10 1.2(추가형), 2026-10-13 1.3(추가형, form_filled), 1.4(추가형, table_title)


@pytest.mark.parametrize("v", ["1.0", "1.1", "1.12"])
def test_chunk_schema_version_format_ok(v):
    assert _chunk(schema_version=v).schema_version == v


@pytest.mark.parametrize("v", ["v1", "1", "1.1.0", "2.0", "1.x", "", " 1.1"])
def test_chunk_schema_version_format_rejected(v):
    with pytest.raises(ValidationError):
        _chunk(schema_version=v)


@pytest.mark.parametrize("chunk_id", ["B1-IT-000002", "B0-R-000001", "B0-S-000001"])
def test_chunk_id_allowed_prefixes(chunk_id):
    meta = {} if chunk_id.startswith("B0-") else {"item_id": "IT-000002"}
    assert _chunk(chunk_id=chunk_id, meta=meta).chunk_id == chunk_id


@pytest.mark.parametrize("chunk_id", ["C1-IT-000002", "b1-IT-000002", "B2-x", "B1", "B1-", "IT-000002", "",
                                      "B0-X-000001", "B0-000001", "B0-R-", "B0-S-", "b0-R-000001"])
def test_chunk_id_other_prefixes_rejected(chunk_id):
    with pytest.raises(ValidationError):
        _chunk(chunk_id=chunk_id)


def test_chunk_text_must_not_be_empty():
    with pytest.raises(ValidationError):
        _chunk(text="")


def test_b0_chunk_meta_must_be_empty():
    assert _chunk(chunk_id="B0-R-000001", meta={}).meta == {}
    with pytest.raises(ValidationError):
        _chunk(chunk_id="B0-R-000001", meta={"item_id": "IT-000002"})


@pytest.mark.parametrize("meta", [{"n": 1}, {"ok": True}, {"nested": {"a": "b"}}, {"list": ["a"]}, {"none": None}])
def test_chunk_meta_values_must_be_flat_strings(meta):
    with pytest.raises(ValidationError):
        _chunk(meta=meta)


def test_chunk_rejects_unknown_field_and_bad_source():
    with pytest.raises(ValidationError):
        _chunk(extra="x")
    with pytest.raises(ValidationError):
        _chunk(source={**SOURCE, "cols": ["B"]})
