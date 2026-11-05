use crate::{
    fixed_window::{FinancialInputError, FinancialValue, GUARD_FACTOR, validate_bar},
    sma::{QUANTUM, coefficient},
};
use num_bigint::BigInt;
use onlyalpha_operators::round_ratio;
use std::{collections::VecDeque, num::NonZeroUsize};

/// Stochastic oscillator with full windows and explicit missing readiness.
pub struct Stochastic {
    k_period: NonZeroUsize,
    d_period: NonZeroUsize,
    bars: VecDeque<Option<(i128, i128)>>,
    smoothing: Option<(NonZeroUsize, VecDeque<Sample>)>,
    recent_k: VecDeque<Sample>,
}

#[derive(Debug, PartialEq, Eq)]
pub struct StochasticPoint {
    pub k: FinancialValue,
    pub d: FinancialValue,
}

#[derive(Clone, Copy)]
enum Sample {
    Warmup,
    Missing,
    Undefined,
    Ready(i128),
}

impl Sample {
    fn value(self, guard: i128) -> FinancialValue {
        match self {
            Self::Warmup => FinancialValue::Warmup,
            Self::Missing => FinancialValue::Missing,
            Self::Undefined => FinancialValue::Undefined,
            Self::Ready(value) => {
                FinancialValue::from_coefficient(round_ratio(&value.into(), &guard.into()))
            }
        }
    }
}

impl Stochastic {
    /// Fast variant. D averages a complete window of published K values.
    pub fn new(k_period: NonZeroUsize, d_period: NonZeroUsize) -> Self {
        Self {
            k_period,
            d_period,
            bars: VecDeque::new(),
            smoothing: None,
            recent_k: VecDeque::new(),
        }
    }

    /// Slow variant. Smooth raw K, then average smoothed K for D. Both
    /// stages retain 24 extra decimal places before publishing scale 12.
    pub fn slow(k_period: NonZeroUsize, smooth_k: NonZeroUsize, d_period: NonZeroUsize) -> Self {
        Self {
            smoothing: Some((smooth_k, VecDeque::new())),
            ..Self::new(k_period, d_period)
        }
    }

    pub fn push(
        &mut self,
        high: Option<&str>,
        low: Option<&str>,
        close: Option<&str>,
    ) -> Result<StochasticPoint, FinancialInputError> {
        let high = high.map(coefficient).transpose()?;
        let low = low.map(coefficient).transpose()?;
        let close = close.map(coefficient).transpose()?;
        validate_bar(high, low, close)?;
        if self.bars.len() == self.k_period.get() {
            self.bars.pop_front();
        }
        self.bars
            .push_back(high.zip(low).filter(|_| close.is_some()));
        let guard = if self.smoothing.is_some() {
            GUARD_FACTOR
        } else {
            1
        };
        let mut k = self.percent_k(close, guard);
        if let Some((period, samples)) = &mut self.smoothing {
            k = push_average(samples, *period, k);
        }
        let d = push_average(&mut self.recent_k, self.d_period, k);
        Ok(StochasticPoint {
            k: k.value(guard),
            d: d.value(guard),
        })
    }

    fn percent_k(&self, close: Option<i128>, guard: i128) -> Sample {
        let Some(close) = close else {
            return Sample::Missing;
        };
        let mut high = i128::MIN;
        let mut low = i128::MAX;
        for bar in &self.bars {
            let Some((bar_high, bar_low)) = bar else {
                return Sample::Missing;
            };
            high = high.max(*bar_high);
            low = low.min(*bar_low);
        }
        if self.bars.len() < self.k_period.get() {
            return Sample::Warmup;
        }
        if high == low {
            return Sample::Undefined;
        }
        let numerator = (BigInt::from(close) - low) * (100 * QUANTUM) * guard;
        let denominator = BigInt::from(high) - low;
        let coefficient = i128::try_from(round_ratio(&numerator, &denominator))
            .expect("stochastic percentage lies between zero and 100");
        Sample::Ready(coefficient)
    }
}

fn push_average(samples: &mut VecDeque<Sample>, period: NonZeroUsize, value: Sample) -> Sample {
    if samples.len() == period.get() {
        samples.pop_front();
    }
    samples.push_back(value);
    if samples.iter().any(|value| matches!(value, Sample::Missing)) {
        return Sample::Missing;
    }
    if samples.len() < period.get() || samples.iter().any(|value| matches!(value, Sample::Warmup)) {
        return Sample::Warmup;
    }
    let mut sum = BigInt::ZERO;
    for value in samples {
        let Sample::Ready(value) = value else {
            return Sample::Undefined;
        };
        sum += *value;
    }
    Sample::Ready(
        i128::try_from(round_ratio(&sum, &period.get().into()))
            .expect("average of stochastic percentages lies between zero and 100"),
    )
}
