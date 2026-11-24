use crate::application::source_access::{Authority, Error, Grant, Permission, Reference, Selection};
use crate::workers::source_sessions::SourceSessions;
use std::sync::Arc;

fn issuer() -> (Authority, Selection) {
    let selection = Selection::new(
        Reference::new("worker-source", &"a".repeat(64), Some("worker.market")).unwrap(),
        "WORKER_MARKET", "LIVE",
    ).unwrap();
    let authority = Authority::new(
        "worker-owner",
        "add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730",
        vec![Grant::new(selection.clone(), vec![Permission::ClosedHistory]).unwrap()],
    ).unwrap();
    (authority, selection)
}

#[tokio::test]
async fn new_load_gets_current_session_without_refreshing_the_retained_session() {
    let (original, selection) = issuer();
    let original_session = original.authenticate(&format!("Bearer {}", "e".repeat(64))).unwrap();
    let owner = Arc::new(tokio::sync::Mutex::new(original_session));
    let weak = Arc::downgrade(&owner);
    let sessions = SourceSessions::new(move |_, _| {
        let weak = weak.clone();
        async move {
            let owner = weak.upgrade().ok_or(Error::ProofUnavailable)?;
            let session = owner.lock().await.clone();
            Ok(session)
        }
    });
    assert!(matches!(sessions.current("other-owner", None).await, Err(Error::Forbidden)));
    let retained = sessions.current("worker-owner", None).await.unwrap();
    retained.require_selection(&selection, Permission::ClosedHistory).unwrap();
    let (replacement, _) = issuer();
    original.withdraw();
    *owner.lock().await = replacement.authenticate(&format!("Bearer {}", "e".repeat(64))).unwrap();
    assert!(retained.require_selection(&selection, Permission::ClosedHistory).is_err());
    let current = sessions.current("worker-owner", None).await.unwrap();
    assert_eq!(current.subject_id().unwrap(), "worker-owner");
    current.require_selection(&selection, Permission::ClosedHistory).unwrap();
    assert!(retained.require_selection(&selection, Permission::ClosedHistory).is_err());
    assert_eq!(Arc::strong_count(&owner), 1, "the provider must not retain its Node owner");
    drop(owner);
    assert!(matches!(sessions.current("worker-owner", None).await, Err(Error::ProofUnavailable)));
}

#[tokio::test]
async fn failed_session_lookup_has_no_default_or_reconstructed_grant() {
    let sessions = SourceSessions::new(|_, _| async { Err(Error::ProofUnavailable) });
    assert!(matches!(sessions.current("worker-owner", None).await, Err(Error::ProofUnavailable)));
}

#[test]
fn retained_source_selection_is_exact_values_and_cannot_supply_a_session() {
    let (_, selection) = issuer();
    let record = selection.record();
    assert_eq!(Selection::from_record(&record).unwrap(), selection);
    for key in ["integration_id", "revision_fingerprint", "expected_type_id", "source_id", "environment"] {
        let mut missing = record.clone();
        missing.as_object_mut().unwrap().remove(key);
        assert!(Selection::from_record(&missing).is_err(), "{key}");
        let mut invalid = record.clone();
        invalid[key] = serde_json::Value::Null;
        assert!(Selection::from_record(&invalid).is_err(), "{key}");
    }
    let mut unexpected = record.clone();
    unexpected["permission"] = serde_json::json!("ClosedHistory");
    assert!(Selection::from_record(&unexpected).is_err());
}
