from zoneinfo import ZoneInfo

from common import only_demo_bar, only_demo_bar_types, only_demo_runtime

from onlyalpha.cluster.base import OnlyClusterConfig
from onlyalpha.cluster.demo import OnlyDemoCluster
from onlyalpha.market_data.subscriptions import OnlyBarSubscription

bar_1m, bar_3m = only_demo_bar_types()
runtime = only_demo_runtime("backtest_001")
cluster = OnlyDemoCluster(OnlyClusterConfig("demo_001"), OnlyBarSubscription((bar_1m, bar_3m)))
runtime.add_cluster("engine", cluster)
runtime.start()
for minute in range(3):
    runtime.process_bar(only_demo_bar(bar_1m, minute))

print("Runtime: backtest_001")
print("Cluster: demo_001")
for record in cluster.records:
    updated = ",".join(f"{item.specification.step}m" for item in sorted(record.updated_bar_types, key=str))
    print(f"{record.ts_event_ns} on_bar primary={record.primary_bar_type.specification.step}m updated={{{updated}}}")
if cluster.records[-1].latest_3m is not None:
    bar = cluster.records[-1].latest_3m
    market_tz = ZoneInfo("Asia/Shanghai")
    print(f"latest_3m={bar.bar_start.astimezone(market_tz):%H:%M}-{bar.bar_end.astimezone(market_tz):%H:%M}")
