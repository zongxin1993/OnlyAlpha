# Execution Runtime Recovery

OnlyAlpha 将 durable transaction truth、Runtime Manager authority、Applied Projection Ledger 与 Outbox delivery 明确分层：

```text
Transaction Store (durable Trade authority)
→ ordered real Manager Projection
→ Projection Ready business visibility
→ durable at-least-once Outbox delivery
```

## 生命周期

Backtest Runtime 的启动顺序固定为：

```text
CREATED
→ plugin resource initialize/connect
→ Cluster initialize
→ Execution Recovery
→ READY
→ plugin resource start
→ recovered Outbox delivery
→ Cluster start
→ RUNNING
→ RUNTIME_STARTED
```

Recovery 发生在正确 Bootstrap/Before Authority 已建立之后、任何新行情、Broker update 或策略回调之前。失败时 Runtime 进入
`FAILED`，保留 `OnlyExecutionRecoveryResult`，不进入 `READY/RUNNING`，也不发布 `RUNTIME_STARTED`。

## 恢复顺序与状态

`OnlyExecutionRecoveryService` 查询最早的未 Ready transaction，按 `execution_sequence` 升序调用正式 Coordinator。前序未 Ready
产生 `SEQUENCE_BLOCKED`；Projection failure、Store failure 分别映射为稳定状态，并立即停止后续 transaction。`NO_WORK` 与
`RECOVERED` 是仅有的成功状态。

每个真实 Target 的恢复状态为：matching Applied Ledger record 返回 `IDEMPOTENT`；Manager 已是 Result authority 而 ledger 缺失时
验证/修复 replay index 并返回 `RECOVERED`；Current 等于 Expected 时安装 Result 并返回 `APPLIED`。Payload、version 或 state conflict
在 mutation 前失败，不覆盖 Manager。

Recovery 不运行 Planner，不调用 Broker、Market Rule 或 Fee Resolver，不生成新 Event，不删除失败 transaction，不跨 Manager
回滚，也不跳过 sequence。

## 查询与诊断

- `OnlyExecutionTransactionQueryPort.records()`：Admin/Recovery/Diagnostic，可读取全部 committed transaction。
- `OnlyProjectionReadyExecutionQueryPort.ready_records()`：正式业务查询，只返回 Ready transaction。
- `OnlyExecutionProjectionStatePort.unprojected()`：恢复工作集。
- `OnlyExecutionTransactionOutboxPort.pending()`：只返回 Ready 且未发布的 Event。

Runtime status 的 execution recovery diagnostic 包含尝试/完成/恢复/幂等 transaction 数、失败 sequence/transaction/component、
Coordinator status、projection error 与 Store error。Backtest Result、Artifact 和 Report 通过标准 diagnostics projection 读取这些信息，
不暴露内部 Store。

## Outbox 故障

Outbox failure 不改变 Projection Ready，也不回滚 Manager。EventBus 已接受但 `mark_published` 失败时，下一次会再次投递同一个稳定
Event ID；因此语义是 at-least-once，消费者必须幂等。Backtest 启动阶段若 recovered Outbox 未完全交付，Runtime 严格失败并阻止
Cluster start，但该错误与 Projection Recovery failure 使用不同异常和 diagnostic。

## 当前限制

当前只支持 Generic T0 Cash、LIMIT、BUY、OPEN、整单成交的 committed Trade tail，并依赖调用方重建正确 Bootstrap Authority。尚未
实现 Full Bootstrap Snapshot、Empty Runtime Recovery、Partial/Multi Fill、SELL/CLOSE、Futures/Margin、Non-Trade Transaction、
Paper/Live Recovery 或 exactly-once delivery。
