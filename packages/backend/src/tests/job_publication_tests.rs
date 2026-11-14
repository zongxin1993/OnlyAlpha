use crate::application::job_contract::JobKind;
use crate::bootstrap::deployment::SemanticStoreId;
use crate::subject::fixture::{Fixture, fixture};
use crate::subject::{
    PublicationError, PublicationObservation, PublicationRepository, PublishOutcome,
};
use onlyalpha_backend::persistence::schema::SchemaHistory;
use serde_json::{Value, json};
use std::{
    path::Path,
    sync::atomic::{AtomicU64, Ordering},
};
use tokio_postgres::{Client, NoTls};
const NS: &str = "99999999-9999-4999-8999-999999999999";
const TEST_LOGIN: &str = "onlyalpha_job_storage_test_login";
const OWNER: &str = "human:publication-test";
static SEQUENCE: AtomicU64 = AtomicU64::new(1);
static INITIALIZED: tokio::sync::OnceCell<()> = tokio::sync::OnceCell::const_new();
struct Connection {
    client: Client,
    driver: tokio::task::JoinHandle<Result<(), tokio_postgres::Error>>,
    runtime: bool,
}
impl Drop for Connection {
    fn drop(&mut self) {
        self.driver.abort();
    }
}
impl Connection {
    async fn runtime(&mut self) {
        if !self.runtime {
            *self = connected(true).await;
        }
    }
    async fn admin(&mut self) {
        if self.runtime {
            *self = connected(false).await;
        } else {
            self.client.batch_execute("RESET ROLE").await.unwrap();
        }
    }
}
async fn connect() -> Connection {
    connected(false).await
}
async fn connected(runtime: bool) -> Connection {
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN").expect("canonical dev PostgreSQL required");
    let mut config: tokio_postgres::Config = dsn.parse().unwrap();
    assert_eq!(config.get_dbname(), Some("onlyalpha_dev_validation_test"));
    if runtime {
        config.user(TEST_LOGIN);
    }
    let (client, connection) = config.connect(NoTls).await.unwrap();
    Connection {
        client,
        driver: tokio::spawn(connection),
        runtime,
    }
}
async fn database() -> Connection {
    INITIALIZED.get_or_init(||async {
  let mut c=connect().await;
  // Explicit controlled-test namespace preparation, never a business DB reset.
  c.client.batch_execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public").await.unwrap();
  let root=Path::new("/workspace/database/postgres/migrations");
  let mut sources=std::fs::read_dir(root).unwrap().map(|e|{let p=e.unwrap().path();(p.file_stem().unwrap().to_str().unwrap().to_owned(),std::fs::read(p).unwrap())}).collect::<Vec<_>>();sources.sort_by(|a,b|a.0.cmp(&b.0));
  let history=SchemaHistory::from_sql(sources,16*1024*1024).unwrap();history.migrate(&mut c.client).await.unwrap();
  assert!(history.migrate(&mut c.client).await.unwrap().is_empty());
  c.client.execute("INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(true,$1::text::uuid)",&[&NS]).await.unwrap();
  let exists=c.client.query_opt("SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolinherit,shobj_description(oid,'pg_authid') FROM pg_roles WHERE rolname=$1",&[&TEST_LOGIN]).await.unwrap();
  let config:tokio_postgres::Config=std::env::var("ONLYALPHA_POSTGRES_DSN").unwrap().parse().unwrap();
  let password=std::str::from_utf8(config.get_password().expect("canonical dev password required")).unwrap();
  let quoted:String=c.client.query_one("SELECT quote_literal($1)",&[&password]).await.unwrap().get(0);
  if let Some(row)=exists {assert!(row.get::<_,bool>(0));for i in 1..7 {assert!(!row.get::<_,bool>(i));}assert_eq!(row.get::<_,Option<String>>(7).as_deref(),Some("OnlyAlpha controlled publication test login"));}
  else {c.client.batch_execute(&format!("CREATE ROLE {TEST_LOGIN} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT; COMMENT ON ROLE {TEST_LOGIN} IS 'OnlyAlpha controlled publication test login'")).await.unwrap();}
  c.client.batch_execute(&format!("ALTER ROLE {TEST_LOGIN} PASSWORD {quoted}; GRANT onlyalpha_job_reader,onlyalpha_job_publisher,onlyalpha_factor_builder TO {TEST_LOGIN}")).await.unwrap();
  println!("CONTROLLED_TEST_SCHEMA_READY: onlyalpha_dev_validation_test; unprivileged login verified");
 }).await;
    connect().await
}
async fn seed(c: &Client, kind: JobKind, parts: usize, bytes: usize) -> Fixture {
    let n = SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let run = format!("{:08x}-1111-4111-8111-111111111111", n);
    let attempt = format!("{:08x}-2222-4222-8222-222222222222", n);
    let worker = format!("{:08x}-3333-4333-8333-333333333333", n);
    let f = fixture(kind, (NS, OWNER), &run, &attempt, &worker, parts, bytes);
    let sql = match kind {
        JobKind::Backtest => {
            "INSERT INTO backtest_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,admission_resolution_schema_version,admission_resolution_payload,queued_at,started_at) VALUES($1::text::uuid,1,'RUNNING',1,$2,'{}',$3,1,'{}','2020-01-01','2020-01-01')"
        }
        JobKind::Research => {
            "INSERT INTO research_run(run_id,revision,state,specification_schema_version,specification_fingerprint,specification_payload,admission_resolution_fingerprint,queued_at,started_at) VALUES($1::text::uuid,1,'RUNNING',1,$2,'{}',$3,'2020-01-01','2020-01-01')"
        }
    };
    c.execute(sql, &[&run, &f.specification(), &f.admission()])
        .await
        .unwrap();
    let table = match kind {
        JobKind::Backtest => "backtest_run_attempt",
        JobKind::Research => "research_run_attempt",
    };
    let extra = if kind == JobKind::Backtest {
        ",fencing_token"
    } else {
        ""
    };
    let value = if kind == JobKind::Backtest { ",1" } else { "" };
    c.execute(&format!("INSERT INTO {table}(run_id,attempt_id,worker_instance_id,attempt_number,state,claimed_at,last_heartbeat_at,lease_expires_at{extra}) VALUES($1::text::uuid,$2::text::uuid,$3::text::uuid,1,'ACTIVE',clock_timestamp(),clock_timestamp(),clock_timestamp()+interval '120 seconds'{value})"),&[&run,&attempt,&worker]).await.unwrap();
    f
}
async fn writer(c: &mut Connection) -> PublicationRepository<'_> {
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_publisher")
        .await
        .unwrap();
    PublicationRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap(), OWNER)
        .await
        .unwrap()
}
#[tokio::test]
async fn schema_roles_and_immutable_permissions_are_real() {
    let mut c = database().await;
    let roles=c.client.query("SELECT rolname,rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit FROM pg_roles WHERE rolname IN ('onlyalpha_job_reader','onlyalpha_job_publisher','onlyalpha_factor_builder')",&[]).await.unwrap();
    assert_eq!(roles.len(), 3);
    for row in roles {
        for i in 1..7 {
            assert!(!row.get::<_, bool>(i));
        }
    }
    for role in [
        "onlyalpha_job_reader",
        "onlyalpha_job_publisher",
        "onlyalpha_factor_builder",
    ] {
        for table in [
            "job_frozen_binding",
            "job_result_member",
            "job_publication",
            "factor_built_program",
            "factor_parameter_certificate",
        ] {
            for privilege in ["UPDATE", "DELETE", "TRUNCATE"] {
                let yes: bool = c
                    .client
                    .query_one(
                        "SELECT has_table_privilege($1,$2,$3)",
                        &[&role, &table, &privilege],
                    )
                    .await
                    .unwrap()
                    .get(0);
                assert!(!yes, "{role} {table} {privilege}");
            }
        }
    }
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_reader")
        .await
        .unwrap();
    assert_eq!(c.client.execute("INSERT INTO job_publication(job_kind,run_id) VALUES('BACKTEST','11111111-1111-4111-8111-111111111111')",&[]).await.unwrap_err().code(),Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE));
    assert!(
        PublicationRepository::new(
            &mut c.client,
            &SemanticStoreId::new("88888888-8888-4888-8888-888888888888").unwrap(),
            OWNER
        )
        .await
        .is_err()
    );
}
#[tokio::test]
async fn research_and_backtest_publish_complete_result_and_terminal_state_atomically() {
    let mut c = database().await;
    for kind in [JobKind::Research, JobKind::Backtest] {
        c.admin().await;
        let f = seed(&c.client, kind, 1, 32).await;
        let mut p = writer(&mut c).await;
        p.register(&f.registration).await.unwrap();
        assert!(matches!(
            p.observe(&f.locator()).await.unwrap(),
            PublicationObservation::ConfirmedUnpublished(_)
        ));
        let published = p.publish(&f.claim, &f.candidate).await.unwrap();
        assert!(matches!(published, PublishOutcome::Committed { .. }));
        let id = published.publication().fingerprint().to_owned();
        assert_eq!(p.read(&f.locator()).await.unwrap().fingerprint(), id);
        assert!(matches!(
            p.publish(&f.claim, &f.candidate).await.unwrap(),
            PublishOutcome::AlreadyPublished(_)
        ));
        assert!(matches!(
            p.observe(&f.locator()).await.unwrap(),
            PublicationObservation::Published(_)
        ));
        assert_eq!(
            p.publish(&f.claim, &f.changed_candidate())
                .await
                .unwrap_err(),
            PublicationError::Conflict
        );
        drop(p);
        c.admin().await;
        let table = if kind == JobKind::Research {
            "research_run"
        } else {
            "backtest_run"
        };
        assert_eq!(
            c.client
                .query_one(
                    &format!("SELECT state FROM {table} WHERE run_id=$1::text::uuid"),
                    &[&f.run_id()]
                )
                .await
                .unwrap()
                .get::<_, String>(0),
            "COMPLETED"
        );
    }
}
#[tokio::test]
async fn stale_attempt_wrong_binding_and_cancelled_run_cannot_publish() {
    let mut c = database().await;
    for mode in ["expired", "fence", "cancelled", "binding"] {
        c.admin().await;
        let f = seed(&c.client, JobKind::Backtest, 1, 0).await;
        {
            let mut p = writer(&mut c).await;
            p.register(&f.registration).await.unwrap();
        }
        c.admin().await;
        match mode {
            "expired" => {
                c.client.execute("UPDATE backtest_run_attempt SET lease_expires_at=last_heartbeat_at WHERE run_id=$1::text::uuid",&[&f.run_id()]).await.unwrap();
            }
            "fence" => {
                c.client.execute("UPDATE backtest_run_attempt SET fencing_token=2 WHERE run_id=$1::text::uuid",&[&f.run_id()]).await.unwrap();
            }
            "cancelled" => {
                c.client.execute("UPDATE backtest_run SET state='CANCELLED',revision=revision+1,finished_at='2020-01-02' WHERE run_id=$1::text::uuid",&[&f.run_id()]).await.unwrap();
            }
            _ => {}
        }
        let mut p = writer(&mut c).await;
        let candidate = if mode == "binding" {
            f.wrong_binding_candidate()
        } else {
            f.candidate.clone()
        };
        assert!(p.publish(&f.claim, &candidate).await.is_err(), "{mode}");
        drop(p);
        assert_eq!(
            c.client
                .query_one(
                    "SELECT count(*) FROM job_publication WHERE run_id=$1::text::uuid",
                    &[&f.run_id()]
                )
                .await
                .unwrap()
                .get::<_, i64>(0),
            0
        );
    }
}
#[tokio::test]
async fn mid_publication_failure_rolls_back_every_member_and_the_original_lifecycle() {
    let mut c = database().await;
    let f = seed(&c.client, JobKind::Backtest, 3, 64).await;
    c.client.batch_execute(&format!("CREATE FUNCTION publication_test_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.run_id='{}'::uuid THEN RAISE EXCEPTION 'controlled failure after members'; END IF; RETURN NEW; END $$; CREATE TRIGGER publication_test_fail BEFORE INSERT ON job_publication FOR EACH ROW EXECUTE FUNCTION publication_test_fail()",f.run_id())).await.unwrap();
    let mut p = writer(&mut c).await;
    p.register(&f.registration).await.unwrap();
    assert!(p.publish(&f.claim, &f.candidate).await.is_err());
    drop(p);
    c.client.batch_execute("SELECT 1").await.unwrap();
    c.admin().await;
    c.client.batch_execute("DROP TRIGGER publication_test_fail ON job_publication; DROP FUNCTION publication_test_fail()").await.unwrap();
    assert_eq!(
        c.client
            .query_one(
                "SELECT count(*) FROM job_result_member WHERE run_id=$1::text::uuid",
                &[&f.run_id()]
            )
            .await
            .unwrap()
            .get::<_, i64>(0),
        0
    );
    assert_eq!(
        c.client
            .query_one(
                "SELECT state FROM backtest_run WHERE run_id=$1::text::uuid",
                &[&f.run_id()]
            )
            .await
            .unwrap()
            .get::<_, String>(0),
        "RUNNING"
    );
    let mut p = writer(&mut c).await;
    p.publish(&f.claim, &f.candidate).await.unwrap();
}
#[tokio::test]
async fn direct_partial_members_and_resultless_completion_are_rejected_at_commit() {
    let mut c = database().await;
    let f = seed(&c.client, JobKind::Backtest, 1, 0).await;
    {
        let mut p = writer(&mut c).await;
        p.register(&f.registration).await.unwrap();
    }
    let tx = c.client.transaction().await.unwrap();
    tx.execute("UPDATE backtest_run SET state='COMPLETED',revision=revision+1,finished_at='2020-01-02',evidence_fingerprint=$2,result_fingerprint=$2,determinism_fingerprint=$2 WHERE run_id=$1::text::uuid",&[&f.run_id(),&"a".repeat(64)]).await.unwrap();
    assert!(tx.commit().await.is_err());
    let tx = c.client.transaction().await.unwrap();
    let descriptor=json!({"key":"orphan","kind":"EXECUTION_FACTS","schema":"a".repeat(64),"axis":"b".repeat(64),"rows":0}).to_string();
    let content = "{}";
    let fp = crate::application::factor_content::hash(&json!({})).unwrap();
    tx.execute("INSERT INTO job_result_member(job_kind,run_id,member_key,descriptor,content,content_fingerprint) VALUES('BACKTEST',$1::text::uuid,'orphan',$2,$3,$4)",&[&f.run_id(),&descriptor,&content,&fp]).await.unwrap();
    assert!(tx.commit().await.is_err());
}

