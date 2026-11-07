//! Existing independent three-fact vector shared by two native tests.
use crate::hash;
use serde_json::{Value, json};
const FIXTURE: &str = include_str!("../../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../../test-data/settlement/common-v1.json");
const ECONOMICS: &str = include_str!("../../../../../test-data/execution/economics-v1.json");
pub(crate) fn configuration(modern: bool) -> Value {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let economics: Value = serde_json::from_str(ECONOMICS).unwrap();
    let mut value = json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST",
  "currency":fixture["fee_contract"]["binding"]["charge_currency"],"initial_cash":economics["initial_cash"],"capitals":{"cluster":economics["initial_cash"]},
  "profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["600000.XSHG"],"rules":[]}},"instruments":[{"schema_version":1,"id":"600000.XSHG","price_precision":2,"quantity_precision":0,"multiplier":"1"}]});
    if modern {
        value["schema_version"] = json!(2);
        value["account_checkpoint_version"] = json!(5);
    }
    value
}
pub(crate) fn original_three_facts() -> [Value; 3] {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let economics: Value = serde_json::from_str(ECONOMICS).unwrap();
    let settlement: Value = serde_json::from_str(SETTLEMENT_FIXTURE).unwrap();
    let config = configuration(false);
    let order = &fixture["fee_contract"]["binding"]["order_id"]["value"];
    let trade = &economics["buy_fills"][0];
    // This existing independent vector's first Fill is one unit, so its exact
    // notional is its declared price; no arithmetic implementation is needed.
    assert_eq!(trade["quantity"], "1");
    let mut notional = fixture["fee_contract"]["funding"]["principal_reservation"].clone();
    notional["amount"] = trade["price"].clone();
    let none = json!({"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null});
    let admission = json!({"schema_version":1,"request":fixture["request"],"fee_contract":fixture["fee_contract"],"fee_budget":trade["charge_target"],
  "market":{"schema_version":1,"verdict":"ACCEPT","source_ref":"market-1","request_digest":hash(&fixture["request"]),"notional":fixture["fee_contract"]["funding"]["principal_reservation"],"rounding":"HALF_EVEN"},"order":order,"collateral":none});
    let mut fill = json!({"schema_version":1,"order":order,"trade":"trade-3","venue_trade":"venue-trade-3","venue_order":"venue-1","quantity":trade["quantity"],"price":trade["price"],"collateral":none,
  "fees":{"schema_version":1,"instruction":"fee-3","source_ref":"fee-source-3","policy":fixture["fee_contract"]["binding"]["fingerprint"],"order":order,"trade":"trade-3","currency":config["currency"],"charge_target":trade["charge_target"],"rebate_target":"0.00"},
  "settlement":{"schema_version":1,"instruction":"settlement-3","source_ref":"settlement-source-3","order":order,"trade":"trade-3","currency":config["currency"],"model":"CASH_SETTLEMENT","gross_notional":notional,"rounding":"HALF_EVEN","calendar":settlement["calendar"],"policy":settlement["policy"]},
  "valuation":{"schema_version":1,"source_ref":"valuation-source-3","currency":config["currency"],"mark":trade["price"]}});
    let scope = json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":config["runtime_kind"],"cluster":"cluster","revision":"revision","instrument":"600000.XSHG","request":fixture["request"]["request_id"]["value"]});
    for (key, family) in [
        ("fees", "ORDER_FEE_ACCRUAL"),
        ("settlement", "SETTLEMENT"),
        ("valuation", "VALUATION"),
    ] {
        let proof = &mut fill[key];
        proof["scope"] = scope.clone();
        proof["family"] = json!(family);
        proof["version"] = json!(3);
        proof["as_of_sequence"] = json!(3);
        proof["source_digest"] = json!(hash(proof));
    }
    let payloads = [
        ("ADMIT", admission),
        (
            "SUBMISSION",
            json!({"schema_version":1,"order":order,"outcome":"UNKNOWN"}),
        ),
        ("FILL", fill),
    ];
    std::array::from_fn(|index| {
        let (operation, payload) = &payloads[index];
        let sequence = index as u64 + 1;
        json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"generation":config["generation"],"runtime_kind":config["runtime_kind"],
   "cluster":"cluster","revision":"revision","input_id":format!("input-{sequence}"),"time":sequence,"runtime_sequence":sequence,"trading_day":"2026-10-19","day_index":1,"source_ref":format!("source-{sequence}"),"op":operation,"payload":payload})
    })
}

