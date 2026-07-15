# OnlyAlpha `OnlyExecutionProcessor` 统一执行回报处理组件实现任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的：

```text
OnlyExecutionProcessor
```

该组件是 Runtime 内所有标准化券商回报的唯一业务处理入口。

当前系统已经存在或已经设计完成：

```text
OnlyRuntime
OnlyClock
OnlyEventBus
OnlyRuntimeContext
OnlyCluster

OnlyMarketDataPipeline
OnlyMarketDataSnapshot

OnlyOrderManager
OnlyOrderService

OnlyRiskService
OnlyRiskReservationManager

OnlyPositionManager
OnlyPositionAllocationManager
OnlyPositionReservationManager

OnlyStrategyLedgerManager
OnlyStrategyCashReservationManager

OnlyAccountManager
OnlyAccountReservationManager

OnlyExecutionService

OnlyBrokerGateway
OnlyVirtualBrokerGateway
OnlyMatchingEngine
OnlyBrokerInboundUpdate
OnlyRuntimeInboundQueue
```

目前需要建立一个明确、稳定、确定性的统一处理链：

```text
OnlyBrokerInboundUpdate
    ↓
OnlyRuntimeInboundQueue
    ↓
OnlyExecutionProcessor
    ↓
按固定顺序更新所有相关 Manager
    ↓
检查跨组件不变量
    ↓
发布事实 Event
    ↓
生成最终一致性 Snapshot
```

本任务的核心目标是解决：

* Broker 回报由谁处理；
* Manager 更新顺序如何固定；
* 部分成交如何更新；
* Reservation 如何消费和释放；
* 重复回报如何幂等；
* 迟到回报如何避免状态回退；
* 乱序回报如何进入 Reconciliation；
* 中途更新失败如何处理；
* Event 何时发布；
* 回测、Virtual Broker、Paper 和 Live 如何复用同一执行链。

---

# 2. 项目身份与执行来源

OnlyAlpha 是一个完全独立、从零设计的量化交易系统。

本任务只依据：

```text
AGENTS.md
docs/
docs/adr/
当前 OnlyAlpha 代码
当前已批准组件设计
```

禁止：

* 参考其他本地工程；
* 保留历史兼容逻辑；
* 模仿未记录的旧行为；
* 为迁移目的增加 Wrapper；
* 修改架构以适配外部旧接口。

---

# 3. 核心架构原则

必须遵守：

```text
BrokerGateway 只负责外部接口和数据标准化

BrokerGateway 不直接修改任何 Manager

所有 Broker Update 进入 Runtime Inbound Queue

OnlyExecutionProcessor 是 Broker Update 的统一业务处理入口

Manager 状态修改使用显式函数调用

Event 只在状态成功更新后发布

EventBus 不承担成交工作流

所有执行顺序由 Processor 明确控制

每个 Runtime 拥有独立 ExecutionProcessor

不同 Runtime 不共享任何执行状态

所有时间来自 Runtime Clock

所有 Update 必须幂等

所有跨组件状态必须保持一致

无法安全完成处理时进入 Reconciliation

回测、Virtual Broker、Paper 和 Live 使用相同 Processor API
```

---

# 4. 组件定位

`OnlyExecutionProcessor` 是：

> Runtime 内对标准化 Broker Update 执行业务处理、状态编排、不变量检查和事实事件生成的应用层 Orchestrator。

它不拥有 Order、Position、Ledger 或 Account 的业务真值。

业务真值分别属于：

```text
OnlyOrderManager
OnlyPositionManager
OnlyPositionAllocationManager
OnlyStrategyLedgerManager
OnlyAccountManager
OnlyRiskService
各 Reservation Manager
```

`OnlyExecutionProcessor` 只负责：

* 验证；
* 解析；
* 排序；
* 编排；
* 调用；
* 汇总 Mutation Result；
* 检查不变量；
* 发布最终事实；
* 产生审计结果；
* 触发 Reconciliation。

---

# 5. 每个 Runtime 一个 Processor

必须采用：

```text
OnlyEngine
├── OnlyBacktestRuntime
│   └── OnlyExecutionProcessor
├── OnlyPaperRuntime
│   └── OnlyExecutionProcessor
├── OnlyLiveRuntime
│   └── OnlyExecutionProcessor
└── OnlyResearchRuntime
    └── 可选 OnlyExecutionProcessor
```

不同 Runtime：

* 不共享 Update 去重状态；
* 不共享 sequence；
* 不共享 audit；
* 不共享 pending transaction；
* 不共享 Manager；
* 不共享 Reservation。

Processor 必须绑定：

```text
runtime_id
clock
manager views/services
invariant checker
event publisher
reconciliation port
```

---

# 6. 本阶段实现范围

本阶段需要实现或完善：

```text
OnlyExecutionProcessor
OnlyExecutionProcessorConfig
OnlyExecutionProcessingContext

OnlyExecutionProcessingResult
OnlyExecutionProcessingStatus
OnlyExecutionFailure
OnlyExecutionFailureCode

OnlyExecutionMutationBundle
OnlyExecutionMutationStep
OnlyExecutionMutationStatus

OnlyExecutionAuditRecord
OnlyExecutionAuditStore
OnlyInMemoryExecutionAuditStore

OnlyExecutionUpdateDeduplicator
OnlyExecutionSequenceTracker

OnlyExecutionInvariantChecker
OnlyExecutionInvariantResult
OnlyExecutionInvariantViolation

OnlyExecutionReconciliationPort
OnlyExecutionReconciliationRequest

OnlyOrderAcceptedUpdateProcessor
OnlyOrderRejectedUpdateProcessor
OnlyOrderCancelledUpdateProcessor
OnlyTradeUpdateProcessor
OnlyAccountUpdateProcessor
OnlyPositionUpdateProcessor
OnlyConnectionUpdateProcessor

OnlyExecutionEventPublisher
OnlyExecutionProcessingEvent

OnlyExecutionSnapshotBundle
```

