"""프로젝트 설정(project.yaml) 읽기·검사.

검사는 실행 전에 전부 한다. 틀린 곳이 하나라도 있으면 어떤 출력도 만들지 않고, 틀린 곳을 모두 모아
ConfigError 하나로 보여 준다(번호 목록, 위치 = 파일 이름 + 키 경로).

두 단계로 검사한다.
  1. 모양 검사(pydantic): 오타 키·타입·필수 키·보기 값·규칙 하나 안에서 판단되는 조건
  2. 서로 맞는지 검사(원래 YAML 값으로): 선언 여부·중복·파일 존재·용어 사전 내용.
     1단계에서 망가진 부분은 건너뛰고 나머지를 끝까지 본다.
프로필 내용이 있어야 판단되는 조건(연결 규칙 ↔ 프로필)은 check_project가 프로필을 읽은 뒤 검사한다.
"""

from collections import Counter
import difflib
from dataclasses import dataclass, field
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Literal, Union, get_args

import yaml
from pydantic import (
    BaseModel, ConfigDict, Field, PrivateAttr, StrictBool, StrictStr, StringConstraints, ValidationError,
    field_validator, model_validator,
)

DocTypeId = Annotated[StrictStr, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
NonEmptyStr = Annotated[StrictStr, StringConstraints(min_length=1)]
LinkKey = Literal["path", "sheet_to_path", "path_prefix", "id_ref", "glossary", "name_similarity"]
LINK_KEYS = list(get_args(LinkKey))              # 연결 등록표의 「알려진 이름」
SAME_TYPE_UNSUPPORTED_KEYS = ("id_ref", "sheet_to_path")   # docs: [x, x]로 쓸 수 없는 key

SHEET_SELECTORS = ("overview", "detail")       # 규칙 sheets 칸의 특별한 값
GLOSSARY_MATCH = ("exact", "prefix")
# check_content를 쓸 수 있는 key(+ glossary match: exact). id_ref는 항목↔항목이지만 실행에서 내용 비교를 하지 않아 뺌
CHECK_CONTENT_KEYS = ("path",)


class ConfigError(Exception):
    """설정 오류 목록. str()은 사람이 바로 고칠 수 있게 번호 목록으로 보여 준다"""

    def __init__(self, source, issues):
        self.source = str(source)
        self.issues = list(issues)
        super().__init__(str(self))

    def __str__(self):
        lines = [f"설정 오류 {len(self.issues)}개 ({self.source})"]
        lines += [f" {n}. {msg}" for n, msg in enumerate(self.issues, 1)]
        return "\n".join(lines)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------- 모델 ----------

class DocTypeDecl(_Model):
    id: DocTypeId
    name: NonEmptyStr


def _relative_inside(path_text):
    """input_dir 안의 상대 경로만 (하위 폴더 허용, 절대 경로·.. 거부)"""
    for pure in (PurePosixPath(path_text), PureWindowsPath(path_text)):
        if pure.is_absolute() or pure.drive or ".." in pure.parts:
            return False
    return True


class DocumentEntry(_Model):
    doc_type: NonEmptyStr
    profile: NonEmptyStr
    files: list[NonEmptyStr] = Field(min_length=1)

    @field_validator("files")
    @classmethod
    def _files_inside_input_dir(cls, v):
        bad = [f for f in v if not _relative_inside(f)]
        if bad:
            raise ValueError(f"files에는 input_dir 안의 상대 경로만 씁니다(절대 경로·.. 금지): {bad}")
        return v


class LinkRule(_Model):
    id: NonEmptyStr
    docs: list[NonEmptyStr] = Field(min_length=2, max_length=2)
    key: LinkKey
    group: NonEmptyStr | None = None
    sheets: list[Any] | None = None
    check_content: StrictBool = False
    options: dict[StrictStr, Any] | None = None

    @field_validator("sheets")
    @classmethod
    def _sheets_two_slots(cls, v):
        if v is None:
            return v
        if len(v) != 2:
            raise ValueError(f"sheets는 docs와 같은 순서의 2칸이어야 합니다(지금 {len(v)}칸)")
        for i, slot in enumerate(v):
            ok = slot is None or slot in SHEET_SELECTORS or (
                isinstance(slot, list) and slot and all(isinstance(s, str) and s for s in slot))
            if not ok:
                raise ValueError(f"sheets[{i}]는 overview / detail / 시트 이름·패턴 목록 / null 중 하나여야 합니다(지금 {slot!r})")
        return v

    @model_validator(mode="after")
    def _key_conditions(self):
        options = self.options or {}
        match = options.get("match")
        if self.key == "glossary":
            unknown = sorted(set(options) - {"match"})
            if unknown:
                raise ValueError(f"glossary 규칙의 options에 모르는 키가 있습니다: {unknown} (쓸 수 있는 키: match)")
            if match not in GLOSSARY_MATCH:
                raise ValueError(f"glossary 규칙은 options.match가 exact 또는 prefix여야 합니다(지금 {match!r})")
        elif options:
            raise ValueError(f"options는 glossary 규칙에서만 씁니다(key={self.key})")
        if self.key in SAME_TYPE_UNSUPPORTED_KEYS and self.docs[0] == self.docs[1]:
            # 찾는 쪽을 프로필(ref_ids·root_separators)로 가르는데, 같은 종류면 양쪽이 같은 프로필이라 가를 수 없음
            raise ValueError("같은 문서 종류끼리 잇는 id_ref·sheet_to_path 규칙은 아직 지원하지 않습니다"
                             f"(docs {self.docs})")
        needs_group = self.key == "path_prefix" or (self.key == "glossary" and match == "prefix")
        if needs_group and self.group is None:
            raise ValueError(f"key={self.key}{' (match: prefix)' if self.key == 'glossary' else ''} 규칙은 "
                             "group(묶음이 되는 문서 종류)이 필요합니다")
        if not needs_group and self.group is not None:
            raise ValueError(f"group은 path_prefix·glossary(prefix) 규칙에서만 씁니다(key={self.key})")
        if self.group is not None and self.group not in self.docs:
            raise ValueError(f"group {self.group!r}는 docs {self.docs} 중 하나여야 합니다")
        compares = self.key in CHECK_CONTENT_KEYS or (self.key == "glossary" and match == "exact")
        if self.check_content and not compares:
            raise ValueError("check_content는 path·glossary(match: exact) 연결 규칙에서만 씁니다"
                             f"(key={self.key}, id_ref·묶음 규칙은 내용 비교를 하지 않음)")
        return self


class Glossary(_Model):
    """용어 사전: 한 묶음 안의 말은 같은 것으로 본다. 첫 번째가 대표어"""

    approved: StrictBool = False
    groups: list[list[NonEmptyStr]]

    @field_validator("groups")
    @classmethod
    def _groups(cls, v):
        from si_prep.schema import step_key
        seen, seen_key = {}, {}
        for i, group in enumerate(v):
            if len(group) < 2:
                raise ValueError(f"groups[{i}]는 2단어 이상이어야 합니다(지금 {len(group)}단어)")   # 단어(셀 내용)는 넣지 않음
            for word in group:
                if word in seen:
                    raise ValueError(f"groups[{seen[word]}]와 groups[{i}]에 같은 단어가 함께 있습니다(한 단어는 한 묶음에만)")
                k = step_key(word)   # 연결은 비교 열쇠로 하므로 표기만 다른 같은 단어도 한 묶음에만
                if seen_key.get(k, i) != i:
                    raise ValueError(f"groups[{seen_key[k]}]와 groups[{i}]에 표기만 다른 같은 단어가 함께 있습니다"
                                     "(띄어쓰기·대소문자를 빼면 같음, 한 단어는 한 묶음에만)")
                seen[word] = i
                seen_key.setdefault(k, i)
        return v


class ProjectConfig(_Model):
    project: NonEmptyStr
    approved: StrictBool = False
    input_dir: NonEmptyStr
    glossary: NonEmptyStr | None = None
    doc_types: list[DocTypeDecl] = Field(min_length=1)
    documents: list[DocumentEntry] = Field(min_length=1)
    link_rules: list[LinkRule] = Field(default_factory=list)
    # 앞이 우선. 안쪽 목록 = 같은 순위([req, [fo, bo], policy]). 적지 않은 종류는 「나머지」(같은 순위).
    # 칸 하나하나의 검사(글자·빈 묶음·묶음 안 묶음·선언·중복)는 2단계(_cross_checks)에서 위치를 붙여 한다
    doc_priority: list[Any] | None = None

    _base_dir: Path = PrivateAttr(default=Path("."))
    _glossary_data: Glossary | None = PrivateAttr(default=None)

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    @property
    def input_path(self) -> Path:
        return _resolve(self._base_dir, self.input_dir)

    def profile_path(self, entry: DocumentEntry) -> Path:
        return _resolve(self._base_dir, entry.profile)

    @property
    def glossary_data(self) -> Glossary | None:
        return self._glossary_data

    @property
    def priority_tiers(self) -> list[list[str]]:
        """순위 묶음 목록(앞이 우선). [req, [fo, bo], policy] → [[req], [fo, bo], [policy]]. 없으면 []"""
        return [list(t) if isinstance(t, list) else [t] for t in self.doc_priority or []]

    def priority_rank(self, doc_type: str) -> int | None:
        """순위 번호(0이 가장 우선). 같은 묶음은 같은 번호. 적지 않은 종류는 None(나머지)"""
        for rank, tier in enumerate(self.priority_tiers):
            if doc_type in tier:
                return rank
        return None


def _resolve(base, path_text):
    p = Path(path_text)
    return p if p.is_absolute() else base / p


# ---------- 1단계: 모양 검사 오류를 읽기 쉬운 문장으로 ----------

_FIELDS_AT = {(): ProjectConfig, ("doc_types",): DocTypeDecl, ("documents",): DocumentEntry,
              ("link_rules",): LinkRule}


def _where(raw, loc):
    """키 경로 글자: link_rules[3] (id=policy_fo).docs"""
    out, node = "", raw
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
            node = node[part] if isinstance(node, list) and part < len(node) else None
            if isinstance(node, dict) and isinstance(node.get("id"), str) and out.startswith("link_rules"):
                out += f" (id={node['id']})"
        else:
            out += ("." if out else "") + str(part)
            node = node.get(part) if isinstance(node, dict) else None
    return out or "(최상위)"


def _known_fields(loc, fields_at=None):
    shape = tuple(p for p in loc[:-1] if not isinstance(p, int))
    model = (fields_at or _FIELDS_AT).get(shape)
    return list(model.model_fields) if model else []


def _suggest(word, choices):
    close = difflib.get_close_matches(str(word), [str(c) for c in choices], n=1, cutoff=0.6)
    return f' 혹시 "{close[0]}"인가요?' if close else ""


def _friendly(raw, err, fields_at=None):
    loc, kind = err["loc"], err["type"]
    where = _where(raw, loc)
    if kind == "union_tag_invalid":  # 모르는 방식 이름(hierarchy·item_boundary의 method)
        ctx = err.get("ctx", {})
        tags = [t.strip(" '") for t in str(ctx.get("expected_tags", "")).split(",") if t.strip()]
        return (f'{where}: 모르는 method "{ctx.get("tag")}"입니다. 쓸 수 있는 method: {", ".join(tags)}.'
                f'{_suggest(ctx.get("tag"), tags)}')
    if kind == "extra_forbidden":
        parent = _where(raw, loc[:-1])
        return f'{parent}: 모르는 키 "{loc[-1]}"가 있습니다.{_suggest(loc[-1], _known_fields(loc, fields_at))}'
    if kind == "missing":
        return f"{where}: 필수 키가 없습니다"
    if kind == "literal_error" and loc[-1] == "key":
        choices = LinkKey.__args__
        return (f'{where}: 모르는 key "{err.get("input")}"입니다. 쓸 수 있는 key: {", ".join(choices)}.'
                f'{_suggest(err.get("input"), choices)}')
    if kind in ("string_type", "bool_type", "list_type", "dict_type"):
        want = {"string_type": "글자", "bool_type": "true/false", "list_type": "목록", "dict_type": "키: 값 묶음"}[kind]
        return f"{where}: {want}여야 합니다(지금 {err.get('input')!r})"
    if kind in ("too_short", "too_long") and loc and loc[-1] == "docs":
        return f"{where}: docs는 문서 종류가 정확히 2개여야 합니다(지금 {len(err.get('input') or [])}개)"
    if kind == "string_pattern_mismatch" and loc and loc[-1] == "id":
        return f"{where}: 문서 종류 id는 영문 소문자로 시작하고 영문 소문자·숫자·_만 씁니다(지금 {err.get('input')!r})"
    if kind == "value_error":
        return f"{where}: {err['msg'].removeprefix('Value error, ')}"
    return f"{where}: {err['msg']}"


# ---------- 2단계: 서로 맞는지 검사 (원래 YAML 값으로, 망가진 부분은 건너뜀) ----------

def _dicts(raw, key):
    value = raw.get(key)
    return [(i, d) for i, d in enumerate(value) if isinstance(d, dict)] if isinstance(value, list) else []


def _duplicates(values):
    seen, dups = set(), []
    for v in values:
        if v in seen and v not in dups:
            dups.append(v)
        seen.add(v)
    return dups


def _cross_checks(raw, base):
    issues = []
    declared = [d.get("id") for _, d in _dicts(raw, "doc_types") if isinstance(d.get("id"), str)]
    for dup in _duplicates(declared):
        issues.append(f'doc_types: 문서 종류 id "{dup}"가 두 번 이상 선언됐습니다')
    names = ", ".join(declared)

    def undeclared(where, value):
        if isinstance(value, str) and value not in declared:
            issues.append(f'{where}: "{value}"는 doc_types에 선언되지 않았습니다. 선언된 종류: {names}')

    input_dir = raw.get("input_dir")
    input_ok = isinstance(input_dir, str) and _resolve(base, input_dir).is_dir()
    if isinstance(input_dir, str) and not input_ok:
        issues.append(f"input_dir: 폴더가 없습니다: {_resolve(base, input_dir)}")

    registered = []
    for i, doc in _dicts(raw, "documents"):
        undeclared(f"documents[{i}].doc_type", doc.get("doc_type"))
        profile = doc.get("profile")
        if isinstance(profile, str) and not _resolve(base, profile).is_file():
            issues.append(f"documents[{i}].profile: 프로필 파일이 없습니다: {_resolve(base, profile)}")
        files = doc.get("files")
        for f in files if isinstance(files, list) else []:
            if not isinstance(f, str) or not _relative_inside(f):
                continue
            key = PurePosixPath(f.replace("\\", "/")).as_posix()
            if key in registered:
                issues.append(f'documents[{i}].files: 파일 "{f}"가 두 번 등록됐습니다(같은 파일 두 번 등록 금지)')
            registered.append(key)
            if input_ok and not (_resolve(base, input_dir) / f).is_file():
                issues.append(f'documents[{i}].files: input_dir에 파일이 없습니다: "{f}"')

    rules = _dicts(raw, "link_rules")
    for dup in _duplicates([r.get("id") for _, r in rules if isinstance(r.get("id"), str)]):
        issues.append(f'link_rules: 규칙 id "{dup}"가 두 번 이상 있습니다')
    for i, rule in rules:
        where = _where(raw, ("link_rules", i))
        for j, d in enumerate(rule.get("docs") or [] if isinstance(rule.get("docs"), list) else []):
            undeclared(f"{where}.docs[{j}]", d)

    glossary = raw.get("glossary")
    if any(r.get("key") == "glossary" for _, r in rules) and glossary is None:
        first = next(_where(raw, ("link_rules", i)) for i, r in rules if r.get("key") == "glossary")
        issues.append(f"{first}: key가 glossary인데 용어 사전이 없습니다. 최상위에 glossary: <파일 경로>를 추가하세요")
    glossary_data = None
    if isinstance(glossary, str):
        path = _resolve(base, glossary)
        if not path.is_file():
            issues.append(f"glossary: 용어 사전 파일이 없습니다: {path}")
        else:
            try:
                data = _read_yaml(path, "용어 사전")
                glossary_data = Glossary.model_validate(data)
            except ConfigError as e:
                issues += [f"{path.name}: {msg}" for msg in e.issues]
            except ValidationError as e:
                lines = _safe_group_lines(path)
                issues += [f"{path.name}: " + _with_lines(_friendly(data or {}, err), lines) for err in e.errors()]

    issues += _priority_issues(raw.get("doc_priority"), undeclared)
    return issues, glossary_data


def _priority_issues(priority, undeclared):
    """doc_priority 칸 검사. 안쪽 목록 = 같은 순위(한 단계만, 한 개짜리 허용)"""
    if not isinstance(priority, list):
        return []  # 목록이 아니면 1단계(모양 검사)에서 알림
    issues, places = [], {}

    def entry(where, value):
        if isinstance(value, list):
            issues.append(f"{where}: 묶음 안에 또 묶음을 쓸 수 없습니다(같은 순위는 한 단계만)")
        elif not isinstance(value, str) or not value:
            issues.append(f"{where}: 문서 종류 id(글자)여야 합니다(지금 {value!r})")
        else:
            undeclared(where, value)
            places.setdefault(value, []).append(where)

    for j, item in enumerate(priority):
        if isinstance(item, list):
            if not item:
                issues.append(f"doc_priority[{j}]: 같은 순위 묶음이 비어 있습니다. 문서 종류를 1개 이상 적거나 묶음을 지우세요")
            for k, value in enumerate(item):
                entry(f"doc_priority[{j}][{k}]", value)
        else:
            entry(f"doc_priority[{j}]", item)
    for value, where in places.items():
        if len(where) > 1:
            issues.append(f'doc_priority: "{value}"가 두 번 이상 있습니다({", ".join(where)}). 한 종류는 한 순위에만 적으세요')
    return issues


# ---------- 읽기 ----------

def _read_yaml(path, what):
    """YAML 파일 읽기. 읽지 못하면 이유를 적은 ConfigError (traceback으로 끝나지 않게)"""
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ConfigError(path, [f"{what} 파일이 없습니다: {path}"]) from None
    except UnicodeDecodeError:
        raise ConfigError(path, [f"UTF-8로 읽을 수 없습니다. 파일을 UTF-8로 저장하세요: {path}"]) from None
    except OSError as e:
        raise ConfigError(path, [f"{what} 파일을 읽을 수 없습니다({e.strerror}): {path}"]) from None
    except yaml.YAMLError as e:
        raise ConfigError(path, [f"YAML 문법 오류: {e}"]) from None


def _safe_group_lines(path):
    try:
        return glossary_group_lines(path)
    except (OSError, yaml.YAMLError):
        return []


def _with_lines(message, lines):
    """오류 문장의 groups[i]에 줄 번호를 붙인다(groups[i](N줄)) — 사전 단어 대신 위치로 알리기 위해"""
    return re.sub(r"groups\[(\d+)\]", lambda m: f"groups[{m.group(1)}]({lines[int(m.group(1))]}줄)"
                  if int(m.group(1)) < len(lines) else m.group(0), message)


def load_project(path, ignore_glossary: bool = False) -> ProjectConfig:
    """project.yaml을 읽고 전부 검사한다. 틀린 곳이 있으면 모두 모아 ConfigError.
    ignore_glossary: 용어 사전과 glossary 규칙을 빼고 읽는다(용어 사전 초안 도구가 깨진 사전 없이 돌 때)"""
    path = Path(path)
    base = path.parent
    raw = _read_yaml(path, "설정")
    if not isinstance(raw, dict):
        raise ConfigError(path, ["최상위는 키: 값 묶음이어야 합니다"])
    if ignore_glossary:
        raw = dict(raw)
        raw.pop("glossary", None)
        if isinstance(raw.get("link_rules"), list):
            raw["link_rules"] = [r for r in raw["link_rules"] if not (isinstance(r, dict) and r.get("key") == "glossary")]

    issues, config = [], None
    try:
        config = ProjectConfig.model_validate(raw)
    except ValidationError as e:
        issues += [_friendly(raw, err) for err in e.errors()]
    cross, glossary_data = _cross_checks(raw, base)
    issues += cross
    if issues:
        raise ConfigError(path, issues)
    config._base_dir = base
    config._glossary_data = glossary_data
    return config


# ======================================================================
# 문서별 프로필 (profiles/*.yaml)
# 6-1: 모델과 단독 검사(엑셀을 열지 않음). 엑셀 시트 대조는 6c, 머리글 못 찾음 오류는 9a
# ======================================================================

StrictPosInt = Annotated[int, Field(strict=True, ge=1)]
ColumnLetter = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{1,3}$")]
DEFAULT_NUMBER_PATTERN = r"^\d+(\.\d+)*$"


def _check_regex(v, what="정규식"):
    if v is None:
        return v
    try:
        re.compile(v)
    except re.error as e:
        raise ValueError(f"{what}이 잘못됐습니다: {v!r} ({e})") from None
    return v


class SheetEntry(_Model):
    """시트 한 줄: name은 시트 이름 또는 *·? 패턴, read 기본 true(읽음). 뺌(read: false)이면 reason 필수"""

    name: NonEmptyStr
    read: StrictBool = True
    reason: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _reason_when_skipped(self):
        if not self.read and self.reason is None:
            raise ValueError(f'시트 "{self.name}"를 뺌(read: false)으로 하려면 reason(이유)을 적어야 합니다')
        return self


class Selector(_Model):
    """열 선택자: header_contains / col / header_pattern(+all: true, hierarchy 전용) 중 정확히 하나"""

    header_contains: NonEmptyStr | None = None
    col: StrictStr | None = None
    header_pattern: NonEmptyStr | None = None
    all: StrictBool | None = None

    @field_validator("col")
    @classmethod
    def _col_letters(cls, v):
        if v is not None and not re.fullmatch(r"[A-Z]{1,3}", v):
            raise ValueError(f"col은 열 문자(A~ZZZ 대문자)여야 합니다(지금 {v!r})")
        return v

    @model_validator(mode="after")
    def _exactly_one(self):
        given = [k for k in ("header_contains", "col", "header_pattern") if getattr(self, k) is not None]
        if len(given) != 1:
            raise ValueError("선택자는 header_contains·col·header_pattern 중 정확히 하나여야 합니다"
                             f"(지금 {given or '없음'})")
        if self.header_pattern is not None:
            _check_regex(self.header_pattern, "header_pattern 정규식")
            if self.all is not True:
                raise ValueError("header_pattern은 all: true와 함께 씁니다(맞는 열 전부를 펼침)")
        elif self.all is not None:
            raise ValueError("all은 header_pattern과 함께만 씁니다")
        return self


class RefIdsSelector(Selector):
    """참조 ID 열: 선택자 + 칸에서 ID를 찾을 정규식"""

    pattern: NonEmptyStr
    # 줄임 표기 펼치기(B2): 「X-2101, 2103」처럼 앞 ID 뒤에 숫자만 있는 조각을 앞 ID의 앞부분으로 펼쳐 연결에만 쓴다
    expand_short: StrictBool = False

    @field_validator("pattern")
    @classmethod
    def _pattern_regex(cls, v):
        return _check_regex(v, "ref_ids pattern 정규식")


def _no_pattern(v, role):
    for sel in v if isinstance(v, list) else [v]:
        if sel is not None and sel.header_pattern is not None:
            raise ValueError(f"header_pattern 선택자는 hierarchy에서만 씁니다({role})")
    return v


class Columns(_Model):
    hierarchy: list[Selector] = Field(default_factory=list)
    id: Selector | None = None
    ref_ids: RefIdsSelector | None = None
    title: Selector | None = None
    description: Selector | None = None
    exclude_from_text: list[Selector] = Field(default_factory=list)

    @field_validator("id", "ref_ids", "title", "description", "exclude_from_text")
    @classmethod
    def _pattern_only_in_hierarchy(cls, v, info):
        return _no_pattern(v, info.field_name)


class ColumnsMethod(_Model):
    method: Literal["columns"]
    fill_down: StrictBool = False
    # 사람 선언: 이 시트는 병합 없는 빈칸이 「위와 같음」인 양식 → 채운 단계는 form_filled(추정 아님)
    blank_means_above: StrictBool = False
    # 테두리 묶음(B1): 선언 시트에서 같은 테두리 묶음(칸 사이 가로 선 없음) 안의 빈칸만 위 값으로 채운다
    border_groups: StrictBool = False

    @model_validator(mode="after")
    def _declaration_needs_fill_down(self):
        if self.blank_means_above and not self.fill_down:
            raise ValueError("blank_means_above는 fill_down: true와 함께 씁니다(빈칸을 위 값으로 채우는 선언)")
        if self.border_groups and not self.blank_means_above:
            raise ValueError("border_groups는 blank_means_above: true와 함께 씁니다(선언 시트에서 테두리 묶음 안만 채움)")
        return self


class SplitCellMethod(_Model):
    method: Literal["split_cell"]
    separators: list[NonEmptyStr] = Field(min_length=1)


class NumberingMethod(_Model):
    method: Literal["numbering"]
    number_pattern: NonEmptyStr = DEFAULT_NUMBER_PATTERN

    @field_validator("number_pattern")
    @classmethod
    def _number_regex(cls, v):
        return _check_regex(v, "number_pattern 정규식")


class NoneMethod(_Model):
    method: Literal["none"]


class IndentMethod(_Model):  # 알려졌지만 미구현 → 실행 때 unsupported
    method: Literal["indent"]


class ParentIdMethod(_Model):  # 알려졌지만 미구현 → 실행 때 unsupported
    method: Literal["parent_id"]


Hierarchy = Annotated[Union[ColumnsMethod, SplitCellMethod, NumberingMethod, NoneMethod, IndentMethod, ParentIdMethod],
                      Field(discriminator="method")]


class RowBoundary(_Model):
    method: Literal["row"]


class ContinuationBoundary(_Model):
    method: Literal["continuation"]
    key_role: Literal["id", "hierarchy"] = "id"


class MergedBlockBoundary(_Model):  # 알려졌지만 미구현
    method: Literal["merged_block"]


ItemBoundary = Annotated[Union[RowBoundary, ContinuationBoundary, MergedBlockBoundary], Field(discriminator="method")]


def _method_names(union):
    """판별 유니온의 method 값 목록 = 설정에서 고를 수 있는 「알려진 이름」(등록표가 받는다)"""
    return [get_args(m.model_fields["method"].annotation)[0] for m in get_args(get_args(union)[0])]


HIERARCHY_METHODS = _method_names(Hierarchy)
ITEM_BOUNDARY_METHODS = _method_names(ItemBoundary)


class VersionSpec(_Model):
    cover_sheet: NonEmptyStr | None = None
    label_pattern: NonEmptyStr | None = None
    filename_pattern: NonEmptyStr | None = None

    @field_validator("label_pattern")
    @classmethod
    def _label_regex(cls, v):
        return _check_regex(v, "label_pattern 정규식")

    @field_validator("filename_pattern")
    @classmethod
    def _filename_regex(cls, v):
        _check_regex(v, "filename_pattern 정규식")
        if v is not None and re.compile(v).groups < 1:
            raise ValueError(f"filename_pattern에는 버전을 잡는 그룹 (…)이 1개 이상 있어야 합니다(그룹 1이 버전): {v!r}")
        return v


class TableTitleRow(_Model):
    """표 제목 행 신호: 원문 값(병합 복원 전)이 이 열들에만 있는 행"""
    only_columns: list[ColumnLetter] = Field(min_length=1)


class TableHeaderRow(_Model):
    """표 머리글 신호: 제목 행 + offset 행의 col 칸 원문 값이 pattern(정규식, search)에 맞음.
    rows: 표마다 머리글 줄 수 — fixed(기본)는 프로필 header_rows의 줄 수, merge는 신호 칸의 세로 병합 높이
    (병합 없음·가로 병합만이면 1줄, 4줄을 넘으면 그 표만 건너뜀)"""
    offset: StrictPosInt = 1
    col: ColumnLetter
    pattern: NonEmptyStr
    rows: Literal["fixed", "merge"] = "fixed"

    @field_validator("pattern")
    @classmethod
    def _header_regex(cls, v):
        return _check_regex(v, "tables.header_row.pattern 정규식")


class Tables(_Model):
    """한 시트에 표 여러 개: 제목 행 신호 + 머리글 신호가 둘 다 맞는 행에서 표가 시작된다.
    머리글 줄 수는 header_row.rows(기본 fixed = header_rows의 줄 수), 데이터는 머리글 다음 행부터 다음 표 제목 앞까지(stop_markers는 표마다).
    title_to: path면 제목을 경로 단계(table_title)로, none이면 넣지 않음.
    first_without_title: true면 첫 제목 표보다 위, 위쪽 행이 모두 빈(또는 시트 맨 위) 머리글 신호 행부터 「제목 없는 표」
    하나를 읽는다(경로에 제목 단계 없음)"""
    title_row: TableTitleRow
    header_row: TableHeaderRow
    title_to: Literal["path", "none"] = "path"
    first_without_title: StrictBool = False


# 시트별로 덮어쓸 수 있는 키 (최상위 키 단위)
OVERRIDABLE = ("header_rows", "data_start_row", "stop_markers", "columns", "hidden_rows", "hierarchy",
               "item_boundary", "sheet_as_root", "root_separators", "id_pattern", "table_gap_rows", "tables")


class SheetOverride(_Model):
    sheets: list[NonEmptyStr] = Field(min_length=1)
    header_rows: list[StrictPosInt] | None = Field(default=None, min_length=1)
    data_start_row: StrictPosInt | None = None
    stop_markers: list[NonEmptyStr] | None = None
    columns: Columns | None = None
    hidden_rows: Literal["include", "skip"] | None = None
    hierarchy: Hierarchy | None = None
    item_boundary: ItemBoundary | None = None
    sheet_as_root: StrictBool | None = None
    root_separators: list[NonEmptyStr] | None = None
    id_pattern: NonEmptyStr | None = None
    table_gap_rows: StrictPosInt | None = None
    tables: Tables | None = None

    @field_validator("id_pattern")
    @classmethod
    def _id_regex(cls, v):
        return _check_regex(v, "id_pattern 정규식")


class Profile(_Model):
    id: NonEmptyStr
    approved: StrictBool = False
    sheets: list[SheetEntry] | None = None
    header_rows: list[StrictPosInt] = Field(min_length=1)
    data_start_row: StrictPosInt
    stop_markers: list[NonEmptyStr] = Field(default_factory=list)
    columns: Columns
    hidden_rows: Literal["include", "skip"] = "include"
    hierarchy: Hierarchy
    item_boundary: ItemBoundary
    sheet_as_root: StrictBool = False
    root_separators: list[NonEmptyStr] | None = None
    overview_sheets: list[NonEmptyStr] | None = None
    version: VersionSpec | None = None
    id_pattern: NonEmptyStr | None = None
    table_gap_rows: StrictPosInt = 2
    tables: Tables | None = None          # 한 시트 여러 표. 없으면 시트 하나 = 표 하나(지금 그대로)
    sheet_overrides: list[SheetOverride] = Field(default_factory=list)

    @field_validator("id_pattern")
    @classmethod
    def _id_regex(cls, v):
        return _check_regex(v, "id_pattern 정규식")

    @field_validator("sheets")
    @classmethod
    def _sheet_names_unique(cls, v):
        for dup in _duplicates([s.name for s in v or []]):
            raise ValueError(f'"{dup}"이 두 번 이상 있습니다(시트 이름·패턴은 한 번만)')
        return v


_PROFILE_FIELDS_AT = {(): Profile, ("columns",): Columns, ("sheets",): SheetEntry, ("sheet_overrides",): SheetOverride,
                      ("version",): VersionSpec, ("columns", "hierarchy"): Selector, ("columns", "id"): Selector,
                      ("columns", "title"): Selector, ("columns", "description"): Selector,
                      ("columns", "exclude_from_text"): Selector, ("columns", "ref_ids"): RefIdsSelector,
                      ("sheet_overrides", "columns"): Columns, ("tables",): Tables, ("tables", "title_row"): TableTitleRow,
                      ("tables", "header_row"): TableHeaderRow, ("sheet_overrides", "tables"): Tables,
                      ("sheet_overrides", "tables", "title_row"): TableTitleRow,
                      ("sheet_overrides", "tables", "header_row"): TableHeaderRow}
# 덮어쓰기 안 columns의 선택자도 같은 모델 (모르는 키 「혹시 …」 추천을 위해)
_PROFILE_FIELDS_AT.update({("sheet_overrides",) + k: v for k, v in list(_PROFILE_FIELDS_AT.items())
                           if k[:1] == ("columns",) and len(k) == 2})


def _name_regex(pattern):
    """시트 이름 패턴 → 정규식. *(아무 글자 0개 이상)와 ?(한 글자)만 패턴이고 [ ] 등은 글자 그대로"""
    return re.compile("".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern), re.DOTALL)


