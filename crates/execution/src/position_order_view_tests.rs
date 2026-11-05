//! This query is data only; every call retains the original owning source guard.
use super::*;
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../tests/support/mod.rs"]
mod support;
use support::{Harness, config, fill, open, stage};
fn current_view(c: &Components, s: &support::MemoryStore) -> Result<Value, Error> {
    c.position_order_view(s)
}
fn configuration(modern: bool) -> Value {
    let mut c = config();
    if modern {
        c["schema_version"] = json!(2);
        c["account_checkpoint_version"] = json!(5);
    }
    c
}
fn apply(h: &mut Harness, input: &Value) {
    let p = h.prepare(input).unwrap();
    crate::coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
#[test]
fn position_order_view_matches_complete_actual_genesis_fill_and_valuation_without_full_state() {
    for modern in [false, true] {
        let mut h = Harness::new(configuration(modern)).unwrap();
        for cut in 0..=4 {
            let state = h.state().unwrap();
            let checkpoint = h.components.checkpoint().unwrap();
            let active = checkpoint["components"][0]["state"]["orders"]
                .as_array()
                .unwrap()
                .iter()
                .filter(|row| {
                    !matches!(
                        row["snapshot"]["status"].as_str(),
                        Some("FILLED" | "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED")
                    )
                })
                .map(|row| row["snapshot"]["order_id"]["value"].clone())
                .collect::<Vec<_>>();
            let expected = json!({"schema_version":2,"active_order_ids":active,"orders":state["execution"]["orders"],"position_accounts":state["position"]["accounts"],"position_allocations":state["position"]["allocations"],"economic_version":state["account"]["snapshot"]["economic_version"],"position_checkpoint_fingerprint":digest(h.components.position.checkpoint().unwrap().0.as_slice())});
            let rows = h.store.rows.clone();
            FULL_STATE_CONSTRUCTIONS.with(|n| n.set(0));
            let mut actual = current_view(&h.components, &h.store).unwrap();
            assert_eq!(
                FULL_STATE_CONSTRUCTIONS.with(std::cell::Cell::get),
                0,
                "a small current query built complete Ledger/Account history at format{modern} cut{cut}"
            );
            assert_eq!(actual, expected);
            assert_eq!(
                actual["position_checkpoint_fingerprint"],
                hash(&checkpoint["components"][1])
            );
            actual["orders"] = json!({"detached":true});
            actual["position_accounts"] = json!([]);
            assert_eq!(h.components.checkpoint().unwrap(), checkpoint);
            assert_eq!(
                h.store.rows, rows,
                "read-only query cannot mark/append/ack any source"
            );
            match cut {
                0 => apply(&mut h, &open(1, "BUY")),
                1 => apply(&mut h, &stage(2, 1, "UNKNOWN")),
                2 => apply(&mut h, &fill(3, 1, "1", "10.00", "1.00")),
                3 => {
                    let valuation = support::input(
                        4,
                        "VALUATION",
                        json!({"schema_version":1,"valuation":"view-valuation","version":1,"position_evidence":expected["position_checkpoint_fingerprint"],"economic_version":expected["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":"view-mark","family":"CLOSED_BAR","version":1,"time":4,"as_of_sequence":4}]}),
                    );
                    apply(&mut h, &valuation);
                }
                _ => {}
            }
        }
    }
}
#[test]
fn position_order_view_rejects_the_same_missing_foreign_and_unready_source_without_effects() {
    for modern in [false, true] {
        let mut h = Harness::new(configuration(modern)).unwrap();
        for input in [
            open(1, "BUY"),
            stage(2, 1, "UNKNOWN"),
            fill(3, 1, "1", "10.00", "1.00"),
        ] {
            apply(&mut h, &input);
        }
        let checkpoint = h.components.checkpoint().unwrap();
        let original = h.store.rows.clone();
        let mut foreign = Harness::new(configuration(modern)).unwrap();
        let mut changed = open(1, "BUY");
        changed["source_ref"] = json!("foreign-original-source");
        for input in [
            changed,
            stage(2, 1, "UNKNOWN"),
            fill(3, 1, "1", "10.00", "1.00"),
        ] {
            apply(&mut foreign, &input);
        }
        for fault in ["missing", "foreign", "unready"] {
            h.store.rows = original.clone();
            match fault {
                "missing" => {
                    h.store.rows.pop();
                }
                "foreign" => h.store.rows = foreign.store.rows.clone(),
                "unready" => {
                    let mut raw = h.store.rows.last().unwrap().record();
                    raw["ready"] = json!(false);
                    raw["delivered"] = json!(false);
                    *h.store.rows.last_mut().unwrap() = crate::Record::decode(&raw).unwrap();
                }
                _ => unreachable!(),
            }
            let actual_rows = h.store.rows.clone();
            let legacy = h.state().unwrap_err();
            assert_eq!(
                current_view(&h.components, &h.store).unwrap_err(),
                legacy,
                "source guard {fault}"
            );
            assert_eq!(h.store.rows, actual_rows);
            assert_eq!(h.components.checkpoint().unwrap(), checkpoint);
        }
        h.store.rows = original;
        let p = h.prepare(&support::terminal(4, 1, "CANCELLED")).unwrap();
        h.commit_only(&p).unwrap();
        let rows = h.store.rows.clone();
        let legacy = h.state().unwrap_err();
        assert_eq!(current_view(&h.components, &h.store).unwrap_err(), legacy);
        assert_eq!(h.store.rows, rows);
    }
}

