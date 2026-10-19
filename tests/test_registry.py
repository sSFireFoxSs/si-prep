"""이름 → 함수 등록표. 알려진 이름(config)과 구현된 이름(등록)을 나눈다."""

import pytest

from si_prep.registry import Registry, Unimplemented, UnknownName


def _reg():
    return Registry("hierarchy", known=["columns", "split_cell", "indent"])


def test_register_and_get():
    reg = _reg()

    @reg.register("columns")
    def by_columns():
        return "columns"

    assert reg.get("columns") is by_columns
    assert by_columns() == "columns"   # 데코레이터가 함수를 그대로 돌려줌


def test_known_but_not_registered_is_unimplemented():
    reg = _reg()
    reg.register("columns")(lambda: None)
    with pytest.raises(Unimplemented) as e:
        reg.get("indent")
    assert e.value.name == "indent" and e.value.kind == "hierarchy"
    assert reg.unimplemented() == ["indent", "split_cell"]
    assert reg.implemented() == ["columns"]


def test_unknown_name_is_error_not_unimplemented():
    reg = _reg()
    with pytest.raises(UnknownName):
        reg.get("colums")
    with pytest.raises(UnknownName):  # Unimplemented와 다른 종류여야 run이 구분할 수 있다
        reg.get("colums")
    assert not issubclass(UnknownName, Unimplemented) and not issubclass(Unimplemented, UnknownName)
    assert not issubclass(UnknownName, LookupError)   # except LookupError로 미구현만 받으려다 오타까지 삼키지 않게


def test_register_same_name_twice_is_error():
    reg = _reg()
    reg.register("columns")(lambda: 1)
    with pytest.raises(ValueError, match="두 번"):
        reg.register("columns")(lambda: 2)


def test_register_unknown_name_is_error():
    # 설정에 없는 이름으로 함수를 만들면 설정에서 고를 수 없으므로 막는다(오타 방지)
    with pytest.raises(UnknownName):
        _reg().register("colums")


def test_registries_are_separate():
    a, b = _reg(), Registry("boundary", known=["row"])
    a.register("columns")(lambda: None)
    with pytest.raises(UnknownName):
        b.get("columns")
