"""프로젝트 설정(project.yaml) 읽기·검사.

틀린 설정은 shop 설정을 임시 폴더에 복사해 한 곳씩 고쳐서 만든다(shop 설정 파일은 건드리지 않음).
"""

import shutil

import pytest
import yaml

from si_prep.config import ConfigError, load_project
from conftest import SHOP_DIR as SHOP



def _write(tmp_path, generated_dir, mutate=None):
    """shop 설정을 tmp_path로 복사(input_dir은 생성 폴더 절대 경로)하고 mutate(dict)로 고친 project.yaml 경로"""
    shutil.copytree(SHOP / "profiles", tmp_path / "profiles")
    shutil.copy(SHOP / "glossary.yaml", tmp_path / "glossary.yaml")
    data = yaml.safe_load((SHOP / "project.yaml").read_text(encoding="utf-8"))
    data["input_dir"] = str(generated_dir)
    if mutate:
        mutate(data)
    path = tmp_path / "project.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _issues(tmp_path, generated_dir, mutate):
    with pytest.raises(ConfigError) as e:
        load_project(_write(tmp_path, generated_dir, mutate))
    return e.value.issues


def _rule(data, rule_id):
    return next(r for r in data["link_rules"] if r["id"] == rule_id)


# ---------- 통과 ----------

def test_shop_project_loads():
    config = load_project(SHOP / "project.yaml")
    assert config.project == "shop" and config.approved is True
    assert [d.id for d in config.doc_types] == ["req", "fo", "bo", "policy", "test", "variation"]
    assert [d.doc_type for d in config.documents] == ["req", "fo", "bo", "policy", "test", "variation"]
    assert [r.id for r in config.link_rules] == [
        "fo_overview_detail", "fo_test", "bo_test", "policy_fo", "test_req", "req_fo_glossary"]
    assert config.doc_priority == ["req", "fo", "policy"]  # 일부만 적어도 됨(나머지는 같은 순위)
    assert config.input_path.is_dir() and config.profile_path(config.documents[0]).is_file()
    assert config.glossary_data.groups == [["회원", "고객"]]


def test_flat_priority_tiers():
    config = load_project(SHOP / "project.yaml")
    assert config.priority_tiers == [["req"], ["fo"], ["policy"]]
    assert [config.priority_rank(t) for t in ("req", "fo", "policy", "bo")] == [0, 1, 2, None]  # 적지 않음 = 나머지


def test_same_rank_group(tmp_path, generated_dir):
    # 안쪽 목록 = 같은 순위. 같은 순위끼리 내용이 다를 때 「둘 다 남기고 경고」는 rag_core 몫
    path = _write(tmp_path, generated_dir, lambda d: d.update(doc_priority=["req", ["fo", "bo"], "policy"]))
    config = load_project(path)
    assert config.doc_priority == ["req", ["fo", "bo"], "policy"]  # 적힌 그대로
    assert config.priority_tiers == [["req"], ["fo", "bo"], ["policy"]]
    assert config.priority_rank("fo") == config.priority_rank("bo") == 1
    assert config.priority_rank("test") is None


def test_single_member_group_allowed(tmp_path, generated_dir):
    path = _write(tmp_path, generated_dir, lambda d: d.update(doc_priority=["req", ["fo"], "policy"]))
    assert load_project(path).priority_tiers == [["req"], ["fo"], ["policy"]]


def test_no_priority(tmp_path, generated_dir):
    config = load_project(_write(tmp_path, generated_dir, lambda d: d.pop("doc_priority")))
    assert config.priority_tiers == [] and config.priority_rank("req") is None


def test_name_similarity_rule_passes_config(tmp_path, generated_dir):
    # 알려졌지만 미구현 key는 설정 단계에서는 통과(실행 때 unsupported)
    path = _write(tmp_path, generated_dir, lambda d: d["link_rules"].append(
        {"id": "req_fo_similar", "docs": ["req", "fo"], "key": "name_similarity"}))
    assert load_project(path).link_rules[-1].key == "name_similarity"


