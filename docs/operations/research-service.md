# Research Service Operations

This runbook is the operator contract for the single-host/small-team Research API and Worker. PostgreSQL is the sole operational authority for Runs, Attempts, leases, cancellation intent, and Worker presence. Immutable stores under `USER_DATA_ROOT/research` remain the sole semantic authority.

## Supported environment

- Python 3.12.
- PostgreSQL server major 16; CI and local certification use PostgreSQL 16.10.
- `pg_dump` and `pg_restore` client major 16. A different major fails closed.
- One writable, durable `USER_DATA_ROOT` shared by the API and Worker.
- `ONLYALPHA_POSTGRES_DSN` supplied through the environment, never argv.

Worker presence is diagnostic only. Attempt leases remain the execution-ownership authority. PostgreSQL server time owns lease and presence coordination.

## Startup

Start in this order:

1. Start PostgreSQL 16.
2. Run `uv run python scripts/database.py status`.
3. If and only if status is `BEHIND` or `LEDGER_MISSING`, follow the migration procedure below.
4. Start the API: `uv run onlyalpha-api --user-data-root "$USER_DATA_ROOT"`.
5. Verify `GET /health/live` and `GET /health/ready`.
6. Start the Worker: `uv run onlyalpha-research-worker --user-data-root "$USER_DATA_ROOT"`.
7. Start the Web application if required.

API and Worker startup check schema compatibility and PostgreSQL major but never migrate or repair the database. Worker startup also checks its required roots and Calculation/plugin composition before it may claim work.

A Worker establishes one `OnlyEngineServices` plugin/component composition at process startup. Specification re-resolution and every Research Runtime execution in that process consume the same Calculation registry from those services. Each claimed Attempt still creates a fresh `OnlyEngine` and a fresh Research Runtime lifecycle; restarting the Worker is the only boundary that re-establishes process composition. This is a process-lifetime wiring invariant, not a new durable identity or store.

## Operational PostgreSQL I/O bounds

Runtime control-plane connections are derived from the one `ONLYALPHA_POSTGRES_DSN`; there is no Worker, heartbeat, or presence DSN.
The repository applies a 5-second connect timeout, 5-second statement timeout, 2-second lock timeout, 5-second TCP user timeout, and
explicit TCP keepalive settings to Run commands/loads, claim, heartbeat, expiry, finalization, cancellation reconciliation, presence,
diagnostic snapshots, startup version/schema inspection, and readiness. PostgreSQL timeout errors remain operational StoreUnavailable
facts. In particular, heartbeat timeout makes Attempt ownership uncertain and forbids local finalization; it is never a Research semantic
failure.

The same repository-owned options force every operational PostgreSQL session to `timezone=UTC`. Run and Attempt timestamps are strict UTC
Domain facts; a non-UTC server/database default may preserve the instant while returning a different offset and must not turn a committed
row into an unreadable authority. Startup probes, API, Worker, Run/Execution/Operations Stores, and readiness all use this UTC policy.

The conservative connect-plus-statement bound is 10 seconds. Worker startup rejects configuration unless this bound is strictly shorter
than both its heartbeat interval and lease duration. Consequently the non-daemon heartbeat and presence threads have a repository-owned
I/O bound shorter than their join deadline. Operator migration, backup, restore, and validation commands retain their explicit operator
lifecycle and are not forced into the short runtime policy.

## Shutdown

Stop Web and API as needed. Send `SIGTERM` or `SIGINT` to the Worker and wait for exit before stopping PostgreSQL. The Worker enters draining, stops new claims, keeps the current Attempt heartbeat alive, completes safe work, and then exits. Process shutdown is not a semantic failure.

The claim admission linearization rule is explicit: if the process stop request is observed before the PostgreSQL claim transaction
begins, the Worker marks presence draining and must not claim. If claim has already begun before stop is observed, that claim is in-flight
and drains normally; the next claim is forbidden. Housekeeping expiry and cancellation reconciliation may run before this barrier because
they advance existing durable operational truth rather than admit new semantic work. `DRAINING` is a process lifecycle notion, not a Run,
Attempt, or PostgreSQL state.

The Worker returns the existing application lifecycle exit codes: normal service return is `0`, `SIGINT`/`KeyboardInterrupt` is `130`,
and `SIGTERM` is `143`. A signal does not request semantic cancellation and does not make a Run fail.

If the Worker is forcibly killed, its heartbeat stops. After the lease expires, the existing Scheduler expires the Attempt and a fresh Worker creates a new Attempt for forward recovery. Never reset a Run or Attempt.

## Health and diagnostics

- `GET /health/live`: HTTP process liveness only. It remains `LIVE` during a database outage.
- `GET /health/ready`: API responsibility readiness. PostgreSQL unavailable, incompatible schema, unusable roots, or invalid composition returns HTTP 503 with a stable, secret-free reason.
- `uv run onlyalpha operations status`: deterministic recent Run diagnosis plus Worker presence.
- `uv run onlyalpha operations run RUN_ID`: deterministic Run and Attempt history ordered by Attempt number and ID.

Diagnosis codes are derived, read-only facts: `HEALTHY`, `QUEUE_AGED`, `NO_READY_WORKER`, `RUNNING_WITHOUT_ACTIVE_ATTEMPT`, `ACTIVE_LEASE_OVERDUE`, and `CANCELLATION_RECOVERY_PENDING`. They never transition a Run. Scheduler expiry, Worker execution/finalization, and the existing cancellation reconciler remain the only recovery paths.

Structured log `event` values are stable machine codes. Logs are diagnostic and must never be used for recovery.

