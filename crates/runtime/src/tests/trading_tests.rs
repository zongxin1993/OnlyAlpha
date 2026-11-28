use super::*;
use crate::{OnlyAlphaRuntime, ResearchPanel, ResearchPlan};
use onlyalpha_calculation::factor_expr::TargetExpr;
use onlyalpha_domain::{
    enums::{OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    numeric::OnlyDecimal,
};
use std::{collections::VecDeque, str::FromStr};

fn d(text: &str) -> Decimal {
    Decimal::from_str(text).unwrap()
}

fn dom(text: &str) -> OnlyDecimal {
    text.parse().unwrap()
}

fn instrument(raw: &str) -> OnlyInstrumentId {
    raw.parse().unwrap()
}

fn timestamp(seconds: i64) -> OnlyTimestamp {
    OnlyTimestamp::from_unix_nanos(seconds.into())
}

fn fields(items: &[(&str, &str)]) -> BTreeMap<String, Cell> {
    items
        .iter()
        .map(|(name, value)| ((*name).to_string(), Some(d(value))))
        .collect()
}

fn bar(seconds: i64, legs: &[(&str, &[(&str, &str)])]) -> MarketBar {
    MarketBar::new(
        timestamp(seconds),
        legs.iter()
            .map(|(id, items)| (instrument(id), fields(items)))
            .collect(),
    )
    .unwrap()
}

fn cohort(items: &[&str]) -> Vec<Cell> {
    items
        .iter()
        .map(|item| if *item == "null" { None } else { Some(d(item)) })
        .collect()
}

fn close_panel(bars: &[MarketBar], warmup: usize) -> ResearchPanel {
    let times: Vec<_> = bars.iter().map(|bar| bar.timestamp().clone()).collect();
    let instruments = bars[0]
        .instruments()
        .iter()
        .enumerate()
        .map(|(i, id)| {
            let closes = bars
                .iter()
                .map(|bar| bar.cohort()[i]["close"].clone())
                .collect();
            (
                id.clone(),
                times.clone(),
                BTreeMap::from([("close".into(), closes)]),
            )
        })
        .collect();
    ResearchPanel::new(&"a".repeat(64), instruments, warmup).unwrap()
}

fn research_plan(factors: &[NamedFactorExpr]) -> ResearchPlan {
    ResearchPlan::new(
        factors
            .iter()
            .map(|factor| (factor.name().into(), factor.expr().clone()))
            .collect(),
        vec![(
            "next_close".into(),
            TargetExpr::compile("Ref($close, -1)").unwrap(),
        )],
        2,
    )
    .unwrap()
}

/// 冷启动演练：每个事件只做一次决策，不持有任何外部状态。
struct Momentum {
    threshold: OnlyDecimal,
}

impl StrategyPort for Momentum {
    fn decide(
        &self,
        instrument: &OnlyInstrumentId,
        factors: &[NamedFactor],
        _account: &ReadonlyAccountState,
    ) -> Result<Vec<OrderIntent>> {
        let Some(value) = factors[0].value() else {
            return Ok(Vec::new());
        };
        if value <= &self.threshold {
            return Ok(Vec::new());
        }
        Ok(vec![
            OrderIntent::new(
                instrument.clone(),
                OnlyOrderSide::Buy,
                OnlyOrderType::Limit,
                dom("100"),
                Some(dom("10.5")),
                OnlyTimeInForce::Day,
                "MOMENTUM_ENTRY",
            )
            .unwrap(),
        ])
    }
}

struct Quiet;

impl StrategyPort for Quiet {
    fn decide(
        &self,
        _instrument: &OnlyInstrumentId,
        _factors: &[NamedFactor],
        _account: &ReadonlyAccountState,
    ) -> Result<Vec<OrderIntent>> {
        Ok(Vec::new())
    }
}

/// 会把意图下给别的标的，用于验证引擎的主语约束。
struct Foreign;

impl StrategyPort for Foreign {
    fn decide(
        &self,
        _instrument: &OnlyInstrumentId,
        _factors: &[NamedFactor],
        _account: &ReadonlyAccountState,
    ) -> Result<Vec<OrderIntent>> {
        Ok(vec![
            OrderIntent::new(
                instrument("999999.XSHG"),
                OnlyOrderSide::Sell,
                OnlyOrderType::Market,
                dom("1"),
                None,
                OnlyTimeInForce::Ioc,
                "FOREIGN",
            )
            .unwrap(),
        ])
    }
}

/// 两种模式共用同一套断言：只有回报事实不同，其余观测必须逐项相同。
struct RecordingBook {
    venue: &'static str,
    received: bool,
    submissions: Vec<String>,
    observations: Vec<onlyalpha_broker::Fact>,
    observation_error: Option<Error>,
}

impl RecordingBook {
    fn new(venue: &'static str, received: bool) -> Self {
        Self {
            venue,
            received,
            submissions: Vec::new(),
            observations: Vec::new(),
            observation_error: None,
        }
    }
}

impl ExecutionPort for RecordingBook {
    fn account(&self, at: &OnlyTimestamp) -> Result<ReadonlyAccountState> {
        let cash = if self.observations.is_empty() {
            "1000000"
        } else {
            "999900"
        };
        Ok(ReadonlyAccountState::new(at.clone(), dom(cash), dom("1000000"), Vec::new()).unwrap())
    }

    fn submit(&mut self, intent: &OrderIntent, _at: &OnlyTimestamp) -> Result<Vec<Value>> {
        let price = intent
            .limit_price()
            .map(ToString::to_string)
            .unwrap_or_default();
        self.submissions.push(format!(
            "{} {} {} @ {}",
            intent.instrument(),
            intent.side().as_str(),
            intent.quantity(),
            price
        ));
        Ok(vec![
            json!({"dispatch_received": self.received, "venue": self.venue}),
        ])
    }

    fn observe_venue(&mut self, fact: &onlyalpha_broker::Fact) -> Result<()> {
        if fact.scope().record()["gateway"] != self.venue {
            return Err(error("TEST_VENUE_SCOPE"));
        }
        self.observations.push(fact.clone());
        if let Some(error) = self.observation_error.take() {
            return Err(error);
        }
        Ok(())
    }
}

struct FrozenSlice {
    bars: std::vec::IntoIter<MarketBar>,
}

impl TradingEventPort for FrozenSlice {
    fn next_event(&mut self) -> Result<Option<TradingEvent>> {
        Ok(self.bars.next().map(TradingEvent::Market))
    }
}

struct LiveStream {
    events: VecDeque<TradingEvent>,
}

impl TradingEventPort for LiveStream {
    fn next_event(&mut self) -> Result<Option<TradingEvent>> {
        Ok(self.events.pop_front())
    }
}

fn collect_market(
    engine: &mut TradingEngine,
    source: &mut impl TradingEventPort,
    strategy: &impl StrategyPort,
    execution: &mut impl ExecutionPort,
) -> Vec<BarOutcome> {
    let mut bars = Vec::new();
    engine
        .run(source, strategy, execution, |_, outcome| {
            let EventOutcome::Market(bar) = outcome else {
                return Err(error("TEST_EXPECTED_MARKET"));
            };
            bars.push(bar);
            Ok(())
        })
        .unwrap();
    bars
}

fn two_instrument_bars() -> Vec<MarketBar> {
    vec![
        bar(
            1,
            &[
                ("000001.XSHE", &[("close", "1")]),
                ("600000.XSHG", &[("close", "2")]),
            ],
        ),
        bar(
            2,
            &[
                ("000001.XSHE", &[("close", "3")]),
                ("600000.XSHG", &[("close", "4")]),
            ],
        ),
        bar(
            3,
            &[
                ("000001.XSHE", &[("close", "6")]),
                ("600000.XSHG", &[("close", "8")]),
            ],
        ),
        bar(
            4,
            &[
                ("000001.XSHE", &[("close", "10")]),
                ("600000.XSHG", &[("close", "12")]),
            ],
        ),
    ]
}

fn trading_engine(factor: &str) -> TradingEngine {
    TradingEngine::new(
        vec![instrument("600000.XSHG"), instrument("000001.XSHE")],
        vec![NamedFactorExpr::compile("momentum", factor).unwrap()],
    )
    .unwrap()
}

fn series(outcomes: &[BarOutcome], instrument: usize, factor: usize) -> Vec<Cell> {
    outcomes
        .iter()
        .map(|outcome| outcome.values()[instrument][factor].clone())
        .collect()
}

#[test]
fn factor_values_match_the_vectorized_panel_pointwise() {
    let mut bars = two_instrument_bars();
    bars[1].cohort[0].insert("close".into(), None);
    let panel = close_panel(&bars, 1);
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let factors = [
        ("price", "$close"),
        ("demeaned", "CSDemean($close)"),
        ("mean_two", "Mean($close, 2)"),
        ("mean_three", "Mean($close, 3)"),
    ]
    .map(|(name, source)| NamedFactorExpr::compile(name, source).unwrap());
    let report = runtime
        .run_research(&panel, &research_plan(&factors))
        .unwrap();
    let mut engine = runtime
        .trading_engine(bars[0].instruments().to_vec(), factors.to_vec())
        .unwrap();
    assert_eq!(engine.instruments(), report.instruments());
    let outcomes = collect_market(
        &mut engine,
        &mut FrozenSlice {
            bars: bars.into_iter(),
        },
        &Quiet,
        &mut RecordingBook::new("memory", false),
    );
    let event_times: Vec<_> = outcomes
        .iter()
        .map(|outcome| outcome.timestamp().clone())
        .collect();
    assert_eq!(report.timestamps(), event_times);
    assert_eq!(report.factors().len(), factors.len());
    for (f, factor) in factors.iter().enumerate() {
        let research = &report.factors()[f];
        assert_eq!(research.name, factor.name());
        assert_eq!(research.fingerprint, factor.expr().fingerprint());
        assert_eq!(research.values.len(), report.instruments().len());
        for (i, instrument) in report.instruments().iter().enumerate() {
            assert_eq!(
                series(&outcomes, i, f),
                research.values[i],
                "{} {instrument}",
                factor.name()
            );
        }
    }
    assert_eq!(outcomes[0].values()[0][1], Some(d("-0.5")));
    assert_eq!(outcomes[0].values()[1][1], Some(d("0.5")));
    // 第一个标的在第二个时点缺值。两期均线在最后一个时点重新就绪，三期仍缺值。
    assert_eq!(
        series(&outcomes, 0, 2),
        cohort(&["null", "null", "null", "8"])
    );
    assert_eq!(
        series(&outcomes, 0, 3),
        cohort(&["null", "null", "null", "null"])
    );
    assert_eq!(series(&outcomes, 1, 2), cohort(&["null", "3", "6", "10"]));
    assert_eq!(
        series(&outcomes, 1, 3),
        cohort(&["null", "null", "4.666666666667", "8"])
    );
}

#[test]
fn one_engine_two_port_sets_produce_identical_decisions() {
    let bars = two_instrument_bars();
    let strategy = Momentum {
        threshold: dom("5"),
    };
    let mut backtest = trading_engine("$close");
    let mut memory = RecordingBook::new("memory", true);
    let replayed = collect_market(
        &mut backtest,
        &mut FrozenSlice {
            bars: bars.clone().into_iter(),
        },
        &strategy,
        &mut memory,
    );
    let mut simulation = trading_engine("$close");
    let mut gateway = RecordingBook::new("gateway", false);
    let mut stream = LiveStream {
        events: bars.into_iter().map(TradingEvent::Market).collect(),
    };
    let streamed = collect_market(&mut simulation, &mut stream, &strategy, &mut gateway);

    assert_eq!(backtest.events(), simulation.events());
    assert_eq!(replayed.len(), streamed.len());
    for (left, right) in replayed.iter().zip(&streamed) {
        assert_eq!(left.timestamp(), right.timestamp());
        assert_eq!(left.values(), right.values());
        assert_eq!(left.intents(), right.intents());
        // 只有执行事实随模式不同，因子与决策完全相同；没有意图的事件两边都不产生事实。
        if left.intents().is_empty() {
            assert_eq!(left.facts(), right.facts());
        } else {
            assert_ne!(left.facts(), right.facts());
        }
    }
    assert_eq!(memory.submissions, gateway.submissions);
    assert_eq!(memory.submissions.len(), 4);
}

fn accepted_event(gateway: &str) -> onlyalpha_broker::Fact {
    onlyalpha_broker::Fact::decode(&json!({
        "scope": {"engine":"engine", "runtime":"runtime", "gateway":gateway, "account":"account",
            "generation":"a".repeat(64), "runtime_kind":"BACKTEST"},
        "session":"session", "update_id":"update", "source_sequence":1, "ts_event":1, "ts_init":1,
        "correlation":"order", "causation":"submit", "quality":[], "kind":"ACCEPTED",
        "payload":{"order":"order", "venue":"order-at-venue"}
    }))
    .unwrap()
}

#[test]
fn same_time_venue_and_market_events_follow_delivery_order() {
    struct CaptureCash(std::cell::RefCell<Vec<OnlyDecimal>>);
    impl StrategyPort for CaptureCash {
        fn decide(
            &self,
            _: &OnlyInstrumentId,
            _: &[NamedFactor],
            account: &ReadonlyAccountState,
        ) -> Result<Vec<OrderIntent>> {
            self.0.borrow_mut().push(account.cash_available().clone());
            Ok(Vec::new())
        }
    }

    let fact = accepted_event("gateway");
    let market = TradingEvent::Market(bar(1, &[("000001.XSHE", &[("close", "1")])]));
    let venue = TradingEvent::Venue(fact.clone());
    for (events, expected_cash, observed_first) in [
        ([venue.clone(), market.clone()], "999900", true),
        ([market, venue], "1000000", false),
    ] {
        let mut source = LiveStream {
            events: events.into(),
        };
        let strategy = CaptureCash(Default::default());
        let mut book = RecordingBook::new("gateway", false);
        let mut engine = TradingEngine::new(
            vec![instrument("000001.XSHE")],
            vec![NamedFactorExpr::compile("price", "$close").unwrap()],
        )
        .unwrap();
        let mut outcomes = Vec::new();
        engine
            .run(&mut source, &strategy, &mut book, |_, outcome| {
                outcomes.push(matches!(outcome, EventOutcome::VenueObserved));
                Ok(())
            })
            .unwrap();
        assert_eq!(outcomes, [observed_first, !observed_first]);
        assert_eq!(strategy.0.into_inner(), [dom(expected_cash)]);
        assert_eq!(book.observations.as_slice(), std::slice::from_ref(&fact));
        assert_eq!(engine.events(), 1);
        assert_eq!(engine.timestamp(), Some(&timestamp(1)));
    }
}

#[test]
fn rejected_venue_observation_stops_at_the_failed_input() {
    let mut bars = two_instrument_bars().into_iter();
    let first = bars.next().unwrap();
    let second = bars.next().unwrap();
    let mut source = LiveStream {
        events: [
            TradingEvent::Market(first),
            TradingEvent::Venue(accepted_event("foreign")),
            TradingEvent::Market(second),
        ]
        .into(),
    };
    let mut book = RecordingBook::new("gateway", false);
    let mut engine = trading_engine("Mean($close, 2)");
    let mut delivered = 0;
    let failure = engine
        .run(&mut source, &Quiet, &mut book, |_, outcome| {
            assert!(matches!(outcome, EventOutcome::Market(_)));
            delivered += 1;
            Ok(())
        })
        .unwrap_err();
    let TradingRunError::Processing {
        event,
        error: cause,
    } = failure
    else {
        panic!("expected processing failure");
    };
    assert!(matches!(*event, TradingEvent::Venue(_)));
    assert_eq!(cause, error("TEST_VENUE_SCOPE"));
    assert_eq!(delivered, 1);
    assert_eq!(source.events.len(), 1);
    assert!(book.observations.is_empty());
    assert_eq!(engine.events(), 1);
    assert_eq!(engine.timestamp(), Some(&timestamp(1)));
}

#[test]
fn uncertain_venue_observation_returns_the_fact_for_reconciliation() {
    let fact = accepted_event("gateway");
    let market = two_instrument_bars().remove(0);
    let mut source = LiveStream {
        events: [
            TradingEvent::Venue(fact.clone()),
            TradingEvent::Market(market),
        ]
        .into(),
    };
    let mut engine = trading_engine("$close");
    let mut book = RecordingBook::new("gateway", true);
    book.observation_error = Some(error("TEST_OBSERVATION_UNKNOWN"));
    let failure = engine
        .run(&mut source, &Quiet, &mut book, |_, _| {
            panic!("unexpected result")
        })
        .unwrap_err();
    let TradingRunError::Processing {
        event,
        error: cause,
    } = failure
    else {
        panic!("expected processing failure");
    };
    assert_eq!(cause, error("TEST_OBSERVATION_UNKNOWN"));
    let TradingEvent::Venue(returned) = *event else {
        panic!("expected venue fact");
    };
    assert_eq!(returned, fact);
    assert_eq!(engine.events(), 0);
    assert_eq!(source.events.len(), 1);
    let observed = book
        .observations
        .iter()
        .find(|item| item.identity() == returned.identity());
    assert_eq!(observed, Some(&returned));

    let bars = collect_market(&mut engine, &mut source, &Quiet, &mut book);
    assert_eq!(bars.len(), 1);
    assert_eq!(bars[0].timestamp(), &timestamp(1));
    assert_eq!(book.observations, [fact]);
}

#[test]
fn rejected_result_preserves_submissions_and_leaves_next_event_unread() {
    let mut source = FrozenSlice {
        bars: two_instrument_bars().into_iter(),
    };
    let mut engine = trading_engine("$close");
    let mut book = RecordingBook::new("memory", true);
    let strategy = Momentum {
        threshold: dom("0"),
    };
    let failure = engine
        .run(&mut source, &strategy, &mut book, |event, outcome| {
            let (TradingEvent::Market(input), EventOutcome::Market(result)) = (event, outcome)
            else {
                panic!("expected market event and result");
            };
            assert_eq!(input.timestamp(), result.timestamp());
            assert_eq!(result.intents().len(), 2);
            Err(error("TEST_RESULT_BUDGET"))
        })
        .unwrap_err();
    let TradingRunError::Consumption {
        event,
        error: cause,
    } = failure
    else {
        panic!("expected consumption failure");
    };
    assert_eq!(cause, error("TEST_RESULT_BUDGET"));
    assert!(matches!(*event, TradingEvent::Market(input) if input.timestamp() == &timestamp(1)));
    assert_eq!(engine.events(), 1);
    assert_eq!(engine.timestamp(), Some(&timestamp(1)));
    assert_eq!(book.submissions.len(), 2);
    assert_eq!(source.bars.as_slice()[0].timestamp(), &timestamp(2));
}

#[test]
fn restarting_from_a_checkpoint_continues_identically() {
    let bars = two_instrument_bars();
    let strategy = Momentum {
        threshold: dom("5"),
    };
    let mut baseline = trading_engine("Mean($close, 2)");
    let mut book = RecordingBook::new("memory", false);
    let whole = collect_market(
        &mut baseline,
        &mut FrozenSlice {
            bars: bars.clone().into_iter(),
        },
        &strategy,
        &mut book,
    );

    let mut first = trading_engine("Mean($close, 2)");
    let mut book = RecordingBook::new("memory", true);
    for bar in &bars[..2] {
        first.advance(bar, &strategy, &mut book).unwrap();
    }
    let checkpoint = first.checkpoint();
    assert_eq!(checkpoint["events"], json!(2));

    let mut resumed = trading_engine("Mean($close, 2)");
    resumed.restore_checkpoint(&checkpoint).unwrap();
    assert_eq!(resumed.events(), 2);
    assert_eq!(resumed.timestamp(), Some(&timestamp(2)));
    let mut tail = Vec::new();
    for bar in &bars[2..] {
        tail.push(resumed.advance(bar, &strategy, &mut book).unwrap());
    }
    assert_eq!(resumed.events(), baseline.events());
    assert_eq!(resumed.timestamp(), baseline.timestamp());
    for (restarted, continuous) in tail.iter().zip(&whole[2..]) {
        assert_eq!(restarted.timestamp(), continuous.timestamp());
        assert_eq!(restarted.values(), continuous.values());
        assert_eq!(restarted.intents(), continuous.intents());
    }
}

#[test]
fn checkpoint_restore_is_atomic() {
    let bars = two_instrument_bars();
    let factors = ["Mean($close, 2)", "CSDemean($close)"]
        .map(|source| NamedFactorExpr::compile(source, source).unwrap());
    let mut engine = TradingEngine::new(bars[0].instruments().to_vec(), factors.to_vec()).unwrap();
    let genesis = engine.checkpoint();
    let mut book = RecordingBook::new("memory", false);
    engine.advance(&bars[0], &Quiet, &mut book).unwrap();
    let before = engine.checkpoint();
    let mut continuous = engine.clone();
    let expected = continuous.advance(&bars[1], &Quiet, &mut book).unwrap();
    let later = continuous.checkpoint();
    let mut bad_factor = later.clone();
    bad_factor["factors"][1]["fingerprint"] = json!("other");
    let mut missing_time = later.clone();
    missing_time["timestamp"] = Value::Null;
    let mut invalid_genesis = genesis.clone();
    invalid_genesis["timestamp"] = later["timestamp"].clone();
    for invalid in [bad_factor, missing_time, invalid_genesis] {
        assert!(engine.restore_checkpoint(&invalid).is_err());
        assert_eq!(engine.checkpoint(), before);
    }
    let actual = engine.advance(&bars[1], &Quiet, &mut book).unwrap();
    assert_eq!(actual.values(), expected.values());
    assert_eq!(engine.checkpoint(), later);
    engine.restore_checkpoint(&genesis).unwrap();
    assert_eq!(engine.checkpoint(), genesis);
}

#[test]
fn a_checkpoint_from_another_definition_is_rejected() {
    let bars = two_instrument_bars();
    let mut source = trading_engine("$close");
    let mut book = RecordingBook::new("memory", false);
    source.advance(&bars[0], &Quiet, &mut book).unwrap();
    let checkpoint = source.checkpoint();

    let mut other = trading_engine("Mean($close, 2)");
    assert_eq!(
        other.restore_checkpoint(&checkpoint).unwrap_err(),
        Error("TRADING_CHECKPOINT_BINDING".into())
    );
}

#[test]
fn the_engine_rejects_wrong_shape_out_of_order_and_foreign_intents() {
    let bars = two_instrument_bars();
    let mut engine = trading_engine("$close");
    let mut book = RecordingBook::new("memory", false);
    let single = bar(1, &[("000001.XSHE", &[("close", "1")])]);
    assert_eq!(
        engine.advance(&single, &Quiet, &mut book).unwrap_err(),
        Error("TRADING_SCHEMA_MISMATCH".into())
    );
    engine.advance(&bars[0], &Quiet, &mut book).unwrap();
    assert_eq!(
        engine.advance(&bars[0], &Quiet, &mut book).unwrap_err(),
        Error("TRADING_EVENT_ORDER".into())
    );
    assert_eq!(
        engine.advance(&bars[1], &Foreign, &mut book).unwrap_err(),
        Error("TRADING_INTENT_INSTRUMENT_MISMATCH".into())
    );
}

#[test]
fn a_failed_event_rolls_the_factor_state_back() {
    let bars = two_instrument_bars();
    let mut engine = trading_engine("Mean($close, 2)");
    let mut book = RecordingBook::new("memory", false);
    engine.advance(&bars[0], &Quiet, &mut book).unwrap();
    // 两条因子列都已推进之后才因外部意图失败，状态必须回到本事件之前。
    assert!(engine.advance(&bars[1], &Foreign, &mut book).is_err());
    assert_eq!(engine.events(), 1);
    assert_eq!(engine.timestamp(), Some(&timestamp(1)));

    let failed = engine.advance(&bars[1], &Quiet, &mut book).unwrap();
    let mut clean = trading_engine("Mean($close, 2)");
    clean.advance(&bars[0], &Quiet, &mut book).unwrap();
    let reference = clean.advance(&bars[1], &Quiet, &mut book).unwrap();
    assert_eq!(failed.values(), reference.values());
    assert_eq!(clean.events(), 2);
}

#[test]
fn bar_shape_is_canonical_and_strict() {
    assert_eq!(
        MarketBar::new(timestamp(1), Vec::new()).unwrap_err(),
        Error("TRADING_NO_INSTRUMENTS".into())
    );
    assert_eq!(
        MarketBar::new(
            timestamp(1),
            vec![
                (instrument("600000.XSHG"), fields(&[("close", "1")])),
                (instrument("600000.XSHG"), fields(&[("close", "2")])),
            ],
        )
        .unwrap_err(),
        Error("TRADING_DUPLICATE_INSTRUMENT".into())
    );
    let bar = bar(
        1,
        &[
            ("600000.XSHG", &[("close", "2")]),
            ("000001.XSHE", &[("close", "1")]),
        ],
    );
    assert_eq!(
        bar.instruments().to_vec(),
        vec![instrument("000001.XSHE"), instrument("600000.XSHG")]
    );
    assert_eq!(
        TradingEngine::new(Vec::new(), Vec::new()).unwrap_err(),
        Error("TRADING_NO_INSTRUMENTS".into())
    );
    assert_eq!(
        TradingEngine::new(vec![instrument("600000.XSHG")], Vec::new()).unwrap_err(),
        Error("TRADING_NO_FACTORS".into())
    );
    assert_eq!(
        TradingEngine::new(
            vec![instrument("600000.XSHG"), instrument("600000.XSHG")],
            vec![NamedFactorExpr::compile("momentum", "$close").unwrap()],
        )
        .unwrap_err(),
        Error("TRADING_DUPLICATE_INSTRUMENT".into())
    );
    assert_eq!(
        TradingEngine::new(
            vec![instrument("600000.XSHG")],
            vec![
                NamedFactorExpr::compile("momentum", "$close").unwrap(),
                NamedFactorExpr::compile("momentum", "$close").unwrap(),
            ],
        )
        .unwrap_err(),
        Error("TRADING_FACTOR_NAME".into())
    );
    assert_eq!(
        NamedFactorExpr::compile("", "$close").unwrap_err(),
        Error("TRADING_FACTOR_NAME".into())
    );
}

#[test]
fn the_facade_builds_research_and_trading_from_the_same_definition() {
    let runtime = OnlyAlphaRuntime::new().unwrap();
    let bars = [bar(1, &[("000001.XSHE", &[("close", "3")])])];
    let factors = [NamedFactorExpr::compile("momentum", "$close").unwrap()];
    let mut engine = runtime
        .trading_engine(bars[0].instruments().to_vec(), factors.to_vec())
        .unwrap();
    let mut book = RecordingBook::new("memory", false);
    let outcome = engine.advance(&bars[0], &Quiet, &mut book).unwrap();
    let report = runtime
        .run_research(&close_panel(&bars, 0), &research_plan(&factors))
        .unwrap();
    assert_eq!(outcome.values()[0][0], report.factors()[0].values[0][0]);
    assert_eq!(outcome.values()[0][0], Some(d("3")));
}
