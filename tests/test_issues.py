"""경고 초안 수집기. 검증 규칙은 schema.Warning_ 하나만 쓴다."""

import pytest

from si_prep.issues import Issue, Issues
from si_prep.schema import Location, Warning_


def _loc(row=3):
    return Location(file="a.xlsx", sheet="S", rows={"start": row, "end": row})


def test_add_and_iterate_in_order():
    issues = Issues()
    issues.add("unsupported", "첫째", file="a.xlsx")
    issues.add("hidden_content", "둘째", locations=[_loc()])
    assert [i.message for i in issues] == ["첫째", "둘째"]
    assert len(issues) == 2
    assert isinstance(issues.items[0], Issue)


def test_unknown_kind_is_error():
    with pytest.raises(ValueError, match="kind"):
        Issues().add("hiden_content", "오타", file="a.xlsx")


def test_empty_message_is_error():
    with pytest.raises(ValueError):
        Issues().add("unsupported", "", file="a.xlsx")


def test_no_location_needs_file():
    with pytest.raises(ValueError, match="file"):
        Issues().add("unsupported", "어디인지 없음")


def test_by_kind():
    issues = Issues()
    issues.add("unsupported", "가", file="a.xlsx")
    issues.add("sheet_skipped", "나", file="a.xlsx", sheet="S")
    issues.add("unsupported", "다", file="b.xlsx")
    assert [i.message for i in issues.by_kind("unsupported")] == ["가", "다"]


def test_issue_to_warning_with_given_id():
    # 번호는 issues가 붙이지 않는다: run이 모두 모아 정렬한 뒤 붙인다
    issue = Issues().add("hidden_content", "나", locations=[_loc(5)], item_ids=["IT-000001"])
    w = issue.to_warning("WN-000007")
    assert isinstance(w, Warning_) and w.warning_id == "WN-000007"
    assert w.item_ids == ["IT-000001"] and w.locations[0].rows.start == 5
    assert not hasattr(Issues, "to_warnings")


def test_issue_is_immutable():
    issue = Issues().add("unsupported", "가", file="a.xlsx")
    with pytest.raises(AttributeError):
        issue.message = "나"
