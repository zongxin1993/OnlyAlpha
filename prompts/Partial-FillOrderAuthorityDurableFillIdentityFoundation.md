# OnlyAlpha PR4.3.1：Partial-Fill Order Authority 与 Durable Fill Identity Foundation

## 一、任务背景

请基于 OnlyAlpha 当前 `master` 分支的真实源码、测试、ADR、Roadmap 和持久化实现，完成：

```text
PR4.3.1
Partial-Fill Order Authority
+
Durable Fill Identity
+
Deterministic Fill Index
+
Multi-Fill Committed Fact Foundation
```

中文名称：

```text
PR4.3.1
部分成交订单权威模型与持久 Fill 身份基础
```

开始工作前必须重新读取当前仓库，不得仅依据本提示词直接修改代码。

当前预期基线最新提交为：

```text
41b6c220f7956c9ffad7fe5d372bf1184f33e21a
Feat: Upate 0.3.0
```

该提交仅同步项目版本号，没有修改 Execution Transaction、Order Reducer、Reservation、Recovery 或 Partial Fill 逻辑。

如果实际 `master` 已更新，以实际代码为准，并在预实现审计中说明差异。

当前 PR4.2 系列已冻结：

```text
PR4.2.2a
Exact Causal Replay

PR4.2.2b
Post-Recovery Authority Validation
与 Durable Finalization

PR4.2.2c
Unified Recovery Event Gate
与 Failure Semantics Hardening
```

PR4.3.1 不再修改 Recovery 架构。

---

# 二、当前问题

当前领域枚举已经存在：

```text
OnlyOrderStatus.PARTIALLY_FILLED
```

Order Snapshot 和 Execution State 也已经保存：

```text
quantity
filled_quantity
remaining_quantity
average_fill_price
last_external_sequence
```

但正式 Trade Planner 当前仍要求：

```text
fill.quantity == order.remaining_quantity
并且
order.filled_quantity == 0
```

否则返回：

```text
PARTIAL_FILL_UNSUPPORTED
```

当前 Order Trade Reducer 又会对任何 Fill 无条件执行：

```text
status = FILLED
filled_quantity = order.quantity
remaining_quantity = 0
filled_at = current fill timestamp
```

这意味着现有架构仍然是：

```text
一个 Order
→ 一个 Fill
→ 一个 Transaction
→ 订单立即终结
```

而不是：

```text
一个 Order
→ Fill 1
→ PARTIALLY_FILLED
→ Fill 2
→ PARTIALLY_FILLED
→ Fill N
→ FILLED
```

---

# 三、PR4.3.1 的核心目标

本任务必须建立以下基础：

```text
Broker Fill
→ Stable Fill Business Identity
→ Duplicate / Conflict Classification
→ Deterministic Fill Index
→ Order Partial-Fill Reduction
→ Exact Cumulative Fill Authority
→ Auditable Committed Fact
→ Durable Store Query
```

必须证明：

1. 同一个订单可以按顺序应用多个 Fill；
2. 每个 Fill 是独立业务事实；
3. 每个 Fill 对应独立 Durable Execution Transaction；
4. Order 可以正确进入 `PARTIALLY_FILLED`；
5. 最终 Fill 才进入 `FILLED`；
6. Filled、Remaining、Fill Count 和平均成交价始终确定；
7. 重复 Fill 不重复应用；
8. 相同身份但不同 Payload 的 Fill 被识别为冲突；
9. Fill 身份在 Runtime 重启后仍可查询；
10. Whole-Fill 旧路径保持完全兼容。

---

# 四、最重要的范围限制

PR4.3.1 只完成：

```text
Order Partial-Fill Authority
Fill Identity
Fill Fingerprint
Fill Index
Committed Fact Audit Fields
Durable Fill Query
Legacy Whole-Fill Compatibility
```

PR4.3.1 不完成：

```text
Account Cash Reservation 分段消费
Strategy Cash Reservation 分段消费
Risk Reservation 正式分段事务
Risk Active Order Count 调整
Account Frozen Cash 分段释放
Strategy Ledger Reserved Cash 分段释放
Order Fee Accrual
跨 Fill 最低佣金
Virtual Broker Partial Fill Schedule
完整 Runtime Multi-Fill
Multi-Fill Recovery Scenario
SELL / CLOSE
Futures / Margin
```

最关键的范围合同是：

> PR4.3.1 完成后，内部 Order Authority、Fill Identity 和持久化模型支持 Multi-Fill，但产品级 Runtime Partial Fill 仍必须 Fail Closed。

不得在 Account、Reservation 和 Ledger 尚未支持分段消费时，提前开放完整 Trade Planner 的 Partial Fill 产品路径。

---

# 五、正式产品边界

本任务只考虑：

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

暂时不考虑：

```text
SELL
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
MARKET Order
IOC
FOK
GTD 特殊终止
订单改单
多个 Fill 放入一个 Broker Update
订单簿撮合
真实流动性模型
```

---

# 六、开始前必须审计的代码

重点读取：

```text
src/onlyalpha/domain/enums.py
src/onlyalpha/domain/execution.py

src/onlyalpha/broker/updates.py

src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/identity.py
src/onlyalpha/execution/planner.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/planned_trade.py
src/onlyalpha/execution/planning_results.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py

src/onlyalpha/execution/reducers/trade_state.py
src/onlyalpha/execution/reducers/trade_reservations.py
src/onlyalpha/execution/reducers/trade_accounting.py

src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/persistence_ports.py
src/onlyalpha/execution/projection.py
src/onlyalpha/execution/projection_applier.py

src/onlyalpha/runtime/persistence/
src/onlyalpha/runtime/backtest/runtime.py

src/onlyalpha/order/
src/onlyalpha/result/
```

重点搜索：