def sheet_matches(sheet, names):
    """시트 이름·*·? 패턴(대소문자 구분)"""
    return any(_name_regex(n).fullmatch(sheet) for n in names)


def _apply_override(profile, override):
    update = {k: getattr(override, k) for k in OVERRIDABLE if k in override.model_fields_set}
    return profile.model_copy(update=update)


def sheet_profile(profile: Profile, sheet: str) -> Profile:
    """그 시트에 적용되는 프로필: 맞는 sheet_overrides를 순서대로 최상위 키 단위로 덮어씀"""
    for override in profile.sheet_overrides:
        if sheet_matches(sheet, override.sheets):
            profile = _apply_override(profile, override)
    return profile


def _effective_issues(p, where=""):
    """한 시트에 실제로 적용될 값들이 서로 맞는지 (기본값, 덮어쓴 결과 각각)"""
    issues = []
    if p.data_start_row <= max(p.header_rows):
        issues.append(f"{where}data_start_row({p.data_start_row})는 헤더 행({max(p.header_rows)})보다 커야 합니다")
    method, cols = p.hierarchy.method, p.columns
    plain = [s for s in cols.hierarchy if s.header_pattern is None]
    if method == "columns" and not cols.hierarchy:
        issues.append(f"{where}columns.hierarchy: hierarchy method가 columns인데 분류 열 선택자가 없습니다")
    if method == "split_cell" and (len(cols.hierarchy) != 1 or len(plain) != 1):
        issues.append(f"{where}columns.hierarchy: split_cell은 한 칸을 쪼개므로 분류 열 선택자가 하나여야 합니다"
                      f"(지금 {len(cols.hierarchy)}개, header_pattern 불가)")
    if method == "numbering":
        if len(cols.hierarchy) != 1 or len(plain) != 1:
            issues.append(f"{where}columns.hierarchy: numbering은 번호 열 하나를 씁니다(지금 {len(cols.hierarchy)}개)")
        if cols.title is None:
            issues.append(f"{where}columns.title: numbering은 이름 열(title)이 필요합니다")
    boundary = p.item_boundary
    if boundary.method == "continuation":
        if boundary.key_role == "id" and cols.id is None:
            issues.append(f"{where}columns.id: item_boundary가 continuation(key_role: id)이면 id 열이 필요합니다")
        if boundary.key_role == "hierarchy" and not cols.hierarchy:
            issues.append(f"{where}columns.hierarchy: continuation(key_role: hierarchy)이면 분류 열이 필요합니다")
    return issues


