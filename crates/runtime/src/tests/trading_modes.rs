use super::{Inputs, MarketInput, MemoryBacktestVenue, Source};
#[path = "support/trading_modes.rs"]
mod execution_test_fixture;
use crate::{
    Cohort, EventOutcome, MarketBar, NamedFactorExpr, OnlyAlphaRuntime, ResearchPanel,
    ResearchPlan, RunConfiguration, StrategyPort, TradingEvent, TradingEventPort, TradingRunError,
    durability::TradingBinding,
    trading::{backtest::FrozenReplay, execution::*},
};
use onlyalpha_broker::{self as broker, BrokerCommand, CommandState, Fact, Scope};
use onlyalpha_broker_virtual::VirtualBroker;
use onlyalpha_calculation::factor_expr::TargetExpr;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, value::OnlyMoney};
use onlyalpha_domain::{
    enums::{OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    identifiers::OnlyInstrumentId,
    numeric::OnlyDecimal,
    strategy::{NamedFactor, OrderIntent, ReadonlyAccountState},
    time::OnlyTimestamp,
};
use onlyalpha_execution::Error;
use serde_json::json;
use std::{cell::RefCell, collections::VecDeque, rc::Rc};

fn boundary(e: impl std::fmt::Display) -> Error {
    Error(e.to_string())
}

fn config(mode: &str) -> RunConfiguration {
    let mut record = execution_test_fixture::configuration(false);
    record["runtime_kind"] = json!(mode);
    RunConfiguration::from_record(record).unwrap()
}

fn scope(config: &RunConfiguration) -> Scope {
    let cfg = config.record();
    Scope::decode(&json!({
        "engine":cfg["engine"], "runtime":cfg["runtime"], "gateway":cfg["gateway"],
        "account":cfg["account"], "generation":cfg["generation"], "runtime_kind":cfg["runtime_kind"]
    }))
    .unwrap()
}

fn instrument() -> OnlyInstrumentId {
    execution_test_fixture::configuration(false)["instruments"][0]["id"]
        .as_str()
        .unwrap()
        .parse()
        .unwrap()
}

fn timestamp(n: i128) -> OnlyTimestamp {
    OnlyTimestamp::from_unix_nanos(n.into())
}

fn factors() -> Vec<NamedFactorExpr> {
    vec![NamedFactorExpr::compile("mean", "Mean($close, 2)").unwrap()]
}

fn panel(snapshot: &str, last_close: &str) -> ResearchPanel {
    let data: Cohort = [(
        "close".into(),
        ["2", "4", "8", last_close]
            .map(|s| Some(s.parse().unwrap()))
            .to_vec(),
    )]
    .into();
    ResearchPanel::new(
        snapshot,
        vec![(
            instrument(),
            (1..=4).map(|n| timestamp(n * MINUTE)).collect(),
            data,
        )],
        2,
    )
    .unwrap()
}

fn market(n: i128) -> TradingEvent {
    TradingEvent::Market(
        MarketBar::new(
            timestamp(n),
            vec![(
                instrument(),
                [("close".into(), Some("4".parse().unwrap()))].into(),
            )],
        )
        .unwrap(),
    )
}

fn venue(config: &RunConfiguration) -> Fact {
    Fact::decode(&json!({
        "scope":scope(config).record(), "session":"session", "update_id":"update", "source_sequence":1,
        "ts_event":1, "ts_init":1, "correlation":"order", "causation":"submit", "quality":[], "kind":"ACCEPTED",
        "payload":{"order":"order", "venue":"order-at-venue"}
    })).unwrap()
}

#[derive(Default, Clone)]
struct Strategy {
    cash: Rc<RefCell<Vec<OnlyDecimal>>>,
    order: bool,
}

impl StrategyPort for Strategy {
    fn decide(
        &self,
        id: &OnlyInstrumentId,
        _: &[NamedFactor],
        account: &ReadonlyAccountState,
    ) -> Result<Vec<OrderIntent>, Error> {
        self.cash
            .borrow_mut()
            .push(account.cash_available().clone());
        if self.order && self.cash.borrow().len() == 1 {
            let order = OrderIntent::new(
                id.clone(),
                OnlyOrderSide::Buy,
                OnlyOrderType::Limit,
                "100".parse().unwrap(),
                Some("10".parse().unwrap()),
                OnlyTimeInForce::Day,
                "MODE_TEST",
            )
            .unwrap();
            return Ok(vec![order]);
        }
        Ok(Vec::new())
    }
}

#[derive(Clone, Default)]
struct Stream(Rc<RefCell<VecDeque<TradingEvent>>>);

impl From<Vec<TradingEvent>> for Stream {
    fn from(events: Vec<TradingEvent>) -> Self {
        Self(Rc::new(RefCell::new(events.into())))
    }
}

impl TradingEventPort for Stream {
    fn next_event(&mut self) -> Result<Option<TradingEvent>, Error> {
        Ok(self.0.borrow_mut().pop_front())
    }
}

const MINUTE: i128 = 60_000_000_000;

struct Owner<B> {
    binding: B,
    scope: Scope,
    observed: Vec<Fact>,
    account_reads: RefCell<Vec<OnlyTimestamp>>,
    admitted: Option<(BrokerCommand, i64)>,
}

impl<B> Owner<B> {
    fn new(binding: B, scope: Scope) -> Self {
        Self {
            binding,
            scope,
            observed: Vec::new(),
            account_reads: RefCell::default(),
            admitted: None,
        }
    }

    fn admitted_at(&self, command: &BrokerCommand) -> Result<i64, broker::Error> {
        self.admitted
            .as_ref()
            .filter(|(original, _)| original == command)
            .map(|(_, at)| *at)
            .ok_or_else(|| broker::Error::new("TEST_COMMAND_NOT_ADMITTED"))
    }

    fn receipt(&self, fact: &Fact) -> Result<Option<broker::ApplicationReceipt>, broker::Error> {
        self.observed
            .iter()
            .find(|f| *f == fact)
            .map(|original| {
                broker::ApplicationReceipt::new(
                    original,
                    "application".into(),
                    original.fingerprint().into(),
                    broker::ApplicationStatus::Applied,
                )
            })
            .transpose()
    }
}

impl<B> EconomicOwner for Owner<B> {
    fn scope(&self) -> &Scope {
        &self.scope
    }

    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState, Error> {
        self.account_reads.borrow_mut().push(at.clone());
        let cash = if self.observed.is_empty() {
            "1000"
        } else {
            "900"
        };
        ReadonlyAccountState::new(
            at.clone(),
            cash.parse().unwrap(),
            "1000".parse().unwrap(),
            vec![],
        )
        .map_err(boundary)
    }

    fn admit(&mut self, intent: &OrderIntent, at: &OnlyTimestamp) -> Result<Admission, Error> {
        assert!(self.admitted.is_none());
        let mut request =
            execution_test_fixture::original_three_facts()[0]["payload"]["request"].clone();
        request["account_id"] = json!({"schema_version":1,"value":self.scope.record()["account"]});
        request["quantity"]["value"] = json!(intent.quantity().to_string());
        let command = BrokerCommand::decode(
            &json!({"schema_version":1,"scope":self.scope.record(),"operation":"SUBMIT",
            "command_id":"submit", "order":"order", "client":"client", "request":request}),
        )
        .map_err(boundary)?;
        self.admitted = Some((command.clone(), i64::try_from(at.unix_nanos()).unwrap()));
        Ok(Admission {
            facts: vec![json!("admitted")],
            command: Some(command),
        })
    }

    fn apply_venue(&mut self, fact: &Fact) -> Result<(), Error> {
        self.observed.push(fact.clone());
        Ok(())
    }
}

impl FiniteEconomicOwner for Owner<RunConfiguration> {
    fn configuration(&self) -> &RunConfiguration {
        &self.binding
    }
}

impl broker::FiniteRuntimeReader for Owner<RunConfiguration> {
    fn simulation_intent(
        &self,
        command: &BrokerCommand,
    ) -> Result<broker::SimulationIntent, broker::Error> {
        broker::SimulationIntent::new(
            command.clone(),
            "tx".into(),
            "b".repeat(64),
            &json!(self.admitted_at(command)?),
        )
    }
    fn simulation_receipt(
        &self,
        fact: &Fact,
    ) -> Result<Option<broker::ApplicationReceipt>, broker::Error> {
        self.receipt(fact)
    }
    fn simulation_order(
        &self,
        _: &BrokerCommand,
    ) -> Result<Option<broker::OrderView>, broker::Error> {
        Ok(None)
    }
}

impl DurableEconomicOwner for Owner<TradingBinding> {
    fn binding(&self) -> &TradingBinding {
        &self.binding
    }
}

impl broker::RuntimeReader for Owner<TradingBinding> {
    fn ready_intent(&self, command: &BrokerCommand) -> Result<broker::ReadyIntent, broker::Error> {
        let at = self.admitted_at(command)?;
        broker::ReadyIntent::new(command.clone(), "tx".into(), "b".repeat(64))?
            .at_admission(&json!(at))
    }
    fn application_receipt(
        &self,
        fact: &Fact,
    ) -> Result<Option<broker::ApplicationReceipt>, broker::Error> {
        self.receipt(fact)
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<broker::OrderView>, broker::Error> {
        Ok(None)
    }
}

fn inputs(snapshot: &str, last_close: &str) -> Inputs {
    use serde_json::Value;
    let template = serde_json::from_str::<Value>(include_str!(
        "../../../../test-data/execution/linear-perpetual.json"
    ))
    .unwrap();
    let time = |n| timestamp(n).to_datetime().unwrap().to_string();
    let source = Source::new(&"d".repeat(64), snapshot, &"e".repeat(64), "recorded", 0, 4).unwrap();
    let records = ["2.00", "4.00", "8.00", last_close]
        .into_iter()
        .enumerate()
        .map(|(row, close)| {
            let mut record = template["venue_bar"].clone();
            let at = (row as i128 + 1) * MINUTE;
            record["bar_start"] = json!(time(at - MINUTE));
            for field in ["bar_end", "ts_event", "ts_init"] {
                record[field] = json!(time(at));
            }
            record["trading_day"] = json!(&time(at)[..10]);
            record["bar_type"]["instrument_id"] = instrument().to_record();
            for field in ["open", "high", "low", "close"] {
                record[field]["value"] = json!(close);
            }
            MarketInput::new(
                source.id(),
                row as u64 + 1,
                "recorded",
                OnlyBar::from_record(&record).unwrap(),
            )
            .unwrap()
        })
        .collect();
    Inputs::new(vec![source], records).unwrap()
}

const TERMINAL_AT: i64 = 4 * MINUTE as i64 + 10;

fn memory_venue<'a>(
    config: &RunConfiguration,
    panel: &ResearchPanel,
    inputs: &'a Inputs,
    expected_inputs: &str,
) -> Result<MemoryBacktestVenue<'a>, Error> {
    let scope = scope(config);
    let cash = OnlyMoney::from_record(&json!({"schema_version":1,"currency":config.record()["currency"], "amount":config.record()["initial_cash"]})).unwrap();
    let artifact = "f".repeat(64);
    let settings = json!({"latency":{"fill_ns":10}});
    let source = VirtualBroker::new(scope, &artifact, cash, &settings).unwrap();
    MemoryBacktestVenue::new(
        config,
        panel,
        &artifact,
        &settings,
        &broker::digest(source.source_binding()),
        inputs,
        TERMINAL_AT,
        expected_inputs,
    )
}

