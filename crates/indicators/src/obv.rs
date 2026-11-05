use crate::{
    fixed_window::{FinancialInputError, FinancialValue, volume},
    sma::coefficient,
};
use num_bigint::BigInt;
use std::cmp::Ordering;

/// On-balance volume from ordered close and volume observations.
#[derive(Default)]
pub struct OBV {
    state: State,
}

#[derive(Default)]
enum State {
    #[default]
    Fresh,
    Active {
        previous: i128,
        total: BigInt,
    },
    Missing,
}

impl OBV {
    pub fn new() -> Self {
        Self::default()
    }

    /// The first complete observation yields zero. A missing observation makes
    /// the cumulative series unavailable for the remainder of this instance.
    pub fn push(
        &mut self,
        close: Option<&str>,
        amount: Option<&str>,
    ) -> Result<FinancialValue, FinancialInputError> {
        let close = close.map(coefficient).transpose()?;
        let amount = volume(amount)?;
        let Some((close, amount)) = close.zip(amount) else {
            self.state = State::Missing;
            return Ok(FinancialValue::Missing);
        };

        match &mut self.state {
            State::Fresh => {
                self.state = State::Active {
                    previous: close,
                    total: BigInt::ZERO,
                };
                Ok(FinancialValue::from_coefficient(BigInt::ZERO))
            }
            State::Active { previous, total } => {
                match close.cmp(previous) {
                    Ordering::Greater => *total += amount,
                    Ordering::Less => *total -= amount,
                    Ordering::Equal => {}
                }
                *previous = close;
                Ok(FinancialValue::from_coefficient(total.clone()))
            }
            State::Missing => Ok(FinancialValue::Missing),
        }
    }
}
