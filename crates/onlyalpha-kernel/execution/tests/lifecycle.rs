const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
const ECONOMICS: &str = include_str!("../../../../test-data/execution/economics-v1.json");
const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
mod support;
use onlyalpha_execution::Prepared;
use serde_json::{Value, json};
use support::*;
fn apply(c: &mut Harness, v: &Value) {
    let p = c.prepare(v).unwrap();
    for i in 0..p.projection_count() {
        c.install_projection(&p, i).unwrap();
    }
    c.complete(&p).unwrap();
}
#[test]
fn pure_plan_then_exact_install_and_complete_economic_chain() {
    let mut c = Harness::new(config()).unwrap();
    let before = c.checkpoint().unwrap();
    let p = c.prepare(&open(1, "BUY")).unwrap();
    assert_eq!(c.checkpoint().unwrap(), before);
    assert_eq!(
        p.record(),
        Prepared::decode(&p.encode().unwrap()).unwrap().record()
    );
    for i in 0..p.projection_count() {
        c.install_projection(&p, i).unwrap();
    }
    assert!(c.state().is_err());
    c.complete(&p).unwrap();
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    assert!(c.prepare(&stage(3, 1, "BEGIN_SUBMIT")).is_err());
    apply(&mut c, &fill(3, 1, "1", "10.00", "1.00"));
    let s = c.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "989.00");
    apply(&mut c, &fill(4, 1, "3", "10.00", "1.00"));
    assert_eq!(c.state().unwrap()["account"]["snapshot"]["cash"], "959.00");
    apply(&mut c, &open(5, "SELL"));
    apply(&mut c, &stage(6, 2, "UNKNOWN"));
    apply(&mut c, &fill(7, 2, "1", "12.00", "1.00"));
    assert_eq!(c.state().unwrap()["account"]["snapshot"]["cash"], "970.00");
    apply(&mut c, &fill(8, 2, "3", "12.00", "1.00"));
    let s = c.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "1006.00");
    assert_eq!(s["account"]["snapshot"]["realized_pnl"], "8.00");
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["cash"],
        "1006.00"
    );
    let cp = c.checkpoint().unwrap();
    let mut fresh = Harness::new(config()).unwrap();
    fresh.store = c.store.clone();
    fresh.restore(&cp).unwrap();
    assert_eq!(fresh.checkpoint().unwrap(), cp);
}
#[test]
fn partial_cancel_releases_only_remainder_and_replay_is_exact() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let f = fill(3, 1, "1", "10.00", "1.00");
    apply(&mut c, &f);
    apply(&mut c, &terminal(4, 1, "CANCELLED"));
    let s = c.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "989.00");
    assert_eq!(s["account"]["snapshot"]["reserved"], "0.00");
    let before = c.checkpoint().unwrap();
    assert!(c.prepare(&fill(5, 1, "1", "10.00", "1.00")).is_err());
    assert_eq!(c.checkpoint().unwrap(), before);
}
#[test]
fn unavailable_wrong_owner_and_bad_economics_never_mutate() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    for field in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
        "cluster",
        "revision",
    ] {
        let mut f = fill(3, 1, "1", "10.00", "1.00");
        f[field] = json!("wrong");
        let cp = c.checkpoint().unwrap();
        assert!(c.prepare(&f).is_err(), "{field}");
        assert_eq!(c.checkpoint().unwrap(), cp);
    }
    for path in ["fees", "settlement"] {
        let mut f = fill(3, 1, "1", "10.00", "1.00");
        f["payload"][path] = Value::Null;
        assert!(c.prepare(&f).is_err());
    }
    assert!(c.prepare(&fill(3, 1, "5", "10.00", "1.00")).is_err());
    let mut f = fill(3, 1, "1", "10.00", "1.00");
    f["payload"]["fees"]["trade"] = json!("other");
    assert!(c.prepare(&f).is_err());
}
#[test]
fn projection_before_result_and_payload_conflicts_are_atomic() {
    let mut c = Harness::new(config()).unwrap();
    let p = c.prepare(&open(1, "BUY")).unwrap();
    assert!(c.install_projection(&p, 1).is_err());
    c.install_projection(&p, 0).unwrap();
    let cp = c.checkpoint().unwrap();
    c.install_projection(&p, 0).unwrap();
    assert_eq!(c.checkpoint().unwrap(), cp);
    let mut record = p.record();
    record["input"]["account"] = json!("other");
    assert!(Prepared::decode(&serde_json::to_vec(&record).unwrap()).is_err());
    let mut other = Harness::new(config()).unwrap();
    let mut checkpoint = other.checkpoint().unwrap();
    checkpoint["config"]["account"] = json!("other");
    assert!(other.restore(&checkpoint).is_err());
}