fn finite_execution<'a>(
    config: &RunConfiguration,
    panel: &ResearchPanel,
    inputs: &'a Inputs,
) -> VirtualExecution<Owner<RunConfiguration>, MemoryBacktestVenue<'a>> {
    let expected = MemoryBacktestVenue::input_fingerprint(panel, inputs, TERMINAL_AT);
    let venue = memory_venue(config, panel, inputs, &expected).unwrap();
    VirtualExecution::new(Owner::new(config.clone(), scope(config)), venue).unwrap()
}

struct OfflineVenue {
    scope: Scope,
    on_prepare: Option<Fact>,
    pending: Option<Fact>,
    dispatches: usize,
}

impl OfflineVenue {
    fn new(config: &RunConfiguration) -> Self {
        Self {
            scope: scope(config),
            on_prepare: None,
            pending: None,
            dispatches: 0,
        }
    }
}

impl VenueFacts<Owner<TradingBinding>> for OfflineVenue {
    fn scope(&self) -> &Scope {
        &self.scope
    }
    fn stage(&mut self, _: &Fact) -> Result<ObservationState, Error> {
        Ok(ObservationState::Pending)
    }
    fn acknowledge(&mut self, owner: &Owner<TradingBinding>, fact: &Fact) -> Result<(), Error> {
        assert_eq!(owner.observed.last(), Some(fact));
        if self.pending.as_ref() == Some(fact) {
            self.pending.take();
        }
        Ok(())
    }
}

