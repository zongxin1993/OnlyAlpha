use onlyalpha_domain::{
    base::OnlyDomainModel,
    execution::OnlyOrderSnapshot,
    fee::{OnlyOrderFeeEstimate, OnlyOrderFeePolicyBinding, OnlyOrderFundingPlan},
    time::OnlyTimestamp,
    value::{OnlyPrice, OnlyQuantity},
};
use onlyalpha_market_crypto::spot::{SpotRuleSnapshot, SpotSimulationPolicy};
use serde_json::{Value, json};

fn symbol() -> Value {
    json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","isSpotTradingAllowed":true,"orderTypes":["LIMIT","MARKET"],"baseAssetPrecision":8,"quoteAssetPrecision":8,"baseCommissionPrecision":8,"quoteCommissionPrecision":8,"filters":[
        {"filterType":"PRICE_FILTER","minPrice":"0.01000000","maxPrice":"1000000.00000000","tickSize":"0.01000000"},
        {"filterType":"LOT_SIZE","minQty":"0.00001000","maxQty":"9000.00000000","stepSize":"0.00001000"},
        {"filterType":"MARKET_LOT_SIZE","minQty":"0.00000000","maxQty":"100.00000000","stepSize":"0.00000000"},
        {"filterType":"NOTIONAL","minNotional":"5.00000000","applyMinToMarket":true,"maxNotional":"9000000.00000000","applyMaxToMarket":false,"avgPriceMins":5}
    ]})
}
fn snapshot() -> SpotRuleSnapshot {
    // Controlled input is a technical fixture; this is not a live venue capture.
    SpotRuleSnapshot::capture(
        symbol(),
        OnlyTimestamp::from_unix_nanos(100.into()),
        "technical-fixture",
    )
    .unwrap()
}
fn configuration() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"},"initial_cash":"10000.00000000","capitals":{"cluster":"10000.00000000"},"profiles":{"cluster":{"schema_version":1,"revision":"b".repeat(64),"instruments":["BTCUSDT.BINANCE"],"rules":[]}},"instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":2,"quantity_precision":5,"multiplier":"1"}]})
}
fn context() -> Value {
    json!({"schema_version":1,"time":1000,"day_index":1,"trading_day":"2025-01-03","cause":"c".repeat(64)})
}
fn price(value: &str) -> OnlyPrice {
    OnlyPrice::new(value.parse().unwrap(), 6).unwrap()
}
fn quantity(value: &str) -> OnlyQuantity {
    OnlyQuantity::new(
        value.parse().unwrap(),
        u8::try_from(value.split('.').nth(1).map_or(0, str::len)).unwrap(),
    )
    .unwrap()
}
fn order(side: &str) -> Value {
    let mut row = include_str!("../../../test-data/domain/fact-records-v1.jsonl")
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap())
        .find(|v| v["id"] == "created")
        .unwrap()["record"]
        .clone();
    row["order_type"] = json!("MARKET");
    row["price"] = Value::Null;
    row["instrument_id"] = json!({"schema_version":1,"symbol":{"schema_version":1,"value":"BTCUSDT"},"venue":{"schema_version":1,"value":"BINANCE"}});
    row["side"] = json!(side);
    row["execution_intent"]["side"] = json!(side);
    row["execution_intent"]["position_effect"] =
        json!(if side == "BUY" { "OPEN" } else { "CLOSE" });
    row["quantity"] = quantity("0.01000").to_record();
    row["remaining_quantity"] = row["quantity"].clone();
    row["filled_quantity"] = quantity("0.00000").to_record();
    OnlyOrderSnapshot::from_record(&row).unwrap().to_record()
}

#[test]
fn snapshot_preserves_source_date_filters_and_independent_quote_precision() {
    let s = snapshot();
    let v = s.record();
    assert_eq!(
        v["captured_at"],
        json!({"schema_version":1,"unix_nanos":100})
    );
    assert_eq!(v["raw_symbol"], symbol());
    assert_eq!(SpotRuleSnapshot::from_record(&v).unwrap().record(), v);
    let p = SpotSimulationPolicy::new(s, configuration()).unwrap();
    let binding = p.binding();
    assert_eq!(binding["reference_policy"], "MODEL_NEXT_OPEN");
    assert_eq!(binding["settlement_currency"]["precision"], 8);
    assert_eq!(configuration()["instruments"][0]["price_precision"], 2);
    let mut bad = v;
    bad["raw_symbol"]["quoteAssetPrecision"] = json!(2);
    assert!(SpotRuleSnapshot::from_record(&bad).is_err());
}

