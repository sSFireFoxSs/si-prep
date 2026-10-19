"""link ① 등록표, path, check_content.
sheet_to_path·path_prefix, glossary, id_ref. name_similarity는 미구현 → 실행 때 규칙 건너뜀 + unsupported.
"""


import pytest

from fixtures import expected as E
from si_prep import boundary, extract, hierarchy, link
from si_prep.config import LINK_KEYS, LinkRule, load_project, load_profile, profile_source, sheet_profile
from si_prep.issues import Issues
from si_prep.layout import build_table, select_sheets
from si_prep.reader import open_workbook
from si_prep.registry import Unimplemented



def _shop_index():
    """합성 프로젝트 전체 항목 초안 → ItemIndex"""
    config = load_project(SHOP)
    index = link.ItemIndex()
    for doc in config.documents:
        profile = load_profile(config.profile_path(doc))
        for f in doc.files:
            wb = open_workbook(config.input_path / f, Issues())
            if wb is None:
                continue
            version = extract.read_doc_version(wb, profile, Issues())
            for grid in select_sheets(wb, profile, Issues()):
                sp = sheet_profile(profile, grid.name)
                try:
                    split = boundary.REGISTRY.get(sp.item_boundary.method)
                    make = hierarchy.REGISTRY.get(sp.hierarchy.method)
                except Unimplemented:
                    continue
                issues = Issues()
                table = build_table(grid, sp, f, issues)
                if table is None:
                    continue
                groups = split(table, sp, issues)
                for d in extract.make_items(table, groups, make(table, groups, sp, issues), doc.doc_type,
                                            profile_source(config.approved, profile.approved), version, issues):
                    index.add(d, profile)
    return config, index


@pytest.fixture(scope="module")
def shop():
    return _shop_index()


def _loc(d):
    return (d.doc_file, d.sheet, d.rows[0])


def _rule(config, rule_id):
    return next(r for r in config.link_rules if r.id == rule_id)


# ---------- 등록표 ----------

def test_registry():
    assert sorted(LINK_KEYS) == ["glossary", "id_ref", "name_similarity", "path", "path_prefix", "sheet_to_path"]
    # 경로 앞부분·용어집, id_ref
    assert link.REGISTRY.implemented() == ["glossary", "id_ref", "path", "path_prefix", "sheet_to_path"]
    with pytest.raises(Unimplemented):
        link.REGISTRY.get("name_similarity")


# ---------- id_ref ----------

def test_id_ref_shop_links_match_final(shop):
    config, index = shop
    issues = Issues()
    made = link.REGISTRY.get("id_ref")(_rule(config, "test_req"), index, config, issues)
    where = {int(i["item_id"][3:]): (i["file"], i["sheet"], i["rows"][0]) for i in E.FINAL_ITEMS}
    want = {frozenset({where[int(l["item_a"][3:])], where[int(l["item_b"][3:])]})
            for l in E.FINAL_LINKS if l["rule_id"] == "test_req"}
    assert {frozenset({_loc(d.a), _loc(d.b)}) for d in made} == want and len(made) == len(want)
    assert {d.method for d in made} == {"id_ref"}
    [w] = issues.items                                         # REQ-999 하나
    assert w.kind == "ref_unresolved" and "REQ-999" in w.message
    assert [(l.sheet, l.rows.start, l.cols) for l in w.locations] == [("테스트케이스", 4, ["C"])]


def _id_draft(doc_type, row, source_id=None, ref_ids=()):
    from si_prep.schema import DocVersion
    return extract.ItemDraft(doc_type=doc_type, doc_file=f"{doc_type}.xlsx", sheet="S", rows=(row, row),
                             category_path=[], category_path_text="", raw_fields={}, merged_fields={},
                             doc_version=DocVersion(), status="ok", profile_source="approved", source_id=source_id,
                             ref_ids=list(ref_ids), id_col="A" if source_id is not None else None,
                             ref_col="B" if ref_ids else None, ref_row=row if ref_ids else None)


def _id_index(seekers, targets):
    config = load_project(SHOP)
    test_p = load_profile(config.profile_path(next(d for d in config.documents if d.doc_type == "test")))
    req_p = load_profile(config.profile_path(next(d for d in config.documents if d.doc_type == "req")))
    index = link.ItemIndex()
    for d in seekers:
        index.add(d, test_p)
    for d in targets:
        index.add(d, req_p)
    return config, index


