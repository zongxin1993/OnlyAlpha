use onlyalpha_domain::{base::OnlyDomainModel, enums::*, instrument::*, value::*};
fn spec() -> OnlyInstrumentSpecification {
    let usd = OnlyCurrency::new("USD", 2, OnlyCurrencyType::Fiat).unwrap();
    OnlyInstrumentSpecification::new(OnlyInstrumentSpecificationInput {
        instrument_id: "A.X".parse().unwrap(),
        raw_symbol: "A".parse().unwrap(),
        asset_class: OnlyAssetClass::Equity,
        instrument_type: OnlyInstrumentType::Equity,
        market_type: OnlyMarketType::Cash,
        quote_currency: usd.clone(),
        settlement_currency: usd,
        price_precision: 2,
        quantity_precision: 0,
        tick_size: OnlyPrice::new("0.05".parse().unwrap(), 2).unwrap(),
        step_size: OnlyQuantity::new("1".parse().unwrap(), 0).unwrap(),
        contract_multiplier: OnlyMultiplier::new("1".parse().unwrap(), 0).unwrap(),
        base_currency: None,
        margin_currency: None,
        minimum_quantity: None,
        maximum_quantity: None,
        minimum_notional: None,
        maximum_notional: None,
        minimum_price: None,
        maximum_price: None,
        lot_size: None,
        instrument_version: 1.into(),
        activation_time: None,
        effective_from: None,
        effective_to: None,
        timezone: "UTC".into(),
        trading_calendar_id: None,
        session_profile_id: None,
        status: OnlySecurityStatus::Active,
    })
    .unwrap()
}
#[test]
fn typed_instruments_keep_flat_schema_and_exact_increment_rules() {
    let instrument = OnlyInstrument::new(spec(), OnlyInstrumentKind::Equity).unwrap();
    assert_eq!(instrument.to_record()["model_type"], "OnlyEquity");
    assert_eq!(
        OnlyInstrument::from_record(&instrument.to_record()).unwrap(),
        instrument
    );
    let price = OnlyPrice::new("1.03".parse().unwrap(), 2).unwrap();
    assert!(!instrument.specification().validates_price(&price).unwrap());
    assert_eq!(
        instrument
            .specification()
            .quantize_price(
                &price,
                onlyalpha_domain::numeric::OnlyRoundingMode::HalfEven
            )
            .unwrap()
            .value()
            .to_string(),
        "1.05"
    );
    let mut record = instrument.to_record();
    record["model_type"] = "UnknownInstrument".into();
    assert!(OnlyInstrument::from_record(&record).is_err());
    let mut fields = spec().input();
    fields.minimum_notional = Some(
        OnlyMoney::new(
            "1".parse().unwrap(),
            OnlyCurrency::new("CNY", 2, OnlyCurrencyType::Fiat).unwrap(),
        )
        .unwrap(),
    );
    assert!(OnlyInstrumentSpecification::new(fields).is_err());
}
#[test]
fn derivative_fields_are_required_and_never_discarded() {
    let mut fields = spec().input();
    fields.instrument_type = OnlyInstrumentType::Future;
    fields.margin_currency = Some(fields.quote_currency.clone());
    let instrument = OnlyInstrument::new(
        OnlyInstrumentSpecification::new(fields).unwrap(),
        OnlyInstrumentKind::Future(OnlyFutureTerms {
            underlying: "B.X".parse().unwrap(),
            expiration_time: "2025-03-01T00:00:00Z".parse().unwrap(),
            last_trade_time: "2025-02-28T00:00:00Z".parse().unwrap(),
            settlement_type: OnlySettlementType::Cash,
            contract_type: OnlyContractType::Linear,
            initial_margin_rate: None,
            maintenance_margin_rate: None,
        }),
    )
    .unwrap();
    assert_eq!(
        OnlyInstrument::from_record(&instrument.to_record()).unwrap(),
        instrument
    );
    let mut record = instrument.to_record();
    record["model_type"] = "OnlyInstrument".into();
    assert!(OnlyInstrument::from_record(&record).is_err());
    let mut record = instrument.to_record();
    record.as_object_mut().unwrap().remove("expiration_time");
    assert!(OnlyInstrument::from_record(&record).is_err());
}
#[test]
fn catalogs_resolve_one_effective_version_and_pnl_uses_contract_semantics() {
    use onlyalpha_domain::{account::OnlyPnLCalculator, catalog::OnlyInstrumentCatalog};
    let instrument = OnlyInstrument::new(spec(), OnlyInstrumentKind::Equity).unwrap();
    let catalog = OnlyInstrumentCatalog::new(vec![instrument.clone()]).unwrap();
    assert_eq!(
        catalog
            .resolve(
                instrument.specification().instrument_id(),
                "2025-01-01T00:00:00Z".parse().unwrap()
            )
            .unwrap(),
        &instrument
    );
    assert!(OnlyInstrumentCatalog::new(vec![instrument.clone(), instrument.clone()]).is_err());
    assert_eq!(
        OnlyInstrumentCatalog::from_record(&catalog.to_record()).unwrap(),
        catalog
    );
    let quantity = OnlyQuantity::new("2".parse().unwrap(), 0).unwrap();
    let entry = OnlyPrice::new("10.00".parse().unwrap(), 2).unwrap();
    let current = OnlyPrice::new("12.50".parse().unwrap(), 2).unwrap();
    let pnl = OnlyPnLCalculator::unrealized(
        &instrument,
        OnlyPositionDirection::Long,
        &quantity,
        &entry,
        &current,
    )
    .unwrap();
    assert_eq!(pnl.amount().to_string(), "5.00");
    let pnl = OnlyPnLCalculator::unrealized(
        &instrument,
        OnlyPositionDirection::Short,
        &quantity,
        &entry,
        &current,
    )
    .unwrap();
    assert_eq!(pnl.amount().to_string(), "-5.00");
}
#[test]
fn independent_records_cover_every_builtin_instrument_variant() {
    for line in include_str!("../../../../test-data/domain/instrument-records-v2.jsonl").lines() {
        let row: serde_json::Value = serde_json::from_str(line).unwrap();
        let result = OnlyInstrument::from_record(&row["record"]);
        if row.get("error").is_some() {
            assert!(result.is_err(), "{}", row["id"]);
        } else {
            assert_eq!(result.unwrap().to_record(), row["record"], "{}", row["id"]);
        }
    }
}

