from common import only_demo_bar, only_demo_bar_types, only_demo_runtime

from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.market_data.subscriptions import OnlyBarSubscription

bar_1m, bar_3m = only_demo_bar_types()
runtimes = [only_demo_runtime("runtime_a"), only_demo_runtime("runtime_b")]
clusters = [OnlyDemoCluster(OnlyClusterConfig("demo"), OnlyBarSubscription((bar_1m, bar_3m))) for _ in runtimes]
for runtime, cluster, price in zip(runtimes, clusters, ("10.00", "20.00"), strict=True):
    runtime.add_cluster("engine", cluster)
    runtime.start()
    for minute in range(3):
        runtime.process_bar(only_demo_bar(bar_1m, minute, base_price=price))
assert clusters[0].context is not None and clusters[1].context is not None
print(f"clock_independent={clusters[0].context.clock is not clusters[1].context.clock}")
print(f"data_independent={clusters[0].records[-1].latest_3m != clusters[1].records[-1].latest_3m}")