def _raw_profile_checks(raw):
    """모양 검사가 실패했을 때도 원래 YAML 값으로 할 수 있는 검사 (틀린 곳을 한 번에 모아 보이기 위해)"""
    rows, start = raw.get("header_rows"), raw.get("data_start_row")
    if isinstance(rows, list) and rows and all(isinstance(r, int) for r in rows) and isinstance(start, int) \
            and start <= max(rows):
        return [f"data_start_row({start})는 헤더 행({max(rows)})보다 커야 합니다"]
    return []


def _profile_issues(profile):
    issues = _effective_issues(profile)
    for i, override in enumerate(profile.sheet_overrides):
        issues += _effective_issues(_apply_override(profile, override), f"sheet_overrides[{i}] {override.sheets}: ")
    return issues


def load_profile(path) -> Profile:
    """프로필 YAML을 읽고 단독 검사를 전부 한다. 틀린 곳이 있으면 모두 모아 ConfigError (엑셀은 열지 않음)"""
    path = Path(path)
    raw = _read_yaml(path, "프로필")
    if not isinstance(raw, dict):
        raise ConfigError(path, ["최상위는 키: 값 묶음이어야 합니다"])
    try:
        profile = Profile.model_validate(raw)
    except ValidationError as e:
        issues = [_friendly(raw, err, _PROFILE_FIELDS_AT) for err in e.errors()]
        raise ConfigError(path, issues + _raw_profile_checks(raw)) from None
    issues = _profile_issues(profile)
    if issues:
        raise ConfigError(path, issues)
    return profile


