"""연결 열쇠 등록표 — 규칙 하나를 실행해 연결 초안을 낸다. 연결에는 방향이 없다.

구현: path(항목↔항목, path_exact / path_normalized), check_content(내용 비교 → content_mismatch),
sheet_to_path·path_prefix(항목↔묶음, path_normalized, 묶음 못 찾으면 link_unconfirmed. sheet_to_path는 그대로 못 찾으면
용어집으로 바꿔 읽은 시트 이름으로도 찾음 → method glossary, 2026-10-14),
glossary(용어 사전으로 경로 단계 전체를 대표어로 바꿔 읽고 실제로 바꾼 단계가 있을 때만, exact = 항목↔항목, prefix = 항목↔묶음),
id_ref(항목↔항목: 참조 ID마다 대상 쪽 같은 자기 ID 항목 전부, 못 찾은 ID는 항목당 ref_unresolved 한 건).
알려졌지만 미구현: name_similarity → 실행 때 규칙 건너뜀 + unsupported.

- 규칙 sheets 두 칸(overview/detail/이름·패턴 목록/전체)으로 양쪽 항목을 고른다(config.slot_selects).
- 경로에 filled_down·empty 단계가 있는 항목(추정 주소)은 경로 연결에서 뺀다. 자기 자신과는 잇지 않는다.
- 한 항목이 반대쪽 같은 경로 항목 여럿과 맞으면 모두와 잇는다(쌍마다 한 줄).
- 짝 없는 항목: 요약↔상세 규칙(한쪽 칸이 overview)의 요약 쪽 항목은 link_unconfirmed, 그 밖은 경고 없이 숫자만
  (실행 화면 요약·처리 보고서). 추정 경로 항목은 경고·숫자 모두에서 뺀다.
- 항목 번호가 아직 없어 초안은 항목 초안을 가리킨다. item_a < item_b 순서와 LK 번호는 실행이 번호를 붙인 뒤 정한다.
"""

from dataclasses import dataclass

from si_prep.config import (LINK_KEYS, glossary_group_lines, has_ref_ids, has_root_separators, seeker_side,
                            slot_selects)
from si_prep.extract import id_location
from si_prep.normalize import compare_key, id_key, path_text
from si_prep.registry import Registry
from si_prep.schema import METHOD_GRADE, GroupRef, Link, Location, has_inferred_step, path_key, path_starts_with, step_key

REGISTRY = Registry("link", known=LINK_KEYS)


class ItemIndex:
    """문서 종류 → [(항목 초안, 그 문서의 프로필)] (규칙 sheets 칸 판정에 프로필의 overview_sheets가 필요)"""

    def __init__(self):
        self._by_type = {}

    def add(self, draft, profile):
        self._by_type.setdefault(draft.doc_type, []).append((draft, profile))

    def side(self, doc_type, slot):
        """규칙 한쪽 칸이 고르는 항목 초안(추가한 순서)"""
        return [d for d, p in self._by_type.get(doc_type, []) if slot_selects(d.sheet, p, slot)]

    def profiles(self, doc_type):
        """그 문서 종류 문서들의 프로필(중복 없이, 추가한 순서)"""
        out = []
        for _, p in self._by_type.get(doc_type, []):
            if all(p is not q for q in out):
                out.append(p)
        return out


@dataclass
class LinkDraft:
    rule_id: str
    method: str
    a: object                       # 항목 초안(ItemDraft) — 항목↔항목의 한쪽
    b: object
    evidence_text: str
    evidence_locations: list
    extra_approved: bool = True     # 연결 근거에 쓴 다른 설정(용어 사전)이 승인됐는지
    glossary_groups: tuple = ()     # glossary 연결이 쓴 사전 묶음 번호(줄별 효과용)
    mismatch: bool = False          # 이 연결에서 content_mismatch가 났는지
    dup_target: bool = False        # id_ref 대상 ID가 대상 문서에 2개 이상(그중 하나와의 연결)

    def to_link(self, link_id: str, ids: dict) -> Link:
        """ids: id(항목 초안) → IT 번호. item_id가 작은 쪽이 item_a"""
        first, second = sorted([ids[id(self.a)], ids[id(self.b)]])
        source = "approved" if self.a.profile_source == self.b.profile_source == "approved" and self.extra_approved else "auto"
        return Link(link_id=link_id, item_a=first, item_b=second, grade=METHOD_GRADE[self.method], method=self.method,
                    rule_id=self.rule_id, evidence_text=self.evidence_text, evidence_locations=self.evidence_locations,
                    needs_review=METHOD_GRADE[self.method] == "inferred", profile_source=source)


