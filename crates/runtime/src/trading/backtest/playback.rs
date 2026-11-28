use super::memory::{CompletedBacktest, ExecutionBinding, FrozenVenue, MemoryRunSpec};
use super::next_open::signal_at_close;
use super::{
    FrozenReplay, Inputs, MemoryBacktestVenue, NextOpenModel, NextOpenPolicy, boundary, err,
};
use crate::trading::{
    execution::{ObservationState, VenueFacts, VirtualExecution, VirtualVenue},
    finite_owner::FiniteSessionOwner,
};
use crate::{
    EventOutcome, ExecutionPort, NamedFactorExpr, OnlyAlphaRuntime, Session, StrategyPort,
    TradingEngine, TradingEvent, TradingEventPort, TradingRunError, TradingTask,
};
use onlyalpha_broker::Fact;
use onlyalpha_domain::{
    enums::{OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    identifiers::OnlyInstrumentId,
    numeric::OnlyDecimal,
    strategy::{NamedFactor, OrderIntent, ReadonlyAccountState},
    time::OnlyTimestamp,
};
use onlyalpha_execution::Error;
use onlyalpha_strategy::{Executor, NodePort, SignalExecution};
use serde_json::{Value, json};
use std::cell::RefCell;

struct SignalState<C: NodePort> {
    signal: SignalExecution<C>,
    row: usize,
    last: Option<(Value, Value, Value)>,
}

struct FrozenStrategy<'a, C: NodePort> {
    inputs: &'a Inputs,
    quantity: OnlyDecimal,
    warmup: usize,
    state: RefCell<SignalState<C>>,
}

impl<C: NodePort> StrategyPort for FrozenStrategy<'_, C> {
    fn decide(
        &self,
        instrument: &OnlyInstrumentId,
        factors: &[NamedFactor],
        account: &ReadonlyAccountState,
    ) -> Result<Vec<OrderIntent>, Error> {
        let mut state = self.state.borrow_mut();
        let input = self
            .inputs
            .records()
            .get(state.row)
            .ok_or_else(|| err("SIGNAL_INPUT_EXHAUSTED"))?;
        if state.last.is_some()
            || input.bar().instrument_id() != instrument
            || &input.event_ns() != account.timestamp().unix_nanos()
            || factors.len() != 1
            || factors[0].value() != Some(input.bar().close().value())
        {
            return Err(err("SIGNAL_INPUT_BINDING"));
        }
        let signal = boundary(state.signal.process(input.bar()))?.to_record();
        let receipts = state.signal.receipts().clone();
        let close = if state.row < self.warmup {
            json!({"status":"WARMUP"})
        } else {
            let position = account
                .positions()
                .iter()
                .find(|p| p.instrument() == instrument);
            if position.is_some_and(|p| !p.quantity().is_zero() && p.quantity() != &self.quantity) {
                return Err(err("POLICY_POSITION_SHAPE"));
            }
            signal_at_close(
                input,
                &signal,
                position.is_some_and(|p| !p.quantity().is_zero()),
            )
        };
        let intent = match close["signal"]["side"].as_str() {
            None => Vec::new(),
            Some(side) => vec![boundary(OrderIntent::new(
                instrument.clone(),
                if side == "BUY" {
                    OnlyOrderSide::Buy
                } else {
                    OnlyOrderSide::Sell
                },
                OnlyOrderType::Market,
                self.quantity.clone(),
                None,
                OnlyTimeInForce::Gtc,
                close["signal"]["decision_identity"]
                    .as_str()
                    .ok_or_else(|| err("SIGNAL_IDENTITY"))?,
            ))?],
        };
        state.last = Some((signal, receipts, close));
        state.row += 1;
        Ok(intent)
    }
}

type MarketExecution<'a> = VirtualExecution<FiniteSessionOwner, MemoryBacktestVenue<'a>>;
struct DelayedExecution<'a> {
    market: MarketExecution<'a>,
    pending: Option<OrderIntent>,
}

