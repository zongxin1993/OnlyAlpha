use super::*;
use crate::{
    application::{
        backtest_run,
        job_input::PreparedJobInput,
        research_admission::{PreparationError, PreparedInputs},
        research_run,
        research_run_execution::Control,
        strategy_research,
    },
    persistence::{
        job_publication::{AttemptClaim, AttemptExecutionBinding, CompletedJobCandidate},
        strategy_research::Composer,
    },
    workers::{
        algorithm::describe_research_runtime, backtest_service::FiniteBacktestCut, trading_program,
    },
};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::{
    ChartInstallation, ProgramFactor, ProgramNodes, native_operators::OperatorCalculation,
};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use onlyalpha_strategy::{Executor, Scope, SourceRevision};
use std::{path::Path, sync::Arc};
const WORK: usize = 8 * 1024 * 1024;
const INVALID: &str = "FINITE_JOB_BINDING_MISMATCH";
const UNKNOWN: &str = "FINITE_JOB_JOIN_UNKNOWN";
pub(super) fn candidate_error(
    error: crate::persistence::job_publication::PublicationError,
    control: &Control,
) -> PreparationError {
    use crate::persistence::job_publication::PublicationError as P;
    match error {
        P::OutcomeUnknown => control.uncertain(UNKNOWN),
        P::Conflict => "RESEARCH_EXECUTION_CANCELLED".into(),
        P::Integrity | P::Mismatch => "FINITE_CANDIDATE_MISMATCH".into(),
        P::BudgetExceeded => "FINITE_CANDIDATE_BUDGET_EXCEEDED".into(),
        P::Denied => "FINITE_CANDIDATE_DENIED".into(),
        P::MissingEvidence => "FINITE_CANDIDATE_MISSING_EVIDENCE".into(),
        P::OwnershipLost => "FINITE_CANDIDATE_OWNERSHIP_LOST".into(),
        P::Unavailable => "FINITE_CANDIDATE_UNAVAILABLE".into(),
    }
}
fn text(v: &Value) -> std::result::Result<&str, PreparationError> {
    v.as_str().ok_or_else(|| INVALID.into())
}
fn rows(v: &Value) -> std::result::Result<&Vec<Value>, PreparationError> {
    v.as_array().ok_or_else(|| INVALID.into())
}
fn mapped<T>(_: T) -> PreparationError {
    INVALID.into()
}
fn fingerprint(v: &Value) -> std::result::Result<String, PreparationError> {
    hash(v).map_err(mapped)
}
fn axis(input: &PreparedJobInput) -> Vec<Value> {
    input
        .dataset()
        .rows()
        .iter()
        .map(|r| {
            json!([
                r["instrument_id"],
                r["bar_start_ns"],
                r["bar_end_ns"],
                r["ts_event_ns"],
                r["revision"]
            ])
        })
        .collect()
}
fn pair(
    axis: Vec<Value>,
    values: Vec<Value>,
) -> std::result::Result<Vec<(Value, Value)>, PreparationError> {
    if axis.len() != values.len() {
        return Err(INVALID.into());
    }
    Ok(axis.into_iter().zip(values).collect())
}
struct NativeBinding<'a> {
    scope: Scope,
    generation: &'a str,
    market: &'a str,
    artifact: &'a str,
    image: &'a str,
}
fn native(
    source: &SourceRevision,
    input: &PreparedJobInput,
    dependencies: &Value,
    binding: NativeBinding<'_>,
) -> std::result::Result<(Executor<ProgramNodes>, BTreeMap<String, String>), PreparationError> {
    let NativeBinding {
        scope,
        generation,
        market,
        artifact,
        image,
    } = binding;
    let source_record = source.to_record();
    if source_record["market_input_contract"]["construction_requirement"]["recipe"]
        != *input.construction_recipe()
    {
        return Err(INVALID.into());
    }
    let graph = Graph::from_record(&source_record["decision_graph"], WORK).map_err(mapped)?;
    let mut capabilities = Vec::new();
    let mut factors = BTreeMap::new();
    let mut used = std::collections::BTreeSet::new();
    for node in graph.ordered_nodes() {
        let record = node.to_record();
        let id = node.fingerprint();
        let binding = rows(&source_record["implementation_bindings"])?
            .iter()
            .find(|b| b["node_fingerprint"] == id)
            .ok_or(INVALID)?;
        let implementation = text(&binding["trading_implementation_fingerprint"])?;
        let (capability, schema) = match record["kind"].as_str() {
            Some("PREDICATE") => continue,
            Some("INDICATOR") => {
                let owner = OperatorCalculation::from_record(&record).map_err(mapped)?;
                if owner
                    .implementation_manifest("TRADING", image)
                    .map_err(mapped)?["implementation_fingerprint"]
                    != implementation
                {
                    return Err(INVALID.into());
                }
                (
                    owner.state_capability().to_owned(),
                    owner.checkpoint_schema_version(),
                )
            }
            Some("FACTOR") => {
                let dependencies = rows(dependencies)?
                    .iter()
                    .filter(|d| d["factor_id"] == record["type_id"])
                    .collect::<Vec<_>>();
                if dependencies.len() != 1 {
                    return Err(INVALID.into());
                }
                let revision = text(&dependencies[0]["revision_fingerprint"])?;
                let ready = input
                    .factors()
                    .iter()
                    .filter(|f| {
                        f.revision_fingerprint() == revision
                            && f.program().parameters().record() == &record["parameters"]
                    })
                    .collect::<Vec<_>>();
                if ready.len() != 1 {
                    return Err(INVALID.into());
                }
                // The original Source graph has already been authenticated by
                // its owning PG build-proof reader. Execution programs do not
                // need authoring source-text privileges to verify that graph.
                let ports = |key: &str| -> std::result::Result<Value, PreparationError> {
                    let mut result = serde_json::Map::new();
                    for p in rows(&record[key])? {
                        let name = text(&p["name"])?;
                        let mut spec = json!({"type":p["data_type"],"nullable":p["nullable"],"semantic_type":p["semantic_type"],"unit":p["unit"]});
                        if key == "inputs" {
                            spec["role"] =
                                ready[0].program().program().record()["inputs"][name]["role"]
                                    .clone();
                        }
                        result.insert(name.into(), spec);
                    }
                    Ok(Value::Object(result))
                };
                let metadata = json!({"factor_id":record["type_id"],"semantic_version":record["semantic_version"],"factor_api_version":1,"factor_api_contract_fingerprint":crate::application::private_assets::authoring::API_FINGERPRINT,"input_contract":ports("inputs")?,"output_contract":ports("outputs")?});
                let calculation = onlyalpha_calculation_bridge::ProgramCalculation::resolve(
                    &metadata,
                    Arc::new(ready[0].program().clone()),
                    ready[0].program_fingerprint(),
                    image,
                    &record["input_bindings"],
                )
                .map_err(mapped)?;
                if calculation.definition() != node
                    || calculation
                        .implementation_manifest("TRADING")
                        .map_err(mapped)?["implementation_fingerprint"]
                        != implementation
                {
                    return Err(INVALID.into());
                }
                used.insert((
                    ready[0].revision_fingerprint().to_owned(),
                    ready[0].program().parameters().fingerprint().to_owned(),
                ));
                factors.insert(
                    id.clone(),
                    ProgramFactor::new(Arc::new(ready[0].program().clone()), implementation)
                        .map_err(mapped)?,
                );
                ("CHECKPOINTABLE".into(), Some(1))
            }
            _ => return Err(INVALID.into()),
        };
        capabilities.push(json!({"node_fingerprint":id,"implementation_fingerprint":implementation,"state_capability":capability,"checkpoint_schema_version":schema}));
    }
    if used.len() != input.factors().len() {
        return Err(INVALID.into());
    }
    let (program, definitions, mapping) = trading_program::materialize(
        source,
        scope,
        generation,
        market,
        artifact,
        &json!(capabilities),
    )
    .map_err(mapped)?;
    let factors = factors
        .into_iter()
        .map(|(key, value)| Ok((mapping.get(&key).ok_or(INVALID)?.clone(), value)))
        .collect::<std::result::Result<BTreeMap<_, _>, PreparationError>>()?;
    let port = ProgramNodes::new(program.clone(), definitions, factors, image).map_err(mapped)?;
    Ok((Executor::new(program, port).map_err(mapped)?, mapping))
}
struct ResearchWork {
    run: research_run::VerifiedRun,
    prepared: PreparedInputs,
    installation: Arc<ChartInstallation>,
    source: SourceRevision,
    private_revision: Value,
}
enum Work {
    Research(Box<ResearchWork>),
    Backtest(FiniteBacktestCut),
}
impl Work {
    fn verify(&self) -> std::result::Result<(), PreparationError> {
        match self {
            Self::Research(w) => {
                w.prepared.verify_runtime()?;
                w.installation.verify().map_err(mapped)?;
                Ok(())
            }
            Self::Backtest(w) => w.verify().map_err(PreparationError::from),
        }
    }
}
/// Owned actual execution task. No external JoinHandle, callback, Completed DTO
/// or caller-provided joined flag is accepted by its constructors.
pub struct FiniteTask {
    handle: tokio::task::JoinHandle<(Work, std::result::Result<Products, PreparationError>)>,
    control: Control,
    binding: FrozenJobBinding,
    execution: Option<AttemptExecutionBinding>,
}
/// Positive reclamation of the exact internally owned task, retaining its
/// physical inputs through cancellation finalization. This is never a result.
pub struct DrainedFiniteJob {
    binding: FrozenJobBinding,
    guard: Arc<JoinedCut>,
}
impl DrainedFiniteJob {
    pub(crate) fn binding(&self) -> &FrozenJobBinding {
        &self.binding
    }
    pub(crate) fn verify_attempt(
        &self,
        claim: &AttemptClaim<'_>,
    ) -> std::result::Result<(), PreparationError> {
        self.guard.control.verify_drained()?;
        if !self
            .guard
            .execution
            .as_ref()
            .is_some_and(|execution| execution.matches(claim))
        {
            return Err(INVALID.into());
        }
        Ok(())
    }
}
pub(crate) enum FiniteOutcome {
    Completed(CompletedJobCandidate),
    Failed {
        drained: DrainedFiniteJob,
        error: PreparationError,
    },
}
fn joined_failure(
    binding: FrozenJobBinding,
    guard: Arc<JoinedCut>,
    error: PreparationError,
) -> std::result::Result<FiniteOutcome, PreparationError> {
    if error.code().contains("UNKNOWN")
        || error.recovery_owner().is_some_and(|owner| {
            owner.state() != onlyalpha_calculation_bridge::ProcessState::Joined
        })
    {
        return Err(error);
    }
    guard.control.verify_drained()?;
    Ok(FiniteOutcome::Failed {
        drained: DrainedFiniteJob { binding, guard },
        error,
    })
}
/// Actual joined resources remain held through candidate validation/publication.
/// There is no constructor or deserializer outside this owning module.
pub struct JoinedFiniteJob {
    binding: FrozenJobBinding,
    members: Vec<(ResultMember, Value)>,
    research_result: Option<String>,
    guard: Arc<JoinedCut>,
}
pub struct JoinedCut {
    execution: Option<AttemptExecutionBinding>,
    work: Work,
    control: Control,
}
impl std::fmt::Debug for JoinedCut {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("JoinedFiniteJobCut")
    }
}
impl JoinedCut {
    pub(crate) fn matches_attempt(&self, claim: &AttemptClaim<'_>) -> bool {
        self.execution
            .as_ref()
            .is_some_and(|execution| execution.matches(claim))
    }
    pub fn verify(&self) -> std::result::Result<(), PreparationError> {
        self.work.verify()?;
        self.control.check()?;
        if matches!(self.work, Work::Research(_)) {
            self.control.verify_joined()?;
        }
        Ok(())
    }
}
pub type JoinedParts = (
    FrozenJobBinding,
    Vec<(ResultMember, Value)>,
    Option<String>,
    Arc<JoinedCut>,
);
impl JoinedFiniteJob {
    pub fn into_parts(self) -> std::result::Result<JoinedParts, PreparationError> {
        self.guard.verify()?;
        Ok((self.binding, self.members, self.research_result, self.guard))
    }
}
/// The exact execution task has returned. Resource verification and candidate
/// construction remain separate, so a cancellation race can still discard an
/// unpublished mathematical result without inventing a result or joined flag.
pub(crate) struct FinishedFiniteTask {
    binding: FrozenJobBinding,
    guard: Arc<JoinedCut>,
    outcome: std::result::Result<Products, PreparationError>,
}
impl FinishedFiniteTask {
    pub(crate) fn into_drained(self) -> std::result::Result<DrainedFiniteJob, PreparationError> {
        if let Err(error) = self.outcome {
            if error.code().contains("UNKNOWN")
                || error.recovery_owner().is_some_and(|owner| {
                    owner.state() != onlyalpha_calculation_bridge::ProcessState::Joined
                })
            {
                return Err(error);
            }
        }
        self.guard.control.verify_drained()?;
        Ok(DrainedFiniteJob {
            binding: self.binding,
            guard: self.guard,
        })
    }
    pub(crate) fn into_outcome(self) -> std::result::Result<FiniteOutcome, PreparationError> {
        let guard = self.guard;
        let mut products = match self.outcome {
            Ok(products) => products,
            Err(error) => return joined_failure(self.binding, guard, error),
        };
        let verification = guard.work.verify().and_then(|_| {
            guard.control.check()?;
            if matches!(guard.work, Work::Research(_)) {
                guard.control.verify_joined()?;
            }
            Ok(())
        });
        if let Err(error) = verification {
            return joined_failure(self.binding, guard, error);
        }
        products.causal["completion"] = json!({"contract":"FINITE_OWNER_FINISH_JOIN_V1","producer":"INTERNALLY_OWNED_EXECUTION_TASK","resources":"POSITIVELY_JOINED"});
        let research_result = products.research_result.take();
        let members = match contents(&self.binding, products) {
            Ok(members) => members,
            Err(error) => {
                tracing::warn!(?error, "finite result construction failed");
                let error = candidate_error(error, &guard.control);
                return joined_failure(self.binding, guard, error);
            }
        };
        let joined = JoinedFiniteJob {
            binding: self.binding.clone(),
            members,
            research_result,
            guard: guard.clone(),
        };
        match CompletedJobCandidate::from_joined(joined) {
            Ok(candidate) => Ok(FiniteOutcome::Completed(candidate)),
            Err(error) => {
                let error = candidate_error(error, &guard.control);
                joined_failure(self.binding, guard, error)
            }
        }
    }
}
impl FiniteTask {
    pub fn cancellation(&self) -> Control {
        self.control.clone()
    }
    /// Stop and positively join both the reaper and the original task. A failed
    /// stop is retained even if the mathematical task returns in the meantime.
    pub async fn drain(self) -> std::result::Result<DrainedFiniteJob, PreparationError> {
        self.control.request_stop();
        let control = self.control.clone();
        let stopping = tokio::task::spawn_blocking(move || control.stop());
        let finished = self.finish().await;
        stopping
            .await
            .map_err(|_| PreparationError::unknown(UNKNOWN, None))??;
        finished?.into_drained()
    }
    pub(crate) async fn finish(self) -> std::result::Result<FinishedFiniteTask, PreparationError> {
        let (work, outcome) = self
            .handle
            .await
            .map_err(|_| self.control.uncertain(UNKNOWN))?;
        Ok(FinishedFiniteTask {
            binding: self.binding,
            guard: Arc::new(JoinedCut {
                execution: self.execution,
                work,
                control: self.control,
            }),
            outcome,
        })
    }
    /// Only the exact internally-created task's positive join reaches a
    /// completion candidate. Existing callers retain the original error.
    pub async fn join(self) -> std::result::Result<CompletedJobCandidate, PreparationError> {
        match self.finish().await?.into_outcome()? {
            FiniteOutcome::Completed(candidate) => Ok(candidate),
            FiniteOutcome::Failed { error, .. } => Err(error),
        }
    }
}

