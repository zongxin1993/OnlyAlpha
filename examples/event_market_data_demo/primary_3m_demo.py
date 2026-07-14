"""Explicit 3m primary-period demo."""

from common import OnlyDemoBarCluster, only_demo_bar, only_demo_system, only_demo_types

from onlyalpha.market_data.dispatcher import OnlyClusterBarSubscription
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


def main() -> None:
    bar_1m, bar_3m = only_demo_types()
    pipeline, dispatcher, _ = only_demo_system()
    cluster = OnlyDemoBarCluster("Cluster-B")
    subscription = OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m)
    dispatcher.register(OnlyClusterBarSubscription(cluster, subscription))
    for minute in range(3):
        dispatcher.dispatch(pipeline.process_bar(only_demo_bar(bar_1m, minute)))


if __name__ == "__main__":
    main()
