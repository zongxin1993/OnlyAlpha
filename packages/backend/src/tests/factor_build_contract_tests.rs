use super::*;
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
