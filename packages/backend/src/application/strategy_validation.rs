//! Finite installed-graph validation for an accepted manual experimental Backtest.
//! No Research Context, Run, Target, Result or Statistics and no Freeze/Run grant.
use crate::{application::{backtest_preparation::BacktestOrigin,command::CommandId,
    private_assets,private_strategy::Definition,research_admission::{PreparationError,select_strategy_implementations,observed_strategy_node},
    research_dataset::MaterializedDataset,research_run_execution::Control,
    strategy_research::{DecisionGraph,ResolvedCalculations,canonical_input_window,observe_graph,source_revision}},
    persistence::{research_dataset::Store as Datasets,research_preparation::Operation,research_runtime::RuntimeInputHold,
        research_evidence::strategy::physical::{Witness,capture_dataset}}};
use onlyalpha_calculation::product::Graph;
use onlyalpha_calculation_bridge::ChartInstallation;
use onlyalpha_domain::time::{OnlyTimestamp,OnlyUtcDateTime};
use onlyalpha_strategy::SourceRevision;
use serde_json::{Value,json};
use std::{collections::BTreeMap,sync::Arc};
use tokio_postgres::{Client,Transaction};
pub(crate) const WORK:usize=8*1024*1024;
pub(crate) const INVALID:&str="STRATEGY_VALIDATION_INPUT_MISMATCH";
pub(crate) const UNAVAILABLE:&str="STRATEGY_VALIDATION_UNAVAILABLE";
type Result<T>=std::result::Result<T,&'static str>;
#[cfg(test)] mod tests;

