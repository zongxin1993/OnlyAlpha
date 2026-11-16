use crate::application::finite_job::{fact_axis_rule, member_schema, plan_members};
use crate::application::job_contract::{JobKind, MemberKind, ResultPlan};
use serde_json::json;
#[test]
fn original_market_occurrence_cannot_be_replaced_by_equal_dataset_content() {
    let (binding, _) = fixture();
    let original = json!({"market_data_revision_bindings":[{"source_id":"source-a","instrument_id":"A.X","data_kind":"BAR","revision_id":"original","revision_fingerprint":"a".repeat(64)}]});
    assert!(super::owners::check_market_origin(&binding, &original).is_ok());
    for replacement in [
        json!([]),
        json!([{"revision_fingerprint":"b".repeat(64)}]),
        json!([
            original["market_data_revision_bindings"][0],
            original["market_data_revision_bindings"][0]
        ]),
    ] {
        assert!(
            super::owners::check_market_origin(
                &binding,
                &json!({"market_data_revision_bindings":replacement})
            )
            .is_err()
        );
    }
}
#[test]
fn candidate_errors_keep_unknown_cancellation_budget_and_mismatch_distinct() {
    use crate::application::research_run_execution::Control;
    use crate::persistence::job_publication::PublicationError as P;
    for (error, code) in [
        (P::OutcomeUnknown, "FINITE_JOB_JOIN_UNKNOWN"),
        (P::Conflict, "RESEARCH_EXECUTION_CANCELLED"),
        (P::Mismatch, "FINITE_CANDIDATE_MISMATCH"),
        (P::Integrity, "FINITE_CANDIDATE_MISMATCH"),
        (P::BudgetExceeded, "FINITE_CANDIDATE_BUDGET_EXCEEDED"),
        (P::Unavailable, "FINITE_CANDIDATE_UNAVAILABLE"),
    ] {
        assert_eq!(
            super::owners::candidate_error(error, &Control::default()).code(),
            code
        );
    }
}
#[test]
fn factor_reader_errors_preserve_unavailable_unknown_missing_and_mismatch() {
    use crate::application::factor_build::{BuildError, preparation_error};
    use crate::persistence::job_publication::PublicationError as Storage;
    for (error, code) in [
        (BuildError::NotReady, "PRIVATE_STRATEGY_PROGRAM_NOT_READY"),
        (
            BuildError::Storage(Storage::Unavailable),
            "PRIVATE_STRATEGY_PROGRAM_UNAVAILABLE",
        ),
        (
            BuildError::Unknown,
            "PRIVATE_STRATEGY_PROGRAM_OUTCOME_UNKNOWN",
        ),
        (
            BuildError::Storage(Storage::OutcomeUnknown),
            "PRIVATE_STRATEGY_PROGRAM_OUTCOME_UNKNOWN",
        ),
        (
            BuildError::Storage(Storage::Mismatch),
            "PRIVATE_STRATEGY_PROGRAM_MISMATCH",
        ),
        (
            BuildError::Storage(Storage::Denied),
            "PRIVATE_STRATEGY_PROGRAM_DENIED",
        ),
        (
            BuildError::Storage(Storage::BudgetExceeded),
            "PRIVATE_STRATEGY_PROGRAM_BUDGET_EXCEEDED",
        ),
    ] {
        assert_eq!(preparation_error(error).code(), code);
    }
}
#[test]
fn finite_plan_requires_complete_actual_axes_and_distinct_formats() {
    let axis = json!([["A.X", "1", "2", "2", 1], ["A.X", "2", "3", "3", 1]]);
    for kind in [JobKind::Research, JobKind::Backtest] {
        let plan = plan_members(kind, &axis, &axis, 1).unwrap();
        let checked = ResultPlan::from_record(&plan.record()).unwrap();
        assert_eq!(checked.record(), plan.record());
        for member in checked.members() {
            let record = serde_json::to_value(member).unwrap();
            assert_eq!(record["schema"], member_schema(member.kind()).unwrap());
            if member.kind() == MemberKind::ExecutionFacts {
                assert_eq!(record["axis_rule"], fact_axis_rule().unwrap());
                assert!(record["axis"].is_null());
            }
        }
    }
    assert_ne!(
        member_schema(MemberKind::CalculationValues).unwrap(),
        member_schema(MemberKind::SignalValues).unwrap()
    );
}

