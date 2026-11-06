//! Read the original official journal. This never creates/replays a Strategy,
//! recovers a pending suffix, advances its clock, delivers Events or invokes SDKs.
use crate::{
    Error, Inputs, NextOpenPolicy, RunSpec, boundary, err, fields, hash, next_open::NativeReplay,
};
use onlyalpha_clock::BigInt;
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_runtime::VerifiedReplaySnapshot;
use onlyalpha_strategy::{Program, Revision, Scope};
use serde_json::{Value, json};
use std::path::Path;
fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str, Error> {
    v[key].as_str().ok_or_else(|| err("TERMINAL_FIELD"))
}
fn count(v: &Value, key: &str) -> Result<u64, Error> {
    v[key].as_u64().ok_or_else(|| err("TERMINAL_COUNTER"))
}
fn time(v: &Value) -> Result<BigInt, Error> {
    let raw = v.as_str().ok_or_else(|| err("TERMINAL_TIME"))?;
    let n: BigInt = boundary(raw.parse())?;
    if n.to_string() != raw {
        return Err(err("TERMINAL_TIME"));
    }
    Ok(n)
}
fn control(v: &Value) -> Value {
    Value::Object(
        v.as_object()
            .into_iter()
            .flatten()
            .filter(|(k, _)| k.as_str() != "participants")
            .map(|(k, v)| (k.clone(), v.clone()))
            .collect(),
    )
}
fn program(binding: &Value, spec: &RunSpec, inputs: &Inputs) -> Result<(), Error> {
    let p = &binding["participants"];
    fields(
        p,
        &[
            "schema_version",
            "configuration",
            "generation",
            "initial_ns",
            "strategies",
            "sources",
            "program",
            "pipeline",
            "policy",
            "native_policy",
            "opening_profile",
        ],
    )?;
    let record = &p["program"];
    fields(
        record,
        &[
            "schema_version",
            "revision",
            "scope",
            "generation",
            "source",
            "artifact",
            "bindings",
        ],
    )?;
    let revision = boundary(Revision::from_record(&record["revision"]))?;
    let scope = Scope {
        engine: boundary(text(&record["scope"], "engine")?.parse())?,
        runtime: boundary(text(&record["scope"], "runtime")?.parse())?,
        cluster: boundary(text(&record["scope"], "cluster")?.parse())?,
    };
    let original = boundary(Program::new(
        revision,
        scope.clone(),
        text(record, "generation")?,
        text(record, "source")?,
        text(record, "artifact")?,
    ))?;
    let sources = inputs.record()["sources"]
        .as_array()
        .ok_or_else(|| err("TERMINAL_INPUTS"))?
        .iter()
        .map(|s| s["source"].clone())
        .collect::<Vec<_>>();
    if original.to_record() != *record
        || !original.revision().is_product_materialization()
        || p["schema_version"] != 1
        || p["configuration"] != hash(&spec.configuration)
        || p["generation"] != spec.configuration["generation"]
        || p["initial_ns"] != spec.initial_ns.to_string()
        || p["opening_profile"] != json!({"schema_version":1,"kind":"OPEN_CLOSE_V1"})
        || p["sources"] != json!(sources)
        || sources != vec![json!(original.source())]
        || scope.engine.value() != spec.configuration["engine"]
        || scope.runtime.value() != spec.configuration["runtime"]
        || original.generation() != spec.configuration["generation"]
        || spec.configuration["profiles"].as_object().map(|p| p.len()) != Some(1)
        || spec.configuration["profiles"][scope.cluster.value()]["revision"]
            != original.revision().fingerprint()
        || p["strategies"] != json!({scope.cluster.value():original.revision().fingerprint()})
        || p["policy"]["execution"] != spec.configuration
        || p["policy"]["schema_version"] != 2
    {
        return Err(err("TERMINAL_PROGRAM"));
    }
    for input in inputs.records() {
        if !original
            .revision()
            .universe()
            .contains(input.bar().instrument_id())
            || input.bar().bar_type().semantic() != original.revision().semantic()
        {
            return Err(err("TERMINAL_MARKET_SCOPE"));
        }
    }
    Ok(())
}
fn checkpoint_program_matches(
    checkpoint: &Value,
    program: &Value,
    legacy: u64,
    current: u64,
) -> bool {
    match checkpoint["schema_version"].as_u64() {
        Some(version) if version == legacy => {
            checkpoint.get("program") == Some(program)
                && checkpoint.get("program_fingerprint").is_none()
        }
        Some(version) if version == current => {
            checkpoint.get("program").is_none()
                && checkpoint.get("program_fingerprint") == Some(&json!(hash(program)))
        }
        _ => false,
    }
}
fn checkpoint(binding: &Value, state: &Value) -> Result<bool, Error> {
    let p = &binding["participants"];
    let checkpoint = &state["participants"];
    fields(
        checkpoint,
        &["schema_version", "binding", "preparation", "native", "now"],
    )?;
    let preparation = &checkpoint["preparation"];
    fields(
        preparation,
        &["schema_version", "pipeline", "strategy", "binding"],
    )?;
    if checkpoint["schema_version"] != 2
        || checkpoint["binding"] != binding["program"]
        || preparation["schema_version"] != 1
        || !checkpoint_program_matches(&preparation["strategy"], &p["program"], 1, 2)
        || !checkpoint_program_matches(&preparation["pipeline"], &p["pipeline"], 2, 3)
        || preparation["binding"]
            != json!({"pipeline":hash(&preparation["pipeline"]),"strategy":hash(&preparation["strategy"])})
        || checkpoint["now"].as_u64().map(|n| n.to_string())
            != state["clock_ns"].as_str().map(str::to_owned)
    {
        return Err(err("TERMINAL_CHECKPOINT_PROGRAM"));
    }
    NativeReplay::read_quiescent(&p["policy"], &p["native_policy"], &checkpoint["native"])
}
/// Only the actual read-only Runtime owner can construct this terminal view.
/// Its private source holds the original database inode through verification.
pub struct TerminalSnapshot {
    source: VerifiedReplaySnapshot,
    trace: Value,
    proof: Value,
    result: Value,
    state: Value,
    inputs: Value,
    replay_state: Value,
}
impl TerminalSnapshot {
    pub fn read(
        root: &Path,
        spec: RunSpec,
        inputs: &Inputs,
        resolve: impl FnOnce(&Value, &Value) -> Result<Box<dyn NextOpenPolicy>, Error>,
    ) -> Result<Self, Error> {
        let source =
            VerifiedReplaySnapshot::read(root, spec.configuration.clone(), &spec.kernel_artifact)?;
        let binding = source.binding();
        if binding["schema_version"] != 2 {
            return Err(err("HISTORICAL_TERMINAL_READER_UNAVAILABLE"));
        }
        if binding["work_id"] != spec.work_id
            || binding["configuration"] != hash(&spec.configuration)
            || binding["kernel_artifact"] != spec.kernel_artifact
            || binding["driver_artifact"] != spec.driver_artifact
            || binding["input_pin"] != inputs.fingerprint()
            || binding["initial_state"]["clock_ns"] != spec.initial_ns.to_string()
        {
            return Err(err("TERMINAL_BINDING"));
        }
        program(binding, &spec, inputs)?;
        let mut previous = binding["initial_state"].clone();
        if control(&previous)
            != json!({"schema_version":1,"cursor":0,"clock_ns":spec.initial_ns.to_string(),"status":"RUNNING","outcome":null,"phase":"OPEN","input_finished":false})
            || checkpoint(binding, &previous)?
        {
            return Err(err("TERMINAL_GENESIS"));
        }
        let mut stopped = false;
        for reference in source.refs() {
            let step = source.read_step(reference)?;
            let cause = &step["cause"];
            fields(cause, &["kind", "outcome", "processing"])?;
            let kind = text(cause, "kind")?;
            let mut expected = control(&previous);
            let cursor = count(&previous, "cursor")?;
            let active = matches!(previous["status"].as_str(), Some("RUNNING" | "PAUSED"));
            match kind {
                "OPEN" | "BAR" => {
                    if previous["status"] != "RUNNING"
                        || previous["input_finished"] != false
                        || cause["outcome"] != Value::Null
                    {
                        return Err(err("TERMINAL_INPUT_TRANSITION"));
                    }
                    let input = inputs
                        .records()
                        .get(usize::try_from(cursor).map_err(|_| err("BOUND"))?)
                        .ok_or_else(|| err("TERMINAL_INPUT_PREFIX"))?;
                    let (expected_input, clock, phase) = if kind == "OPEN" {
                        if previous["phase"] != "OPEN" {
                            return Err(err("TERMINAL_OPEN_ORDER"));
                        }
                        (
                            input.opening().record(),
                            input.opening().event_ns(),
                            "CLOSE",
                        )
                    } else {
                        if previous["phase"] != "CLOSE" {
                            return Err(err("TERMINAL_CLOSE_ORDER"));
                        }
                        expected["cursor"] = json!(cursor + 1);
                        (input.record(), input.event_ns(), "OPEN")
                    };
                    if cause["processing"]["input"] != expected_input
                        || clock < time(&previous["clock_ns"])?
                    {
                        return Err(err("TERMINAL_INPUT_SOURCE"));
                    }
                    expected["clock_ns"] = json!(clock.to_string());
                    expected["phase"] = json!(phase);
                }
                "INPUT_END" | "CANCEL_INPUT" => {
                    if !active
                        || previous["input_finished"] != false
                        || cause["outcome"] != Value::Null
                    {
                        return Err(err("TERMINAL_STOP"));
                    }
                    if kind == "INPUT_END" {
                        if cursor != inputs.records().len() as u64 || previous["phase"] != "OPEN" {
                            return Err(err("TERMINAL_EXHAUSTION"));
                        }
                    } else {
                        expected["input_cancelled"] = json!(true);
                        if cause["processing"]["reason"] != "USER_CANCELLED" {
                            return Err(err("TERMINAL_CANCEL_CAUSE"));
                        }
                    }
                    expected["input_finished"] = json!(true);
                    stopped = true;
                    if !cause["processing"]["signal"].is_null() {
                        let reason = if kind == "INPUT_END" {
                            "INPUT_EXHAUSTED"
                        } else {
                            "USER_CANCELLED"
                        };
                        if cause["processing"]["signal"]["status"] != "CANCELLED"
                            || cause["processing"]["signal"]["reason"] != reason
                        {
                            return Err(err("TERMINAL_SIGNAL_CAUSE"));
                        }
                    }
                }
                "PAUSE" | "RESUME" => {
                    let (from, to) = if kind == "PAUSE" {
                        ("RUNNING", "PAUSED")
                    } else {
                        ("PAUSED", "RUNNING")
                    };
                    if previous["status"] != from
                        || !cause["outcome"].is_null()
                        || !cause["processing"].is_null()
                    {
                        return Err(err("TERMINAL_PAUSE"));
                    }
                    expected["status"] = json!(to);
                }
                "TERMINATE" => {
                    let outcome = &cause["outcome"];
                    fields(outcome, &["schema_version", "status", "reason"])?;
                    if !active
                        || outcome["schema_version"] != 1
                        || !stopped
                        || previous["input_finished"] != true
                        || !cause["processing"].is_null()
                        || !checkpoint(binding, &previous)?
                    {
                        return Err(err("TERMINAL_DRAIN"));
                    }
                    match outcome["status"].as_str() {
                        Some("COMPLETED")
                            if cursor == inputs.records().len() as u64
                                && previous["phase"] == "OPEN"
                                && previous["input_cancelled"] != true
                                && outcome["reason"].is_null() => {}
                        Some("CANCELLED")
                            if previous["input_cancelled"] == true
                                && outcome["reason"] == "USER_CANCELLED" => {}
                        _ => return Err(err("TERMINAL_OUTCOME")),
                    }
                    expected["status"] = json!("TERMINATED");
                    expected["outcome"] = outcome.clone();
                }
                _ => return Err(err("TERMINAL_PROFILE")),
            }
            if !reference.ready() || control(&step["state"]) != expected {
                return Err(err("TERMINAL_DRIVER_SOURCE"));
            }
            checkpoint(binding, &step["state"])?;
            previous = step["state"].clone();
        }
        if previous["status"] != "TERMINATED" || !checkpoint(binding, &previous)? {
            return Err(err("TERMINAL_REQUIRED"));
        }
        crate::native_read::verify(
            &source,
            inputs,
            resolve(
                &binding["participants"]["policy"],
                &binding["participants"]["native_policy"],
            )?,
        )?;
        let state = source.state().clone();
        let outcome = &previous["outcome"];
        let manifest = json!({"schema_version":1,"configuration":hash(&spec.configuration),"kernel_artifact":spec.kernel_artifact,"input_pin":inputs.fingerprint(),"initial_time":OnlyTimestamp::from_unix_nanos(spec.initial_ns).to_record(),"final_time":OnlyTimestamp::from_unix_nanos(time(&previous["clock_ns"])?).to_record(),"inputs":source.records().iter().map(|r|hash(r.prepared().input())).collect::<Vec<_>>()});
        let result = source.backtest_result(&manifest, outcome)?.record();
        if result["run"]["status"] != outcome["status"]
            || result["orders"]
                .as_array()
                .ok_or_else(|| err("TERMINAL_ORDERS"))?
                .iter()
                .any(|order| {
                    !matches!(
                        order["snapshot"]["status"].as_str(),
                        Some("FILLED" | "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED")
                    )
                })
        {
            return Err(err("TERMINAL_OPEN_ORDER"));
        }
        let input_record = inputs.record();
        let logical_hash = crate::trace::fingerprint(|writer| {
            crate::trace::logical(
                writer,
                binding,
                &input_record,
                &previous,
                source.refs(),
                |reference| source.read_step(reference),
            )
        })?;
        let trace = crate::trace::value(|writer| match source.storage_version() {
            2 => crate::trace::logical(
                writer,
                binding,
                &input_record,
                &previous,
                source.refs(),
                |reference| source.read_step(reference),
            ),
            3 | 4 => crate::trace::encoded(
                writer,
                binding,
                &input_record,
                &previous,
                source.refs(),
                |reference, writer| source.write_encoded_step(reference, writer),
            ),
            _ => Err(err("TRACE_STORAGE_VERSION")),
        })?;
        let proof = json!({"schema_version":1,"completion_scope":"BACKTEST_REPLAY","binding":hash(binding),"market_exhausted":previous["cursor"]==inputs.records().len() as u64,"processed_prefix_verified":true,"drained":true,"status":result["run"]["status"],"source":logical_hash,"outcome":outcome,"execution_result":result});
        source.verify_cut()?;
        Ok(Self {
            source,
            trace,
            proof,
            result,
            state,
            inputs: input_record,
            replay_state: previous,
        })
    }
    /// Full physical archive: storage2 retains exact Trace1; storage3 is Trace2.
    pub fn trace(&self) -> &Value {
        &self.trace
    }
    pub fn encoded_trace(&self) -> Result<Value, Error> {
        self.verify_cut()?;
        Ok(self.trace.clone())
    }
    pub fn trace_metadata(&self) -> Result<Value, Error> {
        self.verify_cut()?;
        Ok(json!({"binding":self.source.binding(),"inputs":self.inputs,"state":self.replay_state}))
    }
    pub fn write_trace(&self, writer: &mut dyn std::io::Write) -> Result<(), Error> {
        self.verify_cut()?;
        crate::trace::logical(
            writer,
            self.source.binding(),
            &self.inputs,
            &self.replay_state,
            self.source.refs(),
            |reference| self.source.read_step(reference),
        )?;
        self.verify_cut()
    }
    pub fn for_each_step(
        &self,
        visit: &mut dyn FnMut(&Value, bool) -> Result<(), Error>,
    ) -> Result<(), Error> {
        self.source
            .for_each_step(|step, reference| visit(step, reference.ready()))
    }
    pub fn trace_fingerprint(&self) -> Result<String, Error> {
        crate::trace::fingerprint(|writer| self.write_trace(writer))
    }
    pub fn write_encoded_trace(&self, writer: &mut dyn std::io::Write) -> Result<(), Error> {
        self.verify_cut()?;
        match self.source.storage_version() {
            2 => crate::trace::bounded(writer, |writer| self.write_trace(writer))?,
            3 | 4 => crate::trace::encoded(
                writer,
                self.source.binding(),
                &self.inputs,
                &self.replay_state,
                self.source.refs(),
                |reference, writer| self.source.write_encoded_step(reference, writer),
            )?,
            _ => return Err(err("TRACE_STORAGE_VERSION")),
        }
        self.verify_cut()
    }
    pub fn verify_encoded_trace(&self, trace: &Value) -> Result<(), Error> {
        self.verify_cut()?;
        // The retained full archive was built only from this owner's actual
        // encoded rows; verify_cut freshly rechecks those same physical refs.
        if trace != &self.trace {
            return Err(err("TERMINAL_TRACE_SOURCE"));
        }
        self.verify_cut()
    }
    pub fn proof(&self) -> &Value {
        &self.proof
    }
    pub fn result(&self) -> &Value {
        &self.result
    }
    pub fn state(&self) -> &Value {
        &self.state
    }
    pub fn verify_cut(&self) -> Result<(), Error> {
        self.source.verify_cut()
    }
}

