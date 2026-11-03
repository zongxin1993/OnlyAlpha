//! Technical regressions over a real joined producer occurrence. This module
//! never constructs VerifiedValidation, fabricates Research evidence, or serves
//! a Shipping endpoint. The caller must provision a RUNNING original manual
//! preparation with an actually published strategy-validation manifest.
use crate::{application::{command::CommandId,frozen_strategy::FrozenStore,strategy_projection::{Freezes,freeze_outcome}},
    bootstrap::deployment,persistence::{authority_session::AuthoritySession,research_preparation::{self,Operation,State},strategy_validation::Store as Validations},
    security::{human_access::{Access,Admission},protected_files}};
use serde_json::{Value,json};
use std::{os::fd::AsFd,path::Path,sync::Arc};
const WORK:usize=64*1024*1024;
async fn parent(session:&mut AuthoritySession,command:&CommandId,owner:&str)->Operation {
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();
    let value=research_preparation::load(&tx,command,owner).await.unwrap();tx.commit().await.unwrap();value
}
/// Separate invocations deliberately reopen the actual owners after PREPARED.
/// Suggested sequence for one real producer: stop-prepared -> cancel-parent ->
/// resume-after-cancel -> replay-after-cancel -> physical-replacement -> sql-denials.
/// Use an independent real producer for cancel-before-prepared.
pub async fn run_phase(session:&mut AuthoritySession,root:&Path,phase:&str) {
    let request:Value=serde_json::from_slice(&std::fs::read(std::env::var("ONLYALPHA_MANUAL_FREEZE_REQUEST").unwrap()).unwrap()).unwrap();
    let command=CommandId::new(request["preparation_command_id"].as_str().unwrap()).unwrap();
    let owner=request["owner"].as_str().unwrap();let at=request["at"].as_str().unwrap();
    let original=parent(session,&command,owner).await;
    let child=research_preparation::child_command(&command,"manual-backtest-freeze").unwrap();
    if phase=="cleanup-eligibility-and-retry" {cleanup_eligibility_and_retry(session,root,&request,&original).await;return;}
    if matches!(phase,"cancel-parent"|"cancel-before-prepared") {
        assert_eq!(original.state,State::Running,"new-admission fixture is an actual RUNNING original parent");
        let cancel=research_preparation::child_command(&command,"manual-freeze-test-cancel").unwrap();
        let changed=research_preparation::cancel_backtest(session,&cancel,&command,owner,original.revision,at.parse().unwrap()).await.unwrap();
        assert!(matches!(changed.state,State::CancelRequested|State::Cancelled));
        assert_eq!(original.accepted["schema_version"],2);
        assert!(original.accepted["input"].get("research_command_id").is_none());
        assert_eq!(original.accepted["input"]["backtest_command_id"],original.request.future_command());
        let replayed=research_preparation::cancel_backtest(session,&cancel,&command,owner,original.revision,at.parse().unwrap()).await.unwrap();
        assert_eq!(replayed.view(),changed.view(),"schema2 cancellation reopens its original receipt instead of resubmitting");
        if phase=="cancel-parent" {println!("MANUAL_FREEZE_VALUE {}",json!({"parent":changed.state.as_str(),"freeze_command_id":child.value()}));return;}
    }
    let original=parent(session,&command,owner).await;
    let validations=Validations::open(root).unwrap().with_runtime_root(Path::new(request["runtime_root"].as_str().unwrap())).unwrap();
    let validation=validations.read_verified(session.client_mut().await.unwrap(),command.value()).await.unwrap();
    let selected=protected_files::open_directory(root).unwrap();let namespace=deployment::load_semantic_store_id_at(&selected).unwrap();
    let frozen=FrozenStore::open(selected.as_fd()).unwrap();
    let token="a".repeat(64);let access=Access::new(&token).unwrap();
    let message=http::Request::builder().uri("/api/v2/integration-types").header("host","127.0.0.1:5173").header("cookie",format!("onlyalpha_dev_session={token}")).body(()).unwrap();
    let Admission::Owner(human)=access.admit(&message).unwrap() else {panic!("actual owner session")};
    assert_eq!(human.subject_id().unwrap(),owner);
    if phase.starts_with("q-")||phase.starts_with("p-") {
        qualification_promotion_phase(session,root,phase,&request,&original,&frozen,&namespace,&access,&human).await;return;
    }
    if phase=="cancel-before-prepared" {
        assert_eq!(freeze_outcome(session.client_mut().await.unwrap(),&namespace,owner,&child).await.unwrap()["state"],"NOT_SUBMITTED");
        let error=Freezes::new(session,&frozen,&namespace,&human).execute_manual(&validation,&original,at,4096,WORK).await.unwrap_err();
        assert_eq!(error,"STRATEGY_FREEZE_PREPARATION_NOT_RUNNING");
        assert!(session.verify().await.is_err(),"the original failed mutation session must close");
        println!("MANUAL_FREEZE_VALUE {}",json!({"denied":error,"freeze_command_id":child.value(),"parent":original.state.as_str()}));
        return;
    }
    if phase=="stop-prepared" {
        let mut owner=Freezes::new(session,&frozen,&namespace,&human);owner.stop_at("prepared").unwrap();
        assert_eq!(owner.execute_manual(&validation,&original,at,4096,WORK).await.unwrap_err(),"STRATEGY_FREEZE_COMMAND_UNKNOWN");
        println!("MANUAL_FREEZE_VALUE {}",json!({"freeze_command_id":child.value(),"stopped_at":"PREPARED"}));return;
    }
    if phase=="sql-denials" {sql_denials(session,validation.source_revision().fingerprint(),command.value(),validation.fingerprint(),at).await;return;}
    let before=freeze_outcome(session.client_mut().await.unwrap(),&namespace,owner,&child).await.unwrap();
    if phase=="resume-after-cancel" {assert_eq!(before["state"],"PENDING");assert!(matches!(original.state,State::CancelRequested|State::Cancelled));}
    if phase=="replay-after-cancel" {assert_eq!(before["state"],"COMPLETED");assert!(matches!(original.state,State::CancelRequested|State::Cancelled));}
    let value=Freezes::new(session,&frozen,&namespace,&human).execute_manual(&validation,&original,at,4096,WORK).await.unwrap();
    assert_eq!(value["command_id"],child.value());assert_eq!(value["strategy_fingerprint"],validation.source_revision().fingerprint());
    if phase=="replay-after-cancel" {assert_eq!(value["replayed"],true);assert_eq!(before["result"]["freeze_relation_fingerprint"],value["freeze_relation_fingerprint"]);}
    let relation=value["freeze_relation_fingerprint"].as_str().unwrap();
    let proof=frozen.read_verified_manual(Arc::new(validation),relation,WORK).unwrap();proof.verify_cut().unwrap();
    if phase=="physical-replacement" {
        let file=root.join("strategy/freeze-relations/sha256").join(&relation[..2]).join(relation).join("manifest.json");
        let held=file.with_file_name("retained-original.json");let replacement=file.with_file_name("replacement.json");
        std::fs::copy(&file,&replacement).unwrap();std::fs::rename(&file,&held).unwrap();std::fs::rename(&replacement,&file).unwrap();
        assert!(proof.verify_cut().is_err(),"identical JSON under a replacement inode cannot reseal the selected Frozen cut");
        std::fs::remove_file(&file).unwrap();std::fs::rename(&held,&file).unwrap();proof.verify_cut().unwrap();
    }
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();proof.verify_in_transaction(&tx,&namespace).await.unwrap();
    let frozen_count:i64=tx.query_one("SELECT count(*) FROM public.strategy_freeze_command_admission WHERE command_id=$1::text::uuid",&[&child.value()]).await.unwrap().get(0);assert_eq!(frozen_count,1);
    let related_runs:i64=tx.query_one("SELECT count(*) FROM public.backtest_run WHERE run_id=$1::text::uuid",&[&original.request.reserved_run_id()]).await.unwrap().get(0);assert_eq!(related_runs,0,"Freeze recovery cannot admit a Backtest Run");
    tx.commit().await.unwrap();println!("MANUAL_FREEZE_VALUE {}",value);
}
async fn sql_denials(session:&mut AuthoritySession,strategy:&str,preparation:&str,validation:&str,at:&str) {
    let mut wrong=validation.to_owned();wrong.replace_range(..1,if validation.starts_with('a'){"b"}else{"a"});
    let timestamp=crate::persistence::postgres::system_time(at.parse().unwrap()).unwrap();
    let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
    // Every attempt is rolled back even if a future regression accepts it.
    for (index,(schema,kind,candidate,selected,expected)) in [
        (5,"MANUAL_BACKTEST",Some("a".repeat(64)),validation,tokio_postgres::error::SqlState::CHECK_VIOLATION),
        (5,"RESEARCH",None,validation,tokio_postgres::error::SqlState::CHECK_VIOLATION),
        (5,"MANUAL_BACKTEST",None,wrong.as_str(),tokio_postgres::error::SqlState::FOREIGN_KEY_VIOLATION),
        (4,"MANUAL_BACKTEST",None,validation,tokio_postgres::error::SqlState::CHECK_VIOLATION),
    ].into_iter().enumerate() {
        tx.batch_execute("SAVEPOINT denied_manual_origin").await.unwrap();
        let id=crate::application::factor_content::hash(&json!({"technical_invalid_manual_freeze":index})).unwrap();
        let result=tx.execute("INSERT INTO public.strategy_freeze_record(freeze_record_fingerprint,strategy_fingerprint,actor,created_at,schema_version,origin_kind,preparation_command_id,strategy_validation_fingerprint,candidate_fingerprint) VALUES($1,$2,'technical-origin-test',$3,$4,$5,$6::text::uuid,$7,$8)",&[&id,&strategy,&timestamp,&schema,&kind,&preparation,&selected,&candidate]).await;
        assert_eq!(result.as_ref().err().and_then(|error|error.code()),Some(&expected),"invalid origin {index} must fail in the actual schema");
        tx.batch_execute("ROLLBACK TO SAVEPOINT denied_manual_origin").await.unwrap();
    }
    for (index,(schema,kind,candidate,selected,expected)) in [
        (2i16,"MANUAL_BACKTEST",Some("a".repeat(64)),validation,tokio_postgres::error::SqlState::CHECK_VIOLATION),
        (1i16,"MANUAL_BACKTEST",None,validation,tokio_postgres::error::SqlState::CHECK_VIOLATION),
        (2i16,"MANUAL_BACKTEST",None,wrong.as_str(),tokio_postgres::error::SqlState::FOREIGN_KEY_VIOLATION),
    ].into_iter().enumerate() {
        tx.batch_execute("SAVEPOINT denied_manual_command_origin").await.unwrap();
        let command=format!("00000000-0000-4000-8000-{:012}",9900+index);
        let result=tx.execute("INSERT INTO public.strategy_freeze_command_admission(command_id,command_fingerprint,actor,state,prepared_at,schema_version,origin_kind,preparation_command_id,strategy_validation_fingerprint,candidate_fingerprint) VALUES($1::text::uuid,$2,'technical-origin-test','PREPARED',$3,$4,$5,$6::text::uuid,$7,$8)",&[&command,&"a".repeat(64),&timestamp,&schema,&kind,&preparation,&selected,&candidate]).await;
        assert_eq!(result.as_ref().err().and_then(|error|error.code()),Some(&expected),"invalid Command origin {index} must fail in the actual schema");
        tx.batch_execute("ROLLBACK TO SAVEPOINT denied_manual_command_origin").await.unwrap();
    }
    tx.rollback().await.unwrap();println!("MANUAL_FREEZE_VALUE {}",json!({"sql_origin_denials":7}));
}

