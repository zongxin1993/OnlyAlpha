//! Exact executable-input preflight for the declared input/algorithm ABI.
//! The owning Run Command retains Human Research authorization.
use crate::{
    application::{
        factor_content::hash,
        research_dataset::MaterializedDataset,
        research_factor::{CompiledFactor, InputWindow},
    },
    persistence::{research_dataset::Store, research_runtime::RuntimeInputHold},
    workers::algorithm::AlgorithmProcess,
};
use onlyalpha_calculation_bridge::{Cancellation, ChartInstallation, WorkerError};
use serde_json::{Value, json};
use std::{sync::Arc, time::Duration};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_EXECUTABLE_INPUT_MISMATCH";
/// UNKNOWN retains the original owner; callers drain it, never start replacement work.
pub struct PreparationError {
    code: &'static str,
    recovery: Option<Cancellation>,
}
impl PreparationError {
    pub fn code(&self) -> &'static str {
        if self
            .recovery
            .as_ref()
            .is_some_and(|r| r.state() == onlyalpha_calculation_bridge::ProcessState::Uncertain)
        {
            "RESEARCH_ALGORITHM_OUTCOME_UNKNOWN"
        } else {
            self.code
        }
    }
    pub fn recovery_owner(&self) -> Option<&Cancellation> {
        self.recovery.as_ref()
    }
    pub(crate) fn unknown(code: &'static str, owner: Option<Cancellation>) -> Self {
        Self {
            code,
            recovery: owner,
        }
    }
    pub(crate) fn worker(error: WorkerError, owner: Cancellation) -> Self {
        Self {
            code: if matches!(error, WorkerError::Unknown(_)) {
                "RESEARCH_ALGORITHM_OUTCOME_UNKNOWN"
            } else {
                "RESEARCH_ALGORITHM_UNAVAILABLE"
            },
            recovery: Some(owner),
        }
    }
}
impl From<&'static str> for PreparationError {
    fn from(code: &'static str) -> Self {
        Self {
            code,
            recovery: None,
        }
    }
}
impl std::fmt::Display for PreparationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::fmt::Debug for PreparationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for PreparationError {}
/// Retains the sole Runtime lifecycle shared lock through the consumer's handoff.
/// It is not a portable JSON execution permit or a new Run identity.
pub struct PreparedInputs {
    runtime: Arc<RuntimeInputHold>,
    record: Value,
}
impl PreparedInputs {
    pub(crate) fn runtime_hold(&self) -> Arc<RuntimeInputHold> {
        self.runtime.clone()
    }
    pub fn runtime_manifest(&self) -> &Value {
        self.runtime.manifest()
    }
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn verify_runtime(&self) -> Result<()> {
        self.runtime.verify()
    }
}
/// Recover only the original persisted grant. This is neither a Human session nor new permission.
/// Re-read the retained Dataset materialization and exact Runtime/artifact inputs, then require
/// byte-for-byte agreement with the original admitted preparation observation.
pub fn restore(
    run: &crate::application::research_run::VerifiedRun,
    runtime: RuntimeInputHold,
    installation: &ChartInstallation,
    datasets: &Store,
) -> std::result::Result<PreparedInputs, PreparationError> {
    let spec = run.specification();
    let materialization = run.prepared_inputs["dataset_materialization"]["materialization_id"]
        .as_str()
        .ok_or(INVALID)?;
    let materialized = MaterializedDataset::load(datasets, materialization)?;
    if materialized.lineage() != &run.prepared_inputs["dataset_materialization"] {
        return Err(INVALID.into());
    }
    let factor = spec.factor()?;
    let window = factor.window(crate::application::research_factor::Window {
        start_ns: spec.study.samples[0].start_ns,
        end_ns: spec.study.samples[1].end_ns,
        bar_ns: spec.study.bar_ns,
        horizon_bars: spec.study.horizon_bars,
    })?;
    let restored = prepare(
        runtime,
        installation,
        &factor,
        &spec.revision,
        &window,
        datasets,
        &materialized,
    )?;
    if restored.record() != &run.prepared_inputs {
        return Err(INVALID.into());
    }
    crate::application::research_run_execution::verify_inputs(run, &restored)?;
    Ok(restored)
}
/// All arguments are exact, already owner-selected inputs. The caller still owns
/// Authoring consent and the separate one-run Command/permission transaction.
/// No public route exposes this internal preflight as authorization.
pub fn prepare(
    mut runtime: RuntimeInputHold,
    installation: &ChartInstallation,
    factor: &CompiledFactor,
    revision: &Value,
    window: &InputWindow,
    datasets: &Store,
    materialized: &MaterializedDataset,
) -> std::result::Result<PreparedInputs, PreparationError> {
    crate::application::private_assets::authoring::validate_revision(revision)
        .map_err(|_| INVALID)?;
    if revision["revision_fingerprint"] != factor.revision_fingerprint() {
        return Err(INVALID.into());
    }
    let w = window.to_record();
    if w["factor_preparation_fingerprint"] != factor.fingerprint() {
        return Err(INVALID.into());
    }
    // Re-read physical Dataset and retained provenance at admission; a prior DTO is not a proof.
    let snapshot = materialized.verified().dataset().snapshot_fingerprint();
    let dataset = datasets.load(snapshot)?;
    if dataset.manifest() != materialized.verified().manifest() {
        return Err(INVALID.into());
    }
    let definition = dataset.dataset().definition();
    let ns = |key: &str| -> Result<u64> {
        let t: onlyalpha_domain::time::OnlyUtcDateTime = definition["time_range"][key]
            .as_str()
            .ok_or(INVALID)?
            .parse()
            .map_err(|_| INVALID)?;
        use onlyalpha_domain::time::OnlyTimestamp;
        OnlyTimestamp::from_datetime(t)
            .unix_nanos()
            .to_string()
            .parse::<u64>()
            .map_err(|_| INVALID)
    };
    if ns("start")? != window.dataset_start_ns()
        || ns("end")? != window.dataset_end_ns()
        || definition["instruments"].as_array().map(Vec::len) != Some(1)
    {
        return Err(INVALID.into());
    }
    let stride = definition["bar_semantic"]["formation"]["stride_minutes"]
        .as_u64()
        .and_then(|n| n.checked_mul(60_000_000_000))
        .ok_or(INVALID)?;
    let expected_stride = stride.to_string();
    if w["bar_ns"].as_str() != Some(expected_stride.as_str()) {
        return Err(INVALID.into());
    }
    let bindings = runtime.manifest()["private_factor_bindings"]
        .as_array()
        .ok_or(INVALID)?;
    let matches: Vec<_> = bindings
        .iter()
        .filter(|b| b["entry"]["revision_fingerprint"] == revision["revision_fingerprint"])
        .cloned()
        .collect();
    if matches.len() != 1 {
        return Err(INVALID.into());
    }
    let binding = &matches[0];
    let saved = runtime.private_factor(
        binding["runtime_artifact_fingerprint"]
            .as_str()
            .ok_or(INVALID)?,
    )?;
    let mut metadata = revision.clone();
    metadata
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("source_text");
    if saved["revision_metadata"] != metadata {
        return Err(INVALID.into());
    }
    runtime.verify_artifacts()?;
    let execution_binding = runtime.execution_binding()?;
    let core = runtime.core_artifact()?.clone();
    let generation = runtime.manifest()["runtime_generation_fingerprint"]
        .as_str()
        .ok_or(INVALID)?
        .to_owned();
    let runtime = Arc::new(runtime);
    let mut source = serde_json::Map::new();
    for k in [
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
    ] {
        source.insert(k.into(), revision[k].clone());
    }
    let request = json!({"schema_version":1,"source":source,"graph":factor.graph().to_record(),"core_artifact":core});
    let mut worker =
        AlgorithmProcess::research_resolution(installation, &generation, Box::new(runtime.clone()))
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
    let owner = worker
        .cancellation()
        .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
    let deadline = Duration::from_secs(10);
    worker
        .handshake_research(deadline)
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    let resolved = worker
        .resolve_research(request.clone(), deadline)
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    worker
        .terminate()
        .map_err(|e| PreparationError::worker(e, owner.clone()))?;
    if resolved["schema_version"] != 1
        || resolved["contract"] != "ONLYALPHA_PRIVATE_FACTOR_RESOLVE_V1"
        || resolved["algorithm_artifact"] != installation.artifact_fingerprint()
        || resolved["factor_revision_fingerprint"] != revision["revision_fingerprint"]
        || resolved["core_artifact_sha256"]
            != runtime.manifest()["core_execution"]["artifact_sha256"]
        || !resolved["core_resources_fingerprint"]
            .as_str()
            .is_some_and(crate::is_sha256_hex)
        || resolved["source_projection_fingerprint"] != hash(&request["source"])?
        || resolved["graph"] != request["graph"]
        || resolved["source_artifact"] != saved["source_artifact"]
        || resolved["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
    {
        return Err(INVALID.into());
    }
    check_binding(&resolved, &saved, binding, runtime.manifest())?;
    runtime.verify()?;
    let record = json!({"schema_version":1,"contract":"ONLYALPHA_RESEARCH_PREPARED_INPUTS_V1","runtime_generation_fingerprint":generation,"execution_binding":execution_binding,"runtime_work_binding":runtime.binding(),"factor_preparation_fingerprint":factor.fingerprint(),"factor_revision_fingerprint":factor.revision_fingerprint(),"input_window":w,"dataset_snapshot_fingerprint":snapshot,"dataset_materialization":materialized.lineage(),"dataset_construction_fingerprint":dataset.dataset().construction_fingerprint(),"algorithm_resolution":resolved});
    Ok(PreparedInputs { runtime, record })
}
pub(crate) fn check_binding(
    resolved: &Value,
    saved: &Value,
    binding: &Value,
    manifest: &Value,
) -> Result<()> {
    let entry = &binding["entry"];
    let evidence = &saved["equivalence_evidence"];
    check_equivalence(evidence, entry)?;
    for k in [
        "factor_id",
        "semantic_version",
        "revision_fingerprint",
        "source_sha256",
        "source_artifact_fingerprint",
        "factor_api_version",
        "factor_api_contract_fingerprint",
    ] {
        if resolved["source_artifact"][k] != entry[k] {
            return Err(INVALID);
        }
    }
    check_snapshot(
        &saved["provider_snapshot"],
        entry,
        &binding["provider_snapshot_fingerprint"],
    )?;
    let provider = &saved["provider"];
    exact(
        provider,
        &[
            "manifest",
            "content_fingerprint",
            "calculations",
            "private_factor_snapshot",
        ],
    )?;
    let pm = &provider["manifest"];
    exact(
        pm,
        &[
            "schema_version",
            "provider_id",
            "provider_version",
            "kind",
            "source",
        ],
    )?;
    let id = pm["provider_id"].as_str().ok_or(INVALID)?;
    let groups = id.split(['.', '_', '-']).collect::<Vec<_>>();
    let version = pm["provider_version"].as_str().ok_or(INVALID)?;
    if !id.as_bytes().first().is_some_and(u8::is_ascii_lowercase)
        || groups.len() < 2
        || groups.iter().any(|g| {
            g.is_empty()
                || !g
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit())
        })
        || version.is_empty()
        || version.len() > 64
        || !version.as_bytes()[0].is_ascii_alphanumeric()
        || !version
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._+-".contains(&b))
    {
        return Err(INVALID);
    }
    if pm["schema_version"].as_u64() != Some(1)
        || pm["kind"] != "FACTOR"
        || pm["source"]
            != json!({"kind":"PRIVATE_FACTOR_SNAPSHOT","private_factor_provider_snapshot_fingerprint":binding["provider_snapshot_fingerprint"]})
        || provider["calculations"] != resolved["private_calculations"]
        || provider["private_factor_snapshot"] != saved["provider_snapshot"]
        || provider["content_fingerprint"]
            != hash(
                &json!({"kind":"FACTOR","calculations":resolved["private_calculations"],"private_factor_snapshot":saved["provider_snapshot"]}),
            )?
    {
        return Err(INVALID);
    }
    let actual = resolved["implementations"].as_array().ok_or(INVALID)?;
    let allowed = manifest["implementations"].as_array().ok_or(INVALID)?;
    for implementation in actual {
        let r = &implementation["calculation_type_reference"];
        let expected = json!({"kind":r["kind"],"type_id":r["type_id"],"semantic_version":r["semantic_version"],"backend":implementation["backend_kind"],"implementation_fingerprint":implementation["implementation_fingerprint"]});
        if !allowed.contains(&expected) {
            return Err(INVALID);
        }
        if r["kind"] == "FACTOR" {
            let k = match implementation["backend_kind"].as_str() {
                Some("RESEARCH") => "research_implementation_fingerprint",
                Some("TRADING") => "trading_implementation_fingerprint",
                _ => return Err(INVALID),
            };
            if implementation["implementation_fingerprint"] != entry[k] {
                return Err(INVALID);
            }
        }
    }
    Ok(())
}

