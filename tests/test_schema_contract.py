"""rag_core와 같은 청크 예시 파일로 계약을 확인한다."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from si_prep.schema import Chunk

EXAMPLES = Path(__file__).parent / "fixtures" / "chunk_contract_examples.jsonl"


def _examples():
    lines = [l for l in EXAMPLES.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [json.loads(l) for l in lines]


def test_contract_examples_cover_three_chunk_kinds():
    prefixes = sorted({e["chunk_id"][:5] if e["chunk_id"].startswith("B0-") else e["chunk_id"][:3] for e in _examples()})
    assert prefixes == ["B0-R-", "B0-S-", "B1-"]


@pytest.mark.parametrize("example", _examples(), ids=lambda e: e["chunk_id"])
def test_contract_examples_pass(example):
    chunk = Chunk.model_validate_json(json.dumps(example, ensure_ascii=False))
    assert chunk.model_dump(mode="json") == example  # 읽고 다시 쓰면 같은 모양


@pytest.mark.parametrize("example", [e for e in _examples() if e["chunk_id"].startswith("B0-")], ids=lambda e: e["chunk_id"])
def test_contract_b0_with_meta_rejected(example):
    with pytest.raises(ValidationError):
        Chunk.model_validate({**example, "meta": {"item_id": "IT-000001"}})
