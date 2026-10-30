//! Finite native Research execution. Only an owning admitted Run can reach this path.
//! Factor mathematics stays in the selected managed SDK; Research owns Target and Statistics.
use crate::application::{
    factor_content::hash,
    research_admission::{PreparationError, PreparedInputs},
    research_run::VerifiedRun,
    research_statistics::{self as statistics, Bindings, Observation, Plan},
};
use crate::persistence::research_dataset::Store as Datasets;
use crate::workers::algorithm::AlgorithmProcess;
use bigdecimal::num_bigint::{BigInt, Sign};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::{Value, json};
use std::{collections::BTreeMap, time::Duration};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_EXECUTION_INPUT_MISMATCH";
/// Exact rational (future/current - 1), rounded once to 1e-12, ties to even.
/// This is the native time-series Target method, not the legacy Target plugin ABI.
pub fn close_forward_return(current: &str, future: &str) -> Result<String> {
    let (_, a) = statistics::decimal(current)?;
    let (_, b) = statistics::decimal(future)?;
    if a.sign() != Sign::Plus || b.sign() != Sign::Plus {
        return Err("RESEARCH_TARGET_PRICE_INVALID");
    }
    let numerator = (b - &a) * BigInt::from(1_000_000_000_000u64);
    let mut q = numerator.magnitude() / a.magnitude();
    let rem = numerator.magnitude() % a.magnitude();
    let cmp = (&rem * 2u8).cmp(a.magnitude());
    if cmp.is_gt() || (cmp.is_eq() && &q % 2u8 == 1u8.into()) {
        q += 1u8;
    }
    let digits = format!("{:0>13}", q.to_string());
    let split = digits.len() - 12;
    let sign = if numerator.sign() == Sign::Minus && q != 0u8.into() {
        "-"
    } else {
        ""
    };
    let value = format!("{sign}{}.{}", &digits[..split], &digits[split..]);
    statistics::decimal(&value).map_err(|_| "RESEARCH_TARGET_NUMERIC_OVERFLOW")?;
    Ok(value)
}
/// One in-process owner for stopping the exact selected child. It never issues a retry.
#[derive(Clone, Default)]
pub struct Control(std::sync::Arc<ControlState>);
#[derive(Default)]
struct ControlState {
    stopped: std::sync::atomic::AtomicBool,
    child: std::sync::Mutex<Option<onlyalpha_calculation_bridge::Cancellation>>,
}
impl Control {
    pub fn stop(&self) -> std::result::Result<(), PreparationError> {
        self.0
            .stopped
            .store(true, std::sync::atomic::Ordering::Release);
        if let Some(child) = self
            .0
            .child
            .lock()
            .map_err(|e| {
                PreparationError::unknown(
                    "RESEARCH_ALGORITHM_OUTCOME_UNKNOWN",
                    e.into_inner().clone(),
                )
            })?
            .as_ref()
        {
            child
                .cancel()
                .map_err(|e| PreparationError::worker(e, child.clone()))?;
        }
        Ok(())
    }
    pub(crate) fn uncertain(&self, code: &'static str) -> PreparationError {
        let child = self
            .0
            .child
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone();
        PreparationError::unknown(code, child)
    }
    fn check(&self) -> Result<()> {
        if self.0.stopped.load(std::sync::atomic::Ordering::Acquire) {
            Err("RESEARCH_EXECUTION_CANCELLED")
        } else {
            Ok(())
        }
    }
    fn attach(
        &self,
        child: onlyalpha_calculation_bridge::Cancellation,
    ) -> std::result::Result<(), PreparationError> {
        let mut current = self.0.child.lock().map_err(|_| {
            PreparationError::unknown("RESEARCH_ALGORITHM_OUTCOME_UNKNOWN", Some(child.clone()))
        })?;
        if current.is_some() {
            return Err(INVALID.into());
        }
        *current = Some(child.clone());
        if self.0.stopped.load(std::sync::atomic::Ordering::Acquire) {
            child
                .cancel()
                .map_err(|e| PreparationError::worker(e, child.clone()))?;
            return Err("RESEARCH_EXECUTION_CANCELLED".into());
        }
        Ok(())
    }
}
/// Actual products of the selected executor. No public constructor or deserializer.
pub struct Executed {
    pub(crate) run: VerifiedRun,
    pub(crate) feature: Value,
    pub(crate) targets: Vec<Value>,
    pub(crate) statistics: Vec<Value>,
    pub(crate) evidence: Value,
}
fn verify_executor_image(image: &Value, binding: &Value) -> Result<()> {
    if image["artifact"] != binding["executor_artifact_sha256"]
        || image["protocol"] != binding["protocol"]
        || !image["version"]
            .as_str()
            .is_some_and(|v| !v.is_empty() && binding["executor_version"].as_str() == Some(v))
    {
        return Err("RESEARCH_EXECUTOR_IMAGE_MISMATCH");
    }
    Ok(())
}
#[cfg(test)]
mod executor_version_tests {
    use super::*;
    #[test]
    fn native_executor_descriptor_version_is_bound_to_the_selected_manifest() {
        let binding = json!({"executor_artifact_sha256":"a".repeat(64),"protocol":"onlyalpha.research.executor/1","executor_version":"0.11.1"});
        let mut image = json!({"artifact":"a".repeat(64),"protocol":"onlyalpha.research.executor/1","version":"0.11.1"});
        verify_executor_image(&image, &binding).unwrap();
        for version in [json!("0.0.0"), json!(""), Value::Null, json!(true)] {
            image["version"] = version;
            assert_eq!(
                verify_executor_image(&image, &binding),
                Err("RESEARCH_EXECUTOR_IMAGE_MISMATCH")
            );
        }
    }
}
pub(crate) fn calculation_manifest(logical: &str, body: Value) -> Result<Value> {
    let content = hash(&body)?;
    let result = hash(
        &json!({"schema_version":3,"calculation_fingerprint":logical,"result_content_fingerprint":content}),
    )?;
    Ok(
        json!({"schema_version":3,"profile":"NATIVE_TIME_SERIES_VALUES_V1","calculation_fingerprint":logical,
        "result_content_fingerprint":content,"calculation_result_fingerprint":result,"content":body}),
    )
}
pub(crate) fn signed(mut body: Value, key: &str) -> Result<Value> {
    let digest = hash(&body)?;
    body.as_object_mut()
        .ok_or(INVALID)?
        .insert(key.into(), digest.into());
    Ok(body)
}
pub fn verify_inputs(run: &VerifiedRun, inputs: &PreparedInputs) -> Result<()> {
    inputs.verify_runtime()?;
    let spec = run.specification();
    spec.validate()?;
    let factor = spec.factor()?;
    let window = factor.window(crate::application::research_factor::Window {
        start_ns: spec.study.samples[0].start_ns,
        end_ns: spec.study.samples[1].end_ns,
        bar_ns: spec.study.bar_ns,
        horizon_bars: spec.study.horizon_bars,
    })?;
    let r = inputs.record();
    if *r != run.prepared_inputs
        || r["dataset_snapshot_fingerprint"] != spec.dataset_snapshot_fingerprint
        || r["runtime_generation_fingerprint"] != spec.runtime_generation_fingerprint
        || r["execution_binding"] != spec.execution_binding
        || r["runtime_work_binding"]["work_id"] != run.run_id()
        || r["factor_revision_fingerprint"] != spec.revision["revision_fingerprint"]
        || r["factor_preparation_fingerprint"] != factor.fingerprint()
        || r["input_window"] != window.to_record()
        || r["algorithm_resolution"]["algorithm_artifact"] != spec.algorithm_artifact_fingerprint
        || inputs.runtime_manifest()["catalog_generation_fingerprint"]
            != spec.catalog_generation_fingerprint
    {
        return Err(INVALID);
    }
    Ok(())
}
/// Pure numeric execution still retains the original Runtime/process owner on UNKNOWN.
/// The caller maintains the existing DB Attempt lease and handles cancellation/finalization.
pub fn execute(
    run: VerifiedRun,
    inputs: PreparedInputs,
    datasets: Datasets,
    installation: ChartInstallation,
    native_version: &str,
    control: &Control,
) -> std::result::Result<Executed, PreparationError> {
    control.check()?;
    verify_inputs(&run, &inputs)?;
    let spec = run.specification();
    let image = crate::workers::algorithm::describe_research_runtime(native_version)
        .map_err(|_| "RESEARCH_EXECUTOR_IMAGE_UNAVAILABLE")?;
    verify_executor_image(&image, &spec.execution_binding)?;
    if installation.artifact_fingerprint() != spec.algorithm_artifact_fingerprint {
        return Err(INVALID.into());
    }
    let dataset = datasets.load(&spec.dataset_snapshot_fingerprint)?;
    let factor = spec.factor()?;
    let window = &inputs.record()["input_window"];
    let start: u64 = window["dataset_event_start_ns"]
        .as_str()
        .ok_or(INVALID)?
        .parse()
        .map_err(|_| INVALID)?;
    let end: u64 = window["dataset_event_end_ns"]
        .as_str()
        .ok_or(INVALID)?
        .parse()
        .map_err(|_| INVALID)?;
    let bar = spec.study.bar_ns;
    let count = (end - start) / bar;
    if count == 0 || count > 8192 || end > spec.study.protected_start_ns {
        return Err("RESEARCH_EXECUTION_BUDGET_OR_PROTECTED_SCOPE".into());
    }
    let mut actual = BTreeMap::new();
    for row in dataset.dataset().rows() {
        let t = row["ts_event_ns"]
            .as_i64()
            .and_then(|t| u64::try_from(t).ok())
            .ok_or(INVALID)?;
        if t < start
            || t >= end
            || !(t - start).is_multiple_of(bar)
            || actual.insert(t, row).is_some()
        {
            return Err(INVALID.into());
        }
    }
    let mut presence = Vec::new();
    let mut rows = Vec::new();
    let columns = factor.columns();
    for i in 0..count {
        let t = start + i * bar;
        let row = actual.get(&t);
        presence.push(row.is_some());
        let values = columns
            .iter()
            .map(|k| (k.clone(), row.map_or(Value::Null, |r| r[k].clone())))
            .collect::<serde_json::Map<_, _>>();
        rows.push(json!({"at_ns":t,"values":values}));
    }
    let runtime = inputs.runtime_hold();
    let core = runtime.core_artifact()?.clone();
    let source_keys = [
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_text",
        "source_sha256",
        "factor_api_version",
        "factor_api_contract_fingerprint",
        "input_contract",
        "parameter_contract",
        "output_contract",
    ];
    let source = source_keys
        .into_iter()
        .map(|k| (k.to_string(), spec.revision[k].clone()))
        .collect::<serde_json::Map<_, _>>();
    let resolution = json!({"schema_version":1,"source":source,"graph":factor.graph().to_record(),"core_artifact":core});
    let mut worker = AlgorithmProcess::research_resolution(
        &installation,
        &spec.runtime_generation_fingerprint,
        Box::new(runtime.clone()),
    )
    .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
    let owner = worker
        .cancellation()
        .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
    control.attach(owner.clone())?;
    let deadline = Duration::from_secs(10);
    worker
        .handshake_research(deadline)
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    let result = worker.evaluate_research(json!({"resolution":resolution,"rows":rows,"root_fingerprint":factor.root_fingerprint()}),deadline)
        .map_err(|e| PreparationError::worker(e,owner.clone()))?;
    worker
        .terminate()
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    control.check()?;
    let mut resolved = result.clone();
    resolved
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("evaluation");
    if resolved != inputs.record()["algorithm_resolution"] {
        return Err(INVALID.into());
    }
    let evaluation = &result["evaluation"];
    let axis = rows.iter().map(|r| r["at_ns"].clone()).collect::<Vec<_>>();
    if evaluation["schema_version"] != 1
        || evaluation["input_fingerprint"] != hash(&json!(rows))?
        || evaluation["graph_fingerprint"] != factor.graph().fingerprint()
        || evaluation["axis"] != json!(axis)
        || evaluation["feature"].as_array().map(Vec::len) != Some(count as usize)
    {
        return Err(INVALID.into());
    }
    let features = evaluation["feature"].as_array().ok_or(INVALID)?;
    for value in features {
        if let Some(s) = value.as_str() {
            statistics::decimal(s)?;
        } else if !value.is_null() {
            return Err(INVALID.into());
        }
    }
    let feature = calculation_manifest(
        &spec.calculation_fingerprint()?,
        json!({"role":"FEATURE","dataset_snapshot_fingerprint":spec.dataset_snapshot_fingerprint,
        "graph":factor.graph().to_record(),"root_fingerprint":factor.root_fingerprint(),"axis":axis,
        "source_presence":presence,"algorithm_evaluation":evaluation}),
    )?;
    let mut targets = Vec::new();
    let mut results = Vec::new();
    let family = spec.study.comparison_family()?;
    let subject = spec.subject()?.to_record();
    let intents = spec.statistics_intents()?;
    for (sample, intent) in spec.study.samples.iter().zip(&intents) {
        control.check()?;
        let mut observations = Vec::new();
        let mut target_rows = Vec::new();
        for (t, row) in actual.range(sample.start_ns..sample.end_ns) {
            let exit = t
                .checked_add(u64::from(spec.study.horizon_bars) * bar)
                .ok_or(INVALID)?;
            let value = if exit < sample.end_ns {
                actual
                    .get(&exit)
                    .map(|future| {
                        close_forward_return(
                            row["close"].as_str().ok_or(INVALID)?,
                            future["close"].as_str().ok_or(INVALID)?,
                        )
                    })
                    .transpose()?
            } else {
                None
            };
            let index = ((t - start) / bar) as usize;
            observations.push(Observation {
                at_ns: *t,
                feature: features[index].as_str().map(str::to_owned),
                target: value.clone(),
            });
            target_rows.push(json!({"at_ns":t,"value":value}));
        }
        let logical = hash(
            &json!({"contract":"ONLYALPHA_NATIVE_CLOSE_RETURN_TARGET_V1","dataset_snapshot_fingerprint":spec.dataset_snapshot_fingerprint,
            "sample":sample,"bar_ns":bar,"horizon_bars":spec.study.horizon_bars,"numeric":"EXACT_RATIONAL_QUANTUM_1E-12_HALF_EVEN"}),
        )?;
        let target = calculation_manifest(
            &logical,
            json!({"role":"TARGET","definition":intent["target"],"sample":sample,
            "dataset_snapshot_fingerprint":spec.dataset_snapshot_fingerprint,"bar_ns":bar,"horizon_bars":spec.study.horizon_bars,"rows":target_rows}),
        )?;
        let plan = Plan {
            schema_version: 1,
            bindings: Bindings {
                dataset: spec.dataset_snapshot_fingerprint.clone(),
                feature_result: feature["calculation_result_fingerprint"]
                    .as_str()
                    .ok_or(INVALID)?
                    .into(),
                target_result: target["calculation_result_fingerprint"]
                    .as_str()
                    .ok_or(INVALID)?
                    .into(),
                factor_revision: factor.revision_fingerprint().into(),
                study: spec.study.logical_fingerprint()?,
            },
            start_ns: sample.start_ns,
            end_ns: sample.end_ns,
            bar_ns: bar,
            horizon_bars: spec.study.horizon_bars,
            expected_block_length: spec.study.expected_block_length,
            replicates: spec.study.replicates,
            confidence_bps: spec.study.confidence_bps,
            seed: spec.study.seed.clone(),
            family: family.clone(),
        };
        let analysis = statistics::evaluate(&plan, &observations)?;
        results.push(signed(json!({"schema_version":2,"statistics_family":"ONLYALPHA_TIME_SERIES_ASSOCIATION_V1",
            "statistics_fingerprint":hash(intent)?,"specification":spec.record()?,"evaluation_subject":subject,"dataset_snapshot_fingerprint":spec.dataset_snapshot_fingerprint,
            "intent":intent,"plan":plan,"analysis":analysis,"observations":observations,
            "feature_calculation_fingerprint":feature["calculation_fingerprint"],"target_calculation_fingerprint":target["calculation_fingerprint"]}),"statistics_result_fingerprint")?);
        targets.push(target);
        inputs.verify_runtime()?;
    }
    results.sort_by(|a, b| {
        a["statistics_fingerprint"]
            .as_str()
            .cmp(&b["statistics_fingerprint"].as_str())
    });
    runtime.verify()?;
    installation
        .verify()
        .map_err(|_| "RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
    inputs.verify_runtime()?;
    let mut semantic_prepared = inputs.record().clone();
    semantic_prepared
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("runtime_work_binding");
    if let Some(lineage) = semantic_prepared["dataset_materialization"].as_object_mut() {
        lineage.remove("created_at");
    }
    let evidence = signed(
        json!({"schema_version":1,"contract":"ONLYALPHA_NATIVE_RESEARCH_EXECUTION_V1","specification_fingerprint":run.specification_fingerprint(),
        "prepared_inputs_fingerprint":hash(&semantic_prepared)?,"prepared_inputs":semantic_prepared,"native_image":image,
        "algorithm_artifact_fingerprint":installation.artifact_fingerprint(),"algorithm_result_fingerprint":hash(evaluation)?,
        "feature_result":feature["calculation_result_fingerprint"],
        "target_results":targets.iter().map(|v|v["calculation_result_fingerprint"].clone()).collect::<Vec<_>>(),
        "statistics_results":results.iter().map(|v|v["statistics_result_fingerprint"].clone()).collect::<Vec<_>>() }),
        "evidence_fingerprint",
    )?;
    control.check()?;
    Ok(Executed {
        run,
        feature,
        targets,
        statistics: results,
        evidence,
    })
}

#[cfg(test)]
mod control_tests {
    use super::*;
    use onlyalpha_calculation_bridge::{ProcessControl, ProcessState, Worker, WorkerError};
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    struct Uncertain(Arc<AtomicUsize>);
    impl ProcessControl for Uncertain {
        fn terminate(&self, _drain: bool) -> onlyalpha_calculation_bridge::Result<()> {
            self.0.fetch_add(1, Ordering::SeqCst);
            Err(WorkerError::Unknown("CONTROLLED_DRAIN_UNCERTAIN"))
        }
        fn state(&self) -> ProcessState {
            ProcessState::Uncertain
        }
    }
    #[test]
    fn research_stop_unknown_retains_the_original_owner_for_explicit_drain() {
        let (socket, _peer) = std::os::unix::net::UnixStream::pair().unwrap();
        let calls = Arc::new(AtomicUsize::new(0));
        let worker = Worker::from_stream(
            socket,
            "a".repeat(64),
            "b".repeat(64),
            Arc::new(Uncertain(calls.clone())),
            8 * 1024 * 1024,
        )
        .unwrap();
        let owner = worker.cancellation().unwrap();
        let control = Control::default();
        control.attach(owner).unwrap();
        let error = control.stop().unwrap_err();
        assert_eq!(error.code(), "RESEARCH_ALGORITHM_OUTCOME_UNKNOWN");
        let retained = error
            .recovery_owner()
            .expect("original owner must survive UNKNOWN");
        assert!(retained.drain().is_err());
        assert_eq!(calls.load(Ordering::SeqCst), 2);
        assert!(control.check().is_err());
        assert!(
            control
                .uncertain("RESEARCH_EXECUTION_OUTCOME_UNKNOWN")
                .recovery_owner()
                .is_some()
        );
    }
}