/// All facts and receipts below come from real owners. Use a fresh real
/// mathematical-validation/Freeze fixture before each cancellation scenario.
async fn qualification_promotion_phase(
    session:&mut AuthoritySession,root:&Path,phase:&str,request:&Value,original:&Operation,
    frozen:&FrozenStore,namespace:&deployment::SemanticStoreId,access:&Access,human:&crate::security::human_access::Session,
) {
    use crate::{application::{qualification::Request as QRequest,qualification_policy::Store as Policies},
        persistence::{qualification_commands::{self,Qualifications},qualification_decision::Store as Decisions,
            strategy_promotion::{Promotions,Request as PRequest},postgres::Commands}};
    let owner=request["owner"].as_str().unwrap();let at=request["at"].as_str().unwrap();
    let command=&original.command;
    let freeze=research_preparation::child_command(command,"manual-backtest-freeze").unwrap();
    let outcome=freeze_outcome(session.client_mut().await.unwrap(),namespace,owner,&freeze).await.unwrap();
    assert_eq!(outcome["state"],"COMPLETED","real immutable Freeze is the prior-stage precondition");
    let validations=Validations::open(root).unwrap().with_runtime_root(Path::new(request["runtime_root"].as_str().unwrap())).unwrap();
    let validation=Arc::new(validations.read_verified(session.client_mut().await.unwrap(),command.value()).await.unwrap());
    let proof=Arc::new(frozen.read_verified_manual(validation,outcome["result"]["freeze_relation_fingerprint"].as_str().unwrap(),WORK).unwrap());
    let descriptor=protected_files::open_directory(root).unwrap();let frozen=Arc::new(FrozenStore::open(descriptor.as_fd()).unwrap());
    let policies=Arc::new(Policies::open(descriptor.as_fd()).unwrap());let decisions=Arc::new(Decisions::open(root).unwrap());
    let qcommand=research_preparation::child_command(command,"manual-backtest-qualification").unwrap();
    let qrequest=QRequest::from_manual(qcommand.clone(),"manual-backtest","1",&proof).unwrap();
    if phase.starts_with("q-") {
        let original_q=qualification_commands::command_outcome_readonly(session.client_mut().await.unwrap(),namespace,qrequest.subject(),&qcommand).await.unwrap();
        if phase=="q-cancel-before-admission" {
            assert_eq!(original_q["state"],"NOT_SUBMITTED");assert_eq!(original.state,State::Running);
            let cancel=research_preparation::child_command(command,"manual-stage-test-cancel").unwrap();
            let changed=research_preparation::cancel_backtest(session,&cancel,command,owner,original.revision,at.parse().unwrap()).await.unwrap();
            assert!(matches!(changed.state,State::CancelRequested|State::Cancelled));
        }
        let mut q=Qualifications::new(session,namespace,policies,decisions,frozen,access,human);
        if phase=="q-stop-prepared" {q.stop_at("prepared").unwrap();}
        let result=q.execute_manual(&qrequest,proof,at.parse().unwrap()).await;
        if phase=="q-cancel-before-admission" {
            assert_eq!(result.err(),Some("MANUAL_BACKTEST_PREPARATION_NOT_RUNNING"));drop(q);
            let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
            assert_eq!(Commands::verify_binding_in_transaction(&tx,&qcommand).await.unwrap(),crate::application::command::Binding::None);
            tx.commit().await.unwrap();
        }else if phase=="q-stop-prepared" {assert_eq!(result.err(),Some("QUALIFICATION_COMMAND_OUTCOME_UNKNOWN"));}
        else if phase=="q-qualify" {
            assert_eq!(original.state,State::Running);assert_eq!(original_q["state"],"NOT_SUBMITTED");assert_eq!(result.unwrap().record()["outcome"],"APPROVED");
        }else {
            assert_eq!(phase,"q-resume-after-cancel");assert_eq!(original_q["state"],"PREPARED");
            assert!(matches!(original.state,State::CancelRequested|State::Cancelled));
            let decision=result.unwrap();assert_eq!(decision.record()["outcome"],"APPROVED");drop(q);
            let current=qualification_commands::command_outcome_readonly(session.client_mut().await.unwrap(),namespace,qrequest.subject(),&qcommand).await.unwrap();
            assert_eq!(current["state"],"COMPLETED");assert_eq!(current["decision_fingerprint"],decision.fingerprint());
        }
        println!("MANUAL_FREEZE_VALUE {}",json!({"phase":phase,"qualification_command_id":qcommand.value()}));return;
    }
    let outcome=qualification_commands::command_outcome_readonly(session.client_mut().await.unwrap(),namespace,qrequest.subject(),&qcommand).await.unwrap();
    assert_eq!(outcome["state"],"COMPLETED");
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();
    let decision=decisions.read_verified_in_transaction(&tx,namespace,Path::new(request["runtime_root"].as_str().unwrap()),outcome["decision_fingerprint"].as_str().unwrap()).await.unwrap();tx.commit().await.unwrap();
    let pcommand=research_preparation::child_command(command,"manual-backtest-promotion").unwrap();
    let intent=PRequest::new(pcommand.clone(),qrequest.subject(),decision.fingerprint(),decision.record()["policy_fingerprint"].as_str().unwrap(),"用户确认策略并准备实验回测").unwrap();
    if phase=="p-cancel-before-admission" {
        assert_eq!(original.state,State::Running);
        let cancel=research_preparation::child_command(command,"manual-stage-test-cancel").unwrap();
        let changed=research_preparation::cancel_backtest(session,&cancel,command,owner,original.revision,at.parse().unwrap()).await.unwrap();
        assert!(matches!(changed.state,State::CancelRequested|State::Cancelled));
    }
    let result=Promotions::new(session,namespace,frozen,access,human).promote(&intent,decision,at.parse().unwrap()).await;
    if phase=="p-cancel-before-admission" {
        assert_eq!(result.err(),Some("MANUAL_BACKTEST_PREPARATION_NOT_RUNNING"));
        let tx=session.client_mut().await.unwrap().transaction().await.unwrap();assert_eq!(Commands::verify_binding_in_transaction(&tx,&pcommand).await.unwrap(),crate::application::command::Binding::None);tx.commit().await.unwrap();
    }else {
        assert!(matches!(phase,"p-promote"|"p-replay-after-cancel"));let record=result.unwrap();
        assert_eq!(record.record()["to_stage"],"BACKTEST");
        if phase=="p-replay-after-cancel" {assert!(matches!(original.state,State::CancelRequested|State::Cancelled));}
    }
    let count:i64=session.client_mut().await.unwrap().query_one("SELECT count(*) FROM public.backtest_run WHERE run_id=$1::text::uuid",&[&original.request.reserved_run_id()]).await.unwrap().get(0);assert_eq!(count,0);
    println!("MANUAL_FREEZE_VALUE {}",json!({"phase":phase,"promotion_command_id":pcommand.value()}));
}

