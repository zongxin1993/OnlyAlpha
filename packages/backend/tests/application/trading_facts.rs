use onlyalpha_backend::{
    application::command::{Admission, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
    bootstrap::configuration::load_schema_history,
    persistence::{
        authority_session::AuthoritySession, postgres::Commands,
        trading_facts::TradingFactRepository,
    },
    workers::sim::recover_economic_state,
};
use onlyalpha_runtime::{RunConfiguration, durability::{DurableFactPort, TradingBinding}};
use serde_json::{Value, json};
use std::{path::Path, process::Command};
use tokio::sync::{Mutex, MutexGuard, OnceCell};
use tokio_postgres::{Config, NoTls};

const FIXTURE: &str = include_str!("../../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../../test-data/settlement/common-v1.json");
#[path = "../../../../crates/execution/tests/support/mod.rs"]
mod economics;
#[path = "support/trading_venue.rs"]
mod trading_venue;
#[allow(dead_code)]
#[path = "../../src/tests/support/job_publication_proxy.rs"]
mod commit_fault;

fn virtual_venue_executable() -> std::path::PathBuf {
    let build = Command::new(env!("CARGO"))
        .args(["test", "--locked", "--offline", "-p", "onlyalpha-broker-virtual", "--test", "controlled_trading_venue", "--no-run", "--message-format=json"])
        .output().unwrap();
    assert!(build.status.success(), "{}{}", String::from_utf8_lossy(&build.stderr), String::from_utf8_lossy(&build.stdout));
    let mut executable = None;
    for line in std::str::from_utf8(&build.stdout).unwrap().lines() {
        let message: Value = serde_json::from_str(line).unwrap();
        if message["reason"] == "compiler-artifact" && message["target"]["name"] == "controlled_trading_venue" {
            assert!(executable.is_none());
            executable = message["executable"].as_str().map(std::path::PathBuf::from);
        }
    }
    executable.expect("Cargo must identify the controlled venue test executable")
}

async fn serial() -> MutexGuard<'static, ()> {
    static AUTHORITY: Mutex<()> = Mutex::const_new(());
    AUTHORITY.lock().await
}

fn database() -> Config {
    let config: Config = std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
    assert_eq!(config.get_dbname(), Some("onlyalpha_dev_validation_test"));
    config
}

async fn node_session() -> AuthoritySession {
    static READY: OnceCell<()> = OnceCell::const_new();
    READY.get_or_init(|| async {
        let (mut client, driver) = database().connect(NoTls).await.unwrap();
        let driver = tokio::spawn(driver);
        let history = load_schema_history(Path::new("/workspace/database/postgres/migrations"), 16 * 1024 * 1024).unwrap();
        history.migrate(&mut client).await.unwrap();
        drop(client);
        driver.await.unwrap().unwrap();
        let login = Command::new("python3").current_dir("/workspace").args(["-m", "scripts.node_database", "--test"]).output().unwrap();
        assert!(login.status.success(), "{}", String::from_utf8_lossy(&login.stderr));
    }).await;
    let (client, driver) = database().user("onlyalpha_node_test").connect(NoTls).await.unwrap();
    AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap()
}

fn binding(case_name: &str) -> TradingBinding {
    let mut entropy = [0u8; 32];
    getrandom::fill(&mut entropy).unwrap();
    let generation = onlyalpha_execution::digest(&[case_name.as_bytes(), &entropy].concat());
    binding_for_generation(&generation)
}

fn binding_for_generation(generation: &str) -> TradingBinding {
    let mut config = economics::config();
    config["runtime_kind"] = json!("SIM");
    config["generation"] = json!(generation);
    TradingBinding::new(RunConfiguration::from_record(config).unwrap(), &"b".repeat(64)).unwrap()
}

fn admit(binding: &TradingBinding) -> Value {
    let mut input = economics::open(1, "BUY");
    input["runtime_kind"] = json!("SIM");
    input["generation"] = binding.configuration().record()["generation"].clone();
    input
}

#[tokio::test]
async fn trading_fact_repository_refuses_a_migration_login_holding_the_node_lock() {
    let _guard = serial().await;
    let mut node = node_session().await;
    assert!(TradingFactRepository::new(&mut node).await.is_ok());
    node.close().await.unwrap();

    let (client, driver) = database().connect(NoTls).await.unwrap();
    let mut migration = AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap();
    assert!(matches!(TradingFactRepository::new(&mut migration).await,
        Err(onlyalpha_runtime::durability::DurabilityError::Unavailable)));
    migration.close().await.unwrap();
}