impl VirtualVenue<Owner<TradingBinding>> for OfflineVenue {
    fn prepare_market(&mut self, _: &MarketBar) -> Result<(), Error> {
        assert!(self.pending.is_none());
        self.pending = self.on_prepare.take();
        Ok(())
    }
    fn pending_venue(&mut self) -> Result<Option<Fact>, Error> {
        Ok(self.pending.clone())
    }
    fn dispatch_simulated(
        &mut self,
        owner: &Owner<TradingBinding>,
        command: &BrokerCommand,
    ) -> Result<CommandState, Error> {
        owner.admitted_at(command).map_err(boundary)?;
        self.dispatches += 1;
        Ok(CommandState::Known)
    }
}

impl AuthorizedLiveGateway<Owner<TradingBinding>> for OfflineVenue {
    fn dispatch_authorized(
        &mut self,
        _: &Owner<TradingBinding>,
        _: &BrokerCommand,
    ) -> Result<CommandState, Error> {
        self.dispatches += 1;
        Err(Error("TEST_LIVE_AUTHORIZATION_MISSING".into()))
    }
}

fn durable_owner(binding: &TradingBinding) -> Owner<TradingBinding> {
    Owner::new(binding.clone(), scope(binding.configuration()))
}

fn replay(panel: &ResearchPanel) -> FrozenReplay<'_> {
    FrozenReplay::new(panel, panel.snapshot(), panel.content_digest()).unwrap()
}