def _path_key(draft):
    """경로 연결의 열쇠. 추정 주소(filled_down·empty 단계)거나 경로가 없으면 None"""
    if has_inferred_step(draft.category_path):
        return None
    return compare_key([p.value for p in draft.category_path])


def content_differs(x, y) -> bool:
    """설명 비교: 한쪽이라도 비면 비교하지 않음(not_written으로 이미 드러남), 공백 제거·소문자 열쇠가 다르면 다름"""
    if x is None or y is None:
        return False
    return step_key(x) != step_key(y)


def _desc_location(d):
    """설명 원문 칸 위치(병합에서 받았으면 병합 시작 칸)"""
    return Location(file=d.doc_file, sheet=d.sheet, rows={"start": d.description_row, "end": d.description_row},
                    cols=[d.description_col])


def check_content(rule, a, b, issues) -> bool:
    """내용 비교(check_content): 양쪽 설명이 다르면 content_mismatch(경고를 냈으면 True).
    항목↔항목 규칙(path, glossary exact)이 같이 쓴다"""
    if rule.check_content and content_differs(a.description, b.description):
        issues.add("content_mismatch",
                   f"연결 규칙 {rule.id}: 같은 경로 {a.category_path_text}의 설명이 다릅니다 "
                   f"({a.doc_file} {a.sheet} {a.rows[0]}행 ↔ {b.doc_file} {b.sheet} {b.rows[0]}행)",
                   [_desc_location(a), _desc_location(b)], file=a.doc_file, sheet=a.sheet)
        return True
    return False


@REGISTRY.register("path")
def by_path(rule, index, project, issues) -> list:
    slots = rule.sheets or [None, None]
    left, right = index.side(rule.docs[0], slots[0]), index.side(rule.docs[1], slots[1])
    by_key = {}
    for d in right:
        key = _path_key(d)
        if key is not None:
            by_key.setdefault(key, []).append(d)
    out, seen = [], set()
    for a in left:
        key = _path_key(a)
        if key is None:
            continue
        for b in by_key.get(key, []):
            pair = frozenset({id(a), id(b)})
            if a is b or pair in seen:      # 자기 자신, 같은 종류 규칙에서 같은 쌍 두 번
                continue
            seen.add(pair)
            exact = a.category_path_text == b.category_path_text
            text = (f"분류 경로 일치: {a.category_path_text}" if exact
                    else f"분류 경로 일치(공백·대소문자 정규화): {a.category_path_text} ↔ {b.category_path_text}")
            out.append(LinkDraft(rule.id, "path_exact" if exact else "path_normalized", a, b, text,
                                 [a.location(), b.location()]))
            check_content(rule, a, b, issues)
    return out


def warn_overview_unmatched(rule, index, drafts, glossary_linked, issues) -> list:
    """요약↔상세 path 규칙(한쪽 칸 overview)의 요약 쪽 짝 없는 항목 → link_unconfirmed. 모든 규칙을 실행한 뒤 부른다.
    glossary_linked: id(항목 초안) → 그 항목을 이은 glossary 연결이 쓴 사전 묶음 번호. 거기 있는 항목은 용어 사전으로
    풀린 것이라 경고하지 않고, 풀린 항목마다 묶음 번호 튜플을 돌려준다(용어집 줄별 효과)"""
    resolved = []
    for k, slot in enumerate(rule.sheets or [None, None]):
        if slot != "overview":
            continue
        for d in unmatched(rule, index, drafts)[k]:   # 요약 쪽 짝 없음은 요약과 상세가 어긋났다는 신호
            if id(d) in glossary_linked:
                resolved.append(glossary_linked[id(d)])
            else:
                _unconfirmed(rule, d, "상세 시트에서 같은 경로를 찾지 못했습니다", issues)
    return resolved


def linked_ids(drafts) -> set:
    """연결 초안들이 이은 항목 초안의 id (항목↔항목은 양쪽, 항목↔묶음은 항목 쪽)"""
    out = set()
    for x in drafts:
        out |= {id(getattr(x, k)) for k in ("a", "b", "item") if hasattr(x, k)}
    return out


