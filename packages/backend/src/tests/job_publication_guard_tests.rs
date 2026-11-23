//! Real same-socket role scopes; storage vectors do not prove engine completion.
use super::*;
use crate::persistence::{
    authority_session::AuthoritySession,
    job_publication::{JobRole, with_job_role},
};

async fn publication_losing_original_guard_rolls_back(publishing: bool) {
    let admin = database().await;
    assert!(prepare_node_login().status.success());
    let (kind, run_table, attempt_table) = if publishing {
        (JobKind::Research, "research_run", "research_run_attempt")
    } else {
        (JobKind::Backtest, "backtest_run", "backtest_run_attempt")
    };
    let f = seed(&admin.client, kind, 1, 32).await;
    let run = f.candidate.binding().run_id().to_owned();
    let mut config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
    config.user("onlyalpha_node_test");
    let (client, driver) = config.connect(NoTls).await.unwrap();
    let mut guard = AuthoritySession::acquire(client,tokio::spawn(driver)).await.unwrap();
    if publishing {
        with_job_role(&mut guard,JobRole::Publisher,async |client| {
            PublicationRepository::new(client,&SemanticStoreId::new(NS).unwrap(),OWNER).await?.register(&f.registration).await
        }).await.unwrap();
    }
    let table = if publishing { "job_publication" } else { "job_frozen_binding" };
    admin.client.batch_execute(&format!("CREATE FUNCTION public.publication_test_release_guard() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$ BEGIN PERFORM pg_catalog.pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER publication_test_release_guard AFTER INSERT ON public.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.publication_test_release_guard()")).await.unwrap();
    let result = with_job_role(&mut guard,JobRole::Publisher,async |client| {
        let mut repository = PublicationRepository::new(client,&SemanticStoreId::new(NS).unwrap(),OWNER).await?;
        let mutation = if publishing {
            repository.publish(&f.claim, &f.candidate).await.map(|_| ())
        } else {
            repository.register(&f.registration).await
        };
        assert_eq!(mutation, Err(PublicationError::OwnershipLost));
        mutation
    }).await;
    let row = admin.client.query_one(&format!("SELECT (SELECT count(*) FROM job_frozen_binding WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_result_member WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_publication WHERE run_id=$1::text::uuid),(SELECT state FROM {run_table} WHERE run_id=$1::text::uuid),(SELECT state FROM {attempt_table} WHERE run_id=$1::text::uuid)"),&[&run]).await.unwrap();
    admin.client.batch_execute(&format!("DROP TRIGGER publication_test_release_guard ON public.{table}; DROP FUNCTION public.publication_test_release_guard()")).await.unwrap();
    assert!(result.is_err());
    assert!(guard.client_mut().await.is_err(),"lost original guard must not be reusable");
    assert_eq!(row.get::<_,i64>(0),i64::from(publishing),"unacknowledged binding must roll back");
    assert_eq!(row.get::<_,i64>(1),0,"no result member may survive guard loss");
    assert_eq!(row.get::<_,i64>(2),0,"no publication may survive guard loss");
    assert_eq!(row.get::<_,String>(3),"RUNNING");
    assert_eq!(row.get::<_,String>(4),"ACTIVE");
}

#[tokio::test]
async fn frozen_registration_rolls_back_when_deferred_work_releases_the_original_guard() {
    publication_losing_original_guard_rolls_back(false).await;
}
#[tokio::test]
async fn complete_publication_rolls_back_when_deferred_work_releases_the_original_guard() {
    publication_losing_original_guard_rolls_back(true).await;
}

