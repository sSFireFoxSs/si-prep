"""출력 스키마 — 출력 형식을 정의하는 단 하나의 파일.

rag_core는 이 파일을 import해서 쓴다. 복사본을 만들지 않는다.
변경 기록은 docs/schema/CHANGELOG.md.

항목 3: 위치(RowRange, Location, ChunkSource)와 청크(Chunk).
항목 4: 항목(Item)·연결(Link)·경고(Warning_)와, 쓰는 쪽이 같이 쓰는 판단 함수
(path_text, path_starts_with, group_contains, find_duplicate_links).
"""

import re
from collections.abc import Iterable, Sequence
from typing import Annotated, Literal

from pydantic import (
    BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, StringConstraints,
    field_validator, model_validator,
)

SCHEMA_VERSION = "1.4"
_SCHEMA_VERSION_FORMAT = r"^1\.\d+$"  # v1.x만 (파괴형 변경은 v2)

_COLUMN_LETTERS = re.compile(r"^[A-Z]{1,3}$")
_CHUNK_ID = re.compile(r"^(B1-|B0-R-|B0-S-).+$")
_B0_PREFIX = "B0-"

PATH_SEP = " › "        # 보여주기용 경로 구분 (category_path_text, GroupRef.category_path_text)
EMPTY_STEP = "(빈칸)"   # 빈 분류 단계 표시
MERGED_LINE = "{header} (병합 {cell}): {value}"  # B1 청크의 merged_fields 줄 모양


def _check_file_name(v):
    """파일 이름만 허용 (경로 구분 기호 금지)"""
    if v is not None and ("/" in v or "\\" in v):
        raise ValueError(f"file에는 파일 이름만 씁니다(경로 구분 기호 포함): {v}")
    return v


class _Model(BaseModel):
    """모든 모델 공통: 모르는 필드는 에러"""

    model_config = ConfigDict(extra="forbid")


# ---------- 위치 ----------

class RowRange(_Model):
    """행 범위. Location과 ChunkSource가 같이 쓴다."""

    start: int = Field(ge=1)
    end: int = Field(ge=1)

    @model_validator(mode="after")
    def _start_not_after_end(self):
        if self.start > self.end:
            raise ValueError(f"행 범위의 시작({self.start})이 끝({self.end})보다 큽니다")
        return self


class _SheetRows(_Model):
    """파일·시트·행 — ChunkSource와 Location의 공통 규칙 (한 곳 정의)"""

    file: str = Field(min_length=1)
    sheet: str = Field(min_length=1)
    rows: RowRange

    @field_validator("file")
    @classmethod
    def _file_name_only(cls, v):
        return _check_file_name(v)


class ChunkSource(_SheetRows):
    """청크의 출처. cols 없음 (rag_core 계약)"""


class Location(_SheetRows):
    """원문 위치. cols는 열 문자 목록(중복 없음) 또는 None"""

    cols: list[str] | None = None

    @field_validator("cols")
    @classmethod
    def _column_letters(cls, v):
        if v is None:
            return v
        bad = [c for c in v if not _COLUMN_LETTERS.match(c)]
        if bad:
            raise ValueError(f"열 문자가 아닙니다: {bad}")
        if len(set(v)) != len(v):
            raise ValueError(f"열 문자가 중복됩니다: {v}")
        return v


# ---------- 청크 ----------

class Chunk(_Model):
    """검색용 청크. si-prep은 B1만 만들고, B0는 rag_core가 만들어 이 모델로 검증한다."""

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=_SCHEMA_VERSION_FORMAT)
    chunk_id: str
    text: str = Field(min_length=1)
    source: ChunkSource
    meta: dict[StrictStr, StrictStr] = Field(default_factory=dict)

    @field_validator("chunk_id")
    @classmethod
    def _chunk_id_prefix(cls, v):
        if not _CHUNK_ID.match(v):
            raise ValueError(f"chunk_id는 B1-, B0-R-, B0-S- 중 하나로 시작해야 합니다: {v!r}")
        return v

    @model_validator(mode="after")
    def _b0_meta_empty(self):
        if self.chunk_id.startswith(_B0_PREFIX) and self.meta:
            raise ValueError(f"B0 청크의 meta는 비어 있어야 합니다: {self.chunk_id}")
        return self