fn check_equivalence(evidence: &Value, entry: &Value) -> Result<()> {
    let fields = [
        "revision_fingerprint",
        "source_artifact_fingerprint",
        "factor_api_contract_fingerprint",
        "research_adapter_fingerprint",
        "trading_adapter_fingerprint",
        "research_implementation_fingerprint",
        "trading_implementation_fingerprint",
        "test_vector_set_fingerprint",
        "research_output_fingerprint",
        "trading_output_fingerprint",
        "disposition",
        "equivalence_evidence_fingerprint",
    ];
    exact(evidence, &fields)?;
    for k in fields {
        if k != "disposition" && !evidence[k].as_str().is_some_and(crate::is_sha256_hex) {
            return Err(INVALID);
        }
    }
    let mut content = evidence.clone();
    let pin = content
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("equivalence_evidence_fingerprint")
        .ok_or(INVALID)?;
    if hash(&content)? != pin
        || pin != entry["equivalence_evidence_fingerprint"]
        || evidence["disposition"] != "PASS"
        || evidence["research_output_fingerprint"] != evidence["trading_output_fingerprint"]
    {
        return Err(INVALID);
    }
    for k in [
        "revision_fingerprint",
        "source_artifact_fingerprint",
        "factor_api_contract_fingerprint",
        "research_adapter_fingerprint",
        "trading_adapter_fingerprint",
        "research_implementation_fingerprint",
        "trading_implementation_fingerprint",
    ] {
        if evidence[k] != entry[k] {
            return Err(INVALID);
        }
    }
    Ok(())
}

