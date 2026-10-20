const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::{Components, Record, coordinate, recover};
use serde_json::{Value, json};
use support::*;
#[test]
fn every_fill_commits_a_real_settlement_owner() {
    let mut h = Harness::new(config()).unwrap();
    for v in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "10.00", "1.00"),
    ] {
        let p = h.prepare(&v).unwrap();
        coordinate(&mut h.store, &mut h.components, &p).unwrap();
    }
    let s = h.state().unwrap();
    assert!(s["execution"]["settlement_authority"]["instructions"].is_object());
    assert_eq!(
        s["execution"]["settlement_authority"]["instructions"]
            .as_object()
            .unwrap()
            .len(),
        1
    );
}

fn apply(h: &mut Harness, v: &Value) {
    let p = h.prepare(v).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
fn delayed(n: u64, ordinal: u64) -> Value {
    let mut v = fill(
        n,
        ordinal,
        "4",
        if ordinal == 1 { "10.00" } else { "12.00" },
        "1.00",
    );
    let p = &mut v["payload"]["settlement"];
    p["policy"]["id"] = json!("delayed-policy");
    p["policy"]["asset_trade_available"] = json!(1);
    p["policy"]["cash_withdrawable"] = json!(1);
    p["policy"]["legal_settled"] = json!(2);
    p.as_object_mut().unwrap().remove("source_digest");
    p["source_digest"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
    v
}
fn instruction(h: &Harness, trade: &str) -> String {
    let s = h.state().unwrap();
    s["execution"]["settlement_authority"]["instructions"]
        .as_object()
        .unwrap()
        .iter()
        .find(|(_, v)| v["instruction"]["input"]["trade"] == trade)
        .unwrap()
        .0
        .clone()
}
fn maturity(n: u64, id: &str, version: u64, day: &str) -> Value {
    let mut v = input(
        n,
        "SETTLEMENT_MATURITY",
        json!({"schema_version":1,"instruction":id,"expected_version":version}),
    );
    v["trading_day"] = json!(day);
    v["day_index"] = json!(if day == "2026-10-19" {
        1
    } else if day == "2026-10-20" {
        2
    } else {
        3
    });
    v
}
#[test]
fn deferred_asset_and_cash_are_released_once_with_exact_lifecycle() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &open(1, "BUY"));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    apply(&mut h, &delayed(3, 1));
    assert_eq!(
        h.state().unwrap()["position"]["accounts"][0]["snapshot"]["settled"],
        "0"
    );
    assert!(h.prepare(&open(4, "SELL")).is_err());
    let buy = instruction(&h, "trade-3");
    assert!(h.prepare(&maturity(4, &buy, 1, "2026-10-19")).is_err());
    apply(&mut h, &maturity(4, &buy, 1, "2026-10-20"));
    assert_eq!(
        h.state().unwrap()["position"]["accounts"][0]["snapshot"]["settled"],
        "4"
    );
    let mut sell_order = open(5, "SELL");
    sell_order["trading_day"] = json!("2026-10-20");
    sell_order["day_index"] = json!(2);
    apply(&mut h, &sell_order);
    let mut submit = stage(6, 2, "UNKNOWN");
    submit["trading_day"] = json!("2026-10-20");
    submit["day_index"] = json!(2);
    apply(&mut h, &submit);
    let mut sell = delayed(7, 2);
    sell["trading_day"] = json!("2026-10-20");
    sell["day_index"] = json!(2);
    apply(&mut h, &sell);
    let sold = instruction(&h, "trade-7");
    let s = h.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "1006.00");
    assert_eq!(s["account"]["snapshot"]["withdrawable"], "959.00");
    assert_eq!(s["account"]["snapshot"]["unsettled"], "47.00");
    let p = h.prepare(&maturity(8, &sold, 1, "2026-10-21")).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["withdrawable"],
        "1006.00"
    );
    assert!(h.prepare(&maturity(9, &sold, 1, "2026-10-21")).is_err());
    // Legal completion cannot require the old Position still being open.
    apply(&mut h, &maturity(9, &buy, 2, "2026-10-21"));
    let mut duplicate = maturity(10, &buy, 2, "2026-10-21");
    duplicate["time"] = json!(9);
    assert!(h.prepare(&duplicate).is_err());

    let performance = h
        .components
        .performance(
            &h.store,
            &onlyalpha_domain::time::OnlyTimestamp::from_unix_nanos(0.into()),
        )
        .unwrap()
        .record();
    let points = performance["performance"]["timeline"].as_array().unwrap();
    let settled = points.iter().rfind(|p| p["source"] == "SETTLE").unwrap();
    assert_eq!(settled["snapshot"]["withdrawable"], "1006.00");
    assert_eq!(
        performance["performance"]["summary"]["final_equity"],
        "1006.00"
    );
}
#[test]
fn maturity_commit_cuts_preserve_one_effect_and_wrong_scope_is_atomic() {
    for cut in 1..=6 {
        let mut h = Harness::new(config()).unwrap();
        apply(&mut h, &open(1, "BUY"));
        apply(&mut h, &stage(2, 1, "UNKNOWN"));
        apply(&mut h, &delayed(3, 1));
        let id = instruction(&h, "trade-3");
        let v = maturity(4, &id, 1, "2026-10-20");
        let cp = h.checkpoint().unwrap();
        let mut wrong = v.clone();
        wrong["cluster"] = json!("other");
        assert!(h.prepare(&wrong).is_err());
        assert_eq!(h.checkpoint().unwrap(), cp);
        let p = h.prepare(&v).unwrap();
        for i in 0..cut {
            h.install_projection(&p, i).unwrap();
        }
        assert!(h.state().is_err());
        let mut fresh = Components::new(config()).unwrap();
        recover(&mut h.store, &mut fresh).unwrap();
        assert_eq!(
            fresh.state(&h.store).unwrap()["position"]["accounts"][0]["snapshot"]["settled"],
            "4"
        );
        coordinate(&mut h.store, &mut fresh, &p).unwrap();
        assert_eq!(
            fresh.state(&h.store).unwrap()["position"]["accounts"][0]["snapshot"]["settled"],
            "4"
        );
    }
}
#[test]
fn fresh_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_SETTLEMENT_RECOVERY_FILE") else {
        return;
    };
    let value: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let mut store = MemoryStore::default();
    store.rows = value
        .as_array()
        .unwrap()
        .iter()
        .map(|v| Record::decode(v).unwrap())
        .collect();
    let mut c = Components::new(config()).unwrap();
    recover(&mut store, &mut c).unwrap();
    assert_eq!(
        c.state(&store).unwrap()["position"]["accounts"][0]["snapshot"]["settled"],
        "4"
    );
    println!("SETTLEMENT_FRESH_PROCESS_RECOVERY: PASS");
}
#[test]
fn committed_maturity_rehydrates_in_real_fresh_process() {
    let mut h = Harness::new(config()).unwrap();
    apply(&mut h, &open(1, "BUY"));
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    apply(&mut h, &delayed(3, 1));
    let id = instruction(&h, "trade-3");
    let p = h.prepare(&maturity(4, &id, 1, "2026-10-20")).unwrap();
    h.install_projection(&p, 0).unwrap();
    let path = std::env::temp_dir().join(format!(
        "onlyalpha-settlement-recovery-{}.json",
        std::process::id()
    ));
    assert!(!path.exists());
    std::fs::write(
        &path,
        serde_json::to_vec(&h.store.rows.iter().map(Record::record).collect::<Vec<_>>()).unwrap(),
    )
    .unwrap();
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fresh_recovery_child", "--nocapture"])
        .env("ONLYALPHA_SETTLEMENT_RECOVERY_FILE", &path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(
        String::from_utf8_lossy(&output.stdout).contains("SETTLEMENT_FRESH_PROCESS_RECOVERY: PASS")
    );
}
