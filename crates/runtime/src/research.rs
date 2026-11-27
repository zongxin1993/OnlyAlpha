//! 在冻结面板上求值因子和标签，将同轴结果交给研究统计库。
use onlyalpha_calculation::factor_expr::{FactorExpr, TargetExpr};
use onlyalpha_domain::{identifiers::OnlyInstrumentId, time::OnlyTimestamp};
use onlyalpha_execution::Error;
use onlyalpha_operators::algebra::{Decimal, MAX_WINDOW_WORK};
use onlyalpha_research_statistics::{
    EvaluationAxis, EvaluationInput, FactorSeriesRef, SeriesRef, TargetSeriesRef, evaluate,
};
use serde_json::Value;
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
        Self {
            factors,
            targets,
            minimum_observations,
            statistics: StatisticsPlan::default(),
        }
        .validate()
    }

    pub fn for_factor_pairs(
        factors: Vec<(String, FactorExpr)>,
        pairs: Vec<(String, String)>,
        minimum_observations: usize,
    ) -> Result<Self, Error> {
        Self {
            factors,
            targets: Vec::new(),
            minimum_observations,
            statistics: StatisticsPlan::new(Vec::new(), pairs)?,
        }
        .validate()
    }

    pub fn with_statistics(self, statistics: StatisticsPlan) -> Result<Self, Error> {
        Self { statistics, ..self }.validate()
    }

    fn validate(self) -> Result<Self, Error> {
        self.statistics
            .validate_series_counts(self.factors.len(), self.targets.len())?;
        if self.minimum_observations < 2 {
            return Err(error("RESEARCH_PLAN_INVALID"));
        }
        let names = validate_names(&self.factors)?;
        validate_names(&self.targets)?;
        if self
            .targets
            .iter()
            .any(|(_, target)| target.has_cross_section())
        {
            return Err(error("RESEARCH_TARGET_SHAPE"));
        }
        if self
            .statistics
            .pairs()
            .iter()
            .any(|(a, b)| !names.contains(a.as_str()) || !names.contains(b.as_str()))
        {
            return Err(error("RESEARCH_PLAN_INVALID"));
        }
        Ok(self)
    }
}

fn validate_names<T>(definitions: &[(String, T)]) -> Result<BTreeSet<&str>, Error> {
    let mut seen = BTreeSet::new();
    for (name, _) in definitions {
        if name.trim().is_empty()
            || name.trim() != name
            || name.chars().count() > 128
            || !seen.insert(name.as_str())
        {
            return Err(error("RESEARCH_DEFINITION_NAME"));
        }
    }
    Ok(seen)
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResearchSeries {
    pub name: String,
    pub fingerprint: String,
    /// 完整冻结轴上的 `[标的][事件]` 矩阵，包含预热行。
    pub values: Vec<Vec<Cell>>,
}

impl ResearchSeries {
    pub fn target_lookahead_steps(&self, expression: &TargetExpr) -> Result<usize, Error> {
        if self.fingerprint != expression.fingerprint() {
            return Err(error("RESEARCH_STATISTICS_BINDING"));
        }
        Ok(expression.max_lookahead())
    }

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
    target_lookahead_steps: Vec<usize>,
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

    pub fn target_lookahead_steps(&self) -> &[usize] {
        &self.target_lookahead_steps
    }

    fn set_target_lookahead(&self, reference: ComparisonRef, locator: &mut Value) {
        if let ComparisonRef::FactorTarget(index) = reference {
            let target = self.comparisons()[index].target_index;
            locator["target"]["max_lookahead_steps"] = self.target_lookahead_steps[target].into();
        }
    }

    pub fn summary_view(&self) -> Result<Value, Error> {
        let mut view = self.factor_report.summary_view()?;
        for index in 0..self.comparisons().len() {
            self.set_target_lookahead(
                ComparisonRef::FactorTarget(index),
                &mut view["comparisons"][index]["comparison_ref"],
            );
        }
        Ok(view)
    }

    pub fn comparison_view(&self, reference: ComparisonRef) -> Result<Value, Error> {
        let mut view = self.factor_report.comparison_view(reference)?;
        self.set_target_lookahead(reference, &mut view["comparison"]["comparison_ref"]);
        Ok(view)
    }

    pub fn slice_view(&self, comparison_index: usize, slice_index: usize) -> Result<Value, Error> {
        let mut view = self
            .factor_report
            .slice_view(comparison_index, slice_index)?;
        self.set_target_lookahead(
            ComparisonRef::FactorTarget(comparison_index),
            &mut view["comparison_ref"],
        );
        Ok(view)
    }

    pub fn detail_view(
        &self,
        reference: ComparisonRef,
        start_ns: i128,
        end_ns: i128,
    ) -> Result<Value, Error> {
        let mut view = self
            .factor_report
            .detail_view(reference, start_ns, end_ns)?;
        self.set_target_lookahead(reference, &mut view["comparison_ref"]);
        Ok(view)
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
        let target_lookahead_steps = targets
            .iter()
            .zip(&plan.targets)
            .map(|(series, (_, expr))| series.target_lookahead_steps(expr))
            .collect::<Result<Vec<_>, _>>()?;
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
            target_lookahead_steps,
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
