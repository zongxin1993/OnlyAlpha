"""Short-lived system Clock and Timer demo."""

import threading

from onlyalpha.core.clock import OnlyLiveClock, OnlyTimerEvent


def main() -> None:
    clock = OnlyLiveClock()
    finished = threading.Event()
    print(f"UTC: {clock.now_utc().isoformat()}")
    print(f"Unix ns: {clock.timestamp_ns()}")
    print(f"Monotonic ns: {clock.monotonic_ns()}")

    periodic = clock.schedule_every("heartbeat", 10_000_000, lambda event: print(f"periodic: {event.fire_count}"))

    def finish(event: OnlyTimerEvent) -> None:
        print(f"one-shot: {event.timer_id}")
        periodic.cancel()
        finished.set()

    clock.schedule_after("finish", 25_000_000, finish)
    if not finished.wait(1):
        raise RuntimeError("Live Clock demo timed out")
    clock.close()
    clock.close()


if __name__ == "__main__":
    main()
