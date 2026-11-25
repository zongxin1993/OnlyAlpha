use onlyalpha_broker_virtual::MemoryVirtualActor;
use onlyalpha_domain::numeric::OnlyDecimal;
use onlyalpha_execution::MarketSourceCut;
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
use serde_json::{Value, json};
#[allow(dead_code)]
#[path = "support/perpetual_run.rs"]
mod support;
fn prepare(
    close: bool,
    consume_funding: bool,
) -> (Session, MemoryVirtualActor, MarketSourceCut, Value) {
    prepare_controls(close, consume_funding, true, true)
}
fn prepare_controls(
    close: bool,
    consume_funding: bool,
    apply_trades: bool,
    acknowledge: bool,
) -> (Session, MemoryVirtualActor, MarketSourceCut, Value) {
    let (cfg, inputs) = support::scenario();
    let (scope, cash, settings) = support::venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut venue =
        MemoryVirtualActor::new(scope.clone(), &"f".repeat(64), cash, &settings, binding).unwrap();
    venue.connect().unwrap();
    venue.authenticate().unwrap();
    let config = RunConfiguration::from_record(cfg.clone()).unwrap();
    let pins = RunBinding::new(
        &config,
        &support::artifact(),
        &"c".repeat(64),
        &"d".repeat(64),
    )
    .unwrap();
    let mut session = Session::new(&config, &pins).unwrap();
    let cut = MarketSourceCut::read(
        &serde_json::to_vec(&cfg["perpetual"]["source_rows"]).unwrap(),
        cfg["perpetual"]["source_cut_sha256"].as_str().unwrap(),
    )
    .unwrap();
    let funding = inputs
        .iter()
        .find(|v| v["op"] == "FUNDING")
        .unwrap()
        .clone();
    for input in inputs.iter().take(if consume_funding {
        inputs.len()
    } else {
        inputs.len() - 1
    }) {
        if !apply_trades && input["op"] == "FILL" {
            continue;
        }
        let source = if input["op"] == "FUNDING" {
            Some(
                venue
                    .funding_history(
                        onlyalpha_execution::funding_boundary(&input["payload"]["fact"]).unwrap(),
                        input["time"].as_u64().unwrap(),
                    )
                    .unwrap(),
            )
        } else {
            None
        };
        let event = if matches!(
            input["op"].as_str(),
            Some("MARK" | "FUNDING" | "ACCEPT" | "FILL" | "TERMINAL")
        ) {
            session
                .apply_original(
                    &TradingInput::from_record(input.clone()).unwrap(),
                    &cut,
                    venue.broker(),
                    source.as_ref(),
                )
                .unwrap()
        } else {
            session
                .apply(&TradingInput::from_record(input.clone()).unwrap())
                .unwrap()
        };
        session.acknowledge(event.sequence()).unwrap();
        if input["op"] == "ADMIT" {
            let snapshot = session
                .order("cluster", input["payload"]["order"].as_str().unwrap())
                .unwrap();
            let request = &input["payload"]["request"];
            let command=onlyalpha_broker::BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"original-submit","order":input["payload"]["order"],"client":snapshot["client_order_id"]["value"],"request":request})).unwrap();
            let at = input["time"].as_i64().unwrap();
            venue.advance(at).unwrap();
            venue.dispatch(&session, &command).unwrap();
            venue.advance(at).unwrap();
            for (index, fill) in inputs.iter().filter(|v| v["op"] == "FILL").enumerate() {
                let sequence = index as u64 + 1;
                venue
                    .on_bar(
                        sequence,
                        &support::venue_bar(
                            request,
                            sequence,
                            fill["payload"]["broker"]["record"]["ts_event"]
                                .as_i64()
                                .unwrap(),
                        ),
                    )
                    .unwrap();
            }
            venue.publish().unwrap();
            assert_eq!(
                venue
                    .pending()
                    .iter()
                    .map(onlyalpha_broker::Fact::record)
                    .collect::<Vec<_>>(),
                inputs
                    .iter()
                    .filter(|v| matches!(v["op"].as_str(), Some("ACCEPT" | "FILL" | "TERMINAL")))
                    .map(|v| v["payload"]["broker"]["record"].clone())
                    .collect::<Vec<_>>()
            );
            if close {
                let through =
                    onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap();
                venue.advance(i64::try_from(through).unwrap() + 1).unwrap();
            }
        }
        if acknowledge && let Some(id) = input["payload"]["broker"]["id"].as_str() {
            venue.acknowledge(&session, id).unwrap();
        }
    }
    (session, venue, cut, funding)
}
#[test]
fn original_memory_venue_trade_mark_and_funding_preserve_independent_economics() {
    let (session, venue, _, _) = prepare(true, true);
    assert!(venue.pending().is_empty());
    let state = session.state().unwrap();
    let number = |v: &Value| v.as_str().unwrap().parse::<OnlyDecimal>().unwrap();
    assert_eq!(
        number(&state["account"]["snapshot"]["cash"]),
        "19.816".parse().unwrap()
    );
    assert_eq!(
        number(&state["account"]["snapshot"]["equity"]),
        "23.816".parse().unwrap()
    );
    assert_eq!(
        number(&state["account"]["snapshot"]["fees"]),
        "0.06".parse().unwrap()
    );
    assert_eq!(
        number(&state["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"]),
        "-0.124".parse().unwrap()
    );
    let venue = venue.finish().unwrap();
    let records = venue.protocol_records();
    assert_eq!(
        venue.protocol()["events"].as_u64().unwrap() as usize,
        records.len()
    );
    assert!(!records.is_empty());
    for (index, record) in records.iter().enumerate() {
        assert_eq!(record.record()["sequence"], index + 1);
        if index > 0 {
            assert_eq!(
                record.record()["previous"],
                records[index - 1].record()["hash"]
            );
        }
    }
    assert!(!venue.source_trace().is_empty());
    assert_eq!(
        venue.source_trace().last().unwrap().fingerprint(),
        venue.source_fingerprint()
    );
    assert!(
        venue
            .source_trace()
            .iter()
            .any(|step| step.bar_reference().is_some())
    );
    for step in venue.source_trace() {
        let record = step.record();
        if record["action"]["kind"] == "COMMAND" {
            let dispatch = &record["dispatch"]["record"];
            assert!(!record["dispatch"]["admitted_at"].is_null());
            assert!(records.iter().any(|r| r.record() == *dispatch));
            let witness = onlyalpha_broker::digest(&json!([
                dispatch["hash"],
                record["dispatch"]["admitted_at"]
            ]));
            assert_eq!(
                record["protocol"],
                onlyalpha_broker::digest(&json!([witness, record["dispatch"]["outcome"]]))
            );
        }
    }
    let completed = session.finish().unwrap();
    assert_eq!(completed.facts().len(), 7);
}
#[test]
fn incomplete_original_economic_prefix_cannot_pay_funding() {
    let (mut session, venue, cut, funding) = prepare(false, false);
    let boundary = onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap();
    assert!(
        venue
            .funding_history(boundary, funding["time"].as_u64().unwrap())
            .is_err()
    );
    assert!(
        session
            .apply_original(
                &TradingInput::from_record(funding).unwrap(),
                &cut,
                venue.broker(),
                None
            )
            .is_err()
    );
    assert!(session.finish().is_err());
}