async fn registration_in_control_transaction(commit: bool) {
    let admin = database().await;
    assert!(prepare_node_login().status.success());
    let n = SEQUENCE.fetch_add(1,Ordering::Relaxed);
    let run = format!("{n:08x}-4444-4444-8444-444444444444");
    let f = fixture(JobKind::Backtest,(NS,OWNER),&run,"00000000-0000-4000-8000-000000000901","00000000-0000-4000-8000-000000000902",1,32);
    let mut config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
    config.user("onlyalpha_node_test");
    let (client,driver) = config.connect(NoTls).await.unwrap();
    let guard = AuthoritySession::acquire(client,tokio::spawn(driver)).await.unwrap();
    let mut owned = guard;
    let roles=owned.control_roles().unwrap();
    let tx = owned.client_mut().await.unwrap().transaction().await.unwrap();
    tx.execute("INSERT INTO backtest_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_schema_version,admission_resolution_fingerprint,admission_resolution_payload,queued_at) VALUES($1::text::uuid,0,'QUEUED',1,$2,'{}',1,$3,'{}','2020-01-01')",&[&run,&f.specification(),&f.admission()]).await.unwrap();
    let rejected: Result<Result<(),&'static str>,PublicationError> =
        crate::persistence::job_publication::read_control_facts(&tx,&roles,|reader| async move {
            let selected:String=reader.query_one("SELECT current_user::text",&[]).await.map_err(|_|"read_failed")?.get(0);
            assert_eq!(selected,"onlyalpha_job_reader");
            let _:i64=reader.query_one("SELECT count(*) FROM calculation_build_proof",&[]).await.map_err(|_|"read_failed")?.get(0);
            Err("known_missing_input")
        }).await;
    assert_eq!(rejected.unwrap(),Err("known_missing_input"));
    let key = crate::persistence::job_publication::RunLocator::new(JobKind::Backtest,&run).unwrap();
    let missing = crate::persistence::job_publication::verify_registered_control_transaction(
        &tx,&roles,&SemanticStoreId::new(NS).unwrap(),OWNER,&key,&f.specification(),&f.admission(),
    ).await;
    assert!(matches!(missing,Err(PublicationError::MissingEvidence)),"replay cannot repair missing original input binding");
    crate::persistence::job_publication::register_control_transaction(&tx,&roles,&SemanticStoreId::new(NS).unwrap(),OWNER,&f.registration).await.unwrap();
    crate::persistence::job_publication::verify_registered_control_transaction(
        &tx,&roles,&SemanticStoreId::new(NS).unwrap(),OWNER,&key,&f.specification(),&f.admission(),
    ).await.unwrap();
    assert!(matches!(crate::persistence::job_publication::verify_registered_control_transaction(
        &tx,&roles,&SemanticStoreId::new(NS).unwrap(),OWNER,&key,&"f".repeat(64),&f.admission(),
    ).await,Err(PublicationError::Mismatch)));
    let restored = tx.query_one("SELECT current_user=session_user,has_table_privilege(current_user,'public.job_frozen_binding','INSERT')",&[]).await.unwrap();
    assert!(restored.get::<_,bool>(0));
    assert!(!restored.get::<_,bool>(1));
    if commit {
        AuthoritySession::verify_transaction(&tx).await.unwrap();
        tx.commit().await.unwrap();
    } else { tx.rollback().await.unwrap(); }
    owned.close().await.unwrap();
    let rows = admin.client.query_one("SELECT (SELECT count(*) FROM backtest_run WHERE run_id=$1::text::uuid),(SELECT count(*) FROM job_frozen_binding WHERE run_id=$1::text::uuid)",&[&run]).await.unwrap();
    assert_eq!(rows.get::<_,i64>(0),i64::from(commit));
    assert_eq!(rows.get::<_,i64>(1),i64::from(commit));
}

#[tokio::test]
async fn admitted_binding_rolls_back_with_the_original_control_transaction() {
    registration_in_control_transaction(false).await;
}
#[tokio::test]
async fn admitted_binding_commits_with_the_original_control_transaction() {
    registration_in_control_transaction(true).await;
}

async fn authority(runtime: bool) -> AuthoritySession {
    let mut config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
    assert_eq!(config.get_dbname(), Some("onlyalpha_dev_validation_test"));
    if runtime { config.user(TEST_LOGIN); }
    let (client, connection) = config.connect(NoTls).await.unwrap();
    AuthoritySession::acquire(client, tokio::spawn(connection)).await.unwrap()
}

