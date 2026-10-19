"""항목 초안 만들기 — 경계·경로 결과로 Item 초안(번호만 없음)을 만든다.

- raw_fields: 자기 칸의 원문 칸 값만(병합 복원 값·빈 칸 제외). 분류 열·본문에서 뺄 열도 들어간다.
- merged_fields: 분류 열이 아닌 열에서 병합 시작 칸이 항목 행 위에 있으면 {머리글, 시작 칸 값, 시작 행}.
  가로로 걸친 병합은 시작 칸 열 하나로 한 번만.
- title·description: raw_fields 값을 먼저, 비면 merged_fields 값. not_written은 description 역할이 있고 둘 다 빌 때만.
- status: unparsed > ambiguous > not_written > ok. ambiguous = 경로에 filled_down·empty 단계가 있음.
- 칸 경고: 계산값 없는 수식 → formula_no_value, 수식 오류 값 → unparsed.
- 문서 버전: 표지(label_pattern에 맞는 칸의 오른쪽 칸)·파일 이름(filename_pattern 그룹 1). 원문 그대로 저장하고
  숫자와 점만 남겨 비교한다. 다르면 version_mismatch.
- ID: ref_ids = 참조 칸에서 ref_ids pattern에 맞는 글자 전부(맞은 글자 전체, 원문 순서, 중복 제거). 참조 칸에 글자가
  있는데 하나도 안 맞으면 unparsed. 자기 ID가 id_pattern에 통째로 맞지 않으면 unparsed. 같은 문서 종류 안 자기 ID 중복은
  모든 항목을 만든 뒤 check_duplicate_ids → duplicate_id. ID 비교는 normalize.id_key(앞뒤 공백만 뺌, 대소문자 구분).
이어지는 행(여러 행 이어 붙이기)은 10b.
"""

import re
from dataclasses import dataclass, field

from si_prep import boundary
from si_prep.config import sheet_matches
from si_prep.normalize import id_key
from si_prep.schema import DocVersion, Item, Location, MergedField, PathPart, RawField, has_inferred_step, path_text



@dataclass
class ItemDraft:
    doc_type: str
    doc_file: str
    sheet: str
    rows: tuple                         # (시작 행, 끝 행)
    category_path: list
    category_path_text: str
    raw_fields: dict
    merged_fields: dict
    doc_version: DocVersion
    status: str
    profile_source: str
    title: str | None = None
    source_id: str | None = None
    ref_ids: list = field(default_factory=list)
    description: str | None = None      # 설명 값(raw 먼저, 비면 merged) — 내용 비교(check_content)용, 출력 칸 아님
    description_col: str | None = None  # 그 값을 읽은 열(경고 위치)
    description_row: int | None = None  # 그 값의 원문 칸 행(merged면 병합 시작 행)
    text_excluded: tuple = ()           # 청크 본문에서 뺄 열(분류 열 + exclude_from_text) — 출력 칸 아님
    id_col: str | None = None           # 자기 ID를 읽은 열(duplicate_id·id_ref 근거 위치) — 출력 칸 아님
    ref_col: str | None = None          # 참조 ID 칸 열·행(ref_unresolved·id_ref 근거 위치) — 출력 칸 아님
    ref_row: int | None = None
    expanded_refs: list = field(default_factory=list)  # 줄임 표기를 펼친 ID [(펼친 ID, 조각, 앞 ID)] — 연결에만, 출력 칸 아님(B2)
    short_left: int = 0                 # 참조 칸에서 펼치지 않은(못한) 숫자 조각 수 — 처리 보고서 4절, 출력 칸 아님

    def location(self) -> Location:
        return Location(file=self.doc_file, sheet=self.sheet, rows={"start": self.rows[0], "end": self.rows[1]})

    def to_item(self, item_id: str) -> Item:
        return Item(item_id=item_id, doc_type=self.doc_type, doc_file=self.doc_file, source_id=self.source_id,
                    ref_ids=list(self.ref_ids), title=self.title, category_path=self.category_path,
                    category_path_text=self.category_path_text, raw_fields=self.raw_fields,
                    merged_fields=self.merged_fields, locations=[self.location()], doc_version=self.doc_version,
                    status=self.status, profile_source=self.profile_source)


def _text(value):
    return None if value is None else value if isinstance(value, str) else str(value)


