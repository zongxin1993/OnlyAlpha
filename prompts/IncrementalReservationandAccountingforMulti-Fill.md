# OnlyAlpha PR4.3.2：Incremental Reservation and Accounting for Multi-Fill

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、Roadmap 和持久化实现，完成：

```text
PR4.3.2
Incremental Reservation and Accounting for Multi-Fill
```

中文名称：

```text
PR4.3.2
多 Fill 的增量 Reservation 与 Accounting
```

开始工作前必须重新读取仓库当前状态，不得只根据本提示词直接修改代码。

当前预期基线提交为：

```text
a93416d8ea66fd978b756e90118400df4931346b
Feat: Partial-Fill Order Authority 与 Durable Fill Identity Foundation
```

如果实际 `master` 已更新，以实际源码为准，并在预实施审计中记录差异。

PR4.3.1 已完成：

```text
Order Partial-Fill Authority
Durable Fill Identity
Fill Payload Fingerprint
Per-Order Fill Index
Multi-Fill Committed Fact 基础
Memory / SQLite Durable Query
Legacy Whole-Fill Compatibility
```

当前完整产品 Partial Fill 路径仍通过：

```text
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

保持 Fail Closed。

PR4.3.2 的任务是在不修改 Transaction、Recovery 和 Event Gate 基础架构的前提下，完成 Partial/Multi-Fill 所需的增量资金、费用、持仓成本、风险和 Reservation 记账，并最终安全删除该产品 Gate。

---

# 二、当前问题

当前 Order Authority 已能正确处理：

```text
Fill 1
→ PARTIALLY_FILLED

Fill 2
→ PARTIALLY_FILLED

Fill N
→ FILLED
```

但以下组件仍然假设每次 Fill 都是唯一且最终的 Whole Fill：

```text
Account Cash Reservation
Strategy Cash Reservation
Account Frozen Cash
Strategy Ledger Cash Reserved
Risk Active Order Count
部分 Risk Reserved Authority
Position / Allocation 平均成本
Fee Minimum / Maximum
```

主要错误现象包括：

```text
第一次 Partial Fill 后
未成交部分 Reservation 被全部释放
```

```text
第一次 Partial Fill 后
Risk Active Order Count 被提前减一
```

```text
每个 Fill 都重复记录 ORDER_RESERVATION_RELEASE
```

```text
每个 Fill 都可能重复收取最低佣金
```

```text
Position / Allocation 使用已量化平均价反推历史累计成本
导致多 Fill 舍入误差累积
```

本任务必须彻底消除这些 Whole-Fill 假设。

---

# 三、核心目标

PR4.3.2 必须建立：

```text
Order Terminal Decision
+
Position / Allocation Exact Cost Authority
+
Order-Level Fee Accrual
+
Incremental Cash Reservation Consumption
+
Incremental Account Accounting
+
Incremental Strategy Ledger Accounting
+
Incremental Risk Accounting
```

最终必须支持：

```text
一个 Order
→ 多个独立 Fill
→ 多个不可变 Durable Transaction
→ 每个 Fill 独立 Projection
→ 每个中间状态均满足业务不变量
```

每个 Fill 必须独立、增量地更新：

```text
Order
Position
Allocation
Settlement
Order Fee Accrual
Fee
Account
Strategy Ledger
Account Cash Reservation
Strategy Cash Reservation
Risk Reservation
Risk
Valuation
```

---

# 四、正式产品范围

本任务严格限定为：

```text
GENERIC_T0_CASH
CASH Account
LIMIT
BUY
OPEN
LONG
NETTING
No Margin
Single Currency
One BrokerTradeUpdate per Fill
```

PR4.3.2 不实现：

```text
SELL
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
MARKET Order
IOC
FOK
GTD 特殊终止行为
订单改单
Position Reservation 消费
Futures / Margin
订单簿级撮合
真实流动性分配
Virtual Broker 自动 Partial Fill Schedule
完整 Multi-Fill Crash/Restart Scenario
Paper / Live Multi-Fill
```

Virtual Broker 自动分批成交和完整 Multi-Fill Recovery 留到 PR4.3.3。

---

# 五、不可修改的基础架构

本任务原则上不得修改：

```text
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
src/onlyalpha/runtime/recovery/orchestrator.py
```

必须继续保持：

```text
一个 Fill
=
一个不可变 Prepared Transaction
=
一个独立 Committed Transaction
```

不得将多个 Fill 合并为一个可变 Transaction。

不得修改已经 Commit 的 Transaction。

不得改变：

```text
Transaction ID
Fill Identity
Fill Fingerprint
Fill Index
Projection Ready
Durable Outbox
Recovery Event Gate
```

的既有语义。

---

# 六、开始前必须审计的文件

至少重新读取：

```text
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/planner.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/projection_applier.py
src/onlyalpha/execution/authority_state.py

src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_reservations.py
src/onlyalpha/execution/reducers/trade_accounting.py

src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/risk/
src/onlyalpha/fee/
src/onlyalpha/position/
src/onlyalpha/settlement/

src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/persistence/
```

重点搜索：

```bash
rg "PARTIAL_FILL_ACCOUNTING_NOT_READY"
rg "PARTIALLY_CONSUMED"
rg "remaining_amount"
rg "consumed_amount"
rg "RELEASED"
rg "ORDER_RESERVATION_RELEASE"

rg "active_order_count"
rg "cluster_active_order_count"
rg "reserved_notional"
rg "reserved_quantity"
rg "remaining_order_notional"

rg "average_open_price"
rg "_average_open_price"
rg "position_cost"

rg "minimum"
rg "maximum"
rg "OnlyFeeRateRule"
rg "OnlyFeeInstruction"
rg "OnlyFeeExecutionState"
rg "OnlyFeeManager"

rg "frozen_cash"
rg "cash_reserved"
rg "cash_available"
rg "cash_balance"

rg "OnlyExecutionProjectionComponent"
rg "OnlyExecutionProjection"
rg "projection_sequence"
rg "projection_applier"

