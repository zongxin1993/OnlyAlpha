# ADR 0090: Research Execution Attempt, Lease, Fencing and Recovery Constitution

Date: 2026-08-18

Status: Accepted

## Context

ADR 0089 made `ResearchRun` the PostgreSQL operational intent/outcome authority while keeping Dataset, Calculation, Statistics, Research
Result and Artifact in their existing immutable semantic Stores. A durable QUEUED Run still needed an execution protocol that remains
correct under concurrent workers, process loss, lease expiry, stale workers, cancellation and partial semantic completion.

Physical computation cannot be guaranteed exactly once across pauses and partitions. The required property is at most one authoritative
ACTIVE ownership, fenced operational finalization, deterministic semantic re-entry and eventual terminal Run convergence.

## Decision: Run and Attempt identities

`OnlyResearchRunAttemptId` and `OnlyResearchWorkerInstanceId` are application-generated canonical UUID4 values. Attempt identity is
independent from Run identity; a process restart creates a new Worker identity. Hostname, PID and address are diagnostics only.

Attempt numbers are positive and monotonically allocated per Run while holding the Run row lock. PostgreSQL enforces
`UNIQUE(run_id, attempt_number)`. Attempt states mean:

- `ACTIVE`: this exact Attempt and Worker currently hold lease-governed operational authority;
- `SUCCEEDED`: this Attempt completed the execution and finalization protocol;
- `FAILED`: this Attempt ended with an explicit execution failure;
- `EXPIRED`: its lease crossed the fencing boundary and cannot be revived;
- `CANCELLED`: cooperative cancellation ended this Attempt before semantic completion.

Terminal Attempt facts are immutable. PostgreSQL additionally enforces one `ACTIVE` Attempt per Run with a partial unique index. Attempt
failure describes one try; Run failure describes why the overall intent finally terminated. Retry never changes a terminal Run back to
RUNNING. A retryable failed/expired Attempt leaves the Run RUNNING with no ACTIVE Attempt until a new claim.

## Decision: transactional deterministic claim

Claim is one short PostgreSQL transaction. It locks the earliest eligible Run by `(queued_at, run_id)` with
`FOR UPDATE OF research_run SKIP LOCKED`, rechecks eligibility and attempt budget, assigns the next number, creates the ACTIVE Attempt and,
for first claim, commits `QUEUED -> RUNNING` in the same transaction. Multiple workers therefore select the earliest currently unlocked
candidate; CPU start order is not claimed to be globally strict.

An execution transaction is committed before semantic work begins. No database transaction remains open while Research runs.

## Decision: lease clock, heartbeat and fencing

PostgreSQL `clock_timestamp()` is the only lease coordination clock because it represents actual server time rather than transaction-start
time. Run lifecycle timestamps continue to use the application UTC clock; these clocks answer different questions.

The default policy uses a two-minute lease, thirty-second heartbeat and three-attempt bound; `heartbeat_interval < lease_duration` is a
Domain invariant. Heartbeat uses its own connection and short transaction and succeeds only for the exact Attempt ID, Worker ID, ACTIVE
state and unexpired lease. An expired Attempt cannot be renewed or reassigned. Recovery marks it EXPIRED and creates a new Attempt.

Heartbeat, expiry and every success/failure/cancellation finalization re-prove exact Attempt ID, exact Worker ID, ACTIVE state and a valid
lease. Zero matching rows means ownership lost. Database unavailability means ownership is uncertain and forbids operational finalization.
Worker cooperation improves resource use but is not a correctness premise: stale workers may continue deterministic semantic computation,
but PostgreSQL rejects their outcome.

The general P8.1 PostgreSQL Run Store is correspondingly restricted to user-side cancellation intent (`QUEUED -> CANCELLED` and
`RUNNING -> CANCEL_REQUESTED`). It cannot claim a Run or commit execution terminal outcomes; those mutations exist only on the fenced
Execution Store business transactions.

## Decision: retry, cancellation and recovery

Retry classification is policy, not immutable Failure data. It uses stable failure code, current attempt number and `max_attempts` to
produce `RETRY` or `FINAL_FAIL`. Semantic drift, corrupt verified authority and deterministic contract failures fail finally; explicitly
temporary operational failures may retry. Lease expiry remains retryable while budget remains. Exhaustion records
`ATTEMPT_LIMIT_EXHAUSTED` and transitions the Run to FAILED.

QUEUED cancellation remains `QUEUED -> CANCELLED` with no Attempt. A claimed Run uses
`RUNNING -> CANCEL_REQUESTED -> CANCELLED`; Worker checks cancellation before Dataset work and between Runtime job/sweep/statistics/result/
artifact safe boundaries. Synchronous calculations may finish before the next boundary. Once Result and Artifact have committed and passed
verified load, success finalization wins a cancellation race and preserves `cancel_requested_at`; immutable semantic facts are never
rolled back.

Shutdown stops new claims and drains current work while heartbeats continue. Forced process loss simply stops heartbeats and follows the
same expiry/reclaim path; no PAUSED/STOPPING Run state exists.

## Decision: semantic re-entry and finalization order

Worker reloads the exact Run, verified-loads its Dataset, deterministically resolves its canonical Specification, compares current
admission evidence, and executes only through `OnlyEngine -> OnlyResearchRuntime`. Runtime cooperative control is an operational-neutral
checkpoint Port and does not depend on Scheduler, Worker, Attempt or PostgreSQL.

Recovery stores no factor/node/progress checkpoint. A new Attempt recomputes the same Workload and relies on existing immutable Stores to
verified-load/reuse already committed Calculation, Statistics, Result and Artifact facts. Success ordering is:

```text
immutable semantic commits
-> verified Result and Artifact
-> fenced PostgreSQL transaction
-> Attempt SUCCEEDED + Run COMPLETED
```

An Artifact-commit/process-crash window therefore leaves Run RUNNING; after expiry a new Attempt verified-reuses the exact Artifact and
completes operational finalization.

## Consequences

PostgreSQL migration `0003_research_run_attempt_authority` adds only Attempt, ownership, lease, heartbeat and failure-history facts plus
minimal constraints/indexes. Published `0001` and `0002` remain byte-immutable. There is no Worker registry, in-memory durable queue,
semantic progress table, mutable Research checkpoint, Redis/Kafka/Celery, HTTP command or Web control in this increment.