#[tokio::test]
async fn projection_requires_a_committed_original_and_the_current_authority_connection() {
    let _guard = serial().await;
    let binding = binding("projection-proof");
    let mut session = node_session().await;
    let (other, driver) = database().user("onlyalpha_node_test").connect(NoTls).await.unwrap();
    let driver = tokio::spawn(driver);
    let error = other.execute(
        "INSERT INTO public.trading_fact_stream(scope_key,binding_fingerprint,kernel_artifact,configuration,configuration_fingerprint)
         VALUES ($1,$2,$3,$4,$5)",
        &[&binding.key(), &binding.fingerprint(), &binding.kernel_artifact(),
          &binding.configuration().record().to_string(), &binding.configuration().fingerprint()],
    ).await.unwrap_err();
    assert_eq!(error.as_db_error().unwrap().message(), "TRADING_AUTHORITY_REQUIRED");
    assert!(other.query_opt("SELECT head FROM public.trading_fact_stream WHERE scope_key=$1", &[&binding.key()]).await.unwrap().is_none());
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    repository.register(&binding).await.unwrap();
    let facts = repository.load_recovery(&binding).await.unwrap().prepare(&admit(&binding)).unwrap();
    let plan = facts.prepared();
    let sequence = i64::try_from(plan.sequence()).unwrap();
    let install = "SELECT public.trading_fact_install_projection($1,$2)";
    let insert = "INSERT INTO public.trading_fact(scope_key,sequence,transaction_id,input_id,configuration_fingerprint,payload_fingerprint,prepared)
                  VALUES ($1,$2,$3,$4,$5,$6,$7)";
    let body = String::from_utf8(plan.encode().unwrap()).unwrap();
    let input_id = plan.input()["input_id"].as_str().unwrap();
    let client = session.client_mut().await.unwrap();
    let tx = client.transaction().await.unwrap();
    tx.execute(insert, &[&binding.key(), &sequence, &plan.id(), &input_id, &plan.configuration_fingerprint(), &plan.payload_fingerprint(), &body]).await.unwrap();
    let error = tx.query_one(install, &[&binding.key(), &sequence]).await.unwrap_err();
    assert_eq!(error.as_db_error().unwrap().message(), "TRADING_FACT_PROJECTION_MISSING");
    tx.rollback().await.unwrap();

    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    let error = other.execute(insert, &[&binding.key(), &sequence, &plan.id(), &input_id, &plan.configuration_fingerprint(), &plan.payload_fingerprint(), &body]).await.unwrap_err();
    assert_eq!(error.as_db_error().unwrap().message(), "TRADING_AUTHORITY_REQUIRED");
    let head = other.query_one("SELECT head FROM public.trading_fact_stream WHERE scope_key=$1", &[&binding.key()]).await.unwrap();
    assert_eq!(head.get::<_, i64>(0), 0);
    assert!(repository.load_recovery(&binding).await.unwrap().records().is_empty());
    repository.commit(&facts).await.unwrap();
    let error = other.execute("INSERT INTO public.trading_fact_ready(scope_key,sequence) VALUES ($1,$2)", &[&binding.key(), &sequence]).await.unwrap_err();
    assert_eq!(error.code(), Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE));
    let error = other.query_one(install, &[&binding.key(), &sequence]).await.unwrap_err();
    assert_eq!(error.as_db_error().unwrap().message(), "TRADING_AUTHORITY_REQUIRED");
    let tail = repository.load_recovery(&binding).await.unwrap();
    assert_eq!(tail.unprojected().unwrap().prepared(), plan);
    repository.mark_projected(&tail).await.unwrap();
    let stored = other.query_one("SELECT result_hashes FROM public.trading_fact_ready WHERE scope_key=$1 AND sequence=$2", &[&binding.key(), &sequence]).await.unwrap();
    let expected: Vec<_> = plan.projection_hashes().iter().map(|(_, result)| result.clone()).collect();
    assert_eq!(stored.get::<_, Vec<String>>(0), expected);
    drop(other);
    driver.await.unwrap().unwrap();
    session.close().await.unwrap();
}

