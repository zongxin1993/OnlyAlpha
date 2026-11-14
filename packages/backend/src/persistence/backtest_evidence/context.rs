//! Actual historical read closure. It cannot grant execution or current eligibility.
use super::physical::DatasetCut;
use crate::{
    application::{
        backtest_preparation::{BacktestOrigin, build_prepared_next_open, retained_backtest_rules},
        backtest_run::VerifiedRun,
        command::CommandId,
        research_dataset::MaterializedDataset,
    },
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{
        backtest_run,
        postgres::bounds,
        qualification_decision::Store as Decisions,
        research_dataset::Store as Datasets,
        research_preparation::{self, Operation},
        research_runtime::RuntimeEvidenceHold,
        strategy_promotion::{self, VerifiedBacktestHistory},
        strategy_validation::{Store as Validations, VerifiedValidation},
    },
    security::protected_files,
    workers::backtest::PreparedNextOpen,
};
use onlyalpha_observability::{Correlation, Operation as TraceOperation};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    os::fd::AsFd,
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio_postgres::Client;
use tracing::Instrument;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "BACKTEST_EVIDENCE_CORRUPT";
const UNAVAILABLE: &str = "BACKTEST_EVIDENCE_UNAVAILABLE";
const WORK: usize = 64 * 1024 * 1024;
fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().ok_or(INVALID)
}
fn worker(code: crate::application::research_admission::PreparationError) -> &'static str {
    code.code()
}

