use super::*;
use crate::persistence::sim_venue::with_memory_log;
use onlyalpha_broker::{ApplicationReceipt, Connection, Fact, OrderView, ReadyIntent, RuntimeReader, Scope};
use onlyalpha_domain::{base::OnlyDomainModel, value::OnlyMoney};
use onlyalpha_execution::Record;
use onlyalpha_runtime::{RunConfiguration, durability::TradingBinding};

const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../../../crates/execution/tests/support/mod.rs"]
mod economics;

fn append(facts: &RecoveryFacts, mut input: Value, ready: bool) -> RecoveryFacts {
    input["runtime_kind"] = json!("SIM");
    let plan = facts.prepare(&input).unwrap();
    let mut rows = facts.records().to_vec();
    rows.push(Record::decode(&json!({"schema_version": 1, "prepared": plan.prepared().record(),
        "ready": ready, "delivered": false})).unwrap());
    let binding = facts.binding();
    RecoveryFacts::from_records(binding, binding.fingerprint(), rows.len() as u64, rows).unwrap()
}

fn history() -> (RecoveryFacts, RecoveryFacts, BrokerCommand, BrokerCommand) {
    let mut config = economics::config();
    config["runtime_kind"] = json!("SIM");
    let binding = TradingBinding::new(RunConfiguration::from_record(config).unwrap(), &"b".repeat(64)).unwrap();
    let empty = RecoveryFacts::from_records(&binding, binding.fingerprint(), 0, vec![]).unwrap();
    let first = append(&empty, economics::open(1, "BUY"), true);
    let plan = first.records()[0].prepared();
    let order = economics::order(1);
    let input = plan.input();
    let snapshot = &plan.order_snapshot_data()[0]["snapshot"];
    let mut scope = json!({});
    for key in ["engine", "runtime", "gateway", "account", "generation", "runtime_kind"] {
        scope[key] = input[key].clone();
    }
    let mut request = input["payload"]["request"].clone();
    request["account_id"] = snapshot["account_id"].clone();
    let submit = BrokerCommand::decode(&json!({"schema_version":1,"scope":scope,"operation":"SUBMIT",
        "command_id":"submit","order":order,"client":snapshot["client_order_id"]["value"],"request":request})).unwrap();
    let cancel_input = economics::input(2, "CANCEL", json!({"schema_version":1,"order":order,
        "request_id":"withdraw","reason":"撤单"}));
    let pending = append(&first, cancel_input.clone(), false);
    let ready = append(&first, cancel_input, true);
    let cancel = BrokerCommand::decode(&json!({"schema_version":1,"scope":scope,"operation":"CANCEL",
        "command_id":"cancel","order":order,"client":submit.client(),"request":{"schema_version":1,
        "request_id":{"schema_version":1,"value":"withdraw"},"order_id":snapshot["order_id"],"reason":"撤单","metadata":{}}})).unwrap();
    (ready, pending, submit, cancel)
}

struct Admission(ReadyIntent);

impl RuntimeReader for Admission {
    fn ready_intent(&self, command: &BrokerCommand) -> Result<ReadyIntent, Error> {
        assert_eq!(command.record(), self.0.record()["command"]);
        Ok(self.0.clone())
    }
    fn application_receipt(&self, _: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        unreachable!()
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        unreachable!()
    }
}

fn cash() -> OnlyMoney {
    OnlyMoney::from_record(&json!({"schema_version":1,"amount":"1000.00","currency":economics::config()["currency"]})).unwrap()
}

fn dispatch_log(facts: &RecoveryFacts, commands: &[BrokerCommand; 2], second_tx: &str, second_hash: &str, second_time: u64) -> Vec<Value> {
    let first = facts.records()[0].prepared();
    let sources = [(first.id(), first.payload_fingerprint(), 1), (second_tx, second_hash, second_time)];
    let mut documents = Vec::new();
    with_memory_log(facts.binding(), commands[0].scope(), &cash(), &mut documents, |broker, journal, venue| {
        broker.set_connection(Connection::Ready);
        broker.set_health(true, true, true);
        for (command, (transaction, hash, time)) in commands.iter().zip(sources) {
            venue.advance(time as i64).unwrap();
            let intent = ReadyIntent::new(command.clone(), transaction.into(), hash.into()).unwrap().at_admission(&json!(time)).unwrap();
            broker.dispatch(journal, &Admission(intent), venue, command).unwrap();
        }
    }).unwrap();
    documents
}