#[tokio::test]
async fn mismatched_projection_digests_leave_the_successor_unready() {
    let _guard = serial().await;
    let mut session = node_session().await;
    for field in ["before_hash", "result_hash"] {
        let binding = binding(field);
        let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
        repository.register(&binding).await.unwrap();
        let first = repository.load_recovery(&binding).await.unwrap().prepare(&admit(&binding)).unwrap();
        repository.commit(&first).await.unwrap();
        let tail = repository.load_recovery(&binding).await.unwrap();
        repository.mark_projected(&tail).await.unwrap();
        let mut input = economics::stage(2, 1, "UNKNOWN");
        input["runtime_kind"] = json!("SIM");
        input["generation"] = binding.configuration().record()["generation"].clone();
        let second = repository.load_recovery(&binding).await.unwrap().prepare(&input).unwrap();
        let plan = second.prepared();
        let mut body = plan.record();
        body["projections"][2][field] = json!("0".repeat(64));
        body.as_object_mut().unwrap().remove("payload_hash");
        let digest = onlyalpha_execution::digest(body.to_string().as_bytes());
        body["payload_hash"] = json!(digest);
        let client = session.client_mut().await.unwrap();
        client.execute("INSERT INTO public.trading_fact(scope_key,sequence,transaction_id,input_id,configuration_fingerprint,payload_fingerprint,prepared)
            VALUES ($1,2,$2,$3,$4,$5,$6)", &[&binding.key(), &plan.id(), &input["input_id"].as_str().unwrap(), &plan.configuration_fingerprint(), &digest, &body.to_string()]).await.unwrap();
        let error = client.query_one("SELECT public.trading_fact_install_projection($1,2)", &[&binding.key()]).await.unwrap_err();
        assert_eq!(error.as_db_error().unwrap().message(), "TRADING_FACT_PROJECTION_CONFLICT", "{field}");
        let rows = client.query("SELECT sequence FROM public.trading_fact_ready WHERE scope_key=$1", &[&binding.key()]).await.unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].get::<_, i64>(0), 1);
    }
    session.close().await.unwrap();
}

#[tokio::test]
async fn commit_interruption_keeps_one_original_transaction_across_processes() {
    let _guard = serial().await;
    let binding = binding("restart");
    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    repository.register(&binding).await.unwrap();
    let original = repository.load_recovery(&binding).await.unwrap();
    let prepared = original.prepare(&admit(&binding)).unwrap();
    let receipt = repository.commit(&prepared).await.unwrap();
    assert!(!receipt.ready());
    assert_eq!(receipt.sequence(), 1);
    assert_eq!(repository.commit(&prepared).await.unwrap().transaction_id(), receipt.transaction_id());
    session.close().await.unwrap();

    let child = Command::new(std::env::current_exe().unwrap())
        .args(["--exact", "recover_committed_tail_in_child", "--ignored", "--nocapture"])
        .env("ONLYALPHA_TEST_TRADING_GENERATION", binding.configuration().record()["generation"].as_str().unwrap())
        .env("ONLYALPHA_TEST_TRADING_TRANSACTION", receipt.transaction_id())
        .output().unwrap();
    assert!(child.status.success(), "{}{}", String::from_utf8_lossy(&child.stdout), String::from_utf8_lossy(&child.stderr));
    assert!(String::from_utf8_lossy(&child.stdout).contains("recovered original trading transaction"));

    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    let recovered = repository.load_recovery(&binding).await.unwrap();
    assert_eq!(recovered.records().len(), 1);
    assert!(recovered.unprojected().is_none());
    assert_eq!(recovered.records()[0].prepared(), prepared.prepared());
    session.close().await.unwrap();
}

#[tokio::test]
#[ignore = "spawned by commit_interruption_keeps_one_original_transaction_across_processes"]
async fn recover_committed_tail_in_child() {
    let binding = binding_for_generation(&std::env::var("ONLYALPHA_TEST_TRADING_GENERATION").unwrap());
    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    let recovered = repository.load_recovery(&binding).await.unwrap();
    let pending = recovered.unprojected().unwrap();
    assert_eq!(pending.prepared().id(), std::env::var("ONLYALPHA_TEST_TRADING_TRANSACTION").unwrap());
    assert_eq!(pending.prepared().input(), &admit(&binding));
    let projected = recovered.state().unwrap();
    let observed = recover_economic_state(&mut repository, &binding).await.unwrap();
    assert_eq!(observed.records().len(), 1);
    assert_eq!(observed.records()[0].prepared(), pending.prepared());
    assert!(observed.records()[0].ready());
    assert_eq!(observed.state().unwrap(), projected);
    session.close().await.unwrap();
    println!("recovered original trading transaction");
}

