# P8.2 Research Scheduler, Worker & Recovery — Implementation Report

- Date: 2026-08-18
- `TASK_BASE_SHA`: `6bc7e46151df959fa362d1976b628f94a4ddc0f0`
- Implementation HEAD: `6bc7e46151df959fa362d1976b628f94a4ddc0f0` with intentional dirty Task worktree
- Authority: local implementation and PostgreSQL 16.10 evidence; not P8 Final-SHA certification

## Goal and Task Gate

P8.2 turns a durable QUEUED `ResearchRun` into a transactional, lease-governed, fenced and recoverable execution protocol. Scope is
Attempt Domain/Port, Scheduler/Worker application services, PostgreSQL 0003/adapter, cooperative Runtime safe boundaries, deterministic
semantic re-entry, cancellation/retry/shutdown, architecture/quality/CI integration and current-truth documentation. HTTP/Web commands,
Redis/Kafka/Celery, priorities, Worker registry, mutable semantic progress/checkpoint and P8 certification remain out of scope.

The authority split is unchanged: PostgreSQL owns Run/Attempt/lease operational facts; existing immutable Stores own Dataset,
Calculation, Statistics, Research Result and Artifact semantic facts. Scheduler never plans semantic work. Worker only enters execution
through `OnlyEngine -> OnlyResearchRuntime`.

## Attempt, ownership and state machine

`OnlyResearchRunAttemptId` and `OnlyResearchWorkerInstanceId` are independent canonical UUID4 values. A process restart creates a new Worker
identity. `attempt_number` is a positive per-Run monotonic sequence allocated while the Run row is locked. States are:

```text
ACTIVE -> SUCCEEDED | FAILED | EXPIRED | CANCELLED
```

ACTIVE means the exact Attempt/Worker owns lease-governed operational mutation authority. All terminal Attempt facts are immutable.
FAILED/EXPIRED require the stable P8.1 `phase/code/detail` failure value; SUCCEEDED/CANCELLED forbid failure. Attempt failure is history, not
the overall Run outcome. Retry leaves Run RUNNING and creates Attempt N+1; terminal Runs never reopen.

PostgreSQL enforces `UNIQUE(run_id, attempt_number)` and a partial unique index for one ACTIVE Attempt per Run. Domain validation mirrors
state/failure/time relationships.

## Claim, lease and fencing

Claim uses one short transaction and selects by `queued_at ASC, run_id ASC` with `FOR UPDATE OF research_run SKIP LOCKED`. It rechecks no
ACTIVE Attempt and attempt budget, assigns the next number, inserts ACTIVE Attempt and atomically commits first `QUEUED -> RUNNING`. A
retry claim keeps Run RUNNING. Research execution occurs outside database transactions.

Lease coordination exclusively uses PostgreSQL `clock_timestamp()` because lease expiry is cross-process actual-time coordination. P8.1
Run lifecycle timestamps remain application UTC time. Defaults are two-minute lease, thirty-second heartbeat and three attempts; the
policy enforces positive values and heartbeat shorter than lease.

Heartbeat has a dedicated thread and independent short database connections. Heartbeat and every terminal mutation require exact Attempt
ID, Worker ID, ACTIVE state and unexpired lease. Zero matched rows means ownership lost. Expired Attempts become immutable EXPIRED and are
never reassigned/revived; recovery creates a new Attempt. Database unavailability makes ownership uncertain and suppresses finalization.

The P8.1 PostgreSQL Run Store was cut over to accept only cancellation intent (`QUEUED -> CANCELLED` and
`RUNNING -> CANCEL_REQUESTED`). Direct claim or execution completion/failure/cancellation through the generic transition method fails
closed, so no legacy operational path can bypass Attempt fencing.

## Retry, cancellation and shutdown

Retry classification is separate policy over stable failure code, attempt number and `max_attempts`. Semantic/admission drift and verified
authority corruption fail finally; explicitly temporary operational failures can retry. Expiry after the last allowed Attempt transitions
Run to FAILED with `ATTEMPT_LIMIT_EXHAUSTED`.

QUEUED cancellation remains direct CANCELLED with no Attempt. A claimed Run observes CANCEL_REQUESTED before Dataset work and at Runtime
boundaries before each Job, Sweep, Statistics, Result and Artifact phase. Cooperative cancellation ends Attempt/Run CANCELLED. A synchronous
calculation can finish to the next safe boundary. Once Artifact semantic completion exists, success finalization is allowed from
CANCEL_REQUESTED and preserves the cancellation timestamp.

`OnlyResearchWorkerService.stop()` stops new claims and lets current work drain with heartbeats. Forced loss follows the ordinary
heartbeat-stop -> expiry -> new-Attempt path; no new Run state exists.

## Worker Runtime entry and semantic recovery