rg "capture_checkpoint"
rg "restore_checkpoint"
rg "only_encode"
rg "only_decode"
```

---

# 七、预实施审计

新增：

```text
docs/reports/pr4_3_2_incremental_accounting_pre_implementation_audit.md
```

审计必须回答：

1. Account Cash Reservation 当前如何处理一次 Fill；
2. Strategy Cash Reservation 当前如何处理一次 Fill；
3. Reservation 当前是否已经支持 `PARTIALLY_CONSUMED`；
4. Account Reducer 当前如何更新 `frozen_cash`；
5. Ledger Reducer 当前如何更新 `cash_reserved`；
6. 为什么当前每次 Fill 都会释放全部 Reservation；
7. Risk Reservation 当前是否支持分段数量消费；
8. Risk Snapshot 当前何时减少 Active Order Count；
9. `remaining_order_notional` 的正式业务含义是什么；
10. Position 和 Allocation 当前如何计算平均开仓价；
11. 是否存在累计舍入风险；
12. Ledger 当前如何计算 `position_cost`；
13. 当前 Fee Rule 的 `minimum` 和 `maximum` 作用域是什么；
14. 当前 FeeManager 为什么不能成为订单级累计 Fee Authority；
15. 当前 Fee Instruction 的作用域是什么；
16. Broker Reported Fee 当前如何处理；
17. 当前 Projection Component 是否需要新增订单级 Fee Accrual；
18. 新 Authority 是否需要持久化表；
19. Checkpoint 是否需要 Schema Migration；
20. Legacy Whole-Fill 状态如何兼容；
21. 当前 Product Partial Fill Gate 位于何处；
22. 删除 Gate 前必须完成哪些条件；
23. 本任务需要修改哪些生产文件；
24. 本任务不应修改哪些文件。

完成审计前不得删除产品 Gate。

---

# 八、核心设计原则

## 8.1 Order Reducer 是终态唯一权威

PR4.3.1 已经计算：

```text
terminal_fill
filled_quantity_after
remaining_quantity_after
```

后续所有 Accounting Reducer 必须使用同一份 Order Reduction 结果。

禁止以下组件自行判断 Fill 是否为最终 Fill：

```text
Fee
Account Reservation
Strategy Reservation
Account
Ledger
Risk Reservation
Risk
```

建议扩展：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderTradeReduction:
    ...
    terminal_fill: bool
```

或者定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyFillLifecycleDecision:
    fill_index: int
    terminal_fill: bool
    filled_quantity_after: OnlyQuantity
    remaining_quantity_after: OnlyQuantity
```

但不要重复保存相互可推导且可能不一致的终态权威。

---

## 8.2 所有 Reducer 保持纯函数

任何 Reducer 均不得：

```text
访问 Manager
访问 Store
访问 EventBus
访问 Runtime
写 Outbox
修改全局状态
```

所有 Before Authority 必须在 Planning Context Builder 中提前捕获。

所有 After Authority 和 Delta 必须由 Planner 中的纯 Reducer 生成。

---

## 8.3 显式 Delta 优于从 Before/After 反推

Account 和 Ledger 必须接收 Reservation Reducer 生成的显式：

```text
consumed_delta
released_delta
```

Risk 必须接收：

```text
consumed_quantity_delta
consumed_notional_delta
terminal_fill
```

不得让 Account、Ledger、Risk 再次独立推导同一 Delta。

---

## 8.4 不引入巨型 Accounting 上帝对象

不要将所有业务变化放入一个包含几十个字段的：

```text
OnlyIncrementalFillAccountingAuthority
```

建议维持清晰的领域 Reduction：

```text
Order Reduction
Position Reduction
Allocation Reduction
Order Fee Accrual Reduction
Fee Reduction
Account Reservation Reduction
Strategy Reservation Reduction
Risk Reservation Reduction
Account Reduction
Ledger Reduction
Risk Reduction
Valuation Reduction
```

---

# 九、Position 与 Allocation 精确成本

## 9.1 新增精确 Authority

在 Position 和 Allocation 的 Domain Snapshot 与 Execution State 中增加：

```python
cumulative_open_price_quantity: Decimal
```

定义：

```text
Σ(fill_price × fill_quantity)
```

不得使用已经量化的：

```text
average_open_price × total_quantity
```

作为新状态的精确累计来源。

---

## 9.2 更新公式

```python
new_cumulative_open_price_quantity = (
    before_cumulative_open_price_quantity
    + trade.price.value * trade.quantity.value
)
```

```python
raw_average = (
    new_cumulative_open_price_quantity
    / total_quantity_after.value
)
```

最后一步才按正式 Price Precision 构造：

```python
OnlyPrice(raw_average, resolved_precision)
```

---

## 9.3 Position Cost

Strategy Ledger 的：

```text
position_cost
```

必须基于：

```text
cumulative_open_price_quantity
× contract_multiplier
```

计算。

只在转换为 `OnlyMoney` 时按 Currency Precision 量化。

不得使用量化后的 `average_open_price` 反推成本。

---

## 9.4 Legacy 兼容

旧 Position/Allocation 没有精确累计字段时：

```text
cumulative_open_price_quantity
=
average_open_price × total_quantity
```

因为旧正式产品只支持 Whole Fill，该推导在兼容范围内成立。

要求：

* 兼容逻辑放在 Deserialize / Snapshot Adapter；
* 不修改历史持久记录；
* 不增加生产数据库迁移；
* 新状态必须持久保存精确字段。

---

# 十、Fee Calculation Scope

## 10.1 新增枚举

建议增加：

```python
class OnlyFeeCalculationScope(StrEnum):
    FILL = "FILL"
    ORDER_CUMULATIVE = "ORDER_CUMULATIVE"
```

在 `OnlyFeeRateRule` 中增加：

```python
calculation_scope: OnlyFeeCalculationScope = OnlyFeeCalculationScope.FILL
```

不得仅通过：

```text
minimum > 0
```

自动推断订单累计作用域。

---

## 10.2 FILL Scope

适用于明确逐 Fill 收取的费用。

计算：

```text
incremental_component_fee
=
current_fill_rule_result
```

例如：

* 逐成交交易费；
* Broker 明确上报的本次成交费；
* 明确按 Fill 执行的固定费。

---

## 10.3 ORDER_CUMULATIVE Scope

先计算订单累计目标费用：

```text
target_cumulative_fee_after
=
rule.calculate(
    cumulative_notional_after,
    cumulative_quantity_after
)
```

本次应收增量：

```text
incremental_fee
=
target_cumulative_fee_after
-
cumulative_charged_fee_before
```

要求：

```text
incremental_fee >= 0
```

若计算结果为负，必须 Fail Closed，除非未来通过正式 Fee Adjustment Transaction 处理。

---

# 十一、订单级 Fee Accrual Authority

## 11.1 新增 State

建议定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualExecutionState:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    currency: OnlyCurrency

    cumulative_fill_quantity: OnlyQuantity
    cumulative_fill_notional: OnlyMoney
    cumulative_charged_fee: OnlyMoney

    components: tuple[OnlyOrderFeeComponentAccrual, ...]

    fill_count: int
    last_trade_id: OnlyTradeId
    updated_at: OnlyTimestamp
    version: int
```

