use onlyalpha_account::{Manager, digest};
use onlyalpha_domain::time::OnlyTimestamp;
use serde_json::{Value, json};
fn config() -> Value {
    json!({"schema_version":2,"position_configuration":"b".repeat(64),"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","account_type":"CASH","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"1000.00"})
}
fn at(n: i64) -> OnlyTimestamp {
    OnlyTimestamp::from_unix_nanos(n.into())
}
fn command(n: i64, op: &str, payload: Value) -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"generation","command_id":format!("command-{n}"),"cause":"a".repeat(64),"time":n,"op":op,"payload":payload})
}
fn economic(n: i64, amount: &str) -> Value {
    command(
        n,
        "ECONOMIC",
        json!({"schema_version":1,"cashflow":format!("flow-{n}"),"source_fact":format!("source-{n}"),"kind":"REALIZED_PNL","amount":amount,"instrument":"600000.XSHG"}),
    )
}
#[test]
fn actual_account_path_is_immutable_exact_and_fresh_reader_recoverable() {
    let mut m = Manager::new(config()).unwrap();
    let genesis = m.performance(&at(0)).unwrap();
    let initial = genesis.record();
    m.apply(&economic(1, "200.00")).unwrap();
    m.apply(&economic(2, "-100.00")).unwrap();
    let before = m.checkpoint().unwrap();
    let result = m.performance(&at(0)).unwrap();
    let v = result.record();
    assert_eq!(v["summary"]["maximum_drawdown"], "-0.08333333");
    assert_eq!(v["summary"]["return_since_start"], "0.10000000");
    assert_eq!(v["summary"]["high_water_mark"], "1200.00");
    assert_eq!(v["summary"]["net_pnl"], "100.00");
    assert_eq!(v["timeline"].as_array().unwrap().len(), 3);
    assert_eq!(genesis.record(), initial);
    let mut detached = v.clone();
    detached["timeline"][0]["snapshot"]["equity"] = json!("0.00");
    assert_eq!(result.record(), v);
    assert_eq!(
        serde_json::from_slice::<Value>(&result.encode().unwrap()).unwrap(),
        v
    );
    assert_eq!(m.checkpoint().unwrap(), before);
    let mut fresh = Manager::new(config()).unwrap();
    fresh.restore(&before.0, &before.1).unwrap();
    assert_eq!(fresh.performance(&at(0)).unwrap(), result);
    assert!(m.performance(&at(2)).is_err());
    assert_eq!(digest(&before.0), before.1);
}
#[test]
fn net_zero_external_flow_retains_occurrence_and_never_becomes_simple_return() {
    let mut m = Manager::new(config()).unwrap();
    for (n, kind) in [(1, "DEPOSIT"), (2, "WITHDRAWAL")] {
        m.apply(&command(n,"CASH_CHANGE",json!({"schema_version":1,"change":format!("change-{n}"),"source_fact":format!("source-{n}"),"kind":kind,"amount":"100.00"}))).unwrap();
    }
    let v = m.performance(&at(0)).unwrap().record();
    assert_eq!(v["summary"]["external_cash_flow"], "0.00");
    assert_eq!(v["summary"]["external_cash_flow_occurred"], true);
    assert!(v["summary"]["return_since_start"].is_null());
    assert!(
        v["summary"]["quality_flags"]
            .as_array()
            .unwrap()
            .contains(&json!("EXTERNAL_CASH_FLOW_REQUIRES_TWR"))
    );
}
#[test]
fn explicit_sequence_retains_equal_times_and_duplicate_commands_are_idempotent() {
    let mut m = Manager::new(config()).unwrap();
    let a = economic(1, "200.00");
    m.apply(&a).unwrap();
    m.apply(&a).unwrap();
    let mut b = economic(2, "-100.00");
    b["time"] = json!(1);
    m.apply(&b).unwrap();
    let v = m.performance(&at(1)).unwrap().record();
    assert_eq!(v["timeline"].as_array().unwrap().len(), 3);
    assert_eq!(v["timeline"][1]["time"], v["timeline"][2]["time"]);
    assert_ne!(v["timeline"][1]["sequence"], v["timeline"][2]["sequence"]);
    assert_ne!(v["timeline"][1]["cause"], v["timeline"][2]["cause"]);
}
#[test]
fn zero_initial_equity_has_explicit_unavailable_rates() {
    let mut c = config();
    c["initial_cash"] = json!("0.00");
    let m = Manager::new(c).unwrap();
    let v = m.performance(&at(0)).unwrap().record();
    assert!(v["summary"]["return_since_start"].is_null());
    assert!(v["summary"]["current_drawdown"].is_null());
    assert!(v["summary"]["maximum_drawdown"].is_null());
    assert_eq!(v["summary"]["net_pnl"], "0.00");
}

