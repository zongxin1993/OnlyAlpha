//! Public Shipping reads keep native evidence and human cancellation distinct.
use super::*;

#[test]
fn native_backtest_product_paths_have_typed_human_reads_and_one_cancel_command() {
    let (_, document) = declaration();
    let value = serde_json::to_value(document).unwrap();
    for (method, path, verb, body) in [
        (
            Method::GET,
            "/api/v2/backtest/creation-context",
            "get",
            "BacktestCreationContextV2",
        ),
        (
            Method::GET,
            "/api/v2/backtest/strategy-context",
            "get",
            "ManualStrategyContextView",
        ),
        (
            Method::GET,
            "/api/v2/backtest/runs",
            "get",
            "BacktestRunInventory",
        ),
        (
            Method::GET,
            "/api/v2/backtest/runs/{run_id}",
            "get",
            "BacktestRunView",
        ),
        (
            Method::POST,
            "/api/v2/backtest/runs/{run_id}/cancellation",
            "post",
            "BacktestRunView",
        ),
        (
            Method::GET,
            "/api/v2/backtest/runs/{run_id}/evidence",
            "get",
            "BacktestEvidenceView",
        ),
        (
            Method::GET,
            "/api/v2/backtest/runs/{run_id}/result",
            "get",
            "BacktestResultView",
        ),
    ] {
        assert_eq!(
            operation(&method, path),
            Some(Operation::Implemented),
            "{path}"
        );
        let operation = &value["paths"][path][verb];
        assert_eq!(
            operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            format!("#/components/schemas/{body}")
        );
        assert_eq!(
            operation["security"],
            serde_json::json!([{"LocalDeveloperCookie":[]}])
        );
    }
    assert_eq!(
        operation(&Method::POST, "/api/v2/backtest/runs"),
        Some(Operation::Deferred),
        "the original verified preparation submit remains the sole create boundary"
    );
    assert_eq!(
        operation(
            &Method::GET,
            "/api/v2/backtest/runs/{run_id}/evidence/artifacts/{artifact_name}"
        ),
        Some(Operation::Implemented)
    );
}

#[test]
fn native_backtest_cancellation_input_has_no_evidence_or_execution_authority() {
    use crate::transport::research_wire::BacktestCancellationInput;
    let run = "12345678-1234-4234-8234-123456789abc";
    let good = serde_json::json!({"schema_version":1,"run_id":run});
    assert!(
        serde_json::from_value::<BacktestCancellationInput>(good.clone())
            .unwrap()
            .validate(run)
            .is_ok()
    );
    for key in [
        "state",
        "result",
        "evidence_fingerprint",
        "grant",
        "source_selection",
        "runtime_generation",
    ] {
        let mut forged = good.clone();
        forged[key] = serde_json::json!("caller-value");
        assert!(
            serde_json::from_value::<BacktestCancellationInput>(forged).is_err(),
            "{key}"
        );
    }
    assert!(
        serde_json::from_value::<BacktestCancellationInput>(good)
            .unwrap()
            .validate("12345678-1234-4234-8234-123456789abd")
            .is_err()
    );
}

#[test]
fn normal_backtest_context_defaults_select_a_revision_without_submitting_or_inventing_research() {
    use crate::transport::research_wire::BacktestCreationContextV2;
    let good = serde_json::json!({"schema_version":2,"strategy_name":"BTC 价量动量","input_defaults":{"schema_version":2,"profile":"BTC_SPOT_NEXT_OPEN_BACKTEST_V1","origin":{"kind":"MANUAL_STRATEGY","strategy_id":"private.strategy.btc_momentum","strategy_revision_fingerprint":"a".repeat(64)},"release_manifest_fingerprint":"b".repeat(64),"expected_active_generation":null,"initialize_fresh_runtime":false},"sample_start_at":"2025-01-03T00:00:00Z","sample_end_at":"2025-01-03T12:00:00Z","initial_cash":"10000","quantity":"0.01","fee_bps":10,"slippage_bps":2,"limitations":[],"existing_preparations":[]});
    let parsed = serde_json::from_value::<BacktestCreationContextV2>(good.clone()).unwrap();
    assert_eq!(serde_json::to_value(parsed).unwrap(), good);
    for key in [
        "research_run_id",
        "study_proposal_fingerprint",
        "source",
        "backtest_command_id",
        "qualification_decision_fingerprint",
    ] {
        let mut forged = good.clone();
        forged["input_defaults"][key] = serde_json::json!("not-owner-authority");
        assert!(
            serde_json::from_value::<BacktestCreationContextV2>(forged).is_err(),
            "{key}"
        );
    }
    let mut missing = good;
    missing["input_defaults"]
        .as_object_mut()
        .unwrap()
        .remove("expected_active_generation");
    assert!(serde_json::from_value::<BacktestCreationContextV2>(missing).is_err());
}