#[cfg(test)]
mod checkpoint_program_tests {
    use super::*;
    #[test]
    fn program_reference_reads_each_exact_codec_without_mixing_versions() {
        let program =
            json!({"schema_version":1,"generation":"a".repeat(64),"source":"b".repeat(64)});
        for (legacy, current) in [(1, 2), (2, 3)] {
            let original = json!({"schema_version":legacy,"program":program});
            let original_bytes = original.to_string();
            let original_hash = hash(&original);
            assert!(checkpoint_program_matches(
                &original, &program, legacy, current
            ));
            assert_eq!(original.to_string(), original_bytes);
            assert_eq!(hash(&original), original_hash);
            let reference = json!({"schema_version":current,"program_fingerprint":hash(&program)});
            assert!(checkpoint_program_matches(
                &reference, &program, legacy, current
            ));
            for mode in [
                "wrong_program",
                "legacy_with_reference",
                "current_with_inline",
                "unknown_version",
                "hybrid",
            ] {
                let mut invalid = reference.clone();
                match mode {
                    "wrong_program" => invalid["program_fingerprint"] = json!("f".repeat(64)),
                    "legacy_with_reference" => invalid["schema_version"] = json!(legacy),
                    "current_with_inline" => {
                        invalid
                            .as_object_mut()
                            .unwrap()
                            .remove("program_fingerprint");
                        invalid["program"] = program.clone();
                    }
                    "unknown_version" => invalid["schema_version"] = json!(current + 1),
                    _ => invalid["program"] = program.clone(),
                }
                assert!(
                    !checkpoint_program_matches(&invalid, &program, legacy, current),
                    "{mode}"
                );
            }
        }
    }
}