#[test]
fn model_rules_enforce_lot_market_lot_and_explicit_notional_flags() {
    let p = SpotSimulationPolicy::new(snapshot(), configuration()).unwrap();
    let mut request = order("BUY");
    for (q, accepted) in [
        ("0.01000", true),
        ("0.01000100", false),
        ("101.00000", false),
        ("0.00000", false),
    ] {
        request["quantity"] = quantity(q).to_record();
        request["remaining_quantity"] = request["quantity"].clone();
        // Invalid zero-quantity Domain records must fail closed before policy approval.
        let result = p.admission(&request, &price("100020.000000"), &context());
        if accepted {
            let result = result.unwrap();
            assert_eq!(result["accepted"], true);
            assert_eq!(result["market_provenance"]["verdict"], "MODEL_ACCEPT");
            assert_eq!(
                result["market_provenance"]["reference_policy"],
                "MODEL_NEXT_OPEN"
            );
            assert_eq!(
                result["market_provenance"]["venue_acceptance_proven"],
                false
            );
        } else {
            assert!(result.is_err() || result.unwrap()["accepted"] == false);
        }
    }
    let small = p
        .admission(&order("BUY"), &price("100.000000"), &context())
        .unwrap();
    assert_eq!(small["accepted"], false);
    let mut raw = symbol();
    raw["filters"][3]["applyMinToMarket"] = json!(false);
    let s = SpotRuleSnapshot::capture(
        raw,
        OnlyTimestamp::from_unix_nanos(100.into()),
        "technical-fixture",
    )
    .unwrap();
    let p = SpotSimulationPolicy::new(s, configuration()).unwrap();
    assert_eq!(
        p.admission(&order("BUY"), &price("100.000000"), &context())
            .unwrap()["accepted"],
        true
    );
}

#[test]
fn actual_native_fee_catalog_builds_bound_estimate_and_funding() {
    let p = SpotSimulationPolicy::new(snapshot(), configuration()).unwrap();
    let admission = p
        .admission(&order("BUY"), &price("100020.000000"), &context())
        .unwrap();
    assert_eq!(admission["accepted"], true);
    assert_eq!(admission["fee_budget"], "1.00020000");
    assert_eq!(admission["notional"]["amount"], "1000.20000000");
    let contract = &admission["contract"];
    let binding = OnlyOrderFeePolicyBinding::from_record(&contract["binding"]).unwrap();
    let estimate = OnlyOrderFeeEstimate::from_record(&contract["estimate"]).unwrap();
    let funding = OnlyOrderFundingPlan::from_record(&contract["funding"]).unwrap();
    assert_eq!(estimate.expected().binding(), &binding);
    assert_eq!(funding.binding_fingerprint(), binding.fingerprint());
    assert_eq!(
        contract["funding"]["principal_reservation"]["amount"],
        "1000.20000000"
    );
    assert_eq!(
        contract["funding"]["total_reservation"]["amount"],
        "1001.20020000"
    );
    assert_eq!(
        admission["native_fee_estimate"]["reservation_charge"],
        admission["fee_budget"]
    );
    assert_eq!(
        admission["native_fee_binding"]["catalog"]["schedules"][1]["rules"][0]["terms"][0]["amount"],
        "0.001"
    );
}