fn check_snapshot(snapshot: &Value, entry: &Value, expected: &Value) -> Result<()> {
    exact(snapshot, &["entries", "snapshot_fingerprint"])?;
    if snapshot["snapshot_fingerprint"] != *expected
        || snapshot["entries"] != json!([entry])
        || hash(
            &json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_PROVIDER_SNAPSHOT_V1","entries":snapshot["entries"]}),
        )? != *expected
    {
        return Err(INVALID);
    }
    Ok(())
}
#[cfg(test)]
mod proof_tests {
    use super::*;
    fn evidence() -> Value {
        let mut v = json!({"disposition":"PASS"});
        for k in [
            "revision_fingerprint",
            "source_artifact_fingerprint",
            "factor_api_contract_fingerprint",
            "research_adapter_fingerprint",
            "trading_adapter_fingerprint",
            "research_implementation_fingerprint",
            "trading_implementation_fingerprint",
            "test_vector_set_fingerprint",
            "research_output_fingerprint",
            "trading_output_fingerprint",
        ] {
            v[k] = json!("1".repeat(64));
        }
        v["equivalence_evidence_fingerprint"] = json!(hash(&v).unwrap());
        v
    }
    #[test]
    fn missing_equal_outputs_and_missing_vectors_are_incomplete_not_match() {
        let v = evidence();
        let entry = v.clone();
        assert!(check_equivalence(&v, &entry).is_ok());
        for keys in [
            vec!["research_output_fingerprint", "trading_output_fingerprint"],
            vec!["test_vector_set_fingerprint"],
        ] {
            let mut bad = v.clone();
            bad.as_object_mut()
                .unwrap()
                .remove("equivalence_evidence_fingerprint");
            for k in keys {
                bad.as_object_mut().unwrap().remove(k);
            }
            let fp = hash(&bad).unwrap();
            bad["equivalence_evidence_fingerprint"] = fp.clone().into();
            let mut e = entry.clone();
            e["equivalence_evidence_fingerprint"] = fp.into();
            assert!(check_equivalence(&bad, &e).is_err());
        }
    }
    #[test]
    fn snapshot_claim_is_recomputed_and_duplicate_entry_is_invalid() {
        let entry = json!({"factor_id":"fixture"});
        let entries = json!([entry]);
        let fp = hash(
            &json!({"contract":"ONLYALPHA_PRIVATE_FACTOR_PROVIDER_SNAPSHOT_V1","entries":entries}),
        )
        .unwrap();
        let mut snapshot = json!({"entries":entries,"snapshot_fingerprint":fp});
        assert!(check_snapshot(&snapshot, &entry, &snapshot["snapshot_fingerprint"]).is_ok());
        snapshot["snapshot_fingerprint"] = json!("f".repeat(64));
        assert!(check_snapshot(&snapshot, &entry, &snapshot["snapshot_fingerprint"]).is_err());
    }
}

