import pytest

from onlyalpha.core.clock import OnlyDuplicateTimerError, OnlyTimerState, OnlyVirtualClock


def _run_scenario() -> tuple[tuple[str, int, int], ...]:
    clock = OnlyVirtualClock(0)
    observed: list[tuple[str, int, int]] = []

    def record(event: object) -> None:
        timer_event = event
        observed.append((str(timer_event.timer_id), timer_event.deadline_ns, clock.timestamp_ns()))  # type: ignore[attr-defined]

    clock.schedule_at("later", 20, record)
    clock.schedule_at("same-a", 10, record)
    clock.schedule_at("same-b", 10, record)
    clock.schedule_every("periodic", 5, record)
    result = clock.advance_to(20)
    assert result.current_timestamp_ns == 20
    return tuple(observed)


def test_timer_order_is_deadline_then_registration_sequence_for_100_runs() -> None:
    expected = _run_scenario()
    assert [item[0] for item in expected] == [
        "periodic",
        "same-a",
        "same-b",
        "periodic",
        "periodic",
        "later",
        "periodic",
    ]
    assert all(deadline == observed_now for _, deadline, observed_now in expected)
    assert all(_run_scenario() == expected for _ in range(99))


def test_callback_can_register_and_cancel_at_same_deadline() -> None:
    clock = OnlyVirtualClock(0)
    observed: list[str] = []

    def first(event: object) -> None:
        observed.append(str(event.timer_id))  # type: ignore[attr-defined]
        clock.cancel_timer("cancel-me")
        clock.schedule_at("created-in-callback", clock.timestamp_ns(), lambda item: observed.append(str(item.timer_id)))

    clock.schedule_at("first", 10, first)
    cancelled = clock.schedule_at("cancel-me", 10, lambda item: observed.append(str(item.timer_id)))
    clock.advance_to(10)
    assert observed == ["first", "created-in-callback"]
    assert cancelled.timer.state is OnlyTimerState.CANCELLED


def test_callback_failure_is_structured_and_other_timers_continue() -> None:
    clock = OnlyVirtualClock(0)
    observed: list[str] = []
    failed = clock.schedule_at("failed", 1, lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    clock.schedule_at("healthy", 2, lambda event: observed.append(str(event.timer_id)))
    result = clock.advance_to(2)
    assert failed.timer.state is OnlyTimerState.FAILED
    assert len(result.failures) == 1
    assert str(result.failures[0].event.timer_id) == "failed"
    assert observed == ["healthy"]


def test_cancel_is_safe_to_repeat_and_periodic_cancel_stops_future_fires() -> None:
    clock = OnlyVirtualClock(0)
    observed: list[int] = []
    handle = clock.schedule_every("periodic", 2, lambda event: observed.append(event.fire_count))
    clock.advance_to(4)
    assert handle.cancel()
    assert not handle.cancel()
    clock.advance_to(100)
    assert observed == [1, 2]


def test_timer_id_is_unique_for_clock_lifetime() -> None:
    clock = OnlyVirtualClock(0)
    clock.schedule_at("unique", 1, lambda _: None)
    clock.advance_to(1)
    with pytest.raises(OnlyDuplicateTimerError, match="already used"):
        clock.schedule_at("unique", 2, lambda _: None)


def test_periodic_callback_failure_stops_future_fires() -> None:
    clock = OnlyVirtualClock(0)
    handle = clock.schedule_every("bad-periodic", 1, lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    result = clock.advance_to(100)
    assert len(result.fired_events) == 1
    assert handle.timer.fire_count == 1
    assert handle.timer.state is OnlyTimerState.FAILED