组件：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeComponentAccrual:
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    source_id: str
    schedule_id: str | None
    schedule_version: str | None
    calculation_scope: OnlyFeeCalculationScope

    cumulative_raw_amount: OnlyMoney
    cumulative_target_amount: OnlyMoney
    cumulative_charged_amount: OnlyMoney
```

---

## 11.2 不变量

必须保证：

```text
fill_count >= 1
```

```text
cumulative_fill_quantity > 0
```

```text
cumulative_fill_notional >= 0
```

```text
cumulative_charged_fee
=
所有 component.cumulative_charged_amount 之和
```

```text
所有金额 Currency 一致
```

```text
每个 Component Key 唯一
```

Component Key 建议包含：

```text
fee_type
authority
source_id
schedule_id
schedule_version
calculation_scope
```

---

## 11.3 新增 Reduction

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualTradeReduction:
    before: OnlyOrderFeeAccrualExecutionState | None
    after: OnlyOrderFeeAccrualExecutionState

    incremental_breakdown: OnlyFeeBreakdown
    incremental_total: OnlyMoney

    projection: OnlyOrderFeeAccrualExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]
```

---

## 11.4 新增 Projection Component

新增：

```text
ORDER_FEE_ACCRUAL
```

配套实现：

```text
OnlyOrderFeeAccrualExecutionState
OnlyOrderFeeAccrualExecutionProjection
OnlyOrderFeeAccrualManager
Projection Applier
Codec
Checkpoint Adapter
Restore Adapter
Authority Validator
```

不得复用现有 `FEE` Component。

现有 `FEE` 的 Entity Scope 是单笔 Fee Instruction；订单级 Fee Accrual 的 Entity Scope 是订单。

---

## 11.5 FeeManager 职责保持不变

现有 FeeManager 继续只负责：

```text
接收已经确定的 Fee Instruction
追加不可变 Fee Facts
幂等处理 Instruction Key
```

FeeManager 不得：

```text
解析 Market Profile
计算最低佣金
查询 Order
累积订单费用
```

订单累计费用必须由独立 Order Fee Accrual Reducer 和 Manager 负责。

---

# 十二、Broker Reported Fee 语义

必须明确并测试不同 Broker Reporting Mode。

## 12.1 Broker 明确上报本次 Fill Fee

如果 Broker Reported Fee 表示：

```text
current fill incremental fee
```

则该组件使用：

```text
FILL
```

作用域，直接成为本次增量费用 Authority。

## 12.2 Broker 上报累计订单 Fee

当前模型若无法明确表示累计订单 Fee，不得猜测。

应：

```text
Fail Closed
或
标记为 Deferred Reconciliation
```

不要把累计 Fee 错当成本次 Fill Fee。

## 12.3 Fee Adjustment

PR4.3.2 不要求完成后续 Statement Adjustment，但新 Accrual State 不得阻止未来：

```text
ADJUSTED
REVERSED
```

Fee Transaction 扩展。

---

# 十三、Account Cash Reservation 增量状态机

现有状态可复用：

```text
ACTIVE
PARTIALLY_CONSUMED
CONSUMED
RELEASED
```

## 13.1 输入

Reducer 必须接收：

```text
reservation_before
fill_cost
terminal_fill
```

其中：

```text
fill_cost
=
settled_notional
+
incremental_fee
```

---

## 13.2 中间 Fill

条件：

```text
terminal_fill = false
```

计算：

```python
consumed_delta = fill_cost
released_delta = zero_money

consumed_after = consumed_before + consumed_delta
remaining_after = remaining_before - consumed_delta
```

状态：

```text
PARTIALLY_CONSUMED
```

必须满足：

```text
remaining_after > 0
```

否则订单仍未完成但 Reservation 已耗尽，必须返回正式 Planning Error。

事件：

```text
ACCOUNT_CASH_RESERVATION_CONSUMED
```

不得产生：

```text
ACCOUNT_CASH_RESERVATION_RELEASED
```

---

## 13.3 最终 Fill，刚好耗尽

条件：

```text
terminal_fill = true
remaining_before == fill_cost
```

结果：

```text
consumed_delta = fill_cost
released_delta = 0
remaining_after = 0
state = CONSUMED
```

不得产生空 Release Event。

---

## 13.4 最终 Fill，存在剩余

条件：

```text
terminal_fill = true
remaining_before > fill_cost
```

结果：

```python
consumed_delta = fill_cost
released_delta = remaining_before - fill_cost

consumed_after = consumed_before + consumed_delta
remaining_after = zero_money
state = RELEASED
```

事件：

```text
ACCOUNT_CASH_RESERVATION_CONSUMED
ACCOUNT_CASH_RESERVATION_RELEASED
```

---

## 13.5 Reservation 不足

如果：

```text
fill_cost > remaining_before
```

必须返回正式错误：

```text
ACCOUNT_RESERVATION_INSUFFICIENT
```

并保证：

```text
无 Commit
无 Projection
无 Outbox
无 Authority Mutation
```

---

# 十四、Strategy Cash Reservation 增量状态机

采用与 Account Reservation 相同的：

```text
consumed_delta
released_delta
```

和金额逻辑。

## 14.1 中间 Fill

```text
state = PARTIALLY_CONSUMED
stage 保持原 Broker 生命周期 Stage
```

不得切换为：

```text
RELEASE_PENDING
RELEASED
```

## 14.2 最终刚好耗尽

```text
state = CONSUMED
stage 保持现有 Broker Stage
```

## 14.3 最终存在释放

```text
state = RELEASED
stage = RELEASED
```

## 14.4 事件

中间 Fill：

```text
STRATEGY_CASH_RESERVATION_CONSUMED
```

最终存在释放时才产生：

```text
STRATEGY_CASH_RESERVATION_RELEASED
```

---

# 十五、Reservation Reduction 输出

建议扩展 Reduction：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationTradeReduction:
    after: OnlyAccountCashReservationExecutionState
    projection: OnlyAccountCashReservationExecutionProjection
    consumed_delta: OnlyMoney
    released_delta: OnlyMoney
    event_intents: tuple[OnlyExecutionEventIntent, ...]
