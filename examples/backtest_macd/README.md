# Synthetic MACD Product Backtest

This demo validates the same fixed interfaces a real OnlyAlpha backtest uses. A versioned synthetic HistoricalDataSource is
replayed through the Backtest Clock and MarketData Processor; the Indicator Pipeline prepares MACD before the Cluster runs;
orders pass Risk, Virtual Broker Next-Bar matching, the Broker queue and ExecutionProcessor before Position, Allocation,
Strategy Ledger and Account change.

Run from the repository root with Python 3.12 and the project environment:

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run onlyalpha run \
  --config examples/backtest_macd/config.yaml
```

`config.yaml` and `config.json` have equivalent generic structures; `runtime.type` selects the Runtime. They define common
Runtime, Instrument, Calendar, strategy, account and broker settings while concrete parameters remain under `extensions`.
`synthetic_market.yaml` defines
the deterministic flat/up/down/flat price path, volume and fixed seed. The strategy buys a confirmed MACD golden cross and
requests an exit after a death cross. It reads only its Context views and never assumes submission means fill.

The Day-1 buy enters the formal unsettled bucket. A Day-1 death cross cannot sell because the Cluster Allocation reports zero
available quantity. Runtime advances settlement from the Calendar-derived TradingDay; the pending signal can then submit on
Day 2 without any T+1 branch in strategy code. Matching remains Next-Bar and the expected normal run has one buy, one sell,
two trades and a flat final Position.

`OnlyRuntimeResultExporter` writes the standard
`root_directory/engine_id/runtime_id/run-<fingerprint>/` layout with config, Runtime, market-data, execution, portfolio,
strategy, report and log sections. The Runtime never writes files. Re-running the same configuration and seed produces the
same Bars, signals, IDs, snapshots and business fingerprint.

To use Parquet, register a future `OnlyDataSourceFactory`; do not read Parquet from strategy or call Pipeline directly. To
replace the strategy, register another `OnlyStrategyFactory`. Broker behavior is selected through `OnlyBrokerFactoryRegistry`;
execution updates must still enter Runtime's queue and ExecutionProcessor.

Known limits: this example is one CNY cash account, one ETF, Long-only, 1-minute closed Bars, fixed commission and Next-Bar
matching. It is not a research analytics suite, live adapter, order-book simulator or corporate-action engine.
