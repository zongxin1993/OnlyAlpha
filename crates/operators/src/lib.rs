//! Market-independent mathematical operators.

use num_bigint::BigInt;
use num_integer::Integer;

/// Divides by a positive denominator and rounds to the nearest even integer.
///
/// Panics if the denominator is zero or negative.
pub(crate) fn round_ratio(sum: &BigInt, weight: &BigInt) -> BigInt {
    assert!(weight.sign() == num_bigint::Sign::Plus);
    let (mut mean, remainder) = sum.div_mod_floor(weight);
    let twice_remainder = remainder << 1;
    if &twice_remainder > weight || (&twice_remainder == weight && mean.is_odd()) {
        mean += 1;
    }
    mean
}

pub mod algebra;
pub mod execution;
pub mod registry;
