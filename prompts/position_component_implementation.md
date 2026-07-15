# OnlyAlpha Position、策略归因、T+1 结算与券商持仓对账组件实现任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的 Position 组件。

本阶段需要建立一套支持多策略共享同一券商账户的双层持仓模型：

```text
账户真实持仓
    +
策略归因持仓账本
```

核心原则：

```text
OnlyPositionManager
    维护当前 Runtime 内账户真实持仓

OnlyPositionAllocationManager
    维护各 Cluster 对账户持仓的内部归因

OnlyUnallocatedPosition
    承接无法归因、人工交易、外部交易或对账差异

OnlyPositionReconciliationService
    负责本地账户持仓与券商持仓快照的对账
```

必须明确区分：

```text
券商账户真实账
策略内部归因账
```

券商账户仓位用于：

* 真实持仓数量；
* 真实可卖数量；
* 账户级风险；
* 资金和保证金计算；
* 券商同步；
* 实盘对账。

策略归因仓位用于：

* Cluster 自身持仓；
* Cluster 可操作数量；
* 策略已实现盈亏；
* 策略未实现盈亏；
* 策略手续费；
* 策略资金占用；
* 策略绩效分析。

不得从券商总仓位事后按比例推算策略持仓和收益。

每张 Order 和 Trade 必须保留 `cluster_id`，从订单创建开始持续维护策略归属。

---

# 2. 本阶段范围

本阶段需要实现或完善：

```text
OnlyPosition
OnlyPositionId
OnlyPositionKey
OnlyPositionSide
OnlyPositionMode
OnlyPositionStatus

OnlyPositionSnapshot
OnlyPositionMutationResult
OnlyPositionManager
OnlyPositionQueryService
OnlyPositionQueryView

OnlyPositionAllocation
OnlyPositionAllocationId
OnlyPositionAllocationKey
OnlyPositionAllocationSnapshot
OnlyPositionAllocationManager
OnlyPositionAllocationQueryView

OnlyUnallocatedPosition
OnlyPositionTrade
OnlyPositionFill

OnlyPositionBucket
OnlySettlementBucket
OnlyAvailabilityState
OnlyPositionRestriction
OnlyPositionRestrictionType

OnlyPositionReservation
OnlyPositionReservationId
OnlyPositionReservationStage
OnlyPositionReservationManager

OnlyPnLModel
OnlyLinearPnLModel
OnlyPositionValuation
OnlyPositionValuationService

OnlyBrokerPositionSnapshot
OnlyPositionReconciliationService
OnlyPositionReconciliationResult
OnlyPositionDifference
OnlyPositionConflict
OnlyPositionAuthorityPolicy
OnlyReconciliationSeverity
OnlyReconciliationAction

OnlySettlementService
OnlySettlementRule
OnlySettlementResult

OnlyPositionEventPublisher
OnlyPositionRepository
```

本阶段暂不完整实现：

* 完整 AccountManager；
* 真实资金扣减；
* 完整 Margin Engine；
* 真实券商 SDK；
* 自动强平；
* 内部策略订单净额化；
* 策略间自动转仓；
* 复杂公司行动；
* 跨券商持仓同步；
* 完整期权 Greeks；
* Inverse/Quanto 完整盈亏；
* 税务 FIFO/LIFO；
* 自动人工差异修复。

券商部分只定义标准化持仓快照接口和对账入口，不接真实 SDK。

---

# 3. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md
docs/event.md
docs/runtime_context.md
docs/runtime.md
docs/cluster.md
docs/order.md
docs/risk.md
docs/testing.md
docs/coding_style.md
docs/architecture_principles.md
docs/adr/
```

重点检查现有类型：

```text
OnlyPrice
OnlyQuantity
OnlyMoney
OnlyCurrency
OnlyMultiplier

OnlyRuntimeId
OnlyClusterId
OnlyAccountId
OnlyInstrumentId
OnlyOrderId
OnlyTradeId

OnlyOrder
OnlyOrderSnapshot
OnlyOrderManager
OnlyRiskReservation
OnlyRiskService
OnlyTradingCalendar
OnlyTradingDay
OnlyMarketRule
```

同时分析旧工程：

```text
/home/zongxin/workspace/MyQuant
```

重点了解：

* 当前持仓模型；
* 多策略持仓归因；
* 仓位均价；
* 已实现和未实现盈亏；
* A 股 T+1；
* 可卖数量；
* 冻结数量；
* 券商持仓同步；
* 重启恢复；
* 人工交易；
* 外部交易；
* 策略收益统计。

只参考行为，不直接复制旧架构。

---

# 4. 先创建差距分析

创建：

```text
docs/position_component_analysis.md
```

至少分析：

## 4.1 当前持仓模型

| 类型 | 当前职责 | 当前问题 | 目标类型 |
| -- | ---- | ---- | ---- |

## 4.2 当前持仓更新链

画出：

```text
Trade
→ Order
→ Position
→ Account
→ Risk
→ Strategy
```

检查：

* Position 是否由多个组件同时修改；
* Position 是否直接订阅公共 Event 修改状态；
* Position 是否使用券商原始结构；
* 是否混淆账户仓位和策略仓位；
* 是否只能表示净仓位；
* 是否缺少 T+1；
* 是否缺少 settled/unsettled；
* 是否缺少冻结和预占；
* 是否重复应用 Trade；
* 是否处理乱序 Trade；
* 是否把券商快照直接覆盖本地状态；
* 是否无法解释多策略收益。

## 4.3 当前数据来源

列出：

```text
Order
Trade
Instrument
MarketRule
TradingCalendar
Broker Position Snapshot
Risk Reservation
Position Reservation
Account Snapshot
```

标明当前是否存在、可否复用及本次需要的抽象 Port。

完成差距分析后再开始修改代码。

---

# 5. 总体双层模型

必须采用：

```text
OnlyAccountPosition
    账户真实持仓

OnlyPositionAllocation
    Cluster 持仓归因