#[test]
fn fractional_cost_and_loss_use_one_position_authority_until_final_remainder() {
    let mut c = Harness::new(config()).unwrap();
    let mut buy = open(1, "BUY");
    buy["payload"]["request"]["quantity"]["value"] = json!("3");
    buy["payload"]["request"]["price"]["value"] = json!("3.34");
    refresh_market(&mut buy);
    apply(&mut c, &buy);
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    apply(&mut c, &fill(3, 1, "1", "3.33", "1.00"));
    apply(&mut c, &fill(4, 1, "2", "3.34", "1.00"));
    let mut sell = open(5, "SELL");
    sell["payload"]["request"]["quantity"]["value"] = json!("3");
    sell["payload"]["request"]["price"]["value"] = json!("3.33");
    refresh_market(&mut sell);
    apply(&mut c, &sell);
    apply(&mut c, &stage(6, 2, "UNKNOWN"));
    apply(&mut c, &fill(7, 2, "1", "3.33", "1.00"));
    let s = c.state().unwrap();
    assert_eq!(
        s["position"]["accounts"][0]["snapshot"]["cost"],
        "6.67333333333333333333333333333333333"
    );
    let cp = c.checkpoint().unwrap();
    let mut fresh = Harness::new(config()).unwrap();
    fresh.store = c.store.clone();
    fresh.restore(&cp).unwrap();
    apply(&mut fresh, &fill(8, 2, "2", "3.33", "1.00"));
    let s = fresh.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "997.98");
    assert_eq!(s["account"]["snapshot"]["realized_pnl"], "-0.02");
    assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], "0");
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["cash"],
        "997.98"
    );
}

#[test]
fn acceptance_pending_cancel_and_partial_terminal_observations_preserve_holds() {
    for outcome in ["CANCELLED", "REJECTED", "EXPIRED", "FAILED"] {
        let mut c = Harness::new(config()).unwrap();
        apply(&mut c, &open(1, "BUY"));
        apply(&mut c, &stage(2, 1, "DISPATCHED"));
        apply(
            &mut c,
            &input(
                3,
                "ACCEPT",
                json!({"schema_version":1,"order":order(1),"venue_order":"venue-1"}),
            ),
        );
        apply(
            &mut c,
            &input(
                4,
                "CANCEL",
                json!({"schema_version":1,"order":order(1),"request_id":"cancel-1","reason":"explicit user cancellation"}),
            ),
        );
        assert_eq!(
            c.state().unwrap()["account"]["snapshot"]["reserved"],
            "41.00"
        );
        apply(&mut c, &fill(5, 1, "1", "10.00", "1.00"));
        apply(&mut c, &terminal(6, 1, outcome));
        let s = c.state().unwrap();
        assert_eq!(s["account"]["snapshot"]["cash"], "989.00");
        assert_eq!(s["account"]["snapshot"]["reserved"], "0.00");
    }
}
#[test]
fn malformed_encoded_sequence_never_panics() {
    let c = Harness::new(config()).unwrap();
    let p = c.prepare(&open(1, "BUY")).unwrap();
    let mut v = p.record();
    v["predecessor"] = json!(u64::MAX);
    v["sequence"] = json!(u64::MAX);
    let result = std::panic::catch_unwind(|| Prepared::decode(&serde_json::to_vec(&v).unwrap()));
    assert!(result.is_ok());
    assert!(result.unwrap().is_err());
}

