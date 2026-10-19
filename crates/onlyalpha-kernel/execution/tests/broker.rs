//! Real consumer composition. The owning Execution Ready reader is the admission authority.
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
mod support;
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
use onlyalpha_broker as b;
use onlyalpha_domain::base::OnlyDomainModel;
use onlyalpha_execution::{Components, coordinate};
use serde_json::json;
struct Reader<'a> {
    components: &'a Components,
    store: &'a support::MemoryStore,
}
fn error(_: impl std::fmt::Display) -> b::Error {
    b::Error::new("EXECUTION_AUTHORITY_UNAVAILABLE")
}
impl b::RuntimeReader for Reader<'_> {
    fn ready_intent(&self, c: &b::BrokerCommand) -> Result<b::ReadyIntent, b::Error> {
        let records = self.components.ready_records(self.store).map_err(error)?;
        let snapshot = self
            .components
            .order_snapshot(self.store, "cluster", c.order())
            .map_err(error)?
            .to_record();
        if snapshot["client_order_id"]["value"] != c.record()["client"] {
            return Err(error("client"));
        }
        match c.operation() {
            b::Operation::Submit => {
                let submission = self
                    .components
                    .order_submission(self.store, "cluster", c.order())
                    .map_err(error)?;
                if snapshot["status"] != "SUBMITTED" || submission != "DISPATCHING" {
                    return Err(error("current submit eligibility"));
                }
            }
            b::Operation::Cancel => {
                if snapshot["status"] != "PENDING_CANCEL" {
                    return Err(error("current pending cancel relation"));
                }
            }
        }
        for record in records.into_iter().rev() {
            let p = record.prepared();
            let input = p.input();
            if input["payload"]["order"] != c.order() {
                continue;
            }
            let operation = if c.operation() == b::Operation::Submit {
                "ADMIT"
            } else {
                "CANCEL"
            };
            if input["op"] != operation {
                continue;
            }
            let scope = c.scope().record();
            for name in [
                "engine",
                "runtime",
                "gateway",
                "account",
                "generation",
                "runtime_kind",
            ] {
                if scope[name] != input[name] {
                    return Err(error("scope"));
                }
            }
            let mut expected = input["payload"]["request"].clone();
            if c.operation() == b::Operation::Submit {
                expected["account_id"] = snapshot["account_id"].clone();
                if expected != c.record()["request"] {
                    return Err(error("request"));
                }
            } else {
                let expected =
                    onlyalpha_domain::execution::OnlyCancelOrderRequest::from_record(&json!({
                        "schema_version":1,
                        "request_id":{"schema_version":1,"value":input["payload"]["request_id"]},
                        "order_id":{"schema_version":1,"value":input["payload"]["order"]},
                        "reason":input["payload"]["reason"],"metadata":{}
                    }))
                    .map_err(error)?
                    .to_record();
                if expected != c.record()["request"] {
                    return Err(error("canonical cancel payload"));
                }
            }
            return b::ReadyIntent::new(
                c.clone(),
                p.id().into(),
                p.record()["payload_hash"].as_str().unwrap().into(),
            );
        }
        Err(error("intent"))
    }
    fn application_receipt(&self, _: &b::Fact) -> Result<Option<b::ApplicationReceipt>, b::Error> {
        Ok(None)
    }
    fn order_view(&self, _: &b::BrokerCommand) -> Result<Option<b::OrderView>, b::Error> {
        Ok(None)
    }
}
#[derive(Default)]
struct Journal(Vec<b::Record>);
impl b::Journal for Journal {
    fn records(&self) -> Result<Vec<b::Record>, b::Error> {
        Ok(self.0.clone())
    }
    fn append(&mut self, i: &b::AppendIntent) -> Result<(), b::Error> {
        self.0.push(b::Record::new(i));
        Ok(())
    }
}
struct Adapter(usize);
impl b::TradingPort for Adapter {
    fn capabilities(&self) -> b::Capabilities {
        b::Capabilities::new(&["SUBMIT_ORDER", "CANCEL_ORDER", "LIMIT_ORDER"]).unwrap()
    }
    fn dispatch(&mut self, _: &b::BrokerCommand) -> Result<b::DispatchResult, b::Error> {
        self.0 += 1;
        Ok(b::DispatchResult::Received)
    }
}
#[test]
fn execution_order_intent_is_unavailable_until_exact_committed_projections_are_ready() {
    let mut components = Components::new(support::config()).unwrap();
    let mut store = support::MemoryStore::default();
    let prepared = components
        .prepare(&store, &support::open(1, "BUY"))
        .unwrap();
    let mut scope = support::config();
    scope.as_object_mut().unwrap().retain(|k, _| {
        [
            "engine",
            "runtime",
            "gateway",
            "account",
            "generation",
            "runtime_kind",
        ]
        .contains(&k.as_str())
    });
    let mut request = support::fixture()["request"].clone();
    request["account_id"] = json!({"schema_version":1,"value":"account"});
    // Read the deterministic client identity only after owning Ready publication.
    let mut j = Journal::default();
    let mut broker = b::Broker::recover(b::Scope::decode(&scope).unwrap(), &j, 8).unwrap();
    broker.set_connection(b::Connection::Ready);
    broker.set_health(true, true, true);
    let mut adapter = Adapter(0);
    let preliminary=b::BrokerCommand::decode(&json!({"schema_version":1,"scope":scope,"operation":"SUBMIT","command_id":"submit","order":support::order(1),"client":"unknown-before-ready","request":request})).unwrap();
    assert!(
        broker
            .dispatch(
                &mut j,
                &Reader {
                    components: &components,
                    store: &store
                },
                &mut adapter,
                &preliminary
            )
            .is_err()
    );
    assert_eq!(adapter.0, 0);
    assert!(j.0.is_empty());
    coordinate(&mut store, &mut components, &prepared).unwrap();
    let snapshot = components
        .order_snapshot(&store, "cluster", &support::order(1))
        .unwrap()
        .to_record();
    let mut record = preliminary.record();
    record["client"] = snapshot["client_order_id"]["value"].clone();
    let command = b::BrokerCommand::decode(&record).unwrap();
    assert_eq!(
        broker
            .dispatch(
                &mut j,
                &Reader {
                    components: &components,
                    store: &store
                },
                &mut adapter,
                &command
            )
            .unwrap(),
        b::CommandState::Known
    );
    assert_eq!(adapter.0, 1);
    let mut foreign = record.clone();
    foreign["command_id"] = json!("changed");
    foreign["request"]["price"]["value"] = json!("11.00");
    assert!(
        broker
            .dispatch(
                &mut j,
                &Reader {
                    components: &components,
                    store: &store
                },
                &mut adapter,
                &b::BrokerCommand::decode(&foreign).unwrap()
            )
            .is_err()
    );
    assert_eq!(adapter.0, 1);
    let ready = components.ready_records(&store).unwrap();
    assert_eq!(ready.len(), 1);
    assert_eq!(ready[0].prepared().id(), prepared.id());
    let mut unavailable = store.clone();
    let mut raw = unavailable.rows[0].record();
    raw["ready"] = json!(false);
    unavailable.rows[0] = onlyalpha_execution::Record::decode(&raw).unwrap();
    assert!(
        components
            .order_snapshot(&unavailable, "cluster", &support::order(1))
            .is_err()
    );
    assert!(components.ready_records(&unavailable).is_err());
}

