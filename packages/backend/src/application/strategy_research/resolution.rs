//! Held-Generation mathematical definition resolution. No Research or Freeze grant.
use super::{Composition, Context, DecisionGraph};
use crate::{
    application::{
        private_strategy::Definition,
        research_admission::{PreparationError, check_binding, implementation_projection},
    },
    persistence::research_runtime::RuntimeInputHold,
    workers::algorithm::AlgorithmProcess,
};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    sync::Arc,
    time::Duration,
};
const INVALID: &str = "PRIVATE_STRATEGY_CALCULATION_RESOLUTION_INVALID";
type Result<T> = std::result::Result<T, PreparationError>;
pub struct ResolvedCalculations {
    // Retain the original work/lifecycle hold through the caller's handoff.
    runtime: Arc<RuntimeInputHold>,
    record: Value,
    // Exact request sent to the actual installed producer, retained for the
    // owning execution/restore path. It is never reconstructed from a DTO.
    request: Value,
}
impl ResolvedCalculations {
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub(crate) fn into_preparation(self) -> (Arc<RuntimeInputHold>, Value, Value) {
        (self.runtime, self.record, self.request)
    }
    pub(crate) fn resolve(
        runtime: RuntimeInputHold,
        installation: &ChartInstallation,
        revision: &Value,
        context: &Context,
        factors: &BTreeMap<String, Value>,
        composition: &Composition,
    ) -> Result<Self> {
        let expected=Composition::derive(revision,context,runtime.manifest(),factors)?;
        if expected.record()!=composition.record(){return Err(INVALID.into());}
        Self::resolve_exact(runtime,installation,revision,factors,context.record()["targets"].as_array().ok_or(INVALID)?,Some((context,composition)),None)
    }
    pub(crate) fn resolve_manual(runtime:RuntimeInputHold,installation:&ChartInstallation,revision:&Value,factors:&BTreeMap<String,Value>,control:&crate::application::research_run_execution::Control)->Result<Self> {
        Self::resolve_exact(runtime,installation,revision,factors,&[],None,Some(control))
    }
    fn resolve_exact(mut runtime:RuntimeInputHold,installation:&ChartInstallation,revision:&Value,factors:&BTreeMap<String,Value>,target_instances:&[Value],research:Option<(&Context,&Composition)>,control:Option<&crate::application::research_run_execution::Control>)->Result<Self> {
        runtime.verify_artifacts()?;
        let definition = Definition::from_record(&revision["definition"])?;
        let strategy = definition.to_record();
        let mut saved_factors = BTreeMap::new();
        let bindings = runtime.manifest()["private_factor_bindings"]
            .as_array()
            .ok_or(INVALID)?
            .clone();
        let mut sources = vec![];
        for (id, factor) in factors {
            let binding = bindings
                .iter()
                .find(|b| b["entry"]["factor_id"] == *id)
                .ok_or(INVALID)?;
            let saved = runtime.private_factor(
                binding["runtime_artifact_fingerprint"]
                    .as_str()
                    .ok_or(INVALID)?,
            )?;
            let mut metadata = factor.clone();
            metadata
                .as_object_mut()
                .ok_or(INVALID)?
                .remove("source_text");
            if saved["revision_metadata"] != metadata {
                return Err(INVALID.into());
            }
            let mut source = serde_json::Map::new();
            for key in [
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
                source.insert(key.into(), factor[key].clone());
            }
            sources.push(Value::Object(source));
            saved_factors.insert(id.clone(), (saved, binding.clone()));
        }
        let mut instances = strategy["calculations"].as_array().ok_or(INVALID)?.clone();
        instances.extend_from_slice(target_instances);
        let core = runtime.core_artifact()?.clone();
        let operators = runtime.operator_artifact()?;
        let targets = runtime.target_artifact()?;
        let request = json!({"schema_version":1,"contract":"ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1","sources":sources,"instances":instances,"core_artifact":core,"operator_artifact":operators,"target_artifact":targets});
        let generation = runtime.manifest()["runtime_generation_fingerprint"]
            .as_str()
            .ok_or(INVALID)?
            .to_owned();
        let runtime = Arc::new(runtime);
        let mut worker = AlgorithmProcess::research_resolution(
            installation,
            &generation,
            Box::new(runtime.clone()),
        )
        .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
        let owner = worker
            .cancellation()
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
        if let Some(control)=control{control.attach(owner.clone())?;}
        let deadline = Duration::from_secs(10);
        worker
            .handshake_research(deadline)
            .map_err(|e| PreparationError::worker(e, owner.clone()))?;
        let observed = worker
            .resolve_research(request.clone(), deadline)
            .map_err(|e| PreparationError::worker(e, owner.clone()))?;
        worker
            .terminate()
            .map_err(|e| PreparationError::worker(e, owner.clone()))?;
        if owner.state()!=onlyalpha_calculation_bridge::ProcessState::Joined{return Err(PreparationError::unknown("RESEARCH_ALGORITHM_OUTCOME_UNKNOWN",Some(owner)));}
        if let Some(control)=control{control.verify_joined()?;}
        drop(worker);
        runtime.verify()?;
        installation
            .verify()
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
        crate::application::private_strategy::exact(
            &observed,
            &[
                "schema_version",
                "contract",
                "nodes",
                "source_artifacts",
                "core_artifact_sha256",
                "core_resources_fingerprint",
                "algorithm_artifact",
                "operator_artifact_sha256",
                "operator_resources_fingerprint",
                "target_artifact_sha256",
                "target_resources_fingerprint",
                "isolation",
            ],
        )
        .map_err(|_| INVALID)?;
        if observed["schema_version"] != 1
            || observed["contract"] != request["contract"]
            || observed["algorithm_artifact"] != installation.artifact_fingerprint()
            || observed["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
        {
            return Err(INVALID.into());
        }
        for name in ["core", "operator", "target"] {
            if observed[format!("{name}_artifact_sha256")]
                != request[format!("{name}_artifact")]["sha256"]
                || !observed[format!("{name}_resources_fingerprint")]
                    .as_str()
                    .is_some_and(crate::is_sha256_hex)
            {
                return Err(INVALID.into());
            }
        }
        let nodes = observed["nodes"].as_array().ok_or(INVALID)?;
        if nodes.len() != instances.len() {
            return Err(INVALID.into());
        }
        let allowed = runtime.manifest()["implementations"]
            .as_array()
            .ok_or(INVALID)?;
        let mut seen = BTreeSet::new();
        let mut decision = vec![];
        let mut targets = vec![];
        let calculation_keys = strategy["calculations"]
            .as_array()
            .ok_or(INVALID)?
            .iter()
            .map(|c| c["instance_key"].as_str().ok_or(INVALID))
            .collect::<std::result::Result<BTreeSet<_>, _>>()?;
        let target_keys = target_instances
            .iter()
            .map(|c| c["instance_key"].as_str().ok_or(INVALID))
            .collect::<std::result::Result<BTreeSet<_>, _>>()?;
        for node in nodes {
            crate::application::private_strategy::exact(
                node,
                &[
                    "instance_key",
                    "definition",
                    "definition_fingerprint",
                    "type_declaration",
                    "implementations",
                ],
            )
            .map_err(|_| INVALID)?;
            let key = node["instance_key"].as_str().ok_or(INVALID)?;
            if !seen.insert(key) {
                return Err(INVALID.into());
            }
            let mut backends = BTreeSet::new();
            for implementation in node["implementations"].as_array().ok_or(INVALID)? {
                let r = &implementation["calculation_type_reference"];
                for field in ["kind", "type_id", "semantic_version"] {
                    if r[field] != node["definition"][field] {
                        return Err(INVALID.into());
                    }
                }
                let backend = implementation["backend_kind"].as_str().ok_or(INVALID)?;
                if !backends.insert(backend)
                    || !allowed.contains(&implementation_projection(implementation)?)
                {
                    return Err(INVALID.into());
                }
            }
            let projection = json!({"instance_key":key,"definition":node["definition"],"definition_fingerprint":node["definition_fingerprint"],"type_declaration":node["type_declaration"]});
            if calculation_keys.contains(key) {
                if backends != BTreeSet::from(["RESEARCH", "TRADING"]) {
                    return Err("PRIVATE_STRATEGY_TRADING_CALCULATION_UNAVAILABLE".into());
                }
                decision.push(projection);
            } else if target_keys.contains(key) {
                if backends != BTreeSet::from(["RESEARCH"]) {
                    return Err(INVALID.into());
                }
                targets.push(projection);
            } else {
                return Err(INVALID.into());
            }
        }
        let artifacts = observed["source_artifacts"].as_array().ok_or(INVALID)?;
        if artifacts.len() != factors.len() {
            return Err(INVALID.into());
        }
        let mut source_ids = BTreeSet::new();
        for artifact in artifacts {
            crate::application::private_strategy::exact(
                artifact,
                &[
                    "source_artifact",
                    "validation_evidence",
                    "private_calculations",
                ],
            )
            .map_err(|_| INVALID)?;
            let id = artifact["source_artifact"]["factor_id"]
                .as_str()
                .ok_or(INVALID)?;
            if !source_ids.insert(id) {
                return Err(INVALID.into());
            }
            let (saved, binding) = saved_factors.get(id).ok_or(INVALID)?;
            if artifact["source_artifact"] != saved["source_artifact"] {
                return Err(INVALID.into());
            }
            let implementations = nodes
                .iter()
                .filter(|n| n["definition"]["kind"] == "FACTOR" && n["definition"]["type_id"] == id)
                .flat_map(|n| {
                    n["implementations"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .cloned()
                })
                .collect::<Vec<_>>();
            check_binding(
                &json!({"source_artifact":artifact["source_artifact"],"private_calculations":artifact["private_calculations"],"implementations":implementations}),
                saved,
                binding,
                runtime.manifest(),
            )?;
        }
        let decision = DecisionGraph::derive(&definition, &Value::Array(decision))?;
        let target = match research {Some((context,_))=>DecisionGraph::target_graph(context,&Value::Array(targets))?.to_record(),None=>{if !targets.is_empty(){return Err(INVALID.into());}Value::Null}};
        runtime.verify()?;
        let record = json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_CALCULATION_RESOLUTION_V1","composition":research.map(|(_,c)|c.record()),"runtime_generation_fingerprint":generation,"runtime_work_binding":runtime.binding(),"algorithm_resolution":observed,"decision":decision.record(),"target_graph":target});
        Ok(Self {
            runtime,
            record,
            request,
        })
    }
}