#[test]
fn backtest_matches_research_and_routes_only_post_warmup_intents_to_memory_broker() {
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let config = config("BACKTEST");
    let panel = panel(&"a".repeat(64), "10");
    let factors = factors();
    let plan = ResearchPlan::new(
        vec![("mean".into(), factors[0].expr().clone())],
        vec![(
            "next".into(),
            TargetExpr::compile("Ref($close, -1)").unwrap(),
        )],
        2,
    )
    .unwrap();
    let research = runtime.run_research(&panel, &plan).unwrap();
    let strategy = Strategy {
        order: true,
        ..Default::default()
    };
    let inputs = inputs(panel.snapshot(), "10.00");
    let mut task = runtime
        .backtest_with_ports(
            replay(&panel),
            &config,
            factors,
            strategy.clone(),
            finite_execution(&config, &panel, &inputs),
        )
        .unwrap();
    let mut delivered = Vec::new();
    let mut values = Vec::new();
    let mut emitted = Vec::new();
    task.run(|event, outcome| {
        if let EventOutcome::Market(bar) = outcome {
            assert_eq!(bar.timestamp(), &panel.timestamps()[values.len()]);
            values.push(bar.values()[0][0].clone());
            emitted.push(bar.intents().len());
            delivered.push("MARKET".to_string());
        } else if let TradingEvent::Venue(fact) = event {
            delivered.push(fact.record()["kind"].as_str().unwrap().into());
        } else {
            panic!("预期收到原始场所回报");
        }
        Ok(())
    })
    .unwrap();
    assert_eq!(values, research.factors()[0].values[0]);
    assert_eq!(
        values[2..],
        [Some("6".parse().unwrap()), Some("9".parse().unwrap())]
    );
    assert_eq!(emitted, [0, 0, 1, 0]);
    assert_eq!(
        delivered,
        ["MARKET", "MARKET", "MARKET", "ACCEPTED", "MARKET", "TRADE"]
    );
    assert_eq!(
        &*strategy.cash.borrow(),
        &["1000", "900"].map(|v| v.parse::<OnlyDecimal>().unwrap())
    );
    let (_, source, _, execution) = task.into_parts();
    assert_eq!(source.source().virtual_time(), panel.timestamps().last());
    let (owner, venue) = execution.into_parts();
    assert_eq!(owner.admitted.unwrap().1, (3 * MINUTE) as i64);
    assert_eq!(*owner.account_reads.borrow(), panel.timestamps()[2..]);
    assert_eq!(
        owner
            .observed
            .iter()
            .map(|f| f.record()["kind"].clone())
            .collect::<Vec<_>>(),
        [json!("ACCEPTED"), json!("TRADE")]
    );
    let finished = venue.finish().unwrap();
    let bars: Vec<_> = finished
        .source_trace()
        .iter()
        .filter(|step| step.bar_reference().is_some())
        .collect();
    assert_eq!(bars.len(), 4);
    let last_bar = bars[3].record();
    assert_eq!(
        last_bar["born"],
        json!([
            {"fact": owner.observed[0].record(), "stream_at": 4 * MINUTE as i64},
            {"fact": owner.observed[1].record(), "stream_at": TERMINAL_AT}
        ])
    );
}

