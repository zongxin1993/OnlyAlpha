//! Backtest／SIM／LIVE 共用的统一事件主循环：同一事件链路、同一份 声明式因子定义与同一数值政策。
//!
//! 主循环不知道当前模式。行情与时钟、策略、风控／准入／券商／持久化事实全部由注入端口承担，
//! 因此回测与实盘只在端口实现上不同，不出现 `if mode == Backtest` 之类的分支。
//! 实盘派单权限属于执行端口；本模块不产出任何外部发单能力。
use crate::research::Cell;
use onlyalpha_calculation::factor_expr::{
    DagState, EventExecutor, FactorExpr, PanelDagState, PanelEventExecutor,
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::OnlyInstrumentId,
    numeric::OnlyDecimal,
    strategy::{NamedFactor, OrderIntent, ReadonlyAccountState},
    time::OnlyTimestamp,
};
use onlyalpha_execution::Error;
use onlyalpha_operators::algebra::Decimal;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

type Result<T> = std::result::Result<T, Error>;

fn error(code: &str) -> Error {
    Error(code.to_string())
}

fn boundary(failure: impl std::fmt::Display) -> Error {
    Error(failure.to_string())
}

/// 领域 Decimal 与算子 Decimal 都是精确十进制，经规范十进制字符串互转无损。
/// 因子按 `DECIMAL28_HALF_EVEN_Q12_V1` 产出，落在领域取值范围之内；
/// 超出范围时 Fail-Closed，不做舍入或截断。
fn domain_decimal(value: &Decimal) -> Result<OnlyDecimal> {
    value
        .normalized()
        .to_plain_string()
        .parse()
        .map_err(|_| error("TRADING_FACTOR_NUMERIC_RANGE"))
}

/// 一个事件时间的完整横截面：标的身份与其输入字段按同一索引对齐。
/// 缺失值保持 `None`，不当作零。
#[derive(Clone, Debug)]
pub struct MarketBar {
    timestamp: OnlyTimestamp,
    instruments: Vec<OnlyInstrumentId>,
    cohort: Vec<BTreeMap<String, Cell>>,
}

impl MarketBar {
    /// 按标的身份排序并拒绝重复，保证同一横截面的遍历顺序确定。
    pub fn new(
        timestamp: OnlyTimestamp,
        mut legs: Vec<(OnlyInstrumentId, BTreeMap<String, Cell>)>,
    ) -> Result<Self> {
        if legs.is_empty() {
            return Err(error("TRADING_NO_INSTRUMENTS"));
        }
        legs.sort_by_key(|left| left.0.to_string());
        if legs.windows(2).any(|pair| pair[0].0 == pair[1].0) {
            return Err(error("TRADING_DUPLICATE_INSTRUMENT"));
        }
        let (instruments, cohort) = legs.into_iter().unzip();
        Ok(Self {
            timestamp,
            instruments,
            cohort,
        })
    }

    pub fn timestamp(&self) -> &OnlyTimestamp {
        &self.timestamp
    }

    pub fn instruments(&self) -> &[OnlyInstrumentId] {
        &self.instruments
    }

    pub fn cohort(&self) -> &[BTreeMap<String, Cell>] {
        &self.cohort
    }
}

/// 一个有名字的因子定义。名字是策略绑定身份，表达式是唯一计算来源。
#[derive(Clone, Debug)]
pub struct NamedFactorExpr {
    name: String,
    expr: FactorExpr,
}

impl NamedFactorExpr {
    pub fn compile(name: &str, source: &str) -> Result<Self> {
        Self::build(name, FactorExpr::compile(source).map_err(boundary)?)
    }

    /// `allowed` 是扩展算子派生字段的声明集合：只有列在其中的字段才能进入表达式。
    pub fn compile_with_allowed_fields(
        name: &str,
        source: &str,
        allowed: &BTreeSet<String>,
    ) -> Result<Self> {
        Self::build(
            name,
            FactorExpr::compile_with_allowed_fields(source, allowed).map_err(boundary)?,
        )
    }