#[tokio::test]
async fn commit_disconnect_requires_original_fact_observation() {
    use commit_fault::{Mode, Proxy};
    use onlyalpha_runtime::durability::DurabilityError;

    let _guard = serial().await;
    for (mode, committed) in [(Mode::DropBeforeCommit, false), (Mode::DropCommitReply, true)] {
        let binding = binding("commit-disconnect");
        let mut session = node_session().await;
        let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
        repository.register(&binding).await.unwrap();
        let prepared = repository.load_recovery(&binding).await.unwrap().prepare(&admit(&binding)).unwrap();
        session.close().await.unwrap();

        let mut fault = Proxy::start(mode);
        let socket = tokio::net::TcpStream::connect(("127.0.0.1", fault.port())).await.unwrap();
        let (client, driver) = database().user("onlyalpha_node_test").connect_raw(socket, NoTls).await.unwrap();
        let mut failed_session = AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap();
        let mut repository = TradingFactRepository::new(&mut failed_session).await.unwrap();
        fault.arm();
        assert_eq!(repository.commit(&prepared).await.unwrap_err(), DurabilityError::UnknownCommit);
        fault.entered().await;
        assert!(matches!(repository.load_recovery(&binding).await, Err(DurabilityError::Unavailable)));
        drop(failed_session);
        drop(fault);

        let mut session = node_session().await;
        let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
        let observed = repository.load_recovery(&binding).await.unwrap();
        if committed {
            assert_eq!(observed.records().len(), 1);
            assert_eq!(observed.unprojected().unwrap().prepared(), prepared.prepared());
        } else {
            assert!(observed.records().is_empty());
        }
        session.close().await.unwrap();
    }
}

#[tokio::test]
async fn projection_commit_disconnect_recovers_the_same_sim_plan_on_a_new_connection() {
    use commit_fault::{Mode, Proxy};
    use onlyalpha_runtime::durability::DurabilityError;

    let _guard = serial().await;
    for (mode, ready) in [(Mode::DropBeforeCommit, false), (Mode::DropCommitReply, true)] {
        let binding = binding("sim-projection-disconnect");
        let mut session = node_session().await;
        let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
        repository.register(&binding).await.unwrap();
        let empty = recover_economic_state(&mut repository, &binding).await.unwrap();
        assert!(empty.records().is_empty());
        let prepared = empty.prepare(&admit(&binding)).unwrap();
        repository.commit(&prepared).await.unwrap();
        session.close().await.unwrap();

        let mut fault = Proxy::start(mode);
        let socket = tokio::net::TcpStream::connect(("127.0.0.1", fault.port())).await.unwrap();
        let (client, driver) = database().user("onlyalpha_node_test").connect_raw(socket, NoTls).await.unwrap();
        let mut failed = AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap();
        let mut repository = TradingFactRepository::new(&mut failed).await.unwrap();
        // 第一次 COMMIT 结束原记录读取，第二次才提交投影安装。
        fault.arm_on_match(2);
        assert!(matches!(recover_economic_state(&mut repository, &binding).await, Err(DurabilityError::UnknownCommit)));
        fault.entered().await;
        drop(failed);
        drop(fault);

        let (client, driver) = database().user("onlyalpha_node_test").connect(NoTls).await.unwrap();
        let driver = tokio::spawn(driver);
        // 服务端可能仍在回收断线会话，等待同一把节点锁释放后再正式接手。
        client.batch_execute("BEGIN; SET LOCAL lock_timeout='5s'; SELECT pg_catalog.pg_advisory_xact_lock(1329199301,5); COMMIT").await.unwrap();
        let mut session = AuthoritySession::acquire(client, driver).await.unwrap();
        let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
        let observed = repository.load_recovery(&binding).await.unwrap();
        assert_eq!(observed.records().len(), 1);
        assert_eq!(observed.records()[0].prepared(), prepared.prepared());
        assert_eq!(observed.records()[0].ready(), ready);
        let recovered = recover_economic_state(&mut repository, &binding).await.unwrap();
        assert_eq!(recovered.records().len(), 1);
        assert!(recovered.records()[0].ready());
        assert_eq!(recovered.records()[0].prepared(), prepared.prepared());
        assert_eq!(recovered.state().unwrap(), observed.state().unwrap());
        session.close().await.unwrap();
    }
}