#[path = "support/job_publication_proxy.rs"]
mod proxy;
async fn proxy_connection(proxy: &proxy::Proxy) -> Connection {
    let source: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")
        .unwrap()
        .parse()
        .unwrap();
    assert_eq!(source.get_dbname(), Some("onlyalpha_dev_validation_test"));
    assert!(
        matches!(source.get_hosts(),[tokio_postgres::config::Host::Tcp(host)] if host=="postgres")
    );
    assert!(source.get_ports().is_empty() || source.get_ports() == [5432]);
    let mut config = tokio_postgres::Config::new();
    config
        .host("127.0.0.1")
        .port(proxy.port())
        .user(TEST_LOGIN)
        .password(source.get_password().unwrap())
        .dbname(source.get_dbname().unwrap());
    let (client, driver) = config.connect(NoTls).await.unwrap();
    Connection {
        client,
        driver: tokio::spawn(driver),
        runtime: true,
    }
}
#[tokio::test]
async fn real_inflight_commit_is_unresolved_and_partial_content_is_invisible() {
    let admin = database().await;
    let f = seed(&admin.client, JobKind::Backtest, 3, 32).await;
    let mut proxy = proxy::Proxy::start(proxy::Mode::PauseBeforeCommit);
    let mut c = proxy_connection(&proxy).await;
    let mut p = writer(&mut c).await;
    p.register(&f.registration).await.unwrap();
    proxy.arm();
    let publish = p.publish(&f.claim, &f.candidate);
    let check = async {
        proxy.entered().await;
        let mut other = database().await;
        let mut observer = writer(&mut other).await;
        assert!(matches!(
            observer.observe(&f.locator()).await.unwrap(),
            PublicationObservation::Unresolved
        ));
        assert_eq!(
            observer.read(&f.locator()).await.unwrap_err(),
            PublicationError::MissingEvidence
        );
        let count: i64 = admin
            .client
            .query_one(
                "SELECT count(*) FROM job_result_member WHERE run_id=$1::text::uuid",
                &[&f.run_id()],
            )
            .await
            .unwrap()
            .get(0);
        assert_eq!(count, 0);
        proxy.release();
    };
    let (published, _) = tokio::join!(publish, check);
    published.unwrap();
    assert!(matches!(
        p.observe(&f.locator()).await.unwrap(),
        PublicationObservation::Published(_)
    ));
}
#[tokio::test]
async fn server_commit_with_lost_real_response_is_observed_under_original_identity() {
    let admin = database().await;
    let f = seed(&admin.client, JobKind::Backtest, 1, 0).await;
    let mut proxy = proxy::Proxy::start(proxy::Mode::DropCommitReply);
    let mut c = proxy_connection(&proxy).await;
    let mut p = writer(&mut c).await;
    p.register(&f.registration).await.unwrap();
    proxy.arm();
    let (result, _) = tokio::join!(p.publish(&f.claim, &f.candidate), proxy.entered());
    assert_eq!(result.unwrap_err(), PublicationError::OutcomeUnknown);
    let mut observer_connection = database().await;
    let mut observer = writer(&mut observer_connection).await;
    let PublicationObservation::Published(original) = observer.observe(&f.locator()).await.unwrap()
    else {
        panic!("actual committed result must be observed")
    };
    assert_eq!(original.binding().run_id(), f.run_id());
    assert_eq!(
        admin
            .client
            .query_one(
                "SELECT count(*) FROM job_publication WHERE run_id=$1::text::uuid",
                &[&f.run_id()]
            )
            .await
            .unwrap()
            .get::<_, i64>(0),
        1
    );
}
#[tokio::test]
async fn lost_connection_before_commit_cannot_leave_a_half_publication() {
    let admin = database().await;
    let f = seed(&admin.client, JobKind::Backtest, 1, 0).await;
    let mut proxy = proxy::Proxy::start(proxy::Mode::DropBeforeCommit);
    let mut c = proxy_connection(&proxy).await;
    let mut p = writer(&mut c).await;
    p.register(&f.registration).await.unwrap();
    proxy.arm();
    let (result, _) = tokio::join!(p.publish(&f.claim, &f.candidate), proxy.entered());
    assert_eq!(result.unwrap_err(), PublicationError::OutcomeUnknown);
    // Wait on the same real row lock until server rollback has resolved. No sleep/retry.
    admin
        .client
        .query_one(
            "SELECT state FROM backtest_run WHERE run_id=$1::text::uuid FOR UPDATE",
            &[&f.run_id()],
        )
        .await
        .unwrap();
    let mut other = database().await;
    let mut observer = writer(&mut other).await;
    assert!(matches!(
        observer.observe(&f.locator()).await.unwrap(),
        PublicationObservation::ConfirmedUnpublished(_)
    ));
    assert_eq!(
        admin
            .client
            .query_one(
                "SELECT count(*) FROM job_result_member WHERE run_id=$1::text::uuid",
                &[&f.run_id()]
            )
            .await
            .unwrap()
            .get::<_, i64>(0),
        0
    );
}
#[tokio::test]
async fn exact_factor_program_and_parameter_certificates_are_immutable_storage_not_execution_grants()
 {
    use crate::factor_subject::{FactorBuildRepository, fixture as build_fixture};
    let mut c = database().await;
    let revision = "d".repeat(64);
    let source = "storage test source, never executable";
    c.client.execute("INSERT INTO private_factor_asset(factor_id,schema_version) VALUES('private.factor.pg_storage',1) ON CONFLICT DO NOTHING",&[]).await.unwrap();
    let source_sha = crate::subject::digest(source.as_bytes());
    c.client.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,'private.factor.pg_storage',$2,$3,'{}',1) ON CONFLICT DO NOTHING",&[&revision,&source,&source_sha]).await.unwrap();
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let a = build_fixture::publication(&revision, source, 2);
    let b = build_fixture::publication(&revision, source, 3);
    let (program_a, cert_a) = build_fixture::fingerprints(&a);
    let (program_b, cert_b) = build_fixture::fingerprints(&b);
    assert_eq!(program_a, program_b);
    assert_ne!(cert_a, cert_b);
    let mut store = FactorBuildRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap())
        .await
        .unwrap();
    store.put(&a).await.unwrap();
    store.put(&a).await.unwrap();
    store.put(&b).await.unwrap();
    assert_eq!(
        store.read_program(program_a).await.unwrap().fingerprint(),
        program_a
    );
    assert_ne!(
        store.read_certificate(cert_a).await.unwrap().parameters(),
        store.read_certificate(cert_b).await.unwrap().parameters()
    );
    assert_eq!(
        store.read_certificate(&"0".repeat(64)).await.unwrap_err(),
        PublicationError::MissingEvidence
    );
    assert_eq!(
        c.client
            .execute("UPDATE factor_built_program SET payload='{}'", &[])
            .await
            .unwrap_err()
            .code(),
        Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE)
    );
}

