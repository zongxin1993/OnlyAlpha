"""Manual first-phase Clock complexity smoke benchmark."""

from time import perf_counter_ns

from onlyalpha.core.clock import OnlyVirtualClock


def main() -> None:
    clock = OnlyVirtualClock(0)
    started = perf_counter_ns()
    handles = [clock.schedule_at(f"timer-{index}", index + 1, lambda _: None) for index in range(10_000)]
    registered = perf_counter_ns()
    for handle in handles[::3]:
        handle.cancel()
    cancelled = perf_counter_ns()
    result = clock.advance_to(10_000)
    finished = perf_counter_ns()
    print(
        f"registered=10000 fired={len(result.fired_events)} "
        f"register_ms={(registered - started) / 1_000_000:.3f} "
        f"cancel_ms={(cancelled - registered) / 1_000_000:.3f} "
        f"advance_ms={(finished - cancelled) / 1_000_000:.3f}"
    )


if __name__ == "__main__":
    main()
