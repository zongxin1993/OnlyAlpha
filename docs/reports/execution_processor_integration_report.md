# Execution Processor Integration Report

## 1. 结论摘要

本次将 `OnlyExecutionProcessor` 接入每个 Runtime，并删除 Runtime 上未经过 Inbound Queue 的旧 Order Update
直达入口。所有 `OnlyBrokerInboundUpdate` 现在统一执行：

```text
BrokerGateway → Runtime Inbound Queue → OnlyExecutionProcessor → Managers → Invariant Check → EventBus
```

最终结论：**ACCEPTED**。

## 2. 新增文件

- `src/onlyalpha/execution/`：Processor、immutable model/enums、Invariant Checker、事务事实 Publisher、Runtime-local
  dedup/sequence/audit/reconciliation state；
- `tests/execution/test_execution_processor.py`：7 个组件与直接上下游测试；
- `examples/execution_processor_demo/`：Accepted、Rejected、Partial Fill、部分成交后撤单、重复、乱序、Reconciliation
  与完整链路 Demo；
- `examples/integration_demo/scenarios/scenario_019_broker_rejected.py` 至
  `scenario_023_partial_fill_then_cancel.py`；
- `docs/execution_processor.md`、`docs/execution_processor_component_analysis.md`；
- `docs/adr/0016-execution-processor-ordered-trade-application.md`；
- 本报告。

## 3. 修改文件

修改集中在 Runtime 装配、Broker Update Scope、Order/Position/Allocation/Ledger/Account/Risk Reservation 协调、
Virtual Broker 入站、统一 Integration Environment、场景注册和相关架构文档。历史测试和历史场景均未删除、Skip
或放宽。

## 4. 组件边界与 Runtime 所有权

每个 Runtime 独占以下对象：

- `OnlyExecutionProcessor`；
- `OnlyExecutionEventPublisher`；
- `OnlyExecutionUpdateDeduplicator`；
- `OnlyExecutionSequenceTracker`；
- `OnlyInMemoryExecutionAuditStore`；
- `OnlyInMemoryExecutionReconciliationQueue`。

Processor 不成为业务真值源，不共享 Manager 内部对象；Order、Position、Allocation、Strategy Ledger、Account、Risk
继续各自持有独立状态。双 Runtime 测试验证上述 Processor 状态对象不存在共享。

## 5. Broker Update 统一入口与分派

`OnlyBrokerInboundUpdate` 强制携带 `runtime_id`。Virtual Broker 只向 Runtime Inbound Queue 写标准化回报，不导入或
调用任何 Manager。Runtime 的 `drain_broker_inbound()` 只做 FIFO drain、调用 Processor、保存结果和 drain 事实事件。

分派覆盖：

| Update | 处理结果 |
|---|---|
| Accepted | Order acknowledgement；合法时推进 Reservation acknowledgement |
| Rejected | Order 终态；释放未消费 Reservation；Risk release |
| Cancelled | Order 终态；仅释放剩余 Reservation；Risk release |
| Trade | 固定跨组件 Mutation 链 |
| Position | Broker/Local 字段级 Reconciliation |
| Account | Broker/Local 字段级 Reconciliation |
| Connection | 更新 Runtime-owned connection state |

Runtime 原 `process_order_update()` 直达入口已删除。保留的 `process_trade()` 是 Queue ingress convenience：它只执行
`receive_broker_update()` 后 drain，不直接调用 Manager。

## 6. 固定 Trade 顺序、Mutation Plan 与 Bundle

实际顺序由测试逐步精确断言：

```text
Validation
→ Order
→ Account Position
→ Cluster Allocation
→ Strategy Ledger
→ Account
→ Reservation
→ Risk
→ Invariant Check
→ Event
```

Mutation Plan 在任何写入前完成 Runtime/Gateway/Account/Order Scope、因果时间、sequence、Instrument 与 Trade
身份校验。`OnlyExecutionMutationBundle` 按顺序保存每一步状态，以及 Order、Position、Allocation、Ledger、Account
的正式 Mutation Result 和 Reservation 摘要。

