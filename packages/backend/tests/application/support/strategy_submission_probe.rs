//! Actual Strategy submission/Attempt owners; technical tests, never a Product route.
use onlyalpha_backend::{
    application::{
        command::CommandId,
        factor_content::hash,
        research_admission::PreparedInputs,
        source_access::{Authority as Source, Grant, Permission, Reference, Selection},
        strategy_research::RunSpecification,
    },
    persistence::{
        authority_session::AuthoritySession,
        research_dataset::Store as Datasets,
        research_execution::{ResearchExecution, RunState},
        research_novelty::Authority as Novelty,
        research_submission::{self, Context, SubmissionOutcome, strategy},
    },
    security::human_access::{Access, Admission, Session},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::Path};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
pub(crate) struct AccessFixture {
    human: Access,
    human_session: Session,
    source: Source,
    source_session: onlyalpha_backend::application::source_access::Session,
    selection: Selection,
}
impl AccessFixture {
    pub(crate) fn new(v: &Value) -> Result<Self> {
        let human = Access::new(&"a".repeat(64))?;
        let request = http::Request::builder()
            .uri("/api/v2/integration-types")
            .header("host", "127.0.0.1:5173")
            .header(
                "cookie",
                format!("onlyalpha_dev_session={}", "a".repeat(64)),
            )
            .body(())?;
        let Admission::Owner(human_session) = human.admit(&request)? else {
            return Err("human session".into());
        };
        let reference = Reference::new(
            "fixture.integration",
            v["scope"]["bar_construction"]["plan"]["integration_revision_fingerprint"]
                .as_str()
                .ok_or("source revision")?,
            Some("fixture.sealed-source.v1"),
        )?;
        let selection = Selection::new(
            reference,
            v["scope"]["source_id"].as_str().ok_or("source")?,
            "TEST",
        )?;
        let token = "b".repeat(64);
        let digest = Sha256::digest(token.as_bytes())
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let source = Source::new(
            "local-developer",
            &digest,
            vec![Grant::new(
                selection.clone(),
                vec![Permission::ClosedHistory],
            )?],
        )?;
        let source_session = source.authenticate(&format!("Bearer {token}"))?;
        Ok(Self {
            human,
            human_session,
            source,
            source_session,
            selection,
        })
    }
    pub(crate) fn context(&self) -> Context<'_> {
        Context {
            human_authority: &self.human,
            human: &self.human_session,
            source_authority: &self.source,
            source: &self.source_session,
            selection: &self.selection,
        }
    }
}
pub async fn submit(
    session: &mut AuthoritySession,
    v: &Value,
    inputs: PreparedInputs,
    spec: RunSpecification,
    datasets: &Datasets,
) -> Result<Value> {
    let writer_pid: i32 = session
        .client_mut()
        .await?
        .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
        .await?
        .get(0);
    let access = AccessFixture::new(v)?;
    let context = access.context();
    let command = CommandId::new(v["research_command"].as_str().ok_or("command")?)?;
    let id = research_submission::run_id(&command);
    let roots: BTreeMap<String, std::path::PathBuf> =
        serde_json::from_value(v["source_roots"].clone())?;
    if v["initialize_evidence"] == true {
        onlyalpha_backend::persistence::research_evidence::initialize_fresh_owners(Path::new(
            v["research_root"].as_str().ok_or("research root")?,
        ))?;
    }
    let novelty = Novelty::new(
        Path::new(v["semantic_root"].as_str().ok_or("semantic")?),
        Path::new(v["projection_root"].as_str().ok_or("projection")?),
        roots,
    )?;
    let mut detached = spec.record().clone();
    detached["runtime_generation_fingerprint"] = json!("f".repeat(64));
    let detached = RunSpecification::from_record(&detached)?;
    let detached = strategy::Request::new(
        detached,
        None,
        v["policy_id"].as_str().unwrap_or("native"),
        "1",
    )?;
    assert!(matches!(
        strategy::prepare_study(
            session,
            &novelty,
            &context,
            command.clone(),
            detached,
            &inputs,
            datasets
        )
        .await,
        Err("RESEARCH_SUBMISSION_INVALID")
    ));
    assert!(
        session.verify().await.is_ok(),
        "parsed RunSpec values do not grant inputs; a known refusal preserves writer"
    );
    let request = strategy::Request::new(
        spec.clone(),
        None,
        v["policy_id"].as_str().unwrap_or("native"),
        "1",
    )?;
    let (study, actionable) = strategy::prepare_study(
        session,
        &novelty,
        &context,
        command.clone(),
        request,
        &inputs,
        datasets,
    )
    .await?
    .into_parts();
    assert!(actionable);
    let document = study.record()?;
    let fingerprint = study.fingerprint()?;
    let study = strategy::restore_study(&context, &document, &fingerprint)?;
    assert!(matches!(
        strategy::submission_outcome(session, &context, &study).await?,
        SubmissionOutcome::NotSubmitted
    ));
    let mode = v["submission_mode"].as_str().ok_or("mode")?;
    let at = v["at"].as_str().ok_or("time")?.parse()?;
    if mode == "source-denied" {
        access.source.withdraw();
        assert!(matches!(
            strategy::submit(
                session,
                &novelty,
                &context,
                (&study, &fingerprint),
                &inputs,
                datasets,
                at
            )
            .await,
            Err("RESEARCH_SOURCE_ACCESS_DENIED")
        ));
        assert!(
            session.verify().await.is_ok(),
            "known validation must preserve physical writer"
        );
        return Ok(
            json!({"state":"DENIED","writer_valid":true,"run_id":id,"backend_pid":writer_pid}),
        );
    }
    if mode == "physical-loss" {
        session
            .client_mut()
            .await?
            .simple_query("SELECT pg_catalog.pg_advisory_unlock_all()")
            .await?;
        assert!(
            strategy::submit(
                session,
                &novelty,
                &context,
                (&study, &fingerprint),
                &inputs,
                datasets,
                at
            )
            .await
            .is_err()
        );
        assert!(
            session.verify().await.is_err(),
            "lost physical authority must remain lost"
        );
        return Ok(
            json!({"state":"PHYSICAL_LOSS","writer_valid":false,"run_id":id,"backend_pid":writer_pid}),
        );
    }
    if mode == "cancel-await" {
        {
            let pending = strategy::submit(
                session,
                &novelty,
                &context,
                (&study, &fingerprint),
                &inputs,
                datasets,
                at,
            );
            tokio::pin!(pending);
            tokio::select! {biased; _=&mut pending=>panic!("submit must reach a real database await"),_=std::future::ready(())=>{}}
        }
        assert!(
            session.verify().await.is_err(),
            "cancelled owning future must invalidate physical writer"
        );
        return Ok(
            json!({"state":"CANCELLED_AT_AWAIT","writer_valid":false,"run_id":id,"backend_pid":writer_pid}),
        );
    }
    if mode == "sql-error" {
        session.client_mut().await?.batch_execute("CREATE FUNCTION use_test_strategy_fail() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'CONTROLLED_STRATEGY_AUTH_FAILURE'; END $$; CREATE TRIGGER use_test_strategy_fail BEFORE INSERT ON research_strategy_study_authorization FOR EACH ROW EXECUTE FUNCTION use_test_strategy_fail()").await?;
        assert!(
            strategy::submit(
                session,
                &novelty,
                &context,
                (&study, &fingerprint),
                &inputs,
                datasets,
                at
            )
            .await
            .is_err()
        );
        assert!(
            session.verify().await.is_err(),
            "unexpected database failure must invalidate physical writer"
        );
        return Ok(
            json!({"state":"SQL_ERROR","writer_valid":false,"run_id":id,"backend_pid":writer_pid}),
        );
    }
    if mode == "commit-no-reply" {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let path = Path::new(v["review_file"].as_str().ok_or("review file")?);
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(path)?;
        file.write_all(
            serde_json::to_string(
                &json!({"study":document,"study_fingerprint":fingerprint,"backend_pid":writer_pid}),
            )?
            .as_bytes(),
        )?;
        file.sync_all()?;
    }
    let run = strategy::submit(
        session,
        &novelty,
        &context,
        (&study, &fingerprint),
        &inputs,
        datasets,
        at,
    )
    .await?;
    if mode == "commit-no-reply" {
        std::process::exit(86);
    }
    assert_eq!(run.run_id(), id);
    assert_eq!(run.source_selection(), context.selection);
    assert_eq!(run.owner(), context.source.subject_id()?);
    assert_eq!(run.specification_fingerprint(), spec.fingerprint()?);
    assert_eq!(
        run.specification().scientific_specification_fingerprint()?,
        spec.scientific_specification_fingerprint()?
    );
    assert!(run.factor_specification().is_err());
    let original_runtime =
        onlyalpha_backend::persistence::research_runtime::RuntimeInputHold::open(
            Path::new(v["runtime_root"].as_str().ok_or("runtime")?),
            &id,
            "research",
            run.runtime_generation_fingerprint()?,
        )?;
    let original_installation = onlyalpha_calculation_bridge::ChartInstallation::open(
        Path::new(v["algorithm_root"].as_str().ok_or("algorithms")?),
        v["algorithm_artifact"].as_str().ok_or("artifact")?,
    )?;
    let mut facts = crate::job_fact_connection::Connection::reader().await?;
    let namespace: String = session.client_mut().await?.query_one("SELECT semantic_store_id::text FROM public.research_deployment_semantic_store_binding WHERE singleton",&[]).await?.get(0);
    let namespace = onlyalpha_backend::bootstrap::deployment::SemanticStoreId::new(&namespace)?;
    let frozen = onlyalpha_backend::persistence::job_publication::PublicationRepository::new(&mut facts.client,&namespace,run.owner()).await?
        .frozen_binding(&onlyalpha_backend::persistence::job_publication::RunLocator::new(onlyalpha_backend::application::job_contract::JobKind::Research,run.run_id())?).await?;
    assert_eq!(frozen.run_id(),run.run_id());
    assert_eq!(frozen.owner(),run.owner());
    assert_eq!(frozen.market().record()["dataset_snapshot"],spec.record()["scientific_specification"]["dataset_snapshot_fingerprint"]);
    let restored = onlyalpha_backend::application::research_admission::restore_strategy(
        &mut onlyalpha_backend::persistence::strategy_research::Composer::new(
            session.client_mut().await?,
        ).with_fact_reader(&mut facts.client),
        &run,
        original_runtime,
        &original_installation,
        datasets,
    )
    .await?;
    assert_eq!(
        restored.record(),
        inputs.record(),
        "restart re-reads the original composition and actual installed producer"
    );

    // Losing current source and executable bytes after acceptance cannot create
    // a replacement Run or hide the original committed Command.
    if !mode.starts_with("finite-") { access.source.withdraw(); }
    let alternate = Selection::new(context.selection.reference().clone(), context.selection.source_id(), "OTHER")?;
    let replay_context = Context { selection: &alternate, ..access.context() };
    let replay = strategy::submit(
        session, &novelty, &replay_context, (&study, &fingerprint), &inputs, datasets, at,
    ).await?;
    assert_eq!(replay.run_id(), id);
    assert_eq!(replay.owner(), run.owner());
    assert_eq!(replay.source_selection(), run.source_selection(), "accepted replay must retain the original selection even after withdrawal");
    let mut changed = document.clone();
    changed["request"]["policy_version"] = json!("2");
    let changed_pin = hash(&changed)?;
    let changed = strategy::restore_study(&context, &changed, &changed_pin)?;
    assert!(matches!(
        strategy::submit(
            session,
            &novelty,
            &context,
            (&changed, &changed_pin),
            &inputs,
            datasets,
            at
        )
        .await,
        Err("RESEARCH_COMMAND_CONFLICT")
    ));
    assert!(
        session.verify().await.is_ok(),
        "known conflict must preserve physical writer"
    );
    let candidates =
        research_submission::pending_native_run_ids(session.client_mut().await?).await?;
    assert!(
        candidates.contains(&id),
        "the real worker selector must include exact PRIVATE_STRATEGY5"
    );
    let privileges = session.client_mut().await?.query_one("SELECT current_user=session_user,pg_backend_pid(),pg_catalog.has_column_privilege(current_user,'public.research_run','research_result_fingerprint','UPDATE'),pg_catalog.has_column_privilege(current_user,'public.research_run','artifact_content_fingerprint','UPDATE'),pg_catalog.has_column_privilege(current_user,'public.research_run','calculation_execution_evidence_fingerprints','UPDATE')",&[]).await?;
    assert!(privileges.get::<_,bool>(0));
    assert_eq!(privileges.get::<_,i32>(1), writer_pid);
    for column in 2..5 { assert!(!privileges.get::<_,bool>(column), "control must not acquire result privileges"); }
    assert_eq!(ResearchExecution::new(session.client_mut().await?).observe(&run).await?.state, RunState::Queued);
    if mode == "finite-service" {
        return Ok(json!({"state":"QUEUED","run_id":id,"backend_pid":writer_pid,"study":document,"study_fingerprint":fingerprint}));
    }
    let mut claim = ResearchExecution::claim_recompute(
            session, &namespace, &run,
            "00000000-0000-4000-8000-000000000921",
            "00000000-0000-4000-8000-000000000922",
            at,
        )
        .await?
        .ok_or("claim")?;
    assert!(
        ResearchExecution::claim_recompute(
                session, &namespace, &run,
                "00000000-0000-4000-8000-000000000923",
                "00000000-0000-4000-8000-000000000924",
                at
            )
            .await?
            .is_none()
    );
    if mode == "finite-orphan" {
        return Ok(json!({"state":"RUNNING","run_id":id,"backend_pid":writer_pid}));
    }
    if mode == "heartbeat-guard-loss" {
        let before=facts.client.query_one("SELECT last_heartbeat_at::text,lease_expires_at::text FROM research_run_attempt WHERE attempt_id=$1::text::uuid",&[&claim.attempt_id()]).await?;
        assert!(ResearchExecution::heartbeat_guarded(session,&mut claim).await.is_err());
        assert!(!claim.ownership_certain(),"a failed guard acknowledgement cannot retain claim certainty");
        assert!(session.client_mut().await.is_err(),"the original lost guard socket must be revoked");
        let after=facts.client.query_one("SELECT last_heartbeat_at::text,lease_expires_at::text FROM research_run_attempt WHERE attempt_id=$1::text::uuid",&[&claim.attempt_id()]).await?;
        assert_eq!(before.get::<_,String>(0),after.get::<_,String>(0),"deferred guard loss must roll back heartbeat");
        assert_eq!(before.get::<_,String>(1),after.get::<_,String>(1),"deferred guard loss must roll back lease extension");
        return Ok(json!({"refused":true,"run_id":id,"backend_pid":writer_pid}));
    }
    ResearchExecution::heartbeat_guarded(session, &mut claim).await?;
    assert!(claim.ownership_certain());
    session.verify().await?;
    if matches!(mode,"finite-complete"|"finite-rebound"|"finite-drain") {
        let publication=complete_finite(session,&mut facts.client,FiniteCase {
            values:v,access:&access,namespace:&namespace,binding:frozen,run:run.clone(),
            prepared:inputs,installation:std::sync::Arc::new(original_installation),claim:&mut claim,
        }).await?;
        if mode == "finite-complete" {
            return Ok(json!({"state":"COMPLETED","writer_valid":true,"run_id":id,"backend_pid":writer_pid,"study":document,"study_fingerprint":fingerprint,
                "native_specification_fingerprint":spec.fingerprint()?,"scientific_specification_fingerprint":spec.scientific_specification_fingerprint()?,"publication":publication}));
        }
        assert_eq!(publication["refused"],true);
        if mode == "finite-drain" {
            assert_eq!(publication["drained"],true);
            session.verify().await?;
            return Ok(json!({"state":"CANCELLED","writer_valid":true,"run_id":id,"backend_pid":writer_pid,"study":document,"study_fingerprint":fingerprint,
                "native_specification_fingerprint":spec.fingerprint()?,"scientific_specification_fingerprint":spec.scientific_specification_fingerprint()?}));
        }
    }
    let cancel = CommandId::new("00000000-0000-4000-8000-000000000925")?;
    strategy::cancel(
        session,
        (&access.human, &access.human_session),
        cancel.clone(),
        &id,
        at,
    )
    .await?;
    assert_eq!(
        ResearchExecution::new(session.client_mut().await?)
            .observe(&run)
            .await?
            .state,
        RunState::CancelRequested
    );
    ResearchExecution::new(session.client_mut().await?)
        .cancel(&mut claim, at)
        .await?;
    assert!(
        ResearchExecution::new(session.client_mut().await?)
            .heartbeat(&mut claim)
            .await
            .is_err(),
        "terminal claim cannot heartbeat"
    );
    strategy::cancel(
        session,
        (&access.human, &access.human_session),
        cancel,
        &id,
        at,
    )
    .await?;
    assert!(matches!(
        strategy::submission_outcome(session, &context, &study).await?,
        SubmissionOutcome::Accepted(_)
    ));
    let terminal = session.client_mut().await?.query_one("SELECT current_user=session_user,pg_backend_pid(),research_result_fingerprint IS NULL AND artifact_content_fingerprint IS NULL AND cardinality(calculation_execution_evidence_fingerprints)=0 FROM public.research_run WHERE run_id=$1::text::uuid",&[&id]).await?;
    assert!(terminal.get::<_,bool>(0));
    assert_eq!(terminal.get::<_,i32>(1),writer_pid);
    assert!(terminal.get::<_,bool>(2), "cancellation must not write result pins");
    session.verify().await?;
    Ok(
        json!({"state":"CANCELLED","writer_valid":true,"run_id":id,"backend_pid":writer_pid,"study":document,"study_fingerprint":fingerprint,
        "native_specification_fingerprint":spec.fingerprint()?,"scientific_specification_fingerprint":spec.scientific_specification_fingerprint()?}),
    )
}
pub async fn outcome(session: &mut AuthoritySession, v: &Value) -> Result<Value> {
    let access = AccessFixture::new(v)?;
    access.source.withdraw();
    let context = access.context();
    let study = strategy::restore_study(
        &context,
        &v["study"],
        v["study_fingerprint"].as_str().ok_or("study")?,
    )?;
    let SubmissionOutcome::Accepted(run) =
        strategy::submission_outcome(session, &context, &study).await?
    else {
        return Err("original outcome unavailable".into());
    };
    let status = ResearchExecution::new(session.client_mut().await?)
        .observe(&run)
        .await?;
    session.verify().await?;
    Ok(
        json!({"state":status.state.as_str(),"run_id":run.run_id(),"specification_fingerprint":run.specification_fingerprint(),
        "scientific_specification_fingerprint":run.specification().scientific_specification_fingerprint()?}),
    )
}

