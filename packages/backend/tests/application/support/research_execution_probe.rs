//! Technical owning-authority integration; never a Shipping user operation.
#[path = "../../workers/research_authority.rs"]
mod research_authority;
#[path = "research_report_regressions.rs"]
mod research_report_regressions;
use onlyalpha_backend::{
    application::{
        command::CommandId,
        research_admission,
        research_dataset::MaterializedDataset,
        research_run::{InspectionOutcome, Specification, VerifiedRun},
        source_access::{Authority as Source, Grant, Permission, Reference, Selection},
    },
    persistence::{
        research_dataset::Store as Datasets,
        research_evidence::Store as Evidence,
        research_execution::{ResearchExecution, RunState},
        research_novelty::Authority as Novelty,
        research_runtime::RuntimeInputHold,
        research_submission::{self, Context, Request, SubmissionOutcome},
    },
    security::human_access::{Access, Admission},
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, path::Path};

pub async fn run(
    client: &mut tokio_postgres::Client,
    v: &Value,
    materialized: &MaterializedDataset,
) -> Result<Value, Box<dyn std::error::Error>> {
    let phase = v["phase"].as_str().ok_or("phase")?;
    if phase == "source-cut-inspect" {
        return research_report_regressions::inspect_source_cut(client, v).await;
    }
    if phase == "report-inspect" {
        return research_report_regressions::inspect(client, v).await;
    }
    if phase == "inspect" {
        return inspect_completed(client, v).await;
    }
    if !matches!(phase, "submit" | "execute") {
        return Err("phase".into());
    }
    if v["initialize_evidence"] == true {
        onlyalpha_backend::persistence::research_evidence::initialize_fresh_owners(Path::new(
            v["research_root"].as_str().ok_or("research root")?,
        ))?;
    }
    let f = &v["factor"];
    let command = CommandId::new(v["research_command"].as_str().ok_or("command")?)?;
    let work_id = research_submission::run_id(&command);
    let installation = onlyalpha_calculation_bridge::ChartInstallation::open(
        Path::new(f["installation"].as_str().ok_or("installation")?),
        f["algorithm_artifact"].as_str().ok_or("artifact")?,
    )?;
    let datasets = Datasets::open(
        Path::new(v["dataset_root"].as_str().ok_or("datasets")?),
        512,
        8 * 1024 * 1024,
    )?;
    let study = serde_json::from_value::<
        onlyalpha_backend::application::research_specification::Study,
    >(v["study"].clone())?;
    let compiled = onlyalpha_backend::application::research_factor::compile(
        &f["candidate"],
        &f["draft"],
        &f["revision"],
    )?;
    let window = compiled.window(onlyalpha_backend::application::research_factor::Window {
        start_ns: study.samples[0].start_ns,
        end_ns: study.samples[1].end_ns,
        bar_ns: study.bar_ns,
        horizon_bars: study.horizon_bars,
    })?;
    let hold = RuntimeInputHold::open(
        Path::new(f["runtime_root"].as_str().ok_or("runtime")?),
        &work_id,
        "research",
        f["generation"].as_str().ok_or("generation")?,
    )?;
    let inputs = if phase == "execute" {
        let accepted = research_submission::load(client, &work_id, None).await?;
        research_admission::restore(&accepted, hold, &installation, &datasets)
    } else {
        research_admission::prepare(
            hold,
            &installation,
            &compiled,
            &f["revision"],
            &window,
            &datasets,
            materialized,
        )
    }
    .map_err(|e| format!("input-preparation: {e}"))?;
    let spec = Specification {
        schema_version: 4,
        kind: "TIME_SERIES_FACTOR_RESEARCH".into(),
        candidate: json!({"hypothesis":f["candidate"]["hypothesis"],"expression":f["candidate"]["expression"]}),
        draft: f["draft"].clone(),
        revision: f["revision"].clone(),
        study,
        dataset_snapshot_fingerprint: materialized.verified().manifest()["snapshot_fingerprint"]
            .as_str()
            .ok_or("snapshot")?
            .into(),
        runtime_generation_fingerprint: f["generation"].as_str().ok_or("generation")?.into(),
        catalog_generation_fingerprint: inputs.runtime_manifest()["catalog_generation_fingerprint"]
            .as_str()
            .ok_or("catalog")?
            .into(),
        algorithm_artifact_fingerprint: f["algorithm_artifact"].as_str().ok_or("artifact")?.into(),
        execution_binding: inputs.record()["execution_binding"].clone(),
    };
    let human = Access::new(&"a".repeat(64))?;
    let request = http::Request::builder()
        .uri("/api/v2/integration-types")
        .header("host", "127.0.0.1:5173")
        .header(
            "cookie",
            format!("onlyalpha_dev_session={}", "a".repeat(64)),
        )
        .body(())?;
    let Admission::Owner(session) = human.admit(&request)? else {
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
    let context = Context {
        human_authority: &human,
        human: &session,
        source_authority: &source,
        source: &source_session,
        selection: &selection,
    };
    let at = v["at"]
        .as_str()
        .ok_or("time")?
        .parse::<onlyalpha_domain::time::OnlyUtcDateTime>()?;
    let mode = v["mode"].as_str().unwrap_or("normal");
    if phase == "submit" {
        let roots: BTreeMap<String, std::path::PathBuf> =
            serde_json::from_value(v["source_roots"].clone())?;
        let novelty = Novelty::new(
            Path::new(v["semantic_root"].as_str().ok_or("semantic")?),
            Path::new(v["projection_root"].as_str().ok_or("projection")?),
            roots,
        )?;
        let request = Request {
            schema_version: 1,
            factor_proposal_fingerprint: v["proposal_fingerprint"]
                .as_str()
                .ok_or("proposal")?
                .into(),
            parent_run_id: None,
            policy_id: "native".into(),
            policy_version: "1".into(),
            specification: spec,
        };
        let (proposal, actionable) = research_submission::prepare_study(
            client,
            &novelty,
            &context,
            command.clone(),
            request.clone(),
            &inputs,
            &datasets,
        )
        .await
        .map_err(|e| format!("study-preparation: {e}"))?
        .into_parts();
        assert!(actionable);
        let document = proposal.record()?;
        let fingerprint = proposal.fingerprint()?;
        if mode == "normal" {
            let (reentered, original_actionable) = research_submission::prepare_study(
                client,
                &novelty,
                &context,
                command.clone(),
                request,
                &inputs,
                &datasets,
            )
            .await?
            .into_parts();
            assert_eq!(original_actionable, actionable);
            assert_eq!(reentered.record()?, document);
            assert_eq!(reentered.fingerprint()?, fingerprint);
            assert!(
                client
                    .query_opt(
                        "SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",
                        &[&work_id],
                    )
                    .await?
                    .is_none()
            );
        }
        let restored = research_submission::restore_study(&context, &document, &fingerprint)?;
        if mode == "source-revoked" {
            let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN")?;
            let (mut blocker, connection) =
                tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
            let driver = tokio::spawn(connection);
            let (observer, connection) =
                tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
            let observer_driver = tokio::spawn(connection);
            let writer: i32 = client
                .query_one("SELECT pg_backend_pid()", &[])
                .await?
                .get(0);
            let blocked: i32 = blocker
                .query_one("SELECT pg_backend_pid()", &[])
                .await?
                .get(0);
            let tx = blocker.transaction().await?;
            tx.query_one(
                "SELECT factor_id FROM private_factor_asset WHERE factor_id=$1 FOR UPDATE",
                &[&f["revision"]["factor_id"].as_str().ok_or("factor")?],
            )
            .await?;
            let submit = research_submission::submit(
                client,
                &novelty,
                &context,
                (&restored, &fingerprint),
                &inputs,
                &datasets,
                at,
            );
            let revoke = async {
                tokio::time::timeout(std::time::Duration::from_secs(2), async {
                    loop {
                        let waiting: bool = observer
                            .query_one(
                                "SELECT $1::integer=ANY(pg_blocking_pids($2::integer))",
                                &[&blocked, &writer],
                            )
                            .await?
                            .get(0);
                        if waiting {
                            break;
                        }
                        tokio::task::yield_now().await;
                    }
                    Ok::<(), tokio_postgres::Error>(())
                })
                .await??;
                source.withdraw();
                tx.commit().await?;
                Ok::<(), Box<dyn std::error::Error>>(())
            };
            let (result, revoked) = tokio::join!(submit, revoke);
            revoked?;
            assert!(matches!(result, Err("RESEARCH_SOURCE_ACCESS_DENIED")));
            assert!(
                client
                    .query_opt(
                        "SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",
                        &[&work_id]
                    )
                    .await?
                    .is_none()
            );
            drop(blocker);
            drop(observer);
            driver.await??;
            observer_driver.await??;
            return Ok(json!({"run_id":work_id,"state":"DENIED"}));
        }
        let run = research_submission::submit(
            client,
            &novelty,
            &context,
            (&restored, &fingerprint),
            &inputs,
            &datasets,
            at,
        )
        .await
        .map_err(|e| format!("study-submission: {e}"))?;
        assert_eq!(run.run_id(), work_id);
        // Original Receipt replay ignores subsequent Source withdrawal and does not repeat admission.
        source.withdraw();
        assert_eq!(
            research_submission::submit(
                client,
                &novelty,
                &context,
                (&restored, &fingerprint),
                &inputs,
                &datasets,
                at
            )
            .await?
            .run_id(),
            run.run_id()
        );
        assert!(matches!(
            research_submission::submission_outcome(client, &context, &restored).await?,
            SubmissionOutcome::Accepted(_)
        ));
        if mode == "queued-cancel" {
            let group = Path::new(v["semantic_root"].as_str().ok_or("semantic root")?)
                .join("research/novelty-decision-groups")
                .join(command.value());
            let held = group.with_file_name("held-queued-cancel-group");
            std::fs::rename(&group, &held)?;
            let cancellation = research_submission::cancel(
                client,
                (context.human_authority, context.human),
                CommandId::new("00000000-0000-4000-8000-000000000901")?,
                run.run_id(),
                at,
            )
            .await;
            std::fs::rename(&held, &group)?;
            cancellation?;
            return Ok(
                json!({"run_id":run.run_id(),"state":ResearchExecution::new(client).observe(&run).await?.state.as_str(),"materialization_id":materialized.lineage()["materialization_id"]}),
            );
        }
        return Ok(
            json!({"run_id":run.run_id(),"state":"QUEUED","materialization_id":materialized.lineage()["materialization_id"]}),
        );
    }
    // Fresh process resumes only the original durable grant. No second admission.
    source.withdraw();
    let run = research_submission::load(client, &work_id, Some("local-developer")).await?;
    assert_eq!(run.specification_fingerprint(), spec.fingerprint()?);
    assert_eq!(
        materialized.lineage()["materialization_id"],
        v["materialization_id"]
    );
    let root = Path::new(v["research_root"].as_str().ok_or("research root")?).to_path_buf();
    let worker = "00000000-0000-4000-8000-000000000902";
    let mut first = None;
    if mode == "budget" || mode == "budget-with-result" {
        for i in 0..if mode == "budget" { 3 } else { 2 } {
            let attempt = format!("00000000-0000-4000-8000-{:012}", 910 + i);
            let mut claim = ResearchExecution::new(client)
                .claim(&run, worker, &attempt, at)
                .await?
                .ok_or("claim")?;
            if mode == "budget" && i == 2 {
                first = Some(claim);
                break;
            }
            let failure = onlyalpha_backend::persistence::research_execution::Failure::new(
                onlyalpha_backend::persistence::research_execution::FailurePhase::Operational,
                "CONTROLLED_OPERATIONAL_FAILURE",
                "controlled retry classification",
            )?;
            assert_eq!(
                ResearchExecution::new(client)
                    .fail(
                        &mut claim,
                        &failure,
                        onlyalpha_backend::persistence::research_execution::RetryDecision::Retry,
                        at
                    )
                    .await?
                    .state,
                RunState::Running
            );
        }
    }
    if !matches!(mode, "normal" | "wrong-native-version") && first.is_none() {
        first = Some(
            ResearchExecution::new(client)
                .claim(&run, worker, "00000000-0000-4000-8000-000000000913", at)
                .await?
                .ok_or("claim")?,
        );
    }
    let mut inputs = Some(inputs);
    let store = Evidence::open(&root)?;
    let completion = if matches!(
        mode,
        "cancel-complete"
            | "cancel-partial"
            | "cancel-corrupt"
            | "heartbeat-unknown"
            | "budget-with-result"
    ) {
        let executed = onlyalpha_backend::application::research_run_execution::execute(
            run.clone(),
            inputs.take().unwrap(),
            Datasets::open(
                Path::new(v["dataset_root"].as_str().unwrap()),
                512,
                8 * 1024 * 1024,
            )?,
            onlyalpha_calculation_bridge::ChartInstallation::open(
                Path::new(f["installation"].as_str().ok_or("installation")?),
                f["algorithm_artifact"].as_str().ok_or("artifact")?,
            )?,
            "0.11.1",
            &onlyalpha_backend::application::research_run_execution::Control::default(),
        )?;
        Some(store.commit(executed)?)
    } else {
        None
    };
    if mode == "heartbeat-unknown" {
        let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN")?;
        let (mut blocker, connection) =
            tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
        let driver = tokio::spawn(connection);
        let tx = blocker.transaction().await?;
        tx.query_one(
            "SELECT run_id FROM research_run WHERE run_id=$1::text::uuid FOR UPDATE",
            &[&run.run_id()],
        )
        .await?;
        let claim = first.as_mut().unwrap();
        assert!(
            ResearchExecution::new(client)
                .heartbeat(claim)
                .await
                .is_err()
        );
        assert!(!claim.ownership_certain());
        tx.commit().await?;
        assert_eq!(
            ResearchExecution::new(client)
                .complete(claim, completion.as_ref().unwrap(), at)
                .await
                .unwrap_err(),
            "RESEARCH_EXECUTION_OWNERSHIP_UNCERTAIN"
        );
        ResearchExecution::new(client).heartbeat(claim).await?;
        ResearchExecution::new(client)
            .complete(claim, completion.as_ref().unwrap(), at)
            .await?;
        drop(blocker);
        driver.await??;
    } else if mode.starts_with("cancel-") {
        research_submission::cancel(
            client,
            (context.human_authority, context.human),
            CommandId::new("00000000-0000-4000-8000-000000000914")?,
            run.run_id(),
            at,
        )
        .await?;
        let mut restore = None;
        let plan = onlyalpha_backend::application::factor_content::hash(
            &run.specification().result_plan()?,
        )?;
        let result_path = root
            .join("results/sha256")
            .join(&plan[..2])
            .join(&plan)
            .join("manifest.json");
        let retained_result = completion
            .as_ref()
            .map(|_| std::fs::read(&result_path))
            .transpose()?;
        if let Some(completed) = &completion {
            let id = completed.research_result_fingerprint();
            let artifact = root
                .join("artifacts/research-time-series-v1/sha256")
                .join(&id[..2])
                .join(id);
            if mode == "cancel-partial" {
                std::fs::remove_dir_all(&artifact)?;
            } else if mode == "cancel-corrupt" {
                let path = artifact.join("manifest.json");
                let bytes = std::fs::read(&path)?;
                std::fs::write(&path, b"{}")?;
                restore = Some((path, bytes));
            }
        }
        let attempt = first.as_ref().unwrap().attempt_id();
        client.execute("UPDATE research_run_attempt SET lease_expires_at=last_heartbeat_at WHERE attempt_id=$1::text::uuid",&[&attempt]).await?;
        assert_eq!(
            ResearchExecution::new(client)
                .expire(&run, at)
                .await?
                .unwrap()
                .state,
            RunState::CancelRequested
        );
        let inspection = store.inspect(run.clone(), 2)?;
        let resolved = ResearchExecution::new(client)
            .reconcile(&inspection, at)
            .await?;
        drop(inspection);
        if let Some((path, bytes)) = restore {
            std::fs::write(path, bytes)?;
        }
        if mode != "cancel-complete" {
            if let Some(completed) = completion {
                let bytes = std::fs::read(&result_path)?;
                assert_eq!(Some(&bytes), retained_result.as_ref());
                let result: Value = serde_json::from_slice(&bytes)?;
                assert_eq!(
                    result["research_result_fingerprint"],
                    completed.research_result_fingerprint()
                );
            }
            return Ok(json!({"run_id":run.run_id(),"state":resolved.state.as_str()}));
        }
    } else if mode == "budget" || mode == "budget-with-result" {
        if first.is_none() {
            first = Some(
                ResearchExecution::new(client)
                    .claim(&run, worker, "00000000-0000-4000-8000-000000000915", at)
                    .await?
                    .ok_or("claim")?,
            );
        }
        let claim = first.as_ref().unwrap();
        let attempt = claim.attempt_id();
        client.execute("UPDATE research_run_attempt SET lease_expires_at=last_heartbeat_at WHERE attempt_id=$1::text::uuid",&[&attempt]).await?;
        assert_eq!(
            ResearchExecution::new(client)
                .expire(&run, at)
                .await?
                .unwrap()
                .state,
            RunState::Failed
        );
        assert!(
            ResearchExecution::new(client)
                .claim(&run, worker, "00000000-0000-4000-8000-000000000916", at)
                .await?
                .is_none()
        );
        if completion.is_some() {
            assert!(store.load_verified(&run)?.is_some());
        }
        return Ok(json!({"run_id":run.run_id(),"state":"FAILED"}));
    } else {
        if mode == "stale-reentry" {
            let attempt = first.as_ref().unwrap().attempt_id();
            client.execute("UPDATE research_run_attempt SET lease_expires_at=last_heartbeat_at WHERE attempt_id=$1::text::uuid",&[&attempt]).await?;
        }
        let status = onlyalpha_backend::workers::research::run_once(
            client,
            onlyalpha_backend::workers::research::Work {
                run: run.clone(),
                inputs: inputs.take().unwrap(),
                datasets,
                installation,
                evidence_root: root.clone(),
                native_version: if mode == "wrong-native-version" {
                    "0.0.0"
                } else {
                    "0.11.1"
                }
                .into(),
                worker_id: worker.into(),
                attempt_id: "00000000-0000-4000-8000-000000000903".into(),
            },
            || at,
        )
        .await?;
        if mode == "wrong-native-version" {
            assert_eq!(status.state, RunState::Failed);
            let row = client.query_one("SELECT failure_code,research_result_fingerprint,artifact_content_fingerprint FROM research_run WHERE run_id=$1::text::uuid",&[&run.run_id()]).await?;
            assert_eq!(row.get::<_, String>(0), "RESEARCH_EXECUTOR_IMAGE_MISMATCH");
            assert!(
                row.get::<_, Option<String>>(1).is_none()
                    && row.get::<_, Option<String>>(2).is_none()
            );
            return Ok(json!({"run_id":run.run_id(),"state":"FAILED"}));
        }
        assert_eq!(status.state, RunState::Completed);
        if let Some(mut stale) = first {
            let complete = store.load_verified(&run)?.unwrap();
            assert_eq!(
                ResearchExecution::new(client)
                    .complete(&mut stale, &complete, at)
                    .await
                    .unwrap_err(),
                "RESEARCH_EXECUTION_OWNERSHIP_LOST"
            );
        }
    }
    let status = ResearchExecution::new(client).observe(&run).await?;
    assert_eq!(status.state, RunState::Completed);
    let cancel = research_submission::cancel(
        client,
        (context.human_authority, context.human),
        CommandId::new("00000000-0000-4000-8000-000000000904")?,
        run.run_id(),
        at,
    )
    .await;
    assert!(matches!(cancel, Err("RESEARCH_CANCEL_CONFLICT")));
    assert!(client.query_opt("SELECT 1 FROM product_command_receipt WHERE command_id='00000000-0000-4000-8000-000000000904'",&[]).await?.is_none());
    Ok(json!({"run_id":run.run_id(),"state":status.state.as_str()}))
}

/// Last destructive scenario consumes the actual original Node session; it never
/// acquires a second writer. Its shadow is only the isolated test fault/observation socket.
pub async fn execute_node_fence(
    session: onlyalpha_backend::persistence::authority_session::AuthoritySession,
    v: &Value,
) -> Result<Value, Box<dyn std::error::Error>> {
    let writer = std::sync::Arc::new(tokio::sync::Mutex::new(Some(session)));
    let command = CommandId::new(v["research_command"].as_str().ok_or("command")?)?;
    let id = research_submission::run_id(&command);
    let run = {
        let mut original = writer.lock().await;
        research_submission::load(
            original.as_mut().ok_or("writer")?.client_mut().await?,
            &id,
            None,
        )
        .await?
    };
    let f = &v["factor"];
    let datasets = Datasets::open(
        Path::new(v["dataset_root"].as_str().ok_or("datasets")?),
        512,
        8 * 1024 * 1024,
    )?;
    let installation = onlyalpha_calculation_bridge::ChartInstallation::open(
        Path::new(f["installation"].as_str().ok_or("installation")?),
        &run.specification().algorithm_artifact_fingerprint,
    )?;
    let runtime = RuntimeInputHold::open(
        Path::new(f["runtime_root"].as_str().ok_or("runtime")?),
        &id,
        "research",
        run.runtime_generation_fingerprint(),
    )?;
    let inputs = research_admission::restore(&run, runtime, &installation, &datasets)?;
    let work = onlyalpha_backend::workers::research::Work {
        run,
        inputs,
        datasets,
        installation,
        evidence_root: Path::new(v["research_root"].as_str().ok_or("research root")?).into(),
        native_version: env!("CARGO_PKG_VERSION").into(),
        worker_id: "00000000-0000-4000-8000-000000000902".into(),
        attempt_id: "00000000-0000-4000-8000-000000000903".into(),
    };
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN")?;
    let (mut shadow, connection) = tokio_postgres::connect(&dsn, tokio_postgres::NoTls).await?;
    let driver = tokio::spawn(connection);
    let at = v["at"].as_str().ok_or("time")?.parse()?;
    research_authority::node_socket_loss_during_finalization_cannot_commit_on_another_socket(
        writer,
        work,
        &mut shadow,
        at,
    )
    .await;
    drop(shadow);
    driver.await??;
    Ok(json!({"run_id":id,"state":"RUNNING","node_fence_verified":true}))
}

async fn inspect_completed(
    client: &mut tokio_postgres::Client,
    v: &Value,
) -> Result<Value, Box<dyn std::error::Error>> {
    let command = CommandId::new(v["research_command"].as_str().ok_or("command")?)?;
    let id = research_submission::run_id(&command);
    let run = research_submission::load(client, &id, Some("local-developer")).await?;
    assert_eq!(
        ResearchExecution::new(client).observe(&run).await?.state,
        RunState::Completed
    );
    let root = Path::new(v["research_root"].as_str().ok_or("research root")?);
    let store = Evidence::open(root)?;
    let report = store.read_report(&run)?;
    if v["mode"] == "normal" {
        source_event_mutations();
        let row: String = client
            .query_one(
                "SELECT row_to_json(r)::text FROM research_run r WHERE run_id=$1::text::uuid",
                &[&id],
            )
            .await?
            .get(0);
        run_source_structural_mutations(&serde_json::from_str(&row)?);
        missing_namespaces_are_unavailable(&store, root, &run);
        physical_artifact_corruption_fails_closed(&store, root, &run);
        completed_report_rejects_rebound_chain(&store, root, &run, &report);
    }
    Ok(json!({"run_id":id,"state":"COMPLETED","report":report}))
}

/// Controlled isolated-store fault: every content hash is recomputed, but the
/// completed operational Run still owns its original exact completion tuple.
fn completed_report_rejects_rebound_chain(
    store: &Evidence,
    root: &Path,
    completed: &onlyalpha_backend::application::research_run::VerifiedRun,
    report: &Value,
) {
    use onlyalpha_backend::application::factor_content::hash;
    fn signed(mut value: Value, key: &str) -> Value {
        value.as_object_mut().unwrap().remove(key);
        value[key] = json!(onlyalpha_backend::application::factor_content::hash(&value).unwrap());
        value
    }
    fn path(root: &Path, owner: &str, id: &str) -> std::path::PathBuf {
        root.join(owner)
            .join(&id[..2])
            .join(id)
            .join("manifest.json")
    }
    fn read(path: &Path) -> Value {
        serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap()
    }
    fn write(path: &Path, value: &Value) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        let canonical =
            onlyalpha_metadata_json::canonical_json(&value.to_string(), 8 * 1024 * 1024).unwrap();
        std::fs::write(path, canonical).unwrap();
    }
    let statistic = &report["statistics"][0];
    let stats_path = path(
        root,
        "statistics-results/sha256",
        statistic["statistics_fingerprint"].as_str().unwrap(),
    );
    let old_stats = std::fs::read(&stats_path).unwrap();
    let mut changed = statistic.clone();
    let point = changed["analysis"]["pearson"]["value"].as_str().unwrap();
    changed["analysis"]["pearson"]["value"] =
        json!(if let Some(positive) = point.strip_prefix('-') {
            positive.to_owned()
        } else if point == "0.000000000000" {
            "0.000000000001".into()
        } else {
            format!("-{point}")
        });
    changed = signed(changed, "statistics_result_fingerprint");
    let plan = hash(&completed.specification().result_plan().unwrap()).unwrap();
    let result_path = path(root, "results/sha256", &plan);
    let old_result = std::fs::read(&result_path).unwrap();
    let mut result = read(&result_path);
    let original_evidence = result["calculation_execution_evidence_fingerprints"][0]
        .as_str()
        .unwrap();
    let mut evidence = read(&path(
        root,
        "calculation-execution-evidence/sha256",
        original_evidence,
    ));
    evidence["statistics_results"][0] = changed["statistics_result_fingerprint"].clone();
    evidence = signed(evidence, "evidence_fingerprint");
    result["statistics_references"][0]["statistics_result_fingerprint"] =
        changed["statistics_result_fingerprint"].clone();
    result["calculation_execution_evidence_fingerprints"][0] =
        evidence["evidence_fingerprint"].clone();
    result = signed(result, "research_result_fingerprint");
    let mut artifact = report.clone();
    artifact["statistics"][0] = changed.clone();
    artifact["research_result_fingerprint"] = result["research_result_fingerprint"].clone();
    artifact = signed(artifact, "artifact_content_fingerprint");
    let evidence_path = path(
        root,
        "calculation-execution-evidence/sha256",
        evidence["evidence_fingerprint"].as_str().unwrap(),
    );
    let artifact_path = path(
        root,
        "artifacts/research-time-series-v1/sha256",
        result["research_result_fingerprint"].as_str().unwrap(),
    );
    assert!(!evidence_path.exists() && !artifact_path.exists());
    write(&stats_path, &changed);
    write(&evidence_path, &evidence);
    write(&result_path, &result);
    write(&artifact_path, &artifact);
    let pinned = store.read_report(completed);
    std::fs::write(stats_path, old_stats).unwrap();
    std::fs::write(result_path, old_result).unwrap();
    std::fs::remove_dir_all(evidence_path.parent().unwrap()).unwrap();
    std::fs::remove_dir_all(artifact_path.parent().unwrap()).unwrap();
    // This error is issued only after the owning reader has validated the
    // entire Result/Statistics/Evidence/Artifact closure, immediately at the
    // completed Run's exact tuple comparison. An invalid chain yields a
    // different error and cannot satisfy this assertion.
    assert_eq!(pinned.unwrap_err(), "RESEARCH_COMPLETION_PROOF_MISMATCH");
    assert_eq!(&store.read_report(completed).unwrap(), report);
}

