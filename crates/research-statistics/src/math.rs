//! 冻结面板上的逐时点相关系数及其样本摘要（ADR 0082、0114、0119）。
use super::{Cell, Decimal, Error, error};
use bigdecimal::{Context, RoundingMode, Signed, Zero, num_bigint::BigInt};
use std::num::NonZeroU64;

const PRECISION: u64 = 38;
const OUTPUT_SCALE: i64 = 12;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StatisticStatus {
    Valid,
    InsufficientObservations,
    ZeroVarianceFeature,
    ZeroVarianceTarget,
    NoValidObservations,
    ZeroVariance,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct MissingCounts {
    pub missing_factor_only: usize,
    pub missing_target_only: usize,
    pub missing_both: usize,
}

/// IC 和 RankIC 共用一个完整配对集合，因而具有相同的可计算状态。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StatisticRow {
    pub sample_count: usize,
    pub missing_counts: MissingCounts,
    pub status: StatisticStatus,
    pub ic: Cell,
    pub rank_ic: Cell,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SignStatistics {
    pub positive_count: usize,
    pub negative_count: usize,
    pub zero_count: usize,
    pub positive_ratio: Cell,
    pub negative_ratio: Cell,
    pub zero_ratio: Cell,
    pub ratio_status: StatisticStatus,
}

/// 每个标量独立记录状态。例如，常数序列的样本标准差有效且为零。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SeriesStatistics {
    pub total_count: usize,
    pub observations: usize,
    pub signs: SignStatistics,
    pub mean: Cell,
    pub mean_status: StatisticStatus,
    pub std: Cell,
    pub std_status: StatisticStatus,
    pub ir: Cell,
    pub ir_status: StatisticStatus,
}

fn context() -> Context {
    Context::new(NonZeroU64::new(PRECISION).unwrap(), RoundingMode::HalfEven)
}

fn numeric_failure() -> Error {
    error("RESEARCH_NUMERIC_FAILURE")
}

fn publish(value: &Decimal) -> Result<Decimal, Error> {
    let value = value.with_scale_round(OUTPUT_SCALE, RoundingMode::HalfEven);
    if value.digits() > PRECISION {
        return Err(numeric_failure());
    }
    Ok(value)
}

/// 对整数系数作长除，依据完整余数一次舍入到 38 位。BigDecimal 的 `/` 使用构建时默认精度。
fn divide(a: &Decimal, b: &Decimal) -> Result<Decimal, Error> {
    if b.is_zero() {
        return Err(numeric_failure());
    }
    if a.is_zero() {
        return Ok(Decimal::zero());
    }
    let (num, a_scale) = a.as_bigint_and_exponent();
    let (den, b_scale) = b.as_bigint_and_exponent();
    let negative = num.sign() != den.sign();
    let (mut num, mut den) = (num.abs(), den.abs());
    let mut shift = PRECISION as i64 + b.digits() as i64 - a.digits() as i64;
    let ten = BigInt::from(10u8);
    let power = ten.pow(u32::try_from(shift.unsigned_abs()).map_err(|_| numeric_failure())?);
    if shift >= 0 {
        num *= power;
    } else {
        den *= power;
    }
    // 此时整数商有 38 或 39 位，先定位最后一个保留位，再比较中点。
    if num >= &den * ten.pow(PRECISION as u32) {
        den *= 10u8;
        shift -= 1;
    }
    let mut coefficient = &num / &den;
    let twice_remainder = (num % &den) * 2u8;
    if twice_remainder > den || (twice_remainder == den && coefficient.bit(0)) {
        coefficient += 1u8;
    }
    if negative {
        coefficient = -coefficient;
    }
    Ok(Decimal::new(coefficient, shift + a_scale - b_scale).normalized())
}

/// 将根的最后一个有效位移到个位，以整数比较证明精确根位于哪个舍入区间。
fn sqrt(value: &Decimal) -> Result<Decimal, Error> {
    if value.is_zero() {
        return Ok(Decimal::zero());
    }
    if value.is_negative() {
        return Err(numeric_failure());
    }
    let (coefficient, scale) = value.as_bigint_and_exponent();
    let exponent = value.digits() as i64 - 1 - scale;
    let result_scale = PRECISION as i64 - 1 - exponent.div_euclid(2);
    let shift = 2 * result_scale - scale;
    let power =
        BigInt::from(10u8).pow(u32::try_from(shift.unsigned_abs()).map_err(|_| numeric_failure())?);
    let (num, den) = if shift >= 0 {
        (coefficient * power, BigInt::from(1u8))
    } else {
        (coefficient, power)
    };
    let mut root = (&num / &den).sqrt();
    let twice_midpoint = &root * 2u8 + 1u8;
    let midpoint_squared = &twice_midpoint * &twice_midpoint * den;
    let four_num = num * 4u8;
    if four_num > midpoint_squared || (four_num == midpoint_squared && root.bit(0)) {
        root += 1u8;
    }
    Ok(Decimal::new(root, result_scale).normalized())
}

fn mean(ctx: &Context, values: &[Decimal]) -> Result<Decimal, Error> {
    let sum = values
        .iter()
        .fold(Decimal::zero(), |s, v| ctx.add_refs(&s, v));
    divide(&sum, &Decimal::from(values.len() as u64))
}

fn dot(ctx: &Context, xs: &[Decimal], ys: &[Decimal]) -> Decimal {
    xs.iter().zip(ys).fold(Decimal::zero(), |sum, (x, y)| {
        ctx.add_refs(&sum, &ctx.multiply(x, y))
    })
}

