use onlyalpha_event::*;
use serde_json::json;
fn record() -> serde_json::Value {
    json!({"schema_version":2,"event_id":"00000000-0000-0000-0000-000000000001","event_type":"FACT","ts_event_ns":-1,"ts_init_ns":0,"ts_event":"1969-12-31T23:59:59.999999Z","ts_init":"1970-01-01T00:00:00Z","engine_id":"engine","runtime_id":"runtime","cluster_id":null,"source":"feed","sequence":"18446744073709551616".parse::<serde_json::Number>().unwrap(),"correlation_id":null,"causation_id":null,"priority":"NORMAL","payload":{"kind":"mapping","value":{"nested":{"value":1}}},"metadata":{}})
}
#[test]
fn record_is_exact_and_detached() {
    let original = record();
    let event = OnlyEvent::from_record(&original).unwrap();
    assert_eq!(event.to_record(), original);
    assert_eq!(event.sequence().to_string(), "18446744073709551616");
    let mut detached = event.to_record();
    detached["payload"]["value"]["nested"]["value"] = json!(9);
    assert_eq!(event.to_record(), original);
    assert_eq!(
        OnlyEvent::from_json(&event.to_json().unwrap()).unwrap(),
        event
    );
}
#[test]
fn malformed_records_fail_without_coercion_or_fallback() {
    for (key, value) in [
        ("schema_version", json!(3)),
        ("ts_event_ns", json!(true)),
        ("ts_event_ns", json!(1.5)),
        ("metadata", json!({"bad":1})),
        ("sequence", json!(true)),
        ("sequence", json!("1")),
        ("sequence", json!(-1)),
        ("event_id", json!("bad")),
        ("runtime_id", json!(null)),
        ("ts_init_ns", json!(-2)),
        ("ts_event", json!("1970-01-01T00:00:00Z")),
        ("priority", json!("UNKNOWN")),
        ("payload", json!({"kind":"scalar","value":{}})),
    ] {
        let mut bad = record();
        bad[key] = value;
        assert!(OnlyEvent::from_record(&bad).is_err(), "{key}");
    }
    let mut bad = record();
    bad["extra"] = json!(1);
    assert!(OnlyEvent::from_record(&bad).is_err());
}

#[test]
fn immutable_event_values_can_cross_inbound_boundaries() {
    fn send_sync<T: Send + Sync>() {}
    send_sync::<OnlyEvent>();
}
#[test]
fn nested_numeric_tokens_are_preserved_without_floating_evaluation() {
    let mut row = record();
    let value: serde_json::Value =
        serde_json::from_str("{\"amount\":123456789012345678901234567890.123456789}").unwrap();
    row["payload"] = json!({"kind":"mapping","value":value});
    let event = OnlyEvent::from_record(&row).unwrap();
    assert!(
        event
            .to_json()
            .unwrap()
            .contains("123456789012345678901234567890.123456789")
    );
}

#[test]
fn nested_invalid_number_tokens_are_rejected_before_an_event_exists() {
    for token in ["NaN", "Infinity", "00", "1e"] {
        let mut row = record();
        let mut mapping = serde_json::Map::new();
        mapping.insert(
            "bad".into(),
            serde_json::Value::Number(serde_json::Number::from_string_unchecked(token.into())),
        );
        row["payload"]["value"] = serde_json::Value::Object(mapping);
        assert!(OnlyEvent::from_record(&row).is_err(), "{token}");
    }
}
