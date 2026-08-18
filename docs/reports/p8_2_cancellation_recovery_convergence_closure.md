# P8.2 Cancellation / Recovery Convergence Closure — Implementation Report

- Date: 2026-08-18
- Target version: `0.8.2`
- `TASK_BASE_SHA`: `9b2eaacaa2ffce3f240c88a9093a3250c61ef3e6`
- Working implementation SHA: `9b2eaacaa2ffce3f240c88a9093a3250c61ef3e6` with intentional dirty Task worktree
- Final committed SHA: unavailable in the Task worktree
- Authority: local Task Gate evidence, including PostgreSQL 16.10; not P8 Final-SHA certification

## Root cause and old invalid sequence

The pre-closure `OnlyPostgresResearchExecutionStore.expire_next()` combined two facts that belong to different authorities. It correctly
proved that an ACTIVE Attempt lease had expired, but for a `CANCEL_REQUESTED` Run it immediately committed `CANCELLED` in the same
PostgreSQL transaction. PostgreSQL could not inspect immutable Research Result/Artifact authorities, so the outcome depended on whether
the Worker survived long enough to call operational success finalization.

The invalid ordering was: exact Result and Artifact durable/verified; cancellation requested; Worker process lost before finalization;
Attempt expired; expiry projected `CANCELLED`. The same semantic facts produced `COMPLETED` when the Worker survived. This violated
process-survival independence and the ADR 0090 success-wins rule.

## Canonical invariant and authority split

The frozen invariant is:

```text
authoritative immutable semantic facts
-> application reconciliation decision
-> fenced operational projection
```

Semantic completion means both of the following exact authorities exist and pass their existing `load_verified()` contracts:

1. the Research Result addressed by the canonical resolved `ResearchResultPlan.fingerprint`;
2. the Research Artifact addressed by that verified Result's `research_result_fingerprint`.

The proof also compares Result Plan, Result content, Result identity and Dataset linkage copied into the Artifact manifest. Result-only,
Calculation-only or Statistics-only facts are partial and do not prove completion. PostgreSQL owns Run/Attempt/lease/cancellation and the
terminal projection; it does not inspect semantic Stores. Scheduler remains operational-only.

## Reconciliation boundary and linearization

`OnlyResearchCancellationRecoveryReconciler` is the application boundary that can legitimately combine operational eligibility with a
read-only `OnlyResearchSemanticCompletionProbe`. It loads one `CANCEL_REQUESTED` Run with no ACTIVE Attempt, deterministically resolves its
stored canonical Specification, verifies admission evidence, and inspects existing Result/Artifact authorities without executing Engine,
Runtime, Calculation, Statistics, Result assembly or Artifact materialization.

The authoritative inspection is the cancellation-recovery linearization point:

- exact Result + Artifact present and verified: `COMPLETED` with exact references;
- full completion absent, including Result present/Artifact absent: `CANCELLED`;
- corrupt, conflicting, drifted or ambiguous authority: `FAILED` with a stable machine-readable failure code.

`reconcile_cancellation()` then locks the Run and requires exact `CANCEL_REQUESTED` state/revision plus no ACTIVE Attempt before one short
terminal transaction. Concurrent actors therefore have one CAS winner; a stale actor receives ownership loss. Later stale-Worker semantic
writes may remain deterministic immutable duplicate work, but every operational finalization stays fenced and cannot rewrite the terminal
Run.

## Changed execution responsibilities

- `expire_next()` now terminalizes the expired Attempt only. A `CANCEL_REQUESTED` Run remains pending for semantic reconciliation. Normal
  `RUNNING` retry/exhaustion behavior is unchanged.
- `claim_next()` is unchanged and still admits only `QUEUED/RUNNING`; cancellation recovery never creates an Attempt and does not consume
  retry budget.
- Worker cancellation checkpoints are unchanged. An authoritative active Worker still cooperatively cancels before completion, while
  completion after verified Result + Artifact can still win through existing fenced `complete()`.
- `OnlyResearchWorkerService` runs expiry, one cancellation reconciliation, then normal claim. This also closes cancellation-vs-expiry
  orderings where the cancellation request becomes visible after Attempt fencing.

At `attempt_number == max_attempts`, already verified Result + Artifact still reconcile to `COMPLETED`; attempt budget limits execution
retry, not semantic truth. Partial Result bytes remain immutable and are neither deleted nor promoted by recovery. Artifact corruption is
not treated as absence and yields `CANCELLATION_RECOVERY_ARTIFACT_VERIFICATION_FAILED`.

## Persistence and migration evidence

No migration was added and no published migration was modified. Architecture tests freeze the SHA-256 values:

```text
0001  3e7d6564dc83a062ea2954f7eb23255065c39b3f6398115cde3e2719954062b0
0002  05dd03d41d1418046e705b98e00c51a0041f9acd07122ca0331d9f786980bd6a
0003  b5c9cbb93a3fea8231a9b9ab4f76b2e0b5cd2abede475aa41eb913cdd98fa19d
```

## Verification evidence

Development evidence before version closure:

- `research-execution --coverage`: 28 passed; total 96.32%, line 97.52%, branch 91.00%.
- `research-postgres --coverage`: 51 passed against PostgreSQL 16.10; total 82.63%, line 84.94%, branch 72.22%.
- focused execution architecture tests: 14 passed.
- focused real PostgreSQL execution authority tests: 17 passed.
- semantic E2E: real `OnlyEngine -> OnlyResearchRuntime`, immutable Stores, cancellation, forced lease expiry, recreated Store/Resolver/
  Reconciler objects, and exact fingerprint convergence to `COMPLETED` passed.

The full PostgreSQL lane used PostgreSQL 16.10 and matching v16 `pg_dump/pg_restore` for backup/isolated restore evidence. An initial local
attempt with Homebrew PostgreSQL 18.6 client tools failed only because v18 emitted `transaction_timeout`, which PostgreSQL 16.10 does not
recognize; rerunning with the pinned matching client passed without repository changes.

Final version-sync and impact-aware verification results are recorded below after closure:

```text
version_sync set: PASS — Workspace release graph is consistent at 0.8.2
version_sync check: PASS — Workspace release graph is consistent at 0.8.2
final verify plan: FULL_LOCAL — 20 canonical lanes + release/Web/build checks
final verify agent: PASS — IMPACT VERIFIED, 35 gates
evidence: test-results/verification/20260818T021113Z-9b2eaacaa2ff-36109/
```

The first final agent attempt exposed a real `version_sync.py` defect: Web JSON was emitted at two-space indentation while the repository
Prettier contract requires four. The tool now preserves the canonical four-space format, and `tests/tools/test_version_sync.py` freezes
that behavior (19 tests passed). The official set/check commands were rerun before the successful full verification.

## Remaining limitations and P8.3 readiness

This closure adds no HTTP command API, idempotency key, Run list, Web execution control, mutable semantic checkpoint, Worker registry,
priority/backoff system or production deployment claim. P8 remains `IN_PROGRESS` and is not certified by this Task Gate.

The final version and FULL_LOCAL Task Gate are closed. Cancellation semantics are **READY FOR P8.3** Research Command API exposure.
