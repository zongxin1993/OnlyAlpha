# ADR 0077 — Streaming Recovery Verification and Diagnostics

- Status: Accepted
- Date: 2026-08-14
- Scope: product-neutral Streaming control plane and SIM verification

## Context

The P7.5 final-SHA `core-full` gate exposed a timeout in
`test_engine_sim_gap_recovers_history_then_reconciles_trigger_once`. The Runtime began from `LIVE` revision 4, but the test's
10-second wait did not observe the later `LIVE` revision. The same immutable baseline completed the scenario in other full-suite
runs. A timeout alone could not distinguish blocked historical I/O, replay, suffix reconciliation, continuity verification,
worker failure, or a lost phase transition.

The existing production authorities were already structurally correct: `OnlyStreamingPhaseController` owned every phase
transition, `OnlyStreamingSemanticLane` was the sole `MarketDataProcessor.process()` caller, and
`OnlyStreamingRecoveryLoader` loaded and validated external facts without applying semantic state. The test nevertheless treated
an ad-hoc wall-clock value as if it were a recovery contract. It was also shorter than the configured 30-second historical
operation budget.

## Decision

- Phase revision is the formal asynchronous synchronization point. `wait_for_revision()` observes any transition after a
  captured baseline even when the Runtime has already moved through an intermediate phase.
- Recovery correctness remains `historical facts -> same semantic lane -> suffix reconciliation -> continuity proof -> LIVE`.
  No duration is part of that proof.
- One operational watchdog is derived from the configured historical-operation budget plus the existing five-second
  scheduling/notification grace. The watchdog detects stuck verification; it is not an SLA or economic rule.
- `OnlyStreamingRecoveryDiagnostics` is an immutable read-only projection assembled from existing authorities. Its stage records
  where the current control flow stopped, but the stage is forbidden from controlling Runtime behavior. Semantic Lane state is
  sampled without waiting; a busy Lane reports `busy = true` and an unknown revoked value so watchdog diagnostics cannot hang
  behind the operation they are diagnosing.
- STOP keeps precedence. After semantic permission is revoked, returned external facts are discarded and diagnostic progress
  cannot advance beyond `STOP_CUTOFF`.

## Rejected Alternatives

- Increasing scattered 10-second constants without a shared authority.
- Sleep, pytest reruns, flaky markers, skipped lanes, or removal from `core-full`.
- A second Recovery Manager, phase owner, semantic writer, or mutable test hook.
- Moving historical I/O into the semantic-lane critical section.

## Consequences

- Watchdog failures identify phase/revision, recovery generation/stage/plan, lane cutoff, worker/source/subscription state,
  continuity frontier, and buffered suffix state.
- Tests first prove that a formal phase revision occurred and then wait for a later `LIVE` revision; business assertions still
  prove continuity and exactly-once trading progress.
- No public package export, persistence/checkpoint schema, transaction identity, result identity, or trading economic behavior
  changes.