#[test]
fn common_vector_outputs() {
    let mut outputs = vec![];
    for line in include_str!("../../../../test-data/account/performance-v1.jsonl").lines() {
        let v: Value = serde_json::from_str(line).unwrap();
        let mut c = config();
        c["initial_cash"] = v["initial"].clone();
        let mut m = Manager::new(c).unwrap();
        for (i, amount) in v["amounts"].as_array().unwrap().iter().enumerate() {
            let n = i as i64 + 1;
            let amount = amount.as_str().unwrap();
            let cmd = if v["flow"] == true {
                command(
                    n,
                    "CASH_CHANGE",
                    json!({"schema_version":1,"change":format!("change-{n}"),"source_fact":format!("source-{n}"),"kind":if amount.starts_with('-'){"WITHDRAWAL"}else{"DEPOSIT"},"amount":amount.trim_start_matches('-')}),
                )
            } else {
                economic(n, amount)
            };
            m.apply(&cmd).unwrap();
        }
        let result = m.performance(&at(0)).unwrap().record();
        let mut observed = json!({});
        for key in v["expected"].as_object().unwrap().keys() {
            observed[key] = result["summary"][key].clone();
        }
        assert_eq!(observed, v["expected"], "{}", v["case"]);
        outputs.push(json!({"case":v["case"],"summary":observed}));
    }
    println!("PERFORMANCE_VECTOR_OUTPUT {}", json!(outputs));
}
#[test]
fn corrupt_context_history_and_negative_cash_equity_never_restore_or_change_performance() {
    let mut m = Manager::new(config()).unwrap();
    m.apply(&economic(1, "200.00")).unwrap();
    let cp = m.checkpoint().unwrap();
    let before = m.performance(&at(0)).unwrap();
    for kind in 0..4 {
        let mut v: Value = serde_json::from_slice(&cp.0).unwrap();
        match kind {
            0 => v["config"]["account"] = json!("foreign"),
            1 => {
                v["journal"].as_array_mut().unwrap().clear();
            }
            2 => v["state"]["snapshot"]["equity"] = json!("-1.00"),
            _ => v["journal"][0]["payload"]["source_fact"] = json!("other"),
        }
        let b = serde_json::to_vec(&v).unwrap();
        assert!(m.restore(&b, &digest(&b)).is_err());
        assert_eq!(m.performance(&at(0)).unwrap(), before);
    }
}

#[test]
fn semantic_duplicate_receipt_keeps_one_economic_point_and_binds_complete_history() {
    let mut m = Manager::new(config()).unwrap();
    let original = economic(1, "200.00");
    m.apply(&original).unwrap();
    let a = m.performance(&at(0)).unwrap().record();
    let mut duplicate = original.clone();
    duplicate["command_id"] = json!("other-delivery");
    assert_eq!(
        m.apply(&duplicate).unwrap().status,
        onlyalpha_account::Status::Duplicate
    );
    let b = m.performance(&at(0)).unwrap().record();
    assert_eq!(a["timeline"], b["timeline"]);
    assert_eq!(a["summary"], b["summary"]);
    assert_ne!(a["account_checkpoint"], b["account_checkpoint"]);
    let cp = m.checkpoint().unwrap();
    let mut fresh = Manager::new(config()).unwrap();
    fresh.restore(&cp.0, &cp.1).unwrap();
    assert_eq!(fresh.performance(&at(0)).unwrap().record(), b);
    let mut conflict = original;
    conflict["command_id"] = json!("conflict");
    conflict["payload"]["amount"] = json!("300.00");
    assert_eq!(
        m.apply(&conflict).unwrap().status,
        onlyalpha_account::Status::Conflict
    );
    assert_eq!(m.performance(&at(0)).unwrap().record(), b);
}

