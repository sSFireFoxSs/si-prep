"""엑셀 읽기 — openpyxl을 쓰는 유일한 모듈.

칸 값(원문)·출처(cell / merge_restored / empty)·숨김·수식 계산값 없음만 돌려준다. 열의 역할·헤더는 모른다(layout).
- 파일 형식은 확장자 + 파일 앞부분(zip / OLE)으로 판단한다. 미지원이면 unsupported 경고 후 None.
- 병합 색인은 시트당 한 번 만든다. 데이터 범위는 max_row가 아니라 실제 값·병합 경계로 계산한다.
- 칸 메모·취소선·색은 읽지 않는다. 매크로는 실행·보존하지 않는다(keep_vba 끔).
- 값은 고치지 않는다. 날짜·시각은 ISO 문자열, 경과 시간은 「총 시:분:초」 글자로 바꾼다(JSON에 그 타입이 없음).
  빈 글자("") 칸은 빈칸으로 본다. 수식 오류 값(#REF! 등)은 원문 그대로 두고 error로 표시한다.
  숫자 칸의 서식(일반 아님)은 number_format에 기록만 한다.
"""

import zipfile
from xml.etree.ElementTree import ParseError
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import openpyxl
from openpyxl.chartsheet import Chartsheet
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.utils.exceptions import InvalidFileException

SUPPORTED_SUFFIXES = (".xlsx", ".xlsm")
LOCK_PREFIX = "~$"                               # 엑셀이 열려 있을 때 생기는 잠금 파일
ZIP_SIGNATURE = b"PK\x03\x04"                    # .xlsx·.xlsm
OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")  # 옛 엑셀(.xls) 또는 암호 걸린 파일


@dataclass(frozen=True)
class Cell:
    value: object                  # 원문 값(str·int·float·bool), 날짜는 ISO 문자열, 없으면 None
    origin: str                    # cell / merge_restored / empty
    row: int                       # 1부터
    col: str                       # 열 문자
    hidden: bool = False           # 행 또는 열이 숨김
    formula_no_value: bool = False  # 수식인데 저장된 계산값이 없음
    merge_start: tuple | None = None  # 이 칸이 든 병합 범위의 시작 칸 (행, 열 문자). 병합 밖이면 None
    error: bool = False            # 수식 오류 값(#REF!, #N/A 등). 값은 원문 그대로
    number_format: str | None = None  # 숫자 칸의 서식(일반 서식이면 None). 기록만 한다


@dataclass(frozen=True)
class _Stored:
    value: object
    no_value: bool
    error: bool
    number_format: str | None


@dataclass
class SheetGrid:
    name: str
    hidden: bool                   # 시트 숨김(hidden·veryHidden)
    is_chart: bool = False         # 칸이 없는 차트 시트
    max_row: int = 0               # 실제 값·병합 경계의 마지막 행(없으면 0)
    columns: list = field(default_factory=list)       # A부터 실제 마지막 열까지의 열 문자
    merges: list = field(default_factory=list)        # (시작 행, 시작 열, 끝 행, 끝 열) — 열은 문자
    hidden_rows: dict = field(default_factory=dict)   # 행 → "hidden"(그냥 숨김) / "outline"(그룹 접기)
    hidden_cols: tuple = ()                            # 숨김 열 문자, 열 순서(결정성)
    _values: dict = field(default_factory=dict, repr=False)   # (행, 열 번호) → _Stored
    _merge_of: dict = field(default_factory=dict, repr=False)  # (행, 열 번호) → (시작 행, 시작 열 번호)
    _lines: dict = field(default_factory=dict, repr=False)     # (행, 열 번호) → (위 선, 아래 선) 가로 테두리가 있는 칸만

    def line_above(self, row: int, col: str) -> bool:
        """이 칸 위에 가로 선이 있는지: 이 칸의 위 테두리나 바로 위 칸의 아래 테두리(테두리 묶음, B1).
        셀 서식의 테두리만 본다 — 조건부 서식·표 스타일로 그린 선은 읽지 못한다"""
        c = column_index_from_string(col)
        return self._lines.get((row, c), (False, False))[0] or self._lines.get((row - 1, c), (False, False))[1]

    def cell(self, row: int, col: str) -> Cell:
        c = column_index_from_string(col)
        hidden = row in self.hidden_rows or col in self.hidden_cols
        start = self._merge_of.get((row, c))
        merge_start = (start[0], get_column_letter(start[1])) if start else None
        if (row, c) in self._values:
            v = self._values[(row, c)]
            return Cell(v.value, "cell", row, col, hidden, v.no_value, merge_start, v.error, v.number_format)
        if start and start != (row, c) and start in self._values:
            v = self._values[start]
            if v.value is not None:
                return Cell(v.value, "merge_restored", row, col, hidden, False, merge_start, v.error, v.number_format)
            return Cell(None, "empty", row, col, hidden, v.no_value, merge_start)   # 시작 칸이 계산값 없는 수식
        return Cell(None, "empty", row, col, hidden, False, merge_start)


