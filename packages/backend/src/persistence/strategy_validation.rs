//! The sole immutable owner of actual manual Backtest mathematical validation.
//! Files hold semantic truth; SQL only authenticates the original producer occurrence.
use crate::{
    application::{
        command::CommandId,
        private_strategy::Definition,
        research_dataset::MaterializedDataset,
        strategy_research::{planned_graph_validation, source_revision},
        strategy_validation::{self as validation, JoinedValidation, Origin, WORK},
    },
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{
        authority_session::AuthoritySession,
        research_dataset::Store as Datasets,
        research_evidence::strategy::{
            equivalence,
            physical::{self, ReadCut},
        },
        research_preparation::{self, State},
        research_runtime::RuntimeEvidenceHold,
    },
    security::{
        immutable_json::{self, Directory, SourceLock},
        protected_files,
    },
};
use onlyalpha_calculation::{
    normalize_result_outputs,
    product::{Graph, normalize_scalar},
};
use onlyalpha_strategy::SourceRevision;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet},
    os::fd::AsFd,
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio_postgres::{Client, Transaction};
#[cfg(test)]
mod tests;
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "STRATEGY_VALIDATION_CORRUPT";
const UNAVAILABLE: &str = "STRATEGY_VALIDATION_UNAVAILABLE";
const UNKNOWN: &str = "STRATEGY_VALIDATION_PUBLICATION_OUTCOME_UNKNOWN";
const CONTRACT: &str = "ONLYALPHA_MANUAL_BACKTEST_STRATEGY_VALIDATION_V1";
const JSON_WORK: usize = 64 * 1024 * 1024;
fn rows(value: &Value) -> Result<&Vec<Value>> {
    value.as_array().ok_or(INVALID)
}
fn text(value: &Value) -> Result<&str> {
    value.as_str().ok_or(INVALID)
}
fn exact(value: &Value, keys: &[&str]) -> Result<()> {
    crate::application::private_strategy::exact(value, keys).map_err(|_| INVALID)
}
fn canonical(value: &Value) -> Result<Vec<u8>> {
    let raw = onlyalpha_metadata_json::canonical_json(&value.to_string(), JSON_WORK)
        .map_err(|_| UNAVAILABLE)?
        .into_bytes();
    if raw.len() > WORK {
        return Err(UNAVAILABLE);
    }
    Ok(raw)
}
fn fingerprint(value: &Value) -> Result<String> {
    onlyalpha_metadata_json::fingerprint(&value.to_string(), JSON_WORK).map_err(|_| UNAVAILABLE)
}
fn verify_case(
    graph: &Graph,
    bindings: &Value,
    signals: &Value,
    case: &Value,
    axis: &[Value],
) -> Result<()> {
    if case["axis"] != json!(axis) || !rows(&case["target_outputs"])?.is_empty() {
        return Err(INVALID);
    }
    let mut outputs = Vec::new();
    for (key, implementation) in [
        ("research_outputs", "research_implementation_fingerprint"),
        ("streaming_outputs", "trading_implementation_fingerprint"),
    ] {
        let mut index = BTreeMap::new();
        for output in rows(&case[key])? {
            exact(
                output,
                &["node_fingerprint", "implementation_fingerprint", "values"],
            )?;
            let id = text(&output["node_fingerprint"])?;
            if index.insert(id.to_owned(), output).is_some() {
                return Err(INVALID);
            }
        }
        if index.len() != graph.ordered_nodes().count() {
            return Err(INVALID);
        }
        for node in graph.ordered_nodes() {
            let id = node.fingerprint();
            let d = node.to_record();
            let output = index.get(&id).ok_or(INVALID)?;
            let selected = rows(bindings)?
                .iter()
                .filter(|b| b["node_fingerprint"] == id)
                .collect::<Vec<_>>();
            if selected.len() != 1
                || output["implementation_fingerprint"] != selected[0][implementation]
            {
                return Err(INVALID);
            }
            let fields = output["values"].as_object().ok_or(INVALID)?;
            if fields.len() != rows(&d["outputs"])?.len() {
                return Err(INVALID);
            }
            for port in rows(&d["outputs"])? {
                let name = text(&port["name"])?;
                let values = rows(fields.get(name).ok_or(INVALID)?)?;
                if values.len() != axis.len() {
                    return Err(INVALID);
                }
                for value in values {
                    if normalize_scalar(value, WORK).map_err(|_| INVALID)? != *value
                        || normalize_result_outputs(&json!({(name):value})).map_err(|_| INVALID)?
                            [name]
                            != *value
                    {
                        return Err(INVALID);
                    }
                    if value["type"] == "NULL" {
                        if port["nullable"] != true {
                            return Err(INVALID);
                        }
                    } else if value["type"] != port["data_type"] {
                        return Err(INVALID);
                    }
                }
            }
        }
        outputs.push(index);
    }
    for (id, output) in &outputs[0] {
        if output["values"] != outputs[1].get(id).ok_or(INVALID)?["values"] {
            return Err(INVALID);
        }
    }
    let decisions = rows(&case["decisions"])?;
    if decisions.len() != axis.len() {
        return Err(INVALID);
    }
    for (index, row) in decisions.iter().enumerate() {
        exact(row, &["at_ns", "status", "decision"])?;
        if row["at_ns"] != axis[index]
            || !matches!(row["status"].as_str(), Some("READY" | "BLOCKED"))
            || (row["status"] == "READY") == row["decision"].is_null()
        {
            return Err(INVALID);
        }
        if !row["decision"].is_null() {
            exact(&row["decision"], &["eligibility", "entry", "exit"])?;
            for role in ["eligibility", "entry", "exit"] {
                let reference = &signals[role];
                let node = text(&reference["node_fingerprint"])?;
                let output = text(&reference["output_name"])?;
                let value = &outputs[0].get(node).ok_or(INVALID)?["values"][output][index];
                let expected = if value["type"] == "NULL" {
                    false
                } else {
                    value["value"].as_bool().ok_or(INVALID)?
                };
                if row["decision"][role] != expected {
                    return Err(INVALID);
                }
            }
        }
    }
    Ok(())
}
/// Value validation is deliberately not a publication constructor or grant.
pub(crate) fn verify_observation(
    prepared: &Value,
    observation: &Value,
    materialized: &MaterializedDataset,
) -> Result<Vec<Value>> {
    exact(
        observation,
        &[
            "axis",
            "research_outputs",
            "streaming_outputs",
            "target_outputs",
            "decisions",
            "restoration",
            "graph_cases",
            "node_profiles",
            "producer",
        ],
    )?;
    let graph =
        Graph::from_record(&prepared["decision"]["decision_graph"], WORK).map_err(|_| INVALID)?;
    let signals = &prepared["decision"]["signal_semantics"];
    let bindings = &prepared["implementation_bindings"];
    let axis = materialized
        .verified()
        .dataset()
        .rows()
        .iter()
        .map(|r| r["ts_event_ns"].clone())
        .collect::<Vec<_>>();
    verify_case(&graph, bindings, signals, observation, &axis)?;
    exact(
        &observation["restoration"],
        &[
            "processed_rows",
            "before_checkpoint_fingerprint",
            "restored_checkpoint_fingerprint",
        ],
    )?;
    let before = text(&observation["restoration"]["before_checkpoint_fingerprint"])?;
    if !crate::is_sha256_hex(before)
        || observation["restoration"]["processed_rows"] != axis.len() / 2
        || observation["restoration"]["restored_checkpoint_fingerprint"] != before
    {
        return Err(INVALID);
    }
    let (cases, profiles) = planned_graph_validation(
        &graph,
        &materialized.verified().dataset().bars()?,
        &prepared["input_window"],
    )?;
    let actual = rows(&observation["graph_cases"])?;
    if actual.len() != cases.len() {
        return Err(INVALID);
    }
    for (actual, (name, inputs)) in actual.iter().zip(cases) {
        exact(
            actual,
            &[
                "axis",
                "research_outputs",
                "streaming_outputs",
                "target_outputs",
                "decisions",
                "restoration",
                "case_id",
                "rows",
            ],
        )?;
        if actual["case_id"] != name || actual["rows"] != inputs || !actual["restoration"].is_null()
        {
            return Err(INVALID);
        }
        let axis = rows(&inputs)?
            .iter()
            .map(|r| r["at_ns"].clone())
            .collect::<Vec<_>>();
        verify_case(&graph, bindings, signals, actual, &axis)?;
    }
    let actual = rows(&observation["node_profiles"])?;
    if actual.len() != profiles.len() {
        return Err(INVALID);
    }
    for planned in profiles {
        let d =
            onlyalpha_calculation::product::Definition::from_record(&planned["definition"], WORK)
                .map_err(|_| INVALID)?;
        let matches = actual
            .iter()
            .filter(|p| p["node_fingerprint"] == d.fingerprint())
            .collect::<Vec<_>>();
        if matches.len() != 1 || rows(&matches[0]["cases"])?.len() != rows(&planned["cases"])?.len()
        {
            return Err(INVALID);
        }
        for (observed, planned) in rows(&matches[0]["cases"])?
            .iter()
            .zip(rows(&planned["cases"])?)
        {
            if observed["case_id"] != planned["case_id"] || observed["inputs"] != planned["inputs"]
            {
                return Err(INVALID);
            }
        }
    }
    equivalence::derive(&graph, bindings, observation)
}
fn verify_resolution(
    prepared: &Value,
    archive: &Value,
    factors: &BTreeMap<String, Value>,
    definition: &Definition,
) -> Result<()> {
    let request = &prepared["algorithm_resolution_request"];
    let observed = &prepared["algorithm_resolution"];
    exact(
        observed,
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
    exact(
        request,
        &[
            "schema_version",
            "contract",
            "sources",
            "instances",
            "core_artifact",
            "operator_artifact",
            "target_artifact",
        ],
    )?;
    if request["schema_version"] != 1
        || request["contract"] != "ONLYALPHA_CALCULATION_INSTANCES_RESOLVE_V1"
        || request["instances"] != definition.to_record()["calculations"]
    {
        return Err(INVALID);
    }
    for name in ["core", "operator", "target"] {
        if request[format!("{name}_artifact")] != archive[format!("{name}_artifact")]
            || observed[format!("{name}_artifact_sha256")]
                != archive[format!("{name}_artifact")]["sha256"]
        {
            return Err(INVALID);
        }
    }
    let proof = &archive["installed_proof"];
    if observed["schema_version"] != 1
        || observed["contract"] != request["contract"]
        || observed["isolation"] != "LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"
        || observed["algorithm_artifact"] != proof["algorithm_artifact"]
        || prepared["execution_binding"] != archive["execution_binding"]
    {
        return Err(INVALID);
    }
    let mut sources = Vec::new();
    for (id, factor) in factors {
        let selected = rows(&archive["private_factors"])?
            .iter()
            .filter(|f| f["binding"]["entry"]["factor_id"] == *id)
            .collect::<Vec<_>>();
        if selected.len() != 1 {
            return Err(INVALID);
        }
        let mut metadata = factor.clone();
        metadata
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("source_text");
        if selected[0]["archive"]["revision_metadata"] != metadata {
            return Err(INVALID);
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
        let matches = rows(&observed["source_artifacts"])?
            .iter()
            .filter(|a| a["source_artifact"]["factor_id"] == *id)
            .collect::<Vec<_>>();
        if matches.len() != 1
            || matches[0]["source_artifact"] != selected[0]["archive"]["source_artifact"]
        {
            return Err(INVALID);
        }
        let implementations = rows(&observed["nodes"])?
            .iter()
            .filter(|n| n["definition"]["kind"] == "FACTOR" && n["definition"]["type_id"] == *id)
            .flat_map(|n| {
                n["implementations"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .cloned()
            })
            .collect::<Vec<_>>();
        crate::application::research_admission::check_binding(
            &json!({"source_artifact":matches[0]["source_artifact"],"private_calculations":matches[0]["private_calculations"],"implementations":implementations}),
            &selected[0]["archive"],
            &selected[0]["binding"],
            &prepared["runtime_manifest"],
        )?;
    }
    if request["sources"] != json!(sources)
        || rows(&observed["source_artifacts"])?.len() != factors.len()
    {
        return Err(INVALID);
    }
    let native = &proof["native_descriptor"]["implementations"];
    let mut used = BTreeSet::new();
    for node in rows(&prepared["native_implementations"])? {
        if !rows(native)?.contains(node) || !used.insert(text(&node["implementation_fingerprint"])?)
        {
            return Err(INVALID);
        }
    }
    Ok(())
}
#[derive(Clone)]
pub(crate) struct VerifiedValidation {
    record: Value,
    source: SourceRevision,
    namespace: SemanticStoreId,
    cut: Arc<ReadCut>,
}
impl VerifiedValidation {
    pub(crate) fn source_revision(&self) -> &SourceRevision {
        &self.source
    }
    pub(crate) fn private_strategy_id(&self) -> &str {
        self.record["prepared_inputs"]["origin"]["private_strategy_id"]
            .as_str()
            .expect("verified")
    }
    pub(crate) fn private_strategy_revision_fingerprint(&self) -> &str {
        self.record["prepared_inputs"]["origin"]["private_strategy_revision_fingerprint"]
            .as_str()
            .expect("verified")
    }
    pub(crate) fn dataset_snapshot_fingerprint(&self) -> &str {
        self.record["prepared_inputs"]["dataset_snapshot_fingerprint"]
            .as_str()
            .expect("verified")
    }
    pub(crate) fn runtime_generation_fingerprint(&self) -> &str {
        self.record["prepared_inputs"]["origin"]["runtime_generation_fingerprint"]
            .as_str()
            .expect("verified")
    }
    pub(crate) fn preparation_command_id(&self) -> &str {
        self.record["prepared_inputs"]["origin"]["preparation_command_id"]
            .as_str()
            .expect("verified")
    }
    pub(crate) fn fingerprint(&self) -> &str {
        self.record["validation_fingerprint"]
            .as_str()
            .expect("verified")
    }
    pub(crate) fn record(&self) -> &Value {
        &self.record
    }
    pub(crate) fn source_locks(&self) -> Vec<Arc<SourceLock>> {
        self.cut.locks.clone()
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        self.cut.verify()
    }
    /// Bind this current preparation occurrence to the selected canonical
    /// strategy grant. Equivalent aliases and an earlier canonical promotion
    /// remain valid; current Dataset/runtime/algorithm evidence may not change.
    pub(crate) fn require_backtest_inputs(
        &self,
        operation: &research_preparation::Operation,
        source: &SourceRevision,
        dataset: &MaterializedDataset,
    ) -> Result<()> {
        self.verify_cut()?;
        let origin = Origin::from_operation(operation)?;
        let prepared = &self.record["prepared_inputs"];
        let ready = &operation.outputs["ready"];
        if prepared["origin"] != origin.record()
            || self.preparation_command_id() != operation.command.value()
            || ready["validation_fingerprint"] != self.fingerprint()
            || ready["admission"]["strategy_fingerprint"] != source.fingerprint()
            || self.source_revision().fingerprint() != source.fingerprint()
            || self.dataset_snapshot_fingerprint()
                != dataset.verified().dataset().snapshot_fingerprint()
            || prepared["dataset_manifest"] != *dataset.verified().manifest()
            || prepared["dataset_materialization"] != *dataset.lineage()
            || operation.outputs["environment"]["runtime_generation_fingerprint"]
                != self.runtime_generation_fingerprint()
            || ready["algorithm_resolution"] != prepared["algorithm_resolution"]
            || ready["algorithm_resolution_request"] != prepared["algorithm_resolution_request"]
            || ready["native_implementations"] != prepared["native_implementations"]
        {
            return Err(INVALID);
        }
        self.verify_cut()
    }
    pub(crate) async fn verify_in_transaction(
        &self,
        tx: &Transaction<'_>,
        namespace: &SemanticStoreId,
    ) -> Result<()> {
        self.verify_cut()?;
        if namespace != &self.namespace {
            return Err(INVALID);
        }
        deployment::verify_binding_in_transaction(tx, namespace)
            .await
            .map_err(|e| e.code())?;
        let origin = &self.record["prepared_inputs"]["origin"];
        let command = CommandId::new(self.preparation_command_id()).map_err(|_| INVALID)?;
        let operation = research_preparation::load(tx, &command, text(&origin["owner"])?).await?;
        let actual = Origin::from_operation(&operation)?;
        if actual.record() != *origin {
            return Err(INVALID);
        }
        verify_reference(tx, &actual, self.fingerprint()).await?;
        let (revision, factors) = validation::authoring(tx, &actual).await?;
        if self.record["prepared_inputs"]["strategy_revision"] != revision
            || self.record["prepared_inputs"]["factor_revisions"]
                != serde_json::to_value(factors).map_err(|_| INVALID)?
        {
            return Err(INVALID);
        }
        self.verify_cut()
    }
}
pub(crate) struct Store {
    research: Directory,
    owner: Directory,
    by_preparation: Directory,
    equivalence: Directory,
    runtime: Option<PathBuf>,
}
impl Store {
    /// Existing Infrastructure provision only; neither reads nor open repair owners.
    pub(crate) fn open(research_root: &Path) -> Result<Self> {
        let research = Directory::open(research_root).map_err(|_| UNAVAILABLE)?;
        let owner = research
            .path(&["backtest", "strategy-validation"], false)
            .map_err(|_| UNAVAILABLE)?;
        let by_preparation = owner
            .child("by-preparation", false)
            .map_err(|_| UNAVAILABLE)?;
        immutable_json::inspect_source_layout(&owner.path).map_err(|_| UNAVAILABLE)?;
        let equivalence = research
            .child("calculation-equivalence", false)
            .map_err(|_| UNAVAILABLE)?;
        immutable_json::inspect_source_layout(&equivalence.path).map_err(|_| UNAVAILABLE)?;
        equivalence
            .path(&["evidence-v2", "sha256"], false)
            .map_err(|_| UNAVAILABLE)?;
        let value = Self {
            research,
            owner,
            by_preparation,
            equivalence,
            runtime: None,
        };
        value.verify_layout()?;
        Ok(value)
    }
    pub(crate) fn with_runtime_root(mut self, runtime: &Path) -> Result<Self> {
        if !runtime.is_absolute()
            || runtime.components().any(|part| {
                matches!(
                    part,
                    std::path::Component::CurDir | std::path::Component::ParentDir
                )
            })
        {
            return Err(UNAVAILABLE);
        }
        protected_files::open_directory(runtime).map_err(|_| UNAVAILABLE)?;
        self.runtime = Some(runtime.into());
        Ok(self)
    }
    fn verify_layout(&self) -> Result<()> {
        self.research.verify()?;
        self.owner.verify()?;
        self.by_preparation.verify()?;
        self.equivalence.verify()?;
        immutable_json::inspect_source_layout(&self.equivalence.path)?;
        for name in self.owner.names()? {
            match name.as_str() {
                ".source-cut.lock" => {}
                "by-preparation" | ".immutable-json-staging" => {
                    self.owner.child(&name, false)?;
                }
                _ => return Err(INVALID),
            }
        }
        immutable_json::inspect_source_layout(&self.owner.path).map_err(|_| INVALID)
    }
    pub(crate) async fn read_verified(
        &self,
        client: &mut Client,
        id: &str,
    ) -> Result<VerifiedValidation> {
        let tx = client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::RepeatableRead)
            .read_only(true)
            .start()
            .await
            .map_err(|_| UNAVAILABLE)?;
        let value = self.read_verified_in_transaction(&tx, id).await?;
        value.verify_cut()?;
        tx.commit().await.map_err(|_| UNAVAILABLE)?;
        value.verify_cut()?;
        Ok(value)
    }
    pub(crate) async fn read_verified_in_transaction(
        &self,
        tx: &Transaction<'_>,
        id: &str,
    ) -> Result<VerifiedValidation> {
        let lock = Arc::new(SourceLock::publication(&self.owner.path)?);
        self.read_verified_captured_in_transaction(tx, id, vec![lock])
            .await
    }
    pub(crate) async fn read_verified_captured_in_transaction(
        &self,
        tx: &Transaction<'_>,
        id: &str,
        mut locks: Vec<Arc<SourceLock>>,
    ) -> Result<VerifiedValidation> {
        self.verify_layout()?;
        let command = CommandId::new(id).map_err(|_| INVALID)?;
        if !locks
            .iter()
            .any(|lock| lock.directory.path == self.owner.path)
        {
            locks.push(Arc::new(SourceLock::publication(&self.owner.path)?));
        }
        if !locks
            .iter()
            .any(|lock| lock.directory.path == self.equivalence.path)
        {
            locks.push(Arc::new(SourceLock::publication(&self.equivalence.path)?));
        }
        for lock in &locks {
            lock.verify()?;
        }
        let row=tx.query_opt("SELECT p.owner,v.validation_fingerprint FROM strategy_validation_publication v JOIN research_preparation p ON p.command_id=v.preparation_command_id WHERE v.preparation_command_id=$1::text::uuid",&[&id]).await.map_err(|_|UNAVAILABLE)?.ok_or("STRATEGY_VALIDATION_NOT_FOUND")?;
        let owner: String = row.try_get(0).map_err(|_| INVALID)?;
        let expected: String = row.try_get(1).map_err(|_| INVALID)?;
        let operation = research_preparation::load(tx, &command, &owner).await?;
        let origin = Origin::from_operation(&operation)?;
        verify_reference(tx, &origin, &expected).await?;
        let namespace =
            deployment::load_semantic_store_id_at(&self.research.fd).map_err(|e| e.code())?;
        deployment::verify_binding_in_transaction(tx, &namespace)
            .await
            .map_err(|e| e.code())?;
        let directory = self.by_preparation.child(id, false).map_err(|_| INVALID)?;
        physical::exact_files(&directory, &["manifest.json"])?;
        let (raw, file) = physical::read_file(&directory, "manifest.json")?;
        let record: Value = serde_json::from_slice(&raw).map_err(|_| INVALID)?;
        if canonical(&record)? != raw {
            return Err(INVALID);
        }
        let mut files = vec![physical::witness(&directory, "manifest.json", &raw, &file)?];
        if physical::document(&self.research, ".onlyalpha-semantic-store.json", &mut files)?
            != json!({"schema_version":1,"store_id":namespace.value()})
        {
            return Err(INVALID);
        }
        exact(
            &record,
            &[
                "schema_version",
                "contract",
                "semantic_store_id",
                "prepared_inputs",
                "installed_proof",
                "observation",
                "equivalence_evidence_fingerprints",
                "recorded_at",
                "validation_fingerprint",
            ],
        )?;
        let mut identity = record.clone();
        identity
            .as_object_mut()
            .ok_or(INVALID)?
            .remove("validation_fingerprint");
        if record["schema_version"] != 1
            || record["contract"] != CONTRACT
            || record["semantic_store_id"] != namespace.value()
            || record["validation_fingerprint"] != expected
            || fingerprint(&identity)? != expected
            || record["prepared_inputs"]["origin"] != origin.record()
            || record["recorded_at"] != origin.accepted["accepted_at"]
        {
            return Err(INVALID);
        }
        let prepared = &record["prepared_inputs"];
        exact(
            prepared,
            &[
                "semantic_store_id",
                "origin",
                "strategy_revision",
                "factor_revisions",
                "runtime_manifest",
                "runtime_work_binding",
                "execution_binding",
                "algorithm_resolution",
                "algorithm_resolution_request",
                "native_implementations",
                "decision",
                "implementation_bindings",
                "input_window",
                "dataset_snapshot_fingerprint",
                "dataset_manifest",
                "dataset_materialization",
                "dataset_construction_fingerprint",
                "source_revision",
            ],
        )?;
        if prepared["semantic_store_id"] != namespace.value() {
            return Err(INVALID);
        }
        let (revision, factors) = validation::authoring(tx, &origin).await?;
        if prepared["strategy_revision"] != revision
            || prepared["factor_revisions"]
                != serde_json::to_value(&factors).map_err(|_| INVALID)?
        {
            return Err(INVALID);
        }
        let definition = Definition::from_record(&revision["definition"])?;
        let decision = validation::decision(&definition, &prepared["algorithm_resolution"])?;
        if decision.record() != prepared["decision"] {
            return Err(INVALID);
        }
        let datasets = Datasets::open(&self.research.path.join("datasets"), 8192, WORK)?;
        let materialized = MaterializedDataset::load(
            &datasets,
            text(&prepared["dataset_materialization"]["materialization_id"])?,
        )?;
        if materialized.lineage() != &prepared["dataset_materialization"]
            || materialized.verified().manifest() != &prepared["dataset_manifest"]
            || materialized.verified().dataset().snapshot_fingerprint()
                != text(&prepared["dataset_snapshot_fingerprint"])?
            || materialized.verified().dataset().construction_fingerprint()
                != text(&prepared["dataset_construction_fingerprint"])?
            || validation::check_dataset(&definition, decision.graph(), &materialized)?
                != prepared["input_window"]
        {
            return Err(INVALID);
        }
        validation::check_source(&origin, &materialized)?;
        physical::capture_dataset(
            datasets.root(),
            materialized.verified().manifest(),
            materialized.lineage(),
            &mut files,
        )?;
        let mut runtime = RuntimeEvidenceHold::open(
            self.runtime.as_deref().ok_or(UNAVAILABLE)?,
            &origin.work,
            &origin.runtime_owner,
            &origin.generation,
        )?;
        let archive = runtime.strategy_validation_inputs(text(
            &prepared["algorithm_resolution"]["algorithm_artifact"],
        )?)?;
        if runtime.manifest() != &prepared["runtime_manifest"]
            || runtime.binding() != &prepared["runtime_work_binding"]
            || record["installed_proof"] != archive["installed_proof"]
        {
            return Err(INVALID);
        }
        verify_resolution(prepared, &archive, &factors, &definition)?;
        if validation::implementation_bindings(
            decision.graph(),
            &prepared["algorithm_resolution"],
            &prepared["native_implementations"],
            runtime.manifest(),
        )? != prepared["implementation_bindings"]
        {
            return Err(INVALID);
        }
        let source = source_revision(
            decision.graph(),
            &prepared["implementation_bindings"],
            &prepared["decision"]["signal_semantics"],
            materialized.verified().dataset().definition(),
            &prepared["dataset_manifest"]["provenance"][0]["source_metadata"]["construction_recipe"],
        )?;
        if source.to_record() != prepared["source_revision"] {
            return Err(INVALID);
        }
        let evidence = verify_observation(prepared, &record["observation"], &materialized)?;
        let ids = evidence
            .iter()
            .map(|e| e["evidence_fingerprint"].clone())
            .collect::<Vec<_>>();
        if record["equivalence_evidence_fingerprints"] != json!(ids) {
            return Err(INVALID);
        }
        for evidence in evidence {
            let id = text(&evidence["evidence_fingerprint"])?;
            let directory = self
                .equivalence
                .path(&["evidence-v2", "sha256", &id[..2], id], false)?;
            physical::exact_files(&directory, &["manifest.json"])?;
            if physical::document(&directory, "manifest.json", &mut files)? != evidence {
                return Err(INVALID);
            }
        }
        let image = &record["observation"]["producer"]["native_image"];
        let e = &prepared["execution_binding"];
        if image["artifact"] != e["executor_artifact_sha256"]
            || image["version"] != e["executor_version"]
            || image["protocol"] != e["protocol"]
            || record["observation"]["producer"]["algorithm_artifact_fingerprint"]
                != prepared["algorithm_resolution"]["algorithm_artifact"]
        {
            return Err(INVALID);
        }
        let cut = Arc::new(ReadCut {
            runtime: Arc::new(runtime),
            files,
            locks,
        });
        let value = VerifiedValidation {
            record,
            source,
            namespace,
            cut,
        };
        value.verify_in_transaction(tx, &value.namespace).await?;
        self.verify_layout()?;
        Ok(value)
    }
    /// Only the real joined producer can enroll an occurrence. An orphan file
    /// has no proof of join and is never trusted by a read or automatic repair.
    pub(crate) async fn publish(
        &self,
        session: &mut AuthoritySession,
        joined: JoinedValidation,
    ) -> Result<VerifiedValidation> {
        self.verify_layout()?;
        joined.verify_cut()?;
        let namespace =
            deployment::load_semantic_store_id_at(&self.research.fd).map_err(|e| e.code())?;
        let origin = joined.origin();
        let mut runtime = RuntimeEvidenceHold::open(
            self.runtime.as_deref().ok_or(UNAVAILABLE)?,
            &origin.work,
            &origin.runtime_owner,
            &origin.generation,
        )?;
        let installed = runtime.strategy_validation_inputs(text(
            &joined.record()["algorithm_resolution"]["algorithm_artifact"],
        )?)?;
        let datasets = Datasets::open(&self.research.path.join("datasets"), 8192, WORK)?;
        let materialized = MaterializedDataset::load(
            &datasets,
            text(&joined.record()["dataset_materialization"]["materialization_id"])?,
        )?;
        let evidence = verify_observation(joined.record(), joined.observation(), &materialized)?;
        if joined.record()["semantic_store_id"] != namespace.value() {
            return Err(INVALID);
        }
        let ids = evidence
            .iter()
            .map(|e| e["evidence_fingerprint"].clone())
            .collect::<Vec<_>>();
        let mut record = json!({"schema_version":1,"contract":CONTRACT,"semantic_store_id":namespace.value(),"prepared_inputs":joined.record(),
            "installed_proof":installed["installed_proof"],"observation":joined.observation(),"equivalence_evidence_fingerprints":ids,"recorded_at":origin.accepted["accepted_at"]});
        let identity = fingerprint(&record)?;
        record["validation_fingerprint"] = json!(identity);
        let raw = canonical(&record)?;
        let source = Arc::new(SourceLock::publication(&self.owner.path)?);
        let equivalence_source = Arc::new(SourceLock::publication(&self.equivalence.path)?);
        let mut owned = session.take_ownership();
        let mut mutated = false;
        let result=async {
            let tx=owned.client_mut().await.map_err(|_|UNAVAILABLE)?.build_transaction().isolation_level(tokio_postgres::IsolationLevel::Serializable).start().await.map_err(|_|UNAVAILABLE)?;
            crate::persistence::postgres::bounds(&tx).await.map_err(|_|UNAVAILABLE)?;
            crate::persistence::postgres::Commands::lock_command(&tx,&origin.command).await.map_err(|_|UNAVAILABLE)?;
            deployment::verify_binding_in_transaction(&tx,&namespace).await.map_err(|e|e.code())?;
            let original=research_preparation::load(&tx,&origin.command,&origin.owner).await?;
            if Origin::from_operation(&original)?.record()!=origin.record(){return Err(INVALID);}
            if tx.query_opt("SELECT 1 FROM strategy_validation_publication WHERE preparation_command_id=$1::text::uuid",&[&origin.command.value()]).await.map_err(|_|UNAVAILABLE)?.is_some() {
                let existing=self.read_verified_captured_in_transaction(&tx,origin.command.value(),vec![source.clone(),equivalence_source.clone()]).await?;
                if existing.record()!=&record{return Err(INVALID);}joined.verify_cut()?;AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNAVAILABLE)?;
                tx.commit().await.map_err(|_|UNKNOWN)?;return Ok(existing);
            }
            if !matches!(original.state,State::Running|State::InputPending){return Err("STRATEGY_VALIDATION_PREPARATION_NOT_RUNNING");}
            research_preparation::require_current(&tx,&original).await?;
            let actual=validation::authoring(&tx,origin).await?;
            if joined.record()["strategy_revision"]!=actual.0||joined.record()["factor_revisions"]!=serde_json::to_value(actual.1).map_err(|_|INVALID)?{return Err(INVALID);}
            joined.verify_cut()?;source.verify()?;runtime.verify()?;AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNAVAILABLE)?;
            for value in &evidence {
                let id=text(&value["evidence_fingerprint"])?;
                equivalence_source.verify()?;
                immutable_json::put_at(self.equivalence.fd.as_fd(),&["evidence-v2","sha256",&id[..2],id],"manifest.json",value)?;
            }
            let files=BTreeMap::from([("manifest.json".into(),raw)]);
            immutable_json::put_bundle_at(self.owner.fd.as_fd(),&["by-preparation",origin.command.value()],&files,WORK)?;
            joined.verify_cut()?;source.verify()?;runtime.verify()?;
            mutated=true;
            tx.execute("INSERT INTO strategy_validation_publication(preparation_command_id,validation_fingerprint,accepted_fingerprint,private_strategy_id,private_strategy_revision_fingerprint,recorded_at) VALUES($1::text::uuid,$2,$3,$4,$5,$6::text::timestamptz)",&[&origin.command.value(),&identity,&origin.accepted_fingerprint,&origin.strategy_id,&origin.strategy_revision_fingerprint,&text(&origin.accepted["accepted_at"])?]).await.map_err(|_|UNKNOWN)?;
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(|_|UNKNOWN)?;
            let verified=self.read_verified_captured_in_transaction(&tx,origin.command.value(),vec![source.clone(),equivalence_source.clone()]).await?;
            if verified.record()!=&record||verified.source_revision()!=joined.source_revision(){return Err(INVALID);}
            joined.verify_cut()?;verified.verify_in_transaction(&tx,&namespace).await?;AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNAVAILABLE)?;
            tx.commit().await.map_err(|_|UNKNOWN)?;joined.verify_cut()?;verified.verify_cut()?;Ok(verified)
        }.await;
        // A pending commit never reconnects, invents a new task, or enrolls a
        // file on faith. Recovery queries this same preparation occurrence.
        if let Err(code) = &result {
            if mutated {
                return Err(UNKNOWN);
            }
            let code = *code;
            if owned.verify().await.is_ok() {
                session.restore_ownership(owned);
            }
            return Err(code);
        }
        owned.verify().await.map_err(|_| UNKNOWN)?;
        session.restore_ownership(owned);
        result
    }
}
async fn verify_reference(tx: &Transaction<'_>, origin: &Origin, expected: &str) -> Result<()> {
    let row=tx.query_opt("SELECT validation_fingerprint,accepted_fingerprint,private_strategy_id,private_strategy_revision_fingerprint,recorded_at=$2::text::timestamptz FROM strategy_validation_publication WHERE preparation_command_id=$1::text::uuid",&[&origin.command.value(),&text(&origin.accepted["accepted_at"])?]).await.map_err(|_|UNAVAILABLE)?.ok_or("STRATEGY_VALIDATION_NOT_FOUND")?;
    if row.try_get::<_, String>(0).map_err(|_| INVALID)? != expected
        || row.try_get::<_, String>(1).map_err(|_| INVALID)? != origin.accepted_fingerprint
        || row.try_get::<_, String>(2).map_err(|_| INVALID)? != origin.strategy_id
        || row.try_get::<_, String>(3).map_err(|_| INVALID)? != origin.strategy_revision_fingerprint
        || !row.try_get::<_, bool>(4).map_err(|_| INVALID)?
    {
        return Err(INVALID);
    }
    Ok(())
}
