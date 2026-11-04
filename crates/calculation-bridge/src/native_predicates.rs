//! Bounded Calculation consumer of native Predicate semantics; no Runtime grant.
use onlyalpha_calculation::product::{Definition, normalize_scalar};
use onlyalpha_predicates::{
    decimal_predicate::{DecimalLiteralPredicate, DecimalOperand, DecimalPredicate},
    predicate::Predicate,
};
use serde_json::{Value, json};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "NATIVE_PREDICATE_CALCULATION_INVALID";
const WORK: usize = 8 * 1024 * 1024;

#[derive(Clone, Debug)]
pub struct PredicateCalculation {
    definition: Definition,
}
fn decimal(v: &Value) -> Result<Option<DecimalOperand<'_>>> {
    if v.is_null() {
        return Ok(None);
    }
    DecimalOperand::parse(v.as_str().ok_or(INVALID)?)
        .map(Some)
        .map_err(|_| INVALID)
}
fn boolean(v: &Value) -> Result<Option<bool>> {
    if v.is_null() {
        Ok(None)
    } else {
        v.as_bool().map(Some).ok_or(INVALID)
    }
}
fn port(name: &str, data: &str, semantic: &str) -> Value {
    json!({"name":name,"data_type":data,"nullable":true,"dimensions":["TIME"],"semantic_type":semantic,"unit":null})
}
impl PredicateCalculation {
    /// Rematerialize the supported exact semantic-version 1 definitions. Other
    /// scalar families remain unavailable here rather than falling back to Python.
    pub fn resolve(
        type_id: &str,
        version: &str,
        parameters: &Value,
        bindings: &Value,
    ) -> Result<Self> {
        if version != "1"
            || parameters
                .to_string()
                .len()
                .saturating_add(bindings.to_string().len())
                > WORK
        {
            return Err(INVALID);
        }
        let mut parameters = parameters.as_object().ok_or(INVALID)?.clone();
        let (inputs, output) = if let Ok(p) = Predicate::resolve(type_id, version) {
            if !parameters.is_empty() {
                return Err(INVALID);
            }
            let inputs = if matches!(p, Predicate::And | Predicate::Or) {
                vec![
                    port("left", "BOOLEAN", "PREDICATE_VALUE"),
                    port("right", "BOOLEAN", "PREDICATE_VALUE"),
                ]
            } else {
                vec![port("value", "BOOLEAN", "PREDICATE_VALUE")]
            };
            let semantic = match p {
                Predicate::Eligibility => "ELIGIBILITY",
                Predicate::EntrySignal => "ENTRY_SIGNAL",
                Predicate::ExitSignal => "EXIT_SIGNAL",
                _ => "PREDICATE_VALUE",
            };
            (inputs, port("value", "BOOLEAN", semantic))
        } else if DecimalPredicate::resolve(type_id, version).is_ok() {
            if !parameters.is_empty() {
                return Err(INVALID);
            }
            (
                vec![
                    port("left", "DECIMAL", "PREDICATE_OPERAND"),
                    port("right", "DECIMAL", "PREDICATE_OPERAND"),
                ],
                port("value", "BOOLEAN", "PREDICATE_VALUE"),
            )
        } else {
            if parameters
                .keys()
                .any(|k| k != "literal" && k != "literal_left")
            {
                return Err(INVALID);
            }
            let literal = normalize_scalar(parameters.get("literal").ok_or(INVALID)?, WORK)
                .map_err(|_| INVALID)?;
            if literal["type"] != "DECIMAL" {
                return Err(INVALID);
            }
            let literal_left = parameters
                .entry("literal_left")
                .or_insert(json!({"type":"BOOLEAN","value":false}));
            if literal_left
                != &json!({"type":"BOOLEAN","value":literal_left["value"].as_bool().ok_or(INVALID)?})
            {
                return Err(INVALID);
            }
            DecimalLiteralPredicate::resolve(
                type_id,
                version,
                decimal(&literal["value"])?.ok_or(INVALID)?,
                literal_left["value"].as_bool().ok_or(INVALID)?,
            )
            .map_err(|_| INVALID)?;
            parameters.insert("literal".into(), literal);
            (
                vec![port("left", "DECIMAL", "PREDICATE_OPERAND")],
                port("value", "BOOLEAN", "PREDICATE_VALUE"),
            )
        };
        let record = json!({"schema_version":2,"kind":"PREDICATE","type_id":type_id,"semantic_version":version,"parameters":parameters,"inputs":inputs,"input_bindings":bindings,"outputs":[output],"warmup":{"minimum_observations":1,"ready_condition":"predicate operands are available","pre_ready_output":"NULL","initialization":"UPSTREAM"},"missing_values":"PROPAGATE","timestamp":"EVENT_TIME","numeric":{"representation":"BOOLEAN","precision":1,"output_quantum":null,"rounding":"CONTEXT"},"factor_kind":null,"extensions":{}});
        Ok(Self {
            definition: Definition::from_record(&record, WORK).map_err(|_| INVALID)?,
        })
    }
    pub fn from_record(record: &Value) -> Result<Self> {
        let parsed = Definition::from_record(record, WORK).map_err(|_| INVALID)?;
        let normalized = parsed.to_record();
        let result = Self::resolve(
            normalized["type_id"].as_str().ok_or(INVALID)?,
            normalized["semantic_version"].as_str().ok_or(INVALID)?,
            &normalized["parameters"],
            &normalized["input_bindings"],
        )?;
        if result.definition != parsed {
            return Err(INVALID);
        }
        Ok(result)
    }
    pub fn definition(&self) -> &Definition {
        &self.definition
    }
    /// A value projection of this actual adapter, not Runtime admission. The
    /// backend producer must separately prove this exact running ELF image.
    pub fn implementation_manifest(&self, backend: &str, image_sha256: &str) -> Result<Value> {
        if !matches!(backend, "RESEARCH" | "TRADING")
            || image_sha256.len() != 64
            || !image_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(INVALID);
        }
        let definition = self.definition.to_record();
        let resources =
            json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":image_sha256}]);
        let bundle = onlyalpha_strategy::record_fingerprint(&json!({
            "domain":"onlyalpha.calculation.implementation-bundle","schema_version":1,"resources":resources
        }));
        let mut identity = json!({
            "domain":"onlyalpha.calculation.implementation","schema_version":1,
            "calculation_type_reference":{"kind":"PREDICATE","type_id":definition["type_id"],"semantic_version":definition["semantic_version"]},
            "backend_kind":backend,
            "entrypoint_identity":"onlyalpha_calculation_bridge.native_predicates:PredicateCalculation.evaluate",
            "implementation_bundle_fingerprint":bundle,"semantic_dependencies":[]
        });
        let fingerprint = onlyalpha_strategy::record_fingerprint(&identity);
        identity.as_object_mut().ok_or(INVALID)?.remove("domain");
        identity["resources"] = resources;
        identity["implementation_fingerprint"] = json!(fingerprint);
        Ok(identity)
    }
    pub fn evaluate(&self, inputs: &Value) -> Result<Value> {
        if inputs.to_string().len() > WORK {
            return Err(INVALID);
        }
        let inputs = inputs.as_object().ok_or(INVALID)?;
        let record = self.definition.to_record();
        let bindings = record["input_bindings"].as_object().ok_or(INVALID)?;
        if inputs.keys().ne(bindings.keys()) {
            return Err(INVALID);
        }
        let type_id = record["type_id"].as_str().ok_or(INVALID)?;
        let value = if let Ok(p) = Predicate::resolve(type_id, "1") {
            let operands = inputs.values().map(boolean).collect::<Result<Vec<_>>>()?;
            p.evaluate(&operands).map_err(|_| INVALID)?
        } else if let Ok(p) = DecimalPredicate::resolve(type_id, "1") {
            let operands = inputs.values().map(decimal).collect::<Result<Vec<_>>>()?;
            p.evaluate(&operands).map_err(|_| INVALID)?
        } else {
            let parameters = &record["parameters"];
            let p = DecimalLiteralPredicate::resolve(
                type_id,
                "1",
                decimal(&parameters["literal"]["value"])?.ok_or(INVALID)?,
                parameters["literal_left"]["value"]
                    .as_bool()
                    .ok_or(INVALID)?,
            )
            .map_err(|_| INVALID)?;
            p.evaluate(&[decimal(inputs.get("left").ok_or(INVALID)?)?])
                .map_err(|_| INVALID)?
        };
        Ok(json!({"value":value}))
    }
}

