//! Native next-open admission values and non-portable owning proofs.
use crate::{
    application::{backtest_preparation::BacktestOrigin,command::{self, CommandId}, factor_content::hash, research_dataset::MaterializedDataset, source_access::{self, Permission, Selection}},
    bootstrap::deployment::SemanticStoreId,
    persistence::{research_preparation::{self,Operation},strategy_validation::VerifiedValidation,research_evidence::strategy::physical::{Witness,capture_dataset},backtest_evidence::CompletionProof, research_dataset::Store, research_runtime::RuntimeInputHold, strategy_promotion::VerifiedBacktestAdmission},
    security::human_access,
    workers::backtest::PreparedNextOpen,
};
use onlyalpha_domain::base::OnlyDomainModel;
use serde_json::{Value, json};
#[cfg(test)]
use {crate::security::immutable_json::SourceLock, std::sync::Arc};
pub(crate) type Result<T> = std::result::Result<T, &'static str>;
pub(crate) const INVALID: &str = "BACKTEST_RUN_INPUT_INVALID";
pub(crate) const MISMATCH: &str = "BACKTEST_RUN_PROOF_MISMATCH";
pub(crate) fn fields(v: &Value, names: &[&str]) -> Result<()> {
    let object = v.as_object().ok_or(INVALID)?;
    if object.len() != names.len() || names.iter().any(|k| !object.contains_key(*k)) { return Err(INVALID); }
    Ok(())
}
pub(crate) fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key].as_str().filter(|s| !s.is_empty()).ok_or(INVALID)
}
fn pin(v: &Value, key: &str) -> Result<()> {
    if !crate::is_sha256_hex(text(v, key)?) { return Err(INVALID); } Ok(())
}
#[derive(Clone)]
pub struct Specification(Value);
impl Specification {
    pub fn from_record(v: &Value) -> Result<Self> {
        fields(v, &["schema_version", "kind", "strategy_fingerprint", "dataset_snapshot_fingerprint", "runtime_generation_fingerprint", "preparation_fingerprint"])?;
        if v["schema_version"] != 3 || v["kind"] != "BTC_SPOT_NEXT_OPEN" { return Err(INVALID); }
        for key in ["strategy_fingerprint", "dataset_snapshot_fingerprint", "runtime_generation_fingerprint", "preparation_fingerprint"] { pin(v, key)?; }
        Ok(Self(v.clone()))
    }
    pub fn record(&self) -> &Value { &self.0 }
    pub fn fingerprint(&self) -> Result<String> { hash(&self.0) }
}
pub struct CreateRequest { command: CommandId, run: String, specification: Specification }
impl CreateRequest {
    pub fn new(command: CommandId, run: &str, specification: Specification) -> Result<Self> {
        if !command::uuid4(run) { return Err(INVALID); }
        Ok(Self { command, run: run.into(), specification })
    }
    pub fn command_id(&self) -> &CommandId { &self.command }
    pub fn run_id(&self) -> &str { &self.run }
    pub fn specification(&self) -> &Specification { &self.specification }
    pub(crate) fn fingerprint(&self, owner: &str, resolution: &str) -> Result<String> {
        hash(&json!({"contract":"ONLYALPHA_NEXT_OPEN_BACKTEST_CREATE_V1","owner":owner,"run_id":self.run,"specification":self.specification.record(),"admission_resolution_fingerprint":resolution}))
    }
}
pub struct CancelRequest { command: CommandId, run: String }
impl CancelRequest {
    pub fn new(command: CommandId, run: &str) -> Result<Self> {
        if !command::uuid4(run) { return Err(INVALID); }
        Ok(Self { command, run: run.into() })
    }
    pub fn command_id(&self) -> &CommandId { &self.command }
    pub fn run_id(&self) -> &str { &self.run }
    pub(crate) fn fingerprint(&self, owner: &str) -> Result<String> {
        hash(&json!({"contract":"ONLYALPHA_BACKTEST_CANCEL_V1","owner":owner,"run_id":self.run}))
    }
}
/// Authentication and Source permission remain separate issuer-bound checks.
pub struct Context<'a> {
    pub human_authority: &'a human_access::Access,
    pub human: &'a human_access::Session,
    pub source_authority: &'a source_access::Authority,
    pub source: &'a source_access::Session,
    pub selection: &'a Selection,
}
impl Context<'_> {
    pub(crate) fn owner(&self) -> Result<&str> {
        self.human_authority.check_session(self.human).map_err(|_| "BACKTEST_HUMAN_AUTHORIZATION_REQUIRED")?;
        self.human.subject_id().map_err(|_| "BACKTEST_HUMAN_AUTHORIZATION_REQUIRED")
    }
    pub(crate) fn source(&self) -> Result<()> {
        self.source_authority.check_session(self.source).map_err(|_| "BACKTEST_SOURCE_ACCESS_DENIED")?;
        if self.source.subject_id().map_err(|_| "BACKTEST_SOURCE_ACCESS_DENIED")? != self.owner()? { return Err("BACKTEST_SOURCE_ACCESS_DENIED"); }
        self.source.require_selection(self.selection, Permission::ClosedHistory).map_err(|_| "BACKTEST_SOURCE_ACCESS_DENIED")
    }
}
fn selection_record(selection: &Selection) -> Value {
    json!({"integration_id":selection.reference().integration_id(),"revision_fingerprint":selection.reference().revision(),"expected_type_id":selection.reference().expected_type_id(),"source_id":selection.source_id(),"environment":selection.environment()})
}
enum Holds<'a> {
    Owners { prepared: &'a PreparedNextOpen, admission: &'a VerifiedBacktestAdmission, runtime: &'a RuntimeInputHold, dataset: &'a MaterializedDataset, datasets: &'a Store, operation:&'a Operation, validation:Option<&'a VerifiedValidation>, files:Vec<Witness> },
    #[cfg(test)]
    Value { namespace: SemanticStoreId, cut: Arc<SourceLock> },
}
/// Retained owning borrows, not a deserializable execution grant.
pub struct Inputs<'a> { specification: Specification, resolution: Value, holds: Holds<'a> }
impl<'a> Inputs<'a> {
    pub(crate) fn new(prepared: &'a PreparedNextOpen, admission: &'a VerifiedBacktestAdmission, runtime: &'a mut RuntimeInputHold, dataset: &'a MaterializedDataset, datasets: &'a Store, operation:&'a Operation, validation:Option<&'a VerifiedValidation>) -> Result<Self> {
        admission.verify_cut()?;
        let input=operation.request.backtest()?;let ready=&operation.outputs["ready"];
        match (&input.origin,validation) {
            (BacktestOrigin::ManualStrategy{..},Some(proof))=>proof.require_backtest_inputs(operation,admission.source_revision(),dataset)?,
            (BacktestOrigin::FrozenStrategy{strategy_fingerprint,freeze_relation_fingerprint,qualification_decision_fingerprint,promotion_fingerprint},None)=>{
                if strategy_fingerprint!=admission.strategy_fingerprint()||freeze_relation_fingerprint!=admission.freeze_relation_fingerprint()
                    ||qualification_decision_fingerprint!=admission.qualification_decision_fingerprint()||promotion_fingerprint!=admission.promotion_fingerprint()
                    ||!ready["validation_fingerprint"].is_null(){return Err(MISMATCH);}
            },_=>return Err(MISMATCH),
        }
        let mut files=Vec::new();capture_dataset(datasets.root(),dataset.verified().manifest(),dataset.lineage(),&mut files)?;
        let root=crate::security::immutable_json::Directory::open(datasets.root().parent().ok_or(MISMATCH)?)?;
        if crate::persistence::research_evidence::strategy::physical::document(&root,".onlyalpha-semantic-store.json",&mut files)?!=json!({"schema_version":1,"store_id":admission.namespace().value()}){return Err(MISMATCH);}
        for (key,value) in [("strategy_fingerprint",admission.strategy_fingerprint()),("freeze_relation_fingerprint",admission.freeze_relation_fingerprint()),("qualification_decision_fingerprint",admission.qualification_decision_fingerprint()),("promotion_fingerprint",admission.promotion_fingerprint())] {
            if ready["admission"][key]!=value{return Err(MISMATCH);}
        }
        // The actual held image performs fresh physical and capability checks.
        let execution_binding = runtime.backtest_execution_binding()?;
        let preparation = prepared.record();
        let sources = prepared.inputs().record();
        let source = sources["sources"].as_array().filter(|s| s.len() == 1).ok_or(INVALID)?.first().ok_or(INVALID)?;
        let generation = text(runtime.manifest(), "runtime_generation_fingerprint")?;
        let specification = Specification::from_record(&json!({"schema_version":3,"kind":"BTC_SPOT_NEXT_OPEN","strategy_fingerprint":admission.strategy_fingerprint(),"dataset_snapshot_fingerprint":source["snapshot"],"runtime_generation_fingerprint":generation,"preparation_fingerprint":hash(&preparation)?}))?;
        let resolution = json!({"schema_version":2,"kind":"BTC_SPOT_NEXT_OPEN_ADMISSION","owner":null,"semantic_store_id":admission.namespace().value(),"strategy_fingerprint":admission.strategy_fingerprint(),"freeze_relation_fingerprint":admission.freeze_relation_fingerprint(),"qualification_decision_fingerprint":admission.qualification_decision_fingerprint(),"promotion_fingerprint":admission.promotion_fingerprint(),"dataset_snapshot_fingerprint":source["snapshot"],"dataset_binding_fingerprint":source["dataset_binding"],"runtime_generation_fingerprint":generation,"preparation_fingerprint":hash(&preparation)?,"preparation":preparation,"dataset_materialization":dataset.lineage(),"runtime_work_binding":runtime.binding(),"backtest_binding":execution_binding,"source_selection":null});
        let value = Self { specification, resolution, holds: Holds::Owners { prepared, admission, runtime, dataset, datasets,operation,validation,files } };
        value.verify_cut()?;
        Ok(value)
    }
    pub fn specification(&self) -> &Specification { &self.specification }
    pub(crate) fn namespace(&self) -> &SemanticStoreId {
        match &self.holds { Holds::Owners { admission, .. } => admission.namespace(), #[cfg(test)] Holds::Value { namespace, .. } => namespace }
    }
    pub(crate) async fn verify_transaction(&self,tx:&tokio_postgres::Transaction<'_>,namespace:&SemanticStoreId)->Result<()> {
        match &self.holds {
            Holds::Owners {admission,operation,validation,..}=>{
                self.verify_cut()?;admission.verify_in_transaction(tx,namespace).await?;
                research_preparation::guard_submission(tx,operation,text(self.specification.record(),"preparation_fingerprint")?).await?;
                if let Some(validation)=validation{validation.verify_in_transaction(tx,namespace).await?;}
                self.verify_cut()
            },
            #[cfg(test)] Holds::Value {namespace:original,cut}=> {
                if original!=namespace {return Err(MISMATCH);}
                cut.verify()?;
                crate::bootstrap::deployment::verify_binding_in_transaction(tx,namespace).await.map_err(|_|MISMATCH)
            }
        }
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        match &self.holds {
            Holds::Owners { prepared, admission, runtime, dataset, datasets,operation,validation,files } => {
                admission.verify_cut()?;runtime.verify()?;for file in files{file.verify()?;}
                if let Some(validation)=validation{validation.require_backtest_inputs(operation,admission.source_revision(),dataset)?;}
                if operation.request.reserved_run_id()!=self.resolution["runtime_work_binding"]["work_id"]
                    ||operation.request.future_command()!=self.resolution["runtime_work_binding"]["reason"]
                    ||operation.outputs["ready"]["specification"]!=*self.specification.record()
                    ||operation.outputs["ready"]["preparation"]!=self.resolution["preparation"]{return Err(MISMATCH);}
                let reread = MaterializedDataset::load(datasets, text(dataset.lineage(), "materialization_id")?)?;
                if reread.lineage() != dataset.lineage() || reread.verified().manifest() != dataset.verified().manifest() { return Err(MISMATCH); }
                let bars = reread.verified().dataset().bars()?;
                if bars.len() != prepared.inputs().records().len() || bars.iter().zip(prepared.inputs().records()).any(|(bar, input)| bar.to_record() != input.bar().to_record()) { return Err(MISMATCH); }
                let input = prepared.inputs().record();
                let source = &input["sources"][0];
                let scope = &reread.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"]["scope"];
                if prepared.record()["strategy_fingerprint"] != admission.strategy_fingerprint()
                    || source["snapshot"] != reread.verified().dataset().snapshot_fingerprint()
                    || source["dataset_binding"] != reread.lineage()["request_fingerprint"]
                    || source["data_version"] != scope["data_version"]
                    || self.resolution["runtime_generation_fingerprint"] != runtime.manifest()["runtime_generation_fingerprint"]
                    || &self.resolution["runtime_work_binding"] != runtime.binding() { return Err(MISMATCH); }
                Ok(())
            }
            #[cfg(test)] Holds::Value { cut, .. } => cut.verify(),
        }
    }
    pub(crate) fn resolve(&self, owner: &str, selection: &Selection) -> Result<Value> {
        self.verify_cut()?;
        let mut value = self.resolution.clone();
        match &self.holds {
            Holds::Owners { dataset, .. } => {
                let scope = &dataset.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"]["scope"];
                if scope["source_id"] != selection.source_id() || scope["bar_construction"]["plan"]["integration_revision_fingerprint"] != selection.reference().revision() { return Err("BACKTEST_SOURCE_ACCESS_DENIED"); }
                value["owner"] = owner.into(); value["source_selection"] = selection_record(selection);
            }
            #[cfg(test)] Holds::Value { .. } => { if value["owner"] != owner || value["source_selection"] != selection_record(selection) { return Err(MISMATCH); } }
        }
        validate_resolution(&self.specification, &value, self.namespace())?;
        Ok(value)
    }
    #[cfg(test)]
    pub(crate) fn for_value_test(specification: Specification, resolution: Value, namespace: SemanticStoreId, cut: Arc<SourceLock>) -> Result<Inputs<'static>> {
        validate_resolution(&specification, &resolution, &namespace)?; cut.verify()?;
        Ok(Inputs { specification, resolution, holds: Holds::Value { namespace, cut } })
    }
}
pub(crate) fn validate_resolution(specification: &Specification, value: &Value, namespace: &SemanticStoreId) -> Result<()> {
    fields(value, &["schema_version","kind","owner","semantic_store_id","strategy_fingerprint","freeze_relation_fingerprint","qualification_decision_fingerprint","promotion_fingerprint","dataset_snapshot_fingerprint","dataset_binding_fingerprint","runtime_generation_fingerprint","preparation_fingerprint","preparation","dataset_materialization","runtime_work_binding","backtest_binding","source_selection"])?;
    if value["schema_version"] != 2 || value["kind"] != "BTC_SPOT_NEXT_OPEN_ADMISSION" || value["semantic_store_id"] != namespace.value() { return Err(INVALID); }
    text(value,"owner")?;
    for key in ["strategy_fingerprint","dataset_snapshot_fingerprint","runtime_generation_fingerprint","preparation_fingerprint"] { if value[key] != specification.record()[key] { return Err(MISMATCH); } }
    for key in ["freeze_relation_fingerprint","qualification_decision_fingerprint","promotion_fingerprint","dataset_binding_fingerprint"] { pin(value,key)?; }
    let preparation = &value["preparation"];
    fields(preparation, &["schema_version","contract","strategy_fingerprint","input_pin","settings","policy_binding","window","initial_ns"])?;
    if preparation["schema_version"] != 1 || preparation["contract"] != "ONLYALPHA_BTC_NEXT_OPEN_PREPARATION_V1" || preparation["strategy_fingerprint"] != value["strategy_fingerprint"] || hash(preparation)? != text(value,"preparation_fingerprint")? || preparation["settings"]["schema_version"] != 2 || preparation["settings"]["execution"]["runtime_kind"] != "BACKTEST" || preparation["settings"]["execution"]["generation"] != value["runtime_generation_fingerprint"] || !preparation["policy_binding"].is_object() || !preparation["window"].is_object() { return Err(MISMATCH); }
    pin(preparation,"input_pin")?;
    let binding = &value["backtest_binding"];
    fields(binding, &["executor_manifest_fingerprint","executor_artifact_sha256","executor_version","core_execution_fingerprint","protocol"])?;
    for key in ["executor_manifest_fingerprint","executor_artifact_sha256","core_execution_fingerprint"] { pin(binding,key)?; }
    text(binding,"executor_version")?;
    if binding["protocol"] != "onlyalpha.backtest.executor/1" || !value["dataset_materialization"].is_object() || value["dataset_materialization"]["dataset_snapshot_fingerprint"] != value["dataset_snapshot_fingerprint"] { return Err(MISMATCH); }
    let work = &value["runtime_work_binding"];
    if !matches!(work["kind"].as_str(),Some("RuntimeWorkBound"|"RuntimeExactWorkBound")) || work["generation_fingerprint"] != value["runtime_generation_fingerprint"] || !command::uuid4(text(work,"work_id")?) || !command::uuid4(text(work,"reason")?) { return Err(MISMATCH); }
    let selection = &value["source_selection"];
    fields(selection, &["integration_id","revision_fingerprint","expected_type_id","source_id","environment"])?;
    for key in ["integration_id","source_id","environment"] { text(selection,key)?; } pin(selection,"revision_fingerprint")?;
    if !selection["expected_type_id"].is_null() { text(selection,"expected_type_id")?; }
    Ok(())
}
/// Only the persistence owner constructs its private RunBinding after exact reads.
#[derive(Clone)]
pub struct VerifiedRun { pub(crate) binding: crate::persistence::backtest_run::RunBinding }
impl VerifiedRun {
    pub fn run_id(&self) -> &str { self.binding.run_id() }
    pub fn state(&self)->crate::persistence::backtest_run::RunState {self.binding.state()}
    pub fn was_started(&self)->bool {self.binding.was_started()}
    pub fn completion_fingerprints(&self)->Option<(&str,&str,&str)> {self.binding.completion_fingerprints()}
    pub fn specification(&self) -> &Specification { self.binding.specification() }
    pub fn specification_fingerprint(&self) -> &str { self.binding.specification_fingerprint() }
    pub fn admission_resolution_fingerprint(&self) -> &str { self.binding.admission_resolution_fingerprint() }
    pub fn namespace(&self) -> &SemanticStoreId { self.binding.namespace() }
    pub fn owner(&self) -> &str { self.binding.owner() }
    pub fn resolution(&self) -> &Value { self.binding.resolution() }
    pub fn canonical_specification_payload(&self) -> &str { self.binding.canonical_specification_payload() }
    pub fn runtime_generation_fingerprint(&self) -> &str { self.binding.runtime_generation_fingerprint() }
    pub fn record(&self) -> Value { self.binding.record() }
}
pub struct VerifiedCompletion { proof: CompletionProof }
impl VerifiedCompletion {
    pub fn from_proof(proof: CompletionProof) -> Result<Self> {
        proof.verify_cut()?;
        if !command::uuid4(proof.run_id()) || !matches!(proof.status(),"COMPLETED"|"CANCELLED") || [proof.specification_fingerprint(),proof.admission_resolution_fingerprint(),proof.evidence_fingerprint(),proof.result_fingerprint(),proof.determinism_fingerprint()].iter().any(|p| !crate::is_sha256_hex(p)) { return Err(MISMATCH); }
        Ok(Self { proof })
    }
    pub(crate) fn proof(&self) -> &CompletionProof { &self.proof }
}
// Test-first: values below prove the new specification language, never admission.
#[cfg(test)]
mod tests {
    use super::{CreateRequest, Specification};
    use crate::application::command::CommandId;
    use serde_json::{Value,json};
    fn record() -> Value {
        json!({"schema_version":3,"kind":"BTC_SPOT_NEXT_OPEN","strategy_fingerprint":"a".repeat(64),"dataset_snapshot_fingerprint":"b".repeat(64),"runtime_generation_fingerprint":"c".repeat(64),"preparation_fingerprint":"d".repeat(64)})
    }
    #[test]
    fn specification3_is_an_exact_reference_value_without_execution_permission() {
        let original=record();let value=Specification::from_record(&original).unwrap();
        assert_eq!(value.record(),&original);
        assert_eq!(value.fingerprint().unwrap(),crate::application::factor_content::hash(&original).unwrap());
        let mut detached=value.record().clone();detached["kind"]=json!("LIVE");
        assert_eq!(value.record(),&original);
        for field in ["strategy_fingerprint","dataset_snapshot_fingerprint","runtime_generation_fingerprint","preparation_fingerprint"] {
            let mut changed=original.clone();changed[field]=json!("e".repeat(64));
            assert_ne!(Specification::from_record(&changed).unwrap().fingerprint().unwrap(),value.fingerprint().unwrap());
        }
    }
    #[test]
    fn specification3_rejects_unknown_versions_fields_and_non_exact_pins() {
        for mutation in 0..7 {
            let mut record=record();
            match mutation {
                0=>record["schema_version"]=json!(true),
                1=>record["schema_version"]=json!(2),
                2=>record["kind"]=json!("LIVE"),
                3=>record["granted"]=json!(true),
                4=>record["preparation_fingerprint"]=Value::Null,
                5=>record["strategy_fingerprint"]=json!("A".repeat(64)),
                _=>{record.as_object_mut().unwrap().remove("dataset_snapshot_fingerprint");},
            }
            assert!(Specification::from_record(&record).is_err(),"mutation {mutation}");
        }
    }
    #[test]
    fn create_intent_keeps_the_original_command_run_and_preparation_identity() {
        let command=CommandId::new("00000000-0000-4000-8000-000000000801").unwrap();
        let spec=Specification::from_record(&record()).unwrap();
        let request=CreateRequest::new(command.clone(),"00000000-0000-4000-8000-000000000802",spec).unwrap();
        assert_eq!(request.command_id(),&command);
        assert_eq!(request.run_id(),"00000000-0000-4000-8000-000000000802");
        assert_eq!(request.specification().record(),&record());
        assert!(CreateRequest::new(command,"arbitrary-new-run",Specification::from_record(&record()).unwrap()).is_err());
    }
}
