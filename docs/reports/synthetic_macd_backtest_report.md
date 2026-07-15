# Synthetic MACD Product Backtest Acceptance Report

- Date: 2026-07-15
- Scope: configuration-driven synthetic MACD backtest product demo
- Final conclusion: **ACCEPTED**

## 1. Added and modified assets

Added production packages:

- `src/onlyalpha/data/synthetic.py`: formal calendar-aware `OnlyHistoricalDataSource` implementation;
- `src/onlyalpha/indicator/macd.py`: Decimal MACD config, indicator and immutable snapshot;
- `src/onlyalpha/strategies/macd.py`: formal Context-only example Cluster;
- `src/onlyalpha/backtest/`: typed configuration, assembler, run plan, immutable result and exporter.

Added product example:

- `examples/backtest_macd/config.yaml` and `synthetic_market.yaml`;
- `run.py`, strategy import, expected result, README and output directory contract.

Added automated acceptance:

- synthetic source, exact MACD and strategy architecture tests under `tests/examples/`;
- product vertical slice, T+1, fixed-seed noise, product API/export and 100-replay tests under `tests/integration/`;
- unified Integration scenario 034; scenarios 001–033 are unchanged and retained.

Updated Runtime to perform Calendar-derived local settlement and closed-Bar Account/Strategy mark-to-market before Broker
reconciliation and strategy dispatch. Updated indicator Snapshot serialization for explicit immutable structured values. Added
`docs/backtest.md`, example documentation, gap analysis, ADR 0018 and the required architecture/testing documentation rules.

## 2. Formal product API and assembly

```python
config = OnlyBacktestConfig.load("examples/backtest_macd/config.yaml")
runtime = OnlyBacktestRuntime.from_config(config)
result = runtime.run()
result.save("output")
```

`OnlyBacktestRuntimeAssembler` is the sole configuration assembly boundary. It registers the Instrument, Calendar, MACD
Indicator, MACD Cluster, Synthetic Source configuration and Virtual Broker configuration. `run.py` does not instantiate or
call any Manager. Runtime owns lifecycle, Replay, Broker queue processing, final invariant evaluation and close.

The production import graph remains acyclic: product assembly depends on Runtime; Runtime does not statically depend on the
product package.

## 3. Synthetic HistoricalDataSource

`OnlySyntheticHistoricalDataSource` implements the existing `OnlyHistoricalDataSource` Port. It emits normalized
`OnlyMarketDataInboundUpdate[OnlyBarUpdate]` facts with Source ID, stable Sequence, Data Version, UTC `ts_event/ts_init`,
quality and deterministic Update ID.

Generation inputs are Instrument price/quantity increments, TradingCalendar sessions, TIME BarType, deterministic price
segments, volume model, noise model and fixed seed. Supported segments are FLAT, UPTREND, DOWNTREND, OSCILLATION, GAP_UP,
GAP_DOWN, VOLATILITY_EXPANSION and VOLATILITY_CONTRACTION. The implementation uses integer-state deterministic noise and
Decimal quantization; it does not use unconstrained financial floats.

The accepted default dataset:

- Source: `synthetic-cn-etf`;
- Version: `macd-demo-v1`;
- Seed: `20260715`;
- Instrument: `TESTETF.XSHG`;
- Calendar: two XSHG continuous sessions with the midday break;
- UTC range: 2026-01-05 01:30 through 2026-01-08 07:01;
- generated Bars: **720**;
- processed records: **720**;
- duplicate records: **0**;
- gap detections: **5**, all expected lunch/overnight Session transitions;
- invalid OHLCV/increment/non-session Bars: **0**.

## 4. MACD Indicator and strategy

`OnlyMacdIndicator` uses deterministic Decimal EMAs and accepts only closed, monotonic Bars. `OnlyMacdSnapshot` contains DIF,
DEA, Histogram, sample count, ready state and event time and round-trips through immutable MarketData Snapshot serialization.
Warmup is explicit; the default strategy cannot trade before sample 8.

`OnlyMacdExampleCluster`:

- implements the formal `OnlyCluster` lifecycle;
- declares its Bar and MACD subscription during initialization;
- reads only `ctx.market_data`, `ctx.orders` and its own `ctx.positions.cluster` for decisions;
- checks Cluster-local open orders before submission;
- submits MARKET requests only through `ctx.orders`;
- does not access Manager, Gateway, EventBus, Processor or system time;
- does not assume submit means Accepted or Filled;
- does not contain a T+1 rule or date branch.

Accepted signal counts:

- golden crosses traded: **1**;
- death crosses / pending exits completed: **1**;
- same-day death cross blocked by zero Allocation availability: **1**;
- orders before Warmup: **0**.

## 5. Complete vertical slice

The observed normal path is:

```text
SyntheticHistoricalDataSource
→ HistoricalReplayService
→ BacktestClock
→ MarketDataProcessor
→ MarketDataPipeline
→ IndicatorPipeline / MACD
→ immutable Snapshot
→ OnlyMacdExampleCluster
→ ctx.orders.submit
→ RiskService
→ OrderManager
→ BrokerExecutionService
→ OnlyVirtualBrokerGateway
→ OnlyNextBarMatchingEngine
→ Broker inbound queue
→ OnlyExecutionProcessor
→ PositionManager
→ PositionAllocationManager
→ StrategyLedgerManager
→ AccountManager
→ OnlyBacktestResult
```

No normal scenario directly calls Pipeline, Cluster, Broker, ExecutionProcessor or any Manager workflow method. No fill is
manually constructed. Broker updates enter the Runtime queue before Processor application.