/// Strict source proofs reject incomplete/malformed records before cross-row joins.
pub fn source_event_mutations() {
    use onlyalpha_backend::persistence::research_execution::validate_source_history_event as validate;
    use serde_json::{Value, json};
    let attempt = json!({"attempt_id":"00000000-0000-4000-8000-000000000921","run_id":"00000000-0000-4000-8000-000000000922","attempt_number":1,"state":"ACTIVE","worker_instance_id":"00000000-0000-4000-8000-000000000923","claimed_at":"2026-10-29T03:00:00+00:00","last_heartbeat_at":"2026-10-29T03:00:00+00:00","lease_expires_at":"2026-10-29T03:02:00+00:00","finished_at":null,"failure_phase":null,"failure_code":null,"failure_detail":null});
    validate("RESEARCH_ATTEMPT", &attempt).unwrap();
    for (key, value) in [
        ("attempt_id", json!("x")),
        ("run_id", json!("x")),
        ("worker_instance_id", json!("x")),
        ("attempt_number", json!(true)),
        ("attempt_number", json!(0)),
        ("state", json!("UNKNOWN")),
        ("last_heartbeat_at", json!("2026-10-29T02:00:00Z")),
        ("lease_expires_at", json!("2026-10-29T02:59:59Z")),
        ("claimed_at", json!("2026-10-29T03:00:00+01:00")),
        ("finished_at", json!("2026-10-29T03:00:01Z")),
        ("failure_code", json!("PARTIAL")),
    ] {
        let mut bad = attempt.clone();
        bad[key] = value;
        assert!(validate("RESEARCH_ATTEMPT", &bad).is_err(), "{key}");
    }
    for state in ["SUCCEEDED", "CANCELLED", "FAILED", "EXPIRED"] {
        let mut terminal = attempt.clone();
        terminal["state"] = json!(state);
        terminal["finished_at"] = json!(if state == "EXPIRED" {
            "2026-10-29T03:02:00Z"
        } else {
            "2026-10-29T03:00:01Z"
        });
        if matches!(state, "FAILED" | "EXPIRED") {
            terminal["failure_phase"] = json!("OPERATIONAL");
            terminal["failure_code"] = json!("LEASE_EXPIRED");
            terminal["failure_detail"] = json!("controlled fault");
        }
        validate("RESEARCH_ATTEMPT", &terminal).unwrap();
        if state == "EXPIRED" {
            let mut early = terminal.clone();
            early["finished_at"] = json!("2026-10-29T03:01:59.999999Z");
            assert!(validate("RESEARCH_ATTEMPT", &early).is_err());
        }
        terminal["finished_at"] = Value::Null;
        assert!(validate("RESEARCH_ATTEMPT", &terminal).is_err());
    }
    for key in attempt.as_object().unwrap().keys() {
        let mut bad = attempt.clone();
        bad.as_object_mut().unwrap().remove(key);
        assert!(validate("RESEARCH_ATTEMPT", &bad).is_err());
    }
    let mut bad = attempt.clone();
    bad["unexpected"] = json!(1);
    assert!(validate("RESEARCH_ATTEMPT", &bad).is_err());
    let admission = json!({"command_id":"00000000-0000-4000-8000-000000000922","command_kind":"CREATE_RESEARCH_RUN","command_fingerprint":"a".repeat(64),"schema_version":1});
    validate("PRODUCT_COMMAND_ADMISSION", &admission).unwrap();
    for (key, value) in [
        ("command_id", json!("x")),
        ("command_kind", json!("UNKNOWN")),
        ("command_fingerprint", json!("invalid")),
        ("schema_version", json!(true)),
        ("schema_version", json!(2)),
    ] {
        let mut bad = admission.clone();
        bad[key] = value;
        assert!(validate("PRODUCT_COMMAND_ADMISSION", &bad).is_err());
    }
}