Each operational snapshot is one PostgreSQL `READ ONLY`, `REPEATABLE READ` transaction. The first statement captures `clock_timestamp()` once as the server-side `observed_at` and establishes the MVCC observation used by the subsequent Run, Attempt, and Worker presence reads. Queue age, Worker freshness, and lease-overdue diagnosis all compare against that one returned value. PostgreSQL's default `READ COMMITTED` is insufficient because each statement could otherwise observe a different commit. This read path needs neither `SERIALIZABLE` nor row locks: it observes one stable database state and never coordinates execution or performs recovery.

## Forward-only migration

Never edit an applied migration, repair the checksum ledger, delete an unknown migration, or use a force flag. `AHEAD`, `CHECKSUM_MISMATCH`, and `HISTORY_DIVERGED` require investigation and fail closed.

Use this exact procedure:

1. `uv run python scripts/database.py status`
2. `uv run python scripts/database.py plan`
3. `uv run python scripts/database.py backup /secure/path/pre-migration.dump`
4. Create an empty isolated database whose name ends in `_restore_test`.
5. Set `ONLYALPHA_POSTGRES_RESTORE_TEST_DSN` and run `uv run python scripts/database.py restore-test /secure/path/pre-migration.dump --run-id RUN_ID`.
6. `uv run python scripts/database.py migrate`
7. `uv run python scripts/database.py status`
8. `uv run python scripts/database.py validate --run-id RUN_ID`
9. Verify API readiness and Worker startup.

Migration uses an advisory lock and one transaction. Startup never invokes migration.

## Backup and restore

`database.py backup` creates a PostgreSQL custom-format logical backup and an adjacent `.metadata.json` file. Metadata contains the backup SHA-256, creation time, repository version/SHA when available, PostgreSQL server version, pg_dump version, and exact migration IDs/checksums. It contains no DSN or credential.

`restore-test` requires an isolated empty target, verifies backup metadata and checksum, runs `pg_restore`, checks schema compatibility, verified-loads the selected Run and its ordered Attempt history, and confirms the source remains compatible.

A valid online recovery pair has this order:

1. Capture the PostgreSQL operational backup at its consistent database observation `Tdb` and wait for `pg_dump` to succeed.
2. After that, capture the immutable `USER_DATA_ROOT` snapshot at `Tfs`, where `Tfs >= Tdb`.
3. Keep the two artifacts as one deployment-owned recovery set and verify both before relying on it.

The ordering follows the execution commit contract: verified Research Result and Artifact commits happen before fenced PostgreSQL `COMPLETED` finalization. Therefore every semantic object referenced by a terminal Run in the database backup must exist in the later immutable snapshot:

```text
DB-referenced semantic objects ⊆ restored immutable semantic objects
```

Extra immutable objects are safe. For example, work may commit Result and Artifact after `Tdb` while the database backup still records `RUNNING`; after restore, ordinary verified-load and deterministic re-entry reuse those objects and converge the operational projection. Missing objects already referenced by restored terminal PostgreSQL facts are unsafe: treat the recovery set as incoherent/corrupt and fail closed. Do not reinterpret this as a cache miss, silently recompute, repair or overwrite immutable authority, or reopen a terminal Run.

The reverse online order is unsupported: a filesystem snapshot followed by a newer PostgreSQL backup can restore `COMPLETED` references whose semantic objects are absent. Worker drain may be used as a conservative maintenance optimization—drain, allow the current Attempt to finish safely, then take the database backup followed by the immutable snapshot—but drain is not a correctness prerequisite for the database-first procedure.

For an actual disaster restore:

1. Provision an empty PostgreSQL 16 database.
2. Verify backup SHA-256 against its metadata.
3. Restore with PostgreSQL 16 `pg_restore --exit-on-error`.
4. Run `database.py status` and `database.py validate` against the restored database.
5. Restore the paired immutable `USER_DATA_ROOT` snapshot and confirm its capture did not precede the database observation.
6. Through the existing Research semantic readers, verified-load every exact Research Result and Artifact reference selected for recovery validation. PostgreSQL tooling validates only operational facts and must remain semantic-store blind.
7. If any referenced terminal semantic object is absent, corrupt, or conflicting, stop and fail closed. Extra verified semantic objects require no repair.
8. Start API, check readiness, then start Worker.
9. Verified immutable-store loads and ordinary forward re-entry converge incomplete operational projections.

PostgreSQL backup is not a complete OnlyAlpha backup. Disaster recovery requires both the database backup (operational facts) and the immutable `USER_DATA_ROOT` backup (semantic facts). Use deployment-owned filesystem snapshots or tools such as restic/rsync; OnlyAlpha does not create a second Artifact backup authority.

V1 recovery objectives are:

- RPO: the latest verified logical PostgreSQL backup plus matching immutable user-data snapshot.
- RTO: the documented manual restore procedure and subsequent verified forward recovery.

PITR/WAL shipping is deployment guidance only and is not part of the P8.5 product authority.

## Failure interpretation

- No fresh Worker and queued Runs: start or diagnose the Worker; do not patch Runs.
- Active lease overdue: allow Scheduler expiry; stale Worker finalization is fenced.
- Running without an active Attempt: the next normal claim performs deterministic re-entry.
- Cancellation recovery pending: the existing reconciler verifies exact Result and Artifact evidence; complete evidence wins, absent evidence cancels, corrupt evidence fails closed.
- PostgreSQL outage during execution: heartbeat failure means ownership is uncertain/lost. The old Worker cannot finalize; after recovery, lease expiry and a fresh Attempt converge forward.
- API restart: Run truth remains in PostgreSQL and execution continues independently.
