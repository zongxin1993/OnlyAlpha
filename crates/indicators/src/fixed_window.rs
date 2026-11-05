use crate::sma::{InvalidFixedScaleInput, coefficient, format_coefficient};
use num_bigint::BigInt;
use onlyalpha_operators::round_ratio;
use std::{fmt, num::NonZeroUsize};

const CARRIER_LIMIT: u128 = 10_u128.pow(38);
pub(super) const GUARD_FACTOR: i128 = 10_i128.pow(24);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FinancialInputError {
    InvalidDecimal,
    NegativeVolume,
    InvalidPriceRange,
    InvalidTimestampOrder,
}

impl From<InvalidFixedScaleInput> for FinancialInputError {
    fn from(_: InvalidFixedScaleInput) -> Self {
        Self::InvalidDecimal
    }
}

impl fmt::Display for FinancialInputError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidDecimal => "Indicator input must be an exact decimal at scale 12",
            Self::NegativeVolume => "Indicator volume must be nonnegative",
            Self::InvalidPriceRange => "Indicator price must be between low and high",
            Self::InvalidTimestampOrder => "Indicator timestamps must be strictly increasing",
        })
    }
}

impl std::error::Error for FinancialInputError {}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FinancialValue {
    Warmup,
    Missing,
    Undefined,
    OutOfRange,
    Ready(String),
}

impl FinancialValue {
    pub(super) fn from_coefficient(value: BigInt) -> Self {
        let Ok(value) = i128::try_from(value) else {
            return Self::OutOfRange;
        };
        if value.unsigned_abs() >= CARRIER_LIMIT {
            return Self::OutOfRange;
        }
        Self::Ready(format_coefficient(value))
    }
}

pub(super) fn volume(input: Option<&str>) -> Result<Option<i128>, FinancialInputError> {
    let input = input.map(coefficient).transpose()?;
    if input.is_some_and(|value| value < 0) {
        return Err(FinancialInputError::NegativeVolume);
    }
    Ok(input)
}

pub(super) fn validate_bar(
    high: Option<i128>,
    low: Option<i128>,
    close: Option<i128>,
) -> Result<(), FinancialInputError> {
    if high.zip(low).is_some_and(|(high, low)| high < low)
        || high.zip(close).is_some_and(|(high, close)| close > high)
        || low.zip(close).is_some_and(|(low, close)| close < low)
    {
        return Err(FinancialInputError::InvalidPriceRange);
    }
    Ok(())
}

/// Seeded with the arithmetic mean of the first period. Recurrence retains
/// 24 extra decimal places, with nearest-even rounding at each division.
pub(super) struct WilderMean {
    period: NonZeroUsize,
    count: usize,
    state: BigInt,
}

impl WilderMean {
    pub(super) fn new(period: NonZeroUsize) -> Self {
        Self {
            period,
            count: 0,
            state: BigInt::ZERO,
        }
    }

    pub(super) fn push(&mut self, coefficient: BigInt) -> Option<&BigInt> {
        let period = self.period.get();
        let value = coefficient * GUARD_FACTOR;
        if self.count < period {
            self.count += 1;
            self.state += value;
            if self.count < period {
                return None;
            }
            self.state = round_ratio(&self.state, &period.into());
        } else {
            let total = &self.state * (period - 1) + value;
            self.state = round_ratio(&total, &period.into());
        }
        Some(&self.state)
    }
}
