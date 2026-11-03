//! Existing-table operational proof with explicit cfg(test) semantic preconditions.
//! No claim of actual Freeze/Qualification/Runtime admission or Shipping acceptance.
use crate::{
    application::{backtest_run::{Context,CreateRequest,CancelRequest,Inputs,Specification,VerifiedCompletion},command::{CommandId,OutcomeKind},source_access::{Authority,Grant,Permission,Reference,Selection}},
    bootstrap::deployment::SemanticStoreId,
    persistence::{authority_session::AuthoritySession,backtest_run::Backtests,backtest_evidence::CompletionProof},
    security::{human_access::{Access,Session},immutable_json::SourceLock},
};
use serde_json::json;
use std::{path::Path,sync::Arc};
const COMMAND:&str="00000000-0000-4000-8000-000000000801";
const RUN:&str="00000000-0000-4000-8000-000000000802";
const CANCEL:&str="00000000-0000-4000-8000-000000000803";
const WORKER:&str="00000000-0000-4000-8000-000000000804";
const ATTEMPT1:&str="00000000-0000-4000-8000-000000000805";
const ATTEMPT2:&str="00000000-0000-4000-8000-000000000806";
fn at(second:u32)->onlyalpha_domain::time::OnlyUtcDateTime { format!("2026-11-01T00:01:{second:02}Z").parse().unwrap() }
fn value_inputs(namespace:&SemanticStoreId,root:&Path)->Inputs<'static> {
    let prepared=crate::workers::backtest::tests::prepared();
    let preparation=prepared.record();
    let preparation_fp=crate::application::factor_content::hash(&preparation).unwrap();
    let strategy=preparation["strategy_fingerprint"].clone();
    let generation=preparation["settings"]["execution"]["generation"].clone();
    let source=prepared.inputs().record()["sources"][0].clone();
    let specification=Specification::from_record(&json!({"schema_version":3,"kind":"BTC_SPOT_NEXT_OPEN","strategy_fingerprint":strategy,"dataset_snapshot_fingerprint":source["snapshot"],"runtime_generation_fingerprint":generation,"preparation_fingerprint":preparation_fp})).unwrap();
    // These full controlled records are operational test preconditions. The
    // production Inputs constructor must instead hold all actual owning readers.
    let resolution=json!({"schema_version":2,"kind":"BTC_SPOT_NEXT_OPEN_ADMISSION","owner":"local-developer","semantic_store_id":namespace.value(),"strategy_fingerprint":strategy,"freeze_relation_fingerprint":"f".repeat(64),"qualification_decision_fingerprint":"8".repeat(64),"promotion_fingerprint":"9".repeat(64),"dataset_snapshot_fingerprint":source["snapshot"],"dataset_binding_fingerprint":source["dataset_binding"],"runtime_generation_fingerprint":generation,"preparation_fingerprint":preparation_fp,"preparation":preparation,
        "dataset_materialization":{"schema_version":1,"materialization_id":"controlled-existing-materialization","dataset_snapshot_fingerprint":source["snapshot"]},
        "runtime_work_binding":{"schema_version":1,"kind":"RuntimeWorkBound","work_id":RUN,"generation_fingerprint":generation,"reason":COMMAND},
        "backtest_binding":{"executor_manifest_fingerprint":"5".repeat(64),"executor_artifact_sha256":"6".repeat(64),"executor_version":env!("CARGO_PKG_VERSION"),"core_execution_fingerprint":"7".repeat(64),"protocol":"onlyalpha.backtest.executor/1"},
        "source_selection":{"integration_id":"controlled-market","revision_fingerprint":"a".repeat(64),"expected_type_id":"controlled.spot","source_id":"BINANCE_SPOT","environment":"LIVE"}});
    Inputs::for_value_test(specification,resolution,namespace.clone(),Arc::new(SourceLock::publication(root).unwrap())).unwrap()
}
fn completion(run:&crate::application::backtest_run::VerifiedRun,status:&str,root:&Path)->VerifiedCompletion {
    // Root-owned semantic producer seal exists only under cfg(test) for this
    // persistence proof. No portable fingerprint DTO is accepted in production.
    let proof=CompletionProof::for_value_test(run,status,&"1".repeat(64),&"2".repeat(64),&"3".repeat(64),Arc::new(SourceLock::publication(root).unwrap())).unwrap();
    VerifiedCompletion::from_proof(proof).unwrap()
}
pub async fn run_phase(session:&mut AuthoritySession,namespace:&SemanticStoreId,human_authority:&Access,human:&Session,root:&Path,phase:&str) {
    let selection=Selection::new(Reference::new("controlled-market",&"a".repeat(64),Some("controlled.spot")).unwrap(),"BINANCE_SPOT","LIVE").unwrap();
    let source_authority=Authority::new("local-developer","add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",vec![Grant::new(selection.clone(),vec![Permission::ClosedHistory]).unwrap()]).unwrap();
    let source=source_authority.authenticate(&format!("Bearer {}","e".repeat(64))).unwrap();
    let context=Context{human_authority,human,source_authority:&source_authority,source:&source,selection:&selection};
    let inputs=value_inputs(namespace,root);
    let request=CreateRequest::new(CommandId::new(COMMAND).unwrap(),RUN,inputs.specification().clone()).unwrap();
    if matches!(phase,"deferred-create-guard"|"deferred-create-receipt") {
        let statement=if phase=="deferred-create-guard" {
            "CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER INSERT ON backtest_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION backtest_test_deferred()"
        } else {
            "CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE product_command_receipt SET outcome_id='00000000-0000-4000-8000-000000000807' WHERE command_id=NEW.command_id; RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER INSERT ON product_command_receipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.command_kind='CREATE_BACKTEST_RUN') EXECUTE FUNCTION backtest_test_deferred()"
        };
        session.client_mut().await.unwrap().batch_execute(statement).await.unwrap();
        assert!(Backtests::new(session,namespace).create(&request,&context,&inputs,at(0)).await.is_err());
        if phase=="deferred-create-guard" {assert!(session.client_mut().await.is_err());}
        return;
    }
    let mut store=Backtests::new(session,namespace);
    if phase=="replay" { source_authority.withdraw(); }
    let run=store.create(&request,&context,&inputs,at(0)).await.unwrap();
    assert_eq!(run.run_id(),RUN);
    assert_eq!(run.state().as_str(),"QUEUED");assert!(!run.was_started());
    assert_eq!(run.completion_fingerprints(),None);
    let immutable_admission=run.record();
    if phase=="create" || phase=="replay" {
        let original=run.record();
        let replay=store.create(&request,&context,&inputs,at(30)).await.unwrap();
        assert_eq!(replay.record()["accepted_at"],original["accepted_at"]);
        assert_eq!(replay.record()["replayed"],true);
        let changed=CreateRequest::new(CommandId::new(COMMAND).unwrap(),"00000000-0000-4000-8000-000000000807",inputs.specification().clone()).unwrap();
        assert_eq!(store.create(&changed,&context,&inputs,at(31)).await.err(),Some("PRODUCT_COMMAND_CONFLICT"));
        return;
    }
    if phase=="scheduler-inventory" {
        drop(store);
        let client=session.client_mut().await.unwrap();
        assert_eq!(crate::persistence::backtest_run::pending_native_run_ids(client,namespace).await.unwrap(),vec![RUN.to_owned()]);
        assert_eq!(crate::persistence::backtest_run::pending_native_run_ids(client,namespace).await.unwrap(),vec![RUN.to_owned()]);
        let mut store=Backtests::new(session,namespace);
        let mut claim=store.claim(&run,WORKER,ATTEMPT1,at(1)).await.unwrap().unwrap();
        drop(store);
        assert_eq!(crate::persistence::backtest_run::pending_native_run_ids(session.client_mut().await.unwrap(),namespace).await.unwrap(),vec![RUN.to_owned()]);
        Backtests::new(session,namespace).complete(&mut claim,&completion(&run,"COMPLETED",root),at(2)).await.unwrap();
        assert!(crate::persistence::backtest_run::pending_native_run_ids(session.client_mut().await.unwrap(),namespace).await.unwrap().is_empty());
        return;
    }
    if phase=="scheduler-queued-cancel" {
        let request=CancelRequest::new(CommandId::new(CANCEL).unwrap(),RUN).unwrap();
        store.request_cancel(&request,&context,at(1)).await.unwrap();drop(store);
        assert!(crate::persistence::backtest_run::pending_native_run_ids(session.client_mut().await.unwrap(),namespace).await.unwrap().is_empty());
        assert_eq!(session.client_mut().await.unwrap().query_one("SELECT count(*) FROM backtest_run_attempt WHERE run_id=$1::text::uuid",&[&RUN]).await.unwrap().get::<_,i64>(0),0);
        assert!(!root.join("backtest/runtime").exists());return;
    }
    if phase=="queued-cancel" {
        let request=CancelRequest::new(CommandId::new(CANCEL).unwrap(),RUN).unwrap();
        let receipt=store.request_cancel(&request,&context,at(1)).await.unwrap();
        assert_eq!(receipt.outcome().kind(),OutcomeKind::BacktestRun);assert_eq!(receipt.outcome().id(),RUN);
        let status=store.observe(&run).await.unwrap();assert_eq!(status.state.as_str(),"CANCELLED");
        let replay=store.request_cancel(&request,&context,at(2)).await.unwrap();assert_eq!(replay,receipt);
        let terminal=store.load(RUN).await.unwrap();
        assert_eq!(terminal.state().as_str(),"CANCELLED");assert!(!terminal.was_started());assert_eq!(terminal.completion_fingerprints(),None);
        assert_eq!(terminal.record(),immutable_admission,"mutable read metadata is excluded from the original admission record");
        return;
    }
    if phase=="deferred-claim-guard" {
        drop(store);
        session.client_mut().await.unwrap().batch_execute("CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER INSERT ON backtest_run_attempt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION backtest_test_deferred()").await.unwrap();
        assert!(Backtests::new(session,namespace).claim(&run,WORKER,ATTEMPT1,at(1)).await.is_err(),"no token may escape the original physical guard");
        assert!(session.client_mut().await.is_err());
        return;
    }
    let mut first=store.claim(&run,WORKER,ATTEMPT1,at(1)).await.unwrap().unwrap();
    assert!(first.ownership_certain());assert_eq!(first.attempt_number(),1);assert_eq!(first.fencing_token(),1);
    assert!(store.claim(&run,WORKER,ATTEMPT2,at(2)).await.unwrap().is_none());
    if matches!(phase,"deferred-finalize-guard"|"deferred-finalize-result") {
        drop(store);
        let statement=if phase=="deferred-finalize-guard" {
            "CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER UPDATE ON backtest_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='COMPLETED' AND OLD.state IS DISTINCT FROM NEW.state) EXECUTE FUNCTION backtest_test_deferred()"
        } else {
            "CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE backtest_run SET result_fingerprint=repeat('4',64) WHERE run_id=NEW.run_id; RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER UPDATE ON backtest_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='COMPLETED' AND OLD.state IS DISTINCT FROM NEW.state) EXECUTE FUNCTION backtest_test_deferred()"
        };
        session.client_mut().await.unwrap().batch_execute(statement).await.unwrap();
        assert!(Backtests::new(session,namespace).complete(&mut first,&completion(&run,"COMPLETED",root),at(3)).await.is_err());
        assert!(!first.ownership_certain());
        if phase=="deferred-finalize-guard" {assert!(session.client_mut().await.is_err());}
        return;
    }
    if phase=="complete" {
        let proof=completion(&run,"COMPLETED",root);
        let status=store.complete(&mut first,&proof,at(3)).await.unwrap();assert_eq!(status.state.as_str(),"COMPLETED");
        // The Claim still owns its original QUEUED snapshot. State/pin read
        // metadata must never enter the immutable lineage equality or fence.
        assert_eq!(run.state().as_str(),"QUEUED");assert_eq!(run.completion_fingerprints(),None);
        let terminal=store.load(RUN).await.unwrap();let (e,r,d)=("1".repeat(64),"2".repeat(64),"3".repeat(64));
        assert_eq!(terminal.state().as_str(),"COMPLETED");assert!(terminal.was_started());
        assert_eq!(terminal.completion_fingerprints(),Some((e.as_str(),r.as_str(),d.as_str())));
        assert_eq!(terminal.record(),immutable_admission,"new readonly metadata cannot change Spec3, Resolution2 or original Run identity bytes");
        assert!(store.claim(&run,WORKER,ATTEMPT2,at(4)).await.unwrap().is_none());
        return;
    }
    if phase=="trigger" {
        drop(store);
        let client=session.client_mut().await.unwrap();
        let pid:i32=client.query_one("SELECT pg_backend_pid()",&[]).await.unwrap().get(0);
        client.batch_execute(&format!("CREATE FUNCTION backtest_test_terminate_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_terminate_backend({pid}); RETURN NEW; END $$; CREATE TRIGGER backtest_test_finalization_guard BEFORE UPDATE ON backtest_run FOR EACH ROW WHEN (NEW.state='COMPLETED') EXECUTE FUNCTION backtest_test_terminate_guard()" )).await.unwrap();
        let proof=completion(&run,"COMPLETED",root);
        let result=Backtests::new(session,namespace).complete(&mut first,&proof,at(3)).await;
        assert!(result.is_err());assert!(!first.ownership_certain());assert!(session.client_mut().await.is_err());
        return;
    }
    drop(store);
    if phase=="scheduler-expiry" {
        // Model actual Host shutdown: the Attempt remains ACTIVE; no failure,
        // cancellation, fictitious completion or early expiry is written.
        let row=session.client_mut().await.unwrap().query_one("SELECT state,failure_code,finished_at FROM backtest_run_attempt WHERE attempt_id=$1::text::uuid",&[&ATTEMPT1]).await.unwrap();
        assert_eq!(row.get::<_,&str>(0),"ACTIVE");assert!(row.get::<_,Option<String>>(1).is_none());assert!(row.get::<_,Option<std::time::SystemTime>>(2).is_none());
        assert!(Backtests::new(session,namespace).expire(&run,at(3)).await.unwrap().is_none());
        session.client_mut().await.unwrap().execute("UPDATE backtest_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds',lease_expires_at=clock_timestamp()-interval '1 second' WHERE attempt_id=$1::text::uuid",&[&ATTEMPT1]).await.unwrap();
        let mut store=Backtests::new(session,namespace);store.expire(&run,at(3)).await.unwrap().unwrap();
        let mut second=store.claim(&run,WORKER,ATTEMPT2,at(4)).await.unwrap().unwrap();
        assert_eq!(second.attempt_number(),2);assert_eq!(second.fencing_token(),2);
        assert!(store.heartbeat(&mut first).await.is_err());assert!(!first.ownership_certain());
        store.complete(&mut second,&completion(&run,"COMPLETED",root),at(5)).await.unwrap();
        assert_eq!(store.load(RUN).await.unwrap().record(),immutable_admission);
        return;
    }
    assert_eq!(phase,"fence-cancel");
    // Explicit deterministic expiration in the guarded disposable DB, no sleep.
    session.client_mut().await.unwrap().execute("UPDATE backtest_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds',lease_expires_at=clock_timestamp()-interval '1 second' WHERE attempt_id=$1::text::uuid",&[&ATTEMPT1]).await.unwrap();
    let mut store=Backtests::new(session,namespace);
    store.expire(&run,at(3)).await.unwrap();
    let mut second=store.claim(&run,WORKER,ATTEMPT2,at(4)).await.unwrap().unwrap();
    assert_eq!(second.attempt_number(),2);assert_eq!(second.fencing_token(),2);
    assert!(store.heartbeat(&mut first).await.is_err());assert!(!first.ownership_certain());
    let request=CancelRequest::new(CommandId::new(CANCEL).unwrap(),RUN).unwrap();
    store.request_cancel(&request,&context,at(5)).await.unwrap();
    assert_eq!(store.observe(&run).await.unwrap().state.as_str(),"CANCEL_REQUESTED");
    assert!(store.complete(&mut first,&completion(&run,"COMPLETED",root),at(6)).await.is_err());
    let status=store.cancel(&mut second,&completion(&run,"CANCELLED",root),at(7)).await.unwrap();
    assert_eq!(status.state.as_str(),"CANCELLED");
    let terminal=store.load(RUN).await.unwrap();let (e,r,d)=("1".repeat(64),"2".repeat(64),"3".repeat(64));
    assert_eq!(terminal.state().as_str(),"CANCELLED");assert!(terminal.was_started());
    assert_eq!(terminal.completion_fingerprints(),Some((e.as_str(),r.as_str(),d.as_str())),"the explicit sealed CANCELLED proof must retain its exact three published references");
    assert_eq!(terminal.record(),immutable_admission);
    assert!(store.heartbeat(&mut second).await.is_err());
}
