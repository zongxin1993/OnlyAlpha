//! 非供应商专用样本：2 份 × 30 × 合约乘数 2；初始资金 20、初始保证金 12。
use onlyalpha_broker::ConnectionPort;
use onlyalpha_broker_virtual::BoundVirtualActor;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use onlyalpha_execution::{CommitIntent, Components, Error, Record, Store, coordinate};
use onlyalpha_runtime::{BoundBrokerJournal, Runtime, SqliteStore};
use serde_json::{Value, json};
use std::fs;

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
#[test]
fn independent_multiplier_margin_fee_mark_and_funding_accounting() {
    let (cfg, inputs) = scenario();
    let (_root, mut rt) = prepare_prefix(&cfg, &inputs, 2);
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
    let (_root, mut rt) = prepare_prefix(&cfg, &inputs, 6);
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
    rt.recover().unwrap();
    assert_eq!(rt.state().unwrap(), state);
}

struct RejectFundingCommit<'a>(&'a SqliteStore);
impl Store for RejectFundingCommit<'_> {
    fn head(&self) -> Result<u64, Error> {
        self.0.head()
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        self.0.get(n)
    }
    fn commit(&mut self, _: &CommitIntent) -> Result<Record, Error> {
        Err(Error("TEST_COMMIT_UNKNOWN".into()))
    }
    fn mark_ready(&mut self, _: u64) -> Result<(), Error> {
        Err(Error("OBSERVATION_READ_ONLY".into()))
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        Err(Error("OBSERVATION_READ_ONLY".into()))
    }
}
#[test]
fn new_version_rejects_uninstalled_shapes_and_original_cash_reader_stays_distinct() {
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
    let (_root, mut rt) = prepare_prefix(&cfg, &inputs, 1);
    let before = rt.state().unwrap();
    let mut aliased = inputs[0].clone();
    aliased["input_id"] = json!("new-mark-envelope");
    aliased["source_ref"] = json!("other");
    aliased["runtime_sequence"] = json!(2);
    aliased["payload"]["fact"]["value"]["value"] = json!("30.01");
    assert!(rt.apply(&aliased).is_err());
    rt.recover().unwrap();
    assert_eq!(rt.state().unwrap(), before);
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
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 7);
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
    runtime.save_checkpoint().unwrap();
    drop(runtime);
    let restored = Runtime::open(&root.0, cfg, &artifact()).unwrap();
    assert_eq!(restored.state().unwrap(), state);
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
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 5);
    let entry = runtime.state().unwrap();
    let last = entry["account"]["snapshot"]["last_confirmed_maintenance"].clone();
    amount(&entry["account"]["snapshot"]["occupied_margin"], "12");
    amount(&last["amount"], ".48");
    assert_eq!(last["time"], inputs[4]["time"]);
    runtime.save_checkpoint().unwrap();

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
    let originals = runtime.records().unwrap();
    assert_eq!(originals.len(), 7);
    assert!(originals.iter().all(Record::ready));

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
    drop(runtime);
    let mut restored = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
    assert_eq!(restored.state().unwrap(), funded);
    assert_eq!(restored.records().unwrap(), originals);
    restored.apply(&inputs[6]).unwrap();
    assert_eq!(restored.state().unwrap(), funded);
    assert_eq!(restored.records().unwrap(), originals);
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
    let history = restored.records().unwrap();
    drop(restored);
    let fresh = Runtime::open(&root.0, cfg, &artifact()).unwrap();
    assert_eq!(fresh.state().unwrap(), resumed);
    assert_eq!(fresh.records().unwrap(), history);
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
    let (_wide_dir, mut wide) = prepare_prefix(&cfg, &inputs, 2);
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
    let (stepped_dir, mut existing) = prepare_prefix(&stepped, &stepped_inputs, 2);
    let original = existing.state().unwrap();
    assert_eq!(
        existing
            .apply(&next(3, &stepped["perpetual"]["policy_fingerprint"]))
            .unwrap_err()
            .0,
        "EXECUTION_EXISTING_MARGIN_COVERAGE"
    );
    drop(existing);
    assert_eq!(
        Runtime::open(&stepped_dir.0, stepped, &artifact())
            .unwrap()
            .state()
            .unwrap(),
        original
    );

    cfg["perpetual"]["margin_segments"][0]["upper_bound"] = json!("121");
    let mut narrow_inputs = inputs.clone();
    compile_synthetic_rules(&mut cfg, &mut narrow_inputs);
    let (root, mut run) = prepare_prefix(&cfg, &narrow_inputs, 2);
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
        let records = run.records().unwrap();
        amount(&prefix["account"]["snapshot"]["cash"], "1000");
        amount(&prefix["account"]["snapshot"]["reserved_margin"], "12");
        assert_eq!(
            run.apply(&next(sequence, &cfg["perpetual"]["policy_fingerprint"]))
                .unwrap_err()
                .0,
            "EXECUTION_MARGIN_NOTIONAL_DOMAIN"
        );
        drop(run);
        run = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
        assert_eq!(run.state().unwrap(), prefix);
        assert_eq!(run.records().unwrap(), records);
    }
}

fn unobserved_acceptance(
    cfg: &Value,
    inputs: &[Value],
) -> (
    Root,
    Runtime,
    BoundVirtualActor,
    onlyalpha_broker::Broker,
    BoundBrokerJournal,
) {
    use onlyalpha_broker::{Broker, BrokerCommand, Connection};
    let (root, mut run) = prepare_prefix(cfg, inputs, 1);
    let (scope, cash, settings) = venue_config(inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut actor = BoundVirtualActor::open(
        &root.0,
        scope.clone(),
        &"f".repeat(64),
        cash,
        &settings,
        binding,
    )
    .unwrap();
    actor.connect().unwrap();
    actor.authenticate().unwrap();
    let mut journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let mut broker = Broker::recover(scope.clone(), &journal, 32).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);

    let admission = &inputs[1];
    run.apply(admission).unwrap();
    let owners = run.fork_ready().unwrap().0.checkpoint().unwrap();
    let order = &owners["components"][0]["state"]["orders"][0]["snapshot"];
    let command = BrokerCommand::decode(&json!({
        "schema_version":1, "scope":scope.record(), "operation":"SUBMIT",
        "command_id":"original-submit", "order":admission["payload"]["order"],
        "client":order["client_order_id"]["value"], "request":admission["payload"]["request"]
    }))
    .unwrap();
    let at = admission["time"].as_i64().unwrap();
    actor.advance(at).unwrap();
    journal
        .dispatch(&mut broker, &run, &mut actor, &command)
        .unwrap();
    actor.advance(at).unwrap();
    run.apply(&inputs[2]).unwrap();
    assert!(broker.pending().is_empty());
    (root, run, actor, broker, journal)
}