#[test]
fn complete_but_foreign_economic_evidence_is_never_admitted() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    for family in ["fees", "settlement", "valuation"] {
        for field in [
            "engine",
            "runtime",
            "account",
            "gateway",
            "generation",
            "runtime_kind",
            "cluster",
            "revision",
            "instrument",
            "request",
        ] {
            let mut v = fill(3, 1, "1", "10.00", "1.00");
            v["payload"][family]["scope"][field] = json!("foreign");
            let proof = &mut v["payload"][family];
            proof.as_object_mut().unwrap().remove("source_digest");
            proof["source_digest"] =
                json!(onlyalpha_execution::digest(proof.to_string().as_bytes()));
            let cp = c.checkpoint().unwrap();
            assert!(c.prepare(&v).is_err(), "{family} {field}");
            assert_eq!(c.checkpoint().unwrap(), cp);
        }
    }
    let mut v = fill(3, 1, "1", "10.00", "1.00");
    v["payload"]["valuation"]["mark"] = json!("11.00");
    let proof = &mut v["payload"]["valuation"];
    proof.as_object_mut().unwrap().remove("source_digest");
    proof["source_digest"] = json!(onlyalpha_execution::digest(proof.to_string().as_bytes()));
    apply(&mut c, &v);
    assert_eq!(
        c.state().unwrap()["account"]["snapshot"]["market_value"],
        "11.00"
    );
}

#[test]
fn cached_request_trade_and_source_aliases_cannot_be_repurposed() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let f = fill(3, 1, "1", "10.00", "1.00");
    apply(&mut c, &f);
    let cp = c.checkpoint().unwrap();
    assert!(c.prepare(&f).is_err());
    for field in ["trade", "venue_trade"] {
        let mut changed = fill(4, 1, "1", "10.00", "1.00");
        changed["payload"][field] = f["payload"][field].clone();
        assert!(c.prepare(&changed).is_err());
        assert_eq!(c.checkpoint().unwrap(), cp);
    }
}

#[test]
fn checkpoint_digest_rejects_otherwise_valid_splice() {
    let c = Harness::new(config()).unwrap();
    let checkpoint = c.checkpoint().unwrap();
    let hash = onlyalpha_execution::digest(&serde_json::to_vec(&checkpoint).unwrap());
    let mut fresh = onlyalpha_execution::Components::new(config()).unwrap();
    let mut bad = checkpoint.clone();
    bad["sequence"] = json!(99);
    assert!(fresh.restore(&bad, &hash).is_err());
    assert_eq!(fresh.checkpoint().unwrap(), checkpoint);
}

#[test]
fn independent_economic_vector_matches_real_native_components() {
    let vector: Value = serde_json::from_str(ECONOMICS).unwrap();
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    for (i, f) in vector["buy_fills"].as_array().unwrap().iter().enumerate() {
        apply(
            &mut c,
            &fill(
                3 + i as u64,
                1,
                f["quantity"].as_str().unwrap(),
                f["price"].as_str().unwrap(),
                f["charge_target"].as_str().unwrap(),
            ),
        );
        let s = c.state().unwrap();
        assert_eq!(s["account"]["snapshot"]["cash"], f["cash"]);
        assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], f["cost"]);
        assert_eq!(
            s["position"]["accounts"][0]["snapshot"]["quantity"],
            f["quantity_after"]
        );
    }
    apply(&mut c, &open(5, "SELL"));
    apply(&mut c, &stage(6, 2, "UNKNOWN"));
    for (i, f) in vector["close_fills"].as_array().unwrap().iter().enumerate() {
        apply(
            &mut c,
            &fill(
                7 + i as u64,
                2,
                f["quantity"].as_str().unwrap(),
                f["price"].as_str().unwrap(),
                f["charge_target"].as_str().unwrap(),
            ),
        );
        let s = c.state().unwrap();
        assert_eq!(s["account"]["snapshot"]["cash"], f["cash"]);
        assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], f["cost"]);
        assert_eq!(s["account"]["snapshot"]["realized_pnl"], f["realized"]);
    }
}

