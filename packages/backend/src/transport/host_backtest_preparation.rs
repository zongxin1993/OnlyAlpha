//! Current Backtest consumer of the existing preparation task, dataset and Run owners.
//! Every JSON record is metadata; confirmation reopens the exact owning proofs.
use super::*;
use crate::{application::{backtest_preparation::{BacktestPrepareInput,BacktestOrigin,run_id},backtest_run::{self,CreateRequest},research_dataset::MaterializedDataset},
    bootstrap::deployment,persistence::{backtest_run::{Backtests,CreationOutcome},qualification_decision,
        strategy_promotion::{self,VerifiedBacktestAdmission},research_runtime::RuntimeEvidenceHold},transport::host_research_inputs::DatasetEventWindow,
    workers::backtest::PreparedNextOpen};
use crate::application::backtest_preparation::build_prepared_next_open;
use crate::transport::research_wire::{BacktestPrepareRefusal,BacktestPrepareRefusalReason,BacktestPrepareRefusalState};
use onlyalpha_plugin_binance::{spot_rest::PublicRest,spot_simulation::SpotRuleSnapshot};
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::os::fd::AsFd;
const BAR:u64=60_000_000_000;
const START:&str="2025-01-03T00:00:00Z";
const END:&str="2025-01-03T12:00:00Z";
fn sample()->Result<(u64,u64)> {
    let ns=|s:&str|->Result<u64>{OnlyTimestamp::from_datetime(s.parse::<OnlyUtcDateTime>().map_err(|_|INVALID)?).unix_nanos().to_string().parse().map_err(|_|INVALID.into())};
    Ok((ns(START)?,ns(END)?))
}
// Backtest samples label bar opens; the shared input window labels close events.
fn backtest_dataset_event_window(graph:&onlyalpha_calculation::product::Graph)->Result<Value> {
    let (start,end)=sample()?;
    let start=start.checked_add(BAR).ok_or(INVALID)?;
    let end=end.checked_add(BAR).ok_or(INVALID)?;
    crate::application::strategy_research::canonical_input_window(graph,start,end,BAR,std::iter::empty::<&str>()).map_err(Into::into)
}
fn namespace(config:&PreparationConfig)->Result<deployment::SemanticStoreId> {
    let root=protected_files::open_directory(&config.research_root).map_err(|_|"RESEARCH_SEMANTIC_STORE_UNAVAILABLE")?;
    deployment::load_semantic_store_id_at(&root).map_err(|e|e.code().into())
}
struct ReadyOwners {admission:VerifiedBacktestAdmission,runtime:RuntimeInputHold,materialized:MaterializedDataset,datasets:Datasets,prepared:PreparedNextOpen,validation:Option<Arc<crate::persistence::strategy_validation::VerifiedValidation>>}
/// Locate only actual original active work. Missing progress metadata cannot prove absence.
fn backtest_work_generation(config:&PreparationConfig,o:&Operation)->Result<Option<String>> {
    let input=o.request.backtest()?;let work=o.request.reserved_run_id();
    let active=Registry::unreleased_work_bindings(&config.runtime_root)?;
    let selected=active.into_iter().filter(|(id,_,_)|*id==work).collect::<Vec<_>>();
    if selected.len()>1{return Err(INVALID.into());}
    if let Some((_,generation,owner))=selected.into_iter().next() {
        if owner!=input.backtest_command_id||o.outputs.get("environment").is_some_and(|environment|environment["runtime_generation_fingerprint"]!=generation){return Err(INVALID.into());}
        return Ok(Some(generation));
    }
    if let Some(environment)=o.outputs.get("environment") {
        let observed=Registry::inspect_work(&config.runtime_root,&work,text(environment,"runtime_generation_fingerprint")?,&input.backtest_command_id)?;
        if observed["closed"]!=true{return Err(INVALID.into());}
    }
    Ok(None)
}
fn retained_rules(o:&Operation)->Result<SpotRuleSnapshot> {
    crate::application::backtest_preparation::retained_backtest_rules(&o.outputs["ready"]["rules_response"],&o.source()?,&o.command).map_err(Into::into)
}

