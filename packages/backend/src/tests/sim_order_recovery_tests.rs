use super::sim_orders::recover_original_orders;
use crate::persistence::sim_venue::with_memory_log;
use onlyalpha_broker::{
    ApplicationReceipt, BrokerCommand, CommandState, Connection, Error, Fact, OrderView,
    ReadyIntent, RuntimeReader, Scope,
};
use onlyalpha_domain::{base::OnlyDomainModel, value::OnlyMoney};
use onlyalpha_runtime::{RunConfiguration, durability::TradingBinding};
use serde_json::{Value, json};

struct OriginalAdmission(ReadyIntent);

impl RuntimeReader for OriginalAdmission {
    fn ready_intent(&self, command: &BrokerCommand) -> Result<ReadyIntent, Error> {
        assert_eq!(command.record(), self.0.record()["command"]);
        Ok(self.0.clone())
    }

    fn application_receipt(&self, _: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        Ok(None)
    }

    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        Ok(None)
    }
}

struct LostResult {
    binding: TradingBinding,
    cash: OnlyMoney,
    command: BrokerCommand,
    documents: Vec<Value>,
    result: Value,
}

impl LostResult {
    fn after_venue_command() -> Self {
        Self::with_time_in_force("DAY", "RECEIVED")
    }

    fn with_time_in_force(policy: &str, expected: &str) -> Self {
        let scope = Scope::decode(&json!({
            "engine":"engine", "runtime":"runtime", "gateway":"gateway", "account":"account",
            "generation":"a".repeat(64), "runtime_kind":"SIM"
        })).unwrap();
        let currency = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
        let cash = OnlyMoney::from_record(&json!({"schema_version":1,"amount":"1000.00","currency":currency})).unwrap();
        let mut config = scope.record();
        config.as_object_mut().unwrap().extend(json!({
            "schema_version":1, "currency":currency, "initial_cash":"1000.00", "capitals":{"cluster":"1000.00"},
            "profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]}},
            "instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]
        }).as_object().unwrap().clone());
        let binding = TradingBinding::new(RunConfiguration::from_record(config).unwrap(), &"b".repeat(64)).unwrap();
        let mut fixture: Value = serde_json::from_str(include_str!("../../../../test-data/broker/domain-inputs.json")).unwrap();
        fixture["request"]["time_in_force"] = json!(policy);
        let command = BrokerCommand::decode(&json!({
            "schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"original-submit",
            "order":"original-order","client":"original-client","request":fixture["request"]
        })).unwrap();
        let admission = OriginalAdmission(ReadyIntent::new(command.clone(), "original-tx".into(), "c".repeat(64))
            .unwrap().at_admission(&json!(0)).unwrap());
        let mut documents = Vec::new();
        with_memory_log(&binding, &scope, &cash, &mut documents, |broker, journal, venue| {
            broker.set_connection(Connection::Ready);
            broker.set_health(true, true, true);
            assert_eq!(broker.dispatch(journal, &admission, venue, &command).unwrap(), CommandState::Known);
            assert_eq!(journal.dispatch_admission_time(command.id()), Some(&json!(0)));
        }).unwrap();
        let result = documents.pop().unwrap();
        assert_eq!(result["body"]["record"]["event"], json!({"kind":"RESULT","command_id":command.id(),"result":expected}));
        assert_eq!(documents.last().unwrap()["body"]["inputs"], json!([["COMMAND", command.record()]]));
        Self { binding, cash, command, documents, result }
    }

    fn recover(&mut self, initial_state: CommandState) -> Vec<Value> {
        let command = &self.command;
        with_memory_log(&self.binding, command.scope(), &self.cash, &mut self.documents, |broker, journal, venue| {
            assert_eq!(journal.commands().unwrap().as_slice(), std::slice::from_ref(command));
            assert_eq!(broker.command_state(command.id()), Some(initial_state));
            recover_original_orders(broker, journal, venue).unwrap();
            assert_eq!(broker.command_state(command.id()), Some(CommandState::Reconciling));
            assert!(!broker.ready());
            assert_eq!(journal.dispatch_admission_time(command.id()), Some(&json!(0)));
            broker.pending().iter().map(Fact::record).collect()
        }).unwrap()
    }

    fn discovery(&self) -> &Value {
        let event = &self.documents.last().unwrap()["body"]["record"]["event"];
        assert_eq!(event["kind"], "DISCOVERY");
        assert_eq!(event["command_id"], self.command.id());
        assert_eq!(event["discovery"]["command"], self.command.record());
        &event["discovery"]
    }

    fn recover_inconclusive(&mut self) {
        let before = self.documents.len();
        assert!(self.recover(CommandState::Unknown).is_empty());
        assert_eq!(self.documents.len(), before + 1);
        let observation = self.discovery();
        assert_eq!(observation["presence"], "INCONCLUSIVE");
        assert_eq!(observation["view"], Value::Null);
        assert_eq!(observation["facts"], json!([]));
    }
}