```bash
rg "PARTIAL_FILL_UNSUPPORTED"
rg "Fill must complete an unfilled Order"
rg "OnlyOrderTradeReducer"
rg "filled_quantity"
rg "remaining_quantity"
rg "average_fill_price"
rg "PARTIALLY_FILLED"
rg "filled_at"

rg "only_execution_transaction_id"
rg "broker_update_id"
rg "trade_id"
rg "venue_trade_id"
rg "external_event_id"

rg "OnlyCommittedExecutionFact"
rg "cumulative_filled_quantity"
rg "remaining_quantity"
rg "order_status_after"

rg "OnlyExecutionTransactionQueryPort"
rg "get_by_sequence"
rg "get_by_transaction"
rg "transactions_for"
rg "execution_transactions"

rg "to_dict"
rg "from_dict"
rg "checkpoint"
rg "serialize"
rg "deserialize"
```

---

# 七、预实现审计文档

开始修改生产代码前，新增：

```text
docs/reports/pr4_3_1_partial_fill_authority_pre_implementation_audit.md
```

审计必须回答：

1. 当前 Order Domain、Snapshot 和 Execution State 分别保存哪些成交字段；
2. `PARTIALLY_FILLED` 当前在哪些代码中被使用；
3. 当前 Planner 在哪里拒绝 Partial Fill；
4. 当前 Order Reducer 为什么始终设置 `FILLED`；
5. 当前平均成交价如何计算；
6. 当前平均价计算是否存在累计舍入问题；
7. 当前 Transaction ID 包含哪些身份字段；
8. 当前 Store 如何识别重复 Transaction；
9. 当前是否可以通过不同 Update ID 重复提交同一个 Venue Trade；
10. 当前 Committed Fact 已有哪些 Fill 审计字段；
11. 当前 Store 是否支持按 Order 查询 Transaction；
12. 当前 Store 是否支持按 Fill Identity 查询；
13. 当前 Snapshot/Checkpoint 是否需要 Schema Migration；
14. 当前旧 Whole-Fill 状态是否能推导 Fill Count；
15. 哪些组件已经天然支持增量 Fill；
16. 哪些组件仍假设订单一次完成；
17. 为什么 PR4.3.1 不能正式开放产品级 Partial Fill；
18. 哪些产品级 Gate 必须继续保留；
19. 本任务需要修改哪些生产文件；
20. 本任务明确不修改哪些文件。

审计完成前不得修改生产代码。

---

# 八、核心设计原则

## 8.1 一个 Fill 对应一个 Transaction

必须保持：

```text
Fill 1
→ Transaction 1

Fill 2
→ Transaction 2

Fill 3
→ Transaction 3
```

禁止：

```text
一个可变 Order Transaction
后续不断向其中追加 Fill
```

已提交 Transaction 必须继续不可变。

---

## 8.2 Order 是累计 Authority

单个 Transaction 表示：

```text
本次成交数量
本次成交价格
本次成交身份
```

Order Authority 表示：

```text
累计成交数量
剩余数量
累计成交价值
平均成交价格
Fill Count
最后成交身份
```

---

## 8.3 Planner 和 Reducer 继续保持纯函数边界

Order Reducer 不得：

```text
查询 Store
调用 Manager
调用 EventBus
写 Outbox
读取 Runtime
修改全局状态
```

Fill Identity 查询应发生在 Processor、Planner Orchestration 或正式 Store Adapter 中，而不是 Reducer 内。

---

## 8.4 产品级 Partial Fill 暂不开放

PR4.3.1 中：

```text
Pure Order Reducer
Fill Identity
Committed Fact
Store Query
```

可以支持 Multi-Fill。

但正式 Trade Transaction Planner 仍必须在 Accounting 组装前阻止 Partial Fill 进入完整 Projection 链。

建议将原错误替换为更精确的临时产品 Gate：

```text
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

或保留现有：

```text
PARTIAL_FILL_UNSUPPORTED
```

但必须在文档中明确：

```text
Order Authority 已支持
Accounting Product Path 尚未开放
```

---

# 九、Order Execution State 扩展

在：

```text
src/onlyalpha/execution/execution_state.py
```

扩展：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderExecutionState:
    ...
    fill_count: int
    cumulative_price_quantity: Decimal
    last_trade_id: OnlyTradeId | None
```

根据当前字段组织方式选择合理位置，但序列化顺序必须稳定。

---

# 十、字段语义

## 10.1 `fill_count`

定义：

```text
已经成功应用到 Order Authority 的独立 Fill 数量
```

要求：

```text
fill_count >= 0
```

## 10.2 `cumulative_price_quantity`

定义：

```text
Σ(fill_price × fill_quantity)
```

使用精确 `Decimal` 保存。

不得使用：

```text
average_fill_price × filled_quantity
```

反推累计成交价值。

## 10.3 `last_trade_id`

定义：

```text
最后一个成功应用到 Order Authority 的 Trade ID
```

该字段用于：

* 审计；
* 状态展示；
* 快速一致性检查。

它不能代替 Durable Fill Identity Store Query。

---

# 十一、Order Execution State 不变量

必须增加以下不变量：

```text
quantity
=
filled_quantity + remaining_quantity
```

保留现有检查。

新增：

```text
fill_count >= 0
```

```text
filled_quantity == 0
→ fill_count == 0
```

```text
fill_count == 0
→ average_fill_price is None
```

```text
fill_count == 0
→ cumulative_price_quantity == 0
```

```text
filled_quantity > 0
→ fill_count > 0
```

```text
filled_quantity > 0
→ average_fill_price is not None
```

```text
filled_quantity > 0
→ cumulative_price_quantity > 0
```

```text
status == PARTIALLY_FILLED
→ 0 < filled_quantity < quantity
```

```text
status == FILLED
→ filled_quantity == quantity
→ remaining_quantity == 0
→ filled_at is not None
```

```text
remaining_quantity > 0
→ status != FILLED
```

```text
last_trade_id is None
↔ fill_count == 0
```

对于：

```text
PENDING_CANCEL
```

允许：