#[tokio::test]
async fn publisher_cannot_forge_source_history_but_real_research_updates_are_retained() {
    let mut c = database().await;
    let f = seed(&c.client, JobKind::Research, 1, 0).await;
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_publisher")
        .await
        .unwrap();
    assert_eq!(c.client.execute("INSERT INTO research_source_history(event_index,source_family,native_locator,source_row,operation) VALUES(999999,'RESEARCH_RUN','forged','{}','INSERT')",&[]).await.unwrap_err().code(),Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE));
    assert_eq!(
        c.client
            .query_one(
                "SELECT research_source_record('RESEARCH_RUN','forged','{}','INSERT')",
                &[]
            )
            .await
            .unwrap_err()
            .code(),
        Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE)
    );
    let mut p = writer(&mut c).await;
    p.register(&f.registration).await.unwrap();
    p.publish(&f.claim, &f.candidate).await.unwrap();
    drop(p);
    c.admin().await;
    let events=c.client.query("SELECT source_row->>'state' FROM research_source_history WHERE source_family='RESEARCH_RUN' AND native_locator=$1 ORDER BY event_index",&[&f.run_id()]).await.unwrap();
    assert_eq!(
        events
            .iter()
            .map(|r| r.get::<_, String>(0))
            .collect::<Vec<_>>(),
        ["RUNNING", "COMPLETED"]
    );
}

