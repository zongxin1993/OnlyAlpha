use onlyalpha_broker::*;
use serde_json::{Value, json};

fn scope() -> Scope {
    Scope::decode(&json!({"engine":"engine","runtime":"runtime","gateway":"gateway","account":"account","generation":"a".repeat(64),"runtime_kind":"BACKTEST"})).unwrap()
}
fn command(id: &str) -> BrokerCommand {
    BrokerCommand::decode(&json!({"schema_version":1,"scope":scope().record(),"operation":"SUBMIT","command_id":id,"order":"order","client":"client","request":serde_json::from_str::<Value>(include_str!("../../../../test-data/broker/domain-inputs.json")).unwrap()["request"]})).unwrap()
}
#[derive(Default)]
struct Memory {
    rows: Vec<Record>,
    fail_after: Option<usize>,
}
impl Journal for Memory {
    fn records(&self) -> Result<Vec<Record>, Error> {
        Ok(self.rows.clone())
    }
    fn append(&mut self, intent: &AppendIntent) -> Result<(), Error> {
        self.rows.push(Record::new(intent));
        if self.fail_after == Some(self.rows.len()) {
            return Err(Error::new("STORE_UNKNOWN"));
        }
        Ok(())
    }
}
struct Runtime;
impl RuntimeReader for Runtime {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent, Error> {
        ReadyIntent::new(c.clone(), "tx".into(), "b".repeat(64))
    }
    fn application_receipt(&self, _: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        Ok(None)
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        Ok(None)
    }
}
struct Adapter {
    calls: usize,
}
impl TradingPort for Adapter {
    fn capabilities(&self) -> Capabilities {
        Capabilities::new(&["SUBMIT_ORDER", "CANCEL_ORDER", "LIMIT_ORDER"]).unwrap()
    }
    fn dispatch(&mut self, _: &BrokerCommand) -> Result<DispatchResult, Error> {
        self.calls += 1;
        Err(Error::new("TIMEOUT"))
    }
}
fn connected(b: &mut Broker) {
    b.set_connection(Connection::Ready);
    b.set_health(true, true, true);
}
#[test]
fn durable_unknown_never_repeats_external_side_effect_after_restart() {
    let mut store = Memory::default();
    let mut broker = Broker::recover(scope(), &store, 4).unwrap();
    connected(&mut broker);
    let c = command("submit");
    let mut adapter = Adapter { calls: 0 };
    assert_eq!(
        broker
            .dispatch(&mut store, &Runtime, &mut adapter, &c)
            .unwrap(),
        CommandState::Unknown
    );
    assert_eq!(adapter.calls, 1);
    let mut fresh = Broker::recover(scope(), &store, 4).unwrap();
    connected(&mut fresh);
    assert_eq!(
        fresh
            .dispatch(&mut store, &Runtime, &mut adapter, &c)
            .unwrap(),
        CommandState::Unknown
    );
    assert_eq!(adapter.calls, 1);
    assert!(!fresh.ready());
    let mut changed = c.record();
    changed["request"]["quantity"]["value"] = json!("101");
    assert!(
        fresh
            .dispatch(
                &mut store,
                &Runtime,
                &mut adapter,
                &BrokerCommand::decode(&changed).unwrap()
            )
            .is_err()
    );
    assert!(
        fresh
            .dispatch(
                &mut store,
                &Runtime,
                &mut adapter,
                &command("second-identity")
            )
            .is_err()
    );
}
#[test]
fn uncertain_persisted_dispatched_record_blocks_call_even_if_adapter_never_entered() {
    let mut store = Memory {
        rows: vec![],
        fail_after: Some(2),
    };
    let mut b = Broker::recover(scope(), &store, 4).unwrap();
    connected(&mut b);
    let mut adapter = Adapter { calls: 0 };
    assert!(
        b.dispatch(&mut store, &Runtime, &mut adapter, &command("submit"))
            .is_err()
    );
    assert_eq!(adapter.calls, 0);
    let mut fresh = Broker::recover(scope(), &store, 4).unwrap();
    connected(&mut fresh);
    assert_eq!(
        fresh
            .dispatch(&mut store, &Runtime, &mut adapter, &command("submit"))
            .unwrap(),
        CommandState::Unknown
    );
    assert_eq!(adapter.calls, 0);
}
#[test]
fn unavailable_intent_and_transport_readiness_fail_before_any_durable_command_or_call() {
    let mut store = Memory::default();
    let mut b = Broker::recover(scope(), &store, 4).unwrap();
    let mut a = Adapter { calls: 0 };
    assert!(
        b.dispatch(&mut store, &Runtime, &mut a, &command("submit"))
            .is_err()
    );
    assert!(store.rows.is_empty());
    assert_eq!(a.calls, 0);
}
#[test]
fn decoded_record_cannot_mint_append_authority_and_changed_history_is_rejected() {
    let mut store = Memory::default();
    let mut b = Broker::recover(scope(), &store, 4).unwrap();
    connected(&mut b);
    let mut a = Adapter { calls: 0 };
    b.dispatch(&mut store, &Runtime, &mut a, &command("submit"))
        .unwrap();
    let mut row = store.rows[1].record();
    row["previous"] = json!("0".repeat(64));
    store.rows[1] = Record::decode(&row).unwrap();
    assert!(Broker::recover(scope(), &store, 4).is_err());
}

