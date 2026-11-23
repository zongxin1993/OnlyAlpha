use crate::program::{Program, ProgramInput, ProgramInstance, ProgramValue, evaluate_batch};
use serde_json::{Value, json};
use std::{collections::BTreeMap, str::FromStr, sync::Arc};
pub(super) fn raw() -> Value {
    json!({"schema_version":1,"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","inputs":{"close":{"type":"DECIMAL","role":"MARKET"}},"parameters":[{"name":"period","parameter_type":"INTEGER","required":false,"default":{"type":"INTEGER","value":2},"minimum":{"type":"INTEGER","value":1},"maximum":{"type":"INTEGER","value":100000},"enum_values":[],"uppercase":false}],"nodes":[{"op":"input","name":"close"},{"op":"rolling_mean","args":[0],"period":{"parameter":"period"}}],"outputs":{"value":1}})
}
pub(super) fn program(v: Value) -> Program {
    Program::decode(v.to_string().as_bytes()).unwrap()
}
pub(super) fn input(n: u64, value: Option<&str>) -> ProgramInput {
    ProgramInput::new(
        "TEST",
        n,
        BTreeMap::from([(
            "close".into(),
            value.map_or(ProgramValue::Missing, |s| {
                ProgramValue::Decimal(bigdecimal::BigDecimal::from_str(s).unwrap())
            }),
        )]),
    )
    .unwrap()
}
fn output(v: &BTreeMap<String, ProgramValue>) -> Option<String> {
    match &v["value"] {
        ProgramValue::Decimal(d) => Some(d.to_string()),
        ProgramValue::Missing => None,
        _ => panic!("numeric output"),
    }
}
#[test]
fn rolling_batch_event_prefix_nulls_instances_and_restore_are_exact() {
    let p = program(raw());
    let params = p.resolve_parameters(&json!({})).unwrap();
    let b = Arc::new(p.bind(&params).unwrap());
    let rows = vec![
        input(0, Some("1")),
        input(1, Some("3")),
        input(2, None),
        input(3, Some("7")),
        input(4, Some("9")),
    ];
    let expected = [
        None,
        Some("2.000000000000"),
        None,
        None,
        Some("8.000000000000"),
    ];
    let batch = evaluate_batch(&b, &rows).unwrap();
    assert_eq!(
        batch.iter().map(output).collect::<Vec<_>>(),
        expected.map(|v| v.map(str::to_owned))
    );
    let mut event = ProgramInstance::new(b.clone());
    for (i, r) in rows.iter().enumerate() {
        assert_eq!(event.step(r).unwrap(), batch[i]);
        assert_eq!(evaluate_batch(&b, &rows[..=i]).unwrap(), batch[..=i]);
    }
    let mut first = ProgramInstance::new(b.clone());
    first.step(&rows[0]).unwrap();
    first.step(&rows[1]).unwrap();
    let state = first.capture();
    let mut restored = ProgramInstance::new(b.clone());
    restored.restore(&state).unwrap();
    assert_eq!(restored.step(&rows[2]).unwrap(), batch[2]);
    let mut other = ProgramInstance::new(b.clone());
    assert_eq!(output(&other.step(&input(0, Some("100"))).unwrap()), None);
    let mut changed = state.clone();
    changed["schema_version"] = json!(99);
    assert!(other.restore(&changed).is_err());
    let bound_other = Arc::new(
        p.bind(&p.resolve_parameters(&json!({"period":3})).unwrap())
            .unwrap(),
    );
    assert_ne!(bound_other.fingerprint(), b.fingerprint());
    assert!(ProgramInstance::new(bound_other).restore(&state).is_err());
    let mut foreign = input(5, Some("10"));
    foreign = ProgramInput::new("OTHER", 5, foreign.values().clone()).unwrap();
    assert!(event.step(&foreign).is_err());
}
#[test]
fn forged_programs_types_future_inputs_cycles_and_unbounded_windows_are_rejected() {
    for (key, value) in [
        ("numeric_policy", json!("FLOAT")),
        ("schema_version", json!(2)),
        ("unknown", json!(true)),
    ] {
        let mut r = raw();
        r[key] = value;
        assert!(Program::decode(r.to_string().as_bytes()).is_err());
    }
    let mut r = raw();
    r["nodes"][1]["args"] = json!([1]);
    assert!(Program::decode(r.to_string().as_bytes()).is_err());
    let mut r = raw();
    r["inputs"]["close"]["role"] = json!("TARGET");
    assert!(Program::decode(r.to_string().as_bytes()).is_err());
    let p = program(raw());
    assert!(p.resolve_parameters(&json!({"period":0})).is_err());
    assert!(p.resolve_parameters(&json!({"period":100001})).is_err());
    assert!(
        p.resolve_parameters(&json!({"period":2,"extra":1}))
            .is_err()
    );
}
#[test]
fn native_decimal_golden_ties_negative_zero_division_and_budget_are_preserved() {
    for (a, b, op, want) in [
        ("1.0000000000005", "0", "add", Some("1.000000000000")),
        ("1.0000000000015", "0", "add", Some("1.000000000002")),
        ("-1.0000000000005", "0", "add", Some("-1.000000000000")),
        ("-0.0000000000001", "0", "add", Some("0")),
        ("1", "0", "div", None),
        ("1", "3", "div", Some("0.333333333333")),
    ] {
        let mut r = raw();
        r["parameters"] = json!([]);
        r["nodes"] = json!([{"op":"literal","type":"DECIMAL","value":a},{"op":"literal","type":"DECIMAL","value":b},{"op":op,"args":[0,1]}]);
        r["outputs"] = json!({"value":2});
        let p = program(r);
        let bound = Arc::new(p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap());
        assert_eq!(
            output(
                &ProgramInstance::new(bound)
                    .step(&input(0, Some("1")))
                    .unwrap()
            ),
            want.map(str::to_owned)
        );
    }
    let mut r = raw();
    r["nodes"][0] = json!({"op":"literal","type":"DECIMAL","value":"1e999999999"});
    assert!(Program::decode(r.to_string().as_bytes()).is_err());
}
