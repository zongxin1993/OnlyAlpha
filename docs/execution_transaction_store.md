# Execution Transaction Store

新 Store 的唯一写入口是：

```text
commit(prepared, committed_at)
```

Memory 与 SQLite 在 commit 锁/数据库事务内分配 Runtime-local 连续 sequence，finalize Fact Draft，并原子保存 Prepared payload、Committed Transaction、ordered Projection 和 Outbox。调用方不能预取 sequence。

Transaction ID、Runtime/Gateway/Account/Trade 和 Runtime/Gateway/Account/Update 是幂等键。同键同 prepared hash 返回原事务且 `inserted=False`；同键不同 hash 抛出 hard conflict。

Outbox 可交付查询只返回 `projection_ready=true` 且 `published=false` 的记录。正确生命周期为 durable commit、apply projections、mark ready、outbox delivery。失败或进程停止时 committed transaction 保留，未 Ready Event 不可见；已发布记录继续保留审计字段。

`OnlyInMemoryExecutionTransactionStore` 与 `OnlySqliteExecutionTransactionStore` 实现同一 Commit、Query、Projection State 和 Transaction Outbox 契约。SQLite 校验 prepared/committed hash、canonical round-trip、Event ID，并支持显式 `close()` 和重启恢复。

当前 Runtime 主链仍使用明确命名的 legacy committed execution journal。它与新接口不互相继承，新代码不调用 legacy `next_sequence()`；主链切换属于下一阶段。