```

Strategy Reservation 同样增加：

```text
consumed_delta
released_delta
```

Account 和 Ledger 只能使用这些正式 Delta。

---

# 十六、Account 增量 Accounting

Account Reducer 输入建议改为：

```python
def reduce(
    before: OnlyAccountExecutionState,
    trade: OnlyPlannedTrade,
    reservation_reduction: OnlyAccountCashReservationTradeReduction,
    ...
) -> OnlyAccountTradeReduction:
```

计算：

```python
fill_cost = trade.settled_notional + trade.authoritative_fee
```

```python
cash_balance_after = (
    cash_balance_before
    - fill_cost
)
```

```python
frozen_cash_after = (
    frozen_cash_before
    - reservation_reduction.consumed_delta
    - reservation_reduction.released_delta
)
```

```python
available_cash_after = (
    cash_balance_after
    - frozen_cash_after
    - unsettled_cash_after
)
```

必须继续满足 Account Execution State 现有公式。

---

## 16.1 中间 Fill 的预期

由于成交成本来自已冻结资金：

```text
cash_balance 减少 fill_cost
frozen_cash 同时减少 fill_cost
available_cash 通常保持不变
```

若由于货币量化产生差额，必须通过显式规则处理，不能悄悄产生负值或漂移。

---

## 16.2 最终 Fill 的预期

最终存在未使用 Reservation：

```text
frozen_cash 额外减少 released_delta
available_cash 增加 released_delta
```

---

# 十七、Strategy Ledger 增量 Accounting

计算：

```python
cash_balance_after = (
    cash_balance_before
    - fill_cost
)
```

```python
cash_reserved_after = (
    cash_reserved_before
    - strategy_reservation.consumed_delta
    - strategy_reservation.released_delta
)
```

```python
cash_available_after = (
    cash_balance_after
    - cash_reserved_after
)
```

`position_cost` 必须使用 Position/Allocation 的精确累计成本 Authority。

---

## 17.1 Cash Entries

每个 Fill 都记录：

```text
BUY_SETTLEMENT
```

本次增量 Fee 大于零时记录：

```text
FEE
```

只有：

```text
terminal_fill = true
且 released_delta > 0
```

时记录：

```text
ORDER_RESERVATION_RELEASE
```

不得在中间 Fill 中产生 Release Entry。

---

## 17.2 Fee Entries

每个非零增量 Fee Component 必须产生独立 Fee Entry。

Entry 必须绑定：

```text
order_id
trade_id
fill_index
fee_type
schedule_id
schedule_version
```

如果现有 Entry 模型没有 `fill_index`，可以通过 Metadata 增加，或正式扩展字段。

不得将多次 Fill Fee 合并成一个可变 Entry。

---

# 十八、Risk Reservation 增量处理

现有 Risk Reservation 已经保存：

```text
reserved_quantity
consumed_quantity
remaining_quantity

reserved_notional
consumed_notional
remaining_notional
```

本次 Fill：

```python
consumed_quantity_delta = trade.quantity
consumed_notional_delta = trade.gross_notional
```

更新：

```python
consumed_quantity_after = (
    consumed_quantity_before
    + consumed_quantity_delta
)
```

```python
remaining_quantity_after = (
    remaining_quantity_before
    - consumed_quantity_delta
)
```

Notional 同理。

中间 Fill：

```text
state 保持 ACTIVE
```

最终 Fill：

```text
state = CONSUMED
```

不得在中间 Fill 释放 Risk Reservation。

---

# 十九、Risk Snapshot 增量处理

Risk Reducer 必须接收：

```text
risk_reservation_reduction
terminal_fill
```

更新：

```python
reserved_quantity_after = (
    reserved_quantity_before
    - consumed_quantity_delta.value
)
```

```python
reserved_notional_after = (
    reserved_notional_before
    - consumed_notional_delta
)
```

## 19.1 中间 Fill

```text
active_order_count 不变
cluster_active_order_count 不变
```

## 19.2 最终 Fill

```text
active_order_count -= 1
cluster_active_order_count -= 1
```

一个订单无论有多少 Fill，Active Count 只能减少一次。

---

# 二十、冻结 `remaining_order_notional` 语义

预实施审计必须明确 `remaining_order_notional` 的正式含义。

推荐定义为：

```text
当前 Cluster 所有活动订单剩余未成交部分的名义金额
```

如果采用该定义，每次 Fill：

```python
remaining_order_notional_after = (
    remaining_order_notional_before
    - current_fill_gross_notional
)
```

最终不得小于零。

如果当前真实实现和其他模块使用了不同语义，必须：

1. 在 ADR 中明确真实语义；
2. 编写独立不变量测试；
3. 不得无依据改变公开语义。

---

# 二十一、Planner Context 扩展

Planning Context 建议增加：

```text
order_fee_accrual_before

position_before.cumulative_open_price_quantity
allocation_before.cumulative_open_price_quantity

