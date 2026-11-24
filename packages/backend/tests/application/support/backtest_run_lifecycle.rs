//! Existing-table operational proof with explicit cfg(test) semantic preconditions.
//! No claim of actual Freeze/Qualification/Runtime admission or Shipping acceptance.
use crate::{
    application::{
        backtest_run::{CancelRequest, Context, CreateRequest, Inputs, Specification, VerifiedRun},
        command::{CommandId, OutcomeKind},
        job_contract::JobKind,
        source_access::{Authority, Grant, Permission, Reference, Selection},
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession,
        backtest_run::{Backtests, RunState, pending_native_run_ids},
        job_publication::{JobRole, PublicationObservation, PublicationRepository, RunLocator, with_job_role},
    },
    security::{
        human_access::{Access, Session},
        immutable_json::SourceLock,
    },
};
use serde_json::json;
use std::{path::Path, sync::Arc};
const COMMAND: &str = "00000000-0000-4000-8000-000000000801";
const RUN: &str = "00000000-0000-4000-8000-000000000802";
const CANCEL: &str = "00000000-0000-4000-8000-000000000803";
const WORKER: &str = "00000000-0000-4000-8000-000000000804";
const ATTEMPT1: &str = "00000000-0000-4000-8000-000000000805";
fn at(second: u32) -> onlyalpha_domain::time::OnlyUtcDateTime {
    format!("2026-11-01T00:01:{second:02}Z").parse().unwrap()
}
fn value_inputs(namespace: &SemanticStoreId, root: &Path) -> Inputs<'static> {
    value_inputs_bound(namespace, root, RUN, COMMAND)
}
fn value_inputs_bound(namespace: &SemanticStoreId, root: &Path, run: &str, command: &str) -> Inputs<'static> {
    let prepared = crate::workers::backtest::tests::prepared();
    let preparation = prepared.record();
    let preparation_fp = crate::application::factor_content::hash(&preparation).unwrap();
    let strategy = preparation["strategy_fingerprint"].clone();
    let generation = preparation["settings"]["execution"]["generation"].clone();
    let source = prepared.inputs().record()["sources"][0].clone();
    let specification=Specification::from_record(&json!({"schema_version":3,"kind":"BTC_SPOT_NEXT_OPEN","strategy_fingerprint":strategy,"dataset_snapshot_fingerprint":source["snapshot"],"runtime_generation_fingerprint":generation,"preparation_fingerprint":preparation_fp})).unwrap();
    // These full controlled records are operational test preconditions. The
    // production Inputs constructor must instead hold all actual owning readers.
    let resolution = json!({"schema_version":2,"kind":"BTC_SPOT_NEXT_OPEN_ADMISSION","owner":"local-developer","semantic_store_id":namespace.value(),"strategy_fingerprint":strategy,"freeze_relation_fingerprint":"f".repeat(64),"qualification_decision_fingerprint":"8".repeat(64),"promotion_fingerprint":"9".repeat(64),"dataset_snapshot_fingerprint":source["snapshot"],"dataset_binding_fingerprint":source["dataset_binding"],"runtime_generation_fingerprint":generation,"preparation_fingerprint":preparation_fp,"preparation":preparation,
        "dataset_materialization":{"schema_version":1,"materialization_id":"controlled-existing-materialization","dataset_snapshot_fingerprint":source["snapshot"]},
        "runtime_work_binding":{"schema_version":1,"kind":"RuntimeWorkBound","work_id":run,"generation_fingerprint":generation,"reason":command},
        "backtest_binding":{"executor_manifest_fingerprint":"5".repeat(64),"executor_artifact_sha256":"6".repeat(64),"executor_version":env!("CARGO_PKG_VERSION"),"core_execution_fingerprint":"7".repeat(64),"protocol":"onlyalpha.backtest.executor/1"},
        "source_selection":{"integration_id":"controlled-market","revision_fingerprint":"a".repeat(64),"expected_type_id":"controlled.spot","source_id":"BINANCE_SPOT","environment":"LIVE"}});
    Inputs::for_value_test(
        specification,
        resolution,
        namespace.clone(),
        Arc::new(SourceLock::publication(root).unwrap()),
    )
    .unwrap()
}
async fn register_control_fixture(session: &mut AuthoritySession, run: &VerifiedRun, attempt: &str) {
    let mut fixture = crate::persistence::job_publication::fixture::fixture(
        JobKind::Backtest, (run.namespace().value(), run.owner()), run.run_id(), attempt, WORKER, 1, 32,
    );
    fixture.bind_original_run(run.specification_fingerprint(), run.admission_resolution_fingerprint());
    with_job_role(session, JobRole::Publisher, async |client| {
        PublicationRepository::new(client, run.namespace(), run.owner()).await?
            .register(&fixture.registration).await
    }).await.unwrap();
}

