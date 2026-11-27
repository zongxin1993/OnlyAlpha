//! 纯因子向量化研究：在冻结对齐面板上批量求值因子 DAG，并给出逐事件横截面 IC 证据。
//! 统计量全部复用已认证算子，不引入独立浮点实现；证据只说明本次切片上的观察结果。
use onlyalpha_calculation::qlib::{FactorExpr, TargetExpr};
use onlyalpha_execution::Error;
use onlyalpha_operators::algebra::{Decimal, Error as OperatorError, Kernel, Operator, Parameters};
use std::{collections::BTreeMap, num::NonZeroUsize};

pub type Cell = Option<Decimal>;

/// 单只标的的列式切片：字段名到等长时间序列。
pub type Cohort = BTreeMap<String, Vec<Cell>>;

fn error(code: &str) -> Error {
    Error(code.to_string())
}

fn boundary(failure: impl std::fmt::Display) -> Error {
    Error(failure.to_string())
}

fn operator_error(failure: OperatorError) -> Error {
    let code = match failure {
        OperatorError::InvalidParameters
        | OperatorError::InvalidInputs
        | OperatorError::ResearchOnly
        | OperatorError::Interrupted => "RESEARCH_OPERATOR_INVALID",
        OperatorError::BudgetExceeded => "RESEARCH_RESOURCE_BUDGET",
        OperatorError::NumericFailure => "RESEARCH_NUMERIC_FAILURE",
    };
    error(code)
}

/// 一个冻结切片：每只标的一组等长列，同一索引 `t` 是同一事件时间。
/// 面板不携带时间戳或来源身份，读取与授权由调用方的正式数据端口负责。
#[derive(Clone, Debug)]
pub struct ResearchPanel {
    instruments: Vec<Cohort>,
    periods: usize,
}

impl ResearchPanel {
    pub fn new(instruments: Vec<Cohort>) -> Result<Self, Error> {
        let Some(first) = instruments.first() else {
            return Err(error("RESEARCH_PANEL_EMPTY"));
        };
        let Some(column) = first.values().next() else {
            return Err(error("RESEARCH_PANEL_NO_FIELDS"));
        };
        let periods = column.len();
        for cohort in &instruments {
            if cohort.keys().ne(first.keys()) {
                return Err(error("RESEARCH_PANEL_SCHEMA"));
            }
            if cohort.values().any(|column| column.len() != periods) {
                return Err(error("RESEARCH_PANEL_LENGTH"));
            }
        }
        Ok(Self {
            instruments,
            periods,
        })
    }

    pub fn instruments(&self) -> &[Cohort] {
        &self.instruments
    }

    pub fn instrument_count(&self) -> usize {
        self.instruments.len()
    }

    pub fn periods(&self) -> usize {
        self.periods
    }
}

/// 一个统计量的全样本证据。`observations` 是实际给出该事件取值的数量，
/// 缺失事件不参与均值、标准差与 IR，也不被当作零。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SeriesStatistics {
    pub observations: usize,
    pub mean: Cell,
    pub std: Cell,
    pub ir: Cell,
}

/// 一次 Research 运行的确定性结果。
#[derive(Clone, Debug)]
pub struct ResearchReport {
    factors: Vec<Vec<Cell>>,
    ic: Vec<Cell>,
    rank_ic: Vec<Cell>,
    ic_statistics: SeriesStatistics,
    rank_ic_statistics: SeriesStatistics,
}

impl ResearchReport {
    /// 因子矩阵，按 `[标的][事件]` 索引，与面板列对齐。
    pub fn factors(&self) -> &[Vec<Cell>] {
        &self.factors
    }

    pub fn ic(&self) -> &[Cell] {
        &self.ic
    }

    pub fn rank_ic(&self) -> &[Cell] {
        &self.rank_ic
    }

    pub fn ic_statistics(&self) -> &SeriesStatistics {
        &self.ic_statistics
    }

    pub fn rank_ic_statistics(&self) -> &SeriesStatistics {
        &self.rank_ic_statistics
    }
}

