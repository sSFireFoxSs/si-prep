"""표 읽기 — 시트 선택, 머리글 합치기(" / "), 열 역할 해석(선택자 → 열 문자),
데이터 행 범위·끝 표시, hidden_rows: skip. 분류·연결은 모른다. openpyxl은 쓰지 않는다(reader의 격자만 본다).

한 시트 여러 표: 프로필 tables를 설정한 시트만 split_tables로 표마다 나눠 읽는다(build_tables).
설정이 없는 시트는 시트 하나 = 표 하나 그대로. 빈 행 간격 감지·시트 건너뜀(table_gap_rows)은 아직 없다.
"""

import re
from dataclasses import dataclass, field

from si_prep.config import sheet_matches
from si_prep.schema import Location

HEADER_JOIN = " / "                                   # 여러 줄 머리글을 잇는 글자
SINGLE_ROLES = ("id", "ref_ids", "title", "description")   # 열이 하나여야 하는 역할
HIERARCHY_REQUIRED = ("columns", "split_cell", "numbering")  # 분류 열이 반드시 있어야 하는 분류 방식
MAX_MERGE_HEADER_ROWS = 4   # tables.header_row.rows: merge에서 머리글로 인정하는 병합 높이 상한(넘으면 그 표만 건너뜀)


@dataclass
class Table:
    file: str
    sheet: str
    grid: object                    # reader.SheetGrid
    header_rows: list
    headers: dict                   # 열 문자 → 합친 머리글 글자 (머리글 있는 열만, 열 순서)
    roles: dict                     # 역할 → 열 문자 목록 (찾은 역할만)
    data_rows: list                 # 데이터 행 번호 (끝 표시 앞까지, skip이면 숨김 행 뺌)
    matches: dict = field(default_factory=dict)   # 역할 → [(열, 머리글)] 선택자가 맞은 열(설정 검사 출력용)
    selectors: dict = field(default_factory=dict)  # 역할 → [(열, 그 열을 고른 선택자)]
    header_parts: dict = field(default_factory=dict)  # 열 → [(머리글 칸 글자, 2칸 이상 가로 병합인지)]
    id_pattern: str | None = None                   # 자기 ID 모양 정규식(시트별 설정)
    table_title: str | None = None                  # 한 시트 여러 표: 이 표의 제목(원문 글자), 아니면 None
    title_row: int | None = None                    # 그 제목 행(시트 원래 행 번호)
    title_to: str | None = None                     # 제목을 경로에 넣는지(path / none, 프로필 tables.title_to)
    untitled: bool = False                          # 제목 없는 첫 표(tables.first_without_title)


def _span_where(title_row, header_first) -> str:
    """한 시트 여러 표의 표 하나를 메시지에서 가리키는 글자(표 범위·표 둘 다 이것만 쓴다)"""
    return f"제목 없는 표(머리글 {header_first}행)" if title_row is None else f"표(제목 {title_row}행)"


def table_where(table) -> str:
    """메시지의 표 위치: 「시트 "S"」, 한 시트 여러 표면 「 표(제목 n행)」·「 제목 없는 표(머리글 n행)」를 덧붙임"""
    where = f"시트 \"{table.sheet}\""
    if table.untitled or table.title_row is not None:
        return f"{where} {_span_where(table.title_row, table.header_rows[0])}"
    return where


def table_label(table, header_lines=False) -> str:
    """표 이름(처리 보고서 12절·설정 검사 대조 줄): 시트 이름, 한 시트 여러 표면 「S [표 제목 n행]」·「S [제목 없는 표, 머리글 n행]」.
    header_lines면 머리글 줄 수도(설정 검사): 「S [표 제목 n행 · 머리글 k줄]」·「S [제목 없는 표, 머리글 n행부터 k줄]」"""
    k = len(table.header_rows)
    if table.untitled:
        return f"{table.sheet} [제목 없는 표, 머리글 {table.header_rows[0]}행" + (f"부터 {k}줄]" if header_lines else "]")
    if table.title_row is None:
        return table.sheet
    return f"{table.sheet} [표 제목 {table.title_row}행" + (f" · 머리글 {k}줄]" if header_lines else "]")


