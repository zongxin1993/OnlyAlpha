use super::{NS, database, prepare_node_login};
use crate::application::command::{Admission, CommandId, CommandKind, Outcome, OutcomeKind, Receipt};
use crate::persistence::{
    authority_session::AuthoritySession,
    postgres::{self, Commands},
    sim_run::{Error, StartIntent, lookup_in_transaction, read_intent_resources, recovery_command_ids, recovery_in_transaction, reserve_in_transaction},
};
use tokio_postgres::{Client, NoTls};

async fn command_id(client: &Client) -> CommandId {
    let row = client.query_one("SELECT gen_random_uuid()::text", &[]).await.unwrap();
    CommandId::new(row.get(0)).unwrap()
}

fn intent() -> StartIntent {
    StartIntent {
        deployment_id: NS.into(), subject_kind: "HUMAN".into(), subject_id: "sim-reservation-test".into(),
        strategy_fingerprint: "1".repeat(64), backtest_run_id: "00900000-0000-4000-8000-000000000001".into(),
        policy_fingerprint: "2".repeat(64), decision_fingerprint: "3".repeat(64), promotion_fingerprint: "4".repeat(64),
        account_id: "sim-reservation-test".into(), account_revision_fingerprint: "5".repeat(64), broker_revision_fingerprint: "6".repeat(64),
    }
}

async fn node() -> (AuthoritySession, tokio::task::AbortHandle) {
    let mut config: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
    assert_eq!(config.get_dbname(), Some("onlyalpha_dev_validation_test"));
    config.user("onlyalpha_node_test");
    let (client, driver) = config.connect(NoTls).await.unwrap();
    let task = tokio::spawn(driver);
    let abort = task.abort_handle();
    (AuthoritySession::acquire(client, task).await.unwrap(), abort)
}

