"""B1 청크 — 항목 하나 → 청크 하나. 형식은 schema.Chunk, 계약 예시는 tests/fixtures/chunk_contract_examples.jsonl.

- text: 첫 줄 category_path_text(경로가 없으면 생략), 다음 줄부터 열 순서대로 「머리글: 값」(raw_fields) 또는
  「머리글 (병합 F2): 값」(merged_fields, 모양은 schema.MERGED_LINE). 분류 열·exclude_from_text 열·빈 값은 뺀다.
  머리글이 빈 열은 열 문자를 쓴다. 값은 원문 그대로(숫자는 글자로), 원문에 없는 말을 넣지 않는다.
- source: 항목의 첫 위치. meta: 계약 예시 7칸을 평평한 글자로(없으면 "", ref_ids는 ", "로 이음).
- 경로도 본문 줄도 없으면(분류 none·루트 없음·값이 본문 제외 열에만) 청크를 만들지 않는다(None). 항목은 그대로 두고
  처리 보고서에 「본문이 빈 항목」으로 적는다. 제외 열을 본문에 넣지 않는다.
"""

from si_prep.layout import col_number
from si_prep.schema import MERGED_LINE, Chunk

CHUNK_PREFIX = "B1-"
REF_IDS_JOIN = ", "


def _text(value) -> str:
    return value if isinstance(value, str) else str(value)


def _lines(draft) -> list:
    fields = []
    for col, f in draft.raw_fields.items():
        if col not in draft.text_excluded:
            fields.append((col, f"{f.header or col}: {_text(f.value)}"))
    for col, m in draft.merged_fields.items():
        if col not in draft.text_excluded:
            fields.append((col, MERGED_LINE.format(header=m.header or col, cell=f"{col}{m.source_row}", value=_text(m.value))))
    return [line for _, line in sorted(fields, key=lambda x: col_number(x[0]))]


def make_chunk(draft, item_id: str) -> Chunk | None:
    lines = ([draft.category_path_text] if draft.category_path_text else []) + _lines(draft)
    if not lines:
        return None
    location = draft.location()
    return Chunk(
        chunk_id=f"{CHUNK_PREFIX}{item_id}",
        text="\n".join(lines),
        source={"file": location.file, "sheet": location.sheet, "rows": location.rows.model_dump()},
        meta={"item_id": item_id, "doc_type": draft.doc_type, "doc_file": draft.doc_file, "sheet": draft.sheet,
              "category_path_text": draft.category_path_text, "source_id": draft.source_id or "",
              "ref_ids": REF_IDS_JOIN.join(draft.ref_ids)})