#[tokio::test]
async fn mismatched_binding_and_competing_first_fact_cannot_replace_history() {
    let _guard = serial().await;
    let binding = binding("conflict");
    let repinned = TradingBinding::new(binding.configuration().clone(), &"c".repeat(64)).unwrap();
    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    assert!(matches!(recover_economic_state(&mut repository, &binding).await,
        Err(onlyalpha_runtime::durability::DurabilityError::Rejected(code)) if code == "TRADING_FACT_BINDING_MISSING"));
    repository.register(&binding).await.unwrap();
    assert!(repository.register(&repinned).await.is_err());
    assert!(matches!(recover_economic_state(&mut repository, &repinned).await,
        Err(onlyalpha_runtime::durability::DurabilityError::Rejected(code)) if code == "TRADING_FACT_BINDING_CONFLICT"));
    let empty = repository.load_recovery(&binding).await.unwrap();
    let original = admit(&binding);
    let prepared = empty.prepare(&original).unwrap();
    let mut other = original;
    other["source_ref"] = json!("other-market-observation");
    let competing = empty.prepare(&other).unwrap();
    repository.commit(&prepared).await.unwrap();
    assert!(repository.commit(&competing).await.is_err());
    let recovered = repository.load_recovery(&binding).await.unwrap();
    assert_eq!(recovered.records().len(), 1);
    assert_eq!(recovered.records()[0].prepared(), prepared.prepared());
    session.close().await.unwrap();
}

async fn seed_sim_venue_open(
    venue_client: &mut tokio_postgres::Client,
    binding: &TradingBinding,
) -> String {
    let tx = venue_client.transaction().await.unwrap();
    tx.execute("SET LOCAL lock_timeout = '5s'", &[])
        .await
        .unwrap();
    tx.query_one("SELECT pg_catalog.pg_advisory_xact_lock(1329199301, 5)", &[])
        .await
        .unwrap();
    let command_raw: String = tx
        .query_one("SELECT gen_random_uuid()::text", &[])
        .await
        .unwrap()
        .get(0);
    let deployment_id: String = tx
        .query_one("SELECT gen_random_uuid()::text", &[])
        .await
        .unwrap()
        .get(0);
    let command_id = CommandId::new(&command_raw).unwrap();
    let config = binding.configuration().record();
    let account_id = config["account"].as_str().unwrap();
    let generation = config["generation"].as_str().unwrap();
    let kernel = binding.kernel_artifact();
    let intent_doc = json!({"deployment_id": deployment_id, "account_id": account_id}).to_string();
    let intent_pin = onlyalpha_execution::digest(intent_doc.as_bytes());
    let admission =
        Admission::new(command_id.clone(), CommandKind::StartSimRun, &intent_pin).unwrap();
    Commands::admit_exact_in_transaction(&tx, &admission)
        .await
        .unwrap();
    let run_id: String = tx
        .query_one(
            "INSERT INTO public.sim_run_reservation \
             (command_id,command_fingerprint,intent,deployment_id,account_id,generation,kernel_artifact) \
             VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$7) RETURNING run_id",
            &[
                &command_id.value(),
                &intent_pin,
                &intent_doc,
                &deployment_id,
                &account_id,
                &generation,
                &kernel,
            ],
        )
        .await
        .unwrap()
        .get(0);
    let receipt = Receipt::new(
        admission,
        Outcome::new(OutcomeKind::SimRun, &run_id).unwrap(),
        "2026-11-24T00:00:00Z",
    )
    .unwrap();
    Commands::put_verified_receipt_in_transaction(&tx, &receipt)
        .await
        .unwrap();
    let broker_pin = "c".repeat(64);
    tx.execute(
        "INSERT INTO public.sim_run_admission \
         (command_id,run_id,deployment_id,account_id,scope_key,binding_fingerprint,broker_runtime_fingerprint) \
         VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$7)",
        &[
            &command_id.value(),
            &run_id,
            &deployment_id,
            &account_id,
            &binding.key(),
            &binding.fingerprint(),
            &broker_pin,
        ],
    )
    .await
    .unwrap();
    let genesis_previous = "0".repeat(64);
    let open_doc = json!({
        "scope_key": binding.key(),
        "sequence": 0,
        "previous": genesis_previous,
        "kind": "OPEN",
        "body": {"trading_binding": binding.fingerprint()}
    })
    .to_string();
    let open_fingerprint = onlyalpha_execution::digest(open_doc.as_bytes());
    tx.execute(
        "INSERT INTO public.sim_venue_log (scope_key,sequence,previous,fingerprint,document) \
         VALUES ($1,$2,$3,$4,$5)",
        &[
            &binding.key(),
            &0_i64,
            &genesis_previous,
            &open_fingerprint,
            &open_doc,
        ],
    )
    .await
    .unwrap();
    tx.commit().await.unwrap();
    open_fingerprint
}

