from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from onlyalpha.core.clock import (
    OnlyBacktestClock,
    OnlyClockError,
    OnlyTimerState,
    OnlyVirtualClock,
)
from onlyalpha.core.errors import OnlyValidationError
from onlyalpha.core.time import only_datetime_to_unix_ns

START = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)


def test_virtual_clock_preserves_nanoseconds_as_authoritative_value() -> None:
    clock = OnlyVirtualClock(1)
    assert clock.timestamp_ns() == 1
    assert clock.now_utc() == datetime(1970, 1, 1, tzinfo=UTC)
    result = clock.advance_by(2)
    assert result.previous_timestamp_ns == 1
    assert result.current_timestamp_ns == 3


def test_backtest_rejects_non_utc_and_backward_time() -> None:
    non_utc_dt = datetime(2026, 1, 5, 9, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    with pytest.raises(OnlyValidationError, match="UTC"):
        OnlyBacktestClock(non_utc_dt)
    clock = OnlyBacktestClock(START)
    clock.advance_by(1)
    with pytest.raises(OnlyValidationError, match="backwards"):
        clock.advance_to(only_datetime_to_unix_ns(START))


def test_snapshot_restore_is_time_only() -> None:
    clock = OnlyVirtualClock(100)
    snapshot = clock.snapshot()
    clock.advance_to(200)
    clock.restore(snapshot)
    assert clock.timestamp_ns() == 100

    clock.schedule_after("active", 1, lambda _: None)
    with pytest.raises(OnlyClockError, match="active callbacks"):
        clock.restore(clock.snapshot())


def test_close_is_idempotent_and_rejects_scheduling() -> None:
    clock = OnlyVirtualClock(START)
    handle = clock.schedule_after("cancelled", 10, lambda _: None)
    clock.close()
    clock.close()
    assert handle.timer.state is OnlyTimerState.CANCELLED
    assert clock.now_utc() == START
    with pytest.raises(OnlyClockError, match="closed"):
        clock.schedule_after("late", 1, lambda _: None)


def test_backtest_clock_never_reads_system_time(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = OnlyBacktestClock(START)

    def forbidden() -> int:
        raise AssertionError("Backtest Clock read real system time")

    monkeypatch.setattr("onlyalpha.core.clock.time.time_ns", forbidden)
    monkeypatch.setattr("onlyalpha.core.clock.time.monotonic_ns", forbidden)
    clock.schedule_after("timer", 1, lambda _: None)
    result = clock.advance_by(1)
    assert len(result.fired_events) == 1
