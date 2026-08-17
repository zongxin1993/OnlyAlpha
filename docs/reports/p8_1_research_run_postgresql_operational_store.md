# P8.1 Research Run Authority & PostgreSQL Operational Store — Implementation Report

- Date: 2026-08-17
- `TASK_BASE_SHA`: `081c183c7ee1253eaf129bb715a3c29db4ebfb7e`
- Implementation HEAD: `081c183c7ee1253eaf129bb715a3c29db4ebfb7e` with intentional dirty Task worktree
- Authority: local implementation and real PostgreSQL evidence; not P8 Final-SHA certification

## Task Gate

Goal: turn “the user submitted this Research” into a transactional, persistent, concurrent-safe and restart-verifiable operational fact
without creating a second Research semantic truth.

Modification scope: Research Run Domain/Port/admission, PostgreSQL config/migration/store, operator tools, authoritative dependency audit,
canonical lanes/impact/CI/certification integration, ADR and current-truth docs.

Impact scope: P8.0 Specification resolution and Dataset admission; operational persistence only; quality infrastructure and supply-chain
evidence. Required behavior is exact durable QUEUED acknowledgement, strict restart reload/re-resolution, CAS, forward-only schema and
verified backup restore. Expansion triggers were a new authority, persistence schema, recovery boundary, dependency and verification
infrastructure; all triggered the required architecture and full-local closure. Scheduler/Worker/Attempt persistence/API/Web/promotion/
semantic data storage/HA/PITR are out of scope.

## Inherited baseline and supply chain

Current HEAD had no inherited source/test regression: P8.0.1 reported a successful 32-gate full-local verification and the worktree only
contained the user-supplied untracked P8.1 Prompt. Initial impact plan was correctly docs-only.

The preflight did confirm the stated supply-chain blind spot: CI cached Web `package-lock.json`, but dependency audit only scanned `uv.lock`.
Before adding PostgreSQL, the existing single gate was extended to scan both exact authoritative locks and emit both hashes; no parallel
fourth audit gate was created. Its focused architecture/certification tests passed. Then only `psycopg[binary] 3.3.4` was added and locked;
no ORM, Alembic, async framework or pool was introduced.

## Domain and admission decisions

Run ID is canonical opaque UUID4. Same Specification creates different Runs while preserving the same Specification and all downstream
semantic identities. Initial durable state is QUEUED; SUBMITTED has no distinct committed fact. Legal transitions are exactly QUEUED to
RUNNING/CANCELLED, RUNNING to COMPLETED/FAILED/CANCEL_REQUESTED, and CANCEL_REQUESTED to CANCELLED/COMPLETED/FAILED. Terminal states are
immutable. Cancellation is intent, not rollback, and its timestamp survives completion/failure races.

Revision starts at zero and every Domain transition increments once. The Store commits only an exact Domain successor using expected
revision and state. Failure is stable phase/code/detail without traceback or retry policy. FAILED may retain an already committed
`research_result_fingerprint`; COMPLETED requires that exact Result SHA and the current Artifact's
`artifact_content_fingerprint`. No new Artifact ID exists.

Canonical Specification JSON, schema version and fingerprint are stored. Load reparses, canonicalizes and recomputes linkage. Admission
strictly resolves, calls Dataset `load_verified_table()`, derives a canonical fingerprint over candidate Graph/Calculation/node lineage,
Statistics identities and Result Plan identity, then commits QUEUED. The evidence is an operational cross-deployment drift guard, never a
Calculation/Result identity or reuse key. Runtime execution remains responsible for defensive verified load.

`OnlyResearchRunStore` contains only `create_queued`, `load` and `commit_transition`; there is no arbitrary save/patch. The application
service returns only after PostgreSQL commit. Attempt is frozen as a future concrete execution identity distinct from Run identity, but no
unproven P8.2 Attempt/lease/heartbeat schema is published.

## Database constitution, schema and operations

ADR 0089 freezes PostgreSQL as operational-only authority, repository migration history as the sole schema authority, immutable SHA-256
ledger, advisory-locked transactional forward migration, compatibility-only application startup, no repair/down/manual production DDL,
and backup trust only after isolated restore verification.