如果当前代码规模较小，可以将各子 Processor 作为内部私有类，但统一入口必须是：

```python
processor.process(update)
```

---

# 7. 本阶段不实现

本任务不要实现：

```text
真实 Broker SDK
新的 Broker Gateway
新的 Matching Engine
完整数据库事务
分布式事务
跨 Runtime 事务
自动历史全量重算
复杂期货结算
期权行权
公司行动
融资融券
保证金强平
多币种清算
跨账户成交
生产级消息队列
Web
ARL
```

但接口必须允许未来扩展。

---

# 8. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md

docs/architecture.md
docs/architecture_principles.md
docs/integration_vertical_slice.md

docs/domain_model.md
docs/time_model.md
docs/clock.md
docs/event.md

docs/runtime.md
docs/runtime_context.md
docs/cluster.md

docs/order.md
docs/risk.md
docs/position.md
docs/strategy_ledger.md
docs/account.md
docs/broker_gateway.md
docs/virtual_broker.md

docs/testing.md
docs/coding_style.md
docs/adr/
```

重点检查当前已有：

```text
OnlyBrokerInboundUpdate
OnlyBrokerOrderAcceptedUpdate
OnlyBrokerOrderRejectedUpdate
OnlyBrokerOrderCancelledUpdate
OnlyBrokerTradeUpdate
OnlyBrokerAccountUpdate
OnlyBrokerPositionUpdate
OnlyBrokerConnectionUpdate

OnlyOrderManager
OnlyPositionManager
OnlyPositionAllocationManager
OnlyStrategyLedgerManager
OnlyAccountManager
OnlyRiskService

OnlyRiskReservationManager
OnlyPositionReservationManager
OnlyStrategyCashReservationManager
OnlyAccountReservationManager

OnlyRuntimeInboundQueue
OnlyExecutionService
OnlyEventPublisher
```

禁止重复定义已经存在且语义一致的类型。

---

# 9. 先创建差距分析

创建：

```text
docs/execution_processor_component_analysis.md
```

至少包含：

## 9.1 当前 Broker Update 处理链

画出当前实现：

```text
Broker Update
→ ?
→ Order
→ Position
→ Allocation
→ Ledger
→ Account
→ Risk
```

检查：

* Gateway 是否直接调用 Manager；
* Event Handler 是否直接修改状态；
* 不同 Update 是否由不同路径处理；
* Virtual Broker 与测试是否绕过正式入口；
* 回测与 Live 是否使用不同处理链；
* Reservation 是否由多个组件各自释放；
* Fee 是否重复计算；
* Trade 是否重复应用；
* Event 是否过早发布；
* 失败后是否继续更新其他组件；
* 是否缺少跨组件不变量检查。

## 9.2 当前 Manager API

列出每个 Manager 的：

```text
输入
输出
Mutation Result
幂等语义
错误语义
状态版本
Event
```

## 9.3 当前不一致风险

至少分析：

```text
Order 已 Fill，但 Position 未更新
Position 已更新，但 Allocation 未更新
Allocation 已更新，但 Ledger 未更新
Ledger 已更新，但 Account 未更新
Reservation 重复释放
费用重复记账
重复 Broker Trade 重复处理
迟到 Accepted 导致 Order 状态回退
Broker Position Snapshot 覆盖本地状态
Event 在完整状态未形成前发布
```

完成分析后再修改代码。

---

# 10. 统一 Processor 接口

建议：

```python
class OnlyExecutionProcessor:
    def process(
        self,
        update: OnlyBrokerInboundUpdate,
    ) -> OnlyExecutionProcessingResult:
        ...
```

也可以支持批量：

```python
def process_many(
    self,
    updates: tuple[OnlyBrokerInboundUpdate, ...],
) -> tuple[OnlyExecutionProcessingResult, ...]:
    ...
```

但第一版必须保证逐条顺序确定。

不得提供：

```text
process_order_directly
process_position_directly
process_trade_without_update
```

等绕过标准 Update 的公共入口。

测试 Harness 可以构造标准化 Update，但必须调用统一 `process()`。

---

# 11. Processing Status

定义：

```text
OnlyExecutionProcessingStatus
├── APPLIED
├── DUPLICATE
├── STALE
├── IGNORED
├── REJECTED
├── RECONCILIATION_REQUIRED
└── FAILED
```

语义：

```text
APPLIED
    Update 已完整应用

DUPLICATE
    Update 已处理过，没有任何状态变化

STALE
    Update 顺序过旧，未应用

IGNORED
    Update 合法，但根据当前状态无需处理

REJECTED
    Update 不符合 Scope 或业务条件

RECONCILIATION_REQUIRED
    不能安全应用，需要对账或人工修复

FAILED
    Processor 或依赖组件发生系统错误
```

禁止只返回 `bool`。

---

# 12. Processing Result

定义：

```text
OnlyExecutionProcessingResult
```

至少包含：

```text
runtime_id
update_id
update_type
status

order_snapshot
position_snapshot
allocation_snapshot
ledger_snapshot
account_snapshot
risk_snapshot

reservation_results
mutation_bundle
generated_events
audit_record