/// Enumerate only the finite types actually supported by this compiled adapter.
/// No Python registration, Provider, Runtime grant or arbitrary type claim.
pub fn implementation_manifests(image_sha256: &str) -> Result<Vec<Value>> {
    let reference = json!({"node_fingerprint":"0".repeat(64),"output_name":"value","source":null});
    let mut nodes = Vec::new();
    for name in [
        "boolean.and",
        "boolean.or",
        "boolean.not",
        "terminal.eligibility",
        "terminal.entry_signal",
        "terminal.exit_signal",
    ] {
        let bindings = if matches!(name, "boolean.and" | "boolean.or") {
            json!({"left":reference,"right":reference})
        } else {
            json!({"value":reference})
        };
        nodes.push(PredicateCalculation::resolve(
            &format!("onlyalpha.predicate.internal.{name}"),
            "1",
            &json!({}),
            &bindings,
        )?);
    }
    for operation in ["eq", "ne", "lt", "le", "gt", "ge"] {
        nodes.push(PredicateCalculation::resolve(
            &format!("onlyalpha.predicate.internal.compare.{operation}.decimal.refs"),
            "1",
            &json!({}),
            &json!({"left":reference,"right":reference}),
        )?);
        nodes.push(PredicateCalculation::resolve(
            &format!("onlyalpha.predicate.internal.compare.{operation}.decimal.literal"),
            "1",
            &json!({"literal":{"type":"DECIMAL","value":"0"}}),
            &json!({"left":reference}),
        )?);
    }
    let mut result = Vec::new();
    for node in nodes {
        for backend in ["RESEARCH", "TRADING"] {
            result.push(node.implementation_manifest(backend, image_sha256)?);
        }
    }
    result.sort_by_key(|row| {
        (
            row["calculation_type_reference"]["type_id"]
                .as_str()
                .unwrap_or("")
                .to_owned(),
            row["backend_kind"].as_str().unwrap_or("").to_owned(),
        )
    });
    Ok(result)
}

