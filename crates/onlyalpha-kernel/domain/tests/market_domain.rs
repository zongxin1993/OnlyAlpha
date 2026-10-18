use onlyalpha_domain::{base::OnlyDomainModel, market::*, trading::OnlyReferencePriceKind};
#[test]
fn reference_facts_preserve_lineage_and_total_order() {
    let input = OnlyReferencePriceFactInput {
        fact_id: "fact".into(),
        instrument_id: "A.X".parse().unwrap(),
        kind: OnlyReferencePriceKind::Index,
        value: onlyalpha_domain::value::OnlyPrice::new("10.00".parse().unwrap(), 2).unwrap(),
        ts_event: "2025-01-01T00:00:00Z".parse().unwrap(),
        ts_init: "2025-01-01T00:00:00Z".parse().unwrap(),
        source: "source".into(),
        source_sequence: 2.into(),
        data_version: "v1".into(),
        revision: 0.into(),
        provider_evidence_id: None,
        source_record_hash: None,
    };
    let fact = OnlyReferencePriceFact::new(input).unwrap();
    assert_eq!(fact.stable_order().1, 10);
    assert_eq!(
        OnlyReferencePriceFact::from_record(&fact.to_record()).unwrap(),
        fact
    );
    let mut fields = fact.input();
    fields.provider_evidence_id = Some("evidence".into());
    assert!(OnlyReferencePriceFact::new(fields).is_err());
    let mut fields = fact.input();
    fields.ts_init = "2024-01-01T00:00:00Z".parse().unwrap();
    assert!(OnlyReferencePriceFact::new(fields).is_err());
}
#[test]
fn order_book_keeps_strict_sort_and_crossing_semantics() {
    use onlyalpha_domain::{
        enums::OnlyBookType,
        value::{OnlyPrice, OnlyQuantity},
    };
    let level = |price: &str| {
        OnlyOrderBookLevel::new(OnlyOrderBookLevelInput {
            price: OnlyPrice::new(price.parse().unwrap(), 2).unwrap(),
            quantity: OnlyQuantity::new("1".parse().unwrap(), 0).unwrap(),
            order_count: None,
        })
        .unwrap()
    };
    let book = OnlyOrderBook::new(OnlyOrderBookInput {
        instrument_id: "A.X".parse().unwrap(),
        book_type: OnlyBookType::L2,
        bids: vec![level("11.00"), level("10.00")],
        asks: vec![level("10.00"), level("12.00")],
        sequence: 1.into(),
        event_time: "2025-01-01T00:00:00Z".parse().unwrap(),
    })
    .unwrap();
    assert!(book.is_crossed());
    let mut input = book.input();
    input.bids.reverse();
    assert!(OnlyOrderBook::new(input).is_err());
    assert_eq!(OnlyOrderBook::from_record(&book.to_record()).unwrap(), book);
}
#[test]
fn bar_semantics_and_trade_inputs_keep_the_current_explicit_wire_versions() {
    let semantic = OnlyBarSemantic::fixed_duration(1.into(), None).unwrap();
    assert!(semantic.is_aligned());
    assert_eq!(semantic.window_minutes().unwrap(), &1.into());
    assert_eq!(
        OnlyBarSemantic::from_record(&semantic.to_record()).unwrap(),
        semantic
    );
    let trade = OnlyTradeInputType::new("A.X".parse().unwrap());
    assert_eq!(trade.to_record()["instrument_id"], "A.X");
    assert_eq!(
        OnlyTradeInputType::from_record(&trade.to_record()).unwrap(),
        trade
    );
    for (kind, extra) in [
        ("TICK_COUNT", serde_json::json!({"count":100})),
        ("VOLUME", serde_json::json!({"quantity":"1E+1"})),
        ("VALUE", serde_json::json!({"value":"1E+3"})),
    ] {
        let mut formation = extra;
        formation["schema_version"] = if kind == "TICK_COUNT" { 1 } else { 2 }.into();
        formation["kind"] = kind.into();
        let record = serde_json::json!({"schema_version":3,"formation":formation,"price_type":"LAST","adjustment_policy":"RAW"});
        assert_eq!(
            OnlyBarSemantic::from_record(&record).unwrap().to_record(),
            record
        );
    }
    let mut invalid = semantic.to_record();
    invalid["formation"]["stride_minutes"] = 0.into();
    assert!(OnlyBarSemantic::from_record(&invalid).is_err());
}

#[test]
fn shared_bar_identity_uses_canonical_records_and_explicit_version() {
    for line in include_str!("../../../../test-data/domain/bar-identity-v3.jsonl").lines() {
        let row: serde_json::Value = serde_json::from_str(line).unwrap();
        let mut input = row["record"].clone();
        input["formation"][row["field"].as_str().unwrap()] = row["input"].clone();
        let formation = if row["kind"] == "VOLUME" {
            OnlyBarFormation::Volume(
                OnlyVolumeBarFormation::new(OnlyVolumeBarFormationInput {
                    quantity: row["input"].as_str().unwrap().parse().unwrap(),
                    kind: OnlyBarFormationKind::Volume,
                })
                .unwrap(),
            )
        } else {
            OnlyBarFormation::Value(
                OnlyValueBarFormation::new(OnlyValueBarFormationInput {
                    value: row["input"].as_str().unwrap().parse().unwrap(),
                    kind: OnlyBarFormationKind::Value,
                })
                .unwrap(),
            )
        };
        let semantic = OnlyBarSemantic::new(OnlyBarSemanticInput {
            formation,
            price_type: onlyalpha_domain::enums::OnlyPriceType::Last,
            adjustment_policy: onlyalpha_domain::enums::OnlyAdjustmentType::Raw,
        })
        .unwrap();
        assert_eq!(
            OnlyBarSemantic::from_record(&input).is_ok(),
            input == row["record"]
        );
        assert_eq!(
            OnlyBarSemantic::from_record(&row["record"]).unwrap(),
            semantic
        );
        assert_eq!(semantic.to_record(), row["record"], "{}", row["id"]);
        assert_eq!(
            semantic.fingerprint().unwrap(),
            row["fingerprint"].as_str().unwrap(),
            "{}",
            row["id"]
        );
        input["schema_version"] = 2.into();
        assert!(OnlyBarSemantic::from_record(&input).is_err());
        let mut input = row["record"].clone();
        input["formation"]["schema_version"] = 1.into();
        assert!(OnlyBarSemantic::from_record(&input).is_err());
    }
}