# ======================================================================
# 설정 검사 결과: 프로필 전체 읽기, [검토] 주석, 아직 만들지 않은 방식 경고, 시트별 표
# 엑셀은 열지 않는다. 엑셀 시트 대조(새 시트)는 6c, 머리글 못 찾음 오류는 9a
# ======================================================================

REVIEW_MARK = "[검토]"
UNSUPPORTED_NOTE = "방식은 아직 지원하지 않습니다. 실행 때 실패합니다."
HIDDEN_COL_MARK = "숨김 열"
EMPTY_COL_MARK = "값 없음"
UNIMPLEMENTED_KEY_NOTE = "설정 키는 아직 구현되지 않아 효과가 없습니다"
# 설정 형식에는 있지만 처리 코드가 아직 없는 키 → 설정 검사 경고(적혀 있을 때만). 키 → 무엇이 없는지
UNIMPLEMENTED_KEYS = {
    "table_gap_rows": "표 여러 개 감지(연속 빈 행 → 시트 건너뜀 + unsupported_layout)가 아직 없어 값과 상관없이 시트를 끝까지 읽습니다",
}


def glossary_group_lines(path) -> list:
    """용어 사전 파일에서 groups의 각 묶음이 시작하는 줄 번호(1부터). 글자는 돌려주지 않는다(화면에 단어를 내지 않게)"""
    node = yaml.compose(Path(path).read_text(encoding="utf-8"))
    for key, value in getattr(node, "value", []):
        if getattr(key, "value", None) == "groups" and isinstance(value, yaml.SequenceNode):
            return [item.start_mark.line + 1 for item in value.value]
    return []


