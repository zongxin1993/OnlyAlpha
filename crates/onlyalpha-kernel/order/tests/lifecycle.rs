use onlyalpha_domain::{base::OnlyDomainModel, enums::OnlyOrderStatus};
use onlyalpha_order::{ApplyResult, Manager};
use serde_json::{Value, json};
const FIXTURE: &str = include_str!("../../../../test-data/order/domain-inputs.json");
fn config() -> Value {
    json!({"schema_version":1,"engine_id":"engine","runtime_id":"runtime","gateway_id":"gateway","generation":"a".repeat(64)})
}
fn fixture() -> Value {
    serde_json::from_str(FIXTURE).unwrap()
}
fn create() -> Value {
    json!({"schema_version":1,"op":"CREATE","cluster_id":"cluster","account_id":"account","request":fixture()["request"],"cause":"b".repeat(64),"at":1})
}
fn local(op: &str, at: u64) -> Value {
    json!({"schema_version":1,"op":op,"cluster_id":"cluster","order_id":"runtime-ORDER-000001","at":at})
}
fn fee() -> Value {
    let mut c = local("FEE", 1);
    c["contract"] = fixture()["fee_contract"].clone();
    c["contract"]["schema_version"] = json!(1);
    c
}
fn ready() -> Manager {
    let mut m = Manager::new(config()).unwrap();
    assert_eq!(m.apply(&create()).unwrap().result, ApplyResult::Applied);
    assert_eq!(m.apply(&fee()).unwrap().result, ApplyResult::Applied);
    assert_eq!(
        m.apply(&local("BEGIN_SUBMIT", 2)).unwrap().result,
        ApplyResult::Applied
    );
    m
}
fn external(op: &str, seq: u64, at: u64) -> Value {
    let mut c = local(op, at);
    for key in ["runtime_id", "gateway_id", "generation"] {
        c[key] = config()[key].clone();
    }
    c["account_id"] = json!("account");
    c["event_at"] = json!(at);
    c["event_id"] = json!(format!("event-{seq}"));
    c["sequence"] = json!(seq);
    c
}
fn accept(seq: u64, at: u64) -> Value {
    let mut c = external("ACCEPT", seq, at);
    c["venue_order_id"] = json!("venue-1");
    c
}
fn fill(seq: u64, price: &str, qty: &str) -> Value {
    let mut c = external("FILL", seq, seq + 3);
    c["fill"] = json!({"schema_version":1,"trade_id":{"schema_version":1,"value":format!("trade-{seq}")},"order_id":{"schema_version":1,"value":"runtime-ORDER-000001"},"price":{"schema_version":1,"value":price,"precision":2},"quantity":{"schema_version":1,"value":qty,"precision":0},"ts_event":{"schema_version":1,"unix_nanos":seq+3},"ts_init":{"schema_version":1,"unix_nanos":seq+3},"venue_trade_id":{"schema_version":1,"value":format!("venue-trade-{seq}")},"venue_order_id":{"schema_version":1,"value":"venue-1"},"liquidity_side":"UNKNOWN","external_sequence":seq,"external_event_id":format!("event-{seq}"),"metadata":{},"reference_price":null});
    c
}
fn snapshot(m: &Manager) -> onlyalpha_domain::execution::OnlyOrderSnapshot {
    m.get("cluster", "runtime-ORDER-000001").unwrap()
}
#[test]
fn request_duplicates_require_full_payload_scope_and_cause() {
    let mut m = ready();
    let before = m.checkpoint().unwrap();
    assert_eq!(m.apply(&create()).unwrap().result, ApplyResult::Duplicate);
    for field in ["cluster_id", "account_id", "cause"] {
        let mut c = create();
        c[field] = json!(if field == "cause" {
            "c".repeat(64)
        } else {
            "different".into()
        });
        assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Conflict);
    }
    let mut c = create();
    c["request"]["quantity"]["value"] = json!("5");
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Conflict);
    assert_eq!(before, m.checkpoint().unwrap());
}
#[test]
fn complete_lifecycle_pending_cancel_and_exact_partial_fills() {
    let mut m = ready();
    m.apply(&accept(1, 3)).unwrap();
    let mut cancel = local("CANCEL", 4);
    cancel["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-1"},"order_id":{"schema_version":1,"value":"runtime-ORDER-000001"},"reason":"stop","metadata":{}});
    m.apply(&cancel).unwrap();
    let r = m.apply(&fill(2, "10.01", "1")).unwrap();
    assert_eq!(r.result, ApplyResult::Applied);
    assert_eq!(*snapshot(&m).status(), OnlyOrderStatus::PendingCancel);
    m.apply(&fill(3, "10.02", "3")).unwrap();
    let s = snapshot(&m);
    assert_eq!(*s.status(), OnlyOrderStatus::Filled);
    assert_eq!(
        s.average_fill_price().as_ref().unwrap().value().to_string(),
        "10.02"
    );
    assert_eq!(s.cumulative_price_quantity().to_string(), "40.07");
    assert_eq!(m.open("cluster").len(), 0);
}
#[test]
fn duplicate_and_conflicting_fill_never_change_state() {
    let mut m = ready();
    let f = fill(1, "10.01", "1");
    assert_eq!(m.apply(&f).unwrap().result, ApplyResult::Applied);
    let before = m.checkpoint().unwrap();
    assert_eq!(m.apply(&f).unwrap().result, ApplyResult::Duplicate);
    let mut changed = f.clone();
    changed["fill"]["price"]["value"] = json!("10.02");
    assert_eq!(m.apply(&changed).unwrap().result, ApplyResult::Conflict);
    let mut f2 = fill(2, "10.02", "1");
    f2["fill"]["trade_id"] = f["fill"]["trade_id"].clone();
    assert_eq!(m.apply(&f2).unwrap().result, ApplyResult::Conflict);
    assert_eq!(m.checkpoint().unwrap(), before);
}
#[test]
fn fresh_recovery_continues_exactly_and_rejects_splices_atomically() {
    let mut m = ready();
    m.apply(&fill(1, "10.01", "1")).unwrap();
    let (bytes, hash) = m.checkpoint().unwrap();
    let mut restored = Manager::new(config()).unwrap();
    restored.restore(&bytes, &hash).unwrap();
    assert_eq!(restored.checkpoint().unwrap(), m.checkpoint().unwrap());
    m.apply(&fill(2, "10.02", "3")).unwrap();
    restored.apply(&fill(2, "10.02", "3")).unwrap();
    assert_eq!(restored.checkpoint().unwrap(), m.checkpoint().unwrap());
    let before = restored.checkpoint().unwrap();
    let mut record: Value = serde_json::from_slice(&bytes).unwrap();
    record["state"]["orders"][0]["snapshot"]["version"] = json!(99);
    let bad = serde_json::to_vec(&record).unwrap();
    assert!(
        restored
            .restore(&bad, &onlyalpha_order::digest(&bad))
            .is_err()
    );
    assert_eq!(restored.checkpoint().unwrap(), before);
    assert!(restored.restore(&bytes, &"0".repeat(64)).is_err());
}
#[test]
fn unknown_never_becomes_dispatchable_after_restore() {
    let mut m = ready();
    let mut c = local("SUBMIT_RESULT", 3);
    c["outcome"] = json!("UNKNOWN");
    m.apply(&c).unwrap();
    let (bytes, hash) = m.checkpoint().unwrap();
    let mut r = Manager::new(config()).unwrap();
    r.restore(&bytes, &hash).unwrap();
    assert_eq!(
        r.submission("cluster", "runtime-ORDER-000001").unwrap(),
        "UNKNOWN"
    );
    assert_eq!(
        r.apply(&local("BEGIN_SUBMIT", 4)).unwrap().result,
        ApplyResult::Invalid
    );
    r.apply(&accept(1, 5)).unwrap();
    assert_eq!(
        r.submission("cluster", "runtime-ORDER-000001").unwrap(),
        "RESOLVED"
    );
}
#[test]
fn malformed_scopes_out_of_order_overfills_and_terminals_are_unchanged() {
    let mut m = ready();
    let mut foreign = fill(1, "10.00", "1");
    foreign["account_id"] = json!("foreign");
    assert!(m.apply(&foreign).is_err());
    m.apply(&accept(3, 4)).unwrap();
    let before = m.checkpoint().unwrap();
    assert_eq!(m.apply(&accept(2, 3)).unwrap().result, ApplyResult::Stale);
    assert_eq!(
        m.apply(&fill(4, "10.00", "5")).unwrap().result,
        ApplyResult::Invalid
    );
    assert_eq!(m.checkpoint().unwrap(), before);
    m.apply(&external("CANCELLED", 5, 8)).unwrap();
    let before = m.checkpoint().unwrap();
    assert_eq!(
        m.apply(&fill(6, "10.00", "1")).unwrap().result,
        ApplyResult::Invalid
    );
    assert_eq!(m.checkpoint().unwrap(), before);
    assert_eq!(
        m.executable_remaining("cluster", "runtime-ORDER-000001")
            .unwrap()
            .value()
            .to_string(),
        "0"
    );
    assert_eq!(snapshot(&m).remaining_quantity().value().to_string(), "4");
    assert!(m.get("foreign", "runtime-ORDER-000001").is_err());
}
#[test]
fn cancellation_identity_and_fee_validation_are_atomic() {
    let mut m = Manager::new(config()).unwrap();
    m.apply(&create()).unwrap();
    assert_eq!(
        m.apply(&local("BEGIN_SUBMIT", 2)).unwrap().result,
        ApplyResult::Invalid
    );
    let before = m.checkpoint().unwrap();
    let mut wrong = fee();
    wrong["contract"]["funding"]["binding_fingerprint"] = json!("0".repeat(64));
    assert!(m.apply(&wrong).is_err());
    assert_eq!(m.checkpoint().unwrap(), before);
    m.apply(&fee()).unwrap();
    m.apply(&local("BEGIN_SUBMIT", 2)).unwrap();
    let mut cancel = local("CANCEL", 4);
    cancel["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-1"},"order_id":{"schema_version":1,"value":"runtime-ORDER-000001"},"reason":"stop","metadata":{}});
    m.apply(&cancel).unwrap();
    let before = m.checkpoint().unwrap();
    assert_eq!(m.apply(&cancel).unwrap().result, ApplyResult::Duplicate);
    cancel["request"]["reason"] = json!("changed");
    assert_eq!(m.apply(&cancel).unwrap().result, ApplyResult::Conflict);
    assert_eq!(before, m.checkpoint().unwrap());
}
#[test]
fn every_applied_fact_is_scoped_and_monotonically_sequenced() {
    let mut m = Manager::new(config()).unwrap();
    let result = m.apply(&create()).unwrap();
    assert_eq!(result.fact.unwrap()["sequence"], 1);
    assert_eq!(snapshot(&m).to_record()["runtime_id"]["value"], "runtime");
    let result = m.apply(&fee()).unwrap();
    assert_eq!(result.fact.unwrap()["sequence"], 2);
    let before = m.checkpoint().unwrap();
    let mut bad = local("BEGIN_SUBMIT", 0);
    assert_eq!(m.apply(&bad).unwrap().result, ApplyResult::Stale);
    bad["schema_version"] = json!(true);
    assert!(m.apply(&bad).is_err());
    assert_eq!(m.checkpoint().unwrap(), before);
}
#[test]
fn common_vector_outputs() {
    let mut outputs = Vec::new();
    for line in include_str!("../../../../test-data/order/lifecycle-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        let mut m = ready();
        let mut observed = Vec::new();
        for (n, f) in row["fills"].as_array().unwrap().iter().enumerate() {
            assert_eq!(
                m.apply(&fill(
                    n as u64 + 1,
                    f[0].as_str().unwrap(),
                    f[1].as_str().unwrap()
                ))
                .unwrap()
                .result,
                ApplyResult::Applied
            );
            let s = snapshot(&m);
            observed.push(json!([
                s.status().as_str(),
                s.filled_quantity().value().to_string(),
                s.average_fill_price().as_ref().unwrap().value().to_string(),
                s.cumulative_price_quantity().to_string()
            ]));
            let (bytes, hash) = m.checkpoint().unwrap();
            let mut fresh = Manager::new(config()).unwrap();
            fresh.restore(&bytes, &hash).unwrap();
            assert_eq!(fresh.checkpoint().unwrap(), m.checkpoint().unwrap());
            m = fresh;
        }
        assert_eq!(json!(observed), row["expected"]);
        outputs.push(json!({"case":row["case"],"observed":observed}));
    }
    println!("ORDER_VECTOR_OUTPUT {}", json!(outputs));
}
#[test]
fn facts_bind_input_cause_and_submit_outcome() {
    let mut m = Manager::new(config()).unwrap();
    let c = create();
    let f = m.apply(&c).unwrap().fact.unwrap();
    assert_eq!(f["cause"], c["cause"]);
    assert_eq!(
        f["input_fingerprint"],
        onlyalpha_order::digest(c.to_string().as_bytes())
    );
    assert_eq!(f["submission_outcome"], "NOT_DISPATCHED");
}
#[test]
fn external_proof_requires_exact_runtime_gateway_and_generation() {
    let mut m = ready();
    let before = m.checkpoint().unwrap();
    for key in ["runtime_id", "gateway_id", "generation"] {
        let mut c = accept(1, 3);
        c.as_object_mut().unwrap().remove(key);
        assert!(m.apply(&c).is_err());
        let mut c = accept(1, 3);
        c[key] = json!("foreign");
        assert!(m.apply(&c).is_err());
    }
    assert_eq!(m.checkpoint().unwrap(), before);
}
#[test]
fn all_terminal_variants_keep_fills_and_never_regress() {
    for op in ["CANCELLED", "REJECTED", "EXPIRED", "FAILED"] {
        let mut m = ready();
        m.apply(&fill(1, "10.01", "1")).unwrap();
        let mut c = external(op, 2, 8);
        if op == "REJECTED" {
            c["rejection"] =
                json!({"schema_version":1,"code":"VENUE","message":"definitive rejection"});
        }
        if op == "FAILED" {
            c["failure"] =
                json!({"schema_version":1,"code":"VENUE","message":"definitive failure"});
        }
        assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Applied);
        let s = snapshot(&m);
        assert_eq!(s.filled_quantity().value().to_string(), "1");
        assert_eq!(s.remaining_quantity().value().to_string(), "3");
        assert_eq!(s.cumulative_price_quantity().to_string(), "10.01");
        let before = m.checkpoint().unwrap();
        assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Duplicate);
        assert_eq!(
            m.apply(&fill(3, "10.00", "1")).unwrap().result,
            ApplyResult::Invalid
        );
        assert_eq!(before, m.checkpoint().unwrap());
    }
}
#[test]
fn lost_dispatch_ack_and_cancel_are_recoverable_without_new_order() {
    let m = ready();
    let (bytes, hash) = m.checkpoint().unwrap();
    let mut r = Manager::new(config()).unwrap();
    r.restore(&bytes, &hash).unwrap();
    assert_eq!(
        r.submission("cluster", "runtime-ORDER-000001").unwrap(),
        "DISPATCHING"
    );
    assert_eq!(
        r.apply(&local("BEGIN_SUBMIT", 3)).unwrap().result,
        ApplyResult::Invalid
    );
    let mut c = local("SUBMIT_RESULT", 4);
    c["outcome"] = json!("UNKNOWN");
    r.apply(&c).unwrap();
    assert_eq!(
        r.apply(&local("RECONCILE", 5)).unwrap().result,
        ApplyResult::Applied
    );
    let before = r.checkpoint().unwrap();
    c["at"] = json!(6);
    c["outcome"] = json!("SUPPRESSED");
    assert_eq!(r.apply(&c).unwrap().result, ApplyResult::Invalid);
    assert_eq!(before, r.checkpoint().unwrap());
    assert_eq!(
        r.apply(&create())
            .unwrap()
            .snapshot
            .unwrap()
            .order_id()
            .value(),
        "runtime-ORDER-000001"
    );
}
#[test]
fn malformed_recovery_contexts_counters_journal_and_nested_relations_preserve_receiver() {
    let mut source = ready();
    source.apply(&fill(1, "10.00", "1")).unwrap();
    let (bytes, hash) = source.checkpoint().unwrap();
    let clean: Value = serde_json::from_slice(&bytes).unwrap();
    let mut receiver = ready();
    receiver.apply(&fill(2, "12.00", "2")).unwrap();
    let before = receiver.checkpoint().unwrap();
    let mut bads = Vec::new();
    let mut c = clean.clone();
    c["config"]["runtime_id"] = json!("other");
    bads.push(c);
    let mut c = clean.clone();
    c["state"]["sequence"] = json!(999);
    bads.push(c);
    let mut c = clean.clone();
    let duplicate = c["journal"][0].clone();
    c["journal"].as_array_mut().unwrap().push(duplicate);
    bads.push(c);
    let mut c = clean.clone();
    c["journal"][0]["account_id"] = json!("other");
    bads.push(c);
    let mut c = clean.clone();
    c["state"]["orders"][0]["submission"] = json!("NOT_DISPATCHED");
    bads.push(c);
    let mut c = clean.clone();
    c["journal"][3]["fill"]["venue_trade_id"]["value"] = json!("other");
    bads.push(c);
    for c in bads {
        let bad = serde_json::to_vec(&c).unwrap();
        assert!(
            receiver
                .restore(&bad, &onlyalpha_order::digest(&bad))
                .is_err()
        );
        assert_eq!(receiver.checkpoint().unwrap(), before);
    }
    let mut noncanonical = bytes.clone();
    noncanonical.push(b' ');
    assert!(
        receiver
            .restore(&noncanonical, &onlyalpha_order::digest(&noncanonical))
            .is_err()
    );
    assert_eq!(receiver.checkpoint().unwrap(), before);
    let mut other=Manager::new(json!({"schema_version":1,"engine_id":"other","runtime_id":"runtime","gateway_id":"gateway","generation":"a".repeat(64)})).unwrap();
    assert!(other.restore(&bytes, &hash).is_err());
}
#[test]
fn fill_precision_arithmetic_bounds_and_equal_sequence_conflicts_are_atomic() {
    let mut m = ready();
    m.apply(&accept(1, 3)).unwrap();
    let before = m.checkpoint().unwrap();
    let mut c = fill(2, "10.00", "1");
    c["fill"]["quantity"]["precision"] = json!(1);
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Invalid);
    let mut c = fill(2, "1E+999999999", "1");
    c["fill"]["price"]["precision"] = json!(2);
    assert!(m.apply(&c).is_err());
    let mut c = external("CANCELLED", 1, 6);
    c["event_id"] = json!("different");
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Conflict);
    assert_eq!(m.checkpoint().unwrap(), before);
}
#[test]
fn generations_runtime_scopes_and_generated_counters_are_isolated() {
    let m = ready();
    let (bytes, hash) = m.checkpoint().unwrap();
    let mut restored = Manager::new(config()).unwrap();
    restored.restore(&bytes, &hash).unwrap();
    let mut c = create();
    c["request"]["request_id"]["value"] = json!("request-2");
    let r = restored.apply(&c).unwrap();
    assert_eq!(
        r.snapshot.unwrap().order_id().value(),
        "runtime-ORDER-000002"
    );
    assert_eq!(
        restored.recent("cluster", 1).unwrap()[0]
            .client_order_id()
            .value(),
        "runtime-CLIENT-000002"
    );
    assert_eq!(restored.open("cluster").len(), 2);
    assert_eq!(restored.open("other").len(), 0);
    assert!(restored.recent("cluster", 0).is_err());
    let mut other = config();
    other["generation"] = json!("b".repeat(64));
    let mut foreign = Manager::new(other).unwrap();
    assert!(foreign.restore(&bytes, &hash).is_err());
}
#[test]
fn duplicate_create_after_expiry_and_cancel_after_later_fill_are_idempotent() {
    let mut m = Manager::new(config()).unwrap();
    let mut c = create();
    c["request"]["time_in_force"] = json!("GTD");
    c["request"]["expire_time"] = json!({"schema_version":1,"unix_nanos":10});
    m.apply(&c).unwrap();
    let before = m.checkpoint().unwrap();
    c["at"] = json!(20);
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Duplicate);
    assert_eq!(before, m.checkpoint().unwrap());
    let mut m = ready();
    let mut c = local("CANCEL", 3);
    c["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-1"},"order_id":{"schema_version":1,"value":"runtime-ORDER-000001"},"reason":"stop","metadata":{}});
    m.apply(&c).unwrap();
    m.apply(&fill(1, "10.00", "1")).unwrap();
    let before = m.checkpoint().unwrap();
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Duplicate);
    assert_eq!(before, m.checkpoint().unwrap());
}
#[test]
fn noncanonical_contexts_and_exhausted_bounds_are_fail_closed() {
    let mut c = config();
    c["runtime_id"] = json!(" runtime");
    assert!(Manager::new(c).is_err());
    let mut m = Manager::new(config()).unwrap();
    let mut c = create();
    c["cluster_id"] = json!(" cluster");
    assert!(m.apply(&c).is_err());
    let before = m.checkpoint().unwrap();
    c = create();
    c["request"]["metadata"]["large"] = json!("x".repeat(32768));
    assert!(m.apply(&c).is_err());
    assert_eq!(before, m.checkpoint().unwrap());
    for n in 0..64 {
        let mut c = create();
        c["request"]["request_id"]["value"] = json!(format!("request-{n}"));
        m.apply(&c).unwrap();
    }
    let before = m.checkpoint().unwrap();
    let mut c = create();
    c["request"]["request_id"]["value"] = json!("request-over-limit");
    assert!(m.apply(&c).is_err());
    assert_eq!(before, m.checkpoint().unwrap());
}
#[test]
fn venue_and_trade_identity_cannot_move_between_orders() {
    let mut m = ready();
    m.apply(&accept(1, 3)).unwrap();
    m.apply(&fill(2, "10.00", "1")).unwrap();
    let mut c = create();
    c["request"]["request_id"]["value"] = json!("request-2");
    m.apply(&c).unwrap();
    let mut c = local("FEE", 1);
    c["order_id"] = json!("runtime-ORDER-000002");
    c["contract"] = fixture()["second_fee_contract"].clone();
    c["contract"]["schema_version"] = json!(1);
    m.apply(&c).unwrap();
    let mut c = local("BEGIN_SUBMIT", 2);
    c["order_id"] = json!("runtime-ORDER-000002");
    m.apply(&c).unwrap();
    let before = m.checkpoint().unwrap();
    let mut c = accept(1, 3);
    c["order_id"] = json!("runtime-ORDER-000002");
    c["event_id"] = json!("second-ack");
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Conflict);
    assert_eq!(before, m.checkpoint().unwrap());
    c["venue_order_id"] = json!("venue-2");
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Applied);
    let before = m.checkpoint().unwrap();
    let mut c = fill(3, "10.00", "1");
    c["order_id"] = json!("runtime-ORDER-000002");
    c["fill"]["order_id"]["value"] = json!("runtime-ORDER-000002");
    c["fill"]["venue_order_id"]["value"] = json!("venue-2");
    c["fill"]["venue_trade_id"]["value"] = json!("venue-trade-2");
    assert_eq!(m.apply(&c).unwrap().result, ApplyResult::Conflict);
    assert_eq!(before, m.checkpoint().unwrap());
}

