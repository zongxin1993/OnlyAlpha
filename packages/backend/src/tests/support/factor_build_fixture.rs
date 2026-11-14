//! Only a test owner can publish these synthetic storage records.
use super::*;
use serde_json::json;
pub fn publication(revision: &str, source: &str, parameter: i64) -> BuildPublication {
    let program_raw=encode(&json!({"contract":"FACTOR_PROGRAM_CONTAINER_V1","source_sha256":digest(source.as_bytes()),"interface_fingerprint":"a".repeat(64),"builder_artifact":"b".repeat(64),"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","primitive_artifact":"c".repeat(64),"program_format":"STORAGE_FIXTURE_ONLY","body":{"fixture_only":true}}),8*1024*1024).unwrap();
    let program = StoredProgram {
        fingerprint: digest(program_raw.as_bytes()),
        payload: program_raw,
        source: digest(source.as_bytes()),
    };
    let parameters = encode(
        &json!({"period":{"type":"INTEGER","value":parameter}}),
        262144,
    )
    .unwrap();
    let raw=encode(&json!({"contract":"FACTOR_PARAMETER_CERTIFICATE_V1","revision_fingerprint":revision,"program_fingerprint":program.fingerprint,"parameters_fingerprint":digest(parameters.as_bytes()),"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","certifier_artifact":"d".repeat(64),"case_suite_fingerprint":"e".repeat(64),"evidence":{"storage_fixture_only":true}}),8*1024*1024).unwrap();
    BuildPublication {
        program,
        certificate: StoredCertificate {
            fingerprint: digest(raw.as_bytes()),
            payload: raw,
            parameters,
        },
    }
}
pub fn fingerprints(p: &BuildPublication) -> (&str, &str) {
    (&p.program.fingerprint, &p.certificate.fingerprint)
}