impl ExecutionPort for DelayedExecution<'_> {
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState, Error> {
        self.market.account(at)
    }
    fn submit(&mut self, intent: &OrderIntent, _: &OnlyTimestamp) -> Result<Vec<Value>, Error> {
        if self.pending.is_some() {
            return Err(err("DUPLICATE_CLOSE_INTENT"));
        }
        self.pending = Some(intent.clone());
        Ok(vec![])
    }
    fn observe_venue(&mut self, fact: &Fact) -> Result<(), Error> {
        let (owner, venue) = self.market.parts_mut();
        if &fact.scope() != venue.scope() {
            return Err(err("VENUE_FACT_SCOPE"));
        }
        let status = <MemoryBacktestVenue as VenueFacts<FiniteSessionOwner>>::stage(venue, fact)?;
        if status == ObservationState::Pending {
            owner.apply_observed(&venue.observed(fact)?)?;
            venue.acknowledge(owner, fact)?;
        }
        Ok(())
    }
}

struct Playback<'a> {
    replay: FrozenReplay<'a>,
    inputs: &'a Inputs,
    binding: ExecutionBinding,
    driver_binding: Value,
    row: usize,
    opened: bool,
    awaiting_result: bool,
    exhausted: bool,
    pending_signal: Value,
    warmup: usize,
    events: Vec<Value>,
    curve: Vec<Value>,
    raw: Vec<Value>,
    receipts: Vec<Value>,
    bytes: usize,
}

impl Playback<'_> {
    fn charge(&mut self, value: &Value) -> Result<(), Error> {
        self.bytes = self
            .bytes
            .checked_add(value.to_string().len())
            .filter(|n| *n <= 128 * 1024 * 1024)
            .ok_or_else(|| err("MEMORY_BUDGET"))?;
        Ok(())
    }
    fn event(&mut self, family: &str, body: Value) -> Result<(), Error> {
        let row =
            json!({"schema_version":1,"sequence":self.events.len()+1,"family":family,"body":body});
        self.charge(&row)?;
        self.events.push(row);
        Ok(())
    }
    fn drain(&mut self, execution: &mut MarketExecution<'_>) -> Result<(), Error> {
        for row in execution.owner_mut().drain_events()? {
            self.event("EXECUTION", row)?;
        }
        Ok(())
    }
    fn next<C: NodePort>(
        &mut self,
        engine: &TradingEngine,
        strategy: &FrozenStrategy<'_, C>,
        execution: &mut DelayedExecution<'_>,
    ) -> Result<Option<TradingEvent>, Error> {
        if let Some((signal, receipts, close)) = strategy.state.borrow_mut().last.take() {
            let input = &self.inputs.records()[self.row];
            self.pending_signal = close["signal"].clone();
            if self.pending_signal.is_null() == execution.pending.is_some() {
                return Err(err("SIGNAL_INTENT_RELATION"));
            }
            self.event("BAR", json!({"input_identity":input.identity(),"source_sequence":input.sequence(),"raw_signal":signal,"policy":close}))?;
            self.charge(&signal)?;
            self.charge(&receipts)?;
            self.raw.push(signal);
            self.receipts.push(receipts);
            if self.row >= self.warmup {
                let marker = json!({"bar_start_ns":input.opening().event_ns().to_string(),"bar_end_ns":input.event_ns().to_string(),"execution_prefix":execution.market.owner().session().sequence()});
                self.charge(&marker)?;
                self.curve.push(marker);
            }
            self.row += 1;
            self.opened = false;
        }
        if let Some(fact) = execution.market.pending_venue()? {
            return Ok(Some(TradingEvent::Venue(fact)));
        }
        let Some(input) = self.inputs.records().get(self.row) else {
            if !self.exhausted {
                if self.replay.next_event()?.is_some() {
                    return Err(err("MEMORY_INPUT_BINDING"));
                }
                <MemoryBacktestVenue as VirtualVenue<FiniteSessionOwner>>::finish_market_input(
                    execution.market.venue_mut(),
                )?;
                self.exhausted = true;
                if let Some(fact) = execution.market.pending_venue()? {
                    return Ok(Some(TradingEvent::Venue(fact)));
                }
            }
            self.drain(&mut execution.market)?;
            let signal = if execution.pending.take().is_some() {
                json!({"status":"CANCELLED","reason":"INPUT_EXHAUSTED","signal":self.pending_signal.take()})
            } else {
                Value::Null
            };
            self.event("END", json!({"schema_version":1,"signal":signal,"cancelled_orders":[],"holdings":"RETAINED_AT_LAST_CLOSE"}))?;
            return Ok(None);
        };
        if !self.opened {
            let opening = input.opening();
            execution.market.venue_mut().open(&opening)?;
            self.opened = true;
            if let Some(intent) = execution.pending.take() {
                execution
                    .market
                    .owner_mut()
                    .prepare_open(&opening, &self.pending_signal.take())?;
                let at = OnlyTimestamp::from_unix_nanos(opening.event_ns());
                execution.market.submit(&intent, &at)?;
                self.awaiting_result = true;
                if let Some(fact) = execution.market.pending_venue()? {
                    return Ok(Some(TradingEvent::Venue(fact)));
                }
            }
        }
        let result = if self.awaiting_result {
            execution.market.owner_mut().take_open_result()?
        } else {
            json!({"status":"NO_PENDING"})
        };
        self.awaiting_result = false;
        self.drain(&mut execution.market)?;
        self.event("OPEN", result)?;
        let Some(TradingEvent::Market(bar)) = self.replay.next_event()? else {
            return Err(err("MEMORY_INPUT_BINDING"));
        };
        engine.validate_bar(&bar)?;
        execution.market.prepare_market(&bar)?;
        if execution.market.pending_venue()?.is_some() {
            return Err(err("UNEXPECTED_CLOSE_FACT"));
        }
        execution
            .market
            .owner_mut()
            .valuation(&self.driver_binding, input)?;
        self.drain(&mut execution.market)?;
        Ok(Some(TradingEvent::Market(bar)))
    }
}

