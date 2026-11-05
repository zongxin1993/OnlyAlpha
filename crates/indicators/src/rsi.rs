use crate::{
    fixed_window::{FinancialInputError, FinancialValue, WilderMean},
    sma::{QUANTUM, coefficient},
};
use num_bigint::{BigInt, Sign};
use onlyalpha_operators::round_ratio;
use std::num::NonZeroUsize;

/// Wilder's relative strength index on successive price changes.
pub struct RSI {
    previous: Option<i128>,
    gains: WilderMean,
    losses: WilderMean,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RSIZone {
    Oversold,
    Neutral,
    Overbought,
}

#[derive(Debug, PartialEq, Eq)]
pub struct RSIPoint {
    pub value: FinancialValue,
    pub zone: RSIZone,
}

impl RSI {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            previous: None,
            gains: WilderMean::new(period),
            losses: WilderMean::new(period),
        }
    }

    /// Needs one baseline price followed by a complete window of changes.
    /// A flat seed yields 50, a gain without losses yields 100.
    pub fn push(&mut self, price: &str) -> Result<RSIPoint, FinancialInputError> {
        let price = coefficient(price)?;
        let Some(previous) = self.previous.replace(price) else {
            return Ok(warmup());
        };
        let change = BigInt::from(price) - previous;
        let (gain, loss) = if change.sign() == Sign::Minus {
            (BigInt::ZERO, -change)
        } else {
            (change, BigInt::ZERO)
        };
        let (Some(gain), Some(loss)) = (self.gains.push(gain), self.losses.push(loss)) else {
            return Ok(warmup());
        };
        let total = gain + loss;
        if total == BigInt::ZERO {
            return Ok(RSIPoint {
                value: FinancialValue::from_coefficient(BigInt::from(50 * QUANTUM)),
                zone: RSIZone::Neutral,
            });
        }
        let percentage = gain * 100;
        let zone = if percentage < &total * 30 {
            RSIZone::Oversold
        } else if percentage > &total * 70 {
            RSIZone::Overbought
        } else {
            RSIZone::Neutral
        };
        Ok(RSIPoint {
            value: FinancialValue::from_coefficient(round_ratio(&(percentage * QUANTUM), &total)),
            zone,
        })
    }
}

fn warmup() -> RSIPoint {
    RSIPoint {
        value: FinancialValue::Warmup,
        zone: RSIZone::Neutral,
    }
}
