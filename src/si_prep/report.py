"""처리 보고서 — 실행 결과로 report.md와 report_목록.md를 만든다.

- --out 폴더에 4개 결과 파일과 함께 쓴다(run.write). 셀 내용(경로·title·용어집 단어)은 이 두 파일에만, 화면에는 숫자만.
- 시험 실행(approved: false)에서도 만든다. 사람이 이 보고서를 보고 설정을 고친 뒤 확정한다.
- 맨 위 0절 「먼저 볼 것」(상태·핵심 숫자·할 일), 절마다 제목 아래 쉬운 말 한 줄(EASY)과 고정 문구 「고칠 곳:」(SECTIONS),
  맨 아래 「용어 설명」(TERMS). 설정 이름·전문 용어는 괄호 안에만 쓴다.
- 긴 목록: 항목 목록(4·5·6·8절)은 SHOWN개, 다른 표는 LONG줄을 넘으면 앞 SHOWN개만 report.md에 두고 전체는 report_목록.md
  (같은 절 번호). 4·5·6·8절 항목 목록은 길이와 관계없이 report_목록.md에도 전부 쓴다. 12절 표는 줄이지 않는다.
- 같은 입력이면 바이트까지 같다(시각·절대 경로 없음).
- 4절은 용어집까지 적용한 최종 짝 없음. 규칙 sheets가 고른 시트 밖의 항목은 그 규칙 숫자에 넣지 않는다.
"""

from collections import Counter, defaultdict

from si_prep import glossary_candidates, link
from si_prep.normalize import id_key
from si_prep.schema import INFERRED_BASES, SCHEMA_VERSION, has_inferred_step

REPORT_FILE = "report.md"
LIST_FILE = "report_목록.md"
SHOWN = 10        # 줄인 목록에서 report.md에 남기는 줄 수
LONG = 20         # 항목 목록이 아닌 표는 이 줄 수를 넘으면 줄인다
ITEM_LIST_SECTIONS = (4, 5, 6, 8)   # 항목 목록 절: SHOWN개를 넘으면 줄이고, 전체는 늘 report_목록.md에

# (절 제목, 고칠 곳) — 순서가 절 번호(1부터)
SECTIONS = [
    ("실행 요약", "승인 전 설정 파일(project.yaml·프로필·glossary.yaml의 approved: false). 아래 절을 보고 고친 뒤 승인(approved: true)"),
    ("경고 종류별 수", "처리 실패·지원 범위 밖은 그 문서 프로필(시트·머리글·방식). 정보 없음·정보 차이는 원문 확인(설정으로 고치지 않음)"),
    ("시트별 표", "그 문서 프로필의 시트 목록(sheets: 읽음·뺌·이유)과 요약 시트(overview_sheets)"),
    ("연결 규칙별 짝 없는 항목", "규칙마다 아래 「고칠 곳」 줄(용어집 초안 후보가 있으면 glossary.yaml, 없으면 project.yaml의 규칙)"),
    ("어느 연결에도 없는 항목", "project.yaml의 연결 규칙(link_rules)"),
    ("추정 경로 항목", "프로필의 분류 열과 위 값 채우기(fill_down)"),
    ("본문이 빈 항목", "그 문서 프로필의 역할 열과 본문 제외 열(exclude_from_text). 원문이 비었으면 고칠 것 없음"),
    ("같은 시트 안 같은 경로 항목", "프로필의 분류 열과 항목 경계(item_boundary). 원문에 같은 경로가 두 번이면 고칠 것 없음"),
    ("버전을 못 찾은 파일", "그 문서 프로필의 버전 설정(version: cover_sheet·label_pattern·filename_pattern)"),
    ("역할 열을 못 찾은 시트", "그 문서 프로필의 머리글 행(header_rows)이나 역할 열 이름"),
    ("용어집 줄별 효과", "glossary.yaml"),
    ("구조 진단", "「검토」 시트가 있으면 그 문서 프로필. 무엇을 고칠지는 아래 열 설명의 「확인」 줄"),
]
# 절 번호 → 제목 바로 아래 쉬운 말 한 줄(이 절이 뭘 보는 곳인지, 숫자가 많으면 뭘 하면 되는지)
EASY = {
    0: "이 실행의 상태와 사람이 할 일을 모았습니다. 할 일마다 근거 숫자와 볼 곳이 있습니다. 「알려진 한계」는 도구가 원래 읽지 않는 것이라 설정으로는 고칠 수 없습니다. 머리글 없는 열처럼 중요한 내용일 수 있는 것은 원본을 확인합니다.",
    1: "어떤 설정으로 무엇을 몇 개 만들었는지 봅니다.",
    2: "처리하면서 남긴 경고를 종류별로 셉니다. 「처리 실패」·「지원 범위 밖」이 있으면 warnings.jsonl에서 그 경고의 위치를 봅니다.",
    3: "문서마다 읽은 시트와 뺀 시트를 봅니다. 「새 시트, 확인 필요」가 있으면 그 시트를 읽을지 정합니다.",
    4: "연결 규칙마다 짝을 못 찾은 항목을 셉니다. 「못 찾은」이 많으면 규칙 아래 「고칠 곳」을 봅니다.",
    5: "연결 규칙이 있는 문서인데 어느 연결에도 들지 못한 항목입니다. 많으면 4절에서 어느 규칙 때문인지 봅니다.",
    6: "분류 칸이 비어 위 값으로 채운 단계가 있는 항목입니다. 이 항목은 경로 연결에서 빠집니다.",
    7: "본문이 비어 검색용 조각(청크)을 만들지 않은 항목입니다. 원문이 비었으면 할 일이 없습니다.",
    8: "한 시트 안에서 분류 경로가 같은 항목 묶음입니다. 항목 경계가 잘못 잡혔는지 봅니다.",
    9: "문서 버전을 표지나 파일 이름에서 못 찾은 파일입니다.",
    10: "제목·설명 같은 역할 열을 머리글에서 못 찾은 시트입니다.",
    11: "용어집 줄마다 연결을 몇 개 만들었는지 봅니다. 연결이 0인 줄은 이 데이터에서 쓰이지 않았습니다.",
    12: "시트마다 분류 칸의 병합·빈칸 모양을 셉니다. 빈칸이 「위와 같음」인지 사람이 확인할 시트를 찾습니다.",
}
TERMS_EASY = "괄호 안에 쓴 설정 이름과 용어의 뜻입니다."
# 12절 「검토」 기준: 앞쪽 빈칸 행 ÷ 항목 ≥ 이 값이고 선언 안 한 시트(「행의 절반 이상」 원칙, 특정 문서에 맞춘 값 아님)
BLANK_ROW_REVIEW_RATIO = 0.5
STRUCTURE_TODO = "맨 오른쪽이 '검토'인 시트만 엑셀에서 빈칸을 눌러 보고, 위와 같은 뜻이면 '위와 같음'이라고 알려 주기"
FIX_GLOSSARY = "glossary.yaml"
# 「용어집으로 풀림」을 세는 규칙 방식: 같은 두 쪽 glossary 규칙의 연결로 짝 없음이 풀릴 수 있는 경로 규칙(path_prefix 추가)
GLOSSARY_RESOLVED_KEYS = ("path", "path_prefix")
GLOSSARY_TOTAL_NOTE = ("「용어집으로 해결된 항목」은 경로 규칙(path·path_prefix)의 짝을 찾는 쪽에서 셉니다. 그 규칙으로는 짝이 없고, "
                       "같은 두 쪽 용어집 규칙(glossary)의 연결로 이어진 항목 수입니다. 아래 규칙·쪽별 표의 합입니다(묶음 쪽은 없음)")