struct FiniteCase<'a> {
    values:&'a Value,
    access:&'a AccessFixture,
    namespace:&'a onlyalpha_backend::bootstrap::deployment::SemanticStoreId,
    binding:onlyalpha_backend::application::job_contract::FrozenJobBinding,
    run:onlyalpha_backend::application::research_run::VerifiedRun,
    prepared:PreparedInputs,
    installation:std::sync::Arc<onlyalpha_calculation_bridge::ChartInstallation>,
    claim:&'a mut onlyalpha_backend::persistence::research_execution::Claim,
}
/// Actual opaque Claim -> exact input -> real execution/join -> same-AS PG
/// publication. This technical fixture is not formal worker/Web acceptance.
async fn complete_finite(session:&mut AuthoritySession,facts:&mut tokio_postgres::Client,case:FiniteCase<'_>) -> Result<Value> {
    use onlyalpha_backend::{application::{finite_job,factor_build::FactorBuildService,job_input::{JobInputLoader,MemoryBudget}},persistence::{job_publication::{AttemptClaim,AttemptExecutionBinding,PublicationRepository,RunLocator},market_data::{Catalog,ClickHouse,ClickHouseConfig,Storage},strategy_research::Composer}};
    use std::{sync::Arc,time::{Duration,Instant}};
    let started=Instant::now();
    let rebound=case.values["submission_mode"]=="finite-rebound";
    let mut binding=case.binding;
    if rebound {
        let mut changed=binding.record().clone();
        changed["result_plan"]["members"][0]["schema"]=json!("f".repeat(64));
        binding=onlyalpha_backend::application::job_contract::FrozenJobBinding::from_record(&changed)?;
    }
    let actual=AttemptClaim::from_research(case.claim);
    let execution=AttemptExecutionBinding::capture(&actual)?;
    let mut metadata=crate::job_fact_connection::Connection::reader().await?;
    metadata.client.batch_execute("RESET ROLE").await?;
    let role=metadata.client.query_one("SELECT current_user=session_user,current_setting('default_transaction_read_only')='on'",&[]).await?;
    assert!(role.get::<_,bool>(0) && role.get::<_,bool>(1));
    let database=case.values["database"].as_str().ok_or("CH database")?;
    if !database.starts_with("onlyalpha_test_") { return Err("test CH namespace required".into()); }
    let physical=ClickHouse::new(ClickHouseConfig {
        url:case.values["url"].as_str().ok_or("CH URL")?.into(),database:database.into(),
        user:std::env::var("ONLYALPHA_CLICKHOUSE_USER")?,password:std::env::var("ONLYALPHA_CLICKHOUSE_PASSWORD")?,
        timeout:Duration::from_secs(5),tls_roots_pem:vec![],max_bytes:32*1024*1024,max_rows:10_000,
    })?;
    let input= {
        let mut storage=Storage::new(Catalog::new(&mut metadata.client,10_000,32*1024*1024)?,&physical,10_000)?;
        let mut factors=FactorBuildService::new(facts,case.namespace,Arc::clone(&case.installation)).await?;
        JobInputLoader::new(&mut storage,&mut factors,&case.access.source_session,&case.access.selection)
            .load(&binding,&MemoryBudget::new(8192,32*1024*1024)?).await?
    };
    let input_ns=started.elapsed().as_nanos();
    let rows=input.bars().len();
    let restoring=Instant::now();
    let runtime=onlyalpha_backend::persistence::research_runtime::RuntimeInputHold::open(
        Path::new(case.values["runtime_root"].as_str().ok_or("runtime root")?),case.run.run_id(),"research",case.run.runtime_generation_fingerprint()?,
    )?;
    let reconstructed=onlyalpha_backend::application::research_admission::restore_finite(
        &case.run,runtime,&case.installation,&binding,&input,
    )?;
    assert_eq!(reconstructed.record(),case.prepared.record());
    drop(case.prepared);
    let restore_ns=restoring.elapsed().as_nanos();
    let computing=Instant::now();
    let task=finite_job::start_research_claimed(case.run.clone(),reconstructed,input,binding,
        &mut Composer::new(&mut metadata.client).with_fact_reader(facts),case.installation,execution).await;
    if rebound {
        let refused=match task {
            Err(error)=>Some(error.code()),
            Ok(task)=>{
                task.cancellation().stop()?;
                let _=task.join().await; // Always drain an unexpectedly created real task before asserting.
                None
            }
        };
        assert_eq!(refused,Some("FINITE_JOB_BINDING_MISMATCH"),"a different plan must fail before any actual task is created");
        let count:i64=facts.query_one("SELECT count(*) FROM public.job_result_member WHERE job_kind='RESEARCH' AND run_id=$1::text::uuid",&[&case.run.run_id()]).await?.get(0);
        assert_eq!(count,0);
        return Ok(json!({"refused":true}));
    }
    if case.values["submission_mode"] == "finite-drain" {
        let task=task?;
        let at=case.values["at"].as_str().ok_or("at")?.parse()?;
        strategy::cancel(session,(&case.access.human,&case.access.human_session),
            CommandId::new("00000000-0000-4000-8000-000000000925")?,case.run.run_id(),at).await?;
        let drained=task.drain().await?;
        drop(actual);
        let cancelled=ResearchExecution::cancel_finite_guarded(session,case.namespace,&case.run,case.claim,&drained,at).await?;
        assert_eq!(cancelled.state,RunState::Cancelled);
        let count:i64=facts.query_one("SELECT count(*) FROM public.job_result_member WHERE job_kind='RESEARCH' AND run_id=$1::text::uuid",&[&case.run.run_id()]).await?.get(0);
        assert_eq!(count,0);
        return Ok(json!({"refused":true,"drained":true}));
    }
    let candidate=task?.join().await?;
    let compute_join_ns=computing.elapsed().as_nanos();
    let publishing=Instant::now();
    let outcome=PublicationRepository::publish_guarded(session,case.namespace,&actual,&candidate).await?;
    let publication=outcome.publication().fingerprint().to_owned();
    assert_eq!(publication,candidate.fingerprint());
    let publish_ns=publishing.elapsed().as_nanos();
    let reading=Instant::now();
    let key=RunLocator::new(onlyalpha_backend::application::job_contract::JobKind::Research,case.run.run_id())?;
    let first=PublicationRepository::new(facts,case.namespace,case.run.owner()).await?.read(&key).await?;
    let second=PublicationRepository::new(facts,case.namespace,case.run.owner()).await?.read(&key).await?;
    assert_eq!(first.fingerprint(),publication);
    assert_eq!(second.fingerprint(),publication);
    assert_eq!(first.specification_fingerprint(),case.run.specification_fingerprint());
    assert_eq!(first.admission_fingerprint(),case.run.admission_resolution_fingerprint());
    let read_ns=reading.elapsed().as_nanos();
    assert_eq!(ResearchExecution::new(session.client_mut().await?).observe(&case.run).await?.state,RunState::Completed);
    let baseline=session.client_mut().await?.query_one("SELECT current_user=session_user,NOT has_column_privilege(current_user,'public.research_run','research_result_fingerprint','UPDATE')",&[]).await?;
    assert!(baseline.get::<_,bool>(0) && baseline.get::<_,bool>(1));
    session.verify().await?;
    Ok(json!({"fingerprint":publication,"rows":rows,"input_ns":input_ns,"restore_ns":restore_ns,"compute_join_ns":compute_join_ns,"publish_ns":publish_ns,"two_reads_ns":read_ns,"total_ns":started.elapsed().as_nanos()}))
}

