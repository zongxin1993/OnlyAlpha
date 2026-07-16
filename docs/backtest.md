# Product Backtest

## Public API

```python
config = OnlyRunConfig.load("examples/configs/backtest/macd/run.yaml")
service = only_default_run_service()
result = service.run(config)
```

`OnlyRunConfig` parses common fields and Cluster-owned Strategy/Factor import specs. Runtime-specific, Synthetic and Virtual Broker
parameters are parsed by their concrete factories；Indicator 参数由 Factor Config 解析。`OnlyEngineRunService` is the public boundary; Backtest `run()` owns
historical replay and final invariant evaluation, while `OnlyRuntimeResultExporter` owns the standard output layout.

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
and a deterministic fingerprint. Export writes below `root/engine_id/runtime_id/run_id`; Runtime and Result do not write files.

## Current limits

The first product assembler supports local synthetic closed TIME Bars, one CNY cash account, one ETF, Long-only Average Cost,
one enabled Cluster, fixed commission, no slippage and Next-Bar matching. Live/Paper adapters, portfolio analytics, multi-currency,
corporate actions, order-book matching and persistent recovery remain separate future work.