failure
reconciliation_request

ts_started
ts_completed
sequence
quality_flags
```

未更新的 Snapshot 可以为空，但必须保持类型明确。

---

# 13. Update 分派

Processor 必须根据 Update 类型显式分派：

```text
OnlyBrokerOrderAcceptedUpdate
    → OrderAccepted Processor

OnlyBrokerOrderRejectedUpdate
    → OrderRejected Processor

OnlyBrokerOrderCancelledUpdate
    → OrderCancelled Processor

OnlyBrokerTradeUpdate
    → Trade Processor

OnlyBrokerAccountUpdate
    → Account Update Processor

OnlyBrokerPositionUpdate
    → Position Update / Reconciliation Processor

OnlyBrokerConnectionUpdate
    → Connection Processor
```

禁止依赖 EventBus 订阅者分散处理。

未知 Update：

```text
→ REJECTED / UNSUPPORTED_UPDATE_TYPE
```

---

# 14. 通用处理前置校验

每个 Update 处理前必须验证：

```text
runtime_id
gateway_id
account_id
update_id
source_sequence
ts_event
ts_init
update type
required identifiers
currency
quantity
price
scope
```

至少检查：

* Update 属于当前 Runtime；
* Gateway 已注册；
* Account 已注册；
* Order/Trade 引用存在；
* Cluster Scope 可恢复；
* ID 类型正确；
* 时间为 UTC；
* 金融值不使用非法 float；
* sequence 合法；
* Update 不重复；
* Update 不明显过期。

Scope 校验失败不得修改任何 Manager。

---

# 15. Update 去重

定义：

```text
OnlyExecutionUpdateDeduplicator
```

去重依据优先：

```text
update_id
gateway_id + source_sequence
trade_id / venue_trade_id
```

必须明确区分：

```text
重复 Broker Update
重复 Trade
重复 Fill
重复 Fee
```

同一个 Update 重复处理：

* Manager 状态不变化；
* Reservation 不变化；
* Version 不增加；
* 不重新发布业务 Event；
* 返回 `DUPLICATE`。

---

# 16. Sequence 与迟到回报

定义：

```text
OnlyExecutionSequenceTracker
```

至少按：

```text
runtime_id
gateway_id
account_id
instrument_id
order_id
```

中适当 Scope 维护 sequence。

排序优先：

```text
source_sequence
→ ts_event
→ stable update_id
```

如果 Update 迟到但仍可安全幂等应用，可以返回：

```text
IGNORED
```

如果迟到会改变历史成本、PnL 或状态：

```text
RECONCILIATION_REQUIRED
```

第一版不要自动重放全部历史。

---

# 17. Order Accepted 处理

推荐流程：

```text
OnlyBrokerOrderAcceptedUpdate
    ↓
1. Scope 校验
2. 去重和 sequence 检查
3. 查找 OnlyOrder
4. 验证 VenueOrderId 绑定
5. OrderManager.apply_accepted()
6. 更新 Reservation Stage
7. 生成 Order Snapshot
8. 检查订单状态不变量
9. 发布 OnlyOrderAcceptedEvent
```

必须保证：

* 迟到 Accepted 不让 FILLED/CANCELLED/REJECTED 状态回退；
* VenueOrderId 重复绑定冲突进入 Reconciliation；
* Broker Accepted 不重新创建 Order；
* Accepted 不表示成交。

---

# 18. Order Rejected 处理

推荐流程：

```text
OnlyBrokerOrderRejectedUpdate
    ↓
1. 校验和去重
2. OrderManager.apply_rejected()
3. 释放 Risk Reservation
4. 释放 Strategy Cash Reservation
5. 释放 Position Reservation
6. 释放 Account Reservation
7. 更新 Risk State
8. 检查不变量
9. 发布事实 Event
```

必须：

* 只释放当前 Order 未消费的 Reservation；
* 重复 Rejected 不重复释放；
* 已完全成交订单收到迟到 Rejected 时不得回退；
* 冲突进入 Reconciliation。

---

# 19. Order Cancelled 处理

推荐流程：

```text
OnlyBrokerOrderCancelledUpdate
    ↓
1. 校验和去重
2. OrderManager.apply_cancelled()
3. 计算剩余未成交数量
4. 释放剩余 Risk Reservation
5. 释放剩余 Cash Reservation
6. 释放剩余 Position Reservation
7. 释放 Account Reservation
8. 更新 Risk State
9. 发布事实 Event
```

部分成交后撤单：

* 已成交部分保持；
* 只释放剩余部分；
* Order 终态为 `CANCELLED`；
* Position、Allocation、Ledger、Account 不回滚已成交部分。

---

# 20. Trade Update 统一处理顺序

`OnlyBrokerTradeUpdate` 必须采用固定顺序。

推荐：

```text
OnlyBrokerTradeUpdate
    ↓
1. 前置验证
2. Update 去重
3. Trade 去重
4. Sequence 检查
5. 读取 Order 当前 Snapshot
6. 预计算 Mutation Plan
7. OrderManager.apply_fill()
8. PositionManager.apply_trade()
9. PositionAllocationManager.apply_trade()
10. StrategyLedgerManager.apply_trade_accounting()
11. AccountManager.apply_trade_accounting()
12. 消费或调整各 Reservation
13. RiskService.update_post_trade_state()
14. 检查跨组件不变量
15. 生成一致性 Snapshot Bundle
16. 记录 Audit
17. 发布事实 Event
```

禁止改变上述核心顺序，除非 ADR 明确说明。

---

# 21. 为什么 Order 必须先更新

Trade 必须先通过：

```text
OrderManager.apply_fill()
```

原因：

* 验证该 Fill 是否属于 Order；
* 验证剩余数量；
* 检测重复 Fill；
* 计算本次有效成交数量；
* 得到 Order Fill Mutation Result；
* 确定 Order 是否部分成交或全部成交。

Position 等下游只能使用 OrderManager 确认后的有效 Fill。

不得让 Position 直接使用未验证 Broker Trade。

---

# 22. 标准化 Trade Accounting 输入

推荐定义：

```text
OnlyExecutionTradeAccountingInput
```

至少包含：

```text
broker_trade_update
validated_trade
order_before
order_after
order_fill_mutation