```text
filled_quantity > 0
remaining_quantity > 0
```

---

# 十二、Order Snapshot 与 Manager 兼容

检查：

```text
OnlyOrderSnapshot
Order Manager Snapshot Adapter
Execution State Adapter
Checkpoint Adapter
Result Projection
```

是否需要同步新增：

```text
fill_count
cumulative_price_quantity
last_trade_id
```

建议：

* `fill_count` 可以进入公开 Order Snapshot；
* `last_trade_id` 可以进入 Snapshot；
* `cumulative_price_quantity` 属于精确内部 Authority，可以不暴露为策略 API 字段，但必须可持久化和恢复。

如果不向 Domain Snapshot 暴露 `cumulative_price_quantity`，需要确保 Execution State Restore 能从正式持久 Authority 恢复，而不是依赖量化后的平均价。

---

# 十三、旧状态兼容

PR4.3.1 之前正式产品只支持 Whole Fill，因此可以安全兼容旧状态。

## 未成交旧订单

推导：

```text
fill_count = 0
cumulative_price_quantity = 0
last_trade_id = None
```

## 已完成旧订单

推导：

```text
fill_count = 1
cumulative_price_quantity
=
average_fill_price.value × filled_quantity.value
```

`last_trade_id` 如果旧状态中无法直接获取：

* 优先从对应 Committed Fact 查询；
* 无法获取时可为兼容状态使用 `None`，但必须在兼容模型中明确区分；
* 不得伪造随机 Trade ID。

如果严格不变量要求 `fill_count > 0` 时 `last_trade_id` 非空，则应在 Deserialize Adapter 中从 Durable Transaction 重建。

不得修改历史持久记录。

---

# 十四、Order Trade Reducer 改造

修改：

```text
src/onlyalpha/execution/reducers/trade_state.py
```

当前无条件 Whole-Fill 逻辑必须改为累计逻辑。

建议：

```python
new_filled = before.filled_quantity + trade.quantity

if new_filled.value > before.quantity.value:
    raise ValueError("Fill exceeds Order remaining quantity")

new_remaining = before.quantity - new_filled

new_cumulative_price_quantity = (
    before.cumulative_price_quantity
    + trade.price.value * trade.quantity.value
)

average_value = (
    new_cumulative_price_quantity
    / new_filled.value
)

average = OnlyPrice(
    average_value,
    resolved_price_precision,
)
```

终态判断：

```python
terminal = new_remaining.value == 0
```

状态判断：

```python
if terminal:
    status = OnlyOrderStatus.FILLED
elif before.status is OnlyOrderStatus.PENDING_CANCEL:
    status = OnlyOrderStatus.PENDING_CANCEL
else:
    status = OnlyOrderStatus.PARTIALLY_FILLED
```

After State：

```python
after = replace(
    before,
    status=status,
    filled_quantity=new_filled,
    remaining_quantity=new_remaining,
    average_fill_price=average,
    fill_count=before.fill_count + 1,
    cumulative_price_quantity=new_cumulative_price_quantity,
    last_trade_id=trade.trade_id,
    updated_at=trade.ts_init,
    filled_at=trade.ts_event if terminal else None,
    version=before.version + 1,
    last_external_sequence=trade.source_sequence,
)
```

---

# 十五、Order Event Intent

非最终 Fill：

```text
ORDER_PARTIALLY_FILLED
```

最终 Fill：

```text
ORDER_FILLED
```

`PENDING_CANCEL` 下的非最终 Fill 仍产生：

```text
ORDER_PARTIALLY_FILLED
```

但 Order Status 可以保持：

```text
PENDING_CANCEL
```

Event Payload 必须包含完整 Order After Authority。

不得新增另一个“ORDER_FILL_RECEIVED”事件代替 Order 状态事件，除非当前 Event Model 已有明确层级需要。

---

# 十六、允许接收 Fill 的 Order 状态

Planner 或 Reducer 前置校验允许：

```text
SUBMITTED
ACCEPTED
PARTIALLY_FILLED
PENDING_CANCEL
```

拒绝：

```text
FILLED
CANCELLED
EXPIRED
REJECTED
FAILED
CREATED
```

对于 `CREATED` 是否允许，必须根据当前 Broker 生命周期判断；默认不允许尚未提交的 Order 接收 Fill。

---

# 十七、Fill Quantity 校验

新增正式错误码：

```text
FILL_EXCEEDS_REMAINING_QUANTITY
```

条件：

```text
fill.quantity > order.remaining_quantity
```

必须保证：

```text
无 Prepared Transaction
无 Commit
无 Projection
无 Outbox
无 Authority Mutation
```

保留：

```text
fill.quantity > 0
```

该约束当前已由 `OnlyOrderFill` 保证。

---

# 十八、Average Fill Price 精度

必须明确平均成交价精度策略。

建议：

```text
resolved_price_precision
=
max(
    order.price.precision if order.price else 0,
    trade.price.precision,
    previous average precision
)
```

计算顺序：

```text
先使用精确 Decimal 累计
最后一步再量化到 resolved_price_precision
```

禁止：

```text
先量化每个中间累计值
再继续累加
```

必须增加高精度测试，证明：

```text
连续多 Fill
序列化
恢复
继续 Fill
```

结果与一次性从全部 Fill 重算的平均价相同。

---

# 十九、Fill Business Identity

新增：

```text
src/onlyalpha/execution/fill_identity.py
```

或放入现有：

```text
src/onlyalpha/execution/identity.py
```

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionFillIdentity:
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    venue_trade_id: OnlyVenueTradeId | None
    external_event_id: str | None