GLOSSARY_LINE_NOTE = ("줄별 「풀린 짝 없음」은 요약↔상세 규칙(한쪽 칸 overview)의 요약 쪽만 셉니다. 경로 규칙(path)으로 짝이 없어 "
                      "짝 없음 경고(link_unconfirmed)가 날 항목 중, 그 줄의 묶음을 쓴 용어집 연결로 이어진 수입니다. "
                      "한 항목에 여러 줄이 쓰이면 줄마다 셉니다. 그 줄만 지웠을 때 다시 짝 없음이 되는 수는 아닙니다(다른 줄로도 "
                      "이어질 수 있음). 그래서 줄별 합은 위 표의 「줄별 숫자에 포함: 예」 행과 비교합니다(상세 쪽·기능↔테스트 규칙은 "
                      "줄별 숫자에 없음)")
FIX_RULE = "project.yaml의 규칙 시트·문서(sheets·docs)"
FIX_ID_REF = ("찾는 쪽 프로필의 참조 ID 열(ref_ids: 열·pattern)과 대상 쪽 프로필의 자기 ID 열(id). "
              "원문에 참조가 없으면 고칠 것 없음")

# 경고 종류 → 구분
CATEGORY = {
    "content_mismatch": "정보 차이",
    "unparsed": "처리 실패",
    "unsupported": "지원 범위 밖",
    "unsupported_layout": "지원 범위 밖",
    "merge_unrestored": "정보 없음",
    "link_unconfirmed": "정보 없음",
    "version_mismatch": "정보 차이",
    "sheet_skipped": "처리 범위 기록",
    "hidden_content": "표시",
    "header_not_found": "처리 실패",
    "duplicate_id": "정보 차이",
    "ref_unresolved": "정보 없음",
    "formula_no_value": "정보 없음",
    "read_failed": "처리 실패",
}
TODO_CATEGORIES = ("처리 실패", "지원 범위 밖")   # 0절 할 일에 올리는 경고 구분(「알려진 한계」 경고는 뺌)
LIMIT_KINDS = ("hidden_content",)                # 0절 「알려진 한계」에 올리는 경고 종류(숨김도 그대로 읽음, 표시만)
# 경고 종류 → 쉬운 말(2절 「무엇」 열)
WARNING_MEANING = {
    "content_mismatch": "이은 두 칸의 설명이 다름",
    "unparsed": "칸 글자를 풀지 못함",
    "unsupported": "지원하지 않는 방식이라 건너뜀",
    "unsupported_layout": "읽지 못하는 표 모양",
    "merge_unrestored": "빈 분류 단계를 채우지 못함",
    "link_unconfirmed": "짝을 못 찾음",
    "version_mismatch": "버전 표기가 서로 다름",
    "sheet_skipped": "시트를 건너뜀",
    "hidden_content": "숨긴 행·열에 값 있음",
    "header_not_found": "머리글·역할 열을 못 찾음",
    "duplicate_id": "같은 ID가 두 번 이상",
    "ref_unresolved": "참조 ID를 못 찾음",
    "formula_no_value": "계산값 없는 수식",
    "read_failed": "파일을 읽지 못함",
}
# 연결 방식 → 쉬운 말(4절 「방식」 줄)
KEY_MEANING = {
    "path": "분류 경로가 같음",
    "sheet_to_path": "시트 이름이 묶음 경로와 같음",
    "path_prefix": "분류 경로가 묶음 경로로 시작함",
    "id_ref": "참조 ID가 대상의 자기 ID와 같음",
    "glossary": "용어집으로 바꿔 읽은 분류 경로가 같음",
    "name_similarity": "이름이 비슷함",
}
# 근거 종류(basis) → 쉬운 말(6절 추정 단계)
BASIS_MEANING = {"filled_down": "위 값 채움", "empty": "빈 단계"}
# 용어 설명(맨 아래 절): (용어, 뜻) — 한 줄에 한 용어
TERMS = [
    ("항목", "업무 하나(기능·정책·테스트 한 줄 등). items.jsonl 한 줄"),
    ("연결", "두 항목(또는 항목과 묶음)이 이어진 근거. links.jsonl 한 줄"),
    ("경고", "처리하지 못했거나 사람이 볼 것. warnings.jsonl 한 줄"),
    ("청크", "검색용 조각. 항목마다 분류 경로 + 본문. chunks.jsonl 한 줄"),
    ("분류 경로", "항목의 분류 단계를 이은 글자(예: 대분류 › 중분류)"),
    ("추정 경로", "빈 칸을 위 값으로 채우는 등 원문에 그대로 없는 단계가 있는 경로"),
    ("묶음", "같은 분류 경로로 시작하는 항목들. 항목 하나가 묶음 전체와 이어질 때 씀"),
    ("짝 없음", "연결 규칙의 한쪽 항목인데 다른 쪽에서 짝을 못 찾음"),
    ("시험 실행", "승인 전 설정이 섞인 실행. 평가에 쓰지 않음"),
    ("approved", "설정 파일의 승인 표시. 모두 true면 공식 실행"),
    ("profile_source", "결과가 승인된 설정으로 만들어졌는지(approved / auto)"),
    ("overview", "요약 시트 칸. 프로필 overview_sheets로 정함"),
    ("sheets", "프로필의 시트 목록(읽음·뺌·이유), 또는 연결 규칙이 고르는 시트"),
    ("docs", "연결 규칙이 잇는 두 문서 종류"),
    ("link_rules", "project.yaml의 연결 규칙 목록"),
    ("path", "연결 방식: 분류 경로가 같으면 이음"),
    ("path_prefix", "연결 방식: 항목의 분류 경로로 시작하는 묶음과 이음"),
    ("sheet_to_path", "연결 방식: 시트 이름을 묶음 경로로 읽어 이음"),
    ("id_ref", "연결 방식: 참조 ID 칸의 ID가 대상의 자기 ID와 같으면 이음"),
    ("glossary", "연결 방식: 용어집(glossary.yaml)으로 같은 말로 바꿔 읽은 경로가 같으면 이음"),
    ("ref_ids", "프로필의 참조 ID 열(열·pattern)"),
    ("id", "프로필의 자기 ID 열"),
    ("fill_down", "분류 칸이 비면 위 항목의 값으로 채움(켬·끔)"),
    ("blank_means_above", "사람 선언: 이 시트의 빈 분류 칸은 「위와 같음」"),
    ("border_groups", "테두리(가로 선)로 나뉜 묶음 안에서만 위 값으로 채움"),
    ("sheet_overrides", "프로필에서 시트마다 설정을 덮어쓰는 곳"),
    ("tables", "한 시트에 표가 여러 개일 때 표를 나누는 설정"),
    ("item_boundary", "항목 경계(몇 행이 항목 하나인지)"),
    ("exclude_from_text", "본문에서 빼는 열"),
    ("header_rows", "머리글 행 번호"),
    ("version", "문서 버전을 찾는 설정(cover_sheet·label_pattern·filename_pattern)"),
    ("overview_sheets", "요약 시트를 고르는 프로필 설정"),
]


