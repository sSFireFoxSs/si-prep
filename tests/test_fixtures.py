"""항목 2-1: 합성 주 문서 4종과 shop 설정의 구조를 확인한다.

기대값은 si_prep 코드가 아니라 "생성기가 어느 칸에 무엇을 넣었는지"로만 본다.
"""

import re
import zipfile
from pathlib import Path

import openpyxl
import pytest
import yaml

import real_terms
from fixtures import make_fixtures

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(__file__).parent / "fixtures" / "configs" / "shop"
INTAKE_DIR = ROOT / "docs" / "intake"

FO = "가상몰_기능정의서_v1.2.xlsx"
TEST = "가상몰_테스트케이스.xlsx"
BO = "가상몰_관리자기능정의서.xlsx"
POLICY = "가상몰_정책정의서.xlsx"
REQ = "가상몰_요구사항정의서.xlsx"
MAIN_FILES = [REQ, FO, BO, POLICY, TEST]
VARIATION = "가상몰_변형.xlsx"
OLE_FILES = ["가상몰_옛형식.xls", "가상몰_가짜확장자.xlsx"]  # zip이 아님(openpyxl로 못 엶)


def _load(generated_dir, name):
    return openpyxl.load_workbook(generated_dir / name)


def _merged(ws):
    return {str(r) for r in ws.merged_cells.ranges}


# ---------- 파일 생성 ----------

def test_main_files_created(generated_dir):
    for name in MAIN_FILES:
        assert (generated_dir / name).is_file(), name


# ---------- 기능정의서 (fo) ----------

def test_fo_sheets_and_cover(generated_dir):
    wb = _load(generated_dir, FO)
    assert wb.sheetnames == ["표지", "개정이력", "회원", "주문", "고객센터", "요약"]  # 고객센터: 2026-10-06 승인
    cover = wb["표지"]
    assert cover["B5"].value == "버전"
    assert cover["C5"].value == "v1.3"  # 파일 이름 버전(1.2)과 일부러 다름


def test_fo_menu_sheet_two_row_header(generated_dir):
    ws = _load(generated_dir, FO)["회원"]
    assert ws["B4"].value == "분류"
    assert [ws.cell(5, c).value for c in range(2, 5)] == ["1단계", "2단계", "3단계"]
    assert ws["E4"].value == "기능명"
    assert ws["F4"].value == "설명"
    assert {"B4:D4", "E4:E5", "F4:F5"} <= _merged(ws)


def test_fo_member_sheet_cases(generated_dir):
    ws = _load(generated_dir, FO)["회원"]
    merged = _merged(ws)
    # 분류 병합(merge_restored 대상)
    assert {"B6:B8", "C6:C7"} <= merged
    # 설명 칸이 빈 항목 (not_written)
    assert ws["E8"].value and ws["F8"].value is None
    # 9행: 3단계 빈칸 → 경로 2단계에서 끝
    assert ws["B9"].value and ws["C9"].value and ws["D9"].value is None
    # 10행: 2단계 빈칸(병합 아님), 3단계 있음 → 중간 빈 단계
    assert ws["B10"].value == "회원탈퇴"
    assert ws["C10"].value is None and not any("C10" in r for r in merged)
    assert ws["D10"].value == "탈퇴 사유"


def test_fo_order_sheet_stop_marker(generated_dir):
    ws = _load(generated_dir, FO)["주문"]
    assert ws["C8"].value == "배송지변경"  # 테스트 쪽 "배송지 변경"과 공백만 다름
    assert str(ws["B9"].value).startswith("※")


def test_fo_overview_sheet(generated_dir):
    wb = _load(generated_dir, FO)
    ws = wb["요약"]
    assert ws["B4"].value == "메뉴"
    assert [ws.cell(5, c).value for c in range(3, 6)] == ["1단계", "2단계", "3단계"]
    member = wb["회원"]
    order = wb["주문"]
    # 1행은 메뉴 시트와 설명이 같고, 1행은 다르다
    assert ws["G6"].value == member["F6"].value
    assert ws["G7"].value != order["F6"].value
    assert [ws.cell(7, c).value for c in range(2, 6)] == ["주문", "결제", "결제 수단", "카드 결제"]