```

---

# 二十、Canonical Fill Identity Key

Canonical Identity 优先级：

```text
venue_trade_id
优先于
external_event_id
优先于
trade_id
```

构造 Identity Authority：

```text
schema_version
runtime_id
gateway_id
account_id
order_id
identity_kind
identity_value
```

例如：

```python
authority = "\x1f".join(
    (
        str(FILL_IDENTITY_SCHEMA_VERSION),
        str(runtime_id),
        str(gateway_id),
        str(account_id),
        str(order_id),
        identity_kind,
        identity_value,
    )
)
```

返回：

```text
EFILL-<sha256>
```

必须定义：

```python
ONLY_EXECUTION_FILL_IDENTITY_SCHEMA_VERSION = 1
```

---

# 二十一、为什么不能只使用 Trade ID

不同 Gateway 或账户可能产生格式相同的 Trade ID。

因此不能使用：

```text
trade_id
```

作为全局唯一键。

至少必须包含：

```text
runtime_id
gateway_id
account_id
order_id
canonical external trade identity
```

---

# 二十二、Fill Payload Fingerprint

定义：

```python
def only_execution_fill_payload_fingerprint(
    update: OnlyBrokerTradeUpdate,
) -> str:
    ...
```

参与字段至少包括：

```text
runtime_id
gateway_id
account_id
order_id
trade_id
venue_trade_id
venue_order_id
price
quantity
price_precision
quantity_precision
ts_event
ts_init
source_sequence
external_sequence
external_event_id
liquidity_side
reported_fee
reported_fee_currency
fee_reporting_mode
fee_external_reference
reference_price
```

使用稳定 Canonical JSON：

```text
sort_keys = true
稳定 Decimal 字符串
稳定 Enum Value
稳定 Timestamp Nanoseconds
UTF-8
SHA-256
```

禁止使用：

```text
repr()
对象内存地址
Python hash()
非稳定 dict 顺序
```

---

# 二十三、Duplicate 与 Conflict 语义

## 相同 Fill Identity、相同 Fingerprint

结果：

```text
DUPLICATE_FILL
```

正式行为：

```text
返回已有 Transaction
不创建新 Transaction
不增加 Execution Sequence
不重新应用 Projection
不增加 Order Filled Quantity
不重复写 Outbox
```

如果已有 Transaction 已 Projection Ready：

```text
返回 ALREADY_READY 或等价幂等结果
```

如果已有 Transaction 已 Commit 但未 Ready：

```text
进入现有 recover/coordinate 路径
```

## 相同 Fill Identity、不同 Fingerprint

结果：

```text
FILL_IDENTITY_CONFLICT
```

行为：

```text
Fail Closed
不创建新 Transaction
不修改旧 Transaction
不应用新 Payload
```

---

# 二十四、Transaction Identity 保持不变

当前 Transaction ID 基于：

```text
runtime_id
gateway_id
account_id
broker_update_id
trade_id
```

不得在 PR4.3.1 中删除或替换该正式 Transaction Identity。

Fill Identity 是第二层业务幂等权威：

```text
Transaction ID
→ 本次 Broker Update Envelope 的事务身份

Fill Identity
→ 真实成交业务事实身份
```

二者用途不同。

不得把两者合并成一个可变字段。

---

# 二十五、Fill Index

定义：

```text
fill_index
=
同一 Runtime + Order 下已持久存在的有效 Fill 数量 + 1
```

要求：

```text
从 1 开始
连续递增
按 Order 独立
持久化后稳定
重启后稳定
```

不能直接使用：

```text
source_sequence
execution_sequence
broker_update_id
```

原因：

* Source Sequence 可能是 Account/Gateway 全局序列；
* Execution Sequence 是 Runtime 全局事务序列；
* Broker Update ID 不是连续整数。

---

# 二十六、Fill Index 计算并发边界

Backtest Runtime 当前是确定性串行处理，但设计不能隐式依赖“永远没有并发”。

Fill Index 分配必须与 Durable Commit 处于同一幂等/冲突边界。

建议：

1. Planner 通过 Store Query 获取当前 Order Fill Count；
2. Prepared Transaction 携带 `fill_index`；
3. Commit Store 校验同一 Order 下 `(fill_index)` 不重复；
4. 如果出现竞争，后提交者得到 Transaction Conflict；
5. 重读 Store 后重新分类 Duplicate 或 Conflict。

如果现有 Store 无法原子约束 `(runtime_id, order_id, fill_index)`，PR4.3.1 至少要在 Commit Adapter 中实现确定性冲突检查。

不要只在内存中计数。

---

# 二十七、Persistence Query Port 扩展

修改：

```text
src/onlyalpha/execution/persistence_ports.py
```

建议增加：

```python
class OnlyExecutionTransactionQueryPort(Protocol):
    def get_by_fill_identity(
        self,
        runtime_id: OnlyRuntimeId,
        fill_identity: str,
    ) -> OnlyCommittedExecutionTransaction | None:
        ...

    def transactions_for_order(
        self,
        runtime_id: OnlyRuntimeId,
        order_id: OnlyOrderId,
    ) -> tuple[OnlyCommittedExecutionTransaction, ...]:
        ...

    def latest_fill_for_order(
        self,
        runtime_id: OnlyRuntimeId,
        order_id: OnlyOrderId,
    ) -> OnlyCommittedExecutionTransaction | None:
        ...