#[test]
fn standalone_self_reported_broker_fact_cannot_author_a_ready_acceptance() {
    let (cfg, inputs) = scenario();
    let (root, mut run, mut actor, mut broker, mut journal) = unobserved_acceptance(&cfg, &inputs);
    let prefix = run.records().unwrap();
    let state = run.state().unwrap();
    let acceptance = &inputs[3];
    assert!(broker.pending().is_empty());
    assert_eq!(
        run.apply(acceptance).unwrap_err().0,
        "BROKER_ORIGINAL_OBSERVATION_MISSING"
    );
    drop(run);
    let mut run = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
    assert_eq!(run.records().unwrap(), prefix);
    assert_eq!(run.state().unwrap(), state);

    assert_eq!(actor.publish(&mut broker, &mut journal).unwrap(), 1);
    assert_eq!(
        broker.pending()[0].record(),
        acceptance["payload"]["broker"]["record"]
    );
    run.apply(acceptance).unwrap();
    let accepted = run.records().unwrap();
    assert_eq!(accepted.len(), prefix.len() + 1);
    assert_eq!(accepted.last().unwrap().prepared().input(), acceptance);
    drop(run);
    assert_eq!(
        Runtime::open(&root.0, cfg, &artifact())
            .unwrap()
            .records()
            .unwrap(),
        accepted
    );
}

#[test]
fn altered_funding_rate_cannot_borrow_a_bound_source_record_hash() {
    let (cfg, inputs) = scenario();
    let (root, mut run) = prepare_prefix(&cfg, &inputs, 6);
    let before = run.state().unwrap();
    let mut changed = inputs[6].clone();
    changed["payload"]["fact"]["rate"] = json!("0.5");
    assert!(run.apply(&changed).is_err());
    drop(run);
    let run = Runtime::open(&root.0, cfg, &artifact()).unwrap();
    assert_eq!(run.state().unwrap(), before);
    assert_eq!(run.records().unwrap().len(), 6);
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
        let (root, mut run) = prepare_prefix(&cfg, &inputs, cut);
        let before = run.records().unwrap();
        let next = if cut == 1 { &inputs[1] } else { &second };
        let result = run.apply(next);
        if cap == "1000" {
            result.unwrap();
        } else {
            assert_eq!(result.unwrap_err().0, "EXECUTION_MARGIN_NOTIONAL_DOMAIN");
            drop(run);
            assert_eq!(
                Runtime::open(&root.0, cfg.clone(), &artifact())
                    .unwrap()
                    .records()
                    .unwrap(),
                before
            );
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

fn refresh_fill_observation(input: &mut Value) {
    let fact = onlyalpha_broker::Fact::decode(&input["payload"]["broker"]["record"]).unwrap();
    input["payload"]["broker"] =
        json!({"id":fact.identity(),"fingerprint":fact.fingerprint(),"record":fact.record()});
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
    // 实际场所原件保留原经济日与原生成时刻，Runtime 在第二日才可见。
    refresh_fill_observation(fill);
    let (_root, mut run) = prepare_prefix(&cfg, &inputs, 2);
    amount(
        &run.state().unwrap()["account"]["snapshot"]["reserved"],
        "1",
    );
    for item in &inputs[2..5] {
        run.apply(item).unwrap();
    }
    amount(&run.state().unwrap()["account"]["snapshot"]["fees"], "0");
    let (_root, mut denied) = prepare_prefix(&gap, &inputs, 1);
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
    let (_root, mut later) = prepare_prefix(&cfg, &inputs, 4);
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
        let (root, mut run) = prepare_prefix(&cfg, &inputs, 5);
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
        run.save_checkpoint().unwrap();
        drop(run);
        assert_eq!(
            Runtime::open(&root.0, cfg, &artifact())
                .unwrap()
                .state()
                .unwrap(),
            current
        );
    }
}

#[test]
fn original_funding_projections_reject_rehashed_amounts_and_missing_source_on_reopen() {
    let (cfg, inputs) = scenario();
    let (root, mut run) = prepare_prefix(&cfg, &inputs, 7);
    run.save_checkpoint().unwrap();
    let original = run.fork_ready().unwrap().0.checkpoint().unwrap();
    let mut valid = Components::new(cfg.clone()).unwrap();
    valid
        .restore(
            &original,
            &onlyalpha_execution::digest(&serde_json::to_vec(&original).unwrap()),
        )
        .unwrap();
    assert_eq!(valid.checkpoint().unwrap(), original);
    for (index, op) in [(2, "ECONOMIC"), (3, "FUNDING")] {
        let mut bad = original.clone();
        let history = bad["components"][index]["journal"].as_array_mut().unwrap();
        let command = history.iter_mut().find(|c| c["op"] == op).unwrap();
        command["payload"]["amount"] = json!("91.00000000");
        let mut restored = Components::new(cfg.clone()).unwrap();
        assert!(
            restored
                .restore(
                    &bad,
                    &onlyalpha_execution::digest(&serde_json::to_vec(&bad).unwrap())
                )
                .is_err()
        );
    }
    let before = run.state().unwrap();
    drop(run);
    let path = root.0.join("market-source-cut.json");
    let original = fs::read(&path).unwrap();
    fs::rename(&path, root.0.join("original-cut")).unwrap();
    assert!(Runtime::open(&root.0, cfg.clone(), &artifact()).is_err());
    let mut altered: Value = serde_json::from_slice(&original).unwrap();
    altered.as_array_mut().unwrap().last_mut().unwrap()["facts"][1]["rate"] = json!("0.5");
    fs::write(&path, serde_json::to_vec(&altered).unwrap()).unwrap();
    assert!(Runtime::open(&root.0, cfg.clone(), &artifact()).is_err());
    fs::write(&path, original).unwrap();
    assert_eq!(
        Runtime::open(&root.0, cfg, &artifact())
            .unwrap()
            .state()
            .unwrap(),
        before
    );
}

#[test]
fn funding_requires_economic_watermark_and_all_original_boundary_trades_ready() {
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_venue_prefix(&cfg, &inputs, 4, false);
    let mut mark = inputs[5].clone();
    mark["runtime_sequence"] = json!(5);
    runtime.apply(&mark).unwrap();
    runtime.save_checkpoint().unwrap();
    let before = runtime.state().unwrap();
    let records = runtime.records().unwrap();
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(6);
    assert!(
        runtime
            .apply(&funding)
            .unwrap_err()
            .0
            .contains("BROKER_ECONOMIC_PREFIX_UNPROVEN")
    );
    drop(runtime);
    let mut runtime = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
    assert_eq!(runtime.state().unwrap(), before);
    assert_eq!(runtime.records().unwrap(), records);
    let (scope, cash, settings) = venue_config(&inputs);
    let mut venue = BoundVirtualActor::open(
        &root.0,
        scope,
        &"f".repeat(64),
        cash,
        &settings,
        cfg["perpetual"]["execution_source_binding"]
            .as_str()
            .unwrap(),
    )
    .unwrap();
    venue.advance(funding["time"].as_i64().unwrap()).unwrap();
    assert_eq!(
        runtime.apply(&funding).unwrap_err().0,
        "EXECUTION_FUNDING_UNAPPLIED_TRADE"
    );
    drop(runtime);
    let mut runtime = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
    assert_eq!(runtime.state().unwrap(), before);
    let mut fill = inputs[4].clone();
    fill["runtime_sequence"] = json!(6);
    fill["time"] = funding["time"].clone();
    runtime.apply(&fill).unwrap();
    runtime.apply(&inputs[6]).unwrap();
    amount(
        &runtime.state().unwrap()["account"]["snapshot"]["cash"],
        "19.816",
    );
    let final_state = runtime.state().unwrap();
    drop(runtime);
    assert_eq!(
        Runtime::open(&root.0, cfg, &artifact())
            .unwrap()
            .state()
            .unwrap(),
        final_state
    );
}

#[test]
fn utc_compilation_epoch_controls_processing_days_and_future_admission() {
    let (cfg, inputs) = scenario();
    for (key, value) in [
        ("trading_day", json!("2026-09-02")),
        ("day_index", json!(2)),
    ] {
        let (root, mut run) = prepare_prefix(&cfg, &inputs, 1);
        let before = run.state().unwrap();
        let mut wrong = inputs[1].clone();
        wrong[key] = value;
        assert_eq!(
            run.apply(&wrong).unwrap_err().0,
            "EXECUTION_PERPETUAL_TRADING_DAY"
        );
        drop(run);
        assert_eq!(
            Runtime::open(&root.0, cfg.clone(), &artifact())
                .unwrap()
                .state()
                .unwrap(),
            before
        );
    }
    // 同日真实新编译身份仍不能向编译时点之前的请求签发准入。
    let mut future = cfg.clone();
    let mut rows = inputs.clone();
    future["perpetual"]["limit_rules"]["effective_from"] = json!("2026-09-01T08:00:00Z");
    compile_synthetic_rules(&mut future, &mut rows);
    let (_root, mut run) = prepare_prefix(&future, &rows, 1);
    assert_eq!(
        run.apply(&rows[1]).unwrap_err().0,
        "EXECUTION_MARKET_LIMIT_RULES"
    );
    // 完整当前编译包能准入原请求。
    let (_root, run) = prepare_prefix(&cfg, &inputs, 2);
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
    use onlyalpha_broker::{Broker, BrokerCommand, Connection, Scope};
    use onlyalpha_domain::{
        base::OnlyDomainModel, execution::OnlyOrderRequest, market::OnlyReferencePriceFact,
    };
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
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 5);
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
    runtime.save_checkpoint().unwrap();
    drop(runtime);
    let mut runtime = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
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
    let (_, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut venue = BoundVirtualActor::open(
        &root.0,
        scope.clone(),
        &"f".repeat(64),
        cash,
        &settings,
        binding,
    )
    .unwrap();
    venue.connect().unwrap();
    venue.authenticate().unwrap();
    let mut journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let mut broker = Broker::recover(scope.clone(), &journal, 512).unwrap();
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
        let owners = runtime.fork_ready().unwrap().0.checkpoint().unwrap();
        let row = owners["components"][0]["state"]["orders"]
            .as_array()
            .unwrap()
            .iter()
            .find(|row| row["snapshot"]["order_id"]["value"] == order)
            .unwrap();
        let command = BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"rounded-submit-2","order":order,"client":row["snapshot"]["client_order_id"]["value"],"request":admit["payload"]["request"]})).unwrap();
        broker.set_connection(Connection::Ready);
        broker.set_health(true, true, true);
        journal
            .dispatch(&mut broker, &runtime, &mut venue, &command)
            .unwrap();
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
        venue.advance(venue.now()).unwrap();
        venue.publish(&mut broker, &mut journal).unwrap();
        let original = broker
            .pending()
            .iter()
            .find(|f| f.order() == Some(order) && f.record()["kind"] == "ACCEPTED")
            .unwrap();
        accepted["payload"]["broker"] = json!({"record":original.record(),"id":original.identity(),"fingerprint":original.fingerprint()});
        runtime.apply(&accepted).unwrap();
        second["payload"]["order"] = json!(order);
    }
    venue
        .on_bar(
            2,
            &venue_bar(
                &inputs[1]["payload"]["request"],
                2,
                second["time"].as_i64().unwrap(),
            ),
        )
        .unwrap();
    venue.publish(&mut broker, &mut journal).unwrap();
    let original = broker
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
    let owners = runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let orders = owners["components"][0]["state"]["orders"]
        .as_array()
        .unwrap();
    assert_eq!(orders.len(), if split_orders { 2 } else { 1 });
    assert!(
        orders
            .iter()
            .all(|row| row["snapshot"]["status"] == "FILLED")
    );
    let trades = final_state["execution"]["perpetual"]["broker_facts"]
        .as_object()
        .unwrap()
        .values()
        .filter(|v| v["broker"]["record"]["kind"] == "TRADE")
        .count();
    assert_eq!(trades, 2);
    runtime.save_checkpoint().unwrap();
    let history = runtime.records().unwrap();
    drop(runtime);
    let restored = Runtime::open(&root.0, cfg, &artifact()).unwrap();
    assert_eq!(restored.state().unwrap(), final_state);
    assert_eq!(restored.records().unwrap(), history);
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

