# OnlyAlpha PR4.4.1：Long Position CLOSE Authority

## 一、任务目标

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、Roadmap 和持久化实现，完成：

```text
PR4.4.1
Long Position CLOSE Authority
```

中文名称：

```text
PR4.4.1
Long Position 平仓权威与 Durable Transaction
```

本任务的核心目标是：

> 将 `GENERIC_T0_CASH + LIMIT + SELL + CLOSE + LONG + NETTING` 的成交，从当前 `_unmigrated_trade()` 直接修改 Manager 的旧路径，迁移到与 BUY/OPEN 相同的 Prepared Transaction、Durable Commit、Ordered Projection、Projection Ready、Durable Outbox 和 Recovery 主链。

完成后，Generic T0 Cash 的以下两个方向必须共享唯一正式事务基础设施：

```text
LIMIT BUY OPEN LONG NETTING
LIMIT SELL CLOSE LONG NETTING
```

不得再出现：

```text
BUY/OPEN
→ Durable Transaction

SELL/CLOSE
→ Direct Manager Mutation
```

---

# 二、开始前必须核验的基线

开始工作前必须重新读取当前仓库，不得仅根据本提示词直接修改代码。

当前预期基线为 PR4.3.3 合入后的 `master`，预期最新版本为：

```text
0.3.1
```

预期近期功能提交包括：

```text
PR4.3.1
Partial-Fill Order Authority
与 Durable Fill Identity

PR4.3.2
Incremental Reservation and Accounting for Multi-Fill

PR4.3.3
Virtual Broker Partial Fill Plan
与 End-to-End Multi-Fill Recovery
```

如果实际 `master` 已更新，以实际代码为准，并在预实施审计中记录：

1. 实际起始 Commit；
2. 当前版本；
3. 与本提示词预期的差异；
4. 已经提前完成的工作；
5. 因真实代码而调整的实现方案。

不得覆盖或回退 PR4.3.1～PR4.3.3 已经完成的行为。

---

# 三、当前已完成的基础

当前正式 Durable Transaction 已支持：

```text
GENERIC_T0_CASH
LIMIT
BUY
OPEN
LONG
NETTING
Whole Fill
Partial Fill
Multi-Fill
Virtual Broker Fill Plan
Checkpoint / Restart Recovery
```

当前已有能力包括：

```text
Fill Identity
Fill Payload Fingerprint
Per-Order Fill Index
Prepared Transaction
Durable Transaction Store
Ordered Projection
Projection Preconditions
Projection Ready
Durable Outbox
Order Fee Accrual
Incremental Reservation
Incremental Account / Ledger / Risk
Virtual Broker Checkpoint V2
A→B→C Restart Equivalence
```

PR4.4.1 必须复用这些基础，不得重新设计：

```text
Transaction ID
Fill Identity
Fill Fingerprint
Fill Index
Commit Coordinator
Projection Ready
Outbox
Recovery Phase
Recovery Event Gate
Checkpoint Finalizer
```

---

# 四、当前核心问题

当前 `OnlyExecutionProcessor` 只有在以下条件成立时才进入 Prepared Transaction 路径：

```text
profile_id == GENERIC_T0_CASH
order_type == LIMIT
side == BUY
offset == OPEN
```

而以下成交仍进入：

```python
_unmigrated_trade()
```

包括：

```text
SELL
CLOSE
SHORT
HEDGING
Futures
Margin
Position Reservation
```

`_unmigrated_trade()` 当前会直接依次修改：

```text
Order
Position
Allocation
Settlement
Margin
Fee
Account
Strategy Ledger
Reservation
Risk
```

该路径存在以下架构问题：

```text
无 Prepared Transaction
无 Durable Atomic Commit
无 Ordered Projection
无 Projection Preconditions
无 Projection Ready
无标准 Outbox 语义
无法复用完整 Transaction Recovery
部分失败可能留下半完成 Authority
```

PR4.4.1 必须消除 `GENERIC_T0_CASH SELL CLOSE LONG NETTING` 的这条双轨。

---

# 五、正式产品范围

本任务严格限定为：

```text
Market Profile : GENERIC_T0_CASH
Account Type   : CASH
Order Type     : LIMIT
Order Side     : SELL
Offset         : CLOSE
Position Side  : LONG
Position Mode  : NETTING
Currency       : Single Currency
Margin         : Disabled
Fill Mode      : Whole Fill
```

Whole Fill 的含义是：

```text
Fill Quantity
==
Close Order Remaining Quantity
```

不要求 Close Order 必须关闭整个账户 Position。

合法示例：

```text
Position Before = 1000
SELL CLOSE Order = 400
Fill = 400

Position After = 600
Order = FILLED
Position 仍 OPEN
```

另一个合法示例：

```text
Position Before = 1000
SELL CLOSE Order = 1000
Fill = 1000

Position After = 0
Position = CLOSED
```

---

# 六、本任务明确不实现

PR4.4.1 不实现：

```text
一个 Close Order 的 Partial Fill
一个 Close Order 的 Multi-Fill
Partial Close 后 Cancel
SELL OPEN SHORT
BUY CLOSE SHORT
SHORT Position
HEDGING
CLOSE_TODAY
CLOSE_YESTERDAY
Futures
Margin
Daily MTM
Liquidation
MARKET Close
IOC
FOK
GTD 特殊行为
多币种
FX
真实 Broker
Paper / Live Close Recovery
```

这些内容不得偷偷加入本 PR。

PR4.4.1 完成后，下一阶段才进入：

```text
PR4.4.2
Partial / Multi-Fill CLOSE
```

---

# 七、开始前必须审计的代码

至少重新读取：

```text
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/projection_applier.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/authority_state.py
```

Reducer：

```text
src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_accounting.py
src/onlyalpha/execution/reducers/trade_reservations.py
src/onlyalpha/execution/reducers/trade_fee_accrual.py
```

Position：

```text
src/onlyalpha/position/
```

Account、Ledger、Risk、Fee、Settlement：

