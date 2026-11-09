use onlyalpha_data_source_binance::{reference_capture::ReferenceCapture, reference_store};
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_market_crypto::market_policy::{MarketBinding, Product};
use serde_json::{Value, json};
use std::{collections::BTreeMap, fs};
const EXCHANGE: &[u8] = include_bytes!("fixtures/spot-exchange.json");
const RULES: &[u8] = include_bytes!("fixtures/spot-execution.json");
const USDM: [&[u8]; 4] = [
    include_bytes!("fixtures/usdm-exchange.json"),
    include_bytes!("fixtures/usdm-funding.json"),
    include_bytes!("fixtures/usdm-brackets.json"),
    include_bytes!("fixtures/usdm-account.json"),
];
fn t(raw: &str) -> OnlyUtcDateTime {
    raw.parse().unwrap()
}
fn captured() -> OnlyUtcDateTime {
    t("2026-09-01T08:00:01Z")
}
fn usdm(raw: [&[u8]; 4]) -> ReferenceCapture {
    ReferenceCapture::usdm(
        raw,
        captured(),
        t("2026-08-01T00:00:00Z"),
        Some(t("2026-09-02T00:00:00Z")),
    )
    .unwrap()
}
fn spot(raw: &[u8], at: OnlyUtcDateTime, environment: &str) -> ReferenceCapture {
    ReferenceCapture::spot(raw, RULES, at, environment, &["BTCUSDT", "ETHUSDT"]).unwrap()
}

#[test]
fn spot_capture_binds_each_original_response_but_ignores_nonsemantic_changes_in_authority() {
    use sha2::{Digest, Sha256};
    let first = spot(EXCHANGE, captured(), "SPOT_TESTNET");
    let manifest = first.manifest();
    let provenance = &manifest["provenance"];
    assert_eq!(provenance["provider"], "BINANCE");
    assert_eq!(provenance["product"], "SPOT");
    assert_eq!(provenance["environment"], "SPOT_TESTNET");
    assert_eq!(
        provenance["parser_contract_version"],
        "BINANCE_SPOT_REFERENCE_NORMALIZER@2"
    );
    assert_eq!(
        provenance["requested_symbols"],
        json!(["BTCUSDT", "ETHUSDT"])
    );
    assert_eq!(provenance["server_time"], 1);
    assert_eq!(first.raw_evidence(), [EXCHANGE, RULES]);
    assert_eq!(manifest["evidence"].as_array().unwrap().len(), 2);
    for (i, (endpoint, body)) in [
        ("/api/v3/exchangeInfo", EXCHANGE),
        ("/api/v3/executionRules", RULES),
    ]
    .into_iter()
    .enumerate()
    {
        let descriptor = &manifest["evidence"][i];
        assert_eq!(descriptor["endpoint_id"], endpoint);
        let hash: String = Sha256::digest(body)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(descriptor["raw_sha256"], hash);
        assert_eq!(
            descriptor["request_parameters"],
            json!([["symbols", "[\"BTCUSDT\",\"ETHUSDT\"]"]])
        );
    }
    let authority = first.authorities()[0].fingerprint();
    let original: Value = serde_json::from_slice(EXCHANGE).unwrap();
    // 原始 fixture 从 timezone 开始；serde_json 默认 Map 按 key 排序。
    let reordered = original.to_string();
    assert_ne!(EXCHANGE, reordered.as_bytes());
    let second = spot(reordered.as_bytes(), captured(), "SPOT_TESTNET");
    let mut corrected_clock = original;
    corrected_clock["serverTime"] = json!(2);
    let third = spot(
        corrected_clock.to_string().as_bytes(),
        captured(),
        "SPOT_TESTNET",
    );
    for (a, b) in [(&first, &second), (&second, &third)] {
        assert_eq!(b.authorities()[0].fingerprint(), authority);
        assert_ne!(a.fingerprint(), b.fingerprint());
        assert_ne!(
            a.manifest()["evidence"][0]["raw_sha256"],
            b.manifest()["evidence"][0]["raw_sha256"]
        );
    }
    let later = spot(EXCHANGE, t("2026-09-02T00:00:00Z"), "SPOT_TESTNET");
    assert_eq!(later.authorities()[0].fingerprint(), authority);
    assert_ne!(later.fingerprint(), first.fingerprint());
    assert_eq!(later.manifest()["evidence"], first.manifest()["evidence"]);
}