    fn build(name: &str, expr: FactorExpr) -> Result<Self> {
        if name.is_empty() || name.chars().count() > 128 {
            return Err(error("TRADING_FACTOR_NAME"));
        }
        Ok(Self {
            name: name.to_owned(),
            expr,
        })
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn expr(&self) -> &FactorExpr {
        &self.expr
    }
}

#[derive(Clone, Debug)]
enum FactorExecutor {
    Series(EventExecutor),
    Panel(PanelEventExecutor),
}

#[derive(Clone, Debug)]
enum ExecutorSnapshot {
    Series(DagState),
    Panel(PanelDagState),
}

impl FactorExecutor {
    fn new(expr: &FactorExpr, instrument_count: usize) -> Result<Self> {
        if expr.has_cross_section() {
            return Ok(Self::Panel(
                expr.panel_event_executor(instrument_count)
                    .map_err(boundary)?,
            ));
        }
        if instrument_count == 1 {
            return Ok(Self::Series(expr.event_executor().map_err(boundary)?));
        }
        Ok(Self::Panel(
            expr.panel_event_executor(instrument_count)
                .map_err(boundary)?,
        ))
    }

    fn layout(&self) -> &'static str {
        match self {
            Self::Series(_) => "series",
            Self::Panel(_) => "panel",
        }
    }

    fn step_count(&self) -> u64 {
        match self {
            Self::Series(executor) => executor.step_count(),
            Self::Panel(executor) => executor.step_count(),
        }
    }

    fn step(&mut self, cohort: &[BTreeMap<String, Cell>]) -> Result<Vec<Cell>> {
        match self {
            Self::Series(executor) => Ok(vec![executor.step(&cohort[0]).map_err(boundary)?]),
            Self::Panel(executor) => executor.step(cohort).map_err(boundary),
        }
    }

    fn snapshot(&self) -> ExecutorSnapshot {
        match self {
            Self::Series(executor) => ExecutorSnapshot::Series(executor.capture_state()),
            Self::Panel(executor) => ExecutorSnapshot::Panel(executor.capture_state()),
        }
    }

    fn resume(&mut self, snapshot: ExecutorSnapshot) -> Result<()> {
        match (self, snapshot) {
            (Self::Series(executor), ExecutorSnapshot::Series(state)) => {
                executor.restore_state(state).map_err(boundary)
            }
            (Self::Panel(executor), ExecutorSnapshot::Panel(state)) => {
                executor.restore_state(state).map_err(boundary)
            }
            _ => Err(error("TRADING_CHECKPOINT_LAYOUT")),
        }
    }

    fn state_record(&self) -> Value {
        match self {
            Self::Series(executor) => executor.capture_state().to_record(),
            Self::Panel(executor) => executor.capture_state().to_record(),
        }
    }

    fn restore_record(&mut self, record: &Value) -> Result<()> {
        match self {
            Self::Series(executor) => executor
                .restore_state(DagState::from_record(record).map_err(boundary)?)
                .map_err(boundary),
            Self::Panel(executor) => executor
                .restore_state(PanelDagState::from_record(record).map_err(boundary)?)
                .map_err(boundary),
        }
    }
}

#[derive(Clone, Debug)]
struct BoundFactor {
    name: String,
    expr: FactorExpr,
    executor: FactorExecutor,
}

/// 行情与时钟端口：按事件时间给出完整横截面，由实现决定是冻结切片还是实时流。
pub trait MarketPort {
    fn next_bar(&mut self) -> Result<Option<MarketBar>>;
}

/// 策略端口：只读取已绑定因子与只读账户快照，产出规范化下单意图。
/// 实现不得自行发单或改动持久化状态；风控、准入与派单由执行端口负责。
pub trait StrategyPort {
    /// `instrument` 是本次决策所针对的标的：策略只能看到该标的的因子值。
    /// 跨标的信息只能通过横截面因子进入表达式，不得靠一次调用同时为多只标的决策。
    fn decide(
        &self,
        instrument: &OnlyInstrumentId,
        factors: &[NamedFactor],
        account: &ReadonlyAccountState,
    ) -> Result<Vec<OrderIntent>>;
}

/// 执行端口：持有账户、风控、准入、券商回报与持久化事实。
/// 同一份意图重复提交时按事实身份幂等，不得产生第二笔外部成交。
pub trait ExecutionPort {
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState>;
    fn submit(&mut self, intent: &OrderIntent, at: &OnlyTimestamp) -> Result<Vec<Value>>;
}

/// 策略在一个标的上的确定性产出。
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StrategyDecision {
    instrument: OnlyInstrumentId,
    intent: OrderIntent,
}

impl StrategyDecision {
    pub fn instrument(&self) -> &OnlyInstrumentId {
        &self.instrument
    }

    pub fn intent(&self) -> &OrderIntent {
        &self.intent
    }
}

/// 一个事件的处理结果：与声明标的对齐的因子矩阵、策略意图和执行端口回报的已应用事实。
#[derive(Clone, Debug)]
pub struct BarOutcome {
    timestamp: OnlyTimestamp,
    values: Vec<Vec<Cell>>,
    intents: Vec<StrategyDecision>,
    facts: Vec<Value>,
}

