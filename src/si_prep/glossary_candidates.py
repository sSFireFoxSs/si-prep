"""용어 사전 초안 — 시험 실행의 짝 없는 항목에서만, 코드 규칙으로(LLM 없음).

짝 없는 항목의 경로와 대상 쪽 경로가 단계 수가 같고 단 한 단계만 다르면 (대상 쪽 이름, 짝 없는 쪽 이름)을 후보로 센다.
다른 단계가 마지막 단계면(형제 기능일 수 있음) 후보에서 뺀다 — 중간 단계(메뉴·분류 이름)가 다를 때만.
예외: sheet_to_path는 시트 이름 한 단계만 비교하므로, 마지막 단계여도 괄호 부분·구분 기호·공백을 뺀 열쇠
(normalize.loose_key)가 같으면 후보.
같은 단계 수의 대상 경로가 하나도 없는 짝 없는 항목은 「단계 수가 달라서 비교 못 함」으로 규칙별로 센다.
- 대상 쪽: 요약↔상세 규칙은 상세 쪽, 묶음 규칙(sheet_to_path·path_prefix·glossary prefix)은 묶음 쪽, 그 밖의 path 규칙은 docs 첫 종류.
- 짝 없는 쪽 경로: sheet_to_path는 시트 이름 단계, 그 밖은 경로 전체. 묶음 규칙은 대상 쪽 경로의 같은 길이 앞부분과 비교.
- 이미 사전에서 같은 말로 보는 쌍은 뺀다. 추정 경로 항목은 쓰지 않는다.
초안(glossary.yaml 모양, approved: false)에는 단계 이름(셀 내용)이 들어가므로 --out 폴더(저장소 밖)에만 쓰고,
화면에는 규칙별 후보 개수만 보인다. 사람이 검토해 프로젝트 설정 폴더로 옮긴다.

실행: python -m si_prep.glossary_candidates --project <project.yaml> --out <결과 폴더(저장소 밖)>
"""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from si_prep import link
from si_prep.config import ConfigError
from si_prep.normalize import loose_key
from si_prep.schema import has_inferred_step, step_key

DRAFT_NAME = "glossary_draft.yaml"
GROUP_KEYS = ("sheet_to_path", "path_prefix")
MAX_SOURCES = 3     # 후보 쌍마다 쪽별로 적는 출처(파일·시트·행) 수
USAGE = "사용법: python -m si_prep.glossary_candidates --project <project.yaml> --out <결과 폴더(저장소 밖 또는 저장소의 out 폴더 아래)>"
HEADER = """# 용어 사전 초안 — 자동 생성(짝 없는 항목에서만, 코드 규칙, LLM 없음). approved: false
# 검토 기준: 두 이름이 같은 대상을 부르는 말일 때만 남긴다. 다른 기능(예: 아이디 찾기/비밀번호 찾기)이면 지운다.
# 한 줄 = 한 묶음, 앞이 대표어(대상 쪽 = 메뉴·묶음 쪽 이름). 줄 끝: 규칙 id, 나온 횟수, 예시 위치(시트·행)
# 아래 「출처」 주석: 쌍마다 두 이름이 나온 파일·시트·행(쪽마다 처음 몇 곳). 원문을 열어 같은 대상인지 볼 때 쓴다
# 같은 단어를 가진 쌍은 한 줄로 합쳤다(주석에 원래 쌍마다 규칙·횟수·예시). 틀린 쌍의 단어만 골라 지운다.
# 대상 쪽 실제 이름(대상 문서 경로 단계에 있는 이름)이 둘 이상 한 줄에 섞이면 합치지 않는다: 같은 단어를 가진 쌍 중
# 횟수가 가장 많은 쌍만 남기고(같은 횟수면 모두 뺌) 나머지는 「뺀 쌍: … (대상 이름 겹침)」 주석으로만 적었다.
# 같은 깊이에서 두 이름이 모두 대상 쪽 실제 이름인 쌍은 혼자여도 뺐다. 띄어쓰기·대소문자만 다른 표기는 한 단어로 본다.
# 한 줄에 서로 관계없는 무리가 섞이면 줄을 나눈다(단어 하나를 지워 사슬이 끊어진 경우 등).
# 기존 사전과 합칠 때는 이미 있는 단어를 그 줄에 넣는다(한 단어는 한 줄에만). 검토가 끝나면 approved: true
"""


