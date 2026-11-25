//! Extraction alone never verifies a PG proof or creates an owning capability.
use super::*;
use serde_json::json;

fn decision() -> Value {
    json!({"schema_version":1,"decision_graph_fingerprint":"a".repeat(64),
        "decision_graph":{"nodes":["retained-original"]},
        "signal_semantics":{"entry":"retained-original"}})
}
fn proof(decision: &Value) -> Value {
    json!({"contract":"ONLYALPHA_CALCULATION_BUILD_PROOF_V1","context":{"decision":decision}})
}

#[test]
fn research_uses_original_certified_decision_without_changing_evidence() {
    let original = decision();
    let prepared = json!({"build_certification":proof(&original)});
    let before = prepared.clone();
    let selected = research_decision(&prepared).unwrap();
    assert!(std::ptr::eq(
        selected,
        &prepared["build_certification"]["context"]["decision"]
    ));
    assert_eq!(selected, &original);
    assert_eq!(prepared, before);
}

#[test]
fn research_never_uses_a_top_level_decision_as_missing_proof_fallback() {
    for prepared in [
        json!({}),
        json!({"decision":decision()}),
        json!({"build_certification":null}),
    ] {
        assert!(research_decision(&prepared).is_err());
    }
}

#[test]
fn research_rejects_missing_null_or_malformed_proof_decision() {
    for value in [
        Value::Null,
        json!([]),
        json!({}),
        json!({"decision_graph":null,"signal_semantics":{}}),
    ] {
        assert!(research_decision(&json!({"build_certification":proof(&value)})).is_err());
    }
}

#[test]
fn manual_uses_current_original_top_level_decision() {
    let original = decision();
    let prepared = json!({"decision":original,"build_certification":proof(&original)});
    let before = prepared.clone();
    let selected = manual_decision(&prepared).unwrap();
    assert!(std::ptr::eq(selected, &prepared["decision"]));
    assert_eq!(prepared, before);
    // An original legacy manual record has no new build certification.
    assert_eq!(
        manual_decision(&json!({"decision":original})).unwrap(),
        &original
    );
}

#[test]
fn manual_never_falls_back_to_nested_or_historical_decision() {
    let original = decision();
    for prepared in [
        json!({"build_certification":proof(&original)}),
        json!({"decision":null,"build_certification":proof(&original)}),
    ] {
        assert!(manual_decision(&prepared).is_err());
    }
}

#[test]
fn manual_rejects_conflicting_graph_signal_or_missing_existing_proof_decision() {
    let original = decision();
    for member in ["decision_graph", "signal_semantics"] {
        let mut changed = original.clone();
        changed[member] = json!({"wrong":"occurrence"});
        assert!(
            manual_decision(&json!({"decision":original,"build_certification":proof(&changed)}))
                .is_err()
        );
    }
    assert!(manual_decision(&json!({"decision":original,"build_certification":null})).is_err());
}

fn valid_economics() -> Value {
    json!({
        "roundtrip_count": 2,
        "economic_result": {
            "run": {"status": "COMPLETED"},
            "execution": {"order_count": 6, "trade_count": 4},
            "runtime_performance": {
                "summary": {
                    "authority": "ACCOUNT",
                    "valuation_count": 124,
                    "return_since_start": "0.10000000",
                    "maximum_drawdown": "-0.08333333",
                    "net_pnl": "1000.50000000",
                    "realized_pnl": "1000.50000000",
                    "unrealized_pnl": "-0.00000000",
                    "fees": "12.34000000",
                    "final_equity": "11000.50000000"
                }
            }
        }
    })
}

#[test]
fn backtest_metrics_extraction_normalizes_owned_scalars_and_allows_explicit_nulls() {
    let extracted = extract_backtest_metrics_from_values(120, 120, &valid_economics()).unwrap();
    assert_eq!(extracted.close_curve_point_count, 120);
    assert_eq!(extracted.valuation_count, 124);
    assert_eq!(extracted.order_count, 6);
    assert_eq!(extracted.fill_count, 4);
    assert_eq!(extracted.roundtrip_count, 2);
    assert_eq!(extracted.return_since_start.as_deref(), Some("0.1"));
    assert_eq!(extracted.maximum_drawdown.as_deref(), Some("-0.08333333"));
    assert_eq!(extracted.net_pnl, "1000.5");
    assert_eq!(extracted.realized_pnl, "1000.5");
    assert_eq!(extracted.unrealized_pnl, "0");
    assert_eq!(extracted.fees, "12.34");
    assert_eq!(extracted.final_equity, "11000.5");

    let mut with_nulls = valid_economics();
    with_nulls["economic_result"]["runtime_performance"]["summary"]["return_since_start"] = Value::Null;
    with_nulls["economic_result"]["runtime_performance"]["summary"]["maximum_drawdown"] = Value::Null;
    let extracted = extract_backtest_metrics_from_values(120, 120, &with_nulls).unwrap();
    assert_eq!(extracted.return_since_start, None);
    assert_eq!(extracted.maximum_drawdown, None);
}

#[test]
fn backtest_metrics_extraction_rejects_mismatched_rows_positive_drawdown_or_corrupt_summary() {
    assert!(extract_backtest_metrics_from_values(120, 119, &valid_economics()).is_err());

    let mut positive_drawdown = valid_economics();
    positive_drawdown["economic_result"]["runtime_performance"]["summary"]["maximum_drawdown"] =
        json!("0.01000000");
    assert!(extract_backtest_metrics_from_values(120, 120, &positive_drawdown).is_err());

    let mut not_completed = valid_economics();
    not_completed["economic_result"]["run"]["status"] = json!("FAILED");
    assert!(extract_backtest_metrics_from_values(120, 120, &not_completed).is_err());

    let mut wrong_authority = valid_economics();
    wrong_authority["economic_result"]["runtime_performance"]["summary"]["authority"] =
        json!("ANALYTICAL");
    assert!(extract_backtest_metrics_from_values(120, 120, &wrong_authority).is_err());

    let mut numeric_not_string = valid_economics();
    numeric_not_string["economic_result"]["runtime_performance"]["summary"]["net_pnl"] = json!(1000.5);
    assert!(extract_backtest_metrics_from_values(120, 120, &numeric_not_string).is_err());

    let mut scientific_string = valid_economics();
    scientific_string["economic_result"]["runtime_performance"]["summary"]["fees"] = json!("1e-2");
    assert!(extract_backtest_metrics_from_values(120, 120, &scientific_string).is_err());
}