effective_fill_quantity
effective_fill_price
fee_breakdown

runtime_id
account_id
cluster_id
instrument_id

ts_event
sequence
correlation_id
```

随后各 Manager 使用这一统一输入或其受限投影视图。

避免每个 Manager 重新解析 Broker Update。

---

# 23. Position 更新

PositionManager 只更新账户真实仓位。

输入来自已验证 Trade。

必须返回：

```text
OnlyPositionMutationResult
```

包含：

```text
position_before
position_after
quantity_delta
cost_delta
realized_pnl_delta
settlement_bucket_delta
events
```

T+1 买入：

```text
进入 UNSETTLED
```

卖出：

```text
只减少允许的 SETTLED/可卖 Bucket
```

PositionManager 必须继续保护底层不变量，即使 Risk 已检查。

---

# 24. Allocation 更新

PositionAllocationManager 根据：

```text
order.cluster_id
```

更新对应 Cluster Allocation。

不得根据账户总仓位推断 Cluster 归属。

无法恢复 Cluster：

```text
→ Unallocated Position
或
→ RECONCILIATION_REQUIRED
```

具体行为必须符合当前 Position 文档。

Allocation Mutation 必须输出：

```text
realized_pnl_delta
position_cost_delta
allocation_before
allocation_after
```

供 StrategyLedger 使用。

---

# 25. Strategy Ledger 更新

StrategyLedgerManager 不重新计算持仓成本。

它必须使用：

```text
OnlyPositionAllocationMutationResult
```

更新：

```text
virtual cash
cash reservation
fee
realized pnl
position cost
unrealized pnl input
equity
drawdown
```

买入：

```text
消费 Strategy Cash Reservation
减少虚拟现金
记录费用
```

卖出：

```text
增加虚拟现金
记录费用
应用 Allocation 已实现盈亏
```

重复 Trade 不得重复记账。

---

# 26. Account 更新

AccountManager 维护账户真实资金状态。

它使用账户级 Trade Accounting 输入更新：

```text
cash
frozen cash
fees
realized pnl
position market value input
equity input
```

不得使用 Strategy Ledger 的虚拟现金更新 Account。

不得使用 Cluster Allocation 代替账户 Position。

Account 和 StrategyLedger 的更新是两套独立账。

---

# 27. Reservation 统一协调

ExecutionProcessor 是 Reservation 生命周期的统一协调者。

可能涉及：

```text
OnlyRiskReservation
OnlyPositionReservation
OnlyStrategyCashReservation
OnlyAccountReservation
```

## 买单部分成交

```text
Risk Reservation
    部分消费

Strategy Cash Reservation
    按实际成交金额和费用部分消费

Account Reservation
    部分消费

剩余数量对应 Reservation
    保持 ACTIVE
```

## 卖单部分成交

```text
Position Reservation
    部分消费

Risk Reservation
    部分消费

剩余卖出数量
    保持冻结
