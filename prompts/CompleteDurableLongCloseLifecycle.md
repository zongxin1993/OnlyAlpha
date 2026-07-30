# OnlyAlpha 完整大任务：Complete Durable Long Close Lifecycle

## 一、任务名称

在 OnlyAlpha 当前 `master` 分支上完成一个不可拆分的大型 PR：

```text
PR4.4.2
Complete Durable Long Close Lifecycle
```

中文名称：

```text
PR4.4.2
完整 Durable Long Close 生命周期
```

该 PR 一次性完成：

```text
Partial / Multi-Fill Long CLOSE Incremental Accounting
+
Virtual Broker Multi-Close
+
End-to-End Multi-Close Recovery
+
Durable Terminal Finalization
+
Generic T0 Long Close Legacy Path Elimination
```

这是一个完整任务、一个开发分支、一个最终 PR。

不得拆分成：

```text
PR4.4.2a
PR4.4.2b
PR4.4.3
PR4.4.4
多个独立提交任务
多个待用户确认阶段
多个后续补丁 PR
```

可以在同一分支内创建多个结构清晰的 Git Commit，但这些 Commit 只是内部实现步骤，不是任务停止点，也不是独立交付物。

---

# 二、连续执行要求

从开始执行本任务起，必须连续完成全部工作。

禁止在以下阶段停止：

```text
完成审计后停止
完成 ADR 后停止
完成 Reducer 后停止
完成 Planner 后停止
完成 Multi-Close 后停止
完成 Recovery 后停止
完成 Terminal Transaction 后停止
完成部分测试后停止
```

不得向用户请求：

```text
是否继续
是否进入下一阶段
是否允许修改更多文件
是否先提交当前部分
是否将剩余工作放到下一个 PR
```

必须自主读取真实源码、解决实现细节、修复测试失败，并持续执行，直到：

```text
全部正式范围实现
全部新测试完成
全部现有回归通过
文档更新完成
最终报告完成
```

如果发现本提示词中的文件名、字段名或假设与真实仓库不一致：

1. 以当前源码和现有架构合同为准；
2. 选择满足本任务目标的最小合理设计；
3. 在审计和最终报告中记录差异；
4. 不得因此停止任务或要求重新确认。

除非存在无法绕过的安全问题或仓库本身不可读取，否则必须完成整个任务。

---

# 三、预期基线

当前预期功能基线为：

```text
950757066a0b87ae421312e844af493bb7e02e10
Feat: Long Position CLOSE Authority
```

开始时必须执行：

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git log -10 --oneline
```

确认：

```text
实际 master commit
实际当前分支
工作区是否干净
当前版本号
PR4.4.1 是否已经合入
```

如果实际 `master` 已更新，以实际源码为唯一事实源。

不得回退或破坏：

```text
PR4.3.1 Fill Authority
PR4.3.2 Multi-Fill Incremental Accounting
PR4.3.3 Virtual Broker Fill Plan 与 Recovery
PR4.4.1 Whole-Fill Long Close Durable Transaction
```

---

# 四、最终产品目标

本任务完成后，OnlyAlpha 必须支持以下完整流程：

```text
Strategy 建立 LONG Position
        │
        ▼
Strategy 提交 LIMIT SELL CLOSE
        │
        ▼
Risk 校验 Position 与 Allocation 可卖量
        │
        ▼
建立 Position Reservation 与 Risk Reservation
        │
        ▼
Virtual Broker 按确定性 Fill Plan 分批成交
        │
        ├── Fill 1
        ├── Fill 2
        └── Fill N
        │
        ▼
每个 Fill 生成独立 Durable Transaction
        │
        ▼
Order / Position / Allocation
Settlement / Fee / Account / Ledger
Position Reservation / Risk / Valuation
按 Fill 增量更新
        │
        ▼
最终 Fill 关闭订单和仓位
```

还必须支持：

```text
Close Order 部分成交
        │
        ▼
Cancel / Reject / Expire
        │
        ▼
生成独立 Durable Terminal Transaction
        │
        ▼
保留已成交部分
释放未成交部分 Position Reservation
释放未成交部分 Risk Reservation
终结 Active Order
```

最终必须消除：

```text
Generic T0 Long Close Trade
→ _unmigrated_trade()

Generic T0 Long Close Terminal
→ _terminal_order() 直接修改和释放多个 Manager
```

对于正式支持范围，Trade Fill 和 Terminal Operation 都必须使用统一的：

```text
Runtime Persistence Store
Commit Coordinator
Ordered Projection
Projection Preconditions
Projection Ready
Durable Outbox
Checkpoint
Recovery
```

---

# 五、正式范围

本 PR 严格支持：

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
Runtime        : Backtest
Broker         : Official Virtual Broker
```

成交范围：

```text
Whole Fill
Partial Fill
Multi-Fill
Cross-Bar Multi-Fill
Same-Bar Multi-Fill
PENDING_CANCEL 下继续 Fill
```

终态范围：

```text
CANCELLED
REJECTED
EXPIRED
```

必须覆盖：

```text
未成交后终态
Partial-Filled 后终态
Checkpoint 覆盖部分 Fill
连续 Engine Restart
Broker Execute 与 Publish 之间故障
Commit、Projection、Outbox 各阶段故障
```

当前正式范围继续限定为：

```text
单 Cluster
或 Position 与当前 Cluster Allocation 成本 Authority 完全一致
```