async fn await_original_guard_release(observer: &mut Connection) {
    let tx = observer.client.transaction().await.unwrap();
    crate::persistence::postgres::bounds(&tx).await.unwrap();
    // Wait on the actual original lock, not an arbitrary delay or a new Node.
    tx.query_one("SELECT pg_catalog.pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    tx.rollback().await.unwrap();
}

#[tokio::test]
async fn publication_role_uses_and_restores_the_original_guard_socket() {
    let _database = database().await;
    let mut guard = authority(true).await;
    let before: i32 = guard.client_mut().await.unwrap().query_one("SELECT pg_backend_pid()", &[]).await.unwrap().get(0);
    let observed = with_job_role(&mut guard, JobRole::Publisher, async |client| {
        let row = client.query_one("SELECT pg_backend_pid(),current_user::text,session_user::text", &[]).await.map_err(crate::persistence::job_publication::db)?;
        Ok((row.get::<_,i32>(0),row.get::<_,String>(1),row.get::<_,String>(2)))
    }).await.unwrap();
    assert_eq!(observed, (before,"onlyalpha_job_publisher".into(),TEST_LOGIN.into()));
    let row = guard.client_mut().await.unwrap().query_one("SELECT pg_backend_pid(),current_user=session_user", &[]).await.unwrap();
    assert_eq!(row.get::<_,i32>(0), before);
    assert!(row.get::<_,bool>(1));
    guard.close().await.unwrap();
}

#[tokio::test]
async fn known_operation_failure_restores_role_without_granting_control_permissions() {
    let _database = database().await;
    let mut guard = authority(true).await;
    let result: Result<(),PublicationError> = with_job_role(&mut guard, JobRole::Publisher, async |client| {
        let error = client.execute("INSERT INTO public.backtest_run_attempt DEFAULT VALUES", &[]).await.unwrap_err();
        assert_eq!(error.code(),Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE));
        Err(PublicationError::Mismatch)
    }).await;
    assert_eq!(result.unwrap_err(),PublicationError::Mismatch);
    assert!(guard.client_mut().await.unwrap().query_one("SELECT current_user=session_user",&[]).await.unwrap().get::<_,bool>(0));
    guard.close().await.unwrap();
}

#[tokio::test]
async fn dropping_pending_role_scope_revokes_the_original_socket() {
    let mut observer = database().await;
    let mut guard = authority(true).await;
    let (entered, ready) = tokio::sync::oneshot::channel::<()>();
    let mut operation = Box::pin(with_job_role(&mut guard, JobRole::Publisher, async move |_client| {
        entered.send(()).unwrap();
        std::future::pending::<Result<(),PublicationError>>().await
    }));
    tokio::select! {
        value=ready=>value.unwrap(),
        result=&mut operation=>panic!("operation ended before cancellation: {result:?}"),
    }
    drop(operation);
    assert!(guard.client_mut().await.is_err());
    await_original_guard_release(&mut observer).await;
}

#[tokio::test]
async fn commit_unknown_never_reuses_the_original_authority_socket() {
    let mut observer = database().await;
    let mut guard = authority(true).await;
    let result: Result<(),PublicationError> = with_job_role(&mut guard, JobRole::Publisher, async |_client| {
        Err(PublicationError::OutcomeUnknown)
    }).await;
    assert_eq!(result.unwrap_err(),PublicationError::OutcomeUnknown);
    assert!(guard.client_mut().await.is_err());
    await_original_guard_release(&mut observer).await;
}

#[tokio::test]
async fn failed_role_restore_revokes_the_guard_instead_of_reusing_an_unknown_role() {
    let mut observer = database().await;
    let mut guard = authority(true).await;
    let result: Result<(),PublicationError> = with_job_role(&mut guard, JobRole::Reader, async |client| {
        let pid:i32=client.query_one("SELECT pg_backend_pid()",&[]).await.unwrap().get(0);
        assert!(observer.client.query_one("SELECT pg_terminate_backend($1)",&[&pid]).await.unwrap().get::<_,bool>(0));
        Ok(())
    }).await;
    assert!(result.is_err());
    assert!(guard.client_mut().await.is_err());
    await_original_guard_release(&mut observer).await;
}

