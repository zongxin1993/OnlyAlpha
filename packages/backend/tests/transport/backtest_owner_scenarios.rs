//! Test-only consumer of original READY/Run owners; no DTO can mint a grant.
use super::*;
use crate::{
    application::backtest_run::VerifiedRun,
    bootstrap::workstation_startup::{Configuration as NodeConfiguration, Running},
    persistence::{
        backtest_run::Backtests, research_preparation::child_command,
    },
    workers::{
        backtest_service::Configuration,
        backtest_service_tests as producer,
        backtest_worker::tests as worker,
    },
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::sync::atomic::Ordering;

fn clock()
-> std::result::Result<OnlyUtcDateTime, crate::application::research_admission::PreparationError> {
    now().map_err(|_| "BACKTEST_CLOCK_UNAVAILABLE".into())
}

async fn create_original(
    host: &Arc<Host>,
    human: &human_access::Session,
    original: &Operation,
) -> VerifiedRun {
    let request = Host::backtest_create_request(original).unwrap();
    let namespace = namespace(&host.research_preparation_config).unwrap();
    let source = original.source().unwrap();
    let (authority, session, selection) = host
        .preparation_sources(human, &source, true)
        .await
        .unwrap();
    let context = backtest_run::Context {
        human_authority: &host.human_access,
        human,
        source_authority: &authority,
        source: &session,
        selection: &selection,
    };
    let mut owners = host.backtest_ready_owners(original).await.unwrap();
    let inputs = backtest_run::Inputs::new(
        &owners.prepared,
        &owners.admission,
        &mut owners.runtime,
        &owners.materialized,
        &owners.datasets,
        original,
        owners.validation.as_deref(),
    )
    .unwrap();
    let mut held = host.writer.lock().await;
    Backtests::new(held.as_mut().unwrap(), &namespace)
        .create_prepared(
            &request,
            &context,
            &inputs,
            original,
            text(&original.outputs["ready"], "preparation_fingerprint").unwrap(),
            now().unwrap(),
        )
        .await
        .unwrap()
}

async fn interrupt_worker(
    running: Running,
    listener: tokio::net::TcpListener,
    shutdown: tokio::sync::watch::Receiver<bool>,
    original: &Operation,
    scenario: &str,
) {
    use axum::body::{Body, to_bytes};
    use hyper_util::rt::TokioIo;
    use std::time::Duration;

    let host = Arc::clone(&running.host);
    let address = listener.local_addr().unwrap();
    let preparation = original.command.value();
    let run = original.request.reserved_run_id();
    let recover_cancellation = scenario == "recover-cancel";
    let phase = match scenario {
        "worker-exit-before-claim" => "before_claim",
        "worker-exit-during-execution" => "after_first_step",
        "worker-exit-after-candidate" => "candidate_ready",
        "worker-exit-during-insert" => "member_inserted",
        _ => "before_produce",
    };
    let request = |request: http::Request<Body>| async move {
        let stream = tokio::net::TcpStream::connect(address).await.unwrap();
        let (mut sender, connection) = hyper::client::conn::http1::handshake(TokioIo::new(stream))
            .await
            .unwrap();
        let client = tokio::spawn(connection);
        let (response, body) = sender.send_request(request).await.unwrap().into_parts();
        let body = to_bytes(Body::new(body), 8 << 20).await.unwrap();
        drop(sender);
        client.await.unwrap().unwrap();
        (response, body)
    };
    let drive_worker = async {
        let interrupted = worker::gate(&run, phase);
        let paused = worker::gate(&run, "pause_requested");
        let (navigation, _) = request(
            http::Request::builder()
                .uri("/")
                .header("host", address.to_string())
                .header("accept", "text/html")
                .header("sec-fetch-mode", "navigate")
                .header("sec-fetch-dest", "document")
                .header("sec-fetch-site", "none")
                .body(Body::empty())
                .unwrap(),
        )
        .await;
        assert_eq!(navigation.status, http::StatusCode::OK);
        let cookie = navigation.headers[http::header::SET_COOKIE]
            .to_str()
            .unwrap()
            .split(';')
            .next()
            .unwrap();
        let post = |path: String, command: &str, body: serde_json::Value| {
            let message = http::Request::builder()
                .method("POST")
                .uri(path)
                .header("host", address.to_string())
                .header("origin", format!("http://{address}"))
                .header("cookie", cookie)
                .header("idempotency-key", command)
                .header("content-type", "application/json")
                .body(Body::from(body.to_string()))
                .unwrap();
            async move {
                let (response, body) = request(message).await;
                assert_eq!(response.status, http::StatusCode::OK, "{}", String::from_utf8_lossy(&body));
                serde_json::from_slice::<serde_json::Value>(&body).unwrap()
            }
        };
        let accepted = post(
            format!("/api/v2/backtest/preparations/{preparation}/submit"),
            original.request.future_command(),
            serde_json::json!({
                "schema_version": 1,
                "preparation_command_id": preparation,
                "preparation_fingerprint": original.outputs["ready"]["preparation_fingerprint"],
            }),
        )
        .await;
        assert_eq!(accepted["state"], "ACCEPTED");
        assert_eq!(accepted["backtest_command_id"], original.request.future_command());
        assert_eq!(accepted["run_id"], run);

        interrupted.entered().await;
        if matches!(phase, "before_claim" | "candidate_ready" | "member_inserted") {
            if phase == "candidate_ready" {
                worker::expire_original(&run).await;
            }
            println!("BACKTEST_EXIT_AT {scenario} {run}");
            std::io::Write::flush(&mut std::io::stdout()).unwrap();
            std::process::exit(86);
        }
        assert!(host.admitted());
        host.backtest_wake.get().unwrap().stop();
        paused.entered().await;
        if recover_cancellation {
            {
                let namespace = namespace(&host.research_preparation_config).unwrap();
                let mut held = host.writer.lock().await;
                let mut runs = Backtests::new(held.as_mut().unwrap(), &namespace);
                let original_run = runs.load(&run).await.unwrap();
                assert_eq!(original_run.state().as_str(), "RUNNING");
                worker::expire_original(&run).await;
                assert!(runs.expire(&original_run, now().unwrap()).await.unwrap().is_some());
            }
            let cancel = child_command(&original.command, "backtest-recovery-cancel").unwrap();
            let requested = post(
                format!("/api/v2/backtest/runs/{run}/cancellation"),
                cancel.value(),
                serde_json::json!({"schema_version": 1, "run_id": run}),
            )
            .await;
            assert_eq!(requested["run_id"], run);
            assert_eq!(requested["state"], "CANCEL_REQUESTED");
        }
        assert!(host.admitted(), "Worker has not exited while the interruption is held");
        drop(interrupted);
    };
    let (closed, ()) = tokio::time::timeout(Duration::from_secs(60), async {
        tokio::join!(running.serve(listener, shutdown), drive_worker)
    })
    .await
    .expect("Host must drain its Backtest Worker");
    assert_eq!(closed.unwrap_err().code(), "BACKTEST_SERVICE_UNAVAILABLE");
    assert!(!host.admitted());
    assert!(host.backtest_drained.load(Ordering::Acquire));
    assert!(host.writer.lock().await.is_none());
    assert!(tokio::net::TcpStream::connect(address).await.is_err());
    if !recover_cancellation {
        worker::expire_original(&run).await;
    }
}

/// Locators identify facts produced by the unchanged Shipping HTTP fixture.
/// Every opaque owner is reopened here, never supplied by serialized test data.
pub async fn run_owner_scenario(
    config: NodeConfiguration,
    preparation: &CommandId,
    fresh: Option<&CommandId>,
    scenario: &str,
) {
    let configuration = Configuration {
        research_root: config.user_data.join("research"),
        runtime_root: config.user_data.join("runtime"),
        algorithms_root: config.algorithms.clone(),
        native_version: env!("CARGO_PKG_VERSION").into(),
    };
    if scenario == "recover-published" {
        let namespace = crate::bootstrap::deployment::load_semantic_store_id(
            &configuration
                .research_root
                .join(".onlyalpha-semantic-store.json"),
        )
        .unwrap();
        let (mut connection, writer) =
            crate::bootstrap::workstation_startup::test_backtest_owner(&config, &namespace)
                .await
                .unwrap();
        let run = {
            let mut held = writer.lock().await;
            let original = crate::persistence::research_preparation::Preparations::new(
                held.as_mut().unwrap().client_mut().await.unwrap(),
            )
            .query(preparation, "local-developer")
            .await
            .unwrap();
            let run = Backtests::new(held.as_mut().unwrap(), &namespace)
                .load(&original.request.reserved_run_id())
                .await
                .unwrap();
            assert_eq!(
                run.resolution()["runtime_work_binding"]["reason"],
                original.request.future_command()
            );
            run
        };
        let denied = crate::persistence::backtest_run::read_product_snapshot(
            connection.client_mut().await.unwrap(),
            &namespace,
            run.run_id(),
            "another-backtest-owner",
        ).await;
        assert!(matches!(denied, Err("BACKTEST_RUN_NOT_FOUND")));
        worker::recover_published(
            connection,
            writer.clone(),
            crate::workers::source_sessions::SourceSessions::new(|| async {
                Err(crate::application::source_access::Error::ProofUnavailable)
            }),
            Arc::new(crate::persistence::market_data::ClickHouse::new(config.clickhouse).unwrap()),
            configuration,
            run,
            clock,
        )
        .await;
        writer.lock().await.take().unwrap().close().await.unwrap();
        return;
    }
    let fault_paths = (scenario == "resolve-unknown-commits")
        .then(|| (config.user_data.clone(), config.schema.clone()));
    let listener = tokio::net::TcpListener::bind(config.listen).await.unwrap();
    let (stop, shutdown) = tokio::sync::watch::channel(false);
    let retired_store = config.user_data.join("backtest");
    assert!(!retired_store.exists());
    let running = Running::open(config, &shutdown).await.unwrap();
    assert!(!retired_store.exists());
    let host = &Arc::clone(&running.host);
    {
        let mut held = host.writer.lock().await;
        let pid: i32 = held
            .as_mut()
            .unwrap()
            .client_mut()
            .await
            .unwrap()
            .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
            .await
            .unwrap()
            .get(0);
        println!("BACKTEST_OWNER_PID {pid}");
        std::io::Write::flush(&mut std::io::stdout()).unwrap();
    }
    if scenario == "read-publication-withdrawal" {
        let original = host.preparation_query(preparation, "local-developer").await.unwrap();
        assert_eq!(original.state, State::Ready);
        let run = original.request.reserved_run_id();
        crate::security::ingress::assert_backtest_artifact_withdrawal(
            &running.ingress,
            listener.local_addr().unwrap(),
            &run,
        )
        .await;
        stop.send_replace(true);
        running.serve(listener, shutdown).await.unwrap();
        assert!(host.writer.lock().await.is_none());
        println!("BACKTEST_WITHDRAWAL_FENCED {run}");
        return;
    }
    if matches!(
        scenario,
        "worker-exit"
            | "worker-exit-before-claim"
            | "worker-exit-during-execution"
            | "worker-exit-after-candidate"
            | "worker-exit-during-insert"
            | "recover-cancel"
            | "missing-program"
            | "missing-market-seal"
            | "missing-market-row"
    ) {
        let original = host.preparation_query(preparation, "local-developer").await.unwrap();
        assert_eq!(original.state, State::Ready);
        interrupt_worker(running, listener, shutdown, &original, scenario).await;
        return;
    }
    // No Run exists yet. Positively drain original workers before creating it,
    // so only the scenario's concrete Service can claim the new original row.
    {
        let mut original = host.research.lock().await;
        original.as_mut().unwrap().drain().await.unwrap();
        original.take();
        host.research_drained.store(true, Ordering::Release);
    }
    if scenario != "windows" {
        let mut original = host.backtest.lock().await;
        original.as_mut().unwrap().drain().await.unwrap();
        original.take();
        host.backtest_drained.store(true, Ordering::Release);
    }
    // The actual Node's generated Owner credential, admitted by its authority.
    let navigation = http::Request::builder()
        .uri("/")
        .header("host", "127.0.0.1:5173")
        .header("accept", "text/html")
        .header("sec-fetch-mode", "navigate")
        .header("sec-fetch-dest", "document")
        .header("sec-fetch-site", "none")
        .body(())
        .unwrap();
    let cookie = match host.human_access.admit(&navigation).unwrap() {
        human_access::Admission::Navigation(cookie) => cookie
            .to_str()
            .unwrap()
            .split(';')
            .next()
            .unwrap()
            .to_owned(),
        _ => panic!("normal navigation must issue the actual Node Owner cookie"),
    };
    let message = http::Request::builder()
        .uri("/api/v2/integration-types")
        .header("host", "127.0.0.1:5173")
        .header("cookie", cookie)
        .body(())
        .unwrap();
    let human_access::Admission::Owner(human) = host.human_access.admit(&message).unwrap() else {
        panic!("original Node Owner required");
    };
    let original = host
        .preparation_query(preparation, human.subject_id().unwrap())
        .await
        .unwrap();
    assert_eq!(original.state, State::Ready);
    if scenario == "windows" {
        super::ready_http_with_original_writer_held(&running, &listener, preparation).await;
    }
    let run = create_original(host, &human, &original).await;
    let source = original.source().unwrap();
    let (authority, session, selection) = host
        .preparation_sources(&human, &source, true)
        .await
        .unwrap();
    let permission_context = backtest_run::Context {
        human_authority: &host.human_access,
        human: &human,
        source_authority: &authority,
        source: &session,
        selection: &selection,
    };
    if let Some((user_data, schema)) = fault_paths {
        let cancel = child_command(preparation, "backtest-cancel-after-final-heartbeat").unwrap();
        stop.send_replace(true);
        running.serve(listener, shutdown).await.unwrap();
        worker::resolve_unknown_commits(
            crate::bootstrap::workstation_startup::FaultedBacktestOwner {
                database: &host.database,
                user_data: &user_data,
                schema: &schema,
            },
            host.worker_sources(),
            host.clickhouse.clone(),
            configuration,
            &run,
            clock,
            &permission_context,
            cancel,
        ).await;
        return;
    }
    if scenario == "memory-completion" {
        let mut reader = host.reader.lock().await;
        producer::memory_completion(
            reader.as_mut().unwrap(),
            &run,
            &original,
            &configuration,
            &session,
            &selection,
            &host.clickhouse,
        )
        .await;
    } else if scenario == "windows" {
        let fresh = host
            .preparation_query(fresh.unwrap(), human.subject_id().unwrap())
            .await
            .unwrap();
        assert_eq!(fresh.state, State::Ready);
        super::stopped_worker_preserves_accepted_replay_and_refuses_new_submission(
            host, &human, &original, &fresh,
        )
        .await;
    } else {
        let namespace = run.namespace();
        let following = if matches!(scenario, "expiry-before-finalization" | "expiry-before-recovery-publication" | "lost-guard") {
            let prepared = host
                .preparation_query(fresh.unwrap(), human.subject_id().unwrap())
                .await
                .unwrap();
            assert_eq!(prepared.state, State::Ready);
            let following = create_original(host, &human, &prepared).await;
            let mut reader = host.reader.lock().await;
            let order = crate::persistence::backtest_run::pending_native_run_ids(
                reader.as_mut().unwrap(),
                namespace,
            )
            .await
            .unwrap();
            assert_eq!(order, [run.run_id(), following.run_id()]);
            Some(following)
        } else {
            None
        };
        let connect = || async {
            let mut held = host.writer.lock().await;
            let pid = held
                .as_mut()
                .unwrap()
                .client_mut()
                .await
                .unwrap()
                .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
                .await
                .unwrap()
                .get(0);
            host.database
                .research_connection(namespace, pid, host.writer_live.clone())
                .await
                .unwrap()
        };
        let connection = connect().await;
        let cancel = child_command(preparation, "technical-cancel").unwrap();
        match scenario {
            "finite-publication" => {
                worker::finite_publication(
                    connection,
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    run.clone(),
                    clock,
                )
                .await;
            }
            "queued-cancel" => {
                worker::request_and_replay_cancel(&host.writer, &run, &permission_context, cancel, now().unwrap()).await;
                let cancelled = {
                    let mut held = host.writer.lock().await;
                    Backtests::new(held.as_mut().unwrap(), namespace).load(run.run_id()).await.unwrap()
                };
                worker::queued_cancel(
                    connection,
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    cancelled,
                    clock,
                )
                .await;
            }
            "shutdown-resume" | "attempts-exhausted" => {
                let expected_attempts = if scenario == "attempts-exhausted" { 3 } else { 1 };
                let mut connection = connection;
                for attempt in 1..=expected_attempts {
                    worker::shutdown_pause(
                        connection,
                        host.writer.clone(),
                        host.worker_sources(),
                        host.clickhouse.clone(),
                        configuration.clone(),
                        &run,
                        attempt,
                        clock,
                    )
                    .await;
                    if attempt == expected_attempts {
                        break;
                    }
                    worker::expire_original(run.run_id()).await;
                    connection = connect().await;
                }
                if scenario == "attempts-exhausted" {
                    worker::expire_original(run.run_id()).await;
                } else {
                    worker::resume_expired(
                        connect().await,
                        host.writer.clone(),
                        host.worker_sources(),
                        host.clickhouse.clone(),
                        configuration,
                        run,
                        clock,
                    )
                    .await;
                }
            }
            "running-cancel" => {
                worker::cancel_running(
                    connection,
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    run.clone(),
                    &permission_context,
                    cancel,
                    clock,
                )
                .await
            }
            "crash-after-publication" => {
                worker::crash_after_publication(
                    connection,
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    run.clone(),
                    clock,
                )
                .await
            }
            "expiry-before-finalization" | "expiry-before-recovery-publication" => {
                worker::expiry_before_finalization(
                    [connection, connect().await],
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    &run,
                    following.as_ref().unwrap(),
                    scenario == "expiry-before-finalization",
                    clock,
                )
                .await;
            }
            "lost-guard" => {
                let mut inspector = host.reader.lock().await;
                worker::lost_original_guard(
                    connection,
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    run.clone(),
                    following.as_ref().unwrap(),
                    inspector.as_mut().unwrap(),
                    clock,
                )
                .await;
            }
            "cleanup-busy" => {
                worker::cleanup_busy_then_stop(
                    connection,
                    host.writer.clone(),
                    host.worker_sources(),
                    host.clickhouse.clone(),
                    configuration,
                    run.clone(),
                    clock,
                )
                .await
            }
            _ => panic!("unknown actual-owner scenario: {scenario}"),
        }
    }
    stop.send_replace(true);
    let closed = running.serve(listener, shutdown).await;
    if scenario == "lost-guard" {
        assert_eq!(closed.unwrap_err().code(), "PRODUCT_AUTHORITY_DRAIN_FAILED");
    } else {
        closed.unwrap();
    }
}