#[tokio::test]
async fn concurrent_publishers_produce_exactly_one_original_publication() {
    let mut admin = database().await;
    let f = seed(&admin.client, JobKind::Backtest, 2, 32).await;
    {
        let mut p = writer(&mut admin).await;
        p.register(&f.registration).await.unwrap();
    }
    let mut first = database().await;
    let mut second = database().await;
    let mut a = writer(&mut first).await;
    let mut b = writer(&mut second).await;
    let (x, y) = tokio::join!(
        a.publish(&f.claim, &f.candidate),
        b.publish(&f.claim, &f.candidate)
    );
    let x = x.unwrap();
    let y = y.unwrap();
    assert_eq!(x.publication().fingerprint(), y.publication().fingerprint());
    assert_eq!(
        usize::from(matches!(x, PublishOutcome::Committed { .. }))
            + usize::from(matches!(y, PublishOutcome::Committed { .. })),
        1
    );
}
#[tokio::test]
async fn foreign_owner_missing_evidence_and_cancelled_observation_never_grant_recompute() {
    let mut c = database().await;
    let f = seed(&c.client, JobKind::Backtest, 1, 0).await;
    {
        let mut p = writer(&mut c).await;
        assert_eq!(
            p.read(&f.locator()).await.unwrap_err(),
            PublicationError::MissingEvidence
        );
        p.register(&f.registration).await.unwrap();
    }
    let mut foreign = PublicationRepository::new(
        &mut c.client,
        &SemanticStoreId::new(NS).unwrap(),
        "human:other",
    )
    .await
    .unwrap();
    assert_eq!(
        foreign.read(&f.locator()).await.unwrap_err(),
        PublicationError::Mismatch
    );
    assert_eq!(
        foreign.observe(&f.locator()).await.unwrap_err(),
        PublicationError::Mismatch
    );
    drop(foreign);
    c.admin().await;
    c.client.execute("UPDATE backtest_run SET state='CANCELLED',revision=revision+1,finished_at='2020-01-02' WHERE run_id=$1::text::uuid",&[&f.run_id()]).await.unwrap();
    let mut p = writer(&mut c).await;
    let PublicationObservation::ConfirmedUnpublished(o) = p.observe(&f.locator()).await.unwrap()
    else {
        panic!("cancelled has no publication")
    };
    assert_eq!(o.run_state(), "CANCELLED");
    assert_eq!(o.run_revision(), 2);
}
#[tokio::test]
async fn rewritten_content_with_valid_new_digest_cannot_borrow_the_original_manifest() {
    let mut c = database().await;
    let f = seed(&c.client, JobKind::Backtest, 1, 0).await;
    {
        let mut p = writer(&mut c).await;
        p.register(&f.registration).await.unwrap();
        p.publish(&f.claim, &f.candidate).await.unwrap();
    }
    c.admin().await;
    c.client
        .batch_execute("ALTER TABLE job_result_member DISABLE TRIGGER job_result_member_immutable")
        .await
        .unwrap();
    c.client.execute("UPDATE job_result_member SET content='{}',content_fingerprint=encode(sha256(convert_to('{}','UTF8')),'hex') WHERE run_id=$1::text::uuid AND member_key='causal'",&[&f.run_id()]).await.unwrap();
    c.client
        .batch_execute("ALTER TABLE job_result_member ENABLE TRIGGER job_result_member_immutable")
        .await
        .unwrap();
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_reader")
        .await
        .unwrap();
    let mut reader =
        PublicationRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap(), OWNER)
            .await
            .unwrap();
    assert_eq!(
        reader.read(&f.locator()).await.unwrap_err(),
        PublicationError::Integrity
    );
}