```

## 完全成交

```text
Reservation → CONSUMED
```

## Rejected / Cancelled / Expired / Failed

```text
释放所有未消费部分
```

禁止各 Manager 通过 Event 各自猜测 Reservation 生命周期。

---

# 28. Reservation 操作顺序

推荐：

```text
先完成核心业务状态更新
→ 再消费 Reservation
→ 再检查最终不变量
```

但执行前必须验证 Reservation 足够。

建议采用：

```text
预检查
→ 核心 Mutation
→ Reservation Commit
```

如果 Reservation 不足：

```text
不应静默产生负数
→ RECONCILIATION_REQUIRED
```

---

# 29. Account Update 处理

`OnlyBrokerAccountUpdate` 不得直接覆盖 Account。

推荐：

```text
Broker Account Update
→ 标准化 Snapshot
→ AccountReconciliationService
→ Difference / Severity / Action
→ AccountManager.apply_reconciliation_result()
```

如果完全一致：

```text
APPLIED / IGNORED
```

如果关键冲突：

```text
BLOCK_ACCOUNT
→ Risk Fail Closed
→ RECONCILIATION_REQUIRED
```

---

# 30. Position Update 处理

`OnlyBrokerPositionUpdate` 不得直接覆盖 Position。

推荐：

```text
Broker Position Update
→ PositionReconciliationService
→ Difference
→ Severity
→ Action
```

关键冲突：

```text
BLOCK_INSTRUMENT
或
BLOCK_ACCOUNT
```

不得破坏 Cluster Allocation 历史。

无法解释的数量进入：

```text
OnlyUnallocatedPosition
```

但必须有明确审计。

---

# 31. Connection Update

`OnlyBrokerConnectionUpdate` 至少处理：

```text
CONNECTED
AUTHENTICATED
READY
DISCONNECTED
RECONNECTING
FAILED
```

连接状态变化可能影响：

```text
Runtime Status
Account Status
Risk Fail Closed
```

但不得由 Gateway 直接修改这些状态。

Processor 或专门 Connection Coordinator 负责。

第一版可以仅：

* 更新 Broker Connection State；
* 发布事实 Event；
* 将断线账户标记为受限；
* 让 Risk Account Rule 阻止新订单。

---

# 32. Mutation Plan

为了降低处理中途失败风险，建议定义：

```text
OnlyExecutionMutationPlan
```

在修改前完成：

```text
所有 ID 和 Scope 校验
Order 剩余数量检查
Position 可接受性检查
Allocation 归属检查
Ledger 币种检查
Account 币种检查
Reservation 充足性检查
必要 Manager 可用性检查
```

只有预检查通过后才开始 Commit。

第一版不要求数据库事务，但必须实现逻辑事务边界。

---

# 33. Mutation Bundle

定义：

```text
OnlyExecutionMutationBundle
```

包含：

```text
order_mutation
position_mutation
allocation_mutation
ledger_mutation
account_mutation
risk_mutation
reservation_mutations
generated_events
```

用于：

* Audit；
* Report；
* Reconciliation；
* 测试；
* Replay。

---

# 34. 中途失败处理

如果处理中途发生异常：

```text
Position 已更新
但 Ledger 更新失败
```

不得：

* 继续发布成功 Event；
* 假装整条 Trade 已成功；
* 吞掉异常继续运行；
* 自动反向修改但无审计。

必须：

```text
停止后续处理
→ 保存已完成 Mutation Step
→ 标记相关 Scope 为 RECONCILIATION_REQUIRED
→ 创建 OnlyExecutionReconciliationRequest
→ 返回结构化失败
→ 发布系统错误事实 Event
```

至少标记：

```text
order_id
trade_id
account_id
instrument_id
cluster_id
completed_steps
failed_step
required_recovery
```

---

# 35. Reconciliation Port

定义：

```text
OnlyExecutionReconciliationPort
```

建议：

```python
def request_reconciliation(
    request: OnlyExecutionReconciliationRequest,
) -> None:
    ...
```

第一版提供：

```text
OnlyInMemoryExecutionReconciliationQueue
OnlyNoOpExecutionReconciliationPort（仅测试明确使用）
```

生产 Runtime 不得默认 NoOp。

---

# 36. 跨组件不变量检查

定义：

```text
OnlyExecutionInvariantChecker
```

每次 Trade 完成后至少检查：

```text
Order filled_quantity <= order quantity

Order remaining_quantity >= 0

Account Position
=
Cluster Allocation Sum
+
Unallocated Position

Cluster Allocation 数量非负

T+1 当日买入不进入当日可卖数量

Strategy Ledger 使用 Allocation 成本

Strategy Cash View
=
Strategy PnL View

Account Equity
=
Account Cash
+
Account Position Market Value
-
Liabilities

Reservation remaining >= 0

Consumed + Remaining + Released
符合原始 Reservation 数量/金额

重复 Trade 不改变 Version

不同 Runtime 状态不串流

不同 Cluster Ledger 不串流
```

Blocker 不变量失败：

```text
RECONCILIATION_REQUIRED
```

---

# 37. Event 发布顺序

Event 必须在所有必要状态更新和不变量检查通过后发布。

推荐事实事件顺序：

```text
OnlyOrderFilledEvent
OnlyPositionChangedEvent
OnlyPositionAllocationChangedEvent
OnlyStrategyLedgerUpdatedEvent
OnlyAccountUpdatedEvent
OnlyRiskStateUpdatedEvent
OnlyExecutionUpdateAppliedEvent
```

顺序必须稳定。

如果中途失败：

```text
不得发布上述成功事件
```

只允许发布：

```text
OnlyExecutionProcessingFailedEvent
OnlyExecutionReconciliationRequiredEvent
```

---

# 38. Processor 不应直接依赖完整 EventBus

定义：

```text
OnlyExecutionEventPublisher
```

由 Runtime Adapter 接入 EventBus。

Processor 调用受限 Publisher：

```python
publisher.publish_many(events)
```

避免 Processor 访问 EventBus 的订阅和内部状态。

---

# 39. Audit

定义：

```text
OnlyExecutionAuditRecord
```

至少包含：

```text
audit_id
runtime_id
gateway_id
account_id
update_id
update_type

order_id
trade_id
cluster_id
instrument_id

status
processing_sequence
completed_steps
mutation_summary
invariant_results
generated_event_ids

ts_started
ts_completed
duration
failure
reconciliation_request_id
```

第一版实现内存 Store。

必须可序列化。

---

# 40. Snapshot Bundle

处理成功后生成：

```text
OnlyExecutionSnapshotBundle
```

包含同一处理时点的一致视图：

```text
order
position
allocation
ledger
account
risk
```

所有 Snapshot：

* 不可变；
* 使用相同 logical processing sequence；
* 使用 Runtime Clock；
* 保留版本；
* 可用于测试和报告。

---

# 41. 并发模型

第一版固定：

```text
Runtime 单线程、单写入者、FIFO
```

Processor 不需要自行加多线程并发。

禁止：

* Processor 内部并行调用 Manager；
* 多个 Update 同时修改同一 Runtime；
* 使用线程池处理 Trade；
* Broker Callback Thread 直接调用 Processor；
* Web Thread 直接调用 Processor。

正确：

```text
Broker Callback
→ Runtime Queue
→ Runtime Thread
→ Processor
```

---

# 42. 确定性要求

相同：

```text
初始 Runtime State
Broker Update 序列
Clock
Instrument
Order
Reservation
Position
Allocation
Ledger
Account
```

必须得到相同：

```text
Processing Status
Mutation Bundle
Snapshot Bundle
Event 顺序
Version
PnL
Equity
Audit
Reconciliation Result
```

禁止：

* 随机 ID；
* 系统时间；
* 无序 dict/set 决定顺序；
* 非确定性 Event 排序；
* 依赖线程时序。

---

# 43. 推荐目录

根据当前工程调整，建议：

```text
src/onlyalpha/execution/
├── __init__.py
├── enums.py
├── configs.py
├── contexts.py
├── results.py
├── failures.py
├── mutations.py
├── plans.py
├── processor.py
├── dispatch.py
├── deduplication.py
├── sequence.py
├── invariants.py
├── snapshots.py
├── audit.py
├── reconciliation.py
├── events.py
├── publisher.py
└── processors/
    ├── accepted.py
    ├── rejected.py
    ├── cancelled.py
    ├── trade.py
    ├── account.py
    ├── position.py
    └── connection.py