/// 先平移再中心化，保留大基数上小于 38 位相对精度的原始差值。
fn center(ctx: &Context, values: &mut [Decimal]) -> Result<(), Error> {
    let origin = values[0].clone();
    for value in values.iter_mut() {
        *value = ctx.round_decimal(&*value - &origin);
    }
    let offset_mean = mean(ctx, values)?;
    for value in values {
        *value = ctx.round_decimal(&*value - &offset_mean);
    }
    Ok(())
}

fn pearson(ctx: &Context, mut xs: Vec<Decimal>, mut ys: Vec<Decimal>) -> Result<Decimal, Error> {
    center(ctx, &mut xs)?;
    center(ctx, &mut ys)?;
    let variance_product = ctx.multiply(&dot(ctx, &xs, &xs), &dot(ctx, &ys, &ys));
    let denominator = sqrt(&variance_product)?;
    publish(&divide(&dot(ctx, &xs, &ys), &denominator)?)
}

fn average_ranks(values: &[&Decimal]) -> Vec<Decimal> {
    let mut order: Vec<_> = (0..values.len()).collect();
    order.sort_unstable_by_key(|&index| values[index]);
    let mut ranks = vec![Decimal::zero(); values.len()];
    let mut start = 0;
    while start < order.len() {
        let mut end = start + 1;
        while end < order.len() && values[order[end]] == values[order[start]] {
            end += 1;
        }
        // 一基闭区间 [start + 1, end] 的中秩始终为整数或半整数。
        let rank = (Decimal::from((start + 1) as u64) + Decimal::from(end as u64)).half();
        for &index in &order[start..end] {
            ranks[index] = rank.clone();
        }
        start = end;
    }
    ranks
}

pub(super) fn row(
    pairs: Vec<(&Decimal, &Decimal)>,
    missing_counts: MissingCounts,
    minimum: usize,
) -> Result<StatisticRow, Error> {
    let sample_count = pairs.len();
    if minimum < 2 {
        return Err(error("RESEARCH_PLAN_INVALID"));
    }
    let status = if sample_count < minimum {
        StatisticStatus::InsufficientObservations
    } else if pairs.iter().all(|p| p.0 == pairs[0].0) {
        StatisticStatus::ZeroVarianceFeature
    } else if pairs.iter().all(|p| p.1 == pairs[0].1) {
        StatisticStatus::ZeroVarianceTarget
    } else {
        StatisticStatus::Valid
    };
    if status != StatisticStatus::Valid {
        return Ok(StatisticRow {
            sample_count,
            missing_counts,
            status,
            ic: None,
            rank_ic: None,
        });
    }
    let ctx = context();
    let (xs, ys): (Vec<_>, Vec<_>) = pairs.into_iter().unzip();
    let ic = pearson(
        &ctx,
        xs.iter().copied().cloned().collect(),
        ys.iter().copied().cloned().collect(),
    )?;
    let rank_ic = pearson(&ctx, average_ranks(&xs), average_ranks(&ys))?;
    Ok(StatisticRow {
        sample_count,
        missing_counts,
        status,
        ic: Some(ic),
        rank_ic: Some(rank_ic),
    })
}

pub(super) fn ratio(numerator: usize, denominator: usize) -> Result<Cell, Error> {
    if denominator == 0 {
        return Ok(None);
    }
    let value = divide(
        &Decimal::from(numerator as u64),
        &Decimal::from(denominator as u64),
    )?;
    Ok(Some(publish(&value)?))
}

fn signs(values: &[Decimal]) -> Result<SignStatistics, Error> {
    let n = values.len();
    let positive_count = values.iter().filter(|v| v.is_positive()).count();
    let negative_count = values.iter().filter(|v| v.is_negative()).count();
    let zero_count = n - positive_count - negative_count;
    Ok(SignStatistics {
        positive_count,
        negative_count,
        zero_count,
        positive_ratio: ratio(positive_count, n)?,
        negative_ratio: ratio(negative_count, n)?,
        zero_ratio: ratio(zero_count, n)?,
        ratio_status: if n == 0 {
            StatisticStatus::NoValidObservations
        } else {
            StatisticStatus::Valid
        },
    })
}

pub(super) fn summarize(values: impl Iterator<Item = Cell>) -> Result<SeriesStatistics, Error> {
    use StatisticStatus::{InsufficientObservations, NoValidObservations, Valid, ZeroVariance};

    let mut total_count = 0;
    let mut values: Vec<_> = values.inspect(|_| total_count += 1).flatten().collect();
    let observations = values.len();
    let mut summary = SeriesStatistics {
        total_count,
        observations,
        signs: signs(&values)?,
        mean: None,
        mean_status: NoValidObservations,
        std: None,
        std_status: InsufficientObservations,
        ir: None,
        ir_status: InsufficientObservations,
    };
    if observations == 0 {
        return Ok(summary);
    }
    let ctx = context();
    let average = mean(&ctx, &values)?;
    summary.mean = Some(publish(&average)?);
    summary.mean_status = Valid;
    if observations == 1 {
        return Ok(summary);
    }
    for value in &mut values {
        *value = ctx.round_decimal(&*value - &average);
    }
    let variance = divide(
        &dot(&ctx, &values, &values),
        &Decimal::from((observations - 1) as u64),
    )?;
    let std = sqrt(&variance)?;
    summary.std = Some(publish(&std)?);
    summary.std_status = Valid;
    if std.is_zero() {
        summary.ir_status = ZeroVariance;
    } else {
        summary.ir = Some(publish(&divide(&average, &std)?)?);
        summary.ir_status = Valid;
    }
    Ok(summary)
}
