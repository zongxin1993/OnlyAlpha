from __future__ import annotations

from dataclasses import dataclass

import pytest

from onlyalpha.kernel import OnlyAlphaKernelHost, OnlyKernelState
from onlyalpha.kernel.query import (
    OnlyDuplicateProductQueryBinding,
    OnlyProductQuery,
    OnlyProductQueryBinding,
    OnlyProductQueryDispatcher,
    OnlyUnsupportedProductQuery,
)


@dataclass(frozen=True, slots=True)
class _QueryA(OnlyProductQuery):
    value: str


@dataclass(frozen=True, slots=True)
class _QueryB(OnlyProductQuery):
    value: str


class _QueryASubclass(_QueryA):
    pass


def test_exact_query_resolution_is_order_independent_and_read_only() -> None:
    bindings = (
        OnlyProductQueryBinding(_QueryA, lambda query: f"a:{query.value}"),
        OnlyProductQueryBinding(_QueryB, lambda query: f"b:{query.value}"),
    )
    first = OnlyProductQueryDispatcher(bindings)
    second = OnlyProductQueryDispatcher(tuple(reversed(bindings)))
    kernel = OnlyAlphaKernelHost()

    assert first.dispatch(_QueryA("same")) == second.dispatch(_QueryA("same")) == "a:same"
    assert kernel.state is OnlyKernelState.CREATED
    assert set(vars(first)) == {"_handlers"}


def test_unknown_and_unregistered_subclass_fail_closed() -> None:
    calls: list[_QueryA] = []
    dispatcher = OnlyProductQueryDispatcher((OnlyProductQueryBinding(_QueryA, lambda query: calls.append(query)),))

    with pytest.raises(OnlyUnsupportedProductQuery):
        dispatcher.dispatch(_QueryB("unknown"))
    with pytest.raises(OnlyUnsupportedProductQuery):
        dispatcher.dispatch(_QueryASubclass("subclass"))
    assert calls == []


def test_duplicate_query_binding_fails_at_construction() -> None:
    binding = OnlyProductQueryBinding(_QueryA, lambda query: query)
    with pytest.raises(OnlyDuplicateProductQueryBinding):
        OnlyProductQueryDispatcher((binding, binding))


def test_query_binding_topology_has_no_runtime_mutation_api() -> None:
    dispatcher = OnlyProductQueryDispatcher(())
    assert not hasattr(dispatcher, "register")
    assert not hasattr(dispatcher, "unregister")
    assert not hasattr(dispatcher, "replace_handler")