fn verify(facts: &RecoveryFacts, scope: &Scope, documents: &[Value]) -> Result<(), Error> {
    let mut restored = documents.to_vec();
    let result = with_memory_log(facts.binding(), scope, &cash(), &mut restored,
        |_, journal, _| verify_original_intents(journal, facts)).unwrap();
    assert_eq!(restored, documents);
    result
}

#[test]
fn original_admit_and_cancel_require_their_own_ready_transaction_hash_and_time() {
    let (ready, pending, submit, cancel) = history();
    let terminal = append(&ready, economics::terminal(3, 1, "CANCELLED"), true);
    let commands = [submit, cancel];
    let first = ready.records()[0].prepared();
    let second = ready.records()[1].prepared();
    let documents = dispatch_log(&ready, &commands, second.id(), second.payload_fingerprint(), 2);
    assert_eq!(verify(&terminal, commands[0].scope(), &documents), Ok(()));
    assert_eq!(verify(&pending, commands[0].scope(), &documents), Err(intent_conflict()));
    for (transaction, hash, time) in [
        ("unrelated-transaction", second.payload_fingerprint(), 2),
        (first.id(), first.payload_fingerprint(), 2),
        (second.id(), first.payload_fingerprint(), 2),
        (second.id(), second.payload_fingerprint(), 3),
    ] {
        let changed = dispatch_log(&ready, &commands, transaction, hash, time);
        assert_eq!(verify(&ready, commands[0].scope(), &changed), Err(intent_conflict()));
    }
}

#[test]
fn later_intent_conflict_blocks_discovery_of_an_earlier_unknown_order() {
    let (facts, _, submit, cancel) = history();
    let commands = [submit, cancel];
    let scope = commands[0].scope();
    let second = facts.records()[1].prepared();
    let mut documents = dispatch_log(&facts, &commands, second.id(), second.payload_fingerprint(), 2);
    let first_dispatch = documents.iter().position(|doc| {
        let event = &doc["body"]["record"]["event"];
        event["kind"] == "DISPATCHED" && event["command_id"] == commands[0].id()
    }).unwrap();
    documents.truncate(first_dispatch + 1);

    let mut control = documents.clone();
    with_memory_log(facts.binding(), scope, &cash(), &mut control, |broker, journal, venue| {
        assert_eq!(broker.command_state(commands[0].id()), Some(CommandState::Unknown));
        recover_verified_orders(broker, journal, venue, &facts)
    }).unwrap().unwrap();
    let discovered = &control.last().unwrap()["body"]["record"]["event"];
    assert_eq!(discovered["kind"], "DISCOVERY");
    assert_eq!(discovered["command_id"], commands[0].id());

    let wrong_hash = facts.records()[0].prepared().payload_fingerprint();
    let invalid = ReadyIntent::new(commands[1].clone(), second.id().into(), wrong_hash.into())
        .unwrap().at_admission(&json!(2)).unwrap();
    with_memory_log(facts.binding(), scope, &cash(), &mut documents, |broker, journal, venue| {
        venue.advance(2).unwrap();
        broker.dispatch(journal, &Admission(invalid), venue, &commands[1]).unwrap();
    }).unwrap();
    let before = documents.clone();
    let result = with_memory_log(facts.binding(), scope, &cash(), &mut documents, |broker, journal, venue| {
        recover_verified_orders(broker, journal, venue, &facts)
    }).unwrap();
    assert_eq!(result, Err(intent_conflict()));
    assert_eq!(documents, before);
}

#[test]
fn original_requests_bind_scope_order_client_and_the_complete_submit_or_cancel_body() {
    let (facts, _, submit, cancel) = history();
    let admit = facts.records()[0].prepared();
    let withdrawal = facts.records()[1].prepared();
    assert_eq!(verify_original_request(admit, &cancel), Err(intent_conflict()));
    assert_eq!(verify_original_request(withdrawal, &submit), Err(intent_conflict()));
    for (plan, command, path, value) in [
        (admit, &submit, "/scope/gateway", json!("another-gateway")),
        (admit, &submit, "/order", json!("another-order")),
        (admit, &submit, "/client", json!("another-client")),
        (admit, &submit, "/request/price/value", json!("11.00")),
        (withdrawal, &cancel, "/scope/account", json!("another-account")),
        (withdrawal, &cancel, "/request/reason", json!("不同原因")),
        (withdrawal, &cancel, "/request/request_id/value", json!("another-request")),
        (withdrawal, &cancel, "/request/metadata", json!({"source":"other"})),
    ] {
        let mut raw = command.record();
        *raw.pointer_mut(path).unwrap() = value;
        let other = BrokerCommand::decode(&raw).unwrap();
        assert_eq!(verify_original_request(plan, &other), Err(intent_conflict()), "{path}");
    }
}