def _cell(v) -> str:
    """표 칸 글자: 줄바꿈·| 는 표를 깨므로 바꾼다(원문은 결과 파일에 그대로)"""
    return "" if v is None else str(v).replace("\r", " ").replace("\n", " ").replace("|", "\\|")


def _row(*values) -> str:
    return "| " + " | ".join(_cell(v) for v in values) + " |"


def _head(names: str) -> list:
    """표 머리 두 줄. names = 「열 | 열 | …」"""
    return [f"| {names} |", "|" + " --- |" * len(names.split(" | "))]


def _table(lists, n, sub, head, rows) -> list:
    """표 줄. 항목 목록 절(ITEM_LIST_SECTIONS)은 SHOWN개, 다른 표는 LONG개를 넘으면(12절 표는 C8-2 예외로 이 함수를 쓰지 않음) 앞 SHOWN개 + 안내 줄만 남기고
    전체는 report_목록.md(같은 절 번호). 항목 목록 절의 표는 줄이지 않아도 report_목록.md에 전부 쓴다"""
    item_list = n in ITEM_LIST_SECTIONS
    if item_list or len(rows) > LONG:
        lists[n].append((sub, head + rows))
    if len(rows) <= (SHOWN if item_list else LONG):
        return head + rows
    where = f"{LIST_FILE} {n}절" + (f" 「{sub}」" if sub else "")
    return head + rows[:SHOWN] + ["", f"앞 {SHOWN}개만 보입니다. 전체 {len(rows)}개는 {where}에 있습니다."]


def _ordered(result):
    """항목 초안을 ID 순서로"""
    drafts = [d for entries in result.index._by_type.values() for d, _ in entries]
    return sorted(drafts, key=lambda d: (result.ids.get(id(d), ""), d.rows))


