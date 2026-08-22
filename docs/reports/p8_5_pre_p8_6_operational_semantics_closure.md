# P8.5 Pre-P8.6 Operational Semantics Closure

Date: 2026-08-22

## Baseline and scope

- Baseline SHA: `f8b956a7d97862f44e8e7dbc91e465c100dc29b1`
- Baseline subject: `Feat: P8.5 Post-Closure — Composition Authority & Architecture Gate Closure`
- Final state: uncommitted working tree based on the baseline SHA; the implementation Prompt remains an untracked user input.
- Scope: C1 deterministic failure classification, C2 stop/claim linearization, C3 bounded operational PostgreSQL I/O, C4 Worker exit semantics, and RESEARCH backend process-lifetime reuse wording/conformance.
- Non-scope: P8.6 certification, migrations, new Run/Attempt states, plugin discovery refactoring, registry freeze, hot reload, heterogeneous routing, or a second composition root.

## Problems reproduced and root causes

| ID | Current code path | Proven baseline behavior | Required contract | Root cause | Minimal fix boundary |
|---|---|---|---|---|---|
| C1 | `Worker.execute_claim -> resolver.resolve` | `OnlyResearchSpecificationError` fell through `except Exception`, became retryable `UNEXPECTED_WORKER_FAILURE` | deterministic execution-time re-resolution failure final-fails | the Worker did not preserve the existing structured Specification boundary | Worker exception mapping only |
| C2 | `run_forever -> outer stop check -> run_once -> expire -> reconcile -> claim` | a stop arriving during housekeeping was not observed again before claim | stop observed before claim transaction forbids claim | the only external-stop observation was outside the iteration | one pre-claim observation barrier in Worker Service |
| C3 | Run/Execution/Operations stores and startup probes | raw DSN supplied no repository-owned connect, statement, or lock bound; non-daemon threads relied on final `join(timeout)` | short operational DB I/O is bounded and fails closed | timeout behavior was deployment/OS accidental rather than composition policy | thin options applied to the same DSN and existing adapters |
| C4 | `worker_main -> StopController` | Worker main always returned `0`, including SIGINT/SIGTERM | the existing StopController owns process exit semantics | Worker discarded `controller.exit_code` | return the existing authority value |

## Authority review

1. Process stop request: `OnlyApplicationStopController`.
2. Worker draining lifecycle: `OnlyResearchWorkerService`.
3. New claim initiation: `OnlyResearchWorkerService` through the existing Scheduler.
4. Claim linearization boundary: the pre-claim stop observation immediately before `scheduler.claim_once()`; once that call begins, the claim is in-flight.
5. ACTIVE Attempt ownership: PostgreSQL `ResearchRunAttempt` plus exact Attempt/Worker/ACTIVE/unexpired-lease fencing.
6. Retry policy: `OnlyResearchExecutionPolicy`.
7. Specification resolution error contract: `OnlyResearchSpecificationError(phase, code, detail)`.
8. Retryable failure codes: the existing policy set `LEASE_EXPIRED`, `UNEXPECTED_WORKER_FAILURE`, and `RESEARCH_RUN_STORE_UNAVAILABLE`, bounded by `max_attempts`.
9. Operational PostgreSQL timeouts: repository options now own connect, statement, lock, TCP user timeout, and keepalive settings.
10. Timeout authority: repository configuration, not optional DSN decoration.
11. Attempt heartbeat and presence threads: non-daemon; their DB I/O bound is validated shorter than the Worker heartbeat/presence join deadline.
12. Worker signal exit code: `OnlyApplicationStopController.exit_code` (`0`, `130`, `143`).
13. API and Worker composition: both use the existing PostgreSQL configuration/options mechanism; Calculation composition remains the existing plugin/Engine mechanism.
14. Correctness closure: C1-C4 and explicit provider reuse contract.
15. Future hardening intentionally excluded: selective plugin discovery/capability scope, registry freeze, backend factory/session, hot reload, distributed/capability routing, and P8.6 real vertical certification.

No Manager, Service, Store, Coordinator, Registry, state, migration, or semantic identity was introduced.

## Minimal production changes

- Preserve execution-time `OnlyResearchSpecificationError` as stable non-retryable `EXECUTION_SEMANTIC_DRIFT`; only phase/code enter bounded secret-safe detail.
- Preserve `OnlyResearchRunStoreUnavailableError` as `RESEARCH_RUN_STORE_UNAVAILABLE`; truly unknown exceptions remain `UNEXPECTED_WORKER_FAILURE`.
- Re-observe the existing external stop authority after housekeeping and immediately before claim. Entering this barrier calls the existing idempotent `stop()` transition, marks presence draining, and admits no claim.
- Return Worker process exit code from the existing StopController.
- Add immutable `OnlyPostgresOperationalConnectionOptions`, applied to the same base DSN by existing operational stores and API/Worker startup/readiness paths.
- Document and test that official RESEARCH providers can be process-reused only if execution state is call-local.

