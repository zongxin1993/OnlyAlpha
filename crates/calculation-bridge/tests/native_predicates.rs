//! Actual native predicate consumer; no Runtime admission or publication proof.
use onlyalpha_calculation_bridge::native_predicates::PredicateCalculation;
use serde_json::{Value, json};

fn reference() -> Value {
    json!({"left":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}})
}

#[test]
fn exact_decimal_threshold_and_missing_values_use_native_predicates() {
    let calculation = PredicateCalculation::resolve(
        "onlyalpha.predicate.internal.compare.ge.decimal.literal",
        "1",
        &json!({"literal":{"type":"DECIMAL","value":"0.001"}}),
        &reference(),
    )
    .unwrap();
    for (value, expected) in [
        (json!("0.001"), json!(true)),
        (json!("0.000999999999999999"), json!(false)),
        (json!("-0.001"), json!(false)),
        (Value::Null, Value::Null),
    ] {
        assert_eq!(
            calculation.evaluate(&json!({"left":value})).unwrap(),
            json!({"value":expected})
        );
    }
    assert!(calculation.evaluate(&json!({"left":true})).is_err());
    assert!(calculation.evaluate(&json!({"left":"NaN"})).is_err());
    assert!(
        calculation
            .evaluate(&json!({"left":"1","extra":"1"}))
            .is_err()
    );
    let record = calculation.definition().to_record();
    assert_eq!(
        record["parameters"]["literal_left"],
        json!({"type":"BOOLEAN","value":false})
    );
    assert_eq!(record["outputs"][0]["semantic_type"], "PREDICATE_VALUE");
    assert_eq!(record["warmup"]["initialization"], "UPSTREAM");
    assert_eq!(
        PredicateCalculation::from_record(&record)
            .unwrap()
            .definition(),
        calculation.definition()
    );
    let mut changed = record;
    changed["warmup"]["minimum_observations"] = json!(2);
    assert!(PredicateCalculation::from_record(&changed).is_err());
}

#[test]
fn native_boolean_and_terminals_preserve_null_until_strategy_decision() {
    let bindings = json!({"left":{"node_fingerprint":null,"output_name":"value","source":"left"},"right":{"node_fingerprint":null,"output_name":"value","source":"right"}});
    let and = PredicateCalculation::resolve(
        "onlyalpha.predicate.internal.boolean.and",
        "1",
        &json!({}),
        &bindings,
    )
    .unwrap();
    assert_eq!(
        and.evaluate(&json!({"left":null,"right":false})).unwrap(),
        json!({"value":false})
    );
    assert_eq!(
        and.evaluate(&json!({"left":null,"right":true})).unwrap(),
        json!({"value":null})
    );
    let terminal = PredicateCalculation::resolve(
        "onlyalpha.predicate.internal.terminal.entry_signal",
        "1",
        &json!({}),
        &json!({"value":{"node_fingerprint":null,"output_name":"value","source":"signal"}}),
    )
    .unwrap();
    assert_eq!(
        terminal.definition().to_record()["outputs"][0]["semantic_type"],
        "ENTRY_SIGNAL"
    );
    assert_eq!(
        terminal.evaluate(&json!({"value":null})).unwrap(),
        json!({"value":null})
    );
    assert!(
        PredicateCalculation::resolve(
            "onlyalpha.predicate.internal.boolean.and",
            "2",
            &json!({}),
            &bindings
        )
        .is_err()
    );
}

#[test]
fn comparison_layout_and_literal_direction_remain_explicit() {
    let literal = PredicateCalculation::resolve(
        "onlyalpha.predicate.internal.compare.lt.decimal.literal", "1",
        &json!({"literal":{"type":"DECIMAL","value":"2"},"literal_left":{"type":"BOOLEAN","value":true}}),
        &reference(),
    ).unwrap();
    assert_eq!(
        literal.evaluate(&json!({"left":"3"})).unwrap(),
        json!({"value":true})
    );
    assert_eq!(
        literal.evaluate(&json!({"left":"1"})).unwrap(),
        json!({"value":false})
    );
    let refs = PredicateCalculation::resolve(
        "onlyalpha.predicate.internal.compare.eq.decimal.refs", "1", &json!({}),
        &json!({"left":{"node_fingerprint":null,"output_name":"value","source":"left"},"right":{"node_fingerprint":null,"output_name":"value","source":"right"}}),
    ).unwrap();
    assert_eq!(
        refs.evaluate(&json!({"left":"-0.000","right":"0"}))
            .unwrap(),
        json!({"value":true})
    );
    assert_eq!(
        refs.evaluate(&json!({"left":null,"right":"0"})).unwrap(),
        json!({"value":null})
    );
    assert!(
        PredicateCalculation::resolve(
            "onlyalpha.predicate.internal.compare.eq.decimal.literal",
            "1",
            &json!({"literal":{"type":"INTEGER","value":2}}),
            &reference(),
        )
        .is_err()
    );
}
