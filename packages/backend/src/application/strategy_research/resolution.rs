//! Held-Generation mathematical definition resolution. No Research or Freeze grant.
use super::{Composition, Context, DecisionGraph};
use crate::application::factor_build::ReadyFactorBinding;
use crate::{
    application::{
        private_strategy::Definition,
        research_admission::{PreparationError, implementation_projection},
    },
    persistence::research_runtime::RuntimeInputHold,
    workers::algorithm::AlgorithmProcess,
};
use onlyalpha_calculation_bridge::{ChartInstallation, native_operators::OperatorCalculation};
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
    programs: BTreeMap<String, ReadyFactorBinding>,
}
struct ResolutionRequest<'a> {
    revision: &'a Value,
    factors: &'a BTreeMap<String, Value>,
    target_instances: &'a [Value],
    research: Option<(&'a Context, &'a Composition)>,
    control: Option<&'a crate::application::research_run_execution::Control>,
}
impl ResolvedCalculations {
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub(crate) fn into_preparation(
        self,
    ) -> (
        Arc<RuntimeInputHold>,
        Value,
        Value,
        BTreeMap<String, ReadyFactorBinding>,
    ) {
        (self.runtime, self.record, self.request, self.programs)
    }
    pub(crate) fn resolve(
        runtime: RuntimeInputHold,
        installation: &ChartInstallation,
        revision: &Value,
        context: &Context,
        factors: &BTreeMap<String, Value>,
        composition: &Composition,
        programs: BTreeMap<String, ReadyFactorBinding>,
    ) -> Result<Self> {
        let expected = Composition::derive(revision, context, runtime.manifest(), factors)?;
        if expected.record() != composition.record() {
            return Err(INVALID.into());
        }
        Self::resolve_exact(
            runtime,
            installation,
            ResolutionRequest {
                revision,
                factors,
                target_instances: context.record()["targets"].as_array().ok_or(INVALID)?,
                research: Some((context, composition)),
                control: None,
            },
            programs,
        )
    }
    pub(crate) fn resolve_manual(
        runtime: RuntimeInputHold,
        installation: &ChartInstallation,
        revision: &Value,
        factors: &BTreeMap<String, Value>,
        control: &crate::application::research_run_execution::Control,
        programs: BTreeMap<String, ReadyFactorBinding>,
    ) -> Result<Self> {
        Self::resolve_exact(
            runtime,
            installation,
            ResolutionRequest {
                revision,
                factors,
                target_instances: &[],
                research: None,
                control: Some(control),
            },
            programs,
        )
    }
    fn resolve_exact(
        mut runtime: RuntimeInputHold,
        installation: &ChartInstallation,
        request: ResolutionRequest<'_>,
        programs: BTreeMap<String, ReadyFactorBinding>,
    ) -> Result<Self> {
        let ResolutionRequest {
            revision,
            factors,
            target_instances,
            research,
            control,
        } = request;
        // Prove the held Runtime's exact native image and implementation role
        // before starting an installed numerical worker. An unavailable worker
        // cannot classify a positively observed foreign image on our behalf.
        // This retains the original complete artifact verification and creates
        // no work/fact or cached permission; preparation rechecks its live hold.
        runtime.native_predicate_implementations()?;
        let definition = Definition::from_record(&revision["definition"])?;
        let strategy = definition.to_record();
        let image = runtime.execution_binding()?["executor_artifact_sha256"]
            .as_str()
            .ok_or(INVALID)?
            .to_owned();
        let instances = strategy["calculations"].as_array().ok_or(INVALID)?;
        let (mut nodes, program_bindings) = native_instances(instances, &programs, &image)?;
        let expected_private = instances
            .iter()
            .filter(|n| n["type_reference"]["kind"] == "FACTOR")
            .count();
        if expected_private != programs.len() {
            return Err(INVALID.into());
        }
        for ready in programs.values() {
            let id = ready.metadata()["factor_id"].as_str().ok_or(INVALID)?;
            if factors.get(id) != Some(ready.metadata()) {
                return Err(INVALID.into());
            }
        }
        let generation = runtime.manifest()["runtime_generation_fingerprint"]
            .as_str()
            .ok_or(INVALID)?
            .to_owned();
        let target_request = if target_instances.is_empty() {
            Value::Null
        } else {
            json!({"schema_version":1,"contract":"ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1","sources":[],"instances":target_instances,"core_artifact":runtime.core_artifact()?,"operator_artifact":runtime.operator_artifact()?,"target_artifact":runtime.target_artifact()?})
        };
        let runtime = Arc::new(runtime);
        let target_observed = if target_instances.is_empty() {
            Value::Null
        } else {
            let mut worker = AlgorithmProcess::research_resolution(
                installation,
                &generation,
                Box::new(runtime.clone()),
            )
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
            let owner = worker
                .cancellation()
                .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
            if let Some(control) = control {
                control.attach(owner.clone())?;
            }
            let deadline = Duration::from_secs(10);
            worker
                .handshake_research(deadline)
                .map_err(|e| PreparationError::worker(e, owner.clone()))?;
            let observed = worker
                .resolve_research(target_request.clone(), deadline)
                .map_err(|e| PreparationError::worker(e, owner.clone()))?;
            worker
                .terminate()
                .map_err(|e| PreparationError::worker(e, owner.clone()))?;
            if owner.state() != onlyalpha_calculation_bridge::ProcessState::Joined {
                return Err(PreparationError::unknown(
                    "RESEARCH_ALGORITHM_OUTCOME_UNKNOWN",
                    Some(owner),
                ));
            }
            if let Some(control) = control {
                control.verify_joined()?;
            }
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
            )?;
            if observed["schema_version"] != 1
                || observed["contract"] != target_request["contract"]
                || observed["algorithm_artifact"] != installation.artifact_fingerprint()
                || observed["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
                || observed["source_artifacts"] != json!([])
            {
                return Err(INVALID.into());
            }
            for name in ["core", "operator", "target"] {
                if observed[format!("{name}_artifact_sha256")]
                    != target_request[format!("{name}_artifact")]["sha256"]
                    || !observed[format!("{name}_resources_fingerprint")]
                        .as_str()
                        .is_some_and(crate::is_sha256_hex)
                {
                    return Err(INVALID.into());
                }
            }
            let targets = observed["nodes"].as_array().ok_or(INVALID)?;
            if targets.len() != target_instances.len() {
                return Err(INVALID.into());
            }
            let allowed = runtime.manifest()["implementations"]
                .as_array()
                .ok_or(INVALID)?;
            let mut seen = BTreeSet::new();
            for node in targets {
                let key = node["instance_key"].as_str().ok_or(INVALID)?;
                if !seen.insert(key)
                    || !target_instances.iter().any(|i| i["instance_key"] == key)
                    || node["definition"]["kind"] != "TARGET"
                {
                    return Err(INVALID.into());
                }
                let implementations = node["implementations"].as_array().ok_or(INVALID)?;
                if implementations.len() != 1
                    || implementations[0]["backend_kind"] != "RESEARCH"
                    || !allowed.contains(&implementation_projection(&implementations[0])?)
                {
                    return Err(INVALID.into());
                }
                nodes.push(node.clone());
            }
            observed
        };
        runtime.verify()?;
        installation
            .verify()
            .map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
        let project = |target: bool| {
            json!(nodes.iter().filter(|n|(n["definition"]["kind"]=="TARGET")==target).map(|n|json!({"instance_key":n["instance_key"],"definition":n["definition"],"definition_fingerprint":n["definition_fingerprint"],"type_declaration":n["type_declaration"]})).collect::<Vec<_>>())
        };
        let decision = DecisionGraph::derive(&definition, &project(false))?;
        let target = match research {
            Some((context, _)) => DecisionGraph::target_graph(context, &project(true))?.to_record(),
            None => Value::Null,
        };
        // Explicit composite provenance: native signal nodes are not attributed
        // to the isolated Target child or its seccomp confinement.
        let observed = json!({"schema_version":1,"contract":"ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1","nodes":nodes,"native_execution":{"artifact":image,"program_bindings":program_bindings},"target_resolution":target_observed,"algorithm_artifact":installation.artifact_fingerprint()});
        let request = json!({"schema_version":1,"contract":"ONLYALPHA_NATIVE_SIGNAL_TARGET_RESOLUTION_V1","instances":instances.iter().chain(target_instances).cloned().collect::<Vec<_>>(),"program_bindings":program_bindings,"target_resolution_request":target_request});
        let record = json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_CALCULATION_RESOLUTION_V1","composition":research.map(|(_,c)|c.record()),"runtime_generation_fingerprint":generation,"runtime_work_binding":runtime.binding(),"algorithm_resolution":observed,"decision":decision.record(),"target_graph":target});
        Ok(Self {
            runtime,
            record,
            request,
            programs,
        })
    }
}

