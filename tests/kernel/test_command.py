from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Thread

import pytest

from onlyalpha.kernel import OnlyAlphaKernelHost, OnlyKernelHostError, OnlyKernelLifecycleStep
from onlyalpha.kernel.command import (
    OnlyDuplicateProductCommandBinding,
    OnlyProductCommand,
    OnlyProductCommandBinding,
    OnlyProductCommandDispatcher,
    OnlyUnsupportedProductCommand,
)
from onlyalpha.kernel.lifecycle import OnlyKernelMutationRejected


@dataclass(frozen=True, slots=True)
class _CommandA(OnlyProductCommand):
    value: str


@dataclass(frozen=True, slots=True)
class _CommandB(OnlyProductCommand):
    value: str


class _CommandASubclass(_CommandA):
    pass


def _ready_host() -> OnlyAlphaKernelHost:
    host = OnlyAlphaKernelHost()
    host.start()
    return host


def test_ready_invokes_exact_handler_once_and_returns_outcome() -> None:
    calls: list[_CommandA] = []
    dispatcher = OnlyProductCommandDispatcher(
        _ready_host(),
        (OnlyProductCommandBinding(_CommandA, lambda command: calls.append(command) or command.value),),
    )

    assert dispatcher.dispatch(_CommandA("outcome")) == "outcome"
    assert calls == [_CommandA("outcome")]


def test_non_ready_states_reject_before_handler_invocation() -> None:
    calls: list[OnlyProductCommand] = []

    def binding(host: OnlyAlphaKernelHost) -> OnlyProductCommandDispatcher:
        return OnlyProductCommandDispatcher(
            host,
            (OnlyProductCommandBinding(_CommandA, lambda command: calls.append(command)),),
        )

    created = OnlyAlphaKernelHost()
    with pytest.raises(OnlyKernelMutationRejected):
        binding(created).dispatch(_CommandA("created"))

    draining_dispatch: OnlyProductCommandDispatcher | None = None

    def drain() -> None:
        assert draining_dispatch is not None
        with pytest.raises(OnlyKernelMutationRejected):
            draining_dispatch.dispatch(_CommandA("draining"))

    draining = OnlyAlphaKernelHost(drainers=(OnlyKernelLifecycleStep("probe", drain),))
    draining.start()
    draining_dispatch = binding(draining)
    draining.stop()
    with pytest.raises(OnlyKernelMutationRejected):
        draining_dispatch.dispatch(_CommandA("stopped"))

    failed = OnlyAlphaKernelHost(
        verifiers=(OnlyKernelLifecycleStep("fail", lambda: (_ for _ in ()).throw(RuntimeError("fail"))),)
    )
    with pytest.raises(OnlyKernelHostError):
        failed.start()
    with pytest.raises(OnlyKernelMutationRejected):
        binding(failed).dispatch(_CommandA("failed"))

    assert calls == []


def test_recovering_rejects_mutation_with_zero_handler_side_effect() -> None:
    entered = Event()
    release = Event()
    calls: list[_CommandA] = []

    def recover() -> None:
        entered.set()
        assert release.wait(timeout=10)

    host = OnlyAlphaKernelHost(recoverers=(OnlyKernelLifecycleStep("barrier", recover),))
    dispatcher = OnlyProductCommandDispatcher(
        host,
        (OnlyProductCommandBinding(_CommandA, lambda command: calls.append(command)),),
    )
    thread = Thread(target=host.start)
    thread.start()
    assert entered.wait(timeout=10)
    with pytest.raises(OnlyKernelMutationRejected):
        dispatcher.dispatch(_CommandA("recovering"))
    assert calls == []
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()


def test_unknown_and_unregistered_subclass_fail_closed_without_fallback() -> None:
    base_calls: list[_CommandA] = []
    dispatcher = OnlyProductCommandDispatcher(
        _ready_host(),
        (OnlyProductCommandBinding(_CommandA, lambda command: base_calls.append(command)),),
    )

    with pytest.raises(OnlyUnsupportedProductCommand):
        dispatcher.dispatch(_CommandB("unknown"))
    with pytest.raises(OnlyUnsupportedProductCommand):
        dispatcher.dispatch(_CommandASubclass("subclass"))
    assert base_calls == []


def test_duplicate_binding_fails_at_construction() -> None:
    binding = OnlyProductCommandBinding(_CommandA, lambda command: command)
    with pytest.raises(OnlyDuplicateProductCommandBinding):
        OnlyProductCommandDispatcher(_ready_host(), (binding, binding))


def test_binding_permutation_preserves_resolution_and_handler_failure_propagates() -> None:
    def fail(_command: _CommandB) -> object:
        raise LookupError("domain failure")

    bindings = (
        OnlyProductCommandBinding(_CommandA, lambda command: f"a:{command.value}"),
        OnlyProductCommandBinding(_CommandB, fail),
    )
    first = OnlyProductCommandDispatcher(_ready_host(), bindings)
    second = OnlyProductCommandDispatcher(_ready_host(), tuple(reversed(bindings)))

    assert first.dispatch(_CommandA("same")) == second.dispatch(_CommandA("same")) == "a:same"
    with pytest.raises(LookupError, match="domain failure"):
        first.dispatch(_CommandB("fail"))


def test_binding_topology_has_no_runtime_mutation_api() -> None:
    dispatcher = OnlyProductCommandDispatcher(_ready_host(), ())
    assert not hasattr(dispatcher, "register")
    assert not hasattr(dispatcher, "unregister")
    assert not hasattr(dispatcher, "replace_handler")