fn broker_observation(m: &Manager, n: i64, cash: Option<&str>) -> Value {
    let snapshot = m.snapshot();
    let mut payload = json!({"schema_version":1,"snapshot":format!("broker-{n}"),"sequence":n,"basis_sequence":snapshot["sequence"],"quality":"VERIFIED","cash":snapshot["cash"],"reserved":snapshot["reserved"],"trade_available":snapshot["trade_available"],"withdrawable":snapshot["withdrawable"],"equity":snapshot["equity"]});
    if let Some(cash) = cash {
        payload["cash"] = json!(cash);
    }
    command(n, "BROKER", payload)
}
#[test]
fn late_observation_preserves_both_times_and_cleared_quality_history() {
    let mut m = Manager::new(config()).unwrap();
    let bad = broker_observation(&m, 1, Some("999.00"));
    m.apply(&bad).unwrap();
    let good = broker_observation(&m, 3, None);
    m.apply(&good).unwrap();
    let late = broker_observation(&m, 2, None);
    assert_eq!(
        m.apply(&late).unwrap().status,
        onlyalpha_account::Status::Stale
    );
    let v = m.performance(&at(0)).unwrap().record();
    let points = v["timeline"].as_array().unwrap();
    let last = points.last().unwrap();
    assert_eq!(last["source_time"], 2);
    assert_eq!(last["time"], 3);
    assert_eq!(last["provenance"]["outcome"], "Stale");
    assert_eq!(last["snapshot"]["status"], "ACTIVE");
    assert_eq!(last["snapshot"]["flags"], json!([]));
    assert!(
        v["summary"]["quality_flags"]
            .as_array()
            .unwrap()
            .contains(&json!("BROKER_LOCAL_CONFLICT"))
    );
    assert_eq!(v["summary"]["net_pnl"], "0.00");
    assert_eq!(points.len(), 4);
    let cp = m.checkpoint().unwrap();
    let mut fresh = Manager::new(config()).unwrap();
    fresh.restore(&cp.0, &cp.1).unwrap();
    assert_eq!(fresh.performance(&at(0)).unwrap().record(), v);
}
#[test]
fn release_is_a_state_occurrence_without_becoming_profit_or_duplicate_point() {
    let mut m = Manager::new(config()).unwrap();
    m.apply(&command(
        1,
        "RESERVE",
        json!({"schema_version":1,"reservation":"r","order":"order","amount":"100.00"}),
    ))
    .unwrap();
    for n in [2, 3] {
        m.apply(&command(
            n,
            "RELEASE",
            json!({"schema_version":1,"reservation":"r","outcome":"NOT_SENT"}),
        ))
        .unwrap();
    }
    let v = m.performance(&at(0)).unwrap().record();
    assert_eq!(v["timeline"].as_array().unwrap().len(), 3);
    assert_eq!(v["timeline"][2]["source"], "RELEASE");
    assert_eq!(v["timeline"][2]["snapshot"]["reserved"], "0.00");
    assert_eq!(v["summary"]["net_pnl"], "0.00");
}
#[test]
fn zero_high_water_becomes_positive_and_all_rate_constraints_remain_visible() {
    for external in [false, true] {
        let mut c = config();
        c["initial_cash"] = json!("0.00");
        let mut m = Manager::new(c).unwrap();
        let cmd = if external {
            command(
                1,
                "CASH_CHANGE",
                json!({"schema_version":1,"change":"deposit","source_fact":"deposit-source","kind":"DEPOSIT","amount":"100.00"}),
            )
        } else {
            economic(1, "100.00")
        };
        m.apply(&cmd).unwrap();
        let v = m.performance(&at(0)).unwrap().record();
        let summary = &v["summary"];
        assert!(summary["return_since_start"].is_null());
        assert_eq!(summary["high_water_mark"], "100.00");
        assert_eq!(summary["current_drawdown"], "0.00000000");
        assert_eq!(summary["maximum_drawdown"], "0.00000000");
        let flags = summary["quality_flags"].as_array().unwrap();
        assert!(flags.contains(&json!("ZERO_INITIAL_EQUITY")));
        assert!(flags.contains(&json!("NON_POSITIVE_HIGH_WATER_MARK")));
        assert_eq!(
            flags.contains(&json!("EXTERNAL_CASH_FLOW_REQUIRES_TWR")),
            external
        );
        assert!(v["timeline"][0]["snapshot"]["equity"] == "0.00");
    }
}
