//! The real planner's valuation consumer must not build historical Ledger DTOs.
use super::*;
use crate::support;
use serde_json::{Value, json};
use support::{Harness, config, fill, open, stage};
fn apply(history: &mut Harness, input: &Value) {
    let planned = history.prepare(input).unwrap();
    coordinate(&mut history.store, &mut history.components, &planned).unwrap();
}
#[test]
fn limit_fill_prices_use_the_order_side() {
    use crate::planning::validate_fill_price;
    use bigdecimal::BigDecimal;

    for (side, better, worse) in [("BUY", 99, 101), ("SELL", 101, 99)] {
        let order = json!({"order_type":"LIMIT","side":side,"price":{"value":"100"}});
        let quantity = BigDecimal::from(1);
        for price in [better, 100] {
            validate_fill_price(&order, &BigDecimal::from(price), &quantity).unwrap();
        }
        assert_eq!(
            validate_fill_price(&order, &BigDecimal::from(worse), &quantity)
                .unwrap_err()
                .0,
            "EXECUTION_LIMIT_OR_POSITIVE"
        );
    }
}

#[test]
fn actual_valuation_planning_uses_current_ledger_lines_without_constructing_full_history() {
    for modern in [false, true] {
        let mut configuration = config();
        if modern {
            configuration["schema_version"] = json!(2);
            configuration["account_checkpoint_version"] = json!(5);
        }
        configuration["capitals"] = json!({"cluster":"500.00","second":"500.00"});
        configuration["profiles"]["second"] = configuration["profiles"]["cluster"].clone();
        let mut history = Harness::new(configuration).unwrap();
        for input in [
            open(1, "BUY"),
            stage(2, 1, "UNKNOWN"),
            fill(3, 1, "4", "10.00", "1.00"),
        ] {
            apply(&mut history, &input);
        }
        for n in 4..=6 {
            let before = history.state().unwrap();
            let old_records = history.store.rows.clone();
            let valuation = support::input(
                n,
                "VALUATION",
                json!({"schema_version":1,"valuation":format!("bounded-ledger-view-{n}"),"version":n,
    "position_evidence":digest(history.components.position.checkpoint().unwrap().0.as_slice()),
    "economic_version":before["account"]["snapshot"]["economic_version"],
    "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("bounded-ledger-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
            );
            crate::valuation::FULL_LEDGER_STATE_CAPTURES.with(|count| count.set(0));
            let planned = history.prepare(&valuation).unwrap();
            let captures = crate::valuation::FULL_LEDGER_STATE_CAPTURES.with(std::cell::Cell::get);
            assert_eq!(
                captures, 0,
                "actual valuation planning constructed the complete Ledger timeline/receipts/aliases/entries for account format {modern} at sequence {n}"
            );
            assert_eq!(
                history.store.rows, old_records,
                "planning reads cannot append or acknowledge source"
            );
            coordinate(&mut history.store, &mut history.components, &planned).unwrap();
            let after = history.state().unwrap();
            assert_eq!(
                after["account"]["snapshot"]["cash"],
                before["account"]["snapshot"]["cash"]
            );
            assert_eq!(after["account"]["snapshot"]["market_value"], "48.00");
            assert_eq!(after["position"], before["position"]);
            assert_eq!(
                after["ledger"]["ledgers"]["second"]["snapshot"]["economic_version"],
                0
            );
            assert_eq!(
                after["ledger"]["ledgers"]["second"]["snapshot"]["valuation_version"], n,
                "the empty configured Cluster still consumes the original complete valuation command"
            );
        }
    }
}

#[test]
fn valuation_keeps_ledger_sequences_inside_the_input_range() {
    let sequence = u64::MAX / 64;
    let count = 32;
    let mut configuration = config();
    configuration["capitals"]["cluster"] = json!("38.00");
    for index in 1..count {
        let cluster = format!("cluster-{index:02}");
        configuration["profiles"][&cluster] = configuration["profiles"]["cluster"].clone();
        configuration["capitals"][&cluster] = json!("1.00");
    }
    configuration["initial_cash"] = json!(format!("{}.00", 38 + count - 1));
    let mut history = Harness::new(configuration).unwrap();
    let before = history.state().unwrap();
    let mut valuation = support::input(
        sequence + 1,
        "VALUATION",
        json!({"schema_version":1,"valuation":"last-input-valuation","version":1,
            "position_evidence":digest(history.components.position.checkpoint().unwrap().0.as_slice()),
            "economic_version":before["account"]["snapshot"]["economic_version"],"marks":[]}),
    );
    valuation["time"] = json!(1);
    let error = history.prepare(&valuation).err().unwrap();
    assert_eq!(error.0, "EXECUTION_RUNTIME_SEQUENCE");
    assert_eq!(history.state().unwrap(), before);
    assert!(history.store.rows.is_empty());

    valuation["runtime_sequence"] = json!(sequence);
    apply(&mut history, &valuation);
    let points = history
        .components
        .ledger
        .equity_occurrences()
        .collect::<Vec<_>>();
    assert_eq!(points.len(), count);
    for (ordinal, point) in points.into_iter().enumerate() {
        assert_eq!(
            point["snapshot"]["runtime_sequence"],
            sequence * 64 + ordinal as u64 + 1
        );
    }
}

#[test]
fn same_configuration_empty_position_cannot_fund_the_populated_account_and_ledger() {
    use onlyalpha_broker as broker;
    use onlyalpha_domain::base::OnlyDomainModel;
    #[derive(Clone, Default)]
    struct Journal(Vec<broker::Record>);
    impl broker::Journal for Journal {
        fn records(&self) -> Result<Vec<broker::Record>, broker::Error> {
            Ok(self.0.clone())
        }
        fn append(&mut self, input: &broker::AppendIntent) -> Result<(), broker::Error> {
            self.0.push(broker::Record::new(input));
            Ok(())
        }
    }
    struct Port;
    impl broker::TradingPort for Port {
        fn capabilities(&self) -> broker::Capabilities {
            broker::Capabilities::new(&["SUBMIT_ORDER", "LIMIT_ORDER"]).unwrap()
        }
        fn dispatch(
            &mut self,
            _: &broker::BrokerCommand,
        ) -> Result<broker::DispatchResult, broker::Error> {
            Ok(broker::DispatchResult::Received)
        }
    }
    struct Ready<'a>(&'a Components, &'a support::MemoryStore);
    impl broker::RuntimeReader for Ready<'_> {
        fn ready_intent(
            &self,
            command: &broker::BrokerCommand,
        ) -> Result<broker::ReadyIntent, broker::Error> {
            let unavailable = |_| broker::Error::new("TEST_READY_ORIGINAL_REQUIRED");
            let records = self.0.ready_records(self.1).map_err(unavailable)?;
            let row = records
                .iter()
                .find(|row| {
                    row.prepared().input()["op"] == "ADMIT"
                        && row.prepared().input()["payload"]["order"] == command.order()
                })
                .ok_or_else(|| broker::Error::new("TEST_ADMIT_REQUIRED"))?;
            let input = row.prepared().input();
            let scope = command.scope().record();
            let snapshot = self
                .0
                .order_snapshot(self.1, "cluster", command.order())
                .map_err(unavailable)?
                .to_record();
            if command.operation() != broker::Operation::Submit
                || [
                    "engine",
                    "runtime",
                    "gateway",
                    "account",
                    "generation",
                    "runtime_kind",
                ]
                .iter()
                .any(|key| scope[*key] != input[*key])
                || input["payload"]["request"] != command.record()["request"]
                || snapshot["client_order_id"]["value"] != command.client()
                || snapshot["status"] != "SUBMITTED"
                || self
                    .0
                    .order_submission(self.1, "cluster", command.order())
                    .map_err(unavailable)?
                    != "DISPATCHING"
            {
                return Err(broker::Error::new("TEST_READY_ORIGINAL_REQUIRED"));
            }
            broker::ReadyIntent::new(
                command.clone(),
                row.prepared().id().into(),
                row.prepared().record()["payload_hash"]
                    .as_str()
                    .unwrap()
                    .into(),
            )
        }
        fn application_receipt(
            &self,
            _: &broker::Fact,
        ) -> Result<Option<broker::ApplicationReceipt>, broker::Error> {
            Ok(None)
        }
        fn order_view(
            &self,
            _: &broker::BrokerCommand,
        ) -> Result<Option<broker::OrderView>, broker::Error> {
            Ok(None)
        }
    }
    let sample: Value = serde_json::from_str(include_str!(
        "../../../../test-data/execution/linear-perpetual.json"
    ))
    .unwrap();
    let mut config = sample["config"].clone();
    let inputs = sample["inputs"].as_array().unwrap();
    let mut rows = Vec::new();
    for input in inputs.iter().filter(|v| v["op"] == "MARK") {
        let mark = &input["payload"]["fact"];
        let funding = inputs
            .iter()
            .find(|v| v["op"] == "FUNDING" && v["payload"]["mark_fact_id"] == mark["fact_id"]);
        let mut raw = json!({"at":mark["ts_event"],"price":mark["value"]["value"]});
        let mut facts = vec![mark.clone()];
        if let Some(funding) = funding {
            raw["rate"] = funding["payload"]["fact"]["rate"].clone();
            facts.push(funding["payload"]["fact"].clone());
        }
        let raw = raw.to_string();
        rows.push(json!({"raw_sha256":digest(raw.as_bytes()),"raw":raw,"facts":facts}));
    }
    let bytes = serde_json::to_vec(&rows).unwrap();
    let source = digest(&bytes);
    config["perpetual"]["source_rows"] = json!(rows);
    config["perpetual"]["source_cut_sha256"] = json!(source);
    let cut = crate::MarketSourceCut::read(&bytes, &source).unwrap();
    let scope = broker::Scope::decode(&inputs[3]["payload"]["broker"]["record"]["scope"]).unwrap();
    let source_binding = json!({"scope": scope.record()});
    let source_hash = broker::digest(&source_binding);
    config["perpetual"]["execution_source_binding"] = json!(source_hash);
    let terminal = |kind: &str, sequence: u64, venue: &Value| {
        let mut record = inputs[3]["payload"]["broker"]["record"].clone();
        let ts_init = record["ts_init"].as_u64().unwrap() + 1;
        record["ts_init"] = json!(ts_init);
        record["kind"] = json!(kind);
        record["update_id"] = json!("virtual-update-00000003");
        record["source_sequence"] = json!(sequence);
        record["payload"]["venue"] = venue.clone();
        record["payload"]["reason"] = json!(if kind == "REJECTED" {
            "venue rejected the order"
        } else {
            ""
        });
        let fact = broker::Fact::decode(&record).unwrap();
        let mut input = inputs[3].clone();
        input["op"] = json!("TERMINAL");
        input["time"] = json!(ts_init + 1);
        input["runtime_sequence"] = json!(5);
        input["input_id"] = json!("finite-terminal");
        input["source_ref"] = json!("finite-terminal");
        input["payload"]["broker"] =
            json!({"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":record});
        (input, fact)
    };
    let venue = &inputs[3]["payload"]["broker"]["record"]["payload"]["venue"];
    let wrong_venue = terminal("REJECTED", 3, &Value::Null);
    let expired = terminal("EXPIRED", 3, venue);
    let stale = terminal("REJECTED", 0, venue);
    let repeated_sequence = terminal("REJECTED", 1, venue);
    let mut journal = Journal::default();
    let mut protocol = broker::Broker::recover(scope.clone(), &journal, 512).unwrap();
    protocol.set_connection(broker::Connection::Ready);
    protocol.set_health(true, true, true);
    let mut history = Harness::new(config).unwrap();
    for input in &inputs[..6] {
        let prepared = history
            .components
            .prepare_perpetual(&history.store, input, &cut, &protocol)
            .unwrap();
        coordinate(&mut history.store, &mut history.components, &prepared).unwrap();
        if input["op"] == "ADMIT" {
            let snapshot = history
                .components
                .order_snapshot(
                    &history.store,
                    "cluster",
                    input["payload"]["order"].as_str().unwrap(),
                )
                .unwrap()
                .to_record();
            let command = broker::BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"original-submit","order":input["payload"]["order"],"client":snapshot["client_order_id"]["value"],"request":input["payload"]["request"]})).unwrap();
            protocol
                .dispatch(
                    &mut journal,
                    &Ready(&history.components, &history.store),
                    &mut Port,
                    &command,
                )
                .unwrap();
            protocol
                .ingest(
                    &mut journal,
                    &[
                        broker::Fact::decode(&inputs[3]["payload"]["broker"]["record"]).unwrap(),
                        broker::Fact::decode(&inputs[4]["payload"]["broker"]["record"]).unwrap(),
                    ],
                )
                .unwrap();
        }
        let refusals: &[(&(Value, broker::Fact), &str)] = match input["op"].as_str() {
            Some("SUBMISSION") => &[(&expired, "EXECUTION_ORDER_NOT_APPLIED")],
            Some("ACCEPT") => &[
                (&wrong_venue, "EXECUTION_BROKER_VENUE"),
                (&stale, "EXECUTION_ORDER_NOT_APPLIED"),
                (&repeated_sequence, "EXECUTION_ORDER_NOT_APPLIED"),
            ],
            _ => &[],
        };
        for ((terminal, fact), code) in refusals {
            let before = history.state().unwrap();
            let stored = history.store.rows.clone();
            let mut rejected_journal = journal.clone();
            let mut rejected_broker =
                broker::Broker::recover(scope.clone(), &rejected_journal, 512).unwrap();
            rejected_broker
                .ingest(&mut rejected_journal, std::slice::from_ref(fact))
                .unwrap();
            let error = history
                .components
                .prepare_perpetual(&history.store, terminal, &cut, &rejected_broker)
                .err()
                .unwrap();
            assert_eq!(error.0, *code);
            assert_eq!(history.state().unwrap(), before);
            assert_eq!(history.store.rows, stored);
        }
    }
    // 使用当前 Components 的正式只读配置重新构造其真实 genesis owners，
    // 不从测试猜测的 checkpoint 子路径重建 Position 配置。
    let mut genesis = Components::new(history.components.configuration().clone()).unwrap();
    let reference = json!({"schema_version":1,"mark":inputs[6]["payload"]["mark_fact_id"],"funding":inputs[6]["payload"]["fact"]["fact_id"]});
    let empty_effect = genesis.position.funding(&cut, &reference).unwrap();
    assert_eq!(
        empty_effect.record()["amount"]
            .as_str()
            .unwrap()
            .parse::<bigdecimal::BigDecimal>()
            .unwrap(),
        "0".parse::<bigdecimal::BigDecimal>().unwrap()
    );
    let current_effect = history
        .components
        .position
        .funding(&cut, &reference)
        .unwrap();
    assert_eq!(
        empty_effect.record()["cashflow"],
        current_effect.record()["cashflow"]
    );
    assert_eq!(
        empty_effect.position_configuration(),
        current_effect.position_configuration()
    );
    let trade_ids = vec![
        inputs[4]["payload"]["broker"]["record"]["payload"]["fill"]["trade_id"]["value"]
            .as_str()
            .unwrap()
            .to_owned(),
    ];
    let replayed = history
        .components
        .position
        .funding_at_trade_prefix(&cut, &reference, &trade_ids)
        .unwrap();
    assert_eq!(replayed.account_lineage(), current_effect.account_lineage());
    assert_eq!(replayed.ledger_lineage(), current_effect.ledger_lineage());
    assert!(
        history
            .components
            .position
            .funding_at_trade_prefix(&cut, &reference, &["unknown-trade".into()])
            .is_err()
    );
    assert!(
        history
            .components
            .position
            .funding_at_trade_prefix(
                &cut,
                &reference,
                &[trade_ids[0].clone(), trade_ids[0].clone()]
            )
            .is_err()
    );
    let account_input = history
        .components
        .command(&inputs[6], "ECONOMIC", Value::Null, 0);
    let ledger_input = history
        .components
        .ledger_command(&inputs[6], "FUNDING", Value::Null, 0);
    let mut account = (*history.components.account).clone();
    let mut ledger = (*history.components.ledger).clone();
    let account_before = account.checkpoint().unwrap();
    let ledger_before = ledger.checkpoint().unwrap();
    let account_rejected = account
        .apply_funding(&account_input, &empty_effect)
        .is_err();
    let ledger_rejected = ledger.apply_funding(&ledger_input, &empty_effect).is_err();
    let account_unchanged = account.checkpoint().unwrap() == account_before;
    let ledger_unchanged = ledger.checkpoint().unwrap() == ledger_before;
    let mut good_account = (*history.components.account).clone();
    let mut good_ledger = (*history.components.ledger).clone();
    good_account
        .apply_funding(&account_input, &current_effect)
        .unwrap();
    good_ledger
        .apply_funding(&ledger_input, &current_effect)
        .unwrap();
    let account_checkpoint = good_account.checkpoint().unwrap();
    let ledger_checkpoint = good_ledger.checkpoint().unwrap();
    good_account
        .apply_funding(&account_input, &current_effect)
        .unwrap();
    good_ledger
        .apply_funding(&ledger_input, &current_effect)
        .unwrap();
    assert_eq!(good_account.checkpoint().unwrap(), account_checkpoint);
    assert_eq!(good_ledger.checkpoint().unwrap(), ledger_checkpoint);
    std::sync::Arc::make_mut(&mut genesis.account)
        .restore_with_funding(
            &account_checkpoint.0,
            &account_checkpoint.1,
            &history.components.position,
            &cut,
        )
        .unwrap();
    std::sync::Arc::make_mut(&mut genesis.ledger)
        .restore_with_funding(
            &ledger_checkpoint.0,
            &ledger_checkpoint.1,
            &history.components.position,
            &cut,
        )
        .unwrap();
    assert_eq!(genesis.account.checkpoint().unwrap(), account_checkpoint);
    assert_eq!(genesis.ledger.checkpoint().unwrap(), ledger_checkpoint);
    assert!(
        account_rejected && account_unchanged && ledger_rejected && ledger_unchanged,
        "stale Position effect: Account rejected={account_rejected}/unchanged={account_unchanged}; Ledger rejected={ledger_rejected}/unchanged={ledger_unchanged}"
    );

    struct FiniteReader<'a>(&'a crate::WorkingState);
    impl broker::FiniteRuntimeReader for FiniteReader<'_> {
        fn simulation_intent(
            &self,
            command: &broker::BrokerCommand,
        ) -> Result<broker::SimulationIntent, broker::Error> {
            let admission = self.0.admission(command.order()).unwrap();
            broker::SimulationIntent::new(
                command.clone(),
                admission.transaction().into(),
                admission.payload_fingerprint().into(),
                &admission.input()["time"],
            )
        }
        fn simulation_receipt(
            &self,
            _: &broker::Fact,
        ) -> Result<Option<broker::ApplicationReceipt>, broker::Error> {
            Ok(None)
        }
        fn simulation_order(
            &self,
            _: &broker::BrokerCommand,
        ) -> Result<Option<broker::OrderView>, broker::Error> {
            Ok(None)
        }
    }

    let config = history.components.configuration().clone();
    let fund_at = crate::funding_boundary(&inputs[6]["payload"]["fact"]).unwrap();
    let fund_visible = inputs[6]["time"].as_u64().unwrap();
    use broker::source::{SourceHistory, SourceStep, source_fact_link, source_step_digest};
    let mut source = SourceHistory::new(
        scope.clone(),
        &source_binding,
        &source_hash,
        Some((fund_at, fund_visible)),
    )
    .unwrap();
    let trade = broker::Fact::decode(&inputs[4]["payload"]["broker"]["record"]).unwrap();
    let fill_at = &inputs[4]["time"];
    let clock = json!(["CLOCK", fill_at]);
    let output = source_fact_link("", &trade, fill_at);
    let step_hash = source_step_digest(&source_hash, 1, &clock, 1, &output, None);
    source
        .accept_step(
            SourceStep {
                sequence: 1,
                previous: &source_hash,
                input: &clock,
                fact_count: 1,
                hash: &step_hash,
                protocol_hash: None,
            },
            [Ok((trade.clone(), fill_at.clone()))],
        )
        .unwrap();
    source.observe(&trade).unwrap();
    let clock = json!(["CLOCK", fund_visible]);
    let closure_hash = source_step_digest(&step_hash, 2, &clock, 0, "", None);
    source
        .accept_step(
            SourceStep {
                sequence: 2,
                previous: &step_hash,
                input: &clock,
                fact_count: 0,
                hash: &closure_hash,
                protocol_hash: None,
            },
            std::iter::empty(),
        )
        .unwrap();
    let mut late_admission = inputs[1].clone();
    late_admission["runtime_sequence"] = json!(9);
    late_admission["time"] = json!(fund_at);
    late_admission["input_id"] = json!("late-admission");
    late_admission["source_ref"] = json!("late-admission");
    late_admission["payload"]["order"] = json!("runtime-ORDER-000002");
    late_admission["payload"]["request"]["request_id"]["value"] = json!("late-open");
    let mut wrong_policy = late_admission.clone();
    wrong_policy["payload"]["policy_fingerprint"] = json!("1".repeat(64));
    let mut off_tick = late_admission.clone();
    off_tick["payload"]["request"]["price"] =
        json!({"schema_version":1,"precision":3,"value":"30.001"});
    let assert_production_refusal = |history: &Harness, input: &Value, code: &str| {
        let before = history.state().unwrap();
        let error = history
            .components
            .prepare(&history.store, input)
            .err()
            .unwrap();
        assert_eq!(error.0, code);
        assert_eq!(history.state().unwrap(), before);
    };
    let mut empty = Harness::new(config.clone()).unwrap();
    assert_production_refusal(&empty, &inputs[1], "EXECUTION_MARK_UNAVAILABLE");
    assert!(empty.store.rows.is_empty());
    let mark = empty
        .components
        .prepare_perpetual(&empty.store, &inputs[0], &cut, &protocol)
        .unwrap();
    coordinate(&mut empty.store, &mut empty.components, &mark).unwrap();
    let mut hedged = inputs[1].clone();
    hedged["payload"]["request"]["execution_intent"]["position_mode"] = json!("HEDGING");
    let mut wrong_precision = inputs[1].clone();
    wrong_precision["payload"]["request"]["price"] =
        json!({"schema_version":1,"precision":3,"value":"30.000"});
    let invalid_requests = [
        (hedged, "EXECUTION_UNSUPPORTED_SHAPE"),
        (wrong_precision, "EXECUTION_INSTRUMENT_PRECISION"),
    ];
    let marked_records = empty.store.rows.clone();
    for (input, code) in &invalid_requests {
        assert_production_refusal(&empty, input, code);
    }
    assert_eq!(empty.store.rows, marked_records);
    let stored = history.store.rows.clone();
    assert_production_refusal(&history, &wrong_policy, "EXECUTION_PERPETUAL_ORDER_SHAPE");
    assert_production_refusal(&history, &off_tick, "EXECUTION_MARKET_LIMIT_RULES");
    assert_eq!(history.store.rows, stored);
    let mut broker = broker::MemoryBroker::new(scope, &source_binding, &source_hash, 512).unwrap();
    broker.set_connection(onlyalpha_broker::Connection::Ready);
    broker.set_health(true, true, true);
    let kernel = "a".repeat(64);
    let pin = "b".repeat(64);
    let binding = json!({"configuration":digest(config.to_string().as_bytes()),"kernel_artifact":kernel,"input_pin":pin});
    let mut finite = crate::WorkingState::for_run(config.clone(), &pin).unwrap();
    let mut finite_inputs = inputs[..6].to_vec();
    let mut duplicate = finite_inputs[4].clone();
    duplicate["runtime_sequence"] = json!(7);
    duplicate["time"] = finite_inputs[5]["time"].clone();
    duplicate["input_id"] = json!("duplicate-finite-fill");
    duplicate["source_ref"] = json!("duplicate-finite-fill");
    finite_inputs.push(duplicate);
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(8);
    finite_inputs.push(funding);
    let apply_finite_input =
        |run: &mut crate::WorkingState, input: &Value, broker: &broker::MemoryBroker| {
            if matches!(
                input["op"].as_str(),
                Some("MARK" | "ACCEPT" | "FILL" | "FUNDING")
            ) {
                let evidence = run
                    .check_original_input(input, &cut, broker, Some(&source))
                    .unwrap();
                run.apply_verified(input, evidence).unwrap();
            } else {
                run.apply(input).unwrap();
            }
        };
    for input in &finite_inputs {
        apply_finite_input(&mut finite, input, &broker);
        if input["op"] == "ADMIT" {
            let original = protocol
                .observed(inputs[3]["payload"]["broker"]["id"].as_str().unwrap())
                .unwrap();
            let command =
                onlyalpha_broker::BrokerCommand::decode(&original.intent().record()["command"])
                    .unwrap();
            broker
                .dispatch(&FiniteReader(&finite), &mut Port, &command)
                .unwrap();
            broker
                .ingest(&[
                    onlyalpha_broker::Fact::decode(&inputs[3]["payload"]["broker"]["record"])
                        .unwrap(),
                    onlyalpha_broker::Fact::decode(&inputs[4]["payload"]["broker"]["record"])
                        .unwrap(),
                ])
                .unwrap();
        }
    }
    let mut settled_run = crate::WorkingState::for_run(config.clone(), &pin).unwrap();
    for input in &finite_inputs {
        apply_finite_input(&mut settled_run, input, &broker);
    }
    let last_sequence = settled_run.sequence();
    let error = settled_run.apply(&late_admission).unwrap_err();
    assert_eq!(error.0, "EXECUTION_ADMISSION_AT_SETTLED_BOUNDARY");
    assert_eq!(settled_run.sequence(), last_sequence);

    let initial_ns = finite_inputs[0]["time"].as_i64().unwrap();
    let final_ns = finite_inputs.last().unwrap()["time"].as_i64().unwrap();
    let completed = finite
        .finish(&finite_inputs, &binding, initial_ns, final_ns)
        .unwrap();
    let verified = crate::verify_finite_backtest_result(
        completed.result(),
        completed.account_checkpoint(),
        &config,
        &kernel,
        &pin,
        initial_ns,
        final_ns,
    )
    .unwrap();
    assert_eq!(completed.result()["execution"]["trade_count"], 1);
    assert_eq!(
        completed.result()["account_equity_timeline"]
            .as_array()
            .unwrap()
            .last()
            .unwrap()["source"],
        "ECONOMIC"
    );
    assert_eq!(verified.equity_points(), completed.equity_points());
    assert_eq!(verified.closed_cycles()["cluster"], 0);

    let mut restricted = config.clone();
    restricted["profiles"]["cluster"]["rules"] = json!([
        {"schema_version":1,"id":"one-contract","scope":"CLUSTER","order":1,"mode":"ENFORCING","kind":"MAX_ORDER_QUANTITY","limit":"1"}
    ]);
    let mut restricted_run = crate::WorkingState::for_run(restricted.clone(), &pin).unwrap();
    apply_finite_input(&mut restricted_run, &inputs[0], &broker);
    assert_eq!(
        restricted_run.apply(&inputs[1]).unwrap_err().0,
        "EXECUTION_RISK_DENIED",
    );
    assert_eq!(restricted_run.sequence(), 1);

    let mut restricted_result = completed.result().clone();
    let restricted_fingerprint = crate::model::hash(&restricted);
    restricted_result["scope"] = restricted.clone();
    restricted_result["manifest"]["configuration"] = json!(restricted_fingerprint);
    restricted_result["source"]["configuration"] = json!(restricted_fingerprint);
    restricted_result["reconciliation"]["source"] = restricted_result["source"].clone();
    let rejected = crate::verify_finite_backtest_result(
        &restricted_result,
        completed.account_checkpoint(),
        &restricted,
        &kernel,
        &pin,
        initial_ns,
        final_ns,
    );
    assert_eq!(
        rejected.err().map(|error| error.0).as_deref(),
        Some("EXECUTION_RISK_DENIED")
    );

    let reseal_inputs = |result: &mut Value| {
        let (inputs, causes): (Vec<_>, Vec<_>) = result["facts"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .enumerate()
            .map(|(index, fact)| {
                let input = fact["input"].clone();
                let cause = crate::model::hash(&input);
                fact["sequence"] = json!(index + 1);
                fact["transaction"] = json!(format!("ETX-{cause}"));
                (input, cause)
            })
            .unzip();
        result["manifest"]["inputs"] = json!(causes);
        result["source"]["inputs"] = json!(digest(&serde_json::to_vec(&inputs).unwrap()));
        result["source"]["rows"] = json!(inputs.len());
        result["closure"]["observed"] = json!(inputs.len());
        result["closure"]["expected"] = json!(inputs.len());
        result["execution"]["transaction_count"] = json!(inputs.len());
        result["reconciliation"]["source"] = result["source"].clone();
    };
    let assert_refusal = |result: &Value, checkpoint: &Value, last: i64, code: &str| {
        let error = crate::verify_finite_backtest_result(
            result, checkpoint, &config, &kernel, &pin, initial_ns, last,
        )
        .err()
        .unwrap();
        assert_eq!(error.0, code);
    };
    for (input, code) in [
        (wrong_policy, "EXECUTION_PERPETUAL_ORDER_SHAPE"),
        (off_tick, "EXECUTION_MARKET_LIMIT_RULES"),
    ] {
        let mut changed = completed.result().clone();
        changed["facts"][1]["input"]["payload"]["policy_fingerprint"] =
            input["payload"]["policy_fingerprint"].clone();
        changed["facts"][1]["input"]["payload"]["request"] =
            inputs[1]["payload"]["request"].clone();
        changed["facts"][1]["input"]["payload"]["request"]["price"] =
            input["payload"]["request"]["price"].clone();
        reseal_inputs(&mut changed);
        assert_refusal(&changed, completed.account_checkpoint(), final_ns, code);
    }
    let mut changed = completed.result().clone();
    let facts = changed["facts"].as_array_mut().unwrap();
    facts.push(json!({"sequence":facts.len()+1,"transaction":null,"input":late_admission}));
    reseal_inputs(&mut changed);
    assert_refusal(
        &changed,
        completed.account_checkpoint(),
        final_ns,
        "EXECUTION_ADMISSION_AT_SETTLED_BOUNDARY",
    );

    let (original_terminal, terminal_fact) = terminal("REJECTED", 3, venue);
    broker.ingest(&[terminal_fact]).unwrap();
    for accepted in [false, true] {
        let mut terminal_run = crate::WorkingState::for_run(config.clone(), &pin).unwrap();
        let mut terminal_inputs = inputs[..if accepted { 4 } else { 3 }].to_vec();
        terminal_inputs.push(original_terminal.clone());
        for input in &terminal_inputs {
            if matches!(input["op"].as_str(), Some("MARK" | "ACCEPT" | "TERMINAL")) {
                let evidence = terminal_run
                    .check_original_input(input, &cut, &broker, None)
                    .unwrap();
                terminal_run.apply_verified(input, evidence).unwrap();
            } else {
                terminal_run.apply(input).unwrap();
            }
        }
        let terminal_result = terminal_run
            .finish(&terminal_inputs, &binding, initial_ns, final_ns)
            .unwrap();
        crate::verify_finite_backtest_result(
            terminal_result.result(),
            terminal_result.account_checkpoint(),
            &config,
            &kernel,
            &pin,
            initial_ns,
            final_ns,
        )
        .unwrap();
        assert_eq!(
            terminal_result.result()["orders"][0]["snapshot"]["status"],
            "REJECTED"
        );

        if !accepted {
            let mut changed = terminal_result.result().clone();
            changed["facts"].as_array_mut().unwrap().remove(0);
            reseal_inputs(&mut changed);
            assert_refusal(
                &changed,
                terminal_result.account_checkpoint(),
                final_ns,
                "EXECUTION_MARK_UNAVAILABLE",
            );

            for (input, code) in &invalid_requests {
                let mut changed = terminal_result.result().clone();
                changed["facts"][1]["input"] = input.clone();
                let request = &input["payload"]["request"];
                changed["orders"][0]["creation"]["request"] = request.clone();
                changed["orders"][0]["creation"]["cause"] = json!(crate::model::hash(input));
                changed["orders"][0]["snapshot"]["execution_intent"] =
                    request["execution_intent"].clone();
                changed["orders"][0]["snapshot"]["price"] = request["price"].clone();
                reseal_inputs(&mut changed);
                assert_refusal(
                    &changed,
                    terminal_result.account_checkpoint(),
                    final_ns,
                    code,
                );
            }
        }

        let mut changed = terminal_result.result().clone();
        changed["orders"][0]["snapshot"]["rejection"]["message"] =
            json!("different rejection reason");
        assert_refusal(
            &changed,
            terminal_result.account_checkpoint(),
            final_ns,
            "RESULT_FINITE_ORDER_SNAPSHOT",
        );
        let mut changed = terminal_result.result().clone();
        changed["orders"][0]["snapshot"]["rejected_at"]["unix_nanos"] =
            original_terminal["payload"]["broker"]["record"]["ts_event"].clone();
        assert_refusal(
            &changed,
            terminal_result.account_checkpoint(),
            final_ns,
            "RESULT_FINITE_ORDER_SNAPSHOT",
        );
        let refusals: &[(&(Value, broker::Fact), &str)] = if accepted {
            &[
                (&wrong_venue, "EXECUTION_BROKER_VENUE"),
                (&stale, "EXECUTION_ORDER_NOT_APPLIED"),
                (&repeated_sequence, "EXECUTION_ORDER_NOT_APPLIED"),
            ]
        } else {
            &[(&expired, "EXECUTION_ORDER_NOT_APPLIED")]
        };
        for ((terminal, _), code) in refusals {
            let mut changed = terminal_result.result().clone();
            changed["facts"].as_array_mut().unwrap().last_mut().unwrap()["input"] =
                terminal.clone();
            if !accepted {
                let snapshot = &mut changed["orders"][0]["snapshot"];
                snapshot["status"] = json!("EXPIRED");
                snapshot["expired_at"] = snapshot["rejected_at"].take();
                snapshot["rejection"] = Value::Null;
            }
            reseal_inputs(&mut changed);
            assert_refusal(
                &changed,
                terminal_result.account_checkpoint(),
                final_ns,
                code,
            );
        }
    }

    let mark_cause = crate::model::hash(&inputs[5]);
    let fill_cause = crate::model::hash(&inputs[4]);
    let margin_count = |cause: &str| {
        completed.result()["account_equity_timeline"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|point| {
                point["source"] == "MARGIN" && point["provenance"]["upstream_cause"] == cause
            })
            .count()
    };
    assert_eq!(margin_count(&mark_cause), 1);
    assert_eq!(margin_count(&fill_cause), 2);
    assert_eq!(margin_count(&crate::model::hash(&inputs[0])), 0);

    let mut missing_margin = completed.result().clone();
    let performance = &mut missing_margin["runtime_performance"];
    let timeline = performance["timeline"].as_array_mut().unwrap();
    let index = timeline
        .iter()
        .position(|point| {
            point["source"] == "MARGIN" && point["provenance"]["upstream_cause"] == mark_cause
        })
        .unwrap();
    timeline.remove(index);
    for (sequence, point) in timeline.iter_mut().enumerate().skip(index) {
        point["sequence"] = json!(sequence);
        point["account_sequence"] = json!(sequence);
        point["snapshot"]["sequence"] = json!(sequence);
    }
    performance["summary"]["valuation_count"] = json!(timeline.len());
    missing_margin["final_account"] =
        performance["timeline"].as_array().unwrap().last().unwrap()["snapshot"].clone();
    let performance = &mut missing_margin["runtime_performance"];
    performance.as_object_mut().unwrap().remove("id");
    performance["id"] = json!(format!("AP-{}", crate::model::hash(performance)));
    missing_margin["account_equity_timeline"] = performance["timeline"].clone();
    let error = crate::verify_finite_backtest_result(
        &missing_margin,
        completed.account_checkpoint(),
        &config,
        &kernel,
        &pin,
        initial_ns,
        final_ns,
    )
    .err()
    .unwrap();
    assert_eq!(error.0, "RESULT_FINITE_ACCOUNT_OCCURRENCES");

    let mut changed_margin = completed.result().clone();
    let performance = &mut changed_margin["runtime_performance"];
    let point = performance["timeline"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|point| {
            point["source"] == "MARGIN" && point["provenance"]["upstream_cause"] == mark_cause
        })
        .unwrap();
    let confirmed = &mut point["snapshot"]["last_confirmed_maintenance"];
    assert!(
        confirmed["amount"]
            .as_str()
            .is_some_and(|amount| amount != "0.00000000")
    );
    confirmed["amount"] = json!("0.00000000");
    performance.as_object_mut().unwrap().remove("id");
    performance["id"] = json!(format!("AP-{}", crate::model::hash(performance)));
    changed_margin["account_equity_timeline"] = performance["timeline"].clone();
    let error = crate::verify_finite_backtest_result(
        &changed_margin,
        completed.account_checkpoint(),
        &config,
        &kernel,
        &pin,
        initial_ns,
        final_ns,
    )
    .err()
    .unwrap();
    assert_eq!(error.0, "RESULT_FINITE_ACCOUNT_PERFORMANCE");

    let funding_cause = crate::model::hash(finite_inputs.last().unwrap());
    let mut changed = completed.result().clone();
    let point = changed["cluster_equity_timelines"][0]["points"]
        .as_array_mut()
        .unwrap()
        .iter_mut()
        .find(|entry| entry["point"]["cause"] == funding_cause)
        .unwrap();
    let cash = &mut point["point"]["snapshot"]["cash"];
    assert!(cash.is_string());
    assert_ne!(*cash, "123.00");
    *cash = json!("123.00");
    let error = crate::verify_finite_backtest_result(
        &changed,
        completed.account_checkpoint(),
        &config,
        &kernel,
        &pin,
        initial_ns,
        final_ns,
    )
    .err()
    .unwrap();
    assert_eq!(error.0, "RESULT_FINITE_LEDGER_SNAPSHOT");

    let mut changed = completed.result().clone();
    let funding = changed["facts"].as_array_mut().unwrap().last_mut().unwrap();
    funding["input"]["payload"]["mark_fact_id"] = inputs[0]["payload"]["fact"]["fact_id"].clone();
    funding["transaction"] = json!(format!("ETX-{}", crate::model::hash(&funding["input"])));
    let error = crate::verify_finite_backtest_result(
        &changed,
        completed.account_checkpoint(),
        &config,
        &kernel,
        &pin,
        initial_ns,
        final_ns,
    )
    .err()
    .unwrap();
    assert_eq!(error.0, "EXECUTION_FUNDING_MARK_PAIR");
}