def sheet_entry(name, entries):
    """시트에 해당하는 프로필 sheets 줄: 이름이 똑같은 줄이 먼저, 없으면 처음 맞는 패턴 줄"""
    for e in entries:
        if e.name == name:
            return e
    return next((e for e in entries if sheet_matches(name, [e.name])), None)


def select_sheets(wb, profile, issues) -> list:
    """읽을 시트 격자(통합 문서 안 순서). 뺌(read: false)은 조용히 빼고, 숨김·차트 시트는 sheet_skipped.
    프로필 sheets 어느 줄에도 맞지 않는 새 시트는 기본값으로 읽는다"""
    out = []
    for grid in wb.sheets:
        entry = sheet_entry(grid.name, profile.sheets) if profile.sheets else None
        if entry is not None and not entry.read:
            continue
        if grid.is_chart:
            issues.add("sheet_skipped", f"{wb.file} 시트 \"{grid.name}\": 칸이 없는 차트 시트라 건너뜁니다(chart_sheet)",
                       file=wb.file, sheet=grid.name)
            continue
        if grid.hidden:
            issues.add("sheet_skipped", f"{wb.file} 시트 \"{grid.name}\": 숨김 시트라 건너뜁니다(hidden_sheet)",
                       file=wb.file, sheet=grid.name)
            continue
        out.append(grid)
    return out


def col_number(col):
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _wide_starts(grid):
    """2칸 이상 가로로 걸친 병합의 시작 칸들"""
    return {(r1, c1) for r1, c1, r2, c2 in grid.merges if col_number(c2) > col_number(c1)}


def _headers(grid, header_rows):
    """열마다 머리글 행 값을 " / "로 잇는다. 병합으로 같은 값이 이어지면 한 번만.
    (열 → 합친 글자, 열 → [(칸 글자, 2칸 이상 가로 병합인지)])"""
    out, parts_of = {}, {}
    wide = _wide_starts(grid)
    for col in grid.columns:
        parts = []
        for r in header_rows:
            cell = grid.cell(r, col)
            value = cell.value
            if value is None or (isinstance(value, str) and not value.strip()):
                continue   # 공백만 있는 머리글 칸은 빈칸
            text = value if isinstance(value, str) else str(value)
            is_wide = cell.merge_start in wide
            if parts and parts[-1][0] == text:
                parts[-1] = (text, parts[-1][1] or is_wide)
                continue
            parts.append((text, is_wide))
        if parts:
            out[col] = HEADER_JOIN.join(t for t, _ in parts)
            parts_of[col] = parts
    return out, parts_of


def _describe(sel):
    for key in ("header_contains", "col", "header_pattern"):
        value = getattr(sel, key)
        if value is not None:
            return f'{key}: "{value}"'
    return "(빈 선택자)"


def _match(sel, headers, columns):
    if sel.col is not None:
        return [sel.col] if sel.col in columns else []   # 시트 범위 밖 열은 못 찾음
    if sel.header_contains is not None:
        return [c for c, h in headers.items() if sel.header_contains in h]
    if sel.header_pattern is not None:
        pattern = re.compile(sel.header_pattern)
        return [c for c, h in headers.items() if pattern.search(h)]
    return []


def _location(file, sheet, header_rows, cols=None):
    return Location(file=file, sheet=sheet, rows={"start": min(header_rows), "end": max(header_rows)}, cols=cols)


def _data_rows(grid, sp, first=None, last=None):
    """데이터 행(끝 표시 행 앞까지). first~last: 표 하나의 범위, 없으면 data_start_row~시트 끝"""
    rows = []
    for r in range(sp.data_start_row if first is None else first, (grid.max_row if last is None else last) + 1):
        first = next((c.value for c in (grid.cell(r, col) for col in grid.columns)
                      if c.origin == "cell" and c.value is not None), None)
        if isinstance(first, str) and any(first.startswith(m) for m in sp.stop_markers):
            break   # 끝 표시 행부터 무시
        rows.append(r)
    return rows


