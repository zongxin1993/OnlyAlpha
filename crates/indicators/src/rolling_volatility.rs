use crate::{
    rolling_statistics::{RollingMoments, StatisticalError, format, parse, round_radical},
    sma::FixedScaleAveragePoint,
};
use num_bigint::BigInt;
use std::num::NonZeroUsize;

/// Population standard deviation of prices, in the input price units.
pub struct RollingVolatility {
    moments: RollingMoments,
}

impl RollingVolatility {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            moments: RollingMoments::new(period),
        }
    }

    /// Includes the new sample and emits the available prefix during warmup.
    pub fn push(&mut self, price: &str) -> Result<FixedScaleAveragePoint, StatisticalError> {
        self.moments.push(parse(price)?, |moments| {
            let deviation = round_radical(
                &BigInt::ZERO,
                &moments.spread_squared,
                &moments.count,
                false,
            );
            Ok(FixedScaleAveragePoint {
                value: format(deviation)?,
                ready: moments.ready,
            })
        })
    }
}