def _folded_glossary(config):
    """경로 규칙(path·path_prefix)과 같은 두 쪽인 glossary 규칙 id → 그 경로 규칙 id (4절에서 그 규칙에 합쳐 센다)"""
    out = {}
    for g in config.link_rules:
        if g.key != "glossary":
            continue
        p = next((p for p in config.link_rules if p.key in GLOSSARY_RESOLVED_KEYS and link.same_sides(p, g)), None)
        if p is not None:
            out[g.id] = p.id
    return out


def _section(n, lines):
    title, fix = SECTIONS[n - 1]
    return [f"## {n}. {title}", "", EASY[n], "", f"고칠 곳: {fix}", ""] + lines + [""]


# ---------- 0절 먼저 볼 것 ----------

def _warning_counts(result, exclude=frozenset()) -> dict:
    """경고 종류 → 수(kind 순). exclude: 세지 않을 경고 번호(0절 할 일에서 「알려진 한계」 경고를 뺄 때)"""
    counts = Counter(w.kind for w in result.warnings if w.warning_id not in exclude)
    return dict(sorted(counts.items()))


def _review_rows(result) -> list:
    """12절 「검토」 줄: (문서, 표 이름)"""
    return [(r[0], r[2]) for r in result.structure if _structure_mark(r) == "검토"]


def _structure_mark(row) -> str:
    _, _, _, _, items, _, b, _, declared = row
    ratio = b.front_rows / items if items else 0.0
    return "선언됨" if declared else "검토" if items and ratio >= BLANK_ROW_REVIEW_RATIO else ""


def _todos(result, rule_stats) -> list:
    """0절 할 일: (무엇, 근거 숫자, 볼 곳). 절 순서"""
    out = []
    if result.trial:
        auto_items = sum(i.profile_source == "auto" for i in result.items)
        auto_links = sum(l.profile_source == "auto" for l in result.links)
        out.append(("설정을 검토하고 승인하기(approved: true)", f"승인 전 설정으로 만든 항목 {auto_items} · 연결 {auto_links}",
                    "1절, 설정 파일"))
    counts = _warning_counts(result, exclude=set(result.limit_ids))
    for category in TODO_CATEGORIES:
        kinds = [(k, n) for k, n in counts.items() if CATEGORY.get(k) == category]
        if kinds:
            out.append((f"「{category}」 경고 위치 확인하기",
                        f"{sum(n for _, n in kinds)}건(" + ", ".join(f"{k} {n}" for k, n in kinds) + ")", "2절, warnings.jsonl"))
    new = [r[2] for r in result.sheet_rows if r[6]]
    if new:
        cut = len(result.sheet_rows) > LONG   # 3절 표를 줄였으면 새 시트 줄이 report_목록.md에만 있을 수 있다
        out.append(("새 시트를 읽을지 정하기", f"새 시트 {len(new)}개",
                    "3절 「확인」 열" + (f"({LIST_FILE} 3절에 전체)" if cut else "")))
    for rule_id, missing, cands in rule_stats:
        if missing:
            out.append((f"규칙 {rule_id}의 짝 없는 항목 보기", f"못 찾은 {missing}" + (f" · 용어집 초안 후보 {cands}개" if cands else ""),
                        f"4절 「{rule_id}」"))
    inferred = sum(1 for d in _ordered(result) if has_inferred_step(d.category_path))
    if inferred:
        out.append(("추정 경로 항목 보기(경로 연결에서 빠짐)", f"{inferred}개", "6절"))
    if result.empty_body:
        out.append(("본문이 빈 항목 보기", f"{len(result.empty_body)}개", "7절"))
    listed, _ = _same_path_groups(result)
    if listed:
        out.append(("경로·제목이 같은 항목 보기", f"{len(listed)}묶음", "8절"))
    if result.version_missing:
        out.append(("버전을 못 찾은 파일 보기", f"{len(result.version_missing)}개",
                    "9절 " + ", ".join(f for f, _ in result.version_missing)))
    if result.roles_missing:
        out.append(("역할 열을 못 찾은 시트 보기", f"{len(result.roles_missing)}개", "10절"))
    review = _review_rows(result)
    if review:
        out.append(("빈칸이 「위와 같음」인지 확인하기", f"검토 시트 {len(review)}개",
                    "12절 " + ", ".join(f"「{label}」" for _, label in review)))
    return out


def _todo_lines(todos) -> list:
    if not todos:
        return ["- 할 일 없음"]
    return [f"- [ ] {what} — 근거: {basis} — 볼 곳: {where}" for what, basis, where in todos]


def _limits(result) -> list:
    """0절 알려진 한계: (무엇, 근거 숫자, 볼 곳). 도구가 원래 읽지 않는 것이라 설정으로는 못 고침. 머리글 없는 열은 원본 확인 안내를 붙임"""
    out = []
    if result.above_header:
        cells = sum(x[4] for x in result.above_header)
        out.append(("머리글 위 칸의 값(표 제목·작성자 등, 표 밖이라 읽지 않음)",
                    f"표 {len(result.above_header)}개 · 칸 {cells}개(unsupported_layout)", "2절, warnings.jsonl"))
    headerless = sum(1 for v in result.limit_ids.values() if v == "headerless")
    if headerless:
        out.append(("머리글 없는 열의 값(어느 항목에도 들어가지 않음, 중요한 내용이면 원본 확인)", f"머리글 없는 열의 값 덩어리 {headerless}건(unsupported_layout)",
                    "2절, warnings.jsonl"))
    counts = _warning_counts(result)
    for kind in LIMIT_KINDS:
        if counts.get(kind):
            out.append((f"{WARNING_MEANING[kind]}(숨김도 그대로 읽음)", f"{kind} {counts[kind]}건", "2절, warnings.jsonl"))
    return out


