use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    identifiers::OnlyInstrumentId,
    numeric::OnlyDecimal,
    time::{OnlyTradingDay, OnlyUtcDateTime},
    value::OnlyPrice,
};
use onlyalpha_market_cn_ashare::*;
use serde_json::{Value, json};
fn reference() -> Value {
    json!({"instrument_id":"600000.XSHG","exchange":"SSE","security_type":"COMMON_STOCK","board":"SSE_MAIN",
        "lot_size":"100","price_tick":"0.01","st_status":false,"suspended":false,"previous_close":"10.00",
        "effective_from":"2025-01-01","effective_to":null,"source":"GOLDEN_DATASET","source_version":"plugin-test-v1","data_version":"plugin-test-v1"})
}
fn day(s: &str) -> OnlyTradingDay {
    OnlyTradingDay::from_record(&json!({"schema_version":1,"value":s})).unwrap()
}
fn instrument(s: &str) -> OnlyInstrumentId {
    s.parse().unwrap()
}
fn bundle(version: &str, refs: Value) -> Bundle {
    Factory
        .resolve(PLUGIN_ID, PRODUCT_ID, version, &json!({"references":refs}))
        .unwrap()
}
fn compile(version: &str, raw: Value, date: &str) -> CompiledPolicy {
    let id = instrument(raw["instrument_id"].as_str().unwrap());
    let b = bundle(version, json!([raw]));
    b.compiler().compile(b.reference(), &id, day(date)).unwrap()
}
fn number(v: &Value) -> OnlyDecimal {
    v.as_str().unwrap().parse().unwrap()
}