def profile_source(project_approved: bool, profile_approved: bool) -> str:
    """결과의 profile_source: 프로젝트 설정과 프로필이 모두 approved일 때만 approved, 아니면 auto(시험 실행).
    항목·연결이 같이 쓴다"""
    return "approved" if project_approved and profile_approved else "auto"


def unimplemented_methods():
    """아직 함수가 없는 방식: 등록표가 유일한 출처(설정 검사·실행이 같은 답). {키: 이름 목록}
    hierarchy·boundary는 config를 import하므로 여기서는 늦게 import한다"""
    from si_prep import boundary, hierarchy
    return {"hierarchy": hierarchy.REGISTRY.unimplemented(), "item_boundary": boundary.REGISTRY.unimplemented()}


def unimplemented_link_keys():
    """아직 함수가 없는 연결 key — 연결 등록표가 유일한 출처"""
    from si_prep import link
    return link.REGISTRY.unimplemented()
NOT_YET = "(실행 때)"  # 시트별 표의 항목 수·링크 수 칸은 실행 항목에서 채운다


@dataclass
class SheetRow:
    doc_type: str
    document: str       # 표의 문서 칸: 문서 종류(같은 종류 문서가 여럿이면 "종류 (첫 파일)")
    sheet: str          # 프로필 sheets의 name(패턴일 수 있음)
    read: bool
    reason: str | None
    overview: bool
    new: bool = False   # 엑셀에 있는데 프로필 sheets 어느 줄에도 맞지 않는 시트(read_excel일 때만)


@dataclass
class DocumentResult:
    """documents 항목(파일) 하나의 검사 결과. 같은 문서 종류의 항목이 여럿이어도 덮이지 않는다"""

    index: int
    doc_type: str
    files: list
    profile_file: str   # project.yaml 기준 경로
    profile: Profile


@dataclass
class CheckResult:
    config: ProjectConfig
    documents: list = field(default_factory=list)         # DocumentResult, documents 순서
    warnings: list = field(default_factory=list)          # 설정 검사 경고(출력 warnings.jsonl과 별개)
    review_marks: dict = field(default_factory=dict)      # 파일(project.yaml 기준 경로) → 남은 [검토] 수
    sheet_rows: list = field(default_factory=list)
    header_report: list = field(default_factory=list)   # HeaderRow, --excel일 때만

    @property
    def profiles(self) -> dict:
        """문서 종류 → 그 종류 문서들의 프로필 목록(documents 순서)"""
        out = {}
        for d in self.documents:
            out.setdefault(d.doc_type, []).append(d.profile)
        return out


def _count_review_marks(path):
    """주석(# 뒤)에 [검토]가 있는 줄 수"""
    count = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        hash_at = line.find("#")
        if hash_at >= 0 and REVIEW_MARK in line[hash_at:]:
            count += 1
    return count


def _relative(base, path):
    try:
        return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _unimplemented_warnings(file_name, profile):
    out = []
    targets = [("", profile)] + [(f"sheet_overrides[{i}] {o.sheets} ", o) for i, o in enumerate(profile.sheet_overrides)]
    unimplemented = unimplemented_methods()
    for where, part in targets:
        for key, names in unimplemented.items():
            value = getattr(part, key, None)
            if value is not None and value.method in names:
                out.append(f"{file_name} {where}{key}: {value.method} {UNSUPPORTED_NOTE}")
        for key, what in UNIMPLEMENTED_KEYS.items():   # 기본값이 있어도 적은 경우만(model_fields_set)
            if key in part.model_fields_set:
                out.append(f"{file_name} {where}{key}: {UNIMPLEMENTED_KEY_NOTE} — {what}")
    return out