fn admitted() -> (Components, support::MemoryStore, b::BrokerCommand) {
    let mut c = Components::new(support::config()).unwrap();
    let mut s = support::MemoryStore::default();
    let p = c.prepare(&s, &support::open(1, "BUY")).unwrap();
    coordinate(&mut s, &mut c, &p).unwrap();
    let snapshot = c
        .order_snapshot(&s, "cluster", &support::order(1))
        .unwrap()
        .to_record();
    let mut scope = support::config();
    scope.as_object_mut().unwrap().retain(|k, _| {
        [
            "engine",
            "runtime",
            "gateway",
            "account",
            "generation",
            "runtime_kind",
        ]
        .contains(&k.as_str())
    });
    let mut request = support::fixture()["request"].clone();
    request["account_id"] = snapshot["account_id"].clone();
    let command=b::BrokerCommand::decode(&json!({"schema_version":1,"scope":scope,"operation":"SUBMIT","command_id":"submit","order":support::order(1),"client":snapshot["client_order_id"]["value"],"request":request})).unwrap();
    (c, s, command)
}
fn apply(c: &mut Components, s: &mut support::MemoryStore, input: serde_json::Value) {
    let p = c
        .prepare(s, &input)
        .unwrap_or_else(|e| panic!("{e}: {input}"));
    coordinate(s, c, &p).unwrap();
}
#[test]
fn historical_ready_admit_cannot_reauthorize_dispatched_unknown_or_terminal_order() {
    for outcome in [
        "DISPATCHED",
        "UNKNOWN",
        "REJECTED",
        "CANCELLED",
        "EXPIRED",
        "FILLED",
    ] {
        let (mut c, mut s, command) = admitted();
        apply(
            &mut c,
            &mut s,
            support::stage(
                2,
                1,
                if outcome == "UNKNOWN" {
                    "UNKNOWN"
                } else {
                    "DISPATCHED"
                },
            ),
        );
        if outcome == "FILLED" {
            apply(&mut c, &mut s, support::fill(3, 1, "4", "10.00", "1.00"));
        } else if outcome == "EXPIRED" {
            // The owning Order contract admits EXPIRED after acceptance; the assertion still
            // proves a historical ADMIT cannot authorize a submit after this terminal state.
            apply(
                &mut c,
                &mut s,
                support::input(
                    3,
                    "ACCEPT",
                    json!({"schema_version":1,"order":command.order(),"venue_order":"venue-1"}),
                ),
            );
            apply(&mut c, &mut s, support::terminal(4, 1, outcome));
        } else if !matches!(outcome, "DISPATCHED" | "UNKNOWN") {
            apply(&mut c, &mut s, support::terminal(3, 1, outcome));
        }
        let mut j = Journal::default();
        let mut broker = b::Broker::recover(command.scope().clone(), &j, 8).unwrap();
        broker.set_connection(b::Connection::Ready);
        broker.set_health(true, true, true);
        let mut adapter = Adapter(0);
        assert!(
            broker
                .dispatch(
                    &mut j,
                    &Reader {
                        components: &c,
                        store: &s
                    },
                    &mut adapter,
                    &command
                )
                .is_err(),
            "stale intent after {outcome}"
        );
        assert_eq!(adapter.0, 0);
        assert!(j.0.is_empty());
    }
}
fn cancel_command(c: &b::BrokerCommand) -> b::BrokerCommand {
    let mut v = c.record();
    v["operation"] = json!("CANCEL");
    v["command_id"] = json!("cancel-command");
    v["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-1"},"order_id":{"schema_version":1,"value":c.order()},"reason":"user","metadata":{}});
    b::BrokerCommand::decode(&v).unwrap()
}
#[test]
fn cancel_dispatch_requires_full_canonical_request_and_current_pending_relation() {
    let (mut c, mut s, submit) = admitted();
    apply(
        &mut c,
        &mut s,
        support::input(
            2,
            "CANCEL",
            json!({"schema_version":1,"order":submit.order(),"request_id":"cancel-1","reason":"user"}),
        ),
    );
    let command = cancel_command(&submit);
    for field in ["reason", "metadata"] {
        let mut changed = command.record();
        changed["request"][field] = if field == "reason" {
            json!("changed")
        } else {
            json!({"unapproved":"change"})
        };
        let changed = b::BrokerCommand::decode(&changed).unwrap();
        let mut j = Journal::default();
        let mut broker = b::Broker::recover(command.scope().clone(), &j, 8).unwrap();
        let mut adapter = Adapter(0);
        assert!(
            broker
                .dispatch(
                    &mut j,
                    &Reader {
                        components: &c,
                        store: &s
                    },
                    &mut adapter,
                    &changed
                )
                .is_err(),
            "changed {field}"
        );
        assert_eq!(adapter.0, 0);
        assert!(j.0.is_empty());
    }
    let mut j = Journal::default();
    let mut broker = b::Broker::recover(command.scope().clone(), &j, 8).unwrap();
    let mut adapter = Adapter(0);
    assert_eq!(
        broker
            .dispatch(
                &mut j,
                &Reader {
                    components: &c,
                    store: &s
                },
                &mut adapter,
                &command
            )
            .unwrap(),
        b::CommandState::Known
    );
    assert_eq!(adapter.0, 1);
    apply(&mut c, &mut s, support::terminal(3, 1, "CANCELLED"));
    let mut j = Journal::default();
    let mut fresh = b::Broker::recover(command.scope().clone(), &j, 8).unwrap();
    assert!(
        fresh
            .dispatch(
                &mut j,
                &Reader {
                    components: &c,
                    store: &s
                },
                &mut adapter,
                &command
            )
            .is_err()
    );
    assert_eq!(adapter.0, 1);
    assert!(j.0.is_empty());
}