不得在本 PR 中解决多 Cluster 不同成本批次的 Close 归因。

---

# 六、明确不实现

本任务不实现：

```text
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
MARKET Order
IOC
FOK
GTD 特殊成交
真实订单簿
盘口深度
随机流动性
多币种
FX
Paper Runtime
Live Runtime
Exactly-once Outbox
Subscriber ACK
Delivery Watermark
通用 Non-Trade Transaction Framework
```

不得为这些范围提前增加半成品接口、占位流程或虚假的完成状态。

---

# 七、不可破坏的现有合同

必须保持：

```text
一个 Fill
=
一个不可变 Prepared Transaction
=
一个 Committed Transaction
```

不得修改已有 Trade Fill 的：

```text
Transaction ID 算法
Fill Identity
Fill Payload Fingerprint
Per-Order Fill Index
Execution Sequence
Projection Ready 语义
Durable Outbox 语义
```

不得新增：

```text
Close Transaction Store
Close Commit Coordinator
Close Recovery Phase
Close Event Gate
Close Fill Identity
```

原则上不得重构：

```text
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
```

如果新测试暴露这些基础设施存在真实缺陷，只允许最小修复，并必须在最终报告中说明：

```text
失败测试
根因
修改范围
为什么属于必要修复
```

---

# 八、必须审计的源码

在修改生产代码前，完整阅读至少以下范围。

Execution：

```text
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/projection_targets.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/economic_invariants.py
src/onlyalpha/execution/reservation_presence.py
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/persistence_ports.py
src/onlyalpha/execution/transaction_codec.py
```

Reducers：

```text
src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_accounting.py
src/onlyalpha/execution/reducers/trade_reservations.py
src/onlyalpha/execution/reducers/trade_fee_accrual.py
```

Domain Managers：

```text
src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/risk/
src/onlyalpha/fee/
src/onlyalpha/settlement/
src/onlyalpha/order/
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

相关测试：

```text
tests/execution/
tests/runtime/checkpoint/
tests/runtime/recovery/
tests/integration/
tests/integration_demo/
tests/architecture/

packages/fake/onlyalpha-plugin-broker-virtual/tests/
```

重点搜索：

```bash
rg "PARTIAL_CLOSE_NOT_READY"
rg "_uses_prepared_trade_path"
rg "_unmigrated_trade"
rg "_terminal_order"
rg "closes_position"
rg "position_reservation_port.consume"
rg "release_position_reservation"
rg "release_order"
rg "OnlyPositionReservation"
rg "OnlyPositionReservationExecutionProjection"
rg "average_open_price"
rg "cumulative_open_price_quantity"
rg "released_open_price_quantity"
rg "realized_pnl_delta"
rg "OnlyExecutionProjectionComponent"
rg "OnlyCommittedExecutionFact"
rg "OnlyPreparedExecutionTransaction"
rg "trade_id"
rg "transaction_id"
rg "BrokerOrderCancelled"
rg "BrokerOrderRejected"
rg "BrokerOrderExpired"
rg "schema_version"
```

---

# 九、预实施审计文档

新增：

```text
docs/reports/
pr4_4_2_complete_durable_long_close_lifecycle_audit.md
```

必须在文档中回答：

1. 当前 `PARTIAL_CLOSE_NOT_READY` 的全部触发位置；
2. 当前 Position Close 如何释放累计成本；
3. 当前 Allocation Close 如何释放累计成本；
4. `average_open_price` 的量化规则；
5. `cumulative_open_price_quantity` 的精度规则；
6. 连续 Partial Close 的成本漂移风险；
7. Position Reservation 的 Reserved、Consumed、Remaining、Released 语义；
8. Risk Reservation 的对应语义；
9. Position Reservation 是否已支持 `PARTIALLY_CONSUMED`；
10. Risk Active Count 是否只在 `terminal_fill` 时减少；
11. Fee Accrual 是否可支持 Multi-Close；
12. Account/Ledger 是否已按 Fill 增量记账；
13. Virtual Broker Fill Plan 是否天然支持 SELL/CLOSE；
14. 同 Bar与跨 Bar Fill Plan 是否区分 Side；
15. `_terminal_order()` 当前修改哪些 Authority；
16. Cancel/Reject/Expire 当前是否直接释放 Position Reservation；
17. Cancel/Reject/Expire 当前是否直接释放 Risk Reservation；
18. Runtime Store 是否要求 `trade_id NOT NULL`；
19. Prepared/Committed Codec 是否假设每个 Operation 必有 Trade；
20. Result Collector 是否假设所有 Transaction 都是 Trade；
21. Outbox Identity 是否能支持 Terminal Operation；
22. Checkpoint/Recovery 如何接入 Terminal Projection；
23. `_unmigrated_trade()` 是否仍能接收 Generic T0 Long Close；
24. Processor、Context Builder 和 Planner 是否重复判断 Capability；
25. 是否需要 Runtime Store Schema Version 3；
26. Schema 2 数据库的兼容策略；
27. 本任务预计修改的生产文件；
28. 本任务明确不修改的文件；
29. 当前文档中的过时说明；
30. 最终选定的统一实现方案。

完成审计文档后，不得停止。必须立即继续实现全部任务。

---

# 十、实现顺序

本任务为一个完整 PR，但必须按以下顺序连续实施：

```text
1. Exact Close Cost Authority
2. Position/Allocation Multi-Close Reducer
3. 移除 Partial Close 产品门禁
4. Multi-Close Planner 与 Economic Invariants
5. Sequential Multi-Close Transaction
6. Virtual Broker Multi-Close
7. Multi-Close Recovery
8. Durable Terminal Operation
9. Partial Fill Cancel/Reject/Expire
10. Capability Matrix
11. Legacy Path Elimination
12. Persistence/Codec/Checkpoint 收口
13. Architecture Gate
14. 文档
15. 全量回归
16. 最终报告
```

不得先简单删除 `PARTIAL_CLOSE_NOT_READY`。

---

# 十一、Exact Close Cost Authority

## 11.1 必须修复的问题

禁止继续将以下计算作为连续 Partial Close 的精确成本权威：

```python
released_cost = before.average_open_price.value * fill_quantity.value
```

原因：

```text
average_open_price
=
按 Price Precision 量化后的业务价格