```

不要把 ExecutionProcessor 放入 Broker、Order 或 Event 模块内部。

---

# 44. 单元测试

建议新增：

```text
tests/execution/
├── test_execution_processor_dispatch.py
├── test_execution_processor_scope.py
├── test_execution_processor_unknown_update.py

├── test_order_accepted_processing.py
├── test_late_order_accepted.py
├── test_order_rejected_processing.py
├── test_order_cancelled_processing.py

├── test_trade_processing_order_first.py
├── test_trade_processing_position.py
├── test_trade_processing_allocation.py
├── test_trade_processing_ledger.py
├── test_trade_processing_account.py
├── test_trade_processing_risk.py

├── test_partial_fill_processing.py
├── test_full_fill_processing.py

├── test_risk_reservation_consumption.py
├── test_position_reservation_consumption.py
├── test_strategy_cash_reservation_consumption.py
├── test_account_reservation_consumption.py
├── test_reservation_release_on_reject.py
├── test_reservation_release_on_cancel.py

├── test_duplicate_update.py
├── test_duplicate_trade.py
├── test_stale_update.py
├── test_out_of_order_trade.py
├── test_state_regression_prevention.py

├── test_execution_mutation_plan.py
├── test_execution_mutation_bundle.py
├── test_execution_invariant_checker.py
├── test_execution_failure_reconciliation.py
├── test_execution_audit.py
├── test_execution_snapshot_bundle.py

├── test_account_update_reconciliation.py
├── test_position_update_reconciliation.py
├── test_connection_update.py

├── test_execution_runtime_isolation.py
├── test_execution_cluster_isolation.py
├── test_execution_serialization.py
└── test_execution_determinism.py
```

---

# 45. 完整连通测试强制要求

本任务必须严格遵守：

```text
AGENTS.md
docs/integration_vertical_slice.md
scripts/run_component_validation.sh
```

不能只完成 ExecutionProcessor 单元测试。

必须将 Processor 接入当前统一：

```text
OnlyIntegrationEnvironment
```

并让所有 Broker Update 都通过：

```text
Runtime Inbound Queue
→ OnlyExecutionProcessor
```

不得继续由 Demo 或测试直接依次调用各 Manager 模拟成交链。

---

# 46. 更新完整 Vertical Slice

更新后的正式链路：

```text
OnlyBacktestRuntime
    ↓
OnlyBacktestClock
    ↓
MarketData
    ↓
MarketData Pipeline
    ↓
Snapshot
    ↓
Cluster.on_bar()
    ↓
ctx.orders.submit()
    ↓
RiskService
    ↓
OrderManager
    ↓
ExecutionService
    ↓
VirtualBrokerGateway
    ↓
MatchingEngine
    ↓
Broker Update Queue
    ↓
OnlyExecutionProcessor
    ↓
OrderManager
    ↓
PositionManager
    ↓
PositionAllocationManager
    ↓
StrategyLedgerManager
    ↓
AccountManager
    ↓
Reservation Managers
    ↓
RiskService Post-Trade Update
    ↓
事实 Events
    ↓
