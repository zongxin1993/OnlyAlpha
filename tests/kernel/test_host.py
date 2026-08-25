from __future__ import annotations

from collections.abc import Callable

import pytest

from onlyalpha.kernel import (
    OnlyAlphaKernelHost,
    OnlyKernelFailurePhase,
    OnlyKernelHostError,
    OnlyKernelLifecycleError,
    OnlyKernelLifecycleStep,
    OnlyKernelMutationRejected,
    OnlyKernelState,
)


def _step(name: str, action: Callable[[], None]) -> OnlyKernelLifecycleStep:
    return OnlyKernelLifecycleStep(name, action)


def test_successful_startup_uses_exact_explicit_order() -> None:
    calls: list[tuple[str, OnlyKernelState]] = []
    host: OnlyAlphaKernelHost
    host = OnlyAlphaKernelHost(
        booters=(_step("compose", lambda: calls.append(("compose", host.state))),),
        verifiers=(
            _step("configuration", lambda: calls.append(("configuration", host.state))),
            _step("schema", lambda: calls.append(("schema", host.state))),
        ),
        recoverers=(
            _step("durable-lifecycle", lambda: calls.append(("durable-lifecycle", host.state))),
            _step("reconciliation", lambda: calls.append(("reconciliation", host.state))),
        ),
    )

    status = host.start()

    assert calls == [
        ("compose", OnlyKernelState.BOOTING),
        ("configuration", OnlyKernelState.VERIFYING),
        ("schema", OnlyKernelState.VERIFYING),
        ("durable-lifecycle", OnlyKernelState.RECOVERING),
        ("reconciliation", OnlyKernelState.RECOVERING),
    ]
    assert status.state is OnlyKernelState.READY
    host.assert_mutation_ready()


def test_verification_failure_is_explainable_and_skips_recovery() -> None:
    calls: list[str] = []

    def incompatible() -> None:
        calls.append("schema")
        raise ValueError("secret details are not lifecycle evidence")

    host = OnlyAlphaKernelHost(
        verifiers=(_step("schema", incompatible),),
        recoverers=(_step("recovery", lambda: calls.append("recovery")),),
    )

    with pytest.raises(OnlyKernelHostError) as captured:
        host.start()

    assert calls == ["schema"]
    assert host.state is OnlyKernelState.FAILED
    assert captured.value.failure.phase is OnlyKernelFailurePhase.VERIFYING
    assert captured.value.failure.step == "schema"
    assert captured.value.failure.reason == "ValueError"
    assert "secret details" not in str(captured.value)
    with pytest.raises(OnlyKernelMutationRejected):
        host.assert_mutation_ready()


def test_recovery_failure_is_fail_closed() -> None:
    calls: list[str] = []

    def recovery_failure() -> None:
        calls.append("recover")
        raise LookupError("corrupt durable authority")

    host = OnlyAlphaKernelHost(
        verifiers=(_step("verify", lambda: calls.append("verify")),),
        recoverers=(_step("unfinished-runs", recovery_failure),),
    )

    with pytest.raises(OnlyKernelHostError) as captured:
        host.start()

    assert calls == ["verify", "recover"]
    assert captured.value.failure.phase is OnlyKernelFailurePhase.RECOVERING
    assert captured.value.failure.step == "unfinished-runs"
    assert host.state is OnlyKernelState.FAILED


def test_draining_closes_mutation_before_owned_resources_stop() -> None:
    observations: list[tuple[OnlyKernelState, bool]] = []
    host: OnlyAlphaKernelHost

    def drain_resource() -> None:
        rejected = False
        try:
            host.assert_mutation_ready()
        except OnlyKernelMutationRejected:
            rejected = True
        observations.append((host.state, rejected))

    host = OnlyAlphaKernelHost(drainers=(_step("research-api", drain_resource),))
    with pytest.raises(OnlyKernelMutationRejected):
        host.assert_mutation_ready()
    host.start()
    host.assert_mutation_ready()

    status = host.stop()

    assert observations == [(OnlyKernelState.DRAINING, True)]
    assert status.state is OnlyKernelState.STOPPED
    with pytest.raises(OnlyKernelMutationRejected):
        host.assert_mutation_ready()


def test_drain_failure_transitions_to_failed_without_reopening_mutation() -> None:
    host = OnlyAlphaKernelHost(drainers=(_step("runtime", lambda: (_ for _ in ()).throw(OSError("close failed"))),))
    host.start()

    with pytest.raises(OnlyKernelHostError) as captured:
        host.stop()

    assert captured.value.failure.phase is OnlyKernelFailurePhase.DRAINING
    assert host.state is OnlyKernelState.FAILED
    with pytest.raises(OnlyKernelMutationRejected):
        host.assert_mutation_ready()


def test_repeated_and_invalid_lifecycle_operations_are_rejected_without_restart() -> None:
    created = OnlyAlphaKernelHost()
    with pytest.raises(OnlyKernelLifecycleError, match="stop requires READY"):
        created.stop()

    ready = OnlyAlphaKernelHost()
    ready.start()
    with pytest.raises(OnlyKernelLifecycleError, match="start requires CREATED"):
        ready.start()
    ready.stop()
    with pytest.raises(OnlyKernelLifecycleError, match="start requires CREATED"):
        ready.start()
    with pytest.raises(OnlyKernelLifecycleError, match="stop requires READY"):
        ready.stop()

    failed = OnlyAlphaKernelHost(verifiers=(_step("fail", lambda: (_ for _ in ()).throw(RuntimeError("failure"))),))
    with pytest.raises(OnlyKernelHostError):
        failed.start()
    with pytest.raises(OnlyKernelLifecycleError, match="start requires CREATED"):
        failed.start()


def test_reentrant_start_fails_closed_instead_of_deadlocking() -> None:
    host: OnlyAlphaKernelHost
    host = OnlyAlphaKernelHost(booters=(_step("reentrant", lambda: host.start()),))

    with pytest.raises(OnlyKernelHostError):
        host.start()

    assert host.state is OnlyKernelState.FAILED


def test_step_collections_must_be_explicit_ordered_tuples() -> None:
    step = _step("verify", lambda: None)
    with pytest.raises(TypeError, match="explicitly ordered tuple"):
        OnlyAlphaKernelHost(verifiers=[step])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unique"):
        OnlyAlphaKernelHost(verifiers=(step, step))
