# OnlyAlpha Indicator Indicators

This official public package owns deterministic calculations with stable financial/descriptive meaning and no predictive Target
hypothesis. Its existing Indicator semantic identities are retained. Each named Feature remains a Calculation output port; this
package does not create a Feature Store or independent Feature identity authority.

The package exposes exact execution registrations through `onlyalpha.calculations` and the versioned
`onlyalpha.indicator.library` management provider through `onlyalpha.quant_assets`. A checkout can be installed with
`uv add --editable /path/to/indicators` or `python -m pip install -e /path/to/indicators`; released environments may use a wheel or private
index. Content changes require a new provider version, while semantic changes additionally require a new Indicator semantic version.

The financial family provides `wma@1`, `roc@1`, `vwap@1`, `obv@1`, and `stochastic@1`. VWAP consumes an explicit price series and volume series; it does not
choose close or typical price internally. Stochastic exposes named `k` and `d` output ports. Existing EMA, SMA, RSI, ATR, Bollinger,
Rolling Return, Rolling Volatility, ZScore, and MACD identities are unchanged.

Provider `onlyalpha.indicator.library` version **9** declares readiness contract V1 only for the exact
`onlyalpha.indicator.sma@1` RESEARCH registration. Its atomic `execute_with_readiness()` returns the existing exact Decimal
values with `PARTIAL/WARMUP_INCOMPLETE` before the complete window and `READY/NONE` thereafter. Period 1 is READY from
the first point; partial and ready numeric zero remain numeric zero. Legacy `execute()` is unchanged. This SPI is an
internal publication foundation, not a Product/API/Web workflow; other Indicator registrations do not claim readiness.

## Chart Study semantics

The exact registered backend advertises transient Chart Study presentation metadata;
this does not register additional formal Research readiness publication. SMA@1 remains
the only formal readiness V1 registration. All chart series carry backend-produced,
per-output readiness, including real zero values and explicitly undefined null values.

New numerical identities preserve the previous registrations:

- RSI@2 seeds Wilder mean gains/losses from `period` changes, then recursively smooths;
  it needs `period + 1` prices. All-flat prices produce neutral 50, no loss produces 100.
- ATR@3 seeds the mean of `period` true ranges (first range is high minus low), then
  uses Wilder smoothing. Normalized ATR is null at zero close and is not plotted on
  the price-unit ATR axis.
- MACD@2 retains the first-price EMA seed and DIF/DEA quantization, with histogram
  `DIF - DEA`. MACD@1 retains its historical doubled histogram.
- Stochastic@2 uses raw `%K` over `k_period`, then SMA `smooth_k` and SMA `d_period`;
  K and D become ready independently. A zero high-low range is undefined, not zero.
- VWAP@2 uses typical price `(high + low + close) / 3` and cumulative volume within
  explicit UTC day buckets of ordered integer `bar.start_ns`. It resets at the UTC day
  boundary; zero cumulative volume is undefined. This is labelled **UTC交易日**, not an
  exchange session calendar. VWAP@1 remains the original rolling price/volume definition.

Defaults select one explicit variant per Indicator, with SMA20, conventional Wilder
RSI14/ATR14, MACD12/26/9, Bollinger20/2, Stochastic14/3/3 and UTC-day VWAP.
Rolling volatility remains population standard deviation of prices, labelled **价格波动率**;
it is not annualized return volatility. Chart preview uses the same finite-series kernel
with the supplied unclosed bar; its transient/preview authority is owned by the Application.

Formula references: [TradingView RSI](https://www.tradingview.com/support/solutions/43000502338-relative-strength-index-rsi/),
[ATR](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/),
and [VWAP](https://www.tradingview.com/support/solutions/43000502018-volume-weighted-average-price-vwap/).
The explicit finite start, flat-RSI convention and UTC-day VWAP session above remain the registered semantics;
this is not a claim of point-for-point equivalence with every venue/session setting.
