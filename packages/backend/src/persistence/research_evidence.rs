//! Immutable native Research publication in the existing semantic owners.
//! Execution produces numbers; verified reads validate stored facts and exact relations.
pub(crate) mod strategy;
use crate::application::{
    factor_content::hash,
    research_run::{
        InspectionOutcome, Specification, VerifiedCompletion, VerifiedInspection, VerifiedRun,
    },
    research_run_execution::{Executed, signed},
    research_statistics::{self as statistics, Bindings, Observation, Plan},
};
use crate::security::{
    immutable_json::{Directory, SourceLock, inspect_source_layout, put},
    protected_files::{self as files, ReadError},
};
use rustix::fs;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    ffi::OsStr,
    path::{Path, PathBuf},
    sync::Arc,
};
pub(crate) use strategy::ReadCut as StrategyReadCut;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_EVIDENCE_CORRUPT";
const UNAVAILABLE: &str = "RESEARCH_EVIDENCE_UNAVAILABLE";
const OWNERS: [&str; 5] = [
    "calculation-results",
    "statistics-results",
    "results",
    "calculation-execution-evidence",
    "artifacts",
];
const PROFILE: &str = "research-time-series-v1";
const LIMIT: usize = 8 * 1024 * 1024;

/// Provision only brand-new owner directories; normal publication never creates owners.
pub fn initialize_fresh_owners(root: &Path) -> Result<()> {
    let research = Directory::open(root)?;
    // Inventory all destinations first, so an existing owner cannot be silently repaired.
    let existing = research.names()?;
    if OWNERS.iter().any(|name| existing.iter().any(|n| n == name)) {
        return Err(UNAVAILABLE);
    }
    for name in OWNERS {
        fs::mkdirat(&research.fd, name, fs::Mode::from_raw_mode(0o700)).map_err(|_| UNAVAILABLE)?;
        let owner = research.child(name, false)?;
        let lock = fs::openat(
            &owner.fd,
            ".source-cut.lock",
            fs::OFlags::WRONLY
                | fs::OFlags::CREATE
                | fs::OFlags::EXCL
                | fs::OFlags::NOFOLLOW
                | fs::OFlags::CLOEXEC,
            fs::Mode::from_raw_mode(0o600),
        )
        .map_err(|_| UNAVAILABLE)?;
        fs::fsync(&lock).map_err(|_| UNAVAILABLE)?;
        if name == "artifacts" {
            let profile = owner.child(PROFILE, true)?;
            let sha = profile.child("sha256", true)?;
            fs::fsync(&sha.fd).map_err(|_| UNAVAILABLE)?;
            fs::fsync(&profile.fd).map_err(|_| UNAVAILABLE)?;
        } else {
            let sha = owner.child("sha256", true)?;
            fs::fsync(&sha.fd).map_err(|_| UNAVAILABLE)?;
        }
        fs::fsync(&owner.fd).map_err(|_| UNAVAILABLE)?;
    }
    fs::fsync(&research.fd).map_err(|_| UNAVAILABLE)?;
    Ok(())
}
pub fn initialize_strategy_owners(root: &Path) -> Result<()> {
    strategy::initialize_owners(root)
}
pub struct Store {
    runtime_root: Option<PathBuf>,
    root: Directory,
    calculations: Directory,
    statistics: Directory,
    results: Directory,
    evidence: Directory,
    artifacts: Directory,
    datasets: super::research_dataset::Store,
}
impl Store {
    /// Inspect provisioned structure without acquiring a publication/cut barrier.
    pub(crate) fn inspect_layout(root: &Path) -> Result<()> {
        let store = Self::open_for_source(root)?;
        for owner in [
            &store.calculations,
            &store.statistics,
            &store.results,
            &store.evidence,
            &store.artifacts,
        ] {
            owner.verify().map_err(map_file_error)?;
        }
        store.root.verify().map_err(map_file_error)
    }
    pub fn open(root: &Path) -> Result<Self> {
        let store = Self::open_for_source(root)?;
        let locks = store.locks()?;
        for lock in &locks {
            lock.verify()?;
        }
        Ok(store)
    }
    fn open_for_source(root: &Path) -> Result<Self> {
        let root = Directory::open(root)?;
        let mut dirs = Vec::new();
        for name in OWNERS {
            let owner = root.child(name, false)?;
            verify_lockfile(&owner)?;
            if name == "artifacts" {
                owner.path(&[PROFILE, "sha256"], false)?;
            } else {
                owner.child("sha256", false)?;
            }
            dirs.push(owner);
        }
        let mut dirs = dirs.into_iter();
        let calculations = dirs.next().ok_or(UNAVAILABLE)?;
        let statistics = dirs.next().ok_or(UNAVAILABLE)?;
        let results = dirs.next().ok_or(UNAVAILABLE)?;
        let evidence = dirs.next().ok_or(UNAVAILABLE)?;
        let artifacts = dirs.next().ok_or(UNAVAILABLE)?;
        let datasets =
            super::research_dataset::Store::open(&root.path.join("datasets"), 8192, LIMIT)?;
        Ok(Self {
            runtime_root: None,
            root,
            calculations,
            statistics,
            results,
            evidence,
            artifacts,
            datasets,
        })
    }
    pub(crate) fn locks(&self) -> Result<Vec<SourceLock>> {
        self.root.verify()?;
        [
            &self.calculations,
            &self.statistics,
            &self.results,
            &self.evidence,
            &self.artifacts,
        ]
        .into_iter()
        .map(|d| {
            d.verify()?;
            if d.path.file_name() == Some(OsStr::new("artifacts")) {
                d.path(&[PROFILE, "sha256"], false)?;
            } else {
                d.child("sha256", false)?;
            }
            SourceLock::publication(&d.path)
        })
        .collect()
    }
    /// Only opaque products of the actual admitted executor can publish scientific facts.
    pub fn commit(&self, execution: Executed) -> Result<VerifiedCompletion> {
        let locks = self.locks()?;
        let Executed {
            run,
            feature,
            targets,
            statistics,
            evidence,
        } = execution;
        let spec = run.factor_specification()?;
        spec.validate()?;
        self.validate_calculation(&feature, Some(spec))?;
        save(
            &self.calculations,
            pin(&feature, "calculation_fingerprint")?,
            &feature,
        )?;
        for target in &targets {
            self.validate_calculation(target, Some(spec))?;
            save(
                &self.calculations,
                pin(target, "calculation_fingerprint")?,
                target,
            )?;
        }
        for value in &statistics {
            self.validate_statistics(value)?;
            save(
                &self.statistics,
                pin(value, "statistics_fingerprint")?,
                value,
            )?;
        }
        self.validate_evidence(&evidence, spec, Some(&statistics))?;
        save(
            &self.evidence,
            pin(&evidence, "evidence_fingerprint")?,
            &evidence,
        )?;
        let result = self.result_document(spec, &feature, &statistics, &evidence)?;
        let plan = hash(&spec.result_plan()?)?;
        self.validate_result(&result, &plan)?;
        save(&self.results, &plan, &result)?;
        let artifact = report(&result, &statistics)?;
        let result_fp = pin(&result, "research_result_fingerprint")?;
        put(
            &self.artifacts,
            &[PROFILE, "sha256", &result_fp[..2], result_fp],
            "manifest.json",
            &artifact,
        )?;
        let completed = self.load_without_locks(&run)?.ok_or(INVALID)?;
        for lock in &locks {
            lock.verify()?;
        }
        Ok(completed)
    }
    pub fn load_verified(&self, run: &VerifiedRun) -> Result<Option<VerifiedCompletion>> {
        if matches!(
            run.specification(),
            crate::application::research_run::NativeSpecification::Strategy(_)
        ) {
            return self.load_strategy(run, strategy::source_locks(self)?);
        }
        let locks = self.locks()?;
        let out = self.load_without_locks(run)?;
        for l in &locks {
            l.verify()?;
        }
        Ok(out)
    }
    /// Reconciliation performs no calculations and does not publish missing artifacts.
    pub fn inspect(&self, run: VerifiedRun, expected_revision: i64) -> Result<VerifiedInspection> {
        if expected_revision < 0 {
            return Err(INVALID);
        }
        let publication_cut = [
            &self.calculations,
            &self.statistics,
            &self.results,
            &self.evidence,
            &self.artifacts,
        ]
        .into_iter()
        .map(|d| SourceLock::acquire(&d.path).map(Arc::new))
        .collect::<Result<Vec<_>>>()?;
        let loaded = if matches!(
            run.specification(),
            crate::application::research_run::NativeSpecification::Strategy(_)
        ) {
            self.load_strategy(&run, publication_cut.clone())
        } else {
            self.load_without_locks(&run)
        };
        let outcome = match loaded {
            Ok(Some(c)) => InspectionOutcome::Complete(Box::new(c)),
            Ok(None) => InspectionOutcome::Absent,
            Err(INVALID) => InspectionOutcome::Corrupt,
            Err(e) => return Err(e),
        };
        Ok(VerifiedInspection {
            run,
            revision: expected_revision,
            outcome,
            publication_cut,
        })
    }
    pub fn read_report(&self, run: &VerifiedRun) -> Result<Value> {
        if matches!(
            run.specification(),
            crate::application::research_run::NativeSpecification::Strategy(_)
        ) {
            return self.read_strategy_report(run);
        }
        if !run.completed() {
            return Err("RESEARCH_OPERATIONAL_COMPLETION_REQUIRED");
        }
        let locks = self.locks()?;
        let complete = self.load_without_locks(run)?.ok_or(UNAVAILABLE)?;
        let value = optional(
            &self.artifacts,
            &[PROFILE, "sha256"],
            complete.research_result_fingerprint(),
        )?
        .ok_or(INVALID)?;
        for l in &locks {
            l.verify()?;
        }
        Ok(value)
    }
    fn load_without_locks(&self, run: &VerifiedRun) -> Result<Option<VerifiedCompletion>> {
        let spec = run.factor_specification()?;
        spec.validate()?;
        if spec.fingerprint()? != run.specification_fingerprint() {
            return Err(INVALID);
        }
        let plan = hash(&spec.result_plan()?)?;
        let Some(result) = optional(&self.results, &["sha256"], &plan)? else {
            return Ok(None);
        };
        let statistics = self.validate_result(&result, &plan)?;
        if result["specification"] != spec.record()? {
            return Err(INVALID);
        }
        let result_fp = pin(&result, "research_result_fingerprint")?;
        let Some(artifact) = optional(&self.artifacts, &[PROFILE, "sha256"], result_fp)? else {
            return Ok(None);
        };
        // Reuse this read's fully verified statistics under the same publication
        // cut. Independent reads still revalidate every upstream immutable fact.
        if artifact != report(&result, &statistics)? {
            return Err(INVALID);
        }
        let completion = VerifiedCompletion {
            strategy_cut: None,
            run: run.clone(),
            result: result_fp.into(),
            artifact: pin(&artifact, "artifact_content_fingerprint")?.into(),
            execution_evidence: result["calculation_execution_evidence_fingerprints"]
                .as_array()
                .ok_or(INVALID)?
                .iter()
                .map(|v| v.as_str().map(str::to_owned).ok_or(INVALID))
                .collect::<Result<_>>()?,
        };
        run.verify_completion(&completion)?;
        Ok(Some(completion))
    }
    fn load_calculation(&self, id: &str, spec: Option<&Specification>) -> Result<Value> {
        let v = optional(&self.calculations, &["sha256"], id)?.ok_or(INVALID)?;
        if v["calculation_fingerprint"] != id {
            return Err(INVALID);
        }
        self.validate_calculation(&v, spec)?;
        Ok(v)
    }
    fn validate_calculation(&self, v: &Value, spec: Option<&Specification>) -> Result<()> {
        exact(
            v,
            &[
                "schema_version",
                "profile",
                "calculation_fingerprint",
                "result_content_fingerprint",
                "calculation_result_fingerprint",
                "content",
            ],
        )?;
        if v["schema_version"] != 3 || v["profile"] != "NATIVE_TIME_SERIES_VALUES_V1" {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        let logical = pin(v, "calculation_fingerprint")?;
        let content = hash(&v["content"])?;
        if v["result_content_fingerprint"] != content
            || v["calculation_result_fingerprint"]
                != hash(
                    &json!({"schema_version":3,"calculation_fingerprint":logical,"result_content_fingerprint":content}),
                )?
        {
            return Err(INVALID);
        }
        let c = &v["content"];
        let dataset = self
            .datasets
            .load(pin(c, "dataset_snapshot_fingerprint")?)
            .map_err(|_| INVALID)?;
        match text(c, "role")? {
            "FEATURE" => {
                exact(
                    c,
                    &[
                        "role",
                        "dataset_snapshot_fingerprint",
                        "graph",
                        "root_fingerprint",
                        "axis",
                        "source_presence",
                        "algorithm_evaluation",
                    ],
                )?;
                let spec = spec.ok_or(UNAVAILABLE)?;
                let factor = spec.factor()?;
                if logical != spec.calculation_fingerprint()?
                    || c["graph"] != factor.graph().to_record()
                    || c["root_fingerprint"] != factor.root_fingerprint()
                    || c["dataset_snapshot_fingerprint"] != spec.dataset_snapshot_fingerprint
                {
                    return Err(INVALID);
                }
                let window = factor
                    .window(crate::application::research_factor::Window {
                        start_ns: spec.study.samples[0].start_ns,
                        end_ns: spec.study.samples[1].end_ns,
                        bar_ns: spec.study.bar_ns,
                        horizon_bars: spec.study.horizon_bars,
                    })?
                    .to_record();
                let start = number_text(&window, "dataset_event_start_ns")?;
                let end = number_text(&window, "dataset_event_end_ns")?;
                let bar = spec.study.bar_ns;
                let count = (end - start) / bar;
                if count == 0 || count > 8192 {
                    return Err(INVALID);
                }
                let axis = (0..count)
                    .map(|i| json!(start + i * bar))
                    .collect::<Vec<_>>();
                let mut rows = Vec::new();
                let mut presence = Vec::new();
                for at in &axis {
                    let t = at.as_u64().ok_or(INVALID)?;
                    let found = dataset
                        .dataset()
                        .rows()
                        .iter()
                        .find(|r| r["ts_event_ns"].as_u64() == Some(t));
                    presence.push(found.is_some());
                    let values = factor
                        .columns()
                        .iter()
                        .map(|k| (k.clone(), found.map_or(Value::Null, |r| r[k].clone())))
                        .collect::<serde_json::Map<_, _>>();
                    rows.push(json!({"at_ns":t,"values":values}));
                }
                let e = &c["algorithm_evaluation"];
                exact(
                    e,
                    &[
                        "schema_version",
                        "input_fingerprint",
                        "graph_fingerprint",
                        "axis",
                        "feature",
                        "outputs",
                    ],
                )?;
                if c["axis"] != json!(axis)
                    || c["source_presence"] != json!(presence)
                    || e["schema_version"] != 1
                    || e["input_fingerprint"] != hash(&json!(rows))?
                    || e["graph_fingerprint"] != factor.graph().fingerprint()
                    || e["axis"] != c["axis"]
                {
                    return Err(INVALID);
                }
                let values = e["feature"].as_array().ok_or(INVALID)?;
                if values.len() != count as usize {
                    return Err(INVALID);
                }
                for value in values {
                    decimal_or_null(value)?;
                }
                let outputs = e["outputs"].as_array().ok_or(INVALID)?;
                let mut nodes = factor.graph().ordered_nodes().collect::<Vec<_>>();
                nodes.sort_by_key(|n| n.fingerprint());
                if outputs.len() != nodes.len() {
                    return Err(INVALID);
                }
                for (output, node) in outputs.iter().zip(nodes) {
                    exact(
                        output,
                        &["node_fingerprint", "implementation_fingerprint", "values"],
                    )?;
                    pin(output, "implementation_fingerprint")?;
                    if output["node_fingerprint"] != node.fingerprint() {
                        return Err(INVALID);
                    }
                    let expected = node.to_record();
                    let ports = expected["outputs"].as_array().ok_or(INVALID)?;
                    let map = output["values"].as_object().ok_or(INVALID)?;
                    if map.len() != ports.len() {
                        return Err(INVALID);
                    }
                    for port in ports {
                        let column = map
                            .get(text(port, "name")?)
                            .and_then(Value::as_array)
                            .ok_or(INVALID)?;
                        if column.len() != count as usize {
                            return Err(INVALID);
                        }
                        for v in column {
                            decimal_or_null(v)?;
                        }
                    }
                    if output["node_fingerprint"] == factor.root_fingerprint()
                        && output["values"]["value"] != e["feature"]
                    {
                        return Err(INVALID);
                    }
                }
            }
            "TARGET" => {
                exact(
                    c,
                    &[
                        "role",
                        "definition",
                        "sample",
                        "dataset_snapshot_fingerprint",
                        "bar_ns",
                        "horizon_bars",
                        "rows",
                    ],
                )?;
                let bar = number(c, "bar_ns")?;
                let horizon = number(c, "horizon_bars")?;
                let sample = &c["sample"];
                exact(sample, &["role", "start_ns", "end_ns"])?;
                let start = number(sample, "start_ns")?;
                let end = number(sample, "end_ns")?;
                if bar == 0
                    || horizon == 0
                    || start >= end
                    || start % bar != 0
                    || (end - start) % bar != 0
                    || !matches!(text(sample, "role")?, "DEVELOPMENT" | "OUT_OF_SAMPLE")
                {
                    return Err(INVALID);
                }
                let target = json!({"contract":"CLOSE_FORWARD_RETURN_V1","horizon_bars":horizon,"numeric":{"precision":38,"quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"}});
                if c["definition"] != target
                    || logical
                        != hash(
                            &json!({"contract":"ONLYALPHA_NATIVE_CLOSE_RETURN_TARGET_V1","dataset_snapshot_fingerprint":c["dataset_snapshot_fingerprint"],"sample":sample,"bar_ns":bar,"horizon_bars":horizon,"numeric":"EXACT_RATIONAL_QUANTUM_1E-12_HALF_EVEN"}),
                        )?
                {
                    return Err(INVALID);
                }
                let rows = c["rows"].as_array().ok_or(INVALID)?;
                let observed = dataset
                    .dataset()
                    .rows()
                    .iter()
                    .filter(|r| {
                        r["ts_event_ns"]
                            .as_u64()
                            .is_some_and(|t| t >= start && t < end)
                    })
                    .collect::<Vec<_>>();
                if rows.len() != observed.len() || rows.len() > 4096 {
                    return Err(INVALID);
                }
                for (r, input) in rows.iter().zip(observed) {
                    exact(r, &["at_ns", "value"])?;
                    let t = number(r, "at_ns")?;
                    if Some(t) != input["ts_event_ns"].as_u64() {
                        return Err(INVALID);
                    }
                    let exit = t
                        .checked_add(horizon.checked_mul(bar).ok_or(INVALID)?)
                        .ok_or(INVALID)?;
                    let available = exit < end
                        && dataset
                            .dataset()
                            .rows()
                            .iter()
                            .any(|r| r["ts_event_ns"].as_u64() == Some(exit));
                    if r["value"].is_null() == available {
                        return Err(INVALID);
                    }
                    decimal_or_null(&r["value"])?;
                    if let Some(s) = r["value"].as_str()
                        && s.split_once('.').is_none_or(|(_, f)| f.len() != 12)
                    {
                        return Err(INVALID);
                    }
                }
            }
            _ => return Err(INVALID),
        }
        Ok(())
    }
    fn load_statistics(&self, id: &str) -> Result<Value> {
        let v = optional(&self.statistics, &["sha256"], id)?.ok_or(INVALID)?;
        if v["statistics_fingerprint"] != id {
            return Err(INVALID);
        }
        self.validate_statistics(&v)?;
        Ok(v)
    }
    fn validate_statistics(&self, v: &Value) -> Result<()> {
        exact(
            v,
            &[
                "schema_version",
                "statistics_family",
                "statistics_fingerprint",
                "evaluation_subject",
                "dataset_snapshot_fingerprint",
                "intent",
                "plan",
                "analysis",
                "observations",
                "feature_calculation_fingerprint",
                "target_calculation_fingerprint",
                "specification",
                "statistics_result_fingerprint",
            ],
        )?;
        if v["schema_version"] != 2
            || v["statistics_family"] != "ONLYALPHA_TIME_SERIES_ASSOCIATION_V1"
        {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        verify_signed(v, "statistics_result_fingerprint")?;
        let spec = specification(&v["specification"])?;
        let intents = spec.statistics_intents()?;
        if !intents.contains(&v["intent"])
            || v["statistics_fingerprint"] != hash(&v["intent"])?
            || v["evaluation_subject"] != spec.subject()?.to_record()
            || v["dataset_snapshot_fingerprint"] != spec.dataset_snapshot_fingerprint
            || v["feature_calculation_fingerprint"] != spec.calculation_fingerprint()?
        {
            return Err(INVALID);
        }
        let feature =
            self.load_calculation(pin(v, "feature_calculation_fingerprint")?, Some(&spec))?;
        let target =
            self.load_calculation(pin(v, "target_calculation_fingerprint")?, Some(&spec))?;
        if target["content"]["sample"] != v["intent"]["sample"]
            || target["content"]["definition"] != v["intent"]["target"]
        {
            return Err(INVALID);
        }
        let sample = &v["intent"]["sample"];
        let plan = Plan {
            schema_version: 1,
            bindings: Bindings {
                dataset: spec.dataset_snapshot_fingerprint.clone(),
                feature_result: pin(&feature, "calculation_result_fingerprint")?.into(),
                target_result: pin(&target, "calculation_result_fingerprint")?.into(),
                factor_revision: spec.factor()?.revision_fingerprint().into(),
                study: spec.study.logical_fingerprint()?,
            },
            start_ns: number(sample, "start_ns")?,
            end_ns: number(sample, "end_ns")?,
            bar_ns: spec.study.bar_ns,
            horizon_bars: spec.study.horizon_bars,
            expected_block_length: spec.study.expected_block_length,
            replicates: spec.study.replicates,
            confidence_bps: spec.study.confidence_bps,
            seed: spec.study.seed.clone(),
            family: spec.study.comparison_family()?,
        };
        if v["plan"] != serde_json::to_value(&plan).map_err(|_| INVALID)? {
            return Err(INVALID);
        }
        let observations: Vec<Observation> =
            serde_json::from_value(v["observations"].clone()).map_err(|_| INVALID)?;
        let axis = feature["content"]["axis"].as_array().ok_or(INVALID)?;
        let values = feature["content"]["algorithm_evaluation"]["feature"]
            .as_array()
            .ok_or(INVALID)?;
        let rows = target["content"]["rows"].as_array().ok_or(INVALID)?;
        if observations.len() != rows.len() {
            return Err(INVALID);
        }
        let mut normalized = Vec::new();
        for (o, r) in observations.iter().zip(rows) {
            let index = axis
                .iter()
                .position(|v| v.as_u64() == Some(o.at_ns))
                .ok_or(INVALID)?;
            if Some(o.at_ns) != r["at_ns"].as_u64()
                || json!(o.feature) != values[index]
                || json!(o.target) != r["value"]
            {
                return Err(INVALID);
            }
            normalized.push(Observation {
                at_ns: o.at_ns,
                feature: o
                    .feature
                    .as_deref()
                    .map(statistics::decimal)
                    .transpose()?
                    .map(|v| v.0),
                target: o
                    .target
                    .as_deref()
                    .map(statistics::decimal)
                    .transpose()?
                    .map(|v| v.0),
            });
        }
        validate_analysis(&v["analysis"], &plan, &normalized)?;
        Ok(())
    }
    fn validate_evidence(
        &self,
        v: &Value,
        spec: &Specification,
        verified: Option<&[Value]>,
    ) -> Result<Vec<Value>> {
        exact(
            v,
            &[
                "schema_version",
                "contract",
                "specification_fingerprint",
                "prepared_inputs_fingerprint",
                "prepared_inputs",
                "native_image",
                "algorithm_artifact_fingerprint",
                "algorithm_result_fingerprint",
                "feature_result",
                "target_results",
                "statistics_results",
                "evidence_fingerprint",
            ],
        )?;
        verify_signed(v, "evidence_fingerprint")?;
        exact(
            &v["native_image"],
            &["protocol", "artifact", "target", "version"],
        )?;
        pin(&v["native_image"], "artifact")?;
        if !matches!(
            text(&v["native_image"], "target")?,
            "x86_64-unknown-linux-gnu" | "aarch64-unknown-linux-gnu"
        ) || text(&v["native_image"], "version")?.is_empty()
        {
            return Err(INVALID);
        }
        if v["schema_version"] != 1
            || v["contract"] != "ONLYALPHA_NATIVE_RESEARCH_EXECUTION_V1"
            || v["specification_fingerprint"] != spec.fingerprint()?
            || v["algorithm_artifact_fingerprint"] != spec.algorithm_artifact_fingerprint
            || v["native_image"]["artifact"] != spec.execution_binding["executor_artifact_sha256"]
            || v["native_image"]["protocol"] != spec.execution_binding["protocol"]
            || v["native_image"]["version"] != spec.execution_binding["executor_version"]
        {
            return Err(INVALID);
        }
        let prepared = &v["prepared_inputs"];
        let mut fields = Vec::from([
            "schema_version",
            "contract",
            "runtime_generation_fingerprint",
            "execution_binding",
            "factor_preparation_fingerprint",
            "factor_revision_fingerprint",
            "input_window",
            "dataset_snapshot_fingerprint",
            "dataset_materialization",
            "dataset_construction_fingerprint",
            "algorithm_resolution",
        ]);
        if spec.authoring_generation_fingerprint.is_some() {
            fields.push("authoring_generation_fingerprint");
        }
        exact(prepared, &fields)?;
        if !spec.matches_prepared_authoring(prepared) {
            return Err(INVALID);
        }
        if v["prepared_inputs_fingerprint"] != hash(prepared)?
            || prepared["runtime_generation_fingerprint"] != spec.runtime_generation_fingerprint
            || prepared["execution_binding"] != spec.execution_binding
            || prepared["factor_revision_fingerprint"] != spec.revision["revision_fingerprint"]
            || prepared["factor_preparation_fingerprint"] != spec.factor()?.fingerprint()
            || prepared["dataset_snapshot_fingerprint"] != spec.dataset_snapshot_fingerprint
            || prepared["algorithm_resolution"]["algorithm_artifact"]
                != spec.algorithm_artifact_fingerprint
            || prepared["dataset_materialization"]
                .get("created_at")
                .is_some()
        {
            return Err(INVALID);
        }
        let factor = spec.factor()?;
        let expected_window = factor
            .window(crate::application::research_factor::Window {
                start_ns: spec.study.samples[0].start_ns,
                end_ns: spec.study.samples[1].end_ns,
                bar_ns: spec.study.bar_ns,
                horizon_bars: spec.study.horizon_bars,
            })?
            .to_record();
        let dataset = self
            .datasets
            .load(&spec.dataset_snapshot_fingerprint)
            .map_err(|_| INVALID)?;
        if prepared["input_window"] != expected_window
            || prepared["dataset_construction_fingerprint"]
                != dataset.dataset().construction_fingerprint()
        {
            return Err(INVALID);
        }
        let feature = self.load_calculation(&spec.calculation_fingerprint()?, Some(spec))?;
        let outputs = feature["content"]["algorithm_evaluation"]["outputs"]
            .as_array()
            .ok_or(INVALID)?;
        let implementations = prepared["algorithm_resolution"]["implementations"]
            .as_array()
            .ok_or(INVALID)?;
        for output in outputs {
            let node = factor
                .graph()
                .ordered_nodes()
                .find(|n| output["node_fingerprint"] == n.fingerprint())
                .ok_or(INVALID)?
                .to_record();
            let expected = json!({"kind":node["kind"],"type_id":node["type_id"],"semantic_version":node["semantic_version"]});
            if implementations
                .iter()
                .filter(|i| {
                    i["backend_kind"] == "RESEARCH" && i["calculation_type_reference"] == expected
                })
                .count()
                != 1
                || !implementations.iter().any(|i| {
                    i["implementation_fingerprint"] == output["implementation_fingerprint"]
                        && i["backend_kind"] == "RESEARCH"
                        && i["calculation_type_reference"] == expected
                })
            {
                return Err(INVALID);
            }
        }
        if v["feature_result"] != feature["calculation_result_fingerprint"]
            || v["algorithm_result_fingerprint"]
                != hash(&feature["content"]["algorithm_evaluation"])?
        {
            return Err(INVALID);
        }
        let mut target_results = Vec::new();
        let mut statistics_results = Vec::new();
        let intents = spec.statistics_intents()?;
        if verified.is_some_and(|values| values.len() != intents.len()) {
            return Err(INVALID);
        }
        for intent in intents {
            let id = hash(&intent)?;
            let stat = match verified {
                Some(values) => values
                    .iter()
                    .find(|v| v["statistics_fingerprint"] == id)
                    .cloned()
                    .ok_or(INVALID)?,
                None => self.load_statistics(&id)?,
            };
            let t =
                self.load_calculation(pin(&stat, "target_calculation_fingerprint")?, Some(spec))?;
            target_results.push(t["calculation_result_fingerprint"].clone());
            statistics_results.push(stat);
        }
        statistics_results.sort_by(|a, b| {
            a["statistics_fingerprint"]
                .as_str()
                .cmp(&b["statistics_fingerprint"].as_str())
        });
        if v["target_results"] != json!(target_results)
            || v["statistics_results"]
                != json!(
                    statistics_results
                        .iter()
                        .map(|s| s["statistics_result_fingerprint"].clone())
                        .collect::<Vec<_>>()
                )
        {
            return Err(INVALID);
        }
        Ok(statistics_results)
    }
    fn result_document(
        &self,
        spec: &Specification,
        feature: &Value,
        statistics: &[Value],
        evidence: &Value,
    ) -> Result<Value> {
        let refs=statistics.iter().map(|s|json!({"statistics_fingerprint":s["statistics_fingerprint"],"statistics_result_fingerprint":s["statistics_result_fingerprint"]})).collect::<Vec<_>>();
        signed(
            json!({"schema_version":5,"family":"TIME_SERIES_FACTOR_RESEARCH","specification":spec.record()?,"evaluation_subject":spec.subject()?.to_record(),"research_result_plan":spec.result_plan()?,"research_result_plan_fingerprint":hash(&spec.result_plan()?)?,"dataset_snapshot_fingerprint":spec.dataset_snapshot_fingerprint,"calculation_references":[{"calculation_fingerprint":feature["calculation_fingerprint"],"calculation_result_fingerprint":feature["calculation_result_fingerprint"]}],"statistics_references":refs,"calculation_execution_evidence_fingerprints":[evidence["evidence_fingerprint"]]}),
            "research_result_fingerprint",
        )
    }
    fn validate_result(&self, v: &Value, locator: &str) -> Result<Vec<Value>> {
        self.validate_result_with_statistics(v, locator, None)
    }
    fn validate_result_with_statistics(
        &self,
        v: &Value,
        locator: &str,
        verified: Option<&[Value]>,
    ) -> Result<Vec<Value>> {
        exact(
            v,
            &[
                "schema_version",
                "family",
                "specification",
                "evaluation_subject",
                "research_result_plan",
                "research_result_plan_fingerprint",
                "research_result_fingerprint",
                "dataset_snapshot_fingerprint",
                "calculation_references",
                "statistics_references",
                "calculation_execution_evidence_fingerprints",
            ],
        )?;
        if v["schema_version"] != 5 || v["family"] != "TIME_SERIES_FACTOR_RESEARCH" {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        verify_signed(v, "research_result_fingerprint")?;
        let spec = specification(&v["specification"])?;
        let feature = self.load_calculation(&spec.calculation_fingerprint()?, Some(&spec))?;
        let ids = v["calculation_execution_evidence_fingerprints"]
            .as_array()
            .ok_or(INVALID)?;
        if ids.len() != 1 {
            return Err(INVALID);
        }
        let id = ids[0]
            .as_str()
            .filter(|s| crate::is_sha256_hex(s))
            .ok_or(INVALID)?;
        let evidence = optional(&self.evidence, &["sha256"], id)?.ok_or(INVALID)?;
        if evidence["evidence_fingerprint"] != id {
            return Err(INVALID);
        }
        let statistics = self.validate_evidence(&evidence, &spec, verified)?;
        if v["research_result_plan_fingerprint"] != locator
            || hash(&spec.result_plan()?)? != locator
            || *v != self.result_document(&spec, &feature, &statistics, &evidence)?
        {
            return Err(INVALID);
        }
        Ok(statistics)
    }
}
/// Verified facts live only as long as this exact captured publication cut.
/// The private map can only be populated through complete owning verification.
pub(crate) struct SourceVerification<'cut> {
    locks: &'cut [Arc<SourceLock>],
    facts: BTreeMap<(PathBuf, String), (String, Value)>,
    bytes: usize,
    runtime_root: Option<PathBuf>,
    strategy_cuts: Vec<Arc<StrategyReadCut>>,
    strategy_runs: BTreeMap<String, Value>,
    qualification_cuts: Vec<Arc<super::qualification_decision::VerifiedDecision>>,
}
impl<'cut> SourceVerification<'cut> {
    pub(crate) fn new(locks: &'cut [Arc<SourceLock>]) -> Self {
        Self {
            locks,
            facts: BTreeMap::new(),
            bytes: 0,
            runtime_root: None,
            strategy_cuts: Vec::new(),
            strategy_runs: BTreeMap::new(),
            qualification_cuts: Vec::new(),
        }
    }
    pub(crate) fn with_runtime_root(mut self, root: Option<PathBuf>) -> Self {
        self.runtime_root = root;
        self
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        for lock in self.locks {
            lock.verify()?;
        }
        for cut in &self.strategy_cuts {
            cut.verify()?;
        }
        for decision in &self.qualification_cuts {
            decision.verify_cut()?;
        }
        Ok(())
    }
    /// Same source snapshot transaction as the original PG history capture.
    /// A report is only a locator: the actual DB admission reader creates Run.
    pub(crate) async fn verify_in_transaction(
        &mut self,
        owner_root: &Path,
        family: &str,
        locator: &str,
        tx: &tokio_postgres::Transaction<'_>,
    ) -> Result<(String, Value)> {
        let key = (owner_root.to_path_buf(), locator.to_owned());
        if let Some(value) = self.facts.get(&key) {
            return Ok(value.clone());
        }
        let expected = match family {
            "RESEARCH_RESULT" => "results",
            "RESEARCH_STATISTICS" => "statistics-results",
            _ => return Err("NOVELTY_PROOF_UNAVAILABLE"),
        };
        if owner_root.file_name() != Some(OsStr::new(expected)) {
            return Err(INVALID);
        }
        self.locks
            .iter()
            .find(|l| l.directory.path == owner_root)
            .ok_or(INVALID)?
            .verify()?;
        let mut store = Store::open_for_source(owner_root.parent().ok_or(UNAVAILABLE)?)?;
        let directory = if family == "RESEARCH_RESULT" {
            &store.results
        } else {
            &store.statistics
        };
        // This is only a format candidate. Strategy Statistics1 legitimately
        // owns data.parquet as well; no fact is trusted before the original
        // complete owning reader below verifies its Run and physical closure.
        let value = source_document_candidate(directory, locator)?.ok_or(INVALID)?;
        let strategy = matches!(
            (family, value["schema_version"].as_u64()),
            ("RESEARCH_RESULT", Some(2)) | ("RESEARCH_STATISTICS", Some(1))
        );
        if !strategy {
            return self.verify(owner_root, family, locator);
        }
        let runtime = self
            .runtime_root
            .as_deref()
            .ok_or("NOVELTY_PROOF_UNAVAILABLE")?;
        store = store.with_runtime_root(runtime)?;
        let mut found = false;
        for id in store.strategy_report_ids()? {
            if self.strategy_runs.contains_key(&id) {
                continue;
            }
            let candidate = store.strategy_source_candidate(&id)?;
            let matches = if family == "RESEARCH_RESULT" {
                candidate["research_result_plan_fingerprint"] == locator
            } else {
                candidate["observation"]["statistics"]
                    .as_array()
                    .is_some_and(|rows| rows.iter().any(|r| r["statistics_fingerprint"] == locator))
            };
            if !matches {
                continue;
            }
            let run = super::research_submission::load_in_transaction(tx, &id, None).await?;
            if !matches!(
                run.specification(),
                crate::application::research_run::NativeSpecification::Strategy(_)
            ) || !run.completed()
            {
                return Err("NOVELTY_PROOF_UNAVAILABLE");
            }
            let (report, result, statistics, cut) =
                store.read_strategy_source(&run, self.locks.to_vec())?;
            let mut records = vec![(
                store.results.path.clone(),
                text(&result, "research_result_plan_fingerprint")?.to_owned(),
                text(&result, "research_result_fingerprint")?.to_owned(),
                result,
            )];
            for statistic in statistics {
                records.push((
                    store.statistics.path.clone(),
                    text(&statistic, "statistics_fingerprint")?.to_owned(),
                    text(&statistic, "statistics_result_fingerprint")?.to_owned(),
                    statistic,
                ));
            }
            for (root, logical, identity, value) in records {
                let key = (root, logical);
                let record = (identity, value);
                if let Some(previous) = self.facts.get(&key) {
                    if previous != &record {
                        return Err(INVALID);
                    }
                } else {
                    self.bytes = self
                        .bytes
                        .checked_add(serde_json::to_vec(&record.1).map_err(|_| INVALID)?.len())
                        .filter(|n| *n <= LIMIT)
                        .ok_or(UNAVAILABLE)?;
                    self.facts.insert(key, record);
                }
            }
            let context = json!({"run_id":run.run_id(),"specification_fingerprint":run.specification_fingerprint(),
                "scientific_specification_fingerprint":run.specification().scientific_specification_fingerprint()?,
                "research_result_plan_fingerprint":report["research_result_plan_fingerprint"],"research_result_fingerprint":report["research_result_fingerprint"],
                "artifact_content_fingerprint":report["artifact_content_fingerprint"],"candidate_fingerprint":report["candidate_fingerprint"],
                "calculation_execution_evidence_fingerprints":report["calculation_execution_evidence_fingerprints"]});
            self.strategy_runs.insert(id, context);
            self.strategy_cuts.push(cut);
            found = true;
        }
        if !found && !self.facts.contains_key(&key) {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        self.verify_cut()?;
        self.facts.get(&key).cloned().ok_or(INVALID)
    }
    /// Q enum2 is the canonical evaluator-owned namespace. Original Run/report
    /// records are read locators, not new Decision identity or receipt requirements.
    pub(crate) async fn verify_qualification_in_transaction(
        &mut self,
        owner_root: &Path,
        locator: &str,
        tx: &tokio_postgres::Transaction<'_>,
    ) -> Result<(String, Value)> {
        use super::qualification_decision::Store as Decisions;
        use crate::application::{
            frozen_strategy::FrozenStore, qualification_policy::Store as Policies,
        };
        use std::os::fd::AsFd;
        let key = (owner_root.to_path_buf(), locator.to_owned());
        if let Some(value) = self.facts.get(&key) {
            return Ok(value.clone());
        }
        let strategy = owner_root
            .parent()
            .filter(|path| path.file_name() == Some(OsStr::new("strategy")))
            .ok_or(INVALID)?;
        let research = strategy.parent().ok_or(INVALID)?;
        if owner_root != research.join("strategy/qualification-decisions") {
            return Err(INVALID);
        }
        let source = self
            .locks
            .iter()
            .find(|cut| cut.directory.path == owner_root)
            .ok_or(INVALID)?
            .clone();
        source.verify()?;
        let decisions = Arc::new(Decisions::open(research)?);
        let candidate = decisions.source_candidate(locator, &source)?;
        if candidate["gate"] == "MANUAL_STRATEGY_TO_BACKTEST" {
            let evidence = candidate["evidence"]
                .as_array()
                .filter(|rows| rows.len() == 1)
                .ok_or(INVALID)?;
            let evidence = &evidence[0];
            exact(
                evidence,
                &[
                    "kind",
                    "evidence_fingerprint",
                    "preparation_command_id",
                    "subject_binding_fingerprint",
                ],
            )?;
            if evidence["kind"] != "STRATEGY_VALIDATION" {
                return Err(INVALID);
            }
            let validation_id = pin(evidence, "evidence_fingerprint")?;
            let relation_id = pin(evidence, "subject_binding_fingerprint")?;
            let subject = pin(&candidate, "subject_strategy_fingerprint")?;
            let preparation = crate::application::command::CommandId::new(text(
                evidence,
                "preparation_command_id",
            )?)
            .map_err(|_| INVALID)?;
            let runtime = self
                .runtime_root
                .as_deref()
                .ok_or("NOVELTY_PROOF_UNAVAILABLE")?;
            let validations =
                super::strategy_validation::Store::open(research)?.with_runtime_root(runtime)?;
            let validation = Arc::new(
                validations
                    .read_verified_captured_in_transaction(
                        tx,
                        preparation.value(),
                        self.locks.to_vec(),
                    )
                    .await?,
            );
            if validation.fingerprint() != validation_id
                || validation.source_revision().fingerprint() != subject
            {
                return Err(INVALID);
            }
            let root = Directory::open(research)?;
            let frozen = FrozenStore::open(root.fd.as_fd()).map_err(|_| INVALID)?;
            let proof = Arc::new(
                frozen
                    .read_verified_manual(validation, relation_id, 64 * 1024 * 1024)
                    .map_err(|e| e.code())?,
            );
            let policies = Arc::new(Policies::open(root.fd.as_fd()).map_err(|_| INVALID)?);
            let decision = Arc::new(
                decisions.load_manual_verified_captured(policies, &proof, locator, source)?,
            );
            if decision.record() != &candidate {
                return Err(INVALID);
            }
            decision
                .verify_in_transaction(tx, &decisions.namespace()?)
                .await?;
            let record = (locator.to_owned(), decision.record().clone());
            self.bytes = self
                .bytes
                .checked_add(serde_json::to_vec(&record.1).map_err(|_| INVALID)?.len())
                .filter(|n| *n <= LIMIT)
                .ok_or(UNAVAILABLE)?;
            self.qualification_cuts.push(decision);
            self.facts.insert(key, record.clone());
            self.verify_cut()?;
            return Ok(record);
        }
        if candidate["gate"] != "RESEARCH_TO_BACKTEST" {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        let evidence = candidate["evidence"]
            .as_array()
            .filter(|rows| rows.len() == 1)
            .ok_or(INVALID)?;
        let evidence = &evidence[0];
        exact(
            evidence,
            &[
                "kind",
                "evidence_fingerprint",
                "locator_fingerprint",
                "subject_binding_fingerprint",
            ],
        )?;
        if evidence["kind"] != "RESEARCH_RESULT" {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        let result = pin(evidence, "evidence_fingerprint")?;
        let plan = pin(evidence, "locator_fingerprint")?;
        let relation_id = pin(evidence, "subject_binding_fingerprint")?;
        let subject = pin(&candidate, "subject_strategy_fingerprint")?;
        let runtime = self
            .runtime_root
            .as_deref()
            .ok_or("NOVELTY_PROOF_UNAVAILABLE")?;
        let store = Store::open_for_source(research)?.with_runtime_root(runtime)?;
        let (result_id, _) = self
            .verify_in_transaction(&research.join("results"), "RESEARCH_RESULT", plan, tx)
            .await?;
        if result_id != result {
            return Err(INVALID);
        }
        let frozen = FrozenStore::open(store.root.fd.as_fd()).map_err(|_| INVALID)?;
        // This new source reader uses the existing Qualification/Frozen inventory
        // work allowance. Counts keeps its owning verification/budgets unchanged.
        let relation = frozen
            .load_relation_verified(relation_id, 64 * 1024 * 1024)
            .map_err(|_| INVALID)?;
        let binding = relation.to_record();
        if relation.strategy_fingerprint() != subject
            || binding["research_result_fingerprint"] != result
        {
            return Err(INVALID);
        }
        let policies = Arc::new(Policies::open(store.root.fd.as_fd()).map_err(|_| INVALID)?);
        // The immutable report inventory is only a locator selection. Take a
        // completed exact original occurrence in stable order; once selected,
        // any corrupt owning input fails rather than searching for a substitute.
        let mut verified = None;
        for id in store.strategy_report_ids()? {
            let report = store.strategy_source_candidate(&id)?;
            if report["research_result_plan_fingerprint"] != plan
                || report["research_result_fingerprint"] != result
                || report["candidate_fingerprint"] != binding["candidate_fingerprint"]
                || report["source_revision"]["strategy_fingerprint"] != subject
            {
                continue;
            }
            let run = super::research_submission::load_in_transaction(tx, &id, None).await?;
            if !run.completed() {
                continue;
            }
            if !matches!(
                run.specification(),
                crate::application::research_run::NativeSpecification::Strategy(_)
            ) {
                return Err(INVALID);
            }
            let counts = Arc::new(store.read_verified_counts_captured(
                &run,
                &frozen,
                relation_id,
                self.locks.to_vec(),
            )?);
            if counts.subject_strategy_fingerprint() != subject
                || counts.research_result_fingerprint() != result
                || counts.research_result_plan_fingerprint() != plan
                || counts.freeze_relation_fingerprint() != relation_id
            {
                return Err(INVALID);
            }
            let decision = Arc::new(decisions.load_verified_captured(
                policies.clone(),
                &counts,
                locator,
                source.clone(),
            )?);
            if decision.record() != &candidate {
                return Err(INVALID);
            }
            verified = Some(decision);
            break;
        }
        let decision = verified.ok_or("NOVELTY_PROOF_UNAVAILABLE")?;
        decision.verify_cut()?;
        let record = (locator.to_owned(), decision.record().clone());
        self.bytes = self
            .bytes
            .checked_add(serde_json::to_vec(&record.1).map_err(|_| INVALID)?.len())
            .filter(|n| *n <= LIMIT)
            .ok_or(UNAVAILABLE)?;
        self.qualification_cuts.push(decision);
        self.facts.insert(key, record.clone());
        self.verify_cut()?;
        Ok(record)
    }
    pub(crate) fn qualification_cuts(
        &self,
    ) -> Vec<Arc<super::qualification_decision::VerifiedDecision>> {
        self.qualification_cuts.clone()
    }
    pub(crate) fn strategy_runs(&self) -> &BTreeMap<String, Value> {
        &self.strategy_runs
    }
    pub(crate) fn strategy_cuts(&self) -> Vec<Arc<StrategyReadCut>> {
        self.strategy_cuts.clone()
    }
    pub(crate) fn verify(
        &mut self,
        owner_root: &Path,
        family: &str,
        locator: &str,
    ) -> Result<(String, Value)> {
        let expected = match family {
            "RESEARCH_RESULT" => "results",
            "RESEARCH_STATISTICS" => "statistics-results",
            _ => return Err("NOVELTY_PROOF_UNAVAILABLE"),
        };
        if owner_root.file_name() != Some(OsStr::new(expected)) {
            return Err(INVALID);
        }
        self.locks
            .iter()
            .find(|lock| lock.directory.path == owner_root)
            .ok_or(INVALID)?
            .verify()?;
        let key = (owner_root.to_path_buf(), locator.to_owned());
        if let Some(value) = self.facts.get(&key) {
            return Ok(value.clone());
        }
        let store = Store::open_for_source(owner_root.parent().ok_or(UNAVAILABLE)?)?;
        let value = if family == "RESEARCH_RESULT" {
            let v = optional(&store.results, &["sha256"], locator)?.ok_or(INVALID)?;
            let spec = specification(&v["specification"])?;
            let mut statistics = Vec::new();
            for intent in spec.statistics_intents()? {
                statistics.push(
                    self.verify(
                        &store.statistics.path,
                        "RESEARCH_STATISTICS",
                        &hash(&intent)?,
                    )?
                    .1,
                );
            }
            store.validate_result_with_statistics(&v, locator, Some(&statistics))?;
            v
        } else {
            store.load_statistics(locator)?
        };
        let identity = if family == "RESEARCH_RESULT" {
            pin(&value, "research_result_fingerprint")?
        } else {
            pin(&value, "statistics_result_fingerprint")?
        }
        .to_owned();
        self.bytes = self
            .bytes
            .checked_add(serde_json::to_vec(&value).map_err(|_| INVALID)?.len())
            .filter(|size| *size <= LIMIT)
            .ok_or(UNAVAILABLE)?;
        let verified = (identity, value);
        self.facts.insert(key, verified.clone());
        Ok(verified)
    }
}

fn exact(v: &Value, keys: &[&str]) -> Result<()> {
    let o = v.as_object().ok_or(INVALID)?;
    if o.len() != keys.len() || keys.iter().any(|k| !o.contains_key(*k)) {
        Err(INVALID)
    } else {
        Ok(())
    }
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(INVALID)
}
fn pin<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    Some(text(v, k)?)
        .filter(|s| crate::is_sha256_hex(s))
        .ok_or(INVALID)
}
fn number(v: &Value, k: &str) -> Result<u64> {
    v[k].as_u64().ok_or(INVALID)
}
fn number_text(v: &Value, k: &str) -> Result<u64> {
    text(v, k)?.parse().map_err(|_| INVALID)
}
fn specification(v: &Value) -> Result<Specification> {
    let s: Specification = serde_json::from_value(v.clone()).map_err(|_| INVALID)?;
    s.validate()?;
    Ok(s)
}
fn verify_signed(v: &Value, key: &str) -> Result<()> {
    let expected = pin(v, key)?;
    let mut body = v.clone();
    body.as_object_mut().ok_or(INVALID)?.remove(key);
    if hash(&body)? != expected {
        return Err(INVALID);
    }
    Ok(())
}
fn decimal_or_null(v: &Value) -> Result<()> {
    if v.is_null() {
        Ok(())
    } else {
        statistics::decimal(v.as_str().ok_or(INVALID)?)
            .map(|_| ())
            .map_err(|_| INVALID)
    }
}
fn save(owner: &Directory, id: &str, v: &Value) -> Result<()> {
    if !crate::is_sha256_hex(id) {
        return Err(INVALID);
    }
    put(owner, &["sha256", &id[..2], id], "manifest.json", v).map_err(map_file_error)
}
fn map_file_error(e: &'static str) -> &'static str {
    if e == "IMMUTABLE_JSON_INVALID" {
        INVALID
    } else {
        UNAVAILABLE
    }
}
fn verify_lockfile(owner: &Directory) -> Result<()> {
    inspect_source_layout(&owner.path).map_err(map_file_error)?;
    owner.verify().map_err(map_file_error)
}
/// Canonical format selection only, never a verified fact or Source grant.
/// Factor fallback retains optional()'s manifest-only layout and all validators;
/// Strategy selection still requires the complete original read_strategy_source.
fn source_document_candidate(owner: &Directory, id: &str) -> Result<Option<Value>> {
    if !crate::is_sha256_hex(id) {
        return Err(INVALID);
    }
    owner.verify().map_err(map_file_error)?;
    // A missing owner namespace is unavailable, never a certified absent leaf.
    let namespace = owner.path(&["sha256"], false).map_err(map_file_error)?;
    let Some(leaf) = strategy::physical::optional_directory(&namespace, &[&id[..2], id])? else {
        return Ok(None);
    };
    // Preserve the existing HistoryDocument policy (including trusted hardlinks).
    // The full Strategy physical owner independently enforces its stronger rules.
    let value = leaf.read("manifest.json").map_err(map_file_error)?;
    namespace.verify().map_err(map_file_error)?;
    leaf.verify().map_err(map_file_error)?;
    owner.verify().map_err(map_file_error)?;
    Ok(Some(value))
}
/// Missing immutable leaf is absence only inside a verified, provisioned owner namespace.
fn optional(owner: &Directory, namespace: &[&str], id: &str) -> Result<Option<Value>> {
    if !crate::is_sha256_hex(id) {
        return Err(INVALID);
    }
    owner.verify().map_err(map_file_error)?;
    let namespace = owner.path(namespace, false).map_err(map_file_error)?;
    let shard = match files::open_directory_at(&namespace.fd, OsStr::new(&id[..2])) {
        Ok(fd) => Directory {
            path: namespace.path.join(&id[..2]),
            fd,
        },
        Err(ReadError::Missing) => return Ok(None),
        Err(_) => return Err(UNAVAILABLE),
    };
    let leaf = match files::open_directory_at(&shard.fd, OsStr::new(id)) {
        Ok(fd) => Directory {
            path: shard.path.join(id),
            fd,
        },
        Err(ReadError::Missing) => return Ok(None),
        Err(_) => return Err(UNAVAILABLE),
    };
    if leaf.names().map_err(map_file_error)? != vec!["manifest.json".to_string()] {
        return Err(INVALID);
    }
    let value = leaf.read("manifest.json").map_err(map_file_error)?;
    namespace.verify().map_err(map_file_error)?;
    shard.verify().map_err(map_file_error)?;
    leaf.verify().map_err(map_file_error)?;
    Ok(Some(value))
}
fn report(result: &Value, statistics: &[Value]) -> Result<Value> {
    signed(
        json!({"schema_version":1,"profile":"RESEARCH_TIME_SERIES_REPORT_V1","research_result_fingerprint":result["research_result_fingerprint"],"research_result_plan_fingerprint":result["research_result_plan_fingerprint"],"evaluation_subject":result["evaluation_subject"],"statistics":statistics}),
        "artifact_content_fingerprint",
    )
}
/// Structural diagnostics and numeric representation checks; never re-estimates statistics.
fn validate_analysis(v: &Value, plan: &Plan, observations: &[Observation]) -> Result<()> {
    exact(
        v,
        &[
            "plan_fingerprint",
            "input_fingerprint",
            "diagnostics",
            "pearson",
            "spearman",
        ],
    )?;
    if v["plan_fingerprint"]
        != hash(
            &json!({"method":"ONLYALPHA_TIME_SERIES_ASSOCIATION_V1","plan":serde_json::to_value(plan).map_err(|_|INVALID)?}),
        )?
        || v["input_fingerprint"]
            != hash(
                &json!({"method":"ONLYALPHA_TIME_SERIES_ASSOCIATION_V1","observations":serde_json::to_value(observations).map_err(|_|INVALID)?}),
            )?
    {
        return Err(INVALID);
    }
    let d = &v["diagnostics"];
    exact(
        d,
        &[
            "expected_rows",
            "observed_rows",
            "boundary_excluded",
            "complete_pairs",
            "missing_feature",
            "missing_target",
            "axis_gaps",
        ],
    )?;
    let expected = (plan.end_ns - plan.start_ns) / plan.bar_ns;
    let cutoff = plan.end_ns - u64::from(plan.horizon_bars) * plan.bar_ns;
    let mut boundary = 0u64;
    let mut pairs = 0u64;
    let mut feature = 0u64;
    let mut target = 0u64;
    let mut previous = None;
    for row in observations {
        if row.at_ns < plan.start_ns
            || row.at_ns >= plan.end_ns
            || !(row.at_ns - plan.start_ns).is_multiple_of(plan.bar_ns)
            || previous.is_some_and(|p| p >= row.at_ns)
        {
            return Err(INVALID);
        }
        previous = Some(row.at_ns);
        if row.at_ns >= cutoff {
            boundary += 1;
            continue;
        }
        feature += u64::from(row.feature.is_none());
        target += u64::from(row.target.is_none());
        pairs += u64::from(row.feature.is_some() && row.target.is_some());
    }
    if d != &json!({"expected_rows":expected,"observed_rows":observations.len(),"boundary_excluded":boundary,"complete_pairs":pairs,"missing_feature":feature,"missing_target":target,"axis_gaps":expected.checked_sub(observations.len() as u64).ok_or(INVALID)?})
    {
        return Err(INVALID);
    }
    for key in ["pearson", "spearman"] {
        let e = &v[key];
        exact(
            e,
            &[
                "point_status",
                "value",
                "uncertainty_status",
                "interval",
                "undefined_replicates",
            ],
        )?;
        let point = text(e, "point_status")?;
        let uncertainty = text(e, "uncertainty_status")?;
        const STATES: [&str; 10] = [
            "AVAILABLE",
            "INSUFFICIENT_PAIRS",
            "ZERO_VARIANCE_FEATURE",
            "ZERO_VARIANCE_TARGET",
            "GAPPED_AXIS",
            "INCOMPLETE_PAIRS",
            "INSUFFICIENT_BLOCKS",
            "TAIL_RESOLUTION_INSUFFICIENT",
            "UNDEFINED_BOOTSTRAP_REPLICATES",
            "BOOTSTRAP_DISTRIBUTION_DEGENERATE",
        ];
        if !STATES.contains(&point)
            || !STATES.contains(&uncertainty)
            || number(e, "undefined_replicates")? > u64::from(plan.replicates)
            || (point == "AVAILABLE") != e["value"].is_string()
            || (uncertainty == "AVAILABLE") != e["interval"].is_array()
            || (uncertainty != "AVAILABLE" && !e["interval"].is_null())
            || (uncertainty == "AVAILABLE" && point != "AVAILABLE")
        {
            return Err(INVALID);
        }
        decimal_or_null(&e["value"])?;
        if let Some(interval) = e["interval"].as_array() {
            if interval.len() != 2 {
                return Err(INVALID);
            }
            for value in interval {
                if !value.is_string() {
                    return Err(INVALID);
                }
                decimal_or_null(value)?;
            }
            let a = statistics::decimal(interval[0].as_str().ok_or(INVALID)?)?.1;
            let b = statistics::decimal(interval[1].as_str().ok_or(INVALID)?)?.1;
            if a > b {
                return Err(INVALID);
            }
        }
    }
    Ok(())
}

/// Exact count projection of a verified Result and its verified Freeze relation.
/// Only this persistence owner may construct it; no public constructor,
/// deserializer, mutable record or caller-authored count API is exposed.
pub struct VerifiedResearchCounts {
    subject_strategy_fingerprint: String,
    research_result_fingerprint: String,
    research_result_plan_fingerprint: String,
    freeze_relation_fingerprint: String,
    statistics_result_count: u64,
    calculation_result_count: u64,
    validated_calculations: Option<Value>,
    source_locks: Vec<Arc<SourceLock>>,
    strategy_cut: Option<Arc<StrategyReadCut>>,
}
impl VerifiedResearchCounts {
    /// Original installed definitions/implementations from the actual report,
    /// retained under its owning cut. Unit count vectors supply no provenance.
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        self.validated_calculations
            .as_ref()
            .ok_or("QUALIFICATION_VALIDATED_CALCULATIONS_REQUIRED")
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        if self.source_locks.is_empty() {
            return Err("QUALIFICATION_RESEARCH_CUT_REQUIRED");
        }
        if let Some(cut) = &self.strategy_cut {
            cut.verify()?;
        }
        for lock in &self.source_locks {
            lock.verify()?;
        }
        Ok(())
    }
    pub(crate) fn source_locks(&self) -> Vec<Arc<SourceLock>> {
        self.source_locks.clone()
    }
    pub(crate) fn subject_strategy_fingerprint(&self) -> &str {
        &self.subject_strategy_fingerprint
    }
    pub(crate) fn research_result_fingerprint(&self) -> &str {
        &self.research_result_fingerprint
    }
    pub(crate) fn research_result_plan_fingerprint(&self) -> &str {
        &self.research_result_plan_fingerprint
    }
    pub(crate) fn freeze_relation_fingerprint(&self) -> &str {
        &self.freeze_relation_fingerprint
    }
    pub(crate) fn statistics_result_count(&self) -> u64 {
        self.statistics_result_count
    }
    pub(crate) fn calculation_result_count(&self) -> u64 {
        self.calculation_result_count
    }
}

#[cfg(test)]
impl VerifiedResearchCounts {
    /// Unit value vectors only; never reachable in the production application.
    pub(crate) fn for_value_test(
        subject_strategy_fingerprint: String,
        research_result_fingerprint: String,
        research_result_plan_fingerprint: String,
        freeze_relation_fingerprint: String,
        statistics_result_count: u64,
        calculation_result_count: u64,
    ) -> Self {
        Self {
            subject_strategy_fingerprint,
            research_result_fingerprint,
            research_result_plan_fingerprint,
            freeze_relation_fingerprint,
            statistics_result_count,
            calculation_result_count,
            validated_calculations: None,
            source_locks: vec![],
            strategy_cut: None,
        }
    }
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn for_persistence_test(
        subject: String,
        result: String,
        plan: String,
        relation: String,
        statistics: u64,
        calculations: u64,
        cut: Arc<SourceLock>,
    ) -> Self {
        let mut value =
            Self::for_value_test(subject, result, plan, relation, statistics, calculations);
        value.source_locks = vec![cut];
        value
    }
}

/// An owning-reader seal for complete PRIVATE_STRATEGY scientific and admission
/// evidence. Neither parsing SourceRevision nor receiving a DTO grants this seal.
/// Construction remains private to this persistence owner.
pub struct VerifiedStrategyResearch {
    run_id: String,
    specification_fingerprint: String,
    source_revision: onlyalpha_strategy::SourceRevision,
    candidate_fingerprint: String,
    research_result_fingerprint: String,
    research_execution_evidence_fingerprints: Vec<String>,
    admission_evidence_fingerprint: String,
    equivalence_evidence_fingerprints: Vec<String>,
    source_locks: Vec<Arc<SourceLock>>,
    strategy_cut: Option<Arc<StrategyReadCut>>,
}
impl VerifiedStrategyResearch {
    pub(crate) fn run_id(&self) -> &str {
        &self.run_id
    }
    pub(crate) fn specification_fingerprint(&self) -> &str {
        &self.specification_fingerprint
    }
    pub(crate) fn source_revision(&self) -> &onlyalpha_strategy::SourceRevision {
        &self.source_revision
    }
    pub(crate) fn candidate_fingerprint(&self) -> &str {
        &self.candidate_fingerprint
    }
    pub(crate) fn research_result_fingerprint(&self) -> &str {
        &self.research_result_fingerprint
    }
    pub(crate) fn research_execution_evidence_fingerprints(&self) -> &[String] {
        &self.research_execution_evidence_fingerprints
    }
    pub(crate) fn admission_evidence_fingerprint(&self) -> &str {
        &self.admission_evidence_fingerprint
    }
    pub(crate) fn equivalence_evidence_fingerprints(&self) -> &[String] {
        &self.equivalence_evidence_fingerprints
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        if self.source_locks.is_empty() {
            return Err("STRATEGY_RESEARCH_CUT_REQUIRED");
        }
        if let Some(cut) = &self.strategy_cut {
            cut.verify()?;
        }
        for lock in &self.source_locks {
            lock.verify()?;
        }
        Ok(())
    }
}
#[cfg(test)]
impl VerifiedStrategyResearch {
    /// Value and persistence tests only; absent from production builds.
    #[allow(clippy::too_many_arguments)]
    pub(crate) fn for_value_test(
        run_id: String,
        specification_fingerprint: String,
        source_revision: onlyalpha_strategy::SourceRevision,
        candidate_fingerprint: String,
        research_result_fingerprint: String,
        research_execution_evidence_fingerprints: Vec<String>,
        admission_evidence_fingerprint: String,
        equivalence_evidence_fingerprints: Vec<String>,
        source_locks: Vec<Arc<SourceLock>>,
    ) -> Self {
        Self {
            run_id,
            specification_fingerprint,
            source_revision,
            candidate_fingerprint,
            research_result_fingerprint,
            research_execution_evidence_fingerprints,
            admission_evidence_fingerprint,
            equivalence_evidence_fingerprints,
            source_locks,
            strategy_cut: None,
        }
    }
}

#[cfg(test)]
mod source_document_candidate_tests {
    use super::*;
    use std::{
        fs as std_fs,
        os::unix::fs::{PermissionsExt, symlink},
        sync::atomic::{AtomicU64, Ordering},
    };
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Root(PathBuf);
    impl Root {
        fn new() -> Self {
            let path = std::env::temp_dir().join(format!(
                "oa-evidence-candidate-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            std_fs::create_dir(&path).unwrap();
            Self(path)
        }
        fn leaf(&self, id: &str, value: &Value) -> PathBuf {
            let path = self.0.join("sha256").join(&id[..2]).join(id);
            std_fs::create_dir_all(&path).unwrap();
            std_fs::write(path.join("manifest.json"), value.to_string()).unwrap();
            path
        }
        fn owner(&self) -> Directory {
            Directory::open(&self.0).unwrap()
        }
    }
    impl Drop for Root {
        fn drop(&mut self) {
            std_fs::remove_dir_all(&self.0).unwrap();
        }
    }
    #[test]
    fn classification_reads_strategy_bundle_without_relaxing_the_factor_leaf() {
        let root = Root::new();
        let id = "a".repeat(64);
        // Format candidate only: this does not manufacture a verified Statistics
        // fact, completed Run, physical Parquet proof or publication permission.
        let value = json!({"schema_version":1,"statistics_fingerprint":id});
        let leaf = root.leaf(&id, &value);
        std_fs::write(leaf.join("data.parquet"), b"not a valid Parquet proof").unwrap();
        let owner = root.owner();
        assert_eq!(source_document_candidate(&owner, &id).unwrap(), Some(value));
        assert_eq!(optional(&owner, &["sha256"], &id), Err(INVALID));
        let factor =
            json!({"schema_version":2,"statistics_family":"ONLYALPHA_TIME_SERIES_ASSOCIATION_V1"});
        std_fs::write(leaf.join("manifest.json"), factor.to_string()).unwrap();
        assert_eq!(
            source_document_candidate(&owner, &id).unwrap(),
            Some(factor.clone())
        );
        assert_eq!(
            optional(&owner, &["sha256"], &id),
            Err(INVALID),
            "factor fallback must still reject all extra files"
        );
        std_fs::remove_file(leaf.join("data.parquet")).unwrap();
        assert_eq!(optional(&owner, &["sha256"], &id).unwrap(), Some(factor));
    }
    #[test]
    fn classification_preserves_absence_only_in_an_existing_namespace() {
        let root = Root::new();
        let id = "a".repeat(64);
        let owner = root.owner();
        assert!(source_document_candidate(&owner, &id).is_err());
        assert!(!root.0.join("sha256").exists());
        std_fs::create_dir(root.0.join("sha256")).unwrap();
        assert_eq!(source_document_candidate(&owner, &id).unwrap(), None);
        assert!(root.0.join("sha256").read_dir().unwrap().next().is_none());
        assert_eq!(
            source_document_candidate(&owner, "../foreign"),
            Err(INVALID)
        );
    }
    #[test]
    fn unsafe_or_noncanonical_candidates_never_fall_back_to_other_formats() {
        for fault in [
            "manifest-symlink",
            "leaf-symlink",
            "noncanonical",
            "writable",
        ] {
            let root = Root::new();
            let id = "a".repeat(64);
            let leaf = root.leaf(&id, &json!({"schema_version":1}));
            let manifest = leaf.join("manifest.json");
            match fault {
                "manifest-symlink" => {
                    let saved = root.0.join("retained");
                    std_fs::rename(&manifest, &saved).unwrap();
                    symlink(saved, &manifest).unwrap();
                }
                "leaf-symlink" => {
                    let saved = root.0.join("retained");
                    std_fs::rename(&leaf, &saved).unwrap();
                    symlink(saved, &leaf).unwrap();
                }
                "noncanonical" => std_fs::write(&manifest, "{\"schema_version\": 1}").unwrap(),
                "writable" => {
                    std_fs::set_permissions(&manifest, std_fs::Permissions::from_mode(0o666))
                        .unwrap()
                }
                _ => unreachable!(),
            }
            assert!(
                source_document_candidate(&root.owner(), &id).is_err(),
                "{fault}"
            );
        }
    }
    #[test]
    fn factor_candidate_and_strict_read_keep_trusted_history_hardlinks() {
        let root = Root::new();
        let id = "a".repeat(64);
        let value = json!({"schema_version":2});
        let leaf = root.leaf(&id, &value);
        std_fs::hard_link(leaf.join("manifest.json"), root.0.join("retained")).unwrap();
        let owner = root.owner();
        assert_eq!(
            source_document_candidate(&owner, &id).unwrap(),
            Some(value.clone())
        );
        assert_eq!(optional(&owner, &["sha256"], &id).unwrap(), Some(value));
    }
}