def _runs(rows):
    """연속한 행 번호를 (시작, 끝) 구간으로"""
    out = []
    for r in rows:
        if out and out[-1][1] == r - 1:
            out[-1][1] = r
        else:
            out.append([r, r])
    return [tuple(x) for x in out]


@dataclass(frozen=True)
class TableSpan:
    """한 시트 여러 표의 표 하나. 행 번호는 시트 원래 행"""
    title_row: int | None   # 제목 없는 첫 표면 None
    title: str | None
    header_rows: list
    first: int          # 데이터 첫 행
    last: int           # 데이터 마지막 행(다음 표 제목 앞, 없으면 시트 끝)
    tall_merge: str | None = None   # rows: merge인데 신호 칸 병합이 MAX_MERGE_HEADER_ROWS를 넘음 → 그 병합 범위(표 건너뜀)

    @property
    def start(self):
        """표가 시작하는 행(제목 행, 제목 없는 표는 머리글 첫 행)"""
        return self.header_rows[0] if self.title_row is None else self.title_row

    @property
    def untitled(self):
        return self.title_row is None

    @property
    def where(self):
        return _span_where(self.title_row, self.header_rows[0])


def _raw_cols(grid, row):
    """그 행에서 원문 값(병합 복원 전, 공백만 있는 칸 제외)이 있는 열"""
    out = []
    for col in grid.columns:
        c = grid.cell(row, col)
        if c.origin == "cell" and c.value is not None and not (isinstance(c.value, str) and not c.value.strip()):
            out.append(col)
    return out


def _header_signal(grid, row, head, pattern) -> bool:
    """머리글 신호: row 행 col 칸의 원문 값(병합 복원 전)이 pattern에 맞음"""
    h = grid.cell(row, head.col)
    return h.origin == "cell" and h.value is not None and bool(pattern.search(str(h.value)))


def header_height(grid, head, row, fixed):
    """(머리글 줄 수, 병합 범위 글자 또는 None). rows: fixed면 fixed(프로필 header_rows 줄 수), merge면 신호 칸(row 행 col)의
    세로 병합 높이 — 병합 범위 중간이면 row부터 병합 끝 행까지, 병합이 없거나 가로 병합만이면 1"""
    if head.rows == "fixed":
        return fixed, None
    n = col_number(head.col)
    for r1, c1, r2, c2 in grid.merges:
        if r1 <= row <= r2 and col_number(c1) <= n <= col_number(c2):
            return r2 - row + 1, f"{c1}{r1}:{c2}{r2}"
    return 1, None


def _span(grid, head, title_row, title, header_start, end, fixed):
    height, merge = header_height(grid, head, header_start, fixed)
    header = list(range(header_start, header_start + height))
    tall = merge if head.rows == "merge" and height > MAX_MERGE_HEADER_ROWS else None
    return TableSpan(title_row, title, header, header[-1] + 1, end, tall)


def split_tables(grid, tables, header_count):
    """(표 목록, 첫 표 위에 원문 값이 있는 행 목록). 표 시작 = 제목 행 신호(원문 값이 only_columns에만)와
    머리글 신호(제목 + offset 행의 col 칸이 pattern에 맞음)가 둘 다 맞는 행. 머리글 줄 수는 header_height.
    first_without_title이면 첫 제목 표 위에서 위쪽 행이 모두 빈(또는 시트 맨 위) 머리글 신호 행부터 제목 없는 표 하나"""
    only, head = set(tables.title_row.only_columns), tables.header_row
    pattern = re.compile(head.pattern)
    starts = []
    for r in range(1, grid.max_row + 1):
        cols = _raw_cols(grid, r)
        if not cols or not set(cols) <= only:
            continue
        if _header_signal(grid, r + head.offset, head, pattern):
            title = grid.cell(r, cols[0]).value
            starts.append((r, title if isinstance(title, str) else str(title)))
    spans = []
    for k, (r, title) in enumerate(starts):
        end = starts[k + 1][0] - 1 if k + 1 < len(starts) else grid.max_row
        spans.append(_span(grid, head, r, title, r + head.offset, end, header_count))
    stop = starts[0][0] if starts else grid.max_row + 1
    if tables.first_without_title:
        for r in range(1, stop):
            if _header_signal(grid, r, head, pattern):
                spans.insert(0, _span(grid, head, None, None, r, stop - 1, header_count))
                break
            if _raw_cols(grid, r):
                break   # 신호 행 위에 값이 있는 행이 있으면 제목 없는 표가 아니다
    above = [r for r in range(1, spans[0].start if spans else 1) if _raw_cols(grid, r)]
    return spans, above