def _limit_lines(limits) -> list:
    if not limits:
        return ["- 없음"]
    return [f"- {what} — 근거: {basis} — 볼 곳: {where}" for what, basis, where in limits]


def _first(result, rule_stats) -> list:
    state = ("시험 실행(승인 전 설정이 섞여 있음. 평가에 쓰지 마세요)" if result.trial
             else "공식 실행(모든 설정이 승인됨)")
    lines = ["## 0. 먼저 볼 것", "", EASY[0], "",
             f"- 상태: {state}",
             f"- 핵심 숫자: 항목 {len(result.items)} · 연결 {len(result.links)} · 경고 {len(result.warnings)}",
             "", "할 일:", ""]
    return (lines + _todo_lines(_todos(result, rule_stats)) + ["", "알려진 한계(설정으로는 못 고침):", ""]
            + _limit_lines(_limits(result)) + [""])


# ---------- 1~12절 ----------

def _summary(result, lists):
    c = result.config
    tiers = " > ".join("·".join(t) for t in c.priority_tiers) or "없음"
    lines = []
    if result.trial:
        lines.append("**시험 실행**: 승인 전 설정이 섞여 있습니다(approved: false, profile_source auto). 평가에 쓰지 마세요.")
        lines.append("")
    lines += [f"- 프로젝트: {c.project}", f"- 스키마 버전: {SCHEMA_VERSION}",
              f"- 문서 우선순위(앞이 우선, · 는 같은 순위): {tiers}",
              f"- 항목 {len(result.items)} · 연결 {len(result.links)} · 경고 {len(result.warnings)} · 청크 {len(result.chunks)}",
              f"- 설정 검사 경고: {result.config_warnings}"]
    return lines


def _warnings(result, lists):
    counts = _warning_counts(result)
    if not counts:
        return ["없음"]
    return _table(lists, 2, None, _head("무엇(종류) | 구분 | 수"),
                  [_row(f"{WARNING_MEANING.get(k, k)}({k})", CATEGORY.get(k, "-"), n) for k, n in counts.items()])


def _sheets(result, lists):
    by_id = {i.item_id: i for i in result.items}
    key = lambda i: (i.doc_type, i.doc_file, i.locations[0].sheet)   # noqa: E731
    link_count = Counter(key(by_id[x]) for l in result.links for x in {l.item_a, l.item_b, l.item} - {None})
    item_count = Counter(key(i) for i in result.items)
    rows = []
    for doc_type, file, sheet, status, reason, overview, new in result.sheet_rows:
        key = (doc_type, file, sheet)
        rows.append(_row(doc_type, file, sheet, status, reason, "예" if overview else "",
                         item_count.get(key, 0), link_count.get(key, 0), "새 시트, 확인 필요" if new else ""))
    lines = _table(lists, 3, None, _head("문서 | 파일 | 시트 | 읽음·뺌 | 이유 | 요약 시트(overview) | 항목 수 | 연결 수 | 확인"),
                   rows)
    if result.table_counts:   # 한 시트 여러 표: tables 설정 시트만(설정이 없으면 출력 그대로)
        lines.append("")
        lines += [f"- {doc_type} {file} 「{sheet}」: 표 {found}개" + ("" if untitled is None else f"(제목 없는 표 {untitled}개)")
                  + f", 건너뛴 표 {skipped}개(tables 설정 — 건너뛴 표는 2절 header_not_found)"
                  for doc_type, file, sheet, found, skipped, untitled in result.table_counts]
    return lines


def _rule_stats(blocks) -> list:
    """규칙마다 (규칙 id, 못 찾은 수, 용어집 초안 후보 수) — 4절 줄과 0절 할 일이 같은 계산(_rule_blocks)을 쓴다"""
    return [(rule.id, len(block["missing"]), block["cands"]) for rule, block in blocks if block]


def _rule_blocks(result) -> list:
    """규칙마다 (규칙, 계산 결과 dict 또는 None). None = 지원하지 않아 건너뜀·path 규칙에 합쳐 셈"""
    config, index = result.config, result.index
    cand_count = Counter(c.rule_id for c in glossary_candidates.candidates(config, index, result.made_by_rule))
    folded = _folded_glossary(config)
    out = []
    for rule in config.link_rules:
        if rule.id not in result.made_by_rule or rule.id in folded:
            out.append((rule, None))
            continue
        made = result.made_by_rule[rule.id]
        if rule.key == "id_ref":
            sides, missing = _id_ref_sides(rule, result, made)
            out.append((rule, {"sides": sides, "missing": missing, "cands": 0, "made": made, "fix": FIX_ID_REF}))
            continue
        resolved = link.glossary_linked_for(rule, result.glossary_made) if rule.key in GLOSSARY_RESOLVED_KEYS else {}
        group = link.group_side(rule, index)
        unmatched = link.unmatched(rule, index, made)   # 실행 화면과 같은 기준
        slots = rule.sheets or [None, None]
        sides, missing_all = [], []
        for k, (doc_type, slot) in enumerate(zip(rule.docs, slots)):
            label = f"{doc_type} 쪽" + (f"({slot if not isinstance(slot, list) else ', '.join(slot)})"
                                        if rule.docs[0] == rule.docs[1] else "")
            if k == group:
                sides.append(f"- {label}: 묶음 단위라 해당 없음")
                continue
            scope = index.side(doc_type, slot)
            usable = [d for d in scope if link.has_path_key(d)]
            by_glossary = [d for d in unmatched[k] if id(d) in resolved]
            missing = [d for d in unmatched[k] if id(d) not in resolved]
            sides.append(f"- {label}: 항목 {len(scope)} · 연결된 {len(usable) - len(missing)} · 못 찾은 {len(missing)}"
                         f" · 용어집으로 풀림 {len(by_glossary)} · 추정 경로·경로 없음 제외 {len(scope) - len(usable)}")
            missing_all += [(label, d) for d in missing]
        n = cand_count.get(rule.id, 0)
        out.append((rule, {"sides": sides, "missing": missing_all, "cands": n, "made": made,
                           "fix": FIX_GLOSSARY if n else FIX_RULE}))
    return out


