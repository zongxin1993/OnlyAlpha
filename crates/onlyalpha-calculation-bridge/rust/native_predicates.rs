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
