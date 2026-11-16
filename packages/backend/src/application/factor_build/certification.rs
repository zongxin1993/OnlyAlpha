//! Deterministic controlled cases, never market observations or Research results.
use super::*;
use bigdecimal::BigDecimal as Decimal;
use onlyalpha_calculation::program::{ProgramInput, ProgramInstance, ProgramValue, evaluate_batch};
use std::{
    collections::{BTreeMap, BTreeSet},
    str::FromStr,
    time::Instant,
};
pub(super) fn policy() -> Value {
    json!({"contract":"NATIVE_FACTOR_EXACT_CERTIFICATION_V1","numeric_policy":NUMERIC_POLICY,"max_rows":4096,"max_work":2000000,"cases":["NATIVE_NUMERIC_GOLDEN","NULL_WARMUP_BOUNDARY","BATCH_EVENT_EVERY_POINT","PREFIX_CAUSALITY","RESTORE_SUFFIX","ISOLATED_INSTANCE"],"whole_parameter_domain":false})
}
pub(super) fn signature(source: &Value, program: &Program) -> Result<()> {
    let inputs = source["input_contract"]
        .as_object()
        .ok_or(BuildError::Invalid)?;
    let actual = program.record()["inputs"]
        .as_object()
        .ok_or(BuildError::Invalid)?
        .clone();
    if inputs.len() != actual.len()
        || inputs.iter().any(|(name, v)| {
            actual.get(name).is_none_or(|a| {
                a["type"] != v["type"]
                    || a["role"].as_str() != Some(v["role"].as_str().unwrap_or("MARKET"))
            })
        })
    {
        return Err(BuildError::Failed("FACTOR_INPUT_CONTRACT"));
    }
    let specs = source["parameter_contract"]
        .as_object()
        .ok_or(BuildError::Invalid)?;
    let scalar = |kind: &Value, value: &Value| -> Result<Value> {
        onlyalpha_calculation::product::normalize_scalar(
            &json!({"type":kind,"value":value}),
            1000000,
        )
        .map_err(calc)
    };
    let mut expected = Vec::new();
    for (name, spec) in specs {
        let required = spec.get("required").map_or(
            Ok(!spec
                .as_object()
                .ok_or(BuildError::Invalid)?
                .contains_key("default")),
            |v| v.as_bool().ok_or(BuildError::Invalid),
        )?;
        if required && spec.get("default").is_some() {
            return Err(BuildError::Failed("FACTOR_PARAMETER_CONTRACT"));
        }
        let kind = &spec["type"];
        let bound = |key: &str| -> Result<Value> {
            if spec[key].is_null() {
                Ok(Value::Null)
            } else {
                scalar(kind, &spec[key])
            }
        };
        let enums = spec.get("enum_values").map_or(Ok(Vec::new()), |v| {
            v.as_array()
                .ok_or(BuildError::Invalid)
                .and_then(|a| a.iter().map(|v| scalar(kind, v)).collect())
        })?;
        expected.push(json!({"name":name,"parameter_type":kind,"required":required,"default":if required{Value::Null}else{scalar(kind,&spec["default"])?},"minimum":bound("minimum")?,"maximum":bound("maximum")?,"enum_values":enums,"uppercase":false}));
    }
    if json!(expected) != program.record()["parameters"] {
        return Err(BuildError::Failed("FACTOR_PARAMETER_CONTRACT"));
    }
    for contract in [&source["input_contract"], &source["output_contract"]] {
        for spec in contract.as_object().ok_or(BuildError::Invalid)?.values() {
            for key in ["nullable", "missing"] {
                if spec.get(key).is_some_and(|v| !v.is_boolean()) {
                    return Err(BuildError::Invalid);
                }
            }
            if spec.get("nullable").is_some()
                && spec.get("missing").is_some()
                && spec["nullable"] != spec["missing"]
            {
                return Err(BuildError::Invalid);
            }
        }
    }
    let outputs = source["output_contract"]
        .as_object()
        .ok_or(BuildError::Invalid)?;
    let types = program.output_types();
    if outputs.len() != types.len()
        || outputs
            .iter()
            .any(|(k, v)| types.get(k.as_str()).is_none_or(|t| v["type"] != *t))
    {
        return Err(BuildError::Failed("FACTOR_OUTPUT_CONTRACT"));
    }
    Ok(())
}
fn encoded(rows: &[BTreeMap<String, ProgramValue>]) -> Value {
    json!(
        rows.iter()
            .map(|r| r
                .iter()
                .map(|(k, v)| (k.clone(), v.record()))
                .collect::<BTreeMap<_, _>>())
            .collect::<Vec<_>>()
    )
}
fn numeric_golden() -> Result<()> {
    for (op, a, b, want) in [
        ("add", "1.0000000000005", "0", Some("1")),
        ("add", "-1.0000000000015", "0", Some("-1.000000000002")),
        ("div", "1", "3", Some("0.333333333333")),
        ("div", "1", "0", None),
    ] {
        let record = json!({"schema_version":1,"numeric_policy":NUMERIC_POLICY,"inputs":{},"parameters":[],"nodes":[{"op":"literal","type":"DECIMAL","value":a},{"op":"literal","type":"DECIMAL","value":b},{"op":op,"args":[0,1]}],"outputs":{"value":2}});
        let p = Program::decode(record.to_string().as_bytes()).map_err(calc)?;
        let bound = p
            .bind(&p.resolve_parameters(&json!({})).map_err(calc)?)
            .map_err(calc)?;
        let actual = ProgramInstance::new(Arc::new(bound))
            .step(&ProgramInput::new("GOLDEN", 0, BTreeMap::new()).map_err(calc)?)
            .map_err(calc)?;
        let want = want.map_or(ProgramValue::Missing, |v| {
            ProgramValue::Decimal(Decimal::from_str(v).expect("literal golden"))
        });
        if actual["value"] != want {
            return Err(BuildError::Failed("FACTOR_NUMERIC_GOLDEN"));
        }
    }
    Ok(())
}
pub(super) fn certify(source: &Value, program: &BoundProgram, context: &str) -> Result<Value> {
    numeric_golden()?;
    let history = program.max_history();
    let n = history
        .checked_mul(2)
        .and_then(|n| n.checked_add(4))
        .map(|n| n.max(16))
        .filter(|n| *n <= 4096)
        .ok_or(BuildError::Failed("FACTOR_CERTIFICATION_BUDGET"))?;
    if program.certification_work(n).is_none_or(|w| w > 2000000) {
        return Err(BuildError::Failed("FACTOR_CERTIFICATION_BUDGET"));
    }
    let fields = source["input_contract"]
        .as_object()
        .ok_or(BuildError::Invalid)?;
    if n.checked_mul(fields.len()).is_none_or(|n| n > 1000000) {
        return Err(BuildError::Failed("FACTOR_CERTIFICATION_BUDGET"));
    }
    let inputs = (0..n)
        .map(|i| {
            let mut values = BTreeMap::new();
            for (j, (name, spec)) in fields.iter().enumerate() {
                let nullable = spec["nullable"]
                    .as_bool()
                    .or_else(|| spec["missing"].as_bool())
                    .unwrap_or(false);
                let v = if nullable && i == history + 2 {
                    ProgramValue::Missing
                } else if spec["type"] == "BOOLEAN" {
                    ProgramValue::Boolean(i % 2 == 0)
                } else {
                    ProgramValue::Decimal(Decimal::from(((i + j) % 11) as i64 - 2))
                };
                values.insert(name.clone(), v);
            }
            ProgramInput::new("FACTOR_CERTIFICATION", i as u64, values).map_err(calc)
        })
        .collect::<Result<Vec<_>>>()?;
    let started = Instant::now();
    let check = || {
        if started.elapsed() > Duration::from_secs(10) {
            Err(BuildError::Failed("FACTOR_CERTIFICATION_DEADLINE"))
        } else {
            Ok(())
        }
    };
    let batch = evaluate_batch(program, &inputs).map_err(calc)?;
    check()?;
    for row in &batch {
        for (k, v) in row {
            let spec = &source["output_contract"][k];
            let nullable = spec["nullable"]
                .as_bool()
                .or_else(|| spec["missing"].as_bool())
                .unwrap_or(false);
            if !nullable && matches!(v, ProgramValue::Missing) {
                return Err(BuildError::Failed("FACTOR_OUTPUT_CONTRACT"));
            }
        }
    }
    let mut event = ProgramInstance::new(Arc::new(program.clone()));
    let mut events = Vec::new();
    let split = n / 2;
    let mut snapshot = None;
    for (i, input) in inputs.iter().enumerate() {
        check()?;
        events.push(event.step(input).map_err(calc)?);
        if i + 1 == split {
            snapshot = Some(event.capture());
        }
    }
    if batch != events {
        return Err(BuildError::Failed("FACTOR_BATCH_EVENT_MISMATCH"));
    }
    let cuts = BTreeSet::from([0, 1, history.saturating_sub(1), history, split, n - 1]);
    for cut in &cuts {
        check()?;
        if evaluate_batch(program, &inputs[..*cut]).map_err(calc)? != batch[..*cut] {
            return Err(BuildError::Failed("FACTOR_CAUSAL_PREFIX_MISMATCH"));
        }
    }
    let mut restored = ProgramInstance::new(Arc::new(program.clone()));
    restored
        .restore(&snapshot.ok_or(BuildError::Invalid)?)
        .map_err(calc)?;
    let suffix = inputs[split..]
        .iter()
        .map(|i| restored.step(i).map_err(calc))
        .collect::<Result<Vec<_>>>()?;
    if suffix != batch[split..] {
        return Err(BuildError::Failed("FACTOR_RESTORE_MISMATCH"));
    }
    let isolated = ProgramInstance::new(Arc::new(program.clone()));
    if isolated.capture()["next_sequence"] != 0 || !isolated.capture()["instrument"].is_null() {
        return Err(BuildError::Failed("FACTOR_INSTANCE_ISOLATION"));
    }
    Ok(
        json!({"producer":"NATIVE_SHARED_PROGRAM_CERTIFIER_V1","environment":context,"rows":n,"required_history":history,"prefix_checks":cuts,"input_fingerprint":fp(&json!(inputs.iter().map(|r|r.values().iter().map(|(k,v)|(k.clone(),v.record())).collect::<BTreeMap<_,_>>()).collect::<Vec<_>>()))?,"batch_fingerprint":fp(&encoded(&batch))?,"event_fingerprint":fp(&encoded(&events))?,"restore_suffix_fingerprint":fp(&encoded(&suffix))?,"state_schema_version":1}),
    )
}
pub(super) fn valid_evidence(v: &Value, context: &str) -> bool {
    let expected = [
        "producer",
        "environment",
        "rows",
        "required_history",
        "prefix_checks",
        "input_fingerprint",
        "batch_fingerprint",
        "event_fingerprint",
        "restore_suffix_fingerprint",
        "state_schema_version",
    ];
    v.as_object()
        .is_some_and(|m| m.len() == expected.len() && expected.iter().all(|k| m.contains_key(*k)))
        && v["producer"] == "NATIVE_SHARED_PROGRAM_CERTIFIER_V1"
        && v["environment"] == context
        && v["rows"].as_u64().is_some_and(|n| (16..=4096).contains(&n))
        && v["required_history"]
            .as_u64()
            .is_some_and(|n| n > 0 && Some(n) <= v["rows"].as_u64())
        && v["state_schema_version"] == 1
        && v["batch_fingerprint"] == v["event_fingerprint"]
        && [
            "input_fingerprint",
            "batch_fingerprint",
            "event_fingerprint",
            "restore_suffix_fingerprint",
        ]
        .iter()
        .all(|k| {
            v[*k].as_str().is_some_and(|s| {
                s.len() == 64
                    && s.bytes()
                        .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            })
        })
        && v["prefix_checks"].as_array().is_some_and(|a| {
            !a.is_empty()
                && a.len() <= 6
                && a.iter()
                    .all(|n| n.as_u64().is_some_and(|n| Some(n) < v["rows"].as_u64()))
        })
}

#[cfg(test)]
#[path = "../../tests/factor_build_contract_tests.rs"]
mod tests;
