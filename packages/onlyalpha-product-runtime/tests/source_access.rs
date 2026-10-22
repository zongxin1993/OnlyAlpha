use onlyalpha_product_runtime::source_access::{
    Authority, Error, Grant, Permission, Reference, Selection,
};
use std::sync::{Arc, Barrier};

const TOKEN: &str = "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";
const DIGEST: &str = "add5b41fc5a881fc87ef4640581ed5ff7fe5eab39640b3a3e6e8b90f0aa71730";
fn reference() -> Reference {
    Reference::new("integration", &"a".repeat(64), Some("test.type")).unwrap()
}
fn selection() -> Selection {
    Selection::new(reference(), "test.spot.live", "LIVE").unwrap()
}
fn grant() -> Grant {
    Grant::new(
        selection(),
        vec![Permission::ClosedHistory, Permission::RealtimePreview],
    )
    .unwrap()
}
fn authority() -> Authority {
    Authority::new("operator", DIGEST, vec![grant()]).unwrap()
}
fn authorization() -> String {
    format!("Bearer {TOKEN}")
}

#[test]
fn credentials_require_exact_bearer_syntax_and_every_digest_byte() {
    let owner = authority();
    owner.authenticate(&authorization()).unwrap();
    for header in [
        "".into(),
        "Bearer".into(),
        "Bearer bad".into(),
        format!("bearer {TOKEN}"),
        format!("Bearer {TOKEN} "),
        format!("Bearer {}", "A".repeat(64)),
        format!("Bearer {}", "é".repeat(32)),
        format!("Bearer {}", "a".repeat(4096)),
    ] {
        assert_eq!(owner.authenticate(&header).err(), Some(Error::Unauthorized));
    }
    for index in 0..64 {
        let mut wrong = TOKEN.as_bytes().to_vec();
        wrong[index] = b'0';
        let header = format!("Bearer {}", String::from_utf8(wrong).unwrap());
        assert_eq!(owner.authenticate(&header).err(), Some(Error::Unauthorized));
    }
    assert_eq!(Error::Unauthorized.to_string(), "LOCAL_READ_UNAUTHORIZED");
    assert!(!Error::Unauthorized.to_string().contains(TOKEN));
}

#[test]
fn every_reference_and_leaf_dimension_and_permission_is_required() {
    let owner = authority();
    let session = owner.authenticate(&authorization()).unwrap();
    session
        .require_reference(&reference(), Permission::ClosedHistory)
        .unwrap();
    session
        .require_selection(&selection(), Permission::RealtimePreview)
        .unwrap();
    for other in [
        Reference::new("other", &"a".repeat(64), Some("test.type")).unwrap(),
        Reference::new("integration", &"b".repeat(64), Some("test.type")).unwrap(),
        Reference::new("integration", &"a".repeat(64), Some("other.type")).unwrap(),
        Reference::new("integration", &"a".repeat(64), None).unwrap(),
    ] {
        assert_eq!(
            session
                .require_reference(&other, Permission::ClosedHistory)
                .err(),
            Some(Error::Forbidden)
        );
    }
    for other in [
        Selection::new(reference(), "other.source", "LIVE").unwrap(),
        Selection::new(reference(), "test.spot.live", "SIM").unwrap(),
    ] {
        assert_eq!(
            session.require_selection(&other, Permission::ClosedHistory),
            Err(Error::Forbidden)
        );
    }
    let historical = Authority::new(
        "operator",
        DIGEST,
        vec![Grant::new(selection(), vec![Permission::ClosedHistory]).unwrap()],
    )
    .unwrap();
    assert_eq!(
        historical
            .authenticate(&authorization())
            .unwrap()
            .require_reference(&reference(), Permission::RealtimePreview)
            .err(),
        Some(Error::Forbidden)
    );
}

#[test]
fn same_configuration_in_another_authority_does_not_reissue_the_original_session() {
    let owner = authority();
    let original = owner.authenticate(&authorization()).unwrap();
    let other = authority();
    let foreign = other.authenticate(&authorization()).unwrap();
    assert_eq!(owner.check_session(&foreign), Err(Error::Unauthorized));
    assert_eq!(other.check_session(&original), Err(Error::Unauthorized));
    owner.withdraw();
    assert_eq!(original.check_active(), Err(Error::Unauthorized));
    assert_eq!(
        owner.authenticate(&authorization()).err(),
        Some(Error::Unauthorized)
    );
    other.check_session(&foreign).unwrap();
}

#[test]
fn withdrawal_is_one_way_for_every_cloned_session_after_a_deterministic_barrier() {
    let owner = authority();
    let session = owner.authenticate(&authorization()).unwrap();
    let copy = session.clone();
    let barrier = Arc::new(Barrier::new(2));
    std::thread::scope(|scope| {
        let reader_barrier = barrier.clone();
        scope.spawn(move || {
            let before = copy.require_selection(&selection(), Permission::ClosedHistory);
            reader_barrier.wait();
            reader_barrier.wait();
            assert_eq!(before, Ok(()));
            assert_eq!(
                copy.require_selection(&selection(), Permission::ClosedHistory),
                Err(Error::Unauthorized)
            );
        });
        barrier.wait();
        owner.withdraw();
        barrier.wait();
    });
    owner.withdraw();
    assert_eq!(session.check_active(), Err(Error::Unauthorized));
    assert_eq!(session.subject_id(), Err(Error::Unauthorized));
}