```text
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/risk/
src/onlyalpha/fee/
src/onlyalpha/settlement/
```

Runtime：

```text
src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/checkpoint/
src/onlyalpha/runtime/recovery/
src/onlyalpha/runtime/persistence/
```

Virtual Broker：

```text
packages/fake/onlyalpha-plugin-broker-virtual/src/
onlyalpha_plugin_broker_virtual/
```

重点搜索：

```bash
rg "_uses_prepared_trade_path"
rg "_unmigrated_trade"
rg "UNSUPPORTED_ORDER_SIDE"
rg "UNSUPPORTED_OFFSET"
rg "POSITION_RESERVATION_FORBIDDEN"
rg "OnlyPositionReservation"
rg "consume_order_fill"
rg "realized_pnl"
rg "average_open_price"
rg "cumulative_open_price_quantity"
rg "apply_trade_cash_flow"
rg "ORDER_FEE_ACCRUAL"
rg "OnlyTradeApplicationInstruction"
rg "cash_available_on"
rg "asset_available_on"
rg "settlement_instruction"
rg "OnlyExecutionProjectionComponent"
rg "OnlyCommittedExecutionFact"
```

---

# 八、预实施审计文档

新增：

```text
docs/reports/pr4_4_1_long_close_authority_pre_implementation_audit.md
```

审计必须回答：

1. 当前 `_uses_prepared_trade_path()` 的精确条件；
2. 当前 SELL/CLOSE 为什么进入 `_unmigrated_trade()`；
3. `_unmigrated_trade()` 当前修改哪些 Manager；
4. 当前直接变更顺序是什么；
5. 当前部分失败如何处理；
6. 当前 Position Close 如何计算数量；
7. 当前 Allocation Close 如何计算数量；
8. 当前 Position 和 Allocation 如何计算 Realized PnL；
9. 当前剩余 Position 的平均开仓价如何处理；
10. 当前精确累计开仓价值如何减少；
11. 当前 Position Reservation 如何创建；
12. Position Reservation 当前有哪些 State 和 Stage；
13. Position Reservation 如何消费；
14. Position Reservation 如何区分 Account Hold 和 Allocation Hold；
15. 当前 SELL Risk 如何校验账户和 Cluster 可卖量；
16. 当前 Risk Reservation 如何消费 Close Fill；
17. 当前 SELL Fee 和 Tax 如何解析；
18. 当前 Settlement Instruction 如何描述 SELL Cash；
19. 当前 Account SELL Cash Flow 如何处理；
20. 当前 Strategy Ledger SELL Cash Flow 如何处理；
21. 当前 Result Fact 是否已经保存 Realized PnL；
22. 当前 Projection Component 是否存在 POSITION_RESERVATION；
23. 当前 Checkpoint 是否包含 Position Reservation；
24. 当前 Recovery 是否能恢复 Position Reservation Projection；
25. 当前 Virtual Broker 是否能产生 LIMIT SELL CLOSE Whole Fill；
26. 本任务预计修改哪些生产文件；
27. 本任务明确不修改哪些文件；
28. 哪些文档当前描述已经过时。

审计完成前不得修改生产代码。

---

# 九、核心架构原则

## 9.1 统一 Durable Planner

继续使用：

```python
OnlyTradeExecutionTransactionPlanner
```

不得新增一套完全平行的：

```python
OnlyLongCloseTransactionPlanner
OnlyCloseCommitCoordinator
OnlyCloseTransactionStore
OnlyCloseRecoverySession
```

Planner 可以根据 Trade Scope 选择不同 Reducer 分支，但 Transaction 基础设施必须唯一。

---

## 9.2 一个 Fill 对应一个 Transaction

必须保持：

```text
Broker Fill
=
Prepared Transaction
=
Committed Transaction
```

禁止：

```text
一个 Close Order 使用可变 Transaction
Position 和 Account 各自 Commit
Position Reservation 在 Transaction 外单独消费
```

---

## 9.3 Order 是订单生命周期权威

Order Reducer 继续负责：

```text
filled_quantity
remaining_quantity
fill_count
average_fill_price
status
terminal_fill
```

Position Reducer 不自行判断订单是否结束。

Reservation 和 Risk 必须使用 Order Reduction 输出的：

```text
terminal_fill
```

---

## 9.4 Reducer 保持纯函数

所有 Reducer 不得：

```text
访问 Manager
访问 Store
访问 EventBus
访问 Runtime
写 Outbox
修改外部对象
```

所有 Before Authority 必须由 Planning Context Builder 在规划前一次性捕获。

---

## 9.5 显式 Delta

Position、Allocation、Account、Ledger、Reservation 和 Risk 必须输出明确的 Delta。

不得让下游组件重复计算：

```text
realized_pnl_delta
position_quantity_delta
cash_delta
reservation_consumed_delta
```

---

# 十、正式支持的 Close Scope

新增或扩展正式 Scope 判定：

```python
is_supported_long_open = (
    profile_id == "GENERIC_T0_CASH"
    and order.order_type is OnlyOrderType.LIMIT
    and order.side is OnlyOrderSide.BUY
    and order.offset is OnlyOffset.OPEN
    and position_scope.position_effect is OnlyPositionEffect.OPEN
    and position_scope.position_side is OnlyPositionSide.LONG
    and position_scope.position_mode is OnlyPositionMode.NETTING
)

is_supported_long_close = (
    profile_id == "GENERIC_T0_CASH"
    and order.order_type is OnlyOrderType.LIMIT
    and order.side is OnlyOrderSide.SELL
    and order.offset is OnlyOffset.CLOSE
    and position_scope.position_effect is OnlyPositionEffect.CLOSE
    and position_scope.position_side is OnlyPositionSide.LONG
    and position_scope.position_mode is OnlyPositionMode.NETTING
)
```

正式 Prepared 路径：

```python
return is_supported_long_open or is_supported_long_close
```

PR4.4.1 完成后：

```text
GENERIC_T0_CASH SELL CLOSE
```