Final Snapshot
```

正常完整场景中禁止：

* 手工调用 PositionManager；
* 手工调用 AllocationManager；
* 手工调用 LedgerManager；
* 手工调用 AccountManager；
* 绕过 ExecutionProcessor。

---

# 47. Integration Environment 更新

加入：

```text
execution_processor
execution_update_deduplicator
execution_sequence_tracker
execution_invariant_checker
execution_audit_store
execution_reconciliation_queue
execution_event_publisher
```

确保 Runtime Queue 消费 Broker Update 时调用 Processor。

---

# 48. 新增集成场景

至少新增：

## 48.1 Accepted

```text
Order Submitted
→ Broker Accepted Update
→ Processor
→ Order ACCEPTED
```

验证 Submit 成功和 Accepted 分离。

## 48.2 Rejected

```text
Order Submitted
→ Broker Rejected
→ Order REJECTED
→ 所有未消费 Reservation 释放
→ 无 Position/Ledger/Account Trade 更新
```

## 48.3 Partial Fill

```text
Order 1000
→ Fill 400
```

验证：

* Order PARTIALLY_FILLED；
* Position +400；
* Allocation +400；
* Ledger 和 Account 只记 400；
* Reservation 只消费 400；
* 剩余 600 保留。

## 48.4 Full Fill

继续 Fill 600：

* Order FILLED；
* 所有 Reservation 终结；
* Position/Allocation/Ledger/Account 正确；
* Risk 更新。

## 48.5 Partial Fill Then Cancel

```text
Fill 400
→ Cancel remaining 600
```

验证只释放剩余部分。

## 48.6 Duplicate Trade

相同 Broker Trade Update 两次：

* 第二次返回 DUPLICATE；
* 所有状态和 Version 不变化；
* 不重复发布事实 Event。

## 48.7 Late Accepted

Order 已 FILLED 后收到 Accepted：

* 状态不回退；
* 返回 IGNORED 或 STALE；
* 不产生错误业务变化。

## 48.8 Out-of-Order Trade

旧 sequence Trade 到达：

```text
RECONCILIATION_REQUIRED
```

不得静默应用。

## 48.9 Mid-Pipeline Failure

模拟 Ledger 更新失败：

* 已完成步骤记录；
* 不发布完整成功 Event；
* 创建 Reconciliation Request；
* 相关 Scope 被阻断。

## 48.10 多 Cluster 共享账户

验证：

* A、B Broker Update 串行处理；
* Position 账户级合并；
* Allocation、Ledger 分开；
* Account 合并；
* Reservation Scope 正确。

## 48.11 T+1 买卖闭环

买入成交：

```text
Position UNSETTLED
```

同日卖出：

```text
Risk REJECT
```

下一 Trading Day 结算后卖出成交：

* Position；
* Allocation；
* Ledger；
* Account；
* Reservation；
* PnL；

全部一致。

---

# 49. 历史场景回归

必须运行全部历史场景：

```text
Domain
Clock
Runtime
Context
Cluster
MarketData
Order
Risk
Position
Allocation
StrategyLedger
Account
Broker
VirtualBroker
```

不得：

* 删除；
* Skip；
* 放宽断言；
* 复制新旁路；
* 只运行新场景。

如果旧场景仍手工调用各 Manager，应将其迁移到 Processor 正式路径，但保持业务期望不变。

---

# 50. 完整不变量

全链路至少验证：

```text
BrokerGateway 不直接修改 Manager

所有 Broker Update 通过 Runtime Queue

所有 Update 通过 ExecutionProcessor

Order 先于 Position 更新

Position 先于 Allocation 更新

Allocation 先于 StrategyLedger 更新

Account 使用账户级 Trade 数据

StrategyLedger 使用 Cluster Allocation 成本

Reservation 只消费或释放一次

重复 Fill 不重复记账

迟到状态不回退

Account Position
=
Allocation Sum
+
Unallocated

Strategy Cash View
=
Strategy PnL View

Account Equity 公式正确

T+1 当日买入不可卖

Event 在完整状态形成后发布

失败时不发布成功 Event

相同输入重放结果完全一致
```

---

# 51. Deterministic Replay

使用固定：

```text
Runtime 配置
Clock
Bar 序列
Cluster 配置
Order 请求
Risk Profile
Virtual Broker 配置
Matching 配置
Broker Update 序列
```

至少重复运行 100 次。

比较：

```text
Update Processing Result
Order Snapshot
Position Snapshot
Allocation Snapshot
Ledger Snapshot
Account Snapshot
Risk Snapshot
Reservation State
Mutation Bundle
Audit Record
Event Sequence
Reconciliation Result
```

必须一致。

---

# 52. Demo

更新：

```text
examples/integration_demo/
```

并创建：

```text
examples/execution_processor_demo/
├── README.md
├── accepted_demo.py
├── rejected_demo.py
├── partial_fill_demo.py
├── cancel_after_partial_fill_demo.py
├── duplicate_update_demo.py
├── out_of_order_demo.py
├── reconciliation_demo.py
└── full_vertical_slice_demo.py
```

Demo 必须调用正式 Runtime Queue 和 Processor。

---

# 53. 文档

创建或更新：

```text
docs/execution_processor.md
docs/runtime.md
docs/event.md
docs/order.md
docs/risk.md
docs/position.md
docs/strategy_ledger.md
docs/account.md
docs/broker_gateway.md
docs/virtual_broker.md
docs/integration_vertical_slice.md
docs/architecture.md
docs/architecture_principles.md
docs/testing.md
```

`docs/execution_processor.md` 至少包括：

1. 组件职责；
2. 统一入口；
3. Update 类型；
4. 固定处理顺序；
5. Mutation Plan；
6. Mutation Bundle；
7. Reservation 协调；
8. 幂等；
9. Sequence；
10. 迟到和乱序；
11. 中途失败；
12. Reconciliation；
13. 不变量；
14. Event 顺序；
15. Audit；
16. Snapshot Bundle；
17. Runtime Queue；
18. 并发模型；
19. Determinism；
20. Demo；
21. 已知限制。

---

# 54. ADR

创建：

```text
docs/adr/0016-execution-processor-ordered-trade-application.md
```

至少记录：

## 背景

标准化 Broker Update 到达后，需要按固定顺序更新 Order、Position、Allocation、StrategyLedger、Account、Reservation 和 Risk。使用 EventBus 分散 Handler 无法保证一致性。

## 决策

* 每个 Runtime 一个 ExecutionProcessor；
* 所有 Broker Update 通过 Runtime Queue；
* Processor 是统一处理入口；
* Trade 更新顺序固定；
* Manager 使用函数调用；
* Event 在完整状态形成后发布；
* Processor 负责 Reservation 协调；
* 重复 Update 幂等；
* 迟到和乱序明确处理；
* 中途失败进入 Reconciliation；
* 回测、Virtual Broker、Paper 和 Live 共用同一 Processor。

## 拒绝方案

* Broker 回调直接修改 Manager；
* 多个 Event Handler 分散更新；
* 每个 Manager 自己消费 Reservation；
* Demo 手工调用多个 Manager；
* 更新失败后继续发布成功 Event；
* 回测与 Live 使用不同执行链。

---

# 55. Architecture Principles 新增规则

加入：

```text
Rule: 所有 Broker Update 必须通过 Runtime Inbound Queue。

