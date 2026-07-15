# Product Backtest

## Public API

```python
config = OnlyBacktestConfig.load("examples/backtest_macd/config.yaml")
runtime = OnlyBacktestRuntime.from_config(config)
result = runtime.run()
result.save("output")
```

`OnlyBacktestConfig` resolves UTC range, Instrument, Calendar sessions, source version/seed, BarType, indicator, Cluster,
account, commission and Virtual Broker configuration. `from_config` is the formal assembly boundary. `run` owns Runtime
lifecycle, historical replay, final invariant evaluation and closure.

## Fixed workflow

```text
HistoricalDataSource → HistoricalReplayService → BacktestClock → MarketDataProcessor
→ MarketDataPipeline → IndicatorPipeline → immutable Snapshot → Cluster → ctx.orders
→ Risk → Order → BrokerExecutionService → VirtualBroker → MatchingEngine
→ Broker queue → ExecutionProcessor → Position → Allocation → StrategyLedger → Account → Result
```

Only ReplayService advances the data-driven Clock. The product loop never reads DataFrames or online APIs and never calls
Pipeline, Cluster or Managers directly. Runtime marks Account and Strategy values from closed Bars before Broker
reconciliation and strategy dispatch. Calendar TradingDay changes invoke SettlementService; strategies only see the resulting
available Allocation.

## Result

`OnlyBacktestResult` contains run/data/execution/performance summaries, immutable final Position/Allocation/Ledger/Account
snapshots, Order and Broker Trade facts, strategy signals, invariant results and a deterministic fingerprint. `save` writes
the stable JSON files, `equity.csv` and `run_report.md`. It is deliberately not a full research analytics platform.

## Current limits

The first product assembler supports local synthetic closed TIME Bars, one CNY cash account, one ETF, Long-only Average Cost,
one MACD Cluster, fixed commission, no slippage and Next-Bar matching. Live/Paper adapters, portfolio analytics, multi-currency,
corporate actions, order-book matching and persistent recovery remain separate future work.