#[test]
fn actual_fill_assessment_preserves_exact_2bp_price_and_fee_rounding() {
    let p = SpotSimulationPolicy::new(snapshot(), configuration()).unwrap();
    let mut request = order("BUY");
    let admission = p
        .admission(&request, &price("100020.123456"), &context())
        .unwrap();
    for (dst, src) in [
        ("fee_policy_binding", "binding"),
        ("fee_estimate", "estimate"),
        ("funding_plan", "funding"),
    ] {
        request[dst] = admission["contract"][src].clone();
    }
    OnlyOrderSnapshot::from_record(&request).unwrap();
    let mut ctx = context();
    ctx["trade"] = json!("trade-1");
    let fill = p
        .fill(
            &request,
            &price("100020.123456"),
            &quantity("0.01000"),
            &ctx,
        )
        .unwrap();
    assert_eq!(fill["charge_target"], "1.00020123");
    // Decimal zero retains its canonical native representation (for example 0E-8).
    let currency =
        onlyalpha_domain::value::OnlyCurrency::from_record(&configuration()["currency"]).unwrap();
    let rebate = onlyalpha_domain::value::OnlyMoney::new(
        fill["rebate_target"].as_str().unwrap().parse().unwrap(),
        currency.clone(),
    )
    .unwrap();
    assert_eq!(
        rebate.amount(),
        &"0".parse::<onlyalpha_domain::numeric::OnlyDecimal>()
            .unwrap()
    );
    assert_eq!(rebate.currency(), &currency);
    assert_eq!(rebate.currency().precision(), 8);
    assert_eq!(fill["gross_notional"]["amount"], "1000.20123456");
    assert!(
        fill["native_fee_assessment"]["components"]
            .as_array()
            .unwrap()
            .len()
            >= 2
    );
    assert!(
        p.fill(
            &request,
            &price("100020.123456"),
            &quantity("0.00500"),
            &ctx
        )
        .is_err()
    );
    request["fee_policy_binding"]["fingerprint"] = json!("e".repeat(64));
    assert!(
        p.fill(
            &request,
            &price("100020.123456"),
            &quantity("0.01000"),
            &ctx
        )
        .is_err()
    );
}

#[test]
fn malformed_or_unsupported_rules_and_context_never_grant_model_admission() {
    for mode in [
        "missing-lot",
        "duplicate",
        "missing-notional",
        "market-disabled",
        "bad-quantity",
        "bad-precision",
    ] {
        let mut raw = symbol();
        match mode {
            "missing-lot" => {
                raw["filters"].as_array_mut().unwrap().remove(1);
            }
            "duplicate" => {
                let duplicate = raw["filters"][1].clone();
                raw["filters"].as_array_mut().unwrap().push(duplicate);
            }
            "missing-notional" => {
                raw["filters"].as_array_mut().unwrap().pop();
            }
            "market-disabled" => raw["orderTypes"] = json!(["LIMIT"]),
            "bad-quantity" => raw["filters"][1]["stepSize"] = json!("-0.1"),
            _ => raw["quoteAssetPrecision"] = json!(19),
        }
        assert!(
            SpotRuleSnapshot::capture(
                raw,
                OnlyTimestamp::from_unix_nanos(100.into()),
                "technical-fixture"
            )
            .is_err(),
            "{mode}"
        );
    }
    let mut cfg = configuration();
    cfg["runtime_kind"] = json!("LIVE");
    assert!(SpotSimulationPolicy::new(snapshot(), cfg).is_err());
    let p = SpotSimulationPolicy::new(snapshot(), configuration()).unwrap();
    let mut ctx = context();
    ctx["day_index"] = Value::Null;
    assert!(
        p.admission(&order("BUY"), &price("100020.000000"), &ctx)
            .is_err()
    );
}

#[test]
fn model_instrument_uses_snapshot_money_precision_without_rewriting_the_original() {
    let s = snapshot();
    let original = s.record();
    let before = onlyalpha_market_crypto::spot::instrument(&symbol())
        .unwrap()
        .to_record();
    let instrument = s.model_instrument().unwrap().to_record();
    assert_eq!(instrument["price_precision"], 2);
    assert_eq!(instrument["quantity_precision"], 5);
    assert_eq!(instrument["quote_currency"]["precision"], 8);
    assert_eq!(instrument["settlement_currency"]["precision"], 8);
    assert_eq!(instrument["base_currency"]["precision"], 8);
    assert_eq!(s.record(), original);
    assert_eq!(
        onlyalpha_market_crypto::spot::instrument(&symbol())
            .unwrap()
            .to_record(),
        before
    );
}

