//! 在冻结面板上求值因子和标签，将同轴结果交给研究统计库。
use onlyalpha_calculation::factor_expr::{FactorExpr, TargetExpr};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, time::OnlyTimestamp};
use onlyalpha_execution::Error;
use onlyalpha_operators::algebra::{Decimal, MAX_WINDOW_WORK};
use onlyalpha_research_statistics::{
    EvaluationAxis, EvaluationInput, FactorSeriesRef, SeriesRef, TargetSeriesRef, evaluate,
};
use std::collections::{BTreeMap, BTreeSet};

#[path = "research_panel.rs"]
mod panel;

pub use onlyalpha_research_statistics::{
    ComparisonRef, FactorReport, ResearchComparison, SeriesStatistics, StatisticRow,
    StatisticStatus, StatisticsPlan, TimeSlice,
};
pub use panel::ResearchPanel;

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
    statistics: StatisticsPlan,
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
            statistics: StatisticsPlan::default(),
        })
    }

    pub fn with_statistics(mut self, statistics: StatisticsPlan) -> Result<Self, Error> {
        let names: BTreeSet<_> = self.factors.iter().map(|(name, _)| name).collect();
        if statistics
            .pairs()
            .iter()
            .any(|(a, b)| !names.contains(a) || !names.contains(b))
        {
            return Err(error("RESEARCH_PLAN_INVALID"));
        }
        self.statistics = statistics;
        Ok(self)
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

impl ResearchSeries {
    fn as_ref<'a>(&'a self, axis: EvaluationAxis<'a>) -> SeriesRef<'a> {
        SeriesRef {
            axis,
            name: &self.name,
            fingerprint: &self.fingerprint,
            values: &self.values,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchReport {
    factors: Vec<ResearchSeries>,
    targets: Vec<ResearchSeries>,
    factor_report: FactorReport,
}

impl ResearchReport {
    pub fn snapshot(&self) -> &str {
        self.factor_report.snapshot()
    }

    pub fn content_digest(&self) -> &str {
        self.factor_report.content_digest()
    }

    pub fn instruments(&self) -> &[OnlyInstrumentId] {
        self.factor_report.instruments()
    }

    pub fn timestamps(&self) -> &[OnlyTimestamp] {
        self.factor_report.timestamps()
    }

    pub fn warmup(&self) -> usize {
        self.factor_report.warmup()
    }

    pub fn minimum_observations(&self) -> usize {
        self.factor_report.minimum_observations()
    }

    pub fn factors(&self) -> &[ResearchSeries] {
        &self.factors
    }

    pub fn targets(&self) -> &[ResearchSeries] {
        &self.targets
    }

    pub fn comparisons(&self) -> &[ResearchComparison] {
        self.factor_report.comparisons()
    }

    pub fn factor_report(&self) -> &FactorReport {
        &self.factor_report
    }
}

#[derive(Clone, Debug)]
pub struct ResearchEngine;

impl ResearchEngine {
    pub fn new() -> Result<Self, Error> {
        Ok(Self)
    }

    pub fn run(&self, panel: &ResearchPanel, plan: &ResearchPlan) -> Result<ResearchReport, Error> {
        plan.statistics.check_budget(
            panel.instrument_count(),
            panel.periods(),
            panel.warmup(),
            plan.factors.len(),
            plan.targets.len(),
        )?;
        let panel_cells = panel.periods().saturating_mul(panel.instrument_count());
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
        if vector_work > MAX_WINDOW_WORK {
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
        let axis = EvaluationAxis {
            snapshot: panel.snapshot(),
            content_digest: panel.content_digest(),
            instruments: panel.instrument_ids(),
            timestamps: panel.timestamps(),
            warmup: panel.warmup(),
        };
        let factor_refs: Vec<_> = factors
            .iter()
            .map(|series| FactorSeriesRef(series.as_ref(axis)))
            .collect();
        let target_refs: Vec<_> = targets
            .iter()
            .map(|series| TargetSeriesRef(series.as_ref(axis)))
            .collect();
        let input = EvaluationInput {
            axis,
            factors: &factor_refs,
            targets: &target_refs,
            minimum_observations: plan.minimum_observations,
        };
        let factor_report = evaluate(input, &plan.statistics)?;
        Ok(ResearchReport {
            factors,
            targets,
            factor_report,
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