def test_fo_real_layout_sheet(generated_dir):
    """흔한 SI 양식 구조: 제목·업데이트 행, NO. 열, 4칸 병합 분류, 큰 세로 병합, 여러 줄 설명, 대부분 빈 비고"""
    ws = _load(generated_dir, FO)["고객센터"]
    merged = _merged(ws)
    assert ws["B1"].value and str(ws["B2"].value).startswith("문서 업데이트: ")
    assert ws["B4"].value == "NO." and "B4:B5" in merged
    assert [ws.cell(r, 2).value for r in range(6, 18)] == list(range(1, 13))
    assert ws["C4"].value == "분류" and "C4:F4" in merged
    assert [ws.cell(5, c).value for c in range(3, 7)] == ["1단계", "2단계", "3단계", "4단계"]
    big = [r for r in ws.merged_cells.ranges if r.min_row >= 6]
    assert max(r.max_row - r.min_row + 1 for r in big) >= 10
    multi = [ws.cell(r, 8).value for r in range(6, 18) if "\n- " in str(ws.cell(r, 8).value)]
    assert len(multi) >= 2
    assert ws["I4"].value == "비고"
    assert sum(ws.cell(r, 9).value is not None for r in range(6, 18)) == 2  # 12행 중 2행만


# ---------- 테스트케이스 (test) ----------

def test_test_case_file(generated_dir):
    ws = _load(generated_dir, TEST).worksheets[0]
    header = [c.value for c in ws[1] if c.value is not None]
    assert header == ["케이스 ID", "요구사항 ID", "메뉴", "1단계", "2단계", "3단계", "테스트명", "기대결과", "수행자",
                      "결과(검수자1)", "결과(검수자2)", "결과(검수자3)"]  # 결과 열: 2026-10-06 승인
    refs = [ws.cell(r, 3).value for r in range(2, 7)]
    assert refs == ["REQ-001", "REQ-001, REQ-002", "REQ-999", None, "요구사항 미정"]
    paths = [tuple(v for v in (ws.cell(r, c).value for c in range(4, 8)) if v) for r in range(2, 6)]
    assert paths == [
        ("회원", "로그인", "일반 로그인", "아이디 입력"),
        ("회원", "로그인", "일반 로그인", "비밀번호 입력"),
        ("주문", "결제", "결제 수단", "카드 결제"),
        ("주문", "배송", "배송지 변경"),
    ]


# ---------- 정책정의서 (policy) ----------

def test_policy_file(generated_dir):
    wb = _load(generated_dir, POLICY)
    assert wb.sheetnames == ["주문 - 결제", "회원 - 로그인", "쿠폰 - 발급", "주문 - 배송", "결제 수단 목록"]  # 2026-10-06 승인
    data_rows = {name: sum(1 for r in range(2, wb[name].max_row + 1) if wb[name].cell(r, 2).value) for name in wb.sheetnames}
    assert data_rows == {"주문 - 결제": 2, "회원 - 로그인": 1, "쿠폰 - 발급": 1, "주문 - 배송": 2, "결제 수단 목록": 3}


def test_policy_narrative_and_list_sheets(generated_dir):
    wb = _load(generated_dir, POLICY)
    narrative = wb["주문 - 배송"]  # 서술형: 2단 구분(머리글 병합) + 정책 내용 + 비고
    assert narrative["B1"].value == "세부 구분" and "B1:C1" in _merged(narrative)
    assert [narrative["D1"].value, narrative["E1"].value] == ["정책 내용", "비고"]
    assert "B2:B3" in _merged(narrative) and narrative["C2"].value and narrative["C3"].value
    listing = wb["결제 수단 목록"]  # 목록형: 머리글 모양이 다른 표, 시트 이름에 " - " 없음
    assert _headers_row1(listing) == ["수단 코드", "수단 이름", "수수료율", "사용 여부"]
    assert " - " not in listing.title


def _headers_row1(ws):
    return [c.value for c in ws[1] if c.value is not None]


# ---------- 관리자 기능정의서 (bo) ----------

def test_bo_file(generated_dir):
    wb = _load(generated_dir, BO)
    assert wb.sheetnames == ["회원관리", "주문관리"]
    for ws in wb.worksheets:
        assert ws["B4"].value == "분류" and "B4:D4" in _merged(ws)
        assert [ws.cell(5, c).value for c in range(2, 5)] == ["1단계", "2단계", "3단계"]
        assert ws["B6"].value == ws.title  # 1단계 열에 메뉴 이름(시트 이름은 경로에 안 씀)
        assert "B6:B8" in _merged(ws)