def _rules(result, lists, blocks):
    folded = _folded_glossary(result.config)
    lines = []
    for rule, block in blocks:
        lines.append(f"### {rule.id}")
        lines.append("")
        lines.append(f"- 방식: {KEY_MEANING.get(rule.key, rule.key)}({rule.key}), 문서: {rule.docs[0]} ↔ {rule.docs[1]}")
        if rule.id not in result.made_by_rule:
            lines += ["- 지원하지 않아 건너뜀(경고 unsupported)", ""]
            continue
        if block is None:
            lines += [f"- 같은 두 쪽 경로 규칙 {folded[rule.id]}에 합쳐 셈(path, 용어집으로 풀린 항목)", ""]
            continue
        lines += block["sides"]
        if rule.key != "id_ref":
            lines.append(f"- 용어집 초안 후보 {block['cands']}개")
        if block["missing"]:
            lines.append(f"- 고칠 곳: {block['fix']}")
            rows = [_row(label, result.ids.get(id(d), "-"), d.sheet, f"{d.rows[0]}행", d.category_path_text)
                    for label, d in sorted(block["missing"], key=lambda x: (x[0], result.ids.get(id(x[1]), "")))]
            lines += [""] + _table(lists, 4, rule.id, _head("쪽 | 항목 | 시트 | 행 | 경로"), rows) + [""]
        lines += [_links_per_item(block["made"]), ""]
    return lines


def _links_per_item(made):
    """규칙 하나의 「항목당 연결 수 최대·평균」(연결된 항목 기준). 항목↔항목은 양쪽, 항목↔묶음은 항목 쪽만 센다"""
    per = Counter(id(x) for d in made for x in ((d.a, d.b) if hasattr(d, "a") else (d.item,)))
    if not per:
        return "- 항목당 연결 수: 연결 없음"
    return (f"- 항목당 연결 수: 최대 {max(per.values())} · 평균 {sum(per.values()) / len(per):.2f} "
            f"(연결 {len(made)}개, 연결된 항목 {len(per)}개)")


def _id_ref_sides(rule, result, made):
    """id_ref 규칙(경로를 쓰지 않음): (쪽별 줄, 대상 쪽 못 찾은 [(쪽, 항목)]). 찾는 쪽은 참조 ID 없는 항목·못 찾은 항목 수
    (경고 ref_unresolved), 대상 쪽은 어느 참조에도 안 걸린 항목 목록(요구사항 규칙: 연결 안 된 요구사항을 드러냄)"""
    index = result.index
    seeker = link.id_ref_seeker(rule, index)
    unmatched = link.unmatched(rule, index, made)   # 실행 화면과 같은 기준
    lines, missing_all = [], []
    for k, (doc_type, slot) in enumerate(zip(rule.docs, rule.sheets or [None, None])):
        scope = index.side(doc_type, slot)
        free = unmatched[k]
        head = f"- {doc_type} 쪽: 항목 {len(scope)} · 연결된 {len(scope) - len(free)}"
        if k == seeker:
            lines.append(f"{head} · 참조 ID 없는 항목 {sum(1 for d in scope if not d.ref_ids)}"
                         f" · 참조 ID를 못 찾은 항목 {sum(1 for d in free if d.ref_ids)}(경고 ref_unresolved)")
            # B2: 숫자 조각 남은 참조 칸 = 펼치지 않은(끔) 또는 펼치지 못한 줄임 조각이 있는 칸(columns.ref_ids.expand_short 판단 근거)
            short = f"- {doc_type} 쪽 참조 칸: 숫자 조각 남은 참조 칸 {sum(1 for d in scope if d.short_left)}"
            expanded = [e[0] for d in scope for e in d.expanded_refs]
            if expanded:
                ids = link.id_targets(rule, index, k)
                short += f" · 펼친 ID {len(expanded)}(못 찾음 {sum(1 for e in expanded if id_key(e) not in ids)})"
            lines.append(short)
        else:
            lines.append(f"{head} · 못 찾은 {len(free)}")
            missing_all += [(f"{doc_type} 쪽", d) for d in free]
    return lines, missing_all


def _unlinked(result, lists):
    ruled = {t for r in result.config.link_rules for t in r.docs}
    linked = {x for l in result.links for x in (l.item_a, l.item_b, l.item) if x}
    lines = []
    counts = Counter(i.doc_type for i in result.items if i.doc_type not in ruled)
    for t, n in counts.items():
        lines.append(f"- 연결 규칙 없는 문서 종류: {t} (항목 {n}개)")
    rows = [i for i in result.items if i.doc_type in ruled and i.item_id not in linked]
    lines.append(f"- 연결 규칙이 있는 문서의 어느 연결에도 없는 항목: {len(rows)}")
    if rows:
        lines += [""] + _table(lists, 5, None, _head("항목 | 문서 | 시트 | 행 | 경로"),
                               [_row(i.item_id, i.doc_type, i.locations[0].sheet, f"{i.locations[0].rows.start}행",
                                     i.category_path_text) for i in rows])
    return lines


