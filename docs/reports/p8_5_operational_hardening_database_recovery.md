# P8.5 Operational Hardening & Database Recovery

## Baseline

- Start SHA: `be4b7b13ac60efa044706003fb3e4e9154e13181`
- End SHA: uncommitted working tree on the same HEAD
- Start working tree: only `prompts/P8.5OperationalHardening&DatabaseRecovery.md` was untracked
- Release graph: `0.8.5`
- Milestone status: P8 remains `IN_PROGRESS`

## Repository facts before implementation

- `onlyalpha-api` was the existing full API executable and failed closed on incompatible schema at startup.
- Scheduler, Worker, lease heartbeat, expiry, retry fencing, cancellation reconciliation, semantic completion probing, and Engine Research Runtime execution existed as library capabilities.
- No production Worker executable/composition root existed.
- No operational health endpoints, idle-Worker presence, derived stuck diagnosis, or read-only Run+Attempt operator view existed.
- Migrations 0001–0005 and explicit `database.py status/plan/migrate/backup/restore-test` existed.
- Backup metadata/checksum, same-major tool policy, full restored Attempt/domain validation, and process-level restart/crash evidence were absent.
- The P8.4.4.1 1D/3+ exact Decimal renderer collision gap remained and required the prompt-authorized micro-fix.

## Operational authority review

- Run authority: `OnlyResearchRun` transitions plus PostgreSQL CAS in `research_run`.
- Attempt authority: `OnlyPostgresResearchExecutionStore` plus `research_run_attempt`.
- Lease clock authority: PostgreSQL `clock_timestamp()`.
- Worker presence authority: `research_worker_presence`, written by the Worker with PostgreSQL server time and used only for diagnostics.
- Diagnostics authority: none; diagnoses are ephemeral deterministic projections from one PostgreSQL snapshot.
- Migration authority: ordered repository SQL, SHA-256 ledger, advisory lock, and explicit operator invocation.
- Semantic authority: existing immutable Dataset/Calculation/Statistics/Research Result/Artifact stores.

No semantic content moved into PostgreSQL. Presence does not enter claim, lease, retry, completion, failure, cancellation, or expiry predicates.

## Changed components

### Worker lifecycle

- Added `onlyalpha-research-worker` as a composition-only executable.
- Reused existing plugin discovery, Dataset/Result/Artifact stores, resolver, Scheduler, Worker, Cancellation Reconciler, and `OnlyEngineResearchRuntimeExecutor`.
- Added fail-closed startup checks for PostgreSQL major/schema, required roots, and registry composition.
- Added SIGINT/SIGTERM draining: no new claim, active execution retains heartbeat, then exits.
- Added stable structured Worker/claim/outcome/heartbeat-loss events without DSN or credentials.

### Health, presence, and diagnostics

- Added `/health/live`, independent of PostgreSQL.
- Added `/health/ready`, with deterministic 503 reasons for unavailable PostgreSQL, incompatible schema, unusable roots, or invalid composition.
- Added minimal Worker presence with `worker_instance_id`, `started_at`, `last_seen_at`, `service_version`, and `draining_since`.
- Added the closed read-only diagnosis vocabulary: `HEALTHY`, `QUEUE_AGED`, `NO_READY_WORKER`, `RUNNING_WITHOUT_ACTIVE_ATTEMPT`, `ACTIVE_LEASE_OVERDUE`, and `CANCELLATION_RECOVERY_PENDING`.
- Added `onlyalpha operations status` and `onlyalpha operations run RUN_ID`; Attempt history is ordered by `(attempt_number, attempt_id)`.

### Database operations

- Froze PostgreSQL server major 16 and `pg_dump`/`pg_restore` client major 16.
- Backup now emits an adjacent secret-free metadata JSON with SHA-256, versions, repository evidence, and exact migration checksums.
- Restore-test now validates metadata/SHA, isolated empty target, same-major policy, schema, selected Run, ordered Attempt history, and source compatibility.
- Added explicit post-migration `database.py validate`.
- Pinned CI service to PostgreSQL 16.10 and client package to major 16.

### P8.4 prerequisite micro-fix

Candidate surface projection now rejects distinct exact numeric assignments that collapse to the same JavaScript Number coordinate for every numeric dimension, including 1D and 3+ surfaces. Exact assignment and all semantic identities remain unchanged.

## Schema change

- New migration: `0006_research_worker_presence.sql`
- SHA-256: `0a5d05a7ef81259746d19ead884cfbdf4924099415057ee0116ba96e79532abf`
- Published 0001–0005 checksums are unchanged and frozen by architecture tests.
- No Run, Attempt, Specification, Result, Artifact, or semantic identity changed.