#[test]
fn definite_result_requires_the_same_outcome_at_the_original_venue_prefix() {
    for (policy, actual) in [("DAY", "RECEIVED"), ("IOC", "REJECTED")] {
        let original = LostResult::with_time_in_force(policy, actual);
        for has_command in [true, false] {
            for reported in ["RECEIVED", "REJECTED", "UNKNOWN"] {
                let mut prefix = original.documents.clone();
                if !has_command {
                    prefix.pop().unwrap();
                }
                let previous = prefix.last().unwrap();
                let mut result = original.result.clone();
                result["sequence"] = json!(prefix.len());
                result["previous"] = json!(onlyalpha_broker::digest(previous));
                result["body"]["checkpoint"] = previous["body"]["checkpoint"].clone();
                let record = &mut result["body"]["record"];
                record["event"]["result"] = json!(reported);
                record.as_object_mut().unwrap().remove("hash");
                record["hash"] = json!(onlyalpha_broker::digest(record));
                prefix.push(result);
                let before = prefix.clone();
                let state = with_memory_log(&original.binding, original.command.scope(), &original.cash,
                    &mut prefix, |broker, _, _| broker.command_state(original.command.id()).unwrap());
                let expected = if reported == "UNKNOWN" {
                    Ok(CommandState::Unknown)
                } else if has_command && reported == actual {
                    Ok(CommandState::Known)
                } else {
                    Err(Error::new("SIM_VENUE_HISTORY_CONFLICT"))
                };
                assert_eq!(state, expected, "{policy} {has_command} {reported}");
                assert_eq!(prefix, before);
            }
        }
    }
}

#[test]
fn cold_start_rejects_missing_or_future_dispatch_time_before_query() {
    let original = LostResult::after_venue_command();
    for (at, expected) in [(Value::Null, "SIM_VENUE_HISTORY_CONFLICT"), (json!(1), "BROKER_SOURCE_CLOCK_BEFORE_ADMISSION")] {
        let mut documents = original.documents.clone();
        documents.pop().unwrap();
        let body = &mut documents.last_mut().unwrap()["body"];
        assert_eq!(body["record"]["event"]["kind"], "DISPATCHED");
        body["admitted_at"] = at;
        let before = documents.clone();
        let result: Result<(), Error> = with_memory_log(
            &original.binding, original.command.scope(), &original.cash, &mut documents,
            |_, _, _| panic!("派发时刻无效时不得开始原单查询"),
        );
        assert_eq!(result.unwrap_err(), Error::new(expected));
        assert_eq!(documents, before);
    }
}

#[test]
fn dispatched_without_venue_command_stays_inconclusive_across_two_cold_starts() {
    let mut original = LostResult::after_venue_command();
    original.documents.pop().unwrap();
    let dispatched = &original.documents.last().unwrap()["body"]["record"]["event"];
    assert_eq!(*dispatched, json!({"kind":"DISPATCHED", "command_id":original.command.id()}));
    assert!(original.documents.iter().all(|doc| doc["kind"] != "VENUE"));
    original.recover_inconclusive();
    let first = original.documents.clone();
    assert!(original.recover(CommandState::Reconciling).is_empty());
    assert_eq!(original.documents, first);
}

#[test]
fn lost_result_recovers_original_acceptance_once_across_cold_starts() {
    let mut original = LostResult::after_venue_command();
    let before_discovery = original.documents.clone();
    original.recover_inconclusive();
    assert_eq!(&original.documents[..before_discovery.len()], before_discovery.as_slice());
    let pending_acceptance = original.documents.clone();
    assert!(original.recover(CommandState::Reconciling).is_empty());
    assert_eq!(original.documents, pending_acceptance);

    with_memory_log(&original.binding, original.command.scope(), &original.cash, &mut original.documents,
        |_, _, venue| venue.advance(0).unwrap()).unwrap();
    let before = original.documents.len();
    let pending = original.recover(CommandState::Reconciling);
    assert_eq!(original.documents.len(), before + 1);
    let observation = original.discovery();
    assert_eq!(observation["presence"], "PRESENT");
    assert_eq!(observation["view"]["order"], original.command.order());
    assert_eq!(observation["view"]["client"], original.command.client());
    assert_eq!(observation["view"]["status"], "ACCEPTED");
    assert_eq!(observation["view"]["venue"], "virtual-order-00000001");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0]["kind"], "ACCEPTED");
    assert_eq!(pending[0]["causation"], original.command.id());
    assert_eq!(pending[0]["payload"]["venue"], observation["view"]["venue"]);
    assert_eq!(observation["facts"], json!(pending));
    let first = original.documents.clone();
    assert_eq!(original.recover(CommandState::Reconciling), pending);
    assert_eq!(original.documents, first);
    let inputs: Vec<_> = original.documents.iter().filter(|doc| doc["kind"] == "VENUE")
        .flat_map(|doc| doc["body"]["inputs"].as_array().unwrap()).collect();
    assert_eq!(json!(inputs), json!([["COMMAND", original.command.record()], ["CLOCK", 0]]));
}