#[test]
fn backtest_refuses_different_initial_capital_with_identical_scope() {
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let cfg = config("BACKTEST");
    let mut changed = cfg.record().clone();
    changed["initial_cash"] = json!("2000.00");
    changed["capitals"]["cluster"] = json!("2000.00");
    let other = RunConfiguration::from_record(changed).unwrap();
    assert_eq!(scope(&cfg), scope(&other));
    assert_ne!(cfg.fingerprint(), other.fingerprint());
    let panel = panel(&"a".repeat(64), "10");
    let inputs = inputs(panel.snapshot(), "10.00");
    let execution = finite_execution(&cfg, &panel, &inputs);
    let error = runtime
        .backtest_with_ports(
            replay(&panel),
            &other,
            factors(),
            Strategy::default(),
            execution,
        )
        .err()
        .unwrap();
    assert_eq!(error.0, "TRADING_TASK_BINDING_MISMATCH");

    let (_, venue) = finite_execution(&cfg, &panel, &inputs).into_parts();
    let owner = Owner::new(other.clone(), scope(&other));
    let execution = VirtualExecution::new(owner, venue).unwrap();
    let error = runtime
        .backtest_with_ports(
            replay(&panel),
            &other,
            factors(),
            Strategy::default(),
            execution,
        )
        .err()
        .unwrap();
    assert_eq!(error.0, "BACKTEST_REPLAY_VENUE_INPUT_BINDING");
}

#[test]
fn memory_venue_checks_frozen_digest_snapshot_and_bar_values() {
    let config = config("BACKTEST");
    let panel = panel(&"a".repeat(64), "10");
    let original = inputs(panel.snapshot(), "10.00");
    let changed = inputs(panel.snapshot(), "11.00");
    let pinned = MemoryBacktestVenue::input_fingerprint(&panel, &original, TERMINAL_AT);
    let repinned = MemoryBacktestVenue::input_fingerprint(&panel, &changed, TERMINAL_AT);
    assert_ne!(pinned, repinned);
    let error = memory_venue(&config, &panel, &changed, &pinned)
        .err()
        .unwrap();
    assert_eq!(error.0, "BACKTEST_REPLAY_VENUE_INPUT_BINDING");
    let error = memory_venue(&config, &panel, &changed, &repinned)
        .err()
        .unwrap();
    assert_eq!(error.0, "BACKTEST_REPLAY_VENUE_BAR_VALUE");

    let foreign = inputs(&"b".repeat(64), "10.00");
    let pinned = MemoryBacktestVenue::input_fingerprint(&panel, &foreign, TERMINAL_AT);
    let error = memory_venue(&config, &panel, &foreign, &pinned)
        .err()
        .unwrap();
    assert_eq!(error.0, "BACKTEST_REPLAY_VENUE_INPUT_BINDING");
}