#[test]
fn one_position_order_query_includes_complete_activity_and_keeps_unknown_active() {
    for modern in [false, true] {
        let mut h = Harness::new(configuration(modern)).unwrap();
        let empty = current_view(&h.components, &h.store).unwrap();
        assert_eq!(empty["schema_version"], 2);
        assert_eq!(empty["active_order_ids"], json!([]));
        apply(&mut h, &open(1, "BUY"));
        apply(&mut h, &stage(2, 1, "UNKNOWN"));
        assert_eq!(
            current_view(&h.components, &h.store).unwrap()["active_order_ids"],
            json!(["runtime-ORDER-000001"]),
            "UNKNOWN submit is not a terminal Order"
        );
        apply(&mut h, &fill(3, 1, "1", "10.00", "1.00"));
        assert_eq!(
            current_view(&h.components, &h.store).unwrap()["active_order_ids"],
            json!(["runtime-ORDER-000001"])
        );
        apply(&mut h, &support::terminal(4, 1, "CANCELLED"));
        let closed = current_view(&h.components, &h.store).unwrap();
        assert_eq!(closed["active_order_ids"], json!([]));
        assert_eq!(
            closed["orders"].as_object().unwrap().len(),
            1,
            "completed Order history is retained"
        );
    }
}

#[test]
fn activity_classification_preserves_every_canonical_order_status() {
    use onlyalpha_domain::execution::OnlyOrderSnapshot;
    let mut h = Harness::new(configuration(true)).unwrap();
    apply(&mut h, &open(1, "BUY"));
    let created = h
        .components
        .order
        .get("cluster", "runtime-ORDER-000001")
        .unwrap()
        .to_record();
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    apply(&mut h, &fill(3, 1, "1", "10.00", "1.00"));
    let partial = h
        .components
        .order
        .get("cluster", "runtime-ORDER-000001")
        .unwrap()
        .to_record();
    for (status, active) in [
        ("CREATED", true),
        ("SUBMITTED", true),
        ("ACCEPTED", true),
        ("PARTIALLY_FILLED", true),
        ("PENDING_CANCEL", true),
        ("CANCELLED", false),
        ("EXPIRED", false),
        ("FILLED", false),
        ("REJECTED", false),
        ("FAILED", false),
    ] {
        let mut raw = if matches!(status, "PARTIALLY_FILLED" | "FILLED") {
            partial.clone()
        } else {
            created.clone()
        };
        raw["status"] = json!(status);
        if status == "FILLED" {
            raw["filled_quantity"] = raw["quantity"].clone();
            raw["remaining_quantity"]["value"] = json!("0");
            raw["cumulative_price_quantity"] = json!("40");
            raw["filled_at"] = raw["updated_at"].clone();
        }
        let snapshot = OnlyOrderSnapshot::from_record(&raw).unwrap();
        assert_eq!(
            Components::order_snapshot_is_active(&snapshot),
            active,
            "{status}"
        );
    }
    let mut unknown = created;
    unknown["status"] = json!("UNKNOWN");
    assert!(
        OnlyOrderSnapshot::from_record(&unknown).is_err(),
        "unknown raw statuses cannot become certified terminal activity"
    );
}

#[test]
fn activity_query_rejects_incomplete_metadata_owner_relations_even_at_a_hash_matched_head() {
    for fault in ["orphan", "cluster", "missing-cluster", "omitted"] {
        let mut h = Harness::new(configuration(true)).unwrap();
        apply(&mut h, &open(1, "BUY"));
        match fault {
            "orphan" => {
                std::sync::Arc::make_mut(&mut h.components.meta)["orders"]["orphan-order"] =
                    h.components.meta["orders"]["runtime-ORDER-000001"].clone()
            }
            "cluster" => {
                std::sync::Arc::make_mut(&mut h.components.meta)["orders"]["runtime-ORDER-000001"]["cluster"] = json!("foreign")
            }
            "omitted" => std::sync::Arc::make_mut(&mut h.components.meta)["orders"] = json!({}),
            _ => std::sync::Arc::make_mut(&mut h.components.meta)["orders"]["runtime-ORDER-000001"]["cluster"] = Value::Null,
        }
        h.components.invalidate_payloads();
        let mut raw = h.store.rows[0].record();
        raw["prepared"]["projections"][5]["result"] = h.components.meta.as_ref().clone();
        raw["prepared"]["projections"][5]["result_hash"] = json!(hash(&h.components.meta));
        let mut content = raw["prepared"].clone();
        content.as_object_mut().unwrap().remove("payload_hash");
        raw["prepared"]["payload_hash"] = json!(hash(&content));
        h.store.rows[0] = crate::Record::decode(&raw).unwrap();
        h.components.ready_source(&h.store).unwrap();
        let rows = h.store.rows.clone();
        let checkpoint = h.components.checkpoint().unwrap();
        assert!(
            current_view(&h.components, &h.store).is_err(),
            "incomplete {fault} relation became an activity/absence verdict"
        );
        assert_eq!(h.store.rows, rows);
        assert_eq!(h.components.checkpoint().unwrap(), checkpoint);
    }
}