#[test]
fn common_reference_outputs() {
    use bigdecimal::BigDecimal;
    use std::str::FromStr;
    let mut cfg = config();
    cfg["initial_cash"] = json!("10000.00");
    cfg["capitals"]["cluster"] = json!("10000.00");
    let mut c = Harness::new(cfg).unwrap();
    let mut buy = open(1, "BUY");
    buy["payload"]["request"]["quantity"]["value"] = json!("400");
    refresh_market(&mut buy);
    buy["payload"]["fee_contract"]["funding"]["principal_reservation"]["amount"] = json!("4000.00");
    buy["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"] = json!("4000.00");
    apply(&mut c, &buy);
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    apply(&mut c, &fill(3, 1, "400", "10.00", "0.00"));
    let mut sell = open(5, "SELL");
    sell["payload"]["request"]["quantity"]["value"] = json!("400");
    sell["payload"]["fee_budget"] = json!("4.80");
    refresh_market(&mut sell);
    apply(&mut c, &sell);
    apply(&mut c, &stage(6, 2, "UNKNOWN"));
    let mut rows = vec![];
    let mut cash = BigDecimal::from(6000);
    let mut realized = BigDecimal::from(0);
    let mut fees = BigDecimal::from(0);
    for (n, q, target) in [(7, "100", "1.20"), (8, "300", "4.80")] {
        apply(&mut c, &fill(n, 2, q, "12.00", target));
        let s = c.state().unwrap();
        let a = &s["account"]["snapshot"];
        let next_cash = BigDecimal::from_str(a["cash"].as_str().unwrap()).unwrap();
        let next_realized = BigDecimal::from_str(a["realized_pnl"].as_str().unwrap()).unwrap();
        let next_fees = BigDecimal::from_str(a["fees"].as_str().unwrap()).unwrap();
        rows.push(json!({"quantity_after":s["position"]["accounts"][0]["snapshot"]["quantity"],"cost_after":s["position"]["accounts"][0]["snapshot"]["cost"],"cash_delta":(&next_cash-&cash).with_scale(2).to_plain_string(),"realized_delta":(&next_realized-&realized).with_scale(2).to_plain_string(),"fees":(&next_fees-&fees).with_scale(2).to_plain_string()}));
        cash = next_cash;
        realized = next_realized;
        fees = next_fees;
    }
    println!("EXECUTION_COMMON_JSON {}", json!(rows));
}

#[test]
fn owning_currency_matches_the_complete_fee_contract() {
    let mut cfg = config();
    cfg["currency"]["code"] = json!("USD");
    let c = Harness::new(cfg).unwrap();
    assert!(c.prepare(&open(1, "BUY")).is_err());
}
#[test]
fn owning_instrument_inventory_covers_every_profile() {
    let mut cfg = config();
    cfg["profiles"]["cluster"]["instruments"] = json!(["ETHUSDT.BINANCE"]);
    assert!(Harness::new(cfg).is_err());
}
#[test]
fn owning_funding_requirement_is_not_replaced_by_notional() {
    let mut c = Harness::new(config()).unwrap();
    let mut v = open(1, "BUY");
    v["payload"]["fee_contract"]["funding"]["principal_reservation"]["amount"] = json!("60.00");
    v["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"] = json!("60.00");
    apply(&mut c, &v);
    assert_eq!(
        c.state().unwrap()["account"]["snapshot"]["reserved"],
        "61.00"
    );
}
#[test]
fn owning_fee_budget_covers_the_bound_funding_envelope() {
    let c = Harness::new(config()).unwrap();
    let mut v = open(1, "BUY");
    v["payload"]["fee_contract"]["funding"]["fee_reservation"]["amount"] = json!("2.00");
    v["payload"]["fee_contract"]["funding"]["total_reservation"]["amount"] = json!("42.00");
    assert!(c.prepare(&v).is_err());
}
#[test]
fn owning_contract_schema_is_not_silently_overwritten() {
    let c = Harness::new(config()).unwrap();
    let mut v = open(1, "BUY");
    v["payload"]["fee_contract"]["schema_version"] = json!(2);
    assert!(c.prepare(&v).is_err());
}
#[test]
fn owning_runtime_kind_is_required_explicit_input() {
    let mut cfg = config();
    cfg.as_object_mut().unwrap().remove("runtime_kind");
    assert!(Harness::new(cfg).is_err());
}