@dataclass(frozen=True)
class Candidate:
    rule_id: str
    rep: str            # 대표어(대상 쪽 이름)
    other: str          # 짝 없는 쪽 이름
    count: int
    example: tuple      # (시트, 행) 첫 예시
    other_in_target: bool = False   # 짝 없는 쪽 이름도 대상 쪽 경로의 같은 깊이에 실제로 있음(다른 메뉴 이름일 수 있음)
    level: int | None = None        # 두 이름이 다른 단계 위치(0부터, 첫 예시 기준)
    rep_sources: tuple = ()         # 대표어가 나온 대상 쪽 항목 (파일, 시트, 시작 행), 처음 MAX_SOURCES곳
    other_sources: tuple = ()       # 짝 없는 쪽 이름이 나온 항목 (파일, 시트, 시작 행), 처음 MAX_SOURCES곳


def _target_side(rule, index):
    slots = rule.sheets or [None, None]
    if rule.key in GROUP_KEYS or (rule.key == "glossary" and rule.group):
        return link.group_side(rule, index)
    if "overview" in slots:
        return 1 - slots.index("overview")
    return 0


def candidates(config, index, made_by_rule) -> list:
    """made_by_rule: 실행 결과의 규칙 id → 연결 초안(규칙을 다시 돌리지 않는다)"""
    return _scan(config, index, made_by_rule)[0]


def depth_mismatch_counts(config, index, made_by_rule) -> dict:
    """규칙 id → 같은 단계 수의 대상 경로가 없어 비교하지 못한 짝 없는 항목 수"""
    return _scan(config, index, made_by_rule)[1]


def _scan(config, index, made_by_rule):
    words, _ = link.glossary_maps(config)
    out, depth = [], Counter()
    for rule in config.link_rules:
        if rule.key not in ("path", "glossary") + GROUP_KEYS or rule.id not in made_by_rule:
            continue   # 후보를 만들지 않는 key, 또는 실행 때 건너뛴(미구현) 규칙
        target = _target_side(rule, index)
        if target is None:   # sheet_to_path에서 찾는 쪽을 정할 수 없음
            continue
        slots = rule.sheets or [None, None]
        targets = [t for t in index.side(rule.docs[target], slots[target]) if not has_inferred_step(t.category_path)]
        grouped = rule.key in GROUP_KEYS or (rule.key == "glossary" and rule.group)
        target_at = {}   # 깊이 → 대상 쪽 그 단계에 실제 있는 이름(비교 열쇠)
        for t in targets:
            for i, p in enumerate(t.category_path):
                if p.value is not None:
                    target_at.setdefault(i, set()).add(step_key(p.value))
        found, first, in_target, where = Counter(), {}, {}, {}   # where: 쌍 → (대상 쪽 출처, 짝 없는 쪽 출처) 순서 유지 dict
        for d in link.unmatched(rule, index, made_by_rule[rule.id])[1 - target]:   # 짝 없음 기준은 실행 화면과 같음
            mine = ([p.value for p in d.category_path if p.basis == "sheet_name"] if rule.key == "sheet_to_path"
                    else [p.value for p in d.category_path])
            pairs, comparable = set(), False
            for t in targets:
                theirs = [p.value for p in t.category_path]
                theirs = theirs[:len(mine)] if grouped else theirs
                if len(theirs) != len(mine):
                    continue
                comparable = True
                diff = [i for i, (a, b) in enumerate(zip(mine, theirs)) if step_key(a) != step_key(b)]
                if len(diff) != 1:
                    continue   # 두 단계 이상 다름
                a, b = mine[diff[0]], theirs[diff[0]]
                if diff[0] == len(mine) - 1 and not (rule.key == "sheet_to_path" and loose_key(a) and loose_key(a) == loose_key(b)):
                    continue   # 마지막 단계(기능 이름)만 다름. sheet_to_path는 괄호·기호를 뺀 열쇠가 같으면 예외
                if words.get(step_key(a), step_key(a)) == words.get(step_key(b), step_key(b)):
                    continue   # 이미 사전에서 같은 말
                pairs.add((b, a, diff[0]))
                rep_at, _ = where.setdefault((b, a), ({}, {}))
                rep_at.setdefault((t.doc_file, t.sheet, t.rows[0]))
            if not comparable:
                depth[rule.id] += 1
            for b, a, i in sorted(pairs):
                pair = (b, a)
                found[pair] += 1
                first.setdefault(pair, (d.sheet, d.rows[0], i))
                in_target[pair] = in_target.get(pair, False) or step_key(a) in target_at.get(i, ())
                where[pair][1].setdefault((d.doc_file, d.sheet, d.rows[0]))
        ranked = sorted(found.items(), key=lambda x: (-x[1], x[0]))
        out += [Candidate(rule.id, rep, other, n, first[(rep, other)][:2], in_target[(rep, other)], first[(rep, other)][2],
                          *(tuple(list(w)[:MAX_SOURCES]) for w in where[(rep, other)]))
                for (rep, other), n in ranked]
    return out, depth