def build_tables(grid, sp, file, issues, required_roles=()) -> list:
    """시트 하나 → 표 목록. 프로필 tables가 없으면 build_table 하나(지금 그대로). 있으면 표마다 build_table:
    필수 역할이 없는 표는 그 표만 건너뛰고 header_not_found(위치 = 그 표 머리글), 첫 표 위의 값은 unsupported_layout,
    표를 하나도 못 찾으면 header_not_found + 시트 건너뜀"""
    if sp.tables is None:
        table = build_table(grid, sp, file, issues, required_roles)
        return [] if table is None else [table]
    spans, above = split_tables(grid, sp.tables, len(sp.header_rows))
    if not spans:
        issues.add("header_not_found", f"{file} 시트 \"{grid.name}\": tables 신호(제목 행·머리글)에 맞는 표가 없어 "
                   "시트를 건너뜁니다", file=file, sheet=grid.name)
        return []
    if above:
        issues.add("unsupported_layout", f"{file} 시트 \"{grid.name}\": 첫 표(제목 {spans[0].title_row}행) 위의 값을 "
                   "건너뜁니다(표 제목·머리글 신호에 맞지 않음)",
                   [Location(file=file, sheet=grid.name, rows={"start": above[0], "end": spans[0].title_row - 1})],
                   file=file, sheet=grid.name)
    out = []
    for k, span in enumerate(spans):
        if span.tall_merge is not None:   # rows: merge인데 머리글로 보기엔 너무 높은 병합
            issues.add("header_not_found", f"{file} 시트 \"{grid.name}\" {span.where}: 머리글 신호 칸 병합 {span.tall_merge}이 "
                       f"{len(span.header_rows)}줄이라(머리글은 {MAX_MERGE_HEADER_ROWS}줄까지) 이 표를 건너뜁니다",
                       [_location(file, grid.name, span.header_rows)], file=file, sheet=grid.name)
            continue
        # 다음 표 제목이 이 표 머리글 안에 걸리거나(신호가 잘못 잡힘) 데이터 행이 없는 표는 조용히 넘기지 않는다(리뷰 2026-10-13)
        if span.first > span.last:
            nxt = spans[k + 1].title_row if k + 1 < len(spans) else None
            why = (f"다음 표 제목({nxt}행)이 이 표 머리글 안에 있습니다" if nxt is not None and nxt <= span.header_rows[-1]
                   else "데이터 행이 없습니다")
            issues.add("unsupported_layout", f"{file} 시트 \"{grid.name}\" {span.where}: {why} — 이 표를 "
                       "건너뜁니다(tables 신호 확인)",
                       [Location(file=file, sheet=grid.name,
                                 rows={"start": span.start, "end": max(span.start, (nxt or span.last + 1) - 1)})],
                       file=file, sheet=grid.name)
            continue
        table = build_table(grid, sp, file, issues, required_roles, span=span)
        if table is not None:
            out.append(table)
    return out


