//! Actual Strategy publication and owning reads in the original Research owners.
#[path = "columnar.rs"]
mod columnar;
#[path = "equivalence.rs"]
pub(crate) mod equivalence;
#[path = "physical.rs"]
pub(crate) mod physical;
use super::*;
use crate::{
    application::frozen_strategy::FrozenStore,
    application::{
        research_admission::implementation_projection, research_dataset::MaterializedDataset,
        research_run_execution::ExecutedStrategy, strategy_research::RunSpecification,
    },
    persistence::research_runtime::RuntimeEvidenceHold,
    security::immutable_json::{put_at, put_bundle_at},
};
use onlyalpha_calculation::product::Graph;
use onlyalpha_domain::time::OnlyUtcDateTime;
pub(crate) use physical::ReadCut;
use physical::{Witness, byte_sha, data_file, document, exact_files, optional_directory};
use std::os::fd::AsFd;
const STRATEGY_PROFILE: &str = "research-strategy-v1";
const REPORT: &str = "ONLYALPHA_STRATEGY_RESEARCH_REPORT_V1";
// A report includes the complete joined observation. Keep its wire cap separate
// from bounded traversal, as in the existing manual Strategy Validation owner.
const REPORT_JSON_WORK: usize = 64 * 1024 * 1024;
const BUDGET: usize = 512 * 1024 * 1024;
// Aggregate inventory work is distinct from each immutable document parse cap.
const FROZEN_HISTORY_WORK: usize = 64 * 1024 * 1024;
fn rows(v: &Value) -> Result<&Vec<Value>> {
    v.as_array().ok_or(INVALID)
}
fn pin_value(v: &Value) -> Result<&str> {
    v.as_str()
        .filter(|s| crate::is_sha256_hex(s))
        .ok_or(INVALID)
}
fn audit(at: OnlyUtcDateTime) -> String {
    format!("{}+00:00", at.to_string().trim_end_matches('Z'))
}
fn canonical_bytes(v: &Value) -> Result<Vec<u8>> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), LIMIT)
        .map(String::into_bytes)
        .map_err(|_| INVALID)
}
fn report_bytes(value: &Value) -> Result<Vec<u8>> {
    let raw = value.to_string();
    if raw.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    let bytes = onlyalpha_metadata_json::canonical_json(&raw, REPORT_JSON_WORK)
        .map_err(|error| match error {
            onlyalpha_metadata_json::Error::Invalid => INVALID,
            onlyalpha_metadata_json::Error::Unavailable => UNAVAILABLE,
        })?
        .into_bytes();
    if bytes.len() > LIMIT {
        return Err(UNAVAILABLE);
    }
    Ok(bytes)
}
fn report_fingerprint(value: &Value) -> Result<String> {
    Ok(byte_sha(&report_bytes(value)?))
}
fn signed_report(mut value: Value) -> Result<Value> {
    let identity = report_fingerprint(&value)?;
    value
        .as_object_mut()
        .ok_or(INVALID)?
        .insert("artifact_content_fingerprint".into(), json!(identity));
    report_bytes(&value)?;
    Ok(value)
}
fn verify_report_signature(value: &Value) -> Result<()> {
    let expected = pin(value, "artifact_content_fingerprint")?;
    let mut body = value.clone();
    body.as_object_mut()
        .ok_or(INVALID)?
        .remove("artifact_content_fingerprint");
    if report_fingerprint(&body)? != expected {
        return Err(INVALID);
    }
    Ok(())
}
fn report_document(directory: &Directory, witnesses: &mut Vec<Witness>) -> Result<Value> {
    let (raw, file) = physical::read_report_file(directory, "manifest.json")?;
    let value: Value = serde_json::from_slice(&raw).map_err(|_| INVALID)?;
    if report_bytes(&value)? != raw {
        return Err(INVALID);
    }
    witnesses.push(physical::witness(directory, "manifest.json", &raw, &file)?);
    Ok(value)
}
fn signed_domain(mut value: Value, key: &str, domain: &str) -> Result<Value> {
    let mut identity = value.clone();
    identity["domain"] = json!(domain);
    value[key] = json!(hash(&identity)?);
    Ok(value)
}
struct CalculationBundle {
    logical: String,
    manifest: Value,
    files: BTreeMap<String, Vec<u8>>,
    rows: Vec<Vec<Value>>,
}
struct StatisticsBundle {
    logical: String,
    manifest: Value,
    files: BTreeMap<String, Vec<u8>>,
    rows: Vec<Value>,
}
struct Science {
    calculations: Vec<CalculationBundle>,
    statistics: Vec<StatisticsBundle>,
    executions: Vec<Value>,
    equivalence: Vec<Value>,
    result: Value,
    source: onlyalpha_strategy::SourceRevision,
    admission: String,
}
fn implementation<'a>(
    prepared: &'a Value,
    node: &Value,
    id: &str,
    backend: &str,
) -> Result<&'a Value> {
    let manifests = if node["kind"] == "PREDICATE" {
        rows(&prepared["native_implementations"])?
    } else {
        let mut found = rows(&prepared["algorithm_resolution"]["nodes"])?
            .iter()
            .filter(|n| n["definition_fingerprint"] == id && n["definition"] == *node);
        let actual = found.next().ok_or(INVALID)?;
        if found.next().is_some() {
            return Err(INVALID);
        }
        rows(&actual["implementations"])?
    };
    let mut found = manifests.iter().filter(|m| {
        m["backend_kind"] == backend
            && ["kind", "type_id", "semantic_version"]
                .iter()
                .all(|k| m["calculation_type_reference"][*k] == node[*k])
    });
    let value = found.next().ok_or(INVALID)?;
    if found.next().is_some() {
        return Err(INVALID);
    }
    implementation_projection(value)?;
    Ok(value)
}
fn output_index<'a>(
    values: &'a Value,
    graph: &Graph,
    prepared: &Value,
    backend: &str,
    count: usize,
) -> Result<BTreeMap<String, &'a Value>> {
    let mut index = BTreeMap::new();
    for value in rows(values)? {
        exact(
            value,
            &["node_fingerprint", "implementation_fingerprint", "values"],
        )?;
        let id = text(value, "node_fingerprint")?;
        if index.insert(id.to_owned(), value).is_some() {
            return Err(INVALID);
        }
    }
    if index.len() != graph.ordered_nodes().count() {
        return Err(INVALID);
    }
    for node in graph.ordered_nodes() {
        let id = node.fingerprint();
        let record = node.to_record();
        let value = index.get(&id).ok_or(INVALID)?;
        if value["implementation_fingerprint"]
            != implementation(prepared, &record, &id, backend)?["implementation_fingerprint"]
        {
            return Err(INVALID);
        }
        let columns = value["values"].as_object().ok_or(INVALID)?;
        if columns.len() != rows(&record["outputs"])?.len()
            || columns
                .values()
                .any(|v| v.as_array().is_none_or(|v| v.len() != count))
        {
            return Err(INVALID);
        }
    }
    Ok(index)
}
fn validate_case(
    spec: &RunSpecification,
    prepared: &Value,
    value: &Value,
    axis: &[Value],
) -> Result<()> {
    let graph = spec.calculation_graph("decision")?;
    let r = output_index(
        &value["research_outputs"],
        graph,
        prepared,
        "RESEARCH",
        axis.len(),
    )?;
    let t = output_index(
        &value["streaming_outputs"],
        graph,
        prepared,
        "TRADING",
        axis.len(),
    )?;
    let _targets = output_index(
        &value["target_outputs"],
        spec.target_graph(),
        prepared,
        "RESEARCH",
        axis.len(),
    )?;
    if value["axis"] != json!(axis) || r.keys().collect::<Vec<_>>() != t.keys().collect::<Vec<_>>()
    {
        return Err(INVALID);
    }
    for (id, output) in &r {
        if output["values"] != t[id]["values"] {
            return Err(INVALID);
        }
        let node = graph
            .ordered_nodes()
            .find(|n| n.fingerprint() == *id)
            .ok_or(INVALID)?
            .to_record();
        columnar::calculation_rows(axis, &output["values"], &node["outputs"])?;
    }
    let decisions = rows(&value["decisions"])?;
    if decisions.len() != axis.len() {
        return Err(INVALID);
    }
    for (index, decision) in decisions.iter().enumerate() {
        exact(decision, &["at_ns", "status", "decision"])?;
        if decision["at_ns"] != axis[index]
            || !matches!(decision["status"].as_str(), Some("READY" | "BLOCKED"))
        {
            return Err(INVALID);
        }
        if (decision["status"] == "READY") == decision["decision"].is_null() {
            return Err(INVALID);
        }
        if !decision["decision"].is_null() {
            exact(&decision["decision"], &["eligibility", "entry", "exit"])?;
            for role in ["eligibility", "entry", "exit"] {
                let reference = &spec.record()["decision"]["signal_semantics"][role];
                let node = reference["node_fingerprint"].as_str().ok_or(INVALID)?;
                let output = reference["output_name"].as_str().ok_or(INVALID)?;
                let value = &r.get(node).ok_or(INVALID)?["values"][output][index];
                let expected = if value["type"] == "NULL" {
                    json!(false)
                } else {
                    json!(value["value"].as_bool().ok_or(INVALID)?)
                };
                if decision["decision"][role] != expected {
                    return Err(INVALID);
                }
            }
        }
    }
    Ok(())
}
fn science(
    spec: &RunSpecification,
    prepared: &Value,
    observation: &Value,
    dataset: &super::super::research_dataset::VerifiedDataset,
    at: OnlyUtcDateTime,
) -> Result<Science> {
    exact(
        observation,
        &[
            "schema_version",
            "contract",
            "run_specification_fingerprint",
            "dataset_snapshot_fingerprint",
            "input_window",
            "observation_count",
            "axis",
            "research_outputs",
            "streaming_outputs",
            "target_outputs",
            "decisions",
            "restoration",
            "producer",
            "graph_cases",
            "node_profiles",
            "statistics",
        ],
    )?;
    let axis = dataset
        .dataset()
        .rows()
        .iter()
        .map(|r| r["ts_event_ns"].clone())
        .collect::<Vec<_>>();
    if axis.is_empty()
        || axis.len() > 8192
        || dataset.dataset().definition()["instruments"]
            .as_array()
            .map(Vec::len)
            != Some(1)
        || observation["schema_version"] != 1
        || observation["contract"] != "ONLYALPHA_STRATEGY_EVALUATION_OBSERVATION_V1"
        || observation["run_specification_fingerprint"] != spec.fingerprint()?
        || observation["dataset_snapshot_fingerprint"] != dataset.dataset().snapshot_fingerprint()
        || observation["input_window"] != prepared["input_window"]
    {
        return Err(INVALID);
    }
    let ns = |key: &str| -> Result<u64> {
        prepared["input_window"][key]
            .as_str()
            .ok_or(INVALID)?
            .parse()
            .map_err(|_| INVALID)
    };
    let observation_start = ns("observation_start_ns")?;
    let observation_end = ns("observation_end_ns")?;
    let count = axis
        .iter()
        .filter(|at| {
            at.as_u64()
                .is_some_and(|t| t >= observation_start && t < observation_end)
        })
        .count();
    if observation["observation_count"] != count {
        return Err(INVALID);
    }
    validate_case(spec, prepared, observation, &axis)?;
    exact(
        &observation["restoration"],
        &[
            "processed_rows",
            "before_checkpoint_fingerprint",
            "restored_checkpoint_fingerprint",
        ],
    )?;
    if observation["restoration"]["processed_rows"] != axis.len() / 2
        || pin_value(&observation["restoration"]["before_checkpoint_fingerprint"])?
            != pin_value(&observation["restoration"]["restored_checkpoint_fingerprint"])?
    {
        return Err(INVALID);
    }
    let names = [
        "FLAT_SEQUENCE",
        "NEGATIVE_SLOPE_SEQUENCE",
        "POSITIVE_SLOPE_SEQUENCE",
        "QUANTIZATION_BOUNDARY",
        "WARMUP_AND_STEADY_STATE",
        "ZERO_BOUNDARY",
    ];
    if rows(&observation["graph_cases"])?.len() != names.len() {
        return Err(INVALID);
    }
    for (case, name) in rows(&observation["graph_cases"])?.iter().zip(names) {
        if case["case_id"] != name {
            return Err(INVALID);
        }
        let input = rows(&case["rows"])?;
        let case_axis = input.iter().map(|r| r["at_ns"].clone()).collect::<Vec<_>>();
        if input.len()
            < prepared["input_window"]["warmup_bars"]
                .as_u64()
                .ok_or(INVALID)? as usize
                + 2
            || input.len() > 8192
        {
            return Err(INVALID);
        }
        validate_case(spec, prepared, case, &case_axis)?;
    }
    let instrument = dataset.dataset().definition()["instruments"][0]
        .as_str()
        .ok_or(INVALID)?;
    let mut calculations = Vec::new();
    let mut executions = Vec::new();
    let mut total = 0usize;
    let decision_outputs = output_index(
        &observation["research_outputs"],
        spec.calculation_graph("decision")?,
        prepared,
        "RESEARCH",
        axis.len(),
    )?;
    let target_outputs = output_index(
        &observation["target_outputs"],
        spec.target_graph(),
        prepared,
        "RESEARCH",
        axis.len(),
    )?;
    for (name, graph) in spec.calculation_graphs() {
        let logical = spec.calculation_identity(name)?;
        let observed = if name == "decision" {
            &decision_outputs
        } else {
            &target_outputs
        };
        let mut partitions = Vec::new();
        let mut output_rows = Vec::new();
        let mut files = BTreeMap::new();
        let mut bindings = Vec::new();
        let mut nodes = graph.ordered_nodes().collect::<Vec<_>>();
        nodes.sort_by_key(|n| n.fingerprint());
        for (index, node) in nodes.iter().enumerate() {
            let id = node.fingerprint();
            let record = node.to_record();
            let output = &observed.get(&id).ok_or(INVALID)?["values"];
            let (schema, rows, raw) =
                columnar::write_calculation(&axis, output, &record["outputs"])?;
            total = total
                .checked_add(raw.len())
                .filter(|n| *n <= BUDGET)
                .ok_or(UNAVAILABLE)?;
            let relative = format!("data/p-{index:06}.parquet");
            partitions.push(json!({"node_fingerprint":id,"instrument_id":instrument,"row_count":rows.len(),"arrow_schema":schema,
                "semantic_fingerprint":columnar::partition(&id,instrument,&schema,&rows)?,"relative_path":relative,"byte_sha256":byte_sha(&raw)}));
            output_rows.push(rows);
            files.insert(relative, raw);
            bindings.push(json!({"node_fingerprint":id,"research_implementation_fingerprint":implementation(prepared,&record,&id,"RESEARCH")?["implementation_fingerprint"]}));
        }
        let content = columnar::calculation_content(&partitions)?;
        let result = hash(
            &json!({"schema_version":1,"calculation_fingerprint":logical,"result_content_fingerprint":content}),
        )?;
        let manifest = json!({"schema_version":1,"calculation_fingerprint":logical,"dataset_snapshot_fingerprint":dataset.dataset().snapshot_fingerprint(),
            "calculation_graph_fingerprint":graph.fingerprint(),"calculation_graph":graph.to_record(),"result_content_fingerprint":content,
            "calculation_result_fingerprint":result,"partition_count":partitions.len(),"total_row_count":axis.len()*partitions.len(),"partitions":partitions,"created_at":audit(at)});
        files.insert("manifest.json".into(), canonical_bytes(&manifest)?);
        let execution = signed_domain(
            json!({"schema_version":1,"calculation_fingerprint":logical,"dataset_snapshot_fingerprint":dataset.dataset().snapshot_fingerprint(),
            "calculation_graph_fingerprint":graph.fingerprint(),"calculation_result_fingerprint":result,"result_content_fingerprint":content,
            "research_implementation_bindings":bindings,"execution_contract_version":"RESEARCH_CALCULATION_EXECUTION_V1"}),
            "evidence_fingerprint",
            "onlyalpha.research.calculation-execution-evidence",
        )?;
        executions.push(execution);
        calculations.push(CalculationBundle {
            logical,
            manifest,
            files,
            rows: output_rows,
        });
    }
    calculations.sort_by(|a, b| a.logical.cmp(&b.logical));
    executions.sort_by_key(|v| v["evidence_fingerprint"].as_str().unwrap_or("").to_owned());
    let find_calc = |id: &Value| -> Result<&Value> {
        let id = pin_value(id)?;
        calculations
            .iter()
            .find(|c| c.logical == id)
            .map(|c| &c.manifest)
            .ok_or(INVALID)
    };
    let observed = rows(&observation["statistics"])?;
    let plans = spec.statistics_intents()?;
    if observed.len() != plans.len() {
        return Err(INVALID);
    }
    let mut statistics = Vec::new();
    for plan in plans {
        let logical = hash(&plan)?;
        let mut matches = observed
            .iter()
            .filter(|o| o["statistics_fingerprint"] == logical);
        let actual = matches.next().ok_or(INVALID)?;
        if matches.next().is_some() || actual["plan"] != plan {
            return Err(INVALID);
        }
        exact(actual, &["statistics_fingerprint", "plan", "rows"])?;
        if plan["definition"]["minimum_observations"]
            .as_u64()
            .is_none_or(|n| n < 2)
        {
            return Err(INVALID);
        }
        let lookup = |role: &str, key: &str| -> Result<&Value> {
            let id = plan[role]["node_fingerprint"].as_str().ok_or(INVALID)?;
            rows(&observation[key])?
                .iter()
                .find(|o| o["node_fingerprint"] == id)
                .map(|o| &o["values"][plan[role]["output_name"].as_str().unwrap_or("")])
                .ok_or(INVALID)
        };
        let x = rows(lookup("feature", "research_outputs")?)?;
        let y = rows(lookup("target", "target_outputs")?)?;
        if x.len() != axis.len() || y.len() != axis.len() {
            return Err(INVALID);
        }
        let values=axis.iter().enumerate().map(|(i,t)|json!({"ts_event_ns":t,"statistic_value":null,"sample_count":u8::from(x[i]["type"]!="NULL"&&y[i]["type"]!="NULL"),"status":"INSUFFICIENT_OBSERVATIONS"})).collect::<Vec<_>>();
        if actual["rows"] != json!(values) {
            return Err(INVALID);
        }
        let content = hash(&json!({"schema_version":1,"rows":values}))?;
        let result = hash(
            &json!({"schema_version":1,"statistics_fingerprint":logical,"result_content_fingerprint":content}),
        )?;
        let (schema, raw) = columnar::write_statistics(&values)?;
        total = total
            .checked_add(raw.len())
            .filter(|n| *n <= BUDGET)
            .ok_or(UNAVAILABLE)?;
        let manifest = json!({"schema_version":1,"statistics_fingerprint":logical,"plan":plan,
            "feature_calculation_result_fingerprint":find_calc(&plan["feature"]["calculation_fingerprint"])?["calculation_result_fingerprint"],
            "target_calculation_result_fingerprint":find_calc(&plan["target"]["calculation_fingerprint"])?["calculation_result_fingerprint"],
            "dataset_snapshot_fingerprint":dataset.dataset().snapshot_fingerprint(),"result_content_fingerprint":content,"statistics_result_fingerprint":result,
            "row_count":values.len(),"arrow_schema":schema,"data_byte_sha256":byte_sha(&raw),"created_at":audit(at)});
        let files = BTreeMap::from([
            ("manifest.json".into(), canonical_bytes(&manifest)?),
            ("data.parquet".into(), raw),
        ]);
        statistics.push(StatisticsBundle {
            logical,
            manifest,
            files,
            rows: values,
        });
    }
    statistics.sort_by(|a, b| a.logical.cmp(&b.logical));
    let stats=statistics.iter().map(|s|json!({"statistics_fingerprint":s.logical,"statistics_result_fingerprint":s.manifest["statistics_result_fingerprint"]})).collect::<Vec<_>>();
    let calcs=calculations.iter().map(|c|json!({"calculation_fingerprint":c.logical,"calculation_result_fingerprint":c.manifest["calculation_result_fingerprint"]})).collect::<Vec<_>>();
    let content =
        hash(&json!({"schema_version":2,"statistics_results":stats,"calculation_results":calcs}))?;
    let plan = spec.result_plan()?;
    let plan_fp = hash(&plan)?;
    let result_fp = hash(
        &json!({"schema_version":2,"research_result_plan_fingerprint":plan_fp,"research_result_content_fingerprint":content}),
    )?;
    let result = json!({"schema_version":2,"plan":plan,"research_result_plan_fingerprint":plan_fp,"dataset_snapshot_fingerprint":dataset.dataset().snapshot_fingerprint(),
        "statistics_results":stats,"research_result_content_fingerprint":content,"research_result_fingerprint":result_fp,"created_at":audit(at),"calculation_results":calcs});
    let equivalence = equivalence::derive(
        spec.calculation_graph("decision")?,
        &spec.record()["implementation_bindings"],
        observation,
    )?;
    let ids = equivalence
        .iter()
        .map(|v| v["evidence_fingerprint"].clone())
        .collect::<Vec<_>>();
    let admission = hash(
        &json!({"domain":"onlyalpha.strategy.trading-admission-evidence","schema_version":1,"evidence_fingerprints":ids}),
    )?;
    let mut source = json!({"schema_version":1,"universe":{"kind":"SINGLE_INSTRUMENT","instruments":dataset.dataset().definition()["instruments"]},
        "market_input_contract":{"schema_version":2,"data_kind":"BAR","bar_semantic":dataset.dataset().definition()["bar_semantic"],
            "construction_requirement":{"schema_version":1,"kind":"EXACT_RECIPE","policy":null,"recipe":dataset.manifest()["provenance"][0]["source_metadata"]["construction_recipe"]},"observation_admission":"FINAL_ONLY"},
        "decision_graph_fingerprint":spec.calculation_graph("decision")?.fingerprint(),"implementation_bindings":spec.record()["implementation_bindings"],"signal_semantics":spec.record()["decision"]["signal_semantics"]});
    let mut identity = source.clone();
    identity["domain"] = json!("onlyalpha.strategy.revision");
    source["strategy_fingerprint"] = json!(hash(&identity)?);
    source["decision_graph"] = spec.calculation_graph("decision")?.to_record();
    let source = onlyalpha_strategy::SourceRevision::from_json(&source.to_string(), LIMIT)
        .map_err(|_| INVALID)?;
    Ok(Science {
        calculations,
        statistics,
        executions,
        equivalence,
        result,
        source,
        admission,
    })
}
fn without_audit(value: &Value, key: Option<&str>) -> Result<Value> {
    let mut value = value.clone();
    let object = value.as_object_mut().ok_or(INVALID)?;
    object.remove("created_at");
    if let Some(key) = key {
        object.remove(key);
    }
    Ok(value)
}
fn calculation_semantic(value: &Value) -> Result<Value> {
    let mut value = without_audit(value, None)?;
    let graph = Graph::from_record(&value["calculation_graph"], LIMIT).map_err(|_| INVALID)?;
    if value["calculation_graph_fingerprint"] != graph.fingerprint() {
        return Err(INVALID);
    }
    // Graph1 identity excludes presentation aliases. Validate the complete
    // graph first, then compare its already-declared semantic identity while
    // retaining the original physical manifest and every partition witness.
    value
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("calculation_graph");
    for partition in value["partitions"].as_array_mut().ok_or(INVALID)? {
        partition
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("byte_sha256");
    }
    Ok(value)
}
fn verify_calculation(
    owner: &Directory,
    candidate: &CalculationBundle,
    witnesses: &mut Vec<Witness>,
) -> Result<Value> {
    let logical = &candidate.logical;
    let directory =
        optional_directory(owner, &["sha256", &logical[..2], logical])?.ok_or(INVALID)?;
    exact_files(&directory, &["manifest.json", "data"])?;
    let manifest = document(&directory, "manifest.json", witnesses)?;
    if calculation_semantic(&manifest)? != calculation_semantic(&candidate.manifest)?
        || manifest["created_at"]
            .as_str()
            .is_none_or(|s| s.parse::<OnlyUtcDateTime>().is_err())
    {
        return Err(INVALID);
    }
    let partitions = rows(&manifest["partitions"])?;
    let mut names = Vec::new();
    for ((partition, expected), index) in partitions.iter().zip(&candidate.rows).zip(0usize..) {
        let relative = format!("data/p-{index:06}.parquet");
        if partition["relative_path"] != relative {
            return Err(INVALID);
        }
        let (raw, file) = data_file(&directory, &relative, witnesses)?;
        if partition["byte_sha256"] != byte_sha(&raw) {
            return Err(INVALID);
        }
        let actual = columnar::read(file, &partition["arrow_schema"], 8192)?;
        if actual != *expected
            || partition["semantic_fingerprint"]
                != columnar::partition(
                    text(partition, "node_fingerprint")?,
                    text(partition, "instrument_id")?,
                    &partition["arrow_schema"],
                    &actual,
                )?
        {
            return Err(INVALID);
        }
        names.push(format!("p-{index:06}.parquet"));
    }
    let data = optional_directory(&directory, &["data"])?.ok_or(INVALID)?;
    exact_files(&data, &names.iter().map(String::as_str).collect::<Vec<_>>())?;
    Ok(manifest)
}
fn verify_statistics(
    owner: &Directory,
    candidate: &StatisticsBundle,
    witnesses: &mut Vec<Witness>,
) -> Result<Value> {
    let logical = &candidate.logical;
    let directory =
        optional_directory(owner, &["sha256", &logical[..2], logical])?.ok_or(INVALID)?;
    exact_files(&directory, &["manifest.json", "data.parquet"])?;
    let manifest = document(&directory, "manifest.json", witnesses)?;
    let mut actual = without_audit(&manifest, None)?;
    actual
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("data_byte_sha256");
    let mut expected = without_audit(&candidate.manifest, None)?;
    expected
        .as_object_mut()
        .ok_or(INVALID)?
        .remove("data_byte_sha256");
    if actual != expected
        || manifest["created_at"]
            .as_str()
            .is_none_or(|s| s.parse::<OnlyUtcDateTime>().is_err())
    {
        return Err(INVALID);
    }
    let (raw, file) = data_file(&directory, "data.parquet", witnesses)?;
    if manifest["data_byte_sha256"] != byte_sha(&raw)
        || columnar::read(file, &manifest["arrow_schema"], 8192)? != candidate.rows
    {
        return Err(INVALID);
    }
    Ok(manifest)
}
fn publish_calculation(owner: &Directory, candidate: &CalculationBundle) -> Result<()> {
    let logical = &candidate.logical;
    let exists = || optional_directory(owner, &["sha256", &logical[..2], logical]);
    if exists()?.is_none() {
        if let Err(error) = put_bundle_at(
            owner.fd.as_fd(),
            &["sha256", &logical[..2], logical],
            &candidate.files,
            BUDGET,
        ) {
            if exists()?.is_none() {
                return Err(error);
            }
            // A concurrent complete winner is accepted only through the same
            // semantic/Parquet owner read, retaining its original audit bytes.
        }
    }
    verify_calculation(owner, candidate, &mut Vec::new()).map(drop)
}
fn publish_statistics(owner: &Directory, candidate: &StatisticsBundle) -> Result<()> {
    let logical = &candidate.logical;
    let exists = || optional_directory(owner, &["sha256", &logical[..2], logical]);
    if exists()?.is_none() {
        if let Err(error) = put_bundle_at(
            owner.fd.as_fd(),
            &["sha256", &logical[..2], logical],
            &candidate.files,
            BUDGET,
        ) {
            if exists()?.is_none() {
                return Err(error);
            }
        }
    }
    verify_statistics(owner, candidate, &mut Vec::new()).map(drop)
}
fn verify_single(
    owner: &Directory,
    parts: &[&str],
    expected: &Value,
    witnesses: &mut Vec<Witness>,
) -> Result<Value> {
    let directory = optional_directory(owner, parts)?.ok_or(INVALID)?;
    exact_files(&directory, &["manifest.json"])?;
    let value = document(&directory, "manifest.json", witnesses)?;
    if value != *expected {
        return Err(INVALID);
    }
    Ok(value)
}
fn publish_result(owner: &Directory, result: &Value) -> Result<()> {
    let logical = pin(result, "research_result_plan_fingerprint")?;
    let parts = ["sha256", &logical[..2], logical];
    if optional_directory(owner, &parts)?.is_none() {
        if let Err(error) = put_at(owner.fd.as_fd(), &parts, "manifest.json", result) {
            if optional_directory(owner, &parts)?.is_none() {
                return Err(error);
            }
        }
    }
    let directory = optional_directory(owner, &parts)?.ok_or(INVALID)?;
    exact_files(&directory, &["manifest.json"])?;
    let actual = document(&directory, "manifest.json", &mut Vec::new())?;
    if without_audit(&actual, None)? != without_audit(result, None)?
        || actual["created_at"]
            .as_str()
            .is_none_or(|s| s.parse::<OnlyUtcDateTime>().is_err())
    {
        return Err(INVALID);
    }
    Ok(())
}
fn verify_result(
    owner: &Directory,
    expected: &Value,
    witnesses: &mut Vec<Witness>,
) -> Result<Value> {
    let logical = pin(expected, "research_result_plan_fingerprint")?;
    let directory =
        optional_directory(owner, &["sha256", &logical[..2], logical])?.ok_or(INVALID)?;
    exact_files(&directory, &["manifest.json"])?;
    let actual = document(&directory, "manifest.json", witnesses)?;
    if without_audit(&actual, None)? != without_audit(expected, None)?
        || actual["created_at"]
            .as_str()
            .is_none_or(|s| s.parse::<OnlyUtcDateTime>().is_err())
    {
        return Err(INVALID);
    }
    Ok(actual)
}
fn report_value(
    run: &VerifiedRun,
    observation: &Value,
    proof: &Value,
    science: &Science,
    at: OnlyUtcDateTime,
) -> Result<Value> {
    let value = json!({"schema_version":1,"contract":REPORT,"run_id":run.run_id(),"specification":run.strategy_specification()?.record(),
        "specification_fingerprint":run.specification_fingerprint(),"scientific_specification_fingerprint":run.strategy_specification()?.scientific_specification_fingerprint()?,
        "prepared_inputs":run.prepared_inputs,"candidate_fingerprint":run.strategy_specification()?.candidate_fingerprint()?,"source_revision":science.source.to_record(),
        "research_result_plan_fingerprint":science.result["research_result_plan_fingerprint"],"research_result_fingerprint":science.result["research_result_fingerprint"],
        "calculation_execution_evidence_fingerprints":science.executions.iter().map(|v|v["evidence_fingerprint"].clone()).collect::<Vec<_>>(),
        "equivalence_evidence_fingerprints":science.equivalence.iter().map(|v|v["evidence_fingerprint"].clone()).collect::<Vec<_>>(),
        "admission_evidence_fingerprint":science.admission,"observation":observation,"installed_proof":proof,
        "node_equivalence_producer":{"contract":"ONLYALPHA_NATIVE_TYPED_NODE_EQUIVALENCE_V1","observation_contract":"ONLYALPHA_CALCULATION_NODE_PROFILE_OBSERVATION_V1",
            "case_witness_fingerprint":report_fingerprint(&observation["node_profiles"] )?,"native_image":observation["producer"]["native_image"],
            "algorithm_artifact_fingerprint":observation["producer"]["algorithm_artifact_fingerprint"]},"created_at":audit(at)});
    signed_report(value)
}
fn publish_report(owner: &Directory, run: &VerifiedRun, report: &Value) -> Result<()> {
    let parts = [STRATEGY_PROFILE, "runs", run.run_id()];
    let files = BTreeMap::from([("manifest.json".into(), report_bytes(report)?)]);
    if optional_directory(owner, &parts)?.is_none() {
        if let Err(error) = put_bundle_at(owner.fd.as_fd(), &parts, &files, LIMIT) {
            // An audit-neutral immutable conflict may have a complete winner.
            // I/O and fsync uncertainty must retain the unsuccessful outcome.
            if error != "IMMUTABLE_JSON_INVALID" || optional_directory(owner, &parts)?.is_none() {
                return Err(error);
            }
        }
    }
    let directory = optional_directory(owner, &parts)?.ok_or(INVALID)?;
    exact_files(&directory, &["manifest.json"])?;
    let actual = report_document(&directory, &mut Vec::new())?;
    verify_report_signature(&actual)?;
    if without_audit(&actual, Some("artifact_content_fingerprint"))?
        != without_audit(report, Some("artifact_content_fingerprint"))?
    {
        return Err(INVALID);
    }
    Ok(())
}
fn retained_runtime(
    store: &Store,
    run: &VerifiedRun,
    prepared: &Value,
    observation: &Value,
) -> Result<(Arc<RuntimeEvidenceHold>, Value)> {
    let root = store
        .runtime_root
        .as_deref()
        .ok_or("RESEARCH_RUNTIME_EVIDENCE_UNAVAILABLE")?;
    let spec = run.strategy_specification()?;
    let record = spec.record();
    let generation = pin_value(&record["runtime_generation_fingerprint"])?;
    let mut held = RuntimeEvidenceHold::open(root, run.run_id(), "research", generation)?;
    let proof = held.installed_proof(pin_value(&record["algorithm_artifact_fingerprint"])?)?;
    if held.binding() != &prepared["runtime_work_binding"]
        || held.manifest()["catalog_generation_fingerprint"]
            != record["catalog_generation_fingerprint"]
        || prepared != &run.prepared_inputs
        || prepared["execution_binding"] != record["execution_binding"]
        || proof["native_descriptor"]["image"]["artifact"]
            != record["execution_binding"]["executor_artifact_sha256"]
        || proof["native_descriptor"]["image"]["version"]
            != record["execution_binding"]["executor_version"]
        || observation["producer"]["native_image"]["artifact"]
            != record["execution_binding"]["executor_artifact_sha256"]
        || observation["producer"]["native_image"]["version"]
            != record["execution_binding"]["executor_version"]
        || observation["producer"]["native_image"]["protocol"]
            != record["execution_binding"]["protocol"]
        || observation["producer"]["algorithm_artifact_fingerprint"]
            != record["algorithm_artifact_fingerprint"]
    {
        return Err(INVALID);
    }
    let allowed = rows(&held.manifest()["implementations"])?;
    let native = rows(&proof["native_descriptor"]["implementations"])?;
    for (_, graph) in spec.calculation_graphs() {
        for node in graph.ordered_nodes() {
            let definition = node.to_record();
            let id = node.fingerprint();
            let backends: &[&str] = if definition["kind"] == "TARGET" {
                &["RESEARCH"]
            } else {
                &["RESEARCH", "TRADING"]
            };
            for backend in backends {
                let body = implementation(prepared, &definition, &id, backend)?;
                if !allowed.contains(&implementation_projection(body)?) {
                    return Err(INVALID);
                }
                if definition["kind"] == "PREDICATE" {
                    if !native.contains(body)
                        || body["resources"]
                            != json!([{"relative_path":"bin/onlyalpha-backend","byte_sha256":record["execution_binding"]["executor_artifact_sha256"]}])
                    {
                        return Err(INVALID);
                    }
                }
            }
        }
    }
    held.verify()?;
    Ok((Arc::new(held), proof))
}
fn equivalence_owner(store: &Store) -> Result<Directory> {
    let owner = store.root.child("calculation-equivalence", false)?;
    verify_lockfile(&owner)?;
    owner.path(&["evidence-v2", "sha256"], false)?;
    Ok(owner)
}
pub(super) fn source_locks(store: &Store) -> Result<Vec<Arc<SourceLock>>> {
    let mut locks = store.locks()?.into_iter().map(Arc::new).collect::<Vec<_>>();
    let equivalence = equivalence_owner(store)?;
    locks.push(Arc::new(SourceLock::publication(&equivalence.path)?));
    Ok(locks)
}
fn load(
    store: &Store,
    run: &VerifiedRun,
    locks: Vec<Arc<SourceLock>>,
) -> Result<Option<(Value, Science, Arc<ReadCut>)>> {
    store.root.verify()?;
    let Some(directory) =
        optional_directory(&store.artifacts, &[STRATEGY_PROFILE, "runs", run.run_id()])?
    else {
        return if run.completed() {
            Err(INVALID)
        } else {
            Ok(None)
        };
    };
    exact_files(&directory, &["manifest.json"])?;
    let mut witnesses = Vec::new();
    let namespace = crate::bootstrap::deployment::load_semantic_store_id_at(&store.root.fd)
        .map_err(|_| INVALID)?;
    if document(
        &store.root,
        ".onlyalpha-semantic-store.json",
        &mut witnesses,
    )? != json!({"schema_version":1,"store_id":namespace.value()})
    {
        return Err(INVALID);
    }
    let report = report_document(&directory, &mut witnesses)?;
    exact(
        &report,
        &[
            "schema_version",
            "contract",
            "run_id",
            "specification",
            "specification_fingerprint",
            "scientific_specification_fingerprint",
            "prepared_inputs",
            "candidate_fingerprint",
            "source_revision",
            "research_result_plan_fingerprint",
            "research_result_fingerprint",
            "calculation_execution_evidence_fingerprints",
            "equivalence_evidence_fingerprints",
            "admission_evidence_fingerprint",
            "observation",
            "installed_proof",
            "node_equivalence_producer",
            "created_at",
            "artifact_content_fingerprint",
        ],
    )?;
    verify_report_signature(&report)?;
    let spec = run.strategy_specification()?;
    if report["schema_version"] != 1
        || report["contract"] != REPORT
        || report["run_id"] != run.run_id()
        || report["specification"] != *spec.record()
        || report["specification_fingerprint"] != run.specification_fingerprint()
        || report["prepared_inputs"] != run.prepared_inputs
    {
        return Err(INVALID);
    }
    if let Some((result, artifact, executions)) = &run.completion {
        if report["research_result_fingerprint"] != *result
            || report["artifact_content_fingerprint"] != *artifact
            || report["calculation_execution_evidence_fingerprints"] != json!(executions)
        {
            return Err(INVALID);
        }
    }
    let at: OnlyUtcDateTime = text(&report, "created_at")?.parse().map_err(|_| INVALID)?;
    let materialized = MaterializedDataset::load(
        &store.datasets,
        text(
            &report["prepared_inputs"]["dataset_materialization"],
            "materialization_id",
        )?,
    )?;
    if materialized.lineage() != &report["prepared_inputs"]["dataset_materialization"] {
        return Err(INVALID);
    }
    let dataset = materialized.verified();
    physical::capture_dataset(
        &store.root.path.join("datasets"),
        dataset.manifest(),
        materialized.lineage(),
        &mut witnesses,
    )?;
    let (runtime, proof) = retained_runtime(
        store,
        run,
        &report["prepared_inputs"],
        &report["observation"],
    )?;
    let mut science = science(
        spec,
        &report["prepared_inputs"],
        &report["observation"],
        dataset,
        at,
    )?;
    if report_value(run, &report["observation"], &proof, &science, at)? != report {
        return Err(INVALID);
    }
    for calculation in &mut science.calculations {
        calculation.manifest =
            verify_calculation(&store.calculations, calculation, &mut witnesses)?;
    }
    for statistics in &mut science.statistics {
        statistics.manifest = verify_statistics(&store.statistics, statistics, &mut witnesses)?;
    }
    for value in &science.executions {
        let id = pin(value, "evidence_fingerprint")?;
        verify_single(
            &store.evidence,
            &["sha256", &id[..2], id],
            value,
            &mut witnesses,
        )?;
    }
    let equivalence = equivalence_owner(store)?;
    for value in &science.equivalence {
        let id = pin(value, "evidence_fingerprint")?;
        verify_single(
            &equivalence,
            &["evidence-v2", "sha256", &id[..2], id],
            value,
            &mut witnesses,
        )?;
    }
    science.result = verify_result(&store.results, &science.result, &mut witnesses)?;
    let cut = Arc::new(ReadCut {
        runtime,
        files: witnesses,
        locks,
    });
    cut.verify()?;
    store.root.verify()?;
    Ok(Some((report, science, cut)))
}
fn completion(run: &VerifiedRun, report: &Value, cut: Arc<ReadCut>) -> Result<VerifiedCompletion> {
    let completion = VerifiedCompletion {
        run: run.clone(),
        result: pin(report, "research_result_fingerprint")?.into(),
        artifact: pin(report, "artifact_content_fingerprint")?.into(),
        execution_evidence: rows(&report["calculation_execution_evidence_fingerprints"])?
            .iter()
            .map(|v| pin_value(v).map(str::to_owned))
            .collect::<Result<_>>()?,
        strategy_cut: Some(cut),
    };
    run.verify_completion(&completion)?;
    completion.verify_cut()?;
    Ok(completion)
}
impl Store {
    /// Location supplied by owning deployment composition, never an execution
    /// grant. Factor history does not require this configured root to exist.
    pub fn with_runtime_root(mut self, root: &Path) -> Result<Self> {
        if !root.is_absolute()
            || root
                .as_os_str()
                .to_str()
                .is_none_or(|s| s.split('/').any(|p| matches!(p, "." | "..")))
        {
            return Err(UNAVAILABLE);
        }
        self.runtime_root = Some(root.into());
        Ok(self)
    }
    pub fn commit_strategy(&self, executed: ExecutedStrategy) -> Result<VerifiedCompletion> {
        let (run, inputs, observation, at) = executed.into_parts();
        inputs.verify_runtime()?;
        let locks = source_locks(self)?;
        let spec = run.strategy_specification()?;
        let materialized = MaterializedDataset::load(
            &self.datasets,
            text(
                &inputs.record()["dataset_materialization"],
                "materialization_id",
            )?,
        )?;
        if materialized.lineage() != &inputs.record()["dataset_materialization"] {
            return Err(INVALID);
        }
        let (runtime, proof) = retained_runtime(self, &run, inputs.record(), &observation)?;
        let science = science(
            spec,
            inputs.record(),
            &observation,
            materialized.verified(),
            at,
        )?;
        let report = report_value(&run, &observation, &proof, &science, at)?;
        // All deterministic validation/encoding/resource checks precede writes.
        inputs.verify_runtime()?;
        runtime.verify()?;
        for lock in &locks {
            lock.verify()?;
        }
        for calculation in &science.calculations {
            publish_calculation(&self.calculations, calculation)?;
        }
        for statistics in &science.statistics {
            publish_statistics(&self.statistics, statistics)?;
        }
        for value in &science.executions {
            let id = pin(value, "evidence_fingerprint")?;
            put_at(
                self.evidence.fd.as_fd(),
                &["sha256", &id[..2], id],
                "manifest.json",
                value,
            )?;
        }
        let equivalence = equivalence_owner(self)?;
        for value in &science.equivalence {
            let id = pin(value, "evidence_fingerprint")?;
            put_at(
                equivalence.fd.as_fd(),
                &["evidence-v2", "sha256", &id[..2], id],
                "manifest.json",
                value,
            )?;
        }
        publish_result(&self.results, &science.result)?;
        publish_report(&self.artifacts, &run, &report)?;
        inputs.verify_runtime()?;
        runtime.verify()?;
        for lock in &locks {
            lock.verify()?;
        }
        let (report, _, cut) = load(self, &run, locks)?.ok_or(INVALID)?;
        drop(inputs);
        drop(runtime);
        completion(&run, &report, cut)
    }
    pub(super) fn load_strategy(
        &self,
        run: &VerifiedRun,
        locks: Vec<Arc<SourceLock>>,
    ) -> Result<Option<VerifiedCompletion>> {
        load(self, run, locks)?
            .map(|(report, _, cut)| completion(run, &report, cut))
            .transpose()
    }
    pub fn read_verified_strategy(&self, run: &VerifiedRun) -> Result<VerifiedStrategyResearch> {
        if !run.completed() {
            return Err("RESEARCH_OPERATIONAL_COMPLETION_REQUIRED");
        }
        let (report, science, cut) = load(self, run, source_locks(self)?)?.ok_or(INVALID)?;
        completion(run, &report, cut.clone())?;
        let sealed = VerifiedStrategyResearch {
            run_id: run.run_id().into(),
            specification_fingerprint: run.specification_fingerprint().into(),
            source_revision: science.source,
            candidate_fingerprint: pin(&report, "candidate_fingerprint")?.into(),
            research_result_fingerprint: pin(&report, "research_result_fingerprint")?.into(),
            research_execution_evidence_fingerprints: rows(
                &report["calculation_execution_evidence_fingerprints"],
            )?
            .iter()
            .map(|v| pin_value(v).map(str::to_owned))
            .collect::<Result<_>>()?,
            admission_evidence_fingerprint: science.admission,
            equivalence_evidence_fingerprints: rows(&report["equivalence_evidence_fingerprints"])?
                .iter()
                .map(|v| pin_value(v).map(str::to_owned))
                .collect::<Result<_>>()?,
            source_locks: cut.locks.clone(),
            strategy_cut: Some(cut),
        };
        sealed.verify_cut()?;
        Ok(sealed)
    }
    pub fn read_verified_counts(
        &self,
        run: &VerifiedRun,
        frozen: &FrozenStore,
        relation_id: &str,
    ) -> Result<VerifiedResearchCounts> {
        if !run.completed() {
            return Err("RESEARCH_OPERATIONAL_COMPLETION_REQUIRED");
        }
        self.read_verified_counts_captured(run, frozen, relation_id, source_locks(self)?)
    }
    /// The original Novelty Source snapshot already owns these barriers. Reuse
    /// them rather than attempting nested shared locks under its exclusive cut.
    pub(crate) fn read_verified_counts_captured(
        &self,
        run: &VerifiedRun,
        frozen: &FrozenStore,
        relation_id: &str,
        locks: Vec<Arc<SourceLock>>,
    ) -> Result<VerifiedResearchCounts> {
        for owner in [&self.results, &self.statistics] {
            locks
                .iter()
                .find(|cut| cut.directory.path == owner.path)
                .ok_or(INVALID)?
                .verify()?;
        }
        if !run.completed() {
            return Err("RESEARCH_OPERATIONAL_COMPLETION_REQUIRED");
        }
        let (report, science, mut cut) = load(self, run, locks)?.ok_or(INVALID)?;
        completion(run, &report, cut.clone())?;
        if frozen.namespace().map_err(|_| INVALID)?
            != crate::bootstrap::deployment::load_semantic_store_id_at(&self.root.fd)
                .map_err(|_| INVALID)?
        {
            return Err(INVALID);
        }
        let relation = frozen
            .load_relation_verified(relation_id, FROZEN_HISTORY_WORK)
            .map_err(|_| INVALID)?;
        let source = frozen
            .load_verified(relation.strategy_fingerprint(), FROZEN_HISTORY_WORK)
            .map_err(|_| INVALID)?;
        let expected = relation_record(&report, &science.source)?;
        // Both owning readers recompute Strategy identity. The first Frozen
        // Source and this scientific occurrence can retain different aliases;
        // exact Frozen record/physical witnesses are still checked below.
        if relation.to_record() != expected || source.fingerprint() != science.source.fingerprint()
        {
            return Err(INVALID);
        }
        // Retain exact Frozen files as well as the scientific/Runtime closure.
        let mut frozen_witnesses = Vec::new();
        let frozen_revision = optional_directory(
            &self.root,
            &[
                "strategy",
                "frozen-revisions",
                "sha256",
                &source.fingerprint()[..2],
                source.fingerprint(),
            ],
        )?
        .ok_or(INVALID)?;
        if document(&frozen_revision, "manifest.json", &mut frozen_witnesses)?
            != json!({"schema_version":1,"strategy_fingerprint":source.fingerprint(),"revision":source.to_record()})
        {
            return Err(INVALID);
        }
        let frozen_relation = optional_directory(
            &self.root,
            &[
                "strategy",
                "freeze-relations",
                "sha256",
                &relation_id[..2],
                relation_id,
            ],
        )?
        .ok_or(INVALID)?;
        if document(&frozen_relation, "manifest.json", &mut frozen_witnesses)?
            != relation.to_record()
        {
            return Err(INVALID);
        }
        if frozen
            .load_verified(source.fingerprint(), FROZEN_HISTORY_WORK)
            .map_err(|_| INVALID)?
            != source
            || frozen
                .load_relation_verified(relation_id, FROZEN_HISTORY_WORK)
                .map_err(|_| INVALID)?
                != relation
        {
            return Err(INVALID);
        }
        Arc::get_mut(&mut cut)
            .ok_or(INVALID)?
            .files
            .extend(frozen_witnesses);
        let sealed = VerifiedResearchCounts {
            subject_strategy_fingerprint: source.fingerprint().into(),
            research_result_fingerprint: pin(&report, "research_result_fingerprint")?.into(),
            research_result_plan_fingerprint: pin(&report, "research_result_plan_fingerprint")?
                .into(),
            freeze_relation_fingerprint: relation_id.into(),
            statistics_result_count: science.statistics.len() as u64,
            calculation_result_count: science.calculations.len() as u64,
            validated_calculations: Some(report["prepared_inputs"].clone()),
            source_locks: cut.locks.clone(),
            strategy_cut: Some(cut.clone()),
        };
        cut.verify()?;
        sealed.verify_cut()?;
        Ok(sealed)
    }
}
fn relation_record(report: &Value, source: &onlyalpha_strategy::SourceRevision) -> Result<Value> {
    signed_domain(
        json!({"schema_version":1,"candidate_fingerprint":report["candidate_fingerprint"],"research_result_fingerprint":report["research_result_fingerprint"],
        "strategy_fingerprint":source.fingerprint(),"research_execution_evidence_fingerprints":report["calculation_execution_evidence_fingerprints"],
        "admission_evidence_fingerprint":report["admission_evidence_fingerprint"],"equivalence_evidence_fingerprints":report["equivalence_evidence_fingerprints"]}),
        "relation_fingerprint",
        "onlyalpha.strategy.freeze-relation",
    )
}
/// Controlled infrastructure extension of the original namespace. Existing
/// named owners are inspected; partial/corrupt owners are never repaired.
pub(super) fn initialize_owners(root: &Path) -> Result<()> {
    let research = Directory::open(root)?;
    crate::bootstrap::deployment::load_semantic_store_id_at(&research.fd)
        .map_err(|_| UNAVAILABLE)?;
    provision_directory(
        &research,
        "calculation-equivalence",
        &["evidence-v2", "sha256"],
        true,
    )?;
    let strategy = research.child("strategy", true)?;
    provision_directory(&strategy, "qualification-decisions", &["sha256"], true)?;
    let artifacts = research.child("artifacts", false)?;
    verify_lockfile(&artifacts)?;
    provision_directory(&artifacts, STRATEGY_PROFILE, &["runs"], false)?;
    research.verify()?;
    fs::fsync(&research.fd).map_err(|_| UNAVAILABLE)
}
fn provision_directory(
    parent: &Directory,
    name: &str,
    layout: &[&str],
    source: bool,
) -> Result<()> {
    if let Some(existing) = optional_directory(parent, &[name])? {
        if source {
            verify_lockfile(&existing)?;
        }
        existing.path(layout, false)?;
        existing.verify()?;
        fs::fsync(&existing.fd).map_err(|_| UNAVAILABLE)?;
        return fs::fsync(&parent.fd).map_err(|_| UNAVAILABLE);
    }
    let auxiliary = parent.child(".immutable-json-staging", true)?;
    if fs::fstat(&auxiliary.fd).map_err(|_| UNAVAILABLE)?.st_dev
        != fs::fstat(&parent.fd).map_err(|_| UNAVAILABLE)?.st_dev
    {
        return Err(INVALID);
    }
    let mut entropy = [0_u8; 16];
    getrandom::fill(&mut entropy).map_err(|_| UNAVAILABLE)?;
    let stage = format!(
        ".stage-{}",
        entropy
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>()
    );
    fs::mkdirat(
        &auxiliary.fd,
        stage.as_str(),
        fs::Mode::from_raw_mode(0o700),
    )
    .map_err(|_| UNAVAILABLE)?;
    let held = auxiliary.child(&stage, false)?;
    if source {
        let lock = fs::openat(
            &held.fd,
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
    }
    let nested = held.path(layout, true)?;
    fs::fsync(&nested.fd).map_err(|_| UNAVAILABLE)?;
    fs::fsync(&held.fd).map_err(|_| UNAVAILABLE)?;
    held.verify()?;
    parent.verify()?;
    auxiliary.verify()?;
    match fs::renameat_with(
        &auxiliary.fd,
        stage.as_str(),
        &parent.fd,
        name,
        fs::RenameFlags::NOREPLACE,
    ) {
        Ok(()) => {
            let actual = parent.child(name, false)?;
            let a = fs::fstat(&actual.fd).map_err(|_| UNAVAILABLE)?;
            let b = fs::fstat(&held.fd).map_err(|_| UNAVAILABLE)?;
            if a.st_ino != b.st_ino || a.st_dev != b.st_dev {
                return Err(INVALID);
            }
        }
        Err(rustix::io::Errno::EXIST) => {}
        Err(_) => return Err(UNAVAILABLE),
    }
    fs::fsync(&parent.fd).map_err(|_| UNAVAILABLE)?;
    fs::fsync(&auxiliary.fd).map_err(|_| UNAVAILABLE)?;
    // Any interrupted/losing temporary inode stays in the known auxiliary
    // namespace. Never guess at another invocation's ownership or remove it.
    let actual = parent.child(name, false)?;
    if source {
        verify_lockfile(&actual)?;
    }
    actual.path(layout, false)?;
    actual.verify()?;
    parent.verify()
}
impl Store {
    pub(super) fn read_strategy_report(&self, run: &VerifiedRun) -> Result<Value> {
        if !run.completed() {
            return Err("RESEARCH_OPERATIONAL_COMPLETION_REQUIRED");
        }
        let (report, _, cut) = load(self, run, source_locks(self)?)?.ok_or(INVALID)?;
        completion(run, &report, cut)?.verify_cut()?;
        Ok(report)
    }
}

impl Store {
    /// Existing final report locators only; no work/Run is synthesized from them.
    pub(super) fn strategy_report_ids(&self) -> Result<Vec<String>> {
        let Some(directory) = optional_directory(&self.artifacts, &[STRATEGY_PROFILE, "runs"])?
        else {
            return Ok(Vec::new());
        };
        let names = directory.names()?;
        if names.len() > 1024 {
            return Err(UNAVAILABLE);
        }
        if names
            .iter()
            .any(|id| !crate::application::command::uuid4(id))
        {
            return Err(INVALID);
        }
        Ok(names)
    }
    pub(super) fn strategy_source_candidate(&self, id: &str) -> Result<Value> {
        if !crate::application::command::uuid4(id) {
            return Err(INVALID);
        }
        let directory =
            optional_directory(&self.artifacts, &[STRATEGY_PROFILE, "runs", id])?.ok_or(INVALID)?;
        exact_files(&directory, &["manifest.json"])?;
        let value = report_document(&directory, &mut Vec::new())?;
        if value["schema_version"] != 1 || value["contract"] != REPORT || value["run_id"] != id {
            return Err(INVALID);
        }
        Ok(value)
    }
    pub(super) fn read_strategy_source(
        &self,
        run: &VerifiedRun,
        locks: Vec<Arc<SourceLock>>,
    ) -> Result<(Value, Value, Vec<Value>, Arc<ReadCut>)> {
        if !run.completed() {
            return Err("NOVELTY_PROOF_UNAVAILABLE");
        }
        let (report, science, cut) = load(self, run, locks)?.ok_or(INVALID)?;
        completion(run, &report, cut.clone())?;
        let statistics = science
            .statistics
            .into_iter()
            .map(|s| s.manifest)
            .collect::<Vec<_>>();
        cut.verify()?;
        Ok((report, science.result, statistics, cut))
    }
}

#[cfg(test)]
mod calculation_alias_reuse_tests {
    use super::*;
    use std::os::unix::fs::{MetadataExt, PermissionsExt};

    // Public value/physical owner test only: no PreparedInputs, executed Run,
    // Evidence seal, Runtime hold or publication grant is manufactured here.
    fn value_bundle() -> CalculationBundle {
        let spec = RunSpecification::from_record(
            &crate::application::strategy_research::test_run_record(),
        )
        .unwrap();
        let graph = spec.target_graph();
        let node = graph.ordered_nodes().next().unwrap();
        assert_eq!(graph.ordered_nodes().count(), 1);
        let axis = vec![json!(1), json!(2), json!(3)];
        let (schema,rows,raw)=columnar::write_calculation(&axis,&json!({"target_value":[
            {"type":"NULL","value":null},{"type":"DECIMAL","value":"0"},{"type":"DECIMAL","value":"0.125"}]}),&node.to_record()["outputs"]).unwrap();
        let id = node.fingerprint();
        let instrument = "BINANCE:SPOT:BTCUSDT";
        let partitions = vec![
            json!({"node_fingerprint":id,"instrument_id":instrument,"row_count":rows.len(),"arrow_schema":schema,
            "semantic_fingerprint":columnar::partition(&id,instrument,&schema,&rows).unwrap(),"relative_path":"data/p-000000.parquet","byte_sha256":byte_sha(&raw)}),
        ];
        let logical = spec.calculation_identity("target.forward_return").unwrap();
        let content = columnar::calculation_content(&partitions).unwrap();
        let manifest = json!({"schema_version":1,"calculation_fingerprint":logical,"dataset_snapshot_fingerprint":"d".repeat(64),
            "calculation_graph_fingerprint":graph.fingerprint(),"calculation_graph":graph.to_record(),"result_content_fingerprint":content,
            "calculation_result_fingerprint":hash(&json!({"schema_version":1,"calculation_fingerprint":logical,"result_content_fingerprint":content})).unwrap(),
            "partition_count":1,"total_row_count":rows.len(),"partitions":partitions,"created_at":"2026-11-01T00:00:00+00:00"});
        let files = BTreeMap::from([
            ("manifest.json".into(), canonical_bytes(&manifest).unwrap()),
            ("data/p-000000.parquet".into(), raw),
        ]);
        CalculationBundle {
            logical,
            manifest,
            files,
            rows: vec![rows],
        }
    }
    fn copy(value: &CalculationBundle) -> CalculationBundle {
        CalculationBundle {
            logical: value.logical.clone(),
            manifest: value.manifest.clone(),
            files: value.files.clone(),
            rows: value.rows.clone(),
        }
    }
    #[test]
    fn calculation_alias_reuse_preserves_first_manifest_and_real_parquet() {
        let mut random = [0u8; 16];
        getrandom::fill(&mut random).unwrap();
        let root = std::env::temp_dir().canonicalize().unwrap().join(format!(
            "use_test-calculation-alias-{}",
            random
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        ));
        std::fs::create_dir(&root).unwrap();
        std::fs::set_permissions(&root, std::fs::Permissions::from_mode(0o700)).unwrap();
        let owner = Directory::open(&root).unwrap();
        let original = value_bundle();
        publish_calculation(&owner, &original).unwrap();
        let directory = root
            .join("sha256")
            .join(&original.logical[..2])
            .join(&original.logical);
        let snapshot = |name: &str| {
            let path = directory.join(name);
            (
                std::fs::metadata(&path).unwrap().ino(),
                std::fs::read(path).unwrap(),
            )
        };
        let first_manifest = snapshot("manifest.json");
        let first_parquet = snapshot("data/p-000000.parquet");
        let mut renamed = copy(&original);
        renamed.manifest["calculation_graph"]["nodes"][0]["alias"] = json!("new visible label");
        renamed.manifest["created_at"] = json!("2026-11-02T00:00:00+00:00");
        let graph = Graph::from_record(&renamed.manifest["calculation_graph"], LIMIT).unwrap();
        assert_eq!(
            graph.fingerprint(),
            original.manifest["calculation_graph_fingerprint"]
        );
        renamed.files.insert(
            "manifest.json".into(),
            canonical_bytes(&renamed.manifest).unwrap(),
        );
        publish_calculation(&owner,&renamed).expect("same public Graph1/Calculation1 semantics must reuse the original physical result despite presentation alias and audit changes");
        assert_eq!(
            verify_calculation(&owner, &renamed, &mut Vec::new()).unwrap(),
            original.manifest
        );
        assert_eq!(snapshot("manifest.json"), first_manifest);
        assert_eq!(snapshot("data/p-000000.parquet"), first_parquet);
        // Ignoring presentation aliases must still verify the actual Graph1
        // against its declared identity, all exact node refs, and Parquet rows.
        let mut forged = copy(&renamed);
        forged.manifest["calculation_graph"]["nodes"][0]["definition"]["parameters"]["exit_offset"]
            ["value"] = json!(6);
        assert_ne!(
            Graph::from_record(&forged.manifest["calculation_graph"], LIMIT)
                .unwrap()
                .fingerprint(),
            graph.fingerprint()
        );
        assert!(publish_calculation(&owner, &forged).is_err());
        let mut wrong_rows = copy(&renamed);
        wrong_rows.rows[0][2]["target_value"] = json!("0.250000000000000000");
        assert!(publish_calculation(&owner, &wrong_rows).is_err());
        assert_eq!(snapshot("manifest.json"), first_manifest);
        assert_eq!(snapshot("data/p-000000.parquet"), first_parquet);
        drop(owner);
        std::fs::remove_dir_all(root).unwrap();
    }
}

#[cfg(test)]
mod report_work_tests {
    use super::*;
    use std::{fs, os::unix::fs::DirBuilderExt, path::PathBuf};

    // Codec and physical-file obligations only; no executed Run, completion
    // proof, Runtime admission or business Evidence is manufactured here.
    fn nested(size: usize, depth: usize) -> Value {
        let mut value = json!("x".repeat(size));
        for _ in 0..depth {
            value = json!({"observations":[value]});
        }
        value
    }
    struct Root(PathBuf);
    impl Root {
        fn new() -> Self {
            let mut unique = [0_u8; 8];
            getrandom::fill(&mut unique).unwrap();
            let name = unique
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>();
            let path = std::env::temp_dir()
                .canonicalize()
                .unwrap()
                .join(format!("oa-report-work-{name}"));
            fs::DirBuilder::new().mode(0o700).create(&path).unwrap();
            Self(path)
        }
    }
    impl Drop for Root {
        fn drop(&mut self) {
            fs::remove_dir_all(&self.0).unwrap();
        }
    }
    #[test]
    fn nested_report_under_unchanged_wire_cap_keeps_independent_identity() {
        let value = nested(1024 * 1024, 8);
        let mut expected = b"{\"observations\":[".repeat(8);
        expected.push(b'"');
        expected.extend(vec![b'x'; 1024 * 1024]);
        expected.push(b'"');
        expected.extend(b"]}".repeat(8));
        assert!(expected.len() < LIMIT);
        assert_eq!(report_bytes(&value).unwrap(), expected);
        let sealed = signed_report(value).unwrap();
        assert_eq!(sealed["artifact_content_fingerprint"], byte_sha(&expected));
        verify_report_signature(&sealed).unwrap();
    }
    #[test]
    fn cold_report_file_keeps_actual_witness_and_rejects_same_size_tamper() {
        let root = Root::new();
        let owner = Directory::open(&root.0).unwrap();
        let value = nested(1024 * 1024, 8);
        let raw = value.to_string().into_bytes();
        let files = BTreeMap::from([("manifest.json".into(), raw.clone())]);
        put_bundle_at(owner.fd.as_fd(), &["run"], &files, LIMIT).unwrap();
        let directory = owner.child("run", false).unwrap();
        assert!(document(&directory, "manifest.json", &mut Vec::new()).is_err());
        let mut witnesses = Vec::new();
        assert_eq!(report_document(&directory, &mut witnesses).unwrap(), value);
        assert_eq!(witnesses.len(), 1);
        witnesses[0].verify().unwrap();
        let mut changed = raw.clone();
        let index = changed.iter().position(|b| *b == b'x').unwrap();
        changed[index] = b'y';
        fs::write(directory.path.join("manifest.json"), changed).unwrap();
        assert!(witnesses[0].verify().is_err());
        fs::write(directory.path.join("manifest.json"), raw).unwrap();
        witnesses[0].verify().unwrap();
        for malformed in [
            br#"{"key":1,"key":2}"#.as_slice(),
            br#"{"ratio":1.25}"#.as_slice(),
        ] {
            fs::write(directory.path.join("manifest.json"), malformed).unwrap();
            assert_eq!(report_document(&directory, &mut Vec::new()), Err(INVALID));
        }
    }
    #[test]
    fn report_resource_exhaustion_is_unavailable_and_wire_cap_is_preserved() {
        let too_large = json!("x".repeat(LIMIT));
        assert!(too_large.to_string().len() > LIMIT);
        assert_eq!(report_bytes(&too_large), Err(UNAVAILABLE));
        let too_deep = nested(2 * 1024 * 1024, 40);
        serde_json::from_str::<Value>(&too_deep.to_string()).unwrap();
        assert!(too_deep.to_string().len() < LIMIT);
        assert_eq!(report_bytes(&too_deep), Err(UNAVAILABLE));
    }
    #[test]
    fn report_small_metadata_numbers_keep_the_original_canonical_policy() {
        let value = json!({"ratio":1.25,"zero":-0.0});
        let expected = br#"{"ratio":"1.25","zero":"-0.0"}"#;
        assert_eq!(report_bytes(&value).unwrap(), expected);
        let identity = "abb4c73fdd049ad626b912fad6ccd86211434edbdb392f58592e222ce2035451";
        assert_eq!(report_fingerprint(&value).unwrap(), identity);
        assert_eq!(hash(&value).unwrap(), identity);
        let mut signed = signed_report(value).unwrap();
        verify_report_signature(&signed).unwrap();
        signed["artifact_content_fingerprint"] = json!("f".repeat(64));
        assert_eq!(verify_report_signature(&signed), Err(INVALID));
    }
    #[test]
    fn canonical_report_output_expansion_cannot_exceed_wire_cap() {
        let count = LIMIT / 7 + 1;
        let value = json!(vec![1.25; count]);
        assert!(value.to_string().len() < LIMIT);
        assert!(count * 7 + 1 > LIMIT);
        assert!(matches!(report_bytes(&value), Err(UNAVAILABLE)));
    }
    #[test]
    fn oversized_cold_report_is_unavailable_without_a_partial_witness() {
        use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
        let root = Root::new();
        let owner = Directory::open(&root.0).unwrap();
        let path = root.0.join("manifest.json");
        let file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&path)
            .unwrap();
        file.set_len((LIMIT + 1) as u64).unwrap();
        drop(file);
        let mut witnesses = Vec::new();
        assert_eq!(report_document(&owner, &mut witnesses), Err(UNAVAILABLE));
        assert!(witnesses.is_empty());
        fs::set_permissions(&path, fs::Permissions::from_mode(0o620)).unwrap();
        assert_eq!(report_document(&owner, &mut witnesses), Err(INVALID));
        assert!(witnesses.is_empty());
    }
}
