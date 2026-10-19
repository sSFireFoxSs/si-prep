"""JSON Schema 파일을 내보낸다.

- 출력 스키마: schema.py의 출력 모델 → docs/schema (rag_core 공유용)
- 설정 스키마: config.py의 설정 모델 → docs/config_schema (설정 파일 편집기 자동 완성·검사용).
  모양(1단계)만 담는다. 교차 검사(2단계, 프로필과의 대조)는 python -m si_prep.config로 한다.

실행: python -m si_prep.export_schema [docs 폴더]   (기본: docs) — 두 폴더를 모두 쓴다.
결과는 커밋한다. tests/test_export_schema.py가 커밋된 파일과 지금 모델 결과가 다르면 실패한다.
"""

import json
import sys
from pathlib import Path

from si_prep.config import Glossary, Profile, ProjectConfig
from si_prep.schema import Chunk, Item, Link, Warning_

# 파일 이름 → 모델 (출력 jsonl 한 줄의 모양)
MODELS = {"chunk": Chunk, "item": Item, "link": Link, "warning": Warning_}
# 파일 이름 → 모델 (설정 파일 하나의 모양)
CONFIG_MODELS = {"glossary": Glossary, "profile": Profile, "project": ProjectConfig}

OUTPUT_DIR = "schema"
CONFIG_DIR = "config_schema"


def _write(models, out_dir) -> list[Path]:
    """모델마다 <이름>.schema.json을 쓴다. 키 정렬·들여쓰기·LF 고정이라 같은 모델이면 같은 글자"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in sorted(models.items()):
        text = json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        path = out_dir / f"{name}.schema.json"
        path.write_text(text, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def export(out_dir) -> list[Path]:
    """출력 스키마"""
    return _write(MODELS, out_dir)


def export_config(out_dir) -> list[Path]:
    """설정 스키마"""
    return _write(CONFIG_MODELS, out_dir)


def main(argv=None):
    from si_prep.console import replace_unencodable
    replace_unencodable()   # 화면 출력: 인코딩은 그대로, 못 쓰는 글자만 ?(cp949 콘솔에서 멈추지 않게)
    args = sys.argv[1:] if argv is None else argv
    docs = Path(args[0]) if args else Path("docs")
    for path in export(docs / OUTPUT_DIR) + export_config(docs / CONFIG_DIR):
        print(path)


if __name__ == "__main__":
    main()