/// Original operational Run/Attempt CAS only; synthetic frozen input metadata
/// is a storage-test precondition, never actual factor/market certification.
pub async fn finite_recovery(
    session: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    human_authority: &Access,
    human: &Session,
    root: &Path,
) {
    use crate::application::job_recovery::{JobRecovery, RecoveryDecision, RecoveryRefusal, RetryBudget};
    let run_id = "00000000-0000-4000-8000-000000000851";
    let command = "00000000-0000-4000-8000-000000000852";
    let selection = Selection::new(Reference::new("controlled-market",&"a".repeat(64),Some("controlled.spot")).unwrap(),"BINANCE_SPOT","LIVE").unwrap();
    let source_authority = Authority::new("local-developer","add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",vec![Grant::new(selection.clone(),vec![Permission::ClosedHistory]).unwrap()]).unwrap();
    let source = source_authority.authenticate(&format!("Bearer {}","e".repeat(64))).unwrap();
    let context = Context { human_authority, human, source_authority:&source_authority, source:&source, selection:&selection };
    let inputs = value_inputs_bound(namespace,root,run_id,command);
    let request = CreateRequest::new(CommandId::new(command).unwrap(),run_id,inputs.specification().clone()).unwrap();
    {
        let roles=session.control_roles().unwrap();
        let tx = session.client_mut().await.unwrap().transaction().await.unwrap();
        assert!(crate::persistence::job_publication::FrozenBindingRegistration::from_backtest(
            &crate::persistence::build_fact_read::BuildFactRead::control(&tx,&roles),&inputs,&request,&context,
        ).await.is_err(),"value-only control fixtures cannot authenticate frozen inputs");
        tx.rollback().await.unwrap();
    }
    let run = Backtests::new(session,namespace).create(&request,&context,&inputs,at(0)).await.unwrap();
    register_control_fixture(session, &run, ATTEMPT1).await;
    let key = RunLocator::new(JobKind::Backtest,run_id).unwrap();
    let mut previous_execution = None;
    for number in 1..=3 {
        let decision = with_job_role(session,JobRole::Publisher,async |client| {
            JobRecovery::resolve(&mut PublicationRepository::new(client,namespace,"local-developer").await?,&key,RetryBudget::finite_job()).await
        }).await.unwrap();
        let RecoveryDecision::RecomputeWithNewClaim(proof) = decision else { panic!("expected bounded recompute") };
        let attempt = format!("00000000-0000-4000-8000-{:012}",852+number);
        if number == 2 {
            let (admin, driver) = tokio_postgres::connect(&std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap(), tokio_postgres::NoTls).await.unwrap();
            let driver = tokio::spawn(driver);
            admin.batch_execute("CREATE FUNCTION public.test_remove_previous_attempt() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN DELETE FROM public.backtest_run_attempt WHERE run_id=NEW.run_id AND attempt_number=1; RETURN NEW; END $$; \
                CREATE CONSTRAINT TRIGGER test_remove_previous_attempt AFTER INSERT ON public.backtest_run_attempt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.attempt_number=2) EXECUTE FUNCTION public.test_remove_previous_attempt()").await.unwrap();
            let rejected = Backtests::new(session, namespace).claim_recompute(&run, &proof, WORKER, &attempt, at(4)).await;
            admin.batch_execute("DROP TRIGGER test_remove_previous_attempt ON public.backtest_run_attempt; DROP FUNCTION public.test_remove_previous_attempt()").await.unwrap();
            assert!(rejected.is_err(), "missing predecessor must roll back both the new claim and its cursor");
            let stored = admin.query_one("SELECT state, last_attempt_number, ARRAY(SELECT attempt_number FROM public.backtest_run_attempt WHERE run_id=r.run_id ORDER BY attempt_number) FROM public.backtest_run r WHERE run_id=$1::text::uuid", &[&run_id]).await.unwrap();
            assert_eq!((stored.get::<_, &str>(0), stored.get::<_, i32>(1), stored.get::<_, Vec<i32>>(2)), ("RUNNING", 1, vec![1]));
            drop(admin);
            driver.await.unwrap().unwrap();
        }
        let mut claim = Backtests::new(session,namespace).claim_recompute(&run,&proof,WORKER,&attempt,at(number as u32 * 2)).await.unwrap().unwrap();
        assert_eq!(claim.attempt_number(),number);
        assert_eq!(claim.fencing_token(),i64::from(number));
        assert_eq!(claim.run_id(),run_id);
        let publication_claim = crate::persistence::job_publication::AttemptClaim::from_backtest(&claim);
        let execution = crate::persistence::job_publication::AttemptExecutionBinding::capture(&publication_claim).unwrap();
        assert!(execution.matches(&publication_claim));
        crate::persistence::job_publication::fixture::assert_execution_association(&publication_claim);
        if let Some(previous) = previous_execution {
            let previous: crate::persistence::job_publication::AttemptExecutionBinding = previous;
            assert!(!previous.matches(&publication_claim), "old execution cannot publish under a new Attempt");
        }
        previous_execution = Some(execution);
        assert!(Backtests::new(session,namespace).claim_recompute(&run,&proof,WORKER,"00000000-0000-4000-8000-000000000859",at(number as u32 * 2)).await.unwrap().is_none(),"stale observation must not create a second owner");
        assert!(Backtests::new(session, namespace).heartbeat(&mut claim).await.unwrap().is_some());
        assert!(claim.ownership_certain());
        // Existing deterministic clock fault, on an explicit test admin socket;
        // ordinary Node receives no permission to rewrite claimed_at.
        let (admin,driver) = tokio_postgres::connect(&std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap(),tokio_postgres::NoTls).await.unwrap();
        let driver = tokio::spawn(driver);
        let expired = admin.execute("UPDATE backtest_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds',lease_expires_at=clock_timestamp()-interval '1 second' WHERE attempt_id=$1::text::uuid",&[&attempt]).await;
        driver.abort();
        assert_eq!(expired.unwrap(),1);
        Backtests::new(session,namespace).expire(&run,at(number as u32 * 2+1)).await.unwrap().unwrap();
        assert!(Backtests::new(session, namespace).heartbeat(&mut claim).await.unwrap().is_none());
        assert!(!claim.ownership_certain());
    }
    let decision = with_job_role(session,JobRole::Publisher,async |client| {
        JobRecovery::resolve(&mut PublicationRepository::new(client,namespace,"local-developer").await?,&key,RetryBudget::finite_job()).await
    }).await.unwrap();
    let RecoveryDecision::Refused(RecoveryRefusal::RetryExhausted, proof) = decision else { panic!("expected original exhausted unpublished Run") };
    assert_eq!(proof.binding().run_id(), run.run_id());
    assert_eq!(proof.attempts(),3);
    assert_eq!(proof.active_attempts(),0);
    assert!(Backtests::new(session,namespace).claim_recompute(&run,&proof,WORKER,"00000000-0000-4000-8000-000000000859",at(9)).await.unwrap().is_none(),"claim CAS must independently enforce the limit");
    // A different original Run is cancelled after its only Attempt has ceased.
    // No Source grant is required to settle this absence proof.
    let cancelled_run = "00000000-0000-4000-8000-000000000861";
    let cancelled_command = "00000000-0000-4000-8000-000000000862";
    let cancelled_attempt = "00000000-0000-4000-8000-000000000863";
    let cancelled_inputs = value_inputs_bound(namespace,root,cancelled_run,cancelled_command);
    let cancelled_request = CreateRequest::new(CommandId::new(cancelled_command).unwrap(),cancelled_run,cancelled_inputs.specification().clone()).unwrap();
    let cancellation = Backtests::new(session,namespace).create(&cancelled_request,&context,&cancelled_inputs,at(0)).await.unwrap();
    register_control_fixture(session, &cancellation, cancelled_attempt).await;
    let cancelled_key = RunLocator::new(JobKind::Backtest,cancelled_run).unwrap();
    let observed = with_job_role(session,JobRole::Publisher,async |client| { PublicationRepository::new(client,namespace,"local-developer").await?.observe(&cancelled_key).await }).await.unwrap();
    let PublicationObservation::ConfirmedUnpublished(initial) = observed else { panic!("unpublished cancellation fixture") };
    let _claim = Backtests::new(session,namespace).claim_recompute(&cancellation,&initial,WORKER,cancelled_attempt,at(1)).await.unwrap().unwrap();
    source_authority.withdraw();
    Backtests::new(session,namespace).request_cancel(&CancelRequest::new(CommandId::new("00000000-0000-4000-8000-000000000864").unwrap(),cancelled_run).unwrap(),&context,at(2)).await.unwrap();
    let observed = with_job_role(session,JobRole::Publisher,async |client| { PublicationRepository::new(client,namespace,"local-developer").await?.observe(&cancelled_key).await }).await.unwrap();
    let PublicationObservation::ConfirmedUnpublished(active) = observed else { panic!("unpublished active cancellation") };
    assert!(Backtests::new(session,namespace).finish_cancelled_unpublished(&cancellation,&active,at(3)).await.unwrap().is_none(), "an active owner must drain before cancellation");
    let (admin,driver) = tokio_postgres::connect(&std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap(),tokio_postgres::NoTls).await.unwrap();
    let driver = tokio::spawn(driver);
    assert_eq!(admin.execute("UPDATE backtest_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds',lease_expires_at=clock_timestamp()-interval '1 second' WHERE attempt_id=$1::text::uuid",&[&cancelled_attempt]).await.unwrap(),1);
    drop(admin); driver.await.unwrap().unwrap();
    Backtests::new(session,namespace).expire(&cancellation,at(4)).await.unwrap().unwrap();
    let observed = with_job_role(session,JobRole::Publisher,async |client| { PublicationRepository::new(client,namespace,"local-developer").await?.observe(&cancelled_key).await }).await.unwrap();
    let PublicationObservation::ConfirmedUnpublished(inactive) = observed else { panic!("unpublished inactive cancellation") };
    assert!(Backtests::new(session,namespace).finish_cancelled_unpublished(&cancellation,&proof,at(5)).await.unwrap().is_none(), "another Run absence proof cannot finalize cancellation");
    let cancelled = Backtests::new(session,namespace).finish_cancelled_unpublished(&cancellation,&inactive,at(5)).await.unwrap().unwrap();
    assert_eq!(cancelled.state,RunState::Cancelled);
    assert!(Backtests::new(session,namespace).finish_cancelled_unpublished(&cancellation,&inactive,at(6)).await.unwrap().is_none());
    let row=with_job_role(session,JobRole::Reader,async |client| { client.query_one("SELECT (SELECT count(*) FROM backtest_run_attempt WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_publication WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_result_member WHERE run_id=$1::text::uuid)",&[&cancelled_run]).await.map_err(|_|crate::persistence::job_publication::PublicationError::Unavailable) }).await.unwrap();
    assert_eq!((row.get::<_,i64>(0),row.get::<_,i64>(1),row.get::<_,i64>(2)),(1,0,0));
    source_authority.withdraw();
    assert!(Backtests::new(session,namespace).finish_exhausted(&run,&inactive,at(10)).await.unwrap().is_none(), "another Run absence proof cannot finalize exhaustion");
    let (admin,driver) = tokio_postgres::connect(&std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap(),tokio_postgres::NoTls).await.unwrap();
    let driver = tokio::spawn(driver);
    admin.batch_execute("CREATE FUNCTION use_test_terminal_attempt() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$ BEGIN INSERT INTO public.backtest_run_attempt(attempt_id,run_id,attempt_number,state,worker_instance_id,fencing_token,claimed_at,last_heartbeat_at,lease_expires_at) VALUES('00000000-0000-4000-8000-000000000865',NEW.run_id,4,'ACTIVE','00000000-0000-4000-8000-000000000804',4,clock_timestamp(),clock_timestamp(),clock_timestamp()+interval '120 seconds'); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_terminal_attempt AFTER UPDATE ON public.backtest_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='FAILED' AND OLD.state IS DISTINCT FROM NEW.state) EXECUTE FUNCTION use_test_terminal_attempt()").await.unwrap();
    let polluted = Backtests::new(session,namespace).finish_exhausted(&run,&proof,at(10)).await;
    admin.batch_execute("DROP TRIGGER use_test_terminal_attempt ON public.backtest_run; DROP FUNCTION use_test_terminal_attempt()").await.unwrap();
    let row = admin.query_one("SELECT r.state,(SELECT max(attempt_number) FROM public.backtest_run_attempt a WHERE a.run_id=r.run_id),(SELECT count(*) FROM public.backtest_run_attempt a WHERE a.run_id=r.run_id AND a.state='ACTIVE') FROM public.backtest_run r WHERE r.run_id=$1::text::uuid",&[&run_id]).await.unwrap();
    drop(admin); driver.await.unwrap().unwrap();
    assert!(polluted.is_err(), "deferred creation of a fourth active owner must roll back the terminal mutation");
    assert_eq!((row.get::<_,String>(0),row.get::<_,i32>(1),row.get::<_,i64>(2)),("RUNNING".into(),3,0));
    let failed = Backtests::new(session,namespace).finish_exhausted(&run,&proof,at(10)).await.unwrap().unwrap();
    assert_eq!(failed.state, RunState::Failed);
    assert!(Backtests::new(session,namespace).finish_exhausted(&run,&proof,at(11)).await.unwrap().is_none(), "stale absence observation cannot change a terminal Run");
    let finished = Backtests::new(session,namespace).load(run_id).await.unwrap();
    assert_eq!(finished.run_id(),run_id);
    assert_eq!(finished.completion_fingerprints(),None);
    let row=with_job_role(session,JobRole::Reader,async |client| { client.query_one("SELECT (SELECT count(*) FROM backtest_run_attempt WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_publication WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_result_member WHERE run_id=$1::text::uuid)",&[&run_id]).await.map_err(|_|crate::persistence::job_publication::PublicationError::Unavailable) }).await.unwrap();
    assert_eq!((row.get::<_,i64>(0),row.get::<_,i64>(1),row.get::<_,i64>(2)),(3,0,0));

}
pub async fn run_phase(
    session: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    human_authority: &Access,
    human: &Session,
    root: &Path,
    phase: &str,
) {
    let selection = Selection::new(
        Reference::new(
            "controlled-market",
            &"a".repeat(64),
            Some("controlled.spot"),
        )
        .unwrap(),
        "BINANCE_SPOT",
        "LIVE",
    )
    .unwrap();
    let source_authority = Authority::new(
        "local-developer",
        "add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",
        vec![Grant::new(selection.clone(), vec![Permission::ClosedHistory]).unwrap()],
    )
    .unwrap();
    let source = source_authority
        .authenticate(&format!("Bearer {}", "e".repeat(64)))
        .unwrap();
    let context = Context {
        human_authority,
        human,
        source_authority: &source_authority,
        source: &source,
        selection: &selection,
    };
    let inputs = value_inputs(namespace, root);
    let request = CreateRequest::new(
        CommandId::new(COMMAND).unwrap(),
        RUN,
        inputs.specification().clone(),
    )
    .unwrap();
    if matches!(phase, "deferred-create-guard" | "deferred-create-receipt") {
        let statement = if phase == "deferred-create-guard" {
            "CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER INSERT ON backtest_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION backtest_test_deferred()"
        } else {
            "CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE product_command_receipt SET outcome_id='00000000-0000-4000-8000-000000000807' WHERE command_id=NEW.command_id; RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER INSERT ON product_command_receipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.command_kind='CREATE_BACKTEST_RUN') EXECUTE FUNCTION backtest_test_deferred()"
        };
        session
            .client_mut()
            .await
            .unwrap()
            .batch_execute(statement)
            .await
            .unwrap();
        assert!(
            Backtests::new(session, namespace)
                .create(&request, &context, &inputs, at(0))
                .await
                .is_err()
        );
        if phase == "deferred-create-guard" {
            assert!(session.client_mut().await.is_err());
        }
        return;
    }
    let mut store = Backtests::new(session, namespace);
    if phase == "replay" {
        source_authority.withdraw();
    }
    let run = store
        .create(&request, &context, &inputs, at(0))
        .await
        .unwrap();
    assert_eq!(run.run_id(), RUN);
    assert_eq!(run.state().as_str(), "QUEUED");
    assert!(!run.was_started());
    assert_eq!(run.completion_fingerprints(), None);
    let immutable_admission = run.record();
    if phase == "create" || phase == "replay" {
        let original = run.record();
        let replay = store
            .create(&request, &context, &inputs, at(30))
            .await
            .unwrap();
        assert_eq!(replay.record()["accepted_at"], original["accepted_at"]);
        assert_eq!(replay.record()["replayed"], true);
        let changed = CreateRequest::new(
            CommandId::new(COMMAND).unwrap(),
            "00000000-0000-4000-8000-000000000807",
            inputs.specification().clone(),
        )
        .unwrap();
        assert_eq!(
            store
                .create(&changed, &context, &inputs, at(31))
                .await
                .err(),
            Some("PRODUCT_COMMAND_CONFLICT")
        );
        return;
    }
    if phase == "queued-cancel" {
        let pending = pending_native_run_ids(session.client_mut().await.unwrap(), namespace).await.unwrap();
        assert!(pending.iter().any(|id| id == RUN));
        let mut store = Backtests::new(session, namespace);
        let request = CancelRequest::new(CommandId::new(CANCEL).unwrap(), RUN).unwrap();
        let receipt = store
            .request_cancel(&request, &context, at(1))
            .await
            .unwrap();
        assert_eq!(receipt.outcome().kind(), OutcomeKind::BacktestRun);
        assert_eq!(receipt.outcome().id(), RUN);
        let status = store.observe(&run).await.unwrap();
        assert_eq!(status.state.as_str(), "CANCELLED");
        let replay = store
            .request_cancel(&request, &context, at(2))
            .await
            .unwrap();
        assert_eq!(replay, receipt);
        let terminal = store.load(RUN).await.unwrap();
        assert_eq!(terminal.state().as_str(), "CANCELLED");
        assert!(!terminal.was_started());
        assert_eq!(terminal.completion_fingerprints(), None);
        assert_eq!(
            terminal.record(),
            immutable_admission,
            "mutable read metadata is excluded from the original admission record"
        );
        let pending = pending_native_run_ids(session.client_mut().await.unwrap(), namespace).await.unwrap();
        assert!(!pending.iter().any(|id| id == RUN));
        return;
    }
    if phase == "deferred-claim-guard" {
        register_control_fixture(session, &run, ATTEMPT1).await;
        let observed = Backtests::new(session, namespace).observe_publication(&run).await.unwrap();
        let PublicationObservation::ConfirmedUnpublished(proof) = observed else {
            panic!("queued Run must be unpublished: {observed:?}");
        };
        session.client_mut().await.unwrap().batch_execute("CREATE FUNCTION backtest_test_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER backtest_test_deferred_guard AFTER INSERT ON backtest_run_attempt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION backtest_test_deferred()").await.unwrap();
        assert!(
            Backtests::new(session, namespace)
                .claim_recompute(&run, &proof, WORKER, ATTEMPT1, at(1))
                .await
                .is_err(),
            "no token may escape the original physical guard"
        );
        assert!(session.client_mut().await.is_err());
        return;
    }
    panic!("unknown Backtest lifecycle phase {phase}");
}
