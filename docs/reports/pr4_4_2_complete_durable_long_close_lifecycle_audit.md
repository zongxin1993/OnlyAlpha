# PR4.4.2 Complete Durable Long Close Lifecycle 预实施审计

- 审计日期：2026-07-30
- 分支：`master`
- 实际起始提交：`950757066a0b87ae421312e844af493bb7e02e10`
- 当前版本：`0.3.1`
- Prompt 预期差异：无。PR4.4.1 已合入，当前正式路径已经具备 Whole Fill Long Close Durable Transaction，
  但尚未完成多 Fill Close、持久化终态事务与统一能力判定。
- 工作树基线：仅有用户提供的未跟踪 `prompts/CompleteDurableLongCloseLifecycle.md`；实施保留且不修改该文件。

## Close 成本与多 Fill 基线

1. `PARTIAL_CLOSE_NOT_READY` 有两个实际触发点，均位于 `OnlyGenericT0CashTradePlanner._validate()`：
   Order 已有成交，以及本次成交量不等于 Order 剩余量。错误码枚举本身不是触发点。
2. Position 与 Allocation Close Reducer 当前均以 `average_open_price * fill_quantity` 释放开仓成本。
3. Whole Fill 会把累计开仓价数量归零；Partial Fill 没有按累计成本权威比例释放，因而不能保证最后一笔释放全部余量。
4. 当前平均开仓价通过 Decimal `quantize()` 且显式 `ROUND_HALF_EVEN`，精度取价格增量与原平均价精度上界。
5. `cumulative_open_price_quantity` 已作为精确 Decimal 状态进入 Position、Allocation、Projection 与持久化 Codec。
6. 若每笔 Close 都用平均价乘数量独立释放，有限精度平均价会在多 Fill 累计中留下漂移；最终 Fill 必须释放全部剩余累计成本。
7. Position Reservation 已有 `ACTIVE / PARTIALLY_CONSUMED / CONSUMED / RELEASED` 状态，但没有显式累计 consumed/released 数量；本次将补齐该状态，避免终态释放后丢失已成交事实。
8. Risk Reservation 已有累计 consumed quantity/notional，但 `remaining_*` 未扣除终态释放量；本次将补齐 released quantity/notional，并冻结
   `reserved = consumed + released + remaining`。
9. Order、Position Reservation、Risk Reservation、Risk、Fee Accrual、Account 与 Ledger 的现有 Trade Reducer 已具备逐 Fill 增量结构；阻塞来自 Close 校验和成本释放算法。
10. Order Reducer 已能在非末笔进入 `PARTIALLY_FILLED`，末笔进入 `FILLED`，并保持累计成交、剩余量、Fill Count 与版本单调。
11. Fee Reducer 已支持 `FILL` 与 `ORDER_CUMULATIVE` 两种 Broker reporting mode；多 Fill 的本地 Fee Delta 由累计权威差值产生。
12. Account、Ledger、Reservation 与 Risk Reducer 都按本次 Fill Delta 归约，不需要第二套 Close Manager 或账务真值。

## Virtual Broker 与终态基线

13. Virtual Broker Fill Plan 与每 Bar 调度已经支持同 Bar/跨 Bar 多次计划成交，并不按 BUY/SELL 分叉计划语义。
14. SELL/CLOSE 仅在价格可成交判断与账户/持仓 Broker Projection 中体现方向；无需修改 Fill Identity、Fill Index 或计划序列。
15. `OnlyExecutionProcessor._terminal_order()` 当前直接变更 Order，并释放 Position、Account、Margin、Strategy Ledger 与 Risk Reservation，随后刷新 Risk；这些操作不属于 Durable Transaction。
16. 终态发生在 `PARTIALLY_FILLED` 或 `PENDING_CANCEL` 后时，Order 的既有累计成交必须保留，只释放剩余 Reservation。
17. 直接终态路径可能在多个 Manager 已变更后失败，只能创建 Reconciliation，无法提供与每 Fill 相同的 execute/publish/commit 原子边界。
18. SQLite `execution_transactions.trade_id` 当前为 `TEXT NOT NULL`，且内存存储也以 Trade ID/Fill Identity 假设所有事务都是 Trade Fill。
19. Transaction Codec 当前只编码/解码 `OnlyCommittedExecutionFactDraft` 与 Trade Projection 集合，没有 Operation Kind 或 Terminal Fact 判别。
20. Backtest Result Collector 当前把每个 ready transaction 的 Fact 都当作 Trade；引入终态事务后必须显式筛选 `TRADE_FILL`。
21. Outbox、Projection Applied Ledger、Projection Ready Query、Checkpoint Tail 与 Commit Coordinator 的主协议以 Transaction/Execution Sequence 为中心，能够复用，不需要新建终态 Store、Coordinator 或 Recovery Phase。
22. 现有 ORDER Projection 绑定 Trade Fill 字段；终态需要独立的强类型 Order Terminal Projection，同时复用
   POSITION_RESERVATION、RISK_RESERVATION 与 RISK Projection/Target。

