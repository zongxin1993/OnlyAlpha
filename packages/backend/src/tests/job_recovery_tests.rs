use super::*;
use crate::{
    application::job_contract::JobKind,
    persistence::job_publication::{PublicationError, PublicationObservation, fixture},
};

fn original() -> fixture::Fixture {
    fixture::fixture(
        JobKind::Backtest,
        ("00000000-0000-4000-8000-000000000001", "original-owner"),
        "00000000-0000-4000-8000-000000000002",
        "00000000-0000-4000-8000-000000000003",
        "00000000-0000-4000-8000-000000000004",
        1,
        0,
    )
}

#[test]
fn unresolved_original_transaction_never_authorizes_recomputation() {
    assert!(matches!(
        JobRecovery::decide(PublicationObservation::Unresolved, RetryBudget::new(3).unwrap()).unwrap(),
        RecoveryDecision::WaitForResolution
    ));
}

#[test]
fn only_confirmed_unpublished_inactive_work_can_request_a_new_claim() {
    let fixture = original();
    for (state, attempts) in [("QUEUED", 0), ("RUNNING", 1), ("RUNNING", 2)] {
        let observed = fixture.unpublished(state, attempts, 0);
        let decision = JobRecovery::decide(observed, RetryBudget::new(3).unwrap()).unwrap();
        let RecoveryDecision::RecomputeWithNewClaim(proof) = decision else { panic!("new claim required") };
        assert_eq!(proof.binding().run_id(), fixture.run_id());
        assert_eq!(proof.binding().fingerprint(), fixture.candidate.binding().fingerprint());
    }
}

#[test]
fn active_ownership_blocks_both_recompute_and_cancellation() {
    for state in ["RUNNING", "CANCEL_REQUESTED"] {
        assert!(matches!(
            JobRecovery::decide(original().unpublished(state, 1, 1), RetryBudget::new(3).unwrap()).unwrap(),
            RecoveryDecision::WaitForResolution
        ));
    }
}

#[test]
fn inactive_cancellation_finishes_without_creating_an_attempt_or_candidate() {
    assert!(matches!(
        JobRecovery::decide(original().unpublished("CANCEL_REQUESTED", 3, 0), RetryBudget::new(3).unwrap()).unwrap(),
        RecoveryDecision::FinishCancellation(_)
    ));
}

#[test]
fn terminal_failure_and_cancellation_cannot_be_retried() {
    for state in ["FAILED", "CANCELLED"] {
        assert!(matches!(
            JobRecovery::decide(original().unpublished(state, 1, 0), RetryBudget::new(3).unwrap()).unwrap(),
            RecoveryDecision::Refused(RecoveryRefusal::Terminal, _)
        ));
    }
}

#[test]
fn exhausted_attempt_budget_never_creates_an_automatic_retry() {
    assert!(matches!(
        JobRecovery::decide(original().unpublished("RUNNING", 3, 0), RetryBudget::new(3).unwrap()).unwrap(),
        RecoveryDecision::Refused(RecoveryRefusal::RetryExhausted, _)
    ));
}

#[test]
fn completed_without_publication_and_impossible_attempt_counts_are_corruption() {
    for (state, attempts, active) in [("COMPLETED", 1, 0), ("UNKNOWN", 1, 0), ("QUEUED", 0, 1), ("RUNNING", -1, 0)] {
        assert_eq!(
            JobRecovery::decide(original().unpublished(state, attempts, active), RetryBudget::new(3).unwrap()).unwrap_err(),
            PublicationError::Integrity
        );
    }
}

#[test]
fn retry_budget_is_explicit_and_representable_by_the_existing_attempt_counter() {
    assert!(RetryBudget::new(0).is_err());
    assert!(RetryBudget::new(i64::from(i32::MAX) + 1).is_err());
}

#[test]
fn exhausted_recovery_retains_the_original_absence_proof_for_terminal_cas() {
    let fixture=original();
    let PublicationObservation::ConfirmedUnpublished(original_proof)=fixture.unpublished("RUNNING",3,0) else { panic!("original proof required") };
    let revision=original_proof.run_revision();
    let RecoveryDecision::Refused(RecoveryRefusal::RetryExhausted, proof)=
        JobRecovery::decide(PublicationObservation::ConfirmedUnpublished(original_proof),RetryBudget::finite_job()).unwrap()
        else { panic!("exhausted recovery requires its original observation") };
    assert_eq!(proof.binding().record(),fixture.candidate.binding().record());
    assert_eq!(proof.binding().fingerprint(),fixture.candidate.binding().fingerprint());
    assert_eq!(proof.run_revision(),revision);
    assert_eq!(proof.run_state(),"RUNNING");
    assert_eq!(proof.attempts(),3);
    assert_eq!(proof.active_attempts(),0);
}
