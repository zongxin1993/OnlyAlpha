//! Built-in financial indicators.

mod atr;
mod bollinger;
mod ema;
mod fixed_window;
mod macd;
mod obv;
mod roc;
mod rolling_statistics;
mod rolling_volatility;
mod rsi;
mod sma;
mod stochastic;
mod vwap;
mod wma;
mod zscore;

use onlyalpha_operators::RollingMean;
use std::num::NonZeroUsize;

pub use atr::{ATR, ATRPoint};
pub use bollinger::{Bollinger, BollingerPoint};
pub use ema::EMA;
pub use fixed_window::{FinancialInputError, FinancialValue};
pub use macd::{MACD, MACDCross, MACDPoint};
pub use obv::OBV;
pub use roc::{ROC, RateOfChangeError};
pub use rolling_statistics::StatisticalError;
pub use rolling_volatility::RollingVolatility;
pub use rsi::{RSI, RSIPoint, RSIZone};
pub use sma::{FixedScaleAveragePoint, InvalidFixedScaleInput, SMA};
pub use stochastic::{Stochastic, StochasticPoint};
pub use vwap::{UtcSessionVWAP, VWAP};
pub use wma::WMA;
pub use zscore::ZScore;

/// Simple moving average over prices supplied in chronological order at one fixed scale.
pub struct SimpleMovingAverage {
    mean: RollingMean,
}

#[derive(Debug, PartialEq, Eq)]
pub struct SimpleMovingAveragePoint {
    /// Price coefficient at the input scale.
    pub value: i128,
    /// Whether a full period of prices has been observed.
    pub ready: bool,
}

impl SimpleMovingAverage {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            mean: RollingMean::new(period),
        }
    }

    /// Reports the mean of the available prefix during warmup.
    pub fn push(&mut self, price: i128) -> SimpleMovingAveragePoint {
        let value = self.mean.push(price);
        SimpleMovingAveragePoint {
            value,
            ready: self.mean.is_full(),
        }
    }
}