pub struct FiniteBacktestTask<'a, C: NodePort> {
    task: TradingTask<Playback<'a>, FrozenStrategy<'a, C>, DelayedExecution<'a>>,
    initial: i64,
    end: i64,
    completed: bool,
    started: bool,
}

impl<'a, C: NodePort> FiniteBacktestTask<'a, C> {
    pub fn session(&self) -> &Session {
        self.task.execution().market.owner().session()
    }
    pub fn run(
        &mut self,
        consume: impl FnMut(&TradingEvent, EventOutcome) -> Result<(), Error>,
    ) -> Result<(), TradingRunError> {
        if self.started {
            return Err(TradingRunError::Source(err("MEMORY_NOT_RUNNING")));
        }
        self.started = true;
        self.task.run(consume)?;
        self.completed = true;
        Ok(())
    }
    pub fn finish(self) -> Result<CompletedBacktest, Error> {
        let (engine, tape, strategy, execution) = self.task.into_parts();
        if !self.completed
            || !tape.exhausted
            || execution.pending.is_some()
            || tape.row != tape.inputs.records().len()
            || engine.events() != tape.row as u64
        {
            return Err(err("MEMORY_INCOMPLETE"));
        }
        let mut signal = strategy.state.into_inner().signal;
        let checkpoint = boundary(signal.finish_barrier())?;
        let program = signal.program();
        let (owner, venue) = execution.market.into_parts();
        let first = &tape.inputs.records()[tape.warmup];
        let last = tape
            .inputs
            .records()
            .last()
            .ok_or_else(|| err("MEMORY_SAMPLE_WINDOW"))?;
        let (price, context) = owner.model().baseline_entry(first)?;
        let quote =
            owner
                .policy()
                .analytical_entry_quote(&price, &owner.model().quantity, &context)?;
        let baseline = owner.model().retained_baseline(first, last, &quote)?;
        let venue = venue.finish()?;
        let (session, policy) = owner.finish(self.initial, self.end)?;
        CompletedBacktest::verified(
            tape.binding,
            session,
            venue,
            program.to_record(),
            checkpoint,
            tape.raw,
            tape.receipts,
            tape.events,
            tape.curve,
            baseline,
            tape.inputs,
            &*policy,
        )
    }
}