不得再进入 `_unmigrated_trade()`。

---

# 十一、Whole-Fill Close Gate

本阶段只允许：

```text
fill.quantity == order.remaining_quantity
order.filled_quantity == 0
order.fill_count == 0
```

如果 Close Order 已经部分成交，返回：

```text
PARTIAL_CLOSE_NOT_READY
```

或项目现有命名规范下的等价错误码。

必须保证：

```text
无 Prepared Transaction
无 Commit
无 Projection
无 Outbox
无 Authority Mutation
```

Overfill 继续使用现有正式错误。

---

# 十二、Planning Context 扩展

Close Context 必须捕获：

```text
Order Before
Position Before
Allocation Before
Position Reservation Before
Settlement Authority Before
Order Fee Accrual Before
Fee Authority Before
Account Before
Strategy Ledger Before
Risk Reservation Before
Risk Before
Valuation Before
```

Close Context 必须禁止：

```text
Position Creation Authority
Account Cash Reservation
Strategy Cash Reservation
Margin Reservation
```

建议继续使用：

```python
OnlyTradeExecutionPlanningContext
```

通过可选字段和严格组合不变量表达 OPEN/CLOSE 差异。

禁止复制一整套平行 Planning Context、Codec 和 Coordinator。

---

# 十三、Close Planner 验证

## 13.1 Order

必须满足：

```text
Order status 可接受 Fill
Order Side = SELL
Order Offset = CLOSE
Order Type = LIMIT
Order Remaining = Fill Quantity
Order Filled = 0
Fill Count = 0
```

## 13.2 Position

必须满足：

```text
Position Before 存在
Position status = OPEN
Position side = LONG
Position mode = NETTING
Position total quantity >= Fill Quantity
Position available quantity >= Fill Quantity
Position 不处于 RECONCILING
Position 不处于 ERROR
```

## 13.3 Allocation

必须满足：

```text
Allocation Before 存在
Allocation 属于 Order Cluster
Allocation instrument/account/runtime scope 一致
Allocation total quantity >= Fill Quantity
Allocation available quantity >= Fill Quantity
```

不得因为账户 Position 足够而允许 Cluster 使用其他 Cluster 的 Allocation。

## 13.4 Position Reservation

必须存在：

```text
Position Reservation Before
```

并满足：

```text
reservation.order_id == order.order_id
reservation.runtime_id == order.runtime_id
reservation.account_id == order.account_id
reservation.cluster_id == order.cluster_id
remaining_quantity >= fill.quantity
state 非终态
```

## 13.5 Reservation 组合

SELL/CLOSE 必须满足：

```text
Position Reservation 存在
Risk Reservation 存在
Account Cash Reservation 不存在
Strategy Cash Reservation 不存在
Margin Reservation 不存在
```

错误码建议：

```text
CLOSE_POSITION_RESERVATION_REQUIRED
CLOSE_POSITION_RESERVATION_INSUFFICIENT
CLOSE_CASH_RESERVATION_FORBIDDEN
CLOSE_MARGIN_RESERVATION_FORBIDDEN
```

## 13.6 Scope

必须拒绝：

```text
SELL OPEN
BUY CLOSE
SHORT
HEDGING
Margin
CLOSE_TODAY
CLOSE_YESTERDAY
```

---

# 十四、Projection Component

PR4.4.1 建议使用以下 Projection：

```text
1. ORDER
2. POSITION
3. ALLOCATION
4. SETTLEMENT
5. ORDER_FEE_ACCRUAL
6. FEE
7. ACCOUNT
8. STRATEGY_LEDGER
9. POSITION_RESERVATION
10. RISK_RESERVATION
11. RISK
12. VALUATION
```

不应包含：

```text
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
```

需要新增或正式开放：

```text
POSITION_RESERVATION
```

如果 `POSITION_RESERVATION` 枚举已经存在，必须复用，不得增加同义 Component。

Projection 顺序必须写入 ADR 和 Architecture Test。

---

# 十五、Order Reduction

继续复用现有 Multi-Fill Order Authority。

Whole Fill Close 后：

```text
status = FILLED
filled_quantity = order.quantity
remaining_quantity = 0
fill_count = 1
terminal_fill = true
filled_at = fill.ts_event
```

Order 的平均成交价是：

```text
Close Order 的平均卖出成交价
```

它与 Position 的平均开仓价是不同 Authority。

不得混淆。

---

# 十六、Position Close Reduction

建议扩展现有 Position Trade Reducer，使其支持正式 Durable LONG CLOSE。

输入：

```text
Position Before
Fill Price
Fill Quantity
Multiplier
Settlement Instruction
Position Reservation Authority
```

## 16.1 数量

```python
quantity_after = quantity_before - fill_quantity
```

必须满足：

```text
quantity_after >= 0
```

## 16.2 平均开仓价

如果：

```text
quantity_after > 0
```

则：

```text
average_open_price_after
=
average_open_price_before
```

如果：

```text
quantity_after == 0
```

则：

```text
average_open_price_after = None
```

## 16.3 精确累计成本

对于 Average Cost Long Close：

```text
released_open_price_quantity
=
average_open_price_before × fill_quantity
```

```text
cumulative_open_price_quantity_after
=
cumulative_open_price_quantity_before
-
released_open_price_quantity
```

如果全平：

```text
cumulative_open_price_quantity_after = 0
```

需要使用精确 Decimal Authority。

不得通过：

```text
average_after × quantity_after
```

反推剩余精确成本。

## 16.4 Realized PnL

```text
realized_pnl_delta
=
(fill_price - average_open_price_before)
× fill_quantity
× contract_multiplier
```

费用不进入毛 Realized PnL。

## 16.5 Settlement Bucket

卖出只能减少正式可卖 Bucket。

在 Generic T0 Cash 下仍必须通过 Market Instruction 和 Settlement Authority 决定：

```text
减少哪个 Asset Bucket
现金何时 Available
```

不得硬编码未来 A 股语义。