#[test]
fn factory_returns_one_immutable_effective_bundle_with_real_owners() {
    let first = bundle("2025.1", json!([reference()]));
    let repeated = bundle("2025.1", json!([reference()]));
    assert_eq!(first.record(), repeated.record());
    assert_eq!(first.fingerprint(), repeated.fingerprint());
    assert_eq!(first.fingerprint().len(), 64);
    assert_eq!(
        first
            .reference()
            .resolve(&instrument("600000.XSHG"), day("2026-01-05"))
            .unwrap()
            .record()["source_version"],
        "plugin-test-v1"
    );
    let before = first.record();
    let mut detached = first.record();
    detached["provider_plugin_id"] = json!("foreign");
    assert_eq!(first.record(), before);
    assert_ne!(detached, first.record());
    assert_ne!(
        bundle("2026.07", json!([reference()])).fingerprint(),
        first.fingerprint()
    );
}
#[test]
fn factory_rejects_unknown_identity_version_missing_and_extra_configuration() {
    for (plugin, product, version, config, code) in [
        (
            PLUGIN_ID,
            "OTHER",
            "2025.1",
            json!({"references":[reference()]}),
            "UNSUPPORTED_MARKET_PRODUCT",
        ),
        (
            PLUGIN_ID,
            PRODUCT_ID,
            "2099.1",
            json!({"references":[reference()]}),
            "UNSUPPORTED_MARKET_PRODUCT_VERSION",
        ),
        (
            PLUGIN_ID,
            PRODUCT_ID,
            "2025.1",
            json!({}),
            "INVALID_CN_A_SHARE_CONFIGURATION",
        ),
        (
            PLUGIN_ID,
            PRODUCT_ID,
            "2025.1",
            json!({"references":[reference()],"fallback":true}),
            "INVALID_CN_A_SHARE_CONFIGURATION",
        ),
        (
            "foreign",
            PRODUCT_ID,
            "2025.1",
            json!({"references":[reference()]}),
            "CN_A_SHARE_PROVIDER_IDENTITY_MISMATCH",
        ),
    ] {
        assert_eq!(
            Factory
                .resolve(plugin, product, version, &config)
                .unwrap_err()
                .0,
            code
        );
    }
    for refs in [json!([]), json!([1]), Value::Null] {
        assert!(
            Factory
                .resolve(PLUGIN_ID, PRODUCT_ID, "2025.1", &json!({"references":refs}))
                .is_err()
        );
    }
}
#[test]
fn reference_order_effective_boundaries_and_overlap_have_one_identity() {
    let mut first = reference();
    first["effective_to"] = json!("2025-01-02");
    let mut second = reference();
    second["effective_from"] = json!("2025-01-02");
    second["previous_close"] = json!("10.10");
    second["source_version"] = json!("next");
    let left = bundle("2025.1", json!([first.clone(), second.clone()]));
    let right = bundle("2025.1", json!([second.clone(), first.clone()]));
    assert_eq!(left.fingerprint(), right.fingerprint());
    let id = instrument("600000.XSHG");
    assert_eq!(
        left.reference()
            .resolve(&id, day("2025-01-01"))
            .unwrap()
            .record()["source_version"],
        "plugin-test-v1"
    );
    assert_eq!(
        left.reference()
            .resolve(&id, day("2025-01-02"))
            .unwrap()
            .record()["source_version"],
        "next"
    );
    assert!(left.reference().resolve(&id, day("2024-12-31")).is_err());
    assert!(
        ReferenceAuthority::new(vec![
            Reference::from_record(&reference()).unwrap(),
            Reference::from_record(&second).unwrap()
        ])
        .is_err()
    );
    let mut equivalent = reference();
    equivalent["lot_size"] = json!("100.00");
    equivalent["exchange"] = json!("XSHG");
    equivalent["board"] = json!("MAIN");
    assert_eq!(
        Reference::from_record(&reference()).unwrap().fingerprint(),
        Reference::from_record(&equivalent).unwrap().fingerprint()
    );
    let record = Reference::from_record(&reference()).unwrap();
    let mut supplied = record.record();
    supplied["content_fingerprint"] = json!(record.fingerprint());
    assert!(Reference::from_record(&supplied).is_ok());
    supplied["record_fingerprint"] = json!("f".repeat(64));
    assert!(Reference::from_record(&supplied).is_err());
}
#[test]
fn missing_unknown_invalid_reference_fields_never_gain_defaults() {
    for (field, value) in [
        ("st_status", Value::Null),
        ("suspended", json!("false")),
        ("source", json!("UNKNOWN")),
        ("source_version", json!("")),
        ("data_version", Value::Null),
        ("board", json!("BSE")),
        ("exchange", json!("SZSE")),
        ("security_type", json!("ETF")),
        ("lot_size", json!("0")),
        ("lot_size", json!("0.5")),
        ("price_tick", json!("NaN")),
        ("previous_close", json!(-1)),
        ("previous_close", json!("Infinity")),
        ("effective_from", json!("2025-02-30")),
        ("effective_to", json!("2025-01-01")),
        ("unexpected", json!(true)),
    ] {
        let mut raw = reference();
        raw[field] = value;
        assert!(Reference::from_record(&raw).is_err(), "{field}");
    }
}
#[test]
fn compiler_freezes_board_st_matrix_and_exact_profile_effective_dates() {
    for (board, id, exchange, growth) in [
        ("SSE_MAIN", "600000.XSHG", "SSE", false),
        ("SZSE_MAIN", "000001.XSHE", "SZSE", false),
        ("CHINEXT", "300001.XSHE", "SZSE", true),
        ("STAR", "688001.XSHG", "SSE", true),
    ] {
        for st in [false, true] {
            for (version, date) in [("2025.1", "2026-07-05"), ("2026.07", "2026-07-06")] {
                let mut raw = reference();
                raw["board"] = json!(board);
                raw["instrument_id"] = json!(id);
                raw["exchange"] = json!(exchange);
                raw["st_status"] = json!(st);
                let policy = compile(version, raw, date).record();
                let expected = if growth {
                    "0.2"
                } else if st && version == "2025.1" {
                    "0.05"
                } else {
                    "0.1"
                };
                assert_eq!(
                    number(&policy["price_policy"]["daily_limit_rate"]),
                    expected.parse().unwrap()
                );
                assert_eq!(
                    policy["quantity_policy"]["minimum_buy_quantity"],
                    if board == "STAR" { "200" } else { "100" }
                );
                assert_eq!(
                    policy["quantity_policy"]["buy_quantity_increment"],
                    if board == "STAR" { "1" } else { "100" }
                );
            }
        }
    }
    for (version, date) in [
        ("2025.1", "2024-12-31"),
        ("2025.1", "2026-07-06"),
        ("2026.07", "2026-07-05"),
    ] {
        let b = bundle(version, json!([reference()]));
        assert_eq!(
            b.compiler()
                .compile(b.reference(), &instrument("600000.XSHG"), day(date))
                .unwrap_err()
                .0,
            "MARKET_PRODUCT_VERSION_NOT_EFFECTIVE"
        );
    }
}
fn calendar(policy: &CompiledPolicy) -> OnlyTradingCalendar {
    OnlyTradingCalendar::from_record(&json!({"schema_version":1,"calendar_id":{"schema_version":1,"value":"explicit-fixture-calendar"},
        "venue_id":{"schema_version":1,"value":"XSHG"},"timezone":{"schema_version":1,"name":"Asia/Shanghai"},
        "sessions":policy.sessions().to_record()["sessions"],"holidays":["2026-01-06"],"weekend_days":[5,6],
        "session_profile_id":null,"special_schedules":[],"calendar_version":1,"effective_from":"2025-01-01","effective_to":"2027-01-01"})).unwrap()
}
#[test]
fn compiler_freezes_session_tick_half_up_lot_odd_lot_status_and_real_t1_schedule() {
    let policy = compile("2025.1", reference(), "2026-01-05");
    let record = policy.record();
    assert_eq!(
        number(&record["price_policy"]["previous_close"]),
        "10".parse().unwrap()
    );
    assert_eq!(
        record["quantity_policy"]["odd_lot_liquidation_allowed"],
        true
    );
    assert_eq!(
        record["quantity_policy"]["odd_lot_requires_all_unreserved_available"],
        true
    );
    assert_eq!(record["settlement_policy"]["legal_settled"], 1);
    assert_eq!(record["settlement_policy"]["asset_trade_available"], 1);
    let calendar = calendar(&policy);
    for (utc, phase, orders) in [
        ("01:15", "OPEN_AUCTION", false),
        ("01:25", "PRE_OPEN", false),
        ("01:30", "CONTINUOUS", true),
        ("03:30", "MIDDAY_BREAK", false),
        ("05:00", "CONTINUOUS", true),
        ("06:57", "CLOSING_AUCTION", false),
    ] {
        let instant = format!("2026-01-05T{utc}:00Z")
            .parse::<OnlyUtcDateTime>()
            .unwrap();
        let session = calendar.session_at(instant).unwrap().unwrap();
        assert_eq!(session.session_type().as_str(), phase);
        assert_eq!(*session.allows_orders(), orders);
    }
    assert_eq!(record["session_timezone"], "Asia/Shanghai");
    let closed = "2026-01-05T07:00:00Z".parse::<OnlyUtcDateTime>().unwrap();
    assert!(calendar.session_at(closed).unwrap().is_none());
    use onlyalpha_domain::{enums::OnlyOrderSide, value::OnlyQuantity};
    assert!(
        policy
            .lot_rule()
            .validates(
                OnlyOrderSide::Buy,
                &OnlyQuantity::new("100".parse().unwrap(), 0).unwrap()
            )
            .unwrap()
    );
    assert!(
        !policy
            .lot_rule()
            .validates(
                OnlyOrderSide::Buy,
                &OnlyQuantity::new("150".parse().unwrap(), 0).unwrap()
            )
            .unwrap()
    );
    let schedule = policy.settlement_schedule(&calendar).unwrap();
    assert_eq!(schedule["asset_trade_available"], "2026-01-07");
    assert_eq!(schedule["cash_withdrawable"], "2026-01-07");
    assert_eq!(schedule["legal_settled"], "2026-01-07");
    assert_eq!(schedule["cash_trade_available"], "2026-01-05");
    let mut raw = reference();
    raw["previous_close"] = json!("10.05");
    raw["st_status"] = json!(true);
    raw["suspended"] = json!(true);
    let p = compile("2025.1", raw, "2026-01-05");
    assert_eq!(p.record()["status"], "SUSPENDED");
    assert_eq!(p.price_limits().to_record()["upper"]["value"], "10.55");
    assert_eq!(p.price_limits().to_record()["lower"]["value"], "9.55");
    assert!(
        p.tick_scheme()
            .validates(&OnlyPrice::new("10.55".parse().unwrap(), 2).unwrap())
            .unwrap()
    );
    assert!(
        !p.tick_scheme()
            .validates(&OnlyPrice::new("10.555".parse().unwrap(), 3).unwrap())
            .unwrap()
    );
}
fn broker() -> Value {
    json!({"contract":{"id":"explicit-account-commission","version":"1","broker":"broker","account":"account","families":["commission"]},
        "source":"BROKER_CONTRACT:explicit-account-commission:1","schedules":[{"namespace":"BROKER","family":"commission","version":"1","from":20250630,"to":null,
            "scope":{"broker":"broker","account":"account","currency":"CNY"},"rules":[{"id":"commission","type":"BROKER_COMMISSION","authority":"BROKER","direction":"CHARGE","scope":"ORDER_CUMULATIVE","resolution":"ORDER_FIXED",
                "terms":[{"kind":"RATE","basis":"NOTIONAL","amount":"0.0003"}],"minimum":"5","maximum":null,"quantum":"0.01","rounding":"HALF_UP","pipeline":"BOUNDS_THEN_ROUND","side":null,"offset":null,"liquidity":null}]}]})
}
fn subject(venue: &str, side: &str) -> Value {
    let mut v: Value =
        serde_json::from_str(include_str!("../../../test-data/fee/common-v1.json")).unwrap();
    v = v["subject"].clone();
    v["currency"] = json!({"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"});
    v["market"] = json!("CN_A_SHARE");
    v["venue"] = json!(venue);
    v["instrument"] = json!(if venue == "XSHG" {
        "600000.XSHG"
    } else {
        "000001.XSHE"
    });
    v["side"] = json!(side);
    v
}
#[test]
fn real_fee_catalog_composes_sell_stamp_bilateral_transfer_and_explicit_broker_minimum() {
    let pack = FeePack::new();
    let record = pack.record();
    assert_eq!(record["schedules"].as_array().unwrap().len(), 6);
    for entry in record["schedules"].as_array().unwrap() {
        assert!(
            record["sources"]
                .as_array()
                .unwrap()
                .iter()
                .any(|s| s["source_id"] == entry["source_id"])
        );
        let rule = &entry["schedule"]["rules"][0];
        assert_eq!(
            rule["side"],
            if rule["type"] == "STAMP_DUTY" {
                json!("SELL")
            } else {
                Value::Null
            }
        );
        assert_eq!(rule["rounding"], "HALF_UP");
    }
    for venue in ["XSHG", "XSHE"] {
        for side in ["BUY", "SELL"] {
            let composition = pack.compose(venue, &broker()).unwrap();
            let binding = composition
                .bind(subject(venue, side), day("2026-01-05"))
                .unwrap();
            let basis =
                json!({"notional":"10000","quantity":"1000","contracts":null,"currency":"CNY"});
            let assessment = composition
                .catalog()
                .assess(&binding, 20260105, "fill-1", 1, basis.clone(), basis, None)
                .unwrap()
                .record();
            let components = assessment["components"].as_array().unwrap();
            assert!(
                components
                    .iter()
                    .any(|c| c["identity"]["type"] == "TRANSFER_FEE" && c["target"] == "0.10")
            );
            assert!(
                components
                    .iter()
                    .any(|c| c["identity"]["type"] == "BROKER_COMMISSION" && c["target"] == "5.00")
            );
            assert_eq!(
                components
                    .iter()
                    .filter(|c| c["identity"]["type"] == "STAMP_DUTY")
                    .count(),
                usize::from(side == "SELL")
            );
            if side == "SELL" {
                assert!(
                    components
                        .iter()
                        .any(|c| c["identity"]["type"] == "STAMP_DUTY" && c["target"] == "5.00")
                );
            }
            assert_eq!(binding.record()["catalog"], composition.catalog().record());
            assert!(
                composition
                    .bind(subject(venue, side), day("2025-06-29"))
                    .is_err()
            );
        }
    }
    for fault in ["missing", "source", "account", "currency", "namespace"] {
        let mut b = broker();
        match fault {
            "missing" => b = Value::Null,
            "source" => b["source"] = json!("guessed"),
            "account" => b["contract"]["account"] = json!("foreign"),
            "currency" => b["schedules"][0]["scope"]["currency"] = json!("USD"),
            _ => b["schedules"][0]["namespace"] = json!("MARKET"),
        }
        let result = pack.compose("XSHG", &b);
        assert!(
            result.is_err()
                || result
                    .unwrap()
                    .bind(subject("XSHG", "BUY"), day("2026-01-05"))
                    .is_err(),
            "{fault}"
        );
    }
}
#[test]
fn frozen_public_reference_fixture_is_consumed_by_the_actual_reference_and_compiler() {
    use sha2::{Digest, Sha256};
    let bytes = include_bytes!("../../../test-data/reference/cn_a_share_v1/references.json");
    let manifest: Value = serde_json::from_str(include_str!(
        "../../../test-data/reference/cn_a_share_v1/manifest.json"
    ))
    .unwrap();
    let raw_digest = Sha256::digest(bytes)
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    assert_eq!(raw_digest, manifest["files"]["references.json"]);
    let rows: Value = serde_json::from_slice(bytes).unwrap();
    let b = bundle("2025.1", rows.clone());
    for row in rows.as_array().unwrap() {
        let compiled = b
            .compiler()
            .compile(
                b.reference(),
                &instrument(row["instrument_id"].as_str().unwrap()),
                day("2025-01-02"),
            )
            .unwrap();
        assert_eq!(
            compiled.record()["status"],
            if row["suspended"] == true {
                "SUSPENDED"
            } else {
                "TRADABLE"
            }
        );
        assert!(
            b.reference()
                .resolve(
                    &instrument(row["instrument_id"].as_str().unwrap()),
                    day("2025-01-03")
                )
                .is_err()
        );
    }
}

