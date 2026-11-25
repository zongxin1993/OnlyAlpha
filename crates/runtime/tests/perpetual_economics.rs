//! 非供应商专用样本：2 份 × 30 × 合约乘数 2；初始资金 20、初始保证金 12。
use onlyalpha_domain::{
    base::OnlyDomainModel, execution::OnlyOrderRequest, market::OnlyReferencePriceFact,
};
use onlyalpha_execution::{Components, MarketSourceCut};
use serde_json::{Value, json};

#[path = "support/perpetual_run.rs"]
mod perpetual_run;
use perpetual_run::*;

// 非供应商合成市场的实际编译生产者：改变规则时必须创建新的策略身份。
fn compile_synthetic_rules(cfg: &mut Value, inputs: &mut [Value]) {
    use onlyalpha_domain::{base::OnlyDomainModel, market_rules::OnlyStaticLimitRules};
    bind_venue(cfg, inputs);
    let r = &cfg["perpetual"]["limit_rules"];
    let mut p = json!({"timezone":"UTC","continuous_24x7":true,"instrument_id":cfg["perpetual"]["instrument"],"binding_fingerprint":r["binding"],"provider_status":"TRADING","coverage_start":r["effective_from"],"coverage_end":r["effective_to"],"account_coverage_start":r["effective_from"],"account_coverage_end":r["effective_to"],"as_of":r["effective_from"],"contract_multiplier":r["multiplier"]});
    for key in [
        "market_product",
        "contract_type",
        "position_mode",
        "margin_mode",
        "margin_segments",
        "funding_schedule",
    ] {
        p[key] = cfg["perpetual"][key].clone();
    }
    p["settlement_currency"] = cfg["currency"]["code"].clone();
    for key in [
        "price_tick",
        "minimum_price",
        "maximum_price",
        "quantity_step",
        "minimum_quantity",
        "maximum_quantity",
        "minimum_notional",
        "maximum_notional",
    ] {
        p[key] = r[key].clone();
    }
    let raw = p.to_string();
    let policy = onlyalpha_execution::digest(raw.as_bytes());
    let rules = OnlyStaticLimitRules::from_compiled_policy_json(&raw, &policy).unwrap();
    cfg["perpetual"]["compiled_policy_json"] = json!(raw);
    cfg["perpetual"]["policy_fingerprint"] = json!(policy);
    cfg["perpetual"]["limit_rules_fingerprint"] = json!(rules.content_fingerprint());
    cfg["perpetual"]["limit_rules"] = rules.to_record();
    for input in inputs.iter_mut().filter(|v| v["op"] == "ADMIT") {
        input["payload"]["policy_fingerprint"] = json!(policy);
    }
}
fn amount(v: &Value, wanted: &str) {
    use bigdecimal::BigDecimal;
    assert_eq!(
        v.as_str().unwrap().parse::<BigDecimal>().unwrap(),
        wanted.parse::<BigDecimal>().unwrap()
    );
}
fn verify(s: &Value) {
    let a = &s["account"]["snapshot"];
    let l = &s["ledger"]["ledgers"]["cluster"]["snapshot"];
    // 入场费 120 × .0005，Mark=31 产生 (31-30) × 2 × 2，Funding=-(31 × 2 × 2) × .001。
    amount(&a["cash"], "19.816");
    amount(&a["equity"], "23.816");
    amount(&a["fees"], ".06");
    amount(&a["occupied_margin"], "12");
    amount(&a["maintenance_required"], ".496");
    amount(&a["collateral"], "23.816");
    amount(&a["available_margin"], "11.816");
    amount(&l["funding"], "-.124");
    amount(&l["equity"], "23.816");
    amount(&l["net_pnl"], "3.816");
    amount(&l["external_cash_flow"], "0");
    assert!(!l["simple_return"].is_null());
    let funding = &s["execution"]["perpetual"]["funding"]["funding-50"];
    amount(&funding["cashflow"]["amount"], "-.124");
    assert_eq!(funding["mark_fact_id"], "mark-50");
}
fn refresh_fill_observation(input: &mut Value) {
    let fact = onlyalpha_broker::Fact::decode(&input["payload"]["broker"]["record"]).unwrap();
    input["payload"]["broker"] =
        json!({"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":fact.record()});
}

#[test]
fn independent_multiplier_margin_fee_mark_and_funding_accounting() {
    let (cfg, inputs) = scenario();
    let mut rt = Driver::prefix(&cfg, &inputs, 2);
    let admitted = rt.state().unwrap();
    amount(&admitted["account"]["snapshot"]["reserved_margin"], "12");
    amount(&admitted["account"]["snapshot"]["cash"], "20");
    for input in &inputs[2..5] {
        rt.apply(input).unwrap();
    }
    let filled = rt.state().unwrap();
    amount(&filled["account"]["snapshot"]["occupied_margin"], "12");
    amount(
        &filled["account"]["snapshot"]["maintenance_required"],
        ".48",
    );
    amount(&filled["account"]["snapshot"]["cash"], "19.94");
    amount(&filled["account"]["snapshot"]["equity"], "19.94");
    for input in &inputs[5..] {
        rt.apply(input).unwrap();
    }
    verify(&rt.state().unwrap());
}

#[test]
fn unavailable_collateral_blocks_new_risk_while_original_funding_remains_payable() {
    let (mut cfg, mut inputs) = scenario();
    let raw = br#"{"at":"2026-09-01T08:00:00Z","price":"31.00","rate":"0.5"}"#;
    let original: Value = serde_json::from_slice(raw).unwrap();
    let sha = onlyalpha_execution::digest(raw);
    for input in &mut inputs[5..=6] {
        input["payload"]["fact"]["source_record_hash"] = json!(sha);
        input["payload"]["fact"]["provider_evidence_id"] = json!("row-liability");
    }
    inputs[5]["payload"]["fact"]["value"]["value"] = original["price"].clone();
    inputs[6]["payload"]["fact"]["rate"] = original["rate"].clone();
    bind_offline_source(&mut cfg, &inputs);
    let mut rt = Driver::prefix(&cfg, &inputs, 6);
    let liability = &inputs[6];
    rt.apply(liability).unwrap();
    let state = rt.state().unwrap();
    amount(&state["account"]["snapshot"]["cash"], "-42.06");
    amount(&state["account"]["snapshot"]["equity"], "-38.06");
    amount(
        &state["ledger"]["ledgers"]["cluster"]["snapshot"]["external_cash_flow"],
        "0",
    );
    let mut next = inputs[1].clone();
    next["runtime_sequence"] = json!(8);
    next["input_id"] = json!("input-8");
    next["source_ref"] = json!("occurrence-8");
    next["time"] = liability["time"].clone();
    next["payload"]["order"] = json!("runtime-ORDER-000002");
    next["payload"]["request"]["request_id"]["value"] = json!("next-request");
    assert!(rt.apply(&next).is_err());
    let restored = rt.recompute();
    assert_eq!(restored.state().unwrap(), state);
    assert_eq!(restored.applied(), rt.applied());
}