## 16.6 生命周期

```text
quantity_after > 0
→ Position status = OPEN

quantity_after == 0
→ Position status = CLOSED
```

全平时必须：

```text
average_open_price = None
unrealized_pnl = 0
position_market_value = 0
cumulative_open_price_quantity = 0
```

---

# 十七、Allocation Close Reduction

Allocation 使用与 Position 相同的：

```text
fill_quantity
average_open_price_before
multiplier
realized_pnl_delta
```

更新：

```text
allocation_quantity_after
=
allocation_quantity_before - fill_quantity
```

Realized PnL：

```text
allocation_realized_pnl_delta
=
position_realized_pnl_delta
```

对于当前单 Cluster Allocation Scope：

```text
Allocation Close Delta
必须与 Position Close Delta 一致
```

如果 Allocation 归零：

```text
Allocation = CLOSED
```

Account Position 仍可能保持 OPEN，因为其他 Cluster 可能仍有 Allocation。

必须继续满足：

```text
Account Position
=
sum(Cluster Allocations)
+
Unallocated
```

---

# 十八、Settlement Reduction

必须使用：

```text
OnlyTradeApplicationInstruction.settlement_instruction
```

而不是 Planner 自行构造规则。

SELL/CLOSE 至少需要表达：

```text
Asset Quantity Reduction
Cash Settlement Amount
Cash Available Date
Legal Settlement Date
Settlement Bucket
```

对于 Generic T0 Cash：

```text
Cash 通常当日可用
```

但必须来自 Profile/Instruction，而不是代码写死。

必须为未来 CN A-share T+1/T+0 Cash 规则保留正确边界。

---

# 十九、Order Fee Accrual

继续使用 PR4.3.2 已有：

```text
FILL
ORDER_CUMULATIVE
```

即使 PR4.4.1 只处理 Whole Fill，也不得绕过 Order Fee Accrual。

SELL 费用可能包括：

```text
Commission
Transaction Fee
Tax
Stamp Duty
Broker Fee
```

具体组件由 Runtime 唯一的 Fee Resolver 和 Fee Instruction 决定。

Planner 和 Position Reducer 不得硬编码费率。

---

# 二十、Fee Reduction

FeeManager 继续只保存：

```text
已经确定的 Fee Instruction Facts
```

不得让 FeeManager：

```text
查询 Position
计算 Realized PnL
解析 Market Profile
重新计算税费
```

Fee Fact 必须绑定：

```text
order_id
trade_id
fill_index
fee_type
authority
source_id
schedule_id
schedule_version
```

---

# 二十一、Account Close Reduction

定义：

```text
gross_notional
=
fill_price × fill_quantity × multiplier
```

```text
incremental_fee
=
Order Fee Accrual 本次增量费用
```

现金经济变化：

```text
gross_cash_inflow = gross_notional
net_cash_inflow   = gross_notional - incremental_fee
```

根据 Settlement Instruction：

```text
cash_balance
available_cash
unsettled_cash
```

必须分别正确变化。

Account 还必须更新：

```text
realized_pnl
fees
position_market_value
unrealized_pnl
equity
```

Realized PnL 使用 Position Reducer 产生的正式 Delta。

不得在 Account 中再次计算：

```text
(fill_price - average_open_price) × quantity
```

---

# 二十二、Strategy Ledger Close Reduction

Strategy Ledger 使用当前 Cluster Allocation Authority。

必须更新：

```text
cash_balance
cash_reserved
cash_available
realized_pnl
fees
position_cost
position_market_value
unrealized_pnl
equity
```

SELL/CLOSE 不消费 Strategy Cash Reservation。

Ledger Cash Entry 建议包括：

```text
SELL_SETTLEMENT
FEE
REALIZED_PNL
```

是否单独记录 `REALIZED_PNL` Entry 应遵循当前 Ledger 模型；不得为了展示新增重复经济记账。

关键要求是：

```text
Ledger realized_pnl_delta
==
Allocation realized_pnl_delta
```

---

# 二十三、Position Reservation Reduction

新增或正式扩展纯 Reducer：

```python
OnlyPositionReservationTradeReducer
```

输入：

```text
Position Reservation Before
Fill Quantity
terminal_fill
```

Whole Fill：

```text
consumed_quantity_delta = fill_quantity
consumed_quantity_after = reserved_quantity
remaining_quantity_after = 0
state = CONSUMED
```

必须明确：

```text
Account Position Hold
Cluster Allocation Hold
Broker Acknowledgement Stage
```

如何随消费推进。

不能在 Transaction Projection 完成后再额外调用：

```python
position_reservation_port.consume(...)
```

避免双重消费。

---

# 二十四、Risk Reservation Reduction

SELL/CLOSE 的 Risk Reservation 继续分段消费：

```text
consumed_quantity_delta = fill_quantity
consumed_notional_delta = gross_notional
```

PR4.4.1 是 Whole Fill，因此：

```text
remaining_quantity = 0
state = CONSUMED
terminal_fill = true
```

---

# 二十五、Risk Reduction

使用：

```text
risk_reservation_reduction
terminal_fill
```

更新：

```text
reserved_quantity
reserved_notional
remaining_order_notional
active_order_count
cluster_active_order_count
```

Whole Fill 后：

```text
active_order_count -= 1
cluster_active_order_count -= 1
```

只能减少一次。

---

# 二十六、Valuation Reduction

成交后必须基于 Position After 重新计算：

```text
position_market_value
position_unrealized_pnl
account_equity
strategy_equity
```

已卖出的数量不再属于 Unrealized PnL。

示例：

```text
Position Before = 1000
Fill Close = 400
Position After = 600
```

则：

```text
Market Value After
=
mark_price × 600 × multiplier
```

Realized PnL 属于已卖出的 400。

---

# 二十七、统一 Realized PnL Authority

必须有且只有一个纯计算来源。

建议由：

```text
Position Close Reduction
```

产生：

```text
realized_pnl_delta
```

然后传递给：

