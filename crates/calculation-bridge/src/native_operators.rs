//! 原生算子的 Calculation 适配器。事件时间、标的顺序和准入由调用方负责。
use onlyalpha_calculation::product::{Definition, TypeDeclaration, normalize_scalar};
use onlyalpha_operators::algebra::{
    Decimal, Error as KernelError, Kernel, Operator, Parameters, Stream,
};
pub use onlyalpha_operators::registry::SEMANTIC_VERSION;
use onlyalpha_operators::registry::{OpSpec, StateCapability};
use serde_json::{Map, Value, json};
use std::{num::NonZeroUsize, str::FromStr};

type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "NATIVE_OPERATOR_CALCULATION_INVALID";
const WORK: usize = 8 * 1024 * 1024;
fn op_spec(type_id: &str) -> Result<&'static OpSpec> {
    onlyalpha_operators::registry::lookup(type_id).ok_or(INVALID)
}
fn operation(type_id: &str) -> Result<Operator> {
    op_spec(type_id).map(|spec| spec.operator)
}
fn port(name: &str) -> Value {
    json!({"name":name,"data_type":"DECIMAL","nullable":true,"dimensions":["TIME"],"semantic_type":"NUMERIC_SERIES","unit":null})
}
fn names(op: Operator) -> &'static [&'static str] {
    match op {
        Operator::RegressionResidual3 => &["response", "x1", "x2", "x3"],
        Operator::ConditionalBeta => &["response", "predictor", "condition"],
        Operator::CumProductIf => &["value", "condition"],
        Operator::GroupDemean => &["value", "group"],
        Operator::Pow => &["base", "exponent"],
        _ => match op.input_count() {
            3 => &["condition", "when_true", "when_false"],
            2 => &["left", "right"],
            _ => &["value"],
        },
    }
}
fn output_name(op: Operator) -> &'static str {
    match op {
        Operator::CrossSectionPercentile => "percentile",
        Operator::CrossSectionRank => "rank",
        Operator::CrossSectionZScore => "zscore",
        Operator::CrossSectionDemean => "demeaned",
        Operator::CrossSectionCorrelation => "correlation",
        _ => "value",
    }
}
fn numeric() -> Value {
    json!({"representation":"DECIMAL","precision":28,"output_quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"})
}
fn bounded(v: &Value) -> Result<()> {
    if v.to_string().len() > WORK {
        Err(INVALID)
    } else {
        Ok(())
    }
}
fn decimal(v: &Value, remaining: &mut usize) -> Result<Option<Decimal>> {
    if v.is_null() {
        return Ok(None);
    }
    let normalized = normalize_scalar(
        &json!({"type":"DECIMAL","value":v.as_str().ok_or(INVALID)?}),
        *remaining,
    )
    .map_err(|_| INVALID)?;
    let text = normalized["value"].as_str().ok_or(INVALID)?;
    *remaining = remaining.checked_sub(text.len()).ok_or(INVALID)?;
    Decimal::from_str(text).map(Some).map_err(|_| INVALID)
}
fn encoded(v: &Option<Decimal>) -> Value {
    v.as_ref()
        .map_or(Value::Null, |v| json!(v.to_plain_string()))
}
fn spec(
    name: &str,
    kind: &str,
    required: bool,
    default: Value,
    [minimum, maximum]: [Value; 2],
    choices: Value,
    uppercase: bool,
) -> Value {
    json!({"name":name,"parameter_type":kind,"required":required,"default":default,"minimum":minimum,"maximum":maximum,"enum_values":choices,"uppercase":uppercase})
}
fn parameter_specs(op: Operator) -> Vec<Value> {
    if op.needs_period() {
        let mut specs = vec![spec(
            "period",
            "INTEGER",
            true,
            Value::Null,
            [
                json!(op.minimum_period()),
                json!(onlyalpha_operators::algebra::MAX_WINDOW),
            ],
            json!([]),
            false,
        )];
        if op == Operator::SMA {
            specs.push(spec(
                "weight",
                "INTEGER",
                true,
                Value::Null,
                [json!(1), json!(onlyalpha_operators::algebra::MAX_WINDOW)],
                json!([]),
                false,
            ));
        }
        if op == Operator::RollingQuantile {
            specs.push(spec(
                "quantile",
                "DECIMAL",
                true,
                Value::Null,
                [json!("0"), json!("1")],
                json!([]),
                false,
            ));
        }
        specs
    } else if op == Operator::Scale {
        vec![spec(
            "factor",
            "DECIMAL",
            false,
            json!("1"),
            [Value::Null, Value::Null],
            json!([]),
            false,
        )]
    } else if op == Operator::CrossSectionPercentile {
        vec![
            spec(
                "direction",
                "STRING",
                false,
                json!("HIGHER_IS_BETTER"),
                [Value::Null, Value::Null],
                json!(["HIGHER_IS_BETTER", "LOWER_IS_BETTER"]),
                true,
            ),
            spec(
                "tie_method",
                "STRING",
                false,
                json!("AVERAGE"),
                [Value::Null, Value::Null],
                json!(["AVERAGE"]),
                true,
            ),
        ]
    } else {
        vec![]
    }
}
fn typed(kind: &Value, v: &Value) -> Value {
    json!({"type":if v.is_null() {json!("NULL")} else {kind.clone()},"value":v})
}

