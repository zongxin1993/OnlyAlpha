const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::{Components, Record, coordinate, recover};
use serde_json::{Value, json};
use support::*;
fn apply(h: &mut Harness, v: &Value) {
    let p = h.prepare(v).unwrap();
    coordinate(&mut h.store, &mut h.components, &p).unwrap();
}
fn loaded() -> Harness {
    let mut h = Harness::new(config()).unwrap();
    for v in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "4", "10.00", "1.00"),
    ] {
        apply(&mut h, &v);
    }
    h
}
fn valuation(h: &Harness, n: u64, mark: &str) -> Value {
    let s = h.state().unwrap();
    input(
        n,
        "VALUATION",
        json!({"schema_version":1,"valuation":format!("valuation-{n}"),"version":n,"position_evidence":onlyalpha_execution::digest(h.checkpoint().unwrap()["components"][1].to_string().as_bytes()),"economic_version":s["account"]["snapshot"]["economic_version"],"marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":mark,"source_ref":format!("mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]}),
    )
}
#[test]
fn market_only_valuation_changes_equity_without_trade_or_cash() {
    let mut h = loaded();
    let before = h.state().unwrap();
    let v = valuation(&h, 4, "12.00");
    apply(&mut h, &v);
    let after = h.state().unwrap();
    assert_eq!(after["account"]["snapshot"]["market_value"], "48.00");
    assert_eq!(after["account"]["snapshot"]["unrealized_pnl"], "8.00");
    assert_eq!(
        after["account"]["snapshot"]["cash"],
        before["account"]["snapshot"]["cash"]
    );
    assert_eq!(after["position"], before["position"]);
}

#[test]
fn malformed_source_inputs_never_mutate_any_authority() {
    let h = loaded();
    let before = h.checkpoint().unwrap();
    let v = valuation(&h, 4, "12.00");
    let mut bad = vec![];
    for key in [
        "position_evidence",
        "marks",
        "economic_version",
        "valuation",
        "version",
    ] {
        let mut x = v.clone();
        x["payload"].as_object_mut().unwrap().remove(key);
        bad.push(x);
    }
    for key in [
        "source_ref",
        "family",
        "instrument",
        "mark",
        "time",
        "version",
        "as_of_sequence",
    ] {
        let mut x = v.clone();
        x["payload"]["marks"][0]
            .as_object_mut()
            .unwrap()
            .remove(key);
        bad.push(x);
    }
    for (key, val) in [
        ("family", json!("FILL")),
        ("instrument", json!("other.XSHG")),
        ("mark", json!("0")),
        ("time", json!(5)),
        ("time", json!(2)),
        ("as_of_sequence", json!(5)),
        ("version", json!(0)),
    ] {
        let mut x = v.clone();
        x["payload"]["marks"][0][key] = val;
        bad.push(x);
    }
    let mut x = v.clone();
    x["payload"]["position_evidence"] = json!("b".repeat(64));
    bad.push(x);
    let mut x = v.clone();
    x["payload"]["economic_version"] = json!(0);
    bad.push(x);
    let mut x = v.clone();
    x["payload"]["marks"] = json!([]);
    bad.push(x);
    let mut x = v.clone();
    x["payload"]["marks"] = json!([v["payload"]["marks"][0], v["payload"]["marks"][0]]);
    bad.push(x);
    let mut x = v.clone();
    x["payload"]["market_value"] = json!("999999.00");
    bad.push(x);
    for (i, x) in bad.iter().enumerate() {
        assert!(h.prepare(x).is_err(), "mutation {i}");
        assert_eq!(h.checkpoint().unwrap(), before);
    }
}
#[test]
fn old_mark_versions_and_reused_sources_fail_closed() {
    let mut h = loaded();
    let v = valuation(&h, 4, "12.00");
    apply(&mut h, &v);
    let before = h.checkpoint().unwrap();
    for field in ["version", "as_of_sequence", "source_ref"] {
        let mut next = valuation(&h, 5, "13.00");
        next["payload"]["marks"][0][field] = v["payload"]["marks"][0][field].clone();
        assert!(h.prepare(&next).is_err());
        assert_eq!(h.checkpoint().unwrap(), before);
    }
    let mut next = valuation(&h, 5, "13.00");
    next["payload"]["version"] = json!(4);
    assert!(h.prepare(&next).is_err());
    let next = valuation(&h, 5, "13.00");
    apply(&mut h, &next);
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["market_value"],
        "52.00"
    );
}
#[test]
fn empty_account_requires_complete_empty_source_and_replays() {
    let mut h = Harness::new(config()).unwrap();
    let mut v = valuation(&h, 1, "12.00");
    v["payload"]["marks"] = json!([]);
    apply(&mut h, &v);
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["equity"],
        "1000.00"
    );
    let mut fresh = Components::new(config()).unwrap();
    recover(&mut h.store, &mut fresh).unwrap();
    assert_eq!(fresh.state(&h.store).unwrap(), h.state().unwrap());
}
#[test]
fn every_valuation_commit_cut_hides_prefix_and_recovers_identically() {
    for cut in 0..=6 {
        let mut h = loaded();
        let v = valuation(&h, 4, "12.00");
        let p = h.prepare(&v).unwrap();
        if cut == 0 {
            // Before commit is not an accepted valuation.
            assert_eq!(
                h.state().unwrap()["account"]["snapshot"]["market_value"],
                "40.00"
            );
            continue;
        }
        for i in 0..cut {
            h.install_projection(&p, i).unwrap();
        }
        assert!(h.state().is_err());
        let cp = h.checkpoint().unwrap();
        let mut checkpointed = Components::new(config()).unwrap();
        checkpointed
            .restore(&cp, &onlyalpha_execution::digest(cp.to_string().as_bytes()))
            .unwrap();
        assert!(checkpointed.state(&h.store).is_err());
        recover(&mut h.store, &mut checkpointed).unwrap();
        assert_eq!(
            checkpointed.state(&h.store).unwrap()["account"]["snapshot"]["market_value"],
            "48.00"
        );
        let mut fresh = Components::new(config()).unwrap();
        recover(&mut h.store, &mut fresh).unwrap();
        coordinate(&mut h.store, &mut fresh, &p).unwrap();
        let a = fresh.state(&h.store).unwrap();
        assert_eq!(a["account"]["snapshot"]["market_value"], "48.00");
        let mut again = Components::new(config()).unwrap();
        recover(&mut h.store, &mut again).unwrap();
        assert_eq!(again.state(&h.store).unwrap(), a);
    }
}
#[test]
fn fresh_valuation_recovery_child() {
    let Ok(path) = std::env::var("ONLYALPHA_VALUATION_RECOVERY_FILE") else {
        return;
    };
    let v: Value = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    let mut store = MemoryStore::default();
    store.rows = v
        .as_array()
        .unwrap()
        .iter()
        .map(|r| Record::decode(r).unwrap())
        .collect();
    let mut c = Components::new(config()).unwrap();
    recover(&mut store, &mut c).unwrap();
    assert_eq!(
        c.state(&store).unwrap()["account"]["snapshot"]["market_value"],
        "48.00"
    );
    println!("VALUATION_FRESH_PROCESS_RECOVERY: PASS");
}
#[test]
fn committed_valuation_recovers_from_real_file_in_new_process() {
    let mut h = loaded();
    let p = h.prepare(&valuation(&h, 4, "12.00")).unwrap();
    h.install_projection(&p, 0).unwrap();
    let path = std::env::temp_dir().join(format!(
        "onlyalpha-valuation-recovery-{}.json",
        std::process::id()
    ));
    assert!(!path.exists());
    std::fs::write(
        &path,
        serde_json::to_vec(&h.store.rows.iter().map(Record::record).collect::<Vec<_>>()).unwrap(),
    )
    .unwrap();
    let out = std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "fresh_valuation_recovery_child", "--nocapture"])
        .env("ONLYALPHA_VALUATION_RECOVERY_FILE", &path)
        .output()
        .unwrap();
    std::fs::remove_file(path).unwrap();
    assert!(
        out.status.success(),
        "{} {}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(
        String::from_utf8_lossy(&out.stdout).contains("VALUATION_FRESH_PROCESS_RECOVERY: PASS")
    );
}