```

也可以保留统一名称：

```text
OnlyPosition
    表示账户真实仓位

OnlyPositionAllocation
    表示策略归因仓位
```

## 5.1 账户真实持仓

账户真实仓位唯一键由账户模式决定。

NETTING：

```text
runtime_id
account_id
instrument_id
```

HEDGING：

```text
runtime_id
account_id
instrument_id
position_side
```

账户真实仓位是 Runtime 内交易和对账的权威状态。

## 5.2 策略归因仓位

归因键：

```text
runtime_id
account_id
cluster_id
instrument_id
position_side
```

用于保存：

* Cluster 数量；
* Cluster 平均开仓价；
* Cluster 已实现盈亏；
* Cluster 未实现盈亏；
* Cluster 费用；
* Cluster 结算 Bucket；
* Cluster 冻结和预占；
* Cluster 收益归因。

## 5.3 核心数量不变量

必须满足：

```text
账户真实持仓数量
=
所有 Cluster Allocation 数量之和
+
Unallocated Position 数量
```

如果暂时无法满足，相关 Position 必须进入：

```text
RECONCILING
```

并阻止不安全的交易。

---

# 6. 每个 Runtime 一个 Position 状态域

结构：

```text
OnlyEngine
├── OnlyLiveRuntime
│   ├── OnlyPositionManager
│   └── OnlyPositionAllocationManager
├── OnlyPaperRuntime
│   ├── OnlyPositionManager
│   └── OnlyPositionAllocationManager
└── OnlyBacktestRuntime
    ├── OnlyPositionManager
    └── OnlyPositionAllocationManager
```

不得：

* Engine 使用一个全局可变 PositionManager；
* 每个 Cluster 单独拥有账户 PositionManager；
* 不同 Runtime 共享可变 Position；
* 不同 Runtime 共享 Allocation；
* Cluster 直接修改 Position。

---

# 7. Position Mode

定义：

```text
OnlyPositionMode
├── NETTING
└── HEDGING
```

## 7.1 NETTING

适用于：

* A 股；
* 港股；
* 美股净额账户；
* Crypto Spot；
* 某些期货净额模式。

## 7.2 HEDGING

适用于：

* 中国期货；
* 双向持仓期货或永续；
* 同一 Instrument 同时持有 Long 和 Short。

模型层必须立即支持两种 Mode。

第一版业务重点实现：

```text
NETTING
Long-only 股票/ETF
```

但 `OnlyPositionKey`、`OnlyPositionSide` 和 Manager 结构不得阻碍未来 HEDGING。

---

# 8. Position Side 与成交语义

定义或复用：

```text
OnlyPositionSide
├── LONG
├── SHORT
└── FLAT
```

对于期货必须保留：

```text
OnlyDirection
OnlyOffset
```

语义示例：

```text
BUY + OPEN
    增加 LONG

SELL + OPEN
    增加 SHORT

SELL + CLOSE
    减少 LONG

BUY + CLOSE
    减少 SHORT

SELL + CLOSE_TODAY
    减少 LONG TODAY Bucket

SELL + CLOSE_YESTERDAY
    减少 LONG YESTERDAY Bucket
```

禁止只使用 BUY/SELL 推断所有市场持仓变化。

---

# 9. Position 生命周期

推荐：

```text
每次 FLAT → OPEN 创建新的 PositionId
每次 OPEN → FLAT 关闭当前 Position
下一次开仓创建新的 PositionId
```

状态：

```text
OPEN
CLOSED
RECONCILING
ERROR
```

可以使用派生 `FLAT` 状态，但活跃 Position 索引不应长期持有零数量对象。

这样有利于：

* 每轮开平仓统计；
* 持仓时长；
* 回测分析；
* 审计；
* 策略绩效；
* 生命周期清晰。

---

# 10. Position 内部可变与外部 Snapshot

采用：

> 内部受控可变实体，外部只暴露 immutable Snapshot。

外部禁止：

```python
position.quantity = ...
position.average_open_price = ...
position.realized_pnl = ...
position.status = ...
```

必须通过：

```python
position.apply_trade(...)
position.freeze(...)
position.release(...)
position.settle(...)
position.apply_restriction(...)
position.remove_restriction(...)
```

所有修改返回：

```text
OnlyPositionMutationResult
```

查询返回：

```text
OnlyPositionSnapshot
```

不得向 Cluster、Web、Risk 或 Account 暴露可变 Position 实体。

---

# 11. Position 核心状态

建议账户 Position 包含：

```text
position_id
runtime_id
account_id
instrument_id
position_side
position_mode
status

total_quantity
settled_quantity
unsettled_quantity

order_frozen_quantity
risk_reserved_quantity
restricted_quantity

average_open_price
realized_pnl

opened_at
updated_at
closed_at