fn check_input(
    binding: &FrozenJobBinding,
    input: &PreparedJobInput,
) -> std::result::Result<(), PreparationError> {
    if binding.fingerprint() != input.binding_fingerprint()
        || binding.market().record()["dataset_snapshot"] != input.dataset().snapshot_fingerprint()
    {
        return Err(INVALID.into());
    }
    Ok(())
}
pub(super) fn check_market_origin(
    binding: &FrozenJobBinding,
    materialization: &Value,
) -> std::result::Result<(), PreparationError> {
    let originals = rows(&materialization["market_data_revision_bindings"])?;
    if originals.len() != 1
        || originals[0]["revision_fingerprint"] != binding.market().record()["source_revision"]
        || originals[0]["data_kind"] != "BAR"
        || json!([originals[0]["instrument_id"]]) != binding.market().record()["instruments"]
    {
        return Err("FINITE_JOB_SOURCE_BINDING_MISMATCH".into());
    }
    Ok(())
}
fn check_common(
    binding: &FrozenJobBinding,
    source: &SourceRevision,
    generation: &str,
    image: &Value,
) -> std::result::Result<(), PreparationError> {
    let record = binding.record();
    if record["strategy_revision"] != source.fingerprint()
        || record["signal_graph"] != source.to_record()["decision_graph_fingerprint"]
        || record["runtime_generation"] != generation
        || record["kernel_artifact"] != image["artifact"]
    {
        return Err(INVALID.into());
    }
    Ok(())
}
/// Re-read original PG composition/build facts and retain exact Runtime and
/// installed artifacts. This API remains unwired to formal job dispatch in phase5.
pub async fn start_research(
    run: research_run::VerifiedRun,
    prepared: PreparedInputs,
    input: PreparedJobInput,
    binding: FrozenJobBinding,
    composer: &mut Composer<'_>,
    installation: Arc<ChartInstallation>,
) -> std::result::Result<FiniteTask, PreparationError> {
    start_research_inner(run, prepared, input, binding, composer, installation, None).await
}
/// Formal execution captures the actual Claim before any asynchronous preparation
/// or spawn. The returned task has no API for replacing its Attempt association.
pub async fn start_research_claimed(
    run: research_run::VerifiedRun,
    prepared: PreparedInputs,
    input: PreparedJobInput,
    binding: FrozenJobBinding,
    composer: &mut Composer<'_>,
    installation: Arc<ChartInstallation>,
    execution: AttemptExecutionBinding,
) -> std::result::Result<FiniteTask, PreparationError> {
    execution.check_binding(&binding).map_err(mapped)?;
    start_research_inner(
        run,
        prepared,
        input,
        binding,
        composer,
        installation,
        Some(execution),
    )
    .await
}
async fn start_research_inner(
    run: research_run::VerifiedRun,
    prepared: PreparedInputs,
    input: PreparedJobInput,
    binding: FrozenJobBinding,
    composer: &mut Composer<'_>,
    installation: Arc<ChartInstallation>,
    execution: Option<AttemptExecutionBinding>,
) -> std::result::Result<FiniteTask, PreparationError> {
    check_input(&binding, &input)?;
    prepared.verify_runtime()?;
    check_market_origin(&binding, &prepared.record()["dataset_materialization"])?;
    composer.verify_finite_run(&run, &binding).await?;
    installation.verify().map_err(mapped)?;
    let specification = run.strategy_specification()?;
    let spec = specification.record();
    if binding.kind() != JobKind::Research
        || binding.run_id() != run.run_id()
        || prepared.record() != &run.prepared_inputs
        || prepared.record()["runtime_work_binding"]["work_id"] != run.run_id()
        || prepared.record()["runtime_work_binding"]["reason"] != "research"
        || spec["scientific_specification"]["dataset_snapshot_fingerprint"]
            != input.dataset().snapshot_fingerprint()
        || installation.artifact_fingerprint() != spec["algorithm_artifact_fingerprint"]
    {
        return Err(INVALID.into());
    }
    let (composition, revision, _, _) = composer
        .retained_inputs(&prepared.record()["composition"], &prepared.runtime_hold())
        .await?;
    if composition.record() != &prepared.record()["composition"] {
        return Err(INVALID.into());
    }
    composer
        .verify_calculation_build(&prepared.record()["build_certification"])
        .await?;
    let expected = crate::application::calculation_build::context(
        prepared.record(),
        spec,
        input.dataset().definition(),
        input.construction_recipe(),
    )?;
    crate::application::calculation_build::verify(
        &prepared.record()["build_certification"],
        &expected,
    )?;
    if binding.market().record()["warmup_rows"] != spec["input_window"]["warmup_bars"] {
        return Err(INVALID.into());
    }
    let values = research_execution_values(
        specification,
        input.dataset().definition(),
        input.construction_recipe(),
    )?;
    let source = SourceRevision::from_json(&values["source"].to_string(), WORK).map_err(mapped)?;
    let image = describe_research_runtime(env!("CARGO_PKG_VERSION")).map_err(mapped)?;
    crate::application::research_run_execution::verify_executor_image(
        &image,
        &spec["execution_binding"],
    )?;
    check_common(
        &binding,
        &source,
        run.runtime_generation_fingerprint()?,
        &image,
    )?;
    let frozen = binding.record();
    for key in [
        "execution_configuration",
        "initial_state",
        "calendar",
        "fees",
        "market_rules",
    ] {
        if frozen[key] != values[key] {
            return Err(INVALID.into());
        }
    }
    let work = Work::Research(Box::new(ResearchWork {
        run,
        prepared,
        installation,
        source,
        private_revision: revision,
    }));
    let control = Control::default();
    let child = control.clone();
    let pins = binding.clone();
    input
        .require_source_access()
        .map_err(|_| PreparationError::from("FINITE_JOB_SOURCE_ACCESS_DENIED"))?;
    #[cfg(test)]
    crate::workers::research_service::owner_tests::execution_started(binding.run_id());
    let handle = tokio::task::spawn_blocking(move || {
        let result = execute_research(&work, &input, &pins, &image, &child);
        (work, result)
    });
    Ok(FiniteTask {
        execution,
        handle,
        control,
        binding,
    })
}
fn execute_research(
    work: &Work,
    input: &PreparedJobInput,
    binding: &FrozenJobBinding,
    image: &Value,
    control: &Control,
) -> std::result::Result<Products, PreparationError> {
    let Work::Research(work) = work else {
        return Err(INVALID.into());
    };
    let spec = work.run.strategy_specification()?;
    let generation = work.run.runtime_generation_fingerprint()?;
    let (executor, _) = native(
        &work.source,
        input,
        &work.prepared.record()["composition"]["factor_revision_bindings"],
        NativeBinding {
            scope: Scope {
                engine: "research-observation".parse().map_err(mapped)?,
                runtime: "finite-observation".parse().map_err(mapped)?,
                cluster: "decision".parse().map_err(mapped)?,
            },
            generation,
            market: input.dataset().snapshot_fingerprint(),
            artifact: work.installation.artifact_fingerprint(),
            image: text(&image["artifact"])?,
        },
    )?;
    let mut run =
        onlyalpha_strategy::ResearchRun::new(executor, input.bars().to_vec()).map_err(mapped)?;
    for _ in input.bars() {
        control.check()?;
        run.step().map_err(mapped)?;
    }
    let completed = run.finish().map_err(mapped)?;
    let batch = strategy_research::finite_calculations(
        &work.prepared,
        spec,
        input.bars(),
        text(&image["artifact"])?,
        control,
    )?;
    let features = rows(batch.columns())?.clone();
    let (targets, statistics) = strategy_research::finite_ancillaries(
        &work.prepared,
        spec,
        work.installation.clone(),
        input.bars(),
        json!(features),
        control,
    )?;
    let axes = axis(input);
    let calculations=(0..axes.len()).map(|i|json!({"decision":features.iter().map(|f|json!({"node_fingerprint":f["node_fingerprint"],"implementation_fingerprint":f["implementation_fingerprint"],"outputs":f["values"].as_object().expect("owned columns").iter().map(|(k,v)|(k.clone(),v[i].clone())).collect::<serde_json::Map<_,_>>()})).collect::<Vec<_>>(),"targets":targets.iter().map(|f|json!({"node_fingerprint":f["node_fingerprint"],"implementation_fingerprint":f["implementation_fingerprint"],"outputs":f["values"].as_object().expect("owned target columns").iter().map(|(k,v)|(k.clone(),v[i].clone())).collect::<serde_json::Map<_,_>>()})).collect::<Vec<_>>()})).collect::<Vec<_>>();
    let stats: Vec<(Value, Value)> = statistics
        .into_iter()
        .map(|s| (s["statistics_fingerprint"].clone(), s))
        .collect();
    let calculations = pair(axes.clone(), calculations)?;
    // 科学结果身份与发布成员同源：读取方在同一成员表示上调用同一函数复核。
    let research_result =
        crate::persistence::research_evidence::strategy::published_result_fingerprint(
            spec,
            &calculations,
            &stats,
        )?;
    let report = json!({"specification":spec.record(),"result_plan":spec.result_plan()?,"candidate":spec.candidate_fingerprint()?,"source":work.source.to_record(),"private_revision":work.private_revision,"input_window":spec.record()["input_window"],"binding":binding.record()});
    Ok(Products {
        research_result: Some(research_result),
        sequences: BTreeMap::from([
            (MemberKind::CalculationValues, calculations),
            (
                MemberKind::SignalValues,
                pair(axes, completed.signals().to_vec())?,
            ),
            (MemberKind::Statistics, stats),
        ]),
        roots: BTreeMap::from([(MemberKind::ResearchReport, report)]),
        causal: json!({"program":completed.program(),"source":work.source.to_record(),"private_revision":work.private_revision,"input_evidence":input.source_evidence(),"factor_bindings":binding.record()["factor_bindings"],"signal_execution":completed.execution_fingerprint(),"signal_plane":{"backend_kind":"TRADING","purpose":"SHARED_EVENT_SIGNAL_REFERENCE","implementation_bindings":spec.record()["implementation_bindings"]},"calculation_batch":batch.evidence(),"signal_input":completed.input_fingerprint(),"build_certification":work.prepared.record()["build_certification"],"native_image":image}),
    })
}
/// Original verified admission and exact installed resources. Field privacy
/// prevents callers from substituting Source/configuration values after prepare.
pub struct PreparedBacktestJob {
    cut: FiniteBacktestCut,
    image: Value,
}
/// Preparation retains its owning cut through input loading and actual join;
/// no public preparation JSON is converted into this capability.
pub async fn prepare_backtest(
    client: &mut tokio_postgres::Client,
    facts: &mut tokio_postgres::Client,
    run: &backtest_run::VerifiedRun,
    research_root: &Path,
    runtime_root: &Path,
    algorithm_root: &Path,
) -> std::result::Result<PreparedBacktestJob, PreparationError> {
    let cut = FiniteBacktestCut::load(
        client,
        facts,
        run,
        research_root,
        runtime_root,
        algorithm_root,
    )
    .await?;
    let image = describe_research_runtime(env!("CARGO_PKG_VERSION")).map_err(mapped)?;
    if cut.run().resolution()["backtest_binding"]["executor_artifact_sha256"] != image["artifact"] {
        return Err(INVALID.into());
    }
    Ok(PreparedBacktestJob { cut, image })
}
impl PreparedBacktestJob {
    pub(crate) fn installation(&self) -> Arc<ChartInstallation> {
        self.cut.installation_owner()
    }
    pub fn preparation(&self) -> &crate::workers::backtest::PreparedNextOpen {
        self.cut.prepared()
    }
    pub fn execution_values(&self) -> std::result::Result<Value, PreparationError> {
        backtest_execution_values(self.cut.prepared(), text(&self.image["artifact"])?)
    }
    /// Exact frozen input descriptions from the retained owning calculation cut.
    /// These values do not grant PG READY or replace JobInputLoader verification.
    pub fn factor_bindings(&self) -> std::result::Result<Value, PreparationError> {
        Ok(calculation_factor_inputs(self.cut.calculations()?)?.0)
    }
    pub fn start(
        self,
        input: PreparedJobInput,
        binding: FrozenJobBinding,
    ) -> std::result::Result<FiniteTask, PreparationError> {
        self.start_inner(input, binding, None)
    }
    pub(crate) fn start_claimed(
        self,
        input: PreparedJobInput,
        binding: FrozenJobBinding,
        claim: &AttemptClaim<'_>,
    ) -> std::result::Result<FiniteTask, PreparationError> {
        let execution = AttemptExecutionBinding::capture(claim).map_err(mapped)?;
        execution.check_binding(&binding).map_err(mapped)?;
        self.start_inner(input, binding, Some(execution))
    }
    fn start_inner(
        self,
        input: PreparedJobInput,
        binding: FrozenJobBinding,
        execution: Option<AttemptExecutionBinding>,
    ) -> std::result::Result<FiniteTask, PreparationError> {
        self.cut.verify()?;
        check_input(&binding, &input)?;
        check_market_origin(&binding, self.cut.materialization())?;
        let run = self.cut.run();
        if binding.kind() != JobKind::Backtest
            || binding.run_id() != run.run_id()
            || binding.namespace() != run.namespace().value()
            || binding.owner() != run.owner()
        {
            return Err(INVALID.into());
        }
        check_common(
            &binding,
            self.cut.source(),
            run.runtime_generation_fingerprint(),
            &self.image,
        )?;
        if run.specification().record()["dataset_snapshot_fingerprint"]
            != input.dataset().snapshot_fingerprint()
            || self
                .cut
                .prepared()
                .inputs()
                .records()
                .iter()
                .map(|i| i.bar())
                .ne(input.bars().iter())
        {
            return Err(INVALID.into());
        }
        let values = self.execution_values()?;
        for (key, value) in values.as_object().ok_or(INVALID)? {
            if binding.record()[key] != *value {
                return Err(INVALID.into());
            }
        }
        let control = Control::default();
        let child = control.clone();
        let pins = binding.clone();
        let image = self.image;
        let work = Work::Backtest(self.cut);
        input
            .require_source_access()
            .map_err(|_| PreparationError::from("FINITE_JOB_SOURCE_ACCESS_DENIED"))?;
        let handle = crate::workers::backtest_profile::spawn_blocking(move || {
            let result = crate::workers::backtest_profile::measure(
                pins.run_id(),
                "backtest.execute_frozen",
                || {
                    #[cfg(test)]
                    {
                        use std::io::Write;

                        crate::workers::backtest_worker::tests::blocking_phase(
                            pins.run_id(),
                            "execute_frozen",
                        );
                        let mut stdout = std::io::stdout().lock();
                        writeln!(stdout, "BACKTEST_EXECUTION_STARTED {}", pins.run_id()).unwrap();
                        stdout.flush().unwrap();
                    }
                    execute_backtest(&work, &input, &pins, &image, &child)
                },
            );
            (work, result)
        });
        Ok(FiniteTask {
            execution,
            handle,
            control,
            binding,
        })
    }
}