def test_id_ref_trims_spaces_case_sensitive_one_warning_per_item():
    t1 = _id_draft("test", 2, "T-1", ["R-1", "r-2", "R-9"])
    t2 = _id_draft("test", 3, "T-2", [])                     # 참조 없음 → 경고 없음
    r1, r2, r2b = _id_draft("req", 2, " R-1 "), _id_draft("req", 3, "R-2"), _id_draft("req", 4, "R-1")
    config, index = _id_index([t1, t2], [r1, r2, r2b])
    issues = Issues()
    made = link.REGISTRY.get("id_ref")(_rule(config, "test_req"), index, config, issues)
    assert sorted((d.a.rows[0], d.b.rows[0]) for d in made) == [(2, 2), (2, 4)]   # 대상 ID 중복이면 모두와
    assert all(d.a is t1 for d in made)
    [w] = issues.items                                       # 항목당 1건, 못 찾은 ID를 다 적음
    assert w.kind == "ref_unresolved" and "r-2" in w.message and "R-9" in w.message
    assert [(l.rows.start, l.cols) for l in w.locations] == [(2, ["B"])]
    texts = {d.evidence_text for d in made}
    assert all("R-1" in t for t in texts)


def test_id_ref_unmatched_counts_all_items_without_link():
    t1, t2 = _id_draft("test", 2, "T-1", ["R-1"]), _id_draft("test", 3, "T-2", [])
    r1, r2 = _id_draft("req", 2, "R-1"), _id_draft("req", 3, "R-2")
    config, index = _id_index([t1, t2], [r1, r2])
    rule = _rule(config, "test_req")
    made = link.REGISTRY.get("id_ref")(rule, index, config, Issues())
    left, right = link.unmatched(rule, index, made)            # 경로 열쇠가 없어도(경로 안 씀) 센다
    assert left == [t2] and right == [r2]


# ---------- path ----------

def test_exact_and_normalized(shop):
    config, index = shop
    drafts = link.by_path(_rule(config, "fo_test"), index, config, Issues())
    got = {(_loc(d.a), _loc(d.b)): d.method for d in drafts}
    fo, test = "가상몰_기능정의서_v1.2.xlsx", "가상몰_테스트케이스.xlsx"
    assert got[((fo, "회원", 6), (test, "테스트케이스", 2))] == "path_exact"
    assert got[((fo, "주문", 8), (test, "테스트케이스", 5))] == "path_normalized"      # 배송지변경 ↔ 배송지 변경


def test_sheets_slots_limit_sides(shop):
    # fo_test의 test 쪽은 [테스트케이스]만 → BO테스트케이스 시트 항목과는 연결 안 함
    config, index = shop
    drafts = link.by_path(_rule(config, "fo_test"), index, config, Issues())
    assert all(d.b.sheet == "테스트케이스" for d in drafts) and all(d.a.sheet != "요약" for d in drafts)   # detail만


def test_overview_detail_same_type_no_self_no_duplicates(shop):
    config, index = shop
    drafts = link.by_path(_rule(config, "fo_overview_detail"), index, config, Issues())
    pairs = [(_loc(d.a), _loc(d.b)) for d in drafts]
    assert all(d.a is not d.b for d in drafts)
    assert len({frozenset(p) for p in pairs}) == len(pairs) == 2
    assert all(d.a.sheet == "요약" and d.b.sheet != "요약" for d in drafts)          # sheets [overview, detail]


def test_ambiguous_items_not_linked(shop):
    # fo 회원 10행(중간 빈 단계)은 같은 글자 경로가 있어도 확정 연결을 만들지 않음
    config, index = shop
    drafts = link.by_path(_rule(config, "fo_test"), index, config, Issues())
    assert not any((d.a.doc_file, d.a.sheet, d.a.rows[0]) == ("가상몰_기능정의서_v1.2.xlsx", "회원", 10) for d in drafts)


def test_unmatched_items_no_warning(shop):
    config, index = shop
    issues = Issues()
    link.by_path(_rule(config, "fo_test"), index, config, issues)
    assert len(issues) == 0


def test_evidence_text_and_locations(shop):
    config, index = shop
    d = next(d for d in link.by_path(_rule(config, "fo_test"), index, config, Issues()) if d.method == "path_normalized")
    assert "배송지변경" in d.evidence_text and "배송지 변경" in d.evidence_text
    assert [(l.sheet, l.rows.start) for l in d.evidence_locations] == [("주문", 8), ("테스트케이스", 5)]


