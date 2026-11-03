//! V2 typed origin of the existing queue/Command lifecycle, never a new Run owner.
use super::*;
use crate::{application::{backtest_preparation::{self,BacktestOrigin},backtest_run,private_assets,private_strategy::Definition,
    research_dataset::MaterializedDataset},bootstrap::deployment::{self,SemanticStoreId},
    persistence::{research_dataset::Store as Datasets,research_evidence::strategy::physical::{Witness,capture_dataset},authority_session::AuthoritySession,strategy_promotion::VerifiedBacktestAdmission,strategy_validation::VerifiedValidation},
    security::human_access,workers::backtest::PreparedNextOpen};
use std::collections::BTreeMap;
const MISMATCH:&str="BACKTEST_PREPARATION_PROOF_MISMATCH";
const UNKNOWN:&str="BACKTEST_PREPARATION_OUTCOME_UNKNOWN";
const ACCEPTED:&str="ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V2";

async fn manual_authoring(tx:&Transaction<'_>,input:&BacktestPrepareInput)->Result<(Value,BTreeMap<String,Value>)> {
    let BacktestOrigin::ManualStrategy{strategy_id,strategy_revision_fingerprint}=&input.origin else{return Err(MISMATCH);};
    let strategy=private_assets::strategy_revision_in_transaction(tx,strategy_id,strategy_revision_fingerprint).await.map_err(|e|e.code())?;
    let definition=Definition::from_record(&strategy["definition"])?;let d=definition.to_record();
    require_profile(&d["universe"],&d["market_input"])?;
    let mut factors=BTreeMap::new();
    for dependency in d["factor_revision_dependencies"].as_array().ok_or(CORRUPT)? {
        let id=dependency["factor_id"].as_str().ok_or(CORRUPT)?;let revision=dependency["revision_fingerprint"].as_str().ok_or(CORRUPT)?;
        let factor=private_assets::factor_revision_in_transaction(tx,id,revision).await.map_err(|e|e.code())?;
        if factors.insert(id.to_owned(),factor).is_some(){return Err(CORRUPT);}
    }Ok((strategy,factors))
}
fn require_profile(universe:&Value,market:&Value)->Result<()> {
    if *universe!=json!({"kind":"SINGLE_INSTRUMENT","instruments":["BTCUSDT.BINANCE"]})
        ||market["bar_semantic"]!=json!({"schema_version":3,"price_type":"LAST","adjustment_policy":"RAW","formation":{"schema_version":1,"kind":"FIXED_DURATION","window_minutes":1,"stride_minutes":1,"alignment":"SESSION_START"}})
        ||market["data_kind"]!="BAR"||market["observation_admission"]!="FINAL_ONLY"
        ||market["construction_requirement"]["kind"]!="EXACT_RECIPE"||market["construction_requirement"]["recipe"]["kind"]!="PROVIDER_NATIVE" {return Err(MISMATCH);}Ok(())
}
/// Published authoring from the real owning readers. This grants no Trading admission.
pub(crate) struct VerifiedManualBacktestAuthoring {namespace:SemanticStoreId,input:Value,strategy:Value,factors:BTreeMap<String,Value>}
impl VerifiedManualBacktestAuthoring {
    async fn verify_in_transaction(&self,tx:&Transaction<'_>,namespace:&SemanticStoreId,input:&BacktestPrepareInput)->Result<()> {
        if namespace!=&self.namespace||self.input!=serde_json::to_value(input).map_err(db)?{return Err(MISMATCH);}
        deployment::verify_binding_in_transaction(tx,namespace).await.map_err(|e|e.code())?;
        let (strategy,factors)=manual_authoring(tx,input).await?;
        if strategy!=self.strategy||factors!=self.factors{return Err(MISMATCH);}Ok(())
    }
}
pub(crate) async fn manual_backtest_authoring(client:&mut Client,namespace:&SemanticStoreId,input:&BacktestPrepareInput)->Result<VerifiedManualBacktestAuthoring> {
    input.origin.validate()?;
    let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(db)?;
    bounds(&tx).await.map_err(db)?;deployment::verify_binding_in_transaction(&tx,namespace).await.map_err(|e|e.code())?;
    let (strategy,factors)=manual_authoring(&tx,input).await?;
    let proof=VerifiedManualBacktestAuthoring{namespace:namespace.clone(),input:serde_json::to_value(input).map_err(db)?,strategy,factors};
    proof.verify_in_transaction(&tx,namespace,input).await?;tx.commit().await.map_err(db)?;Ok(proof)
}
pub(crate) enum BacktestAcceptance<'proof> {Manual(&'proof VerifiedManualBacktestAuthoring),Frozen(&'proof VerifiedBacktestAdmission)}
impl BacktestAcceptance<'_> {
    async fn verify_in_transaction(&self,tx:&Transaction<'_>,namespace:&SemanticStoreId,input:&BacktestPrepareInput)->Result<()> {
        match (self,&input.origin) {
            (Self::Manual(proof),BacktestOrigin::ManualStrategy{..})=>proof.verify_in_transaction(tx,namespace,input).await,
            (Self::Frozen(proof),BacktestOrigin::FrozenStrategy{strategy_fingerprint,freeze_relation_fingerprint,qualification_decision_fingerprint,promotion_fingerprint})=>{
                if namespace!=proof.namespace()||strategy_fingerprint!=proof.strategy_fingerprint()||freeze_relation_fingerprint!=proof.freeze_relation_fingerprint()
                    ||qualification_decision_fingerprint!=proof.qualification_decision_fingerprint()||promotion_fingerprint!=proof.promotion_fingerprint(){return Err(MISMATCH);}
                proof.verify_in_transaction(tx,namespace).await?;let source=proof.source_revision().to_record();
                require_profile(&source["universe"],&source["market_input_contract"])
            },_=>Err(MISMATCH),
        }
    }
}
pub(super) async fn validate_accepted(tx:&Transaction<'_>,command:&CommandId,owner:&str,input:&BacktestPrepareInput,value:&Value)->Result<()> {
    exact_fields(value,&["schema_version","contract","command_id","owner","input","semantic_store_id","runtime_work_id","accepted_at"])?;
    if value["schema_version"]!=2||value["contract"]!=ACCEPTED||value["command_id"]!=command.value()
        ||value["owner"]!=owner||value["input"]!=serde_json::to_value(input).map_err(db)?
        ||value["runtime_work_id"]!=backtest_preparation::run_id(&CommandId::new(&input.backtest_command_id).map_err(db)?){return Err(CORRUPT);}
    let namespace=SemanticStoreId::new(text(value,"semantic_store_id")?).map_err(|e|e.code())?;
    deployment::verify_binding_in_transaction(tx,&namespace).await.map_err(|e|e.code())?;
    // Accepted metadata is only an authenticated original request, never a
    // portable cache of a qualified proof. Frozen/Run admission reopens its
    // owning physical and ledger proof at each formal execution boundary.
    if matches!(&input.origin,BacktestOrigin::ManualStrategy{..}){manual_authoring(tx,input).await?;}
    Ok(())
}
/// Original guarded session, original acceptance first, no Research prerequisite.
pub(crate) async fn accept_backtest(session:&mut AuthoritySession,namespace:&SemanticStoreId,human:(&human_access::Access,&human_access::Session),
    command:&CommandId,input:BacktestPrepareInput,proof:BacktestAcceptance<'_>,at:OnlyUtcDateTime)->Result<Operation> {
    input.validate(command)?;human.0.check_session(human.1).map_err(|_|"RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
    let owner=human.1.subject_id().map_err(|_|"RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?.to_owned();
    let request=PreparationRequest::Backtest(input.clone());
    let admission=Admission::new(command.clone(),CommandKind::PrepareBacktest,&request.intent(&owner)?).map_err(db)?;
    let mut owned=session.take_ownership();let mut mutated=false;
    let result=async {
        let tx=owned.client_mut().await.map_err(|_|UNAVAILABLE)?.build_transaction().isolation_level(tokio_postgres::IsolationLevel::Serializable).start().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;Commands::lock_command(&tx,command).await.map_err(db)?;
        match Commands::verify_binding_in_transaction(&tx,command).await.map_err(db)? {
            Binding::Accepted(receipt) if receipt.admission()==&admission=>{let original=load(&tx,command,&owner).await?;AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNAVAILABLE)?;tx.commit().await.map_err(|_|UNKNOWN)?;return Ok(original);},
            Binding::None=>{},Binding::Admitted(_)=>return Err(UNKNOWN),_=>return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT"),
        }
        proof.verify_in_transaction(&tx,namespace,&input).await?;
        let future=CommandId::new(&input.backtest_command_id).map_err(db)?;Commands::lock_command(&tx,&future).await.map_err(db)?;
        if !matches!(Commands::verify_binding_in_transaction(&tx,&future).await.map_err(db)?,Binding::None)
            ||tx.query_opt("SELECT 1 FROM research_preparation WHERE COALESCE(accepted_payload::jsonb->'input'->>'research_command_id',accepted_payload::jsonb->'input'->>'backtest_command_id')=$1 UNION ALL SELECT 1 FROM backtest_run WHERE run_id=$2::text::uuid LIMIT 1",&[&future.value(),&backtest_preparation::run_id(&future)]).await.map_err(db)?.is_some(){return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT");}
        let accepted=json!({"schema_version":2,"contract":ACCEPTED,"command_id":command.value(),"owner":owner,"input":input,
            "semantic_store_id":namespace.value(),"runtime_work_id":request.reserved_run_id(),"accepted_at":at.to_string()});
        let fingerprint=hash(&accepted)?;let payload=canonical(&accepted)?;
        mutated=true;Commands::admit_exact_in_transaction(&tx,&admission).await.map_err(db)?;
        tx.execute("INSERT INTO research_preparation(command_id,owner,accepted_fingerprint,accepted_payload,revision,state,phase,outputs_payload,detail_payload,preparation_kind) VALUES($1::text::uuid,$2,$3,$4,0,'ACCEPTED','ACCEPTED','{}','null','BACKTEST_PREPARATION')",&[&command.value(),&owner,&fingerprint,&payload]).await.map_err(db)?;
        let receipt=Receipt::new(admission,Outcome::new(OutcomeKind::ResearchPreparationOperation,&fingerprint).map_err(db)?,&at.to_string()).map_err(db)?;
        Commands::put_verified_receipt_in_transaction(&tx,&receipt).await.map_err(db)?;
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(|_|UNKNOWN)?;
        let operation=load(&tx,command,&owner).await?;
        if operation.accepted!=accepted||operation.state!=State::Accepted||operation.revision!=0{return Err(CORRUPT);}
        proof.verify_in_transaction(&tx,namespace,&input).await?;
        human.0.check_session(human.1).map_err(|_|"RESEARCH_HUMAN_AUTHORIZATION_REQUIRED")?;
        let Binding::Accepted(actual)=Commands::verify_binding_in_transaction(&tx,command).await.map_err(db)? else{return Err(CORRUPT);};
        if actual!=receipt{return Err(CORRUPT);}AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNKNOWN)?;
        tx.commit().await.map_err(|_|UNKNOWN)?;Ok(operation)
    }.await;
    if result.is_err()&&(mutated||result.as_ref().err().is_some_and(|e|matches!(*e,UNAVAILABLE|UNKNOWN|CORRUPT))){return result;}
    owned.verify().await.map_err(|_|UNAVAILABLE)?;session.restore_ownership(owned);result
}
pub(super) fn validate_environment(o:&Operation)->Result<()> {
    let input=o.request.backtest()?;let e=&o.outputs["environment"];
    exact_fields(e,&["runtime_generation_fingerprint","binding"])?;
    if !e["runtime_generation_fingerprint"].as_str().is_some_and(crate::is_sha256_hex)||e["binding"]["kind"]!="RuntimeWorkBound"
        ||e["binding"]["reason"]!=input.backtest_command_id||e["binding"]["work_id"]!=o.request.reserved_run_id()
        ||e["binding"]["generation_fingerprint"]!=e["runtime_generation_fingerprint"]{return Err(CORRUPT);}Ok(())
}
pub(super) fn validate_ready(o:&Operation,outputs:&Value)->Result<()> {
    let input=o.request.backtest()?;let ready=&outputs["ready"];
    exact_fields(ready,&["preparation_command_id","origin","admission","validation_fingerprint","preparation_fingerprint","preparation","input_sources","specification","dataset_materialization_id","source_selection","algorithm_resolution","algorithm_resolution_request","native_implementations","backtest_binding","rules_response"])?;
    exact_fields(&ready["admission"],&["strategy_fingerprint","freeze_relation_fingerprint","qualification_decision_fingerprint","promotion_fingerprint"])?;
    for key in ["strategy_fingerprint","freeze_relation_fingerprint","qualification_decision_fingerprint","promotion_fingerprint"]{if !text(&ready["admission"],key).is_ok_and(crate::is_sha256_hex){return Err(CORRUPT);}}
    match &input.origin {
        BacktestOrigin::ManualStrategy{..}=>if !ready["validation_fingerprint"].as_str().is_some_and(crate::is_sha256_hex){return Err(CORRUPT);},
        BacktestOrigin::FrozenStrategy{strategy_fingerprint,freeze_relation_fingerprint,qualification_decision_fingerprint,promotion_fingerprint}=>{
            if !ready["validation_fingerprint"].is_null()||ready["admission"]!=json!({"strategy_fingerprint":strategy_fingerprint,"freeze_relation_fingerprint":freeze_relation_fingerprint,"qualification_decision_fingerprint":qualification_decision_fingerprint,"promotion_fingerprint":promotion_fingerprint}){return Err(CORRUPT);}
        },
    }
    let specification=backtest_run::Specification::from_record(&ready["specification"])?;let s=specification.record();let preparation=&ready["preparation"];
    if ready["preparation_command_id"]!=o.command.value()||ready["origin"]!=serde_json::to_value(&input.origin).map_err(db)?
        ||ready["preparation_fingerprint"]!=hash(preparation)?||preparation["contract"]!="ONLYALPHA_BTC_NEXT_OPEN_PREPARATION_V1"
        ||preparation["strategy_fingerprint"]!=ready["admission"]["strategy_fingerprint"]||s["strategy_fingerprint"]!=ready["admission"]["strategy_fingerprint"]
        ||s["runtime_generation_fingerprint"]!=o.outputs["environment"]["runtime_generation_fingerprint"]||s["preparation_fingerprint"]!=ready["preparation_fingerprint"]
        ||s["dataset_snapshot_fingerprint"]!=ready["input_sources"]["sources"][0]["snapshot"]||ready["backtest_binding"]["protocol"]!="onlyalpha.backtest.executor/1"{return Err(CORRUPT);}
    let selected=&ready["source_selection"];exact_fields(selected,&["preparation_command_id","source","acquisition","scope","revision","seal"])?;
    if selected["preparation_command_id"]!=o.command.value()||selected["source"]!=serde_json::to_value(&input.source).map_err(db)?
        ||selected["acquisition"]["status"]!="COMPLETE"||selected["scope"]!=selected["revision"]["scope"]
        ||selected["revision"]["revision_id"]!=selected["seal"]["revision_id"]||selected["acquisition"]["revision_id"]!=selected["revision"]["revision_id"]
        ||selected["acquisition"]["revision_fingerprint"]!=selected["revision"]["fingerprint"]||selected["acquisition"]["seal_id"]!=selected["seal"]["seal_id"]
        ||selected["scope"]["source_id"]!=input.source.source_id||selected["scope"]["bar_construction"]["plan"]["integration_revision_fingerprint"]!=input.source.integration_revision_fingerprint{return Err(CORRUPT);}
    let sources=onlyalpha_backtest::Inputs::from_record(&ready["input_sources"]).map_err(|_|CORRUPT)?;
    if preparation["input_pin"]!=sources.fingerprint(){return Err(CORRUPT);}Ok(())
}
/// Original concrete owners are borrowed through Host's final durable handoff.
/// record() is metadata only; admission is re-opened at Run creation as usual.
pub(crate) struct BacktestReady<'proof> {operation:&'proof Operation,admission:&'proof VerifiedBacktestAdmission,validation:Option<&'proof VerifiedValidation>,files:Vec<Witness>,record:Value}
impl<'proof> BacktestReady<'proof> {
    pub(crate) fn derive(operation:&'proof Operation,admission:&'proof VerifiedBacktestAdmission,validation:Option<&'proof VerifiedValidation>,
        prepared:&PreparedNextOpen,datasets:&Datasets,materialized:&MaterializedDataset,source_selection:&Value,algorithm_resolution:&Value,algorithm_resolution_request:&Value,native_implementations:&Value,backtest_binding:&Value,rules_response:&Value)->Result<Self> {
        let input=operation.request.backtest()?;admission.verify_cut()?;
        let namespace=SemanticStoreId::new(text(&operation.accepted,"semantic_store_id")?).map_err(|e|e.code())?;
        if admission.namespace()!=&namespace{return Err(MISMATCH);}
        match (&input.origin,validation) {
            (BacktestOrigin::ManualStrategy{strategy_id,strategy_revision_fingerprint},Some(proof))=>{
                proof.verify_cut()?;
                if proof.preparation_command_id()!=operation.command.value()||proof.private_strategy_id()!=strategy_id||proof.private_strategy_revision_fingerprint()!=strategy_revision_fingerprint
                    ||proof.source_revision().fingerprint()!=admission.strategy_fingerprint()||proof.dataset_snapshot_fingerprint()!=materialized.verified().dataset().snapshot_fingerprint()
                    ||operation.outputs["environment"]["runtime_generation_fingerprint"]!=proof.runtime_generation_fingerprint(){return Err(MISMATCH);}
                let validated=&proof.record()["prepared_inputs"];
                if validated["algorithm_resolution"]!=*algorithm_resolution||validated["algorithm_resolution_request"]!=*algorithm_resolution_request||validated["native_implementations"]!=*native_implementations{return Err(MISMATCH);}
            },
            (BacktestOrigin::FrozenStrategy{strategy_fingerprint,freeze_relation_fingerprint,qualification_decision_fingerprint,promotion_fingerprint},None)=>{
                if strategy_fingerprint!=admission.strategy_fingerprint()||freeze_relation_fingerprint!=admission.freeze_relation_fingerprint()
                    ||qualification_decision_fingerprint!=admission.qualification_decision_fingerprint()||promotion_fingerprint!=admission.promotion_fingerprint(){return Err(MISMATCH);}
            },_=>return Err(MISMATCH),
        }
        let retained=MaterializedDataset::load(datasets,text(materialized.lineage(),"materialization_id")?)?;
        if retained.lineage()!=materialized.lineage()||retained.verified().manifest()!=materialized.verified().manifest(){return Err(MISMATCH);}
        let mut files=Vec::new();capture_dataset(datasets.root(),retained.verified().manifest(),retained.lineage(),&mut files)?;
        let root=crate::security::immutable_json::Directory::open(datasets.root().parent().ok_or(MISMATCH)?)?;
        if crate::persistence::research_evidence::strategy::physical::document(&root,".onlyalpha-semantic-store.json",&mut files)?!=json!({"schema_version":1,"store_id":namespace.value()}){return Err(MISMATCH);}
        let generation=text(&operation.outputs["environment"],"runtime_generation_fingerprint")?;
        let rules=backtest_preparation::retained_backtest_rules(rules_response,&input.source,&operation.command)?;
        let expected=backtest_preparation::build_prepared_next_open(admission.source_revision(),materialized,rules,generation).map_err(|e|e.code())?;
        if expected.record()!=prepared.record(){return Err(MISMATCH);}
        let sealed=&materialized.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"];
        if source_selection["scope"]!=sealed["scope"]||source_selection["revision"]!=sealed["evidence"]["revision"]||source_selection["seal"]!=sealed["evidence"]["seal"]{return Err(MISMATCH);}
        let preparation=prepared.record();let specification=backtest_run::Specification::from_record(&json!({"schema_version":3,"kind":"BTC_SPOT_NEXT_OPEN","strategy_fingerprint":admission.strategy_fingerprint(),"dataset_snapshot_fingerprint":materialized.verified().dataset().snapshot_fingerprint(),"runtime_generation_fingerprint":generation,"preparation_fingerprint":hash(&preparation)?}))?;
        let record=json!({"preparation_command_id":operation.command.value(),"origin":input.origin,"admission":{"strategy_fingerprint":admission.strategy_fingerprint(),"freeze_relation_fingerprint":admission.freeze_relation_fingerprint(),"qualification_decision_fingerprint":admission.qualification_decision_fingerprint(),"promotion_fingerprint":admission.promotion_fingerprint()},
            "validation_fingerprint":validation.map(VerifiedValidation::fingerprint),"preparation_fingerprint":hash(&preparation)?,"preparation":preparation,"input_sources":prepared.inputs().record(),"specification":specification.record(),
            "dataset_materialization_id":materialized.lineage()["materialization_id"],"source_selection":source_selection,"algorithm_resolution":algorithm_resolution,"algorithm_resolution_request":algorithm_resolution_request,"native_implementations":native_implementations,"backtest_binding":backtest_binding,"rules_response":rules_response});
        let mut outputs=operation.outputs.clone();outputs["ready"]=record.clone();validate_ready(operation,&outputs)?;
        let value=Self{operation,admission,validation,files,record};value.verify_cut()?;Ok(value)
    }
    pub(crate) fn record(&self)->&Value{&self.record}
    pub(crate) fn verify_cut(&self)->Result<()> {
        self.admission.verify_cut()?;if let Some(validation)=self.validation{validation.verify_cut()?;}
        for file in &self.files{file.verify()?;}Ok(())
    }
    pub(crate) async fn verify_in_transaction(&self,tx:&Transaction<'_>)->Result<()> {
        self.verify_cut()?;
        let namespace=SemanticStoreId::new(text(&self.operation.accepted,"semantic_store_id")?).map_err(|e|e.code())?;
        let current=load(tx,&self.operation.command,&self.operation.owner).await?;
        if current.accepted!=self.operation.accepted{return Err(MISMATCH);}
        self.admission.verify_in_transaction(tx,&namespace).await?;
        if let Some(validation)=self.validation{validation.verify_in_transaction(tx,&namespace).await?;}
        self.verify_cut()
    }
}
/// Same queue owner and guarded physical session. The proof remains borrowed
/// through both deferred readback and commit; JSON alone cannot use this entry.
/// Queue progression has no timestamp column: all retained times already come
/// from the original accepted command and the explicit rules occurrence.
pub(crate) async fn publish_backtest_ready(session:&mut AuthoritySession,proof:&BacktestReady<'_>)->Result<Operation> {
    proof.verify_cut()?;let original=proof.operation;
    let mut owned=session.take_ownership();let mut mutated=false;
    let result=async {
        let tx=owned.client_mut().await.map_err(|_|UNAVAILABLE)?.build_transaction().isolation_level(tokio_postgres::IsolationLevel::Serializable).start().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;Commands::lock_command(&tx,&original.command).await.map_err(db)?;
        let current=load(&tx,&original.command,&original.owner).await?;
        if current.accepted!=original.accepted{return Err(MISMATCH);}
        if let Some(ready)=current.outputs.get("ready") {
            if ready!=proof.record(){return Err(CORRUPT);}
            proof.verify_in_transaction(&tx).await?;AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNAVAILABLE)?;
            tx.commit().await.map_err(|_|UNKNOWN)?;proof.verify_cut()?;return Ok(current);
        }
        if current.revision!=original.revision{return Err("RESEARCH_PREPARATION_STALE");}
        if current.state!=State::Running||current.outputs.get("cancellation").is_some(){return Err("RESEARCH_PREPARATION_STALE");}
        if !legal_transition(current.state,State::Ready,"READY_FOR_HUMAN_CONFIRMATION"){return Err("RESEARCH_PREPARATION_ILLEGAL_TRANSITION");}
        require_current(&tx,&current).await?;proof.verify_in_transaction(&tx).await?;
        let mut outputs=current.outputs.clone();outputs["ready"]=proof.record().clone();validate_ready(&current,&outputs)?;
        mutated=true;let expected=update(&tx,&current,State::Ready,"READY_FOR_HUMAN_CONFIRMATION",&outputs,&Value::Null).await?;
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(|_|UNKNOWN)?;
        let actual=load(&tx,&original.command,&original.owner).await?;
        if actual.accepted!=expected.accepted||actual.revision!=expected.revision||actual.state!=expected.state
            ||actual.phase!=expected.phase||actual.outputs!=expected.outputs||actual.detail!=expected.detail{return Err(CORRUPT);}
        proof.verify_in_transaction(&tx).await?;AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNKNOWN)?;proof.verify_cut()?;
        tx.commit().await.map_err(|_|UNKNOWN)?;proof.verify_cut()?;Ok(actual)
    }.await;
    if result.is_err()&&(mutated||result.as_ref().err().is_some_and(|e|matches!(*e,UNAVAILABLE|UNKNOWN|CORRUPT))){return result.map_err(|_|UNKNOWN);}
    owned.verify().await.map_err(|_|UNAVAILABLE)?;session.restore_ownership(owned);result
}
pub(crate) async fn cancel_backtest(session:&mut AuthoritySession,cancel:&CommandId,command:&CommandId,owner:&str,revision:i64,at:OnlyUtcDateTime)->Result<Operation> {
    let mut owned=session.take_ownership();
    let result=async {let client=owned.client_mut().await.map_err(|_|UNAVAILABLE)?;let original=Preparations::new(client).query(command,owner).await?;
        if !original.request.is_backtest(){return Err(INVALID);}Preparations::new(client).cancel(cancel,command,owner,revision,at).await
    }.await;
    if result.as_ref().err().is_some_and(|e|!matches!(*e,INVALID|"RESEARCH_PREPARATION_STALE"|"RESEARCH_PREPARATION_COMMAND_CONFLICT"|"RESEARCH_PREPARATION_NOT_FOUND")){return result;}
    owned.verify().await.map_err(|_|UNAVAILABLE)?;session.restore_ownership(owned);result
}