def build_table(grid, sp, file, issues, required_roles=(), span=None) -> Table | None:
    """시트 하나(또는 span: 한 시트 여러 표의 표 하나)를 표로 해석한다. 머리글을 못 찾으면 header_not_found + None
    (시트 또는 그 표 건너뜀). required_roles: 부르는 쪽이 더 요구하는 역할(예: id_ref 대상 쪽이면 "id")"""
    header_rows = list(sp.header_rows) if span is None else list(span.header_rows)
    where = f"시트 \"{grid.name}\"" if span is None else f"시트 \"{grid.name}\" {span.where}"
    skip = "시트를 건너뜁니다" if span is None else "이 표를 건너뜁니다"
    headers, header_parts = _headers(grid, header_rows)
    if not headers:
        issues.add("header_not_found", f"{file} {where}: 머리글 행 {header_rows}이 비어 있습니다",
                   [_location(file, grid.name, header_rows)], file=file, sheet=grid.name)
        return None

    cols = sp.columns
    roles, matches, missing, overlaps, chosen = {}, {}, [], {}, {}
    hierarchy = []
    for sel in cols.hierarchy:
        found = _match(sel, headers, grid.columns)
        if not found:
            missing.append(f"hierarchy {_describe(sel)}")
        elif len(found) > 1 and sel.header_pattern is None:
            overlaps.setdefault("hierarchy", []).extend(c for c in found if c not in overlaps.get("hierarchy", []))
        else:
            for c in found:
                if c not in hierarchy:   # 선택자 두 개가 같은 열을 고르면 한 번만
                    hierarchy.append(c)
                    chosen.setdefault("hierarchy", []).append((c, sel))
    if cols.hierarchy:
        matches["hierarchy"] = [(c, headers.get(c)) for c in hierarchy]
        if hierarchy and "hierarchy" not in overlaps:
            roles["hierarchy"] = hierarchy
    for role in SINGLE_ROLES:
        sel = getattr(cols, role)
        if sel is None:
            continue
        found = _match(sel, headers, grid.columns)
        matches[role] = [(c, headers.get(c)) for c in found]
        chosen[role] = [(c, sel) for c in found]
        if len(found) > 1:
            overlaps[role] = found
        elif found:
            roles[role] = found
    excluded = []
    for sel in cols.exclude_from_text:
        for c in _match(sel, headers, grid.columns):
            if c not in excluded:
                excluded.append(c)
                chosen.setdefault("exclude_from_text", []).append((c, sel))
    if cols.exclude_from_text:
        matches["exclude_from_text"] = [(c, headers.get(c)) for c in excluded]
        if excluded:
            roles["exclude_from_text"] = excluded

    required = set(required_roles)
    if sp.hierarchy.method in HIERARCHY_REQUIRED:
        required.add("hierarchy")
    if sp.item_boundary.method == "continuation":
        required.add(sp.item_boundary.key_role)
    for role in sorted(required):
        if role not in roles and role not in overlaps and not any(m.startswith(role) for m in missing):
            missing.append(f"{role} (필수 역할, 선택자 {'없음' if getattr(cols, role, None) in (None, []) else '못 찾음'})")

    if missing or overlaps:
        parts = []
        if overlaps:
            parts += [f"{role}에 열 {', '.join(c)}이 함께 걸립니다(열이 하나여야 함)" for role, c in overlaps.items()]
        if missing:
            parts.append("못 찾은 선택자: " + ", ".join(missing))
        overlap_cols = sorted({c for c in sum(overlaps.values(), [])}, key=lambda c: (len(c), c)) or None
        issues.add("header_not_found", f"{file} {where}: " + "; ".join(parts) + f" — {skip}",
                   [_location(file, grid.name, header_rows, overlap_cols)], file=file, sheet=grid.name)
        return None

    data_rows = _data_rows(grid, sp) if span is None else _data_rows(grid, sp, span.first, span.last)
    if sp.hidden_rows == "skip":
        hidden = [r for r in data_rows if r in grid.hidden_rows]
        if hidden:
            data_rows = [r for r in data_rows if r not in grid.hidden_rows]
            outline = sum(grid.hidden_rows[r] == "outline" for r in hidden)
            kinds = ", ".join(t for t in (f"그룹 접기 {outline}줄" if outline else "",
                                          f"그냥 숨김 {len(hidden) - outline}줄" if len(hidden) > outline else "") if t)
            issues.add("hidden_content", f"{file} 시트 \"{grid.name}\": 숨김 행 {len(hidden)}줄({kinds})을 건너뛰었습니다"
                       "(hidden_rows: skip)",
                       [Location(file=file, sheet=grid.name, rows={"start": a, "end": b}) for a, b in _runs(hidden)],
                       file=file, sheet=grid.name)
    return Table(file, grid.name, grid, header_rows, headers, roles, data_rows, matches, chosen, header_parts,
                 sp.id_pattern, span.title if span else None, span.title_row if span else None,
                 sp.tables.title_to if span else None, span is not None and span.untitled)