#[test]
fn spot_semantic_changes_identify_the_affected_symbol_or_exchange_rule() {
    let first = spot(EXCHANGE, captured(), "LIVE");
    let original: Value = serde_json::from_slice(EXCHANGE).unwrap();
    let authority = &first.authorities()[0];
    for (filter, key, value) in [
        (Some("PRICE_FILTER"), "tickSize", json!("0.02")),
        (Some("LOT_SIZE"), "stepSize", json!("0.00002")),
        (Some("NOTIONAL"), "minNotional", json!("6")),
        (Some("NOTIONAL"), "maxNotional", json!("8000000")),
        (Some("PERCENT_PRICE"), "multiplierUp", json!("4")),
        (None, "status", json!("HALT")),
        (None, "permissionSets", json!([["SPOT"], ["TRD_GRP_002"]])),
        (None, "ocoAllowed", json!(false)),
    ] {
        let mut changed = original.clone();
        let symbol = &mut changed["symbols"][0];
        let parent = match filter {
            Some(name) => symbol["filters"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|r| r["filterType"] == name)
                .unwrap(),
            None => symbol,
        };
        assert_ne!(parent[key], value, "{key}");
        parent[key] = value;
        let captured_change = spot(changed.to_string().as_bytes(), captured(), "LIVE");
        let revised = &captured_change.authorities()[0];
        assert_ne!(revised.fingerprint(), authority.fingerprint(), "{key}");
        assert_ne!(
            revised.resolve("BTCUSDT.BINANCE", captured()).unwrap()["content_fingerprint"],
            authority.resolve("BTCUSDT.BINANCE", captured()).unwrap()["content_fingerprint"],
            "{key}"
        );
        assert_eq!(
            revised.resolve("ETHUSDT.BINANCE", captured()).unwrap(),
            authority.resolve("ETHUSDT.BINANCE", captured()).unwrap(),
            "{key}"
        );
    }
    let known = |limit| {
        let mut changed = original.clone();
        changed["exchangeFilters"] =
            json!([{"filterType":"EXCHANGE_MAX_NUM_ORDERS","maxNumOrders":limit}]);
        spot(changed.to_string().as_bytes(), captured(), "LIVE")
    };
    let a = known(1000);
    let b = known(1001);
    assert_ne!(
        a.authorities()[0].fingerprint(),
        b.authorities()[0].fingerprint()
    );
    assert_eq!(
        a.authorities()[0]
            .resolve("BTCUSDT.BINANCE", captured())
            .unwrap(),
        b.authorities()[0]
            .resolve("BTCUSDT.BINANCE", captured())
            .unwrap()
    );
}

