use super::{
    EventOutcome, ExecutionPort, MarketBar, Result, StrategyPort, TradingEngine, TradingEvent,
    TradingEventPort, TradingRunError, error,
    execution::{EconomicOwner, VirtualExecution, VirtualVenue},
};
use crate::{RunConfiguration, durability::TradingBinding};
use onlyalpha_broker::Scope;

type NextEvent = std::result::Result<Option<TradingEvent>, TradingRunError>;
type ReadEvent<P, S, E> = fn(&mut P, &TradingEngine, &S, &mut E) -> NextEvent;

pub struct TradingTask<P, S, E> {
    engine: TradingEngine,
    source: P,
    strategy: S,
    execution: E,
    warmup: u64,
    read: ReadEvent<P, S, E>,
}

impl<P, S: StrategyPort, E: ExecutionPort> TradingTask<P, S, E> {
    pub(super) fn new(
        engine: TradingEngine,
        source: P,
        strategy: S,
        execution: E,
        warmup: u64,
        read: ReadEvent<P, S, E>,
    ) -> Self {
        Self {
            engine,
            source,
            strategy,
            execution,
            warmup,
            read,
        }
    }

    pub fn engine(&self) -> &TradingEngine {
        &self.engine
    }
    pub fn source(&self) -> &P {
        &self.source
    }
    pub fn execution(&self) -> &E {
        &self.execution
    }

    pub fn into_parts(self) -> (TradingEngine, P, S, E) {
        (self.engine, self.source, self.strategy, self.execution)
    }

    pub fn run(
        &mut self,
        consume: impl FnMut(&TradingEvent, EventOutcome) -> Result<()>,
    ) -> std::result::Result<(), TradingRunError> {
        self.engine.drive(
            |engine, execution| (self.read)(&mut self.source, engine, &self.strategy, execution),
            &self.strategy,
            &mut self.execution,
            self.warmup,
            consume,
        )
    }
}

pub(super) fn check_scope(config: &RunConfiguration, mode: &str, actual: &Scope) -> Result<()> {
    let config = config.record();
    let scope = actual.record();
    if config["runtime_kind"] != mode
        || [
            "engine",
            "runtime",
            "gateway",
            "account",
            "generation",
            "runtime_kind",
        ]
        .iter()
        .any(|key| config[*key] != scope[*key])
    {
        return Err(error("TRADING_TASK_SCOPE_MISMATCH"));
    }
    Ok(())
}

pub(super) fn check_binding(
    expected: &TradingBinding,
    actual: &TradingBinding,
    mode: &str,
    scope: &Scope,
) -> Result<()> {
    check_scope(expected.configuration(), mode, scope)?;
    if expected.fingerprint() != actual.fingerprint() {
        return Err(error("TRADING_TASK_BINDING_MISMATCH"));
    }
    Ok(())
}

pub struct VirtualEvents<P> {
    source: P,
    prepared_market: Option<MarketBar>,
    exhausted: bool,
}

impl<P> VirtualEvents<P> {
    pub(super) fn new(source: P) -> Self {
        Self {
            source,
            prepared_market: None,
            exhausted: false,
        }
    }
    pub fn source(&self) -> &P {
        &self.source
    }
    pub fn into_parts(self) -> (P, Option<MarketBar>) {
        (self.source, self.prepared_market)
    }
}

impl<P: TradingEventPort> VirtualEvents<P> {
    pub(super) fn next<O: EconomicOwner, V: VirtualVenue<O>>(
        &mut self,
        engine: &TradingEngine,
        execution: &mut VirtualExecution<O, V>,
    ) -> NextEvent {
        if let Some(fact) = execution.pending_venue().map_err(TradingRunError::Source)? {
            return Ok(Some(TradingEvent::Venue(fact)));
        }
        if let Some(bar) = self.prepared_market.take() {
            return Ok(Some(TradingEvent::Market(bar)));
        }
        if self.exhausted {
            return Ok(None);
        }
        let event = self.source.next_event().map_err(TradingRunError::Source)?;
        let bar = match event {
            Some(TradingEvent::Market(bar)) => bar,
            Some(TradingEvent::Venue(_)) => return Ok(event),
            None => {
                execution
                    .venue_mut()
                    .finish_market_input()
                    .map_err(TradingRunError::Source)?;
                self.exhausted = true;
                return execution
                    .pending_venue()
                    .map(|fact| fact.map(TradingEvent::Venue))
                    .map_err(TradingRunError::Source);
            }
        };
        if let Err(error) = engine
            .validate_bar(&bar)
            .and_then(|()| execution.prepare_market(&bar))
        {
            return Err(TradingRunError::Processing {
                event: Box::new(TradingEvent::Market(bar)),
                error,
            });
        }
        // 先应用该截面触发的回报，策略才能读取已生效的账户；读取回报失败时保留截面。
        self.prepared_market = Some(bar);
        if let Some(fact) = execution.pending_venue().map_err(TradingRunError::Source)? {
            return Ok(Some(TradingEvent::Venue(fact)));
        }
        Ok(self.prepared_market.take().map(TradingEvent::Market))
    }
}