#[test]
fn new_version_rejects_uninstalled_shapes_and_original_mark_alias_stays_distinct() {
    let (cfg, inputs) = scenario();
    assert!(Components::new(cfg.clone()).is_ok());
    for (key, value) in [
        ("margin_mode", "ISOLATED"),
        ("position_mode", "HEDGING"),
        ("contract_type", "INVERSE"),
        ("account", "foreign-account"),
    ] {
        let mut foreign = cfg.clone();
        foreign["perpetual"][key] = json!(value);
        assert!(Components::new(foreign).is_err(), "{key}");
    }
    let mut wrong = cfg.clone();
    wrong["runtime_kind"] = json!("LIVE");
    assert!(Components::new(wrong).is_err());
    let mut reader = cfg.clone();
    reader["account_checkpoint_version"] = json!(4);
    assert!(Components::new(reader).is_err());
    let mut missing = cfg.clone();
    missing["perpetual"]["margin_segments"] = json!([]);
    assert!(Components::new(missing).is_err());
    let mut rt = Driver::prefix(&cfg, &inputs, 1);
    let before = rt.state().unwrap();
    let mut aliased = inputs[0].clone();
    aliased["input_id"] = json!("new-mark-envelope");
    aliased["source_ref"] = json!("other");
    aliased["runtime_sequence"] = json!(2);
    aliased["payload"]["fact"]["value"]["value"] = json!("30.01");
    assert!(rt.apply(&aliased).is_err());
    let restored = rt.recompute();
    assert_eq!(restored.state().unwrap(), before);
    assert_eq!(restored.applied(), rt.applied());
}

#[test]
fn reference_mark_precision_is_independent_of_the_order_price_tick() {
    let (mut cfg, mut inputs) = scenario();
    assert_eq!(cfg["instruments"][0]["price_precision"], 2);
    inputs[5]["payload"]["fact"]["value"] =
        json!({"schema_version":1,"precision":4,"value":"31.0001"});
    let raw_hash = onlyalpha_execution::digest(
        br#"{"at":"2026-09-01T08:00:00Z","price":"31.0001","rate":"0.001"}"#,
    );
    for input in &mut inputs[5..=6] {
        input["payload"]["fact"]["source_record_hash"] = json!(raw_hash);
        input["payload"]["fact"]["provider_evidence_id"] = json!("row-7-fine");
    }
    bind_offline_source(&mut cfg, &inputs);
    let runtime = Driver::prefix(&cfg, &inputs, 7);
    let state = runtime.state().unwrap();
    let acct = &state["account"]["snapshot"];
    let ledger = &state["ledger"]["ledgers"]["cluster"]["snapshot"];
    assert_eq!(
        state["execution"]["perpetual"]["marks"]["mark-50"],
        inputs[5]["payload"]["fact"]
    );
    assert_eq!(
        state["execution"]["margin_authority"]["config"]["observation_capacity"],
        512
    );
    amount(&acct["unrealized_pnl"], "4.0004");
    amount(&acct["maintenance_required"], ".49600160");
    amount(&ledger["funding"], "-.12400040");
    amount(&acct["cash"], "19.81599960");
    amount(&acct["equity"], "23.81639960");
    amount(&ledger["equity"], "23.81639960");
    let restored = runtime.recompute();
    assert_eq!(restored.state().unwrap(), state);
    assert_eq!(restored.applied(), runtime.applied());
}