## Failure classification

| Failure | Classification | Retry | Stable mapping / action | Reason |
|---|---|---:|---|---|
| Calculation type/version unavailable during execution re-resolution | deterministic semantic/composition drift | no | `ADMISSION / EXECUTION_SEMANTIC_DRIFT` | identical Specification and process composition will fail again |
| Admission resolution fingerprint mismatch | deterministic semantic drift | no | `ADMISSION / EXECUTION_SEMANTIC_DRIFT` | admitted evidence no longer matches execution evidence |
| Dataset verified-load corruption/failure | deterministic authority failure | no | `EXECUTION / DATASET_VERIFICATION_FAILED` | immutable authority cannot be treated as transient/missing |
| Runtime structured FAILED result | semantic/runtime contract failure | no unless its exact current code is explicitly policy-owned | preserved Runtime phase/code | known machine-readable semantics are not collapsed |
| Run Store unavailable while revalidating execution | transient infrastructure failure | bounded | `OPERATIONAL / RESEARCH_RUN_STORE_UNAVAILABLE` | same semantic work may succeed after DB recovery |
| Heartbeat/Execution Store unavailable or timed out | ownership uncertainty | no local finalization | `OWNERSHIP_LOST`; lease recovery | Worker cannot prove authority |
| Unknown `RuntimeError` escaping a known boundary | unknown operational failure | bounded | `OPERATIONAL / UNEXPECTED_WORKER_FAILURE` | existing policy controls bounded retry |
| Lease expiry | transient ownership recovery | bounded | `OPERATIONAL / LEASE_EXPIRED` | stale Attempt never revives; fresh Attempt re-enters |

## Shutdown linearization contract

```text
RUNNING / IDLE
    -> stop observed before claim transaction
DRAINING
    -> mark diagnostic presence draining
    -> no new claim
    -> if an ACTIVE claim already began, keep heartbeat and drain it
    -> safe completion/cancellation boundary or ownership loss
STOPPED
```

Expiry and cancellation reconciliation may complete before the barrier because they advance existing durable operational truth. A stop arriving after `claim_once()` begins makes that claim in-flight; it does not cancel or fail the Run. `DRAINING` is not a PostgreSQL, Run, or Attempt state.

## PostgreSQL timeout contract

The one deployment DSN is augmented, not duplicated:

| Bound | Repository default |
|---|---:|
| connect timeout | 5 seconds |
| statement timeout | 5 seconds |
| lock timeout | 2 seconds |
| TCP user timeout | 5 seconds |
| keepalive | enabled; idle 5s, interval 2s, count 2 |

The conservative connect-plus-statement bound is 10 seconds. Worker startup requires it to be strictly shorter than heartbeat interval and lease duration. Run load/command, claim, heartbeat, expiry, finalization, reconciliation, presence, operational snapshot, startup version/schema inspection, and readiness use the bounded operational DSN. Explicit operator migration/backup/restore/validation retains its own lifecycle and base DSN.

Statement/lock/network timeout remains StoreUnavailable. Heartbeat timeout means ownership uncertainty; no timeout path bypasses exact Attempt/Worker/ACTIVE/unexpired fencing or creates semantic state.

## Tests and gates

- Focused Worker classification and interleaving tests: `15 passed`.
- `research-execution`: `40 passed`.
- `research-run`: `46 passed`.
- `research-postgres`: `75 passed` against PostgreSQL 16.10 with PostgreSQL 16 client, including real statement/heartbeat timeout, Worker signal, backup, and restore.
- `research-runtime`: `67 passed`.
- `research-calculation`: `129 passed`, including same-process official backend reuse conformance.
- Full architecture suite: `340 passed`.
- Mypy: `594 source files`, no issues.
- Ruff check: passed repository-wide.
- Ruff format check: `1378 files already formatted`.
- `git diff --check`: passed.

## Remaining risks

1. Default Engine composition still discovers plugin groups not required by Research. An unrelated Trading-only plugin discovery failure may prevent Research API/Worker startup. This is availability/fault-isolation coupling, not a semantic authority violation; selective discovery remains a future one-mechanism/capability-scope design problem.
2. Official Indicator, Factor, Target, and Predicate providers were audited as stateless with execution-local mutable data. The lifecycle contract is now documented and a process-reuse conformance test covers the official execution boundary; third-party conformance enforcement remains future work if a real stateful requirement appears.
3. Calculation Registry remains mutable by API, but architecture gates show no production per-claim rediscovery/registration path. A freeze framework remains unjustified.
4. Exact restore-pair semantic validation still requires the P8.6 real end-to-end recovery vertical.
5. Remote exact-SHA CI and Final-SHA certification are not complete because this is an uncommitted pre-P8.6 closure working tree.

## Verdict

The identified operational semantics gaps are closed without changing semantic identity or introducing a parallel authority. P8 remains `IN_PROGRESS`; this report does not mark P8 done or certified. P8.6 Product Closure & Final Certification remains the next phase.