```

根据当前接口组织可拆成独立：

```text
OnlyExecutionFillQueryPort
```

但不得制造重复、重叠的查询抽象。

---

# 二十八、Store 实现

优先复用现有 Execution Transaction 持久数据。

不建议在 PR4.3.1 立即增加新表。

允许：

```text
从 Committed Fact / Transaction Payload 查询
```

但必须满足：

```text
Runtime 重启后仍可查询
SQLite 和 Memory Store 语义一致
结果顺序稳定
```

`transactions_for_order()` 返回顺序建议：

```text
按 fill_index
其次 execution_sequence
```

如果当前 Schema 无法高效查询，可以先正确实现扫描，后续根据性能基线增加索引。

---

# 二十九、Committed Fact 扩展

修改正式 Committed Fact：

```python
fill_identity: str
fill_payload_fingerprint: str
fill_index: int
fill_count_after: int
terminal_fill: bool
cumulative_price_quantity_after: Decimal
```

保留已有：

```text
fill_quantity
fill_price
cumulative_filled_quantity
remaining_quantity
order_status_after
```

建议可选增加：

```python
cumulative_gross_notional_after: OnlyMoney
```

但不要在 PR4.3.1 中同时实现 Order Fee Accrual。

---

# 三十、Committed Fact 不变量

必须增加：

```text
fill_index >= 1
```

```text
fill_count_after == fill_index
```

当前阶段一个订单的 Fill Index 连续，因此两者应一致。

```text
terminal_fill
↔ remaining_quantity == 0
```

```text
terminal_fill
→ order_status_after == FILLED
```

```text
not terminal_fill
→ order_status_after in {PARTIALLY_FILLED, PENDING_CANCEL}
```

```text
cumulative_filled_quantity + remaining_quantity
=
原订单数量
```

如果 Committed Fact 不保存原订单数量，则通过 Order Projection Before/After 校验。

---

# 三十一、Planning Context 扩展

建议增加：

```python
fill_identity: str
fill_payload_fingerprint: str
fill_index: int
```

或者将其封装：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionFillAuthority:
    identity: str
    payload_fingerprint: str
    fill_index: int
```

然后在：

```text
OnlyTradeExecutionPlanningContext
```

中持有：

```python
fill_authority: OnlyExecutionFillAuthority
```

Planner 必须使用正式捕获的 Immutable Authority，不应自己再次查询 Store。

---

# 三十二、Fill Authority 捕获位置

建议在：

```text
ExecutionProcessor
或 Trade Planning Context Builder
```

执行：

1. 从 `OnlyBrokerTradeUpdate` 构造 Fill Identity；
2. 构造 Payload Fingerprint；
3. 查询 Durable Store；
4. 分类：

   * New；
   * Duplicate Same Payload；
   * Conflict Different Payload；
5. 对 New Fill 分配 Fill Index；
6. 将结果放入 Planning Context。

Pure Planner 不直接查询 Store。

---

# 三十三、Planner Validation 拆分

将当前：

```text
Fill must complete an unfilled Order
```

拆成：

```text
INVALID_ORDER_STATE
FILL_EXCEEDS_REMAINING_QUANTITY
STALE_EXTERNAL_SEQUENCE
FILL_IDENTITY_CONFLICT
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

其中：

## Pure Order Authority 测试路径

允许：

```text
fill.quantity <= remaining_quantity
```

## 完整产品 Transaction 路径

如果：

```text
fill.quantity < remaining_quantity
```

暂时返回：

```text
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

直到 PR4.3.2 删除该 Gate。

Whole Fill：

```text
fill.quantity == remaining_quantity
```

继续走现有完整 Transaction。

---

# 三十四、旧 Whole-Fill 行为保持不变

对于一个 1000 股 Order，一次 Fill 1000：

```text
fill_count_after = 1
fill_index = 1
terminal_fill = true
filled_quantity = 1000
remaining_quantity = 0
status = FILLED
```

现有：

* Position；
* Allocation；
* Fee；
* Settlement；
* Account；
* Ledger；
* Reservation；
* Risk；
* Outbox；

结果必须保持相同。

除新增审计字段外：

```text
Canonical Business Projection
Result Fingerprint
Artifact
```

不应发生无意变化。

如果 Result Fingerprint 包含 Committed Fact 新字段，需要评估是否应更新 Fingerprint Schema Version；不得静默改变历史 Fingerprint 含义。

---

# 三十五、PENDING_CANCEL 行为

必须明确测试：

## PENDING_CANCEL + Partial Fill

```text
Order Status After = PENDING_CANCEL
filled_quantity 增加
remaining_quantity 减少
fill_count 增加
average_fill_price 更新
filled_at 保持 None
Event = ORDER_PARTIALLY_FILLED
```

## PENDING_CANCEL + Final Fill

```text
Order Status After = FILLED
remaining_quantity = 0
filled_at = Fill timestamp
Event = ORDER_FILLED
```

后续 Cancel Ack：

```text
不得将 FILLED Order 改成 CANCELLED
```

如果当前 Cancel Processor 尚未具备该保护，应增加对应测试；生产修复严格限定为 Order 状态正确性。

---

# 三十六、结果与查询模型

检查当前 Result Projection 是否能够表示：

```text
一个 Order
多个 Trade
```

PR4.3.1 至少确保：

```text
transactions_for_order()
```

可以返回：

```text
Order ORD-1
├── Fill Index 1 / Trade T-1
├── Fill Index 2 / Trade T-2
└── Fill Index 3 / Trade T-3
```

不要求在本 PR 实现新的 UI 或 Report。

可以在 JSON Artifact 中保留新增审计字段，但不得破坏旧字段。

---

# 三十七、测试工作包一：Order Partial-Fill Reducer

新增：

```text
tests/execution/test_order_partial_fill_reducer.py
```

至少覆盖：

1. ACCEPTED → PARTIALLY_FILLED；
2. PARTIALLY_FILLED → PARTIALLY_FILLED；
3. PARTIALLY_FILLED → FILLED；
4. ACCEPTED → FILLED Whole Fill；
5. SUBMITTED → PARTIALLY_FILLED；
6. PENDING_CANCEL + Partial Fill；
7. PENDING_CANCEL + Final Fill；
8. FILLED 后拒绝 Fill；
9. CANCELLED 后拒绝 Fill；
10. EXPIRED 后拒绝 Fill；
11. Fill 超过 Remaining；
12. Filled + Remaining 总量守恒；
13. Fill Count 连续；
14. Last Trade ID 更新；
15. Final Fill 才设置 Filled At；
16. Non-Terminal Fill 的 Filled At 为 None。

---

# 三十八、测试工作包二：平均成交价精度

新增：

```text
tests/execution/test_order_fill_average_authority.py
```

