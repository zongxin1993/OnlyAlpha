use crate::sma::{QUANTUM, coefficient, format_coefficient};
use onlyalpha_operators::fractional_change;
use std::{
    collections::VecDeque,
    fmt,
    num::{NonZeroI128, NonZeroU128, NonZeroUsize},
};

const OUTPUT_LIMIT: u128 = 10_u128.pow(38);
const OUTPUT_QUANTUM: NonZeroU128 = NonZeroU128::new(QUANTUM as u128).unwrap();

#[derive(Debug, PartialEq, Eq)]
pub enum RateOfChangeError {
    InvalidPrice,
    OutOfRange,
}

impl fmt::Display for RateOfChangeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidPrice => "ROC input must be an exact decimal at scale 12",
            Self::OutOfRange => "ROC result exceeds the fixed-point coefficient range",
        })
    }
}

impl std::error::Error for RateOfChangeError {}

/// Rate of change expressed as a fractional return over a fixed number of bars.
pub struct ROC {
    period: NonZeroUsize,
    prices: VecDeque<Option<i128>>,
}

impl ROC {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            period,
            prices: VecDeque::new(),
        }
    }

    /// Missing bars advance the window. A missing or zero reference, a
    /// missing current value yields no value. An error leaves the window unchanged.
    pub fn push(&mut self, price: Option<&str>) -> Result<Option<String>, RateOfChangeError> {
        let price = price
            .map(coefficient)
            .transpose()
            .map_err(|_| RateOfChangeError::InvalidPrice)?;
        let full = self.prices.len() == self.period.get();
        let reference = if full {
            self.prices
                .front()
                .copied()
                .flatten()
                .and_then(NonZeroI128::new)
        } else {
            None
        };
        let value = match price.zip(reference) {
            Some((current, reference)) => Some(
                fractional_change(current, reference, OUTPUT_QUANTUM)
                    .filter(|value| value.unsigned_abs() < OUTPUT_LIMIT)
                    .map(format_coefficient)
                    .ok_or(RateOfChangeError::OutOfRange)?,
            ),
            None => None,
        };
        if full {
            self.prices.pop_front();
        }
        self.prices.push_back(price);
        Ok(value)
    }
}
