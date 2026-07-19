# Product Backtest

Deterministic Scenario 是 Backtest 外层消费者，不是 Backtest 专用 API。人工 Bar 仍须走 DataSource、Replay、Pipeline 和
Strategy dispatch；Action 仍经公共 `ctx.orders`。当前 Scenario Runner 尚未接通，禁止以 `process_bar()` 组件测试宣称完成。

## Product API

```python
engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("onlyalpha"), Path("user_data")))
engine.add_cluster_from_file("../OnlyAlpha-plugins/clusters/my_cluster/config.yaml")
result = engine.run()
```

`OnlyClusterRunConfig` parses common fields and Cluster-owned Strategy/Factor import specs. Runtime-specific, Synthetic and Virtual Broker
parameters are parsed by their concrete factories；Indicator 参数由 Factor Config 解析。`OnlyEngine` is the sole product boundary; Backtest `run()` owns
historical replay and final invariant evaluation, while `OnlyEngineResultExporter` writes through `OnlyUserDataLayout`.

## Fixed workflow

```text
HistoricalDataSource → HistoricalReplayService → BacktestClock → MarketDataProcessor
→ MarketDataPipeline → immutable Snapshot → Cluster Factory
→ Factor-created Indicator → Factor Snapshot/Score → Strategy → ctx.orders
→ Risk → Order → BrokerExecutionService → VirtualBroker → MatchingEngine
→ Broker queue → ExecutionProcessor → Position → Allocation → StrategyLedger → Account → Result
```

Only ReplayService advances the data-driven Clock. The product loop never reads DataFrames or online APIs and never calls
Pipeline, Cluster or Managers directly. Runtime marks Account and Strategy values from closed Bars before Broker
reconciliation and strategy dispatch. Calendar TradingDay changes invoke SettlementService; strategies only see the resulting
available Allocation.

## Result

`OnlyBacktestResult` implements the common `OnlyRuntimeResult` view and contains run/data/execution/performance summaries,
immutable final Position/Allocation/Ledger/Account snapshots, standard facts, structured diagnostics, generic extensions and stable fingerprints. Engine 在 Runtime 完成后依次调用纯 Analytics、原子 Artifact Writer 与 Report；Runtime 和 Result 不写文件。完整边界见 `results_framework.md`。

## Current limits

First-phase Backtest 支持 Synthetic 或插件历史 Bar、Virtual Broker、Long-only 持仓、固定费用和 Next-Bar 撮合；兼容 Cluster 可共享 Runtime，不兼容组保持隔离。高级组合分析、跨币种换算、公司行为、订单簿撮合和持久恢复仍属后续工作。
