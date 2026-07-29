from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.model import OnlyEvent
from onlyalpha.event.ports import OnlyRuntimeEventDisposition, OnlyRuntimeEventRoute
from onlyalpha.runtime.events import (
    OnlyRuntimeEventGatePhase,
    OnlyRuntimeEventGateTransitionError,
    OnlyRuntimeEventStageCapacityError,
    OnlyRuntimeRecoveryEventGate,
)


def _event(sequence: int) -> OnlyEvent:
    return OnlyEvent(
        f"TEST_{sequence}",
        datetime(2026, 1, 1, tzinfo=UTC),
        OnlyEngineId("engine"),
        OnlyRuntimeId("runtime"),
        "test",
        sequence,
    )


def test_fresh_bootstrap_stages_atomically_and_opens_fifo() -> None:
    gate = OnlyRuntimeRecoveryEventGate(3)
    assert gate.phase is OnlyRuntimeEventGatePhase.BOOTSTRAPPING
    first = gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(1),))
    batch = gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(2), _event(3)))
    assert first.result.disposition is OnlyRuntimeEventDisposition.STAGED
    assert (batch.result.attempted, batch.result.staged) == (2, 2)
    gate.complete_fresh_bootstrap()
    assert gate.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    assert tuple(int(item.sequence) for item in gate.open()) == (1, 2, 3)
    assert gate.phase is OnlyRuntimeEventGatePhase.OPEN
    assert gate.snapshot().staged_count == 0


def test_staging_capacity_is_batch_atomic_and_fails_closed() -> None:
    gate = OnlyRuntimeRecoveryEventGate(2)
    gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(1),))
    with pytest.raises(OnlyRuntimeEventStageCapacityError):
        gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(2), _event(3)))
    snapshot = gate.snapshot()
    assert snapshot.phase is OnlyRuntimeEventGatePhase.FAILED
    assert snapshot.staged_count == 0


def test_recovery_discards_bootstrap_and_suppresses_bounded_samples() -> None:
    gate = OnlyRuntimeRecoveryEventGate(20, suppressed_sample_capacity=3)
    gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(1), _event(2)))
    assert gate.begin_recovery() == 2
    for sequence in range(3, 8):
        result = gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(sequence),)).result
        assert result.disposition is OnlyRuntimeEventDisposition.SUPPRESSED
    gate.begin_finalization()
    gate.stage_or_route(OnlyRuntimeEventRoute.EXTERNAL_DIRECT, (_event(8),))
    gate.complete_recovery()
    snapshot = gate.snapshot()
    assert snapshot.phase is OnlyRuntimeEventGatePhase.READY_BLOCKED
    assert snapshot.discarded_bootstrap_count == 2
    assert snapshot.suppressed_direct_count == 6
    assert tuple(item.sequence for item in snapshot.last_suppressed_events) == (6, 7, 8)
    assert gate.open() == ()


@pytest.mark.parametrize("route", (OnlyRuntimeEventRoute.DURABLE_OUTBOX, OnlyRuntimeEventRoute.LIFECYCLE))
def test_non_direct_routes_are_rejected_before_open(route: OnlyRuntimeEventRoute) -> None:
    gate = OnlyRuntimeRecoveryEventGate(4)
    result = gate.stage_or_route(route, (_event(1),)).result
    assert result.disposition is OnlyRuntimeEventDisposition.REJECTED
    assert result.rejected == 1


def test_fail_close_and_illegal_transitions() -> None:
    gate = OnlyRuntimeRecoveryEventGate(4)
    with pytest.raises(OnlyRuntimeEventGateTransitionError):
        gate.open()
    gate.fail()
    gate.fail()
    assert gate.phase is OnlyRuntimeEventGatePhase.FAILED
    gate.close()
    gate.close()
    assert gate.phase is OnlyRuntimeEventGatePhase.CLOSED