## 正式路由、能力与持久化基线

23. Formal Long Close Trade 当前经 `_uses_prepared_trade_path()` 进入 Planner，但 Partial Fill 在 Planner 内被拒绝；其他 Close 组合仍可能落入 `_unmigrated_trade()`。本次将用单一能力矩阵硬门禁，Formal 路径不得再触达 legacy trade 或 direct terminal。
24. Capability 判定目前重复散落在 Processor 路由、Runtime Context Builder 的假设与 Planner `_validate()` 中；本次新增一个纯、可测试的 Capability Matrix，三处共同调用。
25. 终态不得伪造 Trade ID，而既有 SQLite schema 强制非空 Trade ID，因此 Runtime Persistence Schema 必须由 2 升至 3。
26. 本任务不迁移、不删除旧库。Schema 2 数据库必须在启动时确定性 fail fast，并给出 expected/actual 版本诊断。
27. 预计修改：Execution operation/capability/terminal identity/models/planner/codec/store/processor/recovery/projections/targets，Runtime context/wiring/result collector，Position/Risk Reservation 状态，Broker Expired update，测试、ADR 与当前文档。
28. 明确冻结：`commit_coordinator.py`、`fill_identity.py`、既有 Trade Transaction ID 算法、Fill Index 语义、Event Gate/Router、Recovery Phase、Recovery Finalizer/Outcome 与 Virtual Broker checkpoint schema。
29. 当前文档把 Durable Close 限定为 Whole Fill，并把 Cancel/Reject 终态留在 direct mutation；README、execution、prepared transaction、backtest、recovery、testing、roadmap 与 result contract 都需要同步修正。
30. 实施只建立一套共享结构：一个累计成本释放 Reducer、一个判别式 Operation Kind、一个 Store/Coordinator/Projection/Recovery 主链、一个 Capability Matrix。不会引入 Close 专用 Manager、Store、Committer、Recovery Phase 或第二套结果模型。

## 冻结后的目标契约

正式范围是 `GENERIC_T0_CASH + CASH + LIMIT SELL CLOSE + LONG + NETTING`。每个 Fill 和每个
`CANCELLED / REJECTED / EXPIRED` 终态操作都必须经过：

```text
Broker Update
→ Capability Matrix
→ Pure Planning Context
→ Prepared Execution Transaction
→ Shared Durable Store / Coordinator
→ Fixed Projection Order
→ Event Gate / Outbox
→ Commit / Projection Ready
→ Checkpoint / A→B→C Recovery
```

Close Trade Projection 顺序保持：

```text
ORDER → POSITION → ALLOCATION → SETTLEMENT → ORDER_FEE_ACCRUAL → FEE
→ ACCOUNT → STRATEGY_LEDGER → POSITION_RESERVATION
→ RISK_RESERVATION → RISK → VALUATION
```

Terminal Projection 顺序冻结为：

```text
ORDER → POSITION_RESERVATION → RISK_RESERVATION → RISK
```

同一 `ETERM-...` 与同一 Payload 必须幂等返回 Duplicate；同一 Terminal Identity 与不同 Payload 必须以
`TERMINAL_IDENTITY_CONFLICT` fail closed。终态 Fact 不伪造 Trade，不进入 Backtest Trade 列表。
