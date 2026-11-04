//! Exact Decimal arithmetic with the shared domain-exact-28-half-even-v1 policy.
use crate::{
    base::{decimal_digit, invalid, whitespace},
    errors::OnlyDomainError,
};
use bigdecimal::{BigDecimal, RoundingMode, Signed, Zero, num_bigint::BigInt};
use num_integer::Integer;
use std::{
    fmt,
    hash::{Hash, Hasher},
    str::FromStr,
};

pub const ONLY_NUMERIC_POLICY: &str = "domain-exact-28-half-even-v1";
pub const ONLY_DIVISION_PRECISION: i64 = 28;
const MAX_EMAX: i64 = 999_999_999_999_999_999;
const MIN_ETINY: i64 = -1_999_999_999_999_999_997;

// Preserve signed zero and scale for wire equality. BigDecimal alone loses -0.
#[derive(Clone, Debug)]
pub struct OnlyDecimal {
    number: BigDecimal,
    negative_zero: bool,
}
impl OnlyDecimal {
    pub(crate) fn canonical(&self) -> Self {
        Self {
            number: self.number.normalized(),
            negative_zero: false,
        }
    }
    pub fn is_negative(&self) -> bool {
        self.number.is_negative() || self.negative_zero
    }
    pub fn is_zero(&self) -> bool {
        self.number.is_zero()
    }
    pub fn fractional_precision(&self) -> i64 {
        self.number.as_bigint_and_exponent().1.max(0)
    }
    fn result(number: BigDecimal, negative_zero: bool) -> Result<Self, OnlyDomainError> {
        let (coefficient, scale) = number.as_bigint_and_exponent();
        let adjusted = coefficient.abs().to_str_radix(10).len() as i64 - scale - 1;
        if !(-MAX_EMAX..=-MIN_ETINY).contains(&scale) || adjusted > MAX_EMAX {
            return Err(invalid("decimal result outside the canonical range"));
        }
        Ok(Self {
            negative_zero: number.is_zero() && negative_zero,
            number,
        })
    }
}
impl PartialEq for OnlyDecimal {
    fn eq(&self, other: &Self) -> bool {
        self.number == other.number
    }
}
impl Eq for OnlyDecimal {}
impl Hash for OnlyDecimal {
    fn hash<H: Hasher>(&self, state: &mut H) {
        let (mut coefficient, mut scale) = self.number.as_bigint_and_exponent();
        if coefficient.is_zero() {
            scale = 0;
        } else {
            while (&coefficient % 10_u8).is_zero() {
                coefficient /= 10_u8;
                scale -= 1;
            }
        }
        coefficient.hash(state);
        scale.hash(state);
    }
}
impl PartialOrd for OnlyDecimal {
    fn partial_cmp(&self, other: &Self) -> Option<std::cmp::Ordering> {
        self.number.partial_cmp(&other.number)
    }
}
impl FromStr for OnlyDecimal {
    type Err = OnlyDomainError;
    fn from_str(input: &str) -> Result<Self, Self::Err> {
        let input = input.trim_matches(whitespace);
        let lexical: String = input
            .chars()
            .filter(|c| *c != '_')
            .map(|c| decimal_digit(c).unwrap_or(c))
            .collect();
        let number =
            BigDecimal::from_str(&lexical).map_err(|_| invalid("invalid finite decimal"))?;
        Self::result(number, lexical.starts_with('-'))
    }
}
impl fmt::Display for OnlyDecimal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (coefficient, scale) = self.number.as_bigint_and_exponent();
        let digits = coefficient.abs().to_str_radix(10);
        let length = digits.len() as i64;
        let adjusted = length - scale - 1;
        if self.is_negative() {
            f.write_str("-")?;
        }
        if scale < 0 || adjusted < -6 {
            f.write_str(&digits[..1])?;
            if digits.len() > 1 {
                write!(f, ".{}", &digits[1..])?;
            }
            write!(f, "E{adjusted:+}")
        } else if scale == 0 {
            f.write_str(&digits)
        } else if scale < length {
            let cut = (length - scale) as usize;
            write!(f, "{}.{}", &digits[..cut], &digits[cut..])
        } else {
            write!(f, "0.{}{}", "0".repeat((scale - length) as usize), digits)
        }
    }
}