account_cash_reservation_before
strategy_cash_reservation_before
risk_reservation_before
risk_before
```

必须在 Context Builder 中一次性捕获所有 Before Authority。

Planner 执行期间不得重新读取 Manager。

---

# 二十二、纯 Reduction 顺序

推荐：

```text
1. Order Reduction
2. Position Reduction
3. Allocation Reduction
4. Settlement Reduction
5. Order Fee Accrual Reduction
6. Fee Reduction
7. Account Cash Reservation Reduction
8. Strategy Cash Reservation Reduction
9. Risk Reservation Reduction
10. Account Reduction
11. Strategy Ledger Reduction
12. Risk Reduction
13. Valuation Reduction
```

理由：

* Order 提供唯一 `terminal_fill`；
* Fee Accrual 决定本次真实增量 Fee；
* Reservation 使用增量 Fee 计算 `fill_cost`；
* Account/Ledger 使用 Reservation Delta；
* Risk 使用 Risk Reservation Delta。

---

# 二十三、Projection 顺序

建议正式 Projection 顺序：

```text
1. ORDER
2. POSITION
3. ALLOCATION
4. SETTLEMENT
5. ORDER_FEE_ACCRUAL
6. FEE
7. ACCOUNT
8. STRATEGY_LEDGER
9. ACCOUNT_CASH_RESERVATION
10. STRATEGY_CASH_RESERVATION
11. RISK_RESERVATION
12. RISK
13. VALUATION
```

如果根据当前 Projection Applier 约束选择 Reservation 在 Account 前，也可以采用：

```text
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
ACCOUNT
STRATEGY_LEDGER
```

但必须确保：

* Planner 使用的是冻结 Before State；
* Reducer 不读取已经 Projection 后的 Manager；
* Projection Preconditions 对全部 Authority 生效；
* 整个 Transaction 仍是一个不可变整体。

最终顺序必须写入 ADR 和 Architecture Test。

---

# 二十四、Projection Applier 与 Manager

新增：

```text
OnlyOrderFeeAccrualManager
```

Manager 职责：

```text
get authority by order
apply projection
restore projection
checkpoint / restore
```

Manager 不得：

```text
解析 Fee Schedule
计算 Fee
修改 Fee Instruction
访问 Order Manager
```

Projection Applier 增加：

```text
ORDER_FEE_ACCRUAL
```

分支。

Recovery Replay 必须能够根据 Projection Before/After 恢复该 Manager。

---

# 二十五、Checkpoint 与持久化

## 25.1 Transaction Codec

所有新增字段必须进入：

```text
Prepared Transaction Codec
Committed Transaction Codec
Projection Codec
Execution State Codec
```

并进行 Round-Trip 测试。

## 25.2 Runtime Checkpoint

新增 Order Fee Accrual Manager 后，必须作为正式 Checkpoint Participant 注册。

要求：

```text
schema version 明确
capture deterministic
restore deterministic
participant fingerprint 稳定
```

## 25.3 Legacy 兼容

旧 Checkpoint 不包含 Order Fee Accrual Manager 时：

* 如果 Participant Registry Fingerprint 原本严格拒绝缺失 Participant，则不得隐式兼容同一 Runtime Store；
* 可以保持新版本与旧 Checkpoint不兼容并 Fail Fast；
* 不得伪造 Accrual Authority。

对于旧 Transaction Payload：

```text
Whole Fill
→ 可推导单次 Fee Accrual
```

但只应在 Transaction Codec Compatibility Boundary 中使用。

必须根据仓库现有 Checkpoint Compatibility Contract 选择，不能私自降低校验。

---

# 二十六、Committed Fact 扩展

建议增加：

```python
incremental_fee_total: OnlyMoney
order_cumulative_fee_after: OnlyMoney

account_reservation_consumed_delta: OnlyMoney
account_reservation_released_delta: OnlyMoney

strategy_reservation_consumed_delta: OnlyMoney
strategy_reservation_released_delta: OnlyMoney

risk_reservation_quantity_consumed_delta: OnlyQuantity
risk_reservation_notional_consumed_delta: OnlyMoney | None

position_cumulative_open_price_quantity_after: Decimal
allocation_cumulative_open_price_quantity_after: Decimal
```

必须增加不变量：

```text
incremental_fee_total >= 0
```

```text
account consumed/released delta >= 0
```

```text
strategy consumed/released delta >= 0
```

```text
risk consumed delta >= 0
```

```text
terminal_fill = false
→ released_delta == 0
```

```text
terminal_fill = false
→ Risk Active Count 不减少
```

---

# 二十七、Event Intents

## 27.1 中间 Fill

必须产生：

```text
ORDER_PARTIALLY_FILLED
POSITION_OPENED 或 POSITION_INCREASED
ALLOCATION_UPDATED
SETTLEMENT_UPDATED
ORDER_FEE_ACCRUAL_UPDATED
FEE_RECORDED（增量 Fee 非零时）
ACCOUNT_TRADE_APPLIED
STRATEGY_TRADE_APPLIED
ACCOUNT_CASH_RESERVATION_CONSUMED
STRATEGY_CASH_RESERVATION_CONSUMED
RISK_RESERVATION_CONSUMED
RISK_STATE_UPDATED
VALUATION_UPDATED
```

不得产生：

```text
ACCOUNT_CASH_RESERVATION_RELEASED
STRATEGY_CASH_RESERVATION_RELEASED
```

## 27.2 最终 Fill

必须产生：

```text
ORDER_FILLED
```

只有 `released_delta > 0` 时才产生 Reservation Released Event。

不得产生金额为零的 Release Event。

所有事件继续通过 Durable Outbox，不修改 Event Gate。

---

# 二十八、错误码

建议增加或明确：

```text
ACCOUNT_RESERVATION_INSUFFICIENT
STRATEGY_RESERVATION_INSUFFICIENT
RISK_RESERVATION_INSUFFICIENT
FEE_ACCRUAL_CONFLICT
FEE_ACCRUAL_NEGATIVE_INCREMENT
FEE_SCOPE_UNSUPPORTED
POSITION_COST_AUTHORITY_CONFLICT
ALLOCATION_COST_AUTHORITY_CONFLICT
RISK_REMAINING_NOTIONAL_UNDERFLOW
```

所有 Planning Error 必须发生在 Commit 前。

---

# 二十九、删除产品 Gate

当前：

```text
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

必须保留到以下全部完成：

1. Position 精确成本；
2. Allocation 精确成本；
3. Ledger Position Cost；
4. Fee Calculation Scope；
5. Order Fee Accrual；
6. Account Reservation 分段消费；
7. Strategy Reservation 分段消费；
8. Account Frozen Cash 增量记账；
9. Ledger Reserved Cash 增量记账；
10. Risk Reservation 分段消费；
11. Risk Active Count；
12. Projection Codec；
13. Projection Applier；
14. Checkpoint Participant；
15. Committed Fact；
16. Whole-Fill 回归；
17. Sequential Multi-Fill Transaction 测试。

最后一个实现 Commit 才允许删除该 Gate。

---

# 三十、删除 Gate 后的 Planner 条件

产品路径允许：

```text
fill.quantity <= order.remaining_quantity
```

且允许：

```text
order.filled_quantity > 0
```

Order 可接受状态：

```text
SUBMITTED
ACCEPTED
PARTIALLY_FILLED
PENDING_CANCEL
```

继续拒绝：

```text
FILLED
CANCELLED
EXPIRED
REJECTED
FAILED
```

Overfill 继续在 Commit 前拒绝。

---

# 三十一、测试工作包一：Exact Position / Allocation Cost

新增：

```text
tests/execution/test_position_multi_fill_exact_cost.py
tests/execution/test_allocation_multi_fill_exact_cost.py
```

覆盖：