```text
Allocation
Account
Strategy Ledger
Committed Fact
```

禁止 Position、Account、Ledger 分别计算。

必须满足：

```text
position_realized_pnl_delta
==
allocation_realized_pnl_delta
==
account_realized_pnl_delta
==
ledger_realized_pnl_delta
==
committed_fact.realized_pnl_delta
```

---

# 二十八、Committed Fact 扩展

PR4.4.1 的 Committed Fact 必须准确记录：

```text
order_side = SELL
offset = CLOSE
position_side = LONG
position_effect = CLOSE
position_mode = NETTING

fill_quantity
fill_price
fill_index = 1
terminal_fill = true

position_quantity_before
position_quantity_after
position_quantity_delta

allocation_quantity_before
allocation_quantity_after
allocation_quantity_delta

position_cumulative_cost_before
position_cumulative_cost_after
released_open_cost

gross_notional
incremental_fee_total
gross_cash_inflow
net_cash_inflow

realized_pnl_delta
position_realized_pnl_delta
allocation_realized_pnl_delta
account_realized_pnl_delta
ledger_realized_pnl_delta

position_reservation_consumed_delta
risk_reservation_quantity_consumed_delta
risk_reservation_notional_consumed_delta

position_closed
allocation_closed
```

字段命名应遵循当前项目规范，不得重复增加已有字段。

Committed Fact 必须具备严格不变量。

---

# 二十九、Committed Fact 不变量

至少保证：

```text
position_quantity_after
=
position_quantity_before - fill_quantity
```

```text
allocation_quantity_after
=
allocation_quantity_before - fill_quantity
```

```text
position_quantity_delta == -fill_quantity
allocation_quantity_delta == -fill_quantity
```

```text
realized_pnl_delta
=
(fill_price - open_price_authority)
× fill_quantity
× multiplier
```

```text
net_cash_inflow
=
gross_notional - incremental_fee_total
```

```text
position_closed
↔ position_quantity_after == 0
```

```text
terminal_fill == true
```

---

# 三十、Prepared Transaction 组装

Close Prepared Transaction 必须包含全部业务 Authority 和 Projection。

不得出现：

```text
Position 已 Projection
但 Account 不在 Transaction 中

Position Reservation 在 Transaction 外消费

Risk 在 Transaction 完成后额外变更
```

所有变化必须在同一 Prepared Transaction 中被冻结。

---

# 三十一、Projection Preconditions

为每个 Projection 建立：

```text
Entity Key
Expected Version
Before Fingerprint
After State
Projection Sequence
```

特别是：

```text
Position
Allocation
Position Reservation
Account
Strategy Ledger
Risk Reservation
Risk
```

必须严格使用捕获时的 Before Authority。

如果 Position 在 Planner 后、Commit 前发生版本变化：

```text
Transaction Conflict
```

不得使用新 Position 偷偷重算。

---

# 三十二、Projection Recovery

新 CLOSE Projection 必须支持：

```text
serialize
deserialize
apply
replay
precondition validation
state fingerprint
checkpoint restore
post-recovery authority validation
```

如果新增 `POSITION_RESERVATION` Component，必须接入：

```text
Projection Applier
Codec
Runtime Target Registry
Checkpoint Participant
Recovery Authority Validator
```

---

# 三十三、ExecutionProcessor 迁移

修改：

```python
_uses_prepared_trade_path()
```

让其支持：

```text
GENERIC_T0_CASH LIMIT SELL CLOSE LONG NETTING
```

PR4.4.1 完成后，增加 Architecture Test：

```text
Generic T0 Cash Long Close
不得调用 _unmigrated_trade()
```

可通过行为测试、Spy 或源码门禁验证。

不建议直接删除 `_unmigrated_trade()`，因为 Futures、Margin、Short 等仍未迁移。

---

# 三十四、Virtual Broker 纵切面

必须通过正式 Virtual Broker 产生 Close Fill。

测试流程：

```text
Strategy BUY OPEN
→ Position 建立

下一阶段 Strategy SELL CLOSE
→ Position Reservation 建立
→ Virtual Broker Whole Fill
→ BrokerTradeUpdate
→ Durable Close Transaction
```

不得只通过手工构造 Position Snapshot 跳过正式开仓流程作为唯一集成测试。

单元测试可以直接准备 Authority，但正式 Engine Integration 必须先真实开仓再平仓。

---

# 三十五、Duplicate 与 Conflict

继续复用现有 Fill Identity。

相同 Fill：

```text
Same Fill Identity
+
Same Payload
→ DUPLICATE
```

必须保证：

```text
Position 不重复减少
Allocation 不重复减少
Cash 不重复增加
Realized PnL 不重复增加
Fee 不重复增加
Reservation 不重复消费
Risk 不重复消费
```

相同 Identity、不同 Payload：

```text
FILL_IDENTITY_CONFLICT
```

必须在 Authority Mutation 前 Fail Closed。

---

# 三十六、错误码建议

增加或明确：

```text
UNSUPPORTED_CLOSE_ORDER_TYPE
UNSUPPORTED_CLOSE_SIDE
UNSUPPORTED_CLOSE_OFFSET
UNSUPPORTED_CLOSE_POSITION_SIDE
UNSUPPORTED_CLOSE_POSITION_MODE

CLOSE_POSITION_REQUIRED
CLOSE_ALLOCATION_REQUIRED
CLOSE_POSITION_INSUFFICIENT
CLOSE_ALLOCATION_INSUFFICIENT

CLOSE_POSITION_RESERVATION_REQUIRED
CLOSE_POSITION_RESERVATION_INSUFFICIENT
CLOSE_POSITION_RESERVATION_CONFLICT

CLOSE_CASH_RESERVATION_FORBIDDEN
CLOSE_MARGIN_RESERVATION_FORBIDDEN

PARTIAL_CLOSE_NOT_READY

CLOSE_REALIZED_PNL_AUTHORITY_CONFLICT
CLOSE_SETTLEMENT_AUTHORITY_CONFLICT
```