def test_bo_test_sheet_and_result_columns(generated_dir):
    wb = _load(generated_dir, TEST)
    assert wb.sheetnames == ["테스트케이스", "BO테스트케이스"]
    fo_ws, bo_ws = wb["테스트케이스"], wb["BO테스트케이스"]
    assert _headers_row1(bo_ws) == _headers_row1(fo_ws)
    paths = [tuple(v for v in (bo_ws.cell(r, c).value for c in range(4, 8)) if v) for r in range(2, 5)]
    assert paths == [("회원관리", "회원 목록", "검색"), ("주문관리", "주문 목록", "상태 변경"),
                     ("주문관리", "주문 목록", "송장입력")]  # BO는 "송장 입력" (공백만 다름)
    for ws in (fo_ws, bo_ws):
        assert [ws.cell(1, c).value for c in (11, 12, 13)] == ["결과(검수자1)", "결과(검수자2)", "결과(검수자3)"]
        values = {ws.cell(r, c).value for r in range(2, ws.max_row + 1) for c in (11, 12, 13)}
        assert values <= {"Pass", "Fail", None} and {"Pass", "Fail"} <= values
    profile = yaml.safe_load((CONFIG_DIR / "profiles" / "test.yaml").read_text(encoding="utf-8"))
    excluded = [s["header_contains"] for s in profile["columns"]["exclude_from_text"]]
    assert {"결과(검수자1)", "결과(검수자2)", "결과(검수자3)"} <= set(excluded)


# ---------- 요구사항정의서 (req) ----------

def test_req_file(generated_dir):
    ws = _load(generated_dir, REQ).worksheets[0]
    assert "B2:B3" in _merged(ws) and ws["B2"].value == "고객"
    ids = [ws.cell(r, 4).value for r in range(2, ws.max_row + 1)]
    assert ids == ["REQ-001", "REQ-002", "REQ-003", "REQ-003"]  # REQ-003 중복(duplicate_id)


# ---------- 같은 코드 두 번 → 같은 내용 ----------

def _structure(path):
    wb = openpyxl.load_workbook(path)
    out = []
    for ws in wb.worksheets:
        cells = sorted((c.coordinate, c.value) for row in ws.iter_rows() for c in row if c.value is not None)
        hidden = sorted(k for k, d in ws.row_dimensions.items() if d.hidden)
        outline = sorted((k, d.outline_level) for k, d in ws.row_dimensions.items() if d.outline_level)
        indent = sorted((c.coordinate, c.alignment.indent) for row in ws.iter_rows() for c in row
                        if c.alignment is not None and c.alignment.indent)
        out.append((ws.title, ws.sheet_state, cells, sorted(_merged(ws)), hidden, outline, indent))
    out.append(("chartsheets", [c.title for c in wb.chartsheets]))
    return out


def test_generation_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_fixtures.generate(a)
    make_fixtures.generate(b)
    for name in MAIN_FILES + [VARIATION]:
        assert _structure(a / name) == _structure(b / name), name
    for name in OLE_FILES:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


# ---------- shop 설정 ----------

def test_shop_config_files(generated_dir):
    project = yaml.safe_load((CONFIG_DIR / "project.yaml").read_text(encoding="utf-8"))
    assert [d["id"] for d in project["doc_types"]] == ["req", "fo", "bo", "policy", "test", "variation"]
    for doc in project["documents"]:
        assert (CONFIG_DIR / doc["profile"]).is_file(), doc["profile"]
        for name in doc["files"]:
            assert (generated_dir / name).is_file(), name
    assert (CONFIG_DIR / project["glossary"]).is_file()
    for profile in (CONFIG_DIR / "profiles").glob("*.yaml"):
        assert yaml.safe_load(profile.read_text(encoding="utf-8"))["id"] == profile.stem


# ---------- 실제 용어가 합성 데이터에 섞이지 않음 ----------

def test_no_real_terms_in_fixtures(generated_dir):
    # 검사 방식·허용 단어는 tests/real_terms.py (목데이터 테스트와 같이 씀)
    strings = real_terms.xlsx_strings(generated_dir.glob("*.xls*"))
    for path in sorted(CONFIG_DIR.rglob("*.yaml")):
        real_terms.nested_strings(yaml.safe_load(path.read_text(encoding="utf-8")), strings)
    real_terms.check_no_real_terms(strings)