fn protocol_intent_document(
    scope_key: &str,
    previous: &str,
    transaction_id: &str,
    payload_hash: &str,
) -> (String, String) {
    let document = json!({
        "scope_key": scope_key,
        "sequence": 1,
        "previous": previous,
        "kind": "PROTOCOL",
        "body": {
            "record": {
                "schema_version": 1,
                "sequence": 1,
                "previous": "0".repeat(64),
                "event": {
                    "kind": "INTENT",
                    "intent": {
                        "transaction": transaction_id,
                        "payload_hash": payload_hash
                    }
                }
            },
            "admitted_at": Value::Null,
            "checkpoint": "0".repeat(64)
        }
    })
    .to_string();
    let fingerprint = onlyalpha_execution::digest(document.as_bytes());
    (document, fingerprint)
}

async fn venue_log_prefix(client: &tokio_postgres::Client, scope_key: &str) -> Vec<(i64, String)> {
    client
        .query(
            "SELECT sequence, fingerprint FROM public.sim_venue_log \
             WHERE scope_key=$1 ORDER BY sequence",
            &[&scope_key],
        )
        .await
        .unwrap()
        .into_iter()
        .map(|row| (row.get(0), row.get(1)))
        .collect()
}

async fn assert_sim_venue_intent_rejected(
    venue_client: &mut tokio_postgres::Client,
    scope_key: &str,
    open_fingerprint: &str,
    transaction_id: &str,
    payload_hash: &str,
) {
    let (document, fingerprint) =
        protocol_intent_document(scope_key, open_fingerprint, transaction_id, payload_hash);
    let tx = venue_client.transaction().await.unwrap();
    tx.execute("SET LOCAL lock_timeout = '5s'", &[])
        .await
        .unwrap();
    tx.query_one("SELECT pg_catalog.pg_advisory_xact_lock(1329199301, 5)", &[])
        .await
        .unwrap();
    let error = tx
        .execute(
            "INSERT INTO public.sim_venue_log (scope_key,sequence,previous,fingerprint,document) \
             VALUES ($1,$2,$3,$4,$5)",
            &[&scope_key, &1_i64, &open_fingerprint, &fingerprint, &document],
        )
        .await
        .unwrap_err();
    let db = error
        .as_db_error()
        .expect("expected PostgreSQL trigger rejection");
    assert_eq!(db.code().code(), "23514");
    assert_eq!(db.message(), "SIM_ORIGINAL_INTENT_NOT_READY");
    tx.rollback().await.unwrap();
    assert_eq!(
        venue_log_prefix(venue_client, scope_key).await,
        vec![(0_i64, open_fingerprint.to_owned())]
    );
}