cumulative_open_price_quantity
=
精确累计成本 Authority
```

多次使用量化均价扣减精确累计成本会产生漂移。

---

## 11.2 统一成本 Reduction

建议新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyCloseCostBasisReduction:
    quantity_before: OnlyQuantity
    fill_quantity: OnlyQuantity
    quantity_after: OnlyQuantity

    cumulative_open_price_quantity_before: Decimal
    released_open_price_quantity: Decimal
    cumulative_open_price_quantity_after: Decimal

    terminal_position_close: bool
```

纯函数：

```python
def only_reduce_average_cost_close(
    *,
    cumulative_open_price_quantity_before: Decimal,
    quantity_before: OnlyQuantity,
    fill_quantity: OnlyQuantity,
) -> OnlyCloseCostBasisReduction:
    ...
```

Position 和 Allocation 必须调用同一个函数。

不得各自实现相似但不一致的算法。

---

## 11.3 精确计算

定义：

```text
C = cumulative_open_price_quantity_before
Q = quantity_before
q = fill_quantity
```

全平：

```text
q == Q

released_open_price_quantity = C
cumulative_open_price_quantity_after = 0
```

部分平仓：

```text
q < Q

released_open_price_quantity
=
C × q ÷ Q

cumulative_open_price_quantity_after
=
C - released_open_price_quantity
```

必须使用：

```python
decimal.localcontext()
```

显式设置：

```text
rounding = ROUND_HALF_EVEN
```

以及足够稳定的 Decimal Precision。

建议：

```text
precision
=
max(
    36,
    price_precision + quantity_precision + 18,
    C 的有效位数 + 12
)
```

最终 Fill 必须强制释放全部剩余成本，消除尾差。

---

## 11.4 Realized PnL

使用精确释放成本计算：

```text
close_value_price_quantity
=
fill_price × fill_quantity
```

```text
realized_pnl_raw
=
(
    close_value_price_quantity
    -
    released_open_price_quantity
)
× contract_multiplier
```

之后转换为 `OnlyMoney`，按 Currency Precision 量化。

禁止由 Account、Ledger 或 Allocation重新计算 Realized PnL。

Position Close Reduction 是唯一来源。

必须满足：

```text
Position realized PnL
=
Allocation realized PnL
=
Account realized PnL delta
=
Ledger realized PnL delta
=
Committed Fact realized PnL
```

费用不进入毛 Realized PnL。

---

# 十二、开放 Partial/Multi-Close

只有成本 Reduction 测试通过后，才能移除生产路径中的：

```text
PARTIAL_CLOSE_NOT_READY
```

允许：

```text
0 < fill.quantity <= order.remaining_quantity
```

允许 Order Before：

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
REJECTED
EXPIRED
FAILED
```

不再因为以下条件拒绝：

```text
order.fill_count > 0
order.filled_quantity > 0
fill.quantity < order.remaining_quantity
```

Overfill 必须继续 Fail Closed。

---

# 十三、Order Multi-Close

继续复用已有 Order Partial-Fill Authority：

```text
filled_after
=
filled_before + fill_quantity
```

```text
remaining_after
=
order_quantity - filled_after
```

中间 Fill：

```text
status = PARTIALLY_FILLED
terminal_fill = false
```

最终 Fill：

```text
status = FILLED
terminal_fill = true
```

PENDING_CANCEL：

```text
非最终 Fill
→ 保持 PENDING_CANCEL
→ 正常生成本次 Close Transaction

