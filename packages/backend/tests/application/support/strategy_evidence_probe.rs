//! Actual Strategy evidence technical path. No fixture creates an execution/read seal.
use onlyalpha_backend::{
    application::{
        command::CommandId,
        research_admission::PreparedInputs,
        research_run_execution::{self, Control},
        strategy_research::{RunSpecification, StrategyEvaluation},
    },
    bootstrap::{deployment, research_namespace},
    persistence::{
        authority_session::AuthoritySession,
        research_dataset::Store as Datasets,
        research_evidence::Store as Evidence,
        research_execution::ResearchExecution,
        research_novelty::Authority as Novelty,
        research_runtime::{Registry, RuntimeInputHold},
        research_submission::{self, strategy},
        strategy_research::Composer,
    },
};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::{Value, json};
use std::{collections::BTreeMap, path::Path, sync::Arc};
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
fn text<'a>(v: &'a Value, key: &str) -> Result<&'a str> {
    v[key]
        .as_str()
        .ok_or_else(|| format!("missing {key}").into())
}
fn store(v: &Value) -> Result<Evidence> {
    Ok(Evidence::open(Path::new(text(v, "research_root")?))?
        .with_runtime_root(Path::new(text(v, "runtime_root")?))?)
}
pub async fn provision(session: &mut AuthoritySession, v: &Value) -> Result<Value> {
    let root = Path::new(text(v, "semantic_root")?);
    let namespace = research_namespace::initialize_fresh(root)?;
    // Explicit infrastructure extension of the same namespace, never reset old owners.
    let profile =
        std::fs::read(root.join("research/.onlyalpha-factor-research-owner-profile.json"))?;
    session.client_mut().await?.execute("INSERT INTO research_deployment_semantic_store_binding(singleton,semantic_store_id) VALUES(TRUE,$1::text::uuid)",&[&namespace.value()]).await?;
    deployment::verify_binding(session.client_mut().await?, &namespace).await?;
    assert_eq!(
        research_namespace::extend_strategy(root, session).await?,
        namespace
    );
    if v["backtest_infrastructure"] == true {
        assert_eq!(
            research_namespace::extend_manual_backtest(root, session).await?,
            namespace
        );
        let schema = onlyalpha_backend::bootstrap::configuration::load_schema_history(
            &Path::new(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .expect("backend package parent")
                .parent()
                .expect("repository root")
                .join("database/postgres/migrations"),
            8 * 1024 * 1024,
        )?;
        let registry =
            research_namespace::initialize_runtime_registry(root, &schema, session).await?;
        assert_eq!(registry, json!({"active_for_new_work":null,"states":{}}));
        let evidence =
            research_namespace::initialize_backtest_evidence(root, &schema, session).await?;
        assert_eq!(
            evidence,
            json!({"semantic_store_id":namespace.value(),"initialized":true})
        );
    }
    assert_eq!(
        std::fs::read(root.join("research/.onlyalpha-factor-research-owner-profile.json"))?,
        profile
    );
    Ok(
        json!({"namespace":namespace.value(),"source_roots":research_namespace::current_source_roots(root)?}),
    )
}
pub async fn submit(
    session: &mut AuthoritySession,
    v: &Value,
    inputs: PreparedInputs,
    spec: RunSpecification,
    datasets: &Datasets,
) -> Result<Value> {
    let access = super::strategy_input_probe::strategy_submission_probe::AccessFixture::new(v)?;
    let context = access.context();
    let command = CommandId::new(text(v, "research_command")?)?;
    let roots: BTreeMap<String, std::path::PathBuf> =
        serde_json::from_value(v["source_roots"].clone())?;
    let novelty = Novelty::new(
        Path::new(text(v, "semantic_root")?),
        Path::new(text(v, "projection_root")?),
        roots,
    )?
    .with_runtime_root(Path::new(text(v, "runtime_root")?))?;
    let request = strategy::Request::new(spec.clone(), None, "onlyalpha.factor-research", "1")?;
    let (study, actionable) = strategy::prepare_study(
        session, &novelty, &context, command, request, &inputs, datasets,
    )
    .await?
    .into_parts();
    assert!(actionable);
    let fingerprint = study.fingerprint()?;
    let run = strategy::submit(
        session,
        &novelty,
        &context,
        (&study, &fingerprint),
        &inputs,
        datasets,
        text(v, "at")?.parse()?,
    )
    .await?;
    assert!(store(v)?.load_verified(&run)?.is_none());
    assert!(
        store(v)?.read_verified_strategy(&run).is_err(),
        "an accepted Run without actual execution is no Freeze grant"
    );
    Ok(
        json!({"run_id":run.run_id(),"specification":spec.record(),"specification_fingerprint":spec.fingerprint()?,
        "scientific_specification_fingerprint":spec.scientific_specification_fingerprint()?,"candidate_fingerprint":spec.candidate_fingerprint()?,
        "prepared_inputs":inputs.record(),"study":study.record()?,"study_fingerprint":fingerprint}),
    )
}
pub async fn phase(session: &mut AuthoritySession, v: &Value) -> Result<Value> {
    let pid: i32 = session
        .client_mut()
        .await?
        .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
        .await?
        .get(0);
    let run = research_submission::load(
        session.client_mut().await?,
        text(v, "run_id")?,
        Some("local-developer"),
    )
    .await?;
    let evidence = store(v)?;
    if v["evidence_phase"] == "completion-read" {
        return Ok(
            json!({"state":if evidence.load_verified(&run)?.is_some(){"COMPLETE"}else{"ABSENT"}}),
        );
    }
    if v["evidence_phase"] == "inspect" {
        eprintln!("[strategy-evidence] phase=historical-display");
        let visible = onlyalpha_backend::transport::host_factor_research::read_strategy_report(
            Path::new(text(v, "research_root")?),
            Path::new(text(v, "runtime_root")?),
            &run,
        )?;
        assert_eq!(visible.observation_count, 720);
        assert_eq!(
            visible.warmup_bars,
            run.strategy_specification()?.record()["input_window"]["warmup_bars"]
                .as_u64()
                .ok_or("warmup")?
        );
        assert!(visible.node_count > 1 && visible.execution_graph_verified);
        assert_eq!(visible.start_at, "2025-01-02T12:00:00Z");
        assert_eq!(visible.end_at, "2025-01-03T00:00:00Z");
        assert!(!visible.limitations.is_empty());
        eprintln!("[strategy-evidence] phase=historical-report");
        let report = evidence.read_report(&run)?;
        eprintln!("[strategy-evidence] phase=historical-completion");
        let complete = evidence
            .load_verified(&run)?
            .ok_or("missing original complete report")?;
        assert_eq!(
            complete.research_result_fingerprint(),
            report["research_result_fingerprint"]
                .as_str()
                .ok_or("result")?
        );
        drop(complete);
        eprintln!("[strategy-evidence] phase=historical-seal");
        let _seal = evidence.read_verified_strategy(&run)?;
        drop(_seal);
        let roots: BTreeMap<String, std::path::PathBuf> =
            serde_json::from_value(v["source_roots"].clone())?;
        eprintln!("[strategy-evidence] phase=historical-novelty-open");
        let novelty = Novelty::new(
            Path::new(text(v, "semantic_root")?),
            Path::new(text(v, "projection_root")?),
            roots,
        )?
        .with_runtime_root(Path::new(text(v, "runtime_root")?))?;
        eprintln!("[strategy-evidence] phase=historical-projection");
        let projection = novelty
            .refresh_projection(session.client_mut().await?)
            .await?;
        eprintln!("[strategy-evidence] phase=historical-complete");
        return Ok(
            json!({"run_id":run.run_id(),"report":report,"projection":projection,"backend_pid":pid}),
        );
    }
    if v["evidence_phase"] == "recover" {
        ResearchExecution::new(session.client_mut().await?)
            .expire(&run, text(v, "at")?.parse()?)
            .await?
            .ok_or("expired original Attempt")?;
        let mut claim = ResearchExecution::new(session.client_mut().await?)
            .claim(
                &run,
                text(v, "worker_id")?,
                text(v, "attempt_id")?,
                text(v, "at")?.parse()?,
            )
            .await?
            .ok_or("recovery claim")?;
        let completion = evidence
            .load_verified(&run)?
            .ok_or("completed original semantic publication")?;
        let state = ResearchExecution::complete_guarded(
            session,
            &mut claim,
            &completion,
            text(v, "at")?.parse()?,
        )
        .await?;
        drop(completion);
        Registry::open_existing(Path::new(text(v, "runtime_root")?))?.release_work_exact(
            run.run_id(),
            run.runtime_generation_fingerprint()?,
            "research",
            "use_test_terminal_joined",
            text(v, "at")?.parse()?,
        )?;
        return Ok(
            json!({"run_id":run.run_id(),"state":state.state.as_str(),"recovered_without_evaluation":true,"backend_pid":pid}),
        );
    }
    let generation = run.runtime_generation_fingerprint()?.to_owned();
    let runtime = RuntimeInputHold::open(
        Path::new(text(v, "runtime_root")?),
        run.run_id(),
        "research",
        &generation,
    )?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(text(v, "algorithm_root")?),
        text(v, "algorithm_artifact")?,
    )?);
    let datasets = Datasets::open(Path::new(text(v, "dataset_root")?), 8192, 8 * 1024 * 1024)?;
    let inputs = onlyalpha_backend::application::research_admission::restore_strategy(
        &mut Composer::new(session.client_mut().await?),
        &run,
        runtime,
        &installation,
        &datasets,
    )
    .await?;
    let mut claim = ResearchExecution::new(session.client_mut().await?)
        .claim(
            &run,
            text(v, "worker_id")?,
            text(v, "attempt_id")?,
            text(v, "at")?.parse()?,
        )
        .await?
        .ok_or("original claim")?;
    let observed = StrategyEvaluation::observe(
        inputs,
        run.strategy_specification()?.clone(),
        &datasets,
        installation.clone(),
        env!("CARGO_PKG_VERSION"),
        &Control::default(),
    )?;
    let execution =
        research_run_execution::execute_strategy(run.clone(), observed, text(v, "at")?.parse()?)?;
    if v["evidence_phase"]
        .as_str()
        .is_some_and(|p| p.starts_with("deferred-"))
    {
        let completion = evidence.commit_strategy(execution)?;
        return refused_deferred_finalization(
            session, v, &run, &mut claim, completion, &evidence, pid,
        )
        .await;
    }
    assert!(
        evidence.read_report(&run).is_err(),
        "an executing Run has no completed report"
    );
    if v["evidence_phase"] == "commit-crash" {
        let completion = evidence.commit_strategy(execution)?;
        assert!(
            evidence.read_verified_strategy(&run).is_err(),
            "semantic files do not grant Freeze before durable Run completion"
        );
        use std::{io::Write, os::unix::fs::OpenOptionsExt};
        let mut marker = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(Path::new(text(v, "crash_marker")?))?;
        marker.write_all(&serde_json::to_vec(&json!({"run_id":run.run_id(),"backend_pid":pid,
            "result":completion.research_result_fingerprint(),"artifact":completion.artifact_content_fingerprint()}))?)?;
        marker.sync_all()?;
        std::process::exit(86);
    }
    // Two opaque products of actual independently joined observations publish
    // the same original admitted work. The barrier synchronizes their owning
    // calls without sleeps; different audit clocks cannot create second facts.
    let runtime = RuntimeInputHold::open(
        Path::new(text(v, "runtime_root")?),
        run.run_id(),
        "research",
        &generation,
    )?;
    let inputs = onlyalpha_backend::application::research_admission::restore_strategy(
        &mut Composer::new(session.client_mut().await?),
        &run,
        runtime,
        &installation,
        &datasets,
    )
    .await?;
    let observed = StrategyEvaluation::observe(
        inputs,
        run.strategy_specification()?.clone(),
        &datasets,
        installation.clone(),
        env!("CARGO_PKG_VERSION"),
        &Control::default(),
    )?;
    let replay = research_run_execution::execute_strategy(
        run.clone(),
        observed,
        text(v, "replay_at")?.parse()?,
    )?;
    let barrier = std::sync::Barrier::new(3);
    let (first, second) = std::thread::scope(|scope| {
        let one = scope.spawn(|| {
            barrier.wait();
            let selected = Evidence::open(Path::new(v["research_root"].as_str().unwrap()))?
                .with_runtime_root(Path::new(v["runtime_root"].as_str().unwrap()))?;
            selected.commit_strategy(execution)
        });
        let two = scope.spawn(|| {
            barrier.wait();
            let selected = Evidence::open(Path::new(v["research_root"].as_str().unwrap()))?
                .with_runtime_root(Path::new(v["runtime_root"].as_str().unwrap()))?;
            selected.commit_strategy(replay)
        });
        barrier.wait();
        (
            one.join().expect("actual first publication thread"),
            two.join().expect("actual second publication thread"),
        )
    });
    let completion = first?;
    let replay = second?;
    assert_eq!(
        completion.artifact_content_fingerprint(),
        replay.artifact_content_fingerprint()
    );
    assert_eq!(
        completion.research_result_fingerprint(),
        replay.research_result_fingerprint()
    );
    drop(replay);
    let snapshot = physical_snapshot(Path::new(text(v, "research_root")?))?;
    let reread = evidence
        .load_verified(&run)?
        .ok_or("completed physical publication")?;
    assert_eq!(
        completion.artifact_content_fingerprint(),
        reread.artifact_content_fingerprint()
    );
    drop(reread);
    assert_eq!(
        physical_snapshot(Path::new(text(v, "research_root")?))?,
        snapshot,
        "first scientific/report audit and Parquet bytes/inodes must survive concurrent semantic replay"
    );
    assert!(
        evidence.read_report(&run).is_err(),
        "semantic files do not substitute operational completion"
    );
    assert!(
        evidence.read_verified_strategy(&run).is_err(),
        "semantic files do not grant Freeze before durable Run completion"
    );
    let state = ResearchExecution::complete_guarded(
        session,
        &mut claim,
        &completion,
        text(v, "at")?.parse()?,
    )
    .await?;
    drop(completion);
    drop(installation);
    Registry::open_existing(Path::new(text(v, "runtime_root")?))?.release_work_exact(
        run.run_id(),
        &generation,
        "research",
        "use_test_terminal_joined",
        text(v, "at")?.parse()?,
    )?;
    Ok(
        json!({"run_id":run.run_id(),"state":state.state.as_str(),"semantic_replay":true,"concurrent_publication":true,"backend_pid":pid}),
    )
}