#[derive(Clone, Debug)]
pub struct OperatorCalculation {
    definition: Definition,
    kernel: Kernel,
}
impl OperatorCalculation {
    /// Accept the Product typed scalar map, normalize defaults and decimal text,
    /// then materialize the complete supported Definition rather than trust it.
    pub fn resolve(
        type_id: &str,
        version: &str,
        parameters: &Value,
        bindings: &Value,
    ) -> Result<Self> {
        bounded(parameters)?;
        bounded(bindings)?;
        if version != SEMANTIC_VERSION {
            return Err(INVALID);
        }
        let op = operation(type_id)?;
        let mut supplied = parameters.as_object().ok_or(INVALID)?.clone();
        let specs = parameter_specs(op);
        if supplied
            .keys()
            .any(|name| !specs.iter().any(|s| s["name"] == name.as_str()))
        {
            return Err(INVALID);
        }
        let mut normalized = Map::new();
        for s in &specs {
            let name = s["name"].as_str().ok_or(INVALID)?;
            let raw = supplied
                .remove(name)
                .unwrap_or_else(|| typed(&s["parameter_type"], &s["default"]));
            let mut scalar = normalize_scalar(&raw, WORK).map_err(|_| INVALID)?;
            if scalar["type"] != s["parameter_type"] {
                return Err(INVALID);
            }
            if s["uppercase"] == true {
                scalar["value"] = json!(scalar["value"].as_str().ok_or(INVALID)?.to_uppercase());
            }
            let choices = s["enum_values"].as_array().ok_or(INVALID)?;
            if !choices.is_empty() && !choices.contains(&scalar["value"]) {
                return Err(INVALID);
            }
            normalized.insert(name.to_owned(), scalar);
        }
        let mut params = Parameters::default();
        if op.needs_period() {
            let n = normalized["period"]["value"]
                .as_u64()
                .and_then(|n| usize::try_from(n).ok())
                .and_then(NonZeroUsize::new)
                .ok_or(INVALID)?;
            params.period = Some(n);
        }
        if op == Operator::SMA {
            params.weight = Some(
                normalized["weight"]["value"]
                    .as_u64()
                    .and_then(|n| usize::try_from(n).ok())
                    .and_then(NonZeroUsize::new)
                    .ok_or(INVALID)?,
            );
        }
        if op == Operator::RollingQuantile {
            let mut remaining = WORK;
            params.quantile = decimal(&normalized["quantile"]["value"], &mut remaining)?;
        }
        if op == Operator::Scale {
            let mut remaining = WORK;
            params.factor = decimal(&normalized["factor"]["value"], &mut remaining)?;
        }
        if op == Operator::CrossSectionPercentile {
            params.lower_is_better = normalized["direction"]["value"] == "LOWER_IS_BETTER";
        }
        let kernel = Kernel::new(op, params).map_err(|_| INVALID)?;
        let observations = u64::try_from(kernel.history_limit()).map_err(|_| INVALID)?;
        let period = normalized
            .get("period")
            .map_or(1, |v| v["value"].as_u64().unwrap_or(0));
        let ready = if matches!(op, Operator::RollingMean | Operator::CrossSectionPercentile) {
            if period > 1 {
                "complete declared input window is available"
            } else {
                "declared input is available"
            }
        } else if observations > 1 {
            "complete inclusive declared window is available"
        } else {
            "declared inputs are available"
        };
        let record = json!({"schema_version":2,"kind":"INDICATOR","type_id":type_id,"semantic_version":SEMANTIC_VERSION,"parameters":normalized,"inputs":names(op).iter().map(|n|port(n)).collect::<Vec<_>>(),"input_bindings":bindings,"outputs":[port(output_name(op))],"warmup":{"minimum_observations":observations,"ready_condition":ready,"pre_ready_output":"NULL","initialization":"UPSTREAM"},"missing_values":"PROPAGATE","timestamp":"EVENT_TIME","numeric":numeric(),"factor_kind":null,"extensions":{}});
        Ok(Self {
            definition: Definition::from_record(&record, WORK).map_err(|_| INVALID)?,
            kernel,
        })
    }
    pub fn from_record(record: &Value) -> Result<Self> {
        let parsed = Definition::from_record(record, WORK).map_err(|_| INVALID)?;
        let r = parsed.to_record();
        let candidate = Self::resolve(
            r["type_id"].as_str().ok_or(INVALID)?,
            r["semantic_version"].as_str().ok_or(INVALID)?,
            &r["parameters"],
            &r["input_bindings"],
        )?;
        if parsed != candidate.definition {
            return Err(INVALID);
        }
        Ok(candidate)
    }
    pub fn definition(&self) -> &Definition {
        &self.definition
    }
    pub fn checkpoint_schema_version(&self) -> Option<u64> {
        (self.state_capability() == "CHECKPOINTABLE").then_some(1)
    }
    pub fn state_capability(&self) -> &'static str {
        // This bridge advances scalar observations and cannot bind a complete event plane.
        if self.kernel.operator().is_cross_section() {
            return "RESEARCH_ONLY";
        }
        match self.kernel.operator().spec().state() {
            StateCapability::Stateless => "STATELESS",
            StateCapability::Checkpointable => "CHECKPOINTABLE",
        }
    }
    pub fn type_declaration(&self) -> Result<Value> {
        let r = self.definition.to_record();
        let specs = parameter_specs(self.kernel.operator());
        let values = specs.iter().map(|s| json!({"default":typed(&s["parameter_type"], &s["default"]),"minimum":typed(&s["parameter_type"], &s["minimum"]),"maximum":typed(&s["parameter_type"], &s["maximum"]),"enum_values":s["enum_values"].as_array().unwrap().iter().map(|v|typed(&s["parameter_type"], v)).collect::<Vec<_>>()})).collect::<Vec<_>>();
        let mut bounds = Map::new();
        bounds.insert(output_name(self.kernel.operator()).into(), Value::Null);
        let descriptor = json!({"kind":"INDICATOR","type_id":r["type_id"],"semantic_version":SEMANTIC_VERSION,"parameters":specs,"inputs":r["inputs"],"outputs":r["outputs"],"missing_values":"PROPAGATE","timestamp":"EVENT_TIME","numeric":numeric(),"factor_kind":null,"execution_shape":if self.kernel.operator().is_cross_section(){"CROSS_SECTION"}else{"TIME_SERIES"},"semantic_bounds":bounds});
        TypeDeclaration::from_record(
            &json!({"schema_version":1,"descriptor":descriptor,"parameter_values":values}),
            WORK,
        )
        .map(|v| v.to_record())
        .map_err(|_| INVALID)
    }
    fn input_columns(&self, inputs: &Value, arrays: bool) -> Result<Vec<Vec<Option<Decimal>>>> {
        bounded(inputs)?;
        let object = inputs.as_object().ok_or(INVALID)?;
        let ports = names(self.kernel.operator());
        if object.len() != ports.len() || ports.iter().any(|n| !object.contains_key(*n)) {
            return Err(INVALID);
        }
        let mut remaining = WORK;
        ports
            .iter()
            .map(|name| {
                if arrays {
                    object[*name]
                        .as_array()
                        .ok_or(INVALID)?
                        .iter()
                        .map(|v| decimal(v, &mut remaining))
                        .collect()
                } else {
                    Ok(vec![decimal(&object[*name], &mut remaining)?])
                }
            })
            .collect()
    }
    /// Evaluate one isolated observation. Use stream() for stateful Trading.
    /// Cross-section requires evaluate_batch with the complete bound plane.
    pub fn evaluate(&self, inputs: &Value) -> Result<Value> {
        if self.kernel.operator().is_cross_section() {
            return Err(INVALID);
        }
        let output = self
            .kernel
            .evaluate(&self.input_columns(inputs, false)?)
            .map_err(|_| INVALID)?;
        Ok(json!({(output_name(self.kernel.operator())):encoded(output.first().ok_or(INVALID)?)}))
    }
    /// Time-series columns or one complete canonical cross-section plane.
    pub fn evaluate_batch(&self, inputs: &Value) -> Result<Value> {
        self.evaluate_batch_controlled(inputs, || Ok(()))
    }
    /// The original process owner supplies cancellation/deadline checks. No
    /// additional clock, I/O, ownership state or retry policy lives here.
    pub fn evaluate_batch_controlled(
        &self,
        inputs: &Value,
        mut check: impl FnMut() -> Result<()>,
    ) -> Result<Value> {
        let columns = self.input_columns(inputs, true)?;
        let output = self
            .kernel
            .evaluate_controlled(&columns, || check().map_err(|_| KernelError::Interrupted))
            .map_err(|error| match error {
                KernelError::Interrupted => "NATIVE_OPERATOR_INTERRUPTED",
                _ => INVALID,
            })?;
        Ok(
            json!({(output_name(self.kernel.operator())):output.iter().map(encoded).collect::<Vec<_>>()}),
        )
    }
    pub fn stream(&self) -> Result<OperatorStream> {
        Ok(OperatorStream {
            calculation: self.clone(),
            stream: Stream::new(self.kernel.clone()).map_err(|_| INVALID)?,
        })
    }
    /// The producer must independently prove the actual running image digest.
    pub fn implementation_manifest(&self, backend: &str, image_sha256: &str) -> Result<Value> {
        if !matches!(backend, "RESEARCH" | "TRADING")
            || (backend == "TRADING" && self.kernel.operator().is_cross_section())
            || image_sha256.len() != 64
            || !image_sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
        {
            return Err(INVALID);
        }
        let record = self.definition.to_record();
        let resources =
            json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":image_sha256}]);
        let bundle = onlyalpha_strategy::record_fingerprint(
            &json!({"domain":"onlyalpha.calculation.implementation-bundle","schema_version":1,"resources":resources}),
        );
        let mut identity = json!({"domain":"onlyalpha.calculation.implementation","schema_version":1,"calculation_type_reference":{"kind":"INDICATOR","type_id":record["type_id"],"semantic_version":SEMANTIC_VERSION},"backend_kind":backend,"entrypoint_identity":if backend=="RESEARCH" {"onlyalpha_calculation_bridge.native_operators:OperatorCalculation.evaluate_batch"}else{"onlyalpha_calculation_bridge.native_operators:OperatorStream.push"},"implementation_bundle_fingerprint":bundle,"semantic_dependencies":[]});
        let fingerprint = onlyalpha_strategy::record_fingerprint(&identity);
        identity.as_object_mut().ok_or(INVALID)?.remove("domain");
        identity["resources"] = resources;
        identity["implementation_fingerprint"] = json!(fingerprint);
        Ok(identity)
    }
}