fn native_instances(
    instances: &[Value],
    programs: &BTreeMap<String, ReadyFactorBinding>,
    image: &str,
) -> Result<(Vec<Value>, Vec<Value>)> {
    native_program_instances(instances, image, |key, bindings| {
        let ready = programs.get(key).ok_or(INVALID)?;
        Ok((
            ready.calculation(image, bindings).map_err(|_| INVALID)?,
            json!({"instance_key":key,"revision":ready.revision_fingerprint(),"program":ready.program_fingerprint(),"parameters":ready.program().parameters().fingerprint(),"certificate":ready.certificate_fingerprint()}),
        ))
    })
}
/// Mathematical reconstruction only; this returns no READY or execution owner.
pub(crate) fn native_program_instances(
    instances: &[Value],
    image: &str,
    mut factor: impl FnMut(
        &str,
        &Value,
    ) -> Result<(onlyalpha_calculation_bridge::ProgramCalculation, Value)>,
) -> Result<(Vec<Value>, Vec<Value>)> {
    let mut pending = instances.to_vec();
    let mut definitions = BTreeMap::<String, onlyalpha_calculation::product::Definition>::new();
    let mut nodes = Vec::new();
    let mut pins = Vec::new();
    while !pending.is_empty() {
        let before = pending.len();
        let mut remaining = Vec::new();
        for instance in pending {
            let key = instance["instance_key"].as_str().ok_or(INVALID)?;
            let inputs = instance["input_bindings"].as_array().ok_or(INVALID)?;
            if inputs.iter().any(|b| {
                !b["source"].is_string()
                    && b["source"]["instance_key"]
                        .as_str()
                        .is_none_or(|p| !definitions.contains_key(p))
            }) {
                remaining.push(instance);
                continue;
            }
            let mut bindings = serde_json::Map::new();
            for input in inputs {
                let name = input["input_name"].as_str().ok_or(INVALID)?;
                let source = &input["source"];
                let reference = if source.is_string() {
                    json!({"node_fingerprint":null,"output_name":"value","source":source})
                } else {
                    json!({"node_fingerprint":definitions[source["instance_key"].as_str().ok_or(INVALID)?].fingerprint(),"output_name":source["output_name"],"source":null})
                };
                if bindings.insert(name.into(), reference).is_some() {
                    return Err(INVALID.into());
                }
            }
            let bindings = Value::Object(bindings);
            let r = &instance["type_reference"];
            let (definition, declaration, manifests) = match r["kind"].as_str() {
                Some("FACTOR") => {
                    let (c, pin) = factor(key, &bindings)?;
                    let record = c.definition().to_record();
                    if record["type_id"] != r["type_id"]
                        || record["semantic_version"] != r["semantic_version"]
                    {
                        return Err(INVALID.into());
                    }
                    pins.push(pin);
                    (
                        c.definition().clone(),
                        c.type_declaration().map_err(|_| INVALID)?.to_record(),
                        json!([
                            c.implementation_manifest("RESEARCH").map_err(|_| INVALID)?,
                            c.implementation_manifest("TRADING").map_err(|_| INVALID)?
                        ]),
                    )
                }
                Some("INDICATOR") => {
                    let params = instance["parameters"]
                        .as_object()
                        .ok_or(INVALID)?
                        .iter()
                        .map(|(k, v)| (k.clone(), v["value"].clone()))
                        .collect::<serde_json::Map<_, _>>();
                    let c = OperatorCalculation::resolve(
                        r["type_id"].as_str().ok_or(INVALID)?,
                        r["semantic_version"].as_str().ok_or(INVALID)?,
                        &Value::Object(params),
                        &bindings,
                    )
                    .map_err(|_| INVALID)?;
                    (
                        c.definition().clone(),
                        c.type_declaration().map_err(|_| INVALID)?,
                        json!([
                            c.implementation_manifest("RESEARCH", image)
                                .map_err(|_| INVALID)?,
                            c.implementation_manifest("TRADING", image)
                                .map_err(|_| INVALID)?
                        ]),
                    )
                }
                _ => return Err(INVALID.into()),
            };
            for implementation in manifests.as_array().ok_or(INVALID)? {
                implementation_projection(implementation)?;
            }
            nodes.push(json!({"instance_key":key,"definition":definition.to_record(),"definition_fingerprint":definition.fingerprint(),"type_declaration":declaration,"implementations":manifests}));
            if definitions.insert(key.into(), definition).is_some() {
                return Err(INVALID.into());
            }
        }
        if remaining.len() == before {
            return Err(INVALID.into());
        }
        pending = remaining;
    }
    nodes.sort_by_key(|n| n["instance_key"].as_str().unwrap_or_default().to_owned());
    pins.sort_by_key(|n| n["instance_key"].as_str().unwrap_or_default().to_owned());
    Ok((nodes, pins))
}