def _raw_text(cell):
    """원문 값(병합 복원 전)의 글자, 없거나 공백뿐이면 None"""
    if cell.origin != "cell" or cell.value is None:
        return None
    text = cell.value if isinstance(cell.value, str) else str(cell.value)
    return text.strip() or None


def _blocks(cells):
    """(행, 열 번호) 칸들을 위아래·좌우로 이어진 덩어리로(너비 우선으로 찾기, BFS). 덩어리마다 칸 목록, 첫 칸 순서"""
    left, out = set(cells), []
    for start in sorted(cells):
        if start not in left:
            continue
        left.discard(start)
        block, queue = [], [start]
        while queue:
            r, c = queue.pop(0)
            block.append((r, c))
            for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if nb in left:
                    left.discard(nb)
                    queue.append(nb)
        out.append(sorted(block))
    return out


LIMIT_ABOVE_HEADER = "above_header"   # 처리 보고서 0절 「알려진 한계」 구분(Issue.limit, 출력 칸 아님)
LIMIT_HEADERLESS = "headerless"


def above_header_warnings(tables, issues, read_cells=frozenset()) -> list:
    """한 시트의 표들마다 머리글 행보다 위의 원문 값 칸 중 어느 기능도 읽지 않는 칸을 세서 unsupported_layout 1건
    (위치 = 값 있는 첫 행부터 끝 행까지, 메시지 = 행 범위·칸 수, 셀 값 없음). 표 제목·작성자 칸도 센다.
    읽는 방식은 그대로.
    - 표 하나짜리 시트(tables 설정 없음): 1행부터 머리글 바로 위까지.
    - tables 설정 시트: 표마다 제목 행부터 머리글 바로 위까지. 제목 행의 첫 값 칸은 표 제목(table_title)으로 읽히므로 뺀다.
      첫 표 위의 값은 build_tables의 「첫 표 위의 값」 경고가 이미 알리므로 세지 않는다. 앞 표 데이터 뒤의 행은 앞 표 범위다.
      제목 없는 표(first_without_title)는 위쪽이 모두 빈 행이라 셀 것이 없다.
    - 다른 기능이 읽는 칸은 뺀다: read_cells {(시트, 행, 열)}(표지 버전 읽기의 라벨·값 칸, extract.cover_cells),
      머리글 행까지 내려오는 세로 병합의 시작 칸(병합 복원으로 머리글 글자·항목 칸에 들어감).
    돌려주는 값: [(파일, 시트, 첫 행, 끝 행, 칸 수)] — 처리 보고서 0절 「알려진 한계」용"""
    found = []
    for table in tables:
        grid, head = table.grid, table.header_rows[0]
        if table.title_row is not None:
            top, read = table.title_row, {(table.title_row, _raw_cols(grid, table.title_row)[0])}
        elif table.untitled:
            continue
        else:
            top, read = 1, set()
        read |= {(r, c) for s, r, c in read_cells if s == table.sheet}
        read |= {(r1, c1) for r1, c1, r2, c2 in grid.merges if r1 < head <= r2}
        cells = [r for r in range(top, head) for c in grid.columns
                 if (r, c) not in read and _raw_text(grid.cell(r, c)) is not None]
        if cells:
            a, b = min(cells), max(cells)
            issues.add("unsupported_layout",
                       f"{table.file} {table_where(table)}: 머리글 행({head}행) 위 {a}~{b}행에 값 있는 칸 {len(cells)}칸 — "
                       "표 밖이라 읽지 않습니다(표 제목·작성자 등일 수 있음, 알려진 한계)",
                       [Location(file=table.file, sheet=table.sheet, rows={"start": a, "end": b})],
                       file=table.file, sheet=table.sheet, limit=LIMIT_ABOVE_HEADER)
            found.append((table.file, table.sheet, a, b, len(cells)))
    return found