def test_subfolder_file_allowed(tmp_path, generated_dir):
    sub = tmp_path / "data" / "sub"
    sub.mkdir(parents=True)
    shutil.copy(generated_dir / "가상몰_요구사항정의서.xlsx", sub / "가상몰_요구사항정의서.xlsx")

    def mutate(d):
        d["input_dir"] = str(tmp_path / "data")
        d["documents"] = [{"doc_type": "req", "profile": "profiles/req.yaml", "files": ["sub/가상몰_요구사항정의서.xlsx"]}]
        d["link_rules"] = []
        d.pop("glossary")
    assert load_project(_write(tmp_path, generated_dir, mutate)).documents[0].files == ["sub/가상몰_요구사항정의서.xlsx"]


# ---------- 틀린 설정: 한 곳씩 ----------

CASES = [
    ("최상위 오타 키", lambda d: d.update(doc_prioirty=["req"]), 'doc_prioirty', '혹시 "doc_priority"인가요?'),
    ("문서 오타 키", lambda d: d["documents"][0].update(profle="x"), "documents[0]", '혹시 "profile"인가요?'),
    ("규칙 오타 키", lambda d: _rule(d, "policy_fo").update(sheet=None), "link_rules[3] (id=policy_fo)", '혹시 "sheets"인가요?'),
    ("문서의 doc_type 미선언", lambda d: d["documents"][1].update(doc_type="fo2"), "documents[1].doc_type", "선언되지 않았습니다"),
    ("규칙 docs 미선언", lambda d: _rule(d, "fo_test").update(docs=["fo", "tests"]), "link_rules[1] (id=fo_test).docs[1]", "선언되지 않았습니다"),
    ("group이 docs 밖", lambda d: _rule(d, "req_fo_glossary").update(group="bo"), "link_rules[5] (id=req_fo_glossary)", "docs"),
    ("doc_priority 미선언", lambda d: d.update(doc_priority=["req", "faq"]), "doc_priority[1]", "선언되지 않았습니다"),
    ("doc_priority 중복", lambda d: d.update(doc_priority=["req", "fo", "req"]), "doc_priority", "두 번 이상"),
    ("doc_priority 묶음 안 중복", lambda d: d.update(doc_priority=["req", ["fo", "fo"]]),
     "doc_priority", "doc_priority[1][0], doc_priority[1][1]"),
    ("doc_priority 묶음과 밖 중복", lambda d: d.update(doc_priority=["req", ["fo", "bo"], "fo"]),
     "doc_priority", "doc_priority[1][0], doc_priority[2]"),
    ("doc_priority 빈 묶음", lambda d: d.update(doc_priority=["req", [], "fo"]), "doc_priority[1]", "비어 있습니다"),
    ("doc_priority 묶음 안 묶음", lambda d: d.update(doc_priority=["req", ["fo", ["bo"]]]),
     "doc_priority[1][1]", "묶음 안에 또 묶음"),
    ("doc_priority 묶음 안 미선언", lambda d: d.update(doc_priority=["req", ["fo", "boo"]]),
     "doc_priority[1][1]", "선언되지 않았습니다"),
    ("doc_priority 묶음 안 숫자", lambda d: d.update(doc_priority=["req", ["fo", 3]]), "doc_priority[1][1]", "글자"),
    ("doc_priority 목록 아님", lambda d: d.update(doc_priority="req"), "doc_priority", "목록"),
    ("doc_types id 중복", lambda d: d["doc_types"].append({"id": "fo", "name": "또 기능"}), "doc_types", '"fo"가 두 번'),
    ("doc_types id 모양", lambda d: d["doc_types"][0].update(id="Req"), "doc_types[0].id", "영문 소문자"),
    ("숫자로 적힌 id", lambda d: d["doc_types"][0].update(id=123), "doc_types[0].id", "글자여야"),
    ("rule id 중복", lambda d: _rule(d, "bo_test").update(id="fo_test"), "link_rules", '"fo_test"가 두 번'),
    ("같은 파일 두 번", lambda d: d["documents"][1]["files"].append("가상몰_요구사항정의서.xlsx"), "documents[1].files", "두 번 등록"),
    ("input_dir 없음", lambda d: d.update(input_dir="없는폴더"), "input_dir", "폴더가 없습니다"),
    ("데이터 파일 없음", lambda d: d["documents"][0].update(files=["없는파일.xlsx"]), "documents[0].files", "파일이 없습니다"),
    ("절대 경로 파일", lambda d: d["documents"][0].update(files=["C:/data/a.xlsx"]), "documents[0].files", "상대 경로만"),
    (".. 경로 파일", lambda d: d["documents"][0].update(files=["../a.xlsx"]), "documents[0].files", "상대 경로만"),
    ("프로필 없음", lambda d: d["documents"][0].update(profile="profiles/없음.yaml"), "documents[0].profile", "프로필 파일이 없습니다"),
    ("모르는 key", lambda d: _rule(d, "fo_test").update(key="paht"), "link_rules[1] (id=fo_test).key", '혹시 "path"인가요?'),
    ("docs 1개", lambda d: _rule(d, "fo_test").update(docs=["fo"]), "link_rules[1] (id=fo_test).docs", "정확히 2개"),
    ("docs 3개", lambda d: _rule(d, "fo_test").update(docs=["fo", "test", "req"]), "link_rules[1] (id=fo_test).docs", "정확히 2개"),
    ("sheets 1칸", lambda d: _rule(d, "fo_test").update(sheets=["detail"]), "link_rules[1] (id=fo_test).sheets", "2칸"),
    ("sheets 3칸", lambda d: _rule(d, "fo_test").update(sheets=["detail", None, None]), "link_rules[1] (id=fo_test).sheets", "2칸"),
    ("sheets 칸 값", lambda d: _rule(d, "fo_test").update(sheets=["요약만", None]), "link_rules[1] (id=fo_test).sheets", "overview / detail"),
    ("path_prefix인데 group 없음", lambda d: d["link_rules"].append({"id": "pp", "docs": ["policy", "fo"], "key": "path_prefix"}),
     "link_rules[6] (id=pp)", "group(묶음이 되는 문서 종류)이 필요"),
    ("path인데 group 있음", lambda d: _rule(d, "fo_test").update(group="fo"), "link_rules[1] (id=fo_test)", "group은 path_prefix"),
    # 같은 문서 종류끼리 잇는 id_ref·sheet_to_path는 아직 지원 범위 밖
    ("같은 종류끼리 id_ref", lambda d: _rule(d, "test_req").update(docs=["test", "test"]),
     "link_rules[4] (id=test_req)", "같은 문서 종류끼리 잇는 id_ref·sheet_to_path 규칙은 아직 지원하지 않습니다"),
    ("같은 종류끼리 sheet_to_path", lambda d: _rule(d, "policy_fo").update(docs=["policy", "policy"]),
     "link_rules[3] (id=policy_fo)", "같은 문서 종류끼리 잇는 id_ref·sheet_to_path 규칙은 아직 지원하지 않습니다"),
    ("glossary인데 사전 없음", lambda d: d.pop("glossary"), "link_rules[5] (id=req_fo_glossary)", "용어 사전이 없습니다"),
    ("사전 파일 없음", lambda d: d.update(glossary="없는사전.yaml"), "glossary", "용어 사전 파일이 없습니다"),
    ("options.match 없음", lambda d: _rule(d, "req_fo_glossary").update(options={}), "link_rules[5] (id=req_fo_glossary)", "options.match"),
    ("options.match 잘못", lambda d: _rule(d, "req_fo_glossary").update(options={"match": "fuzzy"}), "link_rules[5] (id=req_fo_glossary)", "options.match"),
    ("options를 다른 key에", lambda d: _rule(d, "fo_test").update(options={"match": "exact"}), "link_rules[1] (id=fo_test)", "glossary 규칙에서만"),
    ("check_content를 묶음 key에", lambda d: _rule(d, "policy_fo").update(check_content=True), "link_rules[3] (id=policy_fo)", "check_content"),
]