version
last_trade_sequence
quality_flags
metadata
```

以下值建议派生：

```text
tradable_quantity
available_quantity
remaining_quantity
market_value
unrealized_pnl
```

不要同时保存多个可写字段导致不一致。

---

# 12. T+1 核心数量语义

必须明确以下概念。

## 12.1 Total Quantity

```text
total_quantity
```

账户当前拥有的总数量。

## 12.2 Settled Quantity

```text
settled_quantity
```

满足市场结算条件的数量。

## 12.3 Unsettled Quantity

```text
unsettled_quantity
```

尚未满足卖出或交割条件的数量。

## 12.4 Tradable Quantity

```text
tradable_quantity
```

根据市场规则、Instrument 状态和限制计算出的可交易数量。

## 12.5 Available Quantity

```text
available_quantity
```

考虑本地订单冻结、Risk 预占和限制后，当前还能用于新订单的数量。

推荐关系：

```text
available_quantity
=
tradable_quantity
- order_frozen_quantity
- risk_reserved_quantity
- restricted_quantity
```

所有数量不得为负。

对于 A 股常见关系：

```text
available_quantity
<= tradable_quantity
<= settled_quantity
<= total_quantity
```

但不要硬编码为所有市场通用规则，应由 MarketRule 和 SettlementRule 决定。

---

# 13. Position Bucket 模型

不要只使用：

```text
quantity
available_quantity
```

描述所有市场。

定义：

```text
OnlyPositionBucket
OnlySettlementBucket
OnlyAvailabilityState
```

## 13.1 Settlement Bucket

至少：

```text
SETTLED
UNSETTLED
TODAY
YESTERDAY
UNKNOWN
```

第一版 A 股重点使用：

```text
SETTLED
UNSETTLED
```

未来期货使用：

```text
TODAY
YESTERDAY
```

## 13.2 Availability State

至少：

```text
AVAILABLE
ORDER_FROZEN
RISK_RESERVED
MARKET_RESTRICTED
BROKER_RESTRICTED
CORPORATE_ACTION_LOCKED
RECONCILING
```

一个 Quantity 可以同时具有结算状态和可用性状态。

不要把所有状态压缩为单一枚举。

---

# 14. Position Restriction

定义：

```text
OnlyPositionRestriction
OnlyPositionRestrictionId
OnlyPositionRestrictionType
OnlyPositionRestrictionSource
```

字段建议：

```text
restriction_id
runtime_id
account_id
instrument_id
position_side
quantity
restriction_type
source
effective_from
effective_to
reason
version
metadata
```

类型至少预留：

```text
UNSETTLED
SUSPENDED_INSTRUMENT
CORPORATE_ACTION
BROKER_FREEZE
COURT_FREEZE
PLEDGED
LOCKUP
BORROW_RECALL
ACCOUNT_RESTRICTED
PENDING_TRANSFER
UNKNOWN
```

第一版完整支持：

```text
UNSETTLED
SUSPENDED_INSTRUMENT
BROKER_FREEZE
RECONCILING
```

---

# 15. A 股 T+1 示例

初始昨日持仓：

```text
settled = 1000
unsettled = 0
```

当日买入 500：

```text
total_quantity = 1500
settled_quantity = 1000
unsettled_quantity = 500
tradable_quantity = 1000
available_quantity = 1000
```

提交卖单 600：

```text
order_frozen_quantity = 600
available_quantity = 400
```

成交 200：

```text
total_quantity = 1300
settled_quantity = 800
unsettled_quantity = 500
order_frozen_quantity = 400
available_quantity = 400
```

撤销剩余 400：

```text
order_frozen_quantity = 0
available_quantity = 800
```

必须通过测试完整验证。

---

# 16. Position Trade 输入

定义标准化：

```text
OnlyPositionTrade
```

至少包含：

```text
trade_id
venue_trade_id
order_id
cluster_id
runtime_id
account_id
instrument_id

side
direction
offset
position_side

price
quantity
fee

ts_event
ts_init
external_sequence
metadata
```

PositionManager 不接受：

* 券商 SDK 原始对象；
* 普通字典；
* 未标记时区时间；
* 裸 float；
* 不明确的 BUY/SELL-only 期货成交。

---

# 17. Trade 更新顺序

Position 不直接订阅公共 Event 修改状态。

未来统一通过：

```text
OnlyExecutionProcessor
```

调用：

```text
OrderManager.apply_fill()
PositionManager.apply_trade()
PositionAllocationManager.apply_trade()
StrategyLedgerManager.apply_trade()
AccountManager.apply_trade()
RiskService.update()
```

当前阶段可以由测试和最小 Adapter 直接调用：

```python
position_manager.apply_trade(trade)
allocation_manager.apply_trade(trade)
```

但必须确保后续能够被 ExecutionProcessor 编排。

---

# 18. Netting Long-only 第一版逻辑

第一版完整实现 A 股/ETF Long-only。

## 18.1 买入

旧仓位：

```text
100 @ 10
```

买入：

```text
50 @ 12
```

新数量：

```text
150
```

新平均价：

```text
(100×10 + 50×12) / 150
```

当日买入数量进入：

```text
UNSETTLED
```

## 18.2 卖出

卖出必须满足：

```text
quantity <= effective_available_quantity
```

卖出减少：

```text
SETTLED
```

Bucket。

部分卖出后平均开仓价保持不变。

## 18.3 超卖

A 股 Long-only 模式中：

```text
sell_quantity > available_quantity
```

必须拒绝。

不得自动创建 Short Position。

Risk 应提前拒绝，但 PositionManager 仍必须保护不变量。

---

# 19. Position Flip Policy

定义：

```text
OnlyPositionFlipPolicy
├── REJECT
├── CLOSE_THEN_OPEN
└── NET_AUTOMATICALLY
```

第一版 A 股：

```text
REJECT
```

未来净额期货或 Crypto 可使用其他模式。

不得无条件自动反手。

---

# 20. Cost Basis

定义：

```text
OnlyCostBasisMethod
```

至少：

```text
AVERAGE_COST
FIFO
LIFO
SPECIFIC_LOT
```

第一版完整实现：

```text
AVERAGE_COST
```

其他方法只定义扩展点，不伪装已支持。

账户 Position 和 Cluster Allocation 必须分别维护自己的成本。

例如：

```text
A 买入 100 @ 10
B 买入 100 @ 12

账户 Position = 200 @ 11
A Allocation = 100 @ 10
B Allocation = 100 @ 12
```

策略收益不能使用账户合并均价。

---

# 21. PnL Model

定义：

```text
OnlyPnLModel
OnlyLinearPnLModel
OnlyInversePnLModel
OnlyQuantoPnLModel
```

第一版完整实现：

```text
OnlyLinearPnLModel
```

已实现盈亏：

Long：

```text
(close_price - average_open_price)
× closed_quantity
× multiplier
```

Short：

```text
(average_open_price - close_price)
× closed_quantity
× multiplier
```

禁止在 PositionManager 中硬编码所有市场公式。

PositionManager 根据 Instrument 或 PnLModel 计算。

---

# 22. 手续费处理

第一版固定：

```text
Position average_open_price
    只反映成交价格

Fee
    不隐式加入平均开仓价