def _profile_entries(path, config):
    """읽을 프로필 목록 [(문서 순번, 문서 종류, 파일 목록, 프로필 경로)]. project.yaml에 오류가 있으면
    원래 YAML 값에서 경로를 알 수 있는 프로필만 (틀린 곳을 한 번에 보이기 위해)"""
    if config is not None:
        return [(i, d.doc_type, list(d.files), config.profile_path(d)) for i, d in enumerate(config.documents)]
    try:
        raw = _read_yaml(path, "설정")
    except ConfigError:
        return []   # 같은 이유를 load_project가 이미 오류로 보고함
    entries = []
    for i, doc in _dicts(raw if isinstance(raw, dict) else {}, "documents"):
        profile = doc.get("profile")
        if isinstance(profile, str) and _resolve(Path(path).parent, profile).is_file():
            files = [f for f in doc.get("files") or [] if isinstance(f, str)] if isinstance(doc.get("files"), list) else []
            entries.append((i, str(doc.get("doc_type")), files, _resolve(Path(path).parent, profile)))
    return entries


def _has(part, role):
    """프로필(또는 덮어쓰기 하나)의 columns에 그 역할 열이 있는지"""
    return part.columns is not None and getattr(part.columns, role) is not None


def _has_anywhere(profile, role):
    """기본값이나 어느 시트별 덮어쓰기에라도 그 역할 열이 있으면 True"""
    return any(_has(p, role) for p in [profile] + list(profile.sheet_overrides))


def _names_overlap(a, b):
    """시트 이름·패턴 두 개가 같은 시트를 가리킬 수 있는지(어느 쪽이든 패턴일 수 있음).
    한계: 둘 다 패턴이면 한쪽이 다른 쪽에 글자로 맞을 때만 겹친다고 본다("주문*"와 "*결제"는 안 겹침으로 봄)"""
    return sheet_matches(a, [b]) or sheet_matches(b, [a])


def slot_selects(name, profile, slot):
    """규칙의 한쪽 sheets 칸(None·overview·detail·이름 목록)이 이 시트 이름(패턴)을 고를 수 있는지"""
    overview = profile.overview_sheets or []
    if slot == "overview":
        return any(_names_overlap(name, o) for o in overview)
    if slot == "detail":
        return not sheet_matches(name, overview)
    if isinstance(slot, list):
        return any(_names_overlap(name, s) for s in slot)
    return True


def _read_sheet_names(profile):
    return [e.name for e in profile.sheets if e.read] if profile.sheets else None


def _check_content_issues(where, d, slot):
    """check_content: 규칙이 고르는 시트에 적용될 columns(기본값·맞는 덮어쓰기 각각)에 description이 있어야 한다"""
    p, out = d.profile, []
    names = _read_sheet_names(p)
    selected = [n for n in names if slot_selects(n, p, slot)] if names is not None else None
    if selected == []:
        return out   # 고르는 시트가 없음 → 경고 쪽(_slot_warnings)에서 알림
    overrides = [(i, o) for i, o in enumerate(p.sheet_overrides)
                 if o.columns is not None and any(slot_selects(n, p, slot) for n in o.sheets)
                 and (selected is None or any(_names_overlap(s, n) for s in selected for n in o.sheets))]
    # 기본 columns는 덮어쓰기로 columns가 바뀌지 않는 시트가 하나라도 있으면 쓰인다(sheets 목록이 없으면 늘 쓰일 수 있음)
    covered = [o for _, o in overrides]
    if selected is None:   # sheets 목록이 없으면 칸에 적힌 이름(overview는 overview_sheets)으로 판단
        named = p.overview_sheets if slot == "overview" else slot if isinstance(slot, list) else None
        literal = named is not None and not any(c in n for n in named for c in "*?")
        selected = named if literal else None
    base_used = selected is None or any(not any(sheet_matches(s, o.sheets) for o in covered) for s in selected)
    if base_used and not _has(p, "description"):
        out.append(f"{where}: check_content인데 {d.doc_type} 프로필({d.profile_file})의 기본 columns에 description 열이 없습니다")
    for i, o in overrides:
        if not _has(o, "description"):
            out.append(f"{where}: check_content인데 {d.doc_type} 프로필({d.profile_file})의 sheet_overrides[{i}] {o.sheets}"
                       "에 description 열이 없습니다")
    return out


def _slot_warnings(where, k, d, slot):
    """규칙 칸이 프로필의 읽음 시트를 하나도 못 고르거나, 칸에 적은 이름이 어느 시트에도 맞지 않으면 경고
    (프로필 sheets 목록이 있을 때만 — 없으면 엑셀을 열어야 알 수 있음)"""
    names = _read_sheet_names(d.profile)
    if names is None or slot is None:
        return []
    label = f"{where}.sheets[{k}] ({d.doc_type} 프로필 {d.profile_file})"
    if isinstance(slot, list):
        return [f"{label}: {s!r}에 맞는 읽음 시트가 프로필 sheets에 없습니다" for s in slot
                if not any(_names_overlap(s, n) for n in names)]
    if not any(slot_selects(n, d.profile, slot) for n in names):
        return [f"{label}: {slot}가 고르는 시트가 없습니다(overview_sheets {d.profile.overview_sheets}와 읽음 시트를 확인하세요)"]
    return []


def _one_side(where, rule, sides, role, what):
    """id_ref의 ref_ids, sheet_to_path의 root_separators: 정확히 한쪽(그 쪽 문서 전부)에만 있어야 한다.
    찾는 쪽 번호(0·1)를 돌려준다. 정해지지 않으면 None"""
    issues = []
    for t, docs in zip(rule.docs, sides):
        flags = [role(d.profile) for d in docs]
        if any(flags) and not all(flags):
            names = [d.profile_file for d, f in zip(docs, flags) if not f]
            issues.append(f"{where}: {rule.key} 규칙인데 {t} 문서 중 일부 프로필에만 {what}이 있습니다(없는 프로필: {names})")
    has = _side_flags(sides, role)
    if all(has):
        issues.append(f"{where}: {rule.key} 규칙인데 {what}이 양쪽 프로필에 다 있습니다. 찾는 쪽 한쪽에만 두세요")
    elif not any(has):
        issues.append(f"{where}: {rule.key} 규칙인데 {what}이 어느 쪽 프로필에도 없습니다(찾는 쪽 프로필에 두세요)")
    return issues, seeker_side(has)


def has_ref_ids(profile):
    """id_ref의 찾는 쪽 단서: 기본값이나 어느 덮어쓰기에라도 ref_ids 열이 있음. 설정 검사와 연결 실행이 같이 쓴다"""
    return _has_anywhere(profile, "ref_ids")


def has_root_separators(profile):
    """sheet_to_path의 찾는 쪽 단서: 기본값이나 어느 덮어쓰기에라도 root_separators가 있음"""
    return any(bool(x.root_separators) for x in [profile] + list(profile.sheet_overrides))


def _side_flags(sides, role):
    """규칙 양쪽마다 그 쪽 문서 중 하나라도 role(프로필)을 만족하는지"""
    return [any(role(d.profile) for d in docs) for docs in sides]


def seeker_side(has):
    """찾는 쪽 번호: 정확히 한쪽만 단서가 있을 때 그 쪽, 아니면 None (id_ref·sheet_to_path 공통, 설정 검사와 연결 실행이 같이 씀)"""
    return has.index(True) if has.count(True) == 1 else None


def _root_off_sheets(profile, slot):
    """규칙 칸이 고르는 시트 중 sheet_as_root가 꺼진 곳(sheets 목록이 없으면 기본값·맞는 덮어쓰기로 판단)"""
    names = _read_sheet_names(profile)
    if names is not None:
        return [n for n in names if slot_selects(n, profile, slot) and not sheet_profile(profile, n).sheet_as_root]
    bad = [] if profile.sheet_as_root else ["기본값"]
    for i, o in enumerate(profile.sheet_overrides):
        if "sheet_as_root" in o.model_fields_set and not o.sheet_as_root and any(slot_selects(n, profile, slot) for n in o.sheets):
            bad.append(f"sheet_overrides[{i}] {o.sheets}")
    return bad