#[test]
fn verified_empty_grants_authenticate_without_authorizing_any_source() {
    let owner = Authority::new("local-developer", DIGEST, vec![]).unwrap();
    let session = owner.authenticate(&authorization()).unwrap();
    session.check_active().unwrap();
    assert_eq!(session.subject_id().unwrap(), "local-developer");
    assert_eq!(
        session
            .require_reference(&reference(), Permission::ClosedHistory)
            .err(),
        Some(Error::Forbidden)
    );
}

#[test]
fn configuration_rejects_duplicate_owners_empty_duplicate_permissions_and_oversized_grants() {
    assert_eq!(
        Authority::new("operator", DIGEST, vec![grant(), grant()]).err(),
        Some(Error::InvalidConfiguration)
    );
    assert_eq!(
        Grant::new(selection(), vec![]).err(),
        Some(Error::InvalidConfiguration)
    );
    assert_eq!(
        Grant::new(
            selection(),
            vec![Permission::ClosedHistory, Permission::ClosedHistory]
        )
        .err(),
        Some(Error::InvalidConfiguration)
    );
    let grants = (0..33)
        .map(|index| {
            Grant::new(
                Selection::new(
                    Reference::new(
                        &format!("integration-{index}"),
                        &"a".repeat(64),
                        Some("test.type"),
                    )
                    .unwrap(),
                    "test.spot.live",
                    "LIVE",
                )
                .unwrap(),
                vec![Permission::ClosedHistory],
            )
            .unwrap()
        })
        .collect();
    assert_eq!(
        Authority::new("operator", DIGEST, grants).err(),
        Some(Error::InvalidConfiguration)
    );
    for subject in [
        "".into(),
        " operator".into(),
        "operator ".into(),
        "\u{1c}operator".into(),
        "汉".repeat(129),
    ] {
        assert_eq!(
            Authority::new(&subject, DIGEST, vec![]).err(),
            Some(Error::InvalidConfiguration)
        );
    }
    Authority::new(&"汉".repeat(128), DIGEST, vec![]).unwrap();
    for digest in ["".into(), "A".repeat(64), "a".repeat(63), "g".repeat(64)] {
        assert_eq!(
            Authority::new("operator", &digest, vec![]).err(),
            Some(Error::InvalidConfiguration)
        );
    }
}

#[test]
fn invalid_selection_proof_is_distinct_from_a_proved_different_source() {
    assert_eq!(
        Selection::new(reference(), "", "LIVE").err(),
        Some(Error::ProofUnavailable)
    );
    assert_eq!(
        Selection::new(reference(), "test.spot.live", "").err(),
        Some(Error::ProofUnavailable)
    );
    let missing_type = Reference::new("integration", &"a".repeat(64), None).unwrap();
    assert_eq!(
        Selection::new(missing_type, "test.spot.live", "LIVE").err(),
        Some(Error::ProofUnavailable)
    );
    let owner = authority();
    let session = owner.authenticate(&authorization()).unwrap();
    assert_eq!(
        session.require_selection(
            &Selection::new(reference(), "other", "LIVE").unwrap(),
            Permission::ClosedHistory
        ),
        Err(Error::Forbidden)
    );
}

#[test]
fn grant_configuration_preserves_python_codepoint_limits_and_strip_semantics() {
    for source in [
        "*".into(),
        " bad".into(),
        "bad\u{1f}".into(),
        "汉".repeat(257),
    ] {
        assert_eq!(
            Grant::new(
                Selection::new(reference(), &source, "LIVE").unwrap(),
                vec![Permission::ClosedHistory]
            )
            .err(),
            Some(Error::InvalidConfiguration)
        );
    }
    Grant::new(
        Selection::new(reference(), &"汉".repeat(256), "LIVE").unwrap(),
        vec![Permission::ClosedHistory],
    )
    .unwrap();
}

#[test]
fn malformed_reference_is_never_reinterpreted_as_absent_or_a_complete_denial() {
    for revision in ["".into(), "a".repeat(63), "A".repeat(64), "é".repeat(32)] {
        assert_eq!(
            Reference::new("integration", &revision, Some("test.type")).err(),
            Some(Error::InvalidReference)
        );
    }
    for integration in ["", " ", "\u{1c}"] {
        assert_eq!(
            Reference::new(integration, &"a".repeat(64), Some("test.type")).err(),
            Some(Error::InvalidReference)
        );
    }
    assert_eq!(
        Reference::new("integration", &"a".repeat(64), Some(" ")).err(),
        Some(Error::InvalidReference)
    );
    for invalid in [
        "*".into(),
        " bad".into(),
        "bad\u{1f}".into(),
        "汉".repeat(257),
    ] {
        for candidate in [
            Selection::new(
                Reference::new(&invalid, &"a".repeat(64), Some("test.type")).unwrap(),
                "source",
                "LIVE",
            )
            .unwrap(),
            Selection::new(
                Reference::new("integration", &"a".repeat(64), Some(&invalid)).unwrap(),
                "source",
                "LIVE",
            )
            .unwrap(),
            Selection::new(reference(), "source", &invalid).unwrap(),
        ] {
            assert_eq!(
                Grant::new(candidate, vec![Permission::ClosedHistory]).err(),
                Some(Error::InvalidConfiguration)
            );
        }
    }
}
