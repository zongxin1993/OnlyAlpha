//! Decimal common algebra for native Operator semantics 2. No I/O, registration,
//! identity or Python boundary. Arithmetic uses precision 28 HALF_EVEN and q12
//! public outputs. Every numeric zero is canonical positive zero, including
//! signed-zero input spellings and negative results rounded to zero. This API
//! does not preserve Python Decimal signed-zero representations.
//! Cross-section columns describe one already bound event-time plane in canonical
//! instrument order; the caller owns cohort membership and instrument identity.
pub use bigdecimal::BigDecimal as Decimal;
use bigdecimal::{RoundingMode, Zero};
use num_bigint::{BigInt, Sign};
use num_integer::Integer;
use std::num::{NonZeroU64, NonZeroUsize};

const PRECISION: u64 = 28;
/// Deterministic resource admission limits, independent of numeric semantics.
pub const MAX_INPUT_DIGITS: u64 = 256;
pub const MAX_INPUT_SCALE: i64 = 1024;
pub const MAX_WINDOW: usize = 100_000;
pub const MAX_CELLS: usize = 1_000_000;
pub const MAX_WINDOW_WORK: usize = 50_000_000;
type Cell = Option<Decimal>;
pub type Columns = Vec<Vec<Cell>>;
pub type Result<T> = std::result::Result<T, Error>;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Error {
    InvalidParameters,
    InvalidInputs,
    BudgetExceeded,
    NumericFailure,
    ResearchOnly,
    Interrupted,
}
impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for Error {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Operator {
    Add,
    Subtract,
    Multiply,
    Divide,
    Abs,
    Sign,
    Log,
    Delay,
    Delta,
    RollingMean,
    RollingSum,
    RollingStd,
    RollingVar,
    RollingMin,
    RollingMax,
    RollingCovariance,
    RollingCorrelation,
    TSRank,
    Scale,
    DecayLinear,
    CrossSectionPercentile,
    CrossSectionRank,
    CrossSectionZScore,
    CrossSectionDemean,
}
impl Operator {
    pub fn is_cross_section(self) -> bool {
        matches!(
            self,
            Self::CrossSectionPercentile
                | Self::CrossSectionRank
                | Self::CrossSectionZScore
                | Self::CrossSectionDemean
        )
    }
    pub fn input_count(self) -> usize {
        if matches!(
            self,
            Self::Add
                | Self::Subtract
                | Self::Multiply
                | Self::Divide
                | Self::RollingCovariance
                | Self::RollingCorrelation
        ) {
            2
        } else {
            1
        }
    }
    pub fn needs_period(self) -> bool {
        matches!(
            self,
            Self::Delay
                | Self::Delta
                | Self::RollingMean
                | Self::RollingSum
                | Self::RollingStd
                | Self::RollingVar
                | Self::RollingMin
                | Self::RollingMax
                | Self::RollingCovariance
                | Self::RollingCorrelation
                | Self::TSRank
                | Self::DecayLinear
        )
    }
}
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Parameters {
    pub period: Option<NonZeroUsize>,
    pub factor: Option<Decimal>,
    pub lower_is_better: bool,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Kernel {
    operator: Operator,
    parameters: Parameters,
}
impl Kernel {
    pub fn new(operator: Operator, mut parameters: Parameters) -> Result<Self> {
        if operator.needs_period() != parameters.period.is_some()
            || (operator != Operator::Scale && parameters.factor.is_some())
            || (operator != Operator::CrossSectionPercentile && parameters.lower_is_better)
        {
            return Err(Error::InvalidParameters);
        }
        if parameters.period.is_some_and(|p| p.get() > MAX_WINDOW) {
            return Err(Error::BudgetExceeded);
        }
        if operator == Operator::Scale {
            parameters.factor.get_or_insert_with(|| Decimal::from(1));
        }
        if let Some(f) = &parameters.factor {
            validate(f)?;
        }
        Ok(Self {
            operator,
            parameters,
        })
    }
    pub fn operator(&self) -> Operator {
        self.operator
    }
    pub fn history_limit(&self) -> usize {
        self.parameters.period.map_or(1, |p| {
            p.get() + usize::from(matches!(self.operator, Operator::Delay | Operator::Delta))
        })
    }
    fn validate_columns(&self, columns: &[Vec<Cell>]) -> Result<usize> {
        if columns.len() != self.operator.input_count() {
            return Err(Error::InvalidInputs);
        }
        let n = columns[0].len();
        if n.saturating_mul(columns.len()) > MAX_CELLS {
            return Err(Error::BudgetExceeded);
        }
        if columns.iter().any(|c| c.len() != n) {
            return Err(Error::InvalidInputs);
        }
        for value in columns.iter().flatten().flatten() {
            validate(value)?;
        }
        Ok(n)
    }
    pub fn evaluate(&self, columns: &[Vec<Cell>]) -> Result<Vec<Cell>> {
        self.evaluate_controlled(columns, || Ok(()))
    }
    /// The caller supplies explicit cancellation/deadline observations. The pure
    /// kernel reads no clock or environment and commits no partial result.
    pub fn evaluate_controlled(
        &self,
        columns: &[Vec<Cell>],
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<Vec<Cell>> {
        check()?;
        let n = self.validate_columns(columns)?;
        if self.operator.is_cross_section() {
            return self.cross_section(&columns[0]);
        }
        if n.saturating_mul(self.history_limit())
            .saturating_mul(columns.len())
            > MAX_WINDOW_WORK
        {
            return Err(Error::BudgetExceeded);
        }
        (0..n)
            .map(|i| {
                check()?;
                self.at(columns, i)
            })
            .collect()
    }
    fn at(&self, c: &[Vec<Cell>], i: usize) -> Result<Cell> {
        use Operator::*;
        let op = self.operator;
        let v = &c[0][i];
        if matches!(op, Add | Subtract | Multiply | Divide) {
            let (Some(a), Some(b)) = (v.as_ref(), c[1][i].as_ref()) else {
                return Ok(None);
            };
            let r = match op {
                Add => add(a, b),
                Subtract => sub(a, b),
                Multiply => mul(a, b),
                Divide => {
                    if b.is_zero() {
                        return Ok(None);
                    }
                    div(a, b)?
                }
                _ => unreachable!(),
            };
            return q(r).map(Some);
        }
        if matches!(op, Abs | Sign | Log | Scale) {
            let Some(v) = v else { return Ok(None) };
            let r = match op {
                Abs => round(v.abs()),
                Sign => Decimal::from(if v.is_zero() {
                    0
                } else if v.sign() == num_bigint::Sign::Minus {
                    -1
                } else {
                    1
                }),
                Log => {
                    if v <= &Decimal::from(0) {
                        return Ok(None);
                    }
                    ln(v)?
                }
                Scale => mul(
                    v,
                    self.parameters
                        .factor
                        .as_ref()
                        .expect("validated scale factor"),
                ),
                _ => unreachable!(),
            };
            return q(r).map(Some);
        }
        let p = self.parameters.period.expect("validated period").get();
        if matches!(op, Delay | Delta) {
            if i < p {
                return Ok(None);
            }
            let Some(old) = c[0][i - p].as_ref() else {
                return Ok(None);
            };
            if op == Delay {
                return q(old.clone()).map(Some);
            }
            let Some(now) = v.as_ref() else {
                return Ok(None);
            };
            return q(sub(now, old)).map(Some);
        }
        if i + 1 < p {
            return Ok(None);
        }
        let start = i + 1 - p;
        if c.iter()
            .any(|col| col[start..=i].iter().any(Option::is_none))
        {
            return Ok(None);
        }
        let x: Vec<_> = c[0][start..=i]
            .iter()
            .map(|v| v.as_ref().expect("complete window"))
            .collect();
        let result = match op {
            RollingSum => sum(&x),
            RollingMean => mean(&x)?,
            RollingMin => (*x.iter().min().expect("nonempty window")).clone(),
            RollingMax => (*x.iter().max().expect("nonempty window")).clone(),
            RollingVar | RollingStd => {
                let var = variance(&x, &mean(&x)?)?;
                if op == RollingStd { sqrt(&var)? } else { var }
            }
            TSRank => rank(&x, x[x.len() - 1])?,
            DecayLinear => {
                let mut s = Decimal::from(0);
                for (k, v) in x.iter().enumerate() {
                    s = add(&s, &mul(v, &Decimal::from((k + 1) as u64)));
                }
                div(&s, &Decimal::from((p as u64) * (p as u64 + 1) / 2))?
            }
            RollingCovariance | RollingCorrelation => {
                let y: Vec<_> = c[1][start..=i]
                    .iter()
                    .map(|v| v.as_ref().expect("complete window"))
                    .collect();
                let (mx, my) = (mean(&x)?, mean(&y)?);
                let mut total = Decimal::from(0);
                for (a, b) in x.iter().zip(&y) {
                    total = add(&total, &mul(&sub(a, &mx), &sub(b, &my)));
                }
                let cov = div(&total, &Decimal::from(p as u64))?;
                if op == RollingCovariance {
                    cov
                } else {
                    let (vx, vy) = (variance(&x, &mx)?, variance(&y, &my)?);
                    if vx.is_zero() || vy.is_zero() {
                        return Ok(None);
                    }
                    div(&cov, &sqrt(&mul(&vx, &vy))?)?
                }
            }
            _ => return Err(Error::InvalidInputs),
        };
        q(result).map(Some)
    }
    fn cross_section(&self, values: &[Cell]) -> Result<Vec<Cell>> {
        let eligible: Vec<_> = values.iter().flatten().collect();
        if eligible.is_empty() {
            return Ok(vec![None; values.len()]);
        }
        let op = self.operator;
        let scores = if matches!(
            op,
            Operator::CrossSectionRank | Operator::CrossSectionPercentile
        ) {
            let mut sorted = eligible.clone();
            sorted.sort();
            let mut scores = std::collections::BTreeMap::new();
            for value in &sorted {
                if !scores.contains_key(*value) {
                    let low = sorted.partition_point(|v| *v < *value);
                    let high = sorted.partition_point(|v| *v <= *value);
                    scores.insert(*value, rank_counts(sorted.len(), low, high - low)?);
                }
            }
            scores
        } else {
            std::collections::BTreeMap::new()
        };
        let avg = if matches!(
            op,
            Operator::CrossSectionDemean | Operator::CrossSectionZScore
        ) {
            Some(mean(&eligible)?)
        } else {
            None
        };
        let std = if op == Operator::CrossSectionZScore {
            let v = variance(&eligible, avg.as_ref().expect("mean"))?;
            if v.is_zero() {
                return Ok(vec![None; values.len()]);
            }
            Some(sqrt(&v)?)
        } else {
            None
        };
        values
            .iter()
            .map(|v| {
                let Some(v) = v else { return Ok(None) };
                let r = match op {
                    Operator::CrossSectionRank | Operator::CrossSectionPercentile => {
                        let r = scores.get(v).expect("eligible rank").clone();
                        if self.parameters.lower_is_better {
                            sub(&Decimal::from(1), &r)
                        } else {
                            r
                        }
                    }
                    Operator::CrossSectionDemean => sub(v, avg.as_ref().expect("mean")),
                    Operator::CrossSectionZScore => div(
                        &sub(v, avg.as_ref().expect("mean")),
                        std.as_ref().expect("std"),
                    )?,
                    _ => return Err(Error::InvalidInputs),
                };
                q(r).map(Some)
            })
            .collect()
    }
}

/// Candidate updates and restores are committed only after complete validation
/// and numerical evaluation. Checkpoint transport/schema/identity is caller-owned.
#[derive(Clone, Debug)]
pub struct Stream {
    kernel: Kernel,
    columns: Columns,
}
impl Stream {
    pub fn new(kernel: Kernel) -> Result<Self> {
        if kernel.operator.is_cross_section() {
            return Err(Error::ResearchOnly);
        }
        let columns = vec![Vec::new(); kernel.operator.input_count()];
        Ok(Self { kernel, columns })
    }
    pub fn checkpoint(&self) -> Columns {
        self.columns.clone()
    }
    pub fn restore(&mut self, candidate: Columns) -> Result<()> {
        let n = self.kernel.validate_columns(&candidate)?;
        if n > self.kernel.history_limit() {
            return Err(Error::InvalidInputs);
        }
        if n > 0 {
            self.kernel.at(&candidate, n - 1)?;
        }
        self.columns = candidate;
        Ok(())
    }
    pub fn push(&mut self, values: &[Cell]) -> Result<Cell> {
        if values.len() != self.columns.len() {
            return Err(Error::InvalidInputs);
        }
        for v in values.iter().flatten() {
            validate(v)?;
        }
        let mut candidate = self.columns.clone();
        for (col, v) in candidate.iter_mut().zip(values) {
            col.push(v.clone());
            if col.len() > self.kernel.history_limit() {
                col.remove(0);
            }
        }
        let result = self.kernel.at(&candidate, candidate[0].len() - 1)?;
        self.columns = candidate;
        Ok(result)
    }
}

fn validate(v: &Decimal) -> Result<()> {
    let (_, scale) = v.as_bigint_and_exponent();
    if v.digits() > MAX_INPUT_DIGITS || scale.unsigned_abs() > MAX_INPUT_SCALE as u64 {
        Err(Error::BudgetExceeded)
    } else {
        Ok(())
    }
}
fn round(v: Decimal) -> Decimal {
    v.with_precision_round(
        NonZeroU64::new(PRECISION).expect("positive precision"),
        RoundingMode::HalfEven,
    )
}
fn q(v: Decimal) -> Result<Decimal> {
    let v = v.with_scale_round(12, RoundingMode::HalfEven);
    if v.digits() > PRECISION {
        Err(Error::NumericFailure)
    } else if v.is_zero() {
        Ok(Decimal::new(BigInt::ZERO, 12))
    } else {
        Ok(v)
    }
}
fn add(a: &Decimal, b: &Decimal) -> Decimal {
    round(a + b)
}
fn sub(a: &Decimal, b: &Decimal) -> Decimal {
    round(a - b)
}
fn mul(a: &Decimal, b: &Decimal) -> Decimal {
    round(a * b)
}
fn pow10(n: usize) -> BigInt {
    BigInt::from(10u8).pow(n as u32)
}
fn div(a: &Decimal, b: &Decimal) -> Result<Decimal> {
    if b.is_zero() {
        return Err(Error::NumericFailure);
    }
    let (mut n, sa) = a.as_bigint_and_exponent();
    let (mut d, sb) = b.as_bigint_and_exponent();
    let shift = sb - sa;
    if shift >= 0 {
        n *= pow10(shift as usize)
    } else {
        d *= pow10((-shift) as usize)
    }
    ratio(n, d)
}
/// One exact rational division followed by a single precision-28 rounding.
fn ratio(mut n: BigInt, mut d: BigInt) -> Result<Decimal> {
    if d == BigInt::ZERO {
        return Err(Error::NumericFailure);
    }
    if n == BigInt::ZERO {
        return Ok(Decimal::from(0));
    }
    let negative = n.sign() != d.sign();
    n = if n.sign() == Sign::Minus { -n } else { n };
    d = if d.sign() == Sign::Minus { -d } else { d };
    let estimate = n.to_str_radix(10).len() as i64 - d.to_str_radix(10).len() as i64;
    let ge = if estimate >= 0 {
        n >= &d * pow10(estimate as usize)
    } else {
        &n * pow10((-estimate) as usize) >= d
    };
    let magnitude = estimate - i64::from(!ge);
    let scale = 27 - magnitude;
    if scale >= 0 {
        n *= pow10(scale as usize)
    } else {
        d *= pow10((-scale) as usize)
    }
    let coeff = crate::round_ratio(&n, &d);
    Ok(Decimal::new(if negative { -coeff } else { coeff }, scale))
}
/// Exact rational midpoint comparison proves precision-28 HALF_EVEN rounding.
fn sqrt(v: &Decimal) -> Result<Decimal> {
    let (coefficient, scale) = v.as_bigint_and_exponent();
    if coefficient.sign() == Sign::Minus {
        return Err(Error::NumericFailure);
    }
    if coefficient == BigInt::ZERO {
        return Ok(Decimal::from(0));
    }
    let exponent = coefficient.to_str_radix(10).len() as i64 - 1 - scale;
    let target_scale = 27 - exponent.div_euclid(2);
    let power = 2 * target_scale - scale;
    let (a, b) = if power >= 0 {
        (coefficient * pow10(power as usize), BigInt::from(1))
    } else {
        (coefficient, pow10((-power) as usize))
    };
    let mut floor = (&a / &b).sqrt();
    let twice_plus_one = (&floor << 1) + 1;
    let midpoint = &b * &twice_plus_one * &twice_plus_one;
    let four_a = &a << 2;
    if four_a > midpoint || four_a == midpoint && floor.is_odd() {
        floor += 1;
    }
    Ok(Decimal::new(floor, target_scale))
}
fn sum(values: &[&Decimal]) -> Decimal {
    values.iter().fold(Decimal::from(0), |s, v| add(&s, v))
}
fn mean(values: &[&Decimal]) -> Result<Decimal> {
    div(&sum(values), &Decimal::from(values.len() as u64))
}
fn variance(values: &[&Decimal], mean: &Decimal) -> Result<Decimal> {
    let mut total = Decimal::from(0);
    for v in values {
        let delta = sub(v, mean);
        total = add(&total, &mul(&delta, &delta));
    }
    div(&total, &Decimal::from(values.len() as u64))
}
fn rank(values: &[&Decimal], target: &Decimal) -> Result<Decimal> {
    let low = values.iter().filter(|v| ***v < *target).count();
    let equal = values.iter().filter(|v| ***v == *target).count();
    rank_counts(values.len(), low, equal)
}
fn rank_counts(size: usize, low: usize, equal: usize) -> Result<Decimal> {
    if size == 1 {
        return Ok(Decimal::new(BigInt::from(5), 1));
    }
    let half = div(&Decimal::from((equal - 1) as u64), &Decimal::from(2))?;
    div(
        &add(&Decimal::from(low as u64), &half),
        &Decimal::from((size - 1) as u64),
    )
}

/// Correctly rounded natural logarithm. Positive rational atanh series give
/// rigorous lower/upper bounds, including truncation and fixed-scale rounding.
/// No binary float, inverse approximation or unproved convergence threshold.
fn ln(v: &Decimal) -> Result<Decimal> {
    if v == &Decimal::from(1) {
        return Ok(Decimal::from(0));
    }
    let (mut n, scale) = v.as_bigint_and_exponent();
    let mut d = BigInt::from(1);
    if scale >= 0 {
        d = pow10(scale as usize)
    } else {
        n *= pow10((-scale) as usize)
    }
    let negative = n < d;
    if negative {
        std::mem::swap(&mut n, &mut d);
    }
    let mut k = 0u32;
    while n >= (&d << 1) {
        d <<= 1;
        k += 1;
    }
    let zn = &n - &d;
    let zd = &n + &d;
    // Relative precision must include leading zeros of ln(x) when x is close
    // to one. Input admission bounds this offset; absolute precision alone
    // would fail for valid 256-digit values such as 1 + 10^-255.
    let offset = if k == 0 {
        zd.to_str_radix(10)
            .len()
            .saturating_sub(zn.to_str_radix(10).len())
    } else {
        0
    };
    for extra in [64usize, 96, 144, 216] {
        let precision = offset + extra;
        let unit = pow10(precision);
        let (mut low, mut high) = log_bounds(&zn, &zd, &unit, precision)?;
        if k != 0 {
            let (lo, hi) = log_bounds(&BigInt::from(1), &BigInt::from(3), &unit, precision)?;
            low += lo * k;
            high += hi * k;
        }
        if negative {
            let old_low = low;
            low = -high;
            high = -old_low;
        }
        let lo = round(Decimal::new(low, precision as i64));
        let hi = round(Decimal::new(high, precision as i64));
        if lo == hi {
            return Ok(lo);
        }
    }
    Err(Error::NumericFailure)
}
fn ceil_ratio(n: &BigInt, d: &BigInt) -> BigInt {
    (n + d - 1) / d
}
fn log_bounds(n: &BigInt, d: &BigInt, unit: &BigInt, precision: usize) -> Result<(BigInt, BigInt)> {
    if n == &BigInt::ZERO {
        return Ok((BigInt::ZERO, BigInt::ZERO));
    }
    if n * 3 > d.clone() {
        return Err(Error::NumericFailure);
    }
    // All interval endpoints are directed fixed-scale integer bounds. Keeping
    // powers at fixed scale bounds resource use even for very long inputs.
    let zl = n * unit / d;
    let zu = ceil_ratio(&(n * unit), d);
    let z2l = &zl * &zl / unit;
    let z2u = ceil_ratio(&(&zu * &zu), unit);
    let (mut pl, mut pu) = (zl, zu);
    let (mut low, mut high) = (BigInt::ZERO, BigInt::ZERO);
    let terms = precision * 2;
    for i in 0..terms {
        let odd = BigInt::from(2 * i + 1);
        low += &pl / &odd;
        high += ceil_ratio(&pu, &odd);
        pl = &pl * &z2l / unit;
        pu = ceil_ratio(&(&pu * &z2u), unit);
    }
    // For 0 <= z <= 1/3, remainder <= 3*z^(2M+1)/(2M+1).
    // M=2*precision makes this < 10^-precision, i.e. one unit.
    Ok((low * 2, high * 2 + 1))
}

#[cfg(test)]
#[path = "tests/algebra_tests.rs"]
mod tests;