def _components(cands):
    """같은 단어(비교 열쇠)를 공유하는 후보 쌍들을 한 묶음으로(한 단어는 사전의 한 묶음에만 있을 수 있음). 입력 순서 유지"""
    parent = {}

    def find(w):
        parent.setdefault(w, w)
        while parent[w] != w:
            parent[w] = parent[parent[w]]
            w = parent[w]
        return w

    for c in cands:
        parent[find(step_key(c.rep))] = find(step_key(c.other))
    comps = {}
    for c in cands:
        comps.setdefault(find(step_key(c.rep)), []).append(c)
    return list(comps.values())


def _pair_note(c):
    return f"{c.rep}↔{c.other} {c.rule_id} {c.count}회 예: {c.example[0]} {c.example[1]}행"


def _source_note(c):
    """「출처 a↔b: a = 파일 시트 n행, … / b = …」 (출처가 없으면 None)"""
    if not (c.rep_sources or c.other_sources):
        return None
    side = lambda w, src: f"{w} = " + (", ".join(f"{f} {s} {r}행" for f, s, r in src) or "없음")
    return f"출처 {c.rep}↔{c.other}: {side(c.rep, c.rep_sources)} / {side(c.other, c.other_sources)}"


def _keys(c):
    return {step_key(c.rep), step_key(c.other)}


def _both_targets(c, cands):
    """같은 깊이에서 두 이름이 모두 대상 쪽 실제 이름: 짝 없는 쪽 이름이 대상 경로의 같은 단계에 있거나,
    다른 후보(다른 규칙 포함)의 같은 깊이 대표어(대상 쪽 이름)임"""
    if c.other_in_target:
        return True
    return c.level is not None and any(d.level == c.level and step_key(d.rep) == step_key(c.other) for d in cands)


def _split_targets(comp):
    """한 묶음에 대상 쪽 실제 이름이 둘 이상이면 합치지 않는다(서로 다른 메뉴 이름이 사슬로 묶이지 않게).
    횟수가 많은 쌍부터 남기되, 이미 남긴 쌍(또는 막힌 단어)과 단어를 나누는 쌍은 뺀다.
    같은 횟수의 쌍들이 같은 단어를 다투면 그 쌍들을 모두 빼고 그 단어를 막는다(이긴 쪽이 없음).
    진 쌍이 다른 쌍을 빼지 않으므로 연쇄로 맞는 쌍을 잃지 않는다. 돌려주는 값: (남긴 묶음들, 뺀 쌍들)"""
    if len({step_key(c.rep) for c in comp}) < 2:
        return [comp], []
    kept, dropped, taken = [], [], set()
    for count in sorted({c.count for c in comp}, reverse=True):
        level = [c for c in comp if c.count == count]
        free = [c for c in level if not (_keys(c) & taken)]
        dropped += [c for c in level if c not in free]
        uses = Counter(w for c in free for w in _keys(c))
        for c in free:
            if any(uses[w] > 1 for w in _keys(c)):
                dropped.append(c)
            else:
                kept.append(c)
        taken |= {w for c in free for w in _keys(c)}
    return [[c] for c in comp if c in kept], [c for c in comp if c in dropped]