// All history is produced by the real Candidate/Execution owners; no journal
// padding, capacity override, imported checkpoint or second writer is used.
fn capacity_input(candidate: &crate::Candidate, op: &str, payload: Value) -> Value {
    let n = candidate.records().len() as u64 + 1;
    let mut input = original_three_facts()[0].clone();
    input["input_id"] = json!(format!("capacity-input-{n}"));
    input["source_ref"] = json!(format!("capacity-source-{n}"));
    input["time"] = json!(n);
    input["runtime_sequence"] = json!(n);
    input["op"] = json!(op);
    input["payload"] = payload;
    input
}
pub(crate) fn capacity_admission(candidate: &crate::Candidate, buy: bool) -> Value {
    let fixture: Value = serde_json::from_str(FIXTURE).unwrap();
    let mut payload = original_three_facts()[0]["payload"].clone();
    payload["request"]["request_id"]["value"] = json!("request-2");
    payload["request"]["side"] = json!(if buy { "BUY" } else { "SELL" });
    payload["request"]["execution_intent"]["side"] = payload["request"]["side"].clone();
    payload["request"]["execution_intent"]["position_effect"] =
        json!(if buy { "OPEN" } else { "CLOSE" });
    payload["request"]["quantity"] = json!({"schema_version":1,"value":"4.00","precision":2});
    payload["request"]["price"]["value"] = json!("12.00");
    payload["fee_contract"] = fixture["second_fee_contract"].clone();
    payload["order"] = json!("runtime-ORDER-000002");
    // Same formal builder used by ProofPolicy: this is a new actual occurrence,
    // not permission to reuse the historical fixture's 5ns binding.
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        fee::{OnlyOrderFeePolicyBinding, OnlyOrderFeePolicyBindingInput},
        identifiers::OnlyOrderId,
        time::OnlyTimestamp,
    };
    let contract = &mut payload["fee_contract"];
    let old = OnlyOrderFeePolicyBinding::from_record(&contract["binding"]).unwrap();
    let order =
        OnlyOrderId::from_record(&json!({"schema_version":1,"value":"runtime-ORDER-000002"}))
            .unwrap();
    let at = candidate.records().len() as u64 + 1;
    let binding = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
        runtime_id: old.runtime_id().clone(),
        account_id: old.account_id().clone(),
        cluster_id: old.cluster_id().clone(),
        order_id: order.clone(),
        instrument_id: old.instrument_id().clone(),
        market_product_id: old.market_product_id().clone(),
        market_product_version: old.market_product_version().clone(),
        market_fee_pack: old.market_fee_pack().clone(),
        broker_fee_contract: old.broker_fee_contract().clone(),
        applicability_scope: old.applicability_scope().clone(),
        order_fixed_schedules: old.order_fixed_schedules().clone(),
        fill_effective_families: old.fill_effective_families().clone(),
        charge_currency: old.charge_currency().clone(),
        bound_at: OnlyTimestamp::from_record(&json!({"schema_version":1,"unix_nanos":at})).unwrap(),
        fingerprint: String::new(),
    })
    .unwrap();
    contract["binding"] = binding.to_record();
    for assessment in ["expected", "maximum"] {
        contract["estimate"][assessment]["binding"] = binding.to_record();
        contract["estimate"][assessment]["subject"]["order_id"] = order.to_record();
    }
    contract["funding"]["binding_fingerprint"] = json!(binding.fingerprint());
    contract["funding"]["order_id"] = order.to_record();
    payload["market"]["source_ref"] =
        json!(format!("capacity-market-{}", candidate.records().len() + 1));
    payload["market"]["request_digest"] = json!(hash(&payload["request"]));
    payload["market"]["notional"]["amount"] = json!("48.00");
    capacity_input(candidate, "ADMIT", payload)
}
fn capacity_fill(
    candidate: &crate::Candidate,
    sell: bool,
    quantity: &str,
    notional: &str,
) -> Value {
    let n = candidate.records().len() as u64 + 1;
    let ordinal = if sell { 2 } else { 1 };
    let actual_order = candidate
        .order("cluster", &format!("runtime-ORDER-{ordinal:06}"))
        .unwrap();
    let mut payload = original_three_facts()[2]["payload"].clone();
    payload["order"] = json!(format!("runtime-ORDER-{ordinal:06}"));
    payload["trade"] = json!(format!("capacity-trade-{n}"));
    payload["venue_trade"] = json!(format!("capacity-venue-trade-{n}"));
    payload["venue_order"] = json!(format!("capacity-venue-{ordinal}"));
    payload["quantity"] = json!(quantity);
    payload["price"] = json!(if sell { "12.00" } else { "10.00" });
    payload["settlement"]["gross_notional"]["amount"] = json!(notional);
    payload["valuation"]["mark"] = payload["price"].clone();
    for (key, family) in [
        ("fees", "ORDER_FEE_ACCRUAL"),
        ("settlement", "SETTLEMENT"),
        ("valuation", "VALUATION"),
    ] {
        let proof = &mut payload[key];
        proof.as_object_mut().unwrap().remove("source_digest");
        proof["source_ref"] = json!(format!("capacity-{key}-{n}"));
        proof["scope"]["request"] = json!(format!("request-{ordinal}"));
        proof["family"] = json!(family);
        proof["version"] = json!(n);
        proof["as_of_sequence"] = json!(n);
        if key != "valuation" {
            proof["instruction"] = json!(format!("capacity-{key}-instruction-{n}"));
            proof["order"] = json!(format!("runtime-ORDER-{ordinal:06}"));
            proof["trade"] = json!(format!("capacity-trade-{n}"));
        }
        if key == "fees" {
            proof["policy"] = actual_order["fee_policy_binding"]["fingerprint"].clone();
        }
        proof["source_digest"] = json!(hash(proof));
    }
    capacity_input(candidate, "FILL", payload)
}
pub(crate) fn expanded_account_journal_bytes(checkpoint: &Value) -> usize {
    let account = &checkpoint["components"][2];
    account["journal"]
        .as_array()
        .unwrap()
        .iter()
        .map(|entry| {
            let mut full = entry.clone();
            if full["op"] == "VALUATION" {
                let key = full["payload"]
                    .as_object_mut()
                    .unwrap()
                    .remove("position_ref")
                    .unwrap();
                full["payload"]["position"] = account["positions"][key.as_str().unwrap()].clone();
            }
            full.to_string().len()
        })
        .sum()
}
pub(crate) fn account_capacity_history(flat: bool) -> crate::Candidate {
    let mut cfg = configuration(true);
    cfg["instruments"][0]["quantity_precision"] = json!(2);
    let mut candidate = crate::Candidate::new(cfg, vec![]).unwrap();
    let facts = original_three_facts();
    let mut admission = facts[0].clone();
    admission["payload"]["request"]["quantity"] =
        json!({"schema_version":1,"value":"4.00","precision":2});
    admission["payload"]["market"]["request_digest"] =
        json!(hash(&admission["payload"]["request"]));
    candidate.apply(&admission).unwrap();
    candidate.apply(&facts[1]).unwrap();
    for _ in 0..64 {
        let fill = capacity_fill(&candidate, false, "0.05", "0.50");
        candidate.apply(&fill).unwrap();
    }
    let fill = capacity_fill(&candidate, false, "0.80", "8.00");
    candidate.apply(&fill).unwrap();
    if flat {
        let close = capacity_admission(&candidate, false);
        candidate.apply(&close).unwrap();
        let stage = capacity_input(
            &candidate,
            "SUBMISSION",
            json!({"schema_version":1,"order":"runtime-ORDER-000002","outcome":"UNKNOWN"}),
        );
        candidate.apply(&stage).unwrap();
        let fill = capacity_fill(&candidate, true, "4.00", "48.00");
        candidate.apply(&fill).unwrap();
    }
    assert_eq!(
        candidate.state().unwrap()["account"]["snapshot"]["fees"],
        if flat { "2.00" } else { "1.00" }
    );
    for _ in 0..300 {
        let checkpoint = candidate.checkpoint().unwrap();
        if expanded_account_journal_bytes(&checkpoint) > 4 * 1024 * 1024 {
            return candidate;
        }
        let n = candidate.records().len() as u64 + 1;
        let marks = json!([{"schema_version":1,"instrument":"600000.XSHG","mark":if flat { "12.00" } else { "10.00" },"source_ref":format!("capacity-mark-{n}"),"family":"CLOSED_BAR","version":n,"time":n,"as_of_sequence":n}]);
        let valuation = capacity_input(
            &candidate,
            "VALUATION",
            json!({"schema_version":1,"valuation":format!("capacity-valuation-{n}"),"version":n,"position_evidence":hash(&checkpoint["components"][1]),"economic_version":candidate.state().unwrap()["account"]["snapshot"]["economic_version"],"marks":marks}),
        );
        candidate.apply(&valuation).unwrap();
    }
    panic!("real owner history did not reach the unchanged admission-only capacity");
}
pub(crate) fn close_and_cancel_at_capacity(candidate: &mut crate::Candidate) {
    let close = capacity_admission(candidate, false);
    candidate.apply(&close).unwrap();
    let stage = capacity_input(
        candidate,
        "SUBMISSION",
        json!({"schema_version":1,"order":"runtime-ORDER-000002","outcome":"UNKNOWN"}),
    );
    candidate.apply(&stage).unwrap();
    let cancel = capacity_input(
        candidate,
        "CANCEL",
        json!({"schema_version":1,"order":"runtime-ORDER-000002","request_id":"capacity-cancel","reason":"USER_CANCELLED"}),
    );
    candidate.apply(&cancel).unwrap();
    let fill = capacity_fill(candidate, true, "2.00", "24.00");
    candidate.apply(&fill).unwrap();
    let terminal = capacity_input(
        candidate,
        "TERMINAL",
        json!({"schema_version":1,"order":"runtime-ORDER-000002","outcome":"CANCELLED","collateral":{"schema_version":1,"kind":"NONE","instruction":null,"close_allocation":null}}),
    );
    candidate.apply(&terminal).unwrap();
}