#[derive(Clone)]
pub(crate) struct BacktestReadContext {
    run: VerifiedRun,
    operation: Operation,
    owners: Arc<Owners>,
}
struct Owners {
    history: VerifiedBacktestHistory,
    validation: Option<Arc<VerifiedValidation>>,
    runtime: Arc<RuntimeEvidenceHold>,
    installed: Value,
    executor: Value,
    datasets: Datasets,
    dataset: MaterializedDataset,
    dataset_cut: DatasetCut,
    prepared: PreparedNextOpen,
    research_root: PathBuf,
    runtime_root: PathBuf,
}
impl BacktestReadContext {
    pub(crate) fn run(&self) -> &VerifiedRun {
        &self.run
    }
    pub(crate) fn original_operation(&self) -> &Operation {
        &self.operation
    }
    pub(crate) fn prepared(&self) -> &PreparedNextOpen {
        &self.owners.prepared
    }
    pub(crate) fn source_revision(&self) -> &onlyalpha_strategy::SourceRevision {
        self.owners.history.source_revision()
    }
    /// The current manual occurrence owns its calculation evidence even when
    /// the canonical grant originated in an earlier equivalent preparation.
    pub(crate) fn validated_calculations(&self) -> Result<&Value> {
        self.verify_cut()?;
        match &self.owners.validation {
            Some(validation) => Ok(&validation.record()["prepared_inputs"]),
            None => self.owners.history.validated_calculations(),
        }
    }
    pub(super) fn installed_proof(&self) -> &Value {
        &self.owners.installed
    }
    pub(super) fn runtime_manifest(&self) -> &Value {
        self.owners.runtime.manifest()
    }
    pub(super) fn executor_manifest(&self) -> &Value {
        &self.owners.executor
    }
    pub(crate) fn roots_match(&self, research: &Path, runtime: &Path) -> Result<()> {
        if research != self.owners.research_root || runtime != self.owners.runtime_root {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        Ok(())
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        crate::workers::backtest_profile::measure(self.run().run_id(), "context.verify_cut", || {
            crate::workers::backtest_profile::measure(
                self.run().run_id(),
                "context.history.verify",
                || self.owners.history.verify_cut(),
            )?;
            crate::workers::backtest_profile::measure(
                self.run().run_id(),
                "context.runtime.verify",
                || self.owners.runtime.verify(),
            )?;
            crate::workers::backtest_profile::measure(
                self.run().run_id(),
                "context.dataset.verify",
                || self.owners.dataset_cut.verify(),
            )?;
            if let Some(validation) = &self.owners.validation {
                crate::workers::backtest_profile::measure(
                    self.run().run_id(),
                    "context.validation.verify",
                    || {
                        validation.require_backtest_inputs(
                            &self.operation,
                            self.source_revision(),
                            &self.owners.dataset,
                        )
                    },
                )?;
            }
            let again = crate::workers::backtest_profile::measure(
                self.run().run_id(),
                "context.dataset.load",
                || {
                    MaterializedDataset::load(
                        &self.owners.datasets,
                        text(self.owners.dataset.lineage(), "materialization_id")?,
                    )
                },
            )?;
            if again.lineage() != self.owners.dataset.lineage()
                || again.verified().manifest() != self.owners.dataset.verified().manifest()
                || self.owners.prepared.record() != self.run.resolution()["preparation"]
                || self.owners.runtime.binding() != &self.run.resolution()["runtime_work_binding"]
                || self.owners.runtime.backtest_binding_data()?
                    != self.run.resolution()["backtest_binding"]
            {
                return Err(INVALID);
            }
            crate::workers::backtest_profile::measure(
                self.run().run_id(),
                "context.runtime.verify",
                || self.owners.runtime.verify(),
            )?;
            Ok(())
        })
    }
}
/// Original caller-owned readonly connection. No second socket, Command lock,
/// SDK execution, policy selection, generation selection or new work binding.
pub(crate) async fn read_context(
    client: &mut Client,
    namespace: &SemanticStoreId,
    research_root: &Path,
    runtime_root: &Path,
    id: &str,
    owner: Option<&str>,
) -> Result<Arc<BacktestReadContext>> {
    let trace = TraceOperation::start(
        "backend",
        "evidence.read_context",
        Correlation {
            run_id: Some(id.into()),
            ..Default::default()
        },
    );
    let context:Result<Arc<BacktestReadContext>> = async {
    let tx = client
        .build_transaction()
        .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| UNAVAILABLE)?;
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(|_| UNAVAILABLE)?;
    bounds(&tx).await.map_err(|e| e.code())?;
    if !crate::application::command::uuid4(id) {
        return Err("BACKTEST_RUN_INPUT_INVALID");
    }
    let versions=tx.query_opt("SELECT specification_schema_version,admission_resolution_schema_version FROM public.backtest_run WHERE run_id=$1::text::uuid",&[&id]).await.map_err(|_|UNAVAILABLE)?.ok_or("BACKTEST_RUN_NOT_FOUND")?;
    let specification_version: i16 = versions.try_get(0).map_err(|_| INVALID)?;
    let resolution_version: i16 = versions.try_get(1).map_err(|_| INVALID)?;
    if matches!(specification_version, 1 | 2) && resolution_version == 1 {
        return Err("BACKTEST_HISTORICAL_READER_UNAVAILABLE");
    }
    let run = backtest_run::load_in_transaction(&tx, namespace, id).await?;
    if owner.is_some_and(|owner| run.owner() != owner) {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    let future = text(&run.resolution()["runtime_work_binding"], "reason")?;
    let rows=tx.query("SELECT command_id::text FROM public.research_preparation WHERE preparation_kind='BACKTEST_PREPARATION' AND accepted_payload::jsonb->'input'->>'backtest_command_id'=$1 ORDER BY command_id LIMIT 2",&[&future]).await.map_err(|_|UNAVAILABLE)?;
    if rows.len() != 1 {
        return Err(INVALID);
    }
    let preparation = CommandId::new(rows[0].try_get::<_, &str>(0).map_err(|_| INVALID)?)
        .map_err(|e| e.code())?;
    let operation = research_preparation::load(&tx, &preparation, run.owner()).await?;
    let input = operation.request.backtest()?;
    let ready = &operation.outputs["ready"];
    let admission = &ready["admission"];
    if operation.request.future_command() != future
        || operation.request.reserved_run_id() != run.run_id()
        || ready["specification"] != *run.specification().record()
        || ready["preparation"] != run.resolution()["preparation"]
        || ready["preparation_fingerprint"]
            != run.specification().record()["preparation_fingerprint"]
        || ready["backtest_binding"] != run.resolution()["backtest_binding"]
        || admission["strategy_fingerprint"] != run.specification().record()["strategy_fingerprint"]
        || admission["freeze_relation_fingerprint"]
            != run.resolution()["freeze_relation_fingerprint"]
        || admission["qualification_decision_fingerprint"]
            != run.resolution()["qualification_decision_fingerprint"]
        || admission["promotion_fingerprint"] != run.resolution()["promotion_fingerprint"]
    {
        return Err(INVALID);
    }
    let selected = json!({"integration_id":input.source.integration_id,"revision_fingerprint":input.source.integration_revision_fingerprint,
        "expected_type_id":input.source.expected_type_id,"source_id":input.source.source_id,"environment":input.source.environment});
    if run.resolution()["source_selection"] != selected {
        return Err(INVALID);
    }
    let descriptor = protected_files::open_directory(research_root).map_err(|_| UNAVAILABLE)?;
    if deployment::load_semantic_store_id_at(&descriptor).map_err(|e| e.code())? != *namespace {
        return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
    }
    let frozen = Arc::new(
        crate::application::frozen_strategy::FrozenStore::open(descriptor.as_fd())
            .map_err(|e| e.code())?,
    );
    let decisions = Arc::new(Decisions::open(research_root)?);
    let decision = decisions
        .read_verified_in_transaction(
            &tx,
            namespace,
            runtime_root,
            text(admission, "qualification_decision_fingerprint")?,
        )
        .await?;
    let original_validation = decision
        .manual_evidence()
        .map(|evidence| evidence.validation())
        .filter(|proof| proof.preparation_command_id() == operation.command.value())
        .cloned();
    let history = strategy_promotion::read_verified_history_in_transaction(
        &tx,
        namespace,
        frozen,
        decision,
        strategy_promotion::BacktestAdmissionSelection {
            strategy: text(admission, "strategy_fingerprint")?,
            relation: text(admission, "freeze_relation_fingerprint")?,
            promotion: text(admission, "promotion_fingerprint")?,
            max_work: WORK,
        },
    )
    .await?;
    let datasets = Datasets::open(&research_root.join("datasets"), 8192, 8 * 1024 * 1024)?;
    let dataset = MaterializedDataset::load(&datasets, text(ready, "dataset_materialization_id")?)?;
    if dataset.lineage() != &run.resolution()["dataset_materialization"] {
        return Err(INVALID);
    }
    let validation = match &input.origin {
        BacktestOrigin::ManualStrategy { .. } => {
            let proof = if let Some(original) = original_validation {
                original
            } else {
                let store = Validations::open(research_root)?.with_runtime_root(runtime_root)?;
                Arc::new(
                    store
                        .read_verified_in_transaction(&tx, operation.command.value())
                        .await?,
                )
            };
            proof.require_backtest_inputs(&operation, history.source_revision(), &dataset)?;
            proof.verify_in_transaction(&tx, namespace).await?;
            Some(proof)
        }
        BacktestOrigin::FrozenStrategy { .. } => {
            if !ready["validation_fingerprint"].is_null() {
                return Err(INVALID);
            }
            None
        }
    };
    let dataset_cut = DatasetCut::capture(
        &research_root.join("datasets"),
        dataset.verified().manifest(),
        dataset.lineage(),
    )?;
    let rules =
        retained_backtest_rules(&ready["rules_response"], &input.source, &operation.command)?;
    let prepared = build_prepared_next_open(
        history.source_revision(),
        &dataset,
        rules,
        run.runtime_generation_fingerprint(),
    )
    .map_err(worker)?;
    if prepared.record() != run.resolution()["preparation"]
        || prepared.inputs().record() != ready["input_sources"]
    {
        return Err(INVALID);
    }
    let mut held = RuntimeEvidenceHold::open(
        runtime_root,
        run.run_id(),
        future,
        run.runtime_generation_fingerprint(),
    )?;
    let metadata =
        held.backtest_metadata(text(&ready["algorithm_resolution"], "algorithm_artifact")?)?;
    if held.binding() != &run.resolution()["runtime_work_binding"]
        || metadata.binding != run.resolution()["backtest_binding"]
    {
        return Err(INVALID);
    }
    let installed = metadata.installed;
    let binding = &run.resolution()["backtest_binding"];
    if installed["native_descriptor"]["image"]["artifact"] != binding["executor_artifact_sha256"]
        || installed["native_descriptor"]["image"]["version"] != binding["executor_version"]
        || installed["native_descriptor"]["execution_capabilities"]
            .as_array()
            .is_none_or(|caps| {
                caps.iter()
                    .filter(|c| {
                        **c == json!({"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"})
                    })
                    .count()
                    != 1
            })
    {
        return Err(INVALID);
    }
    implementations(
        history.source_revision(),
        ready,
        held.manifest(),
        &installed,
    )?;
    let value = Arc::new(BacktestReadContext {
        run,
        operation,
        owners: Arc::new(Owners {
            history,
            validation,
            runtime: Arc::new(held),
            installed,
            executor: metadata.executor,
            datasets,
            dataset,
            dataset_cut,
            prepared,
            research_root: research_root.into(),
            runtime_root: runtime_root.into(),
        }),
    });
    value.verify_cut()?;
    value.owners.history.verify_in_transaction(&tx).await?;
    if let Some(validation) = &value.owners.validation {
        validation.verify_in_transaction(&tx, namespace).await?;
    }
    deployment::verify_binding_in_transaction(&tx, namespace)
        .await
        .map_err(|e| e.code())?;
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(value)
    }.instrument(trace.span().clone()).await;
    trace.finish(if context.is_ok() { "ok" } else { "failed" }, 1, 0);
    context
}
pub(crate) fn implementations(
    source: &onlyalpha_strategy::SourceRevision,
    ready: &Value,
    runtime: &Value,
    installed: &Value,
) -> Result<()> {
    let mut bodies = BTreeMap::new();
    for node in ready["algorithm_resolution"]["nodes"]
        .as_array()
        .ok_or(INVALID)?
    {
        for body in node["implementations"].as_array().ok_or(INVALID)? {
            insert(&mut bodies, body)?;
        }
    }
    for body in installed["native_descriptor"]["implementations"]
        .as_array()
        .ok_or(INVALID)?
    {
        insert(&mut bodies, body)?;
    }
    let allowed = runtime["implementations"].as_array().ok_or(INVALID)?;
    for binding in source.to_record()["implementation_bindings"]
        .as_array()
        .ok_or(INVALID)?
    {
        for (field, backend) in [
            ("research_implementation_fingerprint", "RESEARCH"),
            ("trading_implementation_fingerprint", "TRADING"),
        ] {
            let body = bodies.get(text(binding, field)?).ok_or(INVALID)?;
            if body["backend_kind"] != backend
                || !allowed.contains(
                    &crate::application::research_admission::implementation_projection(body)?,
                )
            {
                return Err(INVALID);
            }
        }
    }
    Ok(())
}
fn insert(bodies: &mut BTreeMap<String, Value>, body: &Value) -> Result<()> {
    crate::application::research_admission::implementation_projection(body)?;
    let key = text(body, "implementation_fingerprint")?.to_owned();
    if let Some(old) = bodies.insert(key, body.clone())
        && old != *body
    {
        return Err(INVALID);
    }
    Ok(())
}
