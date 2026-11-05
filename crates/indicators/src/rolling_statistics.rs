use crate::sma::{coefficient, format_coefficient};
use num_bigint::{BigInt, Sign};
use num_integer::Integer;
use std::{collections::VecDeque, fmt, num::NonZeroUsize};

const OUTPUT_LIMIT: u128 = 10_u128.pow(38);

#[derive(Debug, PartialEq, Eq)]
pub enum StatisticalError {
    InvalidInput,
    OutOfRange,
}

impl fmt::Display for StatisticalError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidInput => "Indicator input must be an exact decimal at scale 12",
            Self::OutOfRange => "Indicator result exceeds the fixed-point coefficient range",
        })
    }
}

impl std::error::Error for StatisticalError {}

pub(super) fn parse(price: &str) -> Result<i128, StatisticalError> {
    coefficient(price).map_err(|_| StatisticalError::InvalidInput)
}

pub(super) fn format(value: BigInt) -> Result<String, StatisticalError> {
    i128::try_from(value)
        .ok()
        .filter(|value| value.unsigned_abs() < OUTPUT_LIMIT)
        .map(format_coefficient)
        .ok_or(StatisticalError::OutOfRange)
}

pub(super) struct RollingMoments {
    period: NonZeroUsize,
    window: VecDeque<i128>,
    sum: BigInt,
    sum_squares: BigInt,
}

pub(super) struct Moments {
    pub sum: BigInt,
    pub count: BigInt,
    pub spread_squared: BigInt,
    pub ready: bool,
}

impl RollingMoments {
    pub fn new(period: NonZeroUsize) -> Self {
        Self {
            period,
            window: VecDeque::new(),
            sum: BigInt::ZERO,
            sum_squares: BigInt::ZERO,
        }
    }

    pub fn push<T>(
        &mut self,
        price: i128,
        evaluate: impl FnOnce(&Moments) -> Result<T, StatisticalError>,
    ) -> Result<T, StatisticalError> {
        let price_wide = BigInt::from(price);
        let mut sum = &self.sum + &price_wide;
        let mut sum_squares = &self.sum_squares + &price_wide * &price_wide;
        let full = self.window.len() == self.period.get();
        if full {
            let oldest = BigInt::from(self.window[0]);
            sum -= &oldest;
            sum_squares -= &oldest * &oldest;
        }
        let count = BigInt::from(self.window.len() + usize::from(!full));
        // Population standard deviation = sqrt(n * Σx² − (Σx)²) / n.
        let spread_squared = &count * &sum_squares - &sum * &sum;
        let moments = Moments {
            sum,
            count,
            spread_squared,
            ready: self.window.len() >= self.period.get() - 1,
        };
        let output = evaluate(&moments)?;
        if full {
            self.window.pop_front();
        }
        self.window.push_back(price);
        self.sum = moments.sum;
        self.sum_squares = sum_squares;
        Ok(output)
    }
}

/// Rounds (base ± sqrt(square)) / divisor to nearest even with an exact
/// comparison at the half-integer boundary. Square is nonnegative and divisor positive.
pub(super) fn round_radical(
    base: &BigInt,
    square: &BigInt,
    divisor: &BigInt,
    subtract: bool,
) -> BigInt {
    let root = square.sqrt();
    let integral_numerator = if subtract {
        let root_is_exact = &root * &root == *square;
        base - root - u8::from(!root_is_exact)
    } else {
        base + root
    };
    let mut floor = integral_numerator.div_floor(divisor);
    // Compare ±2 * sqrt(square) with the signed midpoint before squaring.
    let midpoint = (2_u8 * &floor + 1_u8) * divisor - 2_u8 * base;
    let twice_square = 4_u8 * square;
    let comparison = match (subtract, midpoint.sign()) {
        (false, Sign::Minus) => std::cmp::Ordering::Greater,
        (true, Sign::Plus) => std::cmp::Ordering::Less,
        (false, _) => twice_square.cmp(&(&midpoint * &midpoint)),
        (true, _) => (&midpoint * &midpoint).cmp(&twice_square),
    };
    if comparison.is_gt() || (comparison.is_eq() && floor.is_odd()) {
        floor += 1_u8;
    }
    floor
}