## 7. 各状态域更新结果

- Order：Accepted/Rejected/Cancelled/Partial Fill/Full Fill 使用既有状态机；终态不回退；
- Position：只消费 Order 已确认的 Trade，并生成账户级 realized PnL；
- Allocation：使用当前 Order 自身冻结量作为卖出授权，不会把自己的 Reservation 误判为超卖；
- Strategy Ledger：使用 Allocation 的成本与 realized delta，不自行从 Account 或 Broker 重算；
- Account：使用账户级 Trade cash flow 和 Position realized delta，不使用 Strategy Ledger 虚拟资金；
- Risk：部分成交按实际 quantity/notional 消费 exposure，保留剩余 exposure；Full Fill 关闭 Reservation。

## 8. Reservation 协调与 Risk Post-Trade

Processor 是跨域 Reservation 生命周期协调者。买单按实际成交额与费用消费 Account/Strategy Cash Reservation；卖单按
实际数量消费 Position Reservation；Risk Reservation 保存累计 consumed 与 remaining exposure。Rejected/Cancelled 只释放
剩余部分。场景 014 验证 40/100 成交后 Risk remaining quantity=60、remaining notional=600；场景 023 验证部分成交后
撤单只释放一次。

## 9. 幂等、Sequence、迟到与乱序

- 相同 update ID：返回 `DUPLICATE`，不增加任何 Manager version，不发布事实；
- 不同 update ID、相同 trade ID 或 venue trade ID：仍返回 `DUPLICATE`；
- 迟到 Accepted：返回 `STALE/IGNORED`，FILLED/CANCELLED/REJECTED 不回退；
- 乱序 Trade：在任何 Manager Mutation 前返回 `RECONCILIATION_REQUIRED`；
- Broker/Local Position 或 Account 冲突：显式生成 Reconciliation Request，不静默覆盖本地历史。

Deduplicator 和 Sequence Tracker 均为 Runtime-local、单写入者状态。

## 10. 中途失败与 Reconciliation

组件调用发生中途失败时，Processor 立即停止后续步骤、丢弃本次缓冲的全部成功事实、标记受影响 Scope 为
RECONCILING，并记录 completed/failed step 与恢复要求。EventBus 只收到
`EXECUTION_PROCESSING_FAILED` 和 `EXECUTION_RECONCILIATION_REQUIRED`，不会收到 `ORDER_FILLED`、
`POSITION_OPENED` 或完整成功事件。

第一版采用“阻断 Scope + Broker 查询/补事实/重放”的恢复边界，不伪造反向业务 Mutation。

## 11. Invariant Checker

事实提交前检查：

- Account Position = Cluster Allocation Sum + Unallocated Position；
- Position、Allocation 和 Reservation 非负；
- T+1 unsettled 不增加当日可卖量；
- Strategy Ledger cash view 与 PnL view equity 一致；
- Account equity = cash + position market value；
- Runtime/Account/Cluster/Instrument Scope 一致。

阻断性失败进入 Reconciliation。

## 12. Event、Audit 与 Snapshot Bundle

Manager 仍构造过去式事实，但 `OnlyExecutionEventPublisher` 在完整业务状态和不变量形成前只缓冲事实。EventBus 不订阅
业务 Handler，不承担状态机编排。成功后一次性提交 Manager facts，再发布 Processor completion fact。

每次处理都生成 immutable `OnlyExecutionSnapshotBundle` 与 `OnlyExecutionAuditRecord`。Audit 包含 Scope、Update、处理
sequence、步骤、Mutation 摘要、不变量、事件类型、失败与 Reconciliation ID；序列化往返已测试。

## 13. Integration Environment 与场景

统一 `OnlyIntegrationEnvironment` 的真实正常链为：

```text
Bar → MarketData → Snapshot → Cluster → Order → Risk → ExecutionService
→ VirtualBroker → MatchingEngine → Runtime Queue → ExecutionProcessor
→ Order → Position → Allocation → StrategyLedger → Account → Reservation/Risk
→ Invariant → Event → Final Snapshot/Report
```

