use bigdecimal::BigDecimal;
use onlyalpha_domain::time::OnlyUtcDateTime;
use onlyalpha_market_crypto::{
    market_policy::{MarketBinding, Product},
    reference::Reference,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;

const SPOT: &str = include_str!("fixtures/spot-resource.json");
const PUBLIC: &str = include_str!("fixtures/usdm-public-resource.json");
const ACCOUNT: &str = include_str!("fixtures/usdm-account-resource.json");
const SPOT_ID: &str = "83e1fcf0caa557998b3b251daac5d55f1aeb8a3b14e956ae5b9bd9e905c2dfe4";
const PUBLIC_ID: &str = "f001e07b0cb19daff4597d76a77db82d8c2d80972c9fc23f6a30af4e5fcceb88";
const ACCOUNT_ID: &str = "797a29f95c58fb3371c91fb39092f895dda118e4c94a673fc968a224b1486e3d";
const PERP: &str = "BTCUSDT-PERP.BINANCE";

fn d(n: &str) -> BigDecimal {
    n.parse().unwrap()
}
fn t(s: &str) -> OnlyUtcDateTime {
    s.parse().unwrap()
}
fn v(s: &str) -> Value {
    serde_json::from_str(s).unwrap()
}
fn usdm_config() -> Value {
    json!({"public_reference_resource_id":"public","expected_public_reference_fingerprint":PUBLIC_ID,
        "account_reference_resource_id":"account","expected_account_reference_fingerprint":ACCOUNT_ID,
        "requested_position_mode":"NETTING","requested_margin_mode":"CROSS","requested_leverage":"10",
        "maker_fee_rate":"0.0002","taker_fee_rate":"0.0005"})
}
fn usdm_resources() -> BTreeMap<String, Reference> {
    BTreeMap::from([
        ("public".into(), Reference::load(&v(PUBLIC)).unwrap()),
        ("account".into(), Reference::load(&v(ACCOUNT)).unwrap()),
    ])
}
#[test]
fn original_resources_verify_content_authority_document_and_blob_identity() {
    for (raw, id, provider) in [
        (SPOT, SPOT_ID, "onlyalpha-plugin-binance-spot/reference@1"),
        (
            PUBLIC,
            PUBLIC_ID,
            "onlyalpha-plugin-binance-usdm/reference@1",
        ),
        (
            ACCOUNT,
            ACCOUNT_ID,
            "onlyalpha-plugin-binance-usdm/reference@1",
        ),
    ] {
        let payload = v(raw);
        let resource = Reference::load(&payload).unwrap();
        assert_eq!(resource.fingerprint(), id);
        assert_eq!(resource.payload(), &payload);
        let bytes=json!({"schema_version":1,"resource_id":"exact","provider_id":provider,"payload":payload}).to_string();
        let sha: String = Sha256::digest(bytes.as_bytes())
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect();
        assert_eq!(
            Reference::document(bytes.as_bytes(), &sha, "exact")
                .unwrap()
                .fingerprint(),
            id
        );
        assert!(Reference::document(bytes.as_bytes(), &"0".repeat(64), "exact").is_err());
        assert!(Reference::document(bytes.as_bytes(), &sha, "another").is_err());
        let mut changed = payload;
        let root = if raw == SPOT {
            &mut changed["authority"]
        } else {
            &mut changed
        };
        root["references"][0]["content_fingerprint"] = json!("0".repeat(64));
        assert!(Reference::load(&changed).is_err());
    }
}
#[test]
fn spot_exact_as_of_filters_and_static_limit_notional() {
    let resources = BTreeMap::from([("spot".into(), Reference::load(&v(SPOT)).unwrap())]);
    let config = json!({"reference_resource_id":"spot","expected_reference_fingerprint":SPOT_ID,"maker_fee_rate":"0.001","taker_fee_rate":"0.001"});
    let binding = MarketBinding::resolve(Product::Spot, &config, &resources).unwrap();
    let policy = binding
        .compile("BTCUSDT.BINANCE", t("2026-08-28T10:00:00Z"))
        .unwrap();
    assert!(
        binding
            .compile("BTCUSDT.BINANCE", t("2026-08-28T09:59:59Z"))
            .is_err()
    );
    let r = policy.record();
    assert_eq!(r["timezone"], "UTC");
    assert_eq!(r["continuous_24x7"], true);
    assert_eq!(r["position_mode"], "NETTING");
    assert_eq!(r["short_allowed"], false);
    assert_eq!(r["price_tick"], "0.01");
    assert_eq!(r["quantity_step"], "0.00001");
    assert_eq!(
        r["dynamic_price_requirements"][0]["reference_kind"],
        "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE"
    );
    assert!(policy.validate_limit(&d("10"), &d("1")).is_ok());
    assert_eq!(
        policy.validate_limit(&d("4"), &d("1")),
        Err("NOTIONAL_BELOW_MINIMUM")
    );
    assert_eq!(
        policy.validate_limit(&d("101"), &d("1")),
        Err("NOTIONAL_ABOVE_MAXIMUM")
    );
    assert!(policy.validate_limit(&d("10.005"), &d("1")).is_err());
    assert!(policy.validate_limit(&d("10"), &d("1.000001")).is_err());
}

#[test]
fn spot_repeated_resolution_reproduces_policy_and_changed_minimum_notional_changes_it() {
    let at = t("2026-08-28T10:00:00Z");
    let compile = |reference: Reference| {
        let config = json!({"reference_resource_id":"spot","expected_reference_fingerprint":reference.fingerprint(),"maker_fee_rate":"0.001","taker_fee_rate":"0.001"});
        let resources = BTreeMap::from([("spot".into(), reference)]);
        let binding = MarketBinding::resolve(Product::Spot, &config, &resources).unwrap();
        let policy = binding.compile("BTCUSDT.BINANCE", at).unwrap();
        (binding.fingerprint().to_owned(), policy)
    };
    let original = v(SPOT);
    let (first_id, first) = compile(Reference::load(&original).unwrap());
    let (again_id, again) = compile(Reference::load(&original).unwrap());
    assert_eq!(first_id, again_id);
    assert_eq!(first.record(), again.record());
    assert_eq!(
        first.compiled_policy_json().unwrap(),
        again.compiled_policy_json().unwrap()
    );
    let authority = &original["authority"];
    let mut rows = authority["references"].as_array().unwrap().clone();
    assert_eq!(rows[0]["instrument_id"], "BTCUSDT.BINANCE");
    assert_eq!(rows[0]["minimum_notional"], "5");
    rows[0]["minimum_notional"] = json!("6");
    let changed = Reference::spot(at, authority["exchange_rules"].clone(), rows).unwrap();
    let (changed_id, changed) = compile(changed);
    assert_ne!(first_id, changed_id);
    assert_ne!(
        first.record()["policy_fingerprint"],
        changed.record()["policy_fingerprint"]
    );
    assert!(first.validate_limit(&d("5"), &d("1")).is_ok());
    assert_eq!(
        changed.validate_limit(&d("5"), &d("1")),
        Err("NOTIONAL_BELOW_MINIMUM")
    );
    assert!(changed.validate_limit(&d("6"), &d("1")).is_ok());
}
#[test]
fn usdm_requires_exact_account_and_compiles_a_continuous_bounded_curve() {
    let resources = usdm_resources();
    let c = usdm_config();
    let binding = MarketBinding::resolve(Product::Usdm, &c, &resources).unwrap();
    let policy = binding.compile(PERP, t("2026-09-01T08:00:01Z")).unwrap();
    assert_eq!(
        policy.record()["funding_schedule"]["interval_seconds"],
        14400
    );
    assert_eq!(
        policy.record()["funding_schedule"]["valuation_price_kind"],
        "MARK"
    );
    assert_eq!(policy.record()["position_mode"], "NETTING");
    for (notional, initial, maintenance) in [
        ("99999.99", "9999.999", "399.99996"),
        ("100000", "10000", "400"),
        ("100000.01", "10000.001", "400.00005"),
        ("500000", "50000", "2400"),
    ] {
        assert_eq!(
            policy.margin_requirement(&d(notional)).unwrap(),
            (d(initial), d(maintenance))
        );
    }
    for n in ["-1", "500000.01"] {
        assert!(policy.margin_requirement(&d(n)).is_err());
    }
    for date in ["2026-07-31T23:59:59Z", "2026-09-02T00:00:00Z"] {
        assert!(binding.compile(PERP, t(date)).is_err());
    }
    for (key, bad) in [
        ("requested_position_mode", "HEDGING"),
        ("requested_margin_mode", "ISOLATED"),
        ("requested_leverage", "11"),
        ("account_reference_resource_id", "missing"),
        ("account_reference_resource_id", "public"),
        ("expected_account_reference_fingerprint", PUBLIC_ID),
    ] {
        let mut cfg = c.clone();
        cfg[key] = json!(bad);
        assert!(MarketBinding::resolve(Product::Usdm, &cfg, &resources).is_err());
    }
}
#[test]
fn role_specific_fees_use_native_catalog_and_participate_in_composition() {
    let resources = usdm_resources();
    let mut c = usdm_config();
    let first = MarketBinding::resolve(Product::Usdm, &c, &resources).unwrap();
    c["taker_fee_rate"] = json!("0.0006");
    assert_ne!(
        first.fingerprint(),
        MarketBinding::resolve(Product::Usdm, &c, &resources)
            .unwrap()
            .fingerprint()
    );
    let broker = json!({"id":"VIRTUAL_SIMULATION_ZERO","version":"1","broker":"virtual","account":"account-1","families":["zero"]});
    let schedule = json!({"namespace":"BROKER","family":"zero","version":"1","from":0,"to":null,"scope":{"broker":"virtual","account":"account-1","currency":"USDT"},"rules":[{"id":"zero","type":"BROKER_COMMISSION","authority":"BROKER","direction":"CHARGE","scope":"FILL","resolution":"ORDER_FIXED","terms":[{"kind":"FIXED","amount":"0"}],"minimum":null,"maximum":null,"quantum":"0.00000001","rounding":"HALF_EVEN","pipeline":"ROUND_THEN_BOUNDS","side":null,"offset":null,"liquidity":null}]});
    assert!(first.fee_catalog(&broker, &[]).is_err());
    let catalog = first.fee_catalog(&broker, &[schedule]).unwrap();
    let subject = json!({"engine":"e","runtime":"r","account":"account-1","broker":"virtual","gateway":"virtual","generation":"a".repeat(64),"runtime_kind":"BACKTEST","cluster":"c","revision":"b".repeat(64),"instrument":PERP,"market":"BINANCE_USDM","venue":"BINANCE","instrument_class":"DERIVATIVE","currency":{"schema_version":1,"code":"USDT","precision":8,"currency_type":"CRYPTO"},"side":"BUY","offset":"OPEN"});
    let basis = json!({"notional":"60","quantity":"0.001","contracts":null,"currency":"USDT"});
    for (role, amount) in [("MAKER", "0.01200000"), ("TAKER", "0.03000000")] {
        let quote = catalog
            .quote_one_fill(subject.clone(), 1, 1, basis.clone(), Some(role))
            .unwrap()
            .record();
        assert_eq!(quote["charges"], amount);
    }
    assert!(catalog.quote_one_fill(subject, 1, 1, basis, None).is_err());
}
