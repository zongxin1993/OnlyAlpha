# ADR 0018: Product-style demo and synthetic backtest

- Status: Superseded by ADR 0019
- Date: 2026-07-15
- Modules: backtest, runtime, data, indicator, cluster, virtual_broker, execution

## Context

Component tests and a manually driven Integration fixture prove individual boundaries, but do not fully represent how a user
runs an OnlyAlpha backtest. A product example must prove that configuration, assembly, lifecycle, historical replay, strategy,
execution and result output use the same fixed interfaces as the main system.

## Decision

- Product demos use `OnlyBacktestConfig.load → OnlyBacktestRuntime.from_config → run → OnlyBacktestResult.save`.
- Demo scripts do not construct Managers or invoke their workflow methods.
- `OnlySyntheticHistoricalDataSource` implements the existing `OnlyHistoricalDataSource` Port and emits versioned normalized
  updates; it has no Pipeline, Cluster or Clock reference.
- Example strategies implement `OnlyCluster`, read only restricted Context views and submit only through `ctx.orders`.
- Indicators are Runtime-owned, update before immutable Snapshot creation and may expose explicitly serializable immutable
  structured values such as `OnlyMacdSnapshot`.
- Historical data always crosses ReplayService, MarketDataProcessor and MarketDataPipeline.
- Executions always cross VirtualBroker, MatchingEngine, Broker inbound queue and the sole ExecutionProcessor.
- Calendar-derived TradingDay transitions drive SettlementService; strategy code only observes Allocation availability.
- The formal result contains immutable public snapshots and a fingerprint over Bars/Audit, Clock, MACD, execution audit,
  stable event sequence and final state.
- Product demos are executable documentation and automated integration acceptance assets.

## Rejected alternatives

- manually constructing Managers in the demo;
- directly calling Pipeline or Cluster;
- constructing fills or mutating Position/Ledger/Account from example code;
- test-only Strategy or Runtime APIs;
- strategy-side T+1 calendar branches;
- online API calls inside deterministic replay;
- random data without an explicit fixed seed;
- fixture-specific final result assembly.

## Consequences

The product entry is intentionally narrow and currently assembles one CNY cash account, one ETF, one MACD Cluster, local
synthetic Bars, Next-Bar matching and fixed commission. New sources, strategies and broker models can replace adapters behind
the same Ports; the product entry cannot introduce a parallel workflow.

Runtime marks Account and Strategy views on every closed Bar before Broker reconciliation and strategy dispatch, and settles
local T+1 buckets on Calendar-derived TradingDay transitions. Non-blocking Broker availability reconciliation warnings remain
auditable and do not masquerade as execution failures.

## Validation

Synthetic source, exact MACD, Context boundary, product API, T+1, fixed-seed noise, complete vertical slice, all historical
tests, 100 deterministic product replays, the unified 34-scenario demo, Ruff and strict Mypy validate this decision.