def same_sides(rule_a, rule_b) -> bool:
    """두 규칙이 같은 두 쪽인지(docs·sheets 칸이 같거나 서로 뒤바뀜). path 규칙과 glossary 규칙을 짝짓는 유일한 기준"""
    a = (list(rule_a.docs), list(rule_a.sheets or [None, None]))
    b = (list(rule_b.docs), list(rule_b.sheets or [None, None]))
    return b in (a, (a[0][::-1], a[1][::-1]))


def glossary_linked_for(path_rule, glossary_made) -> dict:
    """path 규칙과 같은 두 쪽(same_sides)인 glossary 규칙의 연결로 이어진 항목
    → id(항목 초안) → 쓰인 사전 묶음 번호. 다른 규칙의 연결로는 그 path 규칙의 짝 없음이 풀리지 않는다"""
    out = {}
    for rule, drafts in glossary_made:
        if not same_sides(path_rule, rule):
            continue
        for d in drafts:
            for x in ((d.a, d.b) if hasattr(d, "a") else (d.item,)):
                out[id(x)] = tuple(sorted(set(out.get(id(x), ())) | set(d.glossary_groups)))
    return out


def group_side(rule, index):
    """묶음 규칙(sheet_to_path·path_prefix·glossary prefix)에서 묶음(대상) 쪽 칸 번호. 묶음 규칙이 아니거나
    sheet_to_path에서 찾는 쪽을 정할 수 없으면 None"""
    if rule.key == "path_prefix" or (rule.key == "glossary" and rule.group):
        return rule.docs.index(rule.group) if rule.docs[0] != rule.docs[1] else 1
    if rule.key == "sheet_to_path":   # 찾는 쪽 = root_separators가 있는 쪽
        s = seeker_side([any(has_root_separators(p) for p in index.profiles(t)) for t in rule.docs])
        return None if s is None else 1 - s
    return None


def has_path_key(draft) -> bool:
    """짝 없음을 셀 대상인지: 경로 열쇠가 있음(추정 경로·경로 없음·공백만 있는 단계는 아님)"""
    return _path_key(draft) is not None


def unmatched(rule, index, drafts):
    """규칙 양쪽에서 짝이 없는 항목. (왼쪽 목록, 오른쪽 목록), 묶음 쪽은 빈 목록. 경로 규칙은 has_path_key인 것만,
    id_ref는 경로를 쓰지 않으므로 그 쪽 항목 전부. 실행 화면·처리 보고서·용어 사전 초안이 같이 쓰는 유일한 짝 없음 기준"""
    slots = rule.sheets or [None, None]
    linked = linked_ids(drafts)
    group = group_side(rule, index)
    counted = (lambda d: True) if rule.key == "id_ref" else has_path_key
    return tuple([] if k == group else [d for d in index.side(t, slot) if counted(d) and id(d) not in linked]
                 for k, (t, slot) in enumerate(zip(rule.docs, slots)))


def id_ref_seeker(rule, index):
    """id_ref의 찾는 쪽 번호(ref_ids 열이 있는 프로필 쪽). 정할 수 없으면 None(설정 검사에서 이미 오류)"""
    return seeker_side([any(has_ref_ids(p) for p in index.profiles(t)) for t in rule.docs])


# ---------- id_ref ----------

def _ref_location(d):
    return Location(file=d.doc_file, sheet=d.sheet, rows={"start": d.ref_row, "end": d.ref_row}, cols=[d.ref_col])


def id_targets(rule, index, seeker) -> dict:
    """id_ref 대상 쪽(규칙 sheets 칸 안) 자기 ID 열쇠(normalize.id_key) → 항목 초안 목록. 연결과 처리 보고서 4절이 같이 쓴다"""
    slots = rule.sheets or [None, None]
    by_id = {}
    for t in index.side(rule.docs[1 - seeker], slots[1 - seeker]):
        if t.source_id is not None and id_key(t.source_id):
            by_id.setdefault(id_key(t.source_id), []).append(t)
    return by_id


