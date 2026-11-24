//! Actual scheduler over an already admitted original Run. The caller supplies
//! locators only; this fixture neither creates a Work nor asserts Host READY.
use super::*;
use crate::{
    application::source_access::{Authority, Grant, Permission},
    persistence::job_publication::{PublicationRepository, RunLocator},
};
use serde_json::{Value, json};

pub(crate) async fn run(v: &Value) -> Result<Value, Box<dyn std::error::Error>> {
    let root = PathBuf::from(v["research_root"].as_str().ok_or("research root")?);
    let namespace = crate::bootstrap::deployment::load_semantic_store_id(
        &root.join(".onlyalpha-semantic-store.json"),
    )?;
    let (mut metadata, mut writer) =
        crate::bootstrap::workstation_startup::test_research_owner(&namespace).await?;
    let mut facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&metadata).await?;
    let run = research_submission::load(
        metadata.client_mut().await?,
        facts.client_mut().await?,
        &namespace,
        v["run_id"].as_str().ok_or("original run")?,
        None,
    )
    .await?;
    let id = run.run_id().to_owned();
    let owner = run.owner().to_owned();
    let mode = v["mode"].as_str().unwrap_or("complete").to_owned();
    assert!(matches!(
        mode.as_str(),
        "complete"
            | "cancel-preparing"
            | "cancel-child"
            | "cancel-finished"
            | "cancel-after-complete"
            | "recompute"
    ));
    let executions = if mode == "recompute" { 2 } else { 1 };
    let hook = Arc::new(Hook::new(id.clone(), mode.clone()));
    assert!(HOOK.lock().unwrap().replace(hook.clone()).is_none());
    let selection = run.source_selection().clone();
    let issuer = Authority::new(
        &owner,
        "add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",
        vec![Grant::new(selection, vec![Permission::ClosedHistory])?],
    )?;
    let session = issuer.authenticate(&format!("Bearer {}", "e".repeat(64)))?;
    let lookups = Arc::new(std::sync::atomic::AtomicUsize::new(0));
    let queried = lookups.clone();
    let sources = SourceSessions::new(move |_, _| {
        queried.fetch_add(1, Ordering::SeqCst);
        let session = session.clone();
        async move { Ok(session) }
    });
    let database = v["database"].as_str().ok_or("CH database")?;
    if !database.starts_with("onlyalpha_test_") {
        return Err("canonical CH namespace required".into());
    }
    let physical = Arc::new(crate::persistence::market_data::ClickHouse::new(
        crate::persistence::market_data::ClickHouseConfig {
            url: v["url"].as_str().ok_or("CH URL")?.into(),
            database: database.into(),
            user: std::env::var("ONLYALPHA_CLICKHOUSE_USER")?,
            password: std::env::var("ONLYALPHA_CLICKHOUSE_PASSWORD")?,
            timeout: Duration::from_secs(5),
            tls_roots_pem: vec![],
            max_bytes: 64 * 1024 * 1024,
            max_rows: 10_000,
        },
    )?);
    let config = Configuration {
        runtime_root: PathBuf::from(v["runtime_root"].as_str().ok_or("runtime root")?),
        algorithms: PathBuf::from(v["algorithm_root"].as_str().ok_or("algorithms")?),
    };
    let at: OnlyUtcDateTime = v["at"].as_str().ok_or("at")?.parse()?;
    let mut service = Service::start(
        metadata,
        facts,
        writer.clone(),
        sources.clone(),
        physical.clone(),
        config.clone(),
        move || Ok(at),
    )
    .map_err(PreparationError::from)?;
    let mut changed = service.status.clone();
    let outcome = tokio::time::timeout(Duration::from_secs(20), async {
        if mode == "recompute" {
            // The real candidate exists and its task/children are already joined.
            hook.entered().await;
            expire_candidate_lease(&id).await?;
            hook.release();
            loop {
                match changed.borrow_and_update().clone() {
                    Status::Unavailable("RESEARCH_PUBLICATION_OWNERSHIP_LOST") => break,
                    Status::Unavailable(code) | Status::Uncertain(code) => return Err(code),
                    Status::Idle => return Err("OLD_WORKER_PUBLISHED_AFTER_EXPIRY"),
                    _ => {}
                }
                changed
                    .changed()
                    .await
                    .map_err(|_| "RESEARCH_WORKER_OBSERVER_CLOSED")?;
            }
            service.drain().await?;
            if let Some(original) = writer.lock().await.take() {
                original
                    .close()
                    .await
                    .map_err(|_| "TEST_ORIGINAL_AS_CLOSE_UNKNOWN")?;
            }
            // Only after the original task, readers and AS positively close may
            // a cold owner observe this same Run and acquire its second Attempt.
            let (metadata, reopened) =
                crate::bootstrap::workstation_startup::test_research_owner(&namespace)
                    .await
                    .map_err(|_| "TEST_COLD_OWNER_UNAVAILABLE")?;
            let facts = crate::bootstrap::workstation_startup::test_job_fact_reader(&metadata)
                .await
                .map_err(|_| "TEST_COLD_READER_UNAVAILABLE")?;
            writer = reopened;
            service = Service::start(
                metadata,
                facts,
                writer.clone(),
                sources.clone(),
                physical.clone(),
                config.clone(),
                move || Ok(at),
            )?;
            changed = service.status.clone();
        }
        if matches!(
            mode.as_str(),
            "cancel-preparing" | "cancel-child" | "cancel-finished"
        ) {
            hook.entered().await;
            {
                let mut original = writer.lock().await;
                let authority = original.as_mut().ok_or("RESEARCH_WRITER_LOST")?;
                let client = authority
                    .client_mut()
                    .await
                    .map_err(|_| "RESEARCH_WRITER_LOST")?;
                crate::persistence::research_execution::ResearchExecution::new(client)
                    .request_cancel(&run, at)
                    .await?;
            }
            if mode == "cancel-finished" {
                hook.release();
            }
            if mode == "cancel-child" {
                hook.reaped().await;
                assert_eq!(
                    hook.child.lock().unwrap().as_ref().unwrap().state(),
                    ProcessState::Joined
                );
                hook.release();
            }
        }
        let mut running = matches!(
            mode.as_str(),
            "cancel-preparing" | "cancel-child" | "cancel-finished"
        );
        loop {
            match changed.borrow_and_update().clone() {
                Status::Running(current) if current == id => running = true,
                Status::Idle if running => return Ok::<_, &'static str>(()),
                Status::Uncertain(code) | Status::Unavailable(code) => return Err(code),
                Status::Stopped => return Err("RESEARCH_WORKER_STOPPED_BEFORE_COMPLETION"),
                _ => {}
            }
            changed
                .changed()
                .await
                .map_err(|_| "RESEARCH_WORKER_OBSERVER_CLOSED")?;
        }
    })
    .await;
    // The original service owner survives the observation future, including
    // timeout/failure. Stop and join it before reporting the actual outcome.
    hook.release();
    let drained = service.drain().await;
    let verification=async {
        outcome.map_err(|_|"RESEARCH_WORKER_OBSERVATION_TIMEOUT")??;
        drained?;
        assert_eq!(lookups.load(Ordering::SeqCst),executions*usize::from(mode!="cancel-preparing"),"one current Source lookup per actual Attempt");
        let mut original=writer.lock().await;
        let authority=original.as_mut().ok_or("RESEARCH_WRITER_LOST")?;
        authority.verify().await?;
        if matches!(mode.as_str(),"cancel-preparing"|"cancel-child"|"cancel-finished") {
            let row=authority.client_mut().await?.query_one("SELECT state, research_result_fingerprint IS NULL AND artifact_content_fingerprint IS NULL AND cardinality(calculation_execution_evidence_fingerprints)=0 FROM public.research_run WHERE run_id=$1::text::uuid",&[&id]).await?;
            assert_eq!(row.get::<_,String>(0),"CANCELLED");assert!(row.get::<_,bool>(1));
            assert_eq!(hook.started.load(Ordering::Acquire),usize::from(mode!="cancel-preparing"));
            let absent=crate::persistence::job_publication::with_job_role(authority,crate::persistence::job_publication::JobRole::Reader,async |client| {
                client.query_one("SELECT NOT EXISTS(SELECT 1 FROM public.job_publication WHERE job_kind='RESEARCH' AND run_id=$1::text::uuid),NOT EXISTS(SELECT 1 FROM public.job_result_member WHERE job_kind='RESEARCH' AND run_id=$1::text::uuid)",&[&id]).await.map_err(crate::persistence::job_publication::db)
            }).await?;
            assert!(absent.get::<_,bool>(0) && absent.get::<_,bool>(1));
            return Ok(json!({"state":"CANCELLED","run_id":id,"members":0}));
        }
        if mode=="cancel-after-complete" {
            let rejected=crate::persistence::research_execution::ResearchExecution::new(authority.client_mut().await?).request_cancel(&run,at).await;
            assert_eq!(rejected.unwrap_err(),"RESEARCH_CANCEL_CONFLICT");
        }
        let reader=crate::persistence::job_publication::with_job_role(authority,crate::persistence::job_publication::JobRole::Reader,async |client| {
            PublicationRepository::new(client,&namespace,&owner).await?.read(&RunLocator::new(crate::application::job_contract::JobKind::Research,&id)?).await
        }).await?;
        assert_eq!(reader.member_count(),5);
        if mode=="recompute" {
            assert_eq!(hook.candidate.lock().unwrap().as_deref(),Some(reader.fingerprint()),"recomputing the same Run must preserve all canonical result content");
            let attempts=authority.client_mut().await?.query("SELECT state,attempt_number FROM public.research_run_attempt WHERE run_id=$1::text::uuid ORDER BY attempt_number",&[&id]).await?;
            assert_eq!(attempts.iter().map(|row|(row.get::<_,String>(0),row.get::<_,i32>(1))).collect::<Vec<_>>(),vec![("EXPIRED".into(),1),("SUCCEEDED".into(),2)]);
        }
        let first=crate::transport::job_publication::research_report(&run,&reader)?;
        let second=crate::transport::job_publication::research_report(&run,&reader)?;
        assert_eq!(serde_json::to_value(&first)?,serde_json::to_value(&second)?);
        // 报告的科学结果身份是成员正文重算并与 Run 列核对后的取值（读取方不信任写入方），
        // 与发布（artifact）身份分属两个身份域：等 Run 科学列、不等于发布指纹（§4.1/§4.5）。
        assert_eq!(first.research_result_fingerprint,reader.research_result_column().unwrap());
        assert_ne!(first.research_result_fingerprint,reader.fingerprint());
        assert_eq!(first.observation_count,run.strategy_specification()?.record()["input_window"]["observation_capacity"].as_u64().unwrap());
        assert_eq!(hook.started.load(Ordering::Acquire),executions);
        let reading=std::time::Instant::now();
        crate::persistence::job_publication::with_job_role(authority,crate::persistence::job_publication::JobRole::Reader,async |client| {
            for _ in 0..2 {
                let report=crate::transport::job_publication::read_research_report(client,&namespace,&run).await?;
                assert_eq!(serde_json::to_value(report).unwrap(),serde_json::to_value(&first).unwrap());
            }
            Ok(())
        }).await?;
        let reading_ns=reading.elapsed().as_nanos();
        crate::persistence::job_publication::with_job_role(authority,crate::persistence::job_publication::JobRole::Reader,async |client| {
            let proof=crate::persistence::research_evidence::read_published_strategy(client,&namespace,&run).await?;
            assert_eq!(proof.run().run_id(),run.run_id());
            assert_eq!(proof.source().fingerprint(),reader.binding().record()["strategy_revision"].as_str().unwrap());
            assert_eq!(proof.publication().fingerprint(),reader.fingerprint());
            assert_eq!(proof.build_certification(),&run.prepared_inputs["build_certification"]);
            let wrong=crate::bootstrap::deployment::SemanticStoreId::new("22222222-2222-4222-8222-222222222222").unwrap();
            assert_ne!(wrong,namespace);
            assert!(matches!(crate::persistence::research_evidence::read_published_strategy(client,&wrong,&run).await,Err(crate::persistence::job_publication::PublicationError::Mismatch)));
            Ok(())
        }).await?;
        assert_eq!(hook.started.load(Ordering::Acquire),executions,"reading complete results cannot execute again");
        assert_eq!(lookups.load(Ordering::SeqCst),executions,"reading complete results cannot reacquire Source");
        Ok::<_,Box<dyn std::error::Error>>(json!({"state":"COMPLETED","run_id":id,"publication":reader.fingerprint(),"members":reader.member_count(),"report_reads":2,"report_read_ns":reading_ns,"execution_count":executions}))
    }.await;
    if let Some(original) = writer.lock().await.take() {
        original.close().await?;
    }
    issuer.withdraw();
    HOOK.lock().unwrap().take();
    verification
}