保留并通过历史场景 001–018；新增并通过：

- 019 Broker Rejected；
- 020 Execution Audit/Snapshot；
- 021 Out-of-order Trade；
- 022 Mid-pipeline Failure；
- 023 Partial Fill 后 Cancel。

正常场景没有直接调用多个 Manager 模拟成交。场景 022 仅使用明确命名的故障注入测试 Adapter 验证 Ledger 中途失败。

## 14. 测试结果

最终统一命令：`bash scripts/run_component_validation.sh`。

| 验证层 | 结果 |
|---|---:|
| ExecutionProcessor 组件与直接上下游测试 | 7 passed |
| 全部 Unit/Regression/Integration tests | 231 passed，0 failed，0 skipped |
| `tests/integration` | 33 passed，0 failed，0 skipped |
| Integration Demo | 23/23 PASS |
| Execution Processor 专项 Demo | 8/8 入口 PASS |
| Deterministic Replay | baseline + 100 次重放一致 |
| Ruff check | PASS |
| Ruff format check | 361 files formatted |
| Mypy | 171 source files，0 issues |

确定性投影比较 Event 顺序、Order/Position/Allocation/Ledger/Account/Risk Snapshot、Reservation、每次 Processor
Mutation step、Processing Result、Audit、Reconciliation Request 和最终报告状态。

## 15. 关键不变量结果

Runtime/Cluster Scope、Clock/Event 顺序、Order 终态、重复 Fill/Trade 幂等、T+1、Account Position 对账、不同
Cluster Ledger 隔离、Cash/PnL 双视图、部分成交 Reservation、Broker/Local 冲突和相同输入重放全部通过。

## 16. 已知限制

- Audit 与 Reconciliation Queue 当前仅为内存实现；Runtime 重启恢复尚未实现；
- 跨 Manager 不具备数据库事务；部分 Mutation 后失败采用明确阻断和 Reconciliation，而非静默回滚；
- Recovery Orchestrator、持久 checkpoint、自动 Broker re-query/replay 尚未实现；
- Connection Update 只维护 Runtime-owned 状态，尚无完整重连状态机；
- 尚未装配真实 Paper/Live Broker SDK；当前领域范围仍为既有单币种、Long-only、Average Cost 和 T+1 能力。

这些限制均已由正式 Port、状态和审计显式表达；未使用临时代码绕过正式接口。

## 17. 一票否决项审计

| 项目 | 结果 |
|---|---|
| Gateway 直接调用 Manager | 未发现 |
| Broker Update 绕过 Runtime Queue/Processor | 未发现；旧直达入口已删除 |
| EventBus Handler 分散修改业务状态 | 未发现 |
| Reservation 重复消费或释放 | 未发现，部分成交/撤单测试通过 |
| 重复 Trade 修改状态 | 未发生 |
| 迟到 Update 回退状态 | 未发生 |
| 乱序 Update 静默应用 | 未发生，进入 Reconciliation |
| 中途失败发布成功 Event | 未发生 |
| Demo 手工串联 Manager 模拟成交 | 未发现 |
| 删除、Skip、放宽历史场景 | 未发生 |
| Deterministic Replay 不一致 | 未发生 |
| 新增 ARL 或历史兼容旁路 | 未发生 |

## 18. 下一阶段建议

- 是否建议进入 Paper Runtime：**是**。Processor 边界、确定性和故障语义已满足下一阶段装配前提；
- 是否建议进入 Recovery Orchestrator：**是**。这是持久化与自动恢复的明确下一边界；
- 是否建议立即接入首个真实 Broker：**否**。应先完成持久 Audit/Reconciliation、恢复编排、重连状态机和 Paper
  soak test，再引入真实 SDK。

## 19. 最终结论

**ACCEPTED**

本任务要求的组件、正式 Runtime Queue 链路、历史回归、完整 Vertical Slice、100 次确定性重放、文档、Demo、ADR
和报告均已完成，未触发一票否决项。