#[test]
fn pnl_never_relabels_currency_or_treats_flat_as_short() {
    use onlyalpha_domain::account::OnlyPnLCalculator;
    let quantity = OnlyQuantity::new("2".parse().unwrap(), 0).unwrap();
    let entry = OnlyPrice::new("10.00".parse().unwrap(), 2).unwrap();
    let current = OnlyPrice::new("12.50".parse().unwrap(), 2).unwrap();
    let mut fields = spec().input();
    fields.settlement_currency = OnlyCurrency::new("CNY", 2, OnlyCurrencyType::Fiat).unwrap();
    let cross = OnlyInstrument::new(
        OnlyInstrumentSpecification::new(fields).unwrap(),
        OnlyInstrumentKind::Equity,
    )
    .unwrap();
    assert!(
        OnlyPnLCalculator::unrealized(
            &cross,
            OnlyPositionDirection::Long,
            &quantity,
            &entry,
            &current
        )
        .is_err()
    );
    let instrument = OnlyInstrument::new(spec(), OnlyInstrumentKind::Equity).unwrap();
    assert!(
        OnlyPnLCalculator::unrealized(
            &instrument,
            OnlyPositionDirection::Flat,
            &quantity,
            &entry,
            &current
        )
        .is_err()
    );
    let zero = OnlyQuantity::new("0".parse().unwrap(), 0).unwrap();
    let result = OnlyPnLCalculator::unrealized(
        &instrument,
        OnlyPositionDirection::Flat,
        &zero,
        &entry,
        &current,
    )
    .unwrap();
    assert_eq!(result.amount().to_string(), "0.00");
}