最终 Fill
→ FILLED
→ 后续 Cancel Confirmation 为 stale
```

Fill Index：

```text
fill_index = previous durable fill count + 1
```

不得使用 Source Sequence 或 Broker Update Sequence 替代。

---

# 十四、Position 和 Allocation Multi-Close

## Position

每个 Fill：

```text
quantity_after
=
quantity_before - fill_quantity
```

部分平仓后：

```text
status = OPEN
average_open_price_after = average_open_price_before
```

全平后：

```text
status = CLOSED
average_open_price_after = None
cumulative_open_price_quantity_after = 0
market_value = 0
unrealized_pnl = 0
```

## Allocation

每个 Fill：

```text
allocation_quantity_after
=
allocation_quantity_before - fill_quantity
```

全平后：

```text
Allocation = CLOSED
```

当前单 Cluster 范围必须满足：

```text
Position released cost
=
Allocation released cost
```

否则：

```text
CLOSE_COST_AUTHORITY_CONFLICT
```

并在 Commit 前拒绝。

---

# 十五、Position Reservation 增量消费

每个 Fill：

```text
consumed_delta = fill_quantity
remaining_after = remaining_before - fill_quantity
```

中间 Fill：

```text
state = PARTIALLY_CONSUMED
```

最终 Fill：

```text
state = CONSUMED
remaining = 0
```

必须满足：

```text
reserved_quantity
=
consumed_quantity + released_quantity + remaining_quantity
```

如果模型没有显式 `released_quantity`，可以从其他字段推导，但本次 Fact 必须记录：

```text
position_reservation_consumed_delta
position_reservation_remaining_after
```

不得在 Transaction 外再次调用 Reservation Manager 的 `consume()`。

---

# 十六、Risk Reservation 和 Risk

每个 Fill：

```text
consumed_quantity += fill_quantity
consumed_notional += gross_notional
remaining_quantity -= fill_quantity
remaining_notional -= gross_notional
```

中间 Fill：

```text
Risk Reservation = ACTIVE
Active Order Count 不变
```

最终 Fill：

```text
Risk Reservation = CONSUMED
Active Order Count -= 1
Cluster Active Order Count -= 1
```

一个订单无论有多少 Fill，只能减少一次 Active Count。

---

# 十七、Fee、Settlement、Account 与 Ledger

## Fee

每个 Fill 必须经过：

```text
Order Fee Accrual
→ Incremental Fee
→ Fee Projection
```

继续支持：

```text
FILL
ORDER_CUMULATIVE
```

最低佣金不得每 Fill 重复收取。

## Settlement

每个 Fill 产生独立 Settlement Projection。

以下内容必须来自 `OnlyTradeApplicationInstruction`：

```text
Settlement Date
Cash Available Date
Asset Bucket
```

不得在 Planner 写死。

## Account

每个 SELL Fill：

```text
gross_cash_inflow
=
settled_notional
```

```text
net_cash_inflow
=
settled_notional - incremental_fee
```

更新：

```text
cash_balance
available_cash
unsettled_cash
realized_pnl
fees
position_market_value
unrealized_pnl
equity
```

## Strategy Ledger

每个 Fill 更新：

```text
cash_balance
cash_available
realized_pnl
fees
position_cost
position_market_value
unrealized_pnl
equity
```

每个 Fill 产生独立：

```text
SELL_SETTLEMENT Entry
必要时 FEE Entry
Fee Record
```

不得等待最终 Fill 后统一记账。

---

# 十八、Multi-Close Transaction

每个 Fill 的固定 Projection 顺序：

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

示例：

```text
Close Order = 1000
Fill = 300 → 400 → 300
```

必须生成：

```text
Transaction 1 / Fill Index 1
Transaction 2 / Fill Index 2
Transaction 3 / Fill Index 3
```

不得合并为一个可变 Transaction。

---

# 十九、Committed Fact 与经济不变量

每个 Fill Fact 至少准确保存：

```text
fill_index
fill_count_after
terminal_fill

position_quantity_before
position_quantity_after
allocation_quantity_before
allocation_quantity_after

position_cumulative_open_price_quantity_before
released_open_price_quantity
position_cumulative_open_price_quantity_after

allocation_cumulative_open_price_quantity_before
allocation_cumulative_open_price_quantity_after

realized_pnl_delta
position_realized_pnl_delta
allocation_realized_pnl_delta
account_realized_pnl_delta
ledger_realized_pnl_delta

gross_notional
incremental_fee_total
gross_cash_inflow
net_cash_inflow

position_reservation_consumed_delta
position_reservation_remaining_after

risk_reservation_quantity_consumed_delta
risk_reservation_notional_consumed_delta
risk_reservation_remaining_quantity_after

position_closed
allocation_closed
```

扩展经济不变量，至少验证：

```text
position_before - fill = position_after
allocation_before - fill = allocation_after
released_cost + cost_after = cost_before
net_cash_inflow = gross_notional - incremental_fee
```

以及所有 Realized PnL Authority 一致。

---

# 二十、Virtual Broker Multi-Close

必须复用现有：

```text
WHOLE
MAX_PER_BAR
SCHEDULE
ONE_PER_BAR
ALL_DUE
Quantity Plan
Ratio Plan
Plan ID
Plan Fingerprint
Plan Cursor
Checkpoint Schema 2
```

不得增加 Close 专用 Fill Plan。

正式 Engine 测试必须执行：

```text
Strategy BUY OPEN 1000
→ Position = 1000

Strategy SELL CLOSE 1000
→ Virtual Broker Fill Plan
→ 300
→ 400
→ 300
```

必须经过：

```text
OnlyEngine
Strategy
ctx.orders
Risk
Order
Virtual Broker
Broker Queue
ExecutionProcessor
Durable Transaction
```

不能只手工注入 Broker Update。

---

# 二十一、同 Bar 与跨 Bar

跨 Bar：

```yaml
partial_fill:
  mode: SCHEDULE
  dispatch_mode: ONE_PER_BAR
  steps:
    - bar_offset: 1
      quantity: "300"
    - bar_offset: 2
      quantity: "400"
    - bar_offset: 3
      quantity: "300"
```

同 Bar：

```yaml
partial_fill:
  mode: SCHEDULE
  dispatch_mode: ALL_DUE
  steps:
    - bar_offset: 1
      quantity: "300"
    - bar_offset: 1
      quantity: "400"
    - bar_offset: 1
      quantity: "300"
