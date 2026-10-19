"""출력 스키마 ② 항목(Item)·연결(Link)·경고(Warning_)."""

import pytest
from pydantic import ValidationError

from si_prep.schema import (
    EMPTY_STEP, GroupRef, Item, Link, PathPart, Warning_, find_duplicate_links, group_contains,
    path_starts_with, path_text,
)

LOC = {"file": "가상몰_기능정의서_v1.2.xlsx", "sheet": "회원", "rows": {"start": 7, "end": 7}, "cols": ["D"]}


def _path(*steps):
    return [{"level": i, "value": v, "basis": b} for i, (v, b) in enumerate(steps, 1)]


def _item(**over):
    data = {
        "item_id": "IT-000006", "doc_type": "fo", "doc_file": "가상몰_기능정의서_v1.2.xlsx",
        "category_path": _path(("회원", "sheet_name"), ("로그인", "merge_restored"), ("비밀번호 입력", "cell")),
        "category_path_text": "회원 › 로그인 › 비밀번호 입력",
        "raw_fields": {"D": {"header": "분류 / 3단계", "value": "비밀번호 입력"}},
        "locations": [LOC], "doc_version": {"cover": "v1.3", "filename": "1.2"},
        "status": "ok", "profile_source": "approved",
    }
    data.update(over)
    return Item(**data)


# ---------- PathPart ----------

def test_pathpart_value_none_only_when_empty():
    assert PathPart(level=1, value=None, basis="empty").value is None
    with pytest.raises(ValidationError):
        PathPart(level=1, value=None, basis="cell")
    with pytest.raises(ValidationError):
        PathPart(level=1, value="회원", basis="empty")
    with pytest.raises(ValidationError):
        PathPart(level=1, value="", basis="cell")
    with pytest.raises(ValidationError):
        PathPart(level=0, value="회원", basis="cell")
    with pytest.raises(ValidationError):
        PathPart(level=1, value="회원", basis="guess")


# ---------- Item ----------

def test_item_ok_and_defaults():
    item = _item()
    assert item.schema_version == "1.4"   # 2026-10-10 1.2(추가형), 2026-10-13 1.3·1.4(추가형)
    assert item.merged_fields == {} and item.ref_ids == [] and item.title is None


@pytest.mark.parametrize("item_id", ["IT-1", "IT-0000001", "it-000001", "LK-000001", 6])
def test_item_id_format_and_strict(item_id):
    with pytest.raises(ValidationError):
        _item(item_id=item_id)


def test_item_level_must_be_continuous():
    bad = _path(("회원", "sheet_name"), ("로그인", "cell"))
    bad[1]["level"] = 3
    with pytest.raises(ValidationError):
        _item(category_path=bad, category_path_text="회원 › 로그인")


def test_item_path_text_must_match_parts():
    with pytest.raises(ValidationError):
        _item(category_path_text="회원 › 비밀번호 입력")


def test_path_text_empty_steps_and_consecutive_duplicates():
    parts = [PathPart(**p) for p in _path(("회원", "cell"), (None, "empty"), (None, "empty"), ("탈퇴", "cell"))]
    assert path_text(parts) == f"회원 › {EMPTY_STEP} › {EMPTY_STEP} › 탈퇴"  # 빈 단계는 빼지 않음
    dup = [PathPart(**p) for p in _path(("고객센터", "sheet_name"), ("고객센터", "cell"), ("문의", "cell"))]
    assert path_text(dup) == "고객센터 › 문의"  # 연속 중복 제거


def test_item_merged_fields_and_overlap_rule():
    item = _item(merged_fields={"F": {"header": "설명", "value": "공유 설명", "source_row": 2}})
    assert item.merged_fields["F"].source_row == 2
    with pytest.raises(ValidationError):  # raw_fields와 키가 겹치면 에러
        _item(merged_fields={"D": {"header": "분류 / 3단계", "value": "x", "source_row": 2}})
    with pytest.raises(ValidationError):
        _item(merged_fields={"F": {"header": "설명", "value": "x", "source_row": 0}})


