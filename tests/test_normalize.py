"""보여주기용 경로 글자, 비교 열쇠, 시트 이름 쪼개기. 원문은 고치지 않는다."""

from si_prep.normalize import compare_key, path_text, split_sheet_name
from si_prep.schema import EMPTY_STEP, PATH_SEP


def test_path_text_joins_and_drops_consecutive_duplicates():
    assert path_text(["회원", "회원", "가입"]) == PATH_SEP.join(["회원", "가입"])
    assert path_text(["가", "나", "가"]) == PATH_SEP.join(["가", "나", "가"])  # 이어질 때만 한 번


def test_path_text_empty_step_shown():
    assert path_text(["가", None, "다"]) == PATH_SEP.join(["가", EMPTY_STEP, "다"])
    assert path_text([None, None]) == PATH_SEP.join([EMPTY_STEP, EMPTY_STEP])  # 빈 단계는 줄이지 않음


def test_compare_key_strips_spaces_and_lowercases():
    assert compare_key(["배송지 변경", "Web 3"]) == ("배송지변경", "web3")
    assert compare_key(["배송지변경"]) == compare_key([" 배송지  변경 "])


def test_compare_key_drops_consecutive_duplicates():
    assert compare_key(["회원", "회 원", "가입"]) == ("회원", "가입")


def test_compare_key_none_when_any_step_empty():
    assert compare_key(["가", None, "다"]) is None
    assert compare_key([None]) is None


def test_compare_key_none_for_no_steps():
    assert compare_key([]) is None


def test_split_sheet_name_single_separator():
    assert split_sheet_name("이벤트 - 퀴즈", [" - "]) == ["이벤트", "퀴즈"]


def test_split_sheet_name_several_separators():
    assert split_sheet_name("가 - 나 > 다", [" - ", " > "]) == ["가", "나", "다"]


def test_split_sheet_name_longest_separator_first():
    # "-"와 " - "가 같이 있으면 긴 쪽으로 쪼갠다(앞뒤 공백이 단계에 남지 않게)
    assert split_sheet_name("가 - 나-다", ["-", " - "]) == ["가", "나", "다"]


def test_split_sheet_name_keeps_original_text():
    assert split_sheet_name("안내 문구 ", [" - "]) == ["안내 문구 "]   # 원문 공백 그대로
    assert split_sheet_name("가 - 나", []) == ["가 - 나"]


def test_split_sheet_name_empty_piece_is_empty_step():
    assert split_sheet_name("가 -  - 나", [" - "]) == ["가", None, "나"]


def test_compare_key_none_when_step_is_only_spaces():
    # 공백만 있는 단계는 열쇠가 ""가 되어 다른 공백 단계와 맞아 버리므로 빈 단계로 본다(원문 값은 그대로)
    assert compare_key(["회원", " "]) is None
    assert path_text(["회원", " "]) == PATH_SEP.join(["회원", " "])


def test_split_sheet_name_separator_at_start_or_end():
    assert split_sheet_name(" - 가", [" - "]) == [None, "가"]
    assert split_sheet_name("가 - ", [" - "]) == ["가", None]
    assert compare_key(split_sheet_name("가 - ", [" - "])) is None