impl OnlyAlphaRuntime {
    pub fn backtest<'a, C: NodePort>(
        &self,
        replay: FrozenReplay<'a>,
        spec: MemoryRunSpec,
        inputs: &'a Inputs,
        mut executor: Executor<C>,
        policy: Box<dyn NextOpenPolicy>,
        venue: FrozenVenue,
    ) -> Result<FiniteBacktestTask<'a, C>, Error> {
        boundary(executor.require_genesis())?;
        let panel = replay.panel;
        let binding = ExecutionBinding::new(
            &spec.configuration,
            &spec.policy_settings,
            spec.initial_ns,
            &spec.cluster,
            &policy.binding(),
            &venue,
            panel,
        )?;
        let model = NextOpenModel::new(
            &spec.policy_settings,
            policy.binding(),
            spec.initial_ns.into(),
            &spec.cluster,
        )?;
        let end = i64::try_from(model.end.clone()).map_err(|_| err("MEMORY_SAMPLE_WINDOW"))?;
        let config = spec.configuration.record();
        let program = executor.program();
        if spec.binding.record()["execution"] != binding.fingerprint()
            || spec.binding.record()["input_pin"] != inputs.fingerprint()
            || spec.binding.record()["signal_program"] != program.fingerprint()
            || program.generation() != config["generation"]
            || program.scope().engine.value() != config["engine"]
            || program.scope().runtime.value() != config["runtime"]
            || program.scope().cluster.value() != spec.cluster
            || config["profiles"][&spec.cluster]["revision"] != program.revision().fingerprint()
            || program.revision().universe() != panel.instrument_ids()
            || panel.instrument_count() != 1
        {
            return Err(err("MEMORY_PROGRAM_BINDING"));
        }
        let mut bytes = 0usize;
        for (i, input) in inputs.records().iter().enumerate() {
            let start = input.opening().event_ns();
            if input.source() != program.source()
                || input.bar().bar_type().semantic() != program.revision().semantic()
                || start < spec.initial_ns.into()
                || input.event_ns() > model.end
                || (start < model.start) != (i < panel.warmup())
            {
                return Err(err("MEMORY_INPUT_BINDING"));
            }
            bytes = bytes
                .checked_add(input.record().to_string().len())
                .filter(|n| *n <= 128 * 1024 * 1024)
                .ok_or_else(|| err("MEMORY_BUDGET"))?;
        }
        if panel.warmup() >= inputs.records().len() {
            return Err(err("MEMORY_SAMPLE_WINDOW"));
        }
        let driver_binding = json!({"policy":spec.policy_settings,"program":{"scope":{"cluster":spec.cluster},"revision":{"strategy_fingerprint":program.revision().fingerprint()}},"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
        let source = MemoryBacktestVenue::input_fingerprint(panel, inputs, end);
        let venue = MemoryBacktestVenue::new(
            &spec.configuration,
            panel,
            &venue.artifact,
            &venue.settings,
            &venue.source,
            inputs,
            end,
            &source,
        )?;
        let strategy = FrozenStrategy {
            inputs,
            quantity: model.quantity.value().clone(),
            warmup: panel.warmup(),
            state: RefCell::new(SignalState {
                signal: SignalExecution::new(executor),
                row: 0,
                last: None,
            }),
        };
        let owner = FiniteSessionOwner::new(
            Session::new(&spec.configuration, &spec.binding)?,
            venue.scope().clone(),
            model,
            policy,
        )?;
        let market = VirtualExecution::new(owner, venue)?;
        let engine = self.backtest_engine(
            &replay,
            &spec.configuration,
            vec![NamedFactorExpr::compile("close", "$close")?],
            &market,
        )?;
        let tape = Playback {
            replay,
            inputs,
            binding,
            driver_binding,
            row: 0,
            opened: false,
            awaiting_result: false,
            exhausted: false,
            pending_signal: Value::Null,
            warmup: panel.warmup(),
            events: vec![],
            curve: vec![],
            raw: vec![],
            receipts: vec![],
            bytes,
        };
        let task = TradingTask::new(
            engine,
            tape,
            strategy,
            DelayedExecution {
                market,
                pending: None,
            },
            0,
            |source, engine, strategy, execution| {
                source
                    .next(engine, strategy, execution)
                    .map_err(TradingRunError::Source)
            },
        );
        Ok(FiniteBacktestTask {
            task,
            initial: spec.initial_ns,
            end,
            completed: false,
            started: false,
        })
    }
}