#[test]
fn analytical_entry_quote_reuses_the_exact_policy_and_actual_whole_fill_fee() {
    use onlyalpha_domain::numeric::{OnlyDecimal, only_multiply};
    let policy = SpotSimulationPolicy::new(snapshot(), configuration()).unwrap();
    let before = policy.binding();
    let open: OnlyDecimal = "100000.00".parse().unwrap();
    let multiplier: OnlyDecimal = "1.0002".parse().unwrap();
    let reference = OnlyPrice::new(only_multiply(&open, &multiplier).unwrap(), 6).unwrap();
    let quantity = quantity("0.01000");
    let quote = policy
        .analytical_entry_quote(&reference, &quantity, &context())
        .unwrap();
    assert_eq!(quote["kind"], "ANALYTICAL_ESTIMATE");
    assert_eq!(quote["policy_fingerprint"], onlyalpha_fee::digest(&before));
    assert_eq!(quote["rules_fingerprint"], before["rules_fingerprint"]);
    assert_eq!(quote["execution_price"], reference.to_record());
    assert_eq!(quote["quantity"], quantity.to_record());
    assert_eq!(quote["context"], context());
    assert_eq!(quote["gross_notional"]["amount"], "1000.20000000");
    assert_eq!(quote["charges"]["amount"], "1.00020000");
    assert_eq!(quote["charges"]["currency"], configuration()["currency"]);
    assert_eq!(quote["fee_quote"]["kind"], "ANALYTICAL_ESTIMATE");
    assert_eq!(quote["fee_quote"]["day"], context()["day_index"]);
    assert_eq!(
        quote["fee_quote_fingerprint"],
        onlyalpha_fee::digest(&quote["fee_quote"])
    );
    for key in ["order", "trade", "contract", "binding", "application"] {
        assert!(quote.get(key).is_none(), "{key}");
        assert!(quote["fee_quote"].get(key).is_none(), "fee_quote {key}");
        assert!(
            quote["fee_quote"]["subject"].get(key).is_none(),
            "subject {key}"
        );
    }
    let mut actual_order = order("BUY");
    let admission = policy
        .admission(&actual_order, &reference, &context())
        .unwrap();
    for (dst, src) in [
        ("fee_policy_binding", "binding"),
        ("fee_estimate", "estimate"),
        ("funding_plan", "funding"),
    ] {
        actual_order[dst] = admission["contract"][src].clone();
    }
    let mut fill_context = context();
    fill_context["trade"] = json!("actual-whole-fill");
    let actual_fill = policy
        .fill(&actual_order, &reference, &quantity, &fill_context)
        .unwrap();
    assert_eq!(quote["gross_notional"], actual_fill["gross_notional"]);
    assert_eq!(quote["charges"]["amount"], actual_fill["charge_target"]);
    assert_eq!(
        quote["fee_quote"]["components"],
        actual_fill["native_fee_assessment"]["components"]
    );
    assert_eq!(policy.binding(), before);
}

#[test]
fn analytical_entry_quote_refuses_missing_context_and_binds_changed_rules_or_day() {
    let policy = SpotSimulationPolicy::new(snapshot(), configuration()).unwrap();
    let q = quantity("0.01000");
    let p = price("100020.123456");
    let first = policy.analytical_entry_quote(&p, &q, &context()).unwrap();
    let mut missing = context();
    missing.as_object_mut().unwrap().remove("cause");
    assert!(policy.analytical_entry_quote(&p, &q, &missing).is_err());
    let mut day = context();
    day["day_index"] = json!(2);
    let later = policy.analytical_entry_quote(&p, &q, &day).unwrap();
    assert_ne!(
        first["fee_quote_fingerprint"],
        later["fee_quote_fingerprint"]
    );
    let mut changed_context = context();
    changed_context["cause"] = json!("d".repeat(64));
    let later = policy
        .analytical_entry_quote(&p, &q, &changed_context)
        .unwrap();
    assert_ne!(onlyalpha_fee::digest(&first), onlyalpha_fee::digest(&later));
    assert!(
        policy
            .analytical_entry_quote(&price("100.000000"), &q, &context())
            .is_err()
    );
    assert!(
        policy
            .analytical_entry_quote(&p, &quantity("0.01000100"), &context())
            .is_err()
    );
    let mut raw = symbol();
    raw["filters"][3]["minNotional"] = json!("20.00000000");
    let changed = SpotRuleSnapshot::capture(
        raw,
        OnlyTimestamp::from_unix_nanos(100.into()),
        "technical-fixture",
    )
    .unwrap();
    let other = SpotSimulationPolicy::new(changed, configuration())
        .unwrap()
        .analytical_entry_quote(&p, &q, &context())
        .unwrap();
    assert_eq!(first["charges"], other["charges"]);
    assert_ne!(first["rules_fingerprint"], other["rules_fingerprint"]);
    assert_ne!(first["policy_fingerprint"], other["policy_fingerprint"]);
}