#[test]
fn two_clusters_use_common_marks_and_their_own_costs() {
    let mut cfg = config();
    cfg["capitals"] = json!({"cluster":"500.00","other":"500.00"});
    cfg["profiles"]["other"] = cfg["profiles"]["cluster"].clone();
    let mut h = Harness::new(cfg).unwrap();
    for v in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "4", "5.00", "1.00"),
    ] {
        apply(&mut h, &v);
    }
    let contract: Value = serde_json::from_str(include_str!(
        "../../../../test-data/position/valuation-order-contract.json"
    ))
    .unwrap();
    let mut v = open(4, "BUY");
    v["cluster"] = json!("other");
    v["payload"]["order"] = json!(order(2));
    v["payload"]["request"]["request_id"]["value"] = json!("request-2");
    v["payload"]["fee_contract"] = contract.clone();
    refresh_market(&mut v);
    apply(&mut h, &v);
    let mut v = stage(5, 2, "UNKNOWN");
    v["cluster"] = json!("other");
    apply(&mut h, &v);
    let mut v = fill(6, 2, "4", "10.00", "1.00");
    v["cluster"] = json!("other");
    for key in ["fees", "settlement", "valuation"] {
        let p = &mut v["payload"][key];
        p["scope"]["cluster"] = json!("other");
        if key == "fees" {
            p["policy"] = contract["binding"]["fingerprint"].clone();
        }
        p.as_object_mut().unwrap().remove("source_digest");
        p["source_digest"] = json!(onlyalpha_execution::digest(p.to_string().as_bytes()));
    }
    apply(&mut h, &v);
    let before = h.state().unwrap();
    let v = valuation(&h, 7, "12.00");
    apply(&mut h, &v);
    let s = h.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["market_value"], "96.00");
    assert_eq!(s["account"]["snapshot"]["unrealized_pnl"], "36.00");
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["unrealized_pnl"],
        "28.00"
    );
    assert_eq!(
        s["ledger"]["ledgers"]["other"]["snapshot"]["unrealized_pnl"],
        "8.00"
    );
    assert_eq!(s["position"], before["position"]);
    for cluster in ["cluster", "other"] {
        assert_eq!(
            s["ledger"]["ledgers"][cluster]["entries"],
            before["ledger"]["ledgers"][cluster]["entries"]
        );
        assert_eq!(
            s["ledger"]["ledgers"][cluster]["fee_entries"],
            before["ledger"]["ledgers"][cluster]["fee_entries"]
        );
    }
}
#[test]
fn fractional_cost_residual_is_never_rounded_away_by_revaluation() {
    let mut cfg = config();
    cfg["instruments"][0]["price_precision"] = json!(3);
    let mut h = Harness::new(cfg).unwrap();
    let mut buy = open(1, "BUY");
    buy["payload"]["request"]["price"]["precision"] = json!(3);
    buy["payload"]["request"]["price"]["value"] = json!("10.000");
    refresh_market(&mut buy);
    for v in [
        buy,
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "1", "9.995", "1.00"),
    ] {
        apply(&mut h, &v);
    }
    let before = h.state().unwrap();
    let v = valuation(&h, 4, "9.985");
    apply(&mut h, &v);
    let after = h.state().unwrap();
    assert_eq!(after["account"]["snapshot"]["market_value"], "9.98");
    assert_eq!(after["account"]["snapshot"]["unrealized_pnl"], "-0.015");
    assert_eq!(after["position"], before["position"]);
    assert_eq!(
        after["account"]["snapshot"]["realized_rounding_adjustment"],
        before["account"]["snapshot"]["realized_rounding_adjustment"]
    );
}