def _cross_profile_checks(config, documents):
    """연결 규칙 ↔ 프로필 교차 검사 (항목 5에서 넘긴 조건). (오류, 경고). 같은 문장은 한 번만"""
    issues, warnings = [], []
    for i, rule in enumerate(config.link_rules):
        where = f"link_rules[{i}] (id={rule.id})"
        sides = [[d for d in documents if d.doc_type == t] for t in rule.docs]
        for t, docs in zip(rule.docs, sides):
            if not docs:
                warnings.append(f"{where}: {t} 문서 항목이 없어 이 규칙은 연결을 만들지 않습니다")
        for k, docs in enumerate(sides):
            slot = rule.sheets[k] if rule.sheets else None
            for d in docs:
                if slot == "overview" and not d.profile.overview_sheets:
                    issues.append(f"{where}.sheets[{k}]: overview를 썼는데 {d.doc_type} 프로필({d.profile_file})에 "
                                  "overview_sheets가 없습니다")
                    continue
                warnings += _slot_warnings(where, k, d, slot)
                if rule.check_content:
                    issues += _check_content_issues(where, d, slot)
        if not all(sides):
            continue   # 문서가 없는 쪽이 있으면 찾는 쪽 판단(id_ref·sheet_to_path)은 할 수 없음(위 경고만)
        if rule.key == "id_ref":
            found, seeker = _one_side(where, rule, sides, has_ref_ids, "ref_ids 열")
            issues += found
            if seeker is not None:
                for d in sides[1 - seeker]:
                    if not _has_anywhere(d.profile, "id"):
                        issues.append(f"{where}: id_ref 대상 쪽({d.doc_type}) 프로필({d.profile_file})에 id 열이 없습니다")
        if rule.key == "sheet_to_path":
            found, seeker = _one_side(where, rule, sides, has_root_separators, "root_separators")
            issues += found
            if seeker is not None:   # 찾는 쪽은 시트 이름으로 묶음을 찾으므로 규칙 칸 안 시트가 sheet_as_root: true여야 함
                slot = rule.sheets[seeker] if rule.sheets else None
                for d in sides[seeker]:
                    bad = _root_off_sheets(d.profile, slot)
                    if bad:
                        issues.append(f"{where}: sheet_to_path 찾는 쪽({d.doc_type}) 프로필({d.profile_file})의 {bad}에 "
                                      "sheet_as_root가 꺼져 있습니다(시트 이름으로 묶음을 찾으므로 true여야 함)")
    return list(dict.fromkeys(issues)), list(dict.fromkeys(warnings))


NEW_SHEET_NOTE = "새 시트, 확인 필요"


SKIPPED_REASON = {"hidden": "숨김 시트(실행 때 건너뜀)", "chart": "차트 시트(실행 때 건너뜀)"}


@dataclass
class HeaderRow:
    """--excel 설정 검사의 머리글 대조 한 줄: 시트 하나의 역할 하나(셀 값은 담지 않음)"""

    document: str
    sheet: str
    header_count: int | None      # 머리글 있는 열 수(못 찾았으면 None)
    role: str
    columns: list                 # 열마다 보일 글자(_shown) — 선택자로 확인된 머리글 글자만


def id_ref_targets(config, documents):
    """id_ref 규칙의 대상 쪽(찾는 쪽이 아닌 쪽): [(문서 종류, 규칙 sheets 칸)]. 그 칸이 고르는 시트는 id 열이 필수.
    찾는 쪽 판정은 교차 검사와 같은 함수(_side_flags·seeker_side). run도 이 함수를 쓴다"""
    out = []
    for rule in config.link_rules:
        if rule.key != "id_ref":
            continue
        sides = [[d for d in documents if d.doc_type == t] for t in rule.docs]
        seeker = seeker_side(_side_flags(sides, has_ref_ids))
        if all(sides) and seeker is not None:
            target = 1 - seeker
            out.append((rule.docs[target], rule.sheets[target] if rule.sheets else None))
    return out


def needs_id(doc_type, profile, sheet, targets):
    """이 시트가 id_ref 대상으로 읽히는지(그러면 id 열 필수)"""
    return any(t == doc_type and slot_selects(sheet, profile, slot) for t, slot in targets)


def _cell_text(text):
    """markdown 표 칸 안 글자: | 를 이스케이프"""
    return str(text).replace("|", "\\|")


def _shown(col, header, sel, parts):
    """머리글 대조 표에 보일 글자. header_contains로 맞은 열·패턴에 통째로 맞는 열은 합친 머리글 전체.
    그 밖에는 2칸 이상 가로 병합된 머리글 칸(묶음 제목)만 보이고, 병합 안 된 칸은 가린다(데이터 칸일 수 있음)"""
    if header is None:
        return f"{col} (열 지정)"
    if sel is not None and sel.header_contains is not None:
        return f"{col}: {_cell_text(header)}"
    if sel is not None and sel.header_pattern is not None and re.fullmatch(sel.header_pattern, header):
        return f"{col}: {_cell_text(header)}"
    visible = [t for t, wide in parts if wide]
    hidden = len(parts) - len(visible)
    if not visible:
        return f"{col} (열 지정)" if sel is None or sel.col is not None else f"{col}: 패턴 맞음(머리글 글자 가림)"
    text = _cell_text(" / ".join(visible))
    return f"{col}: {text}" if hidden == 0 else f"{col}: {text} (+{hidden}줄 글자 가림: 병합 안 된 머리글 칸)"


def _column_marks(table, col):
    """머리글 대조에서 열 뒤에 붙일 표시: 엑셀에서 숨긴 열, 데이터 행에 원문 값이 하나도 없는 열.
    머리글이 맞아도 실제 값은 다른 열에 있을 수 있음을 알린다"""
    marks = []
    if col in table.grid.hidden_cols:
        marks.append(HIDDEN_COL_MARK)
    if not any(c.origin == "cell" and c.value is not None for c in (table.grid.cell(r, col) for r in table.data_rows)):
        marks.append(EMPTY_COL_MARK)
    return f" [{', '.join(marks)}]" if marks else ""


def _excel_checks(config, documents, labels):
    """엑셀을 열어 하는 설정 검사. (오류, 경고, 문서 순번 → [(새 시트, 건너뛰는 이유)], 머리글 대조 줄)
    - 6c: 시트 목록 ↔ 프로필 sheets(새 시트·없는 시트). 「없음」은 그 문서의 모든 파일 시트를 합쳐서 본다
    - 9a: 프로필에서 읽음인 시트가 머리글을 못 찾으면 오류(새 시트는 이미 「확인 필요」라 검사하지 않음).
      선택자마다 맞은 열 수와 합친 머리글(글자로 맞은 열만)"""
    from si_prep import extract, layout, reader
    from si_prep.issues import Issues
    errors, warnings, new_sheets, report = [], [], {}, []
    id_targets = id_ref_targets(config, documents)
    unimplemented = unimplemented_methods()
    for d in documents:
        opened, all_ok = [], True
        for f in d.files:
            issues = Issues()
            wb = reader.open_workbook(config.input_path / f, issues)
            warnings += [i.message for i in issues]
            if wb is None:
                all_ok = False
            else:
                opened.append((f, wb))
        entries = [e.name for e in d.profile.sheets] if d.profile.sheets is not None else None
        for f, wb in opened:
            missing = extract.missing_version_parts(d.profile, extract.read_doc_version(wb, d.profile, Issues()))
            if missing:
                warnings.append(f"{f}: 버전을 못 찾았습니다({', '.join(missing)}) — {d.doc_type} 프로필({d.profile_file}) version 설정을 확인하세요")
            news = set()
            for grid in wb.sheets:
                if entries is None or sheet_matches(grid.name, entries):
                    continue
                news.add(grid.name)
                skipped = SKIPPED_REASON["chart"] if grid.is_chart else SKIPPED_REASON["hidden"] if grid.hidden else None
                what = skipped or "실행 때 프로필 설정(시트별 덮어쓰기 포함)대로 읽습니다"
                warnings.append(f"{f} 시트 \"{grid.name}\": {NEW_SHEET_NOTE} — {d.doc_type} 프로필({d.profile_file}) "
                                f"sheets 어느 줄에도 맞지 않음. {what}")
                new_sheets.setdefault(d.index, []).append((grid.name, skipped))
            skip_issues = Issues()
            for grid in layout.select_sheets(wb, d.profile, skip_issues):
                if grid.name in news:
                    continue
                sp = sheet_profile(d.profile, grid.name)
                if any(getattr(sp, k).method in names for k, names in unimplemented.items()):
                    continue   # 미구현 방식 시트는 실행 때도 건너뜀(이미 경고)
                t_issues = Issues()
                required = ("id",) if needs_id(d.doc_type, d.profile, grid.name, id_targets) else ()
                tables = layout.build_tables(grid, sp, f, t_issues, required_roles=required)   # 설정 없으면 표 하나
                not_found = t_issues.by_kind("header_not_found")
                if sp.tables is None:
                    errors += [i.message for i in not_found]
                else:   # 한 시트 여러 표: 표 하나 건너뜀(위치 있음)은 경고, 표를 하나도 못 찾음은 오류
                    errors += [i.message for i in not_found if not i.locations]
                    warnings += [i.message for i in not_found if i.locations]
                    warnings += [i.message for i in t_issues.by_kind("unsupported_layout")]
                if not tables:
                    report.append(HeaderRow(labels[d.index], grid.name, None, "(머리글 못 찾음)", []))
                    continue
                for table in tables:
                    label = layout.table_label(table, header_lines=sp.tables is not None)   # 표마다 머리글 줄 수
                    for role, cols in table.matches.items():
                        by_col = dict(table.selectors.get(role, []))
                        report.append(HeaderRow(labels[d.index], label, len(table.headers), role,
                                                [_shown(c, h, by_col.get(c), table.header_parts.get(c, []))
                                                 + _column_marks(table, c) for c, h in cols]))
                        if not cols:
                            warnings.append(f"{f} 시트 \"{label}\": {role} 선택자에 맞는 머리글을 못 찾았습니다"
                                            "(실행 때 이 역할 열 없이 처리)")
                    if not table.matches:   # 역할 지정이 없는 시트도 머리글을 찾았는지·열 수는 보인다
                        report.append(HeaderRow(labels[d.index], label, len(table.headers), "(역할 지정 없음)", []))
            warnings += [i.message for i in skip_issues if i.sheet not in news]
        if entries is not None and all_ok and opened:   # 열지 못한 파일이 있으면 「없음」은 판단하지 않음
            every = [g.name for _, wb in opened for g in wb.sheets]
            files = ", ".join(f for f, _ in opened)
            for e in entries:
                if any(sheet_matches(n, [e]) for n in every):
                    continue
                if any(c in e for c in "*?"):
                    warnings.append(f"{d.doc_type} 프로필({d.profile_file}) sheets의 패턴 \"{e}\"에 아직 맞는 시트가 없습니다({files})")
                else:
                    warnings.append(f"{d.doc_type} 프로필({d.profile_file}) sheets의 \"{e}\"에 맞는 시트가 엑셀에 없습니다({files})")
    return list(dict.fromkeys(errors)), list(dict.fromkeys(warnings)), new_sheets, report


