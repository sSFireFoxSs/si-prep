"""분류 표현 등록표 — 항목마다 분류 경로 하나.

구현: columns(병합 복원, 선택적 fill_down), none. 시트 이름을 경로 앞부분으로 붙이는 처리(sheet_as_root, root_separators).
알려졌지만 미구현: split_cell·numbering, indent·parent_id → 실행 때 시트 건너뜀 + unsupported.

경로는 Step(값, 근거, 열) 목록으로 돌려준다(열은 경고 위치·항목 초안용). PathPart(level 포함)로 바꾸는 것은 extract.
상태(ambiguous 등)는 정하지 않는다 — 근거(filled_down·empty)를 보고 extract가 정한다.
"""

from dataclasses import dataclass

from si_prep import layout
from si_prep.config import HIERARCHY_METHODS
from si_prep.normalize import split_sheet_name
from si_prep.registry import Registry
from si_prep.schema import Location

REGISTRY = Registry("hierarchy", known=HIERARCHY_METHODS)


@dataclass(frozen=True)
class Step:
    value: str | None   # 원문 값(빈 단계면 None)
    basis: str          # schema.Basis: sheet_name / cell / merge_restored / filled_down / empty …
    col: str | None     # 값을 읽은 열(시트 이름 단계는 None)


def _root(table, sp):
    """경로 앞부분: 시트 이름 단계(sheet_as_root일 때, root_separators로 쪼갬) 다음 표 제목 단계
    (한 시트 여러 표이고 tables.title_to: path일 때, basis table_title)"""
    root = []
    if sp.sheet_as_root:
        root = [Step(v, "sheet_name" if v is not None else "empty", None)
                for v in split_sheet_name(table.sheet, sp.root_separators or [])]
    if table.table_title is not None and table.title_to == "path":
        root.append(Step(table.table_title, "table_title", None))
    return root


def _text(value):
    return value if isinstance(value, str) or value is None else str(value)


def plain_blank(cell) -> bool:
    """병합 아닌 빈칸(값 없음, 병합 범위 밖) — fill_down이 위 값으로 채우는 칸. by_columns와 처리 보고서 12절이 같이 쓴다"""
    return cell.value is None and cell.merge_start is None


def fill_limit(cells) -> int:
    """위 값으로 채울 수 있는 단계 수: 이 행에서 원문 값이 처음 나온 단계 앞까지(새 값이 없으면 전부)"""
    first_new = next((i for i, c in enumerate(cells) if c.origin == "cell" and c.value is not None), None)
    return len(cells) if first_new is None else first_new


@dataclass(frozen=True)
class BlankCounts:
    """시트 하나의 분류 칸 모양(처리 보고서 12절, 셀 값 없음). 항목 행(경계의 대표 행)의 분류 열 칸만 센다.
    앞쪽 빈칸·행과 전부 빈 행은 by_columns와 같은 판정(_walk, fill_down 켬)으로 실제 채워지는 것만 센다:
    앞쪽 빈칸 행 + 분류 칸 전부 빈 행 = fill_down이면 채운 단계가 있는 항목 수"""
    merged: int          # 병합으로 복원된 칸(병합 시작 칸 제외)
    blank_all: int       # 병합 아닌 빈칸 전부
    blank_front: int     # 그중 위 값으로 채워지는 칸 — 분류 칸이 전부 빈 행은 빼고 셈
    front_rows: int      # 채워지는 칸이 있는 행(전부 빈 행 제외)
    all_blank_rows: int  # 분류 칸이 전부 빈 행 중 채워지는 행
    border_inner: int = 0  # 앞쪽 빈칸 중 위 항목과 사이에 가로 선이 없는 칸 — 가로 선이 있는 분류 열(border_columns)만 셈
                           # (선이 없는 열은 border_groups가 적용되지 않음). 테두리 묶음 안, B1 — border_groups 판단 근거


def blank_counts(table, groups) -> BlankCounts:
    merged = blank_all = blank_front = front_rows = all_blank_rows = border_inner = 0
    lined = set(border_columns(table))
    for cells, _, filled, all_blank, _, gap in _walk(table, groups, fill=True, declared=False):
        merged += sum(c.origin == "merge_restored" for c in cells)
        blank_all += sum(plain_blank(c) for c in cells)
        if all_blank:
            all_blank_rows += bool(filled)
            continue
        blank_front += len(filled)
        front_rows += bool(filled)
        border_inner += sum(cells[i].col in lined and not gap(cells[i].col) for i in filled)
    return BlankCounts(merged, blank_all, blank_front, front_rows, all_blank_rows, border_inner)


def _line_between(grid, upper, row, col):
    """upper행 아래부터 row행 위까지 그 열에 가로 선이 있는지(새 테두리 묶음)"""
    return any(grid.line_above(r, col) for r in range(upper + 1, row + 1))


def border_columns(table):
    """분류 열 중 데이터 행 사이에 가로 선이 하나라도 있는 열(첫 데이터 행 위 = 머리글 아래 선은 빼고 본다)"""
    rows = table.data_rows[1:]
    return [c for c in table.roles.get("hierarchy", []) if any(table.grid.line_above(r, c) for r in rows)]