#[test]
fn spot_protocol_capabilities_and_unknown_symbol_filter_control_trade_eligibility() {
    let mut exchange: Value = serde_json::from_slice(EXCHANGE).unwrap();
    exchange["symbols"][0]["filters"]
        .as_array_mut()
        .unwrap()
        .push(json!({"filterType":"NEW_SYMBOL_LIMIT","limit":3}));
    let capture = spot(exchange.to_string().as_bytes(), captured(), "LIVE");
    let authority = &capture.authorities()[0];
    let row = authority.resolve("BTCUSDT.BINANCE", captured()).unwrap();
    assert_eq!(row["time_in_force"], json!(["GTC", "IOC", "FOK"]));
    assert_eq!(row["default_stp_mode"], "EXPIRE_MAKER");
    assert_eq!(
        row["allowed_stp_modes"],
        json!(["EXPIRE_BOTH", "EXPIRE_MAKER", "EXPIRE_TAKER", "NONE"])
    );
    assert_eq!(
        row["capabilities"],
        json!([
            ["allowTrailingStop", true],
            ["amendAllowed", true],
            ["cancelReplaceAllowed", true],
            ["pegInstructionsAllowed", true],
            ["quoteOrderQtyMarketAllowed", true]
        ])
    );
    assert_eq!(row["spot_trading_allowed"], true);
    assert_eq!(row["compatibility_status"], "INCOMPATIBLE");
    assert!(
        row["rules"]
            .as_array()
            .unwrap()
            .iter()
            .any(|r| r["rule_type"] == "NEW_SYMBOL_LIMIT"
                && r["category"] == "UNKNOWN_CRITICAL"
                && r["values"] == json!([["limit", 3]]))
    );
    let config = json!({"reference_resource_id":"spot","expected_reference_fingerprint":authority.fingerprint(),"maker_fee_rate":"0.001","taker_fee_rate":"0.001"});
    let binding = MarketBinding::resolve(
        Product::Spot,
        &config,
        &BTreeMap::from([("spot".into(), authority.clone())]),
    )
    .unwrap();
    let validate = |id| {
        binding
            .compile(id, captured())
            .unwrap()
            .validate_limit(&10.into(), &1.into())
    };
    assert_eq!(validate("BTCUSDT.BINANCE"), Err("MARKET_NOT_TRADABLE"));
    assert_eq!(validate("ETHUSDT.BINANCE"), Ok(()));
}
#[test]
fn spot_protocol_capabilities_preserve_canonical_order_instruction_and_time_in_force() {
    use onlyalpha_data_source_binance::spot_reference::{
        ExecutionInstruction::PostOnly, order_type, time_in_force,
    };
    use onlyalpha_domain::enums::{OnlyOrderType, OnlyTimeInForce};
    for (native, canonical, instruction) in [
        ("LIMIT", OnlyOrderType::Limit, None),
        ("MARKET", OnlyOrderType::Market, None),
        ("STOP_LOSS", OnlyOrderType::StopMarket, None),
        ("STOP_LOSS_LIMIT", OnlyOrderType::StopLimit, None),
        ("TAKE_PROFIT", OnlyOrderType::MarketIfTouched, None),
        ("TAKE_PROFIT_LIMIT", OnlyOrderType::LimitIfTouched, None),
        ("LIMIT_MAKER", OnlyOrderType::Limit, Some(PostOnly)),
    ] {
        assert_eq!(order_type(native).unwrap(), (canonical, instruction));
    }
    assert!(order_type("STOP_MARKET").is_err());
    for (native, expected) in [
        ("GTC", OnlyTimeInForce::Gtc),
        ("IOC", OnlyTimeInForce::Ioc),
        ("FOK", OnlyTimeInForce::Fok),
    ] {
        assert_eq!(time_in_force(native).unwrap(), expected);
    }
    assert!(time_in_force("GTD").is_err());
}
#[test]
fn exact_four_responses_produce_independent_public_and_account_authorities() {
    let capture = usdm(USDM);
    assert_eq!(capture.authorities().len(), 2);
    assert_eq!(
        capture.authorities()[0].fingerprint(),
        "f001e07b0cb19daff4597d76a77db82d8c2d80972c9fc23f6a30af4e5fcceb88"
    );
    assert_eq!(
        capture.authorities()[1].fingerprint(),
        "797a29f95c58fb3371c91fb39092f895dda118e4c94a673fc968a224b1486e3d"
    );
    let shifted = ReferenceCapture::usdm(
        USDM,
        captured(),
        t("2026-08-02T00:00:00Z"),
        Some(t("2026-09-02T00:00:00Z")),
    )
    .unwrap();
    for (left, right) in capture.authorities().iter().zip(shifted.authorities()) {
        assert_ne!(left.fingerprint(), right.fingerprint());
        assert_eq!(
            left.payload()["references"][0]["content_fingerprint"],
            right.payload()["references"][0]["content_fingerprint"]
        );
    }
    let mut raw = USDM;
    raw[2] = b"[]";
    assert!(ReferenceCapture::usdm(raw, captured(), captured(), None).is_err());
    assert!(ReferenceCapture::usdm(USDM, captured(), captured(), Some(captured())).is_err());
}
#[test]
fn hedging_isolated_requires_matching_effective_account_and_attributed_evidence() {
    let mut raw = USDM;
    raw[3]=br#"{"positionMode":"HEDGING","symbols":[{"symbol":"BTCUSDT","marginMode":"ISOLATED","leverage":"10"}]}"#;
    let capture = usdm(raw);
    let config = json!({"public_reference_resource_id":"pub","expected_public_reference_fingerprint":capture.authorities()[0].fingerprint(),"account_reference_resource_id":"acct","expected_account_reference_fingerprint":capture.authorities()[1].fingerprint(),"requested_position_mode":"HEDGING","requested_margin_mode":"ISOLATED","requested_leverage":"10","maker_fee_rate":"0.0002","taker_fee_rate":"0.0005"});
    let resources = BTreeMap::from([
        ("pub".into(), capture.authorities()[0].clone()),
        ("acct".into(), capture.authorities()[1].clone()),
    ]);
    let binding = MarketBinding::resolve(Product::Usdm, &config, &resources).unwrap();
    let policy = binding.compile("BTCUSDT-PERP.BINANCE", captured()).unwrap();
    assert_eq!(policy.record()["position_mode"], "HEDGING");
    assert_eq!(policy.record()["margin_mode"], "ISOLATED");
    let mut altered = config;
    altered["requested_position_mode"] = json!("NETTING");
    assert!(MarketBinding::resolve(Product::Usdm, &altered, &resources).is_err());
}
#[test]
fn spot_protocol_rules_are_preserved_and_raw_evidence_is_independent() {
    let a = spot(EXCHANGE, captured(), "LIVE");
    let b = spot(EXCHANGE, captured(), "SPOT_TESTNET");
    assert_ne!(a.fingerprint(), b.fingerprint());
    assert_eq!(
        a.authorities()[0].fingerprint(),
        b.authorities()[0].fingerprint()
    );
    let row = a.authorities()[0]
        .resolve("BTCUSDT.BINANCE", captured())
        .unwrap();
    assert_eq!(row["market_quantity_step"], "0");
    assert_eq!(row["market_maximum_quantity"], "100");
    assert_eq!(
        row["order_group_capabilities"],
        json!(["OCO", "OTO", "OPO"])
    );
    assert_eq!(row["rules"].as_array().unwrap().len(), 11);
    let mut changed: Value = serde_json::from_slice(EXCHANGE).unwrap();
    changed["exchangeFilters"] = json!([{"filterType":"NEW_EXCHANGE_RULE","x":1}]);
    let incompatible = spot(changed.to_string().as_bytes(), captured(), "LIVE");
    assert!(
        incompatible.authorities()[0]
            .resolve("BTCUSDT.BINANCE", captured())
            .is_err()
    );
    changed["exchangeFilters"] = json!([]);
    changed["symbols"][0]["filters"].as_array_mut().unwrap().push(json!({"filterType":"MIN_NOTIONAL","minNotional":"6","applyToMarket":true,"avgPriceMins":5}));
    assert!(
        ReferenceCapture::spot(
            changed.to_string().as_bytes(),
            RULES,
            captured(),
            "LIVE",
            &[]
        )
        .is_err()
    );
}
#[test]
fn immutable_files_verify_capture_and_independently_replay_semantics() {
    let dir = std::env::temp_dir().join(format!(
        "onlyalpha-crypto-reference-test-{}",
        std::process::id()
    ));
    fs::create_dir(&dir).unwrap();
    let a = spot(EXCHANGE, captured(), "LIVE");
    let b = spot(EXCHANGE, t("2026-09-02T00:00:00Z"), "LIVE");
    assert_eq!(
        reference_store::publish_spot(&dir, &a).unwrap(),
        (true, true)
    );
    assert_eq!(
        reference_store::publish_spot(&dir, &a).unwrap(),
        (false, false)
    );
    assert_eq!(
        reference_store::publish_spot(&dir, &b).unwrap(),
        (true, false)
    );
    assert_eq!(
        reference_store::load_spot_capture(&dir, a.fingerprint())
            .unwrap()
            .fingerprint(),
        a.fingerprint()
    );
    let id = a.authorities()[0].fingerprint();
    let manifest_sha = onlyalpha_market_crypto::reference::raw_sha256(
        &fs::read(dir.join("references").join(id).join("manifest.json")).unwrap(),
    );
    assert!(reference_store::load_spot_reference(&dir, id, &"0".repeat(64)).is_err());
    fs::write(
        dir.join("captures")
            .join(a.fingerprint())
            .join("exchangeInfo.json"),
        b"{}",
    )
    .unwrap();
    assert!(reference_store::load_spot_capture(&dir, a.fingerprint()).is_err());
    assert_eq!(
        reference_store::load_spot_reference(&dir, id, &manifest_sha)
            .unwrap()
            .fingerprint(),
        id
    );
    let path = dir.join("references").join(id).join("reference.json");
    fs::write(&path, b"{}").unwrap();
    assert!(reference_store::load_spot_reference(&dir, id, &manifest_sha).is_err());
    assert!(reference_store::publish_spot(&dir, &b).is_err());
    assert_eq!(fs::read(path).unwrap(), b"{}");
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn leverage_brackets_accept_exact_protocol_json_numbers_and_reject_wrong_types() {
    let bytes=br#"[{"symbol":"BTCUSDT","brackets":[{"bracket":1,"initialLeverage":125,"notionalFloor":0,"notionalCap":10000,"maintMarginRatio":0.0065,"cum":0}]}]"#;
    let capture = usdm([USDM[0], USDM[1], bytes, USDM[3]]);
    assert_eq!(capture.raw_evidence()[2].as_slice(), &bytes[..]);
    let account = capture.authorities()[1]
        .resolve("BTCUSDT-PERP.BINANCE", captured())
        .unwrap();
    assert_eq!(account["margin_segments"][0]["upper_bound"], "10000");
    assert_eq!(account["margin_segments"][0]["maintenance_slope"], "0.0065");
    for (field, wrong) in [
        ("notionalFloor", json!(false)),
        ("notionalCap", json!(1.5)),
        ("maintMarginRatio", Value::Null),
        ("cum", json!([])),
    ] {
        let mut broken: Value = serde_json::from_slice(bytes).unwrap();
        broken[0]["brackets"][0][field] = wrong;
        let broken = serde_json::to_vec(&broken).unwrap();
        assert!(
            ReferenceCapture::usdm(
                [USDM[0], USDM[1], &broken, USDM[3]],
                captured(),
                t("2026-08-01T00:00:00Z"),
                None
            )
            .is_err()
        );
    }
}