#[tokio::test]
async fn runtime_repository_refuses_a_migration_admin_even_after_set_role() {
    let mut c = database().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_publisher")
        .await
        .unwrap();
    assert!(
        matches!(
            PublicationRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap(), OWNER)
                .await,
            Err(PublicationError::Denied)
        ),
        "SET ROLE must not disguise an admin-authenticated worker session"
    );
}

#[tokio::test]
async fn caller_timeouts_cannot_be_widened_through_a_temporary_settings_lookalike() {
    let mut c = database().await;
    c.client.batch_execute("CREATE TEMP TABLE pg_settings(name text,setting text,unit text); INSERT INTO pg_settings VALUES('statement_timeout','0','ms'),('lock_timeout','0','ms'); SET statement_timeout='1000ms'; SET lock_timeout='700ms'").await.unwrap();
    let tx = c.client.transaction().await.unwrap();
    crate::persistence::postgres::bounds(&tx).await.unwrap();
    let actual=tx.query_one("SELECT (SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name='statement_timeout'),(SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name='lock_timeout')",&[]).await.unwrap();
    assert_eq!(
        (actual.get::<_, i64>(0), actual.get::<_, i64>(1)),
        (1000, 700)
    );
    tx.rollback().await.unwrap();
}

#[tokio::test]
async fn real_runtime_login_cannot_reset_role_back_to_the_migration_administrator() {
    let mut c = database().await;
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_publisher; RESET ROLE")
        .await
        .unwrap();
    assert_eq!(
        c.client
            .query_one("SELECT current_user::text", &[])
            .await
            .unwrap()
            .get::<_, String>(0),
        TEST_LOGIN
    );
    assert_eq!(
        c.client
            .batch_execute("SET ROLE onlyalpha")
            .await
            .unwrap_err()
            .code(),
        Some(&tokio_postgres::error::SqlState::INSUFFICIENT_PRIVILEGE)
    );
}

