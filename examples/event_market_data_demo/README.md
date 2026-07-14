# Event / MarketData Demo

```bash
python examples/event_market_data_demo/primary_1m_demo.py
python examples/event_market_data_demo/primary_3m_demo.py
python examples/event_market_data_demo/multi_cluster_demo.py
python examples/event_market_data_demo/replay_demo.py
```

示例使用固定 UTC 输入和上海 Calendar，依次证明默认最小主周期、显式 3m 主周期、两个 Cluster
共享唯一 3m Aggregator，以及序列化 Event 重放产生相同 Snapshot 和调用次数。