#[test]
fn compiled_cash_economics_keep_six_settlement_axes_and_no_short_or_flip() {
    let policy = compile("2025.1", reference(), "2026-01-05");
    let record = policy.record();
    assert_eq!(record["currency"], "CNY");
    assert_eq!(record["contract_multiplier"], "1");
    assert_eq!(record["status"], "TRADABLE");
    assert_eq!(
        record["position_policy"],
        json!({"allow_flip":false,"mode":"NETTING","short_selling":"DISABLED"})
    );
    assert_eq!(
        record["settlement_policy"],
        json!({"id":"CN_A_SHARE_T1","version":"1","asset_booked":0,
            "asset_trade_available":1,"cash_booked":0,"cash_trade_available":0,
            "cash_withdrawable":1,"legal_settled":1})
    );
    assert_eq!(record["quantity_policy"]["sell_quantity_increment"], "1");
    assert_eq!(record["quantity_policy"]["round_lot_size"], "100");
    // ADR 0056: previous close and bars cannot prove a realtime price cage.
    assert_eq!(
        record["dynamic_price_cage"],
        json!({"status":"NOT_EVALUATED","reason":"REALTIME_QUOTE_AUTHORITY_UNAVAILABLE"})
    );
    let dates = policy.settlement_schedule(&calendar(&policy)).unwrap();
    assert_eq!(dates["asset_booked"], "2026-01-05");
    assert_eq!(dates["cash_booked"], "2026-01-05");

    // A valid calendar for another venue must not settle this instrument.
    let mut foreign = calendar(&policy).to_record();
    foreign["venue_id"]["value"] = json!("XSHE");
    let foreign = OnlyTradingCalendar::from_record(&foreign).unwrap();
    assert_eq!(
        policy.settlement_schedule(&foreign).unwrap_err().0,
        "SETTLEMENT_CALENDAR_SCOPE"
    );
}

