//! Built-in financial indicators composed strictly from certified dual-kernel operators.

pub mod builtin;
pub mod compose;

pub use builtin::{
    MACDCross, RSIZone, UtcSessionVWAP, UtcSessionVwapState, atr, bollinger, ema, macd, obv, roc,
    rolling_volatility, rsi, sma, stochastic, vwap, wma, zscore,
};
pub use compose::{ComposedIndicator, ComposedStream, IndicatorState, Result};
pub use onlyalpha_operators::algebra::{Columns, Decimal, Error as IndicatorError};