## Determinism review

- Claim order remains `(queued_at, run_id)`.
- Expiry order remains `(lease_expires_at, run_id, attempt_id)`.
- Attempt audit order is `(attempt_number, attempt_id)`.
- Run operator order is `(queued_at DESC, run_id DESC)`.
- Diagnosis priority is explicit and uses one PostgreSQL `observed_at` fact.
- Presence freshness and leases use PostgreSQL server time; process wall time is never coordination authority.
- Recovery remains forward-only: expire stale Attempt, create fresh Attempt, verified immutable re-entry/reuse, then fenced finalization.

## Failure matrix

- Worker SIGTERM: presence becomes draining, new claims stop, service exits without projecting Run failure.
- Worker killed after claim: ACTIVE Attempt remains durable, expires, a fresh Attempt #2 is claimed, and stale Attempt finalization is rejected.
- Worker execution/Result commit death: fresh services re-enter and preserve committed Result bytes/identity.
- Artifact committed before Run completion: fresh execution converges to `COMPLETED` with the exact same Result and Artifact references.
- Cancellation plus committed semantics plus Worker loss: lease expiry followed by reconciliation converges to `COMPLETED` (success wins).
- PostgreSQL temporarily rejects connections during ACTIVE execution: heartbeat failure records ownership loss in process state, Worker does not finalize, lease expires after connectivity returns, fresh Attempt claims, stale completion is fenced.
- API kill/restart: the same PostgreSQL Run remains visible and unchanged.
- Worker restart: durable queue/Attempt truth is PostgreSQL-owned, not process-owned.
- Corrupt immutable evidence: cancellation recovery fails closed rather than treating it as missing or rebuilding.

## Database recovery evidence

- Real server: PostgreSQL `16.10` Docker image.
- Real local clients: PostgreSQL `16.15` `pg_dump` and `pg_restore`, satisfying same-major policy.
- Fresh migration reached `COMPATIBLE`; append-only/history/checksum/advisory-lock tests passed.
- Custom-format backup and metadata SHA-256 were generated.
- Same-source and non-empty restore targets were rejected.
- Isolated restore succeeded and verified schema, exact Run, ACTIVE Attempt history, and unchanged source.
- Real temporary database connection denial caused Worker ownership loss and forward recovery as designed.

RPO is the latest verified logical database backup plus matching immutable user-data snapshot. RTO is the documented manual restore and verified forward-recovery procedure. PITR/WAL automation remains outside P8.5.

## Test evidence

- `uv run python scripts/test_suite.py research-execution` — 33 passed.
- `uv run python scripts/test_suite.py research-run` — 46 passed.
- `uv run python scripts/test_suite.py research-command` — 38 passed.
- `uv run python scripts/test_suite.py research-postgres` against PostgreSQL 16.10 — 71 passed after the final outage test.
- `uv run python scripts/test_suite.py recovery` — 330 passed, metrics exit code 0.
- `uv run python scripts/web_suite.py unit` — 85 passed with 100% line coverage.
- `uv run python scripts/web_suite.py static` — OpenAPI freshness, ESLint, Prettier, and TypeScript passed.
- `uv run python scripts/web_suite.py build` — production build passed.
- `uv build --all-packages` — all 0.8.5 distributions built.
- `uv run mypy src/onlyalpha` — 594 source files passed.
- `uv run ruff check ...` and `uv run ruff format --check ...` — passed.
- `uv run python scripts/version_sync.py check` and `scripts/export_research_openapi.py check` — passed.
- `git diff --check` — passed.

## Remaining risks

- This is a single-host/small-team operational closure, not a distributed Worker platform.
- Presence rows age naturally and are interpreted by freshness; no registry cleanup authority exists by design.
- Logical backup RPO depends on deployment scheduling and matching `USER_DATA_ROOT` snapshots.
- PITR, WAL upload, Kubernetes, distributed scheduling, and a full observability platform remain explicit non-goals.
- P8 still requires P8.6 Product Closure, an exact frozen Final SHA, and Final-SHA Certification before it may be declared DONE/CERTIFIED.

## Verdict

`P8.5 — IMPLEMENTED / VERIFIED LOCALLY`

PostgreSQL remains the sole operational-state authority and immutable stores remain the sole semantic-truth authority across API/Worker restart, Worker crash, lease loss, temporary PostgreSQL unavailability, explicit migration, logical backup, and isolated restore. Diagnostics are read-only derived facts; recovery is forward-only and fenced; no second Scheduler, Recovery authority, semantic Store, startup migration, or hidden repair path was introduced.
