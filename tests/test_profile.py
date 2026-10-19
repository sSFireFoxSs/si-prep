"""문서별 프로필(profiles/*.yaml) 읽기·검사.

6-1: 프로필 모델과 단독 검사(엑셀은 열지 않음). 틀린 프로필은 shop의 fo 프로필을 복사해 한 곳씩 고쳐 만든다.
"""

from pathlib import Path

import pytest
import yaml

from si_prep.config import ConfigError, load_profile, sheet_profile

PROFILES = Path(__file__).parent / "fixtures" / "configs" / "shop" / "profiles"


def _write(tmp_path, mutate, base="fo"):
    data = yaml.safe_load((PROFILES / f"{base}.yaml").read_text(encoding="utf-8"))
    mutate(data)
    path = tmp_path / f"{base}.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _issues(tmp_path, mutate, base="fo"):
    with pytest.raises(ConfigError) as e:
        load_profile(_write(tmp_path, mutate, base))
    return e.value.issues


# ---------- 통과 ----------

@pytest.mark.parametrize("name", ["req", "fo", "bo", "policy", "test", "variation"])
def test_fixture_profiles_load(name):
    profile = load_profile(PROFILES / f"{name}.yaml")
    assert profile.id == name


def test_defaults():
    p = load_profile(PROFILES / "req.yaml")
    assert p.hidden_rows == "include" and p.table_gap_rows == 2 and p.stop_markers == []
    assert p.sheet_as_root is False and p.approved is True


def test_sheet_list_read_and_skip():
    p = load_profile(PROFILES / "fo.yaml")
    skipped = {s.name: s.reason for s in p.sheets if not s.read}
    assert set(skipped) == {"표지", "개정이력"} and all(skipped.values())
    assert [s.name for s in p.sheets if s.read] == ["회원", "주문", "고객센터", "요약"]


def test_sheet_name_pattern_allowed(tmp_path):
    path = _write(tmp_path, lambda d: d.update(sheets=[{"name": "표지*", "read": False, "reason": "메타 시트"},
                                                       {"name": "*"}]))
    assert [s.name for s in load_profile(path).sheets] == ["표지*", "*"]


def test_sheet_profile_applies_overrides():
    v = load_profile(PROFILES / "variation.yaml")
    assert sheet_profile(v, "빈칸채움").hierarchy.fill_down is True
    assert sheet_profile(v, "빈칸채움_끔").hierarchy.fill_down is False
    assert sheet_profile(v, "번호").hierarchy.method == "numbering"
    assert sheet_profile(v, "숨김건너뜀").hidden_rows == "skip" and v.hidden_rows == "include"
    assert sheet_profile(v, "이어지는행").item_boundary.method == "continuation"
    assert sheet_profile(v, "이어지는행").columns.id.header_contains == "기능 ID"


def test_known_but_unimplemented_methods_pass(tmp_path):
    # 알려졌지만 미구현 방식은 설정 검사 통과(실행 때 unsupported)
    assert load_profile(_write(tmp_path, lambda d: d.update(hierarchy={"method": "indent"}))).hierarchy.method == "indent"


def test_continuation_by_hierarchy_allowed(tmp_path):
    path = _write(tmp_path, lambda d: d.update(item_boundary={"method": "continuation", "key_role": "hierarchy"}))
    assert load_profile(path).item_boundary.key_role == "hierarchy"


# ---------- 틀린 프로필: 한 곳씩 ----------

def _cols(d):
    return d["columns"]


