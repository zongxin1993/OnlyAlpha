//! Independent native producers for retained hermetic Order/Fee fixture records.
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::{OnlyOffset, OnlyOrderSide, OnlyOrderType, OnlyTimeInForce},
    execution::{OnlyOrderRequest, OnlyOrderRequestInput, OnlyOrderSnapshot},
    value::{OnlyPrice, OnlyQuantity},
};
use onlyalpha_order::{ApplyResult, Manager};
use serde_json::{Value, json};

// Hermetic zero-fee model for the frozen test Order; not a market policy or
// Product writer. The original fixture remains an independent expected record.
fn native_zero_fee_contract(
    order: &onlyalpha_domain::execution::OnlyOrderSnapshot,
    at: u64,
) -> Value {
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        enums::OnlyCurrencyType,
        fee::*,
        numeric::{only_multiply, only_quantize},
        time::OnlyTimestamp,
        value::{OnlyCurrency, OnlyMoney},
    };
    let currency = OnlyCurrency::new("CNY", 2, OnlyCurrencyType::Fiat).unwrap();
    let digest = "0".repeat(64);
    let scope = OnlyOrderFeeApplicabilityScopeIdentity::create(
        OnlyOrderFeeApplicabilityScopeIdentityInput {
            market_product_id: "TEST_ZERO_FEE".into(),
            market: "TEST".into(),
            venue: "TEST".into(),
            instrument_class: "CASH".into(),
            broker_id: "TEST_BROKER".into(),
            account_id: order.account_id().clone(),
            instrument_id: order.instrument_id().clone(),
            charge_currency: currency.clone(),
            fingerprint: String::new(),
        },
    )
    .unwrap();
    let binding = OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
        runtime_id: order.runtime_id().clone(),
        account_id: order.account_id().clone(),
        cluster_id: order.cluster_id().clone(),
        order_id: order.order_id().clone(),
        instrument_id: order.instrument_id().clone(),
        market_product_id: "TEST_ZERO_FEE".into(),
        market_product_version: "1".into(),
        market_fee_pack: OnlyMarketFeePackIdentity::new(OnlyMarketFeePackIdentityInput {
            pack_id: "TEST_ZERO_MARKET_FEES".into(),
            pack_version: "1".into(),
            fingerprint: digest.clone(),
        })
        .unwrap(),
        broker_fee_contract: OnlyBrokerFeeContractIdentity::new(
            OnlyBrokerFeeContractIdentityInput {
                contract_id: "TEST_ZERO_BROKER_FEES".into(),
                contract_version: "1".into(),
                broker_id: "TEST_BROKER".into(),
                account_scope: OnlyBrokerFeeAccountScope::new(OnlyBrokerFeeAccountScopeInput {
                    scope_type: OnlyBrokerFeeAccountScopeType::ExactAccount,
                    account_id: Some(order.account_id().clone()),
                })
                .unwrap(),
                fingerprint: digest.clone(),
            },
        )
        .unwrap(),
        applicability_scope: scope,
        order_fixed_schedules: vec![],
        fill_effective_families: vec![],
        charge_currency: currency.clone(),
        bound_at: OnlyTimestamp::from_unix_nanos(at.into()),
        fingerprint: String::new(),
    })
    .unwrap();
    let zero = OnlyMoney::new("0".parse().unwrap(), currency.clone()).unwrap();
    let assessment = OnlyFeeAssessment::new(OnlyFeeAssessmentInput {
        assessment_id: "test-zero-fee".into(),
        subject: OnlyFeeSubject::new(OnlyFeeSubjectInput {
            runtime_id: order.runtime_id().clone(),
            account_id: order.account_id().clone(),
            cluster_id: order.cluster_id().clone(),
            order_id: order.order_id().clone(),
            instrument_id: order.instrument_id().clone(),
        })
        .unwrap(),
        trade_id: None,
        components: vec![],
        total_charges: zero.clone(),
        total_rebates: zero.clone(),
        policy_fingerprint: digest.clone(),
        resolution_fingerprint: digest.clone(),
        local_finality: OnlyLocalFeeFinality::ModelConfirmed,
        binding: binding.clone(),
    })
    .unwrap();
    let estimate = OnlyOrderFeeEstimate::new(OnlyOrderFeeEstimateInput {
        expected: assessment.clone(),
        maximum: assessment,
        reservation_charge: zero.clone(),
        estimated_rebate: zero.clone(),
        assumptions_fingerprint: digest.clone(),
    })
    .unwrap();
    let amount = order.price().as_ref().map_or_else(
        || "0".parse().unwrap(),
        |price| only_multiply(price.value(), order.quantity().value()).unwrap(),
    );
    let principal = OnlyMoney::new(
        only_quantize(&amount, &"0.01".parse().unwrap()).unwrap(),
        currency,
    )
    .unwrap();
    let funding = OnlyOrderFundingPlan::new(OnlyOrderFundingPlanInput {
        order_id: order.order_id().clone(),
        principal_reservation: principal.clone(),
        fee_reservation: zero,
        total_reservation: principal,
        binding_fingerprint: binding.fingerprint().clone(),
        estimate_fingerprint: digest,
    })
    .unwrap();
    json!({"binding":binding.to_record(),"estimate":estimate.to_record(),"funding":funding.to_record()})
}

