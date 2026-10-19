"""경고 초안 수집기. 모든 단계가 issues.add(...)로 쌓고, 경고를 버리지 않는다.

검증 규칙(kind 보기 목록, 빈 메시지, 위치 없으면 file 필수 등)은 schema.Warning_ 하나에만 있다.
add는 그 모델로 한 번 만들어 보고 통과한 것만 쌓는다. 번호(WN-…)는 여기서 붙이지 않는다:
run이 모두 모아 정렬한 뒤 Issue.to_warning(번호)로 붙인다.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import ValidationError

from si_prep.schema import Location, Warning_

_PLACEHOLDER_ID = "WN-000000"   # 검증용 자리 번호(밖으로 나가지 않음)


@dataclass(frozen=True)
class Issue:
    kind: str
    message: str
    locations: tuple[Location, ...] = ()
    item_ids: tuple[str, ...] = ()
    file: str | None = None
    sheet: str | None = None
    limit: str | None = None   # 처리 보고서 0절 「알려진 한계」 표시(above_header·headerless). 출력 칸 아님

    def to_warning(self, warning_id: str) -> Warning_:
        return Warning_(warning_id=warning_id, kind=self.kind, message=self.message, item_ids=list(self.item_ids),
                        locations=list(self.locations), file=self.file, sheet=self.sheet)


class Issues:
    def __init__(self):
        self.items: list[Issue] = []

    def add(self, kind: str, message: str, locations: Iterable[Location] = (), *, item_ids: Iterable[str] = (),
            file: str | None = None, sheet: str | None = None, limit: str | None = None) -> Issue:
        issue = Issue(kind, message, tuple(locations), tuple(item_ids), file, sheet, limit)
        try:
            issue.to_warning(_PLACEHOLDER_ID)
        except ValidationError as e:
            fields = ", ".join(".".join(str(p) for p in err["loc"]) or "(전체)" for err in e.errors())
            raise ValueError(f"경고 초안이 스키마에 맞지 않습니다({fields}): {e}") from None
        self.items.append(issue)
        return issue

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def by_kind(self, kind: str) -> list[Issue]:
        return [i for i in self.items if i.kind == kind]