至少覆盖：

1. 两次相同价格；
2. 两次不同价格；
3. 三次不同数量、不同价格；
4. 高精度 Decimal；
5. 小数量；
6. 大数量；
7. 中间序列化后继续 Fill；
8. Checkpoint Restore 后继续 Fill；
9. 直接从全部 Fill 重算结果与增量结果一致；
10. 不使用量化后的平均价反推历史累计值。

示例：

```text
Fill 1：300 @ 10.00
Fill 2：400 @ 10.10
Fill 3：300 @ 9.90
```

最终：

```text
cumulative_price_quantity = 10010
average_fill_price = 10.01
```

---

# 三十九、测试工作包三：Fill Identity

新增：

```text
tests/execution/test_execution_fill_identity.py
```

至少覆盖：

1. 有 Venue Trade ID；
2. 无 Venue Trade ID、有 External Event ID；
3. 仅有 Trade ID；
4. 不同 Runtime；
5. 不同 Gateway；
6. 不同 Account；
7. 不同 Order；
8. 相同 Canonical External Identity；
9. Identity Key 稳定；
10. Schema Version 固定。

---

# 四十、测试工作包四：Fill Payload Fingerprint

新增：

```text
tests/execution/test_execution_fill_fingerprint.py
```

至少覆盖：

1. 完全相同 Payload；
2. Quantity 变化；
3. Price 变化；
4. Timestamp 变化；
5. Source Sequence 变化；
6. Reported Fee 变化；
7. Liquidity Side 变化；
8. Metadata 顺序变化不影响结果；
9. Decimal 表示稳定；
10. Enum 序列化稳定。

---

# 四十一、测试工作包五：Duplicate / Conflict

新增：

```text
tests/execution/test_execution_fill_duplicate_classification.py
```

至少覆盖：

```text
相同 Fill Identity + 相同 Fingerprint
→ DUPLICATE
```

```text
相同 Fill Identity + 不同 Fingerprint
→ CONFLICT
```

```text
相同 Trade ID + 不同 Gateway
→ 不冲突
```

```text
相同 Trade ID + 不同 Account
→ 不冲突
```

```text
新 Update ID + 相同 Venue Trade ID
→ DUPLICATE 或 CONFLICT
```

根据 Fingerprint 决定。

---

# 四十二、测试工作包六：Fill Index

新增：

```text
tests/execution/test_execution_fill_index.py
```

至少覆盖：

1. 第一个 Fill Index 为 1；
2. 第二个为 2；
3. 第三个为 3；
4. 不同 Order 分别从 1 开始；
5. 中间有其他 Account Update 不影响；
6. 中间有其他 Order Fill 不影响；
7. Runtime Restart 后继续；
8. Duplicate Fill 不增加 Index；
9. Conflict Fill 不增加 Index；
10. Store Conflict 时 Fail Closed。

---

# 四十三、测试工作包七：Committed Fact

新增：

```text
tests/execution/test_partial_fill_committed_fact.py
```

至少验证：

```text
fill_identity
fill_payload_fingerprint
fill_index
fill_count_after
terminal_fill
cumulative_price_quantity_after
cumulative_filled_quantity
remaining_quantity
order_status_after
```

三次 Fill 的预期：

```text
ETX 1
fill_index = 1
fill_count_after = 1
terminal_fill = false
status = PARTIALLY_FILLED

ETX 2
fill_index = 2
fill_count_after = 2
terminal_fill = false
status = PARTIALLY_FILLED

ETX 3
fill_index = 3
fill_count_after = 3
terminal_fill = true
status = FILLED
```

完整产品 Planner 可以继续在 Partial Fill Accounting Gate 处拒绝，但 Committed Fact Builder 和 Pure Planning Fixture 必须支持构造并验证上述数据。

---

# 四十四、测试工作包八：Persistence

新增：

```text
tests/runtime/persistence/test_execution_fill_identity_query.py
tests/runtime/persistence/test_execution_order_transactions_query.py
tests/runtime/persistence/test_execution_partial_fill_roundtrip.py
```

Memory Store 和 SQLite Store 均必须覆盖：

1. 按 Fill Identity 查询；
2. 按 Order 查询全部 Transaction；
3. 顺序稳定；
4. Fill Index 持久化；
5. Payload Fingerprint 持久化；
6. Runtime Restart 后查询；
7. Duplicate Detection 在重启后仍有效；
8. Conflict Detection 在重启后仍有效；
9. 旧 Whole-Fill Record 兼容；
10. 不产生新表时现有数据可正常读取。

---

# 四十五、测试工作包九：产品级 Fail Closed

新增：

```text
tests/execution/test_partial_fill_product_gate.py
```

必须证明：

## Whole Fill

```text
仍正常 Commit / Projection / Outbox
```

## Partial Fill