def check_project(path, read_excel: bool = False, ignore_glossary: bool = False) -> CheckResult:
    """project.yaml과 모든 프로필을 읽고 검사한다. 오류는 모두 모아 ConfigError(project.yaml 오류가 있어도
    경로를 알 수 있는 프로필은 읽어서 같이), 경고·[검토] 수·시트별 표는 결과로.
    교차 검사(규칙 ↔ 프로필)는 project.yaml과 프로필이 모두 단독 검사를 통과한 뒤에만 한다(틀린 값 위에서 검사하지 않게).
    read_excel이면 엑셀의 시트 이름을 읽어 프로필 sheets와 대조한다. 기본은 엑셀을 열지 않는다"""
    path = Path(path)
    issues, config = [], None
    try:
        config = load_project(path, ignore_glossary=ignore_glossary)
    except ConfigError as e:
        issues += e.issues
    base = path.parent
    documents, loaded = [], {}
    for index, doc_type, files, profile_path in _profile_entries(path, config):
        key = str(Path(profile_path).resolve())
        if key not in loaded:  # 같은 프로필 파일을 여러 문서가 쓰면 한 번만 읽고 오류도 한 번만
            try:
                loaded[key] = load_profile(profile_path)
            except ConfigError as e:
                loaded[key] = None
                issues += [f"{Path(profile_path).name}: {msg}" for msg in e.issues]
        if loaded[key] is not None:
            documents.append(DocumentResult(index, doc_type, files, _relative(base, profile_path), loaded[key]))
    if config is None or issues:
        raise ConfigError(path, issues)
    issues, cross_warnings = _cross_profile_checks(config, documents)
    if issues:
        raise ConfigError(path, issues)

    result = CheckResult(config=config, documents=documents, warnings=[f"{path.name} {w}" for w in cross_warnings])
    unlinked = unimplemented_link_keys()
    for rule in config.link_rules:
        if rule.key in unlinked:
            result.warnings.append(f"{path.name} link_rules (id={rule.id}) key: {rule.key} {UNSUPPORTED_NOTE}")
    seen = set()
    for d in documents:
        if d.profile_file not in seen:
            seen.add(d.profile_file)
            result.warnings += _unimplemented_warnings(Path(d.profile_file).name, d.profile)

    checked = [(path, config.approved)] + list({d.profile_file: (base / d.profile_file, d.profile.approved)
                                                for d in documents}.values())
    if config.glossary:
        checked.append((base / config.glossary, config.glossary_data.approved if config.glossary_data else False))
    for file, approved in checked:
        marks = _count_review_marks(file)
        if marks:
            name = _relative(base, file)
            result.review_marks[name] = marks
            if approved:
                result.warnings.append(f"{name}: approved: true인데 {REVIEW_MARK} {marks}곳이 남아 있습니다")

    per_type = Counter(d.doc_type for d in documents)
    labels = {d.index: d.doc_type if per_type[d.doc_type] == 1 else f"{d.doc_type} ({d.files[0] if d.files else d.profile_file})"
              for d in documents}
    new_sheets = {}
    if read_excel:
        excel_errors, excel_warnings, new_sheets, result.header_report = _excel_checks(config, documents, labels)
        if excel_errors:   # 같은 실행에서 모은 엑셀 경고도 함께 보인다
            raise ConfigError(path, excel_errors + [f"(경고) {w}" for w in excel_warnings])
        result.warnings += excel_warnings

    for d in documents:
        label = labels[d.index]
        for entry in d.profile.sheets or [SheetEntry(name="*")]:
            result.sheet_rows.append(SheetRow(d.doc_type, label, entry.name, entry.read, entry.reason,
                                              slot_selects(entry.name, d.profile, "overview")))
        for name, skipped in new_sheets.get(d.index, []):
            result.sheet_rows.append(SheetRow(d.doc_type, label, name, skipped is None, skipped,
                                              slot_selects(name, d.profile, "overview"), new=True))
    return result


def format_check(result: CheckResult) -> str:
    """사람이 읽는 검사 결과: 경고 목록, 남은 [검토], 시트별 표"""
    profiles = len({d.profile_file for d in result.documents})
    lines = [f"설정 검사: {result.config.project} (문서 {len(result.config.documents)}개, 프로필 {profiles}개)"]
    lines.append(f"경고 {len(result.warnings)}개")
    lines += [f" - {w}" for w in result.warnings]
    total = sum(result.review_marks.values())
    detail = ", ".join(f"{k} {v}" for k, v in result.review_marks.items())
    lines.append(f"{REVIEW_MARK} 남은 곳: {total}" + (f" ({detail})" if detail else ""))
    lines.append("")
    lines.append("| 문서 | 시트 | 읽음/뺌 | 이유 | overview | 항목 수 | 링크 수 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in result.sheet_rows:
        state = ("읽음" if r.read else "뺌") + (f" · {NEW_SHEET_NOTE}" if r.new else "")
        lines.append(f"| {r.document} | {r.sheet} | {state} | {r.reason or ''} | "
                     f"{'예' if r.overview else ''} | {NOT_YET} | {NOT_YET} |")
    if result.header_report:
        lines += ["", "머리글 대조 (--excel, 셀 값은 보이지 않음. 열 문자로 지정한 열은 머리글 글자도 가림. "
                  f"[{HIDDEN_COL_MARK}] = 엑셀에서 숨긴 열, [{EMPTY_COL_MARK}] = 데이터 행에 원문 값이 없는 열 — 실제 값이 옆 열에 있는지 확인)",
                  "| 문서 | 시트 | 머리글 열 수 | 역할 | 맞은 열 수 | 열: 합친 머리글 |", "| --- | --- | --- | --- | --- | --- |"]
        for h in result.header_report:
            count = "" if h.header_count is None else h.header_count
            lines.append(f"| {_cell_text(h.document)} | {_cell_text(h.sheet)} | {count} | {h.role} | {len(h.columns)} | "
                         f"{', '.join(h.columns)} |")
    return "\n".join(lines)


def main(argv=None):
    """python -m si_prep.config <project.yaml> [--excel] — 설정 검사 결과를 보여 준다. 오류가 있으면 종료 코드 1.
    --excel이면 엑셀의 시트 이름을 읽어 프로필과 대조한다(사람이 실행하는 검사)"""
    import sys
    from si_prep.console import replace_unencodable
    replace_unencodable()   # 화면 출력: 인코딩은 그대로, 못 쓰는 글자만 ?(cp949 콘솔에서 멈추지 않게)
    args = list(sys.argv[1:] if argv is None else argv)
    read_excel = "--excel" in args
    args = [a for a in args if a != "--excel"]
    if len(args) != 1:
        print("사용법: python -m si_prep.config <project.yaml> [--excel]")
        return 2
    try:
        print(format_check(check_project(args[0], read_excel=read_excel)))
    except ConfigError as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
