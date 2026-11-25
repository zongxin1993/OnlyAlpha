use super::*;
use crate::{
    application::{
        backtest_preparation::{prepare_retained_next_open, retained_backtest_rules},
        backtest_run::VerifiedRun,
        calculation_build,
        factor_build::retained_factor_manifest_values,
        factor_content::hash,
        finite_job::{backtest_execution_values, calculation_factor_inputs, plan_members},
        private_strategy::exact,
        research_dataset::NativeMaterializationPlan,
    },
    persistence::{backtest_run, market_data, research_preparation},
    workers::{backtest::{PreparedNextOpen, next_open_policy}, trading_program},
};
use onlyalpha_backtest::{ExecutionBinding, Inputs};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::{
    native_operators::OperatorCalculation,
    native_predicates::PredicateCalculation,
};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_runtime::{RunBinding, RunConfiguration};
use onlyalpha_strategy::{Program, Scope, SourceRevision};
use serde_json::json;
use std::collections::BTreeSet;

const INTEGRITY: PublicationError = PublicationError::Integrity;
const MISMATCH: PublicationError = PublicationError::Mismatch;
const WORK: usize = 8 * 1024 * 1024;

fn invalid<T>(_: T) -> PublicationError { INTEGRITY }
fn owner_error(code: &str) -> PublicationError {
    if code.ends_with("_UNAVAILABLE") || code.ends_with("_BUSY") {
        PublicationError::Unavailable
    } else if code.ends_with("_NOT_FOUND") || code.ends_with("_MISSING") {
        PublicationError::MissingEvidence
    } else if code.ends_with("_DENIED") {
        PublicationError::Denied
    } else if code.ends_with("_BUDGET_EXCEEDED") {
        PublicationError::BudgetExceeded
    } else if code.ends_with("_MISMATCH") {
        MISMATCH
    } else {
        INTEGRITY
    }
}
fn array(value: &Value) -> Result<&[Value]> {
    value.as_array().map(Vec::as_slice).ok_or(INTEGRITY)
}
fn text(value: &Value) -> Result<&str> {
    value.as_str().filter(|value| !value.is_empty()).ok_or(INTEGRITY)
}
fn hash_value(value: &Value) -> Result<String> { hash(value).map_err(invalid) }

#[derive(Default)]
struct Bodies<'a> {
    causal: Option<&'a Value>,
    economics: Option<&'a Value>,
    facts: Vec<&'a Value>,
    curve: Vec<&'a Value>,
    curve_axis: Vec<&'a Value>,
    references: Vec<Value>,
}
impl<'a> Bodies<'a> {
    fn read(members: &[PreparedMember], values: &'a [Value]) -> Result<Self> {
        let mut bodies = Self::default();
        for (member, value) in members.iter().zip(values) {
            let kind = member.descriptor.kind();
            if kind == MemberKind::CausalEvidence {
                if bodies.causal.replace(root(value, kind)?).is_some() {
                    return Err(INTEGRITY);
                }
                continue;
            }
            bodies.references.push(json!({"key":member.descriptor.key(),"content":member.content_fingerprint}));
            match kind {
                MemberKind::CloseCurve => {
                    bodies.curve.extend(array(&value["rows"])?);
                    bodies.curve_axis.extend(array(&value["axis"])?);
                }
                MemberKind::ExecutionFacts => bodies.facts.extend(array(&value["rows"])?),
                MemberKind::EconomicResult => {
                    if bodies.economics.replace(root(value, kind)?).is_some() {
                        return Err(INTEGRITY);
                    }
                }
                _ => return Err(INTEGRITY),
            }
        }
        Ok(bodies)
    }
}
fn root(value: &Value, kind: MemberKind) -> Result<&Value> {
    exact(value, &["schema_version", "kind", "body"]).map_err(invalid)?;
    if value["schema_version"] != 1 || value["kind"] != json!(kind) {
        return Err(INTEGRITY);
    }
    Ok(&value["body"])
}

