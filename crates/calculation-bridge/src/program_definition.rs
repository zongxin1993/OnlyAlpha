//! Pure declarations over a decoded program. PostgreSQL readiness and asset
//! permissions remain the caller's responsibility; this module performs no I/O.
use onlyalpha_calculation::{
    product::{Definition, TypeDeclaration},
    program::BoundProgram,
};
use serde_json::{Value, json};
use std::sync::Arc;

type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "NATIVE_FACTOR_DECLARATION_INVALID";
const WORK: usize = 8 * 1024 * 1024;
fn sha(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
#[derive(Clone)]
pub struct ProgramCalculation {
    definition: Definition,
    program: Arc<BoundProgram>,
    dependencies: Value,
    image: String,
}
impl ProgramCalculation {
    /// `program_artifact` identifies the generic program container, never its
    /// parameter certificate. Callers authenticate both separately before use.
    pub fn resolve(
        metadata: &Value,
        program: Arc<BoundProgram>,
        program_artifact: &str,
        image: &str,
        bindings: &Value,
    ) -> Result<Self> {
        if !sha(program_artifact) || !sha(image) || metadata.to_string().len() > WORK {
            return Err(INVALID);
        }
        let ir = program.program().record();
        let ports = |key: &str, outputs: bool| -> Result<Vec<Value>> {
            let contracts = metadata[key].as_object().ok_or(INVALID)?;
            let actual = if outputs {
                program
                    .program()
                    .output_types()
                    .into_iter()
                    .map(|(k, v)| (k.to_owned(), json!({"type":v})))
                    .collect::<serde_json::Map<_, _>>()
            } else {
                ir["inputs"].as_object().ok_or(INVALID)?.clone()
            };
            if contracts.len() != actual.len() {
                return Err(INVALID);
            }
            contracts.iter().map(|(name, spec)| {
                if actual.get(name).is_none_or(|v| v["type"] != spec["type"])
                    || (!outputs && actual[name]["role"].as_str() != Some(spec["role"].as_str().unwrap_or("MARKET")))
                    || ["nullable","missing"].iter().any(|k|spec.get(*k).is_some_and(|v|!v.is_boolean()))
                    || (spec.get("nullable").is_some() && spec.get("missing").is_some() && spec["nullable"] != spec["missing"]) {
                    return Err(INVALID);
                }
                Ok(json!({"name":name,"data_type":spec["type"],"nullable":spec.get("nullable").or_else(||spec.get("missing")).cloned().unwrap_or(json!(false)),"dimensions":["TIME"],"semantic_type":spec.get("semantic_type").cloned().unwrap_or(json!(if outputs {"FACTOR_VALUE"} else {"NUMERIC_SERIES"})),"unit":spec.get("unit").cloned().unwrap_or(Value::Null)}))
            }).collect()
        };
        let record = json!({"schema_version":2,"kind":"FACTOR","type_id":metadata["factor_id"],"semantic_version":metadata["semantic_version"],"parameters":program.parameters().record(),"inputs":ports("input_contract",false)?,"input_bindings":bindings,"outputs":ports("output_contract",true)?,"warmup":{"minimum_observations":program.max_history(),"ready_condition":"complete inclusive declared window is available","pre_ready_output":"NULL","initialization":"UPSTREAM"},"missing_values":"PROPAGATE","timestamp":"EVENT_TIME","numeric":{"representation":"DECIMAL","precision":28,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"},"factor_kind":"TIME_SERIES","extensions":{}});
        let definition = Definition::from_record(&record, WORK).map_err(|_| INVALID)?;
        let api = metadata["factor_api_contract_fingerprint"]
            .as_str()
            .ok_or(INVALID)?;
        if !sha(api) || metadata["factor_api_version"] != 1 {
            return Err(INVALID);
        }
        let result = Self {
            definition,
            program,
            image: image.into(),
            dependencies: json!([{"kind":"FACTOR_PROGRAM_CONTAINER","fingerprint":program_artifact},{"kind":"FACTOR_API","version":1,"fingerprint":api},{"kind":"NUMERIC_POLICY","identity":"DECIMAL28_HALF_EVEN_Q12_V1"}]),
        };
        result
            .type_declaration()?
            .validate_candidate(&record, WORK)
            .map_err(|_| INVALID)?;
        Ok(result)
    }
    pub fn definition(&self) -> &Definition {
        &self.definition
    }
    pub fn type_declaration(&self) -> Result<TypeDeclaration> {
        let r = self.definition.to_record();
        let specs = self.program.program().record()["parameters"]
            .as_array()
            .ok_or(INVALID)?;
        let mut parameters = Vec::new();
        let mut values = Vec::new();
        for s in specs {
            let mut spec = s.clone();
            let mut tagged = serde_json::Map::new();
            for key in ["default", "minimum", "maximum"] {
                let value = if s[key].is_null() {
                    json!({"type":"NULL","value":null})
                } else {
                    s[key].clone()
                };
                spec[key] = value["value"].clone();
                tagged.insert(key.into(), value);
            }
            let enums = s["enum_values"].as_array().ok_or(INVALID)?;
            spec["enum_values"] =
                json!(enums.iter().map(|v| v["value"].clone()).collect::<Vec<_>>());
            tagged.insert("enum_values".into(), json!(enums));
            parameters.push(spec);
            values.push(Value::Object(tagged));
        }
        let bounds = r["outputs"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .map(|p| {
                Ok((
                    p["name"].as_str().ok_or(INVALID)?.to_owned(),
                    if p["semantic_type"] == "FACTOR_SCORE" {
                        json!(["0", "1"])
                    } else {
                        Value::Null
                    },
                ))
            })
            .collect::<Result<serde_json::Map<_, _>>>()?;
        TypeDeclaration::from_record(&json!({"schema_version":1,"descriptor":{"kind":r["kind"],"type_id":r["type_id"],"semantic_version":r["semantic_version"],"parameters":parameters,"inputs":r["inputs"],"outputs":r["outputs"],"missing_values":r["missing_values"],"timestamp":r["timestamp"],"numeric":r["numeric"],"factor_kind":r["factor_kind"],"execution_shape":"TIME_SERIES","semantic_bounds":bounds},"parameter_values":values}),WORK).map_err(|_|INVALID)
    }
    /// The caller must prove that `image` is the actual loaded executable.
    pub fn implementation_manifest(&self, backend: &str) -> Result<Value> {
        if !matches!(backend, "RESEARCH" | "TRADING") {
            return Err(INVALID);
        }
        let r = self.definition.to_record();
        let resources = json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":self.image}]);
        let bundle = onlyalpha_strategy::record_fingerprint(
            &json!({"domain":"onlyalpha.calculation.implementation-bundle","schema_version":1,"resources":resources}),
        );
        let mut identity = json!({"domain":"onlyalpha.calculation.implementation","schema_version":1,"calculation_type_reference":{"kind":"FACTOR","type_id":r["type_id"],"semantic_version":r["semantic_version"]},"backend_kind":backend,"entrypoint_identity":if backend=="RESEARCH" {"onlyalpha_calculation.program:evaluate_batch"} else {"onlyalpha_calculation.program:ProgramInstance.step"},"implementation_bundle_fingerprint":bundle,"semantic_dependencies":self.dependencies});
        let fp = onlyalpha_strategy::record_fingerprint(&identity);
        identity.as_object_mut().ok_or(INVALID)?.remove("domain");
        identity["resources"] = resources;
        identity["implementation_fingerprint"] = json!(fp);
        Ok(identity)
    }
}