```

同 Bar 三个 Fill 必须产生独立的：

```text
Broker Update
Trade ID
Venue Trade ID
Fill Identity
Execution Sequence
Transaction
Projection Ready
Outbox Intent
```

---

# 二十二、Multi-Close Recovery

覆盖以下故障边界：

## Broker

```text
Execute 前
Execute 后 Publish 前
Publish 后 Runtime Commit 前
```

## Transaction

```text
Commit 后 Projection 前
Position Projection 后
Account Projection 后
Position Reservation Projection 后
Risk Projection 前
Projection Ready 后 Outbox 前
```

## Fill 边界

```text
Fill 1 Commit 后
Fill 1 Mid-Projection
Fill 2 Commit 后
Fill 2 Outbox 前
Fill 3 Commit 后
最终 Projection Ready 后
```

Checkpoint 覆盖 Fill 1 后：

```text
Order filled = 300
Position = 700
Reservation remaining = 700
Plan Cursor = 1
```

Checkpoint 覆盖 Fill 1、2 后：

```text
Order filled = 700
Position = 300
Reservation remaining = 300
Plan Cursor = 2
```

最终恢复不得产生重复 Fill。

---

# 二十三、A→B→C 等价

Baseline：

```text
300 → 400 → 300
无故障完成
```

Engine A：

```text
完成 Fill 1
故障
```

Engine B：

```text
恢复
完成 Fill 2
故障
```

Engine C：

```text
恢复
完成 Fill 3
```

必须满足：

```text
Baseline
==
A→B
==
A→B→C
```

比较：

```text
Orders
Transactions
Trades
Positions
Allocations
Settlements
Fees
Order Fee Accrual
Account
Strategy Ledger
Position Reservation
Risk Reservation
Risk
Valuation
Canonical Business Projection
Result Fingerprint
Artifact Manifest
Virtual Broker Fill Plan
Plan Cursor
Broker Trades
```

---

# 二十四、Durable Terminal Operation

仅为 Generic T0 Cash Long Close 实现：

```text
CANCELLED
REJECTED
EXPIRED
```

适用于：

```text
未成交 Close Order
部分成交 Close Order
PENDING_CANCEL Close Order
```

不得将 Cancel 伪造成 Fill。

---

# 二十五、Operation Kind

新增：

```python
class OnlyExecutionOperationKind(StrEnum):
    TRADE_FILL = "TRADE_FILL"
    ORDER_TERMINAL = "ORDER_TERMINAL"
```

现有 Trade Transaction：

```text
operation_kind = TRADE_FILL
```

必须保持已有 Trade Transaction ID 完全不变。

Terminal：

```text
operation_kind = ORDER_TERMINAL
```

不得伪造 Trade ID。

---

# 二十六、Terminal Identity

生成稳定 Identity：

```text
runtime_id
gateway_id
account_id
order_id
broker_terminal_update_id
terminal_status
```

格式建议：

```text
ETERM-<sha256>
```

语义：

```text
相同 Identity + 相同 Payload
→ DUPLICATE

相同 Identity + 不同 Payload
→ TERMINAL_IDENTITY_CONFLICT
```

Terminal Identity 不得复用 Fill Identity。

---

# 二十七、Terminal Planning Context

捕获：

```text
Order Before
Position Reservation Before
Risk Reservation Before
Risk Snapshot Before
```

不捕获：

```text
Position
Allocation
Settlement
Fee
Account
Ledger
Valuation
```

因为 Terminal Update 不产生新成交事实。

Long Close Terminal 必须保证：

```text
Position Reservation 存在
Risk Reservation 存在
Cash Reservation 不存在
Margin Reservation 不存在
```

---

# 二十八、Terminal Projection

固定顺序：

```text
ORDER
POSITION_RESERVATION
RISK_RESERVATION
RISK
```

部分成交后取消：

```text
Order quantity = 1000
Filled = 300
Remaining = 700
```

Cancel 后：

```text
Order:
  status = CANCELLED
  filled = 300
  remaining = 700
```

Order Remaining 不得改成零。

它表示未成交订单数量。

Position Reservation：

```text
reserved = 1000
consumed = 300
released = 700
remaining = 0
state = RELEASED
```

Risk Reservation：

```text
consumed 保持
剩余 Quantity/Notional 释放
remaining = 0
state = RELEASED
```

Risk：

```text
active_order_count -= 1
cluster_active_order_count -= 1
```

只能减少一次。

---

# 二十九、Terminal Fact 与 Result

Terminal Fact 至少保存：

```text
operation_kind = ORDER_TERMINAL
terminal_identity
broker_update_id
order_id
terminal_status
terminal_reason

filled_quantity_before
order_remaining_quantity

position_reservation_consumed_before
position_reservation_released_delta
position_reservation_remaining_after

risk_reservation_consumed_quantity_before
risk_reservation_released_quantity_delta
risk_reservation_released_notional_delta
risk_reservation_remaining_quantity_after

