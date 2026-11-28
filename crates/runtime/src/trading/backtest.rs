//! 冻结面板按原事件时间回放，预热行与样本行共用同一时间轴。
use super::{
    MarketBar, NamedFactorExpr, Result, StrategyPort, TradingEvent, TradingEventPort, TradingTask,
    VirtualEvents, error,
    execution::{BacktestVenue, FiniteEconomicOwner, VirtualExecution},
    task::check_scope,
};
use crate::{OnlyAlphaRuntime, ResearchPanel, RunConfiguration};
use onlyalpha_domain::time::OnlyTimestamp;

mod finite;
mod inputs;
mod memory;
mod memory_venue;
pub(crate) mod next_open;
mod playback;
pub use playback::FiniteBacktestTask;
pub(crate) mod trading;
pub use finite::verify_finite_backtest;
pub use inputs::{Inputs, MarketInput, OpeningInput, Source};
pub use memory::{CompletedBacktest, ExecutionBinding, FrozenVenue, MemoryRunSpec};
pub use memory_venue::MemoryBacktestVenue;
pub(crate) use next_open::NextOpenModel;
pub use next_open::NextOpenPolicy;
pub use onlyalpha_execution::Error;
use serde_json::Value;

fn err(s: &str) -> Error {
    Error(format!("BACKTEST_REPLAY_{s}"))
}
fn hash(v: &Value) -> String {
    onlyalpha_execution::digest(v.to_string().as_bytes())
}
fn boundary<T, E: std::fmt::Display>(r: std::result::Result<T, E>) -> Result<T> {
    r.map_err(|e| err(&e.to_string()))
}
fn fields(v: &Value, keys: &[&str]) -> Result<()> {
    if v.as_object()
        .is_none_or(|m| m.len() != keys.len() || keys.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(err("FIELDS"));
    }
    Ok(())
}
fn sha(s: &str) -> Result<()> {
    if s.len() != 64
        || !s
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
    {
        return Err(err("IDENTITY"));
    }
    Ok(())
}

pub struct FrozenReplay<'a> {
    panel: &'a ResearchPanel,
    next_row: usize,
}

impl<'a> FrozenReplay<'a> {
    pub fn new(
        panel: &'a ResearchPanel,
        expected_snapshot: &str,
        expected_content: &str,
    ) -> Result<Self> {
        if panel.snapshot() != expected_snapshot {
            return Err(error("TRADING_REPLAY_SNAPSHOT_MISMATCH"));
        }
        panel.verify_content(expected_content)?;
        Ok(Self { panel, next_row: 0 })
    }

    /// 最近一次交付的冻结行情时间；读取首条行情前尚未设置。
    pub fn virtual_time(&self) -> Option<&OnlyTimestamp> {
        self.next_row
            .checked_sub(1)
            .map(|row| &self.panel.timestamps()[row])
    }
}

impl TradingEventPort for FrozenReplay<'_> {
    fn next_event(&mut self) -> Result<Option<TradingEvent>> {
        let row = self.next_row;
        let Some(timestamp) = self.panel.timestamps().get(row) else {
            return Ok(None);
        };
        // ResearchPanel 已校验标的排序和列长，每次只复制当前截面。
        let bar = MarketBar {
            timestamp: timestamp.clone(),
            instruments: self.panel.instrument_ids().to_vec(),
            cohort: self
                .panel
                .instruments()
                .iter()
                .map(|columns| {
                    columns
                        .iter()
                        .map(|(name, values)| (name.clone(), values[row].clone()))
                        .collect()
                })
                .collect(),
        };
        self.next_row += 1;
        Ok(Some(TradingEvent::Market(bar)))
    }
}

impl OnlyAlphaRuntime {
    pub fn backtest_with_ports<'a, S, O, V>(
        &self,
        replay: FrozenReplay<'a>,
        configuration: &RunConfiguration,
        factors: Vec<NamedFactorExpr>,
        strategy: S,
        execution: VirtualExecution<O, V>,
    ) -> Result<TradingTask<VirtualEvents<FrozenReplay<'a>>, S, VirtualExecution<O, V>>>
    where
        S: StrategyPort,
        O: FiniteEconomicOwner,
        V: BacktestVenue<O>,
    {
        let engine = self.backtest_engine(&replay, configuration, factors, &execution)?;
        let warmup = replay.panel.warmup() as u64;
        Ok(TradingTask::new(
            engine,
            VirtualEvents::new(replay),
            strategy,
            execution,
            warmup,
            |source, engine, _, execution| source.next(engine, execution),
        ))
    }

    fn backtest_engine<O: FiniteEconomicOwner, V: BacktestVenue<O>>(
        &self,
        replay: &FrozenReplay<'_>,
        configuration: &RunConfiguration,
        factors: Vec<NamedFactorExpr>,
        execution: &VirtualExecution<O, V>,
    ) -> Result<super::TradingEngine> {
        check_scope(configuration, "BACKTEST", execution.scope())?;
        if configuration.fingerprint() != execution.owner().configuration().fingerprint() {
            return Err(error("TRADING_TASK_BINDING_MISMATCH"));
        }
        if replay.next_row != 0 {
            return Err(error("TRADING_REPLAY_ALREADY_STARTED"));
        }
        execution
            .venue()
            .verify_inputs(configuration, replay.panel)?;
        self.trading_engine(replay.panel.instrument_ids().to_vec(), factors)
    }
}

#[cfg(test)]
#[path = "../tests/backtest_replay.rs"]
mod tests;

#[cfg(test)]
#[path = "../tests/trading_modes.rs"]
mod trading_modes;

#[cfg(test)]
#[path = "../tests/finite_playback.rs"]
mod finite_playback;