@pytest.mark.parametrize("name,mutate,where,text", CASES, ids=[c[0] for c in CASES])
def test_broken_config_reports_location(tmp_path, generated_dir, name, mutate, where, text):
    issues = _issues(tmp_path, generated_dir, mutate)
    assert any(where in msg and text in msg for msg in issues), issues


def test_check_content_allowed_for_glossary_exact(tmp_path, generated_dir):
    def mutate(d):
        rule = _rule(d, "req_fo_glossary")
        rule.update(options={"match": "exact"}, check_content=True)
        rule.pop("group")
    assert load_project(_write(tmp_path, generated_dir, mutate)).link_rules[5].check_content


def test_glossary_word_in_two_groups(tmp_path, generated_dir):
    path = _write(tmp_path, generated_dir)
    (tmp_path / "glossary.yaml").write_text("groups:\n  - [회원, 고객]\n  - [고객, 손님]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_project(path)
    # 2026-10-10: 사전 단어(셀 내용에서 나옴)는 오류 문장에 넣지 않고 groups 번호·줄 번호로만
    assert any("glossary.yaml" in m and "groups[0](2줄)" in m and "groups[1](3줄)" in m and "함께 있습니다" in m
               for m in e.value.issues), e.value.issues
    assert not any("고객" in m or "회원" in m or "손님" in m for m in e.value.issues)


def test_glossary_short_group_message_has_no_words(tmp_path, generated_dir):
    path = _write(tmp_path, generated_dir)
    (tmp_path / "glossary.yaml").write_text("groups:\n  - [회원]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_project(path)
    assert any("groups[0](2줄)" in m and "2단어 이상" in m for m in e.value.issues)
    assert not any("회원" in m for m in e.value.issues)


def test_all_issues_reported_at_once(tmp_path, generated_dir):
    def mutate(d):
        d["documents"][1]["doc_type"] = "fo2"           # 선언 안 된 종류
        _rule(d, "policy_fo")["sheet"] = None           # 오타 키
        d["link_rules"][5]["key"] = "glossery"          # 모르는 key
    issues = _issues(tmp_path, generated_dir, mutate)
    assert len(issues) >= 3
    text = str(ConfigError("project.yaml", issues))
    assert text.startswith(f"설정 오류 {len(issues)}개") and " 1. " in text and " 3. " in text


def test_missing_and_broken_yaml(tmp_path):
    with pytest.raises(ConfigError, match="설정 파일이 없습니다"):
        load_project(tmp_path / "없음.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("project: [\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="YAML 문법 오류"):
        load_project(bad)


# ---------- 2026-10-12: 용어 사전 중복은 비교용 열쇠(공백 제거·소문자)로 ----------

def test_glossary_same_key_different_spelling_in_two_groups_rejected(tmp_path, generated_dir):
    path = _write(tmp_path, generated_dir)
    (tmp_path / "glossary.yaml").write_text("groups:\n  - [로그인, 가]\n  - [로 그인, 나]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_project(path)
    assert any("groups[0](2줄)" in m and "groups[1](3줄)" in m and "표기만 다른 같은 단어" in m for m in e.value.issues)
    assert not any("로그인" in m or "로 그인" in m for m in e.value.issues)


def test_glossary_same_key_within_one_group_allowed():
    from si_prep.config import Glossary
    Glossary.model_validate({"groups": [["로그인", "로 그인", "가"]]})


# ---------- 2026-10-12 리뷰 R3: 시트 이름 패턴 맞추기는 공개 이름 ----------

def test_sheet_matches_public():
    from si_prep.config import sheet_matches
    assert sheet_matches("주문 - 결제", ["주문 - *"]) and not sheet_matches("결제", ["주문*"])


def test_check_content_not_allowed_for_id_ref(tmp_path, generated_dir):
    # id_ref 규칙의 check_content는 실행에서 쓰이지 않으므로 설정 오류
    issues = _issues(tmp_path, generated_dir, lambda d: _rule(d, "test_req").update(check_content=True))
    assert any("link_rules[4] (id=test_req)" in m and "check_content" in m for m in issues), issues
