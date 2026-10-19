const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::{Components, coordinate, recover};
use serde_json::{Value, json};
use support::*;
fn apply(h: &mut Harness, v: &Value) {
    let p = h.prepare(v).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
#[test]
fn fee_owner_is_committed_with_cash_and_recovered_from_every_projection_cut() {
    for cut in 1..=6 {
        let mut h = Harness::new(config()).unwrap();
        apply(&mut h, &open(1, "BUY"));
        apply(&mut h, &stage(2, 1, "UNKNOWN"));
        let p = h.prepare(&fill(3, 1, "1", "10.00", "1.00")).unwrap();
        let fee = &p.record()["projections"][5]["result"]["fee_authority"];
        assert_eq!(fee["history"].as_array().unwrap().len(), 1);
        assert!(
            p.record()["projections"][5]["result"]["orders"][order(1)]
                .get("charge_target")
                .is_none()
        );
        h.install_projection(&p, 0).unwrap();
        for i in 1..cut {
            h.install_projection(&p, i).unwrap();
        }
        assert!(h.state().is_err());
        let mut fresh = Components::new(config()).unwrap();
        recover(&mut h.store, &mut fresh).unwrap();
        assert_eq!(
            fresh.state(&h.store).unwrap()["account"]["snapshot"]["cash"],
            "989.00"
        );
        let p = fresh
            .prepare(&h.store, &fill(4, 1, "3", "10.00", "1.00"))
            .unwrap();
        coordinate(&mut h.store, &mut fresh, &p).unwrap();
        assert_eq!(
            fresh.state(&h.store).unwrap()["account"]["snapshot"]["cash"],
            "959.00"
        );
    }
}
#[test]
fn negative_fee_delta_and_changed_source_are_atomic() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &open(1, "BUY"));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    apply(&mut h, &fill(3, 1, "1", "10.00", "1.00"));
    let before = h.checkpoint().unwrap();
    assert!(h.prepare(&fill(4, 1, "1", "10.00", "0.50")).is_err());
    assert_eq!(h.checkpoint().unwrap(), before);
    let mut wrong = fill(4, 1, "1", "10.00", "1.00");
    wrong["payload"]["fees"]["scope"]["request"] = json!("other");
    assert!(h.prepare(&wrong).is_err());
    assert_eq!(h.checkpoint().unwrap(), before);
}