Every Attempt reloads the exact Run, verified-loads the exact Dataset Snapshot, deterministically resolves the canonical Specification,
recomputes and compares admission evidence, then passes the exact `OnlyResearchWorkloadPlan` to `OnlyEngine`. The Runtime remains free of
Scheduler/Attempt/PostgreSQL dependencies; an operational-neutral checkpoint Port supplies safe-boundary cancellation/ownership signals.

There is no mutable Research checkpoint. A new Attempt re-enters the same immutable authority chain. Calculation/Statistics/Result/
Artifact Stores verified-reuse identical committed facts and fail closed on conflict/corruption. Operational success is committed only
after exact Result and Artifact verified load:

```text
semantic commits -> verified Result/Artifact -> fenced transaction
-> Attempt SUCCEEDED + Run COMPLETED
```

The real integration test executes a complete Engine/Runtime, intentionally leaves its committed Artifact behind with Run RUNNING,
expires Attempt 1, creates fresh Store/Worker/Engine objects for Attempt 2, re-enters, and completes with the exact same Result/Artifact
fingerprints. This covers the highest-value Artifact-commit/crash window and recreated-service recovery.

## Migration and PostgreSQL evidence

Forward migration `0003_research_run_attempt_authority.sql` adds only `research_run_attempt`, operational constraints and the minimal claim/
expiry/history indexes. Published 0001 and 0002 bytes remain unchanged and are frozen by SHA tests. Real PostgreSQL 16.10 proved fresh
M1/M2/M3, exact existing M1/M2 -> M3 planning/application with unchanged Run reload, checksum tamper failure, backup/isolated restore,
two-Worker one-Run claim, deterministic multi-Run order, heartbeat extension, expiry/reclaim, stale heartbeat/success/failure/cancel fencing,
bounded retry, cancellation/completion race and direct SQL constraints.

Canonical `research-postgres --coverage`: 45 passed; aggregate PostgreSQL package 85.37% lines / 71.79% branches, 83.00% combined gate.
The suite used PostgreSQL server 16.10 and PostgreSQL 16.15 client tools for dump/restore compatibility.

## Quality, impact and CI

New `research-execution` owns Attempt/Policy/Scheduler/Worker unit/application tests and the execution architecture firewall. It excludes
external DB tests, runs with bounded parallelism and has formal 95% line / 85% branch thresholds. Final local evidence: 19 passed, 96.84%
lines, 88.16% branches, 95.28% combined coverage. `research-runtime --coverage` passed 66 tests at 99.03% lines / 96.67% branches.

Impact rules propagate Execution changes to `research-execution + research-postgres`, Run changes to Run/Execution/Postgres, Runtime and
Workload changes to Execution consumers, and PostgreSQL changes to both execution application and real database proofs. The new lane is in
release ordering, PR/main CI matrices, coverage workflow and Final-SHA mandatory matrix. This verification-infrastructure self-change
requires one FULL_LOCAL `verify.py agent` closure.

## Verification closure

- Initial `verify.py plan`: `DOCS_ONLY` for the user-provided untracked Prompt.
- Targeted pure/Runtime/architecture: PASS.
- `research-execution --coverage`: PASS, 19 tests, 96.84% lines / 88.16% branches.
- `research-runtime --coverage`: PASS, 66 tests, 99.03% lines / 96.67% branches.
- PostgreSQL 16.10 `research-postgres --coverage`: PASS, 45 tests, 85.37% lines / 71.79% branches.
- Final plan: `VERIFICATION_INFRASTRUCTURE`, complete release checks and all 20 canonical lanes selected.
- Final `verify.py agent`: `IMPACT VERIFIED`, 35/35 gates passed. It included ten release-static commands, Web static/unit/build/E2E,
  all Research lanes, `core-full` (2074 collected), recovery (330), Sim recovery (38), A-share (24), MiniQMT contract (34) and all-package
  build. Final evidence: `test-results/verification/20260818T010406Z-6bc7e46151df-19962/`.

Precursor full-local attempts transparently exposed and closed three integration issues before the successful run: one test file needed
formatting after import auto-fix; the constrained local PATH omitted the existing Node binary; and legacy architecture/current-increment
assertions needed to recognize the new Research Execution namespace, P8.2 status and bounded non-daemon heartbeat ownership. No failure was
waived or skipped.

## Limitations and readiness

V1 is a simple bounded single-Worker service composition; concurrency comes from multiple service instances rather than an unbounded local
pool. There is no backoff/priority/capacity/Worker registry, forced Python-thread interruption, HTTP command, Web UI, HA/PITR certification
or broad PostgreSQL matrix. Exactly-once physical computation is not claimed; authoritative ownership and finalization are fenced while
semantic duplicate work remains deterministic/immutable.

Verdict: **P8.2 IMPLEMENTED / VERIFIED LOCALLY; READY FOR P8.3**. The implementation is ready for P8.3 to add a thin command/API boundary.
P8 remains in progress and uncertified.