active_order_count_delta
cluster_active_order_count_delta
```

Result Collector 不得将 Terminal Fact 计入：

```text
Trade Count
Trade PnL
Trade Fee
Trade Settlement
```

Admin/Audit Query 必须能够读取 Terminal Fact。

---

# 三十、Terminal Recovery

覆盖：

```text
Terminal Commit 前
Commit 后 Projection 前
Order Projection 后
Position Reservation Projection 后
Risk Reservation Projection 后
Projection Ready 后 Outbox 前
Checkpoint 覆盖 Terminal Operation
```

恢复后不得：

```text
重复释放 Position Reservation
重复释放 Risk Reservation
重复减少 Active Count
```

---

# 三十一、Capability Matrix

新增唯一能力判定：

```python
class OnlyExecutionCapability(StrEnum):
    DURABLE_TRADE = "DURABLE_TRADE"
    DURABLE_TERMINAL = "DURABLE_TERMINAL"
    LEGACY_UNMIGRATED = "LEGACY_UNMIGRATED"
    UNSUPPORTED = "UNSUPPORTED"
```

统一函数：

```python
def only_resolve_execution_capability(...) -> OnlyExecutionCapability:
    ...
```

Processor、Context Builder 和 Planner 必须复用。

示例：

```text
Generic T0 BUY OPEN Trade
→ DURABLE_TRADE

Generic T0 SELL CLOSE Trade
→ DURABLE_TRADE

Generic T0 Long Close Cancel/Reject/Expire
→ DURABLE_TERMINAL

Futures SHORT Trade
→ LEGACY_UNMIGRATED

Generic T0 SELL OPEN
→ UNSUPPORTED
```

---

# 三十二、旧路径清理

任务完成后，正式范围不得进入：

```python
_unmigrated_trade()
```

范围：

```text
GENERIC_T0_CASH
LIMIT SELL CLOSE LONG NETTING
```

Long Close Terminal 不得进入直接 `_terminal_order()` 多 Manager 释放路径。

增加硬门禁，防止未来回归。

Legacy Path 暂时只允许：

```text
Futures
Margin
Short
Hedging
```

并明确标记为未迁移兼容路径。

---

# 三十三、Persistence 和 Schema

必须审计现有表结构是否允许 Terminal Operation。

如果不需要修改表结构，保持 Schema 2。

如果 `trade_id` 等字段强制非空，且无法在现有 Payload 模型中正确表达 Terminal Operation，则正式升级：

```text
Runtime Store Schema 2 → 3
```

升级时必须：

```text
显式 schema_version = 3
旧 Schema 2 Fail Fast
不自动迁移
不删除旧数据库
不自动降级 Memory
```

禁止伪造 Trade ID 规避 Schema 设计。

测试必须覆盖：

```text
Memory Round-Trip
SQLite Round-Trip
Trade Operation Codec
Terminal Operation Codec
旧 Schema Reject
新 Schema Reopen
```

---

# 三十四、测试工作包

必须实现以下意图对应的测试。文件名可按仓库现有规范调整，但不得删除测试意图。

## Exact Cost

```text
test_long_close_exact_cost_basis.py
test_long_close_multi_fill_cost_conservation.py
```

## Multi-Close Planner

```text
test_long_close_partial_fill_planner.py
test_long_close_multi_fill_planner.py
```

## Incremental Accounting

```text
test_long_close_multi_fill_accounting.py
test_long_close_multi_fill_fee.py
test_long_close_multi_fill_risk.py
test_long_close_multi_fill_reservation.py
```

## Sequential Projection

```text
test_long_close_multi_fill_sequential_projection.py
```

## Virtual Broker

```text
test_engine_long_close_multi_fill.py
test_engine_long_close_same_bar_multi_fill.py
test_engine_long_close_cross_bar_multi_fill.py
```

## Recovery

```text
test_engine_recovery_long_close_multi_fill_after_execute.py
test_engine_recovery_long_close_multi_fill_after_commit.py
test_engine_recovery_long_close_multi_fill_mid_projection.py
test_engine_recovery_long_close_multi_fill_outbox.py
test_engine_recovery_long_close_multi_fill_checkpoint.py
test_engine_recovery_long_close_multi_fill_abc_restart.py
```

## Terminal

```text
test_long_close_terminal_planner.py
test_long_close_terminal_identity.py
test_long_close_terminal_projection.py
test_long_close_terminal_codec.py
```

## Partial Fill Cancel

```text
test_engine_long_close_partial_fill_then_cancel.py
test_engine_recovery_long_close_partial_cancel.py
```

## Architecture

```text
test_complete_durable_long_close_lifecycle_architecture.py
```

---

# 三十五、关键测试场景

至少覆盖：

```text
1000 → 700 → 300 → 0
1000 → 750 → 500 → 250
非整数精确成本
高精度 Decimal
不同 Fill Price
正 Realized PnL
负 Realized PnL
零 Realized PnL
不同 Fill Fee
订单累计最低佣金
PENDING_CANCEL 下成交
Partial Fill 后 Cancel
Partial Fill 后 Reject
Partial Fill 后 Expire
Duplicate Fill
Conflict Fill
Duplicate Terminal
Conflict Terminal
Overfill
Reservation 不足
Checkpoint 后继续 Close
最终成本严格归零
```

---

# 三十六、Architecture Gate

至少验证：

1. Generic T0 Long Close Trade 使用 Durable Trade；
2. Generic T0 Long Close Terminal 使用 Durable Terminal；
3. 不进入 `_unmigrated_trade()`；
4. 不进入直接 `_terminal_order()` 释放路径；
5. Position/Allocation 使用同一个 Exact Cost Reducer；
6. Account 不计算 Realized PnL；
7. Ledger 不计算 Realized PnL；
8. FeeManager 不计算 Fee；
9. Planner 不硬编码税率；
10. Planner 不硬编码 Settlement Date；
11. Trade Fill Identity 未修改；
12. Terminal Identity 不复用 Fill Identity；
13. 无伪 Trade ID；
14. 无 Close Store；
15. 无 Close Coordinator；
16. 无 Close Recovery Phase；
17. Commit Coordinator 未重构；
18. Event Gate 未修改；
19. Terminal Fact 不计入 Trade Result；
20. 不实现 Short；
21. 不实现 Margin；
22. 无生产 Fault Switch。

---

# 三十七、建议生产文件范围

预计修改：

```text
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/projection_targets.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/economic_invariants.py
src/onlyalpha/execution/transaction_codec.py
src/onlyalpha/execution/persistence_ports.py
src/onlyalpha/execution/capabilities.py