/// Current parent authority is a separate obligation from timeless mathematical
/// evidence. Only first stage admission uses this guard; original accepted
/// Commands and historical facts retain their ordinary recovery/read semantics.
pub(crate) async fn require_running_manual_backtest_parent(tx:&Transaction<'_>,namespace:&SemanticStoreId,evidence:&VerifiedValidation,actor:&str)->Result<()> {
    let command=CommandId::new(evidence.preparation_command_id()).map_err(db)?;
    let origin=&evidence.record()["prepared_inputs"]["origin"];let owner=text(origin,"owner")?;
    if actor!=owner{return Err("MANUAL_BACKTEST_PREPARATION_OWNER_MISMATCH");}
    tx.query_opt("SELECT command_id FROM public.research_preparation WHERE command_id=$1::text::uuid FOR SHARE",&[&command.value()]).await.map_err(db)?.ok_or(CORRUPT)?;
    evidence.verify_in_transaction(tx,namespace).await?;
    let parent=load(tx,&command,owner).await?;
    if parent.state!=State::Running||parent.outputs.get("cancellation").is_some(){return Err("MANUAL_BACKTEST_PREPARATION_NOT_RUNNING");}
    if crate::application::strategy_validation::Origin::from_operation(&parent)?.record()!=*origin{return Err(CORRUPT);}
    evidence.verify_cut()
}
/// Exact read-only eligibility for existing Runtime lifecycle cleanup. A missing
/// Run or absent environment JSON alone never proves a cancelled/drained owner.
/// The caller supplies the tuple read from the actual Runtime journal, then the
/// existing Registry owner independently verifies it before any release append.
pub(crate) async fn cancelled_backtest_cleanup_in_transaction(tx:&Transaction<'_>,namespace:&SemanticStoreId,work:&str,generation:&str,reason:&str)->Result<Option<Operation>> {
    bounds(tx).await.map_err(db)?;deployment::verify_binding_in_transaction(tx,namespace).await.map_err(|e|e.code())?;
    let Ok(future)=CommandId::new(reason) else{return Ok(None);};
    if !crate::application::command::uuid4(work)||backtest_preparation::run_id(&future)!=work{return Ok(None);}
    if !crate::is_sha256_hex(generation){return Err(CORRUPT);}
    let rows=tx.query("SELECT command_id::text,CASE WHEN pg_catalog.octet_length(owner)<=512 THEN owner END AS owner FROM public.research_preparation WHERE preparation_kind='BACKTEST_PREPARATION' AND accepted_payload::jsonb->'input'->>'backtest_command_id'=$1 ORDER BY command_id LIMIT 2",&[&reason]).await.map_err(db)?;
    if rows.is_empty(){return Ok(None);}if rows.len()!=1{return Err(CORRUPT);}
    let command=CommandId::new(&rows[0].try_get::<_,String>(0).map_err(db)?).map_err(db)?;
    let owner:String=rows[0].try_get(1).map_err(db)?;let original=load(tx,&command,&owner).await?;
    if !original.request.is_backtest()||original.request.reserved_run_id()!=work||original.request.future_command()!=reason{return Err(CORRUPT);}
    if original.state!=State::Cancelled||original.outputs.get("cancellation").is_none(){return Ok(None);}
    super::validate_cancellation(tx,&original).await?;
    if !matches!(Commands::verify_binding_in_transaction(tx,&future).await.map_err(db)?,Binding::None)
        ||tx.query_opt("SELECT 1 FROM public.backtest_run WHERE run_id=$1::text::uuid",&[&work]).await.map_err(db)?.is_some(){return Ok(None);}
    if original.outputs.get("environment").is_some() {
        validate_environment(&original)?;
        if original.outputs["environment"]["runtime_generation_fingerprint"]!=generation{return Err(CORRUPT);}
    }
    Ok(Some(original))
}

/// A current mutation precondition, separate from immutable authoring/history reads.
/// The parent lock prevents cancellation from committing across the actual effect.
pub(crate) async fn require_running_backtest_preparation(tx:&Transaction<'_>,namespace:&SemanticStoreId,original:&Operation)->Result<()> {
    deployment::verify_binding_in_transaction(tx,namespace).await.map_err(|e|e.code())?;
    tx.query_opt("SELECT command_id FROM public.research_preparation WHERE command_id=$1::text::uuid FOR SHARE",&[&original.command.value()]).await.map_err(db)?.ok_or(CORRUPT)?;
    let current=load(tx,&original.command,&original.owner).await?;
    if !current.request.is_backtest()||current.accepted!=original.accepted||current.accepted["semantic_store_id"]!=namespace.value(){return Err(MISMATCH);}
    if current.state!=State::Running||current.outputs.get("cancellation").is_some(){return Err("RESEARCH_PREPARATION_CANCEL_REQUESTED");}
    Ok(())
}
