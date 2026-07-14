"""Two primary periods sharing one Runtime Aggregator."""

from common import OnlyDemoBarCluster, only_demo_bar, only_demo_system, only_demo_types

from onlyalpha.market_data.dispatcher import OnlyClusterBarSubscription
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


def main() -> None:
    bar_1m, bar_3m = only_demo_types()
    pipeline, dispatcher, manager = only_demo_system()
    dispatcher.register(
        OnlyClusterBarSubscription(OnlyDemoBarCluster("Cluster-A"), OnlyBarSubscription((bar_1m, bar_3m)))
    )
    dispatcher.register(
        OnlyClusterBarSubscription(
            OnlyDemoBarCluster("Cluster-B"),
            OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m),
        )
    )
    for minute in range(3):
        dispatcher.dispatch(pipeline.process_bar(only_demo_bar(bar_1m, minute)))
    print(f"shared_aggregators={manager.aggregator_count} created={manager.creation_count}")


if __name__ == "__main__":
    main()
