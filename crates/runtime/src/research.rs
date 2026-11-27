//! 在同一冻结面板上求值因子与标签，并按有效配对计算逐时点统计。
use onlyalpha_calculation::factor_expr::{FactorExpr, TargetExpr};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, time::OnlyTimestamp};
use onlyalpha_execution::Error;
use onlyalpha_operators::algebra::{Decimal, MAX_CELLS, MAX_WINDOW_WORK};
use std::collections::{BTreeMap, BTreeSet};

#[path = "research_panel.rs"]
mod panel;
#[path = "research_statistics.rs"]
mod statistics;

pub use panel::ResearchPanel;
pub use statistics::{SeriesStatistics, StatisticRow, StatisticStatus};

pub type Cell = Option<Decimal>;
pub type Cohort = BTreeMap<String, Vec<Cell>>;

fn error(code: &str) -> Error {
    Error(code.to_owned())
}

#[derive(Clone, Debug)]
pub struct ResearchPlan {
    factors: Vec<(String, FactorExpr)>,
    targets: Vec<(String, TargetExpr)>,
    minimum_observations: usize,
}

impl ResearchPlan {
    pub fn new(
        factors: Vec<(String, FactorExpr)>,
        targets: Vec<(String, TargetExpr)>,
        minimum_observations: usize,
    ) -> Result<Self, Error> {
        if factors.is_empty() || targets.is_empty() || minimum_observations < 2 {
            return Err(error("RESEARCH_PLAN_INVALID"));
        }
        validate_names(&factors)?;
        validate_names(&targets)?;
        if targets.iter().any(|(_, target)| target.has_cross_section()) {
            return Err(error("RESEARCH_TARGET_SHAPE"));
        }
        Ok(Self {
            factors,
            targets,
            minimum_observations,
        })
    }
}

fn validate_names<T>(definitions: &[(String, T)]) -> Result<(), Error> {
    let mut seen = BTreeSet::new();
    for (name, _) in definitions {
        if name.trim().is_empty()
            || name.trim() != name
            || name.chars().count() > 128
            || !seen.insert(name)
        {
            return Err(error("RESEARCH_DEFINITION_NAME"));
        }
    }
    Ok(())
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchSeries {
    pub name: String,
    pub fingerprint: String,
    /// 完整冻结轴上的 `[标的][事件]` 矩阵，包含预热行。
    pub values: Vec<Vec<Cell>>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchComparison {
    pub factor_index: usize,
    pub target_index: usize,
    /// 第一行对应报告时间轴的 `warmup` 位置。
    pub rows: Vec<StatisticRow>,
    pub ic_statistics: SeriesStatistics,
    pub rank_ic_statistics: SeriesStatistics,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchReport {
    snapshot: String,
    content_digest: String,
    instruments: Vec<OnlyInstrumentId>,
    timestamps: Vec<OnlyTimestamp>,
    warmup: usize,
    minimum_observations: usize,
    factors: Vec<ResearchSeries>,
    targets: Vec<ResearchSeries>,
    comparisons: Vec<ResearchComparison>,
}

impl ResearchReport {
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

    pub fn factors(&self) -> &[ResearchSeries] {
        &self.factors
    }

    pub fn targets(&self) -> &[ResearchSeries] {
        &self.targets
    }

    pub fn comparisons(&self) -> &[ResearchComparison] {
        &self.comparisons
    }
}

#[derive(Clone, Debug)]
pub struct ResearchEngine;

impl ResearchEngine {
    pub fn new() -> Result<Self, Error> {
        Ok(Self)
    }

    pub fn run(&self, panel: &ResearchPanel, plan: &ResearchPlan) -> Result<ResearchReport, Error> {
        let definitions = plan.factors.len().saturating_add(plan.targets.len());
        let panel_cells = panel.periods().saturating_mul(panel.instrument_count());
        let matrix_cells = panel_cells.saturating_mul(definitions);
        let definitions_work = plan
            .factors
            .iter()
            .map(|(_, expr)| (expr.inputs().len(), expr.resource_budget()))
            .chain(
                plan.targets
                    .iter()
                    .map(|(_, expr)| (expr.inputs().len(), expr.resource_budget())),
            );
        let field_count = panel.instruments()[0].len();
        let mut vector_work = 0usize;
        for (inputs, budget) in definitions_work {
            // 无输入字段的表达式通过扫描每个标的的全部列来确定序列长度。
            let columns = if inputs == 0 { field_count } else { inputs };
            vector_work = vector_work
                .saturating_add(columns.saturating_mul(panel.instrument_count()))
                .saturating_add(budget.work_per_row.saturating_mul(panel_cells));
        }
        let comparison_rows = plan
            .factors
            .len()
            .saturating_mul(plan.targets.len())
            .saturating_mul(panel.periods() - panel.warmup());
        if matrix_cells > MAX_CELLS
            || vector_work > MAX_WINDOW_WORK
            || comparison_rows > MAX_CELLS
            || comparison_rows.saturating_mul(panel.instrument_count()) > MAX_WINDOW_WORK
        {
            return Err(error("RESEARCH_RESOURCE_BUDGET"));
        }
        let factors = evaluate_series(&plan.factors, |expr| {
            Ok((
                expr.fingerprint(),
                expr.evaluate_panel(panel.instruments())?,
            ))
        })?;
        let targets = evaluate_series(&plan.targets, |expr| {
            Ok((
                expr.fingerprint(),
                expr.evaluate_panel(panel.instruments())?,
            ))
        })?;
        let mut comparisons = Vec::new();
        for (factor_index, factor) in factors.iter().enumerate() {
            for (target_index, target) in targets.iter().enumerate() {
                let mut rows = Vec::with_capacity(panel.periods() - panel.warmup());
                for t in panel.warmup()..panel.periods() {
                    let pairs = factor
                        .values
                        .iter()
                        .zip(&target.values)
                        .filter_map(|(x, y)| x[t].as_ref().zip(y[t].as_ref()))
                        .collect();
                    rows.push(statistics::row(pairs, plan.minimum_observations)?);
                }
                comparisons.push(ResearchComparison {
                    factor_index,
                    target_index,
                    ic_statistics: statistics::summarize(rows.iter().map(|row| row.ic.clone()))?,
                    rank_ic_statistics: statistics::summarize(
                        rows.iter().map(|row| row.rank_ic.clone()),
                    )?,
                    rows,
                });
            }
        }
        Ok(ResearchReport {
            snapshot: panel.snapshot().to_owned(),
            content_digest: panel.content_digest().to_owned(),
            instruments: panel.instrument_ids().to_vec(),
            timestamps: panel.timestamps().to_vec(),
            warmup: panel.warmup(),
            minimum_observations: plan.minimum_observations,
            factors,
            targets,
            comparisons,
        })
    }
}

fn evaluate_series<T>(
    definitions: &[(String, T)],
    evaluate: impl Fn(&T) -> onlyalpha_calculation::Result<(&str, Vec<Vec<Cell>>)>,
) -> Result<Vec<ResearchSeries>, Error> {
    definitions
        .iter()
        .map(|(name, expr)| {
            let (fingerprint, values) =
                evaluate(expr).map_err(|failure| Error(failure.to_string()))?;
            Ok(ResearchSeries {
                name: name.clone(),
                fingerprint: fingerprint.to_owned(),
                values,
            })
        })
        .collect()
}

#[cfg(test)]
#[path = "tests/research_tests.rs"]
mod tests;
