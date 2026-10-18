"""Common canonical behavior, not certification of known Python defect paths."""

from collections.abc import Callable
from pathlib import Path

from onlyalpha.core.clock import OnlyTimerEvent, OnlyVirtualClock

ROOT = Path(__file__).resolve().parents[2]


def test_independent_common_clock_vectors() -> None:
    for line in (ROOT / "test-data/clock/timers-v1.tsv").read_text().splitlines():
        if line.startswith("#"):
            continue
        name, initial, target, timers, expected = line.split("\t")
        clock = OnlyVirtualClock(int(initial))
        observed: list[str] = []

        def record(event: OnlyTimerEvent, output: list[str] = observed) -> None:
            output.append(f"{event.timer_id},{event.deadline_ns},{event.sequence},{event.fire_count}")

        for timer in timers.split(";"):
            timer_id, mode, first, interval = timer.split(",")
            if mode == "ONCE":
                clock.schedule_at(timer_id, int(first), record)
            else:
                assert mode == "RATE"
                clock.schedule_every(timer_id, int(interval), record, start_ns=int(first))
        clock.advance_to(int(target))
        assert ";".join(observed) == expected, name


def test_independent_common_lifecycle_vectors() -> None:
    for line in (ROOT / "test-data/clock/lifecycle-v1.tsv").read_text().splitlines():
        if line.startswith("#"):
            continue
        kind, first_text, second_text, target_text, expected, failures, active = line.split("\t")
        first, second, target = int(first_text), int(second_text), int(target_text)
        clock = OnlyVirtualClock(0)
        observed: list[str] = []

        def record(event: OnlyTimerEvent, output: list[str] = observed) -> None:
            output.append(f"{event.timer_id},{event.deadline_ns},{event.sequence},{event.fire_count}")

        if kind == "restore":
            clock.schedule_every("first", first, record)
            clock.advance_to(second)
            snapshot = clock.snapshot()
            clock = OnlyVirtualClock(0)
            clock.schedule_every("first", first, record)
            clock.restore_with_registered_callbacks(snapshot)
        elif kind == "failure":

            def failing(event: OnlyTimerEvent, record_event: Callable[[OnlyTimerEvent], None] = record) -> None:
                record_event(event)
                raise ValueError("controlled callback failure")

            clock.schedule_every("first", first, failing)
            clock.schedule_at("second", second, record)
        elif kind == "register":

            def register(
                event: OnlyTimerEvent,
                current: OnlyVirtualClock = clock,
                record_event: Callable[[OnlyTimerEvent], None] = record,
            ) -> None:
                record_event(event)
                current.cancel_timer("second")
                current.schedule_at("child", event.deadline_ns, record_event)

            clock.schedule_at("first", first, register)
            clock.schedule_at("second", second, record)
        else:
            assert kind in {"cancel", "close"}
            clock.schedule_at("first", first, record)
            if kind == "cancel":
                clock.schedule_at("second", second, record)
                clock.cancel_timer("second")
            else:
                clock.close()
        if kind != "close":
            clock.advance_to(target)
        assert (";".join(observed) or "-") == expected, kind
        assert clock.timestamp_ns() == target, kind
        assert len(clock.failures) == int(failures), kind
        assert clock.has_timer("first") == (active == "true"), kind
