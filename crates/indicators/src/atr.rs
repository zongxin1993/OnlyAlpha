use crate::{
    fixed_window::{FinancialInputError, FinancialValue, GUARD_FACTOR, WilderMean, validate_bar},
    sma::{QUANTUM, coefficient},
};
use num_bigint::{BigInt, Sign};
use onlyalpha_operators::round_ratio;
use std::num::NonZeroUsize;

/// Wilder's average true range, seeded by the first full window of ranges.
pub struct ATR {
    previous_close: Option<i128>,
    mean: WilderMean,
}

#[derive(Debug, PartialEq, Eq)]
pub struct ATRPoint {
    pub atr: FinancialValue,
    pub normalized_atr: FinancialValue,
}

impl ATR {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            previous_close: None,
            mean: WilderMean::new(period),
        }
    }

    /// The first true range is high minus low. Later ranges include gaps
    /// from the previous close. A zero current close has no normalized value.
    pub fn push(
        &mut self,
        high: &str,
        low: &str,
        close: &str,
    ) -> Result<ATRPoint, FinancialInputError> {
        let (high, low, close) = (coefficient(high)?, coefficient(low)?, coefficient(close)?);
        validate_bar(Some(high), Some(low), Some(close))?;
        let mut range = BigInt::from(high) - low;
        if let Some(previous) = self.previous_close {
            range = range
                .max(absolute_difference(high, previous))
                .max(absolute_difference(low, previous));
        }
        self.previous_close = Some(close);
        let Some(mean) = self.mean.push(range) else {
            return Ok(ATRPoint {
                atr: FinancialValue::Warmup,
                normalized_atr: FinancialValue::Warmup,
            });
        };
        let guard = BigInt::from(GUARD_FACTOR);
        let normalized_atr = if close == 0 {
            FinancialValue::Undefined
        } else {
            let numerator = mean * QUANTUM * close.signum();
            let denominator = BigInt::from(close.unsigned_abs()) * &guard;
            FinancialValue::from_coefficient(round_ratio(&numerator, &denominator))
        };
        Ok(ATRPoint {
            atr: FinancialValue::from_coefficient(round_ratio(mean, &guard)),
            normalized_atr,
        })
    }
}

fn absolute_difference(left: i128, right: i128) -> BigInt {
    let difference = BigInt::from(left) - right;
    if difference.sign() == Sign::Minus {
        -difference
    } else {
        difference
    }
}