impl Host {
    pub(crate) async fn backtest_admission(&self,o:&Operation)->Result<VerifiedBacktestAdmission> {
        let input=o.request.backtest()?;
        let selected=match &input.origin {
            BacktestOrigin::FrozenStrategy{strategy_fingerprint,freeze_relation_fingerprint,qualification_decision_fingerprint,promotion_fingerprint}=>json!({
                "strategy_fingerprint":strategy_fingerprint,"freeze_relation_fingerprint":freeze_relation_fingerprint,
                "qualification_decision_fingerprint":qualification_decision_fingerprint,"promotion_fingerprint":promotion_fingerprint}),
            BacktestOrigin::ManualStrategy{..}=>o.outputs["ready"]["admission"].clone(),
        };
        self.backtest_selected_admission(&selected).await
    }
    async fn backtest_selected_admission(&self,selected:&Value)->Result<VerifiedBacktestAdmission> {
        let config=&self.research_preparation_config;let descriptor=protected_files::open_directory(&config.research_root).map_err(|_|INVALID)?;
        let namespace=deployment::load_semantic_store_id_at(&descriptor).map_err(|e|e.code())?;
        let frozen=Arc::new(crate::application::frozen_strategy::FrozenStore::open(descriptor.as_fd()).map_err(|e|e.code())?);
        let decisions=Arc::new(qualification_decision::Store::open(&config.research_root)?);
        let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
        let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_|INVALID)?;
        let decision=decisions.read_verified_in_transaction(&tx,&namespace,&config.runtime_root,text(selected,"qualification_decision_fingerprint")?).await?;
        tx.commit().await.map_err(|_|INVALID)?;
        strategy_promotion::read_verified_admission(client,&namespace,frozen,decision,text(selected,"strategy_fingerprint")?,text(selected,"freeze_relation_fingerprint")?,text(selected,"promotion_fingerprint")?,64*1024*1024).await.map_err(Into::into)
    }
    async fn admit_manual_backtest(&self,o:&Operation,human:&human_access::Session,validation:Arc<crate::persistence::strategy_validation::VerifiedValidation>)->Result<VerifiedBacktestAdmission> {
        use crate::{application::{frozen_strategy::FrozenStore,strategy_projection::Freezes,qualification::Request as QualificationRequest,qualification_policy::Store as Policies},
            persistence::{qualification_commands::Qualifications,strategy_promotion::{Promotions,Request as PromotionRequest},research_preparation::child_command}};
        let config=&self.research_preparation_config;let descriptor=protected_files::open_directory(&config.research_root).map_err(|_|INVALID)?;
        let namespace=namespace(config)?;let frozen=Arc::new(FrozenStore::open(descriptor.as_fd()).map_err(|e|e.code())?);
        let policies=Arc::new(Policies::open(descriptor.as_fd()).map_err(|e|e.code())?);
        let decisions=Arc::new(qualification_decision::Store::open(&config.research_root)?);
        validation.verify_cut()?;
        // Repeated semantics reuse the actual canonical grant, never a second stage transition.
        {let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            if let Some(existing)=strategy_promotion::read_existing_backtest_admission_for_strategy(client,&namespace,frozen.clone(),decisions.clone(),&config.runtime_root,validation.source_revision().fingerprint(),64*1024*1024).await? {return Ok(existing);}}
        let o=self.preparation_checkpoint(o,human).await?;
        let published={let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            Freezes::new(session,&frozen,&namespace,human).execute_manual(&validation,&o,&now().map_err(|e|e.code())?.to_string(),100000,64*1024*1024).await?};
        let evidence=Arc::new(frozen.read_verified_manual(validation,text(&published,"freeze_relation_fingerprint")?,64*1024*1024).map_err(|e|e.code())?);
        self.preparation_checkpoint(&o,human).await?;
        let command=child_command(&o.command,"manual-backtest-qualification")?;
        let request=QualificationRequest::from_manual(command,"manual-backtest","1",&evidence)?;
        let decision={let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            Qualifications::new(session,&namespace,policies,decisions,frozen.clone(),&self.human_access,human).execute_manual(&request,evidence,now().map_err(|e|e.code())?).await?};
        self.preparation_checkpoint(&o,human).await?;
        let subject=request.subject().to_owned();
        let request=PromotionRequest::new(child_command(&o.command,"manual-backtest-promotion")?,&subject,decision.fingerprint(),text(decision.record(),"policy_fingerprint")?,"用户确认策略并准备实验回测")?;
        let promotion={let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            Promotions::new(session,&namespace,frozen.clone(),&self.human_access,human).promote(&request,decision.clone(),now().map_err(|e|e.code())?).await?};
        let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
        strategy_promotion::read_verified_admission(client,&namespace,frozen,decision,&subject,text(&published,"freeze_relation_fingerprint")?,promotion.fingerprint(),64*1024*1024).await.map_err(Into::into)
    }
    /// A scoped response to this original HTTP invocation, never a terminal
    /// Command fact. An already-admitted/accepted original wins the recheck.
    async fn refuse_backtest_before_accept(&self,command:&CommandId,human:&human_access::Session,input:&BacktestPrepareInput,reason:BacktestPrepareRefusalReason)->std::result::Result<Value,Failure> {
        let owner=self.preparation_owner(human).map_err(failure)?;
        let original={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failure("PRODUCT_READ_DRIVER_UNAVAILABLE".into()))?;
            Preparations::new(client).existing_backtest(command,owner,input).await.map_err(|code|failure(code.into()))?};
        if let Some(original)=original{return self.backtest_preparation_view(&original,human).await.map_err(failure);}
        self.preparation_owner(human).map_err(failure)?;
        serde_json::to_value(BacktestPrepareRefusal{schema_version:2,state:BacktestPrepareRefusalState::NotAccepted,command_id:command.value().into(),input:input.clone(),reason})
            .map_err(|_|failure("BACKTEST_PREPARATION_OUTCOME_UNKNOWN".into()))
    }
    pub(crate) async fn accept_backtest_preparation(self:&Arc<Self>,command:CommandId,human:human_access::Session,input:BacktestPrepareInput)->std::result::Result<Value,Failure> {
        let owner=self.preparation_owner(&human).map_err(failure)?.to_owned();input.validate(&command).map_err(|e|failure(e.into()))?;
        let original={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failure("PRODUCT_READ_DRIVER_UNAVAILABLE".into()))?;Preparations::new(client).existing_backtest(&command,&owner,&input).await.map_err(|e|failure(e.into()))?};
        if let Some(original)=original{return self.backtest_preparation_view(&original,&human).await.map_err(failure);}
        if input.release_manifest_fingerprint!=self.research_preparation_config.release_manifest_fingerprint {
            return self.refuse_backtest_before_accept(&command,&human,&input,BacktestPrepareRefusalReason::ConditionsChanged).await;
        }
        release(&self.research_preparation_config).map_err(failure)?;
        match self.preparation_sources(&human,&input.source,true).await {
            Ok(_)=>{},
            Err(error) if error.code()=="RESEARCH_SOURCE_ACCESS_DENIED"=>return self.refuse_backtest_before_accept(&command,&human,&input,BacktestPrepareRefusalReason::SourceUnavailable).await,
            Err(error)=>return Err(failure(error)),
        }
        let accepted={
            let namespace=namespace(&self.research_preparation_config).map_err(failure)?;
            let manual=if matches!(input.origin,BacktestOrigin::ManualStrategy{..}) {
                let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failure("PRODUCT_READ_DRIVER_UNAVAILABLE".into()))?;
                Some(crate::persistence::research_preparation::manual_backtest_authoring(client,&namespace,&input).await.map_err(|e|failure(e.into()))?)
            }else{None};
            let frozen=if let BacktestOrigin::FrozenStrategy{strategy_fingerprint,freeze_relation_fingerprint,qualification_decision_fingerprint,promotion_fingerprint}=&input.origin {
                Some(self.backtest_selected_admission(&json!({"strategy_fingerprint":strategy_fingerprint,"freeze_relation_fingerprint":freeze_relation_fingerprint,"qualification_decision_fingerprint":qualification_decision_fingerprint,"promotion_fingerprint":promotion_fingerprint})).await.map_err(failure)?)
            }else{None};
            let proof=match (&manual,&frozen) {
                (Some(v),None)=>crate::persistence::research_preparation::BacktestAcceptance::Manual(v),
                (None,Some(v))=>crate::persistence::research_preparation::BacktestAcceptance::Frozen(v),
                _=>return Err(failure(INVALID.into())),
            };
            let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or_else(||failure("PRODUCT_AUTHORITY_UNAVAILABLE".into()))?;
            crate::persistence::research_preparation::accept_backtest(session,&namespace,(&self.human_access,&human),&command,input,proof,now()?).await.map_err(|e|failure(e.into()))?
        }; // Drop all Count/Decision/RuntimeEvidence holds before task's EX binding.
        if accepted.state==State::Accepted {self.start_preparation(accepted,human).await.map_err(failure)}else{Ok(accepted.view())}
    }
    pub(crate) async fn require_backtest_preparation_kind(&self,human:&human_access::Session,command:&CommandId)->std::result::Result<(),Failure> {
        let owner=self.preparation_owner(human).map_err(failure)?;let mut reader=self.reader.lock().await;
        let client=reader.as_mut().ok_or_else(||failure("PRODUCT_READ_DRIVER_UNAVAILABLE".into()))?;
        if !Preparations::new(client).query(command,owner).await.map_err(|e|failure(e.into()))?.request.is_backtest(){return Err(failure(INVALID.into()));}Ok(())
    }
    pub(super) async fn prepare_backtest_inputs(self:&Arc<Self>,original:Operation,human:human_access::Session)->Result<()> {
        let config=self.research_preparation_config.clone();pinned_release(&config,&original)?;
        let mut o=self.preparation_checkpoint(&original,&human).await?;let input=o.request.backtest()?.clone();
        o=self.preparation_progress(&o,State::Running,"VALIDATING",&o.outputs,&Value::Null).await?;
        let (authority,session,selection)=self.preparation_sources(&human,&input.source,true).await?;
        let reference=crate::application::source_access::Reference::new(&input.source.integration_id,&input.source.integration_revision_fingerprint,Some(&input.source.expected_type_id)).map_err(|e|e.code())?;
        let (selected,_)=self.resolve(&reference).await.map_err(|e|e.code())?;if selected.selection()!=&selection{return Err(INVALID.into());}
        let release=release(&config)?;
        let installation=Arc::new(ChartInstallation::open(&config.algorithms_root,text(&release,"algorithm_artifact")?).map_err(|_|"RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?);
        // The normal prepare command may activate the selected installed release
        // in the existing Registry. The input pins the prior CAS; outputs pin actual work.
        if matches!(input.origin,BacktestOrigin::ManualStrategy{..}) {
            o=self.prepare_manual_backtest_environment(o,&human,installation.clone()).await?;
        }else if o.outputs.get("environment").is_none() {
            let root=config.runtime_root.clone();let work=o.request.reserved_run_id();let generation=input.expected_active_generation.clone().ok_or(INVALID)?;
            let owner=input.backtest_command_id.clone();let actor=o.owner.clone();let at=now().map_err(|e|e.code())?;
            let binding=tokio::task::spawn_blocking(move||{let mut registry=Registry::open_existing(&root)?;
                registry.bind_new_work_exact(&work,&generation,&owner,&actor,at)}).await.map_err(|_|"RESEARCH_PREPARATION_OUTCOME_UNKNOWN")??;
            let mut outputs=o.outputs.clone();outputs["environment"]=json!({"runtime_generation_fingerprint":input.expected_active_generation,"binding":binding});
            o=self.preparation_progress(&o,State::Running,"INPUTS",&outputs,&Value::Null).await?;
        }
        // Registry was dropped before reopening actual shared proof owners.
        let datasets=Datasets::open(&config.research_root.join("datasets"),8192,8*1024*1024)?;
        let control=crate::application::research_run_execution::Control::default();
        let (source,resolution,request,native,manual,frozen)=match &input.origin {
            BacktestOrigin::ManualStrategy{..}=> {
                let runtime=RuntimeInputHold::open(&config.runtime_root,&o.request.reserved_run_id(),&input.backtest_command_id,text(&o.outputs["environment"],"runtime_generation_fingerprint")?)?;
                if runtime.binding()!=&o.outputs["environment"]["binding"] {return Err(INVALID.into());}
                let resolved={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
                    crate::application::strategy_validation::ResolvedValidation::resolve(client,&o,runtime,installation.clone(),&datasets,&control).await?};
                let source=resolved.source_revision().clone();let record=resolved.record();
                (source,record["algorithm_resolution"].clone(),record["algorithm_resolution_request"].clone(),record["native_implementations"].clone(),Some(resolved),None)
            },
            BacktestOrigin::FrozenStrategy{..}=> {
                let proof=self.backtest_admission(&o).await?;
                let (runtime,record,request)=self.backtest_resolution(&o,installation.clone(),&proof).await?;
                let native=record["native_implementations"].clone();drop(runtime);
                (proof.source_revision().clone(),record["algorithm_resolution"].clone(),request,native,None,Some(proof))
            },
        };
        let graph=onlyalpha_calculation::product::Graph::from_record(&source.to_record()["decision_graph"],8*1024*1024).map_err(|_|INVALID)?;
        let window=backtest_dataset_event_window(&graph)?;
        if manual.as_ref().is_some_and(|resolved|resolved.input_window()["dataset_event_start_ns"]!=window["dataset_event_start_ns"]||resolved.input_window()["dataset_event_end_ns"]!=window["dataset_event_end_ns"]) {return Err(INVALID.into());}
        let event_start=text(&window,"dataset_event_start_ns")?.parse().map_err(|_|INVALID)?;let event_end=text(&window,"dataset_event_end_ns")?.parse().map_err(|_|INVALID)?;
        let definition=json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":["BTCUSDT.BINANCE"],"bar_semantic":source.to_record()["market_input_contract"]["bar_semantic"],"time_range":{"start":timestamp(event_start)?,"end":timestamp(event_end)?},"quality_policy":"STRICT","closed_only":true});
        let result=self.research_inputs(ResearchInputRequest{human:human.clone(),session:&session,source:&input.source,window:DatasetEventWindow::new(event_start,event_end,BAR)?,definition:&definition,command:&o.command,datasets:&datasets,deadline:Instant::now()+Duration::from_secs(10)}).await.map_err(|e|e.code())?;
        let acquired=match result {ResearchInputOutcome::Pending(v)=> {self.preparation_progress(&o,State::InputPending,"ACQUISITION",&o.outputs,&v).await?;return Ok(());},ResearchInputOutcome::Unavailable(v)=> {self.preparation_progress(&o,State::Blocked,"ACQUISITION",&o.outputs,&v).await?;return Ok(());},ResearchInputOutcome::Prepared(v)=>v};
        o=self.preparation_checkpoint(&o,&human).await?;authority.check_session(&session).map_err(|_|"RESEARCH_SOURCE_ACCESS_DENIED")?;
        session.require_selection(&selection,Permission::ClosedHistory).map_err(|_|"RESEARCH_SOURCE_ACCESS_DENIED")?;
        let rest=PublicRest::from_configuration(selected.public_configuration(),8*1024*1024,self.resolver.public_transport_trust()).map_err(|_|"BACKTEST_RULES_UNAVAILABLE")?;
        if rest.source_id()!=selection.source_id(){return Err(INVALID.into());}
        let response=rest.exchange_info(&["BTCUSDT".into()],Instant::now()+Duration::from_secs(10)).await.map_err(|_|"BACKTEST_RULES_UNAVAILABLE")?;
        let captured_at=OnlyTimestamp::from_datetime(now().map_err(|e|e.code())?);
        let source_ref=format!("backtest-rules:{}",o.command.value());
        let rules=response.spot_rule_snapshot(rest.source_id(),captured_at.clone(),&source_ref).map_err(|_|"BACKTEST_RULES_UNAVAILABLE")?;
        let rule_record=json!({"schema_version":1,"contract":"ONLYALPHA_BINANCE_PUBLIC_RULE_OCCURRENCE_V1","source":input.source,
            "request":{"source_id":response.request().source_id(),"rest_base":response.request().rest_base(),"path":response.request().path(),"symbols":response.request().parameter("symbols")},
            "captured_at":captured_at.to_record(),"body":std::str::from_utf8(response.bytes()).map_err(|_|INVALID)?,"body_sha256":Sha256::digest(response.bytes()).iter().map(|b|format!("{b:02x}")).collect::<String>(),"snapshot":rules.record()});
        let (validation,proof)=if let Some(resolved)=manual {
            o=self.preparation_progress(&o,State::Running,"VALIDATING_STRATEGY",&o.outputs,&Value::Null).await?;
            let observer=control.clone();let installed=installation.clone();let version=config.native_version.clone();
            let observed_datasets=Datasets::open(&config.research_root.join("datasets"),8192,8*1024*1024)?;
            let observed=MaterializedDataset::load(&observed_datasets,text(acquired.materialized.lineage(),"materialization_id")?)?;
            let joined=tokio::task::spawn_blocking(move||resolved.observe(installed,&version,&observer,&observed_datasets,&observed)).await
                .map_err(|_|control.uncertain("STRATEGY_VALIDATION_PRODUCER_OUTCOME_UNKNOWN"))??;
            o=self.preparation_checkpoint(&o,&human).await?;
            let store=crate::persistence::strategy_validation::Store::open(&config.research_root)?.with_runtime_root(&config.runtime_root)?;
            let validation={let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
                Arc::new(store.publish(session,joined).await?)};
            o=self.preparation_progress(&o,State::Running,"FREEZING_STRATEGY",&o.outputs,&Value::Null).await?;
            let proof=self.admit_manual_backtest(&o,&human,validation.clone()).await?;
            (Some(validation),proof)
        }else{(None,frozen.ok_or(INVALID)?)};
        let mut runtime=RuntimeInputHold::open(&config.runtime_root,&o.request.reserved_run_id(),&input.backtest_command_id,text(&o.outputs["environment"],"runtime_generation_fingerprint")?)?;
        let binding=runtime.backtest_execution_binding()?;
        let prepared=build_prepared_next_open(proof.source_revision(),&acquired.materialized,rules,text(runtime.manifest(),"runtime_generation_fingerprint")?)?;
        let ready=crate::persistence::research_preparation::BacktestReady::derive(&o,&proof,validation.as_deref(),&prepared,&datasets,&acquired.materialized,&acquired.selection,&resolution,&request,&native,&binding,&rule_record)?;
        ready.verify_cut()?;proof.verify_cut()?;runtime.verify()?;self.preparation_checkpoint(&o,&human).await?;
        authority.check_session(&session).map_err(|_|"RESEARCH_SOURCE_ACCESS_DENIED")?;
        session.require_selection(&selection,Permission::ClosedHistory).map_err(|_|"RESEARCH_SOURCE_ACCESS_DENIED")?;
        // Owning transaction rechecks the actual proofs at the durable READY handoff.
        {let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            crate::persistence::research_preparation::publish_backtest_ready(session,&ready).await?;}
        Ok(())
    }
    async fn backtest_calculations(&self,o:&Operation,proof:&VerifiedBacktestAdmission)->Result<Value> {
        if matches!(o.request.backtest()?.origin,BacktestOrigin::ManualStrategy{..}) {
            let config=&self.research_preparation_config;
            let store=crate::persistence::strategy_validation::Store::open(&config.research_root)?.with_runtime_root(&config.runtime_root)?;
            let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            let validation=store.read_verified(client,o.command.value()).await?;
            if validation.source_revision().fingerprint()!=proof.strategy_fingerprint()
                || o.outputs["ready"]["validation_fingerprint"]!=validation.fingerprint(){return Err(INVALID.into());}
            validation.verify_cut()?;Ok(validation.record()["prepared_inputs"].clone())
        }else{Ok(proof.validated_calculations()?.clone())}
    }
    async fn backtest_resolution(&self,o:&Operation,installation:Arc<ChartInstallation>,proof:&VerifiedBacktestAdmission)->Result<(RuntimeInputHold,Value,Value)> {
        let input=o.request.backtest()?;
        let runtime=RuntimeInputHold::open(&self.research_preparation_config.runtime_root,&o.request.reserved_run_id(),&input.backtest_command_id,text(&o.outputs["environment"],"runtime_generation_fingerprint")?)?;
        if runtime.binding()!=&o.outputs["environment"]["binding"] {return Err(INVALID.into());}
        let original=self.backtest_calculations(o,proof).await?;
        let mut evidence=RuntimeEvidenceHold::open(&self.research_preparation_config.runtime_root,&o.request.reserved_run_id(),&input.backtest_command_id,text(&o.outputs["environment"],"runtime_generation_fingerprint")?)?;
        let installed=evidence.installed_proof(installation.artifact_fingerprint())?;
        if original["algorithm_resolution"]["algorithm_artifact"]!=installation.artifact_fingerprint(){return Err(INVALID.into());}
        let ready=json!({"algorithm_resolution":original["algorithm_resolution"]});
        crate::persistence::backtest_evidence::verify_implementation_bindings(proof.source_revision(),&ready,runtime.manifest(),&installed)?;
        let record=json!({"algorithm_resolution":original["algorithm_resolution"],"native_implementations":installed["native_descriptor"]["implementations"]});
        proof.verify_cut()?;runtime.verify()?;installation.verify().map_err(|_|"RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
        Ok((runtime,record,original["algorithm_resolution_request"].clone()))
    }
    async fn backtest_ready_owners(&self,o:&Operation)->Result<ReadyOwners> {
        let config=&self.research_preparation_config;pinned_release(config,o)?;
        self.backtest_rule_source(o).await?;
        let admission=self.backtest_admission(o).await?;
        let release=release(config)?;let installation=Arc::new(ChartInstallation::open(&config.algorithms_root,text(&release,"algorithm_artifact")?).map_err(|_|"RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?);
        let (mut runtime,resolution,request)=self.backtest_resolution(o,installation,&admission).await?;
        let ready=&o.outputs["ready"];
        if resolution["algorithm_resolution"]!=ready["algorithm_resolution"] || request!=ready["algorithm_resolution_request"]
            || runtime.backtest_execution_binding()?!=ready["backtest_binding"] {return Err(INVALID.into());}
        let datasets=Datasets::open(&config.research_root.join("datasets"),8192,8*1024*1024)?;
        let materialized=MaterializedDataset::load(&datasets,text(ready,"dataset_materialization_id")?)?;
        let prepared=build_prepared_next_open(admission.source_revision(),&materialized,retained_rules(o)?,text(runtime.manifest(),"runtime_generation_fingerprint")?)?;
        let validation=self.verify_manual_validation(o,&admission,&materialized).await?;
        let inputs=backtest_run::Inputs::new(&prepared,&admission,&mut runtime,&materialized,&datasets,o,validation.as_deref())?;
        if prepared.record()!=ready["preparation"] || prepared.inputs().record()!=ready["input_sources"] || inputs.specification().record()!=&ready["specification"] {return Err(INVALID.into());}
        Ok(ReadyOwners{admission,runtime,materialized,datasets,prepared,validation})
    }
    async fn verify_manual_validation(&self,o:&Operation,admission:&VerifiedBacktestAdmission,materialized:&MaterializedDataset)->Result<Option<Arc<crate::persistence::strategy_validation::VerifiedValidation>>> {
        if matches!(o.request.backtest()?.origin,BacktestOrigin::ManualStrategy{..}) {
            let config=&self.research_preparation_config;
            let store=crate::persistence::strategy_validation::Store::open(&config.research_root)?.with_runtime_root(&config.runtime_root)?;
            let validation={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;store.read_verified(client,o.command.value()).await?};
            validation.require_backtest_inputs(o,admission.source_revision(),materialized)?;
            Ok(Some(Arc::new(validation)))
        }else if o.outputs["ready"]["validation_fingerprint"].is_null(){Ok(None)}else{Err(INVALID.into())}
    }
    async fn backtest_rule_source(&self,o:&Operation)->Result<()> {
        let source=o.source()?;let selection=source.selection()?;
        let reference=crate::application::source_access::Reference::new(&source.integration_id,&source.integration_revision_fingerprint,Some(&source.expected_type_id)).map_err(|e|e.code())?;
        let (selected,_)=self.resolve(&reference).await.map_err(|e|e.code())?;
        if selected.selection()!=&selection {return Err(INVALID.into());}
        let rest=PublicRest::from_configuration(selected.public_configuration(),8*1024*1024,self.resolver.public_transport_trust()).map_err(|_|"BACKTEST_RULES_UNAVAILABLE")?;
        if rest.source_id()!=source.source_id || o.outputs["ready"]["rules_response"]["request"]["rest_base"]!=rest.rest_base() {return Err(INVALID.into());}
        Ok(())
    }
    /// A current readiness observation, never executable Inputs or a Run grant.
    /// The retained owners verify original metadata and physical bytes without
    /// opening an SDK child, taking the writer, or reopening a released work.
    pub(crate) async fn backtest_readiness_observation(&self,o:&Operation,human:&human_access::Session)->Result<()> {
        if self.preparation_owner(human)?!=o.owner {return Err(INVALID.into());}
        let input=o.request.backtest()?;
        let (authority,session,selection)=self.preparation_sources(human,&input.source,true).await?;
        self.backtest_rule_source(o).await?;
        let admission=self.backtest_admission(o).await?;
        {let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_|INVALID)?;
            admission.verify_in_transaction(&tx,admission.namespace()).await?;tx.commit().await.map_err(|_|INVALID)?;}
        let datasets=Datasets::open(&self.research_preparation_config.research_root.join("datasets"),8192,8*1024*1024)?;
        let materialized=MaterializedDataset::load(&datasets,text(&o.outputs["ready"],"dataset_materialization_id")?)?;
        let validation=self.verify_manual_validation(o,&admission,&materialized).await?;
        let prior=self.backtest_calculations(o,&admission).await?;
        let config=self.research_preparation_config.clone();let original=o.clone();
        tokio::task::spawn_blocking(move||->Result<()> {
            pinned_release(&config,&original)?;
            let input=original.request.backtest()?;let ready=&original.outputs["ready"];
            let generation=text(&original.outputs["environment"],"runtime_generation_fingerprint")?;
            let work=original.request.reserved_run_id();
            let mut runtime=RuntimeEvidenceHold::open(&config.runtime_root,&work,&input.backtest_command_id,generation)?;
            // Evidence history alone permits released/retired reads. READY must
            // also prove this original work is still active and not closed.
            let observed=Registry::inspect_work(&config.runtime_root,&work,generation,&input.backtest_command_id)?;
            if observed["active"]!=true || observed["closed"]!=false
                || observed["binding"]!=original.outputs["environment"]["binding"]
                || runtime.binding()!=&observed["binding"]
                || runtime.backtest_binding()?!=ready["backtest_binding"] {return Err(INVALID.into());}
            let release=release(&config)?;
            let installation=ChartInstallation::open(&config.algorithms_root,text(&release,"algorithm_artifact")?).map_err(|_|"RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
            let installed=runtime.installed_proof(installation.artifact_fingerprint())?;
            // Archive availability is insufficient: describe the actual linked
            // image now, without running Python, and compare the complete pin.
            let native=crate::workers::algorithm::describe_native_runtime(&config.native_version).map_err(|_|"BACKTEST_EXECUTOR_UNAVAILABLE")?;
            let binding=&ready["backtest_binding"];
            if installed["native_descriptor"]!=native || installed["release_manifest_sha256"]!=config.release_manifest_fingerprint
                || installed["source_inputs"]!=release["source_inputs"]
                || native["image"]["artifact"]!=binding["executor_artifact_sha256"]
                || native["image"]["version"]!=binding["executor_version"]
                || native["execution_capabilities"]!=runtime.executor_manifest()?["execution_capabilities"]
                || native["execution_capabilities"].as_array().is_none_or(|rows|rows.iter().filter(|r|**r==json!({"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"})).count()!=1) {return Err("BACKTEST_EXECUTOR_UNAVAILABLE".into());}
            if ready["algorithm_resolution"]!=prior["algorithm_resolution"] || ready["algorithm_resolution_request"]!=prior["algorithm_resolution_request"]
                || ready["algorithm_resolution"]["algorithm_artifact"]!=installation.artifact_fingerprint() {return Err(INVALID.into());}
            crate::persistence::backtest_evidence::verify_implementation_bindings(admission.source_revision(),ready,runtime.manifest(),&installed)?;
            let datasets=Datasets::open(&config.research_root.join("datasets"),8192,8*1024*1024)?;
            let materialized=MaterializedDataset::load(&datasets,text(ready,"dataset_materialization_id")?)?;
            let prepared=build_prepared_next_open(admission.source_revision(),&materialized,retained_rules(&original)?,generation)?;
            let preparation=prepared.record();let inputs=prepared.inputs().record();
            let specification=backtest_run::Specification::from_record(&json!({"schema_version":3,"kind":"BTC_SPOT_NEXT_OPEN",
                "strategy_fingerprint":admission.strategy_fingerprint(),"dataset_snapshot_fingerprint":materialized.verified().dataset().snapshot_fingerprint(),
                "runtime_generation_fingerprint":generation,"preparation_fingerprint":hash(&preparation)?}))?;
            let selected=&ready["source_selection"];
            let sealed=&materialized.verified().manifest()["provenance"][0]["source_metadata"]["sealed_input"];
            if ready["preparation_command_id"]!=original.command.value() || ready["preparation_fingerprint"]!=hash(&preparation)?
                || preparation!=ready["preparation"] || inputs!=ready["input_sources"] || specification.record()!=&ready["specification"]
                || selected["preparation_command_id"]!=original.command.value() || selected["source"]!=serde_json::to_value(&input.source).map_err(|_|INVALID)?
                || selected["acquisition"]["status"]!="COMPLETE" || selected["scope"]!=sealed["scope"]
                || sealed["scope"]["source_id"]!=input.source.source_id
                || sealed["scope"]["bar_construction"]["plan"]["integration_revision_fingerprint"]!=input.source.integration_revision_fingerprint
                || selected["revision"]!=sealed["evidence"]["revision"] || selected["seal"]!=sealed["evidence"]["seal"] {return Err(INVALID.into());}
            // Repeat physical owners at the completed observation boundary;
            // their private SH holds remain alive until this closure returns.
            let again=MaterializedDataset::load(&datasets,text(ready,"dataset_materialization_id")?)?;
            if again.lineage()!=materialized.lineage() || again.verified().manifest()!=materialized.verified().manifest() {return Err(INVALID.into());}
            if let Some(validation)=&validation{validation.verify_cut()?;}
            admission.verify_cut()?;runtime.verify()?;installation.verify().map_err(|_|"RESEARCH_ALGORITHM_INSTALLATION_CHANGED")?;
            Ok(())
        }).await.map_err(|_|PreparationError::from("BACKTEST_READINESS_UNAVAILABLE"))??;
        self.preparation_owner(human)?;
        authority.check_session(&session).map_err(|_|"RESEARCH_SOURCE_ACCESS_DENIED")?;
        session.require_selection(&selection,Permission::ClosedHistory).map_err(|_|"RESEARCH_SOURCE_ACCESS_DENIED")?;
        Ok(())
    }
    fn backtest_create_request(o:&Operation)->Result<CreateRequest> {
        let future=CommandId::new(o.request.future_command()).map_err(|_|INVALID)?;
        CreateRequest::new(future.clone(),&run_id(&future),backtest_run::Specification::from_record(&o.outputs["ready"]["specification"])?).map_err(Into::into)
    }
    pub(super) async fn backtest_preparation_view(&self,o:&Operation,human:&human_access::Session)->Result<Value> {
        if self.preparation_owner(human)?!=o.owner{return Err(INVALID.into());}
        let mut view=o.view();let namespace=namespace(&self.research_preparation_config)?;
        if o.outputs.get("ready").is_none() {
            let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
            let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_|INVALID)?;
            deployment::verify_binding_in_transaction(&tx,&namespace).await.map_err(|e|e.code())?;
            let future=CommandId::new(o.request.future_command()).map_err(|_|INVALID)?;
            match crate::persistence::postgres::Commands::verify_binding_in_transaction(&tx,&future).await.map_err(|e|e.code())? {
                crate::application::command::Binding::None=> {if tx.query_opt("SELECT 1 FROM backtest_run WHERE run_id=$1::text::uuid",&[&o.request.reserved_run_id()]).await.map_err(|_|INVALID)?.is_some(){return Err(INVALID.into());}view["backtest_outcome"]=json!("NOT_SUBMITTED");},
                crate::application::command::Binding::Admitted(a) if a.kind()==crate::application::command::CommandKind::CreateBacktestRun=>view["backtest_outcome"]=json!("OUTCOME_UNKNOWN"),
                _=>return Err(INVALID.into()),
            }
            tx.commit().await.map_err(|_|INVALID)?;
        }
        else {
            let request=Self::backtest_create_request(o)?;let outcome={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or("PRODUCT_READ_DRIVER_UNAVAILABLE")?;
                crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&request,&o.owner).await?};
            match outcome {CreationOutcome::Accepted(run)=> {view["backtest_outcome"]=json!("ACCEPTED");view["run_id"]=json!(run.run_id());return Ok(view);},CreationOutcome::Pending=> {view["backtest_outcome"]=json!("OUTCOME_UNKNOWN");return Ok(view);},CreationOutcome::NotSubmitted=>view["backtest_outcome"]=json!("NOT_SUBMITTED")}
            if !matches!(o.state,State::Cancelled|State::CancelRequested){view["readiness"]=match self.backtest_readiness_observation(o,human).await {Ok(())=>json!({"state":"VERIFIED","code":null}),Err(e)=>json!({"state":"UNAVAILABLE","code":e.code()})};}
        }
        self.preparation_owner(human)?;
        if o.state==State::Cancelled {
            view["cleanup"]=match backtest_work_generation(&self.research_preparation_config,o) {
                Ok(None)=>json!({"state":"COMPLETED"}),
                Ok(Some(_))|Err(_)=>json!({"state":"PENDING","work_id":o.request.reserved_run_id()}),
            };
        }
        Ok(view)
    }
    pub(super) async fn cleanup_cancelled_backtest_preparation(&self,o:&Operation)->Value {
        let Ok(current)=self.preparation_query(&o.command,&o.owner).await else{return json!({"state":"PENDING"});};
        if current.state!=State::Cancelled {return json!({"state":"NOT_APPLICABLE"});}
        let generation=match backtest_work_generation(&self.research_preparation_config,&current) {Ok(Some(value))=>value,Ok(None)=>return json!({"state":"COMPLETED"}),Err(_)=>return json!({"state":"PENDING"})};
        let Ok(input)=current.request.backtest() else{return json!({"state":"PENDING"});};
        let root=self.research_preparation_config.runtime_root.clone();let work=current.request.reserved_run_id();let command=input.backtest_command_id.clone();
        let namespace=match namespace(&self.research_preparation_config){Ok(v)=>v,Err(_)=>return json!({"state":"PENDING"})};
        let new_work_absent=async {
            let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or(INVALID)?;
            let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(|_|INVALID)?;
            let eligible=crate::persistence::research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&command).await?;
            let exact=eligible.is_some_and(|operation|operation.command==current.command&&operation.owner==current.owner);
            tx.commit().await.map_err(|_|INVALID)?;Ok::<bool,&'static str>(exact)
        }.await;
        if new_work_absent!=Ok(true) {return json!({"state":"RUN_OWNER"});}
        if current.outputs.get("ready").is_some() {let Ok(request)=Self::backtest_create_request(&current) else{return json!({"state":"PENDING"});};
            let mut reader=self.reader.lock().await;let Some(client)=reader.as_mut()else{return json!({"state":"PENDING"});};
            if !matches!(crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&request,&current.owner).await,Ok(CreationOutcome::NotSubmitted)){return json!({"state":"RUN_OWNER"});}}
        // No owning proof is live. A busy historical SH reader retains the
        // exact pending binding; this path never reopens or replaces work.
        let actor=current.owner.clone();let result=tokio::task::spawn_blocking(move||->std::result::Result<Value,&'static str>{
            {let observed=Registry::inspect_work(&root,&work,&generation,&command)?;if observed["closed"]==true{return Ok(json!({"state":"COMPLETED"}));}}
            let mut registry=Registry::open_existing(&root)?;
            registry.release_work_exact(&work,&generation,&command,&actor,now().map_err(|e|e.code())?)?;
            Ok(json!({"state":"COMPLETED"}))
        }).await;
        match result {Ok(Ok(v))=>v,_=>json!({"state":"PENDING","work_id":current.request.reserved_run_id()})}
    }
    pub(crate) async fn confirm_backtest_preparation(self:&Arc<Self>,human:human_access::Session,command:&CommandId,expected:&str,future:&CommandId)->std::result::Result<Value,Failure> {
        let owner=self.preparation_owner(&human).map_err(failure)?.to_owned();let o=self.preparation_query(command,&owner).await.map_err(failure)?;
        if !o.request.is_backtest() || o.request.future_command()!=future.value() || o.outputs["ready"]["preparation_fingerprint"]!=expected {return Err(failure(INVALID.into()));}
        let request=Self::backtest_create_request(&o).map_err(failure)?;let namespace=namespace(&self.research_preparation_config).map_err(failure)?;
        let outcome={let mut reader=self.reader.lock().await;let client=reader.as_mut().ok_or_else(||failure("PRODUCT_READ_DRIVER_UNAVAILABLE".into()))?;
            crate::persistence::backtest_run::creation_outcome_readonly(client,&namespace,&request,&owner).await.map_err(|e|failure(e.into()))?};
        match outcome {CreationOutcome::Accepted(run)=>return Ok(json!({"run_id":run.run_id()})),CreationOutcome::Pending=>return Ok(json!({"state":"SUBMISSION_PENDING","backtest_command_id":future.value()})),CreationOutcome::NotSubmitted=>{}}
        if o.state!=State::Ready{return Err(failure("RESEARCH_PREPARATION_NOT_READY".into()));}
        self.require_backtest_worker().await?;
        self.launch_preparation_confirmation(o,human,expected).await
    }
    pub(super) async fn confirm_backtest_preparation_body(self:&Arc<Self>,o:Operation,human:human_access::Session,expected:&str)->Result<Value> {
        let request=Self::backtest_create_request(&o)?;let namespace=namespace(&self.research_preparation_config)?;
        let source=o.source()?;
        let (a,s,selection)=self.preparation_sources(&human,&source,true).await?;
        let context=backtest_run::Context{human_authority:&self.human_access,human:&human,source_authority:&a,source:&s,selection:&selection};
        let mut owners=self.backtest_ready_owners(&o).await?;
        let inputs=backtest_run::Inputs::new(&owners.prepared,&owners.admission,&mut owners.runtime,&owners.materialized,&owners.datasets,&o,owners.validation.as_deref())?;
        let run={let mut writer=self.writer.lock().await;let session=writer.as_mut().ok_or("PRODUCT_AUTHORITY_UNAVAILABLE")?;
            Backtests::new(session,&namespace).create_prepared(&request,&context,&inputs,&o,expected,now().map_err(|e|e.code())?).await?};
        self.wake_backtest_after_commit();
        Ok(json!({"run_id":run.run_id()}))
    }
}

#[cfg(test)]
#[path="../../tests/transport/backtest_preparation_window.rs"]
mod window_tests;