pub(super) enum Origin<'a, 'tx> {
    Control(&'a crate::persistence::authority_session::ControlRoleOwner),
    Reader(&'a Transaction<'tx>),
}

type Original = (VerifiedRun, research_preparation::Operation, market_data::SealedRevision);

async fn original_metadata(
    tx: &Transaction<'_>,
    binding: &FrozenJobBinding,
    execution: &Value,
) -> Result<Original> {
    let namespace = SemanticStoreId::new(binding.namespace()).map_err(deployment_error)?;
    if !tx.query_one("SELECT current_user=session_user", &[]).await.map_err(db)?.get::<_, bool>(0) {
        return Err(PublicationError::Denied);
    }
    let run = backtest_run::load_in_transaction(tx, &namespace, binding.run_id()).await.map_err(owner_error)?;
    if run.owner() != binding.owner() {
        return Err(MISMATCH);
    }
    let operation = research_preparation::original_backtest_preparation(tx, &run).await.map_err(owner_error)?;
    let ready = &operation.outputs["ready"];
    let evidence = &execution["input_evidence"];
    exact(evidence, &["evidence", "segments"]).map_err(invalid)?;
    let revision = market_data::verify_frozen_input_metadata(tx, &evidence["evidence"], &evidence["segments"], 32 * 1024 * 1024)
        .await.map_err(|error| match error {
            market_data::Error::NotFound | market_data::Error::MissingEvidence => PublicationError::MissingEvidence,
            market_data::Error::Unavailable | market_data::Error::Busy => PublicationError::Unavailable,
            market_data::Error::Unknown => PublicationError::OutcomeUnknown,
            market_data::Error::BudgetExceeded => PublicationError::BudgetExceeded,
            market_data::Error::Conflict => MISMATCH,
            _ => INTEGRITY,
        })?;
    let proof = &execution["calculation_build"];
    if proof.is_null() {
        return Err(PublicationError::MissingEvidence);
    }
    let reference = calculation_build::reference(proof);
    if ["build_key", "proof_fingerprint"].iter().any(|key| {
        !reference[*key].as_str().is_some_and(crate::is_sha256_hex)
    }) {
        return Err(INTEGRITY);
    }
    if reference != ready["calculation_build"] {
        return Err(MISMATCH);
    }
    Ok((run, operation, revision))
}

async fn original(
    tx: &Transaction<'_>,
    origin: Origin<'_, '_>,
    binding: &FrozenJobBinding,
    execution: &Value,
) -> Result<Original> {
    let proof = &execution["calculation_build"];
    match origin {
        Origin::Reader(metadata) => {
            role(tx, &[JobRole::Reader.name()]).await?;
            let original = original_metadata(metadata, binding, execution).await?;
            calculation_build::verify_fact(tx, proof).await.map_err(owner_error)?;
            Ok(original)
        }
        Origin::Control(owner) => {
            let scope = owner.enter();
            role(tx, &[JobRole::Publisher.name()]).await?;
            // Restoration must succeed even when a fact query aborts its subtransaction.
            tx.batch_execute("SAVEPOINT backtest_publication_facts").await.map_err(db)?;
            tx.batch_execute("SET LOCAL ROLE NONE").await.map_err(db)?;
            // PostgreSQL exposes backend_start to the login that owns the session.
            owner.verify_transaction(tx).await.map_err(guarded::authority_error)?;
            let result = async {
                let original = original_metadata(tx, binding, execution).await?;
                tx.batch_execute(JobRole::Reader.select_local()).await.map_err(db)?;
                role(tx, &[JobRole::Reader.name()]).await?;
                calculation_build::verify_fact(tx, proof).await.map_err(owner_error)?;
                Ok(original)
            }.await;
            tx.batch_execute("ROLLBACK TO SAVEPOINT backtest_publication_facts; RELEASE SAVEPOINT backtest_publication_facts")
                .await.map_err(|_| PublicationError::OutcomeUnknown)?;
            role(tx, &[JobRole::Publisher.name()]).await.map_err(|_| PublicationError::OutcomeUnknown)?;
            crate::persistence::authority_session::AuthoritySession::verify_transaction(tx)
                .await.map_err(guarded::authority_error)?;
            scope.restored();
            result
        }
    }
}

fn prepared_input(
    binding: &FrozenJobBinding,
    run: &VerifiedRun,
    operation: &research_preparation::Operation,
    revision: &market_data::SealedRevision,
    execution: &Value,
    source: SourceRevision,
) -> Result<(PreparedNextOpen, Vec<Value>)> {
    let ready = &operation.outputs["ready"];
    let market = binding.market().record();
    let frozen = &ready["source_selection"];
    let original = revision.revision();
    let scope = &original["scope"];
    let seal = revision.seal();
    let construction = onlyalpha_market_data_construction::OnlyConstructionIdentity::from_record(&scope["bar_construction"]).map_err(invalid)?;
    let construction_record = construction.to_record();
    let plan = &construction_record["plan"];
    let lineage = &run.resolution()["dataset_materialization"];
    let segments = array(&original["segment_refs"])?.iter().map(hash_value).collect::<Result<BTreeSet<_>>>()?;
    let seal_id = text(&seal["seal_id"])?;
    if frozen["revision"] != original || frozen["seal"] != seal
        || frozen["scope"] != *scope
        || market["source_revision"] != original["fingerprint"]
        || market["instruments"] != json!([scope["instrument_id"]])
        || market["bar_semantic"] != hash_value(&plan["target_semantic"])?
        || market["versions"] != json!([hash_value(&scope["data_version"])?])
        || market["segments"] != json!(segments)
        || market["seals"] != json!([seal_id.strip_prefix("seal:").ok_or(INTEGRITY)?])
        || ready["dataset_materialization_id"] != lineage["materialization_id"]
        || execution["input_sources"] != ready["input_sources"]
    {
        return Err(MISMATCH);
    }
    let retained = &ready["preparation"];
    let utc = |value: &Value| -> Result<String> {
        let ns = value.as_i64().ok_or(INTEGRITY)?;
        Ok(OnlyTimestamp::from_unix_nanos(ns.into()).to_datetime_exact().map_err(invalid)?.to_string())
    };
    let inputs = Inputs::from_record(&execution["input_sources"]).map_err(invalid)?;
    let bars = inputs.records().iter().map(|row| row.bar().to_record()).collect::<Vec<_>>();
    let definition = json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":market["instruments"],"bar_semantic":plan["target_semantic"],"time_range":{"start":utc(&market["start_ns"])? ,"end":utc(&market["end_ns"])?},"quality_policy":"STRICT","closed_only":true});
    let materialization = NativeMaterializationPlan::new(
        &definition, revision.id(), market_data::Scope::from_record(scope).map_err(invalid)?, 8192,
    ).map_err(owner_error)?;
    let dataset = materialization.retained_dataset(revision, &bars, lineage).map_err(owner_error)?;
    let axis: Vec<_> = dataset.rows().iter().map(|row| json!([row["instrument_id"],row["bar_start_ns"],row["bar_end_ns"],row["ts_event_ns"],row["revision"]])).collect();
    if market["dataset_snapshot"] != dataset.snapshot_fingerprint()
        || market["content"] != dataset.content_fingerprint()
        || market["rows"] != axis.len() || market["axis"] != hash_value(&json!(axis))?
    {
        return Err(MISMATCH);
    }
    let input = operation.request.backtest().map_err(owner_error)?;
    let rules = retained_backtest_rules(&ready["rules_response"], &input.source, &operation.command).map_err(owner_error)?;
    let prepared = prepare_retained_next_open(
        &source, &dataset, scope, &plan["resolved_recipe"], &lineage["request_fingerprint"],
        rules, run.runtime_generation_fingerprint(),
    ).map_err(|error| owner_error(error.code()))?;
    let prepared_record = prepared.record();
    let window = &prepared_record["window"];
    if prepared_record != *retained
        || prepared.inputs().record() != execution["input_sources"]
        || window["warmup_bars"] != market["warmup_rows"]
        || window["sample_bar_count"] != market["sample_rows"]
    {
        return Err(MISMATCH);
    }
    Ok((prepared, axis))
}

fn program(source: &SourceRevision, ready: &Value, image: &str, cfg: &Value, cluster: &str, market: &str) -> Result<Program> {
    let record = source.to_record();
    let graph = Graph::from_record(&record["decision_graph"], WORK).map_err(invalid)?;
    let artifact = text(&ready["algorithm_resolution"]["algorithm_artifact"])?;
    let factors = retained_factor_manifest_values(ready, image, artifact).map_err(owner_error)?;
    let implementations = array(&ready["native_implementations"])?;
    let mut capabilities = Vec::new();
    for node in graph.ordered_nodes() {
        let id = node.fingerprint();
        let definition = node.to_record();
        let binding = array(&record["implementation_bindings"])?.iter().find(|entry| entry["node_fingerprint"] == id).ok_or(INTEGRITY)?;
        let implementation = text(&binding["trading_implementation_fingerprint"])?;
        let (capability, schema) = match text(&definition["kind"])? {
            "PREDICATE" => {
                let predicate = PredicateCalculation::from_record(&definition).map_err(invalid)?;
                let manifest = predicate.implementation_manifest("TRADING", image).map_err(invalid)?;
                if manifest["implementation_fingerprint"] != implementation || !implementations.contains(&manifest) {
                    return Err(MISMATCH);
                }
                continue;
            }
            "INDICATOR" => {
                let operator = OperatorCalculation::from_record(&definition).map_err(invalid)?;
                let manifest = operator.implementation_manifest("TRADING", image).map_err(invalid)?;
                if manifest["implementation_fingerprint"] != implementation || !implementations.contains(&manifest) {
                    return Err(MISMATCH);
                }
                (operator.state_capability().to_owned(), operator.checkpoint_schema_version())
            }
            "FACTOR" => {
                if !factors.contains_key(implementation) { return Err(MISMATCH); }
                ("CHECKPOINTABLE".into(), Some(1))
            }
            _ => return Err(INTEGRITY),
        };
        capabilities.push(json!({"node_fingerprint":id,"implementation_fingerprint":implementation,"state_capability":capability,"checkpoint_schema_version":schema}));
    }
    let scope = Scope {
        engine: text(&cfg["engine"])?.parse().map_err(invalid)?,
        runtime: text(&cfg["runtime"])?.parse().map_err(invalid)?,
        cluster: cluster.parse().map_err(invalid)?,
    };
    trading_program::materialize(source, scope, text(&cfg["generation"])?, market, artifact, &json!(capabilities))
        .map(|(program, _, _)| program).map_err(owner_error)
}

pub(super) async fn verify(
    tx: &Transaction<'_>,
    origin: Origin<'_, '_>,
    binding: &FrozenJobBinding,
    members: &[PreparedMember],
    values: &[Value],
) -> Result<()> {
    let bodies = Bodies::read(members, values)?;
    let execution = &bodies.causal.ok_or(PublicationError::MissingEvidence)?["execution"];
    let originals = original(tx, origin, binding, execution).await?;
    verify_original(originals, binding, bodies)
}

impl BacktestStorage {
    pub(crate) async fn verify(self, tx: &crate::persistence::build_fact_read::BuildFactRead<'_, '_>) -> Result<PublishedJobResult> {
        let Self(result, values) = self;
        let bodies = Bodies::read(&result.members, &values)?;
        let execution = &bodies.causal.ok_or(PublicationError::MissingEvidence)?["execution"];
        let originals = original_metadata(tx, &result.binding, execution).await?;
        tx.verify_calculation(&execution["calculation_build"]).await.map_err(owner_error)?;
        verify_original(originals, &result.binding, bodies)?;
        Ok(result)
    }
}

fn verify_original(originals: Original, binding: &FrozenJobBinding, bodies: Bodies<'_>) -> Result<()> {
    let causal = bodies.causal.ok_or(PublicationError::MissingEvidence)?;
    let economics = bodies.economics.ok_or(PublicationError::MissingEvidence)?;
    exact(causal, &["binding", "execution", "members"]).map_err(invalid)?;
    exact(
        economics,
        &[
            "economic_result",
            "account_checkpoint",
            "analytical_baseline",
            "roundtrip_count",
            "preparation",
        ],
    )
    .map_err(invalid)?;
    let frozen = binding.record();
    let execution = &causal["execution"];
    exact(execution, &["program", "raw_signals", "signal_receipts", "signal_checkpoint", "signal_execution", "execution_binding", "runtime_binding", "input_sources", "input_evidence", "source", "calculation_build", "native_image", "completion"]).map_err(invalid)?;
    if causal["binding"] != frozen || causal["members"] != json!(bodies.references)
        || execution["completion"] != json!({"contract":"FINITE_OWNER_FINISH_JOIN_V1","producer":"INTERNALLY_OWNED_EXECUTION_TASK","resources":"POSITIVELY_JOINED"})
    {
        return Err(INTEGRITY);
    }
    let (run, operation, revision) = originals;
    let ready = &operation.outputs["ready"];
    let source = SourceRevision::from_json(&execution["source"].to_string(), WORK).map_err(invalid)?;
    let source_record = source.to_record();
    let proof_context = &execution["calculation_build"]["context"];
    let signal = calculation_build::signal_preparation(ready).map_err(owner_error)?;
    let image = text(&ready["native_image"]["artifact"])?;
    let (factors, _) = calculation_factor_inputs(ready).map_err(model::owner_error)?;
    if source_record != execution["source"] || source.fingerprint() != text(&frozen["strategy_revision"])?
        || ready["admission"]["strategy_fingerprint"] != source.fingerprint()
        || execution["native_image"] != ready["native_image"]
        || run.runtime_generation_fingerprint() != text(&frozen["runtime_generation"])?
        || image != text(&frozen["kernel_artifact"])? || factors != frozen["factor_bindings"]
        || proof_context["decision"]["decision_graph"] != source_record["decision_graph"]
        || proof_context["decision"]["signal_semantics"] != source_record["signal_semantics"]
        || proof_context["implementation_bindings"] != source_record["implementation_bindings"]
        || proof_context["algorithm_resolution_request_fingerprint"] != hash_value(&signal["algorithm_resolution_request"])?
        || proof_context["algorithm_resolution_fingerprint"] != hash_value(&signal["algorithm_resolution"])?
        || economics["preparation"] != ready["preparation"]
    {
        return Err(MISMATCH);
    }
    let (prepared, axis) = prepared_input(binding, &run, &operation, &revision, execution, source)?;
    let warmup = frozen["market"]["warmup_rows"].as_u64().ok_or(INTEGRITY)?;
    let sample = axis.get(usize::try_from(warmup).map_err(invalid)?..).ok_or(INTEGRITY)?;
    if plan_members(JobKind::Backtest, &json!(axis), &json!(sample), 0)?.record() != binding.result_plan().record()
        || bodies.curve_axis.iter().copied().ne(sample)
        || backtest_execution_values(&prepared, image).map_err(model::owner_error)?.as_object().ok_or(INTEGRITY)?.iter().any(|(key, value)| frozen[key] != *value)
    {
        return Err(MISMATCH);
    }
    let record = prepared.record();
    let mut settings = record["settings"].clone();
    settings["calendar"] = onlyalpha_data_source_binance::spot_source::spot_calendar().map_err(invalid)?.to_record();
    let cfg = prepared.configuration();
    let cluster = cfg["profiles"].as_object().and_then(|profiles| profiles.keys().next()).ok_or(INTEGRITY)?;
    let policy = next_open_policy(prepared.simulation_policy().clone());
    let inputs = prepared.inputs();
    let first = inputs.records().first().ok_or(INTEGRITY)?;
    let program = program(prepared.source_revision(), ready, image, cfg, cluster, first.source())?;
    let configuration = RunConfiguration::from_record(cfg.clone()).map_err(invalid)?;
    let initial = prepared.initial_ns().try_into().map_err(invalid)?;
    let end = text(&settings["policy"]["end_ns"])?.parse().map_err(invalid)?;
    let execution_binding = ExecutionBinding::new(&configuration, &settings, initial, cluster, &policy.binding()).map_err(invalid)?;
    let input_pin = inputs.fingerprint();
    let runtime = RunBinding::new(&configuration, image, &input_pin, program.fingerprint()).map_err(invalid)?
        .with_execution_fingerprint(execution_binding.fingerprint()).map_err(invalid)?;
    let checkpoint = &execution["signal_checkpoint"];
    if execution["program"] != program.to_record() || execution["runtime_binding"] != *runtime.record()
        || execution["execution_binding"] != *execution_binding.record()
        || execution["signal_execution"] != onlyalpha_strategy::record_fingerprint(checkpoint)
    {
        return Err(MISMATCH);
    }
    let signals = array(&execution["raw_signals"])?;
    program.verify_finite_completion(inputs.records().iter().map(|row| row.bar()), signals, array(&execution["signal_receipts"])?, checkpoint).map_err(invalid)?;
    let economic = &economics["economic_result"];
    let baseline = &economics["analytical_baseline"];
    let verified = onlyalpha_execution::verify_finite_backtest_result(
        economic,
        &economics["account_checkpoint"],
        cfg,
        image,
        &input_pin,
        initial,
        end,
    )
    .map_err(|error| {
        onlyalpha_observability::Operation::start(
            "persistence",
            "backtest.verify_economic_result",
            onlyalpha_observability::Correlation {
                run_id: Some(binding.run_id().into()),
                ..Default::default()
            },
        )
        .finish("failed", 1, 0);
        #[cfg(test)]
        crate::workers::backtest_worker::tests::record_economic_rejection(&error.0);
        invalid(error)
    })?;
    let closed = verified.closed_cycles().get(cluster).copied().ok_or(INTEGRITY)?;
    if economics["roundtrip_count"] != closed || !baseline["net_pnl"].is_string() || !baseline["return_since_start"].is_string() {
        return Err(INTEGRITY);
    }
    onlyalpha_backtest::verify_finite_backtest(inputs, &settings, policy.as_ref(), signals, &bodies.facts, &bodies.curve, economic, verified.equity_points(), baseline)
        .map_err(|error| {
            let operation = match error.0.as_str() {
                "BACKTEST_REPLAY_MODEL_SETTLEMENT_POLICY" => "backtest.verify_settlement_policy",
                _ => "backtest.verify_execution_facts",
            };
            onlyalpha_observability::Operation::start(
                "persistence",
                operation,
                onlyalpha_observability::Correlation {
                    run_id: Some(binding.run_id().into()),
                    ..Default::default()
                },
            )
            .finish("failed", 1, 0);
            invalid(error)
        })
}