@dataclass
class Workbook:
    file: str                      # 파일 이름만 (위치 규칙, schema.py)
    sheets: list                   # SheetGrid, 통합 문서 안 시트 순서

    def sheet(self, name: str) -> SheetGrid:
        for s in self.sheets:
            if s.name == name:
                return s
        raise KeyError(name)


def _unsupported(issues, name, message):
    """지원 범위 밖(형식). 경고 종류는 unsupported, 메시지에 「지원 범위 밖」"""
    issues.add("unsupported", f"{name}: 지원 범위 밖 — {message}", file=name)


def _open_failed(issues, name, message):
    """지원하는 형식인데 열지 못함(처리 실패) → read_failed (스키마 1.2)"""
    issues.add("read_failed", f"{name}: 처리 실패 — {message}", file=name)


def _check_format(path, issues) -> bool:
    name, suffix = path.name, path.suffix.lower()
    if name.startswith(LOCK_PREFIX):
        _unsupported(issues, name, "엑셀 잠금 파일(~$)은 입력이 아닙니다. 엑셀을 닫고 다시 실행하세요")
        return False
    if suffix not in SUPPORTED_SUFFIXES:
        what = "옛 엑셀 형식(.xls)" if suffix == ".xls" else f"{suffix or '확장자 없는'} 형식"
        _unsupported(issues, name, f"{what}은 지원하지 않습니다(.xlsx·.xlsm만). .xlsx로 저장해서 넣으세요")
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(8)
    except OSError as e:
        _open_failed(issues, name, f"파일을 열 수 없습니다({e.strerror or type(e).__name__})")
        return False
    if head == OLE_SIGNATURE:
        _unsupported(issues, name, f"확장자는 {suffix}이지만 실제로는 옛 엑셀 형식(.xls)이거나 암호가 걸린 파일입니다. "
                                   "암호를 풀고 .xlsx로 저장해서 넣으세요")
        return False
    if not head.startswith(ZIP_SIGNATURE):
        _open_failed(issues, name, "파일을 열 수 없습니다. 엑셀 파일 형식이 아닙니다(파일이 손상됐을 수 있음)")
        return False
    return True


def _elapsed(value: timedelta) -> str:
    """경과 시간 → 「총 시:분:초」 (예: 1일 2시간 30분 → 26:30:00)"""
    total = round(value.total_seconds())
    sign, total = ("-", -total) if total < 0 else ("", total)
    return f"{sign}{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"


def _iso(value):
    """날짜·시각 → ISO 글자(시각이 00:00이면 날짜만), 경과 시간 → 총 시:분:초. 그 밖은 그대로"""
    if isinstance(value, timedelta):
        return _elapsed(value)
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    return value


def _merge_index(ws):
    """칸 → 병합 범위 시작 칸. 시트당 한 번만 만든다"""
    index, ranges = {}, []
    for rng in ws.merged_cells.ranges:
        ranges.append((rng.min_row, rng.min_col, rng.max_row, rng.max_col))
        for r in range(rng.min_row, rng.max_row + 1):
            for c in range(rng.min_col, rng.max_col + 1):
                index[(r, c)] = (rng.min_row, rng.min_col)
    return index, sorted(ranges)


def _hidden_cols(ws):
    """column_dimensions는 여러 열을 한 항목(min~max)으로 저장할 수 있어 범위를 펼친다"""
    out = set()
    for key, dim in ws.column_dimensions.items():
        if dim.hidden:
            lo = dim.min or column_index_from_string(key)
            hi = dim.max or lo
            out.update(range(lo, hi + 1))
    return tuple(get_column_letter(i) for i in sorted(out))


def _has_line(side):
    return side is not None and side.style is not None


def _line_index(ws):
    """저장된 칸(값 없는 칸 포함)의 가로 테두리. 시트당 한 번"""
    out = {}
    for key, c in ws._cells.items():
        b = c.border
        top, bottom = _has_line(b.top), _has_line(b.bottom)
        if top or bottom:
            out[key] = (top, bottom)
    return out


