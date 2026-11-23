use super::*;
#[test]
fn exact_certificate_checks_nonnullable_outputs_during_executed_warmup() {
    let raw = json!({"schema_version":1,"numeric_policy":NUMERIC_POLICY,"inputs":{"close":{"type":"DECIMAL","role":"MARKET"}},"parameters":[],"nodes":[{"op":"input","name":"close"},{"op":"rolling_mean","args":[0],"period":2}],"outputs":{"value":1}});
    let program = Program::decode(raw.to_string().as_bytes()).unwrap();
    let bound = program
        .bind(&program.resolve_parameters(&json!({})).unwrap())
        .unwrap();
    let mut source = json!({"input_contract":{"close":{"type":"DECIMAL","missing":false}},"output_contract":{"value":{"type":"DECIMAL","nullable":true}}});
    assert!(certify(&source, &bound, &"a".repeat(64)).is_ok());
    source["output_contract"]["value"]["nullable"] = json!(false);
    assert!(matches!(
        certify(&source, &bound, &"a".repeat(64)),
        Err(BuildError::Failed("FACTOR_OUTPUT_CONTRACT"))
    ));
}
#[test]
fn source_contract_and_program_must_agree_on_roles_and_complete_parameter_schema() {
    let source = json!({"input_contract":{"close":{"type":"DECIMAL","role":"MARKET"}},"parameter_contract":{"period":{"type":"INTEGER","default":2}},"output_contract":{"value":{"type":"DECIMAL"}}});
    let raw = json!({"schema_version":1,"numeric_policy":NUMERIC_POLICY,"inputs":{"close":{"type":"DECIMAL","role":"MARKET"}},"parameters":[{"name":"period","parameter_type":"INTEGER","required":false,"default":{"type":"INTEGER","value":2},"minimum":null,"maximum":null,"enum_values":[],"uppercase":false}],"nodes":[{"op":"input","name":"close"}],"outputs":{"value":0}});
    let p = Program::decode(raw.to_string().as_bytes()).unwrap();
    assert!(signature(&source, &p).is_ok());
    let mut forged = raw.clone();
    forged["parameters"][0]["default"]["value"] = json!(3);
    let p = Program::decode(forged.to_string().as_bytes()).unwrap();
    assert!(signature(&source, &p).is_err());
    let mut forged = raw;
    forged["inputs"]["close"]["role"] = json!("FACTOR");
    let p = Program::decode(forged.to_string().as_bytes()).unwrap();
    assert!(signature(&source, &p).is_err());
}

// Pure manifest values only: this index cannot construct READY, a Run or Evidence.
fn retained_manifest_values_fixture() -> (Value, String, String) {
    let image = "c".repeat(64);
    let algorithm = "d".repeat(64);
    let raw = json!({"schema_version":1,"numeric_policy":NUMERIC_POLICY,"inputs":{"close":{"type":"DECIMAL","role":"MARKET"}},"parameters":[],"nodes":[{"op":"input","name":"close"}],"outputs":{"value":0}});
    let program = Program::decode(raw.to_string().as_bytes()).unwrap();
    let bound = program
        .bind(&program.resolve_parameters(&json!({})).unwrap())
        .unwrap();
    let metadata = json!({"factor_id":"private.factor.retained_values","semantic_version":"1","revision_fingerprint":"e".repeat(64),"factor_api_version":1,"factor_api_contract_fingerprint":"a".repeat(64),"input_contract":{"close":{"type":"DECIMAL","missing":false}},"output_contract":{"value":{"type":"DECIMAL","missing":false}}});
    let calculation = onlyalpha_calculation_bridge::ProgramCalculation::resolve(
        &metadata,
        Arc::new(bound),
        &"b".repeat(64),
        &image,
        &json!({"close":{"node_fingerprint":null,"output_name":"close","source":"bar.close"}}),
    )
    .unwrap();
    let node = json!({"definition":calculation.definition().to_record(),"definition_fingerprint":calculation.definition().fingerprint(),"implementations":[calculation.implementation_manifest("RESEARCH").unwrap(),calculation.implementation_manifest("TRADING").unwrap()]});
    (
        json!({"algorithm_resolution":{"contract":"ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1","native_execution":{"artifact":image},"algorithm_artifact":algorithm,"nodes":[node]}}),
        image,
        algorithm,
    )
}
#[test]
fn retained_factor_manifest_values_keep_exact_original_artifacts_and_body_association() {
    let (original, image, algorithm) = retained_manifest_values_fixture();
    let indexed = retained_factor_manifest_values(&original, &image, &algorithm).unwrap();
    assert_eq!(indexed.len(), 2);
    for body in original["algorithm_resolution"]["nodes"][0]["implementations"]
        .as_array()
        .unwrap()
    {
        assert_eq!(
            indexed.get(body["implementation_fingerprint"].as_str().unwrap()),
            Some(body)
        );
    }
    assert!(retained_factor_manifest_values(&original, &"f".repeat(64), &algorithm).is_err());
    assert!(retained_factor_manifest_values(&original, &image, &"f".repeat(64)).is_err());
    for field in [
        "backend_kind",
        "calculation_type_reference",
        "resources",
        "implementation_fingerprint",
    ] {
        let mut invalid = original.clone();
        invalid["algorithm_resolution"]["nodes"][0]["implementations"][0][field] = Value::Null;
        assert!(
            retained_factor_manifest_values(&invalid, &image, &algorithm).is_err(),
            "{field}"
        );
    }
    let mut reassociated = original.clone();
    let body = &mut reassociated["algorithm_resolution"]["nodes"][0]["implementations"][0];
    body["calculation_type_reference"]["type_id"] = json!("private.factor.other");
    let mut identity = body.clone();
    identity.as_object_mut().unwrap().remove("resources");
    identity
        .as_object_mut()
        .unwrap()
        .remove("implementation_fingerprint");
    identity["domain"] = json!("onlyalpha.calculation.implementation");
    body["implementation_fingerprint"] =
        json!(crate::application::factor_content::hash(&identity).unwrap());
    assert!(crate::application::research_admission::implementation_projection(body).is_ok());
    assert!(retained_factor_manifest_values(&reassociated, &image, &algorithm).is_err());
    let mut wrong_contract = original.clone();
    wrong_contract["algorithm_resolution"]["contract"] =
        json!("ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1");
    assert!(retained_factor_manifest_values(&wrong_contract, &image, &algorithm).is_err());
    let mut repeated = original.clone();
    let node = repeated["algorithm_resolution"]["nodes"][0].clone();
    repeated["algorithm_resolution"]["nodes"]
        .as_array_mut()
        .unwrap()
        .push(node);
    assert_eq!(
        retained_factor_manifest_values(&repeated, &image, &algorithm).unwrap(),
        indexed
    );
    let mut duplicate_role = original;
    let body = duplicate_role["algorithm_resolution"]["nodes"][0]["implementations"][0].clone();
    duplicate_role["algorithm_resolution"]["nodes"][0]["implementations"]
        .as_array_mut()
        .unwrap()
        .push(body);
    assert!(retained_factor_manifest_values(&duplicate_role, &image, &algorithm).is_err());
    assert!(retained_factor_manifest_values(&json!({"algorithm_resolution":{"contract":"ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1"}}),&image,&algorithm).is_err());
    assert!(
        retained_factor_manifest_values(&json!({}), &image, &algorithm)
            .unwrap()
            .is_empty()
    );
}
