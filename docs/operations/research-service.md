# Research Service Operations

本页保留旧 Research API/Worker 的运行与恢复约束，不是当前完整的部署或恢复操作手册。
当前入口以[部署文档](../deployment.md)和 [Rust 后端规范](../rust-product-backend.md)为准。下文的旧 Python 服务接线不能运行。

## Supported environment

- Python 3.12.
- PostgreSQL server major 18; the development Compose topology pins PostgreSQL 18.6.
- `pg_dump` and `pg_restore` client major 18. A different major fails closed.
- One writable, durable Research semantic-store namespace shared by the API and Worker. Local mount paths may differ, but each path must
  expose the same immutable namespace identity.
- `ONLYALPHA_POSTGRES_DSN` supplied through the environment, never argv.

Worker presence is diagnostic only. Attempt leases remain the execution-ownership authority. PostgreSQL server time owns lease and presence coordination.

## Startup

当前日常 Web/API 启停使用[部署文档中的原生应用入口](../deployment.md#ordinary-shipping-webapi-startup)。
旧 Compose `api`、`bootstrap` 和 Python Worker 启动流程已退役，不要按旧顺序执行。

The explicit initialization command creates immutable `research/.onlyalpha-semantic-store.json`, binds that namespace ID to the
PostgreSQL deployment, and creates the canonical semantic directories. It is idempotent only for the same binding. It refuses a
non-empty root without identity and refuses a different existing PostgreSQL binding; there is no rebind command.

API and Worker startup check schema compatibility, PostgreSQL major and exact deployment/store identity but never initialize, migrate,
rebind or repair authority. A mismatch keeps the API not-ready and blocks Research product routes. Worker startup fails before presence,
claim or semantic execution. Worker startup also checks its required roots and Calculation/plugin composition before it may claim work.

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
- `OnlyResearchOperationalDiagnosticService` 是 stale worker、Run/Attempt history 和 failure diagnosis 的唯一 application semantics。

Diagnosis codes are derived, read-only facts: `HEALTHY`, `QUEUE_AGED`, `NO_READY_WORKER`, `RUNNING_WITHOUT_ACTIVE_ATTEMPT`, `ACTIVE_LEASE_OVERDUE`, and `CANCELLATION_RECOVERY_PENDING`. They never transition a Run. Scheduler expiry, Worker execution/finalization, and the existing cancellation reconciler remain the only recovery paths.

Structured log `event` values are stable machine codes. Logs are diagnostic and must never be used for recovery.

Each operational snapshot is one PostgreSQL `READ ONLY`, `REPEATABLE READ` transaction. The first statement captures `clock_timestamp()` once as the server-side `observed_at` and establishes the MVCC observation used by the subsequent Run, Attempt, and Worker presence reads. Queue age, Worker freshness, and lease-overdue diagnosis all compare against that one returned value. PostgreSQL's default `READ COMMITTED` is insufficient because each statement could otherwise observe a different commit. This read path needs neither `SERIALIZABLE` nor row locks: it observes one stable database state and never coordinates execution or performs recovery.

## Forward-only migration

Never edit an applied migration, repair the checksum ledger, delete an unknown migration, or use a force flag. `AHEAD`, `CHECKSUM_MISMATCH`, and `HISTORY_DIVERGED` require investigation and fail closed.

当前 PostgreSQL 迁移走 Rust 后端的显式运维命令
`onlyalpha-backend --migrate-postgres-schema <absolute-sql-directory>`。
该命令不在启动时运行，使用 advisory lock 和单个事务核验并应用待执行迁移。
旧 Python `status`、`plan`、`backup`、`restore-test` 和 `validate` 流程已退役；不能把 Rust 迁移命令视为完整替代。
缺少经过验证的成对备份和恢复路径时，不得对正式数据执行迁移或恢复。

## Backup and restore

下面记录成对备份与恢复必须满足的条件，不是可直接执行的步骤。
旧备份和隔离恢复验证脚本已退役，当前没有这一整套已验证的替代入口。
备份应记录内容校验值、工具与服务器版本及迁移身份，不得包含 DSN 或凭据。

The PostgreSQL backup contains the deployment's expected semantic-store ID. The paired filesystem snapshot contains the immutable
namespace identity metadata. A restored pair is coherent only when these typed IDs are equal. Missing, corrupt, unsupported or different
identity fails before API readiness or Worker execution; local restore paths need not equal source paths.

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

实际灾难恢复必须先证明备份校验、隔离恢复、迁移账本、命名空间绑定和所有相关终态语义对象均满足当前契约。
任何证明缺失、损坏或不匹配时保持关闭，不得把重算、重置或直接启动当作恢复。单独的 PostgreSQL 备份不是完整恢复集。

PITR/WAL shipping is deployment guidance only and is not part of the P8.5 product authority.

## Failure interpretation

- No fresh Worker and queued Runs: start or diagnose the Worker; do not patch Runs.
- Active lease overdue: allow Scheduler expiry; stale Worker finalization is fenced.
- Running without an active Attempt: the next normal claim performs deterministic re-entry.
- Cancellation recovery pending: the existing reconciler verifies exact Result and Artifact evidence; complete evidence wins, absent evidence cancels, corrupt evidence fails closed.
- PostgreSQL outage during execution: heartbeat failure means ownership is uncertain/lost. The old Worker cannot finalize; after recovery, lease expiry and a fresh Attempt converge forward.
- API restart: Run truth remains in PostgreSQL and execution continues independently.