/// Only a typed request loaded by the original preparation owner selects origin.
/// Its record is provenance, never a constructor for an execution capability.
pub(crate) struct Origin {
    pub(crate) command:CommandId,pub(crate) owner:String,pub(crate) accepted:Value,
    pub(crate) accepted_fingerprint:String,pub(crate) strategy_id:String,
    pub(crate) strategy_revision_fingerprint:String,pub(crate) work:String,
    pub(crate) runtime_owner:String,pub(crate) generation:String,
}
impl Origin {
    pub(crate) fn from_operation(operation:&Operation)->Result<Self> {
        let input=operation.request.backtest()?;input.validate(&operation.command)?;
        let BacktestOrigin::ManualStrategy{strategy_id,strategy_revision_fingerprint}=&input.origin else{return Err(INVALID);};
        if operation.accepted["schema_version"]!=2||operation.accepted["contract"]!="ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V2"
            ||operation.accepted["runtime_work_id"]!=operation.request.reserved_run_id()
            ||operation.accepted["semantic_store_id"].as_str().is_none_or(|v|!crate::application::command::uuid4(v))
            ||operation.owner.is_empty()||operation.accepted["command_id"]!=operation.command.value()
            ||operation.accepted["owner"]!=operation.owner||operation.accepted["input"]!=serde_json::to_value(input).map_err(|_|INVALID)? {return Err(INVALID);}
        let environment=&operation.outputs["environment"];
        let generation=environment["runtime_generation_fingerprint"].as_str().filter(|s|crate::is_sha256_hex(s)).ok_or(INVALID)?.to_owned();
        if environment["binding"]["kind"]!="RuntimeWorkBound"||environment["binding"]["work_id"]!=operation.request.reserved_run_id()
            ||environment["binding"]["reason"]!=operation.request.future_command()||environment["binding"]["generation_fingerprint"]!=generation{return Err(INVALID);}
        Ok(Self{command:operation.command.clone(),owner:operation.owner.clone(),accepted:operation.accepted.clone(),
            accepted_fingerprint:crate::application::factor_content::hash(&operation.accepted)?,strategy_id:strategy_id.clone(),
            strategy_revision_fingerprint:strategy_revision_fingerprint.clone(),work:operation.request.reserved_run_id(),
            runtime_owner:operation.request.future_command().into(),generation})
    }
    pub(crate) fn record(&self)->Value {json!({"preparation_command_id":self.command.value(),"owner":self.owner,
        "accepted_fingerprint":self.accepted_fingerprint,"accepted_preparation":self.accepted,
        "private_strategy_id":self.strategy_id,"private_strategy_revision_fingerprint":self.strategy_revision_fingerprint,
        "runtime_work_id":self.work,"runtime_owner":self.runtime_owner,"runtime_generation_fingerprint":self.generation})}
}
/// Exact owning reads, shared by execution preparation and historical verification.
pub(crate) async fn authoring(tx:&Transaction<'_>,origin:&Origin)->Result<(Value,BTreeMap<String,Value>)> {
    let revision=private_assets::strategy_revision_in_transaction(tx,&origin.strategy_id,&origin.strategy_revision_fingerprint).await.map_err(|e|e.code())?;
    let mut factors=BTreeMap::new();
    for dependency in revision["definition"]["factor_revision_dependencies"].as_array().ok_or(INVALID)? {
        let id=dependency["factor_id"].as_str().ok_or(INVALID)?;
        let pin=dependency["revision_fingerprint"].as_str().ok_or(INVALID)?;
        let factor=private_assets::factor_revision_in_transaction(tx,id,pin).await.map_err(|e|e.code())?;
        if factors.insert(id.to_owned(),factor).is_some(){return Err(INVALID);}
    }
    Ok((revision,factors))
}
pub(crate) fn ns(text:&str)->Result<u64> {
    let at:OnlyUtcDateTime=text.parse().map_err(|_|INVALID)?;
    OnlyTimestamp::from_datetime(at).unix_nanos().to_string().parse().map_err(|_|INVALID)
}
/// The fixed Product profile uses close events after each requested open time.
/// Targetless validation has no future observation or protected-period input.
pub(crate) fn validation_window(graph:&Graph)->Result<Value> {
    let stride=60_000_000_000;
    let mut window=canonical_input_window(graph,ns("2025-01-03T00:00:00Z")?.checked_add(stride).ok_or(INVALID)?,ns("2025-01-03T12:00:00Z")?.checked_add(stride).ok_or(INVALID)?,stride,std::iter::empty())?;
    let map=window.as_object_mut().ok_or(INVALID)?;
    map.remove("target_future_policy");map.insert("contract".into(),json!("ONLYALPHA_STRATEGY_VALIDATION_INPUT_WINDOW_V1"));Ok(window)
}
pub(crate) fn check_dataset(definition:&Definition,graph:&Graph,materialized:&MaterializedDataset)->Result<Value> {
    let strategy=definition.to_record();let verified=materialized.verified();let dataset=verified.dataset();
    let d=dataset.definition();let p=verified.manifest()["provenance"].as_array().filter(|p|p.len()==1).ok_or(INVALID)?;
    if d["instruments"]!=strategy["universe"]["instruments"]||d["instruments"]!=json!(["BTCUSDT.BINANCE"])
        ||d["bar_semantic"]!=strategy["market_input"]["bar_semantic"]
        ||p[0]["source_metadata"]["construction_recipe"]!=strategy["market_input"]["construction_requirement"]["recipe"] {return Err(INVALID);}
    let window=validation_window(graph)?;
    if d["bar_semantic"]["formation"]["stride_minutes"]!=1||window["dataset_event_start_ns"]!=ns(d["time_range"]["start"].as_str().ok_or(INVALID)?)?.to_string()
        ||window["dataset_event_end_ns"]!=ns(d["time_range"]["end"].as_str().ok_or(INVALID)?)?.to_string()
        ||window["dataset_observation_capacity"].as_u64()!=Some(dataset.rows().len() as u64) {return Err(INVALID);}
    let start=window["dataset_event_start_ns"].as_str().ok_or(INVALID)?.parse::<u64>().map_err(|_|INVALID)?;
    for (index,row) in dataset.rows().iter().enumerate() {
        let at=start.checked_add((index as u64).checked_mul(60_000_000_000).ok_or(INVALID)?).ok_or(INVALID)?;
        if row["ts_event_ns"].as_u64()!=Some(at)||window["dataset_columns"].as_array().ok_or(INVALID)?.iter().any(|c|c.as_str().is_none_or(|c|row.get(c).is_none())){return Err(INVALID);}
    }Ok(window)
}
pub(crate) fn check_source(origin:&Origin,materialized:&MaterializedDataset)->Result<()> {
    let source=&origin.accepted["input"]["source"];
    let scope=&materialized.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"]["scope"];
    if scope["source_id"]!=source["source_id"]||scope["instrument_id"]!=source["instrument_id"]
        ||scope["bar_construction"]["plan"]["integration_revision_fingerprint"]!=source["integration_revision_fingerprint"]{return Err(INVALID);}Ok(())
}
/// Implementation selection reuses the exact Research admission projection.
pub(crate) fn implementation_bindings(graph:&Graph,resolution:&Value,native:&Value,manifest:&Value)->Result<Value> {
    let nodes=resolution["nodes"].as_array().ok_or(INVALID)?;let allowed=manifest["implementations"].as_array().ok_or(INVALID)?;
    let mut bindings=BTreeMap::new();
    for node in graph.ordered_nodes() {
        let d=node.to_record();if d["kind"]=="TARGET"{return Err(INVALID);}
        let actual=if d["kind"]=="PREDICATE"{native}else{&observed_strategy_node(nodes,&d,&node.fingerprint())?["implementations"]};
        let selected=select_strategy_implementations(actual,&d,&["RESEARCH","TRADING"],allowed)?;
        bindings.insert(node.fingerprint(),json!({"node_fingerprint":node.fingerprint(),"research_implementation_fingerprint":selected[0]["implementation_fingerprint"],"trading_implementation_fingerprint":selected[1]["implementation_fingerprint"]}));
    }Ok(json!(bindings.into_values().collect::<Vec<_>>()))
}
pub(crate) fn decision(definition:&Definition,resolution:&Value)->Result<DecisionGraph> {
    let nodes=resolution["nodes"].as_array().ok_or(INVALID)?;
    let projected=nodes.iter().map(|node|json!({"instance_key":node["instance_key"],"definition":node["definition"],"definition_fingerprint":node["definition_fingerprint"],"type_declaration":node["type_declaration"]})).collect::<Vec<_>>();
    DecisionGraph::derive(definition,&json!(projected))
}
/// Concrete original inputs, constructed only by owning authoring/Runtime/Dataset reads.
pub(crate) struct ResolvedValidation {
    origin:Origin,runtime:Arc<RuntimeInputHold>,record:Value,files:Vec<Witness>,source:SourceRevision,
}
impl ResolvedValidation {
    pub(crate) async fn resolve(client:&mut Client,operation:&Operation,runtime:RuntimeInputHold,installation:Arc<ChartInstallation>,datasets:&Datasets,control:&Control)->std::result::Result<Self,PreparationError> {
        let origin=Origin::from_operation(operation)?;control.check()?;
        if runtime.manifest()["runtime_generation_fingerprint"]!=origin.generation||runtime.binding()["work_id"]!=origin.work||runtime.binding()["reason"]!=origin.runtime_owner{return Err(INVALID.into());}
        let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_|UNAVAILABLE)?;
        let actual=crate::persistence::research_preparation::load(&tx,&origin.command,&origin.owner).await?;
        if actual.accepted!=origin.accepted{return Err(INVALID.into());}
        let root=crate::security::immutable_json::Directory::open(datasets.root().parent().ok_or(INVALID)?)?;
        let namespace=crate::bootstrap::deployment::load_semantic_store_id_at(&root.fd).map_err(|_|INVALID)?;
        crate::bootstrap::deployment::verify_binding_in_transaction(&tx,&namespace).await.map_err(|e|e.code())?;
        let (revision,factors)=authoring(&tx,&origin).await?;
        let installed=installation.clone();let worker_control=control.clone();let worker_revision=revision.clone();let worker_factors=factors.clone();
        let resolved=tokio::task::spawn_blocking(move||ResolvedCalculations::resolve_manual(runtime,&installed,&worker_revision,&worker_factors,&worker_control))
            .await.map_err(|_|control.uncertain("STRATEGY_VALIDATION_PRODUCER_OUTCOME_UNKNOWN"))??;
        let (mut runtime,resolution,request)=resolved.into_preparation();
        let definition=Definition::from_record(&revision["definition"])?;let graph=decision(&definition,&resolution["algorithm_resolution"])?;
        if graph.record()!=resolution["decision"]||!resolution["target_graph"].is_null()||!resolution["composition"].is_null(){return Err(INVALID.into());}
        let native=Arc::get_mut(&mut runtime).ok_or(INVALID)?.native_predicate_implementations()?;
        let bindings=implementation_bindings(graph.graph(),&resolution["algorithm_resolution"],&native,runtime.manifest())?;
        let window=validation_window(graph.graph())?;
        let execution=runtime.execution_binding()?;let declared=definition.to_record();
        let source_definition=json!({"instruments":declared["universe"]["instruments"],"bar_semantic":declared["market_input"]["bar_semantic"]});
        let source=source_revision(graph.graph(),&bindings,&graph.record()["signal_semantics"],&source_definition,&declared["market_input"]["construction_requirement"]["recipe"])?;
        let mut files=Vec::new();
        if crate::persistence::research_evidence::strategy::physical::document(&root,".onlyalpha-semantic-store.json",&mut files)?!=json!({"schema_version":1,"store_id":namespace.value()}){return Err(INVALID.into());}
        let record=json!({"semantic_store_id":namespace.value(),"origin":origin.record(),"strategy_revision":revision,"factor_revisions":factors,
            "runtime_manifest":runtime.manifest(),"runtime_work_binding":runtime.binding(),"execution_binding":execution,
            "algorithm_resolution":resolution["algorithm_resolution"],"algorithm_resolution_request":request,"native_implementations":native,
            "decision":graph.record(),"implementation_bindings":bindings,"input_window":window,"source_revision":source.to_record()});
        let reanchored=authoring(&tx,&origin).await?;if record["strategy_revision"]!=reanchored.0||record["factor_revisions"]!=serde_json::to_value(reanchored.1).map_err(|_|INVALID)?{return Err(INVALID.into());}
        for file in &files{file.verify()?;}runtime.verify()?;control.verify_joined()?;
        tx.commit().await.map_err(|_|UNAVAILABLE)?;
        Ok(Self{origin,runtime,record,files,source})
    }
    pub(crate) fn input_window(&self)->&Value{&self.record["input_window"]}
    pub(crate) fn source_revision(&self)->&SourceRevision{&self.source}
    pub(crate) fn record(&self)->&Value{&self.record}
    pub(crate) fn observe(mut self,installation:Arc<ChartInstallation>,native_version:&str,control:&Control,datasets:&Datasets,materialized:&MaterializedDataset)->std::result::Result<JoinedValidation,PreparationError> {
        control.verify_joined()?;self.runtime.verify()?;for file in &self.files{file.verify()?;}
        let image=crate::workers::algorithm::describe_research_runtime(native_version).map_err(|_|UNAVAILABLE)?;
        let e=&self.record["execution_binding"];
        if image["artifact"]!=e["executor_artifact_sha256"]||image["version"]!=e["executor_version"]||image["protocol"]!=e["protocol"]{return Err(INVALID.into());}
        let retained=MaterializedDataset::load(datasets,materialized.lineage()["materialization_id"].as_str().ok_or(INVALID)?)?;
        if retained.lineage()!=materialized.lineage()||retained.verified().manifest()!=materialized.verified().manifest(){return Err(INVALID.into());}
        let definition=Definition::from_record(&self.record["strategy_revision"]["definition"])?;
        let graph=Graph::from_record(&self.record["decision"]["decision_graph"],WORK).map_err(|_|INVALID)?;
        if check_dataset(&definition,&graph,&retained)?!=self.record["input_window"]{return Err(INVALID.into());}
        check_source(&self.origin,&retained)?;
        capture_dataset(datasets.root(),retained.verified().manifest(),retained.lineage(),&mut self.files)?;
        self.record["dataset_snapshot_fingerprint"]=json!(retained.verified().dataset().snapshot_fingerprint());
        self.record["dataset_manifest"]=retained.verified().manifest().clone();self.record["dataset_materialization"]=retained.lineage().clone();
        self.record["dataset_construction_fingerprint"]=json!(retained.verified().dataset().construction_fingerprint());
        let materialized=&retained;
        let mut observation=observe_graph(self.runtime.clone(),&self.record,&self.record,&graph,None,&materialized.verified().dataset().bars()?,materialized.verified().dataset().definition(),&self.record["dataset_manifest"]["provenance"][0]["source_metadata"]["construction_recipe"],installation,control)?;
        observation["producer"]=json!({"native_image":image,"algorithm_artifact_fingerprint":self.record["algorithm_resolution"]["algorithm_artifact"]});
        crate::persistence::strategy_validation::verify_observation(&self.record,&observation,materialized)?;
        control.verify_joined()?;self.runtime.verify()?;for file in &self.files{file.verify()?;}
        Ok(JoinedValidation{resolved:self,observation})
    }
}
/// Only observe() can construct this value, after every original child joined.
pub(crate) struct JoinedValidation {resolved:ResolvedValidation,observation:Value}
impl JoinedValidation {
    pub(crate) fn verify_cut(&self)->Result<()> {self.resolved.runtime.verify()?;for file in &self.resolved.files{file.verify()?;}Ok(())}
    pub(crate) fn origin(&self)->&Origin {&self.resolved.origin}
    pub(crate) fn record(&self)->&Value {&self.resolved.record}
    pub(crate) fn observation(&self)->&Value {&self.observation}
    pub(crate) fn source_revision(&self)->&SourceRevision {&self.resolved.source}
}
