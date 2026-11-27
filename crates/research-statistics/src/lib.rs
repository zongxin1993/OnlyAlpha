//! 对同一冻结面板上的已求值因子和研究标签作截面统计（ADR 0082、0119）。
mod input;
mod math;
mod plan;
mod summary;
mod view;

pub use input::{
    EvaluationAxis, EvaluationInput, FactorSeriesRef, SeriesRef, TargetSeriesRef, column_digest,
};
pub use math::{MissingCounts, SeriesStatistics, SignStatistics, StatisticRow, StatisticStatus};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, time::OnlyTimestamp};
use onlyalpha_execution::Error;
use onlyalpha_operators::algebra::Decimal;
pub use plan::StatisticsPlan;
pub use summary::{
    CoverageSummary, SliceMeanStatistics, SliceStatistics, StabilitySummary, TimeSlice,
};
pub use view::ComparisonRef;

pub type Cell = Option<Decimal>;
fn error(code: &str) -> Error {
    Error(code.to_owned())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SeriesBinding {
    pub name: String,
    pub fingerprint: String,
    pub values_digest: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchComparison {
    pub factor_index: usize,
    pub target_index: usize,
    pub rows: Vec<StatisticRow>,
    pub ic_statistics: SeriesStatistics,
    pub rank_ic_statistics: SeriesStatistics,
    pub coverage: CoverageSummary,
    pub stability: Option<StabilitySummary>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum PairStatus {
    Valid,
    InsufficientObservations,
    ZeroVarianceFirstFactor,
    ZeroVarianceSecondFactor,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FactorPairRow {
    pub sample_count: usize,
    pub status: PairStatus,
    pub correlation: Cell,
    pub rank_correlation: Cell,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FactorPairComparison {
    pub first_index: usize,
    pub second_index: usize,
    pub rows: Vec<FactorPairRow>,
    pub correlation: SeriesStatistics,
    pub rank_correlation: SeriesStatistics,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FactorReport {
    snapshot: String,
    content_digest: String,
    instruments: Vec<OnlyInstrumentId>,
    timestamps: Vec<OnlyTimestamp>,
    warmup: usize,
    minimum_observations: usize,
    factors: Vec<SeriesBinding>,
    targets: Vec<SeriesBinding>,
    comparisons: Vec<ResearchComparison>,
    pairs: Vec<FactorPairComparison>,
    slices: Vec<TimeSlice>,
    slice_plan_digest: String,
}

impl FactorReport {
    pub fn snapshot(&self) -> &str {
        &self.snapshot
    }
    pub fn content_digest(&self) -> &str {
        &self.content_digest
    }
    pub fn instruments(&self) -> &[OnlyInstrumentId] {
        &self.instruments
    }
    pub fn timestamps(&self) -> &[OnlyTimestamp] {
        &self.timestamps
    }
    pub fn warmup(&self) -> usize {
        self.warmup
    }
    pub fn minimum_observations(&self) -> usize {
        self.minimum_observations
    }
    pub fn factors(&self) -> &[SeriesBinding] {
        &self.factors
    }
    pub fn targets(&self) -> &[SeriesBinding] {
        &self.targets
    }
    pub fn comparisons(&self) -> &[ResearchComparison] {
        &self.comparisons
    }
    pub fn pairs(&self) -> &[FactorPairComparison] {
        &self.pairs
    }
    pub fn slices(&self) -> &[TimeSlice] {
        &self.slices
    }
}

fn compare<'a>(
    a: SeriesRef<'a>,
    b: SeriesRef<'a>,
    minimum: usize,
) -> impl Iterator<Item = Result<StatisticRow, Error>> + 'a {
    (a.axis.warmup..a.axis.timestamps.len()).map(move |t| {
        let mut pairs = Vec::new();
        let mut missing = MissingCounts::default();
        for (first, second) in a.values.iter().zip(b.values) {
            match (&first[t], &second[t]) {
                (Some(x), Some(y)) => pairs.push((x, y)),
                (None, Some(_)) => missing.missing_factor_only += 1,
                (Some(_), None) => missing.missing_target_only += 1,
                (None, None) => missing.missing_both += 1,
            }
        }
        math::row(pairs, missing, minimum)
    })
}

fn effects(rows: &[StatisticRow]) -> Result<(SeriesStatistics, SeriesStatistics), Error> {
    Ok((
        math::summarize(rows.iter().map(|r| r.ic.clone()))?,
        math::summarize(rows.iter().map(|r| r.rank_ic.clone()))?,
    ))
}

impl TryFrom<StatisticRow> for FactorPairRow {
    type Error = Error;
    fn try_from(row: StatisticRow) -> Result<Self, Error> {
        let status = match row.status {
            StatisticStatus::Valid => PairStatus::Valid,
            StatisticStatus::InsufficientObservations => PairStatus::InsufficientObservations,
            StatisticStatus::ZeroVarianceFeature => PairStatus::ZeroVarianceFirstFactor,
            StatisticStatus::ZeroVarianceTarget => PairStatus::ZeroVarianceSecondFactor,
            _ => return Err(error("RESEARCH_STATISTIC_ROW_STATUS")),
        };
        Ok(Self {
            sample_count: row.sample_count,
            status,
            correlation: row.ic,
            rank_correlation: row.rank_ic,
        })
    }
}

pub fn evaluate(input: EvaluationInput<'_>, plan: &StatisticsPlan) -> Result<FactorReport, Error> {
    let axis = input.axis;
    let minimum = input.minimum_observations;
    if minimum < 2 {
        return Err(error("RESEARCH_PLAN_INVALID"));
    }
    plan.check_budget(
        axis.instruments.len(),
        axis.timestamps.len(),
        axis.warmup,
        input.factors.len(),
        input.targets.len(),
    )?;
    axis.validate()?;
    let factors = input::bind(axis, input.factors.iter().map(|r| r.0))?;
    let targets = input::bind(axis, input.targets.iter().map(|r| r.0))?;
    let selected = plan.resolve_pairs(&factors)?;
    let mut comparisons = Vec::with_capacity(factors.len() * targets.len());
    for (factor_index, factor) in input.factors.iter().enumerate() {
        for (target_index, target) in input.targets.iter().enumerate() {
            let rows = compare(factor.0, target.0, minimum).collect::<Result<Vec<_>, _>>()?;
            let (ic_statistics, rank_ic_statistics) = effects(&rows)?;
            let coverage = summary::coverage(&rows)?;
            let stability = if plan.slices().is_empty() {
                None
            } else {
                Some(summary::stability(
                    &axis.timestamps[axis.warmup..],
                    &rows,
                    plan.slices(),
                )?)
            };
            comparisons.push(ResearchComparison {
                factor_index,
                target_index,
                rows,
                ic_statistics,
                rank_ic_statistics,
                coverage,
                stability,
            });
        }
    }
    let mut pairs = Vec::with_capacity(selected.len());
    for (first_index, second_index) in selected {
        let rows = compare(
            input.factors[first_index].0,
            input.factors[second_index].0,
            minimum,
        )
        .map(|row| FactorPairRow::try_from(row?))
        .collect::<Result<Vec<_>, Error>>()?;
        let correlation = math::summarize(rows.iter().map(|r| r.correlation.clone()))?;
        let rank_correlation = math::summarize(rows.iter().map(|r| r.rank_correlation.clone()))?;
        pairs.push(FactorPairComparison {
            first_index,
            second_index,
            rows,
            correlation,
            rank_correlation,
        });
    }
    Ok(FactorReport {
        snapshot: axis.snapshot.into(),
        content_digest: axis.content_digest.into(),
        instruments: axis.instruments.to_vec(),
        timestamps: axis.timestamps.to_vec(),
        warmup: axis.warmup,
        minimum_observations: minimum,
        factors,
        targets,
        comparisons,
        pairs,
        slices: plan.slices().to_vec(),
        slice_plan_digest: view::slice_plan_digest(plan.slices()),
    })
}

#[cfg(test)]
#[path = "tests/bindings.rs"]
mod binding_tests;