async fn confirmed_publication_survives_role_restore_failure(replay: bool) {
    let mut admin = database().await;
    // Backtest readback needs the original Preparation and actual Worker output.
    let f = seed(&admin.client, JobKind::Research, 1, 32).await;
    let namespace = SemanticStoreId::new(NS).unwrap();
    let mut fault = proxy::Proxy::start(proxy::Mode::DropBeforeRoleRestore);
    let (client, driver) = proxy_config(&fault).connect(NoTls).await.unwrap();
    let mut guard = AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap();
    with_job_role(&mut guard, JobRole::Publisher, async |client| {
        PublicationRepository::new(client, &namespace, OWNER)
            .await?
            .register(&f.registration)
            .await
    }).await.unwrap();
    if replay {
        let first = PublicationRepository::publish_guarded(&mut guard, &namespace, &f.claim, &f.candidate)
            .await.unwrap();
        assert!(matches!(first, PublishOutcome::Committed { .. }));
    }
    fault.arm();
    let (outcome, ()) = tokio::join!(
        PublicationRepository::publish_guarded(&mut guard, &namespace, &f.claim, &f.candidate),
        fault.entered(),
    );
    let outcome = outcome.unwrap();
    assert_eq!(matches!(&outcome, PublishOutcome::AlreadyPublished(_)), replay);
    assert!(guard.client_mut().await.is_err());
    await_original_guard_release(&mut admin).await;

    let mut reader = connected(true).await;
    reader.client.batch_execute("SET ROLE onlyalpha_job_reader").await.unwrap();
    let observed = PublicationRepository::new(&mut reader.client, &namespace, OWNER)
        .await.unwrap().read(&f.locator()).await.unwrap();
    assert_eq!(observed.binding().run_id(), f.run_id());
    assert_eq!(observed.fingerprint(), outcome.publication().fingerprint());
    assert_eq!(observed.manifest(), outcome.publication().manifest());
    assert_eq!(observed.member_count(), f.candidate.member_count());
    for member in observed.manifest()["members"].as_array().unwrap() {
        let key = member["key"].as_str().unwrap();
        assert_eq!(observed.content(key), f.candidate.content(key));
    }
}

#[tokio::test]
async fn committed_publication_survives_failed_role_restore_on_the_original_socket() {
    confirmed_publication_survives_role_restore_failure(false).await;
}

#[tokio::test]
async fn already_published_result_survives_failed_role_restore_on_the_original_socket() {
    confirmed_publication_survives_role_restore_failure(true).await;
}

#[tokio::test]
async fn administrator_cannot_impersonate_the_ordinary_node_publisher() {
    let mut observer = database().await;
    let mut guard = authority(false).await;
    let result: Result<(),PublicationError> = with_job_role(&mut guard, JobRole::Publisher, async |_client| {
        panic!("administrator must be refused before the operation")
    }).await;
    assert_eq!(result.unwrap_err(),PublicationError::Denied);
    assert!(guard.client_mut().await.is_err());
    await_original_guard_release(&mut observer).await;
}