应复用现有通用错误码时，不要重复造同义枚举。

---

# 三十七、Recovery 故障矩阵

不得新增 Recovery Phase。

复用当前：

```text
Checkpoint Restore
Exact Replay
Stored Transaction Rehydrate
Unprojected Transaction Recovery
Continuation
Authority Validation
Durable Finalization
Event Gate OPEN
```

至少新增以下测试。

## 37.1 Commit 前失败

验证：

```text
无 Committed Transaction
Position 未减少
Account 未增加
Reservation 未消费
```

重启后正常完成。

## 37.2 Commit 后、Projection 前

验证：

```text
Stored Transaction 存在
Projection Ready = false
```

恢复后完整应用一次。

## 37.3 Position Projection 后失败

验证：

```text
Position 已减少
Account 尚未增加
```

恢复时不得再次减少 Position。

## 37.4 Account 后、Reservation 前失败

验证：

```text
Account 已增加
Position Reservation 尚未消费
```

恢复后只完成剩余 Projection。

## 37.5 Projection Ready 后、Outbox 前失败

恢复时：

```text
不重复经济记账
只恢复 Pending Outbox
```

## 37.6 Checkpoint Restart

最终比较：

```text
Fresh Baseline
==
Interrupted + Restart
```

---

# 三十八、最终等价性比较

至少比较：

```text
Order
Committed Transaction
Fill Identity
Position
Closed Position History
Allocation
Closed Allocation History
Settlement
Fee Records
Order Fee Accrual
Account
Strategy Ledger
Position Reservation
Risk Reservation
Risk Snapshot
Valuation
Canonical Business Projection
Result Fingerprint
Artifact Manifest
```

不要求完整 Direct Event Stream 完全相等。

---

# 三十九、测试工作包一：Planner Validation

新增：

```text
tests/execution/test_long_close_planner_validation.py
```

覆盖：

1. 合法部分减仓 Whole Fill；
2. 合法全平 Whole Fill；
3. BUY CLOSE 拒绝；
4. SELL OPEN 拒绝；
5. MARKET 拒绝；
6. SHORT 拒绝；
7. HEDGING 拒绝；
8. Margin 拒绝；
9. 缺少 Position；
10. 缺少 Allocation；
11. Position 数量不足；
12. Allocation 数量不足；
13. 缺少 Position Reservation；
14. Reservation 数量不足；
15. 存在 Cash Reservation；
16. 已部分成交 Close Order；
17. Fill 小于 Remaining；
18. Overfill；
19. Scope 不一致；
20. Currency 不一致。

---

# 四十、测试工作包二：Position Close Reducer

新增：

```text
tests/execution/test_long_close_position_reducer.py
```

覆盖：

1. 1000 → 600；
2. 1000 → 0；
3. 正 Realized PnL；
4. 负 Realized PnL；
5. 零 Realized PnL；
6. Multiplier；
7. 剩余平均开仓价不变；
8. 精确累计成本减少；
9. 全平成本归零；
10. Settled Bucket 减少；
11. Available Quantity 减少；
12. Over-close 拒绝。

---

# 四十一、测试工作包三：Allocation Close Reducer

新增：

```text
tests/execution/test_long_close_allocation_reducer.py
```

覆盖：

1. 部分减少；
2. 全部关闭；
3. Realized PnL 与 Position 一致；
4. Cluster Scope；
5. 其他 Cluster Allocation 不受影响；
6. Allocation 数量不足；
7. 精确累计成本；
8. Closed History。

---

# 四十二、测试工作包四：Position Reservation

新增：

```text
tests/execution/test_long_close_position_reservation_reducer.py
```

覆盖：

1. Whole Fill Consume；
2. Remaining 归零；
3. State = CONSUMED；
4. Account Hold；
5. Allocation Hold；
6. Broker Acknowledged Stage；
7. Reservation 不足；
8. Duplicate 不重复消费；
9. Scope Conflict；
10. Projection Round-Trip。

---

# 四十三、测试工作包五：Account 与 Ledger

新增：

```text
tests/execution/test_long_close_account_accounting.py
tests/execution/test_long_close_strategy_ledger_accounting.py
```

覆盖：

1. Gross Cash Inflow；
2. Fee；
3. Net Cash Inflow；
4. Positive Realized PnL；
5. Negative Realized PnL；
6. Position Market Value；
7. Unrealized PnL；
8. Equity；
9. Settlement Cash Available；
10. Account/Ledger Realized PnL 一致；
11. Account 与 Ledger 独立对象；
12. Whole-Fill Duplicate。

---

# 四十四、测试工作包六：Fee 与 Settlement

新增：

```text
tests/execution/test_long_close_fee_and_settlement.py
```

覆盖：

1. Sell Commission；
2. Sell Tax；
3. FILL Scope；
4. ORDER_CUMULATIVE Scope；
5. Fee Accrual；
6. Settlement Instruction；
7. Cash Available On；
8. Currency；
9. Fee Instruction Round-Trip；
10. Whole-Fill 回归。

---

# 四十五、测试工作包七：Prepared Transaction

新增：

```text
tests/execution/test_long_close_prepared_transaction.py
```

验证 Projection：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
ORDER_FEE_ACCRUAL
FEE
ACCOUNT
STRATEGY_LEDGER
POSITION_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

验证：

```text
Projection Sequence
Preconditions
Committed Fact
Outbox Intent
```

---

# 四十六、测试工作包八：Processor Migration

新增：

```text
tests/execution/test_long_close_uses_durable_path.py
```

验证：

```text
GENERIC_T0_CASH SELL CLOSE
→ Prepared Transaction
```

并验证：

```text
不得调用 _unmigrated_trade()
```

Futures/Margin/Short 暂时仍可进入旧路径。

---

# 四十七、测试工作包九：Engine Vertical Slice

新增：

```text
tests/integration/test_engine_long_close_durable_transaction.py
```

必须通过：