def _walk(table, groups, fill, declared, border_cols=()):
    """항목마다 (분류 칸, 남길 단계, 채운 단계 번호, 분류 칸 전부 빈 행인지, 테두리로 안 채운 단계 번호, 선 판정 함수).
    by_columns와 12절(blank_counts)이 같이 쓴다.
    fill이면 병합 아닌 빈칸을 위 항목의 경로 값으로 채우되, 이 행에서 원문 값이 처음 나온 단계부터 아래는 채우지 않는다.
    border_cols의 열은 위 항목 행과 이 행 사이에 가로 선이 있으면(새 테두리 묶음의 첫 칸) 채우지 않는다(B1).
    뒤쪽 빈 단계는 버린다(분류 칸이 전부 빈 채로 남으면 단계 수만큼 빈 단계)"""
    cols = table.roles.get("hierarchy", [])
    previous, upper = [], None      # 위 항목의 분류 단계 값(채운 값 포함), 위 항목 대표 행
    for g in groups:
        cells = [table.grid.cell(g.rep, c) for c in cols]
        steps = [Step(_text(c.value), c.origin if c.value is not None else "empty", c.col) for c in cells]
        all_blank = all(c.value is None for c in cells)
        gap = (lambda col, u=upper, r=g.rep: u is not None and _line_between(table.grid, u, r, col))
        filled, cut = [], []
        if fill:
            # 새 값이 없는 행(전부 빈 행, 병합 복원 값만 있는 행)은 모든 단계, 있으면 그 단계 위까지만
            basis = "form_filled" if declared and not all_blank else "filled_down"
            for i in range(fill_limit(cells)):
                if plain_blank(cells[i]) and i < len(previous) and previous[i] is not None:   # 병합 아닌 빈칸만
                    if cells[i].col in border_cols and gap(cells[i].col):
                        cut.append(i)
                        continue
                    steps[i] = Step(previous[i], basis, steps[i].col)
                    filled.append(i)
        last = max((i for i, s in enumerate(steps) if s.value is not None), default=None)
        if cut:   # 테두리로 안 채운 단계는 뒤쪽이어도 버리지 않는다(empty + 경고로 남김, 리뷰 2026-10-13)
            last = max(cut) if last is None else max(last, max(cut))
        kept = steps if last is None else steps[:last + 1]
        previous, upper = [s.value for s in kept], g.rep
        yield cells, kept, filled, all_blank, [cells[i].col for i in cut], gap


@REGISTRY.register("columns")
def by_columns(table, groups, sp, issues) -> list:
    """분류 열 여러 개. 병합 빈칸은 항상 복원(merge_restored). fill_down이면 병합 아닌 빈칸을 위 항목의 경로 값으로
    채우되(filled_down), 이 행에서 원문 값이 처음 나온 단계부터 아래는 채우지 않는다. 뒤쪽 빈 단계는 버리고,
    마지막 값 앞의 빈 단계는 empty + merge_unrestored. 분류 칸이 전부 빈 행: fill_down 켬이면 위 경로 그대로,
    끔이면 모든 단계 empty(단계 수 = 분류 열 수) + merge_unrestored.
    blank_means_above(사람 선언)면 채운 단계는 form_filled(추정 아님). 단 분류 칸이 전부 빈 행은 선언 시트에서도
    filled_down(이어지는 행일 수 있음).
    border_groups(B1)면 테두리로 새 묶음이 시작된 칸은 채우지 않는다(empty + merge_unrestored, 메시지에 이유).
    가로 선이 하나도 없는 분류 열은 테두리 묶음만 끄고 선언대로 채운다 + 「테두리로 묶음을 구분할 수 없음」 경고"""
    fill = getattr(sp.hierarchy, "fill_down", False)
    declared = getattr(sp.hierarchy, "blank_means_above", False)
    border_cols = ()
    if getattr(sp.hierarchy, "border_groups", False):
        border_cols = border_columns(table)
        flat = [c for c in table.roles.get("hierarchy", []) if c not in border_cols]
        if flat:   # 표마다 한 건(한 시트 여러 표면 어느 표인지), 위치 = 머리글 행의 그 열들
            where = layout.table_where(table)
            issues.add("unsupported_layout",
                       f"{table.file} {where}: 테두리로 묶음을 구분할 수 없습니다 — 분류 열 {', '.join(flat)}의 "
                       "데이터 행 사이에 가로 선이 없어 그 열은 border_groups 없이 blank_means_above대로 채웁니다",
                       [Location(file=table.file, sheet=table.sheet,
                                 rows={"start": min(table.header_rows), "end": max(table.header_rows)}, cols=flat)],
                       file=table.file, sheet=table.sheet)
    root = _root(table, sp)
    out = []
    for g, (_, kept, _, _, cut, _) in zip(groups, _walk(table, groups, fill, declared, border_cols)):
        empty_cols = [s.col for s in kept if s.value is None]
        if empty_cols:
            why = (f" — {', '.join(f'{c}{g.rep}' for c in cut)}: 테두리(가로 선)로 새 묶음이 시작됐는데 첫 칸이 비어 "
                   "위 값으로 채우지 않았습니다" if cut else "")
            issues.add("merge_unrestored",
                       f"{table.file} 시트 \"{table.sheet}\" {g.rep}행: 분류 단계가 비어 있는데 병합·채우기로 복원하지 못했습니다"
                       f"(열 {', '.join(empty_cols)}){why}",
                       [Location(file=table.file, sheet=table.sheet, rows={"start": g.start, "end": g.end}, cols=empty_cols)],
                       file=table.file, sheet=table.sheet)
        out.append(root + kept)
    return out


@REGISTRY.register("none")
def by_none(table, groups, sp, issues) -> list:
    """분류 경로 없음. 시트 이름 루트만 있을 수 있다"""
    root = _root(table, sp)
    return [list(root) for _ in groups]
