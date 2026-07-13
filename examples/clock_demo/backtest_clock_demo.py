"""Deterministic Backtest Clock advancement demo."""

from datetime import UTC, datetime

from onlyalpha.core.clock import OnlyBacktestClock, OnlyTimerEvent
from onlyalpha.core.time import only_datetime_to_unix_ns


def main() -> None:
    start = datetime(2026, 1, 5, 1, 30, tzinfo=UTC)
    clock = OnlyBacktestClock(start)

    def report(event: OnlyTimerEvent) -> None:
        print(f"[FIRED] {event.timer_id} sequence={event.sequence} at={clock.now_utc().isoformat()}")

    minute = 60 * 1_000_000_000
    start_ns = only_datetime_to_unix_ns(start)
    clock.schedule_at("market_open_check", start_ns + minute, report)
    clock.schedule_at("strategy_timer_a", start_ns + 2 * minute, report)
    clock.schedule_at("strategy_timer_b", start_ns + 2 * minute, report)
    clock.schedule_every("heartbeat", minute, report, start_ns=start_ns + 2 * minute)

    print(f"Initial time: {clock.now_utc().isoformat()}")
    for target in (start_ns + minute, start_ns + 2 * minute):
        print(f"\nAdvance to {target}")
        clock.advance_to(target)
    print(f"\nClock state: {clock.state.value}")
    print(f"Active timers: {len(clock.snapshot().active_timers)}")


if __name__ == "__main__":
    main()