Migration `0001_research_run_operational_authority.sql` creates exactly `onlyalpha_schema_migration` and `research_run`. Defensive CHECKs
cover states, nonnegative revision, SHA shapes, lifecycle timestamps, structured failure and completed references. It has no semantic row,
Result content, Artifact content, Attempt, Worker, lease or heartbeat table. PostgreSQL lifecycle `NOW()` is not used; only migration
ledger infrastructure uses database current time.

`scripts/database.py` provides deterministic status, read-only plan, forward migrate, pg_dump backup and guarded restore-test. DSNs are
environment injected/redacted, SQL is parameterized, and pg client passwords are environment-only rather than process arguments.
Restore-test requires a different empty target whose name ends `_restore_test`, validates migration compatibility and can strict-load an
exact Run while rechecking the source.

## Verification evidence

- Supply-chain/certification contracts: 20 focused tests passed before the PostgreSQL dependency was introduced.
- `research-run --coverage`: 37 tests passed; 100.00% lines and 100.00% branches.
- Real PostgreSQL 16.10 `research-postgres --coverage`: fresh plan/migrate/compatible/no-op, checksum tamper, unknown database migration,
  same-Spec distinct Runs, strict canonical corruption detection, two-connection same-revision race with exactly one winner, constraints,
  durable admission/restart/re-resolution, and pg_dump/isolated pg_restore/source-unchanged proof. Adapter evidence exceeded its 82%
  threshold (88.83% lines / 72.50% branches in the final targeted lane run, 13 tests).
- The PostgreSQL CI/certification job alone starts pinned `postgres:16.10`; Core lanes remain database-independent.
- `research-run` and `research-postgres` are in canonical release ordering, impact mapping and future Final-SHA mandatory evidence.

## Files and limitations

The exact implementation inventory is:

- Domain/application: `src/onlyalpha/research/run/{__init__,admission,errors,evidence,model,store}.py` and the Research public export.
- Infrastructure: `src/onlyalpha/persistence/__init__.py`,
  `src/onlyalpha/persistence/postgres/{__init__,config,migration,research_run_store}.py`, the `0001` SQL migration and
  `scripts/database.py`.
- Dependencies/quality: root `pyproject.toml`, `uv.lock`, dependency audit, certification, test-suite and impact-verifier scripts, plus
  quality and certification workflows.
- Verification: `tests/research/run/`, `tests/research/postgres/`, the Research Run/PostgreSQL architecture gates, and updated quality,
  certification, dependency-audit and impact contract tests.
- Architecture/current truth: ADR 0089, this report, README and roadmap.

P8.1 does not poll or execute QUEUED Runs. No Scheduler, Worker, claim ordering, Attempt persistence, lease, heartbeat, retry, API, Web,
promotion, RBAC, HA or PITR exists. Tested PostgreSQL 16.10 is test authority, not user production configuration. P8 remains in progress and
uncertified.

## Final verification and verdict

The final impact plan was `VERIFICATION_INFRASTRUCTURE`, selecting every release check and all 19 canonical lanes. The required full-local
command was:

```text
uv run python scripts/verify.py agent --base 081c183c7ee1253eaf129bb715a3c29db4ebfb7e
```

The first environment attempt passed all ten release-static commands and exposed a local PATH omission for Node before any semantic lane
ran. After restoring the existing Node path, the complete rerun passed 34/34 gates: release static, Web static/unit/build/E2E,
`research-specification`, `research-run` (39 collected), `research-postgres` (11 collected on PostgreSQL 16.10), every remaining Research
lane, calculation, dataset, `core-full` (2046 collected), recovery (330), Sim recovery (38), A-share (24), MiniQMT contract (34), and the
all-package build. Evidence: `test-results/verification/20260817T074438Z-081c183c7ee1-52599/`.

Two additional migration-contract cases were then added without changing production or verification infrastructure: failed migration
schema+ledger atomic rollback and simultaneous operator advisory-lock serialization. The exact affected `research-postgres --coverage`
rerun passed 13/13 with the coverage recorded above.

Verdict: **P8.1 IMPLEMENTED / VERIFIED LOCALLY; READY FOR P8.2**. This is local Task Gate evidence, not P8 Final-SHA Certification and not
a claim that P8 as a milestone is complete.