# ---------- 항목·연결·경고 공통 타입 (ID·글자 칸은 엄격: 숫자를 글자로 바꿔 받지 않음) ----------

SchemaVersion = Annotated[StrictStr, StringConstraints(pattern=_SCHEMA_VERSION_FORMAT)]
ItemId = Annotated[StrictStr, StringConstraints(pattern=r"^IT-\d{6}$")]
LinkId = Annotated[StrictStr, StringConstraints(pattern=r"^LK-\d{6}$")]
WarningId = Annotated[StrictStr, StringConstraints(pattern=r"^WN-\d{6}$")]
DocType = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
ColumnLetter = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{1,3}$")]
NonEmptyStr = Annotated[StrictStr, StringConstraints(min_length=1)]
CellValue = StrictStr | StrictBool | StrictInt | StrictFloat | None  # 날짜는 ISO 글자

# form_filled(1.3): 사람이 프로필에서 「빈칸 = 위와 같음」을 선언한 시트에서 위 값으로 채운 단계 — 추정 아님
# table_title(1.4): 한 시트에 표가 여러 개일 때(프로필 tables) 그 표의 제목 행 값 — 추정 아님
Basis = Literal["sheet_name", "cell", "merge_restored", "filled_down", "split_cell", "numbering", "empty", "form_filled",
                "table_title"]
Status = Literal["ok", "not_written", "unparsed", "ambiguous"]
ProfileSource = Literal["auto", "approved"]
Grade = Literal["explicit", "structural", "inferred"]
Method = Literal["id_ref", "path_exact", "path_normalized", "glossary", "name_similarity"]
WarningKind = Literal[
    "content_mismatch", "unparsed", "unsupported", "unsupported_layout", "merge_unrestored", "link_unconfirmed",
    "version_mismatch", "sheet_skipped", "hidden_content", "header_not_found", "duplicate_id", "ref_unresolved",
    "formula_no_value", "read_failed",
]

METHOD_GRADE = {"id_ref": "explicit", "path_exact": "structural", "path_normalized": "structural",
                "glossary": "structural", "name_similarity": "inferred"}


# ---------- 항목 ----------

class PathPart(_Model):
    """분류 경로의 한 단계. value는 basis가 empty일 때만 None"""

    level: int = Field(ge=1)
    value: NonEmptyStr | None
    basis: Basis

    @model_validator(mode="after")
    def _value_matches_basis(self):
        if (self.value is None) != (self.basis == "empty"):
            raise ValueError(f"value가 None인 것은 basis가 empty일 때뿐입니다: {self.level}단계 basis={self.basis}")
        return self


class RawField(_Model):
    """원문 칸 값 (헤더는 합친 헤더 글자)"""

    header: StrictStr
    value: CellValue


class MergedField(_Model):
    """병합 시작 칸에서 받은 값 (시작 칸이 항목 행 밖일 때만). source_row는 병합 시작 행"""

    header: StrictStr
    value: CellValue
    source_row: int = Field(ge=1)


class DocVersion(_Model):
    cover: StrictStr | None = None
    filename: StrictStr | None = None


def path_text(parts: Sequence[PathPart]) -> str:
    """보여주기용 경로 글자: " › "로 잇고, 빈 단계는 (빈칸), 값이 같은 단계가 이어지면 한 번만"""
    out = []
    for part in parts:
        step = EMPTY_STEP if part.value is None else part.value
        if part.value is not None and out and out[-1] == step:
            continue
        out.append(step)
    return PATH_SEP.join(out)


