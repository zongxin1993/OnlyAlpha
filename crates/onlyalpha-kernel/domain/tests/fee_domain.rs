use onlyalpha_domain::{
    base::OnlyDomainModel,
    fee::{
        OnlyBrokerFeeAccountScope, OnlyBrokerFeeAccountScopeInput, OnlyBrokerFeeAccountScopeType,
        OnlyFeeSubject, OnlyFeeSubjectInput,
    },
};
#[test]
fn fee_subjects_and_broker_scope_have_exact_identity() {
    let subject = OnlyFeeSubject::new(OnlyFeeSubjectInput {
        runtime_id: "r".parse().unwrap(),
        account_id: "a".parse().unwrap(),
        cluster_id: "c".parse().unwrap(),
        order_id: "o".parse().unwrap(),
        instrument_id: "A.X".parse().unwrap(),
    })
    .unwrap();
    assert_eq!(
        OnlyFeeSubject::from_json(&subject.to_json().unwrap()).unwrap(),
        subject
    );
    assert!(
        OnlyBrokerFeeAccountScope::new(OnlyBrokerFeeAccountScopeInput {
            scope_type: OnlyBrokerFeeAccountScopeType::ExactAccount,
            account_id: None
        })
        .is_err()
    );
}

#[test]
fn fee_identity_digests_and_canonical_sort_keys_are_explicit() {
    use onlyalpha_domain::fee::{
        OnlyFeeAuthority, OnlyFeeCalculationScope, OnlyFeeComponentIdentity,
        OnlyFeeComponentIdentityInput, OnlyFeeEconomicDirection, OnlyFeeResolutionPolicy,
        OnlyFeeScheduleAuthority, OnlyFeeScheduleIdentity, OnlyFeeScheduleIdentityInput,
        OnlyFeeType, OnlyMarketFeePackIdentity, OnlyMarketFeePackIdentityInput,
    };
    let fields = OnlyFeeScheduleIdentityInput {
        authority: OnlyFeeScheduleAuthority::Market,
        schedule_id: "fees".into(),
        version: "1".into(),
        fingerprint: "a".repeat(64),
    };
    let identity = OnlyFeeScheduleIdentity::new(fields.clone()).unwrap();
    assert_eq!(
        OnlyFeeScheduleIdentity::from_json(&identity.to_json().unwrap()).unwrap(),
        identity
    );
    let mut invalid = fields;
    invalid.fingerprint = "A".repeat(64);
    assert!(OnlyFeeScheduleIdentity::new(invalid).is_err());
    let pack = OnlyMarketFeePackIdentity::new(OnlyMarketFeePackIdentityInput {
        pack_id: "pack".into(),
        pack_version: "1".into(),
        fingerprint: "a".repeat(64),
    })
    .unwrap();
    assert_eq!(
        pack.canonical_identity(),
        serde_json::json!({"pack_id":"pack","pack_version":"1","fingerprint":"a".repeat(64)})
    );
    let component = OnlyFeeComponentIdentity::new(OnlyFeeComponentIdentityInput {
        fee_type: OnlyFeeType::MakerFee,
        authority: OnlyFeeAuthority::Venue,
        source_id: "source".into(),
        schedule_id: "fees".into(),
        schedule_version: "1".into(),
        schedule_fingerprint: "a".repeat(64),
        rule_id: "rule".into(),
        rule_fingerprint: "b".repeat(64),
        calculation_scope: OnlyFeeCalculationScope::Fill,
        resolution_policy: OnlyFeeResolutionPolicy::FillEffective,
        economic_direction: OnlyFeeEconomicDirection::Charge,
    })
    .unwrap();
    assert_eq!(
        component.sort_key(),
        [
            "MAKER_FEE",
            "VENUE",
            "source",
            "fees",
            "1",
            "rule",
            "FILL",
            "FILL_EFFECTIVE",
            "CHARGE"
        ]
    );
}