#[test]
fn backtest_checks_frozen_replay_against_venue_panel() {
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let config = config("BACKTEST");
    let original = panel(&"a".repeat(64), "10");
    let inputs = inputs(original.snapshot(), "10.00");
    for other in [
        panel(original.snapshot(), "11"),
        panel(&"b".repeat(64), "10"),
    ] {
        let execution = finite_execution(&config, &original, &inputs);
        let error = runtime
            .backtest_with_ports(
                replay(&other),
                &config,
                factors(),
                Strategy::default(),
                execution,
            )
            .err()
            .unwrap();
        assert_eq!(error.0, "BACKTEST_REPLAY_VENUE_INPUT_BINDING");
    }
}

#[test]
fn sim_applies_market_generated_reports_before_strategy_and_preserves_task_isolation() {
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let cfg = config("SIM");
    let binding = TradingBinding::new(cfg.clone(), &"b".repeat(64)).unwrap();
    let build = |generate| {
        let mut venue_port = OfflineVenue::new(&cfg);
        if generate {
            venue_port.on_prepare = Some(venue(&cfg));
        }
        runtime
            .sim(
                &binding,
                vec![instrument()],
                factors(),
                Stream::from(vec![market(1)]),
                Strategy {
                    order: true,
                    ..Default::default()
                },
                VirtualExecution::new(durable_owner(&binding), venue_port).unwrap(),
            )
            .unwrap()
    };
    let mut first = build(true);
    let mut second = build(false);
    let mut order = Vec::new();
    first
        .run(|_, outcome| {
            order.push(matches!(outcome, EventOutcome::VenueObserved));
            Ok(())
        })
        .unwrap();
    assert_eq!(order, [true, false]);
    assert_eq!(second.engine().events(), 0);
    second
        .run(|_, outcome| {
            assert!(matches!(outcome, EventOutcome::Market(_)));
            Ok(())
        })
        .unwrap();
    for (task, cash, observed) in [(first, "900", 1), (second, "1000", 0)] {
        let (engine, _, strategy, execution) = task.into_parts();
        assert_eq!(engine.events(), 1);
        assert_eq!(
            strategy.cash.borrow().as_slice(),
            &[cash.parse::<OnlyDecimal>().unwrap()]
        );
        let (owner, venue) = execution.into_parts();
        assert_eq!(owner.observed.len(), observed);
        assert_eq!(venue.dispatches, 1);
    }
}

#[test]
fn sim_keeps_source_order_at_equal_times_and_returns_the_consumed_event() {
    let cfg = config("SIM");
    let binding = TradingBinding::new(cfg.clone(), &"b".repeat(64)).unwrap();
    for report_first in [false, true] {
        let report = venue(&cfg);
        let mut events = vec![market(1), TradingEvent::Venue(report.clone())];
        if report_first {
            events.reverse();
        }
        let stream = Stream::from(events);
        let strategy = Strategy::default();
        let mut task = OnlyAlphaRuntime::new()
            .unwrap()
            .sim(
                &binding,
                vec![instrument()],
                factors(),
                stream.clone(),
                strategy.clone(),
                VirtualExecution::new(durable_owner(&binding), OfflineVenue::new(&cfg)).unwrap(),
            )
            .unwrap();
        let error = task
            .run(|_, _| Err(Error("TEST_CONSUMER".into())))
            .unwrap_err();
        let TradingRunError::Consumption { event, error } = error else {
            panic!("应保留已消费的输入")
        };
        assert_eq!(error.0, "TEST_CONSUMER");
        match *event {
            TradingEvent::Market(ref bar) => {
                assert!(!report_first);
                assert_eq!(bar.timestamp(), &timestamp(1));
            }
            TradingEvent::Venue(ref fact) => {
                assert!(report_first);
                assert_eq!(fact, &report);
            }
        }
        assert_eq!(stream.0.borrow().len(), 1);
        task.run(|_, _| Ok(())).unwrap();
        let cash = if report_first { "900" } else { "1000" };
        assert_eq!(
            strategy.cash.borrow().as_slice(),
            &[cash.parse::<OnlyDecimal>().unwrap()]
        );
        assert_eq!(task.engine().events(), 1);
        assert_eq!(task.into_parts().3.into_parts().0.observed, vec![report]);
    }
}