```text
Order Pure Reducer 支持
但完整 Product Transaction Planner 返回
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

并且：

```text
无 Commit
无 Projection
无 Outbox
无 Account Mutation
无 Reservation Mutation
```

这条测试用于防止 PR4.3.1 提前开放错误的半成品路径。

---

# 四十六、测试工作包十：Legacy Compatibility

新增：

```text
tests/execution/test_legacy_whole_fill_order_state_compatibility.py
```

覆盖：

1. 旧未成交 Snapshot；
2. 旧已成交 Snapshot；
3. 旧 Whole-Fill Committed Fact；
4. 旧 Checkpoint Restore；
5. 新代码读取旧状态；
6. 新 Whole-Fill 写入新增字段；
7. 旧业务结果保持一致。

---

# 四十七、Architecture Gate

新增或更新：

```text
tests/architecture/test_partial_fill_authority_architecture.py
```

至少检查：

1. Order Reducer 不导入 Store；
2. Order Reducer 不导入 Manager；
3. Order Reducer 不导入 EventBus；
4. Fill Identity 不依赖 Runtime 实现；
5. Fill Fingerprint 不使用 Python `hash()`；
6. Fill Identity Query 是 Durable Port；
7. Fill Index 不只存在于内存；
8. Transaction ID 算法未被删除；
9. Commit Coordinator 未被修改为可变事务；
10. 已提交 Transaction 仍不可变；
11. Product Partial Fill 仍 Fail Closed；
12. Reservation Reducer未提前改造；
13. Account Reducer未提前改造；
14. Ledger Reducer未提前改造；
15. Risk Snapshot Reducer未提前改造；
16. Event Gate 未修改；
17. Recovery Outcome 未修改；
18. Checkpoint Schema 未无意修改；
19. 不实现 SELL/CLOSE；
20. 不实现 Virtual Broker Partial Schedule。

源码字符串测试只能作为辅助，核心行为必须由运行测试证明。

---

# 四十八、建议错误码

在现有 Planning Error Code 中增加或明确：

```text
FILL_EXCEEDS_REMAINING_QUANTITY
FILL_IDENTITY_CONFLICT
DUPLICATE_FILL
INVALID_FILL_INDEX
FILL_SEQUENCE_CONFLICT
PARTIAL_FILL_ACCOUNTING_NOT_READY
```

`DUPLICATE_FILL` 可以是正常幂等分类，不一定作为异常。

`FILL_IDENTITY_CONFLICT` 必须 Fail Closed。

---

# 四十九、建议生产文件范围

主要修改：

```text
src/onlyalpha/domain/execution.py

src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/identity.py
src/onlyalpha/execution/fill_identity.py
src/onlyalpha/execution/planning_context.py
src/onlyalpha/execution/planner.py
src/onlyalpha/execution/transaction.py
src/onlyalpha/execution/committed_fact.py
src/onlyalpha/execution/persistence_ports.py
src/onlyalpha/execution/reducers/trade_state.py

src/onlyalpha/runtime/persistence/
```

可能修改：

```text
src/onlyalpha/order/
src/onlyalpha/result/
```

原则上不修改：

```text
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
src/onlyalpha/execution/reducers/trade_reservations.py
src/onlyalpha/execution/reducers/trade_accounting.py
```

如果必须修改未预期文件，最终报告必须解释原因。

---

# 五十、推荐实施顺序

## Step 1

完成预实现审计。

## Step 2

写 Order Partial-Fill Reducer 红色测试。

## Step 3

扩展 Order Execution State 和不变量。

## Step 4

实现精确累计成交价值和平均价。

## Step 5

实现 Fill Identity。

## Step 6

实现 Fill Payload Fingerprint。

## Step 7

实现 Durable Duplicate/Conflict Query。

## Step 8

实现 Fill Index。

## Step 9

扩展 Planning Context。

## Step 10

扩展 Committed Fact。

## Step 11

实现 Memory Store 与 SQLite Store Query。

## Step 12

增加 Legacy Compatibility。

## Step 13

保留并测试 Product Partial Fill Fail-Closed Gate。

## Step 14

增加 Architecture Gate。

## Step 15

更新文档和 Roadmap。

## Step 16

运行完整质量门禁。

---

# 五十一、文档要求

新增：

```text
docs/adr/0049-partial-fill-order-authority-and-fill-identity.md
```

ADR 必须说明：

1. 为什么一个 Fill 对应一个 Transaction；
2. 为什么不能使用可变 Order Transaction；
3. Order 累计 Authority 的职责；
4. Transaction Fact 与 Order Authority 的区别；
5. Fill Identity 与 Transaction ID 的区别；
6. Fill Identity Canonical Priority；
7. Fill Payload Fingerprint；
8. Duplicate 与 Conflict 语义；
9. 为什么 Fill Index 不能使用 Source Sequence；
10. 为什么需要精确累计 Price × Quantity；
11. 为什么不使用平均价反推历史累计值；
12. PENDING_CANCEL 收到 Fill 的语义；
13. Legacy Whole-Fill Compatibility；
14. 为什么 PR4.3.1 不开放完整产品 Partial Fill；
15. PR4.3.2 将负责哪些 Accounting 能力。

更新：

```text
docs/roadmap.md
docs/architecture.md
docs/execution.md
docs/execution_runtime_recovery.md
README.md
```

Roadmap 标记：

```text
PR4.3.1
Partial-Fill Order Authority
与 Durable Fill Identity
完成
```

同时明确：

```text
Runtime Product Partial Fill
仍未开放

PR4.3.2
Reservation 与 Incremental Accounting
待完成
```

---

# 五十二、测试命令

根据仓库实际文件名调整，至少执行：

```bash
uv run pytest tests/execution/test_order_partial_fill_reducer.py -q
uv run pytest tests/execution/test_order_fill_average_authority.py -q
uv run pytest tests/execution/test_execution_fill_identity.py -q
uv run pytest tests/execution/test_execution_fill_fingerprint.py -q
uv run pytest tests/execution/test_execution_fill_duplicate_classification.py -q
uv run pytest tests/execution/test_execution_fill_index.py -q
uv run pytest tests/execution/test_partial_fill_committed_fact.py -q
uv run pytest tests/execution/test_partial_fill_product_gate.py -q
uv run pytest tests/execution/test_legacy_whole_fill_order_state_compatibility.py -q

uv run pytest tests/runtime/persistence/test_execution_fill_identity_query.py -q
uv run pytest tests/runtime/persistence/test_execution_order_transactions_query.py -q
uv run pytest tests/runtime/persistence/test_execution_partial_fill_roundtrip.py -q