```text
OnlyEngine
→ Strategy BUY OPEN
→ Virtual Broker Fill
→ Position 建立
→ Strategy SELL CLOSE
→ Virtual Broker Fill
→ Durable Close Transaction
```

验证：

```text
一笔 Open Transaction
一笔 Close Transaction
Position 减少或关闭
Realized PnL
Account Cash
Ledger
Position Reservation
Risk
Result
```

禁止用手工 `ExecutionProcessor.process()` 替代该正式纵切面。

---

# 四十八、测试工作包十：Recovery

新增：

```text
tests/integration/test_engine_recovery_long_close_after_commit.py
tests/integration/test_engine_recovery_long_close_mid_projection.py
tests/integration/test_engine_recovery_long_close_outbox.py
tests/integration/test_engine_recovery_long_close_checkpoint.py
```

验证 Baseline 与 Restart 等价。

---

# 四十九、Architecture Gate

新增：

```text
tests/architecture/test_long_close_durable_transaction_architecture.py
```

至少检查：

1. Generic T0 Long Close 使用 Prepared Path；
2. 不进入 `_unmigrated_trade()`；
3. 不新增 Close Commit Coordinator；
4. 不新增 Close Transaction Store；
5. Reducer 不依赖 Manager；
6. Reducer 不依赖 Store；
7. Position Reservation 是正式 Projection；
8. Account 不重新计算 Realized PnL；
9. Ledger 不重新计算 Realized PnL；
10. FeeManager 不计算 Fee；
11. Planner 不硬编码税率；
12. Planner 不硬编码 Settlement Date；
13. Transaction 仍不可变；
14. Fill Identity 未修改；
15. Commit Coordinator 未重构；
16. Recovery Phase 未新增；
17. Event Gate 未修改；
18. 不实现 Partial Close；
19. 不实现 Short；
20. 不实现 Margin。

---

# 五十、建议生产文件范围

预计修改：

```text
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/projection_applier.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/transaction.py

src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_accounting.py
src/onlyalpha/execution/reducers/trade_reservations.py

src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/risk/
src/onlyalpha/settlement/
```

可能新增：

```text
src/onlyalpha/execution/reducers/trade_close.py
src/onlyalpha/execution/reducers/trade_position_reservation.py
```

原则上不修改：

```text
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/fill_identity.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
```

如果必须修改上述文件，最终报告必须说明原因和最小修复范围。

---

# 五十一、推荐实施顺序

## Commit 1：预实施审计与 ADR 草案

冻结范围、Projection 顺序和 Realized PnL Authority。

## Commit 2：Position / Allocation Close Reducer

只完成纯 Reduction 和单元测试。

## Commit 3：Position Reservation Projection

完成 State、Reducer、Projection、Codec、Manager 接线。

## Commit 4：Account / Ledger / Risk Close Accounting

使用正式 Realized PnL 和 Reservation Delta。

## Commit 5：Planner Integration

让统一 Planner 生成完整 Close Prepared Transaction。

## Commit 6：Processor Migration

扩展 `_uses_prepared_trade_path()`，禁止 Generic T0 Long Close 进入旧路径。

## Commit 7：Engine Vertical Slice

通过正式 Strategy 和 Virtual Broker 完成 Open→Close。

## Commit 8：Recovery Matrix

覆盖 Commit、Projection、Outbox、Checkpoint。

## Commit 9：Architecture、Docs 与 Full Regression

---

# 五十二、ADR

新增：

```text
docs/adr/0052-generic-t0-cash-long-close-durable-transaction.md
```

ADR 必须说明：

1. 为什么需要迁移 `_unmigrated_trade()`；
2. PR4.4.1 的正式范围；
3. Whole Fill 的定义；
4. Unified Planner；
5. Close Planning Context；
6. Position Close Authority；
7. Allocation Close Authority；
8. Realized PnL 唯一权威；
9. Position Reservation；
10. Settlement；
11. Sell Fee/Tax；
12. Account Cash Inflow；
13. Strategy Ledger；
14. Projection 顺序；
15. Recovery；
16. 为什么不实现 Partial Close；
17. 为什么不实现 Short/Margin；
18. PR4.4.2 的后续范围。

更新：

```text
docs/roadmap.md
docs/architecture.md
docs/execution.md
docs/position.md
docs/account.md
docs/strategy_ledger.md
docs/risk.md
docs/order.md
docs/backtest.md
README.md
```

必须清理旧文档中：

```text
SELL/CLOSE 已经完整原子编排
ExecutionProcessor 尚无持久化
Partial Fill 尚未实现
```

等过时描述。

---

# 五十三、必须执行的测试

至少执行：

```bash
uv run pytest tests/execution/test_long_close_planner_validation.py -q
uv run pytest tests/execution/test_long_close_position_reducer.py -q
uv run pytest tests/execution/test_long_close_allocation_reducer.py -q
uv run pytest tests/execution/test_long_close_position_reservation_reducer.py -q
uv run pytest tests/execution/test_long_close_account_accounting.py -q
uv run pytest tests/execution/test_long_close_strategy_ledger_accounting.py -q
uv run pytest tests/execution/test_long_close_fee_and_settlement.py -q
uv run pytest tests/execution/test_long_close_prepared_transaction.py -q
uv run pytest tests/execution/test_long_close_uses_durable_path.py -q

uv run pytest tests/integration/test_engine_long_close_durable_transaction.py -q
uv run pytest tests/integration/test_engine_recovery_long_close_after_commit.py -q
uv run pytest tests/integration/test_engine_recovery_long_close_mid_projection.py -q
uv run pytest tests/integration/test_engine_recovery_long_close_outbox.py -q
uv run pytest tests/integration/test_engine_recovery_long_close_checkpoint.py -q

uv run pytest tests/architecture/test_long_close_durable_transaction_architecture.py -q
```

根据实际测试文件名调整，但不得删除对应测试意图。

---

# 五十四、完整质量门禁