#[test]
fn same_original_funding_is_idempotent_but_plain_input_cannot_borrow_its_proof() {
    let (mut session, mut venue, cut, funding) = prepare(true, true);
    assert_eq!(venue.publish().unwrap(), 0);
    let state = session.state().unwrap();
    let prefix = session.sequence();
    let history = venue
        .funding_history(
            onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap(),
            funding["time"].as_u64().unwrap(),
        )
        .unwrap();
    let input = TradingInput::from_record(funding).unwrap();
    assert_eq!(
        session
            .apply_original(&input, &cut, venue.broker(), Some(&history))
            .unwrap()
            .sequence(),
        prefix
    );
    assert_eq!(session.state().unwrap(), state);
    assert_eq!(session.sequence(), prefix);
    assert!(session.apply(&input).is_err());
    assert!(session.finish().is_err());
}
#[test]
fn observed_but_unapplied_trade_and_undrained_broker_never_complete() {
    let (mut session, venue, cut, funding) = prepare_controls(true, false, false, true);
    let history = venue
        .funding_history(
            onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap(),
            funding["time"].as_u64().unwrap(),
        )
        .unwrap();
    let error = session
        .apply_original(
            &TradingInput::from_record(funding).unwrap(),
            &cut,
            venue.broker(),
            Some(&history),
        )
        .unwrap_err();
    assert!(error.0.contains("FUNDING_UNAPPLIED_TRADE"), "{}", error.0);
    assert!(session.finish().is_err());
    assert!(venue.finish().is_err());
    let (_, venue, _, _) = prepare_controls(true, true, true, false);
    assert!(venue.finish().is_err());
}
#[test]
fn another_run_pin_or_admission_cannot_borrow_original_broker_facts() {
    for other_request in [false, true] {
        let (_, venue, cut, _) = prepare(true, true);
        let (cfg, inputs) = support::scenario();
        let configuration = RunConfiguration::from_record(cfg).unwrap();
        let pin = if other_request { 'c' } else { 'b' };
        let binding = RunBinding::new(
            &configuration,
            &support::artifact(),
            &pin.to_string().repeat(64),
            &"d".repeat(64),
        )
        .unwrap();
        let mut session = Session::new(&configuration, &binding).unwrap();
        let mark = TradingInput::from_record(inputs[0].clone()).unwrap();
        let event = session
            .apply_original(&mark, &cut, venue.broker(), None)
            .unwrap();
        session.acknowledge(event.sequence()).unwrap();
        let mut admission = inputs[1].clone();
        if other_request {
            admission["payload"]["request"]["request_id"]["value"] = json!("another-admission");
        }
        let event = session
            .apply(&TradingInput::from_record(admission).unwrap())
            .unwrap();
        session.acknowledge(event.sequence()).unwrap();
        assert!(
            session
                .apply_original(
                    &TradingInput::from_record(inputs[3].clone()).unwrap(),
                    &cut,
                    venue.broker(),
                    None
                )
                .is_err()
        );
        assert!(session.finish().is_err());
    }
}
#[test]
fn memory_venue_refuses_live_and_bar_replay_rejects_changed_aliases() {
    let (cfg, inputs) = support::scenario();
    let (scope, cash, settings) = support::venue_config(&inputs);
    let mut live = scope.record();
    live["runtime_kind"] = json!("LIVE");
    assert!(
        MemoryVirtualActor::new(
            onlyalpha_broker::Scope::decode(&live).unwrap(),
            &"f".repeat(64),
            cash,
            &settings,
            cfg["perpetual"]["execution_source_binding"]
                .as_str()
                .unwrap()
        )
        .is_err()
    );
    let (_, mut venue, _, _) = prepare(true, true);
    let fill = inputs.iter().find(|v| v["op"] == "FILL").unwrap();
    let bar = support::venue_bar(
        &inputs[1]["payload"]["request"],
        1,
        fill["payload"]["broker"]["record"]["ts_event"]
            .as_i64()
            .unwrap(),
    );
    venue.on_bar(1, &bar).unwrap();
    use onlyalpha_domain::base::OnlyDomainModel;
    let mut changed = bar.to_record();
    let price =
        onlyalpha_domain::value::OnlyPrice::new("31".parse().unwrap(), bar.close().precision())
            .unwrap()
            .to_record();
    changed["close"] = price.clone();
    changed["high"] = price;
    let changed = onlyalpha_domain::market::OnlyBar::from_record(&changed).unwrap();
    assert!(venue.on_bar(1, &changed).is_err());
    assert!(venue.finish().is_err());
}

