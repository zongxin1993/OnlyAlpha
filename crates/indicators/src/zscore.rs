use crate::{
    rolling_statistics::{RollingMoments, StatisticalError, format, parse},
    sma::{FixedScaleAveragePoint, QUANTUM},
};
use num_bigint::{BigInt, Sign};
use num_integer::Integer;
use std::num::NonZeroUsize;

/// Standardizes the newest price against the population moments of its window.
pub struct ZScore {
    moments: RollingMoments,
}

impl ZScore {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            moments: RollingMoments::new(period),
        }
    }

    /// Includes the new sample. A zero-variance window has a score of zero.
    pub fn push(&mut self, price: &str) -> Result<FixedScaleAveragePoint, StatisticalError> {
        let price = parse(price)?;
        self.moments.push(price, |moments| {
            let numerator = (price * &moments.count - &moments.sum) * QUANTUM;
            let value = if moments.spread_squared == BigInt::ZERO {
                BigInt::ZERO
            } else {
                rounded_score(numerator, &moments.spread_squared)
            };
            Ok(FixedScaleAveragePoint {
                value: format(value)?,
                ready: moments.ready,
            })
        })
    }
}

fn rounded_score(numerator: BigInt, spread_squared: &BigInt) -> BigInt {
    let square = &numerator * &numerator;
    let mut magnitude = (&square / spread_squared).sqrt();
    let midpoint = 2_u8 * &magnitude + 1_u8;
    let comparison = (4_u8 * square).cmp(&(&midpoint * &midpoint * spread_squared));
    if comparison.is_gt() || (comparison.is_eq() && magnitude.is_odd()) {
        magnitude += 1_u8;
    }
    if numerator.sign() == Sign::Minus {
        -magnitude
    } else {
        magnitude
    }
}
