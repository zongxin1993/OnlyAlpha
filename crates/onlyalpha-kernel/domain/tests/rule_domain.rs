use onlyalpha_domain::{
    enums::OnlyOrderSide,
    market_rules::{OnlyLotSizeRule, OnlyLotSizeRuleInput},
    value::OnlyQuantity,
};
#[test]
fn market_lot_rules_use_exact_arithmetic() {
    let rule = OnlyLotSizeRule::new(OnlyLotSizeRuleInput {
        buy_increment: "100".parse().unwrap(),
        sell_increment: "1".parse().unwrap(),
    })
    .unwrap();
    let quantity = OnlyQuantity::new("101".parse().unwrap(), 0).unwrap();
    assert!(!rule.validates(OnlyOrderSide::Buy, &quantity).unwrap());
    assert!(rule.validates(OnlyOrderSide::Sell, &quantity).unwrap());
}

#[test]
fn ladders_limits_and_settlement_rules_are_typed_and_exact() {
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        market_rules::{
            OnlyPriceLadder, OnlyPriceLadderInput, OnlyPriceLimitRule, OnlyPriceLimitRuleInput,
            OnlySettlementRule, OnlySettlementRuleInput, OnlyTickScheme, OnlyTickSchemeInput,
        },
        value::OnlyPrice,
    };
    let ladder = OnlyPriceLadder::new(OnlyPriceLadderInput {
        steps: vec![
            (Some("10".parse().unwrap()), "0.01".parse().unwrap()),
            (None, "0.05".parse().unwrap()),
        ],
    })
    .unwrap();
    let price = OnlyPrice::new("11.03".parse().unwrap(), 2).unwrap();
    assert_eq!(ladder.increment_for(&price).unwrap().to_string(), "0.05");
    let tick = OnlyTickScheme::new(OnlyTickSchemeInput {
        ladder: ladder.clone(),
    })
    .unwrap();
    assert!(!tick.validates(&price).unwrap());
    assert!(
        OnlyPriceLadder::from_record(&serde_json::json!({"schema_version":1,"steps":[["0.1"]]}))
            .is_err()
    );
    let limit = OnlyPriceLimitRule::new(OnlyPriceLimitRuleInput {
        lower: None,
        upper: Some(OnlyPrice::new("10".parse().unwrap(), 0).unwrap()),
    })
    .unwrap();
    assert!(!limit.validates(&price));
    assert!(
        OnlySettlementRule::new(OnlySettlementRuleInput {
            settlement_days: "-1".parse().unwrap(),
            allow_same_day_sell: true,
            allowed_offsets: vec![]
        })
        .is_err()
    );
}
#[test]
fn effective_fee_schedule_rounds_down_at_currency_boundary() {
    use onlyalpha_domain::{
        base::OnlyDomainModel,
        enums::{OnlyCurrencyType, OnlyLiquiditySide},
        market_rules::{
            OnlyFeeSchedule, OnlyFeeScheduleCatalog, OnlyFeeScheduleCatalogInput,
            OnlyFeeScheduleInput,
        },
        value::{OnlyCurrency, OnlyMoney, OnlyRate},
    };
    let currency = OnlyCurrency::new("USD", 2, OnlyCurrencyType::Fiat).unwrap();
    let schedule = OnlyFeeSchedule::new(OnlyFeeScheduleInput {
        schedule_id: "fees".into(),
        maker_rate: OnlyRate::new("0.00125".parse().unwrap(), 5).unwrap(),
        taker_rate: OnlyRate::new("0.0025".parse().unwrap(), 4).unwrap(),
        minimum_fee: OnlyMoney::new("0.00".parse().unwrap(), currency.clone()).unwrap(),
        effective_from: "2020-01-01T00:00:00Z".parse().unwrap(),
        effective_to: Some("2025-01-01T00:00:00Z".parse().unwrap()),
    })
    .unwrap();
    let notional = OnlyMoney::new("100.00".parse().unwrap(), currency).unwrap();
    assert_eq!(
        schedule
            .calculate(&notional, OnlyLiquiditySide::Maker)
            .unwrap()
            .amount()
            .to_string(),
        "0.12"
    );
    let as_of = "2024-01-01T00:00:00Z".parse().unwrap();
    let catalog = OnlyFeeScheduleCatalog::new(OnlyFeeScheduleCatalogInput {
        schedules: vec![schedule.clone()],
    })
    .unwrap();
    assert_eq!(catalog.resolve("fees", as_of).unwrap(), &schedule);
    let ambiguous = OnlyFeeScheduleCatalog::new(OnlyFeeScheduleCatalogInput {
        schedules: vec![schedule.clone(), schedule],
    })
    .unwrap();
    assert!(ambiguous.resolve("fees", as_of).is_err());
    assert_eq!(
        OnlyFeeScheduleCatalog::from_json(&catalog.to_json().unwrap()).unwrap(),
        catalog
    );
}
