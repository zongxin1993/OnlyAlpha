# ADR 0089: Research Run Operational Authority and PostgreSQL Constitution

- Status: Accepted
- Date: 2026-08-17
- Related: ADR 0072–0075, 0083–0088

## Context

P8.0 owns the portable `OnlyResearchSpecification` and deterministic resolution into the existing immutable Research semantic
authorities. A server submission was still only a process-local fact. P8.1 needs a transactional authority that survives process and
application restart without moving Dataset, Calculation, Statistics, Research Result or Artifact content into a mutable database.

## Decision: Research Run authority

`OnlyResearchRunId` is an opaque application-generated canonical UUID4. Run identity is independent from Specification, Calculation,
Statistics, Research Result and Artifact identities. Submitting the same Specification twice creates two Runs by default; future command
retry deduplication belongs to the P8.3 Idempotency Key contract. `specification_fingerprint` is deliberately not unique.

The first durable state is `QUEUED`; `SUBMITTED` is not persisted because no durable submission exists before transaction commit and a
committed submission is already eligible for future scheduling. The V1 state machine is:

```text
QUEUED → RUNNING → COMPLETED | FAILED | CANCEL_REQUESTED
QUEUED → CANCELLED
CANCEL_REQUESTED → CANCELLED | COMPLETED | FAILED
```

`COMPLETED`, `FAILED` and `CANCELLED` are immutable terminal states. Cancellation is an intent to stop at a future safe boundary, never a
rollback of immutable semantic facts. A cancel race may therefore complete or fail. Every transition is produced by the unique Domain
transition authority and increments `revision` exactly once. Persistence commits it with `run_id + expected revision + expected state`
CAS; a zero-row update is an explicit concurrency conflict.

Run lifecycle time is injected as timezone-aware UTC by the application Clock boundary. PostgreSQL does not generate Run timestamps.
`OnlyResearchRunFailure` is the stable `(phase, code, detail)` operational fact; traceback belongs in logs and retry policy belongs to
P8.2. A failed Run can retain an already committed Research Result reference when later Artifact commit fails.

The durable request evidence is exact canonical Specification JSON, schema version and fingerprint. Every load strictly parses the
document, reproduces canonical JSON and recomputes its fingerprint. Admission strictly resolves the Specification, verified-loads the
exact Dataset Snapshot, derives one canonical `admission_resolution_fingerprint`, then commits `QUEUED`. Evidence covers exact candidate
Graph/Calculation/node identities, Statistics identities and Research Result Plan identity. It is operational drift evidence, not a new
semantic identity or reuse key. A future worker must verified-load Dataset again, re-resolve and compare this evidence.

`OnlyResearchRunStore` exposes `create_queued`, exact `load` and `commit_transition`; it has no generic save, patch or update. Durable
acknowledgement occurs only after PostgreSQL commit. Semantic completion ordering remains Result commit, Artifact commit, verified exact
references, then operational `COMPLETED` projection. A crash before the last step legitimately leaves `RUNNING` for forward recovery.

One Research Run may eventually own multiple concrete execution Attempts, and Attempt identity is distinct from Run identity. P8.1 has no
Scheduler, Worker, claim, retry, lease or heartbeat consumer, so it publishes no speculative Attempt table or state machine. P8.2 must add
the minimum proven Attempt persistence through a forward migration.

## Decision: PostgreSQL constitution

PostgreSQL is the sole Research Run operational write authority. It stores canonical request evidence, lifecycle state/history,
structured failure and exact existing Result/Artifact SHA references. It never stores Dataset rows, Calculation rows, Factor values,
Statistics rows, Research Result content or Artifact content.

The database constitution is:

1. Domain first, application contract second, persistence port third, schema last.
2. Ordered repository migration history is the only schema authority.
3. Published migration bytes and their SHA-256 ledger entries are immutable.
4. Production evolution is forward-only; no down migration, rollback repair or arbitrary SQL entry exists.
5. Application startup performs compatibility checking only and never migrates or repairs.
6. Missing, behind, ahead, unknown or checksum-mismatched history fails closed with stable operator diagnostics.
7. Migration uses one PostgreSQL advisory lock and transactional schema-plus-ledger commit.
8. Manual production DDL is forbidden; every schema change requires a new durable domain fact and migration.
9. Backup is not trusted until restored into an isolated, empty, explicitly guarded test database and verified through schema and Domain
   load.
10. Database change is an architecture event and requires real pinned-PostgreSQL evidence.

Migration `0001_research_run_operational_authority` creates only the checksum ledger and `research_run`. Domain enum is defended by a TEXT
CHECK rather than PostgreSQL ENUM so future state evolution remains a forward migration. Constraints defend revision, SHA format,
state/timestamp/failure combinations and mandatory completed references. `psycopg[binary]` is the only new runtime dependency: it provides
typed explicit transactions and parameters without introducing ORM, migration framework, async framework or pool authority.

`scripts/database.py` is the explicit operator boundary for status, read-only plan, forward migrate, backup and restore-test. DSN is
environment-injected and redacted; passwords are not printed or passed in PostgreSQL client command arguments. Tested PostgreSQL 16.10 is
the CI/test authority, not a guess about user production deployment.

## Consequences

- Process restart can recover the exact durable `QUEUED` Run and re-prove accepted semantics.
- Same-Spec operational history and immutable semantic reuse remain fully decoupled.
- Lost updates fail through CAS rather than last-writer-wins.
- P8.2 can begin from durable QUEUED Runs but must not redesign Run identity, Specification evidence or migration authority.
- Scheduler/Worker/API/Web, Attempt persistence, retry, lease, heartbeat, promotion, HA, PITR and production deployment remain out of scope.