#[tokio::test]
async fn composition_build_proof_read_uses_only_the_explicit_reader() {
    let admin = database().await;
    assert!(prepare_node_login().status.success());
    let mut config:tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
    config.user("onlyalpha_node_test");
    let (client,driver) = config.connect(NoTls).await.unwrap();
    let mut control = Connection {client,driver:tokio::spawn(driver),runtime:false};
    let (client,driver) = config.connect(NoTls).await.unwrap();
    let mut facts = Connection {client,driver:tokio::spawn(driver),runtime:false};
    facts.client.batch_execute("SET ROLE onlyalpha_job_reader").await.unwrap();
    let before:i32 = control.client.query_one("SELECT pg_backend_pid()",&[]).await.unwrap().get(0);
    let proof = json!({"build_key":"a".repeat(64),"context":{}});
    let missing = crate::persistence::strategy_research::Composer::new(&mut control.client)
        .with_fact_reader(&mut facts.client).verify_calculation_build(&proof).await;
    assert_eq!(missing,Err("CALCULATION_BUILD_PROOF_MISSING"),"missing immutable proof never starts construction");
    let unbound = crate::persistence::strategy_research::Composer::new(&mut control.client)
        .verify_calculation_build(&proof).await;
    assert_eq!(unbound,Err("PRIVATE_STRATEGY_BUILD_READER_REQUIRED"),"no control-client fallback");
    let state = control.client.query_one("SELECT pg_backend_pid(),current_user=session_user,has_table_privilege(current_user,'public.calculation_build_proof','SELECT'),has_table_privilege(current_user,'public.calculation_build_proof','INSERT')",&[]).await.unwrap();
    assert_eq!(state.get::<_,i32>(0),before);
    assert!(state.get::<_,bool>(1));
    assert!(!state.get::<_,bool>(2));
    assert!(!state.get::<_,bool>(3));
    let count:i64 = admin.client.query_one("SELECT count(*) FROM calculation_build_proof WHERE build_key=$1",&[&"a".repeat(64)]).await.unwrap().get(0);
    assert_eq!(count,0);
}

#[tokio::test]
async fn external_build_fact_context_requires_readonly_reader_and_exact_namespace() {
    let mut metadata=database().await;
    let metadata_tx=metadata.client.build_transaction().read_only(true).isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).start().await.unwrap();
    let mut connection=connected(true).await;
    connection.client.batch_execute("SET ROLE onlyalpha_job_reader").await.unwrap();
    let namespace=SemanticStoreId::new(NS).unwrap();
    let tx=connection.client.transaction().await.unwrap();
    assert!(matches!(crate::persistence::build_fact_read::BuildFactRead::reader(&metadata_tx,&tx,&namespace).await,Err(PublicationError::Denied)));
    tx.rollback().await.unwrap();
    let tx=connection.client.build_transaction().read_only(true).isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).start().await.unwrap();
    assert!(matches!(crate::persistence::build_fact_read::BuildFactRead::reader(&metadata_tx,&tx,&namespace).await,Err(PublicationError::Denied)),"old fixed facts snapshots cannot accompany newer metadata");
    tx.rollback().await.unwrap();
    let tx=connection.client.build_transaction().read_only(true).start().await.unwrap();
    let wrong=SemanticStoreId::new("88888888-8888-4888-8888-888888888888").unwrap();
    assert!(matches!(crate::persistence::build_fact_read::BuildFactRead::reader(&metadata_tx,&tx,&wrong).await,Err(PublicationError::Mismatch)));
    let scope=crate::persistence::build_fact_read::BuildFactRead::reader(&metadata_tx,&tx,&namespace).await.unwrap();
    assert_eq!(scope.verify_calculation(&json!({"build_key":"a".repeat(64),"context":{}})).await,Err("CALCULATION_BUILD_PROOF_MISSING"));
    tx.batch_execute("SET LOCAL ROLE onlyalpha_job_publisher").await.unwrap();
    assert!(matches!(crate::persistence::build_fact_read::BuildFactRead::reader(&metadata_tx,&tx,&namespace).await,Err(PublicationError::Denied)));
    tx.rollback().await.unwrap();
}

#[tokio::test]
async fn control_fact_restore_failure_cannot_be_rehabilitated_by_outer_rollback() {
    let mut observer=database().await;
    let mut guard=authority(true).await;
    let mut owned=guard.take_ownership();
    let roles=owned.control_roles().unwrap();
    let tx=owned.client_mut().await.unwrap().transaction().await.unwrap();
    let result: Result<Result<(), &'static str>, PublicationError> =
        crate::persistence::job_publication::read_control_facts(&tx,&roles,|reader| async move {
            reader.batch_execute("SELECT 1 / 0").await.map_err(|_|"fact_query_failed")
        }).await;
    assert_eq!(result,Err(PublicationError::OutcomeUnknown),"an aborted transaction cannot acknowledge role restoration or prove corrupt content");
    // A later rollback is not an acknowledgement of the failed role scope.
    let _=tx.rollback().await;
    assert!(owned.verify().await.is_err(),"the original driver must stay revoked after restoration failed");
    assert!(guard.client_mut().await.is_err());
    await_original_guard_release(&mut observer).await;
}