```

费用保存在 Trade 或未来 StrategyLedger/Account 中。

Position Mutation 可以返回与该次成交相关的 Fee，但不直接改变纯成交均价。

策略净收益后续计算：

```text
realized_pnl
+ unrealized_pnl
- fees
```

---

# 23. Unrealized PnL 与估值

Position 核心实体保存：

```text
quantity
average_open_price
realized_pnl
```

未实现盈亏和市值是估值结果，不应成为无版本语义的永久真值。

定义：

```text
OnlyPositionValuation
OnlyPositionValuationService
```

字段：

```text
position_id
mark_price
market_value
unrealized_pnl
valuation_time
price_source
currency
quality_flags
```

通过 MarketData Snapshot 或 Mark Price 计算。

不要在每个 Tick 中直接修改 Position 核心历史状态。

---

# 24. Position Allocation

定义：

```text
OnlyPositionAllocation
```

字段建议：

```text
allocation_id
runtime_id
account_id
cluster_id
instrument_id
position_side

total_quantity
settled_quantity
unsettled_quantity
order_frozen_quantity
risk_reserved_quantity
restricted_quantity

average_open_price
realized_pnl
fees

opened_at
updated_at
closed_at

version
last_trade_sequence
metadata
```

正常 Trade 归因路径：

```text
Trade.order_id
→ OrderManager
→ OrderSnapshot.cluster_id
→ PositionAllocationManager
```

如果 Trade 无法关联 Cluster：

```text
进入 OnlyUnallocatedPosition
```

不得猜测归属。

---

# 25. Cluster 可操作仓位

普通策略默认权限：

```text
CLUSTER_OWNED_ONLY
```

Cluster 只能卖出自己的归因仓位。

有效可卖量：

```text
cluster_effective_available
=
min(
    cluster_calculated_available,
    account_effective_available
)
```

不得因为账户总持仓充足，就允许 Cluster A 卖出 Cluster B 的 Allocation。

预留权限：

```text
OnlyPositionAccessMode
├── CLUSTER_OWNED_ONLY
├── ACCOUNT_SHARED
├── RISK_LIQUIDATION
└── MANUAL_RECONCILIATION
```

第一版普通策略只实现：

```text
CLUSTER_OWNED_ONLY
```

---

# 26. Position Reservation

多策略共享账户时，卖出订单通过 Risk 后必须立即预占仓位。

定义：

```text
OnlyPositionReservation
OnlyPositionReservationId
OnlyPositionReservationStage
OnlyPositionReservationState
OnlyPositionReservationManager
```

字段建议：

```text
reservation_id
runtime_id
account_id
cluster_id
instrument_id
position_side
order_id
quantity
settlement_bucket
stage
state
created_at
updated_at
version
metadata
```

Stage：

```text
LOCAL_ONLY
SENT_TO_BROKER
BROKER_ACKNOWLEDGED
RELEASE_PENDING
RELEASED
```

State：

```text
ACTIVE
PARTIALLY_CONSUMED
CONSUMED
RELEASED
FAILED
```

---

# 27. Reservation 生命周期

卖单通过 Risk：

```text
创建 Reservation
stage = LOCAL_ONLY
```

发送券商：

```text
stage = SENT_TO_BROKER
```

券商确认冻结：

```text
stage = BROKER_ACKNOWLEDGED
```

成交：

```text
冻结数量转换为持仓减少
Reservation 部分或全部 CONSUMED
```

撤单、拒单、过期：

```text
Reservation 释放
```

撤单已确认但券商可用数量尚未恢复：

```text
stage = RELEASE_PENDING
```

在券商明确恢复前，不得乐观增加可卖数量。

---

# 28. 避免本地与券商重复冻结

券商快照可能已包含已提交订单冻结。

因此必须区分：

```text
本地尚未反映到券商的预占
券商已经反映的冻结
```

实盘有效可用数量建议：

```text
effective_available_quantity
=
min(
    broker_reported_available,
    locally_calculated_tradable
)
-
local_only_reservations
```

不能对 `BROKER_ACKNOWLEDGED` Reservation 重复扣减。

必须通过测试覆盖：

* Local-only；
* Sent；
* Broker acknowledged；
* Release pending；
* Released。

---

# 29. Broker Position Snapshot

定义标准化：

```text
OnlyBrokerPositionSnapshot
```

至少包含：

```text
gateway_id
account_id
instrument_id
position_side

total_quantity
available_quantity
frozen_quantity
settled_quantity
unsettled_quantity
today_quantity
yesterday_quantity

broker_average_price
broker_market_value

snapshot_time
source_sequence
quality_flags
metadata
```

不得直接把券商 Snapshot 当作内部 Position 实体。

不得一接收到 Snapshot 就静默覆盖 Position。

---

# 30. Position Authority Policy

定义：

```text
OnlyPositionAuthority
├── LOCAL
├── BROKER
├── DERIVED
└── RECONCILED
```

以及：

```text
OnlyPositionAuthorityPolicy
```

建议字段权威：

```text
实盘账户总持仓
    BROKER

实盘券商可用数量
    BROKER + 本地预占的保守组合

Cluster Allocation
    LOCAL

Strategy PnL
    LOCAL

Broker Cost Basis
    BROKER

Local Trade Cost Basis
    LOCAL

Backtest/Paper Position
    LOCAL