#[derive(Clone, Debug)]
pub struct OperatorStream {
    calculation: OperatorCalculation,
    stream: Stream,
}
impl OperatorStream {
    pub fn push(&mut self, inputs: &Value) -> Result<Value> {
        let columns = self.calculation.input_columns(inputs, false)?;
        let values = columns
            .into_iter()
            .map(|mut c| c.remove(0))
            .collect::<Vec<_>>();
        let value = self.stream.push(&values).map_err(|_| INVALID)?;
        Ok(json!({(output_name(self.calculation.kernel.operator())):encoded(&value)}))
    }
    pub fn checkpoint(&self) -> Result<Value> {
        if self.calculation.state_capability() != "CHECKPOINTABLE" {
            return Err(INVALID);
        }
        let mut windows = Map::new();
        for (name, values) in names(self.calculation.kernel.operator())
            .iter()
            .zip(self.stream.checkpoint())
        {
            windows.insert(
                (*name).into(),
                json!(values.iter().map(encoded).collect::<Vec<_>>()),
            );
        }
        let record = json!({"schema_version":1,"definition_fingerprint":self.calculation.definition.fingerprint(),"windows":windows});
        bounded(&record)?;
        Ok(record)
    }
    /// Validate into a fresh candidate; any error leaves this stream unchanged.
    pub fn restored_candidate(&self, checkpoint: &Value) -> Result<Self> {
        bounded(checkpoint)?;
        let object = checkpoint.as_object().ok_or(INVALID)?;
        if self.calculation.state_capability() != "CHECKPOINTABLE"
            || object.len() != 3
            || checkpoint["schema_version"] != 1
            || checkpoint["definition_fingerprint"] != self.calculation.definition.fingerprint()
            || !object.contains_key("windows")
        {
            return Err(INVALID);
        }
        let columns = self
            .calculation
            .input_columns(&checkpoint["windows"], true)?;
        let mut candidate = self.calculation.stream()?;
        candidate.stream.restore(columns).map_err(|_| INVALID)?;
        Ok(candidate)
    }
}
fn calculations() -> Result<Vec<OperatorCalculation>> {
    let reference = json!({"node_fingerprint":"0".repeat(64),"output_name":"value","source":null});
    onlyalpha_operators::registry::all()
        .iter()
        .map(|row| {
            let id = row.type_id();
            let op = row.operator;
            let mut bindings = Map::new();
            for n in names(op) {
                bindings.insert((*n).into(), reference.clone());
            }
            let mut parameters = Map::new();
            if op.needs_period() {
                parameters.insert(
                    "period".into(),
                    json!({"type":"INTEGER","value":op.minimum_period()}),
                );
            }
            if op == Operator::SMA {
                parameters.insert("weight".into(), json!({"type":"INTEGER","value":1}));
            }
            if op == Operator::RollingQuantile {
                parameters.insert("quantile".into(), json!({"type":"DECIMAL","value":"0.5"}));
            }
            OperatorCalculation::resolve(
                &id,
                SEMANTIC_VERSION,
                &Value::Object(parameters),
                &Value::Object(bindings),
            )
        })
        .collect()
}
pub fn implementation_manifests(image_sha256: &str) -> Result<Vec<Value>> {
    let mut rows = Vec::new();
    for calculation in calculations()? {
        for backend in ["RESEARCH", "TRADING"] {
            if backend == "TRADING" && calculation.kernel.operator().is_cross_section() {
                continue;
            }
            rows.push(calculation.implementation_manifest(backend, image_sha256)?);
        }
    }
    rows.sort_by_key(|r| {
        (
            r["calculation_type_reference"]["type_id"]
                .as_str()
                .unwrap_or("")
                .to_owned(),
            r["backend_kind"].as_str().unwrap_or("").to_owned(),
        )
    });
    Ok(rows)
}
/// Adapter inventory only; it does not grant Definition or Runtime admission.
pub fn catalog_rows(image_sha256: &str) -> Result<Vec<Value>> {
    let mut rows = Vec::new();
    for c in calculations()? {
        for backend in ["RESEARCH", "TRADING"] {
            if backend == "TRADING" && c.kernel.operator().is_cross_section() {
                continue;
            }
            let implementation = c.implementation_manifest(backend, image_sha256)?;
            rows.push(json!({"type_declaration":c.type_declaration()?,"backend_kind":backend,"implementation":implementation,"state_capability":if backend=="TRADING"{json!(c.state_capability())}else{Value::Null},"checkpoint_schema_version":if backend=="TRADING" && c.state_capability()=="CHECKPOINTABLE"{json!(1)}else{Value::Null}}));
        }
    }
    Ok(rows)
}

