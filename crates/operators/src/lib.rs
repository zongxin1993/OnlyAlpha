//! Market-independent mathematical operators.

use num_bigint::BigInt;
use num_integer::Integer;
use std::{
    collections::VecDeque,
    num::{NonZeroI128, NonZeroU128, NonZeroUsize},
};

/// Rolling mean of fixed-point coefficients that all have the same scale.
pub struct RollingMean {
    period: NonZeroUsize,
    window: VecDeque<i128>,
    sum: BigInt,
}

impl RollingMean {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            period,
            window: VecDeque::new(),
            sum: BigInt::ZERO,
        }
    }

    pub fn is_full(&self) -> bool {
        self.window.len() == self.period.get()
    }

    /// Includes the new sample and rounds the mean once, to nearest even.
    pub fn push(&mut self, value: i128) -> i128 {
        if self.is_full() {
            let oldest = self.window.pop_front().expect("full nonempty window");
            self.sum -= oldest;
        }
        self.window.push_back(value);
        self.sum += value;

        let count = BigInt::from(self.window.len());
        rounded_mean(&self.sum, &count)
    }
}

/// Linear weighted mean with weights 1 through period, oldest first.
pub struct LinearWeightedMean {
    period: NonZeroUsize,
    window: VecDeque<i128>,
    sum: BigInt,
    weighted_sum: BigInt,
}

impl LinearWeightedMean {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            period,
            window: VecDeque::new(),
            sum: BigInt::ZERO,
            weighted_sum: BigInt::ZERO,
        }
    }

    /// Emits a value once the entire window is available.
    pub fn push(&mut self, value: i128) -> Option<i128> {
        if self.window.len() == self.period.get() {
            self.weighted_sum -= &self.sum;
            self.sum -= self.window.pop_front().expect("full nonempty window");
        }
        self.window.push_back(value);
        self.sum += value;
        let count = BigInt::from(self.window.len());
        self.weighted_sum += &count * value;
        if self.window.len() != self.period.get() {
            return None;
        }
        let total_weight = &count * (&count + 1) / 2;
        Some(rounded_mean(&self.weighted_sum, &total_weight))
    }
}

fn rounded_mean(sum: &BigInt, weight: &BigInt) -> i128 {
    // Nonnegative weights keep the rounded mean within the input extrema.
    i128::try_from(round_ratio(sum, weight)).expect("rounded mean fits in the input type")
}

/// Computes a fractional change at the requested scale, rounded to nearest even.
/// A result outside the coefficient range has no value.
pub fn fractional_change(
    current: i128,
    reference: NonZeroI128,
    quantum: NonZeroU128,
) -> Option<i128> {
    let reference = reference.get();
    let difference = BigInt::from(current) - reference;
    let numerator = difference * quantum.get() * reference.signum();
    let denominator = BigInt::from(reference.unsigned_abs());
    i128::try_from(round_ratio(&numerator, &denominator)).ok()
}

/// Divides by a positive denominator and rounds to the nearest even integer.
///
/// Panics if the denominator is zero or negative.
pub fn round_ratio(sum: &BigInt, weight: &BigInt) -> BigInt {
    assert!(weight.sign() == num_bigint::Sign::Plus);
    let (mut mean, remainder) = sum.div_mod_floor(weight);
    let twice_remainder = remainder << 1;
    if &twice_remainder > weight || (&twice_remainder == weight && mean.is_odd()) {
        mean += 1;
    }
    mean
}

pub mod algebra;
