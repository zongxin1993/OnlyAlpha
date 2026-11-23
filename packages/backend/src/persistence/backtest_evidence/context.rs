use super::physical::DatasetCut;
use crate::{
    application::{
        backtest_preparation::{BacktestOrigin, build_prepared_next_open, retained_backtest_rules},
        backtest_run::VerifiedRun,
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
    path::Path,
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
    datasets: Datasets,
    dataset: MaterializedDataset,
    dataset_cut: DatasetCut,
    prepared: PreparedNextOpen,
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
    pub(crate) fn materialization(&self) -> &Value {
        self.owners.dataset.lineage()
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
    /// A current manual occurrence takes precedence over historical promotion
    /// evidence. An invalid current proof never falls back to another occurrence.
    pub(crate) fn validated_decision(&self) -> Result<&Value> {
        self.verify_cut()?;
        match &self.owners.validation {
            Some(validation) => super::super::qualification_decision::manual_decision(
                &validation.record()["prepared_inputs"],
            ),
            None => self.owners.history.validated_decision(),
        }
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
    fact_client: &mut Client,
    namespace: &SemanticStoreId,
    research_root: &Path,
    runtime_root: &Path,
    id: &str,
    owner: &str,
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
    let facts_tx=fact_client.build_transaction().read_only(true).start().await.map_err(|_|UNAVAILABLE)?;
    let facts=crate::persistence::build_fact_read::BuildFactRead::reader(&tx,&facts_tx,namespace).await.map_err(|_|UNAVAILABLE)?;
    if !crate::application::command::uuid4(id) {
        return Err("BACKTEST_RUN_INPUT_INVALID");
    }
    let run = backtest_run::load_in_transaction(&tx, namespace, id).await?;
    if run.owner() != owner {
        return Err("BACKTEST_ACCESS_DENIED");
    }
    let operation = research_preparation::original_backtest_preparation(&tx, &run).await?;
    let input = operation.request.backtest()?;
    let ready = &operation.outputs["ready"];
    let admission = &ready["admission"];
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
            &facts,
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
        &facts,
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
                        .read_verified_in_transaction(&facts,operation.command.value())
                        .await?,
                )
            };
            proof.require_backtest_inputs(&operation, history.source_revision(), &dataset)?;
            proof.verify_in_transaction(&facts,namespace).await?;
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
        operation.request.future_command(),
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
    let calculations = match &validation {
        Some(proof) => &proof.record()["prepared_inputs"],
        None => history.validated_calculations()?,
    };
    if installed["native_descriptor"]["image"] != ready["native_image"]
        || installed["native_descriptor"]["image"]["artifact"] != binding["executor_artifact_sha256"]
        || installed["native_descriptor"]["image"]["version"] != binding["executor_version"]
        || installed["native_descriptor"]["implementations"] != ready["native_implementations"]
        || calculations["algorithm_resolution"] != ready["algorithm_resolution"]
        || calculations["algorithm_resolution_request"] != ready["algorithm_resolution_request"]
        || crate::application::calculation_build::reference(&calculations["build_certification"])
            != ready["calculation_build"]
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
    history.verify_cut()?;
    implementation_records(history.source_revision(), ready, held.manifest(), &installed, Some(calculations))?;
    let value = Arc::new(BacktestReadContext {
        run,
        operation,
        owners: Arc::new(Owners {
            history,
            validation,
            runtime: Arc::new(held),
            datasets,
            dataset,
            dataset_cut,
            prepared,
        }),
    });
    value.verify_cut()?;
    value.owners.history.verify_in_transaction(&facts).await?;
    if let Some(validation) = &value.owners.validation {
        validation.verify_in_transaction(&facts,namespace).await?;
    }
    deployment::verify_binding_in_transaction(&tx, namespace)
        .await
        .map_err(|e| e.code())?;
    facts_tx.commit().await.map_err(|_|UNAVAILABLE)?;
    tx.commit().await.map_err(|_| UNAVAILABLE)?;
    Ok(value)
    }.instrument(trace.span().clone()).await;
    trace.finish(if context.is_ok() { "ok" } else { "failed" }, 1, 0);
    context
}
/// The admitted owner has already authenticated the exact PG graph/certificates.
/// A Source DTO or caller-provided implementation list cannot enter this wrapper.
pub(crate) fn admitted_implementations(
    admission: &crate::persistence::strategy_promotion::VerifiedBacktestAdmission,
    ready: &Value,
    runtime: &Value,
    installed: &Value,
) -> Result<()> {
    admission.verify_cut()?;
    implementation_records(
        admission.source_revision(),
        ready,
        runtime,
        installed,
        Some(admission.validated_calculations()?),
    )
}
fn implementation_records(
    source: &onlyalpha_strategy::SourceRevision,
    ready: &Value,
    runtime: &Value,
    installed: &Value,
    certified: Option<&Value>,
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
    let certified_factors = match certified {
        Some(original) => crate::application::factor_build::retained_factor_manifest_values(
            original,
            text(&installed["native_descriptor"]["image"], "artifact")?,
            text(installed, "algorithm_artifact")?,
        )
        .map_err(|_| INVALID)?,
        None => BTreeMap::new(),
    };
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
            let projection =
                crate::application::research_admission::implementation_projection(body)?;
            let factor = body["calculation_type_reference"]["kind"] == "FACTOR"
                && certified_factors.get(text(binding, field)?) == Some(body);
            if body["backend_kind"] != backend || (!factor && !allowed.contains(&projection)) {
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