def test_content_mismatch(shop):
    config, index = shop
    issues = Issues()
    link.by_path(_rule(config, "fo_overview_detail"), index, config, issues)
    [w] = issues.by_kind("content_mismatch")
    assert {(l.sheet, l.rows.start, tuple(l.cols)) for l in w.locations} == {("주문", 6, ("F",)), ("요약", 7, ("G",))}


def test_content_not_compared_when_one_side_empty():
    a = link.LinkDraft("r", "path_exact", None, None, "", [])
    assert link.content_differs(" 가 나 ", "가나") is False and link.content_differs("가", "다") is True
    assert link.content_differs(None, "다") is False and a.rule_id == "r"


def test_shop_path_links_match_expected(shop):
    config, index = shop
    got = set()
    issues = Issues()
    for rule in config.link_rules:
        if rule.key != "path":      # 항목↔항목 path 규칙만(묶음 연결은 test_sheet_to_path_matches_expected)
            continue
        got |= {(d.rule_id, d.method, frozenset({_loc(d.a), _loc(d.b)})) for d in link.by_path(rule, index, config, issues)}
    where = {int(i["item_id"][3:]): (i["file"], i["sheet"], i["rows"][0]) for i in E.FINAL_ITEMS}
    want = {(l["rule_id"], l["method"], frozenset({where[int(l["item_a"][3:])], where[int(l["item_b"][3:])]}))
            for l in E.FINAL_LINKS if l["rule_id"] in ("fo_overview_detail", "fo_test", "bo_test")}
    assert got == want
    assert len(issues.by_kind("content_mismatch")) == 1


# ---------- 연결 번호 순서: item_id 작은 쪽이 item_a ----------

def test_to_link_orders_by_item_id(shop):
    config, index = shop
    d = link.by_path(_rule(config, "fo_test"), index, config, Issues())[0]
    ids = {id(d.a): "IT-000009", id(d.b): "IT-000002"}
    lk = d.to_link("LK-000001", ids)
    assert (lk.item_a, lk.item_b) == ("IT-000002", "IT-000009")
    assert lk.grade == "structural" and lk.rule_id == "fo_test" and len(lk.evidence_locations) == 2



# ======================================================================
# 항목 15: sheet_to_path, path_prefix (항목↔묶음, method path_normalized)
# ======================================================================

import copy  # noqa: E402

from si_prep.schema import Link, PathPart  # noqa: E402
from conftest import SHOP

POLICY = "가상몰_정책정의서.xlsx"


def _group_rows(drafts):
    return {(_loc(d.item), d.group.doc_type, d.group.category_path_text) for d in drafts}


def test_sheet_to_path_matches_expected(shop):
    config, index = shop
    issues = Issues()
    drafts = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, issues)
    where = {int(i["item_id"][3:]): (i["file"], i["sheet"], i["rows"][0]) for i in E.FINAL_ITEMS}
    want = {(where[int(l["item"][3:])], *l["group"]) for l in E.FINAL_LINKS if l["rule_id"] == "policy_fo"}
    assert _group_rows(drafts) == want
    assert all(d.method == "path_normalized" and d.group.sheets is None for d in drafts)   # 대상 칸 null → 전체
    [w] = issues.by_kind("link_unconfirmed")                                             # 쿠폰 - 발급
    assert [(l.sheet, l.rows.start, l.cols) for l in w.locations] == [("쿠폰 - 발급", 2, ["B", "C"])]
    assert not any(d.item.sheet == "결제 수단 목록" for d in drafts)                     # 규칙 sheets 밖 → 경고도 없음


def test_group_sheets_resolved_from_slot(shop):
    config, index = shop
    rule = LinkRule.model_validate({"id": "pf", "docs": ["policy", "fo"], "key": "sheet_to_path",
                                    "sheets": [["* - *"], "detail"]})
    drafts = link.REGISTRY.get("sheet_to_path")(rule, index, config, Issues())
    assert {tuple(d.group.sheets) for d in drafts} == {("회원", "주문", "고객센터")}      # 요약 시트는 묶음에서 뺌