#[test]
fn runtime_broker_order_view_binds_original_scope_request_and_cancel_shape() {
    use onlyalpha_broker::{BrokerCommand, RuntimeReader};
    let (cfg, inputs) = scenario();
    let (_root, runtime) = prepare_prefix(&cfg, &inputs, 4);
    let before = runtime.state().unwrap();
    let cp = runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let row = &cp["components"][0]["state"]["orders"][0]["snapshot"];
    let raw = json!({"schema_version":1,"scope":inputs[3]["payload"]["broker"]["record"]["scope"],"operation":"SUBMIT","command_id":"original-submit","order":row["order_id"]["value"],"client":row["client_order_id"]["value"],"request":inputs[1]["payload"]["request"]});
    let original = BrokerCommand::decode(&raw).unwrap();
    let exact = runtime.order_view(&original).unwrap().unwrap().record();
    assert_eq!(exact["status"], "ACCEPTED");
    assert_eq!(exact["request"], raw["request"]);
    let mut wrong = Vec::new();
    for (key, value) in [
        ("runtime", json!("foreign-runtime")),
        ("generation", json!("f".repeat(64))),
        ("runtime_kind", json!("LIVE")),
    ] {
        let mut command = raw.clone();
        command["scope"][key] = value;
        let command = BrokerCommand::decode(&command).unwrap();
        if runtime.order_view(&command).is_ok() {
            wrong.push(format!("foreign {key}"));
        }
    }
    let mut changed = raw.clone();
    changed["request"]["price"]["value"] = json!("31.00");
    if runtime
        .order_view(&BrokerCommand::decode(&changed).unwrap())
        .is_ok()
    {
        wrong.push("foreign submit request".into());
    }
    let mut cancel = raw.clone();
    cancel["operation"] = json!("CANCEL");
    cancel["command_id"] = json!("query-cancel");
    cancel["request"] = json!({"schema_version":1,"request_id":{"schema_version":1,"value":"cancel-query"},"order_id":row["order_id"],"reason":"cancel accepted order","metadata":{}});
    let cancel_command = BrokerCommand::decode(&cancel).unwrap();
    match runtime.order_view(&cancel_command) {
        Ok(Some(view))
            if view.record()["request"] == exact["request"]
                && view.record()["scope"] == exact["scope"] => {}
        _ => wrong.push("exact canonical cancel did not read original order".into()),
    }
    cancel["client"] = json!("foreign-client");
    if runtime
        .order_view(&BrokerCommand::decode(&cancel).unwrap())
        .is_ok()
    {
        wrong.push("foreign cancel client".into());
    }
    assert_eq!(runtime.state().unwrap(), before);
    assert!(
        wrong.is_empty(),
        "Runtime order query mismatches: {wrong:?}"
    );
}

