//! Product node lifecycle model only; no startup/READY or Web acceptance proof.
use onlyalpha_http_server::node::{Error, Failure, Lifecycle, Phase, State};
const PATH: [State; 7] = [
    State::Created,
    State::Booting,
    State::Verifying,
    State::Recovering,
    State::Ready,
    State::Draining,
    State::Stopped,
];
const STATES: [State; 8] = [
    State::Created,
    State::Booting,
    State::Verifying,
    State::Recovering,
    State::Ready,
    State::Draining,
    State::Stopped,
    State::Failed,
];
fn at(state: State) -> Lifecycle {
    let mut lifecycle = Lifecycle::new();
    if state == State::Failed {
        lifecycle.transition(State::Booting).unwrap();
        lifecycle
            .fail(Failure::new(Phase::Booting, "composition", "RegistryInvalid").unwrap())
            .unwrap();
    } else {
        for next in PATH.into_iter().skip(1) {
            if lifecycle.state() == state {
                break;
            }
            lifecycle.transition(next).unwrap();
        }
    }
    assert_eq!(lifecycle.state(), state);
    lifecycle
}
#[test]
fn only_the_frozen_lifecycle_edges_are_legal_and_failure_is_not_a_plain_transition() {
    let edges = [
        (State::Created, State::Booting),
        (State::Booting, State::Verifying),
        (State::Verifying, State::Recovering),
        (State::Recovering, State::Ready),
        (State::Ready, State::Draining),
        (State::Draining, State::Stopped),
    ];
    for from in STATES {
        for to in STATES {
            let mut lifecycle = at(from);
            let before = lifecycle.status();
            let result = lifecycle.transition(to);
            if edges.contains(&(from, to)) {
                assert!(result.is_ok());
                assert_eq!(lifecycle.state(), to)
            } else {
                assert_eq!(result, Err(Error::IllegalTransition));
                assert_eq!(lifecycle.status(), before)
            }
        }
    }
}
#[test]
fn status_is_derived_from_the_actual_state_without_a_parallel_ready_flag() {
    for state in STATES {
        let lifecycle = at(state);
        let status = lifecycle.status();
        assert_eq!(status.state(), state);
        assert_eq!(status.live(), state != State::Stopped);
        assert_eq!(status.ready(), state == State::Ready);
        assert_eq!(lifecycle.assert_ready().is_ok(), state == State::Ready);
        assert_eq!(status.failure().is_some(), state == State::Failed);
    }
}
#[test]
fn failure_phase_is_exact_and_terminal_evidence_never_changes() {
    let phases = [
        Phase::Booting,
        Phase::Verifying,
        Phase::Recovering,
        Phase::Ready,
        Phase::Draining,
    ];
    let allowed = [
        (State::Booting, Phase::Booting),
        (State::Verifying, Phase::Verifying),
        (State::Verifying, Phase::Recovering),
        (State::Recovering, Phase::Recovering),
        (State::Ready, Phase::Ready),
        (State::Draining, Phase::Draining),
    ];
    for state in STATES {
        for phase in phases {
            let mut lifecycle = at(state);
            let before = lifecycle.status();
            let failure = Failure::new(phase, "canonical-read", "IntegrityFailure").unwrap();
            let result = lifecycle.fail(failure.clone());
            if allowed.contains(&(state, phase)) {
                assert!(result.is_ok());
                assert_eq!(lifecycle.state(), State::Failed);
                assert_eq!(lifecycle.status().failure(), Some(&failure));
                assert!(!lifecycle.status().ready());
                assert_eq!(
                    lifecycle.fail(Failure::new(phase, "later", "Unavailable").unwrap()),
                    Err(Error::IllegalTransition)
                );
                assert_eq!(lifecycle.status().failure(), Some(&failure));
            } else {
                assert_eq!(result, Err(Error::IllegalTransition));
                assert_eq!(lifecycle.status(), before)
            }
        }
    }
}
#[test]
fn failed_step_and_reason_cannot_be_lost_or_replaced_with_empty_evidence() {
    assert_eq!(
        Failure::new(Phase::Verifying, "", "Unavailable"),
        Err(Error::InvalidFailure)
    );
    assert_eq!(
        Failure::new(Phase::Verifying, "schema", ""),
        Err(Error::InvalidFailure)
    );
    let mut lifecycle = at(State::Verifying);
    let failure = Failure::new(
        Phase::Recovering,
        "mutation-authority-acquire",
        "AlreadyHeld",
    )
    .unwrap();
    assert_eq!(failure.phase(), Phase::Recovering);
    assert_eq!(failure.step(), "mutation-authority-acquire");
    assert_eq!(failure.reason(), "AlreadyHeld");
    lifecycle.fail(failure).unwrap();
    assert_eq!(
        lifecycle.transition(State::Ready),
        Err(Error::IllegalTransition)
    );
    assert_eq!(
        lifecycle.transition(State::Booting),
        Err(Error::IllegalTransition)
    );
    assert_eq!(lifecycle.assert_ready(), Err(Error::NotReady));
}
