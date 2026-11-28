//! 冻结面板按原事件时间回放，预热行与样本行共用同一时间轴。
use super::{
    MarketBar, NamedFactorExpr, Result, StrategyPort, TradingEvent, TradingEventPort, TradingTask,
    VirtualEvents, error,
    execution::{BacktestVenue, FiniteEconomicOwner, VirtualExecution},
    task::check_scope,
};
use crate::{OnlyAlphaRuntime, ResearchPanel, RunConfiguration};
use onlyalpha_domain::time::OnlyTimestamp;

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
    pub fn backtest<'a, S, O, V>(
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
        let engine = self.trading_engine(replay.panel.instrument_ids().to_vec(), factors)?;
        let warmup = replay.panel.warmup() as u64;
        Ok(TradingTask::new(
            engine,
            VirtualEvents::new(replay),
            strategy,
            execution,
            warmup,
            VirtualEvents::next,
        ))
    }
}

#[cfg(test)]
#[path = "../tests/backtest_replay.rs"]
mod tests;