#[test]
fn empty_order_generation_requires_a_visible_original_closure_and_rejects_rewritten_media() {
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 0);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut actor = BoundVirtualActor::open(
        &root.0,
        scope.clone(),
        &"f".repeat(64),
        cash.clone(),
        &settings,
        binding,
    )
    .unwrap();
    assert!(
        BoundVirtualActor::create(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding
        )
        .is_err()
    );
    let mut mark = inputs[5].clone();
    mark["runtime_sequence"] = json!(1);
    runtime.apply(&mark).unwrap();
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(2);
    let boundary = mark["time"].as_i64().unwrap();
    actor.advance(boundary).unwrap();
    assert_eq!(
        runtime.apply(&funding).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    runtime.recover().unwrap();
    let mut late_bar = venue_bar(&inputs[1]["payload"]["request"], 1, boundary + 1000).to_record();
    late_bar["ts_init"] = json!(
        OnlyTimestamp::from_unix_nanos((boundary + 5000).into())
            .to_datetime()
            .unwrap()
            .to_string()
    );
    actor
        .on_bar(1, &OnlyBar::from_record(&late_bar).unwrap())
        .unwrap();
    actor.advance(boundary + 2000).unwrap();
    let mut unseen = funding.clone();
    unseen["time"] = json!(boundary + 2000);
    assert_eq!(
        runtime.apply(&unseen).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    runtime.recover().unwrap();
    funding["time"] = json!(boundary + 5000);
    let mut premature = funding.clone();
    premature["time"] = json!(boundary);
    assert_eq!(
        runtime.apply(&premature).unwrap_err().0,
        "BROKER_ECONOMIC_PREFIX_UNPROVEN"
    );
    runtime.recover().unwrap();
    runtime.apply(&funding).unwrap();
    let final_state = runtime.state().unwrap();
    amount(
        &final_state["ledger"]["ledgers"]["cluster"]["snapshot"]["funding"],
        "0",
    );
    runtime.save_checkpoint().unwrap();
    drop(runtime);
    let mut reopened = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
    reopened.apply(&funding).unwrap();
    assert_eq!(reopened.state().unwrap(), final_state);
    drop(reopened);
    let db = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();
    db.execute(
        "UPDATE source_steps SET input=?1 WHERE sequence=2",
        [json!(["CLOCK", boundary + 2]).to_string()],
    )
    .unwrap();
    assert!(
        BoundVirtualActor::open(&root.0, scope, &"f".repeat(64), cash, &settings, binding).is_err()
    );
    assert!(Runtime::open(&root.0, cfg, &artifact()).is_err());
}

#[test]
fn source_step_preserves_an_admitted_multi_fact_bar_before_and_after_commit_loss() {
    use onlyalpha_broker::{Broker, BrokerCommand, Connection, Journal};
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 1);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let open = || {
        BoundVirtualActor::open(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding,
        )
        .unwrap()
    };
    let mut actor = open();
    actor.connect().unwrap();
    actor.authenticate().unwrap();
    let mut journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let mut broker = Broker::recover(scope.clone(), &journal, 32).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    runtime.apply(&inputs[1]).unwrap();
    let owner = runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let req = &inputs[1]["payload"]["request"];
    let cmd=BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"original-submit","order":inputs[1]["payload"]["order"],"client":owner["components"][0]["state"]["orders"][0]["snapshot"]["client_order_id"]["value"],"request":req})).unwrap();
    let at = inputs[1]["time"].as_i64().unwrap();
    actor.advance(at).unwrap();
    journal
        .dispatch(&mut broker, &runtime, &mut actor, &cmd)
        .unwrap();
    let protocol = journal.records().unwrap();
    let before = actor.checkpoint();
    let db = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();
    db.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(actor.advance(at).is_err());
    assert_eq!(actor.checkpoint(), before);
    db.execute_batch("ROLLBACK").unwrap();
    actor = open();
    assert_eq!(actor.checkpoint(), before);
    db.execute_batch("CREATE TRIGGER interrupt_bar BEFORE INSERT ON source_facts WHEN NEW.ordinal=1 BEGIN SELECT RAISE(ABORT,'second child unavailable'); END;").unwrap();
    let bar = venue_bar(req, 1, at);
    assert!(actor.on_bar(1, &bar).is_err());
    assert_eq!(actor.checkpoint(), before);
    assert_eq!(open().checkpoint(), before);
    assert_eq!(
        db.query_row("SELECT COUNT(*) FROM source_facts", [], |r| r
            .get::<_, i64>(0))
            .unwrap(),
        0
    );
    db.execute_batch("DROP TRIGGER interrupt_bar;").unwrap();
    actor = open();
    actor.on_bar(1, &bar).unwrap();
    let committed = actor.checkpoint();
    let bytes = serde_json::to_vec(&committed).unwrap().len();
    assert!(bytes < 4096);
    drop(actor);
    let mut actor = open();
    assert_eq!(actor.checkpoint(), committed);
    actor.on_bar(1, &bar).unwrap();
    assert_eq!(actor.checkpoint(), committed);
    assert_eq!(
        db.query_row(
            "SELECT fact_count FROM source_steps ORDER BY sequence DESC LIMIT 1",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap(),
        2
    );
    assert_eq!(journal.records().unwrap(), protocol);
    actor.publish(&mut broker, &mut journal).unwrap();
    assert_eq!(
        broker
            .pending()
            .iter()
            .map(onlyalpha_broker::Fact::record)
            .collect::<Vec<_>>(),
        vec![
            inputs[3]["payload"]["broker"]["record"].clone(),
            inputs[4]["payload"]["broker"]["record"].clone()
        ]
    );
    for input in &inputs[2..5] {
        runtime.apply(input).unwrap();
    }
    let expected = runtime.state().unwrap();
    drop(runtime);
    assert_eq!(
        Runtime::open(&root.0, cfg, &artifact())
            .unwrap()
            .state()
            .unwrap(),
        expected
    );
}

