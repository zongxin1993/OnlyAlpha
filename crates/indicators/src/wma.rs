use crate::sma::{InvalidFixedScaleInput, coefficient, format_coefficient};
use onlyalpha_operators::LinearWeightedMean;
use std::num::NonZeroUsize;

/// Linear weighted moving average on exact decimal prices at scale 12.
pub struct WMA {
    mean: LinearWeightedMean,
}

impl WMA {
    pub const TYPE_ID: &str = "onlyalpha.indicator.wma";
    pub const SEMANTIC_VERSION: &str = "2";

    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            mean: LinearWeightedMean::new(period),
        }
    }

    /// Validates input before changing the window. A partial window has no value.
    pub fn push(&mut self, price: &str) -> Result<Option<String>, InvalidFixedScaleInput> {
        Ok(self.mean.push(coefficient(price)?).map(format_coefficient))
    }
}