def test_ambiguous_seeker_not_linked_nor_warned(shop):
    config, _ = shop
    _, index = _shop_index()
    entries = index._by_type["policy"]
    d, p = entries[0]
    fake = copy.copy(d)
    fake.category_path = d.category_path + [PathPart(level=len(d.category_path) + 1, value=None, basis="empty")]
    entries[0] = (fake, p)
    issues = Issues()
    drafts = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, issues)
    assert not any(x.item is fake for x in drafts)
    assert not any(l.rows.start == fake.rows[0] and l.sheet == fake.sheet
                   for w in issues.by_kind("link_unconfirmed") for l in w.locations)


def test_path_prefix_group_side_from_rule(shop):
    config, index = shop
    rule = LinkRule.model_validate({"id": "tf", "docs": ["test", "fo"], "key": "path_prefix", "group": "fo",
                                    "sheets": [["테스트케이스"], None]})
    issues = Issues()
    drafts = link.REGISTRY.get("path_prefix")(rule, index, config, issues)
    got = {(d.item.rows[0], d.group.category_path_text) for d in drafts}
    assert (2, "회원 › 로그인 › 일반 로그인 › 아이디 입력") in got                     # 찾는 쪽 경로 전체가 묶음
    assert any("쿠폰" in w.message for w in issues.by_kind("link_unconfirmed"))       # fo에 쿠폰 경로 없음


def test_group_draft_to_link(shop):
    config, index = shop
    d = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, Issues())[0]
    lk = d.to_link("LK-000010", {id(d.item): "IT-000033"})
    assert isinstance(lk, Link) and lk.item == "IT-000033" and lk.group.category_path_text == "주문 › 결제"
    assert lk.grade == "structural" and lk.item_a is None


def test_group_link_approved_only_when_target_profiles_approved(shop):
    # 찾는 쪽·대상(묶음) 쪽 프로필이 모두 approved일 때만 approved
    config, _ = shop
    _, index = _shop_index()
    entries = index._by_type["fo"]
    unapproved = entries[0][1].model_copy(update={"approved": False})
    index._by_type["fo"] = [(d, unapproved) for d, _ in entries]
    d = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, Issues())[0]
    assert d.to_link("LK-000001", {id(d.item): "IT-000033"}).profile_source == "auto"


def _policy_sheet_renamed(name="주문(Order)", groups=None):
    """정책 「주문 - 결제」 2행의 경로를 시트 이름 한 단계(name)로 바꾼 shop 색인. groups가 있으면 용어집을 그것으로"""
    config, index = _shop_index()
    entries = index._by_type["policy"]
    for n, (d, p) in enumerate(entries):
        if d.sheet == "주문 - 결제" and d.rows[0] == 2:
            fake = copy.copy(d)
            fake.category_path = [PathPart(level=1, value=name, basis="sheet_name")]
            fake.category_path_text = name
            entries[n] = (fake, p)
    if groups is not None:
        from si_prep.config import Glossary
        config._glossary_data = Glossary(approved=True, groups=groups)
    return config, index, fake


def test_sheet_to_path_links_through_glossary_line():
    # 2026-10-14: 시트 이름이 표기만 달라(괄호 영문) 못 잇던 것을 용어집 한 줄로 잇는다(단계 전체 단위)
    config, index, fake = _policy_sheet_renamed(groups=[["주문", "주문(Order)"]])
    issues = Issues()
    drafts = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, issues)
    [d] = [x for x in drafts if x.item is fake]
    assert (d.method, d.group.category_path_text, d.glossary_groups) == ("glossary", "주문", (0,))   # 묶음 = 대상 쪽 실제 이름
    assert "용어집" in d.evidence_text and "줄" in d.evidence_text
    assert not any(l.sheet == fake.sheet and l.rows.start == 2 for w in issues.by_kind("link_unconfirmed") for l in w.locations)
    others = [x for x in drafts if x.item is not fake]
    assert others and all(x.method == "path_normalized" and x.glossary_groups == () for x in others)   # 나머지는 그대로


def test_sheet_to_path_without_glossary_line_not_linked():
    config, index, fake = _policy_sheet_renamed(groups=[["회원", "고객"]])   # 해당 줄 없음
    issues = Issues()
    drafts = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, issues)
    assert not any(x.item is fake for x in drafts)
    assert any(l.sheet == fake.sheet and l.rows.start == 2 for w in issues.by_kind("link_unconfirmed") for l in w.locations)