#[test]
fn admitted_fill_survives_a_source_history_larger_than_the_original_protocol_budget() {
    use onlyalpha_broker::{Broker, BrokerCommand, Connection, Journal};
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 1);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut actor = BoundVirtualActor::open(
        &root.0,
        scope.clone(),
        &"f".repeat(64),
        cash,
        &settings,
        binding,
    )
    .unwrap();
    actor.connect().unwrap();
    actor.authenticate().unwrap();
    let mut journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let mut broker = Broker::recover(scope.clone(), &journal, 32).unwrap();
    broker.set_connection(Connection::Ready);
    broker.set_health(true, true, true);
    runtime.apply(&inputs[1]).unwrap();
    let owner = runtime.fork_ready().unwrap().0.checkpoint().unwrap();
    let req = &inputs[1]["payload"]["request"];
    let command=BrokerCommand::decode(&json!({"schema_version":1,"scope":scope.record(),"operation":"SUBMIT","command_id":"original-submit","order":inputs[1]["payload"]["order"],"client":owner["components"][0]["state"]["orders"][0]["snapshot"]["client_order_id"]["value"],"request":req})).unwrap();
    let at = inputs[1]["time"].as_i64().unwrap();
    actor.advance(at).unwrap();
    journal
        .dispatch(&mut broker, &runtime, &mut actor, &command)
        .unwrap();
    let initial_protocol = journal.records().unwrap();
    let mut market = venue_bar(req, 1, at).to_record();
    market["bar_type"]["instrument_id"]["symbol"]["value"] = json!("OTHER");
    let row_bytes = u64::try_from(market.to_string().len()).unwrap();
    let budget = 32 * 1024 * 1024u64;
    let rows = budget / row_bytes + 2;
    for sequence in 1..=rows {
        // 同一经济钟可观察多条真实闭合 Bar，各自 bar_end 按微秒严格递增。
        let end = at - 1_000_000_000 + i64::try_from(sequence).unwrap() * 1_000;
        market["bar_end"] = json!(
            OnlyTimestamp::from_unix_nanos(end.into())
                .to_datetime()
                .unwrap()
                .to_string()
        );
        actor
            .on_bar(sequence, &OnlyBar::from_record(&market).unwrap())
            .unwrap();
    }
    let db = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();
    assert!(
        db.query_row(
            "SELECT SUM(length(CAST(input AS BLOB))) FROM source_steps",
            [],
            |r| r.get::<_, i64>(0)
        )
        .unwrap()
            > i64::try_from(budget).unwrap()
    );
    assert_eq!(journal.records().unwrap(), initial_protocol);
    actor.on_bar(rows + 1, &venue_bar(req, 1, at)).unwrap();
    actor.publish(&mut broker, &mut journal).unwrap();
    for input in &inputs[2..5] {
        runtime.apply(input).unwrap();
    }
    let final_state = runtime.state().unwrap();
    drop(runtime);
    assert_eq!(
        Runtime::open(&root.0, cfg, &artifact())
            .unwrap()
            .state()
            .unwrap(),
        final_state
    );
}

#[test]
fn source_readers_require_canonical_bytes_for_genesis_and_original_observations() {
    use onlyalpha_broker::Journal;
    let (cfg, inputs) = scenario();
    let (root, runtime) = prepare_prefix(&cfg, &inputs, 4);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let open_venue = || {
        BoundVirtualActor::open(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding,
        )
    };
    let journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let protocol = journal.records().unwrap();
    let checkpoint = open_venue().unwrap().checkpoint();
    drop(runtime);
    let db = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();

    assert_eq!(
        db.execute(
            "UPDATE source_genesis SET binding=' ' || binding WHERE singleton=1",
            []
        )
        .unwrap(),
        1
    );
    assert_eq!(
        open_venue().err().unwrap().to_string(),
        "VIRTUAL_SOURCE_BINDING"
    );
    db.execute(
        "UPDATE source_genesis SET binding=substr(binding,2) WHERE singleton=1",
        [],
    )
    .unwrap();
    let id = inputs[3]["payload"]["broker"]["id"].as_str().unwrap();
    assert_eq!(
        db.execute(
            "UPDATE source_facts SET fact=' ' || fact WHERE identity=?1",
            [id]
        )
        .unwrap(),
        1
    );
    assert_eq!(
        open_venue().err().unwrap().to_string(),
        "VIRTUAL_SOURCE_OUTPUT_CONFLICT"
    );
    assert_eq!(
        journal.records().unwrap_err().to_string(),
        "BROKER_SOURCE_ORIGINAL_FACT_REQUIRED"
    );
    db.execute(
        "UPDATE source_facts SET fact=substr(fact,2) WHERE identity=?1",
        [id],
    )
    .unwrap();
    assert_eq!(open_venue().unwrap().checkpoint(), checkpoint);
    assert_eq!(journal.records().unwrap(), protocol);
}

#[test]
fn funding_plan_from_original_run_must_remain_bound_to_its_writer() {
    let (cfg, inputs) = scenario();
    let (root, runtime) = prepare_prefix(&cfg, &inputs, 6);
    let (mut owners, prefix) = runtime.fork_ready().unwrap();
    let plan = runtime.prepare_original_funding(&inputs[6]).unwrap();
    let original =
        onlyalpha_execution::Prepared::decode(&serde_json::to_vec(plan.value()).unwrap()).unwrap();
    assert!(runtime.prepare(&inputs[6]).is_err());
    let (_other_root, mut other) = prepare_prefix(&cfg, &inputs, 6);
    assert_eq!(
        other.apply_original_funding(&plan).unwrap_err().0,
        "RUNTIME_STORE_FUNDING_WRITER_CONFLICT"
    );
    other.recover().unwrap();
    assert_eq!(other.records().unwrap(), prefix);
    drop(runtime);
    let store = SqliteStore::open(&root.0, cfg.clone(), &artifact()).unwrap();

    // 写入探针只能返回固定错误；若收到 CommitIntent，说明通用入口已签发写资格。
    let generic_error =
        coordinate(&mut RejectFundingCommit(&store), &mut owners, &original).unwrap_err();
    assert_eq!(store.head().unwrap(), 6);
    assert!(store.get(7).unwrap().is_none());
    drop(store);
    let mut actual = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
    assert_eq!(
        actual.apply_original_funding(&plan).unwrap_err().0,
        "RUNTIME_STORE_FUNDING_WRITER_CONFLICT"
    );
    actual.recover().unwrap();
    assert_eq!(actual.records().unwrap(), prefix);
    actual.apply(&inputs[6]).unwrap();
    let funded = actual.records().unwrap();
    assert_eq!(funded.len(), 7);
    drop(actual);
    assert_eq!(
        Runtime::open(&root.0, cfg, &artifact())
            .unwrap()
            .records()
            .unwrap(),
        funded
    );
    assert_ne!(
        generic_error.0, "TEST_COMMIT_UNKNOWN",
        "通用 Store 收到了 Funding CommitIntent"
    );
}