#[test]
fn wrong_cut_original_body_and_source_artifact_are_refused() {
    for changed_market in [false, true] {
        let (mut session, venue, cut, mut funding) = prepare(true, false);
        if changed_market {
            funding["payload"]["fact"]["rate"] = json!("0.002");
        } else {
            funding["payload"]["mark_fact_id"] = json!("foreign-mark");
        }
        let history = venue
            .funding_history(
                onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap(),
                funding["time"].as_u64().unwrap(),
            )
            .unwrap();
        assert!(
            session
                .apply_original(
                    &TradingInput::from_record(funding).unwrap(),
                    &cut,
                    venue.broker(),
                    Some(&history)
                )
                .is_err()
        );
        assert!(session.finish().is_err());
    }
    let (_cfg, inputs) = support::scenario();
    let (scope, cash, settings) = support::venue_config(&inputs);
    let original = onlyalpha_broker_virtual::VirtualBroker::new(
        scope.clone(),
        &"0".repeat(64),
        cash.clone(),
        &settings,
    )
    .unwrap();
    let wrong_binding = onlyalpha_broker::digest(original.source_binding());
    let wrong =
        MemoryVirtualActor::new(scope, &"0".repeat(64), cash, &settings, &wrong_binding).unwrap();
    let (mut session, _, cut, _) = prepare(true, false);
    assert!(
        session
            .apply_original(
                &TradingInput::from_record(inputs[0].clone()).unwrap(),
                &cut,
                wrong.broker(),
                None
            )
            .is_err()
    );
    assert!(session.finish().is_err());
}
