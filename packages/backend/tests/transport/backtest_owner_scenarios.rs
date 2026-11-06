//! Test-only consumer of original READY/Run owners; no DTO can mint a grant.
use super::*;
use crate::{
    application::backtest_run::{CancelRequest, VerifiedCompletion, VerifiedRun},
    bootstrap::workstation_startup::{Configuration as NodeConfiguration, Running},
    persistence::{
        backtest_evidence, backtest_run::Backtests, research_preparation::child_command,
    },
    workers::{
        backtest_service::{Configuration, StartMode},
        backtest_service_tests as producer,
        backtest_worker::tests as worker,
    },
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use std::{path::PathBuf, sync::atomic::Ordering};

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

/// Locators identify facts produced by the unchanged Shipping HTTP fixture.
/// Every opaque owner is reopened here, never supplied by serialized test data.
pub async fn run_owner_scenario(
    config: NodeConfiguration,
    preparation: &CommandId,
    fresh: Option<&CommandId>,
    scenario: &str,
    external_files: &[PathBuf],
) {
    let configuration = Configuration {
        backtest_root: config.user_data.join("backtest"),
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
            Backtests::new(held.as_mut().unwrap(), &namespace)
                .load(&original.request.reserved_run_id())
                .await
                .unwrap()
        };
        let context = backtest_evidence::read_context(
            connection.client_mut().await.unwrap(),
            &namespace,
            &configuration.research_root,
            &configuration.runtime_root,
            run.run_id(),
            Some(run.owner()),
        )
        .await
        .unwrap();
        assert_eq!(context.original_operation().command, *preparation);
        context.verify_cut().unwrap();
        drop(context);
        worker::recover_published(connection, writer.clone(), configuration, run, clock).await;
        writer.lock().await.take().unwrap().close().await.unwrap();
        return;
    }
    let listener = tokio::net::TcpListener::bind(config.listen).await.unwrap();
    let (stop, shutdown) = tokio::sync::watch::channel(false);
    let running = Running::open(config, &shutdown).await.unwrap();
    let host = &running.host;
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
    if scenario == "windows" {
        let fresh = host
            .preparation_query(fresh.unwrap(), human.subject_id().unwrap())
            .await
            .unwrap();
        assert_eq!(fresh.state, State::Ready);
        super::stopped_worker_preserves_accepted_replay_and_refuses_new_submission(
            host, &human, &original, &fresh,
        )
        .await;
    } else if matches!(scenario, "full-interval-evidence" | "pause-cancel") {
        let worker_id = child_command(preparation, "technical-worker").unwrap();
        let attempt = child_command(preparation, "technical-attempt").unwrap();
        let mut reader = host.reader.lock().await;
        let client = reader.as_mut().unwrap();
        let runtime = configuration
            .backtest_root
            .join("runtime")
            .join(run.run_id());
        assert!(!runtime.exists());
        // Resume on a fresh Run cannot create its journal or change its state.
        producer::refuse_mode(client, &run, &original, &configuration, StartMode::Resume).await;
        assert!(!runtime.exists());
        let joined = if scenario == "full-interval-evidence" {
            producer::whole_interval(client, &run, &original, &configuration).await
        } else {
            producer::pause_after_open_then_cancel(client, &run, &original, &configuration).await
        };
        let context = backtest_evidence::read_context(
            client,
            run.namespace(),
            &configuration.research_root,
            &configuration.runtime_root,
            run.run_id(),
            Some(run.owner()),
        )
        .await
        .unwrap();
        let store = backtest_evidence::Store::open(
            &configuration.backtest_root,
            &configuration.research_root,
            &configuration.runtime_root,
        )
        .unwrap();
        let proof = backtest_evidence::owner_tests::commit_and_reopen(
            &store,
            &context,
            joined,
            &configuration.backtest_root,
        );
        let proof = VerifiedCompletion::from_proof(proof).unwrap();
        // Producer-only scenarios prove Work/Joined/publication separately from
        // scheduler claims. Acquire the actual SQL Claim immediately before its
        // terminal commit; long publication corruption checks cannot expire it.
        let mut claim = {
            let mut held = host.writer.lock().await;
            Backtests::new(held.as_mut().unwrap(), run.namespace())
                .claim(&run, worker_id.value(), attempt.value(), now().unwrap())
                .await
                .unwrap()
                .unwrap()
        };
        {
            let mut held = host.writer.lock().await;
            let mut backtests = Backtests::new(held.as_mut().unwrap(), run.namespace());
            if scenario == "pause-cancel" {
                backtests
                    .request_cancel(
                        &CancelRequest::new(
                            child_command(preparation, "technical-cancel").unwrap(),
                            run.run_id(),
                        )
                        .unwrap(),
                        &permission_context,
                        now().unwrap(),
                    )
                    .await
                    .unwrap();
                backtests
                    .cancel(&mut claim, &proof, now().unwrap())
                    .await
                    .unwrap();
            } else {
                backtests
                    .complete(&mut claim, &proof, now().unwrap())
                    .await
                    .unwrap();
            }
        }
        drop(context);
        let context = backtest_evidence::read_context(
            client,
            run.namespace(),
            &configuration.research_root,
            &configuration.runtime_root,
            run.run_id(),
            Some(run.owner()),
        )
        .await
        .unwrap();
        assert!(!external_files.is_empty());
        backtest_evidence::owner_tests::terminal_missing_and_external_tamper(
            &store,
            &context,
            &configuration.backtest_root,
            external_files,
        );
        let journal = runtime.join("runtime.sqlite3");
        let before = std::fs::read(&journal).unwrap();
        producer::refuse_mode(client, &run, &original, &configuration, StartMode::Create).await;
        assert_eq!(std::fs::read(&journal).unwrap(), before);
    } else {
        let namespace = run.namespace();
        let connection = {
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
        let cancel = child_command(preparation, "technical-cancel").unwrap();
        match scenario {
            "queued-cancel" => {
                let cancelled = {
                    let mut held = host.writer.lock().await;
                    let mut backtests = Backtests::new(held.as_mut().unwrap(), namespace);
                    backtests
                        .request_cancel(
                            &CancelRequest::new(cancel, run.run_id()).unwrap(),
                            &permission_context,
                            now().unwrap(),
                        )
                        .await
                        .unwrap();
                    backtests.load(run.run_id()).await.unwrap()
                };
                worker::queued_cancel(
                    connection,
                    host.writer.clone(),
                    configuration,
                    cancelled,
                    clock,
                )
                .await;
            }
            "shutdown-resume" => {
                worker::shutdown_pause(
                    connection,
                    host.writer.clone(),
                    configuration.clone(),
                    run.clone(),
                    clock,
                )
                .await;
                let connection = {
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
                worker::resume_expired(
                    connection,
                    host.writer.clone(),
                    configuration,
                    run.clone(),
                    clock,
                )
                .await;
            }
            "running-cancel" => {
                worker::cancel_running(
                    connection,
                    host.writer.clone(),
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
                    configuration,
                    run.clone(),
                    clock,
                )
                .await
            }
            "lost-guard" => {
                let mut inspector = host.reader.lock().await;
                worker::lost_original_guard(
                    connection,
                    host.writer.clone(),
                    configuration,
                    run.clone(),
                    inspector.as_mut().unwrap(),
                    clock,
                )
                .await;
            }
            "cleanup-busy" => {
                worker::cleanup_busy_then_stop(
                    connection,
                    host.writer.clone(),
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
