from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.bus import OnlyEventBus, OnlyEventCapacityError, OnlyEventScopeError
from onlyalpha.event.model import OnlyEvent, OnlyEventScope
from onlyalpha.runtime.events import (
    OnlyRuntimeEventGateError,
    OnlyRuntimeEventGatePhase,
    OnlyRuntimeEventRouter,
    OnlyRuntimeRecoveryEventGate,
)

_SCOPE = OnlyEventScope(OnlyEngineId("engine"), OnlyRuntimeId("runtime"))


def _event(sequence: int, *, runtime_id: str = "runtime") -> OnlyEvent:
    return OnlyEvent(
        f"TEST_{sequence}",
        datetime(2026, 1, 1, tzinfo=UTC),
        OnlyEngineId("engine"),
        OnlyRuntimeId(runtime_id),
        "router-failure-test",
        sequence,
    )


def test_batch_scope_failure_precedes_gate_and_is_atomic() -> None:
    bus = OnlyEventBus(capacity=4, scope=_SCOPE)
    router = OnlyRuntimeEventRouter(bus, OnlyRuntimeRecoveryEventGate(4), _SCOPE)
    before = router.snapshot()

    with pytest.raises(OnlyEventScopeError):
        router.publish_direct_many((_event(1), _event(2), _event(3, runtime_id="other")))

    assert router.snapshot() == before
    assert bus.pending_count() == 0


@pytest.mark.parametrize(
    "phase",
    (
        OnlyRuntimeEventGatePhase.BOOTSTRAPPING,
        OnlyRuntimeEventGatePhase.RECOVERING,
        OnlyRuntimeEventGatePhase.FINALIZING,
        OnlyRuntimeEventGatePhase.READY_BLOCKED,
        OnlyRuntimeEventGatePhase.OPEN,
        OnlyRuntimeEventGatePhase.FAILED,
    ),
)
def test_empty_direct_batch_is_a_no_op_in_every_active_phase(phase: OnlyRuntimeEventGatePhase) -> None:
    bus = OnlyEventBus(capacity=4, scope=_SCOPE)
    router = OnlyRuntimeEventRouter(bus, OnlyRuntimeRecoveryEventGate(4), _SCOPE)
    if phase is OnlyRuntimeEventGatePhase.RECOVERING:
        router.begin_recovery()
    elif phase is OnlyRuntimeEventGatePhase.FINALIZING:
        router.begin_recovery()
        router.begin_finalization()
    elif phase is OnlyRuntimeEventGatePhase.READY_BLOCKED:
        router.complete_fresh_bootstrap()
    elif phase is OnlyRuntimeEventGatePhase.OPEN:
        router.complete_fresh_bootstrap()
        router.open()
    elif phase is OnlyRuntimeEventGatePhase.FAILED:
        router.fail()
    before = router.snapshot()

    if phase is OnlyRuntimeEventGatePhase.FAILED:
        with pytest.raises(OnlyRuntimeEventGateError):
            router.publish_direct_many(())
        assert router.snapshot() == before
        assert bus.pending_count() == 0
        return

    result = router.publish_direct_many(())

    assert (result.attempted, result.published, result.staged, result.suppressed, result.rejected) == (0, 0, 0, 0, 0)
    assert router.snapshot() == before
    assert bus.pending_count() == 0


def test_open_flush_capacity_failure_has_no_partial_enqueue() -> None:
    bus = OnlyEventBus(capacity=1, scope=_SCOPE)
    router = OnlyRuntimeEventRouter(bus, OnlyRuntimeRecoveryEventGate(3), _SCOPE)
    router.publish_direct_many((_event(1), _event(2), _event(3)))
    router.complete_fresh_bootstrap()

    with pytest.raises(OnlyEventCapacityError):
        router.open()

    assert router.snapshot().phase is OnlyRuntimeEventGatePhase.FAILED
    assert bus.pending_count() == 0
    assert bus.dispatch_results == ()


def test_event_bus_atomic_batch_rejects_drop_low_priority_policy() -> None:
    from onlyalpha.event.bus import OnlyEventBusError, OnlyEventQueuePolicy

    bus = OnlyEventBus(capacity=3, scope=_SCOPE, queue_policy=OnlyEventQueuePolicy.DROP_LOW_PRIORITY)
    with pytest.raises(OnlyEventBusError, match="atomic batch"):
        bus.publish_many_atomic((_event(1),))
    assert bus.pending_count() == 0


def test_event_bus_atomic_batch_validates_all_scopes_before_enqueue() -> None:
    bus = OnlyEventBus(capacity=3, scope=_SCOPE)
    with pytest.raises(OnlyEventScopeError):
        bus.publish_many_atomic((_event(1), _event(2, runtime_id="other")))
    assert bus.pending_count() == 0


def test_event_bus_atomic_batch_enqueues_fifo_or_nothing() -> None:
    bus = OnlyEventBus(capacity=3, scope=_SCOPE)
    assert bus.publish_many_atomic((_event(1), _event(2), _event(3))) == 3
    assert tuple(int(bus.dispatch().event.sequence) for _ in range(3)) == (1, 2, 3)  # type: ignore[union-attr]

    full = OnlyEventBus(capacity=2, scope=_SCOPE)
    with pytest.raises(OnlyEventCapacityError):
        full.publish_many_atomic((_event(1), _event(2), _event(3)))
    assert full.pending_count() == 0
