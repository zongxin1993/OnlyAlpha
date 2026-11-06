//! Human Product contracts and pure values. No parsed response is an execution grant.
use super::{Operation, declaration, operation};
use crate::{
    application::command::CommandId,
    transport::research_wire::{
        QualificationCommandView, QualificationDecisionReadView, QualificationInput,
        QualificationResumeInput, QualifiedPromotionCommandView, QualifiedPromotionInput,
    },
};
use http::Method;
use serde_json::{Value, json};
const COMMAND: &str = "00000000-0000-4000-8000-000000009101";
const RUN: &str = "00000000-0000-4000-8000-000000009102";
#[test]
fn qualification_product_routes_expose_exact_human_reads_and_original_command_recovery() {
    let (_, document) = declaration();
    let doc = serde_json::to_value(document).unwrap();
    for (method, path, verb, response, input) in [
        (
            Method::GET,
            "/api/v2/qualification-policies",
            "get",
            "QualificationPolicyListView",
            None,
        ),
        (
            Method::GET,
            "/api/v2/qualification-policies/{policy_id}/revisions/{policy_version}",
            "get",
            "QualificationPolicyView",
            None,
        ),
        (
            Method::GET,
            "/api/v2/qualification-decisions/{decision_fingerprint}",
            "get",
            "QualificationDecisionReadView",
            None,
        ),
        (
            Method::GET,
            "/api/v2/strategies/{strategy_fingerprint}",
            "get",
            "StrategyQualifiedView",
            None,
        ),
        (
            Method::GET,
            "/api/v2/strategies/{strategy_fingerprint}/qualification-decisions",
            "get",
            "QualificationCommandListView",
            None,
        ),
        (
            Method::POST,
            "/api/v2/strategies/{strategy_fingerprint}/qualifications",
            "post",
            "QualificationCommandView",
            Some("QualificationInput"),
        ),
        (
            Method::GET,
            "/api/v2/strategies/{strategy_fingerprint}/qualifications/commands/{command_id}",
            "get",
            "QualificationCommandView",
            None,
        ),
        (
            Method::POST,
            "/api/v2/strategies/{strategy_fingerprint}/qualifications/commands/{command_id}/resume",
            "post",
            "QualificationCommandView",
            Some("QualificationResumeInput"),
        ),
        (
            Method::POST,
            "/api/v2/strategies/{strategy_fingerprint}/qualification-promotions",
            "post",
            "QualifiedPromotionCommandView",
            Some("QualifiedPromotionInput"),
        ),
        (
            Method::GET,
            "/api/v2/strategies/{strategy_fingerprint}/qualification-promotions/commands/{command_id}",
            "get",
            "QualifiedPromotionCommandView",
            None,
        ),
        (
            Method::POST,
            "/api/v2/strategies/{strategy_fingerprint}/qualification-promotions/commands/{command_id}/resume",
            "post",
            "QualifiedPromotionCommandView",
            Some("QualifiedPromotionInput"),
        ),
    ] {
        assert_eq!(
            operation(&method, path),
            Some(Operation::Implemented),
            "{method} {path}"
        );
        let actual = &doc["paths"][path][verb];
        assert_eq!(actual["security"], json!([{"LocalDeveloperCookie":[]}]));
        assert_eq!(
            actual["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],
            format!("#/components/schemas/{response}")
        );
        assert!(actual["responses"].get("501").is_none());
        for status in ["400", "401", "403", "409", "503"] {
            assert_eq!(
                actual["responses"][status]["content"]["application/json"]["schema"]["$ref"],
                "#/components/schemas/NativeErrorEnvelope"
            );
        }
        if let Some(input) = input {
            assert_eq!(
                actual["requestBody"]["content"]["application/json"]["schema"]["$ref"],
                format!("#/components/schemas/{input}")
            );
            assert!(
                actual["parameters"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .any(|p| p["in"] == "header"
                        && p["name"] == "Idempotency-Key"
                        && p["required"] == true)
            );
        }
        assert_eq!(operation(&Method::DELETE, path), None);
    }
    assert_eq!(
        operation(
            &Method::POST,
            "/api/v2/strategies/{strategy_fingerprint}/promotions"
        ),
        Some(Operation::Deferred),
        "a raw append cannot bypass Qualification"
    );
    let exact = &doc["paths"]["/api/v2/qualification-decisions/{decision_fingerprint}"]["get"];
    assert!(
        exact["parameters"]
            .as_array()
            .unwrap()
            .iter()
            .any(|p| p["in"] == "query"
                && p["name"] == "research_run_id"
                && p["required"] == false),
        "an explicit read locator may resolve ambiguity without changing Decision identity"
    );
}
fn input() -> Value {
    json!({"schema_version":1,"research_run_id":RUN,"freeze_relation_fingerprint":"b".repeat(64),"policy_id":"experimental-backtest","policy_version":"1"})
}
#[test]
fn qualification_inputs_accept_locators_and_policy_choices_but_refuse_caller_conclusions() {
    let subject = "a".repeat(64);
    let original = input();
    let parsed: QualificationInput = serde_json::from_value(original.clone()).unwrap();
    parsed.validate(&subject).unwrap();
    assert_eq!(serde_json::to_value(parsed).unwrap(), original);
    for (key, value) in [
        ("research_run_id", json!("latest")),
        ("freeze_relation_fingerprint", json!("b".repeat(63))),
        ("policy_id", json!("../experimental-backtest")),
        ("policy_version", json!("latest")),
        ("policy_version", json!("01")),
        ("schema_version", json!(2)),
    ] {
        let mut bad = original.clone();
        bad[key] = value;
        assert!(
            serde_json::from_value::<QualificationInput>(bad)
                .map(|v| v.validate(&subject).is_err())
                .unwrap_or(true),
            "{key}"
        );
    }
    for key in [
        "counts",
        "scalars",
        "evidence",
        "observed_value",
        "outcome",
        "APPROVED",
        "to_stage",
        "qualified",
        "run_permit",
    ] {
        let mut bad = original.clone();
        bad[key] = json!(true);
        assert!(
            serde_json::from_value::<QualificationInput>(bad).is_err(),
            "{key}"
        );
    }
    let resume = json!({"schema_version":1,"research_run_id":RUN});
    serde_json::from_value::<QualificationResumeInput>(resume.clone())
        .unwrap()
        .validate()
        .unwrap();
    for key in [
        "policy_id",
        "policy_version",
        "freeze_relation_fingerprint",
        "evidence",
        "outcome",
    ] {
        let mut bad = resume.clone();
        bad[key] = json!("replacement");
        assert!(
            serde_json::from_value::<QualificationResumeInput>(bad).is_err(),
            "resume must restore original {key}"
        );
    }
    let mut promotion = original;
    promotion["qualification_decision_fingerprint"] = json!("c".repeat(64));
    promotion["reason"] = json!("实验性回测；仅验证证据完整性");
    serde_json::from_value::<QualifiedPromotionInput>(promotion.clone())
        .unwrap()
        .validate(&subject)
        .unwrap();
    for key in [
        "outcome",
        "decision",
        "to_stage",
        "from_stage",
        "policy_fingerprint",
        "count",
        "scalar",
        "SIM",
        "LIVE",
    ] {
        let mut bad = promotion.clone();
        bad[key] = json!("APPROVED");
        assert!(
            serde_json::from_value::<QualifiedPromotionInput>(bad).is_err(),
            "{key}"
        );
    }
}
#[test]
fn original_command_projection_and_locator_required_view_do_not_fabricate_approved_facts() {
    let value = json!({"schema_version":1,"command_id":COMMAND,"strategy_fingerprint":"a".repeat(64),"state":"PREPARED",
        "request":{"subject_strategy_fingerprint":"a".repeat(64),"policy_id":"experimental-backtest","policy_version":"1",
            "evidence":[{"kind":"RESEARCH_RESULT","evidence_fingerprint":"b".repeat(64),"locator_fingerprint":"c".repeat(64),"subject_binding_fingerprint":"d".repeat(64)}]},
        "prepared_at":"2026-11-02T00:00:00.123456Z","completed_at":null,"decision_fingerprint":null});
    assert_eq!(
        serde_json::to_value(
            serde_json::from_value::<QualificationCommandView>(value.clone()).unwrap()
        )
        .unwrap(),
        value
    );
    let ambiguous = json!({"schema_version":1,"decision_fingerprint":"e".repeat(64),"state":"LOCATOR_REQUIRED","decision":null,
        "research_run_id":null,"research_run_candidates":[RUN,"00000000-0000-4000-8000-000000009103"]});
    assert_eq!(
        serde_json::to_value(
            serde_json::from_value::<QualificationDecisionReadView>(ambiguous.clone()).unwrap()
        )
        .unwrap(),
        ambiguous
    );
    let unknown = json!({"schema_version":1,"command_id":COMMAND,"strategy_fingerprint":"a".repeat(64),"state":"OUTCOME_UNKNOWN","record":null});
    assert_eq!(
        serde_json::to_value(
            serde_json::from_value::<QualifiedPromotionCommandView>(unknown.clone()).unwrap()
        )
        .unwrap(),
        unknown
    );
    for (record, name) in [
        (value, "qualification"),
        (ambiguous, "locator"),
        (unknown, "promotion"),
    ] {
        let mut bad = record;
        bad["execution_permit"] = json!(true);
        let rejected = match name {
            "qualification" => serde_json::from_value::<QualificationCommandView>(bad).is_err(),
            "locator" => serde_json::from_value::<QualificationDecisionReadView>(bad).is_err(),
            _ => serde_json::from_value::<QualifiedPromotionCommandView>(bad).is_err(),
        };
        assert!(rejected);
    }
    assert!(CommandId::new(COMMAND).is_ok());
}
#[test]
fn startup_experimental_policy_is_exact_evidence_completeness_without_a_profit_claim() {
    let actual = crate::bootstrap::research_namespace::experimental_backtest_policy()
        .unwrap()
        .to_record();
    let mut expected = json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1","gate":"RESEARCH_TO_BACKTEST",
        "missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[
        {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
        {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}]});
    let mut identity = expected.clone();
    identity["domain"] = json!("onlyalpha.strategy.qualification-policy");
    expected["policy_fingerprint"] =
        json!(crate::application::factor_content::hash(&identity).unwrap());
    assert_eq!(actual, expected);
}