// 在不改变解析值的情况下反转首个多字段对象。CLOCK 的数组只有标量。
fn changed_field_order(raw: &str) -> Option<String> {
    fn reordered(v: &Value) -> Option<(String, String)> {
        match v {
            Value::Object(object) if object.len() > 1 => {
                let fields = object
                    .iter()
                    .rev()
                    .map(|(k, v)| format!("{}:{}", json!(k), v))
                    .collect::<Vec<_>>()
                    .join(",");
                Some((v.to_string(), format!("{{{fields}}}")))
            }
            Value::Array(items) => items.iter().find_map(reordered),
            _ => None,
        }
    }
    let v: Value = serde_json::from_str(raw).unwrap();
    let (before, after) = reordered(&v)?;
    let changed = raw.replacen(&before, &after, 1);
    assert_ne!(changed, raw);
    assert_eq!(serde_json::from_str::<Value>(&changed).unwrap(), v);
    Some(changed)
}

#[test]
fn both_source_readers_require_canonical_genesis_clock_and_bar_for_funded_recovery() {
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 0);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let open_actor = || {
        BoundVirtualActor::open(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding,
        )
    };
    let open_runtime = || Runtime::open(&root.0, cfg.clone(), &artifact());
    let mut mark = inputs[5].clone();
    mark["runtime_sequence"] = json!(1);
    let boundary = mark["time"].as_i64().unwrap();
    let bar = venue_bar(&inputs[1]["payload"]["request"], 1, boundary);
    let mut actor = open_actor().unwrap();
    actor.on_bar(1, &bar).unwrap();
    actor.advance(boundary + 1).unwrap();
    let checkpoint = actor.checkpoint();
    actor.on_bar(1, &bar).unwrap();
    assert_eq!(actor.checkpoint(), checkpoint);
    drop(actor);
    runtime.apply(&mark).unwrap();
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(2);
    runtime.apply(&funding).unwrap();
    let ready = runtime.records().unwrap();
    drop(runtime);

    let db = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();
    let mut verdicts = Vec::new();
    for (kind, read, update) in [
        (
            "genesis",
            "SELECT binding FROM source_genesis WHERE singleton=1",
            "UPDATE source_genesis SET binding=?1 WHERE singleton=1",
        ),
        (
            "clock",
            "SELECT input FROM source_steps WHERE json_extract(input,'$[0]')='CLOCK'",
            "UPDATE source_steps SET input=?1 WHERE json_extract(input,'$[0]')='CLOCK'",
        ),
        (
            "bar",
            "SELECT input FROM source_steps WHERE json_extract(input,'$[0]')='BAR'",
            "UPDATE source_steps SET input=?1 WHERE json_extract(input,'$[0]')='BAR'",
        ),
    ] {
        let original: String = db.query_row(read, [], |row| row.get(0)).unwrap();
        let reordered = changed_field_order(&original);
        assert_eq!(reordered.is_some(), kind != "clock");
        let mut outcome = (true, true);
        for altered in std::iter::once(format!(" {original}")).chain(reordered) {
            assert_eq!(db.execute(update, [&altered]).unwrap(), 1);
            outcome.0 &= open_actor().is_err();
            outcome.1 &= open_runtime().is_err();
            assert_eq!(db.execute(update, [&original]).unwrap(), 1);
            let mut restored = open_actor().unwrap();
            assert_eq!(restored.checkpoint(), checkpoint);
            restored.on_bar(1, &bar).unwrap();
            assert_eq!(restored.checkpoint(), checkpoint);
            assert_eq!(open_runtime().unwrap().records().unwrap(), ready);
        }
        verdicts.push((kind, outcome.0, outcome.1));
    }
    assert_eq!(
        verdicts,
        [
            ("genesis", true, true),
            ("clock", true, true),
            ("bar", true, true)
        ]
    );
}

