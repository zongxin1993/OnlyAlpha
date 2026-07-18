# Product Backtest

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
immutable final Position/Allocation/Ledger/Account snapshots, Order and Broker Trade facts, generic Cluster/Factor/Indicator extensions, invariant results
and a deterministic fingerprint. Export writes below `user_data/runs/engine_id/run_id`; Runtime and Result do not write files.

## Current limits

Each first-phase Backtest Runtime supports local synthetic closed TIME Bars, one CNY cash account, one ETF, Long-only Average Cost,
one Cluster, fixed commission, no slippage and Next-Bar matching. One Engine coordinates multiple isolated Backtest runtimes. Live/Paper adapters, portfolio analytics, multi-currency,
corporate actions, order-book matching and persistent recovery remain separate future work.