class Item(_Model):
    schema_version: SchemaVersion = SCHEMA_VERSION
    item_id: ItemId
    doc_type: DocType
    doc_file: NonEmptyStr
    source_id: StrictStr | None = None
    ref_ids: list[StrictStr] = Field(default_factory=list)
    title: StrictStr | None = None
    category_path: list[PathPart]
    category_path_text: StrictStr
    raw_fields: dict[ColumnLetter, RawField] = Field(default_factory=dict)
    merged_fields: dict[ColumnLetter, MergedField] = Field(default_factory=dict)
    locations: list[Location] = Field(min_length=1)
    doc_version: DocVersion
    status: Status
    profile_source: ProfileSource

    @field_validator("doc_file")
    @classmethod
    def _doc_file_name_only(cls, v):
        return _check_file_name(v)

    @field_validator("ref_ids")
    @classmethod
    def _ref_ids_unique(cls, v):
        if len(set(v)) != len(v):
            raise ValueError(f"ref_ids에 중복이 있습니다: {v}")
        return v

    @model_validator(mode="after")
    def _consistency(self):
        levels = [p.level for p in self.category_path]
        if levels != list(range(1, len(levels) + 1)):
            raise ValueError(f"분류 단계 번호가 1부터 이어지지 않습니다: {levels}")
        expected = path_text(self.category_path)
        if self.category_path_text != expected:
            raise ValueError(f"category_path_text가 단계 값과 다릅니다: {self.category_path_text!r} != {expected!r}")
        overlap = set(self.raw_fields) & set(self.merged_fields)
        if overlap:
            raise ValueError(f"raw_fields와 merged_fields의 열이 겹칩니다: {sorted(overlap)}")
        return self


# ---------- 연결 (방향 없음) ----------

class GroupRef(_Model):
    """묶음 = 그 문서 종류에서 이 경로로 (단계 단위로) 시작하는 항목들.
    sheets(1.2): 묶음을 그 시트들의 항목으로 제한(규칙 sheets 칸을 실제 시트 이름으로 푼 것). 없으면 전체"""

    doc_type: DocType
    category_path_text: NonEmptyStr
    # 없으면(None) 출력에 넣지 않는다 — 1.1 결과가 글자 그대로 왕복되게(추가형)
    sheets: list[NonEmptyStr] | None = Field(default=None, min_length=1, exclude_if=lambda v: v is None)

    @field_validator("sheets")
    @classmethod
    def _sheets_unique(cls, v):
        if v is not None and len(set(v)) != len(v):
            raise ValueError(f"sheets에 같은 시트가 두 번 있습니다: {v}")
        return v


class Link(_Model):
    """방향 없는 연결. 항목↔항목(item_a·item_b, item_a < item_b) 또는 항목↔묶음(item·group) 중 한 모양"""

    schema_version: SchemaVersion = SCHEMA_VERSION
    link_id: LinkId
    item_a: ItemId | None = None
    item_b: ItemId | None = None
    item: ItemId | None = None
    group: GroupRef | None = None
    grade: Grade
    method: Method
    rule_id: NonEmptyStr
    evidence_text: NonEmptyStr
    evidence_locations: list[Location] = Field(min_length=1)
    needs_review: StrictBool
    profile_source: ProfileSource

    @model_validator(mode="after")
    def _shape_and_grade(self):
        pair = (self.item_a is not None, self.item_b is not None)
        to_group = (self.item is not None, self.group is not None)
        if not ((pair == (True, True) and to_group == (False, False)) or
                (pair == (False, False) and to_group == (True, True))):
            raise ValueError("연결은 item_a·item_b(항목↔항목) 또는 item·group(항목↔묶음) 중 정확히 한 모양이어야 합니다")
        if self.item_a is not None and not self.item_a < self.item_b:
            raise ValueError(f"item_a는 item_b보다 작아야 합니다(같은 연결을 한 모양으로): {self.item_a}, {self.item_b}")
        if METHOD_GRADE[self.method] != self.grade:
            raise ValueError(f"method {self.method}의 grade는 {METHOD_GRADE[self.method]}입니다: {self.grade}")
        if self.needs_review != (self.grade == "inferred"):
            raise ValueError("needs_review는 grade가 inferred일 때만 true입니다")
        return self


# ---------- 경고 ----------