#[test]
fn price_band_keeps_at_least_one_tick_on_both_sides() {
    // 10% of 0.02 is below half a 0.01 tick. Merely rounding the
    // percentage bounds would collapse both limits onto the close.
    let mut raw = reference();
    raw["previous_close"] = json!("0.02");
    let policy = compile("2025.1", raw, "2026-01-05");
    assert_eq!(policy.price_limits().to_record()["upper"]["value"], "0.03");
    assert_eq!(policy.price_limits().to_record()["lower"]["value"], "0.01");
}

#[test]
fn frozen_market_fee_records_keep_legacy_dates_rates_and_source_links() {
    let pack = FeePack::new().record();
    assert_eq!(pack["pack_id"], "CN_A_SHARE_PRODUCTION_MARKET_FEES");
    assert_eq!(pack["pack_version"], "2025.06.30");
    assert_eq!(
        pack["compatible_market_products"],
        json!(["CN_A_SHARE_CASH"])
    );
    assert_eq!(pack["coverage_from"], "2025-06-30");
    for (venue, name, transfer_source) in [
        ("XSHG", "SSE", "CSDC:SSE-FEE-TABLE:2025-06-30"),
        ("XSHE", "SZSE", "CSDC:SZSE-FEE-TABLE:2025-06-30"),
    ] {
        for (kind, version, from, to, rate, source, authority) in [
            (
                "STAMP_DUTY",
                "1",
                20220701,
                json!(20230828),
                "0.001",
                "PRC-NPC:STAMP-TAX-LAW:2021",
                "REGULATOR",
            ),
            (
                "STAMP_DUTY",
                "2",
                20230828,
                Value::Null,
                "0.0005",
                "MOF-STA:ANNOUNCEMENT-2023-39:1",
                "REGULATOR",
            ),
            (
                "TRANSFER_FEE",
                "1",
                20250630,
                Value::Null,
                "0.00001",
                transfer_source,
                "CLEARING",
            ),
        ] {
            let family = format!("CN_A_SHARE_{name}_{kind}");
            let entry = pack["schedules"]
                .as_array()
                .unwrap()
                .iter()
                .find(|entry| {
                    entry["schedule"]["family"] == family && entry["schedule"]["version"] == version
                })
                .unwrap();
            assert_eq!(entry["source_id"], source);
            let schedule = &entry["schedule"];
            assert_eq!(schedule["from"], from);
            assert_eq!(schedule["to"], to);
            assert_eq!(
                schedule["scope"],
                json!({"market":"CN_A_SHARE","venue":venue,
                "instrument_class":"CASH","currency":"CNY"})
            );
            let rule = &schedule["rules"][0];
            assert_eq!(rule["authority"], authority);
            assert_eq!(rule["direction"], "CHARGE");
            assert_eq!(rule["scope"], "FILL");
            assert_eq!(rule["resolution"], "FILL_EFFECTIVE");
            assert_eq!(rule["pipeline"], "ROUND_THEN_BOUNDS");
            assert_eq!(rule["quantum"], "0.01");
            assert_eq!(
                rule["terms"],
                json!([{"kind":"RATE","basis":"NOTIONAL","amount":rate}])
            );
        }
    }
    let sources = pack["sources"].as_array().unwrap();
    assert_eq!(sources.len(), 6);
    for (id, published, effective, supporting) in [
        ("PRC-NPC:STAMP-TAX-LAW:2021", "2021-06-10", "2022-07-01", 2),
        (
            "MOF-STA:ANNOUNCEMENT-2023-39:1",
            "2023-08-27",
            "2023-08-28",
            3,
        ),
        (
            "CSDC:SSE-FEE-TABLE:2025-06-30",
            "2025-06-30",
            "2025-06-30",
            1,
        ),
        (
            "CSDC:SZSE-FEE-TABLE:2025-06-30",
            "2025-06-30",
            "2025-06-30",
            2,
        ),
        (
            "CSDC:SH-SETTLEMENT-INTERFACE:V3.102",
            "2026-07-17",
            "2026-07-17",
            0,
        ),
        (
            "CSDC:SZ-SETTLEMENT-INTERFACE:V5.17",
            "2026-02-02",
            "2026-02-02",
            0,
        ),
    ] {
        let source = sources
            .iter()
            .find(|source| source["source_id"] == id)
            .unwrap();
        assert_eq!(source["publication_date"], published);
        assert_eq!(source["effective_date"], effective);
        assert_eq!(
            source["supporting_source_ids"].as_array().unwrap().len(),
            supporting
        );
        for linked in source["supporting_source_ids"].as_array().unwrap() {
            assert!(sources.iter().any(|source| source["source_id"] == *linked));
        }
    }
}
