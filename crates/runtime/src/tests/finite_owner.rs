use super::*;
use onlyalpha_broker_virtual::MemoryVirtualActor;
use onlyalpha_domain::{
    enums::{OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    value::{OnlyCurrency, OnlyMoney},
};

#[path = "../../tests/support/memory_run.rs"]
mod fixtures;
#[path = "../../tests/support/memory_signal.rs"]
mod signal_support;

struct Case {
    owner: FiniteSessionOwner,
    venue: MemoryVirtualActor,
    bar: MarketInput,
    binding: Value,
    opening: OpeningInput,
    at: OnlyTimestamp,
    intent: OrderIntent,
    following: Vec<MarketInput>,
}

fn buying(cash: &str) -> Case {
    buying_with_prices(cash, &["1.00", "10.00", "11.00"])
}

fn buying_with_prices(cash: &str, prices: &[&str]) -> Case {
    let setup = fixtures::parts(cash, false, prices, signal_support::executor());
    let spec = setup.spec;
    let cfg = spec.configuration.record();
    let scope = Scope::decode(&json!({"engine":cfg["engine"],"runtime":cfg["runtime"],"account":cfg["account"],"gateway":cfg["gateway"],"generation":cfg["generation"],"runtime_kind":"BACKTEST"})).unwrap();
    let model = NextOpenModel::new(
        &spec.policy_settings,
        setup.policy.binding(),
        spec.initial_ns.into(),
        &spec.cluster,
    )
    .unwrap();
    let session = Session::new(&spec.configuration, &spec.binding).unwrap();
    let mut owner =
        FiniteSessionOwner::new(session, scope.clone(), model, Box::new(setup.policy)).unwrap();
    let balance = OnlyMoney::new(
        cash.parse().unwrap(),
        OnlyCurrency::from_record(&cfg["currency"]).unwrap(),
    )
    .unwrap();
    let mut venue = MemoryVirtualActor::new(
        scope,
        &setup.venue.artifact,
        balance,
        &setup.venue.settings,
        &setup.venue.source,
    )
    .unwrap();
    venue.connect().unwrap();
    venue.authenticate().unwrap();
    let prior = &setup.inputs.records()[0];
    let first = prior.opening();
    venue
        .on_open(
            1,
            first.event_ns().try_into().unwrap(),
            first.instrument_id(),
            first.price(),
        )
        .unwrap();
    venue.on_bar(1, prior.bar()).unwrap();
    let bar = setup.inputs.records()[1].clone();
    let opening = bar.opening();
    venue
        .on_open(
            2,
            opening.event_ns().try_into().unwrap(),
            opening.instrument_id(),
            opening.price(),
        )
        .unwrap();
    let at = OnlyTimestamp::from_unix_nanos(opening.event_ns());
    let (signal, intent) = signal_and_intent(prior, &opening, OnlyOrderSide::Buy);
    owner.prepare_open(&opening, &signal).unwrap();
    let binding = json!({"policy":spec.policy_settings,"program":{"scope":{"cluster":spec.cluster},"revision":{"strategy_fingerprint":setup.executor.program().revision().fingerprint()}},"opening_profile":{"schema_version":1,"kind":"OPEN_CLOSE_V1"}});
    Case {
        owner,
        venue,
        bar,
        binding,
        opening,
        at,
        intent,
        following: setup.inputs.records()[2..].to_vec(),
    }
}

fn signal_and_intent(
    prior: &MarketInput,
    opening: &OpeningInput,
    side: OnlyOrderSide,
) -> (Value, OrderIntent) {
    let decision = json!({"eligibility":true,"entry":side == OnlyOrderSide::Buy,"exit":side == OnlyOrderSide::Sell});
    let cause = crate::session::fingerprint(&decision);
    let signal = json!({"schema_version":1,"side":side.as_str(),"decision":decision,"decision_identity":cause,"source":prior.source(),"source_sequence":prior.sequence(),"signal_input":prior.identity(),"signal_time":prior.event_ns().to_string()});
    let intent = OrderIntent::new(
        opening.instrument_id().clone(),
        side,
        OnlyOrderType::Market,
        "4".parse().unwrap(),
        None,
        OnlyTimeInForce::Gtc,
        &cause,
    )
    .unwrap();
    (signal, intent)
}

fn apply_command(
    owner: &mut FiniteSessionOwner,
    venue: &mut MemoryVirtualActor,
    command: &BrokerCommand,
) {
    venue.dispatch(owner, command).unwrap();
    assert_eq!(venue.publish().unwrap(), 2);
    for fact in venue.pending().to_vec() {
        let original = venue.broker().original().observed(fact.identity()).unwrap();
        owner.apply_observed(&original).unwrap();
        venue.acknowledge(owner, fact.identity()).unwrap();
    }
}

#[test]
fn account_journal_capacity_rejects_without_risk_decision_or_new_facts() {
    let mut case = buying_with_prices("10000.00", &["10.00"; 512]);
    let first = case
        .owner
        .admit(&case.intent, &case.at)
        .unwrap()
        .command
        .unwrap();
    apply_command(&mut case.owner, &mut case.venue, &first);
    case.owner.take_open_result().unwrap();
    let mut prior = case.bar;
    let mut denied_state = None;
    for bar in case.following {
        case.venue.on_bar(prior.sequence(), prior.bar()).unwrap();
        case.owner.valuation(&case.binding, &prior).unwrap();
        case.owner.drain_events().unwrap();
        let opening = bar.opening();
        case.venue
            .on_open(
                bar.sequence(),
                opening.event_ns().try_into().unwrap(),
                opening.instrument_id(),
                opening.price(),
            )
            .unwrap();
        let side = match (bar.sequence() - 2) % 12 {
            11 => Some(OnlyOrderSide::Sell),
            0 => Some(OnlyOrderSide::Buy),
            _ if denied_state.is_some() => Some(OnlyOrderSide::Buy),
            _ => None,
        };
        if let Some(side) = side {
            let (signal, intent) = signal_and_intent(&prior, &opening, side);
            case.owner.prepare_open(&opening, &signal).unwrap();
            let seq = case.owner.session().sequence();
            let before = case.owner.session().state().unwrap();
            let admission = case
                .owner
                .admit(&intent, &OnlyTimestamp::from_unix_nanos(opening.event_ns()))
                .unwrap();
            if let Some(command) = admission.command {
                assert!(denied_state.is_none());
                apply_command(&mut case.owner, &mut case.venue, &command);
                assert_eq!(case.owner.take_open_result().unwrap()["status"], "FILLED");
            } else {
                let open = case.owner.take_open_result().unwrap();
                assert_eq!(open["status"], "REJECTED");
                assert_eq!(open["reason"], "ACCOUNT_JOURNAL_BOUND");
                assert_eq!(open["signal"], signal);
                assert_eq!(open["admission"]["accepted"], true);
                assert!(open.get("risk_denied").is_none());
                assert!(case.owner.drain_events().unwrap().is_empty());
                assert!(case.venue.pending().is_empty());
                assert_eq!(case.owner.session().sequence(), seq);
                assert_eq!(case.owner.session().state().unwrap(), before);
                if let Some(first_rejection) = denied_state {
                    assert_eq!(before, first_rejection);
                    return;
                }
                denied_state = Some(before);
            }
        }
        prior = bar;
    }
    panic!("账户日志应达到准入上限，并在下一次买入时保持拒绝");
}

#[test]
fn opening_gap_rejects_before_creating_an_order_or_dispatching() {
    let mut case = buying("20.00");
    let result = case.owner.admit(&case.intent, &case.at).unwrap();
    assert!(result.command.is_none());
    let open = case.owner.take_open_result().unwrap();
    assert_eq!(open["reason"], "INSUFFICIENT_FUNDS");
    assert_eq!(open["opening"], case.opening.record());
    assert_eq!(case.owner.session().sequence(), 0);
    assert!(
        case.owner.session().position_order_view().unwrap()["orders"]
            .as_object()
            .unwrap()
            .is_empty()
    );
    assert!(case.venue.pending().is_empty());
    assert_eq!(
        case.owner.account(&case.at).unwrap().cash_available(),
        &"20".parse().unwrap()
    );
}

#[test]
fn admit_binds_one_whole_fill_to_this_configuration_policy_order_and_fee_estimate() {
    let mut case = buying("100.00");
    let submit = case
        .owner
        .admit(&case.intent, &case.at)
        .unwrap()
        .command
        .unwrap();
    let events = case.owner.drain_events().unwrap();
    assert_eq!(events.len(), 1);
    let input = &events[0]["input"];
    assert_eq!(input["op"], "ADMIT");
    let payload = &input["payload"];
    let fee = &payload["fee_contract"];
    let policy = crate::session::fingerprint(&case.owner.policy().binding());
    let model = json!({"schema_version":1,"kind":"GUARANTEED_WHOLE_FILL","runtime_kind":"BACKTEST","maximum_fill_count":1,"configuration_fingerprint":case.owner.session().configuration().fingerprint(),"policy_fingerprint":policy});
    let assumptions = fee["estimate"]["assumptions_fingerprint"].as_str().unwrap();
    assert_eq!(payload["schema_version"], 2);
    assert_eq!(
        payload["settlement_fill_contract"],
        json!({"schema_version":1,"kind":"BACKTEST_WHOLE_FILL","maximum_fill_count":1,"model_fingerprint":crate::session::fingerprint(&model),"model":model,"fee_estimate_assumptions_fingerprint":assumptions})
    );
    assert_eq!(case.owner.model().binding()["execution_model"], model);
    assert_eq!(payload["request"]["metadata"]["replay_policy"], policy);
    assert_eq!(fee["binding"]["bound_at"]["unix_nanos"], input["time"]);
    assert_eq!(fee["binding"]["order_id"]["value"], submit.order());
    assert_eq!(
        fee["binding"]["instrument_id"],
        case.opening.instrument_id().to_record()
    );
    assert_eq!(fee["estimate"]["expected"]["binding"], fee["binding"]);
    assert_eq!(fee["estimate"]["maximum"]["binding"], fee["binding"]);
    assert_eq!(
        fee["funding"]["binding_fingerprint"],
        fee["binding"]["fingerprint"]
    );
}

#[test]
fn original_venue_fills_once_and_close_marks_the_economic_account() {
    let mut case = buying("100.00");
    let submit = case
        .owner
        .admit(&case.intent, &case.at)
        .unwrap()
        .command
        .unwrap();
    let mut wrong = submit.record();
    wrong["command_id"] = json!("foreign-submit");
    assert!(
        case.owner
            .simulation_intent(&BrokerCommand::decode(&wrong).unwrap())
            .is_err()
    );
    case.venue.dispatch(&case.owner, &submit).unwrap();
    case.venue.publish().unwrap();
    let facts = case.venue.pending().to_vec();
    assert_eq!(facts.len(), 2);
    for fact in &facts {
        let observed = case
            .venue
            .broker()
            .original()
            .observed(fact.identity())
            .unwrap();
        assert!(case.owner.apply_venue(fact).is_err());
        assert!(case.owner.simulation_receipt(fact).unwrap().is_none());
        case.owner.apply_observed(&observed).unwrap();
        let seq = case.owner.session().sequence();
        case.owner.apply_observed(&observed).unwrap();
        assert_eq!(case.owner.session().sequence(), seq);
        let mut altered = fact.record();
        altered["update_id"] = json!("another-original");
        assert!(
            case.owner
                .simulation_receipt(&Fact::decode(&altered).unwrap())
                .is_err()
        );
        let mut foreign = fact.record();
        foreign["scope"]["account"] = json!("other-account");
        assert!(
            case.owner
                .simulation_receipt(&Fact::decode(&foreign).unwrap())
                .is_err()
        );
        case.venue
            .acknowledge(&case.owner, fact.identity())
            .unwrap();
    }
    assert!(case.venue.pending().is_empty());
    let open = case.owner.take_open_result().unwrap();
    assert_eq!(
        open["venue_facts"],
        json!([facts[0].record(), facts[1].record()])
    );
    let events = case.owner.drain_events().unwrap();
    assert_eq!(
        events
            .iter()
            .map(|v| v["input"]["op"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["ADMIT", "SUBMISSION", "ACCEPT", "FILL"]
    );
    assert_eq!(events[2]["input"]["broker_record"], facts[0].record());
    assert_eq!(events[3]["input"]["broker_record"], facts[1].record());
    let mut changed_bar = case.bar.bar().to_record();
    changed_bar["high"]["value"] = json!("12.00");
    changed_bar["close"]["value"] = json!("12.00");
    let close = MarketInput::new(
        case.bar.source(),
        case.bar.sequence(),
        "recorded",
        onlyalpha_domain::market::OnlyBar::from_record(&changed_bar).unwrap(),
    )
    .unwrap();
    assert_eq!(close.opening().record(), case.opening.record());
    case.venue.on_bar(close.sequence(), close.bar()).unwrap();
    let position = case.owner.session().position_order_view().unwrap();
    let sequence = case.owner.session().sequence() + 1;
    let time = u64::try_from(close.event_ns()).unwrap();
    case.owner.valuation(&case.binding, &close).unwrap();
    let events = case.owner.drain_events().unwrap();
    assert_eq!(events.len(), 1);
    let input = &events[0]["input"];
    assert_eq!(input["op"], "VALUATION");
    assert_eq!(input["time"], time);
    assert_eq!(
        input["payload"],
        json!({"schema_version":1,"valuation":format!("VALUATION-{}",close.identity()),"version":sequence,"position_evidence":position["position_checkpoint_fingerprint"],"economic_version":position["economic_version"],"marks":[{"schema_version":1,"instrument":close.bar().instrument_id().to_string(),"mark":"12.00","source_ref":format!("BAR-{}",close.identity()),"family":"CLOSED_BAR","version":sequence,"time":time,"as_of_sequence":sequence}]})
    );
    assert_eq!(
        case.owner.session().account_snapshot().unwrap()["market_value"],
        "48.00"
    );
    let account = case
        .owner
        .account(&OnlyTimestamp::from_unix_nanos(close.event_ns()))
        .unwrap();
    assert_eq!(account.cash_available(), &"59".parse().unwrap());
    assert_eq!(account.total_equity(), &"107".parse().unwrap());
    assert_eq!(account.positions()[0].quantity(), &"4".parse().unwrap());
}

#[test]
fn close_valuation_stops_when_flat_and_resumes_on_reentry() {
    let fixture = fixtures::parts(
        "100.00",
        false,
        &[
            "1.00", "5.00", "8.00", "1.00", "1.00", "4.00", "1.00", "8.00", "10.00",
        ],
        signal_support::executor(),
    );
    let bars = fixture.inputs.records();
    let expected: Vec<_> = [2, 3, 4, 8]
        .into_iter()
        .map(|i| format!("BAR-{}", bars[i].identity()))
        .collect();
    let run = fixture.run().unwrap();
    let marked: Vec<_> = run
        .execution_facts()
        .iter()
        .filter(|row| row["family"] == "EXECUTION" && row["body"]["input"]["op"] == "VALUATION")
        .map(|row| {
            row["body"]["input"]["payload"]["marks"][0]["source_ref"]
                .as_str()
                .unwrap()
        })
        .collect();
    assert_eq!(marked, expected);
    assert_eq!(run.closed_cycle_count().unwrap(), 1);
    let account = &run.economic_result()["final_account"];
    assert_eq!(account["cash"], "41.00");
    assert_eq!(account["fees"], "3.00");
    assert_eq!(account["market_value"], "40.00");
    assert_eq!(account["unrealized_pnl"], "0.00");
}

#[test]
fn failed_accept_after_submission_ends_the_attempt() {
    let mut case = buying("100.00");
    let command = case
        .owner
        .admit(&case.intent, &case.at)
        .unwrap()
        .command
        .unwrap();
    let session = case.owner.session();
    let mut other_session = Session::new(session.configuration(), session.binding()).unwrap();
    let mut other_admission = session.pending_events().unwrap()[0].input().clone();
    other_admission["input_id"] = json!("other-admission");
    other_session
        .apply(&TradingInput::from_record(other_admission).unwrap())
        .unwrap();

    let mut other_venue = buying("100.00").venue;
    other_venue.dispatch(&other_session, &command).unwrap();
    other_venue.publish().unwrap();
    let wrong = other_venue
        .broker()
        .original()
        .observed(other_venue.pending()[0].identity())
        .unwrap();
    case.venue.dispatch(&case.owner, &command).unwrap();
    case.venue.publish().unwrap();
    let correct = case
        .venue
        .broker()
        .original()
        .observed(case.venue.pending()[0].identity())
        .unwrap();
    assert_eq!(wrong.fact().record(), correct.fact().record());
    assert_ne!(
        wrong.intent().record()["transaction"],
        correct.intent().record()["transaction"]
    );

    assert_eq!(
        case.owner.apply_observed(&wrong).unwrap_err().0,
        "EXECUTION_CASH_OBSERVATION_MISMATCH"
    );
    assert_eq!(case.owner.session().sequence(), 2);
    for observation in [&wrong, &correct] {
        assert_eq!(
            case.owner.apply_observed(observation).unwrap_err().0,
            "FINITE_OBSERVATION_FAILED"
        );
        assert_eq!(case.owner.session().sequence(), 2);
    }
    let events = case.owner.drain_events().unwrap();
    assert_eq!(events.len(), 2);
    assert_eq!(events[0]["input"]["op"], "ADMIT");
    assert_eq!(events[1]["input"]["op"], "SUBMISSION");
    assert!(
        case.owner
            .simulation_receipt(correct.fact())
            .unwrap()
            .is_none()
    );
    assert_eq!(
        case.owner.take_open_result().unwrap_err().0,
        "FINITE_OBSERVATION_FAILED"
    );
    assert!(matches!(case.owner.finish(0, 1), Err(e) if e.0 == "FINITE_OBSERVATION_FAILED"));
}

#[test]
fn incomplete_venue_application_blocks_finish() {
    let mut case = buying("100.00");
    assert!(
        case.owner
            .admit(&case.intent, &OnlyTimestamp::from_unix_nanos(0.into()))
            .is_err()
    );
    assert_eq!(case.owner.session().sequence(), 0);
    case.owner.admit(&case.intent, &case.at).unwrap();
    case.owner.drain_events().unwrap();
    assert!(case.owner.take_open_result().is_err());
    assert!(matches!(case.owner.finish(0,1),Err(e) if e.0=="FINITE_OPEN_INCOMPLETE"));
}
