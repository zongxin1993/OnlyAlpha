use onlyalpha_data_source_binance::{spot_facts, spot_normalize, usdm_facts};
use onlyalpha_domain::{base::OnlyDomainModel, trading::OnlyReferencePriceKind};
use serde_json::json;
fn instrument() -> onlyalpha_domain::instrument::OnlyInstrument {
    spot_normalize::instrument(&json!({"symbol":"BTCUSDT","baseAsset":"BTC","quoteAsset":"USDT","status":"TRADING","filters":[{"filterType":"PRICE_FILTER","tickSize":"0.01"},{"filterType":"LOT_SIZE","stepSize":"0.00001","minQty":"0.00001"}]})).unwrap()
}
#[test]
fn spot_trade_rest_and_websocket_share_exact_original_trade_identity() {
    let i = instrument();
    let rest = json!({"id":123,"price":"10.5000","qty":"1.23000","time":1001,"isBuyerMaker":true});
    let ws =
        json!({"e":"trade","s":"BTCUSDT","t":123,"p":"10.5000","q":"1.23000","T":1001,"m":true});
    let first = spot_facts::rest_trade(&rest, &i).unwrap();
    assert_eq!(first, spot_facts::websocket_trade(&ws, &i).unwrap());
    let record = first.to_record();
    assert_eq!(record["trade_id"]["value"], "123");
    assert_eq!(record["sequence"], 123);
    assert_eq!(record["source"], "BINANCE_SPOT");
    assert_eq!(record["price"]["value"], "10.5");
    assert_eq!(record["quantity"]["value"], "1.23");
    assert_eq!(record["aggressor_side"], "SELL");
    assert_eq!(record["ts_event"], "1970-01-01T00:00:01.001000Z");
    for (field, value) in [
        ("isBuyerMaker", json!(1)),
        ("id", json!(-1)),
        ("time", json!(true)),
        ("qty", json!("0")),
        ("price", json!("NaN")),
        ("price", json!("10.001")),
    ] {
        let mut raw = rest.clone();
        raw[field] = value;
        assert!(spot_facts::rest_trade(&raw, &i).is_err());
    }
    let mut wrong = ws;
    wrong["s"] = json!("ETHUSDT");
    assert!(spot_facts::websocket_trade(&wrong, &i).is_err());
}
#[test]
fn venue_reference_null_is_a_fact_and_average_price_is_not_reference() {
    let i = instrument();
    let raw = json!({"symbol":"BTCUSDT","referencePrice":null,"timestamp":1000});
    let fact = spot_facts::reference_price(&raw, &i).unwrap().to_record();
    assert_eq!(fact["reference_kind"], "VENUE_REFERENCE_PRICE");
    assert!(fact["price"].is_null());
    assert_eq!(fact["sequence"], 1000);
    assert!(
        spot_facts::reference_price(&json!({"mins":5,"price":"10.00","closeTime":1000}), &i)
            .is_err()
    );
    assert!(
        spot_facts::reference_price(
            &json!({"e":"referencePrice","s":"ETHUSDT","r":"10","t":1000}),
            &i
        )
        .is_err()
    );
    let a = spot_facts::reference_price(
        &json!({"e":"referencePrice","s":"BTCUSDT","r":"10.5000","t":1000}),
        &i,
    )
    .unwrap();
    let b = spot_facts::reference_price(
        &json!({"symbol":"BTCUSDT","referencePrice":"10.5000","timestamp":1000}),
        &i,
    )
    .unwrap();
    assert_eq!(a, b);
}
#[test]
fn funding_mark_and_rate_preserve_python_fact_ids_and_independent_hash_fixture() {
    let id = "BTCUSDT-PERP.BINANCE".parse().unwrap();
    let c = usdm_facts::Context {
        instrument_id: &id,
        data_version: "fixture-v2",
        source_sequence: 7,
        received_at: "2026-09-01T08:00:01Z".parse().unwrap(),
    };
    let raw = json!({"symbol":"BTCUSDT","fundingTime":1788249600000_i64,"fundingRate":"0.0001","markPrice":"60000.10","rateType":"REGULAR"});
    let (mark, rate) = usdm_facts::funding_boundary(&raw, &c).unwrap();
    assert_eq!(
        mark.fact_id(),
        "BINANCE-USDM-FUNDING_MARK-b03dd56c14dc6528901c5ad10233d03e3955f7d9721f9ecd6a6dc50df84f7290"
    );
    assert_eq!(
        rate.fact_id(),
        "BINANCE-USDM-FUNDING_RATE-7963c982fd5c954e10423e6249de7f79bda4287808be08b1ea5e6e17a9b4aaf2"
    );
    assert_eq!(
        mark.source_record_hash().as_deref(),
        Some("0aeb924dfb0efdb871320c40117e1363d64ce0387cf124f0a7044e9931de2a45")
    );
    assert_eq!(mark.source_record_hash(), rate.source_record_hash());
    assert_eq!(mark.provider_evidence_id(), rate.provider_evidence_id());
    assert_eq!(mark.to_record()["value"]["value"], "60000.10");
    assert_eq!(mark.to_record()["revision"], 1);
    assert!(mark.stable_order().1 < rate.stable_order().1);
    for (field, value) in [
        ("markPrice", json!(null)),
        ("rateType", json!("SPECIAL")),
        ("fundingTime", json!(true)),
        ("symbol", json!("ETHUSDT")),
        ("fundingRate", json!("Infinity")),
    ] {
        let mut raw = raw.clone();
        raw[field] = value;
        assert!(usdm_facts::funding_boundary(&raw, &c).is_err());
    }
}
#[test]
fn usdm_reference_types_identity_and_receive_time_fail_closed() {
    let id = "BTCUSDT-PERP.BINANCE".parse().unwrap();
    let mut c = usdm_facts::Context {
        instrument_id: &id,
        data_version: "v1",
        source_sequence: 2,
        received_at: "1970-01-01T00:00:02Z".parse().unwrap(),
    };
    let raw = json!({"T":1000,"p":"60000.10","i":"60001.20"});
    let mark = usdm_facts::reference_price(&raw, OnlyReferencePriceKind::Mark, &c).unwrap();
    let index = usdm_facts::reference_price(&raw, OnlyReferencePriceKind::Index, &c).unwrap();
    assert_eq!(mark.to_record()["value"]["value"], "60000.10");
    assert_eq!(index.to_record()["value"]["value"], "60001.20");
    assert_ne!(mark.fact_id(), index.fact_id());
    assert!(usdm_facts::reference_price(&raw, OnlyReferencePriceKind::Settlement, &c).is_err());
    c.received_at = "1970-01-01T00:00:00Z".parse().unwrap();
    assert!(usdm_facts::reference_price(&raw, OnlyReferencePriceKind::Mark, &c).is_err());
}
#[test]
fn usdm_closed_contract_bar_preserves_derivative_identity_and_rejects_spot() {
    let spot = instrument();
    let mut record = spot.to_record();
    record["model_type"] = json!("OnlyCryptoPerpetual");
    record["instrument_id"]["symbol"]["value"] = json!("BTCUSDT-PERP");
    record["instrument_type"] = json!("CRYPTO_PERPETUAL");
    record["market_type"] = json!("DERIVATIVE");
    record["margin_currency"] = record["quote_currency"].clone();
    record["contract_type"] = json!("LINEAR");
    let perpetual = onlyalpha_domain::instrument::OnlyInstrument::from_record(&record).unwrap();
    let row = json!([
        0, "10", "11", "9", "10.5", "1.23", 59999, "12.915", 3, "0", "0", "0"
    ]);
    let bar = usdm_facts::contract_bar(&row, &perpetual)
        .unwrap()
        .to_record();
    assert_eq!(
        bar["bar_type"]["instrument_id"]["symbol"]["value"],
        "BTCUSDT-PERP"
    );
    assert_eq!(bar["bar_end"], "1970-01-01T00:01:00Z");
    assert_eq!(bar["volume"]["value"], "1.23");
    assert!(usdm_facts::contract_bar(&row, &spot).is_err());
    assert!(spot_normalize::rest_bar(&row, &perpetual).is_err());
}
#[test]
fn funding_hash_preserves_python_number_types_unicode_and_negative_zero_extensions() {
    let id = "BTCUSDT-PERP.BINANCE".parse().unwrap();
    let c = usdm_facts::Context {
        instrument_id: &id,
        data_version: "fixture-v2",
        source_sequence: 7,
        received_at: "2026-09-01T08:00:01Z".parse().unwrap(),
    };
    // Independent CPython json.dumps output digests, including whole raw record.
    let mut raw:serde_json::Value=serde_json::from_str(r#"{"symbol":"BTCUSDT","fundingTime":1788249600000,"fundingRate":"0.0001","markPrice":"60000.10","rateType":"REGULAR","extra":1.5}"#).unwrap();
    let (mark, rate) = usdm_facts::funding_boundary(&raw, &c).unwrap();
    assert_eq!(
        mark.source_record_hash().as_deref(),
        Some("42c6c23b26a974079c7649a67de45188d2a1638def9f12466d92044dede4266d")
    );
    assert_eq!(mark.source_record_hash(), rate.source_record_hash());
    raw["integer_float"] = serde_json::from_str("1.0").unwrap();
    raw["scientific"] = serde_json::from_str("1e-7").unwrap();
    raw["unicode"] = json!("币安🌕");
    raw["negative_zero"] = serde_json::from_str("-0.0").unwrap();
    let (mark, rate) = usdm_facts::funding_boundary(&raw, &c).unwrap();
    assert_eq!(
        mark.source_record_hash().as_deref(),
        Some("994c3e12ae60280e966447b41ed4911980ccc290c08d769b88ad36ce4716f281")
    );
    assert_eq!(mark.provider_evidence_id(), rate.provider_evidence_id());
    assert_eq!(
        mark.fact_id(),
        "BINANCE-USDM-FUNDING_MARK-b03dd56c14dc6528901c5ad10233d03e3955f7d9721f9ecd6a6dc50df84f7290"
    );
}