#[tokio::test]
async fn failure_taxonomy_does_not_call_operational_database_errors_corrupt_evidence() {
    let c = database().await;
    for code in ["08006", "57P01", "53300", "42P01"] {
        let error=c.client.batch_execute(&format!("DO $$ BEGIN RAISE EXCEPTION USING ERRCODE='{code}', MESSAGE='controlled operational failure'; END $$")).await.unwrap_err();
        assert_eq!(
            crate::subject::db(error),
            PublicationError::Unavailable,
            "{code}"
        );
    }
}
#[tokio::test]
async fn failure_taxonomy_unreadable_namespace_is_not_a_namespace_mismatch() {
    let admin = database().await;
    let mut c = database().await;
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_reader")
        .await
        .unwrap();
    admin.client.batch_execute("ALTER TABLE research_deployment_semantic_store_binding RENAME TO publication_test_namespace_unavailable").await.unwrap();
    let result =
        PublicationRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap(), OWNER).await;
    let unavailable = matches!(result, Err(PublicationError::Unavailable));
    admin.client.batch_execute("ALTER TABLE publication_test_namespace_unavailable RENAME TO research_deployment_semantic_store_binding").await.unwrap();
    assert!(
        unavailable,
        "namespace read failure must not assert mismatched identity"
    );
}
#[tokio::test]
async fn factor_binding_rejects_wrong_revision_source_and_rolls_back_new_program() {
    use crate::factor_subject::{FactorBuildRepository, fixture as build_fixture};
    let mut c = database().await;
    let revision = "e".repeat(64);
    let source = "original source for precise version binding";
    c.client.execute("INSERT INTO private_factor_asset(factor_id,schema_version) VALUES('private.factor.pg_wrong_source',1)",&[]).await.unwrap();
    let sha = crate::subject::digest(source.as_bytes());
    c.client.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,'private.factor.pg_wrong_source',$2,$3,'{}',1)",&[&revision,&source,&sha]).await.unwrap();
    let invalid = build_fixture::publication(&revision, "different source", 2);
    let (program, _) = build_fixture::fingerprints(&invalid);
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let mut store = FactorBuildRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap())
        .await
        .unwrap();
    assert_eq!(
        store.put(&invalid).await.unwrap_err(),
        PublicationError::Integrity
    );
    assert_eq!(
        store.read_program(program).await.unwrap_err(),
        PublicationError::MissingEvidence
    );
}