def _read_sheet(ws_values, ws_formulas) -> SheetGrid:
    hidden = ws_values.sheet_state != "visible"
    if isinstance(ws_values, Chartsheet):
        return SheetGrid(ws_values.title, hidden, is_chart=True)
    merge_of, ranges = _merge_index(ws_values)
    # 파일에 실제로 저장된 칸만 돈다. iter_rows는 max_row·max_column(서식만 남은 먼 칸 때문에 부풀 수 있음)까지
    # 빈 칸 객체를 새로 만들어서, 부푼 시트에서는 수천만 칸이 생긴다. _cells는 openpyxl 비공개 속성(3.1.x에서 확인)
    stored_f, stored_v = ws_formulas._cells, ws_values._cells
    values = {}
    for key in sorted(set(stored_f) | set(stored_v)):
        cf, cv = stored_f.get(key), stored_v.get(key)
        if all(c is None or c.value is None or c.value == "" for c in (cf, cv)):
            continue   # 빈 글자("")도 빈칸
        is_formula = cf is not None and cf.data_type == "f"
        raw = cv.value if cv is not None else None
        value = None if raw == "" else _iso(raw)
        fmt = cv.number_format if cv is not None else None
        number_format = fmt if isinstance(raw, (int, float)) and not isinstance(raw, bool) and fmt != "General" else None
        values[key] = _Stored(value, is_formula and value is None, cv is not None and cv.data_type == "e", number_format)
    cells = list(values) + [(r2, c2) for _, _, r2, c2 in ranges]
    max_row = max((r for r, _ in cells), default=0)
    max_col = max((c for _, c in cells), default=0)
    hidden_rows = {r: ("outline" if dim.outline_level else "hidden")
                   for r, dim in sorted(ws_values.row_dimensions.items()) if dim.hidden}
    return SheetGrid(
        name=ws_values.title, hidden=hidden, max_row=max_row,
        columns=[get_column_letter(i) for i in range(1, max_col + 1)],
        merges=[(r1, get_column_letter(c1), r2, get_column_letter(c2)) for r1, c1, r2, c2 in ranges],
        hidden_rows=hidden_rows, hidden_cols=_hidden_cols(ws_values),
        _values=values, _merge_of=merge_of, _lines=_line_index(ws_values))


def _load(path, issues, **options):
    """openpyxl로 연다. 열지 못하면 「처리 실패」 경고 후 None (예외를 좁게 잡고 이름을 남긴다)"""
    try:
        return openpyxl.load_workbook(path, **options)
    except OSError as e:   # 권한(엑셀이 파일을 열고 있음) 등
        _open_failed(issues, path.name, f"파일을 열 수 없습니다({e.strerror or type(e).__name__}). 엑셀을 닫고 다시 실행하세요")
    except (zipfile.BadZipFile, InvalidFileException, KeyError, ParseError, ValueError, TypeError) as e:
        # 손상된 파일: zip 안 필요한 부분 없음(KeyError), 깨진 XML(ParseError) 등
        _open_failed(issues, path.name, f"파일을 열 수 없습니다({type(e).__name__}: {e}). 엑셀에서 다시 저장해서 넣으세요")
    return None


def open_workbook(path, issues) -> Workbook | None:
    """엑셀 파일을 읽어 시트 격자 목록을 돌려준다. 지원하지 않거나 열 수 없으면 unsupported 경고 후 None"""
    path = Path(path)
    if not _check_format(path, issues):
        return None
    wb_values = _load(path, issues, data_only=True)        # 저장된 계산값
    wb_formulas = _load(path, issues, data_only=False) if wb_values else None   # 수식인지 알기 위해
    if wb_formulas is None:
        return None
    try:
        sheets = [_read_sheet(wb_values[name], wb_formulas[name]) for name in wb_values.sheetnames]
    finally:
        wb_values.close()
        wb_formulas.close()
    return Workbook(file=path.name, sheets=sheets)


@dataclass(frozen=True)
class SheetInfo:
    name: str
    hidden: bool        # hidden·veryHidden
    is_chart: bool      # 칸이 없는 차트 시트


def sheet_list(path, issues) -> list | None:
    """시트 이름·숨김·차트 여부만 통합 문서 안 순서대로 읽는다(설정 검사의 시트 대조용, 칸은 읽지 않음).
    지원하지 않거나 열 수 없으면 경고 후 None"""
    path = Path(path)
    if not _check_format(path, issues):
        return None
    wb = _load(path, issues, read_only=True)   # 시트 정보만 필요해 가벼운 모드
    if wb is None:
        return None
    try:
        return [SheetInfo(name, wb[name].sheet_state != "visible", isinstance(wb[name], Chartsheet))
                for name in wb.sheetnames]
    finally:
        wb.close()


def sheet_names(path, issues) -> list | None:
    """시트 이름만 통합 문서 안 순서대로"""
    infos = sheet_list(path, issues)
    return None if infos is None else [i.name for i in infos]
