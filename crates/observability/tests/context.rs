//! 跨 await 的操作归属及显式结束；错误归属会使两个 Run 混在同一 trace。
use onlyalpha_observability::{Config, Correlation, Mode, Operation, Session};
mod support;
use support::Buffer;
use tracing::{Instrument, instrument::WithSubscriber};

#[test]
fn long_running_trace_never_reuses_operation_or_parent_identity() {
    let buffer = Buffer::default();
    let session = Session::new(
        Config::new(Mode::Detail, "long-trace", 65536),
        buffer.clone(),
    )
    .unwrap();
    tracing::dispatcher::with_default(session.dispatch(), || {
        let root = Operation::root("backend", "long-lived", Correlation::default());
        root.span().in_scope(|| {
            for _ in 0..20_000 {
                let child = Operation::start("runtime", "short-lived", Correlation::default());
                child.finish("ok", 1, 0);
            }
        });
        root.finish("ok", 20_000, 0);
    });
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    let starts: Vec<_> = rows
        .iter()
        .filter(|row| row["event_kind"] == "operation_start")
        .collect();
    let root = starts
        .iter()
        .find(|row| row["operation"] == "long-lived")
        .unwrap();
    let mut unique = std::collections::BTreeSet::new();
    for row in &starts {
        assert!(
            unique.insert(row["span_id"].as_str().unwrap()),
            "operation identity reused"
        );
        if row["operation"] == "short-lived" {
            assert_eq!(row["parent_span_id"], root["span_id"]);
            assert_eq!(row["trace_id"], root["trace_id"]);
        }
    }
    assert_eq!(starts.len(), 20_001);
}

#[test]
fn resource_markers_keep_origin_dispatch_outside_the_callers_scope() {
    use onlyalpha_observability::Marker;
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Detail, "markers", 64), buffer.clone()).unwrap();
    let op = tracing::dispatcher::with_default(session.dispatch(), || {
        Operation::root("runtime", "hold", Correlation::default())
    });
    op.marker(Marker::LockAcquired);
    op.marker(Marker::LockReleaseBegin);
    op.marker(Marker::LockReleased);
    op.finish("released", 0, 0);
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    let kinds: Vec<_> = rows
        .iter()
        .filter_map(|r| {
            r["event_kind"]
                .as_str()
                .filter(|kind| kind.starts_with("lock_"))
        })
        .collect();
    assert_eq!(
        kinds,
        vec!["lock_acquired", "lock_release_begin", "lock_released"]
    );
    let ids: std::collections::BTreeSet<_> =
        rows.iter().filter_map(|r| r["span_id"].as_str()).collect();
    assert_eq!(ids.len(), 1);
}

#[test]
fn resource_hold_links_current_scope_without_becoming_a_compute_child() {
    let buffer = Buffer::default();
    let session =
        Session::new(Config::new(Mode::Detail, "lock-scope", 64), buffer.clone()).unwrap();
    let hold = tracing::dispatcher::with_default(session.dispatch(), || {
        let source = Operation::root(
            "backend",
            "source",
            Correlation {
                run_id: Some("run".into()),
                command_id: Some("command".into()),
                ..Default::default()
            },
        );
        let hold = source.span().in_scope(|| {
            let hold = Operation::root("runtime", "generation.hold", Correlation::linked_current());
            hold.span().record("lock_type", "shared");
            hold.span().record("device", 12u64);
            hold.span().record("inode", 34u64);
            hold
        });
        source.finish("ok", 1, 0);
        hold
    });
    hold.finish("released", 0, 0);
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    let source = rows
        .iter()
        .find(|r| r["operation"] == "source" && r["event_kind"] == "operation_end")
        .unwrap();
    let hold = rows
        .iter()
        .find(|r| r["operation"] == "generation.hold" && r["event_kind"] == "operation_end")
        .unwrap();
    assert_eq!(hold["run_id"], "run");
    assert_eq!(hold["command_id"], "command");
    assert!(hold.get("parent_span_id").is_none());
    assert_eq!(
        hold["links"],
        format!(
            "{}/{}",
            source["trace_id"].as_str().unwrap(),
            source["span_id"].as_str().unwrap()
        )
    );
    assert_eq!(hold["device"], 12);
    assert_eq!(hold["inode"], 34);
    assert_eq!(hold["lock_type"], "shared");
    assert_ne!(hold["trace_id"], source["trace_id"]);
}

#[tokio::test(flavor = "current_thread")]
async fn cancelled_future_records_incomplete_after_leaving_poll_dispatch() {
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Detail, "cancel", 64), buffer.clone()).unwrap();
    let (started, ready) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(
        async move {
            let op = Operation::root("backend", "job", Correlation::default());
            started.send(()).unwrap();
            std::future::pending::<()>().await;
            op.finish("ok", 1, 0);
        }
        .with_subscriber(session.dispatch().clone()),
    );
    ready.await.unwrap();
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    assert_eq!(
        rows.iter()
            .filter(|r| r["event_kind"] == "operation_abandoned")
            .count(),
        1
    );
    assert_eq!(
        rows.iter()
            .filter(|r| r["event_kind"] == "operation_end")
            .count(),
        0
    );
}

