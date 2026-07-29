from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.bus import OnlyEventBus, OnlyEventCapacityError, OnlyEventScopeError
from onlyalpha.event.model import OnlyEvent, OnlyEventScope
from onlyalpha.event.ports import OnlyRuntimeEventDisposition
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
        "test",
        sequence,
    )


def _router(capacity: int = 10) -> tuple[OnlyRuntimeEventRouter, OnlyEventBus]:
    bus = OnlyEventBus(capacity=capacity, scope=_SCOPE)
    return OnlyRuntimeEventRouter(bus, OnlyRuntimeRecoveryEventGate(capacity), _SCOPE), bus


def test_fresh_router_stages_flushes_and_publishes_all_routes() -> None:
    router, bus = _router()
    staged = router.publish_direct_many((_event(1), _event(2)))
    assert (staged.disposition, staged.attempted, staged.staged) == (
        OnlyRuntimeEventDisposition.STAGED,
        2,
        2,
    )
    router.complete_fresh_bootstrap()
    flushed = router.open()
    assert (flushed.attempted, flushed.published, bus.pending_count()) == (2, 2, 2)
    assert router.publish_direct(_event(3)).disposition is OnlyRuntimeEventDisposition.PUBLISHED
    assert router.publish_durable(_event(4)).disposition is OnlyRuntimeEventDisposition.PUBLISHED
    assert router.publish_lifecycle(_event(5)).disposition is OnlyRuntimeEventDisposition.PUBLISHED
    snapshot = router.snapshot()
    assert (snapshot.published_direct_count, snapshot.published_durable_count) == (3, 1)
    assert snapshot.published_lifecycle_count == 1


def test_recovery_suppresses_direct_rejects_other_routes_and_opens_empty() -> None:
    router, bus = _router()
    router.publish_direct(_event(1))
    router.begin_recovery()
    suppressed = router.publish_direct(_event(2))
    assert suppressed.disposition is OnlyRuntimeEventDisposition.SUPPRESSED
    with pytest.raises(OnlyRuntimeEventGateError):
        router.publish_durable(_event(3))
    with pytest.raises(OnlyRuntimeEventGateError):
        router.publish_lifecycle(_event(4))
    router.begin_finalization()
    router.complete_recovery()
    assert router.open().attempted == 0
    assert bus.pending_count() == 0


def test_router_validates_scope_before_gate_and_fails_on_bus_capacity() -> None:
    router, bus = _router(capacity=1)
    with pytest.raises(OnlyEventScopeError):
        router.publish_direct(_event(1, runtime_id="other"))
    assert router.snapshot().staged_count == 0
    router.publish_direct(_event(1))
    router.complete_fresh_bootstrap()
    router.open()
    with pytest.raises(OnlyEventCapacityError):
        router.publish_direct(_event(2))
    assert router.snapshot().phase is OnlyRuntimeEventGatePhase.FAILED
    assert bus.pending_count() == 1