```

不得为整个 Position 设置一个简单统一 Authority。

---

# 31. Reconciliation Service

定义：

```text
OnlyPositionReconciliationService
```

流程：

```text
Broker Position Snapshot
→ 标准化
→ 获取本地账户 Position Snapshot
→ 比较字段
→ 生成 Difference
→ 评估 Severity
→ 生成 Reconciliation Action
```

必须比较：

```text
total_quantity
available_quantity
frozen_quantity
settled_quantity
unsettled_quantity
position_side
average_price
```

但不同字段使用不同 Authority Policy。

---

# 32. 冲突处理规则

## 32.1 总持仓冲突

例如：

```text
local total = 1000
broker total = 800
```

实盘 Runtime 中：

* Broker 是账户真实外部权威；
* 不得静默覆盖；
* 相关 Instrument 进入 `RECONCILING`；
* 暂停该 Instrument 新订单；
* 查询 Order 和 Trade；
* 重放缺失 Trade；
* 生成差异记录；
* 无法归因部分进入 Unallocated；
* 一致后恢复。

禁止：

```python
position.total_quantity = broker.total_quantity
```

无审计直接覆盖。

## 32.2 可用数量冲突

例如：

```text
local available = 1000
broker available = 800
```

冲突期间使用更保守值：

```text
effective_available = min(local, broker)
```

同时必须：

* 标记 conflict；
* 触发对账；
* 不永久用 `min()` 掩盖差异。

## 32.3 冻结数量冲突

不得立即释放本地额外冻结。

必须先查询：

```text
open orders
pending cancels
recent fills
reservation state
```

冲突期间使用更保守冻结。

## 32.4 平均价格冲突

同时保留：

```text
local_average_price
broker_average_price
```

策略 Allocation 成本不得被券商账户均价覆盖。

---

# 33. Reconciliation Severity

定义：

```text
OnlyReconciliationSeverity
├── INFO
├── WARNING
├── BLOCK_INSTRUMENT
├── BLOCK_ACCOUNT
└── FAIL_RUNTIME
```

示例：

```text
INFO
    券商均价与本地均价因费用算法不同

WARNING
    冻结数量轻微延迟

BLOCK_INSTRUMENT
    某 Instrument 总持仓不一致

BLOCK_ACCOUNT
    多个资产或账户可用量大范围冲突

FAIL_RUNTIME
    账户身份错误、快照损坏、关键状态无法解析
```

---

# 34. Unallocated Position

定义：

```text
OnlyUnallocatedPosition
```

用于：

* 人工交易；
* 外部系统交易；
* 启动恢复无法归因仓位；
* 本地 Ledger 缺失；
* 对账差异；
* 券商回报缺失 Cluster 信息。

字段至少：

```text
runtime_id
account_id
instrument_id
position_side
total_quantity
settled_quantity
unsettled_quantity
reason
source
created_at
updated_at
version
metadata
```

普通 Cluster 不得操作 Unallocated Position。

只有以下权限可处理：

```text
ACCOUNT_LEVEL_TRADING
RISK_LIQUIDATION
MANUAL_RECONCILIATION
```

第一版只定义内部管理接口，不暴露给策略。

---

# 35. Settlement Service

定义：

```text
OnlySettlementService
OnlySettlementRule
OnlySettlementResult
```

结算不能简单在 UTC 00:00 执行。

必须依赖：

```text
OnlyTradingCalendar
OnlyTradingDay
OnlyVenue
OnlyMarketRule
```

A 股新交易日流程：

```text
UNSETTLED
→ SETTLED
```

建议：

* Runtime 启动恢复时先查询券商；
* 确认 Trading Day；
* 进行结算对账；
* 再迁移 Bucket；
* 券商尚未确认时不乐观增加可卖量。

---

# 36. 启动恢复流程

实盘 Runtime 启动建议：

```text
1. Runtime 进入 RECOVERING
2. 加载本地 Order、Trade、Position、Allocation
3. 连接券商
4. 查询 Open Orders
5. 查询当日 Trades
6. 查询 Broker Position Snapshot
7. 查询 available/frozen/today/yesterday
8. 重放缺失 Trade
9. 对账账户 Position
10. 对账 Position Reservation
11. 对账 Cluster Allocation
12. 无法归因部分进入 Unallocated
13. 更新 Risk State
14. 无阻断冲突后进入 READY
15. Cluster 才能启动
```

本阶段实现数据结构、服务接口和测试 Demo，不接真实 Gateway。

---

# 37. Position Manager

建议接口：

```python
create_position(...)
apply_trade(...)
apply_restriction(...)
remove_restriction(...)
freeze(...)
release(...)
settle(...)
set_reconciling(...)
clear_reconciling(...)

get_snapshot(...)
require_snapshot(...)
list_open(...)
list_by_account(...)
list_by_instrument(...)
snapshot_all(...)
```

第一版核心必须完整实现：

```text
apply_trade
get_snapshot
list_open
settle
reconciliation state
```

冻结和限制接口至少有可测试实现。

---

# 38. Position Allocation Manager

建议接口：

```python
apply_trade(...)
reserve(...)
release(...)
settle(...)
get_snapshot(...)
list_by_cluster(...)
list_by_account(...)
list_by_instrument(...)
calculate_cluster_available(...)
move_to_unallocated(...)
```

必须按 `trade.cluster_id` 更新归因。

如果 Cluster 无法解析：

```text
不得更新任意 Cluster
必须进入 Unallocated
```

---

# 39. Strategy Ledger 扩展边界

本阶段 Position Allocation 至少维护：

```text
quantity
average_open_price
realized_pnl
fees
settled/unsettled
```

可以定义：

```text
OnlyStrategyPositionPnLSnapshot
```

但完整资金账和策略净值序列将在后续：

```text
OnlyStrategyLedgerManager
```

中实现。

不要在 Position 组件中承担完整账户现金和资金流。

---

# 40. ctx.positions 接口

策略统一通过 Context 访问。

必须明确区分：

```text
ctx.positions.account
ctx.positions.cluster
```

例如：

```python
account_position = ctx.positions.account.get(instrument_id)
cluster_position = ctx.positions.cluster.get(instrument_id)
```

不要只提供含义模糊的：

```python
ctx.positions.get(...)
```

策略可见接口：

```text
OnlyAccountPositionQueryView
OnlyClusterPositionQueryView
OnlyPositionContextView
```

策略不能：

* 修改 Position；
* 应用 Trade；
* 结算 Bucket；
* 处理 Reconciliation；
* 修改其他 Cluster Allocation；
* 操作 Unallocated Position。

---

# 41. Risk 集成

Risk 读取：

```text
OnlyAccountPositionRiskView
OnlyClusterPositionRiskView
OnlyPositionReservationView
```

卖出 Pre-Trade Risk 必须同时检查：

```text
Cluster 自己可用归因仓位
账户真实有效可用仓位
```

普通策略：

```text
requested_sell_quantity
<= cluster_effective_available
<= account_effective_available
```

PositionManager 不负责 Risk 决策，但必须保护底层不变量。

---

# 42. Position Event

状态成功变化后可以发布：

```text
OnlyPositionOpenedEvent
OnlyPositionIncreasedEvent
OnlyPositionReducedEvent
OnlyPositionClosedEvent
OnlyPositionSettledEvent
OnlyPositionRestrictedEvent
OnlyPositionRestrictionRemovedEvent
OnlyPositionFrozenEvent
OnlyPositionReleasedEvent
OnlyPositionReconciliationStartedEvent
OnlyPositionReconciledEvent
OnlyPositionConflictDetectedEvent

