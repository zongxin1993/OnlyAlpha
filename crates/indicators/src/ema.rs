use crate::sma::{FixedScaleAveragePoint, InvalidFixedScaleInput, coefficient, format_coefficient};
use num_bigint::BigInt;
use onlyalpha_operators::round_ratio;
use std::num::NonZeroUsize;

const GUARD_QUANTUM: u128 = 10_u128.pow(24);

/// Exponential moving average seeded by the first input.
pub struct EMA {
    state: ExponentialState,
    period: NonZeroUsize,
    samples: usize,
}

impl EMA {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            state: ExponentialState::new(period),
            period,
            samples: 0,
        }
    }

    /// Uses alpha = 2 / (period + 1). Each recurrence is rounded to 36 fractional
    /// digits, and the reported value to 12, both to nearest even.
    pub fn push(&mut self, price: &str) -> Result<FixedScaleAveragePoint, InvalidFixedScaleInput> {
        let next = self.state.next(&BigInt::from(coefficient(price)?));
        let reported =
            i128::try_from(reported(&next)).expect("exponential mean fits in the input type");
        self.state.accept(next);
        self.samples = self.samples.saturating_add(1).min(self.period.get());
        Ok(FixedScaleAveragePoint {
            value: format_coefficient(reported),
            ready: self.samples == self.period.get(),
        })
    }
}

pub(super) struct ExponentialState {
    denominator: BigInt,
    prior_weight: BigInt,
    prior: Option<BigInt>,
}

impl ExponentialState {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            denominator: BigInt::from(period.get()) + 1_u8,
            prior_weight: BigInt::from(period.get() - 1),
            prior: None,
        }
    }

    pub fn next(&self, coefficient: &BigInt) -> BigInt {
        let input = coefficient * GUARD_QUANTUM;
        match &self.prior {
            Some(prior) => round_ratio(
                &(prior * &self.prior_weight + 2_u8 * input),
                &self.denominator,
            ),
            None => input,
        }
    }

    pub fn accept(&mut self, next: BigInt) {
        self.prior = Some(next);
    }
}

pub(super) fn reported(state: &BigInt) -> BigInt {
    round_ratio(state, &BigInt::from(GUARD_QUANTUM))
}