@pytest.mark.parametrize("field,value", [
    ("raw_fields", {"d": {"header": "h", "value": "v"}}),   # 키는 열 문자
    ("doc_file", "dir/가상몰.xlsx"),
    ("doc_type", "FO"),
    ("ref_ids", ["REQ-001", "REQ-001"]),                       # 중복 없음
    ("locations", []),                                         # 1개 이상
    ("status", "done"),
    ("profile_source", "manual"),
    ("title", 3),                                              # 글자 칸은 엄격
])
def test_item_rejects_bad_fields(field, value):
    with pytest.raises(ValidationError):
        _item(**{field: value})


def test_item_raw_value_types():
    for v in ("글자", 3, 2.5, True, None):
        assert _item(raw_fields={"D": {"header": "h", "value": v}}).raw_fields["D"].value == v


def test_item_rejects_unknown_field():
    with pytest.raises(ValidationError):
        _item(note="x")


# ---------- Link ----------

def _link(**over):
    data = {"link_id": "LK-000003", "item_a": "IT-000005", "item_b": "IT-000043", "grade": "structural",
            "method": "path_exact", "rule_id": "fo_test", "evidence_text": "분류 경로 일치",
            "evidence_locations": [LOC], "needs_review": False, "profile_source": "approved"}
    data.update(over)
    return Link(**data)


def _group_link(**over):
    data = {"link_id": "LK-000010", "item": "IT-000033", "group": {"doc_type": "fo", "category_path_text": "주문 › 결제"},
            "grade": "structural", "method": "path_normalized", "rule_id": "policy_fo",
            "evidence_text": "시트 이름 = 기능 묶음", "evidence_locations": [LOC], "needs_review": False,
            "profile_source": "approved"}
    data.update(over)
    return Link(**data)


def test_link_two_shapes_ok():
    assert _link().item is None and _group_link().item_a is None


@pytest.mark.parametrize("over", [
    {"item": "IT-000001"},                                     # 두 모양이 섞임
    {"item_b": None},                                          # 반쪽
    {"item_a": None, "item_b": None},                          # 아무 모양도 없음
    {"item_a": "IT-000043", "item_b": "IT-000005"},            # a > b (방향 없음 → 작은 쪽이 a)
    {"item_b": "IT-000005"},                                   # a == b
])
def test_link_shape_and_order_rules(over):
    with pytest.raises(ValidationError):
        _link(**over)


def test_group_link_shape_rules():
    with pytest.raises(ValidationError):
        _group_link(group=None)
    with pytest.raises(ValidationError):
        _group_link(item_a="IT-000001", item_b="IT-000002")


@pytest.mark.parametrize("over", [
    {"grade": "explicit"},                                     # method→grade 고정
    {"method": "id_ref"},
    {"needs_review": True},                                    # inferred가 아닌데 true
    {"method": "name_similarity", "grade": "inferred", "needs_review": False},
    {"evidence_text": ""},                                     # 근거 없는 연결 금지
    {"evidence_locations": []},
    {"rule_id": ""},
    {"link_id": "LK-1"},
])
def test_link_rejects(over):
    with pytest.raises(ValidationError):
        _link(**over)


def test_link_inferred_needs_review():
    assert _link(method="name_similarity", grade="inferred", needs_review=True).needs_review


# ---------- Warning_ ----------

def _warning(**over):
    data = {"warning_id": "WN-000003", "kind": "merge_unrestored", "message": "분류 2단계가 비어 있음",
            "item_ids": ["IT-000009"], "locations": [LOC], "file": "가상몰_기능정의서_v1.2.xlsx", "sheet": "회원"}
    data.update(over)
    return Warning_(**data)