#[test]
fn exact_unchanged_mark_fact_can_be_explicitly_reused_at_next_barrier() {
    let mut h = loaded();
    let first = valuation(&h, 4, "12.00");
    apply(&mut h, &first);
    let mut next = valuation(&h, 5, "12.00");
    next["payload"]["marks"] = first["payload"]["marks"].clone();
    apply(&mut h, &next);
    assert_eq!(
        h.state().unwrap()["account"]["snapshot"]["market_value"],
        "48.00"
    );
}
#[test]
fn rehashed_valuation_metadata_cannot_replace_its_source_history() {
    let mut h = loaded();
    let input = valuation(&h, 4, "12.00");
    apply(&mut h, &input);
    let mut cp = h.checkpoint().unwrap();
    cp["components"][5]["valuation_marks"]["600000.XSHG"]["mark"] = json!("999.00");
    let mut fresh = Components::new(config()).unwrap();
    let before = fresh.checkpoint().unwrap();
    assert!(
        fresh
            .restore(&cp, &onlyalpha_execution::digest(cp.to_string().as_bytes()))
            .is_err()
    );
    assert_eq!(fresh.checkpoint().unwrap(), before);
}

#[test]
fn valuation_preserves_unknown_order_collateral_and_all_cash_authorities() {
    let mut h = Harness::new(config()).unwrap();
    let mut v = open(1, "BUY");
    let fixture: Value =
        serde_json::from_str(include_str!("../../../../test-data/margin/common-v1.json")).unwrap();
    let mut c = fixture["reserve"].clone();
    c["scope"]["request"] = json!("request-1");
    c["source_order"] = json!(order(1));
    c["id"] = json!("margin-1");
    c["time"] = json!(1);
    c["source_ref"] = json!("source-1");
    c["quantity"] = json!("4");
    c["amount"] = json!("10.00");
    c.as_object_mut().unwrap().remove("source_fingerprint");
    c["source_fingerprint"] = json!(onlyalpha_execution::digest(c.to_string().as_bytes()));
    v["payload"]["collateral"] =
        json!({"schema_version":1,"kind":"MARGIN","instruction":c,"close_allocation":null});
    apply(&mut h, &v);
    apply(&mut h, &stage(2, 1, "UNKNOWN"));
    let before = h.state().unwrap();
    let cp = h.checkpoint().unwrap();
    let mut v = valuation(&h, 3, "12.00");
    v["payload"]["marks"] = json!([]);
    apply(&mut h, &v);
    let after = h.state().unwrap();
    for field in [
        "cash",
        "reserved",
        "unsettled",
        "trade_available",
        "withdrawable",
        "realized_pnl",
        "realized_rounding_adjustment",
        "fees",
        "reserved_margin",
        "occupied_margin",
        "released_margin",
        "maintenance_required",
    ] {
        assert_eq!(
            after["account"]["snapshot"][field], before["account"]["snapshot"][field],
            "{field}"
        );
    }
    for field in ["margin", "margin_owner", "reservations", "receivables"] {
        assert_eq!(after["account"][field], before["account"][field]);
    }
    for field in ["margin_authority", "fee_authority", "settlement_authority"] {
        assert_eq!(after["execution"][field], before["execution"][field]);
    }
    assert_eq!(after["risk"], before["risk"]);
    assert_eq!(
        h.checkpoint().unwrap()["components"][0],
        cp["components"][0]
    );
    assert_eq!(after["account"]["snapshot"]["reserved_margin"], "10.00");
}