#[tokio::test]
async fn caller_asynchronous_commit_cannot_make_a_formal_publication_nondurable() {
    let mut c = database().await;
    let f = seed(&c.client, JobKind::Backtest, 1, 0).await;
    c.client.batch_execute("CREATE TABLE publication_test_durability_seen(value text); CREATE FUNCTION publication_test_durability_probe() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$ BEGIN INSERT INTO public.publication_test_durability_seen VALUES(current_setting('synchronous_commit')); RETURN NEW; END $$; CREATE TRIGGER publication_test_durability_probe BEFORE INSERT ON job_publication FOR EACH ROW EXECUTE FUNCTION publication_test_durability_probe()").await.unwrap();
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_job_publisher; SET synchronous_commit=off")
        .await
        .unwrap();
    let mut p = writer(&mut c).await;
    p.register(&f.registration).await.unwrap();
    p.publish(&f.claim, &f.candidate).await.unwrap();
    drop(p);
    let outside: String = c
        .client
        .query_one("SHOW synchronous_commit", &[])
        .await
        .unwrap()
        .get(0);
    c.admin().await;
    let seen: String = c
        .client
        .query_one("SELECT value FROM publication_test_durability_seen", &[])
        .await
        .unwrap()
        .get(0);
    c.client.batch_execute("DROP TRIGGER publication_test_durability_probe ON job_publication; DROP FUNCTION publication_test_durability_probe(); DROP TABLE publication_test_durability_seen").await.unwrap();
    assert_eq!(
        seen, "on",
        "formal publish must flush WAL before acknowledging"
    );
    assert_eq!(
        outside, "off",
        "transaction-local policy must not rewrite caller defaults"
    );
}
#[tokio::test]
#[ignore = "explicit release-only real PostgreSQL performance matrix"]
async fn postgres_publication_performance_matrix() {
    if cfg!(debug_assertions) {
        panic!("use --release for performance evidence");
    }
    let mut c = database().await;
    let mut samples = Vec::new();
    for (profile, parts, padding) in [("small", 1, 32), ("large", 32, 128 * 1024)] {
        let mut expected = None;
        for sample in 0..4 {
            c.admin().await;
            let f = seed(&c.client, JobKind::Backtest, parts, padding).await;
            let content = f.content_digest();
            if let Some(expected) = &expected {
                assert_eq!(&content, expected);
            } else {
                expected = Some(content.clone());
            }
            let mut p = writer(&mut c).await;
            p.register(&f.registration).await.unwrap();
            let outcome = p.publish(&f.claim, &f.candidate).await.unwrap();
            let PublishOutcome::Committed {
                publication,
                timings,
            } = outcome
            else {
                panic!("fresh sample must commit once")
            };
            assert_eq!(publication.member_count(), parts + 3);
            let start = std::time::Instant::now();
            let read = p.read(&f.locator()).await.unwrap();
            let read_ns = start.elapsed().as_nanos();
            assert_eq!(publication.fingerprint(), read.fingerprint());
            let accounted = timings.lock_wait_ns
                + timings.members_write_ns
                + timings.finalization_ns
                + timings.commit_ns;
            assert!(accounted <= timings.total_ns);
            let peak = std::fs::read_to_string("/proc/self/status")
                .unwrap()
                .lines()
                .find(|l| l.starts_with("VmHWM:"))
                .unwrap()
                .to_owned();
            samples.push(json!({"profile":profile,"sample":sample,"warmup":sample==0,"run_id":f.run_id(),"binding":publication.binding().fingerprint(),"publication":publication.fingerprint(),"benchmark_content_digest_excluding_run_binding":content,"members":parts+3,"payload_bytes":f.payload_bytes(),"descriptor_rows":f.descriptor_rows(),"preparation_ns":f.preparation_ns,"publish":timings,"unattributed_publish_ns":timings.total_ns-accounted,"read_ns":read_ns,"process_peak":peak}));
        }
    }
    let source: Value = serde_json::from_str(
        &std::fs::read_to_string("/workspace/.onlyalpha-dev-source-cut.json").unwrap(),
    )
    .unwrap();
    let version: String = c
        .client
        .query_one("SHOW server_version", &[])
        .await
        .unwrap()
        .get(0);
    let compiler = std::process::Command::new("rustc")
        .arg("--version")
        .output()
        .unwrap();
    assert!(compiler.status.success());
    let output =
        Path::new("/workspace/test-results/strategy-research-framework-pg-publication.json");
    std::fs::write(output,serde_json::to_vec_pretty(&json!({"schema_version":1,"fixture_only":true,"profile":"release","arch":std::env::consts::ARCH,"os":std::env::consts::OS,"compiler":String::from_utf8(compiler.stdout).unwrap().trim(),"postgres":version,"source_operation":source["operation_id"],"source_inputs":source["inputs"],"cache":"application warm; OS/PostgreSQL caches not cleared","peak_limit":"process VmHWM cumulative; PostgreSQL backend peak not measured","workload":"synthetic immutable result payload publication, not Backtest engine throughput","fixture_encoding":"canonical JSON with highly compressible x padding; descriptor_rows are fixture declarations, not real trade events","samples":samples})).unwrap()).unwrap();
    println!("PG_PUBLICATION_BENCHMARK {}", output.display());
}

