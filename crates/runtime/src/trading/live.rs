use super::{
    NamedFactorExpr, Result, StrategyPort, TradingEventPort, TradingRunError, TradingTask,
    execution::{AuthorizedLiveGateway, DurableEconomicOwner, LiveExecution},
    task::check_binding,
};
use crate::{OnlyAlphaRuntime, durability::TradingBinding};
use onlyalpha_domain::identifiers::OnlyInstrumentId;

impl OnlyAlphaRuntime {
    pub fn live<P, S, O, G>(
        &self,
        binding: &TradingBinding,
        instruments: Vec<OnlyInstrumentId>,
        factors: Vec<NamedFactorExpr>,
        source: P,
        strategy: S,
        execution: LiveExecution<O, G>,
    ) -> Result<TradingTask<P, S, LiveExecution<O, G>>>
    where
        P: TradingEventPort,
        S: StrategyPort,
        O: DurableEconomicOwner,
        G: AuthorizedLiveGateway<O>,
    {
        check_binding(binding, execution.binding(), "LIVE", execution.scope())?;
        let engine = self.trading_engine(instruments, factors)?;
        Ok(TradingTask::new(
            engine,
            source,
            strategy,
            execution,
            0,
            |source, _, _, _| source.next_event().map_err(TradingRunError::Source),
        ))
    }
}
