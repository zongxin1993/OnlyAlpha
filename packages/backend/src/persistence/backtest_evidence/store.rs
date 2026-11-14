//! One immutable Evidence owner. Only the concrete positively joined producer may publish.
use super::{
    BUDGET, BacktestReadContext, CompletionProof, INVALID, Manifest, Result, UNAVAILABLE,
    physical::{self, Bundle},
};
use crate::{
    application::factor_content::hash,
    persistence::backtest_run::RunState,
    security::{
        immutable_json::{self, Directory, SourceLock},
        protected_files,
    },
    workers::{
        algorithm::describe_research_runtime, backtest_result::ObservedBacktest,
        backtest_service::JoinedBacktest,
    },
};
use onlyalpha_backtest::{RunSpec, TerminalSnapshot};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    os::fd::AsFd,
    path::{Path, PathBuf},
    sync::Arc,
};
const HISTORICAL: &str = "BACKTEST_HISTORICAL_READER_UNAVAILABLE";
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(INVALID)
}
pub(super) struct Cut {
    context: BacktestReadContext,
    source: Arc<SourceLock>,
    bundle: Arc<Bundle>,
    snapshot: Arc<TerminalSnapshot>,
}
impl Cut {
    pub(super) fn verify(&self) -> Result<()> {
        crate::workers::backtest_profile::measure(
            self.context.run().run_id(),
            "evidence.cut.verify",
            || {
                self.source.verify().map_err(|_| INVALID)?;
                self.context.verify_cut()?;
                crate::workers::backtest_profile::measure(
                    self.context.run().run_id(),
                    "evidence.bundle.verify",
                    || self.bundle.verify(),
                )?;
                crate::workers::backtest_profile::measure(
                    self.context.run().run_id(),
                    "terminal.verify_cut",
                    || self.snapshot.verify_cut(),
                )
                .map_err(|_| INVALID)?;
                self.source.verify().map_err(|_| INVALID)?;
                self.context.verify_cut()
            },
        )
    }
}
pub(crate) struct VerifiedEvidence {
    manifest: Manifest,
    values: BTreeMap<String, Value>,
    cut: Arc<Cut>,
}
impl VerifiedEvidence {
    pub(crate) fn manifest(&self) -> &Manifest {
        &self.manifest
    }
    pub(crate) fn observation(&self) -> &Value {
        &self.values["observation.json"]
    }
    pub(crate) fn result(&self) -> &Value {
        &self.values["result.json"]
    }
    pub(crate) fn trace(&self) -> &Value {
        &self.values["replay-trace.json"]
    }
    pub(crate) fn artifact(&self, name: &str) -> Result<(Vec<u8>, String)> {
        self.verify_cut()?;
        let artifact = self.manifest.record()["artifacts"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .find(|a| a["name"] == name)
            .ok_or("BACKTEST_EVIDENCE_ARTIFACT_NOT_FOUND")?;
        let value = (
            self.cut.bundle.bytes(name)?.to_vec(),
            text(artifact, "media_type")?.to_owned(),
        );
        self.verify_cut()?;
        Ok(value)
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        self.cut.verify()
    }
    pub(crate) fn for_each_step(
        &self,
        visit: &mut dyn FnMut(&Value, bool) -> Result<()>,
    ) -> Result<()> {
        self.verify_cut()?;
        self.cut
            .snapshot
            .for_each_step(&mut |step, ready| {
                visit(step, ready).map_err(|code| onlyalpha_backtest::Error(code.into()))
            })
            .map_err(|_| INVALID)?;
        self.verify_cut()
    }
    fn completion(&self) -> Result<CompletionProof> {
        self.verify_cut()?;
        let run = self.cut.context.run();
        let record = self.manifest.record();
        Ok(CompletionProof {
            run: run.run_id().into(),
            specification: run.specification_fingerprint().into(),
            resolution: run.admission_resolution_fingerprint().into(),
            status: text(&self.values["replay-proof.json"], "status")?.into(),
            evidence: self.manifest.fingerprint().into(),
            result: text(record, "result_fingerprint")?.into(),
            determinism: text(record, "determinism_fingerprint")?.into(),
            cut: vec![self.cut.source.clone()],
            verified: Some(self.cut.clone()),
        })
    }
}
pub(crate) struct Store {
    root: Directory,
    evidence: Directory,
    research: PathBuf,
    runtime: PathBuf,
}
impl Store {
    /// Existing Infrastructure-provisioned roots only. No writer or repair is opened.
    pub(crate) fn open(backtest: &Path, research: &Path, runtime: &Path) -> Result<Self> {
        let root = Directory::open(backtest).map_err(|_| UNAVAILABLE)?;
        let evidence = root.child("evidence", false).map_err(|_| UNAVAILABLE)?;
        immutable_json::inspect_source_layout(&evidence.path).map_err(|_| UNAVAILABLE)?;
        evidence.child("sha256", false).map_err(|_| UNAVAILABLE)?;
        protected_files::open_directory(research).map_err(|_| UNAVAILABLE)?;
        protected_files::open_directory(runtime).map_err(|_| UNAVAILABLE)?;
        let value = Self {
            root,
            evidence,
            research: research.into(),
            runtime: runtime.into(),
        };
        value.verify_layout()?;
        Ok(value)
    }
    fn verify_layout(&self) -> Result<()> {
        self.root.verify().map_err(|_| INVALID)?;
        self.evidence.verify().map_err(|_| INVALID)?;
        let mut budget = 64 * 1024 * 1024;
        for name in physical::names(&self.evidence, &mut budget)? {
            match name.as_str() {
                ".source-cut.lock" => {}
                "sha256" | ".immutable-json-staging" => {
                    self.evidence.child(&name, false).map_err(|_| INVALID)?;
                }
                _ => return Err(INVALID),
            }
        }
        immutable_json::inspect_source_layout(&self.evidence.path).map_err(|_| INVALID)
    }
    fn require_context(&self, context: &BacktestReadContext) -> Result<()> {
        crate::workers::backtest_profile::measure(
            context.run().run_id(),
            "evidence.require_context",
            || {
                self.verify_layout()?;
                context.roots_match(&self.research, &self.runtime)?;
                context.verify_cut()
            },
        )
    }
    /// The original Run locator is selected only when SQL has not yet pinned
    /// its terminal bundle. Every encountered manifest retains exact SHA identity.
    fn find(&self, run: &str) -> Result<Option<String>> {
        let sha = self.evidence.child("sha256", false).map_err(|_| INVALID)?;
        let mut budget = 64 * 1024 * 1024;
        let mut selected = None;
        for prefix in physical::names(&sha, &mut budget)? {
            if prefix.len() != 2
                || !prefix
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err(INVALID);
            }
            let directory = sha.child(&prefix, false).map_err(|_| INVALID)?;
            for identity in physical::names(&directory, &mut budget)? {
                if !crate::is_sha256_hex(&identity) || !identity.starts_with(&prefix) {
                    return Err(INVALID);
                }
                let leaf = directory.child(&identity, false).map_err(|_| INVALID)?;
                let manifest = physical::header(&leaf, &mut budget)?;
                if manifest.fingerprint() != identity {
                    return Err(INVALID);
                }
                if manifest.record()["backtest_run_id"] == run
                    && selected.replace(identity).is_some()
                {
                    return Err(INVALID);
                }
            }
        }
        Ok(selected)
    }
    fn terminal(&self, context: &BacktestReadContext) -> Result<Arc<TerminalSnapshot>> {
        crate::workers::backtest_profile::measure(
            context.run().run_id(),
            "evidence.terminal",
            || {
                let run = context.run();
                let binding = &run.resolution()["backtest_binding"];
                let artifact = text(binding, "executor_artifact_sha256")?;
                // Observe the actually loaded image only. Never re-describe archived
                // implementation manifests using a different currently running image.
                let current =
                    describe_research_runtime(env!("CARGO_PKG_VERSION")).map_err(|_| HISTORICAL)?;
                if current["artifact"] != artifact
                    || current["version"] != binding["executor_version"]
                {
                    return Err(HISTORICAL);
                }
                let prepared = context.prepared();
                let specification = RunSpec {
                    work_id: run.run_id().into(),
                    configuration: prepared.configuration().clone(),
                    kernel_artifact: artifact.into(),
                    driver_artifact: artifact.into(),
                    initial_ns: prepared.initial_ns().clone(),
                };
                let directory = self
                    .root
                    .child("runtime", false)
                    .and_then(|d| d.child(run.run_id(), false))
                    .map_err(|_| INVALID)?;
                let snapshot = crate::workers::backtest_profile::measure(
                    run.run_id(),
                    "terminal.read",
                    || {
                        TerminalSnapshot::read(
                            &directory.path,
                            specification,
                            prepared.inputs(),
                            crate::workers::backtest::terminal_policy,
                        )
                    },
                )
                .map_err(|_| INVALID)?;
                directory.verify().map_err(|_| INVALID)?;
                crate::workers::backtest_profile::measure(
                    context.run().run_id(),
                    "terminal.verify_cut",
                    || snapshot.verify_cut(),
                )
                .map_err(|_| INVALID)?;
                Ok(Arc::new(snapshot))
            },
        )
    }
    pub(crate) fn read_verified(
        &self,
        context: &BacktestReadContext,
    ) -> Result<Option<VerifiedEvidence>> {
        crate::workers::backtest_profile::measure(
            context.run().run_id(),
            "evidence.read_verified",
            || {
                self.require_context(context)?;
                let source = Arc::new(
                    SourceLock::publication(&self.evidence.path).map_err(|_| UNAVAILABLE)?,
                );
                let run = context.run();
                let selected = if let Some((e, _, _)) = run.completion_fingerprints() {
                    Some(e.to_owned())
                } else {
                    self.find(run.run_id())?
                };
                let Some(identity) = selected else {
                    if run.state() == RunState::Completed
                        || (run.state() == RunState::Cancelled && run.was_started())
                    {
                        return Err(INVALID);
                    }
                    source.verify().map_err(|_| INVALID)?;
                    self.require_context(context)?;
                    return Ok(None);
                };
                if run.state() == RunState::Failed
                    || (run.state() == RunState::Cancelled && !run.was_started())
                {
                    return Err(INVALID);
                }
                let directory =
                    physical::optional(&self.evidence, &["sha256", &identity[..2], &identity])?
                        .ok_or(INVALID)?;
                let bundle = Arc::new(crate::workers::backtest_profile::measure(
                    context.run().run_id(),
                    "evidence.bundle.open",
                    || Bundle::open(directory, &identity),
                )?);
                if !matches!(bundle.manifest().schema_version(), 2 | 3) {
                    return Err(HISTORICAL);
                }
                let snapshot = self.terminal(context)?;
                let retained_trace = physical::parsed(bundle.bytes("replay-trace.json")?)?;
                snapshot
                    .verify_encoded_trace(&retained_trace)
                    .map_err(|_| INVALID)?;
                let observed = crate::workers::backtest_profile::measure(
                    context.run().run_id(),
                    "result.from_terminal",
                    || ObservedBacktest::from_terminal(context.prepared(), &snapshot),
                )
                .map_err(|_| INVALID)?;
                let (expected, files) = contents(context, &observed)?;
                if bundle.manifest().record() != expected.record() {
                    return Err(INVALID);
                }
                for (name, raw) in &files {
                    if bundle.bytes(name)? != raw {
                        return Err(INVALID);
                    }
                }
                if let Some((e, r, d)) = run.completion_fingerprints()
                    && (e != identity
                        || expected.record()["result_fingerprint"] != r
                        || expected.record()["determinism_fingerprint"] != d)
                {
                    return Err(INVALID);
                }
                let status = text(observed.proof(), "status")?;
                if matches!(run.state(), RunState::Completed | RunState::Cancelled)
                    && status != run.state().as_str()
                {
                    return Err(INVALID);
                }
                let mut values = BTreeMap::new();
                for name in super::manifest::NAMES {
                    values.insert(name.into(), physical::parsed(bundle.bytes(name)?)?);
                }
                let value = VerifiedEvidence {
                    manifest: expected,
                    values,
                    cut: Arc::new(Cut {
                        context: context.clone(),
                        source,
                        bundle,
                        snapshot,
                    }),
                };
                value.verify_cut()?;
                self.require_context(context)?;
                Ok(Some(value))
            },
        )
    }
    /// Recovery consumes the same complete owning cut as read_verified. Neither
    /// filesystem existence nor a result-shaped DTO can construct this proof.
    pub(crate) fn load_completion(
        &self,
        context: &BacktestReadContext,
    ) -> Result<Option<CompletionProof>> {
        self.read_verified(context)?
            .map(|verified| verified.completion())
            .transpose()
    }
    pub(crate) fn commit(&self, joined: JoinedBacktest) -> Result<CompletionProof> {
        crate::workers::backtest_profile::measure(joined.run().run_id(), "evidence.commit", || {
            joined.verify_cut()?;
            let context = joined.read_context();
            self.require_context(context)?;
            // Existing corrupt history is never an invitation to overwrite it.
            if let Some(existing) = self.read_verified(context)? {
                compare_observation(&existing, joined.observation())?;
                joined.verify_cut()?;
                return existing.completion();
            }
            // Serialize Run-to-bundle membership with the existing source barrier.
            // SHA NOREPLACE alone cannot prevent two different manifests for one Run.
            let source = SourceLock::acquire(&self.evidence.path).map_err(|_| UNAVAILABLE)?;
            if self.find(joined.run().run_id())?.is_some() {
                drop(source);
                let existing = self.read_verified(context)?.ok_or(INVALID)?;
                compare_observation(&existing, joined.observation())?;
                joined.verify_cut()?;
                return existing.completion();
            }
            let snapshot = self.terminal(context)?;
            let actual = crate::workers::backtest_profile::measure(
                context.run().run_id(),
                "result.from_terminal",
                || ObservedBacktest::from_terminal(context.prepared(), &snapshot),
            )
            .map_err(|_| INVALID)?;
            if actual.record() != joined.observation().record()
                || actual.result() != joined.observation().result()
                || actual.proof() != joined.observation().proof()
                || actual.trace() != joined.observation().trace()
            {
                return Err(INVALID);
            }
            let (manifest, files) = contents(context, &actual)?;
            source.verify().map_err(|_| INVALID)?;
            joined.verify_cut()?;
            crate::workers::backtest_profile::measure(
                context.run().run_id(),
                "terminal.verify_cut",
                || snapshot.verify_cut(),
            )
            .map_err(|_| INVALID)?;
            crate::workers::backtest_profile::measure(
                context.run().run_id(),
                "evidence.put_bundle",
                || {
                    immutable_json::put_bundle_at(
                        self.evidence.fd.as_fd(),
                        &[
                            "sha256",
                            &manifest.fingerprint()[..2],
                            manifest.fingerprint(),
                        ],
                        &files,
                        BUDGET,
                    )
                },
            )
            .map_err(|_| INVALID)?;
            source.verify().map_err(|_| INVALID)?;
            joined.verify_cut()?;
            crate::workers::backtest_profile::measure(
                context.run().run_id(),
                "terminal.verify_cut",
                || snapshot.verify_cut(),
            )
            .map_err(|_| INVALID)?;
            if self.find(joined.run().run_id())?.as_deref() != Some(manifest.fingerprint()) {
                return Err(INVALID);
            }
            // Release the membership barrier before obtaining the retained read cut.
            // Another publisher must now observe this original Run, never append a second.
            drop(source);
            // No fresh identity on original UNKNOWN/crash recovery. This read also
            // rejects any second terminal bundle for an unpinned original Run.
            let verified = self.read_verified(context)?.ok_or(INVALID)?;
            compare_observation(&verified, &actual)?;
            let proof = verified.completion()?;
            joined.verify_cut()?;
            proof.verify_cut()?;
            Ok(proof)
        })
    }
}
fn compare_observation(value: &VerifiedEvidence, actual: &ObservedBacktest) -> Result<()> {
    if value.observation() != actual.record()
        || value.result() != actual.result()
        || value.trace() != actual.trace()
        || value.values["replay-proof.json"] != *actual.proof()
    {
        return Err(INVALID);
    }
    value.verify_cut()
}
fn contents(
    context: &BacktestReadContext,
    observed: &ObservedBacktest,
) -> Result<(Manifest, BTreeMap<String, Vec<u8>>)> {
    crate::workers::backtest_profile::measure(context.run().run_id(), "evidence.contents", || {
        context.verify_cut()?;
        let run = context.run();
        let proof = observed.proof();
        let result = observed.result();
        let status = text(proof, "status")?;
        if observed.trace()["binding"]["participants"]["program"]["revision"]["product"]["source"]
            != context.source_revision().to_record()
        {
            return Err(INVALID);
        }
        if !matches!(status, "COMPLETED" | "CANCELLED")
            || proof["drained"] != true
            || (status == "COMPLETED" && proof["market_exhausted"] != true)
            || observed.preparation() != &run.resolution()["preparation"]
        {
            return Err(INVALID);
        }
        let streamed = match observed.trace()["schema_version"].as_u64() {
            Some(1) => false,
            Some(2) if observed.trace()["kind"] == "RUNTIME_ENCODED_REPLAY_TRACE" => true,
            _ => return Err(INVALID),
        };
        if !proof["source"].as_str().is_some_and(crate::is_sha256_hex) {
            return Err(INVALID);
        }
        let operation = context.original_operation();
        let runtime = json!({"schema_version":if streamed{2}else{1},"contract":if streamed{"ONLYALPHA_NATIVE_BACKTEST_PRODUCER_V2"}else{"ONLYALPHA_NATIVE_BACKTEST_PRODUCER_V1"},
        "run":run.record(),"preparation_command_id":operation.command.value(),"accepted_preparation":operation.accepted,
        "ready":operation.outputs["ready"],"runtime_manifest":context.runtime_manifest(),"executor_manifest":context.executor_manifest(),"installed_proof":context.installed_proof(),
        "replay_binding":observed.trace()["binding"]});
        let mut files = BTreeMap::new();
        for (name, value) in [
            ("observation.json", observed.record()),
            ("replay-proof.json", proof),
            ("replay-trace.json", observed.trace()),
            ("result.json", result),
            ("runtime.json", &runtime),
        ] {
            files.insert(name.into(), physical::canonical(value)?);
        }
        let artifacts=files.iter().map(|(name,bytes)|json!({"name":name,"sha256":physical::sha(bytes),"size":bytes.len(),"media_type":"application/json"})).collect::<Vec<_>>();
        let resolution = run.resolution();
        let mut record = json!({"schema_version":if streamed{3}else{2},"kind":"NATIVE_BTC_SPOT_NEXT_OPEN_EVIDENCE","backtest_run_id":run.run_id(),
        "specification_fingerprint":run.specification_fingerprint(),"admission_resolution_fingerprint":run.admission_resolution_fingerprint(),
        "strategy_fingerprint":resolution["strategy_fingerprint"],"dataset_snapshot_fingerprint":resolution["dataset_snapshot_fingerprint"],
        "dataset_binding_fingerprint":resolution["dataset_binding_fingerprint"],"runtime_generation_fingerprint":run.runtime_generation_fingerprint(),
        "preparation_fingerprint":resolution["preparation_fingerprint"],"result_fingerprint":result["result_fingerprint"],
        "determinism_fingerprint":result["determinism_fingerprint"],"artifacts":artifacts});
        if streamed {
            record["trace_format"] = json!("RUNTIME_ENCODED_REPLAY_TRACE@2");
            record["logical_trace_fingerprint"] = proof["source"].clone();
        }
        record["evidence_fingerprint"] = json!(hash(&record)?);
        let manifest = Manifest::from_record(&record)?;
        files.insert("manifest.json".into(), physical::canonical(&record)?);
        let total = files.values().try_fold(0_usize, |total, raw| {
            total
                .checked_add(raw.len())
                .filter(|n| *n <= BUDGET)
                .ok_or(UNAVAILABLE)
        })?;
        if total == 0 {
            return Err(INVALID);
        }
        context.verify_cut()?;
        Ok((manifest, files))
    })
}