/// Recovery fixture reads the original PG Run without opening executable inputs.
pub async fn recover_finite(session:&mut AuthoritySession,v:&Value) -> Result<Value> {
    use onlyalpha_backend::application::job_recovery::{RecoveryDecision,RecoveryRefusal};
    let mut facts=crate::job_fact_connection::Connection::reader().await?;
    let namespace=onlyalpha_backend::bootstrap::deployment::load_semantic_store_id(
        &Path::new(v["research_root"].as_str().ok_or("research root")?).join(".onlyalpha-semantic-store.json"),
    )?;
    let id=v["run_id"].as_str().ok_or("original run")?;
    let run=onlyalpha_backend::persistence::research_submission::load(
        session.client_mut().await?,&mut facts.client,&namespace,id,None,
    ).await?;
    let at=v["at"].as_str().ok_or("at")?.parse()?;
    if v["request_cancel"] == true {
        ResearchExecution::new(session.client_mut().await?).request_cancel(&run,at).await?;
    }
    let state=match ResearchExecution::recover_finite_guarded(session,&namespace,&run,at).await? {
        RecoveryDecision::AlreadyPublished(_)=>"COMPLETED",
        RecoveryDecision::RecomputeWithNewClaim(_)=>{
            if v["claim"] == true {
                let claim=ResearchExecution::claim_recompute(session,&namespace,&run,
                    "00000000-0000-4000-8000-000000000921",v["attempt_id"].as_str().ok_or("attempt")?,at).await?.ok_or("recovery claim")?;
                assert!(claim.ownership_certain());
                "CLAIMED"
            } else {"READY"}
        },
        RecoveryDecision::Refused(RecoveryRefusal::Terminal,proof)=>match proof.run_state() {
            "FAILED"=>"FAILED","CANCELLED"=>"CANCELLED",_=>return Err("invalid recovered terminal".into()),
        },
        RecoveryDecision::WaitForResolution=>"WAIT",
        _=>return Err("recovery returned unsettled cancellation or exhaustion".into()),
    };
    session.verify().await?;
    Ok(json!({"state":state,"run_id":run.run_id()}))
}
