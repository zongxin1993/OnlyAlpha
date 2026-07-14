from datetime import UTC, datetime

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId, OnlyRuntimeId
from onlyalpha.event.bus import (
    OnlyEventBus,
    OnlyEventCapacityError,
    OnlyEventQueuePolicy,
    OnlyEventRuntimeFailure,
    OnlyEventScopeError,
)
from onlyalpha.event.model import OnlyEvent, OnlyEventPriority, OnlyEventScope


def _event(
    sequence: int, *, runtime_id: str = "runtime", priority: OnlyEventPriority = OnlyEventPriority.NORMAL
) -> OnlyEvent:
    return OnlyEvent(
        "BAR_RECEIVED",
        datetime(2026, 1, 5, 1, 31, tzinfo=UTC),
        "engine",
        runtime_id,
        "feed",
        sequence,
        priority=priority,
    )


def test_bus_is_fifo_and_handler_priority_is_explicit() -> None:
    bus = OnlyEventBus()
    observed: list[tuple[str, int]] = []
    bus.subscribe("BAR_RECEIVED", lambda event: observed.append(("normal", int(event.sequence))))
    bus.subscribe(
        "BAR_RECEIVED",
        lambda event: observed.append(("high", int(event.sequence))),
        priority=OnlyEventPriority.HIGH,
    )
    bus.publish_many((_event(1), _event(2)))
    assert bus.drain() == 2
    assert observed == [("high", 1), ("normal", 1), ("high", 2), ("normal", 2)]


def test_subscription_can_be_removed_idempotently() -> None:
    bus = OnlyEventBus()
    subscription = bus.subscribe("BAR_RECEIVED", lambda _: None)
    assert bus.unsubscribe(subscription.subscription_id)
    assert not bus.unsubscribe(subscription.subscription_id)


def test_handler_failure_is_structured_and_does_not_stop_others() -> None:
    bus = OnlyEventBus()
    observed: list[int] = []
    bus.subscribe("BAR_RECEIVED", lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.subscribe("BAR_RECEIVED", lambda event: observed.append(int(event.sequence)))
    bus.publish(_event(1))
    result = bus.dispatch()
    assert result is not None and not result.succeeded
    assert observed == [1]
    assert len(bus.failures) == 1


def test_runtime_scope_rejects_cross_runtime_event() -> None:
    scope = OnlyEventScope(OnlyEngineId("engine"), OnlyRuntimeId("runtime"))
    bus = OnlyEventBus(scope=scope)
    bus.publish(_event(1))
    with pytest.raises(OnlyEventScopeError):
        bus.publish(_event(2, runtime_id="other"))


def test_capacity_policies_never_silently_drop_core_events() -> None:
    reject = OnlyEventBus(capacity=1)
    reject.publish(_event(1))
    with pytest.raises(OnlyEventCapacityError):
        reject.publish(_event(2))

    fail = OnlyEventBus(capacity=1, queue_policy=OnlyEventQueuePolicy.FAIL_RUNTIME)
    fail.publish(_event(1))
    with pytest.raises(OnlyEventRuntimeFailure):
        fail.publish(_event(2))

    drop = OnlyEventBus(capacity=1, queue_policy=OnlyEventQueuePolicy.DROP_LOW_PRIORITY)
    drop.publish(_event(1, priority=OnlyEventPriority.LOW))
    assert drop.publish(_event(2, priority=OnlyEventPriority.HIGH))
    assert len(drop.dropped_events) == 1
    assert drop.dropped_events[0].dropped.sequence == 1
    assert drop.dispatch().event.sequence == 2  # type: ignore[union-attr]


def test_close_drains_then_rejects_new_events() -> None:
    bus = OnlyEventBus()
    observed: list[int] = []
    bus.subscribe("BAR_RECEIVED", lambda event: observed.append(int(event.sequence)))
    bus.publish(_event(1))
    bus.close()
    bus.close()
    assert observed == [1]
    with pytest.raises(Exception, match="closed"):
        bus.publish(_event(2))
