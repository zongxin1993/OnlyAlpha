use onlyalpha_calculation::product::{Error, TypeDeclaration};
use serde_json::{Value, json};
const WORK: usize = 1024 * 1024;
fn sample() -> Value {
    json!({
        "schema_version":1,
        "descriptor": {
            "kind":"INDICATOR","type_id":"example.indicator","semantic_version":"1",
            "parameters":[{"name":"label","parameter_type":"STRING","required":false,
                "default":"20","minimum":null,"maximum":null,
                "enum_values":["2.0",2,true,"2","2E+1","20"],"uppercase":false}],
            "inputs":[],"outputs":[{"name":"value","data_type":"DECIMAL","nullable":true,
                "dimensions":["TIME"],"semantic_type":"NUMERIC_SERIES","unit":null}],
            "missing_values":"FAIL","timestamp":"EVENT_TIME",
            "numeric":{"representation":"DECIMAL","precision":28,"output_quantum":null,"rounding":"CONTEXT"},
            "factor_kind":null,"execution_shape":"TIME_SERIES","semantic_bounds":{"value":null}
        },
        "parameter_values":[{"default":{"type":"DECIMAL","value":"2E+1"},
            "minimum":{"type":"NULL","value":null},"maximum":{"type":"NULL","value":null},
            "enum_values":[{"type":"DECIMAL","value":"2.0"},{"type":"INTEGER","value":2},
                {"type":"BOOLEAN","value":true},{"type":"STRING","value":"2"},
                {"type":"STRING","value":"2E+1"},{"type":"STRING","value":"20"}]}]
    })
}
#[test]
fn lossless_values_preserve_public_projection_without_a_new_product_identity() {
    let v = sample();
    let declaration = TypeDeclaration::from_record(&v, WORK).unwrap();
    assert_eq!(declaration.to_record(), v);
    assert_eq!(declaration.descriptor(), v["descriptor"]);
    let mut changed = v.clone();
    changed["parameter_values"][0]["default"]["value"] = json!("20");
    let other = TypeDeclaration::from_record(&changed, WORK).unwrap();
    assert_eq!(other.descriptor(), declaration.descriptor());
    assert_ne!(other, declaration);
    for (raw, projected) in [
        ("-0E-7", "-0.0000000"),
        ("1.2300E+5", "123000"),
        ("0E+2", "0"),
        ("-0.00", "-0.00"),
        ("-0E+999999999", "-0"),
        ("0E+999999999", "0"),
    ] {
        let mut v = sample();
        v["parameter_values"][0]["default"]["value"] = json!(raw);
        v["descriptor"]["parameters"][0]["default"] = json!(projected);
        let d = TypeDeclaration::from_record(&v, WORK).unwrap_or_else(|err| panic!("{raw}: {err}"));
        assert_eq!(d.to_record(), v);
    }
}
#[test]
fn mismatched_or_malformed_values_cannot_be_admitted_as_an_exact_declaration() {
    for (path, value) in [
        ("/schema_version", json!(true)),
        ("/descriptor/parameters/0/default", json!("2E+1")),
        (
            "/parameter_values/0/default",
            json!({"type":"DECIMAL","value":20}),
        ),
        ("/parameter_values/0/default/value", json!("NaN")),
        (
            "/parameter_values/0/enum_values/1",
            json!({"type":"INTEGER","value":true}),
        ),
        ("/parameter_values/0/enum_values/1/type", json!("BOOLEAN")),
        ("/parameter_values", json!([])),
        ("/descriptor/type_id", json!("Example.indicator")),
        ("/descriptor/outputs/0/nullable", json!(1)),
        ("/descriptor/semantic_bounds/value", json!(["0", "1"])),
        ("/descriptor/factor_kind", json!("TIME_SERIES")),
        ("/descriptor/execution_shape", json!("UNKNOWN")),
        ("/descriptor/parameters/0/name", json!("bad name")),
        ("/descriptor/parameters/0/required", json!(0)),
        ("/descriptor/parameters/0/uppercase", json!(0)),
    ] {
        let mut v = sample();
        *v.pointer_mut(path).unwrap() = value;
        assert_eq!(
            TypeDeclaration::from_record(&v, WORK),
            Err(Error::Invalid),
            "{path}"
        );
    }
    for path in [
        "",
        "/descriptor",
        "/descriptor/parameters/0",
        "/parameter_values/0",
        "/parameter_values/0/default",
    ] {
        let mut v = sample();
        v.pointer_mut(path)
            .unwrap()
            .as_object_mut()
            .unwrap()
            .insert("unknown".into(), json!(0));
        assert_eq!(
            TypeDeclaration::from_record(&v, WORK),
            Err(Error::Invalid),
            "{path}"
        );
    }
}
#[test]
fn original_schema_rules_keep_required_defaults_duplicate_enums_and_bound_types() {
    let mut v = sample();
    // Required parameters may declare a default; it is not an implicit default.
    v["descriptor"]["parameters"][0]["required"] = json!(true);
    assert!(TypeDeclaration::from_record(&v, WORK).is_ok());
    let mut v = sample();
    for field in ["default", "minimum", "maximum"] {
        v["parameter_values"][0][field] = json!({"type":"NULL","value":null});
        v["descriptor"]["parameters"][0][field] = Value::Null;
    }
    assert_eq!(TypeDeclaration::from_record(&v, WORK), Err(Error::Invalid));
    v["descriptor"]["parameters"][0]["required"] = json!(true);
    assert!(TypeDeclaration::from_record(&v, WORK).is_ok());
    for (field, raw, projected) in [
        (
            "minimum",
            json!({"type":"DECIMAL","value":"2.0"}),
            json!("2.0"),
        ),
        ("maximum", json!({"type":"INTEGER","value":2}), json!(2)),
    ] {
        v["parameter_values"][0][field] = raw;
        v["descriptor"]["parameters"][0][field] = projected;
    }
    // Mixed exact Decimal/integer bound types are legitimate Product semantics.
    assert!(TypeDeclaration::from_record(&v, WORK).is_ok());
    v["parameter_values"][0]["maximum"]["value"] = json!(1);
    v["descriptor"]["parameters"][0]["maximum"] = json!(1);
    assert_eq!(TypeDeclaration::from_record(&v, WORK), Err(Error::Invalid));
    let mut v = sample();
    v["descriptor"]["parameters"][0]["enum_values"] = json!([true, true]);
    v["parameter_values"][0]["enum_values"] =
        json!([{"type":"BOOLEAN","value":true},{"type":"BOOLEAN","value":true}]);
    assert!(TypeDeclaration::from_record(&v, WORK).is_ok());
}
#[test]
fn complete_declaration_and_decimal_projection_share_a_bounded_work_budget() {
    for budget in [0, 1, 50] {
        assert_eq!(
            TypeDeclaration::from_record(&sample(), budget),
            Err(Error::Unavailable)
        );
    }
    let mut v = sample();
    v["parameter_values"][0]["default"]["value"] = json!("1E+999999999");
    assert_eq!(
        TypeDeclaration::from_record(&v, WORK),
        Err(Error::Unavailable)
    );
}

