# P8.5 Closure — Operational Determinism and Recovery Coherence

## Repository baseline

- Start SHA: `3f2882bba03f75754b82e10df4f2ba11b43610f1`
- Branch: `master`
- Start state: the task prompt was the only untracked file; no tracked modifications were present.
- Final SHA: not created. This report records pre-commit working-tree evidence, not Final-SHA certification.

## Repository facts and root cause

The current implementation matches the P8.5 authority model: PostgreSQL owns mutable Run, Attempt, lease, cancellation-intent, and Worker-presence facts; immutable stores under `USER_DATA_ROOT/research` own semantic truth. Diagnostics are read-only, presence is not ownership, the Scheduler and PostgreSQL adapters are semantic-store blind, and Worker semantic execution enters through `OnlyEngine -> OnlyResearchRuntime`.

`OnlyPostgresResearchOperationsStore.load_operational_snapshot()` previously issued `observed_at`, Run, Attempt, and presence queries in one implicit transaction without selecting an isolation level. PostgreSQL therefore used `READ COMMITTED`, whose snapshot is statement-scoped. A concurrent claim could produce a returned combination such as an old `QUEUED` Run and a newly committed ACTIVE Attempt even though that combination never existed at one database observation.

## Resolution and concurrency evidence

The operational adapter now sets the transaction to `READ ONLY` and `REPEATABLE READ` before its first statement. The existing single server-side `clock_timestamp()` value remains the observation clock for every diagnosis derived from the returned snapshot. This is the minimal database-native fix: no lock, cache, retry, snapshot table, `SERIALIZABLE` transaction, mutation port, or new authority is required.

The PostgreSQL 16.10 integration test deliberately pauses a real reader after its Run query, commits a real claim through a second connection, and then lets the reader continue to Attempt and presence reads. The first reader remains internally consistent as `QUEUED + no Attempt`; a subsequent reader sees `RUNNING + ACTIVE Attempt`. The test also verifies the server reports `repeatable read` and `transaction_read_only=on` inside the observed transaction.

## Recovery coherence

Actual Worker ordering remains semantic Result/Artifact completion and verified references before fenced PostgreSQL `COMPLETED` finalization. The supported online recovery pair is therefore database-first:

```text
PostgreSQL consistent backup at Tdb
→ immutable USER_DATA_ROOT snapshot at Tfs, Tfs >= Tdb
```

The recovery invariant is:

```text
DB-referenced semantic objects ⊆ restored immutable semantic objects
```

Extra immutable objects are allowed and converge through verified deterministic re-entry/reuse. A terminal PostgreSQL reference whose Result or Artifact is missing, corrupt, or conflicting makes the recovery set incoherent and must fail closed; it is not permission to rebuild, repair, overwrite, delete, or reopen terminal authority. Worker drain reduces forward-recovery work but is not required for correctness. PostgreSQL backup/restore tooling continues to validate operational facts only; existing semantic readers validate exact immutable references.

## Authority and architecture review

| Concern | Authority / permission |
|---|---|
| Run state and cancellation intent | PostgreSQL `research_run`; changed only through Domain-valid CAS/fenced execution paths |
| Attempt ownership and history | PostgreSQL `research_run_attempt`; exact ACTIVE Attempt, Worker ID, and unexpired server-clock lease fence execution |
| Lease clock | PostgreSQL server `clock_timestamp()` |
| Worker presence | PostgreSQL `research_worker_presence`; diagnostic writes only, never an ownership predicate |
| Semantic truth | Immutable Dataset, Calculation, Statistics, Research Result, and Artifact stores |
| Diagnostics | Ephemeral deterministic projection of one read-only operational MVCC snapshot |
| Migration | Ordered repository migrations plus exact PostgreSQL checksum ledger |

Run claim ordering remains `(queued_at, run_id)`, Attempt history remains `(attempt_number, attempt_id)`, expiry ordering is unchanged, operator Run projection remains its existing documented order, diagnosis priority remains explicit, and Worker freshness and lease decisions remain server-time based. Database unavailability and integrity uncertainty still fail closed.

No migration was added or modified. No new state, Manager, Store, recovery worker, backup coordinator, test-only production hook, semantic identity, or alternate Engine/Runtime path was introduced.

## Changed files

- `src/onlyalpha/persistence/postgres/research_operations_store.py`: explicit read-only repeatable-read observation.
- `tests/research/postgres/test_postgres_authority.py`: real PostgreSQL Reader/Writer interleaving proof.
- `docs/operations/research-service.md`: observation and recovery-pair invariants, supported ordering, and failure interpretation.
- `docs/reports/p8_5_closure.md`: closure evidence and verdict record.

## Verification evidence

All closure-required lanes passed:

| Command | Result |
|---|---|
| `uv run python scripts/test_suite.py research-execution` | 33 passed |
| `uv run python scripts/test_suite.py research-postgres` against PostgreSQL 16.10 and v16 clients | 72 passed, including concurrency and isolated backup/restore |
| `uv run python scripts/test_suite.py research-run` | 46 passed |
| `uv run python scripts/test_suite.py recovery` | 330 passed; existing performance warnings only |
| `uv run python -m pytest tests/architecture/test_postgres_operational_authority.py tests/architecture/test_research_execution_boundaries.py -q` | 21 passed |
| `uv run mypy src/onlyalpha` | no issues in 594 source files |
| `uv run ruff check src tests packages scripts` | passed |
| `uv run ruff format --check src tests packages scripts` | 1,378 files already formatted |
| `git diff --check` | passed |

Migration files `0001` through `0006` retain their baseline SHA-256 values and no `0007` exists.

An additional whole-directory architecture audit collected 338 tests and reported 335 passed plus three pre-existing gate inconsistencies unrelated to C1/C2: the certification contract still expects the P8.4.4.1 documentation label, and two older firewalls do not recognize the existing P8.5 `research/worker_main.py` composition root. The canonical PostgreSQL and Research execution architecture gates listed above pass. Scope control requires recording these baseline issues rather than changing unrelated production boundaries or weakening tests in this closure.

## Remaining risks

- Deployment tooling owns immutable filesystem snapshot creation and recovery-pair retention; OnlyAlpha does not create a second backup authority.
- Exact semantic-reference validation across a restored pair is a documented Reader-boundary procedure, not yet a single P8.6 end-to-end certification command.
- The three stale whole-suite architecture expectations described above should be reconciled with current P8.5 repository truth outside this two-issue closure.

## Remaining P8.6 work

P8 remains `IN_PROGRESS`. P8.6 Product Closure and Final-SHA Certification must run the complete PostgreSQL-to-browser product vertical, restart/crash/recovery scenarios, coherent restore evidence, phase gate, and exact Final-SHA certification. This closure does not claim `P8 DONE`.

## Verdict

`P8.5 CLOSURE — PASS`

P8 remains `IN_PROGRESS`; no P8 or Final-SHA certification claim is made.