#[test]
fn missing_mark_margin_tier_preserves_the_original_valuation_and_funding() {
    let (mut cfg, mut inputs) = scenario();
    cfg["instruments"][0]["quantity_precision"] = json!(1);
    cfg["perpetual"]["limit_rules"]["quantity_step"] = json!("0.1");
    inputs[1]["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"precision":1,"value":"2.0"});
    inputs[4]["payload"]["broker"]["record"]["payload"]["fill"]["quantity"] =
        inputs[1]["payload"]["request"]["quantity"].clone();
    refresh_fill_observation(&mut inputs[4]);
    cfg["perpetual"]["margin_segments"][0]["upper_bound"] = json!("121");
    let mut back = inputs[5].clone();
    back["runtime_sequence"] = json!(8);
    back["input_id"] = json!("mark-return-input");
    back["source_ref"] = json!("return-observation");
    back["time"] = json!(1788249660000000000_u64);
    let raw = &mut back["payload"]["fact"];
    raw["fact_id"] = json!("mark-51");
    raw["source_sequence"] = json!(51);
    raw["value"]["value"] = json!("30.00");
    raw["ts_event"] = json!("2026-09-01T08:01:00Z");
    raw["ts_init"] = raw["ts_event"].clone();
    raw["source_record_hash"] = json!(onlyalpha_execution::digest(
        br#"{"at":"2026-09-01T08:01:00Z","price":"30.00"}"#
    ));
    raw["provider_evidence_id"] = json!("source-row-8");
    inputs.push(back.clone());
    let mut safe = back.clone();
    safe["runtime_sequence"] = json!(9);
    safe["input_id"] = json!("mark-safe-input");
    safe["source_ref"] = json!("safe-observation");
    safe["time"] = json!(1788249720000000000_u64);
    let raw = &mut safe["payload"]["fact"];
    raw["fact_id"] = json!("mark-52");
    raw["source_sequence"] = json!(52);
    raw["value"]["value"] = json!("28.50");
    raw["ts_event"] = json!("2026-09-01T08:02:00Z");
    raw["ts_init"] = raw["ts_event"].clone();
    raw["source_record_hash"] = json!(onlyalpha_execution::digest(
        br#"{"at":"2026-09-01T08:02:00Z","price":"28.50"}"#
    ));
    raw["provider_evidence_id"] = json!("source-row-9");
    inputs.push(safe.clone());
    compile_synthetic_rules(&mut cfg, &mut inputs);
    bind_offline_source(&mut cfg, &inputs);
    let mut runtime = Driver::prefix(&cfg, &inputs, 5);
    let entry = runtime.state().unwrap();
    let last = entry["account"]["snapshot"]["last_confirmed_maintenance"].clone();
    amount(&entry["account"]["snapshot"]["occupied_margin"], "12");
    amount(&last["amount"], ".48");
    assert_eq!(last["time"], inputs[4]["time"]);

    runtime.apply(&inputs[5]).unwrap();
    let marked = runtime.state().unwrap();
    assert_eq!(
        marked["execution"]["perpetual"]["marks"]["mark-50"],
        inputs[5]["payload"]["fact"]
    );
    let account = &marked["account"]["snapshot"];
    amount(&account["unrealized_pnl"], "4");
    amount(&account["equity"], "23.94");
    assert_eq!(account["maintenance_status"], "UNAVAILABLE");
    assert!(
        account["maintenance_required"].is_null() && account["maintenance_to_equity"].is_null()
    );
    assert_eq!(account["last_confirmed_maintenance"], last);

    runtime.apply(&inputs[6]).unwrap();
    let funded = runtime.state().unwrap();
    assert_eq!(
        funded["execution"]["perpetual"]["funding"]["funding-50"]["fact"],
        inputs[6]["payload"]["fact"]
    );
    amount(
        &funded["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "-.124",
    );
    amount(&funded["account"]["snapshot"]["cash"], "19.816");
    amount(&funded["account"]["snapshot"]["equity"], "23.816");
    assert_eq!(
        funded["account"]["snapshot"]["last_confirmed_maintenance"],
        last
    );
    assert_eq!(runtime.retained(), 7);

    // 新申请自身只增加 0.50 名义；已有仓位的维护要求缺证就须拒绝。
    let mut next = inputs[1].clone();
    next["runtime_sequence"] = json!(8);
    next["input_id"] = json!("second-risk");
    next["source_ref"] = json!("second-risk-source");
    next["time"] = json!(inputs[6]["time"].as_u64().unwrap() + 1);
    next["payload"]["order"] = json!("runtime-ORDER-000002");
    next["payload"]["request"]["request_id"]["value"] = json!("second-request");
    next["payload"]["request"]["quantity"]["value"] = json!("0.1");
    next["payload"]["request"]["price"]["value"] = json!("2.50");
    assert_eq!(
        runtime.apply(&next).unwrap_err().0,
        "MARGIN_MAINTENANCE_UNAVAILABLE"
    );
    let mut restored = runtime.recompute();
    assert_eq!(restored.state().unwrap(), funded);
    assert_eq!(restored.retained(), 7);
    restored.apply(&inputs[6]).unwrap();
    assert_eq!(restored.state().unwrap(), funded);
    assert_eq!(restored.retained(), 7);
    restored.apply(&back).unwrap();
    let current = restored.state().unwrap();
    let account = &current["account"]["snapshot"];
    assert_eq!(account["maintenance_status"], "CURRENT");
    amount(&account["maintenance_required"], ".48");
    assert_eq!(account["last_confirmed_maintenance"]["time"], back["time"]);
    assert_eq!(
        current["execution"]["perpetual"]["marks"]["mark-51"],
        back["payload"]["fact"]
    );
    amount(&account["equity"], "19.816");
    restored.apply(&safe).unwrap();
    amount(
        &restored.state().unwrap()["account"]["snapshot"]["equity"],
        "13.816",
    );
    next["time"] = safe["time"].clone();
    next["runtime_sequence"] = json!(10);
    restored.apply(&next).unwrap();
    let resumed = restored.state().unwrap();
    amount(&resumed["account"]["snapshot"]["reserved_margin"], ".05");
    let history = restored.retained();
    let fresh = restored.recompute();
    assert_eq!(fresh.state().unwrap(), resumed);
    assert_eq!(fresh.retained(), history);
}

#[test]
fn pending_open_orders_share_the_frozen_margin_tier_at_admission() {
    let (mut cfg, inputs) = scenario();
    cfg["initial_cash"] = json!("1000.00000000");
    cfg["capitals"]["cluster"] = json!("1000.00000000");
    assert_eq!(cfg["profiles"]["cluster"]["rules"], json!([]));
    let next = |seq: u64, policy: &Value| {
        let mut input = inputs[1].clone();
        input["runtime_sequence"] = json!(seq);
        input["input_id"] = json!(format!("attempt-{seq}"));
        input["source_ref"] = json!(format!("attempt-source-{seq}"));
        input["payload"]["order"] = json!("runtime-ORDER-000002");
        input["payload"]["request"]["request_id"]["value"] = json!("another-open");
        input["payload"]["policy_fingerprint"] = policy.clone();
        input
    };

    // 除冻结模型上界外，使用相同资金、请求、序列及 Risk 前置，两单均可进入较宽的档位。
    let mut wide = Driver::prefix(&cfg, &inputs, 2);
    wide.apply(&next(3, &cfg["perpetual"]["policy_fingerprint"]))
        .unwrap();
    amount(
        &wide.state().unwrap()["account"]["snapshot"]["reserved_margin"],
        "24",
    );

    // 名义仍在域内但有两档初始斜率。新单先成交会令原单按第二档占用最多 24，其预留只有 12。
    let mut stepped = cfg.clone();
    stepped["perpetual"]["margin_segments"][0]["upper_bound"] = json!("120");
    let mut higher = stepped["perpetual"]["margin_segments"][0].clone();
    higher["lower_bound"] = json!("120");
    higher["upper_bound"] = json!("1000");
    higher["initial_slope"] = json!("0.2");
    higher["initial_intercept"] = json!("-12");
    stepped["perpetual"]["margin_segments"]
        .as_array_mut()
        .unwrap()
        .push(higher);
    let mut stepped_inputs = inputs.clone();
    compile_synthetic_rules(&mut stepped, &mut stepped_inputs);
    let mut existing = Driver::prefix(&stepped, &stepped_inputs, 2);
    let original = existing.state().unwrap();
    assert_eq!(
        existing
            .apply(&next(3, &stepped["perpetual"]["policy_fingerprint"]))
            .unwrap_err()
            .0,
        "EXECUTION_EXISTING_MARGIN_COVERAGE"
    );
    assert_eq!(existing.recompute().state().unwrap(), original);

    cfg["perpetual"]["margin_segments"][0]["upper_bound"] = json!("121");
    let mut narrow_inputs = inputs.clone();
    compile_synthetic_rules(&mut cfg, &mut narrow_inputs);
    let mut run = Driver::prefix(&cfg, &narrow_inputs, 2);
    let mut unknown = inputs[2].clone();
    unknown["payload"]["outcome"] = json!("UNKNOWN");
    let mut cancel = unknown.clone();
    cancel["runtime_sequence"] = json!(4);
    cancel["input_id"] = json!("cancel-4");
    cancel["source_ref"] = json!("cancel-source-4");
    cancel["op"] = json!("CANCEL");
    cancel["payload"] = json!({"schema_version":1,"order":"runtime-ORDER-000001","request_id":"cancel-first","reason":"withdraw pending order"});
    for (sequence, original) in [(3, None), (4, Some(unknown)), (5, Some(cancel))] {
        if let Some(input) = original {
            run.apply(&input).unwrap();
        }
        let prefix = run.state().unwrap();
        let records = run.applied().len();
        amount(&prefix["account"]["snapshot"]["cash"], "1000");
        amount(&prefix["account"]["snapshot"]["reserved_margin"], "12");
        assert_eq!(
            run.apply(&next(sequence, &cfg["perpetual"]["policy_fingerprint"]))
                .unwrap_err()
                .0,
            "EXECUTION_MARGIN_NOTIONAL_DOMAIN"
        );
        run = run.recompute();
        assert_eq!(run.state().unwrap(), prefix);
        assert_eq!(run.applied().len(), records);
    }
}

#[test]
fn altered_funding_rate_cannot_borrow_a_bound_source_record_hash() {
    let (cfg, inputs) = scenario();
    let mut run = Driver::prefix(&cfg, &inputs, 6);
    let before = run.state().unwrap();
    let mut changed = inputs[6].clone();
    changed["payload"]["fact"]["rate"] = json!("0.5");
    assert!(run.apply(&changed).is_err());
    let restored = run.recompute();
    assert_eq!(restored.state().unwrap(), before);
    assert_eq!(restored.applied().len(), 6);
}

#[test]
fn pending_and_new_fills_must_fit_the_current_mark_notional_domain() {
    let (mut cfg, mut inputs) = scenario();
    cfg["initial_cash"] = json!("1000.00000000");
    cfg["capitals"]["cluster"] = json!("1000.00000000");
    inputs[0]["payload"]["fact"]["value"]["value"] = json!("31.00");
    bind_offline_source(&mut cfg, &inputs);
    let mut second = inputs[1].clone();
    second["runtime_sequence"] = json!(3);
    second["input_id"] = json!("second");
    second["source_ref"] = json!("second-source");
    second["payload"]["order"] = json!("runtime-ORDER-000002");
    second["payload"]["request"]["request_id"]["value"] = json!("second-open");
    for (cap, cut) in [("1000", 2), ("121", 1), ("243", 2)] {
        cfg["perpetual"]["margin_segments"][0]["upper_bound"] = json!(cap);
        compile_synthetic_rules(&mut cfg, &mut inputs);
        second["payload"]["policy_fingerprint"] = cfg["perpetual"]["policy_fingerprint"].clone();
        let mut run = Driver::prefix(&cfg, &inputs, cut);
        let before = run.state().unwrap();
        let records = run.applied().len();
        let next = if cut == 1 { &inputs[1] } else { &second };
        let result = run.apply(next);
        if cap == "1000" {
            result.unwrap();
        } else {
            assert_eq!(result.unwrap_err().0, "EXECUTION_MARGIN_NOTIONAL_DOMAIN");
            let restored = run.recompute();
            assert_eq!(restored.state().unwrap(), before);
            assert_eq!(restored.applied().len(), records);
        }
    }
}

#[test]
fn frozen_margin_configuration_proves_every_supported_occupancy_increment() {
    let (mut cfg, mut inputs) = scenario();
    cfg["perpetual"]["margin_segments"][0]["upper_bound"] = json!("120");
    let next = json!({"lower_bound":"120","upper_bound":"200","initial_slope":"0.1","initial_intercept":"0","maintenance_slope":"0.2","maintenance_intercept":"-23.52"});
    cfg["perpetual"]["margin_segments"]
        .as_array_mut()
        .unwrap()
        .push(next);
    compile_synthetic_rules(&mut cfg, &mut inputs);
    assert!(
        Components::new(cfg).is_err(),
        "at 120→180 maintenance increases by 12 but the owner supports at most 6"
    );
}

#[test]
fn gtc_fee_reservation_covers_future_effective_rates_and_uses_the_fill_economic_day() {
    let (mut cfg, mut inputs) = scenario();
    let schedules = cfg["perpetual"]["fee_catalog"]["schedules"]
        .as_array_mut()
        .unwrap();
    let market = &mut schedules[0];
    market["to"] = json!(2);
    for rule in market["rules"].as_array_mut().unwrap() {
        rule["resolution"] = json!("FILL_EFFECTIVE");
        rule["terms"] = json!([{"kind":"FIXED","amount":"0"}]);
    }
    let mut future = market.clone();
    future["from"] = json!(2);
    future["to"] = Value::Null;
    future["version"] = json!("2");
    for rule in future["rules"].as_array_mut().unwrap() {
        rule["terms"][0]["amount"] = json!("1");
    }
    let gap = cfg.clone();
    cfg["perpetual"]["fee_catalog"]["schedules"]
        .as_array_mut()
        .unwrap()
        .push(future);
    inputs[1]["payload"]["request"]["quantity"]["value"] = json!("1");
    let fill = &mut inputs[4];
    fill["payload"]["broker"]["record"]["payload"]["fill"]["quantity"]["value"] = json!("1");
    let day_two = fill["time"].as_u64().unwrap() + 86_400_000_000_000;
    fill["time"] = json!(day_two);
    fill["trading_day"] = json!("2026-09-02");
    fill["day_index"] = json!(2);
    // 实际场所原件保留原经济日与原生成时刻，运行在第二日才可见。
    refresh_fill_observation(fill);
    let mut run = Driver::prefix(&cfg, &inputs, 2);
    amount(&run.state().unwrap()["account"]["snapshot"]["reserved"], "1");
    for item in &inputs[2..5] {
        run.apply(item).unwrap();
    }
    amount(&run.state().unwrap()["account"]["snapshot"]["fees"], "0");
    let mut denied = Driver::prefix(&gap, &inputs, 1);
    assert!(
        denied.apply(&inputs[1]).is_err(),
        "open-ended order would reach a fee schedule gap"
    );
    let mut economic = inputs[4].clone();
    economic["payload"]["broker"]["record"]["ts_event"] = json!(day_two);
    economic["payload"]["broker"]["record"]["ts_init"] = json!(day_two);
    economic["payload"]["broker"]["record"]["payload"]["fill"]["ts_init"]["unix_nanos"] =
        json!(day_two);
    economic["payload"]["broker"]["record"]["payload"]["fill"]["ts_event"]["unix_nanos"] =
        json!(day_two);
    refresh_fill_observation(&mut economic);
    inputs[4] = economic.clone();
    let mut later = Driver::prefix(&cfg, &inputs, 4);
    later.apply(&economic).unwrap();
    amount(&later.state().unwrap()["account"]["snapshot"]["fees"], "1");
}

#[test]
fn perpetual_flat_fractional_fills_use_exact_cost_before_rounding_cash() {
    for multiplier in ["1", "2"] {
        let (mut cfg, mut inputs) = scenario();
        cfg["currency"]["precision"] = json!(2);
        cfg["perpetual"]["currency"] = cfg["currency"].clone();
        cfg["initial_cash"] = json!("20.00");
        cfg["capitals"]["cluster"] = json!("20.00");
        cfg["instruments"][0]["multiplier"] = json!(multiplier);
        cfg["perpetual"]["multiplier"] = json!(multiplier);
        cfg["perpetual"]["limit_rules"]["multiplier"] = json!(multiplier);
        cfg["instruments"][0]["quantity_precision"] = json!(1);
        for schedule in cfg["perpetual"]["fee_catalog"]["schedules"]
            .as_array_mut()
            .unwrap()
        {
            for rule in schedule["rules"].as_array_mut().unwrap() {
                rule["quantum"] = json!("0.01");
                rule["terms"] = json!([{"kind":"FIXED","amount":"0"}]);
            }
        }
        inputs[0]["payload"]["fact"]["value"]["value"] = json!("30.01");
        let req = &mut inputs[1]["payload"]["request"];
        req["quantity"] = json!({"schema_version":1,"precision":1,"value":"0.2"});
        req["price"]["value"] = json!("30.01");
        let f = &mut inputs[4]["payload"]["broker"]["record"]["payload"]["fill"];
        f["quantity"] = json!({"schema_version":1,"precision":1,"value":"0.1"});
        f["price"]["value"] = json!("30.01");
        f["reference_price"]["value"] = json!("30.01");
        refresh_fill_observation(&mut inputs[4]);
        let mut second = inputs[4].clone();
        second["runtime_sequence"] = json!(6);
        second["input_id"] = json!("next-fill");
        second["source_ref"] = json!("second-fill");
        let record = &mut second["payload"]["broker"]["record"];
        record["source_sequence"] = json!(3);
        record["update_id"] = json!("virtual-update-00000003");
        let f = &mut record["payload"]["fill"];
        f["external_sequence"] = json!(3);
        f["external_event_id"] = json!("virtual-fill-00000002");
        f["trade_id"]["value"] = json!("virtual-trade-00000002");
        f["venue_trade_id"]["value"] = json!("virtual-venue-trade-00000002");
        refresh_fill_observation(&mut second);
        let mut mark = inputs[5].clone();
        mark["runtime_sequence"] = json!(7);
        mark["payload"]["fact"]["value"] =
            json!({"schema_version":1,"value":"30.051","precision":3});
        inputs.truncate(5);
        inputs.push(second.clone());
        inputs.push(mark.clone());
        compile_synthetic_rules(&mut cfg, &mut inputs);
        bind_offline_source(&mut cfg, &inputs);
        let mut run = Driver::prefix(&cfg, &inputs, 5);
        amount(
            &run.state().unwrap()["account"]["snapshot"]["unrealized_pnl"],
            "0",
        );
        run.apply(&second).unwrap();
        let flat = run.state().unwrap();
        amount(&flat["account"]["snapshot"]["unrealized_pnl"], "0");
        amount(&flat["account"]["snapshot"]["equity"], "20");
        amount(
            &flat["ledger"]["ledgers"]["cluster"]["snapshot"]["equity"],
            "20",
        );
        run.apply(&mark).unwrap();
        let current = run.state().unwrap();
        let (pnl, cash) = if multiplier == "1" {
            (".0082", "20.01")
        } else {
            (".0164", "20.02")
        };
        amount(&current["account"]["snapshot"]["unrealized_pnl"], pnl);
        amount(&current["account"]["snapshot"]["equity"], cash);
        amount(
            &current["ledger"]["ledgers"]["cluster"]["snapshot"]["equity"],
            cash,
        );
        let restored = run.recompute();
        assert_eq!(restored.state().unwrap(), current);
        assert_eq!(restored.applied(), run.applied());
    }
}

#[test]
fn original_source_rows_must_be_canonical_under_the_frozen_cut_digest() {
    let (cfg, _) = scenario();
    let rows = cfg["perpetual"]["source_rows"].clone();
    let expected = cfg["perpetual"]["source_cut_sha256"].as_str().unwrap();
    MarketSourceCut::read(&serde_json::to_vec(&rows).unwrap(), expected).unwrap();

    // 重排字节而不更新冻结摘要：切口身份必须失配。
    let mut reordered = rows.clone();
    reordered.as_array_mut().unwrap().reverse();
    let bytes = serde_json::to_vec(&reordered).unwrap();
    let rewritten = onlyalpha_execution::digest(&bytes);
    assert!(MarketSourceCut::read(&bytes, expected).is_err());
    assert!(MarketSourceCut::read(&bytes, &rewritten).is_ok());

    // 原始行摘要与事实都不允许被改写。
    for tamper in ["raw_sha256", "facts", "extra"] {
        let mut altered = rows.clone();
        let row = altered.as_array_mut().unwrap().last_mut().unwrap();
        match tamper {
            "raw_sha256" => row["raw_sha256"] = json!("0".repeat(64)),
            "facts" => row["facts"][1]["note"] = json!("foreign"),
            _ => row["note"] = json!("foreign"),
        }
        let bytes = serde_json::to_vec(&altered).unwrap();
        let digest = onlyalpha_execution::digest(&bytes);
        assert!(
            MarketSourceCut::read(&bytes, &digest).is_err(),
            "{tamper} was accepted"
        );
    }
}

#[test]
fn funding_requires_economic_watermark_and_all_original_boundary_trades_ready() {
    let (cfg, inputs) = scenario();
    let mut runtime = Driver::prefix_closing(&cfg, &inputs, 4, false);
    let mut mark = inputs[5].clone();
    mark["runtime_sequence"] = json!(5);
    runtime.apply(&mark).unwrap();
    let before = runtime.state().unwrap();
    let records = runtime.applied().len();
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(6);
    assert!(
        runtime
            .apply(&funding)
            .unwrap_err()
            .0
            .contains("BROKER_ECONOMIC_PREFIX_UNPROVEN")
    );
    let mut runtime = runtime.recompute();
    assert_eq!(runtime.state().unwrap(), before);
    assert_eq!(runtime.applied().len(), records);
    runtime.advance(funding["time"].as_i64().unwrap()).unwrap();
    assert_eq!(
        runtime.apply(&funding).unwrap_err().0,
        "EXECUTION_FUNDING_UNAPPLIED_TRADE"
    );
    let mut runtime = runtime.recompute();
    assert_eq!(runtime.state().unwrap(), before);
    let mut fill = inputs[4].clone();
    fill["runtime_sequence"] = json!(6);
    fill["time"] = funding["time"].clone();
    runtime.apply(&fill).unwrap();
    runtime.advance(funding["time"].as_i64().unwrap()).unwrap();
    runtime.apply(&inputs[6]).unwrap();
    amount(
        &runtime.state().unwrap()["account"]["snapshot"]["cash"],
        "19.816",
    );
    let final_state = runtime.state().unwrap();
    assert_eq!(runtime.recompute().state().unwrap(), final_state);
}

#[test]
fn utc_compilation_epoch_controls_processing_days_and_future_admission() {
    let (cfg, inputs) = scenario();
    for (key, value) in [
        ("trading_day", json!("2026-09-02")),
        ("day_index", json!(2)),
    ] {
        let mut run = Driver::prefix(&cfg, &inputs, 1);
        let before = run.state().unwrap();
        let mut wrong = inputs[1].clone();
        wrong[key] = value;
        assert_eq!(
            run.apply(&wrong).unwrap_err().0,
            "EXECUTION_PERPETUAL_TRADING_DAY"
        );
        assert_eq!(run.recompute().state().unwrap(), before);
    }
    // 同日真实新编译身份仍不能向编译时点之前的请求签发准入。
    let mut future = cfg.clone();
    let mut rows = inputs.clone();
    future["perpetual"]["limit_rules"]["effective_from"] = json!("2026-09-01T08:00:00Z");
    compile_synthetic_rules(&mut future, &mut rows);
    let mut run = Driver::prefix(&future, &rows, 1);
    assert_eq!(
        run.apply(&rows[1]).unwrap_err().0,
        "EXECUTION_MARKET_LIMIT_RULES"
    );
    // 完整当前编译包能准入原请求。
    let run = Driver::prefix(&cfg, &inputs, 2);
    amount(
        &run.state().unwrap()["account"]["snapshot"]["reserved_margin"],
        "12",
    );
    for (key, value) in [
        ("timezone", json!("Asia/Shanghai")),
        ("continuous_24x7", json!(false)),
    ] {
        let mut changed = cfg.clone();
        let mut body: Value = serde_json::from_str(
            changed["perpetual"]["compiled_policy_json"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        body[key] = value;
        let raw = body.to_string();
        let policy = onlyalpha_execution::digest(raw.as_bytes());
        use onlyalpha_domain::{base::OnlyDomainModel, market_rules::OnlyStaticLimitRules};
        let rules = OnlyStaticLimitRules::from_compiled_policy_json(&raw, &policy).unwrap();
        changed["perpetual"]["compiled_policy_json"] = json!(raw);
        changed["perpetual"]["policy_fingerprint"] = json!(policy);
        changed["perpetual"]["limit_rules"] = rules.to_record();
        changed["perpetual"]["limit_rules_fingerprint"] = json!(rules.content_fingerprint());
        assert!(Components::new(changed).is_err());
    }
}

// 一份真实冻结合约的两个成交量子跨过维护额的 HALF_EVEN 舍入格。
#[derive(Clone, Copy, PartialEq, Eq)]
enum MarginFillCase {
    Partial,
    CrossOrder,
    ExactCost,
    ChangedMark,
}
fn rounded_margin_fill_case(case: MarginFillCase, precision: u8) {
    let split_orders = case == MarginFillCase::CrossOrder;
    let precise = case == MarginFillCase::ExactCost;
    let changed_mark = case == MarginFillCase::ChangedMark;
    let price = if precise { "0.010501" } else { "0.01" };
    let price_precision = if precise { 6 } else { 2 };
    use onlyalpha_broker::{Scope};
    let (mut cfg, mut inputs) = scenario();
    cfg["currency"]["precision"] = json!(precision);
    cfg["perpetual"]["currency"] = cfg["currency"].clone();
    cfg["initial_cash"] = json!(if precision == 2 {
        "20.00"
    } else {
        "20.00000000"
    });
    cfg["capitals"]["cluster"] = cfg["initial_cash"].clone();
    cfg["instruments"][0]["multiplier"] = json!("1");
    cfg["instruments"][0]["price_precision"] = json!(price_precision);
    cfg["perpetual"]["multiplier"] = json!("1");
    let rules = &mut cfg["perpetual"]["limit_rules"];
    rules["multiplier"] = json!("1");
    rules["price_tick"] = json!(if precise { "0.000001" } else { "0.01" });
    rules["quantity_step"] = json!("1");
    rules["minimum_quantity"] = json!("1");
    rules["minimum_notional"] = json!("0.01");
    cfg["perpetual"]["margin_segments"] = json!([{"lower_bound":"0","upper_bound":null,"initial_slope":"0.1","initial_intercept":"0","maintenance_slope":if split_orders { "0.099" } else { "0.005" },"maintenance_intercept":"0"}]);
    for schedule in cfg["perpetual"]["fee_catalog"]["schedules"]
        .as_array_mut()
        .unwrap()
    {
        for rule in schedule["rules"].as_array_mut().unwrap() {
            rule["quantum"] = json!(if precision == 2 { "0.01" } else { "0.00000001" });
            rule["terms"] = json!([{"kind":"FIXED","amount":"0"}]);
        }
    }
    let mut later_mark = inputs[5].clone();
    inputs.truncate(5);
    let mark = &mut inputs[0]["payload"]["fact"];
    mark["fact_id"] = json!("rounded-margin-initial-mark");
    mark["value"] = json!({"schema_version":1,"precision":price_precision,"value":price});
    mark["provider_evidence_id"] = json!("rounded-margin-original-row");
    let raw = json!({"at":mark["ts_event"],"price":price}).to_string();
    mark["source_record_hash"] = json!(onlyalpha_execution::digest(raw.as_bytes()));
    assert_eq!(
        OnlyReferencePriceFact::from_record(mark)
            .unwrap()
            .to_record(),
        *mark
    );
    let order_price = mark["value"].clone();
    inputs[1]["payload"]["request"]["price"] = order_price;
    inputs[1]["payload"]["request"]["quantity"]["value"] = json!(if split_orders {
        "106"
    } else if precise {
        "200"
    } else {
        "101"
    });
    let fill = &mut inputs[4]["payload"]["broker"]["record"]["payload"]["fill"];
    fill["price"] = json!({"schema_version":1,"precision":price_precision,"value":price});
    fill["reference_price"] = fill["price"].clone();
    fill["quantity"]["value"] = json!(if split_orders { "106" } else { "100" });
    refresh_fill_observation(&mut inputs[4]);
    assert_eq!(
        OnlyOrderRequest::from_record(&inputs[1]["payload"]["request"])
            .unwrap()
            .to_record(),
        inputs[1]["payload"]["request"]
    );
    compile_synthetic_rules(&mut cfg, &mut inputs);
    if changed_mark {
        later_mark["input_id"] = json!("rounded-later-mark-input");
        later_mark["source_ref"] = json!("rounded-later-mark-source");
        later_mark["runtime_sequence"] = json!(6);
        let mark = &mut later_mark["payload"]["fact"];
        mark["fact_id"] = json!("rounded-margin-later-mark");
        mark["value"] = json!({"schema_version":1,"precision":2,"value":"1.00"});
        mark["provider_evidence_id"] = json!("rounded-later-original-row");
        let raw = json!({"at":mark["ts_event"],"price":"1.00"}).to_string();
        mark["source_record_hash"] = json!(onlyalpha_execution::digest(raw.as_bytes()));
        assert_eq!(
            OnlyReferencePriceFact::from_record(mark)
                .unwrap()
                .to_record(),
            *mark
        );
        inputs.push(later_mark.clone());
    }
    bind_offline_source(&mut cfg, &inputs);
    let runtime = Driver::prefix(&cfg, &inputs, 5);
    let first = runtime.state().unwrap();
    let first_initial = match (split_orders, precision) {
        (true, 2) => ".11",
        (true, _) => ".106",
        (false, _) => {
            if precise {
                ".11"
            } else {
                ".10"
            }
        }
    };
    let first_maintenance = match (split_orders, precision) {
        (true, 2) => ".10",
        (true, _) => ".10494",
        (false, 2) => {
            if precise {
                ".01"
            } else {
                "0"
            }
        }
        (false, _) => ".005",
    };
    amount(
        &first["account"]["snapshot"]["occupied_margin"],
        first_initial,
    );
    amount(
        &first["account"]["snapshot"]["maintenance_required"],
        first_maintenance,
    );
    amount(&first["account"]["snapshot"]["cash"], "20");
    let mut runtime = runtime.recompute();
    assert_eq!(runtime.state().unwrap(), first);
    if changed_mark {
        runtime.apply(&later_mark).unwrap();
        amount(
            &runtime.state().unwrap()["account"]["snapshot"]["maintenance_required"],
            ".50",
        );
        amount(
            &runtime.state().unwrap()["account"]["snapshot"]["occupied_margin"],
            ".10",
        );
    }
    let scope = Scope::decode(&inputs[3]["payload"]["broker"]["record"]["scope"]).unwrap();
    let mut second = inputs[4].clone();
    second["runtime_sequence"] = json!(if split_orders {
        9
    } else if changed_mark {
        7
    } else {
        6
    });
    second["input_id"] = json!("rounded-second-fill");
    second["source_ref"] = json!("rounded-second-fill-source");
    if changed_mark {
        second["time"] = later_mark["time"].clone();
        let time = second["time"].clone();
        let record = &mut second["payload"]["broker"]["record"];
        record["ts_event"] = time.clone();
        record["ts_init"] = time.clone();
        record["payload"]["fill"]["ts_event"]["unix_nanos"] = time.clone();
        record["payload"]["fill"]["ts_init"]["unix_nanos"] = time;
    }
    if split_orders {
        let order = "runtime-ORDER-000002";
        let mut admit = inputs[1].clone();
        admit["runtime_sequence"] = json!(6);
        admit["input_id"] = json!("rounded-second-admit");
        admit["source_ref"] = json!("rounded-second-admit-source");
        admit["payload"]["order"] = json!(order);
        admit["payload"]["request"]["request_id"]["value"] = json!("rounded-second-request");
        admit["payload"]["request"]["quantity"]["value"] = json!("11");
        assert_eq!(
            OnlyOrderRequest::from_record(&admit["payload"]["request"])
                .unwrap()
                .to_record(),
            admit["payload"]["request"]
        );
        runtime.apply(&admit).unwrap();
        amount(
            &runtime.state().unwrap()["account"]["snapshot"]["reserved_margin"],
            if precision == 2 { ".01" } else { ".011" },
        );
        let row = runtime.order("cluster", order).unwrap();
        let command = onlyalpha_broker::BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"rounded-submit-2","order":order,"client":row["client_order_id"]["value"],"request":admit["payload"]["request"]})).unwrap();
        runtime.dispatch(&command).unwrap();
        let mut submitted = inputs[2].clone();
        submitted["runtime_sequence"] = json!(7);
        submitted["input_id"] = json!("rounded-second-submission");
        submitted["source_ref"] = json!("rounded-second-submission-source");
        submitted["payload"]["order"] = json!(order);
        runtime.apply(&submitted).unwrap();
        let mut accepted = inputs[3].clone();
        accepted["runtime_sequence"] = json!(8);
        accepted["input_id"] = json!("rounded-second-accept");
        accepted["source_ref"] = json!("rounded-second-accept-source");
        accepted["payload"]["order"] = json!(order);
        let now = runtime.now();
        runtime.advance(now).unwrap();
        runtime.publish().unwrap();
        let original = runtime
            .pending()
            .iter()
            .find(|f| f.order() == Some(order) && f.record()["kind"] == "ACCEPTED")
            .unwrap();
        accepted["payload"]["broker"] = json!({"record":original.record(),"id":original.identity(),"fingerprint":original.fingerprint()});
        runtime.apply(&accepted).unwrap();
        second["payload"]["order"] = json!(order);
    }
    runtime
        .bar(
            2,
            &venue_bar(
                &inputs[1]["payload"]["request"],
                2,
                second["time"].as_i64().unwrap(),
            ),
        )
        .unwrap();
    runtime.publish().unwrap();
    let original = runtime
        .pending()
        .iter()
        .rfind(|f| f.record()["kind"] == "TRADE")
        .unwrap();
    amount(
        &original.record()["payload"]["fill"]["quantity"]["value"],
        if split_orders {
            "11"
        } else if precise {
            "100"
        } else {
            "1"
        },
    );
    assert_eq!(original.record()["ts_event"], second["time"]);
    second["payload"]["broker"] = json!({"record":original.record(),"id":original.identity(),"fingerprint":original.fingerprint()});
    runtime.apply(&second).unwrap();
    let final_state = runtime.state().unwrap();
    let account = &final_state["account"]["snapshot"];
    let total_initial = match (split_orders, precision) {
        (true, 2) => ".12",
        (true, _) => ".117",
        (false, 2) => {
            if precise {
                ".21"
            } else {
                ".10"
            }
        }
        (false, _) => ".101",
    };
    let total_maintenance = match (split_orders, precision) {
        (true, 2) => ".12",
        (true, _) => ".11583",
        (false, 2) => {
            if changed_mark {
                ".50"
            } else {
                ".01"
            }
        }
        (false, _) => ".00505",
    };
    amount(&account["occupied_margin"], total_initial);
    amount(&account["maintenance_required"], total_maintenance);
    amount(&account["cash"], "20");
    if changed_mark {
        amount(&account["equity"], "119.99");
        let states = final_state["execution"]["margin_authority"]["states"]
            .as_object()
            .unwrap();
        assert_eq!(states.len(), 1);
        amount(&states.values().next().unwrap()["entry_maintenance"], ".01");
    }
    let view = runtime.position_order_view().unwrap();
    let orders = view["orders"].as_object().unwrap();
    assert_eq!(orders.len(), if split_orders { 2 } else { 1 });
    for id in orders.keys() {
        assert_eq!(runtime.order("cluster", id).unwrap()["status"], "FILLED");
    }
    let trades = final_state["execution"]["perpetual"]["broker_facts"]
        .as_object()
        .unwrap()
        .values()
        .filter(|v| v["broker"]["record"]["kind"] == "TRADE")
        .count();
    assert_eq!(trades, 2);
    let history = runtime.applied().len();
    let restored = runtime.recompute();
    assert_eq!(restored.state().unwrap(), final_state);
    assert_eq!(restored.applied().len(), history);
}

#[test]
fn rounded_margin_single_order_partial_fills_preserve_exact_entry_requirements() {
    rounded_margin_fill_case(MarginFillCase::Partial, 2);
}
#[test]
fn rounded_margin_cross_orders_share_exact_entry_requirements() {
    rounded_margin_fill_case(MarginFillCase::CrossOrder, 2);
}
#[test]
fn fine_currency_margin_control_supports_the_same_single_and_cross_order_fills() {
    rounded_margin_fill_case(MarginFillCase::Partial, 8);
    rounded_margin_fill_case(MarginFillCase::CrossOrder, 8);
}

#[test]
fn exact_entry_cost_is_not_reconstructed_from_rounded_settlement_notional() {
    rounded_margin_fill_case(MarginFillCase::ExactCost, 2);
}

#[test]
fn frozen_entry_margin_curve_requires_a_zero_initial_and_maintenance_origin() {
    let (cfg, inputs) = scenario();
    Components::new(cfg.clone()).unwrap();
    for (initial, maintenance) in [("1", "0"), ("1", "0.5")] {
        let mut changed = cfg.clone();
        changed["perpetual"]["margin_segments"][0]["initial_intercept"] = json!(initial);
        changed["perpetual"]["margin_segments"][0]["maintenance_intercept"] = json!(maintenance);
        compile_synthetic_rules(&mut changed, &mut inputs.clone());
        assert!(
            Components::new(changed).is_err(),
            "nonzero origin {initial}/{maintenance} was accepted"
        );
    }
}

#[test]
fn original_fill_uses_entry_pool_proof_even_when_current_mark_maintenance_is_higher() {
    rounded_margin_fill_case(MarginFillCase::ChangedMark, 2);
}