@REGISTRY.register("id_ref")
def by_id_ref(rule, index, project, issues) -> list:
    """찾는 쪽 항목의 참조 ID마다 대상 쪽(규칙 sheets 칸 안)에서 자기 ID가 같은(normalize.id_key) 항목 전부와 잇는다.
    경로를 쓰지 않으므로 추정 경로 항목도 잇는다. 못 찾은 ID는 항목마다 ref_unresolved 한 건(못 찾은 ID를 다 적음)"""
    seeker = id_ref_seeker(rule, index)
    if seeker is None:
        return []
    slots = rule.sheets or [None, None]
    target_type = rule.docs[1 - seeker]
    by_id = id_targets(rule, index, seeker)
    out = []
    for d in index.side(rule.docs[seeker], slots[seeker]):
        missing, seen = [], set()
        # 원문 ID(ref_ids) 다음 줄임 표기를 펼친 ID(B2, 내부용 — 근거 글자에 「펼침」과 조각·앞 ID)
        refs = [(r, None) for r in d.ref_ids] + [(new, (frag, base)) for new, frag, base in d.expanded_refs]
        for ref, short in refs:
            found = by_id.get(id_key(ref), [])
            if not found:
                missing.append(ref if short is None else f"{ref}(펼친 ID)")
            how = (f"참조 ID 일치: {ref}" if short is None else
                   f"참조 ID 일치(펼침): 조각 {short[0]} ← 앞 ID {short[1]}의 앞부분 → {ref}")
            dup = len(found) > 1   # 대상 ID 중복: 모두와 잇되 근거에 표시(duplicate_id 경고는 실행이 이 연결 상대도 붙임)
            for t in found:
                if id(t) in seen:
                    continue
                seen.add(id(t))
                out.append(LinkDraft(rule.id, "id_ref", d, t,
                                     f"{how} ({d.doc_file} {d.sheet} {d.ref_col}{d.ref_row} → "
                                     f"{t.doc_file} {t.sheet} {t.id_col}{t.rows[0]})"
                                     + (f" — 대상 ID 중복({len(found)}개, 모두와 연결)" if dup else ""),
                                     [_ref_location(d), id_location(t)], dup_target=dup))
        if missing:
            # 경고 위치는 이 항목 행의 참조 칸(병합 값이면 시작 칸을 메시지에) — 실행이 이 항목에 붙인다(A9와 같음)
            row = d.rows[0]
            cell = f"{d.ref_col}{row}" + (f"(병합 {d.ref_col}{d.ref_row} 칸의 값)" if d.ref_row != row else "")
            issues.add("ref_unresolved",
                       f"연결 규칙 {rule.id}: {d.doc_file} {d.sheet} {cell}의 참조 ID "
                       f"{', '.join(missing)}를 {target_type} 문서에서 찾지 못했습니다",
                       [Location(file=d.doc_file, sheet=d.sheet, rows={"start": row, "end": row}, cols=[d.ref_col])],
                       file=d.doc_file, sheet=d.sheet)
    return out


# ---------- 항목↔묶음: sheet_to_path, path_prefix ----------

@dataclass
class GroupLinkDraft:
    rule_id: str
    method: str
    item: object                    # 찾는 쪽 항목 초안
    group: GroupRef
    evidence_text: str
    evidence_locations: list
    target_approved: bool = True    # 대상(묶음) 쪽 문서 프로필이 모두 approved인지
    glossary_groups: tuple = ()     # glossary 연결이 쓴 사전 묶음 번호(줄별 효과용)

    def to_link(self, link_id: str, ids: dict) -> Link:
        return Link(link_id=link_id, item=ids[id(self.item)], group=self.group, grade=METHOD_GRADE[self.method],
                    method=self.method, rule_id=self.rule_id, evidence_text=self.evidence_text,
                    evidence_locations=self.evidence_locations, needs_review=METHOD_GRADE[self.method] == "inferred",
                    profile_source="approved" if self.item.profile_source == "approved" and self.target_approved else "auto")


def _ambiguous(draft):
    return has_inferred_step(draft.category_path)


def _unconfirmed(rule, d, why, issues):
    cols = sorted(d.raw_fields, key=lambda c: (len(c), c)) or None
    issues.add("link_unconfirmed",
               f"연결 규칙 {rule.id}: {d.doc_file} {d.sheet} {d.rows[0]}행 — {why}",
               [Location(file=d.doc_file, sheet=d.sheet, rows={"start": d.rows[0], "end": d.rows[1]}, cols=cols)],
               file=d.doc_file, sheet=d.sheet)


