use crate::{
    ema::{ExponentialState, reported},
    rolling_statistics::{StatisticalError, format, parse},
};
use num_bigint::{BigInt, Sign};
use std::num::NonZeroUsize;

#[derive(Debug, PartialEq, Eq)]
pub enum MACDCross {
    None,
    Golden,
    Death,
}

#[derive(Debug, PartialEq, Eq)]
pub struct MACDPoint {
    pub dif: String,
    pub dea: String,
    pub histogram: String,
    pub cross: MACDCross,
    pub ready: bool,
}

/// MACD with the scale-12 DIF feeding its signal EMA, and histogram = DIF − DEA.
pub struct MACD {
    fast: ExponentialState,
    slow: ExponentialState,
    signal: ExponentialState,
    previous_histogram_sign: Sign,
    slow_period: NonZeroUsize,
    samples: usize,
}

impl MACD {
    /// Returns no indicator unless the fast period is shorter than the slow period.
    pub fn new(fast: NonZeroUsize, slow: NonZeroUsize, signal: NonZeroUsize) -> Option<Self> {
        if fast >= slow {
            return None;
        }
        Some(Self {
            fast: ExponentialState::new(fast),
            slow: ExponentialState::new(slow),
            signal: ExponentialState::new(signal),
            previous_histogram_sign: Sign::NoSign,
            slow_period: slow,
            samples: 0,
        })
    }

    /// Reports a seeded value during warmup. Errors leave all three averages unchanged.
    pub fn push(&mut self, price: &str) -> Result<MACDPoint, StatisticalError> {
        let input = BigInt::from(parse(price)?);
        let fast = self.fast.next(&input);
        let slow = self.slow.next(&input);
        let dif = reported(&(&fast - &slow));
        let signal = self.signal.next(&dif);
        let dea = reported(&signal);
        let histogram = &dif - &dea;
        let sign = histogram.sign();
        let cross = match (self.previous_histogram_sign, sign) {
            (Sign::Minus | Sign::NoSign, Sign::Plus) => MACDCross::Golden,
            (Sign::Plus | Sign::NoSign, Sign::Minus) => MACDCross::Death,
            _ => MACDCross::None,
        };
        let samples = self.samples.saturating_add(1).min(self.slow_period.get());
        let point = MACDPoint {
            dif: format(dif)?,
            dea: format(dea)?,
            histogram: format(histogram)?,
            cross,
            ready: samples == self.slow_period.get(),
        };
        self.fast.accept(fast);
        self.slow.accept(slow);
        self.signal.accept(signal);
        self.previous_histogram_sign = sign;
        self.samples = samples;
        Ok(point)
    }
}
