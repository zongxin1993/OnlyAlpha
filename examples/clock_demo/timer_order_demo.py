"""Stable same-deadline Timer ordering demo."""

from onlyalpha.core.clock import OnlyTimerEvent, OnlyVirtualClock


def main() -> None:
    clock = OnlyVirtualClock(0)
    observed: list[str] = []

    def record(event: OnlyTimerEvent) -> None:
        observed.append(str(event.timer_id))

    clock.schedule_at("registered-first", 10, record)
    clock.schedule_at("registered-second", 10, record)
    clock.schedule_at("earlier-deadline", 5, record)
    clock.advance_to(10)
    print(observed)


if __name__ == "__main__":
    main()
