"""경로 글자·비교 열쇠·시트 이름 쪼개기. 순수 함수만. 원문은 고치지 않는다.

보여주기용 글자와 단계 열쇠 규칙은 schema.py(rag_core와 같이 씀)에 있고, 여기서는 그것을 그대로 쓴다.
"""

import re
from collections.abc import Sequence

from si_prep import schema


def path_text(steps: Sequence[str | None]) -> str:
    """단계 값 목록 → " › "로 이은 글자. 빈 단계(None)는 (빈칸), 같은 값이 이어지면 한 번.
    단계 값은 None이나 빈 글자가 아닌 str이어야 한다(PathPart 규칙, 부르는 쪽이 지킴)"""
    parts = [schema.PathPart(level=i, value=s, basis="empty" if s is None else "cell")
             for i, s in enumerate(steps, start=1)]
    return schema.path_text(parts)


def compare_key(steps: Sequence[str | None]) -> tuple[str, ...] | None:
    """경로 비교 열쇠(단계별 공백 제거·소문자, 이어지는 같은 단계 한 번). 빈 단계가 있거나 단계가 없으면 None
    — 그런 경로는 경로 연결의 열쇠로 쓰지 않는다. 공백만 있는 단계(열쇠가 "")도 빈 단계로 본다"""
    if not steps or any(s is None or not schema.step_key(s) for s in steps):
        return None
    return schema.path_key(steps)


def split_sheet_name(name: str, separators: Sequence[str]) -> list[str | None]:
    """시트 이름을 구분 기호들로 쪼갠다. 긴 구분 기호부터 맞춘다. 조각 글자는 원문 그대로, 빈 조각은 None"""
    if not separators:
        return [name]
    pattern = "|".join(re.escape(s) for s in sorted(set(separators), key=lambda s: (-len(s), s)))
    return [piece if piece else None for piece in re.split(pattern, name)]


_BRACKETED = re.compile(r"\([^()]*\)|（[^（）]*）|\[[^\[\]]*\]")


def loose_key(step: str) -> str:
    """용어집 후보용 느슨한 열쇠: 괄호 부분((…)·（…）·[…])을 빼고 글자·숫자만 남긴 소문자.
    후보(사람 승인)에만 쓰고 연결 확정에는 쓰지 않는다"""
    return re.sub(r"[\W_]+", "", _BRACKETED.sub("", step)).lower()


def id_key(value: str) -> str:
    """ID 비교 열쇠: 앞뒤 공백만 뺀다. 대소문자는 구분한다. 자기 ID 중복·id_pattern·id_ref가 같이 쓴다"""
    return value.strip()