/// Shared source-owned native library projection. It binds current ELF bytes
/// through each manifest; the caller still proves the actual running image.
pub fn provider_record(image_sha256: &str, distribution_version: &str) -> Result<Value> {
    if distribution_version.is_empty()
        || distribution_version.len() > 255
        || distribution_version
            .chars()
            .any(|c| c.is_whitespace() || c.is_control())
    {
        return Err(INVALID);
    }
    let mut calculations = catalog_rows(image_sha256)?
        .into_iter()
        .map(|row| {
            json!({
                "type":row["type_declaration"]["descriptor"],
                "backend":row["backend_kind"],
                "implementation_fingerprint":row["implementation"]["implementation_fingerprint"],
                "state_capability":row["state_capability"],
                "checkpoint_schema_version":row["checkpoint_schema_version"]
            })
        })
        .collect::<Vec<_>>();
    calculations.sort_by_key(onlyalpha_strategy::record_fingerprint);
    let content_fingerprint = onlyalpha_strategy::record_fingerprint(&json!({
        "kind":"OPERATOR","calculations":calculations,"private_factor_snapshot":null
    }));
    Ok(json!({
        "manifest":{"schema_version":1,"provider_id":"onlyalpha.operator.library","provider_version":"8","kind":"OPERATOR",
            "source":{"kind":"DISTRIBUTION","distribution_name":"onlyalpha-backend","distribution_version":distribution_version}},
        "content_fingerprint":content_fingerprint,"calculations":calculations,"private_factor_snapshot":null
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn resolve(name: &str, parameters: Value) -> OperatorCalculation {
        let id = format!("onlyalpha.operator.{name}");
        let mut bindings = Map::new();
        for n in names(operation(&id).unwrap()) {
            bindings.insert(
                (*n).into(),
                json!({"node_fingerprint":"a".repeat(64),"output_name":"value","source":null}),
            );
        }
        OperatorCalculation::resolve(&id, SEMANTIC_VERSION, &parameters, &Value::Object(bindings))
            .unwrap()
    }
    #[test]
    fn inventory_is_exact_and_bound_to_current_image() {
        let all = calculations().unwrap();
        assert_eq!(all.len(), 43);
        assert_eq!(
            all.iter()
                .filter(|c| c.state_capability() == "STATELESS")
                .count(),
            10
        );
        assert_eq!(
            all.iter()
                .filter(|c| c.state_capability() == "CHECKPOINTABLE")
                .count(),
            26
        );
        assert_eq!(
            all.iter()
                .filter(|c| c.state_capability() == "RESEARCH_ONLY")
                .count(),
            7
        );
        for c in all {
            assert!(c.type_declaration().is_ok());
            let record = c.definition().to_record();
            let declaration =
                TypeDeclaration::from_record(&c.type_declaration().unwrap(), WORK).unwrap();
            assert_eq!(
                declaration.validate_candidate(&record, WORK).unwrap(),
                *c.definition()
            );
            assert_eq!(
                OperatorCalculation::from_record(&record)
                    .unwrap()
                    .definition(),
                c.definition()
            );
            assert_ne!(
                c.implementation_manifest("RESEARCH", &"a".repeat(64))
                    .unwrap()["implementation_fingerprint"],
                c.implementation_manifest("RESEARCH", &"b".repeat(64))
                    .unwrap()["implementation_fingerprint"]
            );
        }
        assert_eq!(implementation_manifests(&"a".repeat(64)).unwrap().len(), 79);
        assert_eq!(catalog_rows(&"a".repeat(64)).unwrap().len(), 79);
        assert!(implementation_manifests(&"A".repeat(64)).is_err());
    }
    #[test]
    fn rolling_statistics_preserve_their_parameters_and_checkpoint_identity() {
        let period = json!({"type":"INTEGER","value":3});
        let inputs = json!({"value":["2","4","2"]});
        for (name, quantile, expected) in [
            ("rolling_r_squared", None, "0.000000000000"),
            ("rolling_residual", None, "-0.666666666667"),
            ("rolling_arg_max", None, "2.000000000000"),
            ("rolling_arg_min", None, "1.000000000000"),
            ("rolling_quantile", Some("0"), "2.000000000000"),
            ("rolling_quantile", Some("0.75"), "3.000000000000"),
            ("rolling_quantile", Some("1"), "4.000000000000"),
        ] {
            let mut parameters = json!({"period":period});
            if let Some(q) = quantile {
                parameters["quantile"] = json!({"type":"DECIMAL","value":q});
            }
            let c = resolve(name, parameters);
            let expected = json!([null, null, expected]);
            assert_eq!(
                c.evaluate_batch(&inputs).unwrap()["value"],
                expected,
                "{name}"
            );
            let mut stream = c.stream().unwrap();
            for (i, input) in inputs["value"].as_array().unwrap().iter().enumerate() {
                stream = c
                    .stream()
                    .unwrap()
                    .restored_candidate(&stream.checkpoint().unwrap())
                    .unwrap();
                assert_eq!(
                    stream.push(&json!({"value":input})).unwrap()["value"],
                    expected[i],
                    "{name} at {i}"
                );
            }
        }

        let c = resolve(
            "rolling_quantile",
            json!({"period":period,"quantile":{"type":"DECIMAL","value":"0.5"}}),
        );
        let other = resolve(
            "rolling_quantile",
            json!({"period":period,"quantile":{"type":"DECIMAL","value":"0.75"}}),
        );
        let declaration = c.type_declaration().unwrap();
        let q = &declaration["descriptor"]["parameters"][1];
        assert_eq!(q["name"], "quantile");
        assert_eq!(q["minimum"], "0");
        assert_eq!(q["maximum"], "1");
        assert_eq!(q["required"], true);
        assert!(
            other
                .stream()
                .unwrap()
                .restored_candidate(&c.stream().unwrap().checkpoint().unwrap())
                .is_err()
        );
        let bindings = &c.definition().to_record()["input_bindings"];
        for invalid in [
            json!({"period":period}),
            json!({"period":period,"quantile":{"type":"STRING","value":"0.5"}}),
            json!({"period":period,"quantile":{"type":"DECIMAL","value":"-0.01"}}),
            json!({"period":period,"quantile":{"type":"DECIMAL","value":"1.01"}}),
        ] {
            assert!(
                OperatorCalculation::resolve(
                    "onlyalpha.operator.rolling_quantile",
                    SEMANTIC_VERSION,
                    &invalid,
                    bindings
                )
                .is_err(),
                "{invalid}"
            );
        }
    }
    #[test]
    fn conditional_product_checkpoint_preserves_both_ports() {
        let c = resolve("cum_product_if", json!({}));
        let values = [json!("2"), Value::Null, json!("9"), json!("3")];
        let conditions = ["1", "1", "0", "1"];
        let expected = json!(["2.000000000000", null, "2.000000000000", "6.000000000000"]);
        let batch = json!({"value":values,"condition":conditions});
        assert_eq!(c.evaluate_batch(&batch).unwrap()["value"], expected);
        let mut stream = c.stream().unwrap();
        for (i, value) in values.iter().enumerate() {
            let checkpoint = stream.checkpoint().unwrap();
            assert_eq!(checkpoint["windows"]["condition"], json!([]));
            stream = c.stream().unwrap().restored_candidate(&checkpoint).unwrap();
            let output = stream
                .push(&json!({"value":value,"condition":conditions[i]}))
                .unwrap();
            assert_eq!(output["value"], expected[i]);
        }
    }
    #[test]
    fn controlled_batch_interrupts_without_partial_result() {
        let c = resolve(
            "rolling_sum",
            json!({"period":{"type":"INTEGER","value":2}}),
        );
        let inputs = json!({"value":["1","2","3","4"]});
        let mut calls = 0;
        let interrupted = c.evaluate_batch_controlled(&inputs, || {
            calls += 1;
            if calls == 3 {
                Err("OWNER_CANCELLED")
            } else {
                Ok(())
            }
        });
        assert_eq!(interrupted, Err("NATIVE_OPERATOR_INTERRUPTED"));
        assert_eq!(calls, 3);
        assert_eq!(
            c.evaluate_batch_controlled(&inputs, || Ok(())).unwrap(),
            c.evaluate_batch(&inputs).unwrap()
        );
        assert_eq!(
            c.evaluate_batch_controlled(&inputs, || Err("OWNER_DEADLINE")),
            Err("NATIVE_OPERATOR_INTERRUPTED")
        );
        assert_eq!(
            c.evaluate_batch_controlled(&json!({"value":["NaN"]}), || Ok(())),
            Err(INVALID)
        );
        let cross = resolve("cross_section_rank", json!({}));
        assert_eq!(
            cross.evaluate_batch_controlled(&inputs, || Err("OWNER_CANCELLED")),
            Err("NATIVE_OPERATOR_INTERRUPTED")
        );
        assert_eq!(
            cross.evaluate_batch_controlled(&inputs, || Ok(())).unwrap(),
            cross.evaluate_batch(&inputs).unwrap()
        );
    }
    #[test]
    fn native_operators_and_shared_provider_have_exact_current_identity() {
        let c = resolve("scale", json!({}));
        assert_eq!(c.definition().to_record()["semantic_version"], "3");
        assert_eq!(
            c.evaluate(&json!({"value":"-0"})).unwrap()["value"],
            "0.000000000000"
        );
        let provider = provider_record(&"a".repeat(64), "0.9.0").unwrap();
        assert_eq!(
            provider["manifest"],
            json!({"schema_version":1,"provider_id":"onlyalpha.operator.library","provider_version":"8","kind":"OPERATOR","source":{"kind":"DISTRIBUTION","distribution_name":"onlyalpha-backend","distribution_version":"0.9.0"}})
        );
        let calculations = provider["calculations"].as_array().unwrap();
        assert_eq!(calculations.len(), 79);
        assert!(
            calculations
                .iter()
                .all(|row| row["type"]["semantic_version"] == "3")
        );
        let fingerprints = calculations
            .iter()
            .map(onlyalpha_strategy::record_fingerprint)
            .collect::<Vec<_>>();
        assert!(fingerprints.windows(2).all(|w| w[0] <= w[1]));
        assert_eq!(
            provider["content_fingerprint"],
            onlyalpha_strategy::record_fingerprint(
                &json!({"kind":"OPERATOR","calculations":calculations,"private_factor_snapshot":null})
            )
        );
        assert_ne!(
            provider["content_fingerprint"],
            provider_record(&"b".repeat(64), "0.9.0").unwrap()["content_fingerprint"]
        );
        assert!(provider_record(&"a".repeat(64), "").is_err());
        assert!(provider_record(&"A".repeat(64), "0.9.0").is_err());
    }
    #[test]
    fn typed_defaults_and_foreign_definition_are_checked() {
        let c = resolve("scale", json!({}));
        assert_eq!(
            c.definition().to_record()["parameters"]["factor"],
            json!({"type":"DECIMAL","value":"1"})
        );
        assert_eq!(
            c.evaluate(&json!({"value":"2"})).unwrap(),
            json!({"value":"2.000000000000"})
        );
        let mut foreign = c.definition().to_record();
        foreign["numeric"]["precision"] = json!(38);
        assert!(OperatorCalculation::from_record(&foreign).is_err());
        let mut foreign = c.definition().to_record();
        foreign["warmup"]["ready_condition"] = json!("foreign");
        assert!(OperatorCalculation::from_record(&foreign).is_err());
        let bindings = &c.definition().to_record()["input_bindings"];
        for params in [
            json!({"factor":{"type":"STRING","value":"2"}}),
            json!({"unknown":{"type":"INTEGER","value":1}}),
        ] {
            assert!(
                OperatorCalculation::resolve(
                    "onlyalpha.operator.scale",
                    SEMANTIC_VERSION,
                    &params,
                    bindings
                )
                .is_err()
            );
        }
        assert!(
            OperatorCalculation::resolve("onlyalpha.operator.scale", "2", &json!({}), bindings)
                .is_err()
        );
        assert!(
            OperatorCalculation::resolve(
                "onlyalpha.operator.scale_v2",
                SEMANTIC_VERSION,
                &json!({}),
                bindings
            )
            .is_err()
        );
        assert!(c.evaluate(&json!({"value":2})).is_err());
        assert!(c.evaluate(&json!({"value":"NaN"})).is_err());
        assert!(c.evaluate(&json!({"value":"1E+999999999"})).is_err());
        assert!(c.evaluate(&json!({"value":"1","extra":null})).is_err());
    }
    #[test]
    fn stream_batch_and_original_checkpoint_recovery_agree() {
        let c = resolve(
            "rolling_covariance",
            json!({"period":{"type":"INTEGER","value":2}}),
        );
        let left = [json!("1"), json!("2"), Value::Null, json!("4"), json!("6")];
        let right = [json!("2"), json!("4"), json!("6"), json!("8"), json!("12")];
        let batch = c
            .evaluate_batch(&json!({"left":left,"right":right}))
            .unwrap();
        let mut stream = c.stream().unwrap();
        let mut actual = Vec::new();
        for i in 0..left.len() {
            actual.push(
                stream
                    .push(&json!({"left":left[i],"right":right[i]}))
                    .unwrap()["value"]
                    .clone(),
            );
            stream = stream
                .restored_candidate(&stream.checkpoint().unwrap())
                .unwrap();
        }
        assert_eq!(batch["value"], json!(actual));
        let checkpoint = stream.checkpoint().unwrap();
        let mut invalid = checkpoint.clone();
        invalid["windows"]["right"] = json!([]);
        assert!(stream.restored_candidate(&invalid).is_err());
        assert_eq!(stream.checkpoint().unwrap(), checkpoint);
        invalid = checkpoint.clone();
        invalid["definition_fingerprint"] = json!("0".repeat(64));
        assert!(stream.restored_candidate(&invalid).is_err());
        invalid = checkpoint.clone();
        invalid["schema_version"] = json!(2);
        assert!(stream.restored_candidate(&invalid).is_err());
        invalid = checkpoint.clone();
        invalid["windows"]["left"] = json!(["1", "2", "3"]);
        invalid["windows"]["right"] = json!(["1", "2", "3"]);
        assert!(stream.restored_candidate(&invalid).is_err());
        assert!(stream.push(&json!({"left":"3","right":"NaN"})).is_err());
        assert_eq!(stream.checkpoint().unwrap(), checkpoint);
    }
    #[test]
    fn cross_section_is_research_only_and_keeps_population_nulls() {
        let c = resolve(
            "cross_section_percentile",
            json!({"direction":{"type":"STRING","value":"lower_is_better"}}),
        );
        assert_eq!(
            c.evaluate_batch(&json!({"value":["1",null,"3"]})).unwrap(),
            json!({"percentile":["1.000000000000",null,"0.000000000000"]})
        );
        assert!(c.stream().is_err());
        assert!(c.evaluate(&json!({"value":"1"})).is_err());
        assert!(
            c.implementation_manifest("TRADING", &"a".repeat(64))
                .is_err()
        );
        assert!(
            resolve("add", json!({}))
                .stream()
                .unwrap()
                .checkpoint()
                .is_err()
        );
    }
}