#[tokio::test]
async fn cancelling_a_borrowed_control_scope_revokes_its_still_retained_owner() {
    let mut observer=database().await;
    let mut guard=authority(true).await;
    let roles=guard.control_roles().unwrap();
    let tx=guard.client_mut().await.unwrap().transaction().await.unwrap();
    let (entered,ready)=tokio::sync::oneshot::channel();
    let mut operation=Box::pin(crate::persistence::job_publication::read_control_facts(&tx,&roles,|_| async move {
        entered.send(()).unwrap();
        std::future::pending::<Result<(),&'static str>>().await
    }));
    tokio::select! {
        value=ready=>value.unwrap(),
        value=&mut operation=>panic!("scope ended before cancellation: {value:?}"),
    }
    drop(operation);
    let _=tx.rollback().await;
    assert!(guard.verify().await.is_err());
    await_original_guard_release(&mut observer).await;
}

#[tokio::test]
async fn restored_sql_role_without_final_scope_ack_cannot_rehabilitate_the_owner() {
    let mut observer=database().await;
    let mut guard=authority(true).await;
    let roles=guard.control_roles().unwrap();
    let tx=guard.client_mut().await.unwrap().transaction().await.unwrap();
    let scope=roles.enter();
    roles.verify_transaction(&tx).await.unwrap();
    tx.batch_execute("SET LOCAL ROLE onlyalpha_job_reader; SET LOCAL ROLE NONE").await.unwrap();
    assert!(tx.query_one("SELECT current_user=session_user",&[]).await.unwrap().get::<_,bool>(0));
    AuthoritySession::verify_transaction(&tx).await.unwrap();
    // Model loss/cancellation after the server restored the role, before the
    // actual owner acknowledged the whole scope. SQL state is insufficient.
    drop(scope);
    let _=tx.rollback().await;
    assert!(guard.verify().await.is_err());
    await_original_guard_release(&mut observer).await;
}

#[tokio::test]
async fn control_scope_rejects_a_different_physical_transaction() {
    let mut observer=database().await;
    let mut guard=authority(true).await;
    let roles=guard.control_roles().unwrap();
    // Move the infrastructure lock to the foreign socket without killing the
    // original driver: a lock-only check would now accept the wrong socket.
    assert!(guard.client_mut().await.unwrap().query_one("SELECT pg_catalog.pg_advisory_unlock(1329199301,5)",&[]).await.unwrap().get::<_,bool>(0));
    let mut other=connected(true).await;
    let tx=other.client.transaction().await.unwrap();
    assert!(tx.query_one("SELECT pg_catalog.pg_try_advisory_lock(1329199301,5)",&[]).await.unwrap().get::<_,bool>(0));
    AuthoritySession::verify_transaction(&tx).await.unwrap();
    let result:Result<Result<(),&'static str>,PublicationError>=crate::persistence::job_publication::read_control_facts(&tx,&roles,|_| async {panic!("foreign transaction cannot enter the operation")}).await;
    assert!(result.is_err());
    let expired:Result<Result<(),&'static str>,PublicationError>=crate::persistence::job_publication::read_control_facts(&tx,&roles,|_| async {panic!("a revoked token cannot execute another operation")}).await;
    assert!(expired.is_err());
    assert!(tx.query_one("SELECT pg_catalog.pg_advisory_unlock(1329199301,5)",&[]).await.unwrap().get::<_,bool>(0));
    tx.rollback().await.unwrap();
    assert!(other.client.query_one("SELECT current_user=session_user",&[]).await.unwrap().get::<_,bool>(0));
    assert!(guard.verify().await.is_err());
    await_original_guard_release(&mut observer).await;
}