src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_accounting.py
src/onlyalpha/execution/reducers/trade_reservations.py

src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/persistence/

packages/fake/onlyalpha-plugin-broker-virtual/
```

建议新增：

```text
src/onlyalpha/execution/reducers/close_cost_basis.py
src/onlyalpha/execution/terminal_identity.py
src/onlyalpha/execution/terminal_planner.py
src/onlyalpha/execution/reducers/terminal_reservations.py
```

原则上不修改：

```text
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
```

---

# 三十八、内部 Commit 建议

本任务最终只有一个 PR，但应创建结构清晰的内部 Commit：

```text
1. Audit and exact close cost contract
2. Shared exact close cost reducer
3. Multi-close planner and gate removal
4. Incremental reservation/risk/accounting
5. Multi-close facts and sequential projections
6. Virtual broker multi-close integration
7. Multi-close recovery matrix
8. Terminal operation model and identity
9. Durable cancel/reject/expire
10. Capability matrix and legacy path closure
11. Persistence, architecture and documentation
```

这些 Commit 不得作为中途交付点。

不得在任何 Commit 后停止等待用户确认。

---

# 三十九、文档

新增：

```text
docs/adr/
0053-complete-durable-long-close-lifecycle.md
```

ADR 必须说明：

1. 完整任务范围；
2. Exact Close Cost Authority；
3. Multi-Close Authority；
4. Position/Allocation Incremental Close；
5. Position Reservation；
6. Risk；
7. Fee Accrual；
8. Virtual Broker Fill Plan 复用；
9. Recovery Matrix；
10. Trade Fill 与 Terminal Operation 的区别；
11. Terminal Identity；
12. Partial Fill Cancel；
13. Capability Matrix；
14. Legacy Path Elimination；
15. Persistence Schema 决策；
16. Result 对 Terminal Fact 的处理；
17. 不支持范围。

更新：

```text
README.md
docs/roadmap.md
docs/architecture.md
docs/execution.md
docs/order.md
docs/position.md
docs/account.md
docs/strategy_ledger.md
docs/risk.md
docs/backtest.md
docs/execution_runtime_recovery.md
docs/virtual_broker.md
```

必须清理以下过时描述：

```text
Partial Close 尚未实现
Long Close 只支持首个 Whole Fill
Long Close Cancel 直接释放多个 Manager 是正式路径
Generic T0 Long Close 可能进入 Legacy Execution
```

---

# 四十、完整目标场景一：Multi-Close

初始：

```text
Position = 1000
Close Order = 1000
Fill Plan = 300 → 400 → 300
```

Fill 1：

```text
Order = PARTIALLY_FILLED
Position = 700
Allocation = 700
Position Reservation = PARTIALLY_CONSUMED
Risk Active Count = 1
Transaction Count = 1
```

Fill 2：

```text
Order = PARTIALLY_FILLED
Position = 300
Allocation = 300
Position Reservation = PARTIALLY_CONSUMED
Risk Active Count = 1
Transaction Count = 2
```

Fill 3：

```text
Order = FILLED
Position = CLOSED
Allocation = CLOSED
Position Reservation = CONSUMED
Risk Reservation = CONSUMED
Risk Active Count = 0
Transaction Count = 3
```

---

# 四十一、完整目标场景二：Partial Fill 后取消

初始：

```text
Position = 1000
Close Order = 1000
```

Fill 1：

```text
Fill = 300
Trade Transaction = 1
Position = 700
Reservation Remaining = 700
```

Cancel Confirmed：

```text
Terminal Transaction = 1

Order:
  status = CANCELLED
  filled = 300
  remaining = 700

Position:
  quantity = 700
  status = OPEN

Position Reservation:
  reserved = 1000
  consumed = 300
  released = 700
  remaining = 0
  state = RELEASED

Risk Reservation:
  consumed = 300
  released = 700
  remaining = 0
  state = RELEASED

Risk:
  active_order_count = 0
