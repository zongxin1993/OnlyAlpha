# Product Backtest

内建 `scenario-exact` 通过 DataSource SPI 和正式 Historical Replay 提供 exact bars；Action Strategy 只经 `ctx.orders` 下单。

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

`OnlyBacktestResult` implements the common `OnlyRuntimeResult` view. Schema v3 separates Account-authoritative
`runtime_performance` from every Ledger-authoritative `cluster_performance`. It also contains the full Account and Cluster
equity timelines, one `final_account`, final Position/Allocation/Ledger snapshots, committed facts, structured diagnostics,
final Runtime/Ledger reconciliation and stable fingerprints. The ambiguous `performance` and `final_accounts` fields were
deleted without aliases. Engine 在 Runtime 完成后依次调用纯 Analytics、原子 Artifact Writer 与 Report；Runtime 和 Result 不写文件。

## Current limits

First-phase Backtest 支持一个共享 Account、一个 Base Currency 和多个显式 `FIXED_CAPITAL` Cluster。单 Cluster 可省略
capital，此时等于 Account initial cash；多 Cluster 必须逐个声明，且精确加总为 Account initial cash。当前不支持
SHARED_POOL、动态再分配、多 Account、FX、System Ledger 或 TWR/MWR。中途逐点对账仍是后续工作；当前正式结果执行最终
Account/Ledger 对账并在不一致时失败。