1. 两个不同价格 Fill；
2. 三个不同价格 Fill；
3. 高精度 Decimal；
4. 不同 Quantity Precision；
5. Serialize 后继续 Fill；
6. Checkpoint Restore 后继续 Fill；
7. 与直接 `Σ(price × quantity)` 重算一致；
8. Position 和 Allocation 一致；
9. Ledger Position Cost 与精确 Authority 一致；
10. Legacy Whole-Fill 兼容。

---

# 三十二、测试工作包二：Fee Scope 与 Accrual

新增：

```text
tests/fee/test_fee_calculation_scope.py
tests/execution/test_order_fee_accrual_reducer.py
tests/execution/test_order_fee_accrual_projection.py
tests/execution/test_order_fee_accrual_checkpoint.py
```

覆盖：

1. FILL Scope Percent Fee；
2. FILL Scope Fixed Minimum；
3. ORDER_CUMULATIVE Minimum；
4. 第一次 Fill 收最低费用；
5. 第二次 Fill 不重复收费；
6. 累计 Raw Fee 超过 Minimum 后只收差额；
7. Maximum Cap；
8. 多 Component；
9. 不同 Schedule Version；
10. Duplicate Fill 不重复 Accrual；
11. Same Fill Identity Conflict；
12. Negative Increment Fail Closed；
13. Broker Reported Incremental Fee；
14. Unsupported Cumulative Report；
15. Checkpoint Round-Trip；
16. Projection Replay；
17. Whole-Fill Fee 结果不变。

---

# 三十三、测试工作包三：Account Reservation

新增：

```text
tests/execution/test_account_cash_reservation_multi_fill.py
```

覆盖：

1. 第一次 Partial Consume；
2. 第二次 Partial Consume；
3. 最终 Exact Consume；
4. 最终 Consume + Release；
5. 中间 Fill 不产生 Release；
6. Zero Release 不产生 Event；
7. Reservation 不足；
8. Duplicate Fill 不重复消费；
9. State/Amount 不变量；
10. Legacy Whole-Fill。

---

# 三十四、测试工作包四：Strategy Reservation

新增：

```text
tests/execution/test_strategy_cash_reservation_multi_fill.py
```

覆盖：

1. Partial State；
2. Stage 保持；
3. Final Consumed；
4. Final Released；
5. Release Stage；
6. 中间 Fill 无 Release Event；
7. Reservation 不足；
8. Duplicate 不重复消费；
9. Amount 不变量；
10. Whole-Fill 回归。

---

# 三十五、测试工作包五：Account Accounting

新增：

```text
tests/execution/test_account_multi_fill_accounting.py
```

覆盖：

1. Partial Fill 后 Cash Balance；
2. Partial Fill 后 Frozen Cash；
3. Partial Fill 后 Available Cash；
4. 第二 Fill；
5. 最终 Release；
6. Unsettled Cash 不变量；
7. Fee 为零；
8. Fee 非零；
9. Reservation 不足无 Mutation；
10. 三 Fill 资金守恒；
11. Whole-Fill 结果不变。

---

# 三十六、测试工作包六：Strategy Ledger Accounting

新增：

```text
tests/execution/test_strategy_ledger_multi_fill_accounting.py
```

覆盖：

1. Cash Balance；
2. Cash Reserved；
3. Cash Available；
4. Position Cost；
5. BUY_SETTLEMENT Entry 每 Fill 一条；
6. FEE Entry 仅非零 Fee；
7. Release Entry 只在最终有释放时；
8. 三 Fill Entry Sequence；
9. Duplicate 不重复 Entry；
10. Whole-Fill 回归。

---

# 三十七、测试工作包七：Risk

新增：

```text
tests/execution/test_risk_reservation_multi_fill.py
tests/execution/test_risk_snapshot_multi_fill.py
```

覆盖：

1. Quantity 分段消费；
2. Notional 分段消费；
3. Partial State；
4. Final Consumed；
5. Partial Fill Active Count 不变；
6. 三 Fill 只在最后减少一次；
7. Cluster Active Count；
8. Remaining Order Notional；
9. Underflow；
10. Duplicate 不重复减少；
11. Whole-Fill 回归。

---

# 三十八、测试工作包八：Prepared Transaction

新增：

```text
tests/execution/test_multi_fill_incremental_accounting_planner.py
```

构造一个订单：

```text
quantity = 1000
```

连续处理：

```text
Fill 1：300
Fill 2：400
Fill 3：300
```

必须验证：

```text
3 个独立 Transaction
Fill Index 1、2、3
Order 状态 Partial、Partial、Filled
Position 数量 300、700、1000
Allocation 数量 300、700、1000
Reservation Partial、Partial、终结
Risk Active Count 1、1、0
Account/Ledger 每次增量正确
Fee Accrual 正确
3 组 Outbox
3 次 Projection Ready
```

该测试可以直接构造三个 Broker Trade Update，不要求 Virtual Broker 自动产生。

---

# 三十九、测试工作包九：产品 Gate 删除

修改或替换：

```text
tests/execution/test_partial_fill_product_gate.py
```

删除 Gate 前测试应保持红色或 Fail Closed。

删除 Gate 后必须改为：

```text
Partial Fill
→ Prepared Transaction 成功
→ Commit 成功
→ Projection Ready
```

并验证：

```text
无 Manager 直接 Mutation
所有变化均来自 Projection
```

Whole-Fill 测试继续保留。

---

# 四十、测试工作包十：Persistence 与 Checkpoint

新增：

```text
tests/runtime/persistence/test_order_fee_accrual_roundtrip.py
tests/runtime/checkpoint/test_order_fee_accrual_checkpoint.py
tests/runtime/checkpoint/test_multi_fill_accounting_checkpoint.py
```

覆盖：

1. Memory Codec；
2. SQLite Codec；
3. New Projection Component；
4. Manager Checkpoint；
5. Restore 后继续下一 Fill；
6. Fill Index 继续；
7. Fee Accrual 继续；
8. Reservation 继续；
9. Position Exact Cost 继续；
10. Whole-Fill Legacy Compatibility。

---

# 四十一、Architecture Gate

新增：

```text
tests/architecture/test_multi_fill_incremental_accounting_architecture.py
```

至少检查：

