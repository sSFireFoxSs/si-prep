"""항목 경계 등록표 — 데이터 행들을 항목 단위(RowGroup)로 묶는다.

구현: row. 알려졌지만 미구현: continuation, merged_block → 실행 때 시트 건너뜀 + unsupported.
"""

from dataclasses import dataclass

from si_prep.config import ITEM_BOUNDARY_METHODS
from si_prep.registry import Registry

REGISTRY = Registry("item_boundary", known=ITEM_BOUNDARY_METHODS)


@dataclass(frozen=True)
class RowGroup:
    start: int          # 항목이 차지하는 첫 행
    end: int            # 마지막 행
    rep: int            # 대표 행(항목 번호·위치의 기준)


def own_columns(table):
    """항목의 자기 칸: 역할 지정된 열 + 머리글 있는 열 (열 순서)"""
    role_cols = {c for cols in table.roles.values() for c in cols}
    return [c for c in table.grid.columns if c in table.headers or c in role_cols]


def _has_own_value(table, row, cols):
    """원문 칸에 내용이 있는지(병합으로 복원된 값은 원문 칸이 아님). 계산값 없는 수식 칸도 내용이 있는 칸,
    공백만 있는 칸도 원문 값이라 내용이 있는 칸으로 본다(행을 조용히 버리지 않게)"""
    return any(c.origin == "cell" and (c.value is not None or c.formula_no_value)
               for c in (table.grid.cell(row, col) for col in cols))


@REGISTRY.register("row")
def by_row(table, sp, issues) -> list:
    """한 행 = 한 항목. 자기 칸이 모두 빈 행은 건너뜀(경고 없음). 분류 칸이 전부 빈 행도 별도 항목"""
    cols = own_columns(table)
    return [RowGroup(r, r, r) for r in table.data_rows if _has_own_value(table, r, cols)]
