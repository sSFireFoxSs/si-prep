"""JSON Schema 내보내기. 커밋된 docs/schema/*.schema.json이 지금 schema.py로 새로 만든 결과와 같아야 한다
(내보내기를 잊고 커밋하는 것 방지)."""

import json
from pathlib import Path

from si_prep import export_schema
from si_prep.schema import Chunk, Item, Link, Warning_

COMMITTED = Path(__file__).resolve().parents[1] / "docs" / "schema"


def test_export_writes_one_file_per_output_model(tmp_path):
    written = export_schema.export(tmp_path)
    assert sorted(p.name for p in written) == [
        "chunk.schema.json", "item.schema.json", "link.schema.json", "warning.schema.json"]
    titles = {json.loads(p.read_text(encoding="utf-8"))["title"] for p in written}
    assert titles == {"Chunk", "Item", "Link", "Warning"}


def test_export_is_deterministic(tmp_path):
    a = export_schema.export(tmp_path / "a")
    b = export_schema.export(tmp_path / "b")
    assert [p.read_bytes() for p in a] == [p.read_bytes() for p in b]


def test_committed_schema_files_match_current_schema(tmp_path):
    fresh = {p.name: p.read_text(encoding="utf-8") for p in export_schema.export(tmp_path)}
    committed = {p.name: p.read_text(encoding="utf-8") for p in COMMITTED.glob("*.schema.json")}
    assert sorted(committed) == sorted(fresh), "docs/schema의 파일 목록이 다름 — python -m si_prep.export_schema 실행"
    for name in fresh:
        assert committed[name] == fresh[name], f"{name}이 schema.py와 다름 — python -m si_prep.export_schema 실행"


def test_exported_schema_matches_models(tmp_path):
    export_schema.export(tmp_path)
    for model, name in ((Chunk, "chunk"), (Item, "item"), (Link, "link"), (Warning_, "warning")):
        data = json.loads((tmp_path / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert data == json.loads(json.dumps(model.model_json_schema(), ensure_ascii=False))


# ---------- 항목 6-4: 설정 JSON Schema (docs/config_schema) ----------

from si_prep.config import Glossary, Profile, ProjectConfig  # noqa: E402

COMMITTED_CONFIG = Path(__file__).resolve().parents[1] / "docs" / "config_schema"
CONFIG_MODELS = {"glossary": Glossary, "profile": Profile, "project": ProjectConfig}


def test_export_config_writes_one_file_per_config_model(tmp_path):
    written = export_schema.export_config(tmp_path)
    assert sorted(p.name for p in written) == ["glossary.schema.json", "profile.schema.json", "project.schema.json"]
    titles = {json.loads(p.read_text(encoding="utf-8"))["title"] for p in written}
    assert titles == {"Glossary", "Profile", "ProjectConfig"}


def test_export_config_is_deterministic(tmp_path):
    a = export_schema.export_config(tmp_path / "a")
    b = export_schema.export_config(tmp_path / "b")
    assert [p.read_bytes() for p in a] == [p.read_bytes() for p in b]


def test_committed_config_schema_files_match_current_models(tmp_path):
    fresh = {p.name: p.read_text(encoding="utf-8") for p in export_schema.export_config(tmp_path)}
    committed = {p.name: p.read_text(encoding="utf-8") for p in COMMITTED_CONFIG.glob("*.schema.json")}
    assert sorted(committed) == sorted(fresh), "docs/config_schema의 파일 목록이 다름 — python -m si_prep.export_schema 실행"
    for name in fresh:
        assert committed[name] == fresh[name], f"{name}이 config.py와 다름 — python -m si_prep.export_schema 실행"


def test_exported_config_schema_matches_models(tmp_path):
    export_schema.export_config(tmp_path)
    for name, model in CONFIG_MODELS.items():
        data = json.loads((tmp_path / f"{name}.schema.json").read_text(encoding="utf-8"))
        assert data == json.loads(json.dumps(model.model_json_schema(), ensure_ascii=False))
        assert data["additionalProperties"] is False   # 모르는 키 거부(extra="forbid")가 편집기에서도 보이게


def test_main_writes_output_and_config_schema(tmp_path, capsys):
    export_schema.main([str(tmp_path)])
    assert sorted(p.name for p in (tmp_path / "schema").glob("*.schema.json")) == [
        "chunk.schema.json", "item.schema.json", "link.schema.json", "warning.schema.json"]
    assert sorted(p.name for p in (tmp_path / "config_schema").glob("*.schema.json")) == [
        "glossary.schema.json", "profile.schema.json", "project.schema.json"]
    assert len(capsys.readouterr().out.splitlines()) == 7