fn fact(kind: &str, update: &str) -> Fact {
    Fact::decode(&json!({"scope":scope().record(),"session":"session-1","update_id":update,"source_sequence":1,"ts_event":1,"ts_init":2,"correlation":"correlation","causation":"causation","quality":[],"kind":kind,"payload":if kind=="ACCEPTED"{json!({"order":"order","venue":"venue"})}else{json!({"order":"order","venue":"venue","reason":""})}})).unwrap()
}
fn view() -> OrderView {
    OrderView::decode(&json!({"scope":scope().record(),"order":"order","client":"client","venue":"venue","request":command("submit").record()["request"],"filled":"0","status":"CANCELLED"})).unwrap()
}
struct Local {
    receipts: bool,
    wrong: bool,
    view: Option<OrderView>,
}
impl RuntimeReader for Local {
    fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent, Error> {
        Runtime.ready_intent(c)
    }
    fn application_receipt(&self, f: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
        if !self.receipts {
            return Ok(None);
        }
        let target = if self.wrong {
            fact("EXPIRED", "other")
        } else {
            f.clone()
        };
        Ok(Some(ApplicationReceipt::new(
            &target,
            "applied-tx".into(),
            "c".repeat(64),
            ApplicationStatus::Applied,
        )?))
    }
    fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
        Ok(self.view.clone())
    }
}
struct Venue {
    n: u64,
    presence: Presence,
    facts: Vec<Fact>,
    view: Option<OrderView>,
}
impl DiscoveryPort for Venue {
    fn discover(&mut self, c: &BrokerCommand) -> Result<Discovery, Error> {
        self.n += 1;
        Discovery::new(
            c.clone(),
            format!("proof-{}", self.n),
            self.n,
            self.presence,
            self.view.clone(),
            self.facts.clone(),
        )
    }
}
fn unknown() -> (Memory, Broker, Adapter) {
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    let mut a = Adapter { calls: 0 };
    b.dispatch(&mut j, &Runtime, &mut a, &command("submit"))
        .unwrap();
    (j, b, a)
}
#[test]
fn incomplete_wrong_or_unavailable_application_receipts_never_resolve() {
    let (mut j, mut b, _) = unknown();
    let mut venue = Venue {
        n: 0,
        presence: Presence::Present,
        facts: vec![fact("ACCEPTED", "a"), fact("CANCELLED", "c")],
        view: Some(view()),
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    assert_eq!(b.pending().len(), 2);
    venue.facts.clear();
    for local in [
        Local {
            receipts: false,
            wrong: false,
            view: Some(view()),
        },
        Local {
            receipts: true,
            wrong: true,
            view: Some(view()),
        },
        Local {
            receipts: true,
            wrong: false,
            view: None,
        },
    ] {
        assert!(b.resolve(&mut j, &local, &mut venue, "submit").is_err());
        assert!(!b.ready());
        assert_eq!(b.command_state("submit"), Some(CommandState::Reconciling));
    }
    let mut fresh = Broker::recover(scope(), &j, 8).unwrap();
    assert_eq!(fresh.pending().len(), 2);
    fresh
        .resolve(
            &mut j,
            &Local {
                receipts: true,
                wrong: false,
                view: Some(view()),
            },
            &mut venue,
            "submit",
        )
        .unwrap();
    assert!(fresh.pending().is_empty());
    assert_eq!(fresh.command_state("submit"), Some(CommandState::Resolved));
    assert!(!fresh.ready());
    connected(&mut fresh);
    assert!(fresh.ready());
}
#[test]
fn a_second_discovery_cannot_erase_missing_fact_receipt_obligations() {
    let (mut j, mut b, _) = unknown();
    let mut venue = Venue {
        n: 0,
        presence: Presence::Present,
        facts: vec![fact("CANCELLED", "c")],
        view: Some(view()),
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    venue.facts.clear();
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    assert!(
        b.resolve(
            &mut j,
            &Local {
                receipts: false,
                wrong: false,
                view: Some(view())
            },
            &mut venue,
            "submit"
        )
        .is_err()
    );
    assert_eq!(b.pending().len(), 1);
}
#[test]
fn ingress_record_bound_is_checked_before_persistence() {
    let mut journal = Memory::default();
    let mut broker = Broker::recover(scope(), &journal, 1).unwrap();
    let duplicate = fact("ACCEPTED", "a");
    assert!(
        broker
            .ingest(&mut journal, &vec![duplicate.clone(); 4097])
            .is_err()
    );
    assert!(journal.rows.is_empty());
    assert!(broker.pending().is_empty());
    let mut fresh = Broker::recover(scope(), &journal, 1).unwrap();
    fresh.ingest(&mut journal, &vec![duplicate; 4096]).unwrap();
    assert_eq!(fresh.pending().len(), 1);
    assert_eq!(journal.rows.len(), 1);
    assert_eq!(
        Broker::recover(scope(), &journal, 1)
            .unwrap()
            .pending()
            .len(),
        1
    );
}
#[test]
fn batch_overflow_is_atomic_and_conflicting_fact_latches_after_restart() {
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 1).unwrap();
    connected(&mut b);
    assert!(
        b.ingest(&mut j, &[fact("ACCEPTED", "a"), fact("CANCELLED", "c")])
            .is_err()
    );
    assert!(b.pending().is_empty());
    assert!(j.rows.is_empty());
    b.ingest(&mut j, &[fact("ACCEPTED", "a")]).unwrap();
    let mut duplicate = fact("ACCEPTED", "a").record();
    duplicate["session"] = json!("new-session");
    duplicate["update_id"] = json!("query-observation");
    duplicate["source_sequence"] = Value::Null;
    duplicate["quality"] = json!(["PROVIDER_SEQUENCE_UNAVAILABLE"]);
    b.ingest(&mut j, &[Fact::decode(&duplicate).unwrap()])
        .unwrap();
    assert_eq!(b.pending().len(), 1);
    let mut bad = fact("CANCELLED", "c").record();
    bad["kind"] = json!("REJECTED");
    bad["payload"]["reason"] = json!("a:one");
    let f = Fact::decode(&bad).unwrap();
    let mut other = bad.clone();
    other["payload"]["reason"] = json!("a:two");
    let mut large = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut large);
    large.ingest(&mut j, &[f]).unwrap();
    assert!(
        large
            .ingest(&mut j, &[Fact::decode(&other).unwrap()])
            .is_err()
    );
    let mut fresh = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut fresh);
    assert!(!fresh.ready());
}
#[test]
fn strong_absence_resolves_only_submit_and_never_resends_or_fabricates_terminal() {
    let (mut j, mut b, mut adapter) = unknown();
    let mut venue = Venue {
        n: 0,
        presence: Presence::AbsentProven,
        facts: vec![],
        view: None,
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    b.resolve(&mut j, &Runtime, &mut venue, "submit").unwrap();
    assert!(b.pending().is_empty());
    assert_eq!(
        b.dispatch(&mut j, &Runtime, &mut adapter, &command("submit"))
            .unwrap(),
        CommandState::Resolved
    );
    assert_eq!(adapter.calls, 1);
    assert!(
        b.dispatch(&mut j, &Runtime, &mut adapter, &command("another-submit"))
            .is_err()
    );
    let mut cancel = command("cancel").record();
    cancel["operation"] = json!("CANCEL");
    cancel["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-request"},"order_id":{"schema_version":1,"value":"order"},"reason":"user","metadata":{}});
    let c = BrokerCommand::decode(&cancel).unwrap();
    b.set_connection(Connection::Disconnected);
    assert_eq!(
        b.dispatch(&mut j, &Runtime, &mut adapter, &c).unwrap(),
        CommandState::Unknown
    );
    b.reconcile(&mut j, &mut venue, "cancel").unwrap();
    assert!(b.resolve(&mut j, &Runtime, &mut venue, "cancel").is_err());
}
#[test]
fn resolution_persistence_failure_does_not_grant_local_readiness() {
    let (mut j, mut b, _) = unknown();
    let mut venue = Venue {
        n: 0,
        presence: Presence::Present,
        facts: vec![],
        view: Some(view()),
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    j.fail_after = Some(j.rows.len() + 1);
    assert!(
        b.resolve(
            &mut j,
            &Local {
                receipts: true,
                wrong: false,
                view: Some(view())
            },
            &mut venue,
            "submit"
        )
        .is_err()
    );
    assert!(!b.ready());
    let fresh = Broker::recover(scope(), &j, 8).unwrap();
    assert_eq!(fresh.command_state("submit"), Some(CommandState::Resolved));
    assert!(!fresh.ready());
}

#[test]
fn unavailable_runtime_or_changed_ready_request_never_reaches_external_port() {
    struct Denied;
    impl RuntimeReader for Denied {
        fn ready_intent(&self, _: &BrokerCommand) -> Result<ReadyIntent, Error> {
            Err(Error::new("INTENT_NOT_READY"))
        }
        fn application_receipt(&self, _: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
            Ok(None)
        }
        fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
            Ok(None)
        }
    }
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    let mut a = Adapter { calls: 0 };
    assert!(
        b.dispatch(&mut j, &Denied, &mut a, &command("submit"))
            .is_err()
    );
    assert!(j.rows.is_empty());
    assert_eq!(a.calls, 0);
}
#[test]
fn foreign_scope_discovery_and_stale_proof_cannot_change_pending_or_resolution() {
    let (mut j, mut b, _) = unknown();
    let mut wrong = command("submit").record();
    wrong["scope"]["account"] = json!("foreign");
    wrong["request"]["account_id"]["value"] = json!("foreign");
    assert!(
        Discovery::new(
            BrokerCommand::decode(&wrong).unwrap(),
            "proof".into(),
            1,
            Presence::Present,
            Some(view()),
            vec![]
        )
        .is_err()
    );
    let mut venue = Venue {
        n: 0,
        presence: Presence::Present,
        facts: vec![],
        view: Some(view()),
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    venue.n = 0;
    assert!(
        b.resolve(
            &mut j,
            &Local {
                receipts: true,
                wrong: false,
                view: Some(view())
            },
            &mut venue,
            "submit"
        )
        .is_err()
    );
    assert_eq!(b.command_state("submit"), Some(CommandState::Reconciling));
}

#[test]
fn undeclared_trading_and_fee_capabilities_fail_before_dispatch() {
    struct Unsupported;
    impl TradingPort for Unsupported {
        fn capabilities(&self) -> Capabilities {
            Capabilities::new(&[]).unwrap()
        }
        fn dispatch(&mut self, _: &BrokerCommand) -> Result<DispatchResult, Error> {
            panic!("undeclared port entered")
        }
    }
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    assert!(
        b.dispatch(&mut j, &Runtime, &mut Unsupported, &command("submit"))
            .is_err()
    );
    assert!(j.rows.is_empty());
    assert!(fee_evidence_port(&Capabilities::new(&[]).unwrap(), None).is_err());
    assert!(fee_evidence_port(&Capabilities::new(&["QUERY_FEE_EVIDENCE"]).unwrap(), None).is_err());
}
#[test]
fn client_and_request_aliases_cannot_bind_a_second_local_order() {
    let (mut j, mut b, mut a) = unknown();
    let mut other = command("alias").record();
    other["order"] = json!("other-order");
    other["request"]["request_id"]["value"] = json!("other-request");
    assert!(
        b.dispatch(
            &mut j,
            &Runtime,
            &mut a,
            &BrokerCommand::decode(&other).unwrap()
        )
        .is_err()
    );
    assert_eq!(a.calls, 1);
    // Prove this is identity rejection even after the first command is resolved.
    let mut venue = Venue {
        n: 0,
        presence: Presence::AbsentProven,
        facts: vec![],
        view: None,
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    b.resolve(&mut j, &Runtime, &mut venue, "submit").unwrap();
    connected(&mut b);
    assert!(
        b.dispatch(
            &mut j,
            &Runtime,
            &mut a,
            &BrokerCommand::decode(&other).unwrap()
        )
        .is_err()
    );
    assert_eq!(a.calls, 1);
}
#[test]
fn a_venue_order_alias_on_another_local_order_latches_identity_conflict() {
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    b.ingest(&mut j, &[fact("ACCEPTED", "a")]).unwrap();
    let mut other = fact("ACCEPTED", "b").record();
    other["payload"]["order"] = json!("other-order");
    assert!(b.ingest(&mut j, &[Fact::decode(&other).unwrap()]).is_err());
    assert!(!b.ready());
}

#[test]
fn real_virtual_broker_facts_reuse_v2_identity_and_detect_changed_fill_payload() {
    let cases: Value =
        serde_json::from_str(include_str!("../../../../test-data/broker/virtual-v2.json")).unwrap();
    for case in cases.as_array().unwrap() {
        let f = Fact::decode(&case["fact"]).unwrap();
        assert_eq!(f.identity(), case["identity"].as_str().unwrap());
        assert_eq!(f.fingerprint(), case["fingerprint"].as_str().unwrap());
    }
    let original = Fact::decode(&cases[1]["fact"]).unwrap();
    let mut changed = cases[1]["fact"].clone();
    changed["payload"]["fill"]["price"]["value"] = json!("10.01");
    let conflict = Fact::decode(&changed).unwrap();
    assert_eq!(original.identity(), conflict.identity());
    assert_ne!(original.fingerprint(), conflict.fingerprint());
    let mut j = Memory::default();
    let mut broker = Broker::recover(original.scope(), &j, 8).unwrap();
    connected(&mut broker);
    broker.ingest(&mut j, &[original]).unwrap();
    assert!(broker.ingest(&mut j, &[conflict]).is_err());
    assert!(!broker.ready());
}
#[test]
fn recovered_durable_command_cannot_rebind_to_a_different_runtime_transaction() {
    struct Changed;
    impl RuntimeReader for Changed {
        fn ready_intent(&self, c: &BrokerCommand) -> Result<ReadyIntent, Error> {
            ReadyIntent::new(c.clone(), "changed-tx".into(), "d".repeat(64))
        }
        fn application_receipt(&self, _: &Fact) -> Result<Option<ApplicationReceipt>, Error> {
            Ok(None)
        }
        fn order_view(&self, _: &BrokerCommand) -> Result<Option<OrderView>, Error> {
            Ok(None)
        }
    }
    let mut j = Memory {
        rows: vec![],
        fail_after: Some(1),
    };
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    let mut a = Adapter { calls: 0 };
    assert!(
        b.dispatch(&mut j, &Runtime, &mut a, &command("submit"))
            .is_err()
    );
    let mut fresh = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut fresh);
    assert!(
        fresh
            .dispatch(&mut j, &Changed, &mut a, &command("submit"))
            .is_err()
    );
    assert_eq!(a.calls, 0);
}
#[test]
fn invalid_numbers_missing_explicit_intent_and_source_sequence_fail_before_domain_coercion() {
    let mut c = command("invalid").record();
    c["request"]["price"]["value"] = json!("1E+9223372036854775807");
    assert!(BrokerCommand::decode(&c).is_err());
    let mut c = command("invalid").record();
    c["request"]["execution_intent"] = Value::Null;
    assert!(BrokerCommand::decode(&c).is_err());
    let mut f = fact("ACCEPTED", "a").record();
    f["source_sequence"] = Value::Null;
    assert!(Fact::decode(&f).is_err());
    f["quality"] = json!(["PROVIDER_SEQUENCE_UNAVAILABLE"]);
    assert!(Fact::decode(&f).is_ok());
    f["payload"]["venue"] = json!("venue\u{1f}alias");
    assert!(Fact::decode(&f).is_err());
}

#[test]
fn command_receipt_is_not_acceptance_and_can_reconcile_missing_stream_facts() {
    struct Received;
    impl TradingPort for Received {
        fn capabilities(&self) -> Capabilities {
            Capabilities::new(&["SUBMIT_ORDER", "LIMIT_ORDER"]).unwrap()
        }
        fn dispatch(&mut self, _: &BrokerCommand) -> Result<DispatchResult, Error> {
            Ok(DispatchResult::Received)
        }
    }
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    assert_eq!(
        b.dispatch(&mut j, &Runtime, &mut Received, &command("submit"))
            .unwrap(),
        CommandState::Known
    );
    assert!(b.pending().is_empty());
    let mut venue = Venue {
        n: 0,
        presence: Presence::Present,
        facts: vec![fact("CANCELLED", "c")],
        view: Some(view()),
    };
    b.reconcile(&mut j, &mut venue, "submit").unwrap();
    assert_eq!(b.pending().len(), 1);
    assert!(!b.ready());
}

#[test]
fn one_local_order_cannot_silently_switch_venue_identity() {
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    b.ingest(&mut j, &[fact("ACCEPTED", "a")]).unwrap();
    let mut changed = fact("ACCEPTED", "b").record();
    changed["payload"]["venue"] = json!("other-venue");
    assert!(
        b.ingest(&mut j, &[Fact::decode(&changed).unwrap()])
            .is_err()
    );
    assert!(!b.ready());
}
#[test]
fn owning_application_ack_is_durable_and_repeated_stream_fact_stays_deduplicated() {
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    let f = fact("ACCEPTED", "a");
    b.ingest(&mut j, std::slice::from_ref(&f)).unwrap();
    assert!(b.acknowledge(&mut j, &Runtime, f.identity()).is_err());
    assert_eq!(b.pending().len(), 1);
    b.acknowledge(
        &mut j,
        &Local {
            receipts: true,
            wrong: false,
            view: None,
        },
        f.identity(),
    )
    .unwrap();
    let mut fresh = Broker::recover(scope(), &j, 8).unwrap();
    fresh.ingest(&mut j, &[f]).unwrap();
    assert!(fresh.pending().is_empty());
}
#[test]
fn account_and_position_observations_validate_currency_and_quantity_relations() {
    let currency = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
    let money = json!({"schema_version":1,"currency":currency,"amount":"10.00"});
    let snapshot = json!({"scope":scope().record(),"kind":"ACCOUNT","source_sequence":1,"snapshot_time":1,"payload":{"currency":currency,"ledger_cash":money,"trade_available_cash":money,"order_reserved_cash":money,"equity":money}});
    assert!(Snapshot::decode(&snapshot).is_ok());
    let mut bad = snapshot.clone();
    bad["payload"]["equity"]["currency"]["code"] = json!("USD");
    assert!(Snapshot::decode(&bad).is_err());
    let q = json!({"schema_version":1,"precision":0,"value":"4"});
    let position = json!({"scope":scope().record(),"kind":"POSITION","source_sequence":1,"snapshot_time":1,"payload":{"instrument":command("submit").record()["request"]["instrument_id"],"side":"LONG","quantity":q,"available":q,"frozen":{"schema_version":1,"precision":0,"value":"0"},"average_price":null}});
    assert!(Snapshot::decode(&position).is_ok());
    let mut bad = position.clone();
    bad["payload"]["frozen"]["value"] = json!("1");
    assert!(Snapshot::decode(&bad).is_err());
}

#[test]
fn source_sequence_and_timestamps_preserve_domain_integers_beyond_machine_width() {
    let mut record = fact("ACCEPTED", "a").record();
    let large: Value = serde_json::from_str("100000000000000000000000000000000000").unwrap();
    record["source_sequence"] = large.clone();
    record["ts_event"] = large.clone();
    record["ts_init"] = large;
    let decoded = Fact::decode(&record).unwrap();
    assert_eq!(decoded.record(), record);
    record["source_sequence"] = json!(-1);
    assert!(Fact::decode(&record).is_err());
}

#[test]
fn unavailable_reconciliation_after_command_receipt_clears_discovery_readiness() {
    struct Received;
    impl TradingPort for Received {
        fn capabilities(&self) -> Capabilities {
            Capabilities::new(&["SUBMIT_ORDER", "LIMIT_ORDER"]).unwrap()
        }
        fn dispatch(&mut self, _: &BrokerCommand) -> Result<DispatchResult, Error> {
            Ok(DispatchResult::Received)
        }
    }
    struct Unavailable;
    impl DiscoveryPort for Unavailable {
        fn discover(&mut self, _: &BrokerCommand) -> Result<Discovery, Error> {
            Err(Error::new("VENUE_UNAVAILABLE"))
        }
    }
    let mut j = Memory::default();
    let mut b = Broker::recover(scope(), &j, 8).unwrap();
    connected(&mut b);
    b.dispatch(&mut j, &Runtime, &mut Received, &command("submit"))
        .unwrap();
    assert!(b.ready());
    assert!(b.reconcile(&mut j, &mut Unavailable, "submit").is_err());
    assert!(!b.ready());
}