/// Called with a root-owned genuine native Run4 row (no alternate fixture format).
pub fn run_source_structural_mutations(row: &serde_json::Value) {
    use onlyalpha_backend::persistence::research_execution::validate_source_history_event as validate;
    use serde_json::json;
    validate("RESEARCH_RUN", row).unwrap();
    for key in row.as_object().unwrap().keys() {
        let mut bad = row.clone();
        bad.as_object_mut().unwrap().remove(key);
        assert!(validate("RESEARCH_RUN", &bad).is_err(), "{key}");
    }
    for (key, value) in [
        ("revision", json!(-1)),
        ("origin_kind", json!("PRIVATE_STRATEGY")),
        ("state", json!("UNKNOWN")),
        ("specification_fingerprint", json!("0".repeat(64))),
        ("admission_resolution_fingerprint", json!("x")),
        (
            "strategy_research_composition_fingerprint",
            json!("a".repeat(64)),
        ),
        ("specification_payload", json!("{}")),
        ("failure_phase", json!("UNKNOWN")),
        (
            "calculation_execution_evidence_fingerprints",
            json!(["a".repeat(64), "a".repeat(64)]),
        ),
    ] {
        let mut bad = row.clone();
        bad[key] = value;
        assert!(validate("RESEARCH_RUN", &bad).is_err(), "{key}");
    }
}