def _to_groups(rule, index, issues, seeker, group_steps, what, glossary=None):
    """찾는 쪽 항목마다 group_steps(항목)로 묶음 경로를 만들고, 대상 쪽에 그 경로로 (단계 단위로) 시작하는 항목이
    있으면 그 묶음과 연결 한 줄. 없으면 link_unconfirmed. 추정 주소 항목은 찾는 쪽·대상 쪽 모두 쓰지 않는다.
    glossary(words, group_of, 묶음별 줄 번호, 승인): 그대로 못 찾았을 때만 용어집으로 바꿔 읽어 찾는다(method glossary)"""
    slots = rule.sheets or [None, None]
    target = 1 - seeker
    target_type = rule.docs[target]
    targets_all = index.side(target_type, slots[target])
    targets = [t for t in targets_all if not _ambiguous(t)]
    sheets = None
    if slots[target] is not None:   # 규칙 칸을 실제 시트 이름으로 푼다(스키마 1.2 GroupRef.sheets)
        sheets = list(dict.fromkeys(t.sheet for t in targets_all)) or None
    out = []
    for d in index.side(rule.docs[seeker], slots[seeker]):
        if _ambiguous(d):
            continue
        steps = group_steps(d)
        if not steps:
            _unconfirmed(rule, d, f"{what}이 없어 묶음을 찾을 수 없습니다", issues)
            continue
        text = path_text(steps)
        match = next((t for t in targets if t is not d and path_starts_with(t.category_path, text)), None)   # 자기 자신은 근거 아님
        hit = _glossary_target(d, steps, targets, glossary[0]) if match is None and glossary else None
        if hit:
            t, k = hit
            words, group_of, lines, approved = glossary
            used = groups_used(steps, _values(t)[:k], group_of)
            group_text = path_text(_values(t)[:k])   # 묶음 경로는 대상 쪽 실제 단계 이름
            out.append(GroupLinkDraft(rule.id, "glossary", d,
                                      GroupRef(doc_type=target_type, category_path_text=group_text, sheets=sheets),
                                      f"{what} 「{text}」를 용어집({', '.join(f'{lines[g]}줄' for g in used)})으로 바꿔 읽으면 "
                                      f"{target_type} 묶음 「{group_text}」의 경로 앞부분",
                                      [d.location(), t.location()],
                                      approved and all(p.approved for p in index.profiles(target_type)), used))
            continue
        if match is None:
            _unconfirmed(rule, d, f"{target_type} 쪽에 「{text}」로 시작하는 묶음이 없습니다", issues)
            continue
        out.append(GroupLinkDraft(rule.id, "path_normalized", d,
                                  GroupRef(doc_type=target_type, category_path_text=text, sheets=sheets),
                                  f"{what} 「{text}」 = {target_type} 묶음 「{text}」의 경로 앞부분",
                                  [d.location(), match.location()],
                                  all(p.approved for p in index.profiles(target_type))))
    return out


@REGISTRY.register("sheet_to_path")
def by_sheet_to_path(rule, index, project, issues) -> list:
    """찾는 쪽 = root_separators가 있는 프로필 쪽. 묶음 경로 = 찾는 쪽 항목의 시트 이름 단계"""
    seeker = seeker_side([any(has_root_separators(p) for p in index.profiles(t)) for t in rule.docs])
    if seeker is None:
        return []   # 설정 검사에서 이미 오류(양쪽·어느 쪽에도 없음)
    glossary = None
    if project.glossary and project.glossary_data and project.glossary_data.groups:   # 2026-10-14: 시트 이름도 용어집으로
        glossary = (*glossary_maps(project), glossary_group_lines(project.base_dir / project.glossary),
                    project.glossary_data.approved)
    return _to_groups(rule, index, issues, seeker,
                      lambda d: [p.value for p in d.category_path if p.basis == "sheet_name"], "시트 이름", glossary)


@REGISTRY.register("path_prefix")
def by_path_prefix(rule, index, project, issues) -> list:
    """묶음 쪽 = 규칙의 group. 묶음 경로 = 찾는 쪽 항목의 경로 전체"""
    return _to_groups(rule, index, issues, 1 - group_side(rule, index), lambda d: [p.value for p in d.category_path],
                      "분류 경로")


# ---------- glossary ----------

def glossary_maps(project) -> tuple:
    """(비교 열쇠(공백 제거·소문자) → 대표어(묶음의 첫 단어)의 비교 열쇠, 비교 열쇠 → 사전 묶음 번호)"""
    words, group_of = {}, {}
    for i, group in enumerate(project.glossary_data.groups if project.glossary_data else []):
        for word in group:
            words[step_key(word)], group_of[step_key(word)] = step_key(group[0]), i
    return words, group_of