```

---

# 四十二、完整质量门禁

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

如果某一命令因真实目录不存在而失败：

1. 核验仓库结构；
2. 使用实际对应测试目录；
3. 在最终报告中记录调整；
4. 不得跳过测试意图。

不得伪造测试结果。

---

# 四十三、完成标准

只有以下全部满足，才能声明任务完成：

1. Exact Close Cost 使用共享纯函数；
2. 不再使用量化均价释放精确成本；
3. Position/Allocation 成本守恒；
4. 最终 Close 成本严格归零；
5. 产品路径不再产生 `PARTIAL_CLOSE_NOT_READY`；
6. 支持首个 Partial Close；
7. 支持历史 Fill 后继续 Close；
8. 支持 Final Fill；
9. 支持 PENDING_CANCEL 下成交；
10. 每个 Fill 一个独立 Transaction；
11. Fill Index 连续；
12. Position 增量减少正确；
13. Allocation 增量减少正确；
14. Realized PnL 每 Fill 正确；
15. Position Reservation 分段消费；
16. Risk Reservation 分段消费；
17. Active Count 仅最终 Fill 减少；
18. Fee Accrual 跨 Fill 正确；
19. Account 每 Fill 现金流正确；
20. Ledger 每 Fill 记账正确；
21. Virtual Broker 自动生成 Multi-Close；
22. 支持跨 Bar Multi-Close；
23. 支持同 Bar Multi-Close；
24. Fill Plan Checkpoint 连续；
25. Broker Execute/Publish 故障可恢复；
26. Commit 后故障可恢复；
27. Mid-Projection 故障可恢复；
28. Outbox 故障可恢复；
29. Checkpoint 覆盖 Fill 1 后继续；
30. Checkpoint 覆盖 Fill 1、2 后继续；
31. A→B→C 与 Baseline 等价；
32. Partial Fill 后 Cancel 使用 Durable Terminal Operation；
33. Reject 使用 Durable Terminal Operation；
34. Expire 使用 Durable Terminal Operation；
35. Terminal Identity 稳定；
36. Terminal Duplicate 幂等；
37. Terminal Conflict Fail Closed；
38. Terminal 不伪造 Trade ID；
39. Terminal Fact 不计入 Trade Result；
40. Position Reservation 剩余量正确释放；
41. Risk Reservation 剩余量正确释放；
42. Active Count 在 Terminal 时仅减少一次；
43. Generic T0 Long Close 不进入 `_unmigrated_trade()`；
44. Generic T0 Long Close Terminal 不走直接释放路径；
45. Capability Matrix 是唯一支持范围入口；
46. Commit Coordinator 未重构；
47. Recovery Phase 未新增；
48. Event Gate 未修改；
49. 不实现 Short；
50. 不实现 Margin；
51. Ruff、Mypy、Pytest、Integration、Recovery、Architecture 全部通过。

---

# 四十四、禁止实现

以下任一情况视为任务失败：

```text
中途停止并要求用户确认

只完成审计或 ADR 后停止

将任务拆成多个 PR

简单删除 PARTIAL_CLOSE_NOT_READY
但不修复 Exact Cost

使用 average_open_price × fill_quantity
释放精确成本

Position 和 Allocation 使用不同成本算法

多个 Fill 合并成一个 Transaction

仅手工注入 Fill
却声称 Virtual Broker Multi-Close 完成

重启后重新执行已经 Broker Execute 的 Fill

部分成交后 Cancel 直接修改多个 Manager

伪造 Trade ID 表示 Cancel

Terminal Update 使用 Fill Identity

Account 或 Ledger 重算 Realized PnL

FeeManager 计算 Fee

Planner 硬编码税率

Planner 硬编码 Settlement Date

Generic T0 Long Close 继续进入 _unmigrated_trade()

Generic T0 Long Close Terminal 继续直接释放 Reservation

新增 Close Store

新增 Close Coordinator

新增 Close Recovery Phase

修改 Trade Fill Identity

修改 Fill Index 语义

修改 Event Gate

实现 Short

实现 Hedging

实现 Futures/Margin

增加生产 Fault Switch

直接篡改测试对象私有状态

伪造测试结果
```

---

# 四十五、最终交付报告

只有整个任务完成后，输出一次最终结构化报告。

不得输出中途完成报告。

最终报告必须包含：

## 1. 基线

```text
实际 master commit
任务起始 commit
最终 commit
最终分支
```

## 2. 修改前边界

说明：

```text
Whole Close 已完成
Partial Close Gate
成本精度问题
Terminal Direct Mutation
Legacy Close Path
```

## 3. Exact Cost

说明：

```text
算法
Decimal Precision
成本守恒
最终归零
```

## 4. Multi-Close

说明：

```text
Order
Position
Allocation
Reservation
Risk
Fee
Account
Ledger
```

## 5. Virtual Broker

说明：

```text
Fill Plan
同 Bar
跨 Bar
Identity
Checkpoint
```

## 6. Recovery

逐项说明：

```text
Execute
Publish
Commit
Projection
Outbox
Checkpoint
A→B→C
```

## 7. Terminal Operation

说明：

```text
Operation Kind
Terminal Identity
Projection
Fact
Cancel
Reject
Expire
```

## 8. Legacy Closure

明确：

```text
Generic T0 Long Close Trade
不再进入 _unmigrated_trade()

Generic T0 Long Close Terminal
不再直接释放 Manager Authority
```

## 9. Persistence

说明：

```text
是否升级 Schema
Schema Version
Checkpoint Compatibility
旧数据库策略
```

## 10. 测试结果

列出真实命令和真实结果。

## 11. 未修改的基础架构

明确：

```text
Trade Fill Identity
Fill Index
Commit Coordinator
Recovery Phase
Event Gate
Outbox Semantics
```

保持不变。

## 12. 未完成范围

明确：

```text
Short
Hedging
CloseToday/CloseYesterday
Futures/Margin
Paper/Live
Exactly-once
```

## 13. 下一步

推荐进入：

```text
PR4.5
CN A-share Cash Product Closure
```

不得将本任务中未完成的内容伪装成下一 PR 的正常范围。

如果正式范围中的任何完成标准未满足，本任务不得声明完成。
