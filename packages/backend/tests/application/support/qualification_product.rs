//! Product's actual counts and original-command read/recovery seam.
//! Existing completed installed-SDK research is the technical precondition; no cfg seal.
use crate::{
    application::{
        command::CommandId, frozen_strategy::FrozenStore, qualification::Request,
        qualification_policy::Store as Policies,
    },
    bootstrap::deployment,
    persistence::{
        authority_session::AuthoritySession,
        qualification_commands::{self, Qualifications},
        qualification_decision::Store as Decisions,
        research_evidence::Store as Evidence,
        research_submission,
        strategy_promotion::{self, Promotions, Request as PromotionRequest},
    },
    security::{
        human_access::{Access, Admission},
        protected_files,
    },
};
use serde_json::{Value, json};
use std::{os::fd::AsFd, path::Path, sync::Arc};
const OWNER: &str = "local-developer";
const WORK: usize = 64 * 1024 * 1024;
fn text<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap()
}
fn command(v: &Value, k: &str) -> CommandId {
    CommandId::new(text(v, k)).unwrap()
}
fn output(v: Value) {
    println!("QUALIFICATION_PRODUCT_VALUE {v}");
    std::io::Write::flush(&mut std::io::stdout()).unwrap();
}
pub(super) async fn run_phase(session: &mut AuthoritySession, root: &Path, phase: &str) {
    let request: Value = serde_json::from_slice(
        &std::fs::read(std::env::var("ONLYALPHA_QUALIFICATION_PRODUCT_REQUEST").unwrap()).unwrap(),
    )
    .unwrap();
    let fd = protected_files::open_directory(root).unwrap();
    let namespace = deployment::load_semantic_store_id_at(&fd).unwrap();
    let subject = text(&request, "strategy_fingerprint");
    let id = command(&request, "qualification_command");
    if phase == "observe" {
        let before = qualification_commands::command_outcome_readonly(
            session.client_mut().await.unwrap(),
            &namespace,
            subject,
            &id,
        )
        .await
        .unwrap();
        let after = qualification_commands::command_outcome_readonly(
            session.client_mut().await.unwrap(),
            &namespace,
            subject,
            &id,
        )
        .await
        .unwrap();
        assert_eq!(before, after);
        assert!(
            qualification_commands::command_outcome_readonly(
                session.client_mut().await.unwrap(),
                &namespace,
                &"f".repeat(64),
                &id
            )
            .await
            .is_err()
        );
        let wrong =
            deployment::SemanticStoreId::new("22222222-2222-4222-8222-222222222222").unwrap();
        assert!(
            qualification_commands::command_outcome_readonly(
                session.client_mut().await.unwrap(),
                &wrong,
                subject,
                &id
            )
            .await
            .is_err()
        );
        output(before);
        return;
    }
    if phase == "promotion-observe" {
        let id = command(&request, "promotion_command");
        let value = strategy_promotion::promotion_outcome_readonly(
            session.client_mut().await.unwrap(),
            &namespace,
            subject,
            OWNER,
            &id,
        )
        .await
        .unwrap();
        assert!(
            strategy_promotion::promotion_outcome_readonly(
                session.client_mut().await.unwrap(),
                &namespace,
                subject,
                "other-human",
                &id
            )
            .await
            .is_err()
        );
        output(value);
        return;
    }
    // Actual deployment selected Policy, admitted before any retained Count/Runtime hold.
    let policies = Arc::new(Policies::open(fd.as_fd()).unwrap());
    let selected = crate::bootstrap::research_namespace::experimental_backtest_policy().unwrap();
    policies
        .admit(session, &namespace, &[selected], WORK)
        .await
        .unwrap();
    let frozen = Arc::new(FrozenStore::open(fd.as_fd()).unwrap());
    let run = research_submission::load(
        session.client_mut().await.unwrap(),
        text(&request, "run_id"),
        Some(OWNER),
    )
    .await
    .unwrap();
    let evidence = Evidence::open(root)
        .unwrap()
        .with_runtime_root(Path::new(text(&request, "runtime_root")))
        .unwrap();
    let counts = Arc::new(
        evidence
            .read_verified_counts(&run, &frozen, text(&request, "freeze_relation"))
            .unwrap(),
    );
    let canonical =
        Request::from_counts(id.clone(), "experimental-backtest", "1", &counts).unwrap();
    assert_eq!(canonical.fingerprint().unwrap(),crate::application::factor_content::hash(&json!({"subject_strategy_fingerprint":subject,
        "policy_id":"experimental-backtest","policy_version":"1","evidence":[{"kind":"RESEARCH_RESULT","evidence_fingerprint":counts.research_result_fingerprint(),
            "locator_fingerprint":counts.research_result_plan_fingerprint(),"subject_binding_fingerprint":counts.freeze_relation_fingerprint()}]})).unwrap());
    assert_eq!(canonical.subject(), subject);
    canonical.matches_counts(&counts).unwrap();
    let access = Access::new(&"a".repeat(64)).unwrap();
    let http = http::Request::builder()
        .uri("/api/v2/integration-types")
        .header("host", "127.0.0.1:5173")
        .header(
            "cookie",
            format!("onlyalpha_dev_session={}", "a".repeat(64)),
        )
        .body(())
        .unwrap();
    let Admission::Owner(human) = access.admit(&http).unwrap() else {
        panic!("actual Human identity")
    };
    let decisions = Arc::new(Decisions::open(root).unwrap());
    let at = text(&request, "at").parse().unwrap();
    if let Some(boundary) = phase.strip_prefix("qualification-stop:") {
        let mut owner = Qualifications::new(
            session, &namespace, policies, decisions, frozen, &access, &human,
        );
        owner.stop_at(boundary).unwrap();
        assert!(owner.execute(&canonical, counts, at).await.is_err());
        std::process::exit(86);
    }
    let original = qualification_commands::original_request_readonly(
        session.client_mut().await.unwrap(),
        &namespace,
        subject,
        &id,
    )
    .await
    .unwrap()
    .unwrap();
    assert_eq!(
        original.fingerprint().unwrap(),
        canonical.fingerprint().unwrap()
    );
    assert_eq!(original.evidence(), canonical.evidence());
    assert_eq!(original.policy_version(), "1");
    let decision = Qualifications::new(
        session,
        &namespace,
        policies,
        decisions,
        frozen.clone(),
        &access,
        &human,
    )
    .execute(&original, counts, at)
    .await
    .unwrap();
    if phase == "resume" {
        output(
            qualification_commands::command_outcome_readonly(
                session.client_mut().await.unwrap(),
                &namespace,
                subject,
                &id,
            )
            .await
            .unwrap(),
        );
        return;
    }
    let promotion = PromotionRequest::new(
        command(&request, "promotion_command"),
        subject,
        decision.fingerprint(),
        decision.record()["policy_fingerprint"].as_str().unwrap(),
        "实验性回测；仅验证证据完整性",
    )
    .unwrap();
    if phase == "promotion-stop" {
        let mut owner = Promotions::new(session, &namespace, frozen, &access, &human);
        owner.stop_at("after_commit").unwrap();
        assert!(owner.promote(&promotion, decision, at).await.is_err());
        std::process::exit(86);
    }
    assert_eq!(phase, "promotion-resume");
    let original = strategy_promotion::promotion_outcome_readonly(
        session.client_mut().await.unwrap(),
        &namespace,
        subject,
        OWNER,
        &command(&request, "promotion_command"),
    )
    .await
    .unwrap();
    let record = Promotions::new(session, &namespace, frozen, &access, &human)
        .promote(&promotion, decision, at)
        .await
        .unwrap();
    assert_eq!(original["record"], *record.record());
    output(
        strategy_promotion::promotion_outcome_readonly(
            session.client_mut().await.unwrap(),
            &namespace,
            subject,
            OWNER,
            &command(&request, "promotion_command"),
        )
        .await
        .unwrap(),
    );
}