def table_warnings(table, sp, issues) -> None:
    """표 배치 경고(실행 때). 읽는 방식은 바꾸지 않고 경고만 낸다.
    R1 머리글 없는 열의 원문 값 덩어리(데이터 행 안, 어느 항목에도 안 들어감) → unsupported_layout 덩어리마다 1건
    R2 tables 설정이 없는 시트에서 머리글 마지막 줄과 글자가 같은 데이터 행(반복 머리글) → unsupported_layout 1건(행마다 위치)
    R3 숨김 열에 원문 값 → hidden_content 열마다 1건"""
    grid, file = table.grid, table.file
    where = table_where(table)
    index = {c: i for i, c in enumerate(grid.columns)}
    # 머리글 있는 열까지 덮는 가로 병합의 시작 칸은 그 열의 merged_fields로 항목에 들어가므로 덩어리가 아니다
    into_header = {(r1, c1) for r1, c1, r2, c2 in grid.merges
                   if any(c in table.headers for c in grid.columns[index[c1]:index[c2] + 1])}
    # 숨김 열의 값은 R3(hidden_content)에서만 알린다(같은 칸을 두 경고로 내지 않음)
    loose = [(r, index[c]) for c in grid.columns if c not in table.headers and c not in grid.hidden_cols
             for r in table.data_rows if _raw_text(grid.cell(r, c)) is not None and (r, c) not in into_header]
    for block in _blocks(loose):
        rows = [r for r, _ in block]
        cols = [grid.columns[i] for i in sorted({i for _, i in block})]
        issues.add("unsupported_layout",
                   f"{file} {where}: 머리글 없는 열 {', '.join(cols)}의 값 덩어리({min(rows)}~{max(rows)}행)는 어느 항목에도 "
                   "들어가지 않습니다(표 밖 메모·다른 표일 수 있음, 읽지 않음)",
                   [Location(file=file, sheet=table.sheet, rows={"start": min(rows), "end": max(rows)}, cols=cols)],
                   file=file, sheet=table.sheet, limit=LIMIT_HEADERLESS)
    if sp.tables is not None:
        # 표 안 데이터 행에서 머리글 신호가 다시 맞음 = 제목 행 신호가 없어 표로 나뉘지 않은 머리글 행이 항목이 됨.
        # 읽는 방식은 그대로, 경고만
        head = sp.tables.header_row
        pattern = re.compile(head.pattern)
        again = [r for r in table.data_rows if _header_signal(grid, r, head, pattern)]
        if again:
            issues.add("unsupported_layout",
                       f"{file} {where}: 데이터 행에서 머리글 신호가 다시 맞는 행 {len(again)}줄 — 제목 행이 없어 표로 나뉘지 않고 "
                       "이 표의 항목이 됩니다(tables 신호·first_without_title 검토)",
                       [Location(file=file, sheet=table.sheet, rows={"start": r, "end": r}) for r in again],
                       file=file, sheet=table.sheet)
    if sp.tables is None:
        # 머리글 쪽은 병합 복원 글자까지(다단 머리글의 세로 병합), 데이터 쪽은 원문 칸 — 머리글 칸 전부와 같아야 반복 머리글
        head = {c: str(v).strip() for c in table.headers
                if (v := grid.cell(table.header_rows[-1], c).value) is not None and str(v).strip()}
        repeated = [r for r in table.data_rows
                    if head and all(_raw_text(grid.cell(r, c)) == t for c, t in head.items())]
        if repeated:
            issues.add("unsupported_layout",
                       f"{file} {where}: 머리글과 글자가 같은 행(반복 머리글) {len(repeated)}줄 — 한 시트에 표가 여러 개일 수 있습니다"
                       "(tables 설정 검토). 항목은 그대로 만듭니다",
                       [Location(file=file, sheet=table.sheet, rows={"start": r, "end": r}) for r in repeated],
                       file=file, sheet=table.sheet)
    for c in grid.hidden_cols:
        rows = [r for r in table.data_rows if _raw_text(grid.cell(r, c)) is not None]
        if rows:
            issues.add("hidden_content",
                       f"{file} {where}: 숨김 열 {c}에 값이 {len(rows)}칸 있습니다(숨김 열도 그대로 읽음)",
                       [Location(file=file, sheet=table.sheet, rows={"start": min(rows), "end": max(rows)}, cols=[c])],
                       file=file, sheet=table.sheet)

