use onlyalpha_backend::application::command::{
    Admission, Binding, CommandId, CommandKind, Error, Outcome, OutcomeKind, Receipt,
    verify_binding,
};
const ID: &str = "00000000-0000-4000-8000-000000000501";
const RUN: &str = "00000000-0000-4000-8000-000000000510";
fn admission() -> Admission {
    Admission::new(
        CommandId::new(ID).unwrap(),
        CommandKind::CreateResearchRun,
        &"a".repeat(64),
    )
    .unwrap()
}
fn receipt() -> Receipt {
    Receipt::new(
        admission(),
        Outcome::new(OutcomeKind::ResearchRun, RUN).unwrap(),
        "2026-08-27T00:00:00+00:00",
    )
    .unwrap()
}
#[test]
fn admission_is_not_an_outcome_and_missing_proof_cannot_mean_absence() {
    assert_eq!(verify_binding(None, None).unwrap(), Binding::None);
    assert_eq!(
        verify_binding(Some(admission()), None).unwrap(),
        Binding::Admitted(admission())
    );
    assert_eq!(
        verify_binding(Some(admission()), Some(receipt())).unwrap(),
        Binding::Accepted(receipt())
    );
    assert_eq!(
        verify_binding(None, Some(receipt())),
        Err(Error::ReceiptCorrupt)
    );
    let foreign = Admission::new(
        CommandId::new(ID).unwrap(),
        CommandKind::CreateBacktestRun,
        &"a".repeat(64),
    )
    .unwrap();
    assert_eq!(
        verify_binding(Some(foreign), Some(receipt())),
        Err(Error::BindingMismatch)
    );
}
#[test]
fn canonical_command_identity_rejects_loose_uuid_and_wrong_outcome_family() {
    for id in [
        "bad",
        "00000000-0000-1000-8000-000000000501",
        "00000000-0000-4000-7000-000000000501",
        "00000000-0000-4000-8000-00000000050A",
    ] {
        assert!(CommandId::new(id).is_err());
    }
    assert!(
        Admission::new(
            CommandId::new(ID).unwrap(),
            CommandKind::SaveWatchlists,
            &"A".repeat(64)
        )
        .is_err()
    );
    assert!(Outcome::new(OutcomeKind::ResearchRun, &"a".repeat(64)).is_err());
    assert!(Outcome::new(OutcomeKind::WatchlistRevision, RUN).is_err());
    assert!(
        Receipt::new(
            admission(),
            Outcome::new(OutcomeKind::ResearchRun, RUN).unwrap(),
            "2026-08-27T01:00:00+01:00"
        )
        .is_err()
    );
}
#[test]
fn all_existing_command_and_outcome_families_are_supported_without_new_identities() {
    assert_eq!(CommandKind::ALL.len(), 20);
    for kind in CommandKind::ALL {
        assert_eq!(kind.as_str().parse::<CommandKind>().unwrap(), *kind);
    }
    assert_eq!(OutcomeKind::ALL.len(), 11);
    for kind in OutcomeKind::ALL {
        assert_eq!(kind.as_str().parse::<OutcomeKind>().unwrap(), *kind);
        let uuid = matches!(
            kind,
            OutcomeKind::ResearchRun
                | OutcomeKind::BacktestRun
                | OutcomeKind::Integration
                | OutcomeKind::ChartCalculationOperation
        );
        assert!(
            Outcome::new(
                *kind,
                if uuid {
                    RUN
                } else {
                    "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                }
            )
            .is_ok()
        );
    }
    assert!("create_research_run".parse::<CommandKind>().is_err());
    assert!("FUTURE_KIND".parse::<OutcomeKind>().is_err());
}
#[test]
fn every_copied_intent_dimension_requires_its_own_admission_proof() {
    let foreign = Admission::new(
        CommandId::new(RUN).unwrap(),
        CommandKind::CreateResearchRun,
        &"a".repeat(64),
    )
    .unwrap();
    assert_eq!(
        verify_binding(Some(foreign), Some(receipt())),
        Err(Error::BindingMismatch)
    );
    let foreign = Admission::new(
        CommandId::new(ID).unwrap(),
        CommandKind::CreateResearchRun,
        &"b".repeat(64),
    )
    .unwrap();
    assert_eq!(
        verify_binding(Some(foreign), Some(receipt())),
        Err(Error::BindingMismatch)
    );
    for instant in [
        "2026-08-27T00:00:00",
        "2026-02-30T00:00:00Z",
        "2026-08-27T00:00:00.0000001Z",
        "0000-01-01T00:00:00Z",
    ] {
        assert_eq!(
            Receipt::new(
                admission(),
                Outcome::new(OutcomeKind::ResearchRun, RUN).unwrap(),
                instant
            ),
            Err(Error::InvalidAcceptedAt)
        );
    }
    assert_eq!(
        Receipt::new(
            admission(),
            Outcome::new(OutcomeKind::ResearchRun, RUN).unwrap(),
            "2026-08-27T00:00:00Z"
        )
        .unwrap(),
        receipt()
    );
}