#[cfg(test)]
mod native_manifest_tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn finite_native_manifests_bind_actual_adapter_entrypoint_and_entire_image() {
        let image = "a".repeat(64);
        let rows = implementation_manifests(&image).unwrap();
        assert_eq!(rows.len(), 36);
        let mut keys = BTreeSet::new();
        for row in &rows {
            assert_eq!(row["schema_version"], 1);
            assert_eq!(row["calculation_type_reference"]["kind"], "PREDICATE");
            assert_eq!(row["calculation_type_reference"]["semantic_version"], "1");
            assert!(matches!(
                row["backend_kind"].as_str(),
                Some("RESEARCH" | "TRADING")
            ));
            assert_eq!(
                row["entrypoint_identity"],
                "onlyalpha_calculation_bridge.native_predicates:PredicateCalculation.evaluate"
            );
            assert_eq!(
                row["resources"],
                json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":image}])
            );
            assert_eq!(row["semantic_dependencies"], json!([]));
            assert!(
                keys.insert((
                    row["calculation_type_reference"]["type_id"]
                        .as_str()
                        .unwrap()
                        .to_owned(),
                    row["backend_kind"].as_str().unwrap().to_owned()
                ))
            );
        }
        for type_id in [
            "onlyalpha.predicate.internal.boolean.and",
            "onlyalpha.predicate.internal.boolean.or",
            "onlyalpha.predicate.internal.boolean.not",
            "onlyalpha.predicate.internal.terminal.eligibility",
            "onlyalpha.predicate.internal.terminal.entry_signal",
            "onlyalpha.predicate.internal.terminal.exit_signal",
            "onlyalpha.predicate.internal.compare.eq.decimal.refs",
            "onlyalpha.predicate.internal.compare.ne.decimal.refs",
            "onlyalpha.predicate.internal.compare.lt.decimal.refs",
            "onlyalpha.predicate.internal.compare.le.decimal.refs",
            "onlyalpha.predicate.internal.compare.gt.decimal.refs",
            "onlyalpha.predicate.internal.compare.ge.decimal.refs",
            "onlyalpha.predicate.internal.compare.eq.decimal.literal",
            "onlyalpha.predicate.internal.compare.ne.decimal.literal",
            "onlyalpha.predicate.internal.compare.lt.decimal.literal",
            "onlyalpha.predicate.internal.compare.le.decimal.literal",
            "onlyalpha.predicate.internal.compare.gt.decimal.literal",
            "onlyalpha.predicate.internal.compare.ge.decimal.literal",
        ] {
            for backend in ["RESEARCH", "TRADING"] {
                assert!(
                    keys.contains(&(type_id.to_owned(), backend.to_owned())),
                    "{type_id} {backend}"
                );
            }
        }
        assert_eq!(implementation_manifests(&image).unwrap(), rows);
    }
    #[test]
    fn node_semantics_remain_separate_from_native_implementation_bytes() {
        let node = PredicateCalculation::resolve(
            "onlyalpha.predicate.internal.terminal.entry_signal", "1", &json!({}),
            &json!({"value":{"node_fingerprint":"b".repeat(64),"output_name":"value","source":null}}),
        ).unwrap();
        let original = node.definition().fingerprint();
        let a = node
            .implementation_manifest("RESEARCH", &"a".repeat(64))
            .unwrap();
        let b = node
            .implementation_manifest("RESEARCH", &"b".repeat(64))
            .unwrap();
        let trading = node
            .implementation_manifest("TRADING", &"a".repeat(64))
            .unwrap();
        assert_eq!(node.definition().fingerprint(), original);
        assert_ne!(
            a["implementation_fingerprint"],
            b["implementation_fingerprint"]
        );
        assert_ne!(
            a["implementation_fingerprint"],
            trading["implementation_fingerprint"]
        );
        assert_eq!(
            a["implementation_bundle_fingerprint"],
            "1c570bb3ae1b56f450e5bf64fa917ac63cd13a8df33aaa05b3b601426c2f7f87"
        );
        assert_eq!(
            a["implementation_fingerprint"],
            "5350fcd513eb40216cc5d531f34e68e2f08943a368e2400a921863f367084ecb"
        );
        assert_eq!(
            node.evaluate(&json!({"value":true})).unwrap(),
            json!({"value":true})
        );
        for invalid in ["".to_owned(), "A".repeat(64), "a".repeat(63)] {
            assert!(implementation_manifests(&invalid).is_err());
            assert!(node.implementation_manifest("RESEARCH", &invalid).is_err());
        }
        assert!(
            node.implementation_manifest("BACKTEST", &"a".repeat(64))
                .is_err()
        );
    }
}