def groups_used(a_values, b_values, group_of) -> tuple:
    """두 경로를 잇는 데 쓰인 사전 묶음: 양쪽에 그 묶음 단어가 있고 서로 다른 단어인 묶음(번호 순)"""
    a = {step_key(v) for v in a_values}
    b = {step_key(v) for v in b_values}
    used = set()
    for key in a | b:
        g = group_of.get(key)
        if g is None:
            continue
        ga = {k for k in a if group_of.get(k) == g}
        gb = {k for k in b if group_of.get(k) == g}
        if ga and gb and ga != gb:
            used.add(g)
    return tuple(sorted(used))


def glossary_key(steps, words) -> tuple:
    """단계 전체가 사전 단어면 대표어로 바꾼 경로 열쇠(단계 안 일부는 바꾸지 않음)"""
    return path_key([words.get(step_key(s), step_key(s)) for s in steps])


def _values(d):
    return [p.value for p in d.category_path]


def _glossary_prefix(values, tv, words):
    """대상 경로 tv의 앞 몇 단계를 용어집으로 바꿔 읽으면 values와 같은지 — 그 단계 수. 못 찾거나
    바꾸지 않고도 같으면 None(바꾸지 않고 같으면 path 계열 규칙의 몫)"""
    key = glossary_key(values, words)
    k = next((j for j in range(1, len(tv) + 1) if glossary_key(tv[:j], words) == key), None)
    return None if k is None or path_key(tv[:k]) == path_key(values) else k


def _glossary_target(d, steps, targets, words):
    """steps를 용어집으로 바꿔 읽어 앞부분이 맞는 첫 대상 항목과 그 단계 수. 없으면 None"""
    for t in targets:
        k = None if t is d else _glossary_prefix(steps, _values(t), words)
        if k:
            return t, k
    return None


@REGISTRY.register("glossary")
def by_glossary(rule, index, project, issues) -> list:
    """용어 사전으로 바꿔 읽어 같을 때만, 그리고 실제로 바꾼 단계가 있을 때만(바꾸지 않고 같으면 path 규칙의 몫).
    짝 없는 항목은 경고하지 않는다"""
    words, group_of = glossary_maps(project)
    approved = bool(project.glossary_data and project.glossary_data.approved)
    slots = rule.sheets or [None, None]
    if (rule.options or {}).get("match") == "exact":
        left = [d for d in index.side(rule.docs[0], slots[0]) if _path_key(d) is not None]
        right = [d for d in index.side(rule.docs[1], slots[1]) if _path_key(d) is not None]
        by_key = {}
        for d in right:
            by_key.setdefault(glossary_key(_values(d), words), []).append(d)
        out, seen = [], set()
        for a in left:
            for b in by_key.get(glossary_key(_values(a), words), []):
                pair = frozenset({id(a), id(b)})
                if a is b or pair in seen or _path_key(a) == _path_key(b):
                    continue
                seen.add(pair)
                draft = LinkDraft(rule.id, "glossary", a, b,
                                  f"용어 사전으로 바꿔 읽으면 분류 경로 일치: {a.category_path_text} ↔ {b.category_path_text}",
                                  [a.location(), b.location()], approved,
                                  groups_used(_values(a), _values(b), group_of))
                draft.mismatch = check_content(rule, a, b, issues)
                out.append(draft)
        return out
    target = group_side(rule, index)
    seeker = 1 - target
    targets_all = index.side(rule.docs[target], slots[target])
    targets = [t for t in targets_all if not _ambiguous(t)]
    sheets = list(dict.fromkeys(t.sheet for t in targets_all)) or None if slots[target] is not None else None
    out = []
    for d in index.side(rule.docs[seeker], slots[seeker]):
        if _ambiguous(d) or not d.category_path:
            continue
        values = _values(d)
        for t in targets:
            if t is d:
                continue
            tv = _values(t)
            k = _glossary_prefix(values, tv, words)
            if k is None:
                continue
            text = path_text(tv[:k])   # 묶음 경로는 대상 쪽 실제 단계 이름(rag_core group_contains가 원문 경로로 찾게)
            out.append(GroupLinkDraft(rule.id, "glossary", d,
                                      GroupRef(doc_type=rule.docs[target], category_path_text=text, sheets=sheets),
                                      f"용어 사전으로 바꿔 읽으면 「{d.category_path_text}」 = {rule.docs[target]} 묶음 「{text}」의 경로 앞부분",
                                      [d.location(), t.location()],
                                      approved and all(p.approved for p in index.profiles(rule.docs[target])),
                                      groups_used(values, tv[:k], group_of)))
            break
    return out