OnlyPositionAllocationCreatedEvent
OnlyPositionAllocationIncreasedEvent
OnlyPositionAllocationReducedEvent
OnlyPositionAllocationClosedEvent
OnlyUnallocatedPositionCreatedEvent
```

正确顺序：

```text
函数调用
→ 修改 Position
→ 修改索引和版本
→ 生成 MutationResult
→ 发布 Event
```

EventBus 不负责修改 Position。

---

# 43. 幂等

PositionManager 和 AllocationManager 必须按：

```text
trade_id
venue_trade_id
execution_id
```

去重。

重复 Trade：

* quantity 不变化；
* settled/unsettled 不变化；
* realized_pnl 不变化；
* version 不增加；
* 不生成 Event。

Position Reservation 重复创建和释放也必须幂等。

---

# 44. 乱序 Trade

第一版采用严格模式：

```text
同账户、同 Instrument、同 PositionSide
必须按稳定顺序应用 Trade
```

排序依据优先级：

```text
external_sequence
→ ts_event
→ stable_trade_id
```

发现旧 Trade 时返回：

```text
STALE
RECONCILIATION_REQUIRED
```

第一版不自动重算整个历史 Position。

回测输入必须始终有序。

实盘迟到数据进入 Reconciliation 流程。

---

# 45. Repository 抽象

定义：

```text
OnlyPositionRepository
OnlyPositionAllocationRepository
```

第一版提供：

```text
OnlyInMemoryPositionRepository
OnlyInMemoryPositionAllocationRepository
```

不实现具体数据库。

Repository 只持久化 Snapshot 或稳定 DTO，不暴露可变实体。

---

# 46. 序列化

以下对象必须无损序列化：

```text
OnlyPositionSnapshot
OnlyPositionAllocationSnapshot
OnlyPositionTrade
OnlyPositionMutationResult DTO
OnlyPositionReservation
OnlyPositionRestriction
OnlyBrokerPositionSnapshot
OnlyPositionDifference
OnlyPositionReconciliationResult
OnlyUnallocatedPosition
```

必须保持：

* Decimal；
* Price；
* Quantity；
* Money；
* Currency；
* UTC 时间；
* Trading Day；
* Enum；
* ID 类型；
* Bucket；
* Restriction；
* version；
* quality_flags。

禁止将 Decimal 转为 float。

---

# 47. 并发策略

第一版明确：

```text
每个 Runtime 使用单写入者串行修改 Position 状态。
```

未来 Gateway 回调流程：

```text
SDK Callback Thread
→ Gateway 标准化
→ Runtime Inbound Queue
→ Runtime 单写入线程
→ ExecutionProcessor
→ PositionManager
```

禁止 SDK 回调线程直接修改 PositionManager。

---

# 48. 推荐目录

```text
src/onlyalpha/position/
├── __init__.py
├── identifiers.py
├── enums.py
├── keys.py
├── entities.py
├── allocations.py
├── buckets.py
├── restrictions.py
├── reservations.py
├── trades.py
├── pnl.py
├── valuation.py
├── snapshots.py
├── results.py
├── manager.py
├── allocation_manager.py
├── queries.py
├── views.py
├── settlement.py
├── reconciliation.py
├── broker_models.py
├── authority.py
├── repositories.py
├── events.py
├── publisher.py
├── ports.py
└── exceptions.py
```

根据当前工程结构调整，但职责不得混合。

---

# 49. 最小 Demo

创建：

```text
examples/position_demo/
├── README.md
├── account_position_demo.py
├── multi_cluster_allocation_demo.py
├── t1_settlement_demo.py
├── position_reservation_demo.py
├── broker_reconciliation_demo.py
├── unallocated_position_demo.py
└── deterministic_replay_demo.py
```

## 49.1 账户仓位

```text
Cluster A 买入 100 @ 10
Cluster B 买入 200 @ 12
```

期望：

```text
Account Position:
    quantity = 300
    average = 11.333...

A Allocation:
    quantity = 100
    average = 10

B Allocation:
    quantity = 200
    average = 12
```

## 49.2 策略卖出

A 卖出 40：

```text
Account quantity 减少 40
A Allocation 减少 40
B Allocation 不变化
```

A 的 realized PnL 只使用 A 的成本。

## 49.3 T+1

昨日 1000，当日买入 500：

```text
settled = 1000
unsettled = 500
available = 1000
```

A 当日买入部分不能卖出。

## 49.4 Reservation

账户可卖 1000：

```text
A 预占卖出 700
B 再请求卖出 700
```

B 必须看到剩余只有 300。

## 49.5 Broker Conflict

本地 total=1000，券商 total=800：

```text
Position → RECONCILING
Severity → BLOCK_INSTRUMENT
禁止相关 Instrument 新交易
生成 Difference
```

## 49.6 Unallocated

券商总持仓 1000，本地 Cluster 归因 700：

```text
Unallocated = 300
```

不得自动分给 A 或 B。

---

# 50. 必须新增的测试

建议：

```text
tests/position/
├── test_position_key.py
├── test_position_creation.py
├── test_position_open_increase_reduce_close.py
├── test_position_average_cost.py
├── test_position_realized_pnl.py
├── test_position_over_sell.py
├── test_position_new_lifecycle_after_flat.py
├── test_position_snapshot_immutability.py
├── test_position_manager_indexes.py
├── test_position_duplicate_trade.py
├── test_position_stale_trade.py
├── test_position_runtime_isolation.py