#[tokio::test]
async fn sim_venue_intent_requires_ready_original_transaction_at_write_time() {
    let _guard = serial().await;
    let other_binding = binding("sim-venue-ready-intent-other");
    let binding = binding("sim-venue-ready-intent");
    assert_ne!(binding.key(), other_binding.key());

    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    repository.register(&binding).await.unwrap();
    repository.register(&other_binding).await.unwrap();
    let other_prepared = repository
        .load_recovery(&other_binding)
        .await
        .unwrap()
        .prepare(&admit(&other_binding))
        .unwrap();
    repository.commit(&other_prepared).await.unwrap();
    let other_tail = repository.load_recovery(&other_binding).await.unwrap();
    repository.mark_projected(&other_tail).await.unwrap();
    let prepared = repository
        .load_recovery(&binding)
        .await
        .unwrap()
        .prepare(&admit(&binding))
        .unwrap();
    session.close().await.unwrap();

    let plan = prepared.prepared();
    let other_plan = other_prepared.prepared();
    assert_ne!(plan.id(), other_plan.id());

    let (mut venue_client, driver) = database().user("onlyalpha_node_test").connect(NoTls).await.unwrap();
    let driver = tokio::spawn(driver);
    let open_fingerprint = seed_sim_venue_open(&mut venue_client, &binding).await;
    assert_eq!(
        venue_log_prefix(&venue_client, binding.key()).await,
        vec![(0_i64, open_fingerprint.clone())]
    );

    assert_sim_venue_intent_rejected(
        &mut venue_client,
        binding.key(),
        &open_fingerprint,
        plan.id(),
        plan.payload_fingerprint(),
    )
    .await;

    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    repository.commit(&prepared).await.unwrap();
    assert!(
        repository
            .load_recovery(&binding)
            .await
            .unwrap()
            .unprojected()
            .is_some()
    );
    session.close().await.unwrap();

    assert_sim_venue_intent_rejected(
        &mut venue_client,
        binding.key(),
        &open_fingerprint,
        plan.id(),
        plan.payload_fingerprint(),
    )
    .await;

    let mut session = node_session().await;
    let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
    let tail = repository.load_recovery(&binding).await.unwrap();
    repository.mark_projected(&tail).await.unwrap();
    session.close().await.unwrap();

    assert_sim_venue_intent_rejected(
        &mut venue_client,
        binding.key(),
        &open_fingerprint,
        other_plan.id(),
        other_plan.payload_fingerprint(),
    )
    .await;

    let wrong_tx = "wrong-transaction-id";
    assert_ne!(plan.id(), wrong_tx);
    assert_sim_venue_intent_rejected(
        &mut venue_client,
        binding.key(),
        &open_fingerprint,
        wrong_tx,
        plan.payload_fingerprint(),
    )
    .await;

    let wrong_hash = if plan.payload_fingerprint().starts_with('0') {
        "1".repeat(64)
    } else {
        "0".repeat(64)
    };
    assert_sim_venue_intent_rejected(
        &mut venue_client,
        binding.key(),
        &open_fingerprint,
        plan.id(),
        &wrong_hash,
    )
    .await;

    let (document, intent_fingerprint) = protocol_intent_document(
        binding.key(),
        &open_fingerprint,
        plan.id(),
        plan.payload_fingerprint(),
    );
    let insert_intent = "INSERT INTO public.sim_venue_log (scope_key,sequence,previous,fingerprint,document) \
                         VALUES ($1,$2,$3,$4,$5)";
    let key = binding.key();
    let params: &[&(dyn tokio_postgres::types::ToSql + Sync)] =
        &[&key, &1_i64, &open_fingerprint, &intent_fingerprint, &document];
    let error = venue_client.execute(insert_intent, params).await.unwrap_err();
    let refusal = error.as_db_error().unwrap();
    assert_eq!(refusal.code().code(), "42501");
    assert_eq!(refusal.message(), "TRADING_AUTHORITY_REQUIRED");
    assert_eq!(venue_log_prefix(&venue_client, key).await, vec![(0, open_fingerprint.clone())]);

    let tx = venue_client.transaction().await.unwrap();
    tx.execute("SET LOCAL lock_timeout = '5s'", &[])
        .await
        .unwrap();
    tx.query_one("SELECT pg_catalog.pg_advisory_xact_lock(1329199301, 5)", &[])
        .await
        .unwrap();
    assert_eq!(tx.execute(insert_intent, params).await.unwrap(), 1);
    tx.commit().await.unwrap();
    assert_eq!(
        venue_log_prefix(&venue_client, binding.key()).await,
        vec![(0_i64, open_fingerprint), (1_i64, intent_fingerprint)]
    );

    drop(venue_client);
    driver.await.unwrap().unwrap();
}