#[test]
fn equal_position_snapshots_do_not_prove_cause_or_configuration_identity() {
    let h = loaded();
    let cp = h.checkpoint().unwrap();
    for change_configuration in [false, true] {
        let mut config = cp["components"][1]["config"].clone();
        if change_configuration {
            config["instruments"][0]["multiplier"] = json!("2");
        }
        let mut position = onlyalpha_position::Manager::new(config).unwrap();
        for original in cp["components"][1]["journal"].as_array().unwrap() {
            let mut command = original.clone();
            if !change_configuration && command["op"] == "TRADE" {
                command["cause"] = json!("f".repeat(64));
            }
            position.apply(&command).unwrap();
        }
        assert_eq!(
            position.account("600000.XSHG").unwrap(),
            h.state().unwrap()["position"]["accounts"][0]["snapshot"]
        );
        let mut intent = valuation(&h, 4, "12.00")["payload"].clone();
        intent["position_evidence"] = json!(position.checkpoint().unwrap().1);
        intent["time"] = json!(4);
        let effect = position.value(&intent).unwrap();
        let ac = &cp["components"][2];
        let mut account = onlyalpha_account::Manager::new(ac["config"].clone()).unwrap();
        let bytes = serde_json::to_vec(ac).unwrap();
        account
            .restore(&bytes, &onlyalpha_account::digest(&bytes))
            .unwrap();
        let before = account.state();
        let command = json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"command_id":"foreign-source","cause":"b".repeat(64),"time":4,"op":"VALUATION","payload":null});
        assert_eq!(
            account.apply_valuation(&command, &effect).unwrap_err().0,
            "ACCOUNT_VALUATION_SOURCE_RELATION"
        );
        assert_eq!(account.state(), before);
    }
}
