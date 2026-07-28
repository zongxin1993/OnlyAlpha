# ADR 0043: Execution Store Factory and Runtime State Directory

- Status: Accepted
- Date: 2026-07-28

## Context

ADR 0042 已定义 Runtime initialize transaction-tail recovery，但正式 `OnlyEngine` →
`OnlyBacktestRuntimeFactory` 链没有从产品配置创建持久 Store。Runtime 隐式创建 Memory Store，SQLite 也没有 schema/identity
metadata 或明确 close 所有者。一次性 Run Artifact 目录包含随机 Run ID，不能作为 restart state identity。

## Decision

`runtime.execution_store` 是正式强类型配置，支持 `MEMORY`（默认、不可跨进程恢复）和显式 `SQLITE`。SQLite 默认路径为：

```text
user_data/state/engines/<engine-id>/runtimes/<runtime-id>/execution.sqlite3
```

显式 path 必须是相对 Runtime state root 的非空路径，禁止绝对路径和 `..` 逃逸。State Directory 与
`user_data/runs/<engine-id>/<run-id>` Artifact Directory 分离；state identity 不使用时间、UUID、Run ID 或 Cluster ID。

`OnlyDefaultExecutionTransactionStoreFactory` 是唯一产品 Store 创建位置。`OnlyBacktestRuntimeFactory.validate()` 只验证配置，
不创建目录、数据库或 metadata；`create()` 创建 Store 并显式注入 Runtime。Runtime 不解析 Store 配置，也不创建第二 Store。
Coordinator、Recovery、Admin/Ready Query、Projection State 与 Outbox 共用同一实例。

SQLite schema version 当前为 `1`。metadata 至少包含 schema version、created_at、engine/runtime identity、runtime mode、完整产品
config fingerprint、base currency、account identity 与 market profile identity。未知 schema、缺表/缺 metadata、identity mismatch 或
corrupt SQLite 一律 fail fast，不删除、不覆盖、不迁移、不降级 Memory。

Store 是 Runtime-owned resource。Factory 在 Runtime 接管前失败时关闭 Store；接管后 Runtime close 在 Outbox drain、plugin cleanup 和
EventBus close 之后、Clock close 之前关闭 Store。close 幂等，首个错误保留且其他资源继续清理。

Runtime Factory 在发现一个 sequence-one、committed-but-unprojected Generic T0 transaction 时，通过正式
`bootstrap_execution_transaction_before()` 边界恢复 transaction contract 明确携带的 Before authority，再由 `initialize()` 自动执行
ordered forward recovery。该边界只支持一笔 sequence-one tail；它不是任意 Manager snapshot，也不处理已投影历史 tail。

Engine restart 故障点选择 durable commit 后、首个 Projection 前，避免依赖 Engine A 已安装但未持久化的 Manager After state。
Applied Projection Ledger 仍是 in-memory rebuildable index。Recovered Outbox 在 Cluster start 前发布，Event ID 稳定，交付语义仍为
at-least-once，不是 exactly-once。

## Consequences and limits

相同产品配置、相同 user_data 和相同 engine/runtime identity 会定位并验证同一个 Store；不兼容配置会明确失败。SQLite 的配置会参与
Runtime compatibility 与 config fingerprint。

本 ADR 不实现 Full Bootstrap Snapshot、Empty Runtime Recovery、Partial/Multi Fill、SELL/CLOSE、Futures/Margin、Non-Trade
Transaction、Paper/Live Recovery 或 exactly-once delivery。Transaction-before bootstrap 对更早的完整 Account/Strategy equity timeline
恢复 transaction contract 中携带的精确历史点，并恢复当前 Before economic authority；这仍不是可覆盖任意历史 tail 的 Full Bootstrap
Snapshot。
