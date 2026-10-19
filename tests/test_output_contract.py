"""항목·연결·경고 계약 예시 (rag_core 공유용, 청크 예시 파일과 별도).

각 줄은 {"model": "Item|Link|Warning", "data": {...}}. 모델 검증을 통과하고, 읽고 다시 쓰면 같은 모양이며,
값은 합성 데이터 기대값(expected.FINAL)과 맞는다.
"""

import json
from pathlib import Path

import pytest

from fixtures import expected as E
from si_prep.schema import Item, Link, Warning_

EXAMPLES = Path(__file__).parent / "fixtures" / "output_contract_examples.jsonl"
MODELS = {"Item": Item, "Link": Link, "Warning": Warning_}


def _examples():
    return [json.loads(l) for l in EXAMPLES.read_text(encoding="utf-8").splitlines() if l.strip()]


def _loc_key(loc):
    return (loc["sheet"], loc["rows"]["start"], loc["rows"]["end"], loc["cols"])


def test_examples_cover_each_model_twice():
    kinds = [e["model"] for e in _examples()]
    assert sorted(set(kinds)) == ["Item", "Link", "Warning"] and all(kinds.count(k) == 2 for k in set(kinds))


@pytest.mark.parametrize("example", _examples(), ids=lambda e: f'{e["model"]}-{list(e["data"].values())[1]}')
def test_example_passes_and_round_trips(example):
    obj = MODELS[example["model"]].model_validate_json(json.dumps(example["data"], ensure_ascii=False))
    assert obj.model_dump(mode="json") == example["data"]


def test_item_examples_match_final():
    final = {i["item_id"]: i for i in E.FINAL["items"]}
    for e in (x["data"] for x in _examples() if x["model"] == "Item"):
        f = final[e["item_id"]]
        loc = e["locations"][0]
        assert (e["doc_type"], e["doc_file"], loc["sheet"], (loc["rows"]["start"], loc["rows"]["end"])) == \
               (f["doc_type"], f["file"], f["sheet"], tuple(f["rows"]))
        assert e["category_path_text"] == f["path_text"] and e["status"] == f["status"] and e["title"] == f["title"]
        assert [(p["value"], p["basis"]) for p in e["category_path"]] == [(v, b) for v, b, _ in f["path"]]
        assert sorted(e["raw_fields"]) == f["raw"]
        assert {k: v["source_row"] for k, v in e["merged_fields"].items()} == f["merged"]


def test_link_examples_match_final():
    final = {l["link_id"]: l for l in E.FINAL["links"]}
    for e in (x["data"] for x in _examples() if x["model"] == "Link"):
        f = final[e["link_id"]]
        assert (e["rule_id"], e["method"], e["grade"]) == (f["rule_id"], f["method"], f["grade"])
        if f.get("item_a"):
            assert (e["item_a"], e["item_b"]) == (f["item_a"], f["item_b"])
        else:
            assert (e["item"], e["group"]["doc_type"], e["group"]["category_path_text"]) == (f["item"], *f["group"])


def test_warning_examples_match_final():
    final = {w["warning_id"]: w for w in E.FINAL["warnings"]}
    for e in (x["data"] for x in _examples() if x["model"] == "Warning"):
        f = final[e["warning_id"]]
        assert (e["kind"], e["file"], e["sheet"], e["item_ids"]) == (f["kind"], f["file"], f["sheet"], f["item_ids"])
        assert [_loc_key(l) for l in e["locations"]] == [tuple(x) for x in f["locations"]]
