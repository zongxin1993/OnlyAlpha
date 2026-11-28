//! Pure mathematical declarations; these values are not PG READY or Run grants.
use onlyalpha_calculation::program::Program;
use onlyalpha_calculation_bridge::{ImplementationArtifact, ProgramCalculation};
use serde_json::{Value, json};
use std::sync::Arc;
fn source() -> Value {
    json!({"factor_id":"private.factor.definition_test","semantic_version":"1","revision_fingerprint":"d".repeat(64),"factor_api_version":1,"factor_api_contract_fingerprint":"a".repeat(64),"input_contract":{"value":{"type":"DECIMAL","missing":true}},"output_contract":{"value":{"type":"DECIMAL","missing":true,"semantic_type":"FACTOR_VALUE"}}})
}
fn program() -> Program {
    Program::decode(json!({"schema_version":1,"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","inputs":{"value":{"type":"DECIMAL","role":"MARKET"}},"parameters":[{"name":"period","parameter_type":"INTEGER","required":false,"default":{"type":"INTEGER","value":2},"minimum":{"type":"INTEGER","value":1},"maximum":{"type":"INTEGER","value":100},"enum_values":[],"uppercase":false}],"nodes":[{"op":"input","name":"value"},{"op":"rolling_mean","args":[0],"period":{"parameter":"period"}}],"outputs":{"value":1}}).to_string().as_bytes()).unwrap()
}
fn resolved(period: u64, container: &str, artifact: &ImplementationArtifact) -> ProgramCalculation {
    let p = program();
    ProgramCalculation::resolve(
        &source(),
        Arc::new(
            p.bind(&p.resolve_parameters(&json!({"period":period})).unwrap())
                .unwrap(),
        ),
        container,
        artifact,
        &json!({"value":{"node_fingerprint":null,"output_name":"value","source":"bar.close"}}),
    )
    .unwrap()
}
#[test]
fn declaration_binds_real_ir_ports_parameters_warmup_numeric_and_implementation() {
    let artifact = ImplementationArtifact::new("bin/test-runner", &"f".repeat(64)).unwrap();
    let container = "c".repeat(64);
    let a = resolved(2, &container, &artifact);
    let b = resolved(3, &container, &artifact);
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
fn declarations_cannot_relabel_program_types() {
    let artifact = ImplementationArtifact::new("bin/test-runner", &"f".repeat(64)).unwrap();
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
            ProgramCalculation::resolve(&s, bound.clone(), &"c".repeat(64), &artifact, &bindings)
                .is_err()
        );
    }
}

#[test]
fn factor_manifest_binds_artifact_path_and_bytes_independently_of_program_container() {
    let path = "bin/test-runner";
    let digest = "f".repeat(64);
    let container = "c".repeat(64);
    let manifest = |container: &str, path: &str, digest: &str| {
        let artifact = ImplementationArtifact::new(path, digest).unwrap();
        resolved(2, container, &artifact)
            .implementation_manifest("TRADING")
            .unwrap()
    };
    let baseline = manifest(&container, path, &digest);
    assert_eq!(baseline, manifest(&container, path, &digest));
    assert_eq!(
        baseline["resources"],
        json!([{"relative_path":path,"byte_sha256":digest}])
    );

    let changed_digest = "e".repeat(64);
    for (other_path, other_digest) in [
        ("bin/other-runner", digest.as_str()),
        (path, changed_digest.as_str()),
    ] {
        let other = manifest(&container, other_path, other_digest);
        assert_eq!(
            other["resources"],
            json!([{"relative_path":other_path,"byte_sha256":other_digest}])
        );
        assert_ne!(
            baseline["implementation_bundle_fingerprint"],
            other["implementation_bundle_fingerprint"]
        );
        assert_ne!(
            baseline["implementation_fingerprint"],
            other["implementation_fingerprint"]
        );
    }

    let other_container = manifest(&"b".repeat(64), path, &digest);
    assert_eq!(
        baseline["implementation_bundle_fingerprint"],
        other_container["implementation_bundle_fingerprint"]
    );
    assert_ne!(
        baseline["implementation_fingerprint"],
        other_container["implementation_fingerprint"]
    );
}