// These are pure format observations, deliberately not joined candidates or
// authority fixtures. Owning database/execution tests cover candidate minting.
fn fixture() -> (super::FrozenJobBinding, super::Products) {
    use super::*;
    let full = json!([["A.X", "1", "2", "2", 1], ["A.X", "2", "3", "3", 1]]);
    let sample = json!([["A.X", "2", "3", "3", 1]]);
    let plan = plan_members(JobKind::Backtest, &full, &sample, 0).unwrap();
    let pin = "a".repeat(64);
    let binding=FrozenJobBinding::from_record(&json!({"schema_version":1,"kind":"BACKTEST","scope":{"namespace":"22222222-2222-4222-8222-222222222222","owner":"human:test","run_id":"11111111-1111-4111-8111-111111111111"},"strategy_revision":pin,"signal_graph":pin,"factor_bindings":[],"kernel_artifact":pin,"runtime_generation":pin,"initial_state":pin,"execution_configuration":pin,"calendar":pin,"fees":pin,"market_rules":pin,"market":{"dataset_snapshot":pin,"source_revision":pin,"bar_semantic":pin,"instruments":["A.X"],"start_ns":1,"end_ns":3,"versions":[pin],"seals":[pin],"segments":[pin],"rows":2,"warmup_rows":1,"sample_rows":1,"axis":pin,"content":pin},"result_plan":plan.record()})).unwrap();
    let products = Products {
        sequences: BTreeMap::from([
            (
                MemberKind::ExecutionFacts,
                vec![(
                    json!([1, "OPEN", hash(&json!({"input":"original"})).unwrap()]),
                    json!({"sequence":1,"family":"OPEN","body":{"input":"original"}}),
                )],
            ),
            (
                MemberKind::CloseCurve,
                vec![(sample[0].clone(), json!({"account_sequence":1,"nav":"100"}))],
            ),
        ]),
        roots: BTreeMap::from([(
            MemberKind::EconomicResult,
            json!({"typed_owning_result":"format-only"}),
        )]),
        causal: json!({"format_only":true}),
    };
    (binding, products)
}
#[test]
fn complete_body_inventory_axes_schemas_and_causal_links_are_checked() {
    use super::*;
    let (binding, products) = fixture();
    let values = contents(&binding, products).unwrap();
    assert_eq!(values.len(), 4);
    let cause = &values
        .iter()
        .find(|(m, _)| m.kind() == MemberKind::CausalEvidence)
        .unwrap()
        .1;
    assert_eq!(cause["body"]["members"].as_array().unwrap().len(), 3);
    for (member, body) in &values {
        if member.kind() != MemberKind::CausalEvidence {
            assert!(
                cause["body"]["members"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|r| r["key"] == member.key() && r["content"] == hash(body).unwrap())
            );
        }
    }
    for fault in [
        "missing-body",
        "wrong-axis",
        "wrong-count",
        "wrong-schema",
        "wrong-rule",
        "wrong-body-axis",
    ] {
        let (binding, mut products) = fixture();
        let mut raw = binding.record();
        if fault == "missing-body" {
            products.roots.clear();
        } else if fault == "wrong-body-axis" {
            products
                .sequences
                .get_mut(&MemberKind::ExecutionFacts)
                .unwrap()[0]
                .0 = json!([1, "OPEN", "b".repeat(64)]);
        } else if fault == "wrong-axis" {
            products.sequences.get_mut(&MemberKind::CloseCurve).unwrap()[0].0 =
                json!(["foreign bar"]);
        } else {
            let member = raw["result_plan"]["members"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|m| {
                    m["kind"]
                        == if fault == "wrong-rule" {
                            "EXECUTION_FACTS"
                        } else {
                            "CLOSE_CURVE"
                        }
                })
                .unwrap();
            match fault {
                "wrong-count" => member["rows"] = json!(2),
                "wrong-schema" => member["schema"] = json!("b".repeat(64)),
                _ => member["axis_rule"] = json!("b".repeat(64)),
            };
        }
        assert!(
            contents(&FrozenJobBinding::from_record(&raw).unwrap(), products).is_err(),
            "{fault}"
        );
    }
}

#[test]
fn result_references_use_the_publication_content_budget() {
    let (binding, mut products) = fixture();
    // A result member is governed by the existing 128 MiB publication budget,
    // not the unrelated 8 MiB factor metadata canonicalization work budget.
    products.roots.insert(
        MemberKind::EconomicResult,
        json!({"observation":"x".repeat(9 * 1024 * 1024)}),
    );
    let members =
        super::contents(&binding, products).expect("valid result below publication limit");
    let result = &members
        .iter()
        .find(|(m, _)| m.kind() == MemberKind::EconomicResult)
        .unwrap()
        .1;
    let encoded = crate::persistence::job_publication::encode(result, 128 * 1024 * 1024).unwrap();
    let expected = crate::persistence::job_publication::digest(encoded.as_bytes());
    let cause = &members
        .iter()
        .find(|(m, _)| m.kind() == MemberKind::CausalEvidence)
        .unwrap()
        .1;
    assert!(
        cause["body"]["members"]
            .as_array()
            .unwrap()
            .iter()
            .any(|r| r["key"] == "economic_result" && r["content"] == expected)
    );
}