def test_warning_ok_and_file_level():
    assert _warning().kind == "merge_unrestored"
    w = Warning_(warning_id="WN-000027", kind="unsupported", message="지원하지 않는 형식", file="가상몰_옛형식.xls")
    assert w.locations == [] and w.item_ids == [] and w.sheet is None


@pytest.mark.parametrize("over", [
    {"locations": [], "file": None},                           # 위치 없으면 file 필수
    {"kind": "oops"},
    {"message": ""},
    {"item_ids": ["IT-9"]},
    {"file": "dir/a.xlsx"},
    {"warning_id": "WN-000003-1"},
])
def test_warning_rejects(over):
    with pytest.raises(ValidationError):
        _warning(**over)


# ---------- 묶음 연결 판단 (경로 단계 단위) ----------

def _parts(*values):
    return [PathPart(level=i, value=v, basis="cell" if v else "empty") for i, v in enumerate(values, 1)]


def test_group_match_is_step_based_not_text_prefix():
    assert path_starts_with(_parts("회원", "로그인", "아이디 입력"), "회원")
    assert path_starts_with(_parts("회원", "로그인"), "회원 › 로그인")
    assert not path_starts_with(_parts("회원가입", "약관 동의"), "회원")       # 글자 앞부분만 같음 → 아님
    assert not path_starts_with(_parts("회원"), "회원 › 로그인")                # 묶음이 더 깊음
    assert path_starts_with(_parts("주문", "배송지변경"), "주문 › 배송지 변경")  # 단계별 공백 무시(비교 열쇠)
    assert not path_starts_with(_parts(None, "로그인"), f"{EMPTY_STEP} › 로그인")  # 빈 단계는 어디에도 안 맞음


def test_group_contains_checks_doc_type():
    item = _item()
    assert group_contains(GroupRef(doc_type="fo", category_path_text="회원 › 로그인"), item)
    assert not group_contains(GroupRef(doc_type="bo", category_path_text="회원 › 로그인"), item)
    assert not group_contains(GroupRef(doc_type="fo", category_path_text="회원가"), item)


# ---------- 중복 연결 검사 ----------

def test_find_duplicate_links():
    a = _link()
    assert find_duplicate_links([a, _link(link_id="LK-000004", item_b="IT-000044")]) == []
    assert find_duplicate_links([a, _link(link_id="LK-000009")]) == [("fo_test", "IT-000005", "IT-000043")]
    # 같은 짝이라도 규칙이 다르면 근거가 다른 별개 연결
    assert find_duplicate_links([a, _link(link_id="LK-000009", rule_id="other_rule")]) == []
    g = _group_link()
    dup_g = _group_link(link_id="LK-000011", group={"doc_type": "fo", "category_path_text": "주문 ›  결제"})
    assert find_duplicate_links([g, dup_g]) == [("policy_fo", "IT-000033", ("fo", ("주문", "결제")))]


def test_find_duplicate_links_accepts_dicts_in_any_order():
    # rag_core가 jsonl을 dict로 읽었을 때도: 순서만 바꾼 짝을 같은 연결로 본다
    d1 = {"rule_id": "fo_test", "item_a": "IT-000005", "item_b": "IT-000043"}
    d2 = {"rule_id": "fo_test", "item_a": "IT-000043", "item_b": "IT-000005"}
    assert find_duplicate_links([d1, d2]) == [("fo_test", "IT-000005", "IT-000043")]


# ---------- 1.2: GroupRef 시트 목록, read_failed ----------

def test_group_sheets_optional_and_checked():
    assert GroupRef(doc_type="fo", category_path_text="회원").sheets is None            # 1.1 결과도 그대로 통과
    assert GroupRef(doc_type="fo", category_path_text="회원", sheets=["회원", "주문"]).sheets == ["회원", "주문"]
    for bad in ([], ["회원", "회원"], [""]):
        with pytest.raises(ValidationError):
            GroupRef(doc_type="fo", category_path_text="회원", sheets=bad)