fn candidate() -> Value {
    json!({"schema_version":2,"kind":"INDICATOR","type_id":"example.indicator","semantic_version":"1",
        "parameters":{"label":{"type":"STRING","value":"2E+1"}},"inputs":[],"input_bindings":{},
        "outputs":[{"name":"value","data_type":"DECIMAL","nullable":true,
            "dimensions":["TIME"],"semantic_type":"NUMERIC_SERIES","unit":null}],
        "warmup":{"minimum_observations":1,"ready_condition":"samples >= 1","pre_ready_output":"NULL","initialization":"first sample"},
        "missing_values":"FAIL","timestamp":"EVENT_TIME",
        "numeric":{"representation":"DECIMAL","precision":28,"output_quantum":null,"rounding":"CONTEXT"},
        "factor_kind":null,"extensions":{}})
}
#[test]
fn candidate_is_validated_against_the_lossless_schema_and_original_definition_two() {
    let declaration = TypeDeclaration::from_record(&sample(), WORK).unwrap();
    let v = candidate();
    let checked = declaration.validate_candidate(&v, WORK).unwrap();
    assert_eq!(checked.to_record(), v);
    assert_eq!(
        checked.fingerprint(),
        "ed5902d9c4cafaeaf69127d6d02754d15bb4b08d7f265946da44ac9eb5873edb"
    );
    for (path, value) in [
        ("/type_id", json!("example.other")),
        ("/semantic_version", json!("2")),
        ("/parameters/label", json!({"type":"INTEGER","value":2})),
        ("/parameters/label/value", json!("2.0")), // Decimal enum entry is not a string.
        ("/parameters", json!({})),
        (
            "/parameters",
            json!({"label":{"type":"STRING","value":"20"},"extra":{"type":"INTEGER","value":1}}),
        ),
        ("/schema_version", json!(3)),
    ] {
        let mut changed = v.clone();
        *changed.pointer_mut(path).unwrap() = value;
        assert_eq!(
            declaration.validate_candidate(&changed, WORK),
            Err(Error::Invalid),
            "{path}"
        );
    }
    // Generic resolver semantics can derive ports, warmup and extensions. These
    // are not Chart admission; the owning caller must enforce its own contract.
    let mut derived = v.clone();
    derived["warmup"]["minimum_observations"] = json!(37);
    derived["outputs"][0]["name"] = json!("derived");
    derived["extensions"] = json!({"algorithm":{"type":"STRING","value":"selected"}});
    assert_eq!(
        declaration
            .validate_candidate(&derived, WORK)
            .unwrap()
            .to_record(),
        derived
    );
}
#[test]
fn candidate_parameter_bounds_are_inclusive_and_enums_keep_python_numeric_equality() {
    let mut raw = sample();
    let spec = &mut raw["descriptor"]["parameters"][0];
    spec["parameter_type"] = json!("DECIMAL");
    spec["minimum"] = json!(false);
    spec["maximum"] = json!("2.00");
    spec["enum_values"] = json!([true, 2, "-0.00"]);
    let values = &mut raw["parameter_values"][0];
    values["minimum"] = json!({"type":"BOOLEAN","value":false});
    values["maximum"] = json!({"type":"DECIMAL","value":"2.00"});
    values["enum_values"] = json!([{"type":"BOOLEAN","value":true},{"type":"INTEGER","value":2},{"type":"DECIMAL","value":"-0.00"}]);
    let declaration = TypeDeclaration::from_record(&raw, WORK).unwrap();
    for (value, valid) in [
        ("0.00", true),
        ("-0.000", true),
        ("1.000", true),
        ("2.0", true),
        ("-0.01", false),
        ("1.5", false),
        ("2.01", false),
    ] {
        let mut v = candidate();
        v["parameters"]["label"] = json!({"type":"DECIMAL","value":value});
        assert_eq!(
            declaration.validate_candidate(&v, WORK).is_ok(),
            valid,
            "{value}"
        );
    }
    let mut v = candidate();
    v["parameters"]["label"] = json!({"type":"BOOLEAN","value":true});
    assert_eq!(
        declaration.validate_candidate(&v, WORK),
        Err(Error::Invalid)
    );
    for budget in [0, 1, 100] {
        assert_eq!(
            declaration.validate_candidate(&candidate(), budget),
            Err(Error::Unavailable)
        );
    }
}

#[test]
fn candidate_enum_comparisons_consume_the_same_cumulative_work_budget() {
    let mut raw = sample();
    raw["descriptor"]["parameters"][0]["enum_values"] = json!(vec!["x".repeat(1024); 32]);
    raw["parameter_values"][0]["enum_values"] =
        json!(vec![json!({"type":"STRING","value":"x".repeat(1024)}); 32]);
    let declaration = TypeDeclaration::from_record(&raw, WORK).unwrap();
    let mut v = candidate();
    v["parameters"]["label"]["value"] = json!("y".repeat(1024));
    assert_eq!(
        declaration.validate_candidate(&v, 80_000),
        Err(Error::Unavailable)
    );
    assert_eq!(
        declaration.validate_candidate(&v, WORK),
        Err(Error::Invalid)
    );
}