#[test]
fn decoded_cache_cannot_mint_authority_without_the_owning_store() {
    let mut c = Harness::new(config()).unwrap();
    let mut cache = c.checkpoint().unwrap();
    let mut foreign =
        onlyalpha_account::Manager::new(cache["components"][2]["config"].clone()).unwrap();
    foreign.apply(&json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"command_id":"invented-deposit","cause":"b".repeat(64),"time":0,"op":"CASH_CHANGE","payload":{"schema_version":1,"change":"invented","kind":"DEPOSIT","amount":"100.00","source_fact":"invented-source"}})).unwrap();
    cache["components"][2] = serde_json::from_slice(&foreign.checkpoint().unwrap().0).unwrap();
    c.restore(&cache).unwrap();
    assert!(c.prepare(&open(1, "BUY")).is_err());
    assert!(c.state().is_err());
}

#[test]
fn explicit_fractional_settlement_keeps_cost_and_cash_rounding_separate() {
    let mut cfg = config();
    cfg["instruments"][0]["price_precision"] = json!(3);
    cfg["instruments"][0]["quantity_precision"] = json!(3);
    let mut c = Harness::new(cfg).unwrap();
    let mut v = open(1, "BUY");
    v["payload"]["request"]["price"] = json!({"schema_version":1,"value":"3.333","precision":3});
    v["payload"]["request"]["quantity"] = json!({"schema_version":1,"value":"0.003","precision":3});
    v["payload"]["market"]["request_digest"] = json!(onlyalpha_execution::digest(
        v["payload"]["request"].to_string().as_bytes()
    ));
    v["payload"]["market"]["notional"] =
        json!({"schema_version":1,"amount":"0.01","currency":config()["currency"]});
    v["payload"]["market"]["rounding"] = json!("HALF_EVEN");
    v["payload"]["fee_budget"] = json!("0.00");
    apply(&mut c, &v);
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let mut f = fill(3, 1, "0.003", "3.333", "0.00");
    f["payload"]["settlement"]["gross_notional"] =
        json!({"schema_version":1,"amount":"0.01","currency":config()["currency"]});
    f["payload"]["settlement"]["rounding"] = json!("HALF_EVEN");
    let proof = &mut f["payload"]["settlement"];
    proof.as_object_mut().unwrap().remove("source_digest");
    proof["source_digest"] = json!(onlyalpha_execution::digest(proof.to_string().as_bytes()));
    apply(&mut c, &f);
    let s = c.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "999.99");
    assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], "0.009999");
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["status"],
        "ACTIVE"
    );
    assert_eq!(
        s["account"]["snapshot"]["realized_rounding_adjustment"],
        "-0.000001"
    );
    let mut sell = open(5, "SELL");
    sell["payload"]["request"]["price"] = json!({"schema_version":1,"value":"3.333","precision":3});
    sell["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"0.003","precision":3});
    refresh_market(&mut sell);
    apply(&mut c, &sell);
    apply(&mut c, &stage(6, 2, "UNKNOWN"));
    apply(&mut c, &fill(7, 2, "0.003", "3.333", "0.00"));
    let s = c.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "1000.00");
    assert_eq!(
        s["account"]["snapshot"]["realized_rounding_adjustment"],
        "0.00"
    );
    assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], "0");
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["status"],
        "ACTIVE"
    );
}

