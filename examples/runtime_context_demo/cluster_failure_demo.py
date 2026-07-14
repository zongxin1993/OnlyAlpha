from common import only_demo_bar, only_demo_bar_types, only_demo_runtime

from onlyalpha.cluster.bar_context import OnlyBarContext
from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.domain.market import OnlyBar
from onlyalpha.market_data.subscriptions import OnlyBarSubscription


class OnlyFailingDemoCluster(OnlyDemoCluster):
    def on_bar(self, bar: OnlyBar, context: OnlyBarContext) -> None:
        super().on_bar(bar, context)
        if len(self.records) == 2:
            raise RuntimeError("demonstration failure")


bar_1m, bar_3m = only_demo_bar_types()
runtime = only_demo_runtime("failure_demo")
subscription = OnlyBarSubscription((bar_1m, bar_3m))
failing = OnlyFailingDemoCluster(OnlyClusterConfig("cluster_a"), subscription)
healthy = OnlyDemoCluster(OnlyClusterConfig("cluster_b"), subscription)
runtime.add_cluster("engine", failing)
runtime.add_cluster("engine", healthy)
runtime.start()
for minute in range(3):
    runtime.process_bar(only_demo_bar(bar_1m, minute))
print(f"A={failing.state.value} calls={len(failing.records)}")
print(f"B={healthy.state.value} calls={len(healthy.records)}")
print(f"Runtime={runtime.state.value}")