// The existing technical probe owns this exact AuthoritySession. No cfg seal,
// replacement connection, precomputed graph result or Shipping shortcut is used.
async fn worker_work(
    mut session: AuthoritySession,
    v: Value,
) -> Result<(AuthoritySession, onlyalpha_backend::workers::research::Work)> {
    let runtime = tokio::runtime::Handle::current();
    tokio::task::spawn_blocking(move || -> std::result::Result<_, String> {
        runtime.block_on(async move {
            let run = research_submission::load(
                session.client_mut().await.map_err(|e| e.to_string())?,
                text(&v, "run_id").map_err(|e| e.to_string())?,
                Some("local-developer"),
            )
            .await
            .map_err(|e| e.to_string())?;
            let root =
                Path::new(text(&v, "runtime_root").map_err(|e| e.to_string())?).to_path_buf();
            let held = RuntimeInputHold::open(
                &root,
                run.run_id(),
                "research",
                run.runtime_generation_fingerprint()
                    .map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
            let installation = ChartInstallation::open(
                Path::new(text(&v, "algorithm_root").map_err(|e| e.to_string())?),
                text(&v, "algorithm_artifact").map_err(|e| e.to_string())?,
            )
            .map_err(|e| e.to_string())?;
            let datasets = Datasets::open(
                Path::new(text(&v, "dataset_root").map_err(|e| e.to_string())?),
                8192,
                8 * 1024 * 1024,
            )
            .map_err(|e| e.to_string())?;
            let inputs = onlyalpha_backend::application::research_admission::restore_strategy(
                &mut Composer::new(session.client_mut().await.map_err(|e| e.to_string())?),
                &run,
                held,
                &installation,
                &datasets,
            )
            .await
            .map_err(|e| e.to_string())?;
            let work = onlyalpha_backend::workers::research::Work {
                run,
                inputs,
                datasets,
                installation,
                runtime_root: root,
                evidence_root: Path::new(text(&v, "research_root").map_err(|e| e.to_string())?)
                    .into(),
                native_version: env!("CARGO_PKG_VERSION").into(),
                worker_id: text(&v, "worker_id").map_err(|e| e.to_string())?.into(),
                attempt_id: text(&v, "attempt_id").map_err(|e| e.to_string())?.into(),
            };
            Ok((session, work))
        })
    })
    .await?
    .map_err(Into::into)
}
pub async fn worker(mut session: AuthoritySession, v: &Value) -> Result<Value> {
    let pid: i32 = session
        .client_mut()
        .await?
        .query_one("SELECT pg_backend_pid()", &[])
        .await?
        .get(0);
    let guarded = v["evidence_phase"] == "worker-guard";
    let frontier: i64 = session
        .client_mut()
        .await?
        .query_one(
            "SELECT last_index FROM research_source_history_frontier WHERE singleton",
            &[],
        )
        .await?
        .get(0);
    if guarded {
        session.client_mut().await?.batch_execute("CREATE FUNCTION use_test_worker_guard() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_worker_guard AFTER UPDATE ON research_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='COMPLETED' AND OLD.state IS DISTINCT FROM NEW.state) EXECUTE FUNCTION use_test_worker_guard()").await?;
    }
    let (session, work) = worker_work(session, v.clone()).await?;
    let run = work.run.clone();
    let generation = run.runtime_generation_fingerprint()?.to_owned();
    let writer = Arc::new(tokio::sync::Mutex::new(Some(session)));
    let actual_pid: i32 = writer
        .lock()
        .await
        .as_mut()
        .ok_or("original session")?
        .client_mut()
        .await?
        .query_one("SELECT pg_backend_pid()", &[])
        .await?
        .get(0);
    assert_eq!(
        actual_pid, pid,
        "restoration preserves the original physical Node session"
    );
    let at = text(v, "at")?.parse()?;
    let outcome = onlyalpha_backend::workers::research::run_owned(&writer, work, || Ok(at)).await;
    if guarded {
        assert!(
            outcome.is_err(),
            "the Shipping worker must refuse deferred physical guard loss before completion commits"
        );
        let mut original = writer.lock().await.take().ok_or("original session")?;
        assert!(original.verify().await.is_err());
        let _ = original.close().await;
        return Ok(
            json!({"guarded_finalization_refused":true,"run_id":run.run_id(),"expected_state":"RUNNING","expected_attempt":"ACTIVE","history_frontier_before":frontier,"backend_pid":pid}),
        );
    }
    let completed = outcome?;
    assert_eq!(completed.state.as_str(), "COMPLETED");
    let mut original = writer.lock().await.take().ok_or("original session")?;
    let current = research_submission::load(
        original.client_mut().await?,
        run.run_id(),
        Some("local-developer"),
    )
    .await?;
    let report = store(v)?.read_report(&current)?;
    assert_eq!(
        report["candidate_fingerprint"],
        run.strategy_specification()?.candidate_fingerprint()?
    );
    Registry::open_existing(Path::new(text(v, "runtime_root")?))?.release_work_exact(
        run.run_id(),
        &generation,
        "research",
        "use_test_worker_terminal_joined",
        at,
    )?;
    original.close().await?;
    Ok(json!({"run_id":run.run_id(),"state":"COMPLETED","actual_worker":true,"backend_pid":pid}))
}
fn physical_snapshot(root: &Path) -> Result<BTreeMap<String, (u64, Vec<u8>)>> {
    use std::os::unix::fs::MetadataExt;
    fn visit(base: &Path, at: &Path, out: &mut BTreeMap<String, (u64, Vec<u8>)>) -> Result<()> {
        for entry in std::fs::read_dir(at)? {
            let path = entry?.path();
            let name = path.file_name().ok_or("name")?.to_str().ok_or("utf8")?;
            if name == ".immutable-json-staging" || name.starts_with('.') {
                continue;
            }
            if path.is_dir() {
                visit(base, &path, out)?;
            } else {
                out.insert(
                    path.strip_prefix(base)?.to_str().ok_or("relative")?.into(),
                    (std::fs::metadata(&path)?.ino(), std::fs::read(path)?),
                );
            }
        }
        Ok(())
    }
    let mut output = BTreeMap::new();
    visit(root, root, &mut output)?;
    Ok(output)
}

async fn refused_deferred_finalization(
    session: &mut AuthoritySession,
    v: &Value,
    run: &onlyalpha_backend::application::research_run::VerifiedRun,
    claim: &mut onlyalpha_backend::persistence::research_execution::Claim,
    completion: onlyalpha_backend::application::research_run::VerifiedCompletion,
    evidence: &Evidence,
    pid: i32,
) -> Result<Value> {
    let fault = text(v, "evidence_phase")?;
    let reconcile = fault.starts_with("deferred-reconcile-");
    let guard = fault.ends_with("guard");
    let at = text(v, "at")?.parse()?;
    let mut completion = Some(completion);
    let mut expected_state = "RUNNING";
    let mut expected_attempt = "ACTIVE";
    if reconcile {
        drop(completion.take());
        let access = super::strategy_input_probe::strategy_submission_probe::AccessFixture::new(v)?;
        let context = access.context();
        strategy::cancel(
            session,
            (context.human_authority, context.human),
            CommandId::new(text(v, "cancel_command")?)?,
            run.run_id(),
            at,
        )
        .await?;
        session.client_mut().await?.execute("UPDATE research_run_attempt SET lease_expires_at=clock_timestamp()-interval '1 second' WHERE run_id=$1::text::uuid AND state='ACTIVE'",&[&run.run_id()]).await?;
        ResearchExecution::new(session.client_mut().await?)
            .expire(run, at)
            .await?
            .ok_or("expired original active Attempt")?;
        expected_state = "CANCEL_REQUESTED";
        expected_attempt = "EXPIRED";
    }
    let mutation = if guard {
        "PERFORM pg_advisory_unlock(1329199301,5);"
    } else {
        "UPDATE research_run SET revision=revision+1,research_result_fingerprint=repeat('e',64),artifact_content_fingerprint=repeat('f',64) WHERE run_id=NEW.run_id;"
    };
    let sql = format!(
        "CREATE FUNCTION use_test_research_deferred() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {mutation} RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_research_deferred AFTER UPDATE ON research_run DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='COMPLETED' AND OLD.state IS DISTINCT FROM NEW.state) EXECUTE FUNCTION use_test_research_deferred()"
    );
    session.client_mut().await?.batch_execute(&sql).await?;
    let before: i64 = session
        .client_mut()
        .await?
        .query_one(
            "SELECT last_index FROM research_source_history_frontier WHERE singleton",
            &[],
        )
        .await?
        .get(0);
    let rejected = if reconcile {
        let current = research_submission::load(
            session.client_mut().await?,
            run.run_id(),
            Some("local-developer"),
        )
        .await?;
        let state = ResearchExecution::new(session.client_mut().await?)
            .observe(&current)
            .await?;
        let inspection = evidence.inspect(current, state.revision)?;
        ResearchExecution::reconcile_guarded(session, &inspection, at)
            .await
            .is_err()
    } else {
        ResearchExecution::complete_guarded(
            session,
            claim,
            completion.as_ref().ok_or("completion")?,
            at,
        )
        .await
        .is_err()
    };
    assert!(
        rejected,
        "no completed state may cross a deferred mutation/physical guard loss"
    );
    if !reconcile {
        assert!(!claim.ownership_certain());
    }
    assert!(
        session.verify().await.is_err(),
        "unexpected deferred authority mutation revokes the original writer"
    );
    Ok(
        json!({"guarded_finalization_refused":true,"run_id":run.run_id(),"expected_state":expected_state,
        "expected_attempt":expected_attempt,"history_frontier_before":before,"backend_pid":pid}),
    )
}