use onlyalpha_calculation_bridge::{Cancellation, ProcessState};
use std::sync::{
    Condvar, Mutex,
    atomic::{AtomicBool, AtomicUsize, Ordering},
};
static HOOK: Mutex<Option<Arc<Hook>>> = Mutex::new(None);
struct Hook {
    run: String,
    mode: String,
    entered: AtomicBool,
    entry: Notify,
    reaped: AtomicBool,
    reap: Notify,
    released: AtomicBool,
    release: Notify,
    gate: (Mutex<bool>, Condvar),
    started: AtomicUsize,
    child: Mutex<Option<Cancellation>>,
    candidate: Mutex<Option<String>>,
}
impl Hook {
    fn new(run: String, mode: String) -> Self {
        Self {
            run,
            mode,
            entered: AtomicBool::new(false),
            entry: Notify::new(),
            reaped: AtomicBool::new(false),
            reap: Notify::new(),
            released: AtomicBool::new(false),
            release: Notify::new(),
            gate: (Mutex::new(false), Condvar::new()),
            started: AtomicUsize::new(0),
            child: Mutex::new(None),
            candidate: Mutex::new(None),
        }
    }
    fn release(&self) {
        self.released.store(true, Ordering::Release);
        self.release.notify_one();
        *self.gate.0.lock().unwrap() = true;
        self.gate.1.notify_all();
    }
    async fn entered(&self) {
        while !self.entered.load(Ordering::Acquire) {
            self.entry.notified().await;
        }
    }
    async fn reaped(&self) {
        while !self.reaped.load(Ordering::Acquire) {
            self.reap.notified().await;
        }
    }
}
fn current(run: &str) -> Option<Arc<Hook>> {
    HOOK.lock()
        .unwrap()
        .as_ref()
        .filter(|hook| hook.run == run)
        .cloned()
}
pub(crate) async fn preparation_gate(run: &str) {
    let Some(hook) = current(run).filter(|hook| hook.mode == "cancel-preparing") else {
        return;
    };
    hook.entered.store(true, Ordering::Release);
    hook.entry.notify_one();
    while !hook.released.load(Ordering::Acquire) {
        hook.release.notified().await;
    }
}
pub(crate) fn execution_started(run: &str) {
    if let Some(hook) = current(run) {
        hook.started.fetch_add(1, Ordering::Release);
    }
}
pub(crate) fn child_gate(run: &str, child: Cancellation) {
    let Some(hook) = current(run).filter(|hook| hook.mode == "cancel-child") else {
        return;
    };
    assert_eq!(child.state(), ProcessState::Running);
    *hook.child.lock().unwrap() = Some(child);
    hook.entered.store(true, Ordering::Release);
    hook.entry.notify_one();
    let mut released = hook.gate.0.lock().unwrap();
    while !*released {
        released = hook.gate.1.wait(released).unwrap();
    }
}
pub(crate) fn reaper_finished(run: &str, success: bool) {
    if let Some(hook) = current(run).filter(|hook| hook.mode == "cancel-child") {
        if success {
            hook.reaped.store(true, Ordering::Release);
            hook.reap.notify_one();
        }
    }
}

