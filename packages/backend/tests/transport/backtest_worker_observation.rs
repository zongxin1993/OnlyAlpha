//! Worker state is a typed operational observation, independent of Run truth.
use super::*;
use crate::workers::backtest_worker::Status;

#[test]
fn worker_observation_preserves_research_vocabulary_and_exact_optional_fields() {
    let run = "12345678-1234-4234-8234-123456789abc";
    for (actual, want) in [
        (Some(Status::Starting), json!({"state":"STARTING"})),
        (Some(Status::Idle), json!({"state":"IDLE"})),
        (
            Some(Status::Running(run.into())),
            json!({"state":"RUNNING","run_id":run}),
        ),
        (
            Some(Status::Uncertain("BACKTEST_EXECUTION_OWNERSHIP_UNCERTAIN")),
            json!({"state":"UNKNOWN","code":"BACKTEST_EXECUTION_OWNERSHIP_UNCERTAIN"}),
        ),
        (
            Some(Status::Unavailable("BACKTEST_RUNTIME_CLEANUP_PENDING")),
            json!({"state":"UNAVAILABLE","code":"BACKTEST_RUNTIME_CLEANUP_PENDING"}),
        ),
        (Some(Status::Stopped), json!({"state":"STOPPED"})),
        (
            None,
            json!({"state":"UNAVAILABLE","code":"BACKTEST_SERVICE_UNAVAILABLE"}),
        ),
    ] {
        let observation: BacktestWorkerObservation = worker_observation(actual);
        assert_eq!(serde_json::to_value(observation).unwrap(), want);
    }
}

#[test]
fn worker_loss_never_rewrites_run_status_or_publication_availability() {
    let original = json!({"schema_version":1,"run_id":"12345678-1234-4234-8234-123456789abc","strategy_fingerprint":"a".repeat(64),
        "state":"RUNNING","revision":"2","accepted_at":"2025-01-03T00:00:00Z","preparation_command_id":null,
        "report_status":{"state":"PENDING","code":null}});
    let mut view: BacktestRunView = serde_json::from_value(original.clone()).unwrap();
    assert!(
        view.worker_observation.is_none(),
        "the additive observation remains optional"
    );
    view.worker_observation = Some(worker_observation(Some(Status::Unavailable(
        "BACKTEST_SERVICE_UNAVAILABLE",
    ))));
    let mut actual = serde_json::to_value(view).unwrap();
    assert_eq!(
        actual.as_object_mut().unwrap().remove("worker_observation"),
        Some(json!({"state":"UNAVAILABLE","code":"BACKTEST_SERVICE_UNAVAILABLE"}))
    );
    assert_eq!(
        actual, original,
        "operational health must not fabricate FAILED, completion, revision or report facts"
    );
    assert!(
        serde_json::from_value::<BacktestWorkerObservation>(json!({"state":"COMPLETED"})).is_err()
    );
    assert!(
        serde_json::from_value::<BacktestWorkerObservation>(json!({"state":"IDLE","grant":true}))
            .is_err()
    );
}

#[test]
fn new_submission_requires_a_live_worker_but_not_an_idle_worker() {
    for status in [
        Status::Starting,
        Status::Idle,
        Status::Running("12345678-1234-4234-8234-123456789abc".into()),
    ] {
        assert!(require_worker(Some(status)).is_ok());
    }
    for status in [
        None,
        Some(Status::Unavailable("BACKTEST_SERVICE_UNAVAILABLE")),
        Some(Status::Stopped),
        Some(Status::Uncertain("BACKTEST_EXECUTION_OWNERSHIP_UNCERTAIN")),
    ] {
        assert_eq!(
            require_worker(status).unwrap_err().code(),
            "BACKTEST_SERVICE_UNAVAILABLE"
        );
    }
}
