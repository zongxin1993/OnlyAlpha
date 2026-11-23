//! Pure mathematical declarations; these values are not PG READY or Run grants.
use onlyalpha_calculation::program::Program;
use onlyalpha_calculation_bridge::ProgramCalculation;
use serde_json::{Value, json};
use std::sync::Arc;
fn source() -> Value {
    json!({"factor_id":"private.factor.definition_test","semantic_version":"1","revision_fingerprint":"d".repeat(64),"factor_api_version":1,"factor_api_contract_fingerprint":"a".repeat(64),"input_contract":{"value":{"type":"DECIMAL","missing":true}},"output_contract":{"value":{"type":"DECIMAL","missing":true,"semantic_type":"FACTOR_VALUE"}}})
}
fn program() -> Program {
    Program::decode(json!({"schema_version":1,"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","inputs":{"value":{"type":"DECIMAL","role":"MARKET"}},"parameters":[{"name":"period","parameter_type":"INTEGER","required":false,"default":{"type":"INTEGER","value":2},"minimum":{"type":"INTEGER","value":1},"maximum":{"type":"INTEGER","value":100},"enum_values":[],"uppercase":false}],"nodes":[{"op":"input","name":"value"},{"op":"rolling_mean","args":[0],"period":{"parameter":"period"}}],"outputs":{"value":1}}).to_string().as_bytes()).unwrap()
}
fn resolved(period: u64) -> ProgramCalculation {
    let p = program();
    ProgramCalculation::resolve(
        &source(),
        Arc::new(
            p.bind(&p.resolve_parameters(&json!({"period":period})).unwrap())
                .unwrap(),
        ),
        &"c".repeat(64),
        &"f".repeat(64),
        &json!({"value":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}}),
    )
    .unwrap()
}
#[test]
fn declaration_binds_real_ir_ports_parameters_warmup_numeric_and_implementation() {
    let a = resolved(2);
    let b = resolved(3);
    let d = a.definition().to_record();
    assert_eq!(d["kind"], "FACTOR");
    assert_eq!(d["numeric"]["precision"], 28);
    assert_eq!(d["warmup"]["minimum_observations"], 2);
    assert_eq!(d["outputs"][0]["semantic_type"], "FACTOR_VALUE");
    assert_ne!(a.definition().fingerprint(), b.definition().fingerprint());
    assert_eq!(
        a.implementation_manifest("TRADING").unwrap(),
        b.implementation_manifest("TRADING").unwrap(),
        "exact parameter certificates are separate from implementation identity"
    );
    a.type_declaration()
        .unwrap()
        .validate_candidate(&d, 8 * 1024 * 1024)
        .unwrap();
    assert_ne!(
        a.implementation_manifest("RESEARCH").unwrap(),
        a.implementation_manifest("TRADING").unwrap()
    );
}
#[test]
fn declarations_cannot_relabel_program_types_or_unbind_code_artifacts() {
    let p = program();
    let bound = Arc::new(p.bind(&p.resolve_parameters(&json!({})).unwrap()).unwrap());
    let bindings =
        json!({"value":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}});
    for output in [false, true] {
        let mut s = source();
        s[if output {
            "output_contract"
        } else {
            "input_contract"
        }]["value"]["type"] = json!("BOOLEAN");
        assert!(
            ProgramCalculation::resolve(
                &s,
                bound.clone(),
                &"c".repeat(64),
                &"f".repeat(64),
                &bindings
            )
            .is_err()
        );
    }
    let a = resolved(2).implementation_manifest("TRADING").unwrap();
    for (container, image) in [
        ("b".repeat(64), "f".repeat(64)),
        ("c".repeat(64), "e".repeat(64)),
    ] {
        let other =
            ProgramCalculation::resolve(&source(), bound.clone(), &container, &image, &bindings)
                .unwrap();
        assert_ne!(a, other.implementation_manifest("TRADING").unwrap());
    }
}
