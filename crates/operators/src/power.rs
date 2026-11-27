use super::{Cell, Decimal, Error, Result, Sign, pow10, q, round};
use bigdecimal::{ToPrimitive, Zero};
use num_bigint::BigInt;
use num_integer::Integer;

fn fraction(value: &Decimal) -> (BigInt, BigInt) {
    let (n, scale) = value.normalized().as_bigint_and_exponent();
    if scale <= 0 {
        (n * pow10((-scale) as usize), BigInt::from(1))
    } else {
        let d = pow10(scale as usize);
        let gcd = n.gcd(&d);
        (n / &gcd, d / gcd)
    }
}

fn exact_root(mut n: BigInt, mut d: BigInt, degree: u32) -> Decimal {
    let estimate = n.to_str_radix(10).len() as i64 - d.to_str_radix(10).len() as i64;
    let below = if estimate >= 0 {
        n < &d * pow10(estimate as usize)
    } else {
        &n * pow10((-estimate) as usize) < d
    };
    let magnitude = (estimate - i64::from(below)).div_euclid(i64::from(degree));
    let scale = 27 - magnitude;
    let shift = scale * i64::from(degree);
    if shift >= 0 {
        n *= pow10(shift as usize);
    } else {
        d *= pow10((-shift) as usize);
    }
    let mut floor = (&n / &d).nth_root(degree);
    let midpoint = ((&floor << 1usize) + BigInt::from(1)).pow(degree) * d;
    let scaled = n << degree;
    if scaled > midpoint || (scaled == midpoint && floor.is_odd()) {
        floor += 1;
    }
    Decimal::new(floor, scale)
}

struct Bounds {
    low: BigInt,
    high: BigInt,
}

impl Bounds {
    fn ratio(n: &BigInt, d: &BigInt, unit: &BigInt) -> Self {
        let scaled = n * unit;
        Self {
            low: &scaled / d,
            high: scaled.div_ceil(d),
        }
    }

    fn sqrt(&self, unit: &BigInt) -> Self {
        let upper = &self.high * unit;
        let root = upper.sqrt();
        Self {
            low: (&self.low * unit).sqrt(),
            high: if &root * &root == upper {
                root
            } else {
                root + 1
            },
        }
    }

    fn multiply(&self, other: &Self, unit: &BigInt, cap: &BigInt) -> Self {
        Self {
            low: ((&self.low * &other.low) / unit).min(cap.clone()),
            high: (&self.high * &other.high).div_ceil(unit).min(cap.clone()),
        }
    }

    fn rounded(&self, inverse: bool, precision: usize, unit: &BigInt) -> Option<Result<Decimal>> {
        let (low, high) = if inverse {
            let square = unit * unit;
            (&square / &self.high, square.div_ceil(&self.low))
        } else {
            (self.low.clone(), self.high.clone())
        };
        let finish = |bound| q(round(Decimal::new(bound, precision as i64)));
        let low = finish(low);
        (low == finish(high)).then_some(low)
    }
}

fn positive_power(
    base: (&BigInt, &BigInt),
    exponent: (&BigInt, &BigInt),
    inverse: bool,
    precision: usize,
) -> Option<Result<Decimal>> {
    let unit = pow10(precision);
    // Above 10^17 all direct results overflow q12 and all reciprocals round to zero.
    let cap = &unit * pow10(17);
    let original = Bounds::ratio(base.0, base.1, &unit);
    let mut factor = Bounds {
        low: original.low.clone(),
        high: original.high.clone(),
    };
    let mut result = Bounds {
        low: unit.clone(),
        high: unit.clone(),
    };
    let (mut integer, mut remainder) = exponent.0.div_rem(exponent.1);
    while !integer.is_zero() {
        if integer.is_odd() {
            result = result.multiply(&factor, &unit, &cap);
        }
        integer >>= 1;
        factor = factor.multiply(&factor, &unit, &cap);
        if result.low == cap {
            return result.rounded(inverse, precision, &unit);
        }
    }
    if remainder.is_zero() {
        return result.rounded(inverse, precision, &unit);
    }
    // After k binary digits the omitted fractional power lies in [1, base^(1/2^k)].
    let mut root = original;
    for bit in 1..=4 * precision + 16 {
        root = root.sqrt(&unit);
        remainder <<= 1;
        if &remainder >= exponent.1 {
            remainder -= exponent.1;
            result = result.multiply(&root, &unit, &cap);
        }
        if remainder.is_zero() {
            return result.rounded(inverse, precision, &unit);
        }
        if bit % 16 == 0 {
            let envelope = Bounds {
                low: result.low.clone(),
                high: (&result.high * &root.high).div_ceil(&unit).min(cap.clone()),
            };
            if let Some(value) = envelope.rounded(inverse, precision, &unit) {
                return Some(value);
            }
        }
    }
    None
}

pub(super) fn power(base: &Decimal, exponent: &Decimal) -> Result<Cell> {
    if base.is_zero() {
        return if exponent.sign() == Sign::Plus {
            q(Decimal::from(0)).map(Some)
        } else {
            Ok(None)
        };
    }
    if exponent.is_zero() {
        return q(Decimal::from(1)).map(Some);
    }
    let (p, degree) = fraction(&exponent.abs());
    if base.sign() == Sign::Minus && degree != BigInt::from(1) {
        return Ok(None);
    }
    let negative = base.sign() == Sign::Minus && p.is_odd();
    let (mut n, mut d) = fraction(&base.abs());
    if exponent.sign() == Sign::Minus {
        std::mem::swap(&mut n, &mut d);
    }
    let out = if n == d {
        q(Decimal::from(1))?
    } else if let (Some(p @ 1..=16), Some(degree @ 1..=16)) = (p.to_u32(), degree.to_u32()) {
        q(exact_root(n.pow(p), d.pow(p), degree))?
    } else {
        let inverse = n < d;
        if inverse {
            std::mem::swap(&mut n, &mut d);
        }
        [48, 96, 192, 384]
            .into_iter()
            .find_map(|precision| positive_power((&n, &d), (&p, &degree), inverse, precision))
            .ok_or(Error::NumericFailure)??
    };
    Ok(Some(if negative && !out.is_zero() {
        -out
    } else {
        out
    }))
}

#[cfg(test)]
#[path = "tests/power_tests.rs"]
mod tests;