Rule: OnlyExecutionProcessor 是 Broker Update 的唯一业务处理入口。

Rule: BrokerGateway 不直接修改任何 Manager。

Rule: Trade 更新必须按明确固定顺序执行。

Rule: Event 只能在完整状态成功形成后发布。

Rule: ExecutionProcessor 统一协调 Reservation 生命周期。

Rule: 重复 Broker Update 必须幂等。

Rule: 迟到 Update 不得导致状态回退。

Rule: 无法安全应用的乱序 Update 必须进入 Reconciliation。

Rule: 中途失败不得发布完整成功 Event。

Rule: Backtest、Paper、Live 和 Virtual Broker 共用同一 ExecutionProcessor API。

Rule: 所有新增组件必须接入完整 Vertical Slice 并运行历史回归。
```

---

# 56. 实现顺序

严格按以下顺序：

1. 扫描现有 Broker Update 和成交处理链；
2. 创建差距分析；
3. 定义 Processing Status/Result/Failure；
4. 定义 Processing Context；
5. 实现 Update 分派；
6. 实现 Update 去重；
7. 实现 Sequence Tracker；
8. 实现 Accepted Processor；
9. 实现 Rejected Processor；
10. 实现 Cancelled Processor；
11. 定义 Trade Accounting Input；
12. 实现 Mutation Plan；
13. 实现 Trade Processor；
14. 接入 OrderManager；
15. 接入 PositionManager；
16. 接入 AllocationManager；
17. 接入 StrategyLedgerManager；
18. 接入 AccountManager；
19. 接入 Reservation Manager；
20. 接入 Risk Post-Trade；
21. 实现 Invariant Checker；
22. 实现 Mutation Bundle；
23. 实现中途失败处理；
24. 实现 Reconciliation Port；
25. 实现 Audit；
26. 实现 Snapshot Bundle；
27. 实现 Event Publisher；
28. 接入 Runtime Queue；
29. 更新 Integration Environment；
30. 迁移旧成交场景到 Processor；
31. 新增完整集成场景；
32. 运行全部历史测试；
33. 运行 Replay；
34. 创建 Demo；
35. 更新文档；
36. 创建 ADR；
37. 生成集成报告。

---

# 57. 验收标准

完成后必须满足：

* 每个 Runtime 拥有独立 ExecutionProcessor；
* BrokerGateway 不直接修改 Manager；
* Broker Update 全部进入 Runtime Queue；
* Processor 是唯一业务入口；
* Accepted/Rejected/Cancelled 语义正确；
* Partial Fill 正确；
* Full Fill 正确；
* Order 更新先于 Position；
* Position 更新先于 Allocation；
* Allocation 更新先于 Ledger；
* Account 更新使用账户级数据；
* Reservation 生命周期统一；
* 重复 Update 幂等；
* 重复 Trade 幂等；
* 迟到 Accepted 不回退状态；
* 乱序 Trade 进入 Reconciliation；
* 中途失败不发布成功 Event；
* 跨组件不变量被检查；
* Snapshot Bundle 一致；
* Audit 完整；
* Virtual Broker 正常链路通过 Processor；
* 所有历史集成场景通过；
* Deterministic Replay 通过；
* 文档、Demo、ADR、报告完整。

---

# 58. 一票否决项

存在以下任一项，任务必须判定为 `REJECTED`：

* Broker Gateway 直接调用 Manager；
* Broker Update 绕过 Runtime Queue；
* Trade 绕过 ExecutionProcessor；
* 使用 EventBus Handler 分散修改业务状态；
* 更新顺序依赖订阅顺序；
* StrategyLedger 自己重算 Allocation 成本；
* Account 使用 StrategyLedger 虚拟资金；
* Reservation 被重复消费或释放；
* 重复 Trade 重复修改状态；
* 迟到 Update 导致状态回退；
* 乱序 Update 被静默应用；
* 中途失败后发布成功 Event；
* Demo 直接调用多个 Manager 模拟成交；
* 历史场景被删除、Skip 或放宽；
* 相同输入重放结果不同；
* 新增 ARL；
* 引入历史兼容设计。

---

# 59. 集成报告

生成：

```text
docs/reports/execution_processor_integration_report.md
```

至少包含：

```text
新增文件
修改文件
ExecutionProcessor 组件边界
Runtime 所有权
Broker Update 统一入口
Update 分派
固定 Trade 更新顺序
Mutation Plan
Mutation Bundle
Order 更新结果
Position 更新结果
Allocation 更新结果
StrategyLedger 更新结果
Account 更新结果
Reservation 协调
Risk Post-Trade 更新
幂等设计
Sequence 设计
迟到回报处理
乱序回报处理
中途失败处理
Reconciliation
Invariant Checker
Event 发布顺序
Audit
Snapshot Bundle
Runtime Queue 接入
Integration Environment 更新
新增集成场景
历史场景结果
单元测试结果
上下游集成测试结果
完整 Vertical Slice 结果
Deterministic Replay 结果
关键不变量
已知限制
一票否决项
是否建议进入 Paper Runtime
是否建议进入 Recovery Orchestrator
是否建议接入首个真实 Broker
```

最终结论只能是：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```