#[test]
fn extreme_request_decimal_is_rejected_before_typed_arithmetic() {
    let c = Harness::new(config()).unwrap();
    let mut v = open(1, "BUY");
    v["payload"]["request"]["price"]["value"] = json!("1E+9223372036854775807");
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| c.prepare(&v)));
    assert!(result.is_ok());
    assert!(result.unwrap().is_err());
}

#[test]
fn ready_cache_requires_the_whole_committed_lineage() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let checkpoint = c.checkpoint().unwrap();
    let mut v = c.store.rows[0].record();
    v["ready"] = json!(false);
    c.store.rows[0] = onlyalpha_execution::Record::decode(&v).unwrap();
    assert!(c.state().is_err());
    assert!(
        onlyalpha_execution::pending_events(&c.store, &c.components)
            .unwrap()
            .is_empty()
    );
    assert!(c.prepare(&fill(3, 1, "1", "10.00", "1.00")).is_err());
    let mut fresh = onlyalpha_execution::Components::new(config()).unwrap();
    fresh
        .restore(
            &checkpoint,
            &onlyalpha_execution::digest(checkpoint.to_string().as_bytes()),
        )
        .unwrap();
    assert!(onlyalpha_execution::recover(&mut c.store, &mut fresh).is_err());
}

#[test]
fn immutable_market_and_valuation_sources_cannot_be_repurposed() {
    let mut c = Harness::new(config()).unwrap();
    apply(&mut c, &open(1, "BUY"));
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    let first = fill(3, 1, "1", "10.00", "0.00");
    apply(&mut c, &first);
    let mut second = fill(4, 1, "3", "10.00", "0.00");
    second["payload"]["valuation"]["source_ref"] =
        first["payload"]["valuation"]["source_ref"].clone();
    let proof = &mut second["payload"]["valuation"];
    proof.as_object_mut().unwrap().remove("source_digest");
    proof["source_digest"] = json!(onlyalpha_execution::digest(proof.to_string().as_bytes()));
    let before = c.checkpoint().unwrap();
    assert!(c.prepare(&second).is_err());
    assert_eq!(c.checkpoint().unwrap(), before);
    apply(&mut c, &fill(4, 1, "3", "10.00", "0.00"));
    let mut sell = open(5, "SELL");
    sell["payload"]["market"]["source_ref"] =
        open(1, "BUY")["payload"]["market"]["source_ref"].clone();
    assert!(c.prepare(&sell).is_err());
}

#[test]
fn split_cent_fills_preserve_positive_quantity_with_zero_settlement() {
    let mut cfg = config();
    cfg["instruments"][0]["price_precision"] = json!(3);
    cfg["instruments"][0]["quantity_precision"] = json!(3);
    let mut c = Harness::new(cfg).unwrap();
    let mut v = open(1, "BUY");
    v["payload"]["request"]["price"] = json!({"schema_version":1,"value":"3.333","precision":3});
    v["payload"]["request"]["quantity"] = json!({"schema_version":1,"value":"0.003","precision":3});
    refresh_market(&mut v);
    v["payload"]["fee_budget"] = json!("0.00");
    apply(&mut c, &v);
    apply(&mut c, &stage(2, 1, "UNKNOWN"));
    for n in 3..=5 {
        apply(&mut c, &fill(n, 1, "0.001", "3.333", "0.00"));
    }
    let s = c.state().unwrap();
    assert_eq!(s["account"]["snapshot"]["cash"], "1000.00");
    assert_eq!(
        s["position"]["accounts"][0]["snapshot"]["quantity"],
        "0.003"
    );
    assert_eq!(s["position"]["accounts"][0]["snapshot"]["cost"], "0.009999");
    assert_eq!(
        s["account"]["snapshot"]["realized_rounding_adjustment"],
        "0.009999"
    );
    assert_eq!(
        s["ledger"]["ledgers"]["cluster"]["snapshot"]["status"],
        "ACTIVE"
    );
}