## 6. T+1 behavior

The Day-1 BUY fills into UNSETTLED Position and Allocation buckets. The Day-1 death cross observes Cluster available quantity
zero and records a pending exit without submitting an invalid SELL. On the next Calendar-derived TradingDay, Runtime invokes
SettlementService before Broker reconciliation and Cluster dispatch. The strategy then sees available quantity 1000 and
submits the pending SELL; Virtual Broker fills it on the next Bar.

T+1 is therefore enforced by Settlement/Position/Allocation/Risk boundaries, not by strategy hardcoding.

## 7. Orders, trades and final financial result

- BUY: quantity 1000, Next-Bar fill price 10.04, status FILLED;
- SELL: quantity 1000, Next-Bar fill price 9.00, status FILLED;
- order count: **2**;
- rejected orders: **0**;
- Broker trade count: **2**;
- fixed fees: **2.00 CNY**;
- final Account Position: flat;
- final Cluster Allocation: flat;
- realized PnL: **-1040.00 CNY**;
- unrealized PnL: **0.00 CNY**;
- final Account cash: **998958.00 CNY**;
- final Account equity: **998958.00 CNY**;
- final Strategy Ledger cash/equity: **998958.00 CNY**;
- maximum drawdown: **-0.00299513**.

The loss is intentional and deterministic: the scenario is designed to prove a same-day T+1 exit block and next-day exit,
not to optimize strategy profitability.

## 8. Result and output

`OnlyBacktestResult` contains run, data, execution and performance summaries; immutable final Position, Allocation, Ledger and
Account snapshots; Order and Broker Trade facts; strategy signals; invariant results and fingerprint. `save()` produced and
validated:

```text
result.json
orders.json
trades.json
positions.json
allocations.json
ledgers.json
accounts.json
equity.csv
run_report.md
```

The demo never reads Manager-private dictionaries to build these files.

## 9. Invariants

Final checks passed:

- Account equity equals cash plus position market value;
- Strategy Ledger cash and PnL equity views match;
- Account Position equals Allocation sum plus Unallocated;
- filled quantity never exceeds order quantity;
- no negative Account/Risk/Position reservation;
- no active Risk reservation remains;
- no blocking Execution failure or blocking reconciliation remains;
- final Account and Strategy state agree while remaining independent objects;
- no future Bar enters MACD or Snapshot;
- all source/event/Clock timestamps are UTC;
- same configuration produces the same result.

Virtual Broker settlement emits one non-blocking Position availability reconciliation warning. It is retained in Processor
Audit and the deterministic fingerprint; it neither overwrites local trade history nor blocks the account. This is expected
under the current field-level authority model and is not treated as a successful Trade event or hidden.

## 10. Deterministic replay

The product replay test executes a baseline plus **100 repeated complete runs**. The fingerprint covers:

- MarketData audit, update identity, Source sequence and quality;
- HistoricalReplay Clock/update order;
- every MACD snapshot and strategy signal;
- Order and Trade IDs and snapshots;
- ExecutionProcessor audit and mutation order;
- stable Event type/source/sequence/time/scope projection (random envelope UUIDs excluded);
- Position, Allocation, Ledger, Account and final result.

All repetitions matched:

```text
9a001bcf340a1c155453804ffe2dd90a85883094a9bb3ca445c68d31a49b3f22
```

The existing unified vertical slice also completed its independent baseline plus 100-repeat replay.

## 11. Historical regression and quality gates

Executed `bash scripts/run_component_validation.sh` after all changes:

- all tests: **263 passed in 97.61s**;
- all integration tests: **49 passed in 93.74s**;
- unified integration demo: **34/34 PASS**;
- explicit historical vertical-slice replay: **1 passed in 46.74s** (baseline plus 100 repeats);
- product deterministic replay: passed inside both full and integration suites (baseline plus 100 repeats in each suite);
- Ruff: **All checks passed**;
- Ruff format: **412 files already formatted**;
- strict Mypy: **192 source files, 0 issues**;
- skipped/deleted/relaxed historical scenarios: **0**.

## 12. Known limitations

- One CNY cash account, one ETF, one MACD Cluster and one external 1-minute BarType;
- Long-only Average Cost and current T+1 bucket semantics;
- fixed commission, no slippage and Next-Bar OHLC matching;
- no persistent Runtime transaction/recovery store;
- no complete research performance series or portfolio analytics;
- no corporate actions, multi-currency, margin, short, futures/options or order-book queue model;
- the first assembler selects Synthetic Source only; Parquet already implements the same HistoricalDataSource Port but is not
  yet selectable by this example configuration.

These are declared product-scope limits, not bypasses of the accepted workflow.

## 13. Veto audit and conclusion

No veto condition is present:

- Synthetic Source implements the formal HistoricalDataSource;
- Demo does not call Pipeline or Cluster directly;
- Demo does not assemble/call Managers or manually construct fills;
- every fill crosses VirtualBroker and ExecutionProcessor;
- strategy has no Manager access, future-data access or system-time access;
- Warmup and T+1 behavior are enforced at the correct boundaries;
- seed and version are fixed;
- formal configuration, Runtime and Result APIs run successfully;
- all historical scenarios and both 100-repeat replay suites pass.

OnlyAlpha now demonstrates a complete, reusable core backtest loop through product-style interfaces. Entry into the next
approved phase is allowed without adding any post-task feature to this scope.

**Final conclusion: ACCEPTED**