1. Reducer 不导入 Manager；
2. Reducer 不导入 Store；
3. Reducer 不导入 EventBus；
4. FeeManager 不计算 Fee；
5. Order Fee Accrual Manager 不解析 Schedule；
6. Order Fee Accrual 是独立 Projection Component；
7. Order 不持有 Fee Accrual；
8. Account 不自行计算 Reservation Delta；
9. Ledger 不自行计算 Reservation Delta；
10. Risk 不自行判断 Terminal Fill；
11. Position/Allocation 不使用 Average 反推精确成本；
12. Transaction 仍不可变；
13. Commit Coordinator 未被重构；
14. Event Gate 未修改；
15. Recovery Outcome 未修改；
16. 不实现 SELL/CLOSE；
17. 不实现 Virtual Broker Partial Schedule；
18. 不实现 Margin；
19. Product Gate 仅在全部 Accounting 完成后删除；
20. 不新增生产 Fault Switch。

---

# 四十二、文档要求

新增：

```text
docs/adr/0050-incremental-multi-fill-reservation-and-accounting.md
```

ADR 必须说明：

1. 为什么 Order 是 Fill Terminal 唯一权威；
2. 为什么 Account/Ledger 使用显式 Reservation Delta；
3. Position/Allocation 精确成本 Authority；
4. Fee FILL Scope；
5. Fee ORDER_CUMULATIVE Scope；
6. 为什么需要独立 Order Fee Accrual；
7. FeeManager 与 Fee Accrual Manager 的职责区别；
8. Account Reservation 状态机；
9. Strategy Reservation State/Stage；
10. Risk Active Count 语义；
11. `remaining_order_notional` 定义；
12. Projection 顺序；
13. Checkpoint 和 Legacy 策略；
14. 为什么 PR4.3.2 不实现 Virtual Broker 和 Recovery 场景；
15. PR4.3.3 的范围。

更新：

```text
docs/roadmap.md
docs/architecture.md
docs/execution.md
docs/fee.md
docs/risk.md
docs/execution_runtime_recovery.md
README.md
```

Roadmap 标记：

```text
PR4.3.2
Incremental Reservation and Accounting for Multi-Fill
完成
```

同时明确：

```text
Virtual Broker Partial Fill Schedule
Multi-Fill Recovery
仍由 PR4.3.3 完成
```

---

# 四十三、建议生产文件范围

预期修改：

```text
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/projection_applier.py
src/onlyalpha/execution/authority_state.py

src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_reservations.py
src/onlyalpha/execution/reducers/trade_accounting.py

src/onlyalpha/fee/models.py
src/onlyalpha/fee/schedules.py
src/onlyalpha/fee/manager.py

src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/risk/

src/onlyalpha/runtime/backtest/runtime.py
```

可能新增：

```text
src/onlyalpha/execution/reducers/trade_fee_accrual.py
src/onlyalpha/fee/accrual.py
src/onlyalpha/fee/accrual_manager.py
```

原则上不修改：

```text
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
```

如果必须修改其他文件，最终报告必须说明原因。

---

# 四十四、推荐提交顺序

## Commit 1：审计与合同

完成预实施审计和 ADR 草案。

## Commit 2：Position / Allocation Exact Cost

增加精确累计开仓成本及 Legacy 兼容。

## Commit 3：Fee Scope 和 Order Fee Accrual

完成：

```text
Fee Scope
Accrual State
Reducer
Manager
Projection
Codec
Checkpoint
```

## Commit 4：Incremental Reservation

完成：

```text
Account Cash Reservation
Strategy Cash Reservation
Risk Reservation
```

## Commit 5：Account / Ledger / Risk

使用显式 Delta，删除 Whole-Fill 假设。

## Commit 6：Planner Integration

接线全部 Reduction、Fact 和 Projection。

## Commit 7：Product Path Open

删除：

```text
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

并增加三 Fill 正式 Transaction 测试。

## Commit 8：文档与回归

完成 Roadmap、ADR、README 和完整质量门禁。

---

# 四十五、必须执行的测试

至少执行：

```bash
uv run pytest tests/execution/test_position_multi_fill_exact_cost.py -q
uv run pytest tests/execution/test_allocation_multi_fill_exact_cost.py -q

uv run pytest tests/fee/test_fee_calculation_scope.py -q
uv run pytest tests/execution/test_order_fee_accrual_reducer.py -q
uv run pytest tests/execution/test_order_fee_accrual_projection.py -q
uv run pytest tests/execution/test_order_fee_accrual_checkpoint.py -q

uv run pytest tests/execution/test_account_cash_reservation_multi_fill.py -q
uv run pytest tests/execution/test_strategy_cash_reservation_multi_fill.py -q
uv run pytest tests/execution/test_account_multi_fill_accounting.py -q
uv run pytest tests/execution/test_strategy_ledger_multi_fill_accounting.py -q
uv run pytest tests/execution/test_risk_reservation_multi_fill.py -q
uv run pytest tests/execution/test_risk_snapshot_multi_fill.py -q

uv run pytest tests/execution/test_multi_fill_incremental_accounting_planner.py -q
uv run pytest tests/execution/test_partial_fill_product_gate.py -q

uv run pytest tests/runtime/persistence/test_order_fee_accrual_roundtrip.py -q
uv run pytest tests/runtime/checkpoint/test_order_fee_accrual_checkpoint.py -q
uv run pytest tests/runtime/checkpoint/test_multi_fill_accounting_checkpoint.py -q

uv run pytest tests/architecture/test_multi_fill_incremental_accounting_architecture.py -q
```

---

# 四十六、完整质量门禁

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run mypy packages/fake/onlyalpha-plugin-broker-virtual/src
uv run mypy packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare
uv run mypy packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt

uv run pytest tests/execution -q
uv run pytest tests/position -q
uv run pytest tests/account -q
uv run pytest tests/strategy_ledger -q
uv run pytest tests/risk -q
uv run pytest tests/fee -q
uv run pytest tests/runtime/persistence -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/integration -q
uv run pytest tests/architecture -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

uv run python scripts/version_sync.py check
git diff --check
```

不得伪造未执行的结果。

---

# 四十七、完成标准

只有全部满足才能声明 PR4.3.2 完成：

