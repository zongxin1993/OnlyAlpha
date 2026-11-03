use crate::{Candidate, MarketInput, NextOpenPolicy, next_open::NativeReplay};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::OnlyBar,
    time::{OnlyTimestamp, OnlyUtcDateTime},
    value::{OnlyPrice, OnlyQuantity},
};
use serde_json::{Value, json};
use std::str::FromStr;
const FACTS: &str = include_str!("../../../test-data/domain/fact-records-v1.jsonl");
fn configuration() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"10000.00","capitals":{"cluster":"10000.00"},"profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["A.X"],"rules":[]}},"instruments":[{"schema_version":1,"id":"A.X","price_precision":2,"quantity_precision":2,"multiplier":"1"}]})
}
fn input(index: u64, price: &str) -> MarketInput {
    let mut v = FACTS
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap())
        .find(|v| v["id"] == "bar")
        .unwrap()["record"]
        .clone();
    for key in ["open", "high", "low", "close"] {
        v[key]["value"] = json!(price);
    }
    for key in ["bar_start", "bar_end", "ts_event", "ts_init"] {
        let t = OnlyUtcDateTime::from_str(v[key].as_str().unwrap()).unwrap();
        let ns = OnlyTimestamp::from_datetime(t).to_unix_nanos() + (index - 1) * 60_000_000_000_u64;
        v[key] = json!(
            OnlyTimestamp::from_unix_nanos(ns)
                .to_datetime_exact()
                .unwrap()
                .to_string()
        );
    }
    MarketInput::new(
        &"a".repeat(64),
        index,
        "recorded",
        OnlyBar::from_record(&v).unwrap(),
    )
    .unwrap()
}
fn settings() -> Value {
    let start = OnlyTimestamp::from_datetime(*input(2, "10.00").bar().bar_start()).to_unix_nanos();
    let end = input(6, "10.00").event_ns();
    json!({"schema_version":2,"execution":configuration(),"instrument":null,"calendar":{},"policy":{"schema_version":1,"kind":"NEXT_OPEN_LONG_ONLY_V1","quantity":{"schema_version":1,"value":"0.01","precision":2},"buy_multiplier":"1.0002","sell_multiplier":"0.9998","start_ns":start.to_string(),"end_ns":end.to_string()}})
}
struct Denied;
impl NextOpenPolicy for Denied {
    fn binding(&self) -> Value {
        json!({"schema_version":1,"kind":"UNIT_MODEL_POLICY","configuration":crate::hash(&configuration()),"reference_policy":"MODEL_NEXT_OPEN"})
    }
    fn admission(&self, _: &Value, _: &OnlyPrice, _: &Value) -> Result<Value, crate::Error> {
        Ok(
            json!({"schema_version":1,"accepted":false,"reason":"CONTROLLED_MODEL_REJECTION","market_provenance":{"kind":"MODEL_RULE_DECISION","verdict":"MODEL_REJECT","reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false}}),
        )
    }
    fn fill(
        &self,
        _: &Value,
        _: &OnlyPrice,
        _: &OnlyQuantity,
        _: &Value,
    ) -> Result<Value, crate::Error> {
        panic!("rejected admission cannot reach fill")
    }
}
fn state() -> (NativeReplay, Candidate) {
    (
        NativeReplay::new(&settings(), Box::new(Denied), 0.into(), "cluster").unwrap(),
        Candidate::new(configuration(), vec![]).unwrap(),
    )
}
fn decision(entry: bool, exit: bool) -> Value {
    json!({"schema_version":1,"decisions":[{"schema_version":1,"status":"READY","decision":{"eligibility":true,"entry":entry,"exit":exit}}]})
}
#[test]
fn missing_warmup_and_ineligible_decisions_cannot_schedule_orders() {
    let (mut p, c) = state();
    assert_eq!(
        p.closed(&input(1, "10.00"), &decision(true, false), &c)
            .unwrap()["status"],
        "WARMUP"
    );
    assert!(p.capture()["pending"].is_null());
    let blocked = json!({"schema_version":1,"decisions":[{"status":"BLOCKED","decision":null}]});
    p.closed(&input(2, "10.00"), &blocked, &c).unwrap();
    assert!(p.capture()["pending"].is_null());
    let mut ineligible = decision(true, false);
    ineligible["decisions"][0]["decision"]["eligibility"] = json!(false);
    p.closed(&input(2, "10.00"), &ineligible, &c).unwrap();
    assert!(p.capture()["pending"].is_null());
}
#[test]
fn a_closed_signal_waits_for_the_next_open_and_rejection_creates_no_order() {
    let (mut p, mut c) = state();
    let scheduled = p
        .closed(&input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    assert_eq!(scheduled["status"], "PENDING");
    let pending = p.capture()["pending"].clone();
    p.closed(&input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    assert_eq!(p.capture()["pending"], pending);
    assert!(c.records().is_empty());
    assert!(p.opening(&input(2, "10.00").opening(), &mut c).is_err());
    let result = p.opening(&input(3, "12.00").opening(), &mut c).unwrap();
    assert_eq!(result["status"], "REJECTED");
    assert_eq!(result["reason"], "CONTROLLED_MODEL_REJECTION");
    assert_eq!(result["execution_price"]["value"], "12.002400");
    assert_eq!(result["execution_price"]["precision"], 6);
    assert!(c.records().is_empty());
    assert!(p.capture()["pending"].is_null());
}
#[test]
fn finite_end_cancels_an_unsubmitted_signal_without_fabricating_an_order() {
    let (mut p, mut c) = state();
    p.closed(&input(6, "10.00"), &decision(true, false), &c)
        .unwrap();
    let ended = p.end_input(&mut c).unwrap();
    assert_eq!(ended["signal"]["status"], "CANCELLED");
    assert_eq!(ended["signal"]["reason"], "INPUT_EXHAUSTED");
    assert!(c.records().is_empty());
    assert!(p.quiescent().unwrap());
    assert!(p.capture()["finished"].as_bool().unwrap());
}
#[test]
fn immutable_policy_and_pending_checkpoint_are_exactly_bound() {
    let (mut p, c) = state();
    p.closed(&input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    let cp = p.capture();
    let (mut restored, _) = state();
    restored.restore(&cp).unwrap();
    assert_eq!(restored.capture(), cp);
    let mut foreign = cp.clone();
    foreign["binding"] = json!("f".repeat(64));
    assert!(restored.restore(&foreign).is_err());
    assert_eq!(restored.capture(), cp);
}

// Controlled immutable economic inputs isolate this policy boundary; the real plugin/Fee lane is separate.
struct ProofPolicy {
    cfg: Value,
}
impl ProofPolicy {
    fn money(&self, price: &OnlyPrice, quantity: &OnlyQuantity) -> Value {
        let exact =
            onlyalpha_domain::numeric::only_multiply(price.value(), quantity.value()).unwrap();
        let resolved =
            onlyalpha_domain::numeric::only_quantize(&exact, &"0.01".parse().unwrap()).unwrap();
        onlyalpha_domain::value::OnlyMoney::new(
            resolved,
            onlyalpha_domain::value::OnlyCurrency::from_record(&self.cfg["currency"]).unwrap(),
        )
        .unwrap()
        .to_record()
    }
}
impl NextOpenPolicy for ProofPolicy {
    fn binding(&self) -> Value {
        json!({"schema_version":1,"kind":"UNIT_CANONICAL_INPUTS_MODEL","configuration":crate::hash(&self.cfg),"reference_policy":"MODEL_NEXT_OPEN"})
    }
    fn admission(
        &self,
        order: &Value,
        price: &OnlyPrice,
        context: &Value,
    ) -> Result<Value, crate::Error> {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../test-data/execution/domain-inputs.json"
        ))
        .unwrap();
        let mut contract = if order["side"] == "BUY" {
            fixture["fee_contract"].clone()
        } else {
            fixture["second_fee_contract"].clone()
        };
        // This is a new modeled Order occurrence, not the fixture's original 1ns binding.
        use onlyalpha_domain::fee::{OnlyOrderFeePolicyBinding, OnlyOrderFeePolicyBindingInput};
        let original = OnlyOrderFeePolicyBinding::from_record(&contract["binding"]).unwrap();
        let binding = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
            runtime_id: original.runtime_id().clone(),
            account_id: original.account_id().clone(),
            cluster_id: original.cluster_id().clone(),
            order_id: original.order_id().clone(),
            instrument_id: original.instrument_id().clone(),
            market_product_id: original.market_product_id().clone(),
            market_product_version: original.market_product_version().clone(),
            market_fee_pack: original.market_fee_pack().clone(),
            broker_fee_contract: original.broker_fee_contract().clone(),
            applicability_scope: original.applicability_scope().clone(),
            order_fixed_schedules: original.order_fixed_schedules().clone(),
            fill_effective_families: original.fill_effective_families().clone(),
            charge_currency: original.charge_currency().clone(),
            bound_at: OnlyTimestamp::from_record(
                &json!({"schema_version":1,"unix_nanos":context["time"]}),
            )
            .unwrap(),
            fingerprint: String::new(),
        })
        .unwrap();
        assert_ne!(binding.fingerprint(), original.fingerprint());
        assert_eq!(
            binding.bound_at().to_record()["unix_nanos"],
            context["time"]
        );
        contract["binding"] = binding.to_record();
        for assessment in ["expected", "maximum"] {
            contract["estimate"][assessment]["binding"] = binding.to_record();
        }
        contract["funding"]["binding_fingerprint"] = json!(binding.fingerprint());
        let quantity = OnlyQuantity::from_record(&order["quantity"]).unwrap();
        let notional = self.money(price, &quantity);
        if order["side"] == "BUY" {
            contract["funding"]["principal_reservation"]["amount"] = notional["amount"].clone();
            contract["funding"]["total_reservation"]["amount"] = notional["amount"].clone();
        }
        Ok(
            json!({"schema_version":1,"accepted":true,"contract":contract,"fee_budget":"1.00","notional":notional,"market_provenance":{"kind":"MODEL_RULE_DECISION","verdict":"MODEL_ACCEPT","reference_policy":"MODEL_NEXT_OPEN","venue_acceptance_proven":false}}),
        )
    }
    fn fill(
        &self,
        _: &Value,
        price: &OnlyPrice,
        quantity: &OnlyQuantity,
        _: &Value,
    ) -> Result<Value, crate::Error> {
        let fixture: Value =
            serde_json::from_str(include_str!("../../../test-data/settlement/common-v1.json"))
                .unwrap();
        Ok(
            json!({"schema_version":1,"charge_target":"1.00","rebate_target":"0.00","gross_notional":self.money(price,quantity),"settlement_policy":fixture["policy"]}),
        )
    }
}
fn native_input(index: u64, price: &str) -> MarketInput {
    let i = input(index, price);
    let mut v = i.bar().to_record();
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../test-data/execution/domain-inputs.json"
    ))
    .unwrap();
    v["bar_type"]["instrument_id"] = fixture["request"]["instrument_id"].clone();
    MarketInput::new(
        i.source(),
        i.sequence(),
        "recorded",
        OnlyBar::from_record(&v).unwrap(),
    )
    .unwrap()
}
fn native_state(cash: &str) -> (NativeReplay, Candidate) {
    let mut cfg = configuration();
    cfg["currency"] = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
    cfg["initial_cash"] = json!(cash);
    cfg["capitals"]["cluster"] = json!(cash);
    cfg["profiles"]["cluster"]["instruments"] = json!(["600000.XSHG"]);
    cfg["instruments"][0]["id"] = json!("600000.XSHG");
    cfg["instruments"][0]["quantity_precision"] = json!(0);
    let fixture: Value =
        serde_json::from_str(include_str!("../../../test-data/settlement/common-v1.json")).unwrap();
    let mut s = settings();
    s["execution"] = cfg.clone();
    // A fresh proof calendar covers these 2025 Bars. The shared settlement
    // vector's 2026 coverage belongs to its original occurrence, not this one.
    let mut calendar = fixture["calendar"].clone();
    calendar["calendar_id"]["value"] = json!("native-policy-proof-calendar-2025");
    calendar["effective_from"] = json!("2025-01-01");
    calendar["effective_to"] = json!("2026-01-01");
    calendar["holidays"] = json!([]);
    let calendar = onlyalpha_domain::calendar::OnlyTradingCalendar::from_record(&calendar).unwrap();
    let day = onlyalpha_domain::time::OnlyTradingDay::from_record(
        &json!({"schema_version":1,"value":native_input(3,"10.00").bar().to_record()["trading_day"]}),
    ).unwrap();
    assert!(calendar.is_effective_on(day));
    assert!(calendar.is_trading_day(day));
    s["calendar"] = calendar.to_record();
    s["policy"]["quantity"] = json!({"schema_version":1,"value":"4","precision":0});
    (
        NativeReplay::new(
            &s,
            Box::new(ProofPolicy { cfg: cfg.clone() }),
            0.into(),
            "cluster",
        )
        .unwrap(),
        Candidate::new(cfg, vec![]).unwrap(),
    )
}
#[test]
fn whole_next_open_roundtrip_uses_canonical_kernel_cost_fee_and_position() {
    let (mut p, mut c) = native_state("10000.00");
    p.closed(&native_input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    let bought = p
        .opening(&native_input(3, "10.00").opening(), &mut c)
        .unwrap();
    assert_eq!(bought["status"], "FILLED");
    assert_eq!(bought["execution_price"]["value"], "10.002000");
    let state = c.state().unwrap();
    assert_eq!(state["account"]["snapshot"]["cash"], "9958.99");
    assert_eq!(state["account"]["snapshot"]["market_value"], "40.00");
    assert_eq!(
        state["position"]["accounts"][0]["snapshot"]["cost"],
        "40.008"
    );
    assert_eq!(
        p.closed(&native_input(3, "10.00"), &decision(true, false), &c)
            .unwrap()["status"],
        "NO_SIGNAL"
    );
    assert!(p.capture()["pending"].is_null());
    p.closed(&native_input(4, "12.00"), &decision(false, true), &c)
        .unwrap();
    let sold = p
        .opening(&native_input(5, "12.00").opening(), &mut c)
        .unwrap();
    assert_eq!(sold["status"], "FILLED");
    assert_eq!(sold["execution_price"]["value"], "11.997600");
    let state = c.state().unwrap();
    assert_eq!(state["account"]["snapshot"]["cash"], "10005.98");
    assert_eq!(state["account"]["snapshot"]["fees"], "2.00");
    assert_eq!(
        state["position"]["accounts"][0]["snapshot"]["quantity"],
        "0"
    );
    assert_eq!(state["execution"]["orders"].as_object().unwrap().len(), 2);
    let fills: Vec<_> = c
        .records()
        .iter()
        .filter(|r| r.prepared().input()["op"] == "FILL")
        .collect();
    assert_eq!(fills.len(), 2);
    assert_eq!(
        fills[0].prepared().input()["time"],
        bought["opening"]["time"]["unix_nanos"]
    );
}
#[test]
fn opening_gap_insufficient_funds_is_a_rejection_with_no_kernel_order() {
    let (mut p, mut c) = native_state("40.00");
    p.closed(&native_input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    let result = p
        .opening(&native_input(3, "10.00").opening(), &mut c)
        .unwrap();
    assert_eq!(result["status"], "REJECTED");
    assert_eq!(result["reason"], "INSUFFICIENT_FUNDS");
    assert!(c.records().is_empty());
    assert!(p.capture()["pending"].is_null());
}

#[test]
fn native_day_index_reuses_domain_date_difference() {
    let ordinal = |day: &str| {
        crate::next_open::context(&"a".repeat(64), 0.into(), &json!(day)).unwrap()["day_index"]
            .as_u64()
            .unwrap()
    };
    assert_eq!(ordinal("0001-01-01"), 1);
    assert_eq!(ordinal("1970-01-01"), 719163);
    assert_eq!(ordinal("1900-03-01") - ordinal("1900-02-28"), 1);
    assert_eq!(ordinal("2000-03-01") - ordinal("2000-02-28"), 2);
    assert_eq!(ordinal("2024-03-01") - ordinal("2024-02-29"), 1);
}

#[test]
fn pending_cut_requires_the_owning_strategy_outcome_and_rejects_rehashed_splices() {
    let (mut p, c) = state();
    p.closed(&input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    let cp = p.capture();
    let owner = json!({"status":"READY","event_ns":input(2,"10.00").event_ns().to_string(),"decision":cp["pending"]["decision"]});
    assert!(p.validate_cut(&"a".repeat(64), None).is_err());
    p.validate_cut(&"a".repeat(64), Some(&owner)).unwrap();
    for field in ["decision", "time", "source"] {
        let mut forged = cp.clone();
        match field {
            "decision" => {
                forged["pending"]["decision"]["exit"] = json!(true);
                forged["pending"]["decision_identity"] =
                    json!(crate::hash(&forged["pending"]["decision"]));
            }
            "time" => forged["pending"]["signal_time"] = json!("0"),
            _ => forged["pending"]["source"] = json!("b".repeat(64)),
        }
        // Integrity fields alone do not authenticate a decision producer.
        p.restore(&forged).unwrap();
        assert!(
            p.validate_cut(&"a".repeat(64), Some(&owner)).is_err(),
            "{field}"
        );
    }
    p.restore(&cp).unwrap();
    p.validate_cut(&"a".repeat(64), Some(&owner)).unwrap();
}
#[test]
fn pending_close_cannot_be_rebound_to_a_flat_execution_genesis() {
    let (mut p, mut c) = native_state("10000.00");
    p.closed(&native_input(2, "10.00"), &decision(true, false), &c)
        .unwrap();
    p.opening(&native_input(3, "10.00").opening(), &mut c)
        .unwrap();
    p.closed(&native_input(4, "12.00"), &decision(false, true), &c)
        .unwrap();
    p.validate_execution(&c).unwrap();
    let flat = Candidate::new(c.configuration().clone(), vec![]).unwrap();
    assert!(p.validate_execution(&flat).is_err());
}

#[test]
fn user_cancel_clears_only_the_unsent_signal_and_retains_actual_position_and_cost() {
    let (mut policy, mut execution) = native_state("10000.00");
    policy.closed(&native_input(2, "10.00"), &decision(true, false), &execution).unwrap();
    policy.opening(&native_input(3, "10.00").opening(), &mut execution).unwrap();
    policy.closed(&native_input(3, "10.00"), &decision(false, true), &execution).unwrap();
    assert_eq!(policy.capture()["pending"]["side"], "SELL");
    let before = execution.state().unwrap();
    let records = execution.records().to_vec();
    let stopped = policy.cancel_input(&mut execution).unwrap();
    assert_eq!(stopped["signal"]["status"], "CANCELLED");
    assert_eq!(stopped["signal"]["reason"], "USER_CANCELLED");
    assert_eq!(stopped["signal"]["signal"]["side"], "SELL");
    assert!(stopped["cancelled_orders"].as_array().unwrap().is_empty());
    assert_eq!(execution.state().unwrap(), before);
    assert_eq!(execution.records(), records);
    assert_eq!(before["position"]["accounts"][0]["snapshot"]["quantity"], "4");
    assert_eq!(before["position"]["accounts"][0]["snapshot"]["cost"], "40.008");
    assert!(policy.capture()["pending"].is_null());
    assert!(policy.quiescent().unwrap());
    let checkpoint = policy.capture();
    let (mut restored, _) = native_state("10000.00");
    restored.restore(&checkpoint).unwrap();
    assert_eq!(restored.capture(), checkpoint);
    restored.validate_execution(&execution).unwrap();
    assert!(restored.opening(&native_input(4, "12.00").opening(), &mut execution).is_err());
}

#[test]
fn whole_fill_native_producer_binds_the_actual_model_and_fee_estimate_in_admit2() {
    let (mut policy,mut execution)=native_state("10000.00");
    policy.closed(&native_input(2,"10.00"),&decision(true,false),&execution).unwrap();
    policy.opening(&native_input(3,"10.00").opening(),&mut execution).unwrap();
    let admit=execution.records().iter().map(|r|r.prepared().input()).find(|r|r["op"]=="ADMIT").unwrap();
    let contract=&admit["payload"]["settlement_fill_contract"];
    assert_eq!(admit["payload"]["schema_version"],2);
    assert_eq!(contract["kind"],"BACKTEST_WHOLE_FILL");assert_eq!(contract["maximum_fill_count"],1);
    assert_eq!(contract["model"]["kind"],"GUARANTEED_WHOLE_FILL");
    assert_eq!(contract["model"]["configuration_fingerprint"],crate::hash(execution.configuration()));
    assert_eq!(contract["model"]["policy_fingerprint"],admit["payload"]["request"]["metadata"]["replay_policy"]);
    assert_eq!(contract["model_fingerprint"],crate::hash(&contract["model"]));
    assert_eq!(contract["fee_estimate_assumptions_fingerprint"],admit["payload"]["fee_contract"]["estimate"]["assumptions_fingerprint"]);
    assert_eq!(policy.capture()["execution_model"],contract["model"]);
}