CASES = [
    ("모르는 키", lambda d: d.update(heder_rows=[4]), "heder_rows", '혹시 "header_rows"인가요?'),
    ("header_rows 없음", lambda d: d.pop("header_rows"), "header_rows", "필수 키가 없습니다"),
    ("data_start_row가 헤더 행 이하", lambda d: d.update(data_start_row=5), "data_start_row", "헤더 행"),
    ("선택자 두 종류", lambda d: _cols(d).update(title={"header_contains": "기능명", "col": "E"}), "columns.title", "정확히 하나"),
    ("선택자 비어 있음", lambda d: _cols(d).update(title={}), "columns.title", "정확히 하나"),
    ("열 문자 잘못", lambda d: _cols(d).update(title={"col": "e1"}), "columns.title", "열 문자"),
    ("header_pattern을 title에", lambda d: _cols(d).update(title={"header_pattern": "기능", "all": True}),
     "columns.title", "hierarchy에서만"),
    ("header_pattern에 all 없음", lambda d: _cols(d).update(hierarchy=[{"header_pattern": "단계$"}]),
     "columns.hierarchy[0]", "all: true"),
    ("header_pattern 정규식 오류", lambda d: _cols(d).update(hierarchy=[{"header_pattern": "[", "all": True}]),
     "columns.hierarchy[0]", "정규식"),
    ("id_pattern 정규식 오류", lambda d: d.update(id_pattern="(REQ"), "id_pattern", "정규식"),
    ("filename_pattern 그룹 없음", lambda d: d["version"].update(filename_pattern="_v\\d+"), "version.filename_pattern", "그룹"),
    ("덮어쓰기 안 선택자의 모르는 키",
     lambda d: d["sheet_overrides"][0]["columns"].update(description={"header_contian": "설명"}),
     "sheet_overrides[0].columns.description", '혹시 "header_contains"인가요?'),
    ("덮어쓰기 안 분류 선택자의 모르는 키",
     lambda d: d["sheet_overrides"][0]["columns"]["hierarchy"][0].update(header_contian="1단계"),
     "sheet_overrides[0].columns.hierarchy[0]", '혹시 "header_contains"인가요?'),
    ("모르는 분류 방식", lambda d: d.update(hierarchy={"method": "colums"}), "hierarchy", '혹시 "columns"인가요?'),
    ("모르는 경계 방식", lambda d: d.update(item_boundary={"method": "rows"}), "item_boundary", '혹시 "row"인가요?'),
    ("columns 방식인데 분류 열 없음", lambda d: _cols(d).update(hierarchy=[]), "columns.hierarchy", "분류 열"),
    ("split_cell인데 분류 열 2개", lambda d: d.update(hierarchy={"method": "split_cell", "separators": [" > "]}),
     "columns.hierarchy", "하나"),
    ("numbering인데 title 없음", lambda d: (d.update(hierarchy={"method": "numbering"}), _cols(d).pop("title")),
     "columns.title", "numbering"),
    ("continuation(id)인데 id 열 없음", lambda d: d.update(item_boundary={"method": "continuation"}),
     "columns.id", "continuation"),
    ("ref_ids에 pattern 없음", lambda d: _cols(d).update(ref_ids={"header_contains": "요구사항 ID"}),
     "columns.ref_ids", "pattern"),
    ("hidden_rows 값 잘못", lambda d: d.update(hidden_rows="hide"), "hidden_rows", "include"),
    ("table_gap_rows 0", lambda d: d.update(table_gap_rows=0), "table_gap_rows", ""),
    ("뺌인데 이유 없음", lambda d: d["sheets"][0].pop("reason"), "sheets[0]", "reason"),
    ("시트 이름 두 번", lambda d: d["sheets"].append({"name": "회원"}), "sheets", '"회원"이 두 번'),
    ("시트별 덮어쓰기에 쓸 수 없는 키", lambda d: d["sheet_overrides"][0].update(version={"cover_sheet": "표지"}),
     "sheet_overrides[0]", "version"),
    ("덮어쓴 결과 data_start_row가 헤더 이하", lambda d: d["sheet_overrides"][0].update(header_rows=[10]),
     "sheet_overrides[0]", "헤더 행"),
    ("숫자로 적힌 id", lambda d: d.update(id=7), "id", "글자여야"),
]


@pytest.mark.parametrize("name,mutate,where,text", CASES, ids=[c[0] for c in CASES])
def test_broken_profile_reports_location(tmp_path, name, mutate, where, text):
    issues = _issues(tmp_path, mutate)
    assert any(where in msg and text in msg for msg in issues), issues


def test_all_profile_issues_at_once(tmp_path):
    def mutate(d):
        d["heder_rows"] = [4]
        d["data_start_row"] = 3
        d["sheets"][0].pop("reason")
    with pytest.raises(ConfigError) as e:
        load_profile(_write(tmp_path, mutate))
    assert len(e.value.issues) >= 3 and str(e.value).startswith("설정 오류")
