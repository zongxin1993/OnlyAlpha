# Execution Processor 组件差距分析

## 1. 当前 Broker Update 处理链

当前实现的实际链路是：

```text
VirtualBrokerGateway
→ OnlyVirtualBrokerUpdateQueue
→ OnlyBacktestRuntime.drain_broker_inbound()
→ Runtime 内按 update 类型分支
→ Accepted/Rejected/Cancelled: OnlyOrderUpdateProcessor
→ Trade: OnlyBacktestRuntime.process_trade()
→ Order → Position → Allocation → StrategyLedger → Account → Reservation → Risk
→ 各 Manager/Processor 在各自步骤立即向 EventBus 入队事实
```

Gateway 没有持有或直接调用 Manager，Virtual Broker 与 Runtime 状态物理隔离，正常集成场景也已通过独立撮合产生回报。
但 Runtime 自身同时承担 Update 去重、分派、Trade 转换、跨 Manager 编排、对账与结果聚合，尚不存在每 Runtime 独立的
`OnlyExecutionProcessor`。`process_order_update()` 和公开 `process_trade()` 仍构成 Broker Queue 之外的业务入口。

当前风险如下：

- update ID 仅由 Runtime `set` 去重，重复项没有结构化 `DUPLICATE` 结果和审计；
- Accepted/Rejected/Cancelled 与 Trade 使用不同路径，sequence 也没有统一跟踪；
- Order Processor 会自行推进/释放 Reservation，而 Trade 编排又由 Runtime 处理 Account/Risk，生命周期协调分散；
- Strategy Ledger 在自身 Trade accounting 内消费 Cash Reservation，不能证明统一固定步骤；
- 各 Manager 在每一步成功后立即把事实放入 EventBus；若后续 Ledger/Account/Reservation 失败，完整成功事实已经入队；
- Position 或 Allocation 已更新而后续失败时，没有结构化 completed steps、Audit 或 Reconciliation Request；
- Broker Account/Position 对账结果没有统一 Processing Result；
- `process_trade(fill_update, position_trade)` 允许调用方绕过 Broker Update 和 Runtime Queue；
- 没有统一 Snapshot Bundle，也没有每条 Update 的一致 logical processing sequence。

## 2. 当前 Manager API

| 状态域 | 正式输入 | 结果/快照 | 幂等与顺序 | 错误语义 | Event |
|---|---|---|---|---|---|
| Order | 标准 Gateway Accepted/Rejected/Cancelled/Fill | `OnlyOrderMutationResult` + immutable Order Snapshot | event/trade ID、external sequence；终态不回退 | INVALID/DUPLICATE/STALE/CONFLICT 或异常 | Mutation 成功后生成 Order facts |
| Position | `OnlyPositionTrade` | `OnlyPositionMutationResult` + immutable Position Snapshot | execution/venue trade/trade ID；stable order | DUPLICATE/STALE 或超卖异常 | Manager 成功保存后发布 |
| Allocation | `OnlyPositionTrade` | `OnlyPositionMutationStatus` + immutable Allocation Snapshot | 同 Trade fingerprint/stable order | DUPLICATE/STALE 或归因/超卖异常 | 当前不直接发布公共 Event |
| Strategy Ledger | `OnlyStrategyTradeAccountingInput` | `OnlyStrategyLedgerMutationResult` + immutable Ledger Snapshot | Trade/Fee/valuation/reservation 独立幂等 | DUPLICATE/STALE 或币种/现金/双视图异常 | Manager 成功保存后发布 |
| Account | `OnlyAccountTradeCashFlow`、valuation、reconciliation | `OnlyAccountMutationResult` + immutable Account Snapshot | trade ID、external sequence、valuation version | unchanged、RECONCILING 或资金异常 | Manager 成功保存后发布 |
| Risk | reserve/release/consume 与只读 post-state | immutable Risk Snapshot/Reservation Result | Order ID 幂等 | NOT_FOUND/INVALID 或 Fail Closed | 状态/Reservation 变化后发布 |
| Position Reservation | stage/consume/release | immutable Reservation Result | Order ID 和剩余量幂等 | 非法 stage/Scope 异常 | 不驱动状态机 |
| Strategy Cash Reservation | consume/release | immutable Reservation/Ledger Snapshot | Order ID、剩余金额 | 现金不足或 Scope 异常 | Ledger facts |
| Account Reservation | AccountManager consume/release + 独立索引 Manager | immutable Account Mutation/Reservation | Reservation ID、剩余金额 | 现金不足或 Scope 异常 | Account facts |

所有公开 Snapshot 已为 frozen Domain DTO；Manager 持有的实体或内部映射没有进入 Cluster Context。

## 3. 必须修复的不一致风险

本组件需要在不改变既有领域账务语义的前提下消除以下风险：

1. Order 已 Fill，而 Position、Allocation、Ledger 或 Account 因中途失败未完成；
2. Reservation 由 Order Processor、Ledger 和 Runtime 多处协调，可能提前消费或重复释放；
3. 重复 Broker Update 被静默跳过，无法形成可审计结果；
4. 迟到 Accepted 与乱序 Trade 没有统一、类型敏感的处理策略；
5. Broker Position/Account Snapshot 可能绕开统一审计和 Reconciliation Queue；
6. Event 在完整跨组件状态形成前入队；
7. 失败后缺少明确的受阻 Scope、已完成 Mutation Step 和恢复请求；
8. Runtime `process_trade()` 公开旁路使测试或 Demo 可以手工依次驱动业务状态。

目标实现必须把 Queue 后的所有 Update 交给一个 Runtime-owned Processor，先完成 scope/计划/幂等/sequence 预检，再按固定顺序
提交；成功后一次性发布缓冲事实，失败时丢弃成功事实并只发布失败/对账事实。第一版没有数据库事务，因此已提交 Manager
Mutation 不做无审计反向补偿，而是立即阻断并进入确定性 Reconciliation。