def test_sheet_to_path_glossary_link_auto_when_glossary_not_approved():
    config, index, fake = _policy_sheet_renamed(groups=[["주문", "주문(Order)"]])
    config._glossary_data = config._glossary_data.model_copy(update={"approved": False})
    drafts = link.REGISTRY.get("sheet_to_path")(_rule(config, "policy_fo"), index, config, Issues())
    [d] = [x for x in drafts if x.item is fake]
    assert d.to_link("LK-000001", {id(fake): "IT-000001"}).profile_source == "auto"


def test_path_prefix_same_type_not_linked_to_itself(shop):
    # 같은 종류 규칙에서 자기 자신만 있는 묶음은 근거가 아님 → 짝 없음
    config, index = shop
    rule = LinkRule.model_validate({"id": "ff", "docs": ["fo", "fo"], "key": "path_prefix", "group": "fo",
                                    "sheets": [["회원"], ["회원"]]})
    issues = Issues()
    drafts = link.REGISTRY.get("path_prefix")(rule, index, config, issues)
    assert all(d.evidence_locations[0] != d.evidence_locations[1] for d in drafts)   # 근거가 자기 자신 아님
    assert len(issues.by_kind("link_unconfirmed")) > 0                                  # 자기만 있는 묶음은 짝 없음


# ======================================================================
# 2026-10-10 (3): path 규칙의 짝 없는 항목 — 요약 쪽은 link_unconfirmed, 나머지는 숫자만
# ======================================================================

def _with_changed_overview_row(index, sheet="요약", row=6, steps=("회원", "로그인", "없는 단계"), basis="cell"):
    entries = index._by_type["fo"]
    for n, (d, p) in enumerate(entries):
        if d.sheet == sheet and d.rows[0] == row:
            fake = copy.copy(d)
            fake.category_path = [PathPart(level=i, value=v, basis=basis) for i, v in enumerate(steps, start=1)]
            fake.category_path_text = " › ".join(steps)
            entries[n] = (fake, p)
            return fake


def test_overview_item_without_pair_warns():
    config, index = _shop_index()
    fake = _with_changed_overview_row(index)
    issues = Issues()
    rule = _rule(config, "fo_overview_detail")
    # 2026-10-10: 요약 쪽 짝 없음 경고는 모든 규칙(glossary 포함) 실행 뒤에 판단 → warn_overview_unmatched
    link.warn_overview_unmatched(rule, index, link.by_path(rule, index, config, issues), {}, issues)
    [w] = issues.by_kind("link_unconfirmed")
    assert [(l.sheet, l.rows.start) for l in w.locations] == [("요약", 6)] and w.locations[0].cols
    assert "fo_overview_detail" in w.message and fake.doc_file == w.file


def test_overview_inferred_item_without_pair_not_warned():
    config, index = _shop_index()
    _with_changed_overview_row(index, basis="filled_down")
    issues = Issues()
    rule = _rule(config, "fo_overview_detail")
    link.warn_overview_unmatched(rule, index, link.by_path(rule, index, config, issues), {}, issues)
    assert issues.by_kind("link_unconfirmed") == []


def test_detail_side_and_other_path_rules_no_warning(shop):
    config, index = shop
    issues = Issues()
    for rid in ("fo_overview_detail", "fo_test", "bo_test"):
        link.by_path(_rule(config, rid), index, config, issues)
    assert issues.by_kind("link_unconfirmed") == []          # 상세 쪽(회원 7행 등)·fo_test 짝 없음은 경고 안 함


def test_unmatched_counts(shop):
    config, index = shop
    rule = _rule(config, "fo_test")
    drafts = link.by_path(rule, index, config, Issues())
    left, right = link.unmatched(rule, index, drafts)
    assert all(not link.has_inferred_step(d.category_path) for d in left + right)    # 추정 경로는 셈에서 뺌
    assert ("가상몰_기능정의서_v1.2.xlsx", "회원", 8) in {_loc(d) for d in left}       # 테스트에 없는 fo 경로
    assert ("가상몰_테스트케이스.xlsx", "테스트케이스", 6) in {_loc(d) for d in right}  # fo에 없는 쿠폰 경로


# ======================================================================
# 항목 16a: glossary (용어 사전으로 단계 전체를 대표어로 바꿔 읽음, 바꾼 단어가 있을 때만)
# ======================================================================