#[tokio::test]
async fn sim_reservation_survives_loss_of_its_original_session_at_the_commit_boundary() {
    let mut observer = database().await;
    assert!(prepare_node_login().status.success());
    let id = command_id(&observer.client).await;
    let pending = command_id(&observer.client).await;
    let intent = intent();
    let generation = "a".repeat(64);
    let kernel = "b".repeat(64);
    let (mut first, socket) = node().await;
    let tx = first.client_mut().await.unwrap().transaction().await.unwrap();
    let saved = reserve_in_transaction(&tx, &id, &intent, &generation, &kernel).await.unwrap();
    assert!(saved.accepted.is_none());
    tx.commit().await.unwrap();

    let tx = first.client_mut().await.unwrap().transaction().await.unwrap();
    reserve_in_transaction(&tx, &pending, &intent, &generation, &kernel).await.unwrap();
    socket.abort();
    let release = observer.client.transaction().await.unwrap();
    postgres::bounds(&release).await.unwrap();
    release.query_one("SELECT pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    release.commit().await.unwrap();
    assert!(tx.commit().await.is_err());
    assert!(first.client_mut().await.is_err());

    let (mut next, _) = node().await;
    let tx = next.client_mut().await.unwrap().transaction().await.unwrap();
    let replay = reserve_in_transaction(&tx, &id, &intent, &"c".repeat(64), &"d".repeat(64)).await.unwrap();
    assert_eq!(replay.run_id, saved.run_id);
    assert_eq!(replay.generation, generation);
    assert_eq!(replay.kernel_artifact, kernel);
    assert!(lookup_in_transaction(&tx, NS, "HUMAN", &intent.subject_id, &pending).await.unwrap().is_none());
    assert!(lookup_in_transaction(&tx, NS, "AGENT", &intent.subject_id, &id).await.unwrap().is_none());
    assert!(lookup_in_transaction(&tx, NS, "HUMAN", "another-subject", &id).await.unwrap().is_none());
    assert!(lookup_in_transaction(&tx, &intent.backtest_run_id, "HUMAN", &intent.subject_id, &id).await.unwrap().is_none());
    let original = lookup_in_transaction(&tx, NS, "HUMAN", &intent.subject_id, &id).await.unwrap().unwrap();
    assert_eq!(original.run_id, saved.run_id);
    let ids = recovery_command_ids(&tx, NS).await.unwrap();
    assert_eq!(ids.iter().filter(|value| value.as_str() == id.value()).count(), 1);
    assert!(!ids.iter().any(|value| value == pending.value()));
    let recovered = recovery_in_transaction(&tx, NS, id.value()).await.unwrap();
    assert_eq!(recovered.command_id, id);
    assert_eq!(recovered.run_id, saved.run_id);
    assert!(recovered.accepted.is_none());
    let mut changed = intent.clone();
    changed.broker_revision_fingerprint = "7".repeat(64);
    assert_eq!(reserve_in_transaction(&tx, &id, &changed, &generation, &kernel).await.unwrap_err(), Error::Conflict);
    assert!(matches!(read_intent_resources(&tx, &intent).await, Err(Error::Missing)));
    changed.deployment_id = intent.backtest_run_id.clone();
    assert!(matches!(read_intent_resources(&tx, &changed).await, Err(Error::Mismatch)));
    tx.rollback().await.unwrap();
    next.close().await.unwrap();
}

#[tokio::test]
async fn corrupt_reservation_does_not_hide_other_commands_from_recovery() {
    let mut admin = database().await;
    let damaged = command_id(&admin.client).await;
    let healthy = command_id(&admin.client).await;
    let mut intent = intent();
    intent.deployment_id = healthy.value().to_owned();
    let tx = admin.client.transaction().await.unwrap();
    tx.query_one("SELECT pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    let pin = "a".repeat(64);
    let original = reserve_in_transaction(&tx, &healthy, &intent, &pin, &pin).await.unwrap();
    let mut malformed = serde_json::to_value(&intent).unwrap();
    malformed.as_object_mut().unwrap().remove("subject_id");
    let raw = malformed.to_string();
    let hash = onlyalpha_execution::digest(raw.as_bytes());
    let admission = Admission::new(damaged.clone(), CommandKind::StartSimRun, &hash).unwrap();
    tx.batch_execute("SET CONSTRAINTS public.sim_run_command_reserved DEFERRED").await.unwrap();
    Commands::admit_exact_in_transaction(&tx, &admission).await.unwrap();
    tx.execute("INSERT INTO public.sim_run_reservation
        (command_id,command_fingerprint,intent,deployment_id,account_id,generation,kernel_artifact)
        VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$6)",
        &[&damaged.value(), &hash, &raw, &intent.deployment_id, &intent.account_id, &pin]).await.unwrap();
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.unwrap();
    let ids = recovery_command_ids(&tx, &intent.deployment_id).await.unwrap();
    assert_eq!(ids.len(), 2);
    assert!(ids.iter().any(|id| id == damaged.value()));
    assert!(ids.iter().any(|id| id == healthy.value()));
    assert!(matches!(recovery_in_transaction(&tx, &intent.deployment_id, damaged.value()).await, Err(Error::Integrity)));
    let verified = recovery_in_transaction(&tx, &intent.deployment_id, healthy.value()).await.unwrap();
    assert_eq!(verified.run_id, original.run_id);
    assert!(verified.accepted.is_none());
    tx.rollback().await.unwrap();
}

#[tokio::test]
async fn sim_reservation_requires_both_ownership_relations_and_the_original_lock() {
    let mut admin = database().await;
    let id = command_id(&admin.client).await;
    let intent = intent();
    let generation = "a".repeat(64);
    let kernel = "b".repeat(64);
    let tx = admin.client.transaction().await.unwrap();
    tx.batch_execute("CREATE TEMP TABLE sim_test_guard_loss (id int) ON COMMIT DROP;
        CREATE FUNCTION pg_temp.sim_test_release() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NULL; END $$;
        CREATE CONSTRAINT TRIGGER sim_guard_loss AFTER INSERT ON sim_test_guard_loss DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION pg_temp.sim_test_release(); INSERT INTO sim_test_guard_loss VALUES (1)").await.unwrap();
    tx.query_one("SELECT pg_advisory_lock(1329199301,5)", &[]).await.unwrap();
    assert_eq!(reserve_in_transaction(&tx, &id, &intent, &generation, &kernel).await.unwrap_err(), Error::Unavailable);
    tx.rollback().await.unwrap();
    let admission = Admission::new(id.clone(), CommandKind::StartSimRun, &intent.fingerprint().unwrap()).unwrap();
    let tx = admin.client.transaction().await.unwrap();
    assert!(matches!(Commands::verify_binding_in_transaction(&tx, &id).await.unwrap(), crate::application::command::Binding::None));
    Commands::admit_exact_in_transaction(&tx, &admission).await.unwrap();
    assert_eq!(tx.commit().await.unwrap_err().as_db_error().unwrap().message(), "SIM_RUN_RESERVATION_MISSING");

    let tx = admin.client.transaction().await.unwrap();
    tx.query_one("SELECT pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    let original = reserve_in_transaction(&tx, &id, &intent, &generation, &kernel).await.unwrap();
    tx.commit().await.unwrap();
    let tx = admin.client.transaction().await.unwrap();
    let receipt = Receipt::new(admission, Outcome::new(OutcomeKind::SimRun, &original.run_id).unwrap(), "2026-11-24T00:00:00Z").unwrap();
    Commands::put_verified_receipt_in_transaction(&tx, &receipt).await.unwrap();
    assert_eq!(tx.commit().await.unwrap_err().as_db_error().unwrap().message(), "SIM_RUN_ADMISSION_MISSING");

    let tx = admin.client.transaction().await.unwrap();
    tx.query_one("SELECT pg_advisory_xact_lock(1329199301,5)", &[]).await.unwrap();
    let scope = onlyalpha_execution::digest(id.value().as_bytes());
    let config = r#"{"runtime_kind":"SIM"}"#;
    let config_pin = onlyalpha_execution::digest(config.as_bytes());
    tx.execute("INSERT INTO public.trading_fact_stream (scope_key,binding_fingerprint,kernel_artifact,configuration,configuration_fingerprint)
        VALUES ($1,$2,$3,$4,$5)", &[&scope, &config_pin, &kernel, &config, &config_pin]).await.unwrap();
    tx.batch_execute("SAVEPOINT before_admission").await.unwrap();
    let insert_admission = "INSERT INTO public.sim_run_admission (command_id,run_id,deployment_id,account_id,scope_key,binding_fingerprint,broker_runtime_fingerprint)
        VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$7)";
    let command = id.value();
    let params: &[&(dyn tokio_postgres::types::ToSql + Sync)] = &[&command, &original.run_id, &NS,
        &intent.account_id, &scope, &config_pin, &intent.broker_revision_fingerprint];
    let err = tx.execute(insert_admission, params).await.unwrap_err();
    assert_eq!(err.as_db_error().unwrap().constraint(), Some("sim_run_admission_receipt_fk"));
    tx.batch_execute("ROLLBACK TO SAVEPOINT before_admission").await.unwrap();
    Commands::put_verified_receipt_in_transaction(&tx, &receipt).await.unwrap();
    tx.execute(insert_admission, params).await.unwrap();
    let err = tx.commit().await.unwrap_err();
    assert_eq!(err.as_db_error().unwrap().constraint(), Some("sim_run_open_fk"));
    let tx = admin.client.transaction().await.unwrap();
    assert!(lookup_in_transaction(&tx, NS, "HUMAN", &intent.subject_id, &id).await.unwrap().unwrap().accepted.is_none());
    tx.rollback().await.unwrap();
}