pub(crate) fn calculation_factor_inputs(
    calculations: &Value,
) -> std::result::Result<(Value, Value), PreparationError> {
    if calculations["algorithm_resolution"]["contract"]
        != "ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1"
    {
        return Err(INVALID.into());
    }
    let observed = &calculations["algorithm_resolution"];
    let mut bindings = BTreeMap::new();
    let mut dependencies = BTreeMap::new();
    for pin in rows(&observed["native_execution"]["program_bindings"])? {
        let nodes = rows(&observed["nodes"])?
            .iter()
            .filter(|n| {
                n["instance_key"] == pin["instance_key"] && n["definition"]["kind"] == "FACTOR"
            })
            .collect::<Vec<_>>();
        if nodes.len() != 1 {
            return Err(INVALID.into());
        }
        let d = &nodes[0]["definition"];
        if fingerprint(&d["parameters"])? != pin["parameters"] {
            return Err(INVALID.into());
        }
        let value = json!({"revision":pin["revision"],"program":pin["program"],"certificate":pin["certificate"],"parameters":pin["parameters"],"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1"});
        let key = (
            text(&pin["revision"])?.to_owned(),
            text(&pin["parameters"])?.to_owned(),
        );
        if bindings
            .insert(key, value.clone())
            .is_some_and(|old| old != value)
        {
            return Err(INVALID.into());
        }
        let id = text(&d["type_id"])?;
        let dependency = json!({"factor_id":id,"revision_fingerprint":pin["revision"]});
        if dependencies
            .insert(id.to_owned(), dependency.clone())
            .is_some_and(|old| old != dependency)
        {
            return Err(INVALID.into());
        }
    }
    Ok((
        json!(bindings.into_values().collect::<Vec<_>>()),
        json!(dependencies.into_values().collect::<Vec<_>>()),
    ))
}
fn execute_backtest(
    work: &Work,
    input: &PreparedJobInput,
    binding: &FrozenJobBinding,
    image: &Value,
    control: &Control,
) -> std::result::Result<Products, PreparationError> {
    let Work::Backtest(work) = work else {
        return Err(INVALID.into());
    };
    work.verify()?;
    let prepared = work.prepared();
    let cfg = prepared.configuration();
    let profiles = cfg["profiles"]
        .as_object()
        .filter(|p| p.len() == 1)
        .ok_or(INVALID)?;
    let cluster = profiles.keys().next().ok_or(INVALID)?;
    let calculations = work.calculations()?;
    let (_, dependencies) = calculation_factor_inputs(calculations)?;
    let (executor, _) = native(
        work.source(),
        input,
        &dependencies,
        NativeBinding {
            scope: Scope {
                engine: text(&cfg["engine"])?.parse().map_err(mapped)?,
                runtime: text(&cfg["runtime"])?.parse().map_err(mapped)?,
                cluster: cluster.parse().map_err(mapped)?,
            },
            generation: work.run().runtime_generation_fingerprint(),
            market: prepared.inputs().records().first().ok_or(INVALID)?.source(),
            artifact: work.installation().artifact_fingerprint(),
            image: text(&image["artifact"])?,
        },
    )?;
    let configuration =
        onlyalpha_runtime::RunConfiguration::from_record(cfg.clone()).map_err(mapped)?;
    let mut settings = prepared.record()["settings"].clone();
    settings["calendar"] = onlyalpha_data_source_binance::spot_source::spot_calendar()
        .map_err(mapped)?
        .to_record();
    let initial: i64 = prepared.initial_ns().try_into().map_err(mapped)?;
    let resolver = prepared.simulation_policy().binding();
    let execution = onlyalpha_backtest::ExecutionBinding::new(
        &configuration,
        &settings,
        initial,
        cluster,
        &resolver,
    )
    .map_err(mapped)?;
    let frozen = binding.record();
    if frozen["execution_configuration"] != execution.fingerprint()
        || frozen["initial_state"] != fingerprint(cfg)?
        || frozen["calendar"] != fingerprint(&settings["calendar"])?
        || frozen["fees"] != fingerprint(&resolver)?
        || frozen["market_rules"] != fingerprint(&resolver["rules_snapshot"])?
    {
        return Err(INVALID.into());
    }
    let pins = onlyalpha_runtime::RunBinding::new(
        &configuration,
        text(&image["artifact"])?,
        &prepared.inputs().fingerprint(),
        executor.program().fingerprint(),
    )
    .map_err(mapped)?
    .with_execution_fingerprint(execution.fingerprint())
    .map_err(mapped)?;
    let mut run = onlyalpha_backtest::BacktestRun::new(
        onlyalpha_backtest::MemoryRunSpec {
            configuration,
            binding: pins,
            policy_settings: settings,
            initial_ns: initial,
            cluster: cluster.clone(),
        },
        prepared.inputs().clone(),
        executor,
        crate::workers::backtest::next_open_policy(prepared.simulation_policy().clone()),
    )
    .map_err(mapped)?;
    #[cfg(test)]
    let mut first_step = true;
    for _ in input.bars() {
        control.check()?;
        run.step().map_err(mapped)?;
        #[cfg(test)]
        if std::mem::take(&mut first_step) {
            crate::workers::backtest_worker::tests::blocking_phase(
                binding.run_id(),
                "after_first_step",
            );
        }
    }
    let completed = run.finish().map_err(mapped)?;
    control.check()?;
    work.verify()?;
    let event_axis = completed
        .execution_facts()
        .iter()
        .enumerate()
        .map(|(index, fact)| {
            Ok((fact_coordinate(fact, index + 1).map_err(mapped)?, fact.clone()))
        })
        .collect::<std::result::Result<Vec<_>, PreparationError>>()?;
    let full = axis(input);
    let curve = completed.close_curve();
    let sample_axis = input
        .bars()
        .iter()
        .zip(full)
        .filter_map(|(bar, axis)| {
            let start = OnlyTimestamp::from_datetime(*bar.bar_start())
                .unix_nanos()
                .to_string();
            curve
                .iter()
                .any(|c| c["bar_start_ns"] == start)
                .then_some(axis)
        })
        .collect::<Vec<_>>();
    if curve.len() as u64
        != binding.market().record()["sample_rows"]
            .as_u64()
            .ok_or(INVALID)?
    {
        return Err(INVALID.into());
    }
    use onlyalpha_domain::numeric::{OnlyDecimal, only_divide, only_quantize, only_subtract};
    let mut baseline = completed.baseline().clone();
    let initial: OnlyDecimal = text(&baseline["initial_equity"])?.parse().map_err(mapped)?;
    let equity: OnlyDecimal = text(&baseline["final_equity"])?.parse().map_err(mapped)?;
    let net = only_subtract(&equity, &initial).map_err(mapped)?;
    let rate = only_divide(&net, &initial).map_err(mapped)?;
    let quantum = "0.00000001".parse().map_err(mapped)?;
    baseline["net_pnl"] = json!(net.to_string());
    baseline["return_since_start"] = json!(only_quantize(&rate, &quantum).map_err(mapped)?.to_string());
    let roundtrip_count = completed.closed_cycle_count().map_err(mapped)?;
    Ok(Products {
        research_result: None,
        sequences: BTreeMap::from([
            (MemberKind::ExecutionFacts, event_axis),
            (MemberKind::CloseCurve, pair(sample_axis, curve.to_vec())?),
        ]),
        roots: BTreeMap::from([(
            MemberKind::EconomicResult,
            json!({
                "economic_result": completed.economic_result(),
                "account_checkpoint": completed.account_checkpoint(),
                "analytical_baseline": baseline,
                "roundtrip_count": roundtrip_count,
                "preparation": prepared.record(),
            }),
        )]),
        causal: json!({
            "program":completed.program(),
            "raw_signals":completed.raw_signals(),
            "signal_receipts":completed.signal_receipts(),
            "signal_checkpoint":completed.signal_checkpoint(),
            "signal_execution":completed.signal_execution_fingerprint(),
            "execution_binding":completed.execution_binding().record(),
            "runtime_binding":completed.binding().record(),
            "input_sources":prepared.inputs().record(),
            "input_evidence":input.source_evidence(),
            "source":work.source().to_record(),
            "calculation_build":calculations["build_certification"],
            "native_image":image
        }),
    })
}

