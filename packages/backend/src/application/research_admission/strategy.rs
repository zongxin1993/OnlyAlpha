//! Strategy preparation consumes the actual Composer resolution and Runtime hold.
//! Re-anchored values describe executable inputs; they grant no Run or Freeze.
use super::{INVALID, PreparationError, PreparedInputs, Result, implementation_projection};
use crate::{
    application::{
        private_strategy::Definition,
        research_dataset::MaterializedDataset,
        strategy_research::{Context, DecisionGraph, ResolvedCalculations, RunSpecification, Specification},
    },
    persistence::{research_dataset::Store, strategy_research::Composer},
};
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::{OnlyTimestamp, OnlyUtcDateTime};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};

impl PreparedInputs {
    /// Consume an actual installed resolution, retaining its original work and
    /// lifecycle hold. Neither parsed values nor a new Runtime selection suffice.
    pub async fn prepare_strategy(
        composer: &mut Composer<'_>,
        resolved: ResolvedCalculations,
        context: &Context,
        installation: &ChartInstallation,
        datasets: &Store,
        materialized: &MaterializedDataset,
    ) -> std::result::Result<(Self, RunSpecification), PreparationError> {
        let (mut runtime, resolution, request) = resolved.into_preparation();
        if resolution["composition"]["research_context_fingerprint"] != context.fingerprint()?
            || resolution["runtime_generation_fingerprint"] != runtime.manifest()["runtime_generation_fingerprint"]
            || resolution["runtime_work_binding"] != *runtime.binding()
            || resolution["algorithm_resolution"]["algorithm_artifact"] != installation.artifact_fingerprint()
        {
            return Err(INVALID.into());
        }
        installation.verify().map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
        let revision = composer.reanchor(&resolution["composition"], context, &runtime).await?;
        let definition = Definition::from_record(&revision["definition"])?;
        let strategy = definition.to_record();
        let observed = &resolution["algorithm_resolution"];
        let nodes = observed["nodes"].as_array().ok_or(INVALID)?;
        let project = |declarations: &Value| -> Result<Value> {
            let mut rows = Vec::new();
            for declaration in declarations.as_array().ok_or(INVALID)? {
                let mut matches = nodes.iter().filter(|n| n["instance_key"] == declaration["instance_key"]);
                let node = matches.next().ok_or(INVALID)?;
                if matches.next().is_some() {
                    return Err(INVALID);
                }
                rows.push(json!({"instance_key":node["instance_key"],"definition":node["definition"],
                    "definition_fingerprint":node["definition_fingerprint"],"type_declaration":node["type_declaration"]}));
            }
            Ok(json!(rows))
        };
        let decision = DecisionGraph::derive(&definition, &project(&strategy["calculations"])?)?;
        let targets = DecisionGraph::target_graph(context, &project(&context.record()["targets"])?)?;
        if decision.record() != resolution["decision"] || targets.to_record() != resolution["target_graph"] {
            return Err(INVALID.into());
        }
        // Re-read the retained source occurrence and every immutable Dataset byte.
        // A prior MaterializedDataset value is not the current physical proof.
        let id = materialized.lineage()["materialization_id"].as_str().ok_or(INVALID)?;
        let retained = MaterializedDataset::load(datasets, id)?;
        if retained.lineage() != materialized.lineage()
            || retained.verified().manifest() != materialized.verified().manifest()
        {
            return Err(INVALID.into());
        }
        let dataset = retained.verified().dataset();
        let dataset_definition = dataset.definition();
        let provenance = retained.verified().manifest()["provenance"].as_array()
            .filter(|p| p.len() == 1).ok_or(INVALID)?;
        if dataset_definition["instruments"] != strategy["universe"]["instruments"]
            || dataset_definition["bar_semantic"] != strategy["market_input"]["bar_semantic"]
            || provenance[0]["source_metadata"]["construction_recipe"]
                != strategy["market_input"]["construction_requirement"]["recipe"]
        {
            return Err(INVALID.into());
        }
        let bar_ns = dataset_definition["bar_semantic"]["formation"]["stride_minutes"]
            .as_u64().and_then(|n| n.checked_mul(60_000_000_000)).ok_or(INVALID)?;
        let mut window = decision.input_window(context, bar_ns)?;
        window.as_object_mut().ok_or(INVALID)?.remove("research_context_fingerprint");
        let start = ns(&dataset_definition["time_range"]["start"])?;
        let end = ns(&dataset_definition["time_range"]["end"])?;
        if window["dataset_event_start_ns"] != start.to_string()
            || window["dataset_event_end_ns"] != end.to_string()
            || window["dataset_observation_capacity"].as_u64() != Some(dataset.rows().len() as u64)
        {
            return Err(INVALID.into());
        }
        for (index, row) in dataset.rows().iter().enumerate() {
            let expected = (index as u64).checked_mul(bar_ns).and_then(|n| start.checked_add(n)).ok_or(INVALID)?;
            if row["ts_event_ns"].as_u64() != Some(expected)
                || window["dataset_columns"].as_array().ok_or(INVALID)?.iter()
                    .any(|c| c.as_str().is_none_or(|c| row.get(c).is_none()))
            {
                return Err(INVALID.into());
            }
        }
        // Only this original opaque resolution retains the hold. Its resolver
        // positively joined the installed child before handing it to preparation.
        let native = Arc::get_mut(&mut runtime).ok_or(INVALID)?.native_predicate_implementations()?;
        let allowed = runtime.manifest()["implementations"].as_array().ok_or(INVALID)?;
        let mut native_used = BTreeMap::new();
        let mut bindings = BTreeMap::new();
        for node in decision.graph().ordered_nodes() {
            let d = node.to_record();
            let manifests = if d["kind"] == "PREDICATE" {
                select(&native, &d, &["RESEARCH", "TRADING"], allowed)?
            } else {
                select(&observed_node(nodes, &d, &node.fingerprint())?["implementations"], &d, &["RESEARCH", "TRADING"], allowed)?
            };
            if d["kind"] == "PREDICATE" {
                for manifest in &manifests {
                    let pin = manifest["implementation_fingerprint"].as_str().ok_or(INVALID)?;
                    if native_used.insert(pin.to_owned(), manifest.clone()).is_some_and(|old| old != *manifest) {
                        return Err(INVALID.into());
                    }
                }
            }
            bindings.insert(node.fingerprint(), json!({"node_fingerprint":node.fingerprint(),
                "research_implementation_fingerprint":manifests[0]["implementation_fingerprint"],
                "trading_implementation_fingerprint":manifests[1]["implementation_fingerprint"]}));
        }
        // Targets are independently observed RESEARCH calculations. They cannot
        // acquire a TRADING implementation by being included in a Strategy study.
        for node in targets.ordered_nodes() {
            let d = node.to_record();
            let actual = &observed_node(nodes, &d, &node.fingerprint())?["implementations"];
            if actual.as_array().map(Vec::len) != Some(1) {
                return Err(INVALID.into());
            }
            select(actual, &d, &["RESEARCH"], allowed)?;
        }
        let research_definition = context.definition(&definition)?;
        let science = Specification::derive(&research_definition, &decision, &targets, dataset.snapshot_fingerprint())?;
        let execution = runtime.execution_binding()?;
        let specification = RunSpecification::from_record(&json!({"schema_version":5,"kind":"PRIVATE_STRATEGY_RESEARCH",
            "scientific_specification":science.record(),"decision":decision.record(),"target_graph":targets.to_record(),
            "input_window":window,"runtime_generation_fingerprint":runtime.manifest()["runtime_generation_fingerprint"],
            "catalog_generation_fingerprint":runtime.manifest()["catalog_generation_fingerprint"],
            "algorithm_artifact_fingerprint":installation.artifact_fingerprint(),"execution_binding":execution,
            "implementation_bindings":bindings.into_values().collect::<Vec<_>>()}))?;
        installation.verify().map_err(|_| "RESEARCH_ALGORITHM_UNAVAILABLE")?;
        runtime.verify()?;
        let record = json!({"schema_version":1,"contract":"ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1",
            "composition":resolution["composition"],"runtime_generation_fingerprint":runtime.manifest()["runtime_generation_fingerprint"],
            "runtime_work_binding":runtime.binding(),"execution_binding":execution,"input_window":window,
            "dataset_snapshot_fingerprint":dataset.snapshot_fingerprint(),"dataset_materialization":retained.lineage(),
            "dataset_construction_fingerprint":dataset.construction_fingerprint(),"run_specification_fingerprint":specification.fingerprint()?,
            "algorithm_resolution_request":request,"algorithm_resolution":observed,
            "native_implementations":native_used.into_values().collect::<Vec<_>>()});
        Ok((Self { runtime, record }, specification))
    }
}
fn ns(value: &Value) -> Result<u64> {
    let time = value.as_str().ok_or(INVALID)?.parse::<OnlyUtcDateTime>().map_err(|_| INVALID)?;
    OnlyTimestamp::from_datetime(time).unix_nanos().to_string().parse().map_err(|_| INVALID)
}
pub(crate) fn observed_node<'a>(nodes: &'a [Value], definition: &Value, fingerprint: &str) -> Result<&'a Value> {
    let mut found = nodes.iter().filter(|n| n["definition_fingerprint"] == fingerprint && n["definition"] == *definition);
    let actual = found.next().ok_or(INVALID)?;
    if found.next().is_some() {
        return Err(INVALID);
    }
    Ok(actual)
}
pub(crate) fn select(manifests: &Value, definition: &Value, backends: &[&str], allowed: &[Value]) -> Result<Vec<Value>> {
    let mut selected = Vec::new();
    for backend in backends {
        let mut found = manifests.as_array().ok_or(INVALID)?.iter().filter(|m| {
            m["backend_kind"] == *backend && ["kind", "type_id", "semantic_version"].iter()
                .all(|key| m["calculation_type_reference"][*key] == definition[*key])
        });
        let manifest = found.next().ok_or(INVALID)?;
        if found.next().is_some() || !allowed.contains(&implementation_projection(manifest)?) {
            return Err(INVALID);
        }
        selected.push(manifest.clone());
    }
    Ok(selected)
}

/// Restore only the original verified Strategy authorization. The owning reader
/// re-anchors retained source revisions before invoking actual installed math.
pub async fn restore_strategy(
    composer:&mut Composer<'_>, run:&crate::application::research_run::VerifiedRun,
    runtime:crate::persistence::research_runtime::RuntimeInputHold,
    installation:&ChartInstallation, datasets:&Store,
) -> std::result::Result<PreparedInputs,PreparationError> {
    let spec=run.strategy_specification()?;
    let materialization=run.prepared_inputs["dataset_materialization"]["materialization_id"].as_str().ok_or(INVALID)?;
    let materialized=MaterializedDataset::load(datasets,materialization)?;
    if materialized.lineage()!=&run.prepared_inputs["dataset_materialization"] {return Err(INVALID.into());}
    let (resolved,context)=composer.resolve_retained(&run.prepared_inputs["composition"],runtime,installation).await?;
    let (restored,actual)=PreparedInputs::prepare_strategy(composer,resolved,&context,installation,datasets,&materialized).await?;
    if restored.record()!=&run.prepared_inputs||actual.record()!=spec.record() {return Err(INVALID.into());}
    Ok(restored)
}
