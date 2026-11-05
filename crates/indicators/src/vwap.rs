use crate::{
    fixed_window::{FinancialInputError, FinancialValue, validate_bar, volume},
    sma::coefficient,
};
use num_bigint::BigInt;
use onlyalpha_operators::round_ratio;
use std::{collections::VecDeque, num::NonZeroUsize};

/// Volume-weighted average price over a complete rolling window.
pub struct VWAP {
    period: NonZeroUsize,
    window: VecDeque<Option<(BigInt, i128)>>,
    weighted: BigInt,
    volume: BigInt,
    missing: usize,
}

impl VWAP {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            period,
            window: VecDeque::new(),
            weighted: BigInt::ZERO,
            volume: BigInt::ZERO,
            missing: 0,
        }
    }

    /// A missing observation advances the window. Zero total volume is undefined.
    pub fn push(
        &mut self,
        price: Option<&str>,
        amount: Option<&str>,
    ) -> Result<FinancialValue, FinancialInputError> {
        let price = price.map(coefficient).transpose()?;
        let amount = volume(amount)?;
        let point = price
            .zip(amount)
            .map(|(price, amount)| (BigInt::from(price) * amount, amount));
        if self.window.len() == self.period.get() {
            match self.window.pop_front().expect("full nonempty window") {
                Some((weighted, amount)) => {
                    self.weighted -= weighted;
                    self.volume -= amount;
                }
                None => self.missing -= 1,
            }
        }
        if let Some((weighted, amount)) = &point {
            self.weighted += weighted;
            self.volume += *amount;
        } else {
            self.missing += 1;
        }
        self.window.push_back(point);

        Ok(if self.missing > 0 {
            FinancialValue::Missing
        } else if self.window.len() < self.period.get() {
            FinancialValue::Warmup
        } else if self.volume == BigInt::ZERO {
            FinancialValue::Undefined
        } else {
            FinancialValue::from_coefficient(round_ratio(&self.weighted, &self.volume))
        })
    }
}

const DAY_NS: u64 = 86_400_000_000_000;

/// Session VWAP over typical prices (high + low + close) / 3, reset at UTC midnight.
#[derive(Default)]
pub struct UtcSessionVWAP {
    previous_start: Option<u64>,
    weighted: BigInt,
    volume: BigInt,
}

impl UtcSessionVWAP {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn push(
        &mut self,
        start_ns: u64,
        high: &str,
        low: &str,
        close: &str,
        amount: &str,
    ) -> Result<FinancialValue, FinancialInputError> {
        let (high, low, close) = (coefficient(high)?, coefficient(low)?, coefficient(close)?);
        validate_bar(Some(high), Some(low), Some(close))?;
        let amount = volume(Some(amount))?.expect("supplied volume is present");
        if let Some(previous) = self.previous_start {
            if start_ns <= previous {
                return Err(FinancialInputError::InvalidTimestampOrder);
            }
            if start_ns / DAY_NS != previous / DAY_NS {
                self.weighted = BigInt::ZERO;
                self.volume = BigInt::ZERO;
            }
        }
        self.previous_start = Some(start_ns);
        self.weighted += (BigInt::from(high) + low + close) * amount;
        self.volume += amount;
        if self.volume == BigInt::ZERO {
            return Ok(FinancialValue::Undefined);
        }
        Ok(FinancialValue::from_coefficient(round_ratio(
            &self.weighted,
            &(&self.volume * 3),
        )))
    }
}