/// Pure frozen-value preparation; this does not authenticate the Source, Run,
/// build proof, image or input. start_research independently reads those owners.
pub fn research_execution_values(
    specification: &strategy_research::RunSpecification,
    definition: &Value,
    recipe: &Value,
) -> std::result::Result<Value, PreparationError> {
    let spec = specification.record();
    let graph = Graph::from_record(&spec["decision"]["decision_graph"], WORK).map_err(mapped)?;
    let source = strategy_research::source_revision(
        &graph,
        &spec["implementation_bindings"],
        &spec["decision"]["signal_semantics"],
        definition,
        recipe,
    )?;
    let configuration = json!({"schema_version":1,"kind":"FINITE_RESEARCH","signal_state":"GENESIS","source":source.to_record(),"execution":spec["execution_binding"],"scientific_specification":spec["scientific_specification"],"input_window":spec["input_window"]});
    let na = fingerprint(&json!({"schema_version":1,"kind":"NOT_APPLICABLE","job":"RESEARCH"}))?;
    Ok(
        json!({"source":source.to_record(),"strategy_revision":source.fingerprint(),"signal_graph":source.to_record()["decision_graph_fingerprint"],"runtime_generation":spec["runtime_generation_fingerprint"],"kernel_artifact":spec["execution_binding"]["executor_artifact_sha256"],"execution_configuration":fingerprint(&configuration)?,"initial_state":fingerprint(&json!({"signal_state":"GENESIS"}))?,"calendar":na,"fees":na,"market_rules":na}),
    )
}
/// Actual selected cash-market policy values only, not a Backtest admission.
pub fn backtest_execution_values(
    prepared: &crate::workers::backtest::PreparedNextOpen,
    kernel: &str,
) -> std::result::Result<Value, PreparationError> {
    let configuration =
        onlyalpha_runtime::RunConfiguration::from_record(prepared.configuration().clone())
            .map_err(mapped)?;
    let mut settings = prepared.record()["settings"].clone();
    settings["calendar"] = onlyalpha_data_source_binance::spot_source::spot_calendar()
        .map_err(mapped)?
        .to_record();
    let cluster = prepared.configuration()["profiles"]
        .as_object()
        .filter(|m| m.len() == 1)
        .and_then(|m| m.keys().next())
        .ok_or(INVALID)?;
    let initial: i64 = prepared.initial_ns().try_into().map_err(mapped)?;
    let resolver = prepared.simulation_policy().binding();
    let execution = onlyalpha_backtest::ExecutionBinding::new(
        &configuration,
        &settings,
        initial,
        cluster,
        &resolver,
    )
    .map_err(mapped)?;
    let source = prepared.source_revision();
    Ok(
        json!({"strategy_revision":source.fingerprint(),"signal_graph":source.to_record()["decision_graph_fingerprint"],"runtime_generation":prepared.configuration()["generation"],"kernel_artifact":kernel,"execution_configuration":execution.fingerprint(),"initial_state":fingerprint(prepared.configuration())?,"calendar":fingerprint(&settings["calendar"])?,"fees":fingerprint(&resolver)?,"market_rules":fingerprint(&resolver["rules_snapshot"])?}),
    )
}