#[test]
fn same_terminal_status_with_different_reason_is_not_a_duplicate() {
    for (op, field) in [("REJECTED", "rejection"), ("FAILED", "failure")] {
        let mut m = ready();
        let mut first = external(op, 1, 3);
        first[field] = json!({"schema_version":1,"code":"VENUE","message":"original reason"});
        assert_eq!(m.apply(&first).unwrap().result, ApplyResult::Applied);
        let before = m.checkpoint().unwrap();
        let mut changed = external(op, 2, 4);
        changed[field] = json!({"schema_version":1,"code":"OTHER","message":"different reason"});
        assert_eq!(m.apply(&changed).unwrap().result, ApplyResult::Conflict);
        assert_eq!(m.checkpoint().unwrap(), before);
    }
}

#[test]
fn unseen_cancel_request_is_not_certified_duplicate_while_pending() {
    for restart in [false, true] {
        let mut m = ready();
        let mut first = local("CANCEL", 3);
        first["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-1"},"order_id":{"schema_version":1,"value":"runtime-ORDER-000001"},"reason":"original","metadata":{}});
        assert_eq!(m.apply(&first).unwrap().result, ApplyResult::Applied);
        if restart {
            let (bytes, hash) = m.checkpoint().unwrap();
            let mut fresh = Manager::new(config()).unwrap();
            fresh.restore(&bytes, &hash).unwrap();
            m = fresh;
        }
        let before = m.checkpoint().unwrap();
        let mut second = first.clone();
        second["at"] = json!(4);
        second["request"]["request_id"]["value"] = json!("cancel-2");
        second["request"]["reason"] = json!("new request");
        assert_eq!(m.apply(&second).unwrap().result, ApplyResult::Invalid);
        second["request"]["metadata"]["changed"] = json!("yes");
        assert_eq!(m.apply(&second).unwrap().result, ApplyResult::Invalid);
        assert_eq!(m.apply(&first).unwrap().result, ApplyResult::Duplicate);
        assert_eq!(m.checkpoint().unwrap(), before);
    }
}