def draft_yaml(cands) -> str:
    """glossary.yaml 모양의 초안. 같은 단어를 가진 쌍은 한 줄로 합치고(대표어 = 대상 쪽 이름으로 가장 많이 나온 단어),
    줄 끝 주석에 원래 쌍마다 「a↔b 규칙 n회 예: 시트 행」을 따로 적는다(틀린 단어만 골라 지울 수 있게).
    줄은 가장 큰 쌍의 규칙별로 묶고, 합친 횟수가 많은 순"""
    lines = [HEADER.rstrip("\n"), "approved: false", "groups:"]
    if not cands:
        lines[-1] = "groups: []   # 짝 없는 항목에서 한 단계만 다른 후보가 없음"
    rule_order = list(dict.fromkeys(c.rule_id for c in cands))
    entries, comps = [], []
    dropped = [c for c in cands if _both_targets(c, cands)]   # 혼자여도 뺀다
    for comp in _components([c for c in cands if c not in dropped]):
        kept, out = _split_targets(comp)
        comps += kept
        dropped += out
    for comp in comps:
        as_rep, total, shown = {}, {}, {}   # 비교 열쇠별로 세고, 보이는 글자는 처음 나온 표기
        for c in comp:
            for w in (c.rep, c.other):
                shown.setdefault(step_key(w), w)
                total[step_key(w)] = total.get(step_key(w), 0) + c.count
            as_rep[step_key(c.rep)] = as_rep.get(step_key(c.rep), 0) + c.count
        rep_key = sorted(as_rep, key=lambda k: (-as_rep[k], shown[k]))[0]
        rep = shown[rep_key]
        words = [rep] + [shown[k] for k in sorted((k for k in total if k != rep_key), key=lambda k: (-total[k], shown[k]))]
        main = max(comp, key=lambda c: (c.count, c.rule_id))
        ordered = sorted(comp, key=lambda c: (-c.count, c.rule_id, c.rep, c.other))
        notes = "; ".join(_pair_note(c) for c in ordered)
        near = [d for d in dropped if _keys(d) & {step_key(w) for w in words}]
        if near:
            notes += "; 뺀 쌍: " + ", ".join(_pair_note(d) for d in near) + " (대상 이름 겹침)"
            dropped = [d for d in dropped if d not in near]
        entries.append((rule_order.index(main.rule_id), -sum(c.count for c in comp), rep, main.rule_id, words, notes,
                        ordered + near))
    for d in dropped:   # 남긴 줄과 단어를 나누지 않는 뺀 쌍(같은 횟수라 모두 뺀 경우)은 주석 줄로만
        entries.append((rule_order.index(d.rule_id), -d.count, d.rep, d.rule_id, None,
                        f"뺀 쌍: {_pair_note(d)} (대상 이름 겹침)", [d]))
    if cands and not any(e[4] for e in entries):
        lines[-1] = "groups: []   # 남은 후보 없음(뺀 쌍만 아래 주석에)"
    last_rule = None
    for _, _, _, rule_id, words, notes, pairs in sorted(entries, key=lambda e: e[:3] + (e[4] is None,)):
        if rule_id != last_rule:
            lines.append(f"  # 규칙 {rule_id}")
            last_rule = rule_id
        lines.append(f"  - {json.dumps(words, ensure_ascii=False)}   # {notes}" if words else f"  # {notes}")
        lines += [f"  #   {n}" for n in map(_source_note, pairs) if n]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    from si_prep.console import replace_unencodable
    replace_unencodable()   # 화면 출력: 인코딩은 그대로, 못 쓰는 글자만 ?(cp949 콘솔에서 멈추지 않게)
    from si_prep import run   # 실행은 main에서만(후보 계산은 run 없이 — 보고서가 import)
    opts = run.parse_project_out(argv, USAGE)
    if opts is None:
        return 2
    error = run.out_location_error(opts["--out"])   # 실행과 같은 위치 규칙(초안에도 단계 이름 = 셀 내용)
    if error:
        print(error)
        return 1
    try:
        result = run.build(opts["--project"])
    except ConfigError:
        # 새 용어집을 만드는 도구라 기존 사전이 깨졌거나 없어도 돈다. 사전 없이도 안 되면 다른 설정 오류
        try:
            result = run.build(opts["--project"], ignore_glossary=True)
        except ConfigError as e:
            print(e)
            return 1
        print("기존 사전에 오류가 있어 무시하고 새로 만들었어요(사전·glossary 규칙 없이 시험 실행)")
    cands, depth = _scan(result.config, result.index, result.made_by_rule)
    out = Path(opts["--out"])
    out.mkdir(parents=True, exist_ok=True)
    existed = (out / DRAFT_NAME).exists()
    (out / DRAFT_NAME).write_text(draft_yaml(cands), encoding="utf-8", newline="\n")
    if existed:
        print(f"이전 초안을 덮어썼습니다: {out / DRAFT_NAME} (고친 내용은 프로젝트 설정 폴더로 옮겨 두세요)")
    counts = Counter(c.rule_id for c in cands)
    print(f"용어 사전 초안을 썼습니다: {out / DRAFT_NAME} (단계 이름이 들어 있어 화면에는 개수만)")
    print("규칙별 후보 개수: " + (", ".join(f"{r} {n}" for r, n in counts.items()) or "없음"))
    print("규칙별 단계 수가 달라서 비교 못 한 짝 없는 항목: " + (", ".join(f"{r} {n}" for r, n in depth.items()) or "없음"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
