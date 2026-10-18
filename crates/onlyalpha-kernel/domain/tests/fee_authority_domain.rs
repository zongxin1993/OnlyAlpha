use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyCurrencyType,
    fee::*,
    time::OnlyTimestamp,
    value::{OnlyCurrency, OnlyMoney},
};
use serde_json::Value;
fn money(value: &str) -> OnlyMoney {
    OnlyMoney::new(
        value.parse().unwrap(),
        OnlyCurrency::new("USD", 2, OnlyCurrencyType::Fiat).unwrap(),
    )
    .unwrap()
}
fn binding(runtime: &str) -> OnlyOrderFeePolicyBinding {
    let scope = OnlyOrderFeeApplicabilityScopeIdentity::create(
        OnlyOrderFeeApplicabilityScopeIdentityInput {
            market_product_id: "product".into(),
            market: "test".into(),
            venue: "X".into(),
            instrument_class: "asset".into(),
            broker_id: "broker".into(),
            account_id: "a".parse().unwrap(),
            instrument_id: "A.X".parse().unwrap(),
            charge_currency: money("0").currency().clone(),
            fingerprint: String::new(),
        },
    )
    .unwrap();
    OnlyOrderFeePolicyBinding::create(OnlyOrderFeePolicyBindingInput {
        runtime_id: runtime.parse().unwrap(),
        account_id: "a".parse().unwrap(),
        cluster_id: "c".parse().unwrap(),
        order_id: "o".parse().unwrap(),
        instrument_id: "A.X".parse().unwrap(),
        market_product_id: "product".into(),
        market_product_version: "1".into(),
        market_fee_pack: OnlyMarketFeePackIdentity::new(OnlyMarketFeePackIdentityInput {
            pack_id: "pack".into(),
            pack_version: "1".into(),
            fingerprint: "a".repeat(64),
        })
        .unwrap(),
        broker_fee_contract: OnlyBrokerFeeContractIdentity::new(
            OnlyBrokerFeeContractIdentityInput {
                contract_id: "contract".into(),
                contract_version: "1".into(),
                broker_id: "broker".into(),
                account_scope: OnlyBrokerFeeAccountScope::new(OnlyBrokerFeeAccountScopeInput {
                    scope_type: OnlyBrokerFeeAccountScopeType::AllAccounts,
                    account_id: None,
                })
                .unwrap(),
                fingerprint: "b".repeat(64),
            },
        )
        .unwrap(),
        applicability_scope: scope,
        order_fixed_schedules: vec![],
        fill_effective_families: vec![],
        charge_currency: money("0").currency().clone(),
        bound_at: OnlyTimestamp::from_unix_nanos(0.into()),
        fingerprint: String::new(),
    })
    .unwrap()
}
fn assessment(runtime: &str) -> OnlyFeeAssessment {
    OnlyFeeAssessment::new(OnlyFeeAssessmentInput {
        assessment_id: "assessment".into(),
        subject: OnlyFeeSubject::new(OnlyFeeSubjectInput {
            runtime_id: runtime.parse().unwrap(),
            account_id: "a".parse().unwrap(),
            cluster_id: "c".parse().unwrap(),
            order_id: "o".parse().unwrap(),
            instrument_id: "A.X".parse().unwrap(),
        })
        .unwrap(),
        trade_id: None,
        components: vec![],
        total_charges: money("0.00"),
        total_rebates: money("0.00"),
        policy_fingerprint: "a".repeat(64),
        resolution_fingerprint: "b".repeat(64),
        local_finality: OnlyLocalFeeFinality::Estimated,
        binding: binding(runtime),
    })
    .unwrap()
}
#[test]
fn canonical_fee_fingerprints_match_independent_preimages_and_detect_tampering() {
    for line in include_str!("../../../../test-data/domain/fee-authority-v1.jsonl").lines() {
        let row: Value = serde_json::from_str(line).unwrap();
        assert_eq!(
            only_fee_fingerprint(&row["payload"]).unwrap(),
            row["sha256"].as_str().unwrap()
        );
        assert_eq!(
            row["payload"].to_string(),
            row["canonical_json"].as_str().unwrap()
        );
    }
    let bound = binding("r");
    assert_eq!(
        bound.applicability_scope().fingerprint(),
        "ce4166f857f7c0190523193a2c1d234cf38868602db8fb9df0df283102dc381c"
    );
    assert_eq!(
        OnlyOrderFeePolicyBinding::from_json(&bound.to_json().unwrap()).unwrap(),
        bound
    );
    let mut corrupt = bound.to_record();
    corrupt["runtime_id"]["value"] = "foreign".into();
    assert!(OnlyOrderFeePolicyBinding::from_record(&corrupt).is_err());
}
#[test]
fn fee_assessments_estimates_and_reservations_have_one_bound_scope() {
    let valid = assessment("r");
    assert_eq!(
        OnlyFeeAssessment::from_record(&valid.to_record()).unwrap(),
        valid
    );
    let mut mismatch = valid.input();
    mismatch.subject = assessment("other").subject().clone();
    assert!(OnlyFeeAssessment::new(mismatch).is_err());
    let mut mismatch = valid.input();
    mismatch.total_charges = money("1.00");
    assert!(OnlyFeeAssessment::new(mismatch).is_err());
    let fields = OnlyOrderFeeEstimateInput {
        expected: valid.clone(),
        maximum: valid.clone(),
        reservation_charge: money("0.00"),
        estimated_rebate: money("0.00"),
        assumptions_fingerprint: "c".repeat(64),
    };
    assert!(OnlyOrderFeeEstimate::new(fields.clone()).is_ok());
    let mut mismatch = fields;
    mismatch.maximum = assessment("other");
    assert!(OnlyOrderFeeEstimate::new(mismatch).is_err());
    let fields = OnlyOrderFundingPlanInput {
        order_id: "o".parse().unwrap(),
        principal_reservation: money("10.00"),
        fee_reservation: money("0.12"),
        total_reservation: money("10.12"),
        binding_fingerprint: valid.binding().fingerprint().clone(),
        estimate_fingerprint: "c".repeat(64),
    };
    assert!(OnlyOrderFundingPlan::new(fields.clone()).is_ok());
    let mut mismatch = fields;
    mismatch.total_reservation = money("10.13");
    assert!(OnlyOrderFundingPlan::new(mismatch).is_err());
}