def test_group_contains_respects_sheets():
    item = _item()                                                   # 시트 「회원」
    assert group_contains(GroupRef(doc_type="fo", category_path_text="회원 › 로그인", sheets=["회원"]), item)
    assert not group_contains(GroupRef(doc_type="fo", category_path_text="회원 › 로그인", sheets=["요약"]), item)


def test_duplicate_group_links_differ_by_sheets():
    g = _group_link()
    other = _group_link(link_id="LK-000011", group={"doc_type": "fo", "category_path_text": "주문 › 결제", "sheets": ["주문"]})
    assert find_duplicate_links([g, other]) == []


def test_read_failed_warning_kind():
    w = Warning_(warning_id="WN-000001", kind="read_failed", message="열 수 없음", file="a.xlsx")
    assert w.kind == "read_failed"


def test_group_without_sheets_not_written():
    # 1.1 결과와 글자가 같게: sheets가 없으면 출력 칸에도 없다
    assert "sheets" not in GroupRef(doc_type="fo", category_path_text="회원").model_dump(mode="json")
    assert GroupRef(doc_type="fo", category_path_text="회원", sheets=["회원"]).model_dump(mode="json")["sheets"] == ["회원"]


# ---------- 2026-10-10: group_contains는 추정 경로 항목을 묶음에서 뺀다 (si-prep 묶음 판단과 같은 규칙) ----------

def test_group_contains_excludes_inferred_path_items():
    from si_prep.schema import has_inferred_step
    filled = _item(category_path=_path(("회원", "sheet_name"), ("로그인", "filled_down"), ("비밀번호 입력", "cell")),
                   status="ambiguous")
    group = GroupRef(doc_type="fo", category_path_text="회원 › 로그인")
    assert has_inferred_step(filled.category_path) and not group_contains(group, filled)
    # status가 우선순위로 unparsed여도 경로가 추정이면 뺀다
    unparsed = _item(category_path=_path(("회원", "sheet_name"), ("로그인", "filled_down"), ("비밀번호 입력", "cell")),
                     status="unparsed")
    assert not group_contains(group, unparsed)
    assert group_contains(group, _item()) and not has_inferred_step(_item().category_path)


# ---------- 1.3: form_filled — 사람 선언으로 채운 단계, 추정 아님 ----------

def test_form_filled_is_confirmed_step():
    from si_prep.schema import INFERRED_BASES, has_inferred_step
    item = _item(category_path=_path(("회원", "sheet_name"), ("로그인", "form_filled"), ("비밀번호 입력", "cell")))
    group = GroupRef(doc_type="fo", category_path_text="회원 › 로그인")
    assert "form_filled" not in INFERRED_BASES
    assert not has_inferred_step(item.category_path) and group_contains(group, item)
    with pytest.raises(ValidationError):
        PathPart(level=1, value=None, basis="form_filled")              # 값 없는 단계는 empty뿐


def test_older_1_2_results_still_validate():
    # 1.3은 추가형: 1.2로 쓴 결과 파일(schema_version "1.2", form_filled 없음)도 그대로 통과(평가기 호환)
    assert _item(schema_version="1.2").schema_version == "1.2"


# ---------- 1.4: table_title — 한 시트 여러 표의 표 제목 단계, 추정 아님 ----------

def test_table_title_is_confirmed_step():
    from si_prep.schema import INFERRED_BASES, has_inferred_step
    item = _item(category_path=_path(("회원", "sheet_name"), ("가입 정책", "table_title"), ("비밀번호 입력", "cell")),
                 category_path_text="회원 › 가입 정책 › 비밀번호 입력")
    assert "table_title" not in INFERRED_BASES and not has_inferred_step(item.category_path)
    group = GroupRef(doc_type="fo", category_path_text="회원 › 가입 정책")
    assert group_contains(group, item)
    with pytest.raises(ValidationError):
        PathPart(level=1, value=None, basis="table_title")


def test_older_1_3_results_still_validate():
    assert _item(schema_version="1.3").schema_version == "1.3"