/// 纯因子向量化引擎。因子与标签共用同一个已编译 DAG 底座，
/// 因此 Research 与事件主循环消费的是同一定义与同一数值政策。
#[derive(Clone, Debug)]
pub struct ResearchEngine {
    rank: Kernel,
    correlation: Kernel,
    divide: Kernel,
}

impl ResearchEngine {
    pub fn new() -> Result<Self, Error> {
        Ok(Self {
            rank: Kernel::new(Operator::CrossSectionRank, Parameters::default())
                .map_err(operator_error)?,
            correlation: Kernel::new(Operator::CrossSectionCorrelation, Parameters::default())
                .map_err(operator_error)?,
            divide: Kernel::new(Operator::Divide, Parameters::default()).map_err(operator_error)?,
        })
    }

    /// 只读求值：不改变面板、因子或标签，也不产出任何可发布事实。
    pub fn run(
        &self,
        panel: &ResearchPanel,
        factor: &FactorExpr,
        target: &TargetExpr,
    ) -> Result<ResearchReport, Error> {
        let factors = factor
            .evaluate_panel(panel.instruments())
            .map_err(boundary)?;
        let labels = target
            .evaluate_panel(panel.instruments())
            .map_err(boundary)?;
        let mut ic = Vec::with_capacity(panel.periods());
        let mut rank_ic = Vec::with_capacity(panel.periods());
        for t in 0..panel.periods() {
            let factor_cohort: Vec<Cell> = factors.iter().map(|column| column[t].clone()).collect();
            let label_cohort: Vec<Cell> = labels.iter().map(|column| column[t].clone()).collect();
            ic.push(self.cross_section_correlation(&factor_cohort, &label_cohort)?);
            let ranked_factor = self
                .rank
                .evaluate(&[factor_cohort])
                .map_err(operator_error)?;
            let ranked_label = self
                .rank
                .evaluate(&[label_cohort])
                .map_err(operator_error)?;
            rank_ic.push(self.cross_section_correlation(&ranked_factor, &ranked_label)?);
        }
        let ic_statistics = self.statistics(&ic)?;
        let rank_ic_statistics = self.statistics(&rank_ic)?;
        Ok(ResearchReport {
            factors,
            ic,
            rank_ic,
            ic_statistics,
            rank_ic_statistics,
        })
    }

    /// 一个事件只有一个横截面，算子把同一系数广播到每个完整配对，
    /// 因此取首格即该事件唯一的相关系数。
    fn cross_section_correlation(&self, xs: &[Cell], ys: &[Cell]) -> Result<Cell, Error> {
        Ok(self
            .correlation
            .evaluate(&[xs.to_vec(), ys.to_vec()])
            .map_err(operator_error)?
            .into_iter()
            .next()
            .flatten())
    }

    fn statistics(&self, series: &[Cell]) -> Result<SeriesStatistics, Error> {
        let defined: Vec<Cell> = series
            .iter()
            .filter(|cell| cell.is_some())
            .cloned()
            .collect();
        let mean = self.whole_sample(Operator::RollingMean, &defined)?;
        let std = self.whole_sample(Operator::RollingStd, &defined)?;
        let ir = match (&mean, &std) {
            (Some(mean), Some(std)) => self
                .divide
                .evaluate(&[vec![Some(mean.clone())], vec![Some(std.clone())]])
                .map_err(operator_error)?
                .into_iter()
                .next()
                .flatten(),
            _ => None,
        };
        Ok(SeriesStatistics {
            observations: defined.len(),
            mean,
            std,
            ir,
        })
    }

    fn whole_sample(&self, operator: Operator, values: &[Cell]) -> Result<Cell, Error> {
        let Some(period) = NonZeroUsize::new(values.len()) else {
            return Ok(None);
        };
        let kernel = Kernel::new(
            operator,
            Parameters {
                period: Some(period),
                ..Parameters::default()
            },
        )
        .map_err(operator_error)?;
        Ok(kernel
            .evaluate(&[values.to_vec()])
            .map_err(operator_error)?
            .into_iter()
            .next_back()
            .flatten())
    }
}

#[cfg(test)]
#[path = "tests/research_tests.rs"]
mod tests;