async fn bounded_build_read(certificate: bool) {
    use crate::factor_subject::FactorBuildRepository;
    use std::time::Duration;
    for (statement_ms, lock_ms, safety_seconds) in [(0, 0, 7), (200, 50, 1)] {
        let mut c = database().await;
        c.runtime().await;
        c.client.batch_execute(&format!("SET ROLE onlyalpha_job_reader; SET statement_timeout={statement_ms}; SET lock_timeout={lock_ms}")).await.unwrap();
        let mut store =
            FactorBuildRepository::new(&mut c.client, &SemanticStoreId::new(NS).unwrap())
                .await
                .unwrap();
        let mut blocker = database().await;
        let hold = blocker.client.transaction().await.unwrap();
        let table = if certificate {
            "factor_parameter_certificate"
        } else {
            "factor_built_program"
        };
        hold.batch_execute(&format!(
            "LOCK TABLE public.{table} IN ACCESS EXCLUSIVE MODE"
        ))
        .await
        .unwrap();
        let result = tokio::time::timeout(Duration::from_secs(safety_seconds), async {
            let missing = "0".repeat(64);
            if certificate {
                store.read_certificate(&missing).await.map(|_| ())
            } else {
                store.read_program(&missing).await.map(|_| ())
            }
        })
        .await;
        // Always resolve the actual blocking transaction before asserting, also on RED.
        hold.rollback().await.unwrap();
        assert!(
            result.is_ok(),
            "owning read must apply the existing DB budget, not hang until the test safety deadline"
        );
        assert_eq!(result.unwrap().unwrap_err(), PublicationError::Unavailable);
        let settings = c
            .client
            .query_one(
                "SELECT setting::bigint FROM pg_catalog.pg_settings WHERE name='lock_timeout'",
                &[],
            )
            .await
            .unwrap();
        assert_eq!(
            settings.get::<_, i64>(0),
            i64::from(lock_ms),
            "local budget must preserve caller defaults"
        );
    }
}
#[tokio::test]
async fn program_reads_bound_real_table_locks_and_keep_smaller_caller_budgets() {
    bounded_build_read(false).await;
}
#[tokio::test]
async fn certificate_reads_bound_real_table_locks_and_keep_smaller_caller_budgets() {
    bounded_build_read(true).await;
}