必须执行：

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
uv run pytest tests/order -q
uv run pytest tests/position -q
uv run pytest tests/account -q
uv run pytest tests/strategy_ledger -q
uv run pytest tests/risk -q
uv run pytest tests/fee -q
uv run pytest tests/settlement -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/integration -q
uv run pytest tests/integration_demo -q
uv run pytest tests/architecture -q

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"

uv run python scripts/version_sync.py check
git diff --check
```

不得伪造未执行的测试结果。

---

# 五十五、完成标准

只有全部满足才能声明 PR4.4.1 完成：

1. Generic T0 Cash LIMIT SELL CLOSE 进入 Prepared Path；
2. 不再进入 `_unmigrated_trade()`；
3. 一个 Close Fill 对应一个不可变 Transaction；
4. Order 正确 FILLED；
5. Position 正确减少；
6. Allocation 正确减少；
7. Position 可部分保留；
8. Position 可完全关闭；
9. Allocation 可部分保留；
10. Allocation 可完全关闭；
11. 剩余平均开仓价保持不变；
12. 精确累计成本正确减少；
13. 全平成本归零；
14. Realized PnL 正确；
15. Position/Allocation/Account/Ledger PnL 一致；
16. Gross Cash Inflow 正确；
17. Net Cash Inflow 正确；
18. Sell Fee/Tax 正确；
19. Settlement 正确；
20. Account 正确；
21. Strategy Ledger 正确；
22. Position Reservation 正确消费；
23. Risk Reservation 正确消费；
24. Risk Active Count 只减少一次；
25. Valuation 正确；
26. Committed Fact 完整；
27. Duplicate Fill 不重复平仓；
28. Conflict Fill Fail Closed；
29. Planner Error 无外部副作用；
30. Commit 后故障可恢复；
31. Mid-Projection 故障可恢复；
32. Outbox 故障可恢复；
33. Checkpoint Restart 等价；
34. Result Fingerprint 等价；
35. Canonical Business Projection 等价；
36. 不修改 Fill Identity；
37. 不重构 Commit Coordinator；
38. 不新增 Recovery Phase；
39. 不实现 Partial Close；
40. 不实现 Short；
41. 不实现 Margin；
42. Ruff、Mypy、Pytest、Integration、Recovery 和 Architecture 全部通过。

---

# 五十六、禁止实现

以下任一情况视为任务失败：

```text
Generic T0 Long Close 继续进入 _unmigrated_trade()

Position 直接修改后再尝试构造 Transaction

Position Reservation 在 Transaction 外消费

Account 和 Ledger 分别重新计算 Realized PnL

FeeManager 计算税费

Planner 硬编码印花税率

Planner 硬编码 Settlement Date

使用平均价反推精确累计成本

多个 Projection 使用不同的 Fill Quantity

修改已 Commit Transaction

新增 Close Transaction Store

新增 Close Commit Coordinator

新增 Close Recovery Phase

修改 Fill Identity

修改 Fill Index 语义

修改 Event Gate

实现 Partial Close

实现 Multi-Close

实现 SHORT

实现 HEDGING

实现 Futures/Margin

增加生产 Fault Switch

直接篡改测试对象私有状态

伪造测试结果
```

---

# 五十七、最终交付报告

完成后输出结构化报告。

## 1. 基线

列出：

```text
实际 master commit
任务起始 commit
最终 commit
```

## 2. 修改前双轨

说明：

```text
BUY/OPEN Durable
SELL/CLOSE Unmigrated
```

以及 `_unmigrated_trade()` 的风险。

## 3. Close Scope

说明支持和拒绝的组合。

## 4. Planning Context

列出全部 Before Authority。

## 5. Position / Allocation

说明：

```text
Quantity
Average Cost
Exact Cost
Realized PnL
Lifecycle
```

## 6. Position Reservation

说明 State、Stage、消费和 Projection。

## 7. Settlement / Fee

说明 Instruction、Sell Fee、Tax 和 Cash Availability。

## 8. Account / Ledger

说明 Cash、Realized PnL、Fee、Valuation 和双账一致性。

## 9. Transaction

列出 Projection 顺序和 Committed Fact 字段。

## 10. Processor Migration

明确：

```text
GENERIC_T0_CASH SELL CLOSE
已不再进入 _unmigrated_trade()
```

## 11. Recovery

列出 Commit、Mid-Projection、Outbox 和 Checkpoint 结果。

## 12. 测试结果

列出真实命令、通过数量和任何跳过项。

## 13. 未修改架构

明确：

```text
Transaction Identity
Fill Identity
Fill Index
Commit Coordinator
Recovery Phase
Event Gate
Outbox Semantics
```

保持不变。

## 14. 未完成范围

明确：

```text
Partial/Multi-Close
Short
Hedging
Futures/Margin
CloseToday/CloseYesterday
Paper/Live
```

## 15. 下一步

明确：

```text
PR4.4.2
Partial / Multi-Fill CLOSE Incremental Accounting
```

---

# 五十八、最终目标现象

已有：

```text
LONG Position = 1000
Average Open Price = 10.00
```

策略提交：

```text
LIMIT SELL CLOSE 400
```

Virtual Broker Whole Fill：

```text
400 @ 12.00
Fee = 2.00
```

最终：

```text
Order
FILLED

Position
1000 → 600
Average Open Price = 10.00
Realized PnL += 800.00

Allocation
1000 → 600
Realized PnL += 800.00

Account
Cash += 4798.00
Fee += 2.00
Realized PnL += 800.00

Strategy Ledger
Cash += 4798.00
Fee += 2.00
Realized PnL += 800.00

Position Reservation
CONSUMED

Risk Reservation
CONSUMED

Transaction
Committed
Projection Ready
Durable Outbox Pending/Published
```

最终必须证明：

> 对于 Generic T0 Cash，LIMIT BUY OPEN 与 LIMIT SELL CLOSE 均使用同一套 Durable Transaction、Projection、Outbox、Checkpoint 和 Recovery 机制。SELL/CLOSE 不再通过直接 Manager Mutation 形成第二套执行权威。