#[test]
fn fee_numeric_bounds_precede_arithmetic_bearing_domain_decoding() {
    let mut m = Manager::new(config()).unwrap();
    m.apply(&create()).unwrap();
    let before = m.checkpoint().unwrap();
    let mut c = fee();
    for key in ["principal_reservation", "total_reservation"] {
        c["contract"]["funding"][key]["amount"] = json!("1E+257");
    }
    // This safe exponent demonstrates the missing bound without requesting destructive allocation.
    assert!(m.apply(&c).is_err());
    assert_eq!(m.checkpoint().unwrap(), before);
}

#[test]
fn noncanonical_event_alias_cannot_apply_a_second_fill_fresh_or_restored() {
    for restart in [false, true] {
        let mut m = ready();
        let mut first = fill(1, "10.00", "1");
        first["sequence"] = Value::Null;
        first["fill"]["external_sequence"] = Value::Null;
        first["fill"]["venue_trade_id"] = Value::Null;
        assert_eq!(m.apply(&first).unwrap().result, ApplyResult::Applied);
        if restart {
            let (bytes, hash) = m.checkpoint().unwrap();
            let mut fresh = Manager::new(config()).unwrap();
            fresh.restore(&bytes, &hash).unwrap();
            m = fresh;
        }
        let before = m.checkpoint().unwrap();
        let mut second = fill(2, "10.02", "1");
        second["sequence"] = Value::Null;
        second["fill"]["external_sequence"] = Value::Null;
        second["fill"]["venue_trade_id"] = Value::Null;
        second["event_id"] = json!(" event-1");
        second["fill"]["external_event_id"] = json!(" event-1");
        assert!(m.apply(&second).is_err());
        assert_eq!(m.checkpoint().unwrap(), before);
    }
}