uv run pytest tests/execution -q
uv run pytest tests/order -q
uv run pytest tests/runtime/persistence -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/integration -q
uv run pytest tests/architecture -q
```

---

# 五十三、完整质量门禁

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
uv run pytest tests/order -q
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

不得伪造未执行的测试结果。

---

# 五十四、完成标准

只有全部满足才能声明 PR4.3.1 完成：

1. Order Execution State 支持 Partial Fill；
2. `PARTIALLY_FILLED` 具备严格不变量；
3. Order Reducer 不再无条件设置 `FILLED`；
4. 非最终 Fill 正确设置 Remaining；
5. 最终 Fill 才设置 `filled_at`；
6. PENDING_CANCEL Partial Fill 语义明确；
7. Fill Count 正确累计；
8. Last Trade ID 正确更新；
9. Cumulative Price Quantity 精确累计；
10. Average Fill Price 从精确累计值计算；
11. 序列化/恢复后继续 Fill 结果一致；
12. Overfill 被拒绝；
13. Terminal Order 不接受新 Fill；
14. Fill Identity 稳定；
15. Fill Identity 包含 Runtime/Gateway/Account/Order Scope；
16. Identity 优先使用 Venue Trade ID；
17. 无 Venue Trade ID 时正确降级；
18. Fill Fingerprint 稳定；
19. 相同 Identity + 相同 Payload 被识别为 Duplicate；
20. 相同 Identity + 不同 Payload 被识别为 Conflict；
21. Duplicate 不创建新 Transaction；
22. Duplicate 不增加 Fill Index；
23. Conflict 不修改已有 Authority；
24. Fill Identity 在 Runtime Restart 后仍可查询；
25. 每个 Order 的 Fill Index 从 1 开始连续；
26. 不同 Order 的 Fill Index 独立；
27. Fill Index 不直接使用 Source Sequence；
28. Committed Fact 包含 Multi-Fill 审计字段；
29. Whole-Fill 结果保持不变；
30. 旧 Whole-Fill 状态可兼容读取；
31. Memory Store 与 SQLite Store 语义一致；
32. Commit Coordinator 不被重写；
33. Transaction ID 算法不被删除；
34. 已提交 Transaction 仍不可变；
35. Product Partial Fill 仍 Fail Closed；
36. Reservation Reducer 未提前开放；
37. Account/Ledger Accounting 未提前开放；
38. Recovery Event Gate 未修改；
39. Recovery Outcome 未修改；
40. 不实现 SELL/CLOSE；
41. Ruff、Mypy、Pytest 和 Architecture Gate 全部通过。

---

# 五十五、禁止实现

以下任一情况视为任务失败：

```text
删除现有 Transaction ID
用 Fill Identity 替代 Transaction ID
将多个 Fill 追加到一个可变 Transaction
修改已提交 Transaction
让 Order Reducer 查询 Store
让 Order Reducer调用 Manager
让 Planner直接修改 Order Manager
Fill Identity 只保存在内存
Fill Index 使用随机数
Fill Index 直接等于 Source Sequence
Fill Index 直接等于 Execution Sequence
使用 Python hash() 生成持久身份
使用 repr() 生成 Fingerprint
使用量化后的平均价反推精确累计值
第一次 Partial Fill 就释放全部 Reservation
第一次 Partial Fill 就减少 Active Order Count
正式开放 Runtime Partial Fill
修改 Event Gate
修改 Recovery Outcome
修改 Finalizer Phase
实现 Virtual Broker Partial Schedule
实现 Multi-Fill Recovery
实现 SELL/CLOSE
实现 Futures/Margin
增加生产 fault_injection
直接修改测试对象私有状态
伪造测试结果
```

---

# 五十六、最终交付报告

完成后输出结构化报告。

## 1. 基线

列出：

```text
实际 master commit
任务起始 commit
最终 commit
```

## 2. 修改前限制

说明：

```text
Planner Whole-Fill Gate
Order Reducer Whole-Fill 假设
平均价累计误差风险
Durable Fill Identity 缺失
```

## 3. Order Authority

说明：

* 新增字段；
* 新增不变量；
* 状态转换；
* PENDING_CANCEL 语义；
* Legacy 兼容。

## 4. Fill Identity

说明：

* Canonical Priority；
* Identity Schema Version；
* Scope；
* Transaction ID 与 Fill Identity 的区别。

## 5. Fill Fingerprint

列出正式参与字段和稳定序列化方式。

## 6. Duplicate / Conflict

说明：

```text
Same Identity + Same Payload
Same Identity + Different Payload
```

分别如何处理。

## 7. Fill Index

说明：

* 如何分配；
* 如何持久化；
* 如何保证重启稳定；
* 为什么不使用 Source Sequence。

## 8. Committed Fact

列出新增审计字段。

## 9. Persistence

说明：

* Memory Store；
* SQLite Store；
* Query Port；
* Legacy Round-Trip。

## 10. 产品 Gate

明确：

```text
Order Authority 已支持 Partial Fill
Runtime Product Partial Fill 仍 Fail Closed
```

## 11. 未修改的架构

明确：

```text
Commit Coordinator
Recovery
Event Gate
Checkpoint Finalization
Reservation Accounting
```

保持不变。

## 12. 测试结果

列出所有真实执行命令和结果。

## 13. 剩余边界

明确尚未完成：

```text
Reservation 分段消费
Risk Snapshot Multi-Fill
Order Fee Accrual
Account/Ledger Incremental Accounting
Virtual Broker Partial Schedule
Multi-Fill Recovery
SELL/CLOSE
```

## 14. 下一步

明确：

```text
PR4.3.2
Reservation、Risk、Fee、Account 与 Ledger
Incremental Multi-Fill Accounting
```

---

# 五十七、最终目标

PR4.3.1 完成后必须能够证明：

> OnlyAlpha 已建立稳定的部分成交订单权威模型。一个订单可以按确定顺序累积多个独立 Fill；每个 Fill 拥有稳定、持久、可冲突检测的业务身份和连续 Fill Index；订单的 Filled、Remaining、Fill Count、累计成交价值和平均成交价始终满足严格不变量。与此同时，完整 Runtime Partial Fill 产品路径仍保持 Fail Closed，直到 PR4.3.2 完成 Reservation 和 Accounting 的分段消费。
