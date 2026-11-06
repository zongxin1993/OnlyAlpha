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
    let restored = onlyalpha_backend::application::research_admission::restore_strategy(
        &mut onlyalpha_backend::persistence::strategy_research::Composer::new(
            session.client_mut().await?,
        ),
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
    access.source.withdraw();
    assert_eq!(
        strategy::submit(
            session,
            &novelty,
            &context,
            (&study, &fingerprint),
            &inputs,
            datasets,
            at
        )
        .await?
        .run_id(),
        id
    );
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
    let mut operational = ResearchExecution::new(session.client_mut().await?);
    assert_eq!(operational.observe(&run).await?.state, RunState::Queued);
    let mut claim = operational
        .claim(
            &run,
            "00000000-0000-4000-8000-000000000921",
            "00000000-0000-4000-8000-000000000922",
            at,
        )
        .await?
        .ok_or("claim")?;
    assert!(
        operational
            .claim(
                &run,
                "00000000-0000-4000-8000-000000000923",
                "00000000-0000-4000-8000-000000000924",
                at
            )
            .await?
            .is_none()
    );
    operational.heartbeat(&mut claim).await?;
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
