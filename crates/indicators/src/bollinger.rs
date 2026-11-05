use crate::{
    rolling_statistics::{RollingMoments, StatisticalError, format, parse, round_radical},
    sma::QUANTUM,
};
use num_bigint::BigInt;
use onlyalpha_operators::round_ratio;
use std::num::NonZeroUsize;

/// Population Bollinger bands over up to one period of exact scale-12 prices.
pub struct Bollinger {
    moments: RollingMoments,
    multiplier_squared: BigInt,
}

#[derive(Debug, PartialEq, Eq)]
pub struct BollingerPoint {
    pub middle: String,
    pub upper: String,
    pub lower: String,
    pub ready: bool,
}

impl Bollinger {
    /// The multiplier is a nonnegative, exact decimal with at most 12 fractional digits.
    pub fn new(period: NonZeroUsize, multiplier: &str) -> Result<Self, StatisticalError> {
        let multiplier = parse(multiplier)?;
        if multiplier < 0 {
            return Err(StatisticalError::InvalidInput);
        }
        let multiplier = BigInt::from(multiplier);
        Ok(Self {
            moments: RollingMoments::new(period),
            multiplier_squared: &multiplier * &multiplier,
        })
    }

    /// Includes the new sample and rounds each band once to nearest even.
    /// An error leaves the window unchanged.
    pub fn push(&mut self, price: &str) -> Result<BollingerPoint, StatisticalError> {
        self.moments.push(parse(price)?, |moments| {
            let middle = round_ratio(&moments.sum, &moments.count);
            let base = &moments.sum * QUANTUM;
            let divisor = &moments.count * QUANTUM;
            let square = &moments.spread_squared * &self.multiplier_squared;
            Ok(BollingerPoint {
                middle: format(middle)?,
                upper: format(round_radical(&base, &square, &divisor, false))?,
                lower: format(round_radical(&base, &square, &divisor, true))?,
                ready: moments.ready,
            })
        })
    }
}
