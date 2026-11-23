use super::program_tests::{input, program, raw};
use crate::program::{ProgramInstance, ProgramValue};
use serde_json::json;
use std::sync::Arc;
#[test]
fn failed_numeric_step_does_not_advance_any_window_or_cursor() {
    let mut r = raw();
    r["parameters"] = json!([]);
    r["nodes"] = json!([{"op":"input","name":"close"},{"op":"rolling_mean","args":[0],"period":2},{"op":"mul","args":[0,0]}]);
    r["outputs"] = json!({"value":2});
    let p = program(r);
    let b = Arc::new(p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap());
    let mut s = ProgramInstance::new(b);
    s.step(&input(0, Some("2"))).unwrap();
    let before = s.capture();
    assert!(s.step(&input(1, Some("9999999999999999"))).is_err());
    assert_eq!(s.capture(), before);
    assert_eq!(
        s.step(&input(1, Some("3"))).unwrap()["value"],
        ProgramValue::Decimal(9.into())
    );
}
#[test]
fn binding_rejects_numerical_parameters_before_allocating_an_instance() {
    let mut r = raw();
    r["parameters"][0]["maximum"] = json!(null);
    r["nodes"] = json!([{"op":"parameter","name":"period"}]);
    r["outputs"] = json!({"value":0});
    let p = program(r);
    let resolved = p
        .resolve_parameters(&json!({"period":"9".repeat(600)}))
        .unwrap();
    assert!(p.bind(&resolved).is_err());
}
#[test]
fn missing_boolean_logic_is_three_valued_and_cannot_change_numeric_types() {
    for (op, x, y, want) in [
        ("and_", json!(false), json!(null), json!(false)),
        ("or_", json!(true), json!(null), json!(true)),
        ("and_", json!(true), json!(null), json!(null)),
    ] {
        let mut r = raw();
        r["parameters"] = json!([]);
        r["nodes"] = json!([{"op":"literal","type":"BOOLEAN","value":x},{"op":"literal","type":"BOOLEAN","value":y},{"op":op,"args":[0,1]}]);
        r["outputs"] = json!({"value":2});
        let p = program(r);
        let b = Arc::new(p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap());
        assert_eq!(
            ProgramInstance::new(b).step(&input(0, Some("1"))).unwrap()["value"].record(),
            want
        );
    }
}
#[test]
fn nested_windows_report_the_complete_prefix_requirement() {
    let mut r = raw();
    r["nodes"]
        .as_array_mut()
        .unwrap()
        .push(json!({"op":"delay","args":[1],"period":2}));
    r["outputs"] = json!({"value":2});
    let p = program(r);
    let b = p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap();
    assert_eq!(b.max_history(), 4);
}

#[test]
fn integer_inputs_and_literals_reject_fractional_values_without_advancing() {
    let mut r = raw();
    r["inputs"]["close"]["type"] = json!("INTEGER");
    let p = program(r);
    let b = Arc::new(p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap());
    let mut s = ProgramInstance::new(b);
    let before = s.capture();
    assert!(s.step(&input(0, Some("1.5"))).is_err());
    assert_eq!(s.capture(), before);
    assert!(s.step(&input(0, Some("1"))).is_ok());
    let mut r = raw();
    r["nodes"] = json!([{"op":"literal","type":"INTEGER","value":"1.5"}]);
    r["outputs"] = json!({"value":0});
    assert!(crate::program::Program::decode(r.to_string().as_bytes()).is_err());
}

#[test]
fn integer_type_information_survives_input_parameters_literals_and_selection() {
    let mut r = raw();
    r["inputs"]["close"]["type"] = json!("INTEGER");
    r["nodes"] = json!([
     {"op":"input","name":"close"},{"op":"parameter","name":"period"},
     {"op":"literal","type":"INTEGER","value":"-3"},{"op":"literal","type":"BOOLEAN","value":true},
     {"op":"where","args":[3,0,1]},{"op":"coalesce","args":[0,1]},
     {"op":"min","args":[0,1]},{"op":"add","args":[0,1]},
     {"op":"literal","type":"DECIMAL","value":"1"},{"op":"eq","args":[0,8]}
    ]);
    r["outputs"] = json!({"input":0,"parameter":1,"literal":2,"where":4,"coalesce":5,"min":6,"sum":7,"equal":9});
    let p = program(r);
    for key in ["input", "parameter", "literal", "where", "coalesce", "min"] {
        assert_eq!(p.output_types()[key], "INTEGER");
    }
    assert_eq!(p.output_types()["sum"], "DECIMAL");
    let b = Arc::new(p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap());
    let mut state = ProgramInstance::new(b);
    let values = state.step(&input(0, Some("1"))).unwrap();
    for (key, want) in [
        ("input", 1),
        ("parameter", 2),
        ("literal", -3),
        ("where", 1),
        ("coalesce", 1),
        ("min", 1),
    ] {
        assert_eq!(values[key].record(), json!(want));
    }
    assert_eq!(values["sum"].record(), json!("3.000000000000"));
    assert_eq!(values["equal"].record(), json!(true));
    let before = state.capture();
    assert!(state.step(&input(1, Some("1.5"))).is_err());
    assert_eq!(state.capture(), before);
}