class Warning_(_Model):
    """경고. 행 위치가 없는 파일·시트 단위 경고는 locations가 비고 file(·sheet)을 쓴다"""

    model_config = ConfigDict(extra="forbid", title="Warning")

    schema_version: SchemaVersion = SCHEMA_VERSION
    warning_id: WarningId
    kind: WarningKind
    message: NonEmptyStr
    item_ids: list[ItemId] = Field(default_factory=list)
    locations: list[Location] = Field(default_factory=list)
    file: NonEmptyStr | None = None
    sheet: NonEmptyStr | None = None

    @field_validator("file")
    @classmethod
    def _warning_file_name_only(cls, v):
        return _check_file_name(v)

    @model_validator(mode="after")
    def _file_when_no_location(self):
        if not self.locations and self.file is None:
            raise ValueError("locations가 비어 있으면 file이 있어야 합니다")
        return self


# ---------- 쓰는 쪽(si-prep link 모듈, rag_core)이 같이 쓰는 판단 함수 ----------

def step_key(step: str) -> str:
    """경로 한 단계의 비교 열쇠: 공백 제거·소문자"""
    return re.sub(r"\s+", "", step).lower()


def path_key(steps: Sequence[str | None]) -> tuple[str | None, ...]:
    """단계 목록의 비교 열쇠. 빈 단계는 None(어디에도 맞지 않음), 같은 단계가 이어지면 한 번만"""
    out = []
    for s in steps:
        k = None if s is None else step_key(s)
        if k is not None and out and out[-1] == k:
            continue
        out.append(k)
    return tuple(out)


def _group_steps(group_text: str) -> tuple[str | None, ...]:
    return path_key([s for s in group_text.split(PATH_SEP.strip())])


def path_starts_with(parts: Sequence[PathPart] | Sequence[str | None], group_text: str) -> bool:
    """항목 경로가 묶음 경로로 시작하는지 — **단계(PathPart) 단위** 앞부분 일치.
    글자 앞부분 비교가 아니다: 묶음 "회원"은 "회원가입 › …" 항목에 걸리지 않는다."""
    steps = [p.value if isinstance(p, PathPart) else p for p in parts]
    item, group = path_key(steps), _group_steps(group_text)
    if not group or None in group or len(item) < len(group):
        return False
    return item[:len(group)] == group


INFERRED_BASES = ("filled_down", "empty")   # 추정 경로 단계: 확정 연결의 근거로 쓰지 않음.
                                            # form_filled(사람 선언)·table_title(원문 제목 칸)은 넣지 않는다


def has_inferred_step(parts) -> bool:
    """경로에 추정 단계(filled_down·empty)가 있는지. status가 우선순위로 unparsed여도 경로로 판단한다.
    si-prep의 연결 판단과 rag_core의 묶음 펼치기(group_contains)가 같은 규칙을 쓰기 위해 여기 하나만 둔다"""
    return any(p.basis in INFERRED_BASES for p in parts)


def group_contains(group: GroupRef, item: Item) -> bool:
    """항목이 묶음에 드는지: 같은 문서 종류이고, (sheets가 있으면) 그 시트의 항목이고, 추정 경로 항목이 아니고,
    경로가 단계 단위로 묶음 경로로 시작"""
    if group.sheets is not None and item.locations[0].sheet not in group.sheets:
        return False
    if has_inferred_step(item.category_path):
        return False
    return item.doc_type == group.doc_type and path_starts_with(item.category_path, group.category_path_text)


def _link_key(link: Link | dict):
    get = link.get if isinstance(link, dict) else lambda k: getattr(link, k)
    if get("item_a") is not None:
        a, b = sorted([get("item_a"), get("item_b")])  # 순서만 바꾼 짝도 같은 연결
        return (get("rule_id"), a, b)
    group = get("group")
    g = group if isinstance(group, dict) else group.model_dump()
    key = (g["doc_type"], _group_steps(g["category_path_text"]))
    if g.get("sheets") is not None:   # 1.2: 시트 범위가 다르면 다른 묶음
        key += (tuple(g["sheets"]),)
    return (get("rule_id"), get("item"), key)


def find_duplicate_links(links: Iterable[Link | dict]) -> list[tuple]:
    """같은 규칙에서 같은 짝(순서 무관)·같은 항목↔묶음이 두 번 이상 나온 열쇠 목록. 없으면 []"""
    seen, dups = set(), []
    for link in links:
        key = _link_key(link)
        if key in seen and key not in dups:
            dups.append(key)
        seen.add(key)
    return dups
