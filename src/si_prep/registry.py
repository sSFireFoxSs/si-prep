"""이름 → 함수 등록표. hierarchy·boundary·link가 같은 클래스를 쓴다.

- 알려진 이름(known): 설정에서 고를 수 있는 이름. config.py의 옵션 모델에서 받는다.
- 구현된 이름: register로 함수를 붙인 이름.
get은 구현됨 → 함수, 알려졌지만 미구현 → Unimplemented(run이 건너뛰고 unsupported 경고), 모르는 이름 → UnknownName.
"""

from collections.abc import Callable, Iterable


class UnknownName(Exception):
    """설정이 고를 수 없는 이름(오타 등). 설정 검사에서 이미 막혀야 하므로 여기 오면 코드 오류"""

    def __init__(self, kind, name):
        super().__init__(f"{kind}: 알 수 없는 이름 {name!r}")
        self.kind, self.name = kind, name


class Unimplemented(Exception):
    """알려졌지만 아직 함수가 없는 이름"""

    def __init__(self, kind, name):
        super().__init__(f"{kind}: {name} 방식은 아직 지원하지 않습니다")
        self.kind, self.name = kind, name


class Registry:
    def __init__(self, kind: str, known: Iterable[str]):
        self.kind = kind
        self._known = frozenset(known)
        self._funcs: dict[str, Callable] = {}

    def register(self, name: str):
        """@REGISTRY.register("columns") — 함수를 그대로 돌려준다"""
        if name not in self._known:
            raise UnknownName(self.kind, name)

        def deco(func):
            if name in self._funcs:
                raise ValueError(f"{self.kind}: {name!r}을 두 번 등록했습니다")
            self._funcs[name] = func
            return func
        return deco

    def get(self, name: str) -> Callable:
        if name in self._funcs:
            return self._funcs[name]
        if name in self._known:
            raise Unimplemented(self.kind, name)
        raise UnknownName(self.kind, name)

    def implemented(self) -> list[str]:
        return sorted(self._funcs)

    def unimplemented(self) -> list[str]:
        return sorted(self._known - self._funcs.keys())
