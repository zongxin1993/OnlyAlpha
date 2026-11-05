use crate::SimpleMovingAverage;
use std::{fmt, num::NonZeroUsize};

const SCALE: usize = 12;
pub(super) const QUANTUM: i128 = 10_i128.pow(SCALE as u32);

/// SMA version 2 over decimal prices with up to 26 integral and 12 fractional digits.
pub struct SMA {
    average: SimpleMovingAverage,
}

#[derive(Debug, PartialEq, Eq)]
pub struct FixedScaleAveragePoint {
    /// Fixed-point decimal with exactly 12 fractional digits.
    pub value: String,
    pub ready: bool,
}

#[derive(Debug, PartialEq, Eq)]
pub struct InvalidFixedScaleInput;

impl fmt::Display for InvalidFixedScaleInput {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("Indicator input must be an exact decimal at scale 12")
    }
}

impl std::error::Error for InvalidFixedScaleInput {}

impl SMA {
    pub const TYPE_ID: &str = "onlyalpha.indicator.sma";
    pub const SEMANTIC_VERSION: &str = "2";

    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            average: SimpleMovingAverage::new(period),
        }
    }

    /// Validates the sample before changing the window. Rounds the exact mean once.
    /// Zero is returned without a sign.
    pub fn push(&mut self, price: &str) -> Result<FixedScaleAveragePoint, InvalidFixedScaleInput> {
        let point = self.average.push(coefficient(price)?);
        Ok(FixedScaleAveragePoint {
            value: format_coefficient(point.value),
            ready: point.ready,
        })
    }
}

pub(super) fn coefficient(price: &str) -> Result<i128, InvalidFixedScaleInput> {
    let (sign, unsigned) = price
        .strip_prefix('-')
        .map_or((1, price), |value| (-1, value));
    let (whole, fraction) = match unsigned.split_once('.') {
        Some((_, "")) => return Err(InvalidFixedScaleInput),
        Some(parts) => parts,
        None => (unsigned, ""),
    };
    if whole.is_empty()
        || whole.len() > 26
        || (whole.len() > 1 && whole.starts_with('0'))
        || fraction.len() > SCALE
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|byte| byte.is_ascii_digit())
    {
        return Err(InvalidFixedScaleInput);
    }
    let whole: i128 = whole.parse().map_err(|_| InvalidFixedScaleInput)?;
    let fraction_value: i128 = if fraction.is_empty() {
        0
    } else {
        fraction.parse().map_err(|_| InvalidFixedScaleInput)?
    };
    // At most 38 digits after scaling, within the signed i128 range.
    let magnitude = whole * QUANTUM + fraction_value * 10_i128.pow((SCALE - fraction.len()) as u32);
    Ok(sign * magnitude)
}

pub(super) fn format_coefficient(value: i128) -> String {
    let sign = if value < 0 { "-" } else { "" };
    let magnitude = value.unsigned_abs();
    let quantum = QUANTUM as u128;
    format!(
        "{sign}{}.{:0SCALE$}",
        magnitude / quantum,
        magnitude % quantum
    )
}