def _inferred(result, lists):
    rows = [d for d in _ordered(result) if has_inferred_step(d.category_path)]
    if not rows:
        return ["없음"]
    out = []
    for d in rows:
        steps = ", ".join(f"{p.level}단계 {BASIS_MEANING.get(p.basis, p.basis)}({p.basis})"
                          for p in d.category_path if p.basis in INFERRED_BASES)
        out.append(_row(result.ids.get(id(d), "-"), d.doc_type, d.sheet, f"{d.rows[0]}행", steps, d.category_path_text))
    return [f"- 추정 경로 항목: {len(rows)}", ""] + _table(lists, 6, None, _head("항목 | 문서 | 시트 | 행 | 추정 단계 | 경로"), out)


def _empty_body(result, lists):
    if not result.empty_body:
        return ["없음"]
    return [f"- 본문이 빈 항목: {len(result.empty_body)}", ""] + _table(
        lists, 7, None, _head("문서 | 파일 | 시트 | 행"), [_row(t, f, s, f"{r}행") for t, f, s, r in result.empty_body])


def _same_path_groups(result):
    """(경로·제목이 모두 같은 묶음 목록, 경로만 같고 제목이 다른 묶음 수)"""
    groups = {}
    for d in _ordered(result):
        if d.category_path_text:
            groups.setdefault((d.doc_type, d.doc_file, d.sheet, d.category_path_text), []).append(d)
    listed, other = [], 0
    for (doc_type, file, sheet, path), ds in groups.items():
        if len(ds) < 2:
            continue
        by_title = {}
        for d in ds:
            by_title.setdefault(d.title or "", []).append(d)
        same = [g for g in by_title.values() if len(g) > 1]
        for g in same:
            listed.append((doc_type, file, sheet, ", ".join(str(d.rows[0]) for d in sorted(g, key=lambda d: d.rows)),
                           g[0].title or "", path))
        if len(by_title) > 1:
            other += 1
    return listed, other


def _same_path(result, lists):
    listed, other = _same_path_groups(result)
    lines = [f"- 경로·제목(title)이 모두 같은 묶음: {len(listed)}", f"- 경로만 같고 제목(title)이 다른 묶음: {other}"]
    if listed:
        lines += [""] + _table(lists, 8, None, _head("문서 | 파일 | 시트 | 행 | 제목(title) | 경로"), [_row(*x) for x in listed])
    return lines


def _version(result, lists):
    if not result.version_missing:
        return ["없음"]
    return _table(lists, 9, None, _head("파일 | 못 찾은 곳"), [_row(f, "·".join(m)) for f, m in result.version_missing])


def _roles(result, lists):
    if not result.roles_missing:
        return ["없음"]
    return _table(lists, 10, None, _head("문서 | 파일 | 시트 | 역할"), [_row(*r) for r in result.roles_missing])


def _glossary(result, lists):
    c = result.config
    if not (c.glossary and c.glossary_data):
        return ["용어집 없음"]
    sides = []   # (규칙 id, 쪽 이름, 해결된 수, 줄별 숫자에 포함)
    for rule in c.link_rules:
        if rule.key in GLOSSARY_RESOLVED_KEYS and rule.id in result.made_by_rule:
            resolved = link.glossary_linked_for(rule, result.glossary_made)
            unmatched = link.unmatched(rule, result.index, result.made_by_rule[rule.id])
            slots = rule.sheets or [None, None]
            group = link.group_side(rule, result.index)
            for k, (t, s) in enumerate(zip(rule.docs, slots)):
                if k == group:
                    continue   # 묶음 쪽은 짝 없음을 세지 않음(4절 「묶음 단위라 해당 없음」)
                n = sum(1 for d in unmatched[k] if id(d) in resolved)
                label = f"{t} 쪽" + (f"({s if not isinstance(s, list) else ', '.join(s)})" if rule.docs[0] == rule.docs[1] else "")
                sides.append((rule.id, label, n, "예" if s == "overview" else "아니오"))
    total = sum(n for _, _, n, _ in sides)
    lines = [f"- 용어집으로 해결된 항목: {total}",
             f"- 승인: {'예' if c.glossary_data.approved else '아니오(검토 전)'}", "",
             f"- {GLOSSARY_TOTAL_NOTE}", ""]
    lines += _table(lists, 11, "규칙·쪽별", _head("규칙 | 문서 | 해결된 항목 | 줄별 숫자에 포함"), [_row(*x) for x in sides])
    lines += ["", f"- {GLOSSARY_LINE_NOTE}", ""]
    rows = [_row(line, f"groups[{g}]", ", ".join(c.glossary_data.groups[g]), n, r, m)
            for line, g, n, r, m in result.glossary_effects]
    lines += _table(lists, 11, "줄별", _head("줄 | 묶음 | 단어 | 연결 | 풀린 짝 없음(요약 쪽) | 새 내용 차이"), rows)
    return lines


