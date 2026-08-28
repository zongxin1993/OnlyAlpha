from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from onlyalpha.kernel import (
    OnlyKernelFailure,
    OnlyKernelFailurePhase,
    OnlyKernelLifecycle,
    OnlyKernelLifecycleError,
    OnlyKernelMutationRejected,
    OnlyKernelState,
)


def _advance(lifecycle: OnlyKernelLifecycle, target: OnlyKernelState) -> None:
    path = (
        OnlyKernelState.BOOTING,
        OnlyKernelState.VERIFYING,
        OnlyKernelState.RECOVERING,
        OnlyKernelState.READY,
        OnlyKernelState.DRAINING,
        OnlyKernelState.STOPPED,
    )
    for state in path:
        lifecycle.transition(state)
        if state is target:
            return


def test_legal_transition_graph_is_exact_and_ready_projection_is_unique() -> None:
    lifecycle = OnlyKernelLifecycle()
    observed = [lifecycle.status]
    for target in (
        OnlyKernelState.BOOTING,
        OnlyKernelState.VERIFYING,
        OnlyKernelState.RECOVERING,
        OnlyKernelState.READY,
        OnlyKernelState.DRAINING,
        OnlyKernelState.STOPPED,
    ):
        observed.append(lifecycle.transition(target))

    assert tuple(item.state for item in observed) == (
        OnlyKernelState.CREATED,
        OnlyKernelState.BOOTING,
        OnlyKernelState.VERIFYING,
        OnlyKernelState.RECOVERING,
        OnlyKernelState.READY,
        OnlyKernelState.DRAINING,
        OnlyKernelState.STOPPED,
    )
    assert all(item.ready is (item.state is OnlyKernelState.READY) for item in observed)
    assert all(item.live for item in observed[:-1])
    assert not observed[-1].live


@pytest.mark.parametrize(
    ("state", "phase"),
    (
        (OnlyKernelState.BOOTING, OnlyKernelFailurePhase.BOOTING),
        (OnlyKernelState.VERIFYING, OnlyKernelFailurePhase.VERIFYING),
        (OnlyKernelState.RECOVERING, OnlyKernelFailurePhase.RECOVERING),
        (OnlyKernelState.READY, OnlyKernelFailurePhase.READY),
        (OnlyKernelState.DRAINING, OnlyKernelFailurePhase.DRAINING),
    ),
)
def test_relevant_active_phases_have_explicit_failure_transition(
    state: OnlyKernelState, phase: OnlyKernelFailurePhase
) -> None:
    lifecycle = OnlyKernelLifecycle()
    _advance(lifecycle, state)
    failure = OnlyKernelFailure(phase, "stable-step", "StableError")

    status = lifecycle.fail(failure)

    assert status.state is OnlyKernelState.FAILED
    assert status.failure == failure
    assert not status.ready
    assert status.live


def test_recovery_authority_failure_can_fail_closed_before_recovering_transition() -> None:
    lifecycle = OnlyKernelLifecycle()
    _advance(lifecycle, OnlyKernelState.VERIFYING)
    failure = OnlyKernelFailure(
        OnlyKernelFailurePhase.RECOVERING,
        "mutation-authority-acquire",
        "Unavailable",
    )

    status = lifecycle.fail(failure)

    assert status.state is OnlyKernelState.FAILED
    assert status.failure == failure


@pytest.mark.parametrize(
    ("before", "target"),
    (
        (OnlyKernelState.CREATED, OnlyKernelState.READY),
        (OnlyKernelState.VERIFYING, OnlyKernelState.READY),
        (OnlyKernelState.READY, OnlyKernelState.BOOTING),
        (OnlyKernelState.FAILED, OnlyKernelState.READY),
        (OnlyKernelState.STOPPED, OnlyKernelState.READY),
    ),
)
def test_illegal_transitions_fail_closed(before: OnlyKernelState, target: OnlyKernelState) -> None:
    lifecycle = OnlyKernelLifecycle()
    if before is OnlyKernelState.FAILED:
        lifecycle.transition(OnlyKernelState.BOOTING)
        lifecycle.fail(OnlyKernelFailure(OnlyKernelFailurePhase.BOOTING, "boot", "Failure"))
    elif before is not OnlyKernelState.CREATED:
        _advance(lifecycle, before)

    with pytest.raises(OnlyKernelLifecycleError, match="Illegal Product Kernel lifecycle transition"):
        lifecycle.transition(target)
    assert lifecycle.state is before


def test_failed_state_requires_matching_failure_evidence() -> None:
    lifecycle = OnlyKernelLifecycle()
    lifecycle.transition(OnlyKernelState.BOOTING)

    with pytest.raises(OnlyKernelLifecycleError):
        lifecycle.transition(OnlyKernelState.FAILED)
    with pytest.raises(OnlyKernelLifecycleError):
        lifecycle.fail(OnlyKernelFailure(OnlyKernelFailurePhase.VERIFYING, "schema", "Incompatible"))
    assert lifecycle.state is OnlyKernelState.BOOTING


def test_state_and_status_cannot_be_rewritten_through_public_properties() -> None:
    lifecycle = OnlyKernelLifecycle()
    status = lifecycle.status

    with pytest.raises(AttributeError):
        lifecycle.state = OnlyKernelState.READY  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        status.state = OnlyKernelState.READY  # type: ignore[misc]
    assert lifecycle.state is OnlyKernelState.CREATED


def test_mutation_is_admitted_if_and_only_if_ready() -> None:
    lifecycle = OnlyKernelLifecycle()
    for target in (
        OnlyKernelState.CREATED,
        OnlyKernelState.BOOTING,
        OnlyKernelState.VERIFYING,
        OnlyKernelState.RECOVERING,
        OnlyKernelState.READY,
        OnlyKernelState.DRAINING,
        OnlyKernelState.STOPPED,
    ):
        if target is not OnlyKernelState.CREATED:
            lifecycle.transition(target)
        if target is OnlyKernelState.READY:
            lifecycle.assert_mutation_ready()
        else:
            with pytest.raises(OnlyKernelMutationRejected):
                lifecycle.assert_mutation_ready()

    failed = OnlyKernelLifecycle()
    failed.transition(OnlyKernelState.BOOTING)
    failed.fail(OnlyKernelFailure(OnlyKernelFailurePhase.BOOTING, "boot", "Failure"))
    with pytest.raises(OnlyKernelMutationRejected):
        failed.assert_mutation_ready()
