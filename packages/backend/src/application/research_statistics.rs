//! Pure time-series Statistics; never admission, Evidence publication or Qualification.
//! Mathematics and limits: docs/research-time-series-statistics.md.
use bigdecimal::{
    BigDecimal,
    num_bigint::{BigInt, BigUint, Sign},
};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{cmp::Ordering, str::FromStr};

const METHOD: &str = "ONLYALPHA_TIME_SERIES_ASSOCIATION_V1";
const QUANTUM: u64 = 1_000_000_000_000;
type Result<T> = std::result::Result<T, &'static str>;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Bindings {
    pub dataset: String,
    pub feature_result: String,
    pub target_result: String,
    pub factor_revision: String,
    pub study: String,
}
#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Metric {
    Pearson,
    Spearman,
}
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(deny_unknown_fields)]
pub struct Comparison {
    pub start_ns: u64,
    pub end_ns: u64,
    pub horizon_bars: u32,
    pub metric: Metric,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Plan {
    pub schema_version: u32,
    pub bindings: Bindings,
    pub start_ns: u64,
    pub end_ns: u64,
    pub bar_ns: u64,
    pub horizon_bars: u32,
    pub expected_block_length: u32,
    pub replicates: u32,
    pub confidence_bps: u32,
    pub seed: String,
    pub family: Vec<Comparison>,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Observation {
    pub at_ns: u64,
    pub feature: Option<String>,
    pub target: Option<String>,
}
#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Status {
    Available,
    InsufficientPairs,
    ZeroVarianceFeature,
    ZeroVarianceTarget,
    GappedAxis,
    IncompletePairs,
    InsufficientBlocks,
    TailResolutionInsufficient,
    UndefinedBootstrapReplicates,
    BootstrapDistributionDegenerate,
}
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct Estimate {
    pub point_status: Status,
    pub value: Option<String>,
    pub uncertainty_status: Status,
    pub interval: Option<[String; 2]>,
    pub undefined_replicates: u32,
}
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct Diagnostics {
    pub expected_rows: usize,
    pub observed_rows: usize,
    pub boundary_excluded: usize,
    pub complete_pairs: usize,
    pub missing_feature: usize,
    pub missing_target: usize,
    pub axis_gaps: usize,
}
#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
pub struct Analysis {
    pub plan_fingerprint: String,
    pub input_fingerprint: String,
    pub diagnostics: Diagnostics,
    pub pearson: Estimate,
    pub spearman: Estimate,
}
fn fingerprint(v: &serde_json::Value) -> Result<String> {
    onlyalpha_metadata_json::fingerprint(&v.to_string(), 8 * 1024 * 1024)
        .map_err(|_| "STATISTICS_IDENTITY_INVALID")
}
fn record(v: &impl Serialize) -> Result<serde_json::Value> {
    serde_json::to_value(v).map_err(|_| "STATISTICS_RECORD_INVALID")
}
impl Plan {
    fn canonical(&self, observed: usize) -> Result<(Self, usize)> {
        let b = &self.bindings;
        if [
            b.dataset.as_str(),
            &b.feature_result,
            &b.target_result,
            &b.factor_revision,
            &b.study,
            &self.seed,
        ]
        .iter()
        .any(|s| !crate::is_sha256_hex(s))
        {
            return Err("STATISTICS_BINDING_INVALID");
        }
        let width = self
            .end_ns
            .checked_sub(self.start_ns)
            .filter(|v| *v > 0)
            .ok_or("STATISTICS_INTERVAL_INVALID")?;
        if self.schema_version != 1
            || self.bar_ns == 0
            || width % self.bar_ns != 0
            || self.horizon_bars == 0
            || self.expected_block_length < 2
            || self.expected_block_length <= self.horizon_bars
            || !(400..=8192).contains(&self.replicates)
            || !(8000..=9900).contains(&self.confidence_bps)
            || self.family.len() < 2
            || self.family.len() > 32
        {
            return Err("STATISTICS_PLAN_INVALID");
        }
        let expected = width / self.bar_ns;
        if expected > 4096
            || observed > 4096
            || observed as u64 > expected
            || expected <= u64::from(self.horizon_bars)
            || observed as u64 * u64::from(self.replicates) > 8_388_608
        {
            return Err("STATISTICS_RESOURCE_OR_SCOPE_INVALID");
        }
        let mut canonical = self.clone();
        canonical.family.sort();
        if canonical.family.windows(2).any(|w| w[0] == w[1])
            || canonical.family.iter().any(|c| {
                c.start_ns >= c.end_ns
                    || c.horizon_bars == 0
                    || (c.end_ns - c.start_ns) % self.bar_ns != 0
                    || (c.end_ns - c.start_ns) / self.bar_ns <= u64::from(c.horizon_bars)
            })
        {
            return Err("STATISTICS_FAMILY_INVALID");
        }
        for metric in [Metric::Pearson, Metric::Spearman] {
            if !canonical.family.contains(&Comparison {
                start_ns: self.start_ns,
                end_ns: self.end_ns,
                horizon_bars: self.horizon_bars,
                metric,
            }) {
                return Err("STATISTICS_FAMILY_INCOMPLETE");
            }
        }
        Ok((canonical, expected as usize))
    }
}
/// Exact finite decimal parser. Resource bounds precede arbitrary-magnitude allocation.
pub(crate) fn decimal(s: &str) -> Result<(String, BigInt)> {
    let unsigned = s.strip_prefix('-').unwrap_or(s);
    let (whole, fraction) = unsigned.split_once('.').unwrap_or((unsigned, ""));
    if whole.is_empty()
        || whole.len() > 20
        || fraction.len() > 18
        || whole.len() + fraction.len() > 38
        || s.ends_with('.')
        || !whole
            .bytes()
            .chain(fraction.bytes())
            .all(|b| b.is_ascii_digit())
    {
        return Err("STATISTICS_DECIMAL_INVALID");
    }
    let value = BigDecimal::from_str(s).map_err(|_| "STATISTICS_DECIMAL_INVALID")?;
    let canonical = value.normalized().to_plain_string();
    let (integer, scale) = value.as_bigint_and_exponent();
    let power = u32::try_from(18 - scale).map_err(|_| "STATISTICS_DECIMAL_INVALID")?;
    Ok((canonical, integer * BigInt::from(10u8).pow(power)))
}
fn formatted(value: i64) -> String {
    let sign = if value < 0 { "-" } else { "" };
    let magnitude = value.unsigned_abs();
    format!("{sign}{}.{:012}", magnitude / QUANTUM, magnitude % QUANTUM)
}
/// Round C/sqrt(A*B) by comparing exact squared half-quantum boundaries.
fn rounded(c: &BigInt, a: &BigInt, b: &BigInt) -> i64 {
    let numerator = c.magnitude() * BigUint::from(QUANTUM);
    let squared = &numerator * &numerator;
    let denominator = (a * b).to_biguint().expect("strict positive variances");
    let mut floor = (&squared / &denominator).sqrt();
    let half = &floor * 2u8 + 1u8;
    let comparison = (&squared * 4u8).cmp(&(&denominator * &half * &half));
    if comparison == Ordering::Greater
        || (comparison == Ordering::Equal && &floor % 2u8 == BigUint::from(1u8))
    {
        floor += 1u8;
    }
    let value = i64::from_str(&floor.to_string()).expect("correlation magnitude <= 1e12");
    if c.sign() == Sign::Minus {
        -value
    } else {
        value
    }
}
fn correlation(x: &[BigInt], y: &[BigInt]) -> std::result::Result<i64, Status> {
    if x.len() < 2 {
        return Err(Status::InsufficientPairs);
    }
    let n = BigInt::from(x.len());
    let zero = BigInt::from(0u8);
    let sum_x: BigInt = x.iter().sum();
    let sum_y: BigInt = y.iter().sum();
    let xx: BigInt = x.iter().map(|v| v * v).sum();
    let yy: BigInt = y.iter().map(|v| v * v).sum();
    let xy: BigInt = x.iter().zip(y).map(|(a, b)| a * b).sum();
    let a = &n * xx - &sum_x * &sum_x;
    let b = &n * yy - &sum_y * &sum_y;
    if a == zero {
        return Err(Status::ZeroVarianceFeature);
    }
    if b == zero {
        return Err(Status::ZeroVarianceTarget);
    }
    Ok(rounded(&(&n * xy - sum_x * sum_y), &a, &b))
}
fn ranks(values: &[BigInt]) -> Vec<BigInt> {
    let mut order: Vec<usize> = (0..values.len()).collect();
    order.sort_by(|a, b| values[*a].cmp(&values[*b]));
    let mut result = vec![BigInt::from(0u8); values.len()];
    let mut i = 0;
    while i < order.len() {
        let mut j = i + 1;
        while j < order.len() && values[order[i]] == values[order[j]] {
            j += 1;
        }
        // Twice the average one-based rank: integer scale cancels in Pearson.
        for k in i..j {
            result[order[k]] = BigInt::from(i + j + 1);
        }
        i = j;
    }
    result
}
struct Stream {
    seed: [u8; 32],
    replicate: u64,
    counter: u64,
}
impl Stream {
    fn uniform(&mut self, bound: usize) -> Result<usize> {
        let b = bound as u64;
        let threshold = b.wrapping_neg() % b;
        for _ in 0..64 {
            let mut hash = Sha256::new();
            hash.update(b"ONLYALPHA_STATIONARY_BOOTSTRAP_V1");
            hash.update(self.seed);
            hash.update(self.replicate.to_be_bytes());
            hash.update(self.counter.to_be_bytes());
            self.counter = self
                .counter
                .checked_add(1)
                .ok_or("STATISTICS_RANDOM_STREAM_EXHAUSTED")?;
            let bytes = hash.finalize();
            let value = u64::from_be_bytes(bytes[..8].try_into().expect("SHA256 prefix"));
            if value >= threshold {
                return Ok((value % b) as usize);
            }
        }
        Err("STATISTICS_RANDOM_STREAM_EXHAUSTED")
    }
    fn indices(&mut self, n: usize, block: usize) -> Result<Vec<usize>> {
        let mut at = self.uniform(n)?;
        let mut result = vec![at];
        for _ in 1..n {
            at = if self.uniform(block)? == 0 {
                self.uniform(n)?
            } else {
                (at + 1) % n
            };
            result.push(at);
        }
        Ok(result)
    }
}
fn estimate(point: std::result::Result<i64, Status>, status: Status) -> Estimate {
    match point {
        Ok(value) => Estimate {
            point_status: Status::Available,
            value: Some(formatted(value)),
            uncertainty_status: status,
            interval: None,
            undefined_replicates: 0,
        },
        Err(point_status) => Estimate {
            point_status,
            value: None,
            uncertainty_status: point_status,
            interval: None,
            undefined_replicates: 0,
        },
    }
}
fn finish(estimate: &mut Estimate, values: &mut [i64], plan: &Plan) {
    if estimate.point_status != Status::Available {
        return;
    }
    if estimate.undefined_replicates > 0 {
        estimate.uncertainty_status = Status::UndefinedBootstrapReplicates;
        return;
    }
    values.sort_unstable();
    if values.first() == values.last() {
        estimate.uncertainty_status = Status::BootstrapDistributionDegenerate;
        return;
    }
    let denominator = 20_000 * plan.family.len() as u64;
    let alpha = u64::from(10_000 - plan.confidence_bps);
    let r = u64::from(plan.replicates);
    let lower = ((r + 1) * alpha / denominator).max(1);
    let upper = ((r + 1) * (denominator - alpha))
        .div_ceil(denominator)
        .min(r);
    estimate.interval = Some([
        formatted(values[lower as usize - 1]),
        formatted(values[upper as usize - 1]),
    ]);
    estimate.uncertainty_status = Status::Available;
}
/// Calculates only over supplied series. Caller must prove their owning immutable artifacts.
pub fn evaluate(plan: &Plan, observations: &[Observation]) -> Result<Analysis> {
    let (plan, expected) = plan.canonical(observations.len())?;
    let mut normalized = Vec::with_capacity(observations.len());
    let mut x = Vec::new();
    let mut y = Vec::new();
    let mut times = Vec::new();
    let mut diagnostics = Diagnostics {
        expected_rows: expected,
        observed_rows: observations.len(),
        boundary_excluded: 0,
        complete_pairs: 0,
        missing_feature: 0,
        missing_target: 0,
        axis_gaps: expected - observations.len(),
    };
    let cutoff = plan.end_ns - u64::from(plan.horizon_bars) * plan.bar_ns;
    let mut last = None;
    for row in observations {
        if row.at_ns < plan.start_ns
            || row.at_ns >= plan.end_ns
            || (row.at_ns - plan.start_ns) % plan.bar_ns != 0
            || last.is_some_and(|v| v >= row.at_ns)
        {
            return Err("STATISTICS_AXIS_INVALID");
        }
        last = Some(row.at_ns);
        let feature = row.feature.as_deref().map(decimal).transpose()?;
        let target = row.target.as_deref().map(decimal).transpose()?;
        normalized.push(Observation {
            at_ns: row.at_ns,
            feature: feature.as_ref().map(|v| v.0.clone()),
            target: target.as_ref().map(|v| v.0.clone()),
        });
        if row.at_ns >= cutoff {
            diagnostics.boundary_excluded += 1;
            continue;
        }
        diagnostics.missing_feature += usize::from(feature.is_none());
        diagnostics.missing_target += usize::from(target.is_none());
        if let (Some((_, a)), Some((_, b))) = (feature, target) {
            x.push(a);
            y.push(b);
            times.push(row.at_ns);
        }
    }
    diagnostics.complete_pairs = x.len();
    let interior_axis_gap = times
        .first()
        .zip(times.last())
        .is_some_and(|(first, last)| {
            let retained_rows = observations
                .iter()
                .filter(|row| row.at_ns >= *first && row.at_ns <= *last)
                .count();
            (retained_rows as u64) < (last - first) / plan.bar_ns + 1
        });
    let status = if interior_axis_gap {
        Status::GappedAxis
    } else if times.windows(2).any(|w| w[1] - w[0] != plan.bar_ns) {
        Status::IncompletePairs
    } else if x.len() < 40 || x.len() < 10 * plan.expected_block_length as usize {
        Status::InsufficientBlocks
    } else if u64::from(plan.replicates) * u64::from(10000 - plan.confidence_bps)
        < 400_000 * plan.family.len() as u64
    {
        Status::TailResolutionInsufficient
    } else {
        Status::Available
    };
    let mut pearson = estimate(correlation(&x, &y), status);
    let mut spearman = estimate(correlation(&ranks(&x), &ranks(&y)), status);
    if status == Status::Available
        && (pearson.point_status == Status::Available || spearman.point_status == Status::Available)
    {
        let mut seed = [0u8; 32];
        for (i, part) in plan.seed.as_bytes().as_chunks::<2>().0.iter().enumerate() {
            seed[i] = u8::from_str_radix(std::str::from_utf8(part).expect("validated hex"), 16)
                .expect("validated hex");
        }
        let mut ps = Vec::new();
        let mut ss = Vec::new();
        for replicate in 0..u64::from(plan.replicates) {
            let indices = Stream {
                seed,
                replicate,
                counter: 0,
            }
            .indices(x.len(), plan.expected_block_length as usize)?;
            let a: Vec<BigInt> = indices.iter().map(|i| x[*i].clone()).collect();
            let b: Vec<BigInt> = indices.iter().map(|i| y[*i].clone()).collect();
            match correlation(&a, &b) {
                Ok(v) => ps.push(v),
                Err(_) => pearson.undefined_replicates += 1,
            };
            match correlation(&ranks(&a), &ranks(&b)) {
                Ok(v) => ss.push(v),
                Err(_) => spearman.undefined_replicates += 1,
            };
        }
        finish(&mut pearson, &mut ps, &plan);
        finish(&mut spearman, &mut ss, &plan);
    }
    Ok(Analysis {
        plan_fingerprint: fingerprint(&serde_json::json!({"method":METHOD,"plan":record(&plan)?}))?,
        input_fingerprint: fingerprint(
            &serde_json::json!({"method":METHOD,"observations":record(&normalized)?}),
        )?,
        diagnostics,
        pearson,
        spearman,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn half_quantum_rounding_is_exact_and_ties_to_even() {
        let denominator = BigInt::from(2_000_000_000_000u64);
        for (c, want) in [(1, 0), (3, 2), (-3, -2)] {
            assert_eq!(rounded(&BigInt::from(c), &denominator, &denominator), want);
        }
    }
    #[test]
    fn stationary_indices_match_independent_sha256_reference() {
        let indices = Stream {
            seed: [0; 32],
            replicate: 0,
            counter: 0,
        }
        .indices(99, 4)
        .unwrap();
        assert_eq!(
            &indices[..20],
            &[
                63, 64, 71, 72, 91, 92, 93, 5, 6, 7, 1, 88, 89, 90, 91, 93, 40, 41, 42, 43
            ]
        );
    }
}