#[test]
fn live_denied_dispatch_preserves_following_report_for_observation() {
    let cfg = config("LIVE");
    let binding = TradingBinding::new(cfg.clone(), &"b".repeat(64)).unwrap();
    let report = venue(&cfg);
    let source = Stream::from(vec![
        market(1),
        TradingEvent::Venue(report.clone()),
        market(2),
    ]);
    let strategy = Strategy {
        order: true,
        ..Default::default()
    };
    let mut task = OnlyAlphaRuntime::new()
        .unwrap()
        .live(
            &binding,
            vec![instrument()],
            factors(),
            source.clone(),
            strategy.clone(),
            LiveExecution::new(durable_owner(&binding), OfflineVenue::new(&cfg)).unwrap(),
        )
        .unwrap();
    let err = task.run(|_, _| Ok(())).unwrap_err();
    let TradingRunError::Processing { event, error } = err else {
        panic!("派单拒绝须返回失败行情")
    };
    assert_eq!(error.0, "TEST_LIVE_AUTHORIZATION_MISSING");
    assert!(matches!(*event, TradingEvent::Market(ref b) if b.timestamp() == &timestamp(1)));
    assert_eq!(source.0.borrow().len(), 2);
    let mut observed = Vec::new();
    task.run(|_, outcome| {
        observed.push(matches!(outcome, EventOutcome::VenueObserved));
        Ok(())
    })
    .unwrap();
    assert_eq!(observed, [true, false]);
    assert_eq!(
        &*strategy.cash.borrow(),
        &["1000", "900"].map(|v| v.parse::<OnlyDecimal>().unwrap())
    );
    let (owner, gateway) = task.into_parts().3.into_parts();
    assert_eq!(owner.observed, vec![report]);
    assert_eq!(gateway.dispatches, 1);
}

#[test]
fn continuous_tasks_reject_foreign_modes_and_repinned_artifacts() {
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let sim = TradingBinding::new(config("SIM"), &"b".repeat(64)).unwrap();
    let live = TradingBinding::new(config("LIVE"), &"b".repeat(64)).unwrap();
    let repin = |binding: &TradingBinding| {
        let other = TradingBinding::new(binding.configuration().clone(), &"c".repeat(64)).unwrap();
        assert_eq!(other.key(), binding.key());
        assert_ne!(other.fingerprint(), binding.fingerprint());
        other
    };
    for (expected, code) in [
        (repin(&sim), "TRADING_TASK_BINDING_MISMATCH"),
        (live.clone(), "TRADING_TASK_SCOPE_MISMATCH"),
    ] {
        let execution =
            VirtualExecution::new(durable_owner(&sim), OfflineVenue::new(sim.configuration()))
                .unwrap();
        let error = runtime
            .sim(
                &expected,
                vec![instrument()],
                factors(),
                Stream::default(),
                Strategy::default(),
                execution,
            )
            .err()
            .unwrap();
        assert_eq!(error.0, code);
    }
    for (expected, code) in [
        (repin(&live), "TRADING_TASK_BINDING_MISMATCH"),
        (sim.clone(), "TRADING_TASK_SCOPE_MISMATCH"),
    ] {
        let execution = LiveExecution::new(
            durable_owner(&live),
            OfflineVenue::new(live.configuration()),
        )
        .unwrap();
        let error = runtime
            .live(
                &expected,
                vec![instrument()],
                factors(),
                Stream::default(),
                Strategy::default(),
                execution,
            )
            .err()
            .unwrap();
        assert_eq!(error.0, code);
    }
    let mut foreign = sim.configuration().record().clone();
    foreign["gateway"] = json!("another_gateway");
    let foreign = RunConfiguration::from_record(foreign).unwrap();
    assert!(VirtualExecution::new(durable_owner(&sim), OfflineVenue::new(&foreign)).is_err());
    assert!(
        VirtualExecution::new(
            durable_owner(&live),
            OfflineVenue::new(live.configuration())
        )
        .is_err()
    );
    assert!(
        LiveExecution::new(durable_owner(&sim), OfflineVenue::new(sim.configuration())).is_err()
    );
}