def _role_cell(role, table, raw, merged, row=None):
    """(역할 열 값, 그 열, 원문 칸 행). raw_fields 먼저(행 = 항목 행), 비면 merged_fields(행 = 병합 시작 행)"""
    cols = table.roles.get(role, [])
    if not cols:
        return None, None, None
    col = cols[0]
    if col in raw:
        return _text(raw[col].value), col, row
    if col in merged:
        return _text(merged[col].value), col, merged[col].source_row
    return None, None, None


def _ref_ids(text, pattern):
    """참조 칸 글자에서 pattern에 맞는 글자 전부(맞은 글자 전체 — 그룹이 있어도), 원문 순서, 중복 제거"""
    return list(dict.fromkeys(m.group(0) for m in re.finditer(pattern, text) if m.group(0)))


# 줄임 표기(B2): ID 뒤 조각을 나누는 기호(쉼표·빗금·가운뎃점·모점·쌍반점·공백), 숫자만 있는 조각, 범위 표기
_SHORT_TOKEN = re.compile(r"[^\s,/·、;]+")
_DIGITS = re.compile(r"[0-9]+")
_RANGE = re.compile(r"[~∼〜]")


def _short_fragments(text, matches):
    """맞은 ID마다 그 뒤에 나눔 기호로만 이어지는 조각 [(앞 ID, 조각, 범위인지)]. 숫자만 있는 조각과 범위 표기만 모으고,
    다른 글자가 나오면 그 ID의 조각은 끝"""
    out = []
    for k, m in enumerate(matches):
        end = matches[k + 1].start() if k + 1 < len(matches) else len(text)
        for t in _SHORT_TOKEN.findall(text[m.end():end]):
            if _RANGE.search(t) and _DIGITS.search(t):
                out.append((m.group(0), t, True))
                break
            if not _DIGITS.fullmatch(t):
                break
            out.append((m.group(0), t, False))
    return out


def _expand_short(text, pattern, refs):
    """(펼친 ID 목록 [(ID, 조각, 앞 ID)], 펼치지 못한 조각 [(조각, 이유)]). 앞 ID 끝 숫자 묶음을 같은 길이 조각으로 바꾸고,
    결과가 pattern에 통째로 맞을 때만 받는다"""
    matches = [m for m in re.finditer(pattern, text) if m.group(0)]
    expanded, failed = [], []
    for base, frag, is_range in _short_fragments(text, matches):
        tail = re.search(r"[0-9]+$", base)
        if is_range:
            failed.append((frag, "범위 표기"))
        elif tail is None:
            failed.append((frag, f"앞 ID {base}의 끝이 숫자가 아님"))
        elif len(tail.group(0)) != len(frag):
            failed.append((frag, f"앞 ID {base}의 끝 숫자와 길이가 다름"))
        else:
            new = base[:tail.start()] + frag
            if not re.fullmatch(pattern, new):
                failed.append((frag, f"펼친 {new}가 ref_ids pattern과 맞지 않음"))
            elif new not in refs and new not in [e[0] for e in expanded]:
                expanded.append((new, frag, base))
    return expanded, failed


def _ids(table, raw, merged, row, issues):
    """(source_id, id 열, ref_ids, 참조 열, 참조 행, unparsed인지, 펼친 ID, 펼치지 않은 조각 수). 경고는 여기서 낸다"""
    unparsed = False
    id_cols = table.roles.get("id", [])
    id_col = id_cols[0] if id_cols and id_cols[0] in raw else None
    source_id = _text(raw[id_col].value) if id_col else None
    key = id_key(source_id) if source_id is not None else ""
    if key and table.id_pattern and not re.fullmatch(table.id_pattern, key):
        unparsed = True
        _cell_warning(issues, "unparsed", table, table.grid.cell(row, id_col),
                      f"자기 ID {source_id!r}가 id_pattern과 맞지 않습니다")
    text, ref_col, ref_row = _role_cell("ref_ids", table, raw, merged, row)
    refs, expanded, left = [], [], 0
    if text is not None and ref_col is not None:
        selector = table.selectors["ref_ids"][0][1]
        refs = _ref_ids(text, selector.pattern)
        expanded, failed = _expand_short(text, selector.pattern, refs)
        if not selector.expand_short:
            expanded, failed, left = [], [], len(expanded) + len(failed)   # 끔: 세기만(보고서 4절)
        else:
            left = len(failed)
        if failed:
            unparsed = True
            merged_from = f"(병합 {ref_col}{ref_row} 칸의 값)" if ref_row != row else ""
            _cell_warning(issues, "unparsed", table, table.grid.cell(row, ref_col),
                          "참조 ID 칸의 줄임 조각을 펼치지 못했습니다" + merged_from + ": "
                          + ", ".join(f"{f}({why})" for f, why in failed))
        if not refs and text.strip():
            # 위치는 이 항목 행의 칸(병합 값이면 시작 칸을 메시지에) — 병합이 여러 항목에 걸쳐도 항목마다 자기 경고 1건
            # (시작 행 위치면 실행이 위 항목에 붙여 같은 항목에 두 번)
            unparsed = True
            merged_from = f"(병합 {ref_col}{ref_row} 칸의 값)" if ref_row != row else ""
            _cell_warning(issues, "unparsed", table, table.grid.cell(row, ref_col),
                          f"참조 ID 칸에 ref_ids pattern에 맞는 ID가 없습니다{merged_from}")
    return source_id, id_col, refs, ref_col, ref_row, unparsed, expanded, left