├── test_position_allocation_create.py
├── test_position_allocation_multi_cluster.py
├── test_position_allocation_realized_pnl.py
├── test_cluster_cannot_sell_other_allocation.py
├── test_unallocated_position.py
├── test_account_allocation_invariant.py

├── test_t1_buy_unsettled.py
├── test_t1_sell_settled_only.py
├── test_t1_settlement_transition.py
├── test_tradable_quantity.py
├── test_available_quantity.py
├── test_position_restriction.py
├── test_suspended_instrument.py

├── test_position_reservation_create.py
├── test_position_reservation_release.py
├── test_position_reservation_idempotency.py
├── test_position_reservation_stage.py
├── test_multi_cluster_sell_reservation.py
├── test_no_double_freeze_with_broker.py

├── test_broker_position_snapshot.py
├── test_position_reconciliation_equal.py
├── test_total_quantity_conflict.py
├── test_available_quantity_conflict.py
├── test_frozen_quantity_conflict.py
├── test_average_price_conflict.py
├── test_reconciliation_block_instrument.py
├── test_reconciliation_unallocated.py
├── test_position_authority_policy.py

├── test_position_serialization.py
├── test_position_events_after_mutation.py
├── test_ctx_account_positions_read_only.py
├── test_ctx_cluster_positions_read_only.py
└── test_position_determinism.py
```

---

# 51. 核心验收场景

## 51.1 双层数量一致

```text
Account quantity
=
sum(Cluster Allocation)
+
Unallocated
```

任何不一致必须显式进入 Reconciliation。

## 51.2 策略收益独立

A、B 不同买入价格时：

* 账户平均价可以合并；
* A、B 各自成本不得被合并；
* 各自 realized/unrealized PnL 独立计算。

## 51.3 T+1

当日买入：

* 增加 total；
* 增加 unsettled；
* 不增加当日可卖 settled。

## 51.4 Cluster 权限

普通 Cluster 不能卖出其他 Cluster 的 Allocation。

## 51.5 Reservation

连续策略卖出请求必须考虑最新 Position Reservation。

## 51.6 Broker Conflict

关键冲突不能静默覆盖。

## 51.7 Unallocated

无法归因持仓不得自动分配给策略。

## 51.8 Determinism

相同初始状态和 Trade 序列运行 100 次：

* PositionId；
* Allocation；
* Quantity；
* Average Price；
* PnL；
* Version；
* Event 顺序；
* Reconciliation 结果；

完全一致。

---

# 52. 文档输出

创建或更新：

```text
docs/position.md
docs/order.md
docs/risk.md
docs/runtime_context.md
docs/event.md
docs/architecture.md
docs/testing.md
docs/architecture_principles.md
```

`docs/position.md` 至少包含：

1. Position 组件边界；
2. 双层持仓模型；
3. 账户仓位；
4. Cluster Allocation；
5. Unallocated Position；
6. Position Mode；
7. Position Side；
8. Position 生命周期；
9. Trade 更新；
10. Cost Basis；
11. Realized/Unrealized PnL；
12. T+1；
13. Settlement Bucket；
14. Availability；
15. Restriction；
16. Reservation；
17. Broker Snapshot；
18. Authority Policy；
19. Reconciliation；
20. Conflict Severity；
21. Context Query；
22. Risk 集成；
23. Event；
24. 序列化；
25. 并发；
26. Demo；
27. 已知限制。

---

# 53. ADR

创建：

```text
docs/adr/0013-position-allocation-settlement-and-reconciliation.md
```

至少记录：

## 背景

多个 Cluster 共用同一个券商账户时，券商只提供账户总仓位，无法直接表达策略归因、策略收益和 T+1 可卖数量。

## 决策

* 每个 Runtime 一个账户 Position 状态域；
* 同时维护账户真实 Position 和 Cluster Allocation；
* 无法归因仓位进入 Unallocated；
* 每笔 Order/Trade 保留 Cluster 来源；
* 普通 Cluster 只能操作自己的 Allocation；
* Position 使用 Bucket 表达结算状态；
* A 股当日买入进入 Unsettled；
* Available Quantity 是派生值；
* 本地 Reservation 与券商冻结分开；
* Broker Snapshot 不直接静默覆盖本地 Position；
* Reconciliation 生成 Difference 和 Severity；
* 关键冲突期间阻止交易；
* 每次完整开平仓使用新的 PositionId；
* 第一版实现 Average Cost 和 Linear PnL；
* Position 状态修改使用函数调用，事实通知使用 Event。

## 拒绝方案

* 只维护账户总仓位；
* 每个 Cluster 独立维护一套与券商无关的真实仓位；
* 从账户总仓位事后按比例分配收益；
* T+1 只使用一个 available_quantity；
* 券商快照直接覆盖本地历史；
* 无法归因仓位自动均分给策略；
* Cluster 可以默认卖出其他策略持仓；
* 公共 EventBus Handler 独立修改 Position。

---

# 54. Architecture Principles 新增规则

加入：

```text
Rule: 每个 Runtime 拥有独立账户 Position 状态域。

Rule: 账户真实 Position 与 Cluster Allocation 必须分离。

Rule: 策略收益必须基于自身 Trade 和 Allocation 计算。

Rule: 无法归因的持仓必须进入 Unallocated。

Rule: 普通 Cluster 只能操作自己的 Allocation。

Rule: Position 修改使用函数调用，Event 只通知已发生事实。

Rule: PositionManager 不直接依赖券商 SDK。