1. Position 保存精确累计开仓价值；
2. Allocation 保存精确累计开仓价值；
3. 平均开仓价不再反推历史累计成本；
4. Ledger Position Cost 使用精确 Authority；
5. Fee Rule 支持 FILL Scope；
6. Fee Rule 支持 ORDER_CUMULATIVE Scope；
7. Order Fee Accrual 是独立 Authority；
8. FeeManager 职责保持不变；
9. 最低佣金不会被每个 Fill 重复收取；
10. 累计 Fee 超过最低值后只收差额；
11. Account Reservation 支持 Partial Consume；
12. Strategy Reservation 支持 Partial Consume；
13. 中间 Fill 不释放 Reservation；
14. 最终 Exact Consume 不产生空 Release；
15. 最终有余额时正确 Release；
16. Reservation 不足时 Commit 前拒绝；
17. Account 使用显式 consumed/released delta；
18. Ledger 使用显式 consumed/released delta；
19. Risk Reservation 按 Fill 分段消费；
20. Partial Fill 不减少 Active Order Count；
21. Final Fill 只减少一次 Active Count；
22. `remaining_order_notional` 语义明确；
23. Committed Fact 保存增量 Accounting 审计字段；
24. 新 Projection Component 可序列化；
25. 新 Projection Component 可 Replay；
26. 新 Manager 可 Checkpoint/Restore；
27. 三个 Fill 生成三个独立 Transaction；
28. 三个 Fill 的 Fill Index 为 1、2、3；
29. 中间订单状态为 `PARTIALLY_FILLED`；
30. 最终订单状态为 `FILLED`；
31. 中间 Reservation 为 `PARTIALLY_CONSUMED`；
32. 最终 Reservation 为 `CONSUMED` 或 `RELEASED`；
33. 三个 Fill 只产生一次最终 Release；
34. 三个 Fill 只减少一次 Risk Active Count；
35. 三个 Fill 的资金、费用、持仓全部守恒；
36. Duplicate Fill 不重复记账；
37. Conflict Fill 不修改 Authority；
38. Whole-Fill 结果保持兼容；
39. Product Partial Fill Gate 已安全删除；
40. Commit Coordinator 未重构；
41. Recovery Event Gate 未修改；
42. Recovery Outcome 未修改；
43. 不实现 SELL/CLOSE；
44. 不实现 Virtual Broker Partial Schedule；
45. 不实现 Futures/Margin；
46. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 四十八、禁止实现

以下任一情况视为任务失败：

```text
先删除 PARTIAL_FILL_ACCOUNTING_NOT_READY
再逐步修复 Accounting

第一次 Partial Fill 就释放全部 Reservation
第一次 Partial Fill 就减少 Active Order Count
每个 Fill 重复收取订单级最低佣金
使用平均开仓价反推精确累计成本
让 Account 自行推导 Reservation Delta
让 Ledger 自行推导 Reservation Delta
让 Risk 自行判断 Terminal Fill
将 Fee Accrual 塞进 Order
让 FeeManager 计算订单累计费用
修改已提交 Transaction
合并多个 Fill 到一个可变 Transaction
让 Reducer访问 Store
让 Reducer访问 Manager
让 Reducer访问 EventBus
修改 Commit Coordinator 架构
修改 Recovery Event Gate
修改 Recovery Outcome
实现 Virtual Broker 自动 Partial Fill
实现完整 Multi-Fill Recovery
实现 SELL/CLOSE
实现 Futures/Margin
增加生产 fault_injection
直接篡改测试对象私有状态
伪造测试结果
```

---

# 四十九、最终交付报告

完成后输出结构化报告。

## 1. 基线

列出：

```text
实际 master commit
任务起始 commit
最终 commit
```

## 2. 修改前问题

说明：

```text
Reservation Whole-Fill 假设
Account/Ledger Whole-Fill 假设
Risk Active Count 问题
Position/Allocation 舍入问题
Fee Minimum 重复收费问题
```

## 3. Position / Allocation Exact Cost

说明：

* 新增字段；
* 计算公式；
* Legacy 兼容；
* Ledger 接线。

## 4. Fee Scope

说明：

```text
FILL
ORDER_CUMULATIVE
```

各自的正式语义。

## 5. Order Fee Accrual

说明：

* State；
* Component；
* Reducer；
* Manager；
* Projection；
* Checkpoint；
* FeeManager 职责保持。

## 6. Reservation

说明：

* Partial；
* Final Exact Consume；
* Final Consume + Release；
* Event 行为。

## 7. Account / Ledger

说明显式 Delta、现金公式和 Entry 结果。

## 8. Risk

说明 Reservation Delta、Active Count 和 Remaining Notional。

## 9. Planner 和 Projection

列出最终 Reduction 顺序与 Projection 顺序。

## 10. Product Gate

明确：

```text
PARTIAL_FILL_ACCOUNTING_NOT_READY
已在所有 Accounting 能力完成后删除
```

## 11. 三 Fill 结果

展示：

```text
Fill 1
Fill 2
Fill 3
```

后的 Order、Position、Reservation、Account、Ledger、Risk 和 Fee 结果。

## 12. 持久化和 Checkpoint

说明新 Authority 如何编码、恢复和兼容。

## 13. 未修改的架构

明确：

```text
Commit Coordinator
Recovery
Event Gate
Outbox
Transaction Identity
Fill Identity
```

保持不变。

## 14. 测试结果

列出真实命令和结果。

## 15. 未完成范围

明确：

```text
Virtual Broker Partial Schedule
Multi-Fill Crash/Restart Recovery
SELL/CLOSE
Futures/Margin
Paper/Live Multi-Fill
```

## 16. 下一步

明确：

```text
PR4.3.3
Virtual Broker Partial Fill Schedule
与 Multi-Fill Recovery
```

---

# 五十、最终目标现象

订单：

```text
LIMIT BUY
数量：1000
```

收到：

```text
Fill 1：300
Fill 2：400
Fill 3：300
```

最终必须出现：

```text
Order
ACCEPTED
→ PARTIALLY_FILLED
→ PARTIALLY_FILLED
→ FILLED
```

```text
Position
0
→ 300
→ 700
→ 1000
```

```text
Reservation
ACTIVE
→ PARTIALLY_CONSUMED
→ PARTIALLY_CONSUMED
→ CONSUMED / RELEASED
```

```text
Risk Active Order Count
1
→ 1
→ 1
→ 0
```

```text
Transaction Count
0
→ 1
→ 2
→ 3
```

每一个中间状态都必须同时满足：

```text
数量守恒
资金守恒
费用守恒
Reservation 守恒
Risk 守恒
Projection Preconditions
Durable Transaction 不可变
```

PR4.3.2 完成后，OnlyAlpha 必须能够证明：

> 一个订单可以由多个独立 Durable Fill 逐步完成；每个 Fill 都只消费本次对应的资金、费用、风险和 Reservation，未成交部分继续保持冻结和活动状态，最终 Fill 才释放剩余资源并终结订单。
