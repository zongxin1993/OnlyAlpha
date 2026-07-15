# Synthetic MACD Backtest Example

The runnable example is `examples/backtest_macd/`. Its deterministic three-day XSHG calendar path contains an initial flat
region, an uptrend that creates one confirmed MACD golden cross, a reversal that creates one death cross on the buy day, and
a stable tail. The buy fills on the next Bar through Virtual Broker. The same-day exit sees zero Cluster Allocation available
quantity; after Runtime settles the next Calendar TradingDay, the pending exit submits and fills on the next Bar.

The strategy reads MACD, open Orders and its own Allocation through Context. It does not read Managers, Broker state, future
Bars or system time. The default run generates 720 Bars, two filled Orders and two Broker Trades, then ends flat.

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python examples/backtest_macd/run.py \
  --config examples/backtest_macd/config.yaml \
  --output examples/backtest_macd/output
```

See the example README for configuration and adapter replacement guidance.
