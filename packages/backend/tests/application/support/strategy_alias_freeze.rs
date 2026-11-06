//! Presentation-alias identity regression through the actual Freeze owner.
//! Artificial completed scientific preconditions reuse the existing test seal;
//! this is a persistence/semantic reuse test, never Product or Web acceptance.
use crate::{
    application::{
        command::CommandId,
        frozen_strategy::FrozenStore,
        strategy_projection::{FreezeRequest, Freezes},
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession, research_evidence::VerifiedStrategyResearch,
    },
    security::{human_access::Session, immutable_json::SourceLock},
};
use onlyalpha_strategy::SourceRevision;
use serde_json::{Value, json};
use std::{path::Path, sync::Arc};

pub(super) async fn run(
    session: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    human: &Session,
    store: &FrozenStore,
    root: &Path,
) {
    let fixture: Value =
        serde_json::from_str(include_str!("../fixtures/frozen_strategy.json")).unwrap();
    let original =
        SourceRevision::from_json(&fixture["source"].to_string(), 8 * 1024 * 1024).unwrap();
    let mut renamed = original.to_record();
    renamed["decision_graph"]["nodes"][0]["alias"] = json!("renamed display label");
    let renamed = SourceRevision::from_json(&renamed.to_string(), 8 * 1024 * 1024).unwrap();
    assert_eq!(
        renamed.fingerprint(),
        original.fingerprint(),
        "labels do not define a second Strategy identity"
    );
    assert_ne!(
        renamed.to_record(),
        original.to_record(),
        "the fixture must retain distinct presentation bytes"
    );
    let relation = &fixture["relation"];
    let evidence = VerifiedStrategyResearch::for_value_test(
        "00000000-0000-4000-8000-000000000703".into(),
        "7".repeat(64),
        renamed,
        "0".repeat(64),
        relation["research_result_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
        relation["research_execution_evidence_fingerprints"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect(),
        relation["admission_evidence_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
        relation["equivalence_evidence_fingerprints"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect(),
        vec![Arc::new(SourceLock::publication(root).unwrap())],
    );
    let command = CommandId::new("00000000-0000-4000-8000-000000000704").unwrap();
    let input = FreezeRequest::new(
        command,
        evidence.run_id(),
        evidence.candidate_fingerprint(),
        Some("same Strategy with another display alias"),
    )
    .unwrap();
    let mut freezes = Freezes::new(session, store, namespace, human);
    let completed = freezes
        .execute(
            &input,
            &evidence,
            "2026-11-01T00:00:02Z",
            1000,
            64 * 1024 * 1024,
        )
        .await
        .unwrap();
    assert_eq!(completed["strategy_fingerprint"], original.fingerprint());
    assert_ne!(
        completed["freeze_relation_fingerprint"], relation["relation_fingerprint"],
        "another Candidate keeps its own provenance relation"
    );
    let replay = freezes
        .execute(
            &input,
            &evidence,
            "2026-11-01T00:00:03Z",
            1000,
            64 * 1024 * 1024,
        )
        .await
        .unwrap();
    assert_eq!(replay["accepted_at"], completed["accepted_at"]);
    assert_eq!(
        replay["freeze_relation_fingerprint"],
        completed["freeze_relation_fingerprint"]
    );
    assert_eq!(replay["replayed"], true);
    let stored = store
        .load_verified(original.fingerprint(), 64 * 1024 * 1024)
        .unwrap();
    assert_eq!(
        stored.to_record(),
        original.to_record(),
        "the first immutable source record must remain authoritative"
    );
    session.verify().await.unwrap();
}
