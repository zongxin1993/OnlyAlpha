//! Inspect the original owning history without an encoding round trip.
use crate::*;
use serde_json::{Value, json};
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../tests/support/mod.rs"]
mod support;
use support::{Harness, config, fill, input, open, stage};
fn apply(h: &mut Harness, value: &Value) {
    let prepared = h.prepare(value).unwrap();
    coordinate(&mut h.store, &mut h.components, &prepared).unwrap();
}
#[test]
fn valuation_metadata_reads_original_history_without_recapturing_account_checkpoint() {
    for modern in [false, true] {
        let mut configuration = config();
        if modern { configuration["schema_version"] = json!(2); configuration["account_checkpoint_version"] = json!(5); }
        let mut h = Harness::new(configuration).unwrap();
        for value in [open(1, "BUY"), stage(2, 1, "UNKNOWN"), fill(3, 1, "1", "10.00", "1.00")] { apply(&mut h, &value); }
        let mut first_mark = Value::Null;
        for n in 4..=6_u64 {
            let view = h.components.position_order_view(&h.store).unwrap();
            let marks = if n == 5 { first_mark.clone() } else {
                json!([{"schema_version":1,"instrument":"600000.XSHG","mark":"12.00","source_ref":format!("history-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}])
            };
            if n == 4 { first_mark = marks.clone(); }
            let value = input(n, "VALUATION", json!({"schema_version":1,"valuation":format!("history-{n}"),"version":n,"position_evidence":view["position_checkpoint_fingerprint"],"economic_version":view["economic_version"],"marks":marks}));
            apply(&mut h, &value);
        }
        let before = h.components.checkpoint().unwrap();
        let rows = h.store.rows.clone();
        let metadata = h.components.meta.clone();
        super::VALUATION_HISTORY_ACCOUNT_CAPTURES.with(|count| count.set(0));
        for _ in 0..3 { h.components.validate_valuation_metadata(&metadata).unwrap(); }
        for field in ["valuation_marks", "valuation_sources"] {
            let mut changed = metadata.clone(); changed[field] = json!({});
            assert_eq!(h.components.validate_valuation_metadata(&changed).unwrap_err().0, "EXECUTION_VALUATION_HISTORY_MISMATCH");
        }
        assert_eq!(super::VALUATION_HISTORY_ACCOUNT_CAPTURES.with(std::cell::Cell::get), 0,
            "metadata inspection encoded the complete owning Account journal at format{modern}");
        assert_eq!(h.components.checkpoint().unwrap(), before);
        assert_eq!(h.store.rows, rows);
        let mut fresh = Components::new(h.components.config.clone()).unwrap();
        fresh.restore(&before, &digest(before.to_string().as_bytes())).unwrap();
        fresh.validate_valuation_metadata(&metadata).unwrap();
        assert_eq!(fresh.checkpoint().unwrap(), before);
    }
}