def test_glossary_prefix_matches_expected(shop):
    config, index = shop
    rule = _rule(config, "req_fo_glossary")
    drafts = link.REGISTRY.get("glossary")(rule, index, config, Issues())
    where = {int(i["item_id"][3:]): (i["file"], i["sheet"], i["rows"][0]) for i in E.FINAL_ITEMS}
    want = {(where[int(l["item"][3:])], *l["group"]) for l in E.FINAL_LINKS if l["rule_id"] == "req_fo_glossary"}
    assert _group_rows(drafts) == want                                       # 고객 › 로그인 → fo 묶음 회원 › 로그인
    assert all(d.method == "glossary" for d in drafts)


def test_glossary_needs_replaced_word(shop):
    # 요구사항 「주문 › 결제」는 사전으로 바꾼 단어가 없으므로 glossary 연결 아님(바꾸지 않고 같으면 path 규칙의 몫)
    config, index = shop
    drafts = link.REGISTRY.get("glossary")(_rule(config, "req_fo_glossary"), index, config, Issues())
    assert not any("주문" in d.group.category_path_text for d in drafts)


def test_glossary_exact_item_to_item_with_content_check():
    config, index = _shop_index()
    _with_changed_overview_row(index, steps=("고객", "로그인", "일반 로그인", "아이디 입력"))  # 회원 대신 고객
    rule = LinkRule.model_validate({"id": "g", "docs": ["fo", "fo"], "key": "glossary", "sheets": ["overview", "detail"],
                                    "check_content": True, "options": {"match": "exact"}})
    issues = Issues()
    drafts = link.REGISTRY.get("glossary")(rule, index, config, issues)
    assert [(_loc(d.a)[1:], _loc(d.b)[1:], d.method) for d in drafts] == [(("요약", 6), ("회원", 6), "glossary")]
    assert issues.by_kind("content_mismatch") == []                          # 설명 같음


def test_glossary_replaces_whole_steps_only():
    from si_prep.link import glossary_key
    words = {"회원": "회원", "고객": "회원"}
    assert glossary_key(["고객", "로그인"], words) == ("회원", "로그인")
    assert glossary_key(["고객센터", "로그인"], words) == ("고객센터", "로그인")   # 단계 안 일부는 안 바꿈
    assert glossary_key(["고 객", "로그인"], words) == ("회원", "로그인")        # 비교 열쇠(공백·대소문자) 기준


def test_glossary_prefix_independent_of_word_order():
    # 16a 검토 M1: 사전을 [고객, 회원](대표어 = 고객)으로 적어도 같은 연결(찾는 쪽이 이미 대표어여도)
    from si_prep.config import Glossary
    config, index = _shop_index()
    config._glossary_data = Glossary(approved=True, groups=[["고객", "회원"]])
    drafts = link.REGISTRY.get("glossary")(_rule(config, "req_fo_glossary"), index, config, Issues())
    assert {(d.item.rows[0], d.group.category_path_text) for d in drafts} == {(2, "회원 › 로그인")}



# ======================================================================
# 2026-10-10: 용어집 줄별 효과 — glossary 연결이 쓴 사전 묶음, 요약 쪽 짝 없음이 glossary로 풀림
# ======================================================================

def test_glossary_link_records_groups_used():
    config, index = _shop_index()
    d = link.REGISTRY.get("glossary")(_rule(config, "req_fo_glossary"), index, config, Issues())[0]
    assert d.glossary_groups == (0,)                                   # shop 사전 groups[0] = [회원, 고객]


def test_overview_unmatched_resolved_by_glossary_not_warned():
    config, index = _shop_index()
    _with_changed_overview_row(index, steps=("고객", "로그인", "일반 로그인", "아이디 입력"))   # path로는 짝 없음
    path_rule = _rule(config, "fo_overview_detail")
    g_rule = LinkRule.model_validate({"id": "g", "docs": ["fo", "fo"], "key": "glossary", "sheets": ["overview", "detail"],
                                      "check_content": True, "options": {"match": "exact"}})
    issues = Issues()
    g_drafts = link.REGISTRY.get("glossary")(g_rule, index, config, issues)
    by_glossary = {id(x): d.glossary_groups for d in g_drafts for x in (d.a, d.b)}
    resolved = link.warn_overview_unmatched(path_rule, index, link.by_path(path_rule, index, config, issues),
                                            by_glossary, issues)
    assert issues.by_kind("link_unconfirmed") == [] and resolved == [(0,)]   # 사전 0번 줄 덕분에 풀린 1건