def _cell_warning(issues, kind, table, cell, message):
    issues.add(kind, f"{table.file} 시트 \"{table.sheet}\" {cell.col}{cell.row}: {message}",
               [Location(file=table.file, sheet=table.sheet, rows={"start": cell.row, "end": cell.row}, cols=[cell.col])],
               file=table.file, sheet=table.sheet)


def make_items(table, groups, paths, doc_type, source, doc_version, issues) -> list:
    """경계(groups)와 경로(paths, hierarchy의 Step 목록)를 받아 항목 초안 목록(행 순서).
    source: config.profile_source(프로젝트 approved, 프로필 approved). status 우선순위는 unparsed > ambiguous > not_written > ok"""
    own = boundary.own_columns(table)
    hierarchy_cols = set(table.roles.get("hierarchy", []))
    drafts = []
    for g, steps in zip(groups, paths):
        raw, merged, unparsed = {}, {}, False
        for col in own:
            cell = table.grid.cell(g.start, col)
            header = table.headers.get(col, "")
            if cell.origin == "cell":
                if cell.formula_no_value:
                    _cell_warning(issues, "formula_no_value", table, cell, "수식에 저장된 계산값이 없습니다(값 없음으로 처리)")
                if cell.error:
                    unparsed = True
                    _cell_warning(issues, "unparsed", table, cell, f"수식 오류 값 {cell.value!r}이 있습니다(원문 그대로 둠)")
                if cell.value is not None:
                    raw[col] = RawField(header=header, value=cell.value)
            elif cell.merge_start is not None and col not in hierarchy_cols:
                start_row, start_col = cell.merge_start
                if start_col == col and start_row < g.start:        # 시작 칸이 항목 행 위 → merged_fields
                    start = table.grid.cell(start_row, start_col)
                    if start.value is not None:
                        merged[col] = MergedField(header=header, value=start.value, source_row=start_row)
        source_id, id_col, refs, ref_col, ref_row, bad_id, expanded, left = _ids(table, raw, merged, g.start, issues)
        unparsed = unparsed or bad_id
        parts = [PathPart(level=i, value=s.value, basis=s.basis) for i, s in enumerate(steps, start=1)]
        status = "ok"
        if "description" in table.roles and _role_cell("description", table, raw, merged)[0] is None:
            status = "not_written"
        if has_inferred_step(steps):
            status = "ambiguous"
        if unparsed:
            status = "unparsed"
        description, description_col, description_row = _role_cell("description", table, raw, merged, g.start)
        drafts.append(ItemDraft(
            doc_type=doc_type, doc_file=table.file, sheet=table.sheet, rows=(g.start, g.end),
            category_path=parts, category_path_text=path_text(parts), raw_fields=raw, merged_fields=merged,
            doc_version=doc_version, status=status, profile_source=source,
            title=_role_cell("title", table, raw, merged)[0],
            source_id=source_id, ref_ids=refs, id_col=id_col, ref_col=ref_col, ref_row=ref_row,
            expanded_refs=expanded, short_left=left,
            description=description, description_col=description_col, description_row=description_row,
            text_excluded=tuple(table.roles.get("hierarchy", [])) + tuple(table.roles.get("exclude_from_text", []))))
    return drafts


