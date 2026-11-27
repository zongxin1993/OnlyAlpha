use onlyalpha_domain::enums::{OnlyOrderSide, OnlyOrderType};
use onlyalpha_operators::algebra::Decimal;
use onlyalpha_wasm_host::{
    MarketRuleDecision, MarketRuleInput, ResourceBudget, WasmPluginManager, sha256_hex,
};

// Frozen from compile_market_rule_component(false, false) so each host consumes identical bytes.
const COMPONENT: &[u8] = include_bytes!("fixtures/settled_quantity.wasm");
const SHA256: &str = "d4dcece09daa3aa912b355e36b88e8de45b94a3c82e39f82b3ad175a6d44cbce";

#[test]
fn frozen_market_rule_returns_identical_decisions() {
    assert_eq!(sha256_hex(COMPONENT), SHA256);
    let manager = WasmPluginManager::new(ResourceBudget::default()).unwrap();
    let rule = manager
        .load_market_rule("market.cn_ashare", COMPONENT, SHA256, None)
        .unwrap();
    let buy = MarketRuleInput {
        trading_day: "2026-11-26".into(),
        instrument_id: "600519.SH".into(),
        side: OnlyOrderSide::Buy,
        order_type: OnlyOrderType::Limit,
        quantity: Decimal::from(100),
        price: Some("1500.125".parse().unwrap()),
        reference_price: Some(Decimal::from(1490)),
        settled_quantity: Decimal::from(0),
        rule_version: "cn-a-share-v1".into(),
    };
    let allowed = MarketRuleDecision {
        allowed: true,
        reject_code: None,
        normalized_quantity: Some(Decimal::from(100)),
        normalized_price: Some("1500.125".parse().unwrap()),
        fee_estimate: Some("0.01".parse().unwrap()),
    };
    assert_eq!(rule.validate_order(&buy).unwrap().value, allowed);
    let sell = MarketRuleInput {
        side: OnlyOrderSide::Sell,
        ..buy
    };
    let rejected = MarketRuleDecision {
        allowed: false,
        reject_code: Some("T_PLUS_1_INSUFFICIENT_SETTLED".into()),
        normalized_quantity: None,
        normalized_price: None,
        fee_estimate: None,
    };
    assert_eq!(rule.validate_order(&sell).unwrap().value, rejected);
}