pub(crate) async fn finished_gate(run: &str) {
    let Some(hook) = current(run).filter(|hook| hook.mode == "cancel-finished") else {
        return;
    };
    hook.entered.store(true, Ordering::Release);
    hook.entry.notify_one();
    while !hook.released.load(Ordering::Acquire) {
        hook.release.notified().await;
    }
}

/// Controlled valid lease expiry only; never a Run/result/Claim constructor.
async fn expire_candidate_lease(run: &str) -> Result<(), &'static str> {
    let mut configuration: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")
        .map_err(|_| "TEST_OPERATOR_DSN_MISSING")?
        .parse()
        .map_err(|_| "TEST_OPERATOR_DSN_INVALID")?;
    if !configuration
        .get_dbname()
        .is_some_and(|name| name.ends_with("_test"))
    {
        return Err("TEST_DATABASE_REQUIRED");
    }
    configuration.options("-c statement_timeout=5000 -c lock_timeout=2000");
    let (client, connection) = configuration
        .connect(tokio_postgres::NoTls)
        .await
        .map_err(|_| "TEST_OPERATOR_UNAVAILABLE")?;
    let driver = tokio::spawn(connection);
    let result=async {
        let changed=client.execute("UPDATE public.research_run_attempt SET claimed_at=clock_timestamp()-interval '3 seconds',last_heartbeat_at=clock_timestamp()-interval '2 seconds',lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=$1::text::uuid AND state='ACTIVE' AND attempt_number=1",&[&run]).await.map_err(|_|"TEST_LEASE_EXPIRY_FAILED")?;
        if changed!=1 {return Err("TEST_ORIGINAL_ATTEMPT_REQUIRED");}
        let row=client.query_one("SELECT NOT EXISTS(SELECT 1 FROM public.job_publication WHERE job_kind='RESEARCH' AND run_id=$1::text::uuid),NOT EXISTS(SELECT 1 FROM public.job_result_member WHERE job_kind='RESEARCH' AND run_id=$1::text::uuid)",&[&run]).await.map_err(|_|"TEST_PUBLICATION_OBSERVATION_FAILED")?;
        if !row.get::<_,bool>(0) || !row.get::<_,bool>(1) {return Err("TEST_CANDIDATE_ALREADY_PUBLISHED");}
        Ok(())
    }.await;
    drop(client);
    let closed = driver
        .await
        .map_err(|_| "TEST_OPERATOR_JOIN_UNKNOWN")?
        .map_err(|_| "TEST_OPERATOR_CLOSE_UNKNOWN");
    closed?;
    result
}
pub(crate) async fn candidate_gate(run: &str, fingerprint: &str) {
    let Some(hook) = current(run).filter(|hook| hook.mode == "recompute") else {
        return;
    };
    {
        let mut candidate = hook.candidate.lock().unwrap();
        if candidate.is_some() {
            return;
        }
        *candidate = Some(fingerprint.into());
    }
    hook.entered.store(true, Ordering::Release);
    hook.entry.notify_one();
    while !hook.released.load(Ordering::Acquire) {
        hook.release.notified().await;
    }
}