fn manager() -> Manager {
    Manager::new(json!({"schema_version":1,"engine_id":"engine","runtime_id":"runtime","gateway_id":"gateway","generation":"a".repeat(64)})).unwrap()
}
fn request(ordinal: u64, side: OnlyOrderSide, price: &str) -> OnlyOrderRequest {
    OnlyOrderRequest::new(OnlyOrderRequestInput {
        request_id: format!("request-{ordinal}").parse().unwrap(),
        instrument_id: "600000.XSHG".parse().unwrap(),
        side,
        order_type: OnlyOrderType::Limit,
        quantity: OnlyQuantity::new("4".parse().unwrap(), 0).unwrap(),
        time_in_force: OnlyTimeInForce::Day,
        account_id: None,
        offset: OnlyOffset::None,
        price: Some(OnlyPrice::new(price.parse().unwrap(), 2).unwrap()),
        stop_price: None,
        expire_time: None,
        tags: vec![],
        metadata: Default::default(),
        execution_intent: None,
    })
    .unwrap()
}
fn create(
    manager: &mut Manager,
    request: &OnlyOrderRequest,
    cluster: &str,
    at: u64,
) -> OnlyOrderSnapshot {
    let result = manager.apply(&json!({"schema_version":1,"op":"CREATE","cluster_id":cluster,"account_id":"account","request":request.to_record(),"cause":"b".repeat(64),"at":at})).unwrap();
    assert_eq!(result.result, ApplyResult::Applied);
    result.snapshot.unwrap()
}
#[test]
fn frozen_order_fee_fixtures_match_native_owners() {
    let mut m = manager();
    let first_request = request(1, OnlyOrderSide::Buy, "10.00");
    let first = create(&mut m, &first_request, "cluster", 1);
    let second = create(
        &mut m,
        &request(2, OnlyOrderSide::Buy, "10.00"),
        "cluster",
        1,
    );
    let order = json!({"request":first_request.to_record(),"fee_contract":native_zero_fee_contract(&first,1),"second_fee_contract":native_zero_fee_contract(&second,1)});
    assert_eq!(
        include_str!("../../../test-data/order/domain-inputs.json"),
        format!("{order}\n")
    );

    let mut m = manager();
    let first = create(&mut m, &first_request, "cluster", 1);
    let close = create(
        &mut m,
        &request(2, OnlyOrderSide::Sell, "12.00"),
        "cluster",
        5,
    );
    let execution = json!({"request":first_request.to_record(),"fee_contract":native_zero_fee_contract(&first,1),"second_fee_contract":native_zero_fee_contract(&close,5)});
    assert_eq!(
        include_str!("../../../test-data/execution/domain-inputs.json"),
        format!("{execution}\n")
    );

    let mut broker_request = first_request.input();
    broker_request.account_id = Some("account".parse().unwrap());
    let broker = json!({"request":OnlyOrderRequest::new(broker_request).unwrap().to_record()});
    assert_eq!(
        serde_json::from_str::<Value>(include_str!("../../../test-data/broker/domain-inputs.json"))
            .unwrap(),
        broker
    );

    let mut m = manager();
    create(&mut m, &first_request, "cluster", 1);
    let second = create(
        &mut m,
        &request(2, OnlyOrderSide::Buy, "10.00"),
        "cluster",
        4,
    );
    let third = create(
        &mut m,
        &request(3, OnlyOrderSide::Sell, "12.00"),
        "cluster",
        7,
    );
    let contracts =
        json!({"2":native_zero_fee_contract(&second,4),"3":native_zero_fee_contract(&third,7)});
    let margin: Value =
        serde_json::from_str(include_str!("../../../test-data/margin/common-v1.json")).unwrap();
    assert_eq!(margin["fee_contracts"], contracts);

    let mut m = manager();
    create(&mut m, &first_request, "cluster", 1);
    let second = create(&mut m, &request(2, OnlyOrderSide::Buy, "10.00"), "other", 4);
    let valuation: Value = serde_json::from_str(include_str!(
        "../../../test-data/position/valuation-order-contract.json"
    ))
    .unwrap();
    assert_eq!(native_zero_fee_contract(&second, 4), valuation);
    assert_ne!(native_zero_fee_contract(&second, 5), valuation);
    println!("NATIVE_ORDER_FIXTURES: PASS");
}
