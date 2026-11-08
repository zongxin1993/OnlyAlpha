//! The real planner's valuation consumer must not build historical Ledger DTOs.
use super::*;
use serde_json::{Value, json};
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../tests/support/mod.rs"]
mod support;
use support::{Harness, config, fill, open, stage};
fn apply(history: &mut Harness, input: &Value) {
    let planned = history.prepare(input).unwrap();
    coordinate(&mut history.store, &mut history.components, &planned).unwrap();
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
fn same_configuration_empty_position_cannot_fund_the_populated_account_and_ledger() {
    use onlyalpha_broker as broker;
    use onlyalpha_domain::base::OnlyDomainModel;
    #[derive(Default)]
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
}