pub fn only_add(left: &OnlyDecimal, right: &OnlyDecimal) -> Result<OnlyDecimal, OnlyDomainError> {
    let scale = left
        .number
        .as_bigint_and_exponent()
        .1
        .max(right.number.as_bigint_and_exponent().1);
    OnlyDecimal::result(
        (&left.number + &right.number).with_scale(scale),
        left.is_negative() && right.is_negative(),
    )
}
pub fn only_subtract(
    left: &OnlyDecimal,
    right: &OnlyDecimal,
) -> Result<OnlyDecimal, OnlyDomainError> {
    let scale = left
        .number
        .as_bigint_and_exponent()
        .1
        .max(right.number.as_bigint_and_exponent().1);
    OnlyDecimal::result(
        (&left.number - &right.number).with_scale(scale),
        left.is_negative() && !right.is_negative(),
    )
}
pub fn only_multiply(
    left: &OnlyDecimal,
    right: &OnlyDecimal,
) -> Result<OnlyDecimal, OnlyDomainError> {
    let scale = left
        .number
        .as_bigint_and_exponent()
        .1
        .checked_add(right.number.as_bigint_and_exponent().1)
        .ok_or_else(|| invalid("decimal scale overflow"))?;
    if !(-MAX_EMAX..=-MIN_ETINY).contains(&scale) {
        return Err(invalid("decimal result outside the canonical range"));
    }
    OnlyDecimal::result(
        (&left.number * &right.number).with_scale(scale),
        left.is_negative() != right.is_negative(),
    )
}
pub fn only_quantize(
    value: &OnlyDecimal,
    quantum: &OnlyDecimal,
) -> Result<OnlyDecimal, OnlyDomainError> {
    only_quantize_with_rounding(value, quantum, OnlyRoundingMode::HalfEven)
}
pub fn only_remainder(
    left: &OnlyDecimal,
    right: &OnlyDecimal,
) -> Result<OnlyDecimal, OnlyDomainError> {
    if right.is_zero() {
        return Err(invalid("domain remainder by zero"));
    }
    OnlyDecimal::result(&left.number % &right.number, left.is_negative())
}
fn power10(exponent: i64) -> Result<BigInt, OnlyDomainError> {
    let exponent =
        u32::try_from(exponent).map_err(|_| invalid("decimal exponent cannot be materialized"))?;
    Ok(BigInt::from(10).pow(exponent))
}
pub fn only_divide(
    left: &OnlyDecimal,
    right: &OnlyDecimal,
) -> Result<OnlyDecimal, OnlyDomainError> {
    if right.is_zero() {
        return Err(invalid("domain division by zero"));
    }
    let (mut numerator, left_scale) = left.number.as_bigint_and_exponent();
    let (mut denominator, right_scale) = right.number.as_bigint_and_exponent();
    let exponent = right_scale
        .checked_sub(left_scale)
        .ok_or_else(|| invalid("decimal scale overflow"))?;
    let divisor = numerator.gcd(&denominator);
    numerator /= &divisor;
    denominator /= divisor;
    if denominator.is_negative() {
        numerator = -numerator;
        denominator = -denominator;
    }
    let mut residual = denominator.clone();
    let mut twos = 0_i64;
    let mut fives = 0_i64;
    while (&residual % 2_u8).is_zero() {
        residual /= 2_u8;
        twos += 1;
    }
    while (&residual % 5_u8).is_zero() {
        residual /= 5_u8;
        fives += 1;
    }
    if residual == BigInt::from(1) {
        let scale = twos.max(fives);
        numerator *= BigInt::from(2).pow((scale - twos) as u32)
            * BigInt::from(5).pow((scale - fives) as u32);
        let mut scale = scale
            .checked_sub(exponent)
            .ok_or_else(|| invalid("decimal scale overflow"))?;
        if numerator.is_zero() {
            scale = 0;
        }
        while scale > 0 && (&numerator % 10_u8).is_zero() {
            numerator /= 10_u8;
            scale -= 1;
        }
        return OnlyDecimal::result(BigDecimal::new(numerator, scale), false);
    }
    // The library has no context-parameterized division. Round the exact integer
    // quotient once, using num-integer for gcd/div_rem; never multiply a rounded inverse.
    let negative = numerator.is_negative();
    numerator = numerator.abs();
    let mut magnitude =
        numerator.to_str_radix(10).len() as i64 - denominator.to_str_radix(10).len() as i64;
    let below = if magnitude >= 0 {
        numerator < &denominator * power10(magnitude)?
    } else {
        &numerator * power10(-magnitude)? < denominator
    };
    if below {
        magnitude -= 1;
    }
    let mut scale = ONLY_DIVISION_PRECISION - 1 - magnitude;
    if scale >= 0 {
        numerator *= power10(scale)?;
    } else {
        denominator *= power10(-scale)?;
    }
    let (mut quotient, remainder) = numerator.div_rem(&denominator);
    let twice = &remainder * 2_u8;
    if twice > denominator || (twice == denominator && quotient.is_odd()) {
        quotient += 1_u8;
    }
    if quotient.to_str_radix(10).len() > ONLY_DIVISION_PRECISION as usize {
        quotient /= 10_u8;
        scale -= 1;
    }
    if negative {
        quotient = -quotient;
    }
    OnlyDecimal::result(
        BigDecimal::new(
            quotient,
            scale
                .checked_sub(exponent)
                .ok_or_else(|| invalid("decimal scale overflow"))?,
        ),
        false,
    )
}

