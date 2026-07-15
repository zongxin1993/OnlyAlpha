# Synthetic MACD Product Backtest Gap Analysis

Date: 2026-07-15

## Scope and architectural baseline

The repository already has the production boundaries needed by a complete deterministic backtest: Runtime-owned Clock,
MarketData Processor and Pipeline, HistoricalReplayService, restricted Cluster Context, synchronous Risk and Order services,
an independent Virtual Broker and Matching Engine, the Broker inbound queue, the sole ExecutionProcessor, Position,
Allocation, Strategy Ledger and Account. ADR 0001 through 0017 make these boundaries mandatory.

This task will compose those components. It will not add a second execution workflow, a test-only Runtime, or a new financial
domain component.

## 1. Formal backtest entry

Current state:

- `OnlyBacktestRuntime` owns and composes the complete data and execution resources.
- Its public lifecycle is `register → add_cluster → start → replay → stop/close`.
- There is no `OnlyBacktestConfig`, `OnlyBacktestRuntime.from_config(config)`, or zero-argument product `run()` API.
- Existing complete examples use `OnlyIntegrationEnvironment`, which is an acceptance fixture rather than a user product API.

Gap:

- Add a typed, immutable, YAML-loadable backtest configuration.
- Add one formal assembler behind `OnlyBacktestRuntime.from_config(config)`.
- Make Runtime own lifecycle, replay and result construction through `run()` without exposing Managers to the demo.

## 2. Data path

Current state:

```text
OnlyHistoricalDataSource
→ OnlyHistoricalReplayService
→ OnlyBacktestClock
→ OnlyMarketDataProcessor
→ OnlyMarketDataPipeline
```

This path is already formal and deterministic. `OnlyHistoricalReplayService` is the only data-driven Clock owner, and
`OnlyMarketDataProcessor` is the only Pipeline ingress after replay.

Gap:

- No synthetic implementation of the existing `OnlyHistoricalDataSource` Port.
- No typed deterministic segment/noise/volume configuration bound to Instrument and TradingCalendar.
- Runtime's historical replay convenience method is unnecessarily narrowed to the in-memory source concrete type and must
  accept the formal Port.

## 3. Indicator and strategy path

Current state:

- Runtime owns `OnlyIndicatorPipeline`, updates it before immutable Snapshot creation, and Cluster reads only declared
  indicator values through `ctx.market_data`.
- The generic indicator value contract currently handles scalar values only.
- No MACD implementation or reusable MACD Cluster exists.

Gap:

- Add immutable `OnlyMacdSnapshot` and deterministic Decimal EMA/MACD state.
- Extend the indicator Snapshot serialization boundary for the named immutable MACD value without exposing indicator state.
- Add a formal `OnlyMacdExampleCluster` which uses only `ctx`, checks its own open orders and Allocation, and submits orders
  without assuming a fill.

## 4. Execution path

Current state:

```text
Cluster → Order → Risk → BrokerExecutionService → VirtualBroker → MatchingEngine
→ Broker inbound queue → ExecutionProcessor → Position → Allocation → Strategy Ledger → Account
```

The Virtual Broker has independent stores and emits only normalized updates. Runtime drains those updates through its sole
ExecutionProcessor. The normal product path does not need a new execution abstraction.

Gap:

- Product assembly must always enable `OnlyVirtualBrokerGateway` and must reject a configuration that asks for a manual or
  placeholder fill path.
- Local T+1 settlement must be driven at a Calendar-derived TradingDay transition as part of Runtime orchestration; it cannot
  be strategy logic.

## 5. Result and output

Current state:

- Components expose immutable snapshots and audit histories.
- Integration has a fixture-specific final snapshot/report builder.
- There is no formal `OnlyBacktestResult`, deterministic fingerprint, or exporter.

Gap:

- Add immutable run/data/execution/performance summaries and final public snapshots.
- Build the result only after replay completes and invariants are evaluated.
- Export result, orders, trades, positions, allocations, ledgers, accounts, equity and a run report through a formal result
  API; the demo must not read Manager internals.

## 6. Required implementation boundary

The minimum complete change is:

1. synthetic source and configuration under the existing data Port;
2. MACD under the existing Indicator Pipeline;
3. MACD Cluster under the existing Context API;
4. a thin backtest application/assembly package used by `OnlyBacktestRuntime.from_config(...).run()`;
5. immutable result/export APIs, product-style demo, automated integration scenarios and deterministic replay;
6. ADR 0018 and documentation updates.

No Manager semantics, Domain state model, direct Pipeline/Cluster invocation, manual fill, online data dependency, or
test-only business path is required or permitted.