/// Owner/namespace loss must never be interpreted as a certified missing Result.
pub fn missing_namespaces_are_unavailable(store: &Evidence, root: &Path, run: &VerifiedRun) {
    for relative in [
        "results/sha256",
        "statistics-results/sha256",
        "calculation-results/sha256",
        "calculation-execution-evidence/sha256",
        "artifacts/research-time-series-v1/sha256",
    ] {
        let source = root.join(relative);
        let held = source.with_file_name("held-sha256");
        std::fs::rename(&source, &held).unwrap();
        let outcome = store.load_verified(run);
        std::fs::rename(&held, &source).unwrap();
        assert!(outcome.is_err(), "{relative}");
    }
    assert!(
        onlyalpha_backend::persistence::research_evidence::initialize_fresh_owners(root).is_err()
    );
}

pub fn physical_artifact_corruption_fails_closed(store: &Evidence, root: &Path, run: &VerifiedRun) {
    let completion = store.load_verified(run).unwrap().unwrap();
    let id = completion.research_result_fingerprint();
    let manifest = root
        .join("artifacts/research-time-series-v1/sha256")
        .join(&id[..2])
        .join(id)
        .join("manifest.json");
    let original = std::fs::read(&manifest).unwrap();
    std::fs::write(&manifest, b"{}").unwrap();
    let loaded = store.load_verified(run);
    let inspected = store.inspect(run.clone(), 2);
    std::fs::write(&manifest, &original).unwrap();
    assert!(loaded.is_err());
    assert!(matches!(
        inspected.unwrap().outcome(),
        InspectionOutcome::Corrupt
    ));
    assert!(store.load_verified(run).unwrap().is_some());
}
