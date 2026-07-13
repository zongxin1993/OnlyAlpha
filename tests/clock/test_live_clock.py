import threading
import time
from datetime import UTC

import pytest

from onlyalpha.core.clock import OnlyClockError, OnlyLiveClock, OnlyTimerState


def test_live_clock_uses_utc_and_single_scheduler_thread() -> None:
    before_threads = {thread.ident for thread in threading.enumerate()}
    clock = OnlyLiveClock()
    fired = threading.Event()
    handle = clock.schedule_after("once", 1_000_000, lambda _: fired.set())
    assert clock.now_utc().tzinfo is UTC
    assert fired.wait(0.5)
    assert handle.timer.state is OnlyTimerState.COMPLETED
    scheduler_threads = [thread for thread in threading.enumerate() if thread.name == "onlyalpha-clock"]
    assert len(scheduler_threads) <= 1
    assert clock.monotonic_ns() <= time.monotonic_ns()
    clock.close()
    assert all(thread.ident in before_threads for thread in threading.enumerate() if thread.name == "onlyalpha-clock")


def test_live_callback_failure_does_not_kill_scheduler() -> None:
    clock = OnlyLiveClock()
    healthy = threading.Event()
    clock.schedule_after("bad", 1_000_000, lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    clock.schedule_after("good", 2_000_000, lambda _: healthy.set())
    assert healthy.wait(0.5)
    assert len(clock.failures) == 1
    clock.close()


def test_live_cancel_and_close_prevent_callbacks() -> None:
    clock = OnlyLiveClock()
    fired = threading.Event()
    handle = clock.schedule_after("cancel", 100_000_000, lambda _: fired.set())
    assert handle.cancel()
    clock.close()
    clock.close()
    assert not fired.wait(0.01)
    with pytest.raises(OnlyClockError, match="closed"):
        clock.schedule_after("late", 1, lambda _: None)


def test_live_clock_registration_and_cancel_are_thread_safe() -> None:
    clock = OnlyLiveClock()
    handles = []
    handles_lock = threading.Lock()

    def register(batch: int) -> None:
        local = [clock.schedule_after(f"thread-{batch}-{index}", 1_000_000_000, lambda _: None) for index in range(50)]
        with handles_lock:
            handles.extend(local)

    threads = [threading.Thread(target=register, args=(batch,)) for batch in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(handles) == 200
    assert all(handle.cancel() for handle in handles)
    clock.close()