def test_glossary_resolves_only_same_pair_rules():
    # 검토 M1: 요약↔상세 path 규칙의 짝 없음은 같은 docs·sheets 칸의 glossary 규칙 연결로만 풀린다
    config, index = _shop_index()
    _with_changed_overview_row(index, steps=("고객", "로그인", "일반 로그인", "아이디 입력"))
    path_rule = _rule(config, "fo_overview_detail")
    same = LinkRule.model_validate({"id": "g1", "docs": ["fo", "fo"], "key": "glossary", "sheets": ["overview", "detail"],
                                    "options": {"match": "exact"}})
    other = LinkRule.model_validate({"id": "g2", "docs": ["fo", "test"], "key": "glossary",
                                     "sheets": ["overview", ["테스트케이스"]], "options": {"match": "exact"}})
    made = [(r, link.REGISTRY.get("glossary")(r, index, config, Issues())) for r in (other,)]
    assert made[0][1]                                                       # 요약 항목이 테스트와는 이어짐
    assert link.glossary_linked_for(path_rule, made) == {}                  # 그래도 요약↔상세 짝 없음은 안 풀림
    made.append((same, link.REGISTRY.get("glossary")(same, index, config, Issues())))
    assert len(link.glossary_linked_for(path_rule, made)) == 2              # 같은 쪽 규칙 연결의 양쪽 항목


def test_id_ref_unresolved_in_merged_ref_cell_at_own_row():
    # 리뷰 지적(A9와 같은 문제): 참조 칸 B2:B3 병합 → 3행 항목의 ref_row는 병합 시작 2.
    # 경고 위치는 항목 자기 행(B3)이어야 실행이 3행 항목에 붙인다. 연결 근거 위치는 값이 있는 B2 그대로
    t1, t2 = _id_draft("test", 2, "T-1", ["R-9"]), _id_draft("test", 3, "T-2", ["R-9", "R-1"])
    t2.ref_row = 2
    config, index = _id_index([t1, t2], [_id_draft("req", 2, "R-1")])
    issues = Issues()
    made = link.REGISTRY.get("id_ref")(_rule(config, "test_req"), index, config, issues)
    assert [[(l.rows.start, l.cols) for l in w.locations] for w in issues.items] == [[(2, ["B"])], [(3, ["B"])]]
    assert "B3" in issues.items[1].message and "B2" in issues.items[1].message
    [d] = made
    assert d.evidence_locations[0].rows.start == 2


def test_id_ref_uses_expanded_short_ids_with_evidence():
    # B2: 펼친 ID는 ref_ids에 없고 내부(expanded_refs)로만 연결. 근거 글자에 「펼침」과 조각·앞 ID
    t1 = _id_draft("test", 2, "T-1", ["R-0101"])
    t1.expanded_refs = [("R-0103", "0103", "R-0101"), ("R-0105", "0105", "R-0101")]
    config, index = _id_index([t1], [_id_draft("req", 2, "R-0101"), _id_draft("req", 3, "R-0103")])
    issues = Issues()
    made = link.REGISTRY.get("id_ref")(_rule(config, "test_req"), index, config, issues)
    assert sorted(d.b.rows[0] for d in made) == [2, 3]
    ev = next(d.evidence_text for d in made if d.b.rows[0] == 3)
    assert "펼침" in ev and "0103" in ev and "R-0101" in ev and "R-0103" in ev
    [w] = issues.items
    assert w.kind == "ref_unresolved" and "R-0105(펼친 ID)" in w.message


def test_id_ref_duplicate_target_marked_in_evidence():
    # 대상 ID가 대상 문서에 2개 이상이면 연결은 모두 만들되 근거에 「대상 ID 중복」
    t1 = _id_draft("test", 2, "T-1", ["R-1", "R-2"])
    config, index = _id_index([t1], [_id_draft("req", 2, "R-1"), _id_draft("req", 3, "R-1"), _id_draft("req", 4, "R-2")])
    made = link.REGISTRY.get("id_ref")(_rule(config, "test_req"), index, config, Issues())
    dup = sorted(d.b.rows[0] for d in made if "대상 ID 중복" in d.evidence_text)
    assert dup == [2, 3] and len(made) == 3
    assert all(d.dup_target == (d.b.rows[0] in (2, 3)) for d in made)