#[test]
fn both_source_readers_require_canonical_unpublished_acceptance_for_funding() {
    let (cfg, inputs) = scenario();
    let (root, mut runtime, mut actor, broker, _journal) = unobserved_acceptance(&cfg, &inputs);
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let mut mark = inputs[5].clone();
    mark["runtime_sequence"] = json!(4);
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(5);
    let boundary = mark["time"].as_i64().unwrap();
    actor.advance(boundary + 1).unwrap();
    runtime.apply(&mark).unwrap();
    let original_plan = runtime.prepare_original_funding(&funding).unwrap();
    let original_checkpoint = actor.checkpoint();
    drop(actor);
    assert!(broker.pending().is_empty());
    let open_actor = || {
        BoundVirtualActor::open(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding,
        )
    };

    let db = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();
    let id = inputs[3]["payload"]["broker"]["id"].as_str().unwrap();
    let ingress_count: i64 = db
        .query_row(
            "SELECT count(*) FROM protocol_ingress WHERE identity=?1",
            [id],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(ingress_count, 0);
    let original: String = db
        .query_row(
            "SELECT fact FROM source_facts WHERE identity=?1",
            [id],
            |r| r.get(0),
        )
        .unwrap();
    let update = "UPDATE source_facts SET fact=?1 WHERE identity=?2";
    for changed in [
        format!(" {original}"),
        changed_field_order(&original).unwrap(),
    ] {
        assert_eq!(
            db.execute(update, rusqlite::params![changed, id]).unwrap(),
            1
        );
        let actor_rejected = open_actor().is_err();
        let runtime_rejected = runtime.prepare_original_funding(&funding).is_err();
        assert_eq!(
            db.execute(update, rusqlite::params![original, id]).unwrap(),
            1
        );
        assert_eq!(open_actor().unwrap().checkpoint(), original_checkpoint);
        assert_eq!(
            runtime.prepare_original_funding(&funding).unwrap().value(),
            original_plan.value()
        );
        assert_eq!((actor_rejected, runtime_rejected), (true, true));
    }
}

/// 只读副本。每个行体均从原 Run 的正式 Ready 行重新解码，不能写入或发布。
struct FundingObservation(Vec<Record>);

impl Store for FundingObservation {
    fn head(&self) -> Result<u64, Error> {
        u64::try_from(self.0.len()).map_err(|e| Error(e.to_string()))
    }
    fn get(&self, n: u64) -> Result<Option<Record>, Error> {
        let index = n
            .checked_sub(1)
            .and_then(|i| usize::try_from(i).ok())
            .ok_or_else(|| Error("OBSERVATION_SEQUENCE".into()))?;
        Ok(self.0.get(index).cloned())
    }
    fn commit(&mut self, _: &CommitIntent) -> Result<Record, Error> {
        Err(Error("OBSERVATION_READ_ONLY".into()))
    }
    fn mark_ready(&mut self, _: u64) -> Result<(), Error> {
        Err(Error("OBSERVATION_READ_ONLY".into()))
    }
    fn acknowledge(&mut self, _: u64) -> Result<(), Error> {
        Err(Error("OBSERVATION_READ_ONLY".into()))
    }
}

#[test]
fn decoded_original_funding_rows_cannot_certify_a_detached_ready_prefix() {
    let (cfg, inputs) = scenario();
    let (_root, run) = prepare_prefix(&cfg, &inputs, 7);
    let (original_owners, originals) = run.fork_ready().unwrap();
    let checkpoint = original_owners.checkpoint().unwrap();
    let checkpoint_digest = onlyalpha_execution::digest(&serde_json::to_vec(&checkpoint).unwrap());
    let rows = originals
        .iter()
        .map(|r| Record::decode(&r.record()).unwrap())
        .collect();
    let mut observation = FundingObservation(rows);
    let mut replayed = Components::new(cfg.clone()).unwrap();
    let detached_recovery = onlyalpha_execution::recover(&mut observation, &mut replayed);
    let mut copied = Components::new(cfg).unwrap();
    copied.restore(&checkpoint, &checkpoint_digest).unwrap();
    let detached_ready = copied.fork_ready(&observation);
    let detached_state = copied.state(&observation);
    let existing = observation.get(7).unwrap().unwrap();
    let detached_coordinate = coordinate(&mut observation, &mut copied, existing.prepared());
    assert_eq!(run.records().unwrap(), originals);
    verify(&run.state().unwrap());
    assert_eq!(
        [
            detached_recovery.is_err(),
            detached_ready.is_err(),
            detached_state.is_err(),
            detached_coordinate.is_err()
        ],
        [true; 4],
        "通用只读记录不能证明目的 Run 的 Funding 已 Ready"
    );
}

#[test]
fn pure_source_history_from_original_clock_cannot_issue_a_funding_commit_intent() {
    use onlyalpha_broker::source::{SourceHistory, SourceStep};
    use onlyalpha_execution::MarketSourceCut;
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 0);
    let (scope, cash, settings) = venue_config(&inputs);
    let terms = &cfg["perpetual"];
    let binding = terms["execution_source_binding"].as_str().unwrap();
    let mut mark = inputs[5].clone();
    mark["runtime_sequence"] = json!(1);
    runtime.apply(&mark).unwrap();
    let mut funding = inputs[6].clone();
    funding["runtime_sequence"] = json!(2);
    let boundary = onlyalpha_execution::funding_boundary(&funding["payload"]["fact"]).unwrap();
    let visible = funding["time"].as_u64().unwrap();
    let mut actor = BoundVirtualActor::open(
        &root.0,
        scope.clone(),
        &"f".repeat(64),
        cash,
        &settings,
        binding,
    )
    .unwrap();
    assert!(runtime.prepare_original_funding(&funding).is_err());
    assert!(runtime.apply(&funding).is_err());
    runtime.recover().unwrap();
    actor.advance(i64::try_from(boundary + 1).unwrap()).unwrap();
    let native = runtime.prepare_original_funding(&funding).unwrap();

    let db = rusqlite::Connection::open_with_flags(
        root.0.join("broker.sqlite3"),
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .unwrap();
    let genesis: String = db
        .query_row(
            "SELECT binding FROM source_genesis WHERE singleton=1",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let (previous, input, step_hash): (String, String, String) = db.query_row(
        "SELECT previous,input,hash FROM source_steps WHERE sequence=1 AND fact_count=0 AND witness IS NULL",
        [], |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    ).unwrap();
    let input = serde_json::from_str(&input).unwrap();
    let mut history = SourceHistory::new(
        scope.clone(),
        &serde_json::from_str(&genesis).unwrap(),
        binding,
        Some((boundary, visible)),
    )
    .unwrap();
    history
        .accept_step(
            SourceStep {
                sequence: 1,
                previous: &previous,
                input: &input,
                fact_count: 0,
                hash: &step_hash,
                protocol_hash: None,
            },
            std::iter::empty(),
        )
        .unwrap();
    assert!(
        history
            .funding_closure(binding, boundary, visible)
            .unwrap()
            .1
            .is_empty()
    );
    let journal = BoundBrokerJournal::open(&root.0, binding).unwrap();
    let broker = onlyalpha_broker::Broker::recover(scope, &journal, 32).unwrap();
    let cut = MarketSourceCut::read(
        &fs::read(root.0.join("market-source-cut.json")).unwrap(),
        terms["source_cut_sha256"].as_str().unwrap(),
    )
    .unwrap();
    let (mut isolated, rows) = runtime.fork_ready().unwrap();
    let mut observation = FundingObservation(rows);
    fn returns_prepared<T: 'static>(_: &Result<T, Error>) -> bool {
        std::any::TypeId::of::<T>() == std::any::TypeId::of::<onlyalpha_execution::Prepared>()
    }
    let data = onlyalpha_execution::ProjectionData::new(&isolated, &observation.0);
    let candidate = data.evaluate_funding(&funding, &cut, &broker, &history);
    let public_returns_prepared = returns_prepared(&candidate);
    let draft = candidate.unwrap();
    assert_eq!(draft.value(), native.value());
    let wire =
        onlyalpha_execution::Prepared::decode(&serde_json::to_vec(draft.value()).unwrap()).unwrap();
    let issued_intent = coordinate(&mut observation, &mut isolated, &wire)
        .unwrap_err()
        .0
        == "OBSERVATION_READ_ONLY";
    assert_eq!(observation.head().unwrap(), 1);
    runtime.apply(&funding).unwrap();
    assert_eq!(runtime.records().unwrap().len(), 2);
    runtime.apply(&funding).unwrap();
    assert_eq!(runtime.records().unwrap().len(), 2);
    assert_eq!(
        (public_returns_prepared, issued_intent),
        (false, false),
        "被动计算的公开返回类型以及通用 Store 实际是否收到 CommitIntent"
    );
}

#[test]
fn original_query_reopen_checks_header_children_protocol_and_media_version() {
    use onlyalpha_broker::{Journal, source::QueryPhase};
    let (cfg, inputs) = scenario();
    let (root, run, mut actor, mut broker, mut journal) = unobserved_acceptance(&cfg, &inputs);
    let key = actor
        .observe_command(QueryPhase::Discovery, "original-submit")
        .unwrap();
    journal
        .reconcile_original(&mut broker, "original-submit", &key)
        .unwrap();
    let protocol = journal.records().unwrap();
    let checkpoint = actor.checkpoint();
    drop((actor, run));
    let (scope, cash, settings) = venue_config(&inputs);
    let binding = cfg["perpetual"]["execution_source_binding"]
        .as_str()
        .unwrap();
    let open = || {
        BoundVirtualActor::open(
            &root.0,
            scope.clone(),
            &"f".repeat(64),
            cash.clone(),
            &settings,
            binding,
        )
    };
    let sql = rusqlite::Connection::open(root.0.join("broker.sqlite3")).unwrap();
    let header: String = sql
        .query_row(
            "SELECT header FROM source_queries WHERE id=?1",
            [&key],
            |r| r.get(0),
        )
        .unwrap();
    assert_eq!(
        sql.execute(
            "UPDATE source_queries SET header=' '||header WHERE id=?1",
            [&key]
        )
        .unwrap(),
        1
    );
    assert!(open().is_err());
    assert!(journal.records().is_err());
    sql.execute(
        "UPDATE source_queries SET header=?1 WHERE id=?2",
        rusqlite::params![header, key],
    )
    .unwrap();
    let child: String = sql
        .query_row(
            "SELECT identity FROM source_query_facts WHERE query_id=?1 AND ordinal=0",
            [&key],
            |r| r.get(0),
        )
        .unwrap();
    sql.execute(
        "DELETE FROM source_query_facts WHERE query_id=?1 AND ordinal=0",
        [&key],
    )
    .unwrap();
    assert!(open().is_err());
    assert!(journal.records().is_err());
    sql.execute(
        "INSERT INTO source_query_facts VALUES(?1,0,?2)",
        rusqlite::params![key, child],
    )
    .unwrap();
    let predecessor: i64 = sql
        .query_row(
            "SELECT protocol FROM source_queries WHERE id=?1",
            [&key],
            |r| r.get(0),
        )
        .unwrap();
    sql.execute(
        "UPDATE source_queries SET protocol=?1 WHERE id=?2",
        rusqlite::params![predecessor - 1, key],
    )
    .unwrap();
    assert!(open().is_err());
    assert!(journal.records().is_err());
    sql.execute(
        "UPDATE source_queries SET protocol=?1 WHERE id=?2",
        rusqlite::params![predecessor, key],
    )
    .unwrap();
    assert_eq!(open().unwrap().checkpoint(), checkpoint);
    assert_eq!(journal.records().unwrap(), protocol);
    sql.pragma_update(None, "user_version", 1).unwrap();
    assert!(open().is_err());
    assert!(BoundBrokerJournal::open(&root.0, binding).is_err());
    assert!(Runtime::open(&root.0, cfg.clone(), &artifact()).is_err());
    sql.pragma_update(None, "user_version", 2).unwrap();
    assert_eq!(open().unwrap().checkpoint(), checkpoint);
    assert_eq!(journal.records().unwrap(), protocol);
}

#[test]
fn decoded_post_funding_input_cannot_create_a_new_runtime_record() {
    let (cfg, inputs) = scenario();
    let (_root, mut runtime) = prepare_prefix(&cfg, &inputs, 7);
    let before = runtime.records().unwrap();
    let state = runtime.state().unwrap();
    let mut input = inputs[1].clone();
    input["input_id"] = json!("post-funding-open");
    input["source_ref"] = json!("post-funding-open");
    input["runtime_sequence"] = json!(8);
    input["time"] = json!(inputs[6]["time"].as_u64().unwrap() + 1);
    input["payload"]["order"] = json!("runtime-ORDER-000002");
    input["payload"]["request"]["request_id"]["value"] = json!("second-open");
    input["payload"]["request"]["quantity"]["value"] = json!("1");
    assert_eq!(
        runtime.prepare(&input).unwrap_err().0,
        "RUNTIME_RUN_PLAN_REQUIRED"
    );
    let original = runtime.prepare_run_plan(&input).unwrap();
    let wire =
        onlyalpha_execution::Prepared::decode(&serde_json::to_vec(original.value()).unwrap())
            .unwrap();
    assert!(
        runtime.apply_prepared(&wire).is_err(),
        "解码后的被动传输件不得创建 Funding 后的新交易事实"
    );
    runtime.recover().unwrap();
    assert_eq!(runtime.records().unwrap(), before);
    assert_eq!(runtime.state().unwrap(), state);
    runtime.apply_run_plan(&original).unwrap();
    let committed = runtime.records().unwrap();
    assert_eq!(committed.len(), 8);
    runtime.apply_prepared(&wire).unwrap();
    assert_eq!(runtime.records().unwrap(), committed);
}

#[test]
fn uncommitted_funding_projection_cannot_issue_a_sealed_transcript() {
    let (cfg, inputs) = scenario();
    let (_root, mut runtime) = prepare_prefix(&cfg, &inputs, 6);
    let (owners, mut rows) = runtime.fork_ready().unwrap();
    let native = runtime.prepare_original_funding(&inputs[6]).unwrap();
    rows.push(
        Record::decode(
            &json!({"schema_version":1,"prepared":native.value(),"ready":false,"delivered":false}),
        )
        .unwrap(),
    );
    let mut data = onlyalpha_execution::ProjectionData::new(&owners, &rows);
    data.replay().unwrap();
    let manifest = json!({"schema_version":1,"configuration":onlyalpha_execution::digest(cfg.to_string().as_bytes()),"kernel_artifact":artifact(),"input_pin":"c".repeat(64),"initial_time":{"schema_version":1,"unix_nanos":inputs[0]["time"]},"final_time":{"schema_version":1,"unix_nanos":inputs[6]["time"]},"inputs":inputs.iter().map(|v| onlyalpha_execution::digest(v.to_string().as_bytes())).collect::<Vec<_>>()});
    let outcome =
        json!({"schema_version":1,"status":"INCOMPLETE","reason":"projection comparison"});
    let result = data.transcript(&manifest, &outcome).unwrap().record();
    assert_eq!(runtime.records().unwrap().len(), 6);
    assert!(
        [
            "final_seal",
            "id",
            "determinism_fingerprint",
            "result_fingerprint"
        ]
        .iter()
        .all(|field| result.get(*field).is_none()),
        "未提交 Funding 的纯回放不得生成正式 Execution transcript 封存身份"
    );
    runtime.apply_original_funding(&native).unwrap();
    let actual = runtime
        .backtest_result(&manifest, &outcome)
        .unwrap()
        .record();
    assert!(!actual["final_seal"].is_null());
    assert!(actual["id"].as_str().unwrap().starts_with("BTR-"));
    assert_eq!(
        actual["determinism_fingerprint"].as_str().unwrap().len(),
        64
    );
    assert_eq!(
        actual["result_fingerprint"],
        actual["determinism_fingerprint"]
    );
    for (field, value) in result.as_object().unwrap() {
        assert_eq!(
            actual.get(field.as_str()),
            Some(value),
            "候选经济数据与实际封存的字段 {field} 应一致"
        );
    }
}
