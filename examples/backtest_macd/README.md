# Synthetic MACD Product Backtest

This demo validates the same fixed interfaces a real OnlyAlpha backtest uses. A versioned synthetic HistoricalDataSource is
replayed through the Backtest Clock and MarketData Processor; the Indicator Pipeline prepares MACD before the Cluster runs;
orders pass Risk, Virtual Broker Next-Bar matching, the Broker queue and ExecutionProcessor before Position, Allocation,
Strategy Ledger and Account change.

Run from the repository root with Python 3.12 and the project environment:

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python examples/backtest_macd/run.py \
  --config examples/backtest_macd/config.yaml \
  --output examples/backtest_macd/output
```

`config.yaml` defines Runtime, Instrument, Calendar, strategy, account and broker settings. `synthetic_market.yaml` defines
the deterministic flat/up/down/flat price path, volume and fixed seed. The strategy buys a confirmed MACD golden cross and
requests an exit after a death cross. It reads only its Context views and never assumes submission means fill.

The Day-1 buy enters the formal unsettled bucket. A Day-1 death cross cannot sell because the Cluster Allocation reports zero
available quantity. Runtime advances settlement from the Calendar-derived TradingDay; the pending signal can then submit on
Day 2 without any T+1 branch in strategy code. Matching remains Next-Bar and the expected normal run has one buy, one sell,
two trades and a flat final Position.

The result API writes `result.json`, orders, trades, positions, allocations, ledgers, accounts, `equity.csv` and
`run_report.md`. The fingerprint covers the public deterministic result. Re-running the same configuration and seed produces
the same Bars, signals, IDs, snapshots and fingerprint.

To use Parquet, select a future product assembler configuration that supplies `OnlyParquetHistoricalDataSource`; do not read
Parquet from strategy or call Pipeline directly. To replace the strategy, register another formal `OnlyCluster` through the
assembler. Broker behavior can be replaced by another implementation of the same Broker Ports; execution updates must still
enter Runtime's queue and ExecutionProcessor.

Known limits: this example is one CNY cash account, one ETF, Long-only, 1-minute closed Bars, fixed commission and Next-Bar
matching. It is not a research analytics suite, live adapter, order-book simulator or corporate-action engine.