#[test]
fn finish_and_abandon_keep_the_originating_dispatch_after_task_context_has_left() {
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Detail, "origin", 64), buffer.clone()).unwrap();
    let (finished, abandoned) = tracing::dispatcher::with_default(session.dispatch(), || {
        (
            Operation::root("backend", "finished", Correlation::default()),
            Operation::root("backend", "abandoned", Correlation::default()),
        )
    });
    finished.finish("ok", 1, 0);
    drop(abandoned);
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    assert_eq!(
        rows.iter()
            .filter(|r| r["event_kind"] == "operation_end")
            .count(),
        1
    );
    assert_eq!(
        rows.iter()
            .filter(|r| r["event_kind"] == "operation_abandoned")
            .count(),
        1
    );
}

#[tokio::test(flavor = "current_thread")]
async fn concurrent_runs_keep_parent_after_yield_and_blocking_handoff() {
    let buffer = Buffer::default();
    let session = Session::new(
        Config::new(Mode::Detail, "process-one", 128),
        buffer.clone(),
    )
    .unwrap();
    async {
        let mut handles = Vec::new();
        for run in ["run-a", "run-b"] {
            let root = Operation::root(
                "backend",
                "job",
                Correlation {
                    run_id: Some(run.into()),
                    ..Default::default()
                },
            );
            let dispatch = tracing::dispatcher::get_default(Clone::clone);
            handles.push(tokio::spawn(
                async move {
                    async {
                        tokio::task::yield_now().await;
                        let child = Operation::start("runtime", "read", Correlation::default());
                        let span = child.span().clone();
                        tokio::task::spawn_blocking(move || {
                            tracing::dispatcher::with_default(&dispatch, || {
                                span.in_scope(|| {
                                    let nested = Operation::start(
                                        "runtime",
                                        "restore",
                                        Correlation::default(),
                                    );
                                    nested.finish("ok", 1, 4);
                                })
                            })
                        })
                        .await
                        .unwrap();
                        child.finish("ok", 2, 8);
                    }
                    .instrument(root.span().clone())
                    .await;
                    root.finish("ok", 2, 8);
                }
                .with_subscriber(tracing::dispatcher::get_default(Clone::clone)),
            ));
        }
        for handle in handles {
            handle.await.unwrap();
        }
    }
    .with_subscriber(session.dispatch().clone())
    .await;
    let receipt = session.close();
    assert!(receipt.shutdown_complete);
    assert_eq!(receipt.dropped_events, 0);
    let rows = buffer.rows();
    for run in ["run-a", "run-b"] {
        let owned: Vec<_> = rows
            .iter()
            .filter(|r| r["run_id"] == run && r["event_kind"] == "operation_end")
            .collect();
        assert_eq!(owned.len(), 3);
        let root = owned.iter().find(|r| r["operation"] == "job").unwrap();
        let read = owned.iter().find(|r| r["operation"] == "read").unwrap();
        let restore = owned.iter().find(|r| r["operation"] == "restore").unwrap();
        assert_eq!(read["parent_span_id"], root["span_id"]);
        assert_eq!(restore["parent_span_id"], read["span_id"]);
        assert_eq!(root["trace_id"], restore["trace_id"]);
    }
    assert_ne!(
        rows.iter().find(|r| r["run_id"] == "run-a").unwrap()["trace_id"],
        rows.iter().find(|r| r["run_id"] == "run-b").unwrap()["trace_id"]
    );
}

#[test]
fn explicit_end_precedes_last_handle_drop_and_unfinished_operation_is_abandoned() {
    let buffer = Buffer::default();
    let session = Session::new(Config::new(Mode::Detail, "process", 128), buffer.clone()).unwrap();
    let saved = tracing::dispatcher::with_default(session.dispatch(), || {
        let op = Operation::root("backend", "request", Correlation::default());
        let saved = op.span().clone();
        op.finish("failed", 0, 0);
        let abandoned = Operation::root("backend", "cancelled", Correlation::default());
        drop(abandoned);
        saved
    });
    assert!(session.close().shutdown_complete);
    let rows = buffer.rows();
    assert_eq!(
        rows.iter()
            .filter(|r| r["event_kind"] == "operation_end")
            .count(),
        1
    );
    assert!(
        rows.iter()
            .any(|r| r["event_kind"] == "operation_abandoned")
    );
    assert!(rows.iter().any(|r| r["outcome"] == "failed"));
    drop(saved);
}

#[test]
fn background_root_links_request_across_process_restart_without_fake_parent() {
    for instance in ["before-restart", "after-restart"] {
        let buffer = Buffer::default();
        let session =
            Session::new(Config::new(Mode::Detail, instance, 128), buffer.clone()).unwrap();
        tracing::dispatcher::with_default(session.dispatch(), || {
            let request = Operation::root("backend", "accepted", Correlation::default());
            request.span().in_scope(|| {
                let job = Operation::root(
                    "backend",
                    "job",
                    Correlation {
                        command_id: Some("command".into()),
                        run_id: Some("run".into()),
                        links: Some("accepted-request-trace/span".into()),
                        ..Default::default()
                    },
                );
                job.finish("ok", 1, 0);
            });
            request.finish("accepted", 1, 0);
        });
        assert!(session.close().shutdown_complete);
        let rows = buffer.rows();
        let job = rows.iter().find(|r| r["operation"] == "job").unwrap();
        assert_eq!(job["process_instance_id"], instance);
        assert!(job.get("parent_span_id").is_none());
        assert_eq!(job["links"], "accepted-request-trace/span");
        assert_eq!(job["command_id"], "command");
    }
}