/// Source corruption is injected only in rollback-only technical transactions.
/// Busy/retry uses an actual shared Runtime hold, never sleep as an oracle.
async fn cleanup_eligibility_and_retry(session:&mut AuthoritySession,_root:&Path,request:&Value,original:&Operation) {
    use crate::{bootstrap::deployment::SemanticStoreId,persistence::{postgres::Commands,research_runtime::{Registry,RuntimeEvidenceHold}},
        application::command::{Admission as CommandAdmission,CommandKind}};
    let runtime_root=Path::new(request["runtime_root"].as_str().unwrap());let at=request["at"].as_str().unwrap();
    let work=original.request.reserved_run_id();let reason=original.request.future_command().to_owned();
    let binding=Registry::unreleased_work_bindings(runtime_root).unwrap().into_iter().filter(|(w,_,o)|w==&work&&o==&reason).collect::<Vec<_>>();
    assert_eq!(binding.len(),1);let generation=binding[0].1.clone();
    let namespace=SemanticStoreId::new(original.accepted["semantic_store_id"].as_str().unwrap()).unwrap();
    let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
    research_preparation::require_running_backtest_preparation(&tx,&namespace,original).await.unwrap();tx.rollback().await.unwrap();
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&reason).await.unwrap().is_none(),"RUNNING is not an owner-drain proof");tx.commit().await.unwrap();
    let cancel=research_preparation::child_command(&original.command,"manual-cleanup-test-cancel").unwrap();
    let cancelled=research_preparation::cancel_backtest(session,&cancel,&original.command,&original.owner,original.revision,at.parse().unwrap()).await.unwrap();
    let before_environment_mutation=std::fs::read(runtime_root.join("generation-events.jsonl")).unwrap();
    let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
    assert_eq!(research_preparation::require_running_backtest_preparation(&tx,&namespace,original).await.unwrap_err(),"RESEARCH_PREPARATION_CANCEL_REQUESTED");tx.rollback().await.unwrap();
    assert_eq!(std::fs::read(runtime_root.join("generation-events.jsonl")).unwrap(),before_environment_mutation,"a cancelled parent cannot pass the actual environment-mutation gate");
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&reason).await.unwrap().is_none(),"CANCEL_REQUESTED still has an original worker drain obligation");tx.commit().await.unwrap();
    // The fixture either joined the real mathematical producer before returning,
    // or bound work before launching any child. No original child is outstanding.
    let drained=research_preparation::Preparations::new(session.client_mut().await.unwrap()).progress(&cancelled,State::Cancelled,"OWNER_DRAINED",&cancelled.outputs,&Value::Null).await.unwrap();
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();
    let exact=research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&reason).await.unwrap().unwrap();
    assert_eq!(exact.command,original.command);assert_eq!(exact.accepted,original.accepted);
    let future=CommandId::new(&reason).unwrap();
    let research_work=crate::persistence::research_submission::run_id(&future);
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&research_work,&generation,&reason).await.unwrap().is_none(),"Research's different Run identity is not this Backtest resource");
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,"chart-study:technical").await.unwrap().is_none());
    let other=research_preparation::child_command(&original.command,"not-the-original-future").unwrap();
    let other_work=crate::application::backtest_preparation::run_id(&other);
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,other.value()).await.unwrap().is_none());
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&other_work,&generation,other.value()).await.unwrap().is_none());tx.commit().await.unwrap();
    let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
    let unknown=CommandAdmission::new(future.clone(),CommandKind::CreateBacktestRun,&"a".repeat(64)).unwrap();
    Commands::admit_exact_in_transaction(&tx,&unknown).await.unwrap();
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&reason).await.unwrap().is_none(),"original UNKNOWN submit cannot be called absent");tx.rollback().await.unwrap();
    let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
    let mut corrupt=drained.outputs.clone();corrupt["cancellation"]["command_id"]=json!(other.value());
    let raw=onlyalpha_metadata_json::canonical_json(&corrupt.to_string(),8*1024*1024).unwrap();
    let corrupted=tx.execute("UPDATE public.research_preparation SET outputs_payload=$2 WHERE command_id=$1::text::uuid",&[&original.command.value(),&raw]).await;
    let rejected=match corrupted {Ok(_)=>research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&reason).await.is_err(),Err(error)=>matches!(error.code(),Some(code) if *code==tokio_postgres::error::SqlState::CHECK_VIOLATION||*code==tokio_postgres::error::SqlState::FOREIGN_KEY_VIOLATION||*code==tokio_postgres::error::SqlState::RAISE_EXCEPTION)};
    assert!(rejected,"a raw CANCELLED label with another Command cannot replace the actual cancellation receipt");tx.rollback().await.unwrap();
    let held=RuntimeEvidenceHold::open(runtime_root,&work,&reason,&generation).unwrap();
    let journal=runtime_root.join("generation-events.jsonl");let before=std::fs::read(&journal).unwrap();
    assert!(Registry::open_existing(runtime_root).is_err(),"real SH barrier makes the first EX cleanup unavailable");
    assert_eq!(std::fs::read(&journal).unwrap(),before,"a busy attempt cannot append a release or a replacement binding");drop(held);
    let tx=session.client_mut().await.unwrap().build_transaction().read_only(true).start().await.unwrap();
    assert!(research_preparation::cancelled_backtest_cleanup_in_transaction(&tx,&namespace,&work,&generation,&reason).await.unwrap().is_some());tx.commit().await.unwrap();
    let released=Registry::open_existing(runtime_root).unwrap().release_work_exact(&work,&generation,&reason,&original.owner,at.parse().unwrap()).unwrap();
    let again=Registry::open_existing(runtime_root).unwrap().release_work_exact(&work,&generation,&reason,&original.owner,at.parse().unwrap()).unwrap();assert_eq!(released,again);
    assert!(!Registry::unreleased_work_bindings(runtime_root).unwrap().iter().any(|(w,_,_)|w==&work));
    let run_count:i64=session.client_mut().await.unwrap().query_one("SELECT count(*) FROM public.backtest_run WHERE run_id=$1::text::uuid",&[&work]).await.unwrap().get(0);assert_eq!(run_count,0);
    println!("MANUAL_FREEZE_VALUE {}",json!({"phase":"cleanup-eligibility-and-retry","environment_was_present":original.outputs.get("environment").is_some(),"work_id":work,"released":true,"backtest_runs":0}));
}