impl BarOutcome {
    pub fn timestamp(&self) -> &OnlyTimestamp {
        &self.timestamp
    }

    /// 因子矩阵按 `[标的][因子]` 索引，标的顺序与引擎声明一致。
    pub fn values(&self) -> &[Vec<Cell>] {
        &self.values
    }

    pub fn intents(&self) -> &[StrategyDecision] {
        &self.intents
    }

    pub fn facts(&self) -> &[Value] {
        &self.facts
    }
}

/// 统一事件主循环。引擎只负责因子求值、事件顺序与策略调用编排；
/// 不含模式字段，也不决定任何市场、券商或存储实现。
#[derive(Clone, Debug)]
pub struct TradingEngine {
    instruments: Vec<OnlyInstrumentId>,
    factors: Vec<BoundFactor>,
    timestamp: Option<OnlyTimestamp>,
}

impl TradingEngine {
    pub fn new(instruments: Vec<OnlyInstrumentId>, factors: Vec<NamedFactorExpr>) -> Result<Self> {
        if instruments.is_empty() {
            return Err(error("TRADING_NO_INSTRUMENTS"));
        }
        if factors.is_empty() {
            return Err(error("TRADING_NO_FACTORS"));
        }
        let mut instruments = instruments;
        instruments.sort_by_key(|instrument| instrument.to_string());
        if instruments.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(error("TRADING_DUPLICATE_INSTRUMENT"));
        }
        let mut seen = BTreeSet::new();
        let mut bound = Vec::with_capacity(factors.len());
        for factor in factors {
            if !seen.insert(factor.name.clone()) {
                return Err(error("TRADING_FACTOR_NAME"));
            }
            let executor = FactorExecutor::new(&factor.expr, instruments.len())?;
            bound.push(BoundFactor {
                name: factor.name,
                expr: factor.expr,
                executor,
            });
        }
        Ok(Self {
            instruments,
            factors: bound,
            timestamp: None,
        })
    }

    pub fn instruments(&self) -> &[OnlyInstrumentId] {
        &self.instruments
    }

    pub fn factor_names(&self) -> Vec<&str> {
        self.factors
            .iter()
            .map(|factor| factor.name.as_str())
            .collect()
    }

    pub fn events(&self) -> u64 {
        self.factors[0].executor.step_count()
    }

    pub fn timestamp(&self) -> Option<&OnlyTimestamp> {
        self.timestamp.as_ref()
    }

    /// 推进一个事件：求值因子、读取只读账户、调用策略、按标的上报意图。
    ///
    /// 任一步失败都会把因子状态回滚到本事件之前；已经提交的外部事实留给执行端口对账，
    /// 引擎不会重发已建立的意图。
    pub fn advance<S, E>(
        &mut self,
        bar: &MarketBar,
        strategy: &S,
        execution: &mut E,
    ) -> Result<BarOutcome>
    where
        S: StrategyPort + ?Sized,
        E: ExecutionPort + ?Sized,
    {
        if bar.instruments() != self.instruments {
            return Err(error("TRADING_SCHEMA_MISMATCH"));
        }
        if self
            .timestamp
            .as_ref()
            .is_some_and(|last| last >= bar.timestamp())
        {
            return Err(error("TRADING_EVENT_ORDER"));
        }
        let snapshots: Vec<ExecutorSnapshot> = self
            .factors
            .iter()
            .map(|factor| factor.executor.snapshot())
            .collect();
        match self.step(bar, strategy, execution) {
            Ok(outcome) => Ok(outcome),
            Err(failure) => match self.rollback(snapshots) {
                Ok(()) => Err(failure),
                Err(rollback) => Err(error(&format!("TRADING_ROLLBACK_FAILED:{}", rollback.0))),
            },
        }
    }

    fn step<S, E>(&mut self, bar: &MarketBar, strategy: &S, execution: &mut E) -> Result<BarOutcome>
    where
        S: StrategyPort + ?Sized,
        E: ExecutionPort + ?Sized,
    {
        let mut values = vec![Vec::with_capacity(self.factors.len()); self.instruments.len()];
        for factor in &mut self.factors {
            let column = factor.executor.step(bar.cohort())?;
            for (row, cell) in values.iter_mut().zip(column) {
                row.push(cell);
            }
        }
        let account = execution.account(bar.timestamp())?;
        let mut intents = Vec::new();
        let mut facts = Vec::new();
        for (index, instrument) in self.instruments.iter().enumerate() {
            let mut bindings = Vec::with_capacity(self.factors.len());
            for (factor, cell) in self.factors.iter().zip(&values[index]) {
                let value = match cell {
                    Some(value) => Some(domain_decimal(value)?),
                    None => None,
                };
                bindings.push(NamedFactor::new(&factor.name, value).map_err(boundary)?);
            }
            for intent in strategy.decide(instrument, &bindings, &account)? {
                if intent.instrument() != instrument {
                    return Err(error("TRADING_INTENT_INSTRUMENT_MISMATCH"));
                }
                facts.extend(execution.submit(&intent, bar.timestamp())?);
                intents.push(StrategyDecision {
                    instrument: instrument.clone(),
                    intent,
                });
            }
        }
        self.timestamp = Some(bar.timestamp().clone());
        Ok(BarOutcome {
            timestamp: bar.timestamp().clone(),
            values,
            intents,
            facts,
        })
    }

    fn rollback(&mut self, snapshots: Vec<ExecutorSnapshot>) -> Result<()> {
        for (factor, snapshot) in self.factors.iter_mut().zip(snapshots) {
            factor.executor.resume(snapshot)?;
        }
        Ok(())
    }

    /// 主循环本身：同一份代码在回测、仿真与实盘上运行，差异只在端口实现。
    pub fn run<M, S, E>(
        &mut self,
        market: &mut M,
        strategy: &S,
        execution: &mut E,
    ) -> Result<Vec<BarOutcome>>
    where
        M: MarketPort + ?Sized,
        S: StrategyPort + ?Sized,
        E: ExecutionPort + ?Sized,
    {
        let mut outcomes = Vec::new();
        while let Some(bar) = market.next_bar()? {
            outcomes.push(self.advance(&bar, strategy, execution)?);
        }
        Ok(outcomes)
    }

    /// 恢复所需的最小内核状态：标的集合、因子身份与布局、各因子算子滚动状态、最后事件时间。
    /// 账户与外部事实的恢复和对账由执行端口的持久化事实负责。
    pub fn checkpoint(&self) -> Value {
        json!({
            "schema_version": 1,
            "instruments": self.instruments.iter().map(ToString::to_string).collect::<Vec<_>>(),
            "timestamp": self.timestamp.as_ref().map(OnlyDomainModel::to_record),
            "events": self.events(),
            "factors": self.factors.iter().map(|factor| json!({
                "name": factor.name,
                "fingerprint": factor.expr.fingerprint(),
                "layout": factor.executor.layout(),
                "state": factor.executor.state_record(),
            })).collect::<Vec<_>>(),
        })
    }

    pub fn restore_checkpoint(&mut self, record: &Value) -> Result<()> {
        if record["schema_version"] != 1
            || record["factors"].as_array().map(Vec::len) != Some(self.factors.len())
        {
            return Err(error("TRADING_CHECKPOINT_INVALID"));
        }
        let instruments = record["instruments"]
            .as_array()
            .filter(|items| items.len() == self.instruments.len())
            .ok_or_else(|| error("TRADING_CHECKPOINT_INVALID"))?;
        for (stored, declared) in instruments.iter().zip(&self.instruments) {
            if stored.as_str() != Some(declared.to_string().as_str()) {
                return Err(error("TRADING_CHECKPOINT_BINDING"));
            }
        }
        let events = record["events"]
            .as_u64()
            .ok_or_else(|| error("TRADING_CHECKPOINT_INVALID"))?;
        for (factor, stored) in self.factors.iter_mut().zip(
            record["factors"]
                .as_array()
                .ok_or_else(|| error("TRADING_CHECKPOINT_INVALID"))?,
        ) {
            if stored["name"].as_str() != Some(factor.name.as_str())
                || stored["fingerprint"].as_str() != Some(factor.expr.fingerprint())
                || stored["layout"].as_str() != Some(factor.executor.layout())
            {
                return Err(error("TRADING_CHECKPOINT_BINDING"));
            }
            factor.executor.restore_record(&stored["state"])?;
            if factor.executor.step_count() != events {
                return Err(error("TRADING_CHECKPOINT_BINDING"));
            }
        }
        self.timestamp = match &record["timestamp"] {
            Value::Null => None,
            value => Some(OnlyTimestamp::from_record(value).map_err(boundary)?),
        };
        Ok(())
    }
}

#[cfg(test)]
#[path = "tests/trading_tests.rs"]
mod tests;