STRUCTURE_COLUMNS = [
    ("문서", "문서 종류"),
    ("파일", "엑셀 파일 이름"),
    ("시트", "시트 이름. 한 시트에 표가 여러 개면 「시트 [표 제목 n행]」처럼 표마다 한 줄"),
    ("머리글 줄", "그 시트(표)의 머리글 행 수"),
    ("항목", "그 시트(표)에서 만든 항목 수. 아래 칸 수는 항목 행의 분류 칸만 셈"),
    ("분류 열", "분류 단계로 읽은 열 수"),
    ("병합 칸", "병합으로 값을 복원한 분류 칸 수. 병합 시작 칸은 세지 않음"),
    ("병합 없는 빈칸", "병합이 아닌 빈 분류 칸 전부"),
    ("앞쪽 빈칸", "위 값 채우기가 위 값으로 채우는 병합 없는 빈칸(fill_down). 끔 시트는 켰다면 채울 칸. "
               "그 행에서 처음 원문 값이 나온 단계보다 위이고, 위 항목의 같은 단계에 값이 있는 칸"),
    ("앞쪽 빈칸 행", "앞쪽 빈칸이 있는 행 수. 분류 칸이 전부 빈 행은 넣지 않음"),
    ("테두리 묶음 안 빈칸", "데이터 행 사이에 가로 선(셀 테두리)이 있는 분류 열에서, 앞쪽 빈칸 중 위 항목과 사이에 선이 없는 칸. "
                     "많으면 테두리 묶음 안만 채우기를 검토(hierarchy.border_groups)"),
    ("분류 칸 전부 빈 행", "분류 칸이 모두 비어 위 경로를 그대로 받는 행 수. 선언해도 추정이라 앞쪽 빈칸 행과 따로 셈. "
                    "앞쪽 빈칸 행 + 이 수 = 위 값으로 채우는 항목 수"),
    ("앞쪽 빈칸 행 비율", "앞쪽 빈칸 행 ÷ 항목"),
    ("위 값 채우기", "켬·끔(hierarchy.fill_down)"),
    ("확인", f"「검토」 = 앞쪽 빈칸 행 비율이 {BLANK_ROW_REVIEW_RATIO} 이상이고 빈칸 뜻을 선언하지 않은 시트. "
           "「선언됨」 = 빈칸이 「위와 같음」이라고 선언한 시트(hierarchy.blank_means_above: true, fill_down: true와 함께, "
           "시트별은 sheet_overrides). 「검토」 시트가 「위와 같음」이면 이 선언을 넣음"),
]


def _structure(result, lists):
    """C4 순서: ① 요약 한 줄(문서별) ② 할 일 ③ 표 ④ 열 설명. 설정 이름은 ④ 괄호 안에만. 표는 줄이지 않는다"""
    rows = result.structure
    if not rows:
        return ["분류 열 방식 시트 없음(columns)"]
    per_doc = {}
    for r in rows:
        s = per_doc.setdefault(r[0], [0, 0, 0])
        mark = _structure_mark(r)
        s[0] += mark == "검토"
        s[1] += mark == "선언됨"
        s[2] += r[6].blank_all
    lines = ["- 요약: " + " / ".join(f"{doc} 검토 {a} · 선언됨 {b} · 병합 없는 빈칸 {c}" for doc, (a, b, c) in per_doc.items())]
    review = sum(s[0] for s in per_doc.values())
    lines.append(f"- 할 일: {STRUCTURE_TODO}(검토 시트 {review}개)" if review else "- 할 일 없음")
    lines += [""] + _head(" | ".join(name for name, _ in STRUCTURE_COLUMNS))
    for r in rows:
        doc_type, file, sheet, header, items, ncols, b, fill, declared = r
        ratio = b.front_rows / items if items else 0.0
        lines.append(_row(doc_type, file, sheet, header, items, ncols, b.merged, b.blank_all, b.blank_front, b.front_rows,
                          b.border_inner, b.all_blank_rows, f"{ratio:.2f}", "켬" if fill else "끔", _structure_mark(r)))
    lines += ["", "열 설명:", ""] + _head("열 | 뜻") + [_row(name, meaning) for name, meaning in STRUCTURE_COLUMNS]
    return lines


def _terms():
    return ["## 용어 설명", "", TERMS_EASY, ""] + _head("용어 | 뜻") + [_row(t, m) for t, m in TERMS] + [""]


def _list_file(result, lists) -> str:
    parts = [f"# 처리 보고서 목록 — {result.config.project}", "",
             f"{REPORT_FILE}의 항목 목록({'·'.join(map(str, ITEM_LIST_SECTIONS))}절)과 {REPORT_FILE}에서 줄인 표의 전체입니다. 절 번호는 {REPORT_FILE}와 같습니다.", ""]
    if not lists:
        parts += ["줄인 목록이 없습니다.", ""]
    for n in sorted(lists):
        parts += [f"## {n}. {SECTIONS[n - 1][0]}", ""]
        for sub, table in lists[n]:
            if sub:
                parts += [f"### {sub}", ""]
            parts += table + [""]
    return "\n".join(parts).rstrip("\n") + "\n"


def render_all(result) -> dict:
    """{report.md: 글자, report_목록.md: 글자} (LF, 끝 줄바꿈 하나). 같은 입력이면 바이트까지 같다"""
    lists = defaultdict(list)   # report_목록.md에 쓸 전체 목록: 절 번호 → [(소제목 또는 None, 표 줄들)] (넣은 순서)
    blocks = _rule_blocks(result)
    parts = [f"# 처리 보고서 — {result.config.project}", ""]
    parts += _first(result, _rule_stats(blocks))
    rules = lambda r, l: _rules(r, l, blocks)   # noqa: E731
    for n, make in enumerate((_summary, _warnings, _sheets, rules, _unlinked, _inferred, _empty_body, _same_path,
                              _version, _roles, _glossary, _structure), start=1):
        parts += _section(n, make(result, lists))
    parts += _terms()
    return {REPORT_FILE: "\n".join(parts).rstrip("\n") + "\n", LIST_FILE: _list_file(result, lists)}


def render(result) -> str:
    """report.md 글자"""
    return render_all(result)[REPORT_FILE]