fn exact(v: &Value, fields: &[&str]) -> Result<()> {
    let m = v.as_object().ok_or(INVALID)?;
    if m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)) {
        return Err(INVALID);
    }
    Ok(())
}

#[cfg(test)]
mod recovery_tests {
    use super::*;
    use onlyalpha_calculation_bridge::{ProcessControl, ProcessState, Worker};
    use std::{
        os::unix::net::UnixStream,
        sync::atomic::{AtomicBool, Ordering},
    };
    struct Control {
        joined: AtomicBool,
        retained: Arc<AtomicBool>,
    }
    impl Drop for Control {
        fn drop(&mut self) {
            self.retained.store(false, Ordering::SeqCst);
        }
    }
    impl ProcessControl for Control {
        fn state(&self) -> ProcessState {
            if self.joined.load(Ordering::SeqCst) {
                ProcessState::Joined
            } else {
                ProcessState::Uncertain
            }
        }
        fn terminate(&self, recover: bool) -> onlyalpha_calculation_bridge::Result<()> {
            if !recover {
                return Err(WorkerError::Unknown("CONTROLLED_JOIN"));
            }
            self.joined.store(true, Ordering::SeqCst);
            self.retained.store(false, Ordering::SeqCst);
            Ok(())
        }
    }
    #[test]
    fn unknown_returns_same_drain_owner_and_never_releases_hold_early() {
        let held = Arc::new(AtomicBool::new(true));
        let (a, _peer) = UnixStream::pair().unwrap();
        let worker = Worker::from_stream(
            a,
            "1".repeat(64),
            "2".repeat(64),
            Arc::new(Control {
                joined: AtomicBool::new(false),
                retained: held.clone(),
            }),
            8 * 1024 * 1024,
        )
        .unwrap();
        let error = PreparationError::worker(
            WorkerError::Unknown("CONTROLLED_RESPONSE"),
            worker.cancellation().unwrap(),
        );
        drop(worker);
        assert_eq!(error.code(), "RESEARCH_ALGORITHM_OUTCOME_UNKNOWN");
        assert!(held.load(Ordering::SeqCst));
        error.recovery_owner().unwrap().drain().unwrap();
        assert!(!held.load(Ordering::SeqCst));
        assert_eq!(
            error.recovery_owner().unwrap().state(),
            ProcessState::Joined
        );
    }
}