Rule: Position 使用 Settlement Bucket 表达 T+1 和今昨仓。

Rule: Available Quantity 是派生值，不是无条件可信的持久化字段。

Rule: 本地 Reservation 与券商冻结必须区分。

Rule: Broker Snapshot 不得静默覆盖本地 Position 历史。

Rule: 关键持仓冲突必须阻止相关交易。

Rule: 重复 Trade 必须幂等。

Rule: 乱序 Trade 必须进入严格处理或 Reconciliation。

Rule: Cluster 只能通过 ctx.positions 读取不可变 Snapshot。

Rule: 每次完整开平仓周期使用新的 PositionId。
```

---

# 55. 实现顺序

严格按以下顺序：

1. 扫描当前 Position 和收益实现；
2. 创建差距分析；
3. 定义 Position ID、Key、Mode、Side、Status；
4. 定义 Bucket、Availability 和 Restriction；
5. 实现 Position Snapshot；
6. 实现 PositionTrade；
7. 定义 PnLModel；
8. 实现 Linear Average Cost；
9. 实现账户 OnlyPosition 实体；
10. 完成增仓、减仓、平仓和超卖测试；
11. 实现 PositionManager；
12. 完成索引和生命周期测试；
13. 实现 PositionAllocation；
14. 实现 PositionAllocationManager；
15. 完成多 Cluster 归因和收益测试；
16. 实现 Unallocated Position；
17. 实现 T+1 Bucket；
18. 实现 SettlementService；
19. 完成 T+1 测试；
20. 实现 PositionReservation；
21. 完成多 Cluster 卖出预占测试；
22. 定义 BrokerPositionSnapshot；
23. 定义 AuthorityPolicy；
24. 实现 ReconciliationService；
25. 完成冲突和阻断测试；
26. 实现 Context Query View；
27. 接入 Risk 只读 Position Port；
28. 实现 Position Event 和 Publisher Port；
29. 完成序列化；
30. 创建 Demo；
31. 更新文档；
32. 创建 ADR；
33. 运行全部测试；
34. 输出验收报告。

---

# 56. 验收标准

完成后必须满足：

* 每个 Runtime 拥有独立 PositionManager；
* 每个 Runtime 拥有独立 AllocationManager；
* 账户 Position 与 Cluster Allocation 分离；
* Cluster Allocation 总和与账户仓位可对账；
* 无法归因仓位进入 Unallocated；
* 普通 Cluster 不能操作其他 Cluster Allocation；
* Account 和 Cluster Position 查询语义明确；
* Position 内部受控可变；
* 外部只获得 immutable Snapshot；
* PositionId 生命周期明确；
* Average Cost 正确；
* Realized PnL 正确；
* 重复 Trade 幂等；
* Over-sell 被拒绝；
* T+1 当日买入不可卖；
* Settled/Unsettled 正确；
* Available Quantity 正确；
* Reservation 不重复冻结；
* Broker Snapshot 不直接覆盖本地状态；
* 总仓位冲突进入 Reconciliation；
* 冲突期间采用保守可用数量；
* 关键冲突阻止交易；
* 无法归因数量不自动分配；
* 策略收益不使用账户合并成本；
* 不同 Runtime 状态完全隔离；
* Context 不暴露 Manager；
* Event 在状态成功变化后发布；
* 回测输入确定性；
* 文档、测试、Demo、ADR 完整。

---

# 57. 一票否决项

存在以下任一项，不得标记完成：

* Engine 使用一个全局可变 PositionManager；
* 每个 Cluster 单独维护账户真实仓位；
* 账户真实 Position 和策略归因使用同一个对象且无法区分；
* 从账户总仓位按比例推算 Cluster 收益；
* Cluster 可以卖出其他 Cluster Allocation；
* 无法归因仓位被自动分配给策略；
* T+1 只使用单个 available_quantity 且无结算 Bucket；
* 当日买入立即进入可卖数量；
* 重复 Trade 重复修改仓位；
* Position 使用裸 float；
* Strategy PnL 使用账户合并平均价；
* Broker Snapshot 静默覆盖本地 Position；
* Position 冲突时仍允许无限制下单；
* 本地 Reservation 和券商冻结重复扣减；
* SDK 回调线程直接修改 PositionManager；
* EventBus Handler 承担 Position 状态机；
* Query 返回可变 Position；
* Runtime 之间共享可变仓位；
* 相同输入产生不同 Position 或 PnL；
* 未实现 AccountManager 时伪造无限资金或虚假账户权益。

---

# 58. 最终交付报告

完成后必须输出：

```text
新增文件
修改文件
Position 组件边界
双层持仓模型
账户 Position 设计
Cluster Allocation 设计
Unallocated Position 设计
Position Key 和 Mode
Position 生命周期
Trade 更新规则
Average Cost 实现
Realized PnL 实现
Valuation 设计
T+1 Bucket 设计
Available Quantity 计算
Restriction 设计
Reservation 生命周期
Broker Position Snapshot
Authority Policy
Reconciliation 规则
冲突 Severity
ctx.positions API
Risk Position Port
Position Event
测试通过数
测试失败数
测试跳过数
确定性测试结果
Demo 运行结果
已知限制
一票否决项
是否建议进入 StrategyLedgerManager
是否建议进入 AccountManager
是否建议进入 ExecutionProcessor
```

最终结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现：

```text
Position Domain
Position Manager
Position Allocation
Unallocated Position
T+1 Bucket
Settlement
Position Reservation
PnL Model
Position Snapshot
Position Query
Broker Snapshot Abstraction
Position Reconciliation
Position Event
Risk Position Port
Context Integration
测试
Demo
文档
ADR
```

不要在本任务中实现：

* 完整 AccountManager；
* 完整 Strategy Capital Ledger；
* 真实券商 SDK；
* 完整 ExecutionProcessor；
* Matching Engine；
* 自动强平；
* 内部策略订单净额化；
* 跨策略自动转仓；
* Web；
* 数据库具体实现；
* 真实交易。