def id_location(d) -> Location:
    """자기 ID 칸 위치"""
    return Location(file=d.doc_file, sheet=d.sheet, rows={"start": d.rows[0], "end": d.rows[0]}, cols=[d.id_col])


def check_duplicate_ids(drafts, issues) -> None:
    """같은 문서 종류 안에서 자기 ID(id_key)가 두 번 이상이면 ID마다 duplicate_id 한 건(위치 = 그 ID 칸들, 처리 순서).
    모든 항목 초안을 만든 뒤 부른다"""
    seen = {}
    for d in drafts:
        if d.source_id is not None and id_key(d.source_id):
            seen.setdefault((d.doc_type, id_key(d.source_id)), []).append(d)
    for (doc_type, key), same in seen.items():
        if len(same) > 1:
            where = ", ".join(f"{d.doc_file} {d.sheet} {d.rows[0]}행" for d in same)
            issues.add("duplicate_id", f"{doc_type} 문서에 자기 ID {key!r}가 {len(same)}번 있습니다({where})",
                       [id_location(d) for d in same], file=same[0].doc_file, sheet=same[0].sheet)


def _version_key(text):
    """버전 비교 열쇠: 숫자와 점만 (「v1.2」 = 「1.2」)"""
    return re.sub(r"[^0-9.]", "", text)


def cover_cells(wb, profile) -> set:
    """표지 버전 읽기가 읽는 칸 {(시트, 행, 열)}: 라벨 칸과 값 칸. 없으면 빈 집합
    (머리글 위 칸 경고에서 이미 읽히는 칸을 빼는 데 씀)"""
    hit = _cover_hit(wb, profile.version) if profile.version is not None else None
    return set() if hit is None else {(hit[0], c.row, c.col) for c in hit[1:]}


def _cover_hit(wb, spec):
    """표지 시트에서 label_pattern에 맞는 칸과 그 오른쪽 첫 값 칸 → (시트, 라벨 칸, 값 칸). 없으면 None"""
    if not spec.cover_sheet or not spec.label_pattern:
        return None
    label = re.compile(spec.label_pattern)
    for grid in wb.sheets:
        if not sheet_matches(grid.name, [spec.cover_sheet]):
            continue
        for r in range(1, grid.max_row + 1):
            cells = [grid.cell(r, c) for c in grid.columns]
            for i, cell in enumerate(cells):
                if cell.origin == "cell" and isinstance(cell.value, str) and label.search(cell.value):
                    # 라벨 오른쪽에서 처음 나오는 원문 칸(라벨 칸의 병합이 오른쪽으로 이어진 부분은 건너뜀)
                    value = next((c for c in cells[i + 1:] if c.origin == "cell" and c.value is not None), None)
                    if value is not None:
                        return grid.name, cell, value
    return None


def read_doc_version(wb, profile, issues) -> DocVersion:
    """문서 버전: 표지·파일 이름에서 원문 그대로. 둘 다 있고 숫자·점이 다르면 version_mismatch"""
    spec = profile.version
    if spec is None:
        return DocVersion()
    hit = _cover_hit(wb, spec)
    cover = None if hit is None else _text(hit[2].value)
    filename = None
    if spec.filename_pattern:
        m = re.search(spec.filename_pattern, wb.file)
        filename = m.group(1) if m else None
    if hit and filename is not None and _version_key(cover) != _version_key(filename):
        sheet, _, cell = hit
        issues.add("version_mismatch",
                   f"{wb.file}: 표지 버전 {cover!r}과 파일 이름 버전 {filename!r}이 다릅니다",
                   [Location(file=wb.file, sheet=sheet, rows={"start": cell.row, "end": cell.row}, cols=[cell.col])],
                   file=wb.file, sheet=sheet)
    return DocVersion(cover=cover, filename=filename)


def missing_version_parts(profile, version) -> list:
    """버전 설정이 있는데 값을 못 찾은 곳(「표지」·「파일 이름」). 처리 보고서·--excel 설정 검사가 같이 쓴다"""
    spec = profile.version
    if spec is None:
        return []
    out = []
    if spec.cover_sheet and spec.label_pattern and version.cover is None:
        out.append("표지")
    if spec.filename_pattern and version.filename is None:
        out.append("파일 이름")
    return out
