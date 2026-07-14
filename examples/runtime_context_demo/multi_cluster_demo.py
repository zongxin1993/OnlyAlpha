from common import only_demo_bar, only_demo_bar_types, only_demo_runtime

from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.market_data.subscriptions import OnlyBarSubscription

bar_1m, bar_3m = only_demo_bar_types()
runtime = only_demo_runtime("multi_cluster")
cluster_a = OnlyDemoCluster(OnlyClusterConfig("cluster_a"), OnlyBarSubscription((bar_1m, bar_3m)))
cluster_b = OnlyDemoCluster(
    OnlyClusterConfig("cluster_b"),
    OnlyBarSubscription((bar_1m, bar_3m), primary_bar_type=bar_3m),
)
runtime.add_cluster("engine", cluster_a)
runtime.add_cluster("engine", cluster_b)
runtime.start()
for minute in range(3):
    runtime.process_bar(only_demo_bar(bar_1m, minute))
print(f"A calls={len(cluster_a.records)} B calls={len(cluster_b.records)}")
print(f"shared_3m_equal={cluster_a.records[-1].latest_3m == cluster_b.records[-1].latest_3m}")
