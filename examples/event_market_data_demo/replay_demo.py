"""Serialized input-event replay produces identical Snapshots."""

from datetime import UTC, datetime

from common import OnlyDemoBarCluster, only_demo_bar, only_demo_system, only_demo_types

from onlyalpha.domain.market import OnlyBar
from onlyalpha.event.model import OnlyEvent
from onlyalpha.market_data.dispatcher import OnlyClusterBarSubscription
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


def replay(events: list[dict[str, object]]) -> tuple[list[dict[str, object]], int]:
    bar_1m, bar_3m = only_demo_types()
    pipeline, dispatcher, _ = only_demo_system()
    cluster = OnlyDemoBarCluster("Replay")
    dispatcher.register(OnlyClusterBarSubscription(cluster, OnlyBarSubscription((bar_1m, bar_3m))))
    snapshots = []
    for payload in events:
        event = OnlyEvent.from_dict(payload)
        if not isinstance(event.payload, OnlyBar):
            raise TypeError("replay event must carry OnlyBar")
        update = pipeline.process_bar(event.payload)
        dispatcher.dispatch(update)
        snapshots.append(update.snapshot.to_dict())
    return snapshots, len(cluster.calls)


def main() -> None:
    bar_1m, _ = only_demo_types()
    events = [
        OnlyEvent(
            "BAR_RECEIVED",
            only_demo_bar(bar_1m, minute).bar_end,
            "engine",
            "runtime",
            "demo",
            minute,
            payload=only_demo_bar(bar_1m, minute),
            ts_init=datetime(2026, 1, 5, 7, 0, tzinfo=UTC),
        ).to_dict()
        for minute in range(3)
    ]
    first = replay(events)
    second = replay(events)
    print(f"replay_equal={first == second} calls={first[1]}")


if __name__ == "__main__":
    main()