crate::enums::domain_enum! { OnlyRoundingMode {
 HalfEven=>"ROUND_HALF_EVEN", HalfUp=>"ROUND_HALF_UP", HalfDown=>"ROUND_HALF_DOWN",
 Up=>"ROUND_UP",Down=>"ROUND_DOWN",Ceiling=>"ROUND_CEILING",Floor=>"ROUND_FLOOR",ZeroFiveUp=>"ROUND_05UP",
}}

pub fn only_quantize_with_rounding(
    value: &OnlyDecimal,
    quantum: &OnlyDecimal,
    mode: OnlyRoundingMode,
) -> Result<OnlyDecimal, OnlyDomainError> {
    let (coefficient, scale) = value.number.as_bigint_and_exponent();
    let target = quantum.number.as_bigint_and_exponent().1;
    let library_mode = match mode {
        OnlyRoundingMode::HalfEven => RoundingMode::HalfEven,
        OnlyRoundingMode::HalfUp => RoundingMode::HalfUp,
        OnlyRoundingMode::HalfDown => RoundingMode::HalfDown,
        OnlyRoundingMode::Up => RoundingMode::Up,
        OnlyRoundingMode::Down => RoundingMode::Down,
        OnlyRoundingMode::Ceiling => RoundingMode::Ceiling,
        OnlyRoundingMode::Floor => RoundingMode::Floor,
        OnlyRoundingMode::ZeroFiveUp => {
            if target >= scale {
                return OnlyDecimal::result(value.number.with_scale(target), value.is_negative());
            }
            let difference = scale
                .checked_sub(target)
                .ok_or_else(|| invalid("decimal scale overflow"))?;
            let units = if difference > coefficient.abs().to_str_radix(10).len() as i64 {
                if coefficient.is_zero() {
                    BigInt::from(0)
                } else if coefficient.is_negative() {
                    BigInt::from(-1)
                } else {
                    BigInt::from(1)
                }
            } else {
                rounded_integer(coefficient, power10(difference)?, mode)
            };
            return OnlyDecimal::result(BigDecimal::new(units, target), value.is_negative());
        }
    };
    OnlyDecimal::result(
        value.number.with_scale_round(target, library_mode),
        value.is_negative(),
    )
}

fn rounded_integer(numerator: BigInt, denominator: BigInt, mode: OnlyRoundingMode) -> BigInt {
    let negative = numerator.is_negative();
    let (mut units, remainder) = numerator.abs().div_rem(&denominator);
    if !remainder.is_zero() {
        let twice = &remainder * 2_u8;
        let increase = match mode {
            OnlyRoundingMode::Down => false,
            OnlyRoundingMode::Up => true,
            OnlyRoundingMode::Ceiling => !negative,
            OnlyRoundingMode::Floor => negative,
            OnlyRoundingMode::HalfEven => {
                twice > denominator || (twice == denominator && units.is_odd())
            }
            OnlyRoundingMode::HalfUp => twice >= denominator,
            OnlyRoundingMode::HalfDown => twice > denominator,
            OnlyRoundingMode::ZeroFiveUp => {
                (&units % 10_u8).is_zero() || &units % 10_u8 == BigInt::from(5)
            }
        };
        if increase {
            units += 1_u8;
        }
    }
    if negative { -units } else { units }
}

pub fn only_increment(
    value: &OnlyDecimal,
    increment: &OnlyDecimal,
    mode: OnlyRoundingMode,
) -> Result<OnlyDecimal, OnlyDomainError> {
    if increment.is_negative() || increment.is_zero() {
        return Err(invalid("increment must be positive"));
    }
    let (mut numerator, value_scale) = value.number.as_bigint_and_exponent();
    let (coefficient, increment_scale) = increment.number.as_bigint_and_exponent();
    let mut denominator = coefficient.clone();
    let exponent = increment_scale
        .checked_sub(value_scale)
        .ok_or_else(|| invalid("decimal scale overflow"))?;
    let common = numerator.gcd(&denominator);
    numerator /= &common;
    denominator /= common;
    if exponent >= 0 {
        numerator *= power10(exponent)?;
    } else {
        denominator *= power10(-exponent)?;
    }
    let units = rounded_integer(numerator, denominator, mode);
    OnlyDecimal::result(BigDecimal::new(units * coefficient, increment_scale), false)
}
