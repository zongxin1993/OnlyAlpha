from datetime import UTC, datetime, timedelta

import pytest

from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.core.errors import OnlyLifecycleError, OnlyValidationError
from onlyalpha.event.bus import OnlyEventBus
from onlyalpha.event.model import OnlyEvent


def test_backtest_clock_is_deterministic_and_monotonic() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    clock = OnlyBacktestClock(start)
    clock.advance_to(start + timedelta(minutes=1))
    assert clock.now() == start + timedelta(minutes=1)
    with pytest.raises(OnlyValidationError):
        clock.advance_to(start)


def test_event_bus_is_bounded_and_isolates_handler_failure() -> None:
    bus = OnlyEventBus(capacity=1)
    received: list[int] = []
    event = OnlyEvent("bar", datetime.now(UTC), "e", "r", "test", 1)
    bus.subscribe("bar", lambda _: (_ for _ in ()).throw(RuntimeError("broken")))
    bus.subscribe("bar", lambda item: received.append(item.sequence))
    bus.publish(event)
    with pytest.raises(OnlyLifecycleError):
        bus.publish(event)
    assert bus.drain() == 1
    assert received == [1]
    assert len(bus.failures) == 1
