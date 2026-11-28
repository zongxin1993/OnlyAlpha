# Research Service Operations

原 API 与 Worker 已退役。以下是产品宿主恢复时须满足的运行、排空与恢复约束。数据库拓扑见[部署说明](../deployment.md)。PostgreSQL 服务器时间用于判断 lease；进程在线状态仅供诊断。验证角色、schema 与命名空间前禁止受理或认领任务。

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

进程退出或系统信号本身不构成语义取消或失败。


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

产品迁移工具已随 Backend 退役。迁移必须显式执行，以 advisory lock 和事务核验迁移历史。缺少经过验证的成对备份和恢复路径时，不得对正式数据执行迁移或恢复。

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
