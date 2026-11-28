use super::{
    NamedFactorExpr, Result, StrategyPort, TradingEventPort, TradingTask, VirtualEvents,
    execution::{DurableEconomicOwner, VirtualExecution, VirtualVenue},
    task::check_binding,
};
use crate::{OnlyAlphaRuntime, durability::TradingBinding};
use onlyalpha_domain::identifiers::OnlyInstrumentId;

impl OnlyAlphaRuntime {
    pub fn sim<P, S, O, V>(
        &self,
        binding: &TradingBinding,
        instruments: Vec<OnlyInstrumentId>,
        factors: Vec<NamedFactorExpr>,
        source: P,
        strategy: S,
        execution: VirtualExecution<O, V>,
    ) -> Result<TradingTask<VirtualEvents<P>, S, VirtualExecution<O, V>>>
    where
        P: TradingEventPort,
        S: StrategyPort,
        O: DurableEconomicOwner,
        V: VirtualVenue<O>,
    {
        check_binding(binding, execution.binding(), "SIM", execution.scope())?;
        let engine = self.trading_engine(instruments, factors)?;
        Ok(TradingTask::new(
            engine,
            VirtualEvents::new(source),
            strategy,
            execution,
            0,
            |source, engine, _, execution| source.next(engine, execution),
        ))
    }
}
