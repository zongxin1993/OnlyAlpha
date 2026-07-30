# OnlyAlpha PR4.3.3：Virtual Broker 确定性 Partial Fill Plan 与端到端 Multi-Fill Recovery

## 一、任务目标

请在 OnlyAlpha 当前 `master` 分支上完成：

```text
PR4.3.3
Deterministic Virtual Broker Partial Fill Schedule
and End-to-End Multi-Fill Recovery
```

中文名称：

```text
PR4.3.3
Virtual Broker 确定性部分成交计划
与端到端 Multi-Fill Recovery
```

本任务的核心目标是：

> 将当前 Virtual Broker 基于 `maximum_fill_quantity` 的隐式按 Bar 限量成交，升级为显式、确定、可审计、可 Checkpoint、可跨 Engine Restart 继续执行的订单级 Fill Plan，并证明多个 Partial Fill 在任意 Broker、Commit、Projection、Outbox 和 Checkpoint 边界崩溃后，最终业务结果与无故障 Baseline 完全一致。

开始实现前，必须重新读取当前仓库源码、测试、ADR 和 Roadmap，不得只依据本提示词直接修改代码。

---

# 二、预期基线

当前预期 `master` 基线为：

```text
1274963617fff3b51af00ed682386845eeaa8f6b
Feat: Incremental Reservation and Accounting for Multi-Fill
```

如果实际 `master` 已经更新，以实际代码为准，并在预实施审计中说明：

1. 实际起始 Commit；
2. 与本提示词假设的差异；
3. 哪些工作已经被其他提交完成；
4. 哪些设计需要根据实际代码调整。

---

# 三、当前已完成能力

PR4.3.1 已完成：

```text
Order Partial-Fill Authority
Durable Fill Identity
Fill Payload Fingerprint
Per-Order Fill Index
Multi-Fill Committed Fact
Durable Fill Query
Legacy Whole-Fill Compatibility
```

PR4.3.2 已完成：

```text
Position / Allocation Exact Cost Authority
FILL / ORDER_CUMULATIVE Fee Scope
Order Fee Accrual
Account Cash Reservation Incremental Consumption
Strategy Cash Reservation Incremental Consumption
Risk Reservation Incremental Consumption
Account Incremental Accounting
Strategy Ledger Incremental Accounting
Risk Active Order Lifecycle
Product Partial Fill Transaction Path
```

当前正式执行路径已经支持：

```text
一个外部 BrokerTradeUpdate Fill
=
一个不可变 Prepared Transaction
=
一个 Durable Committed Transaction
=
一组 Ordered Projection
=
一个 Projection Ready Transaction
=
一组 Durable Outbox Intent
```

PR4.3.3 不得重新设计上述能力。

---

# 四、当前 Virtual Broker 的真实基础

当前 Virtual Broker 已经具备简单 Partial Fill 能力：

```text
maximum_fill_quantity
```

`OnlyNextBarMatchingEngine` 会选择：

```text
min(order.remaining_quantity, maximum_fill_quantity)
```

因此当前已经可以在多个满足条件的 Bar 上产生：

```text
300 → 300 → 300 → 100
```

当前 Gateway 已经保存：

```text
Account Store
Order Store
Trade Store
Accepted Bar
Latest Bars
Bar Sequence
Source Sequence
Trade Sequence
Venue Order Sequence
Scheduler
Connection State
Plugin State
```

Scheduler 已经支持 Checkpoint：

```text
due_ns
sequence
checkpoint_payload
```

并能恢复：

```text
ACCEPT
CANCEL
PUBLISH_FILL
```

PR4.3.3 不得推倒重写 Virtual Broker，而应在现有结构上增加：

```text
Explicit Fill Schedule
Normalized Fill Plan
Fill Plan Store
Fill Plan Cursor
Fill Plan Checkpoint
Stable Order Matching Order
Broker Restore Validation
End-to-End Recovery Matrix
```

---

# 五、关键范围

本任务正式支持：

```text
GENERIC_T0_CASH
CASH Account
LIMIT
BUY
OPEN
LONG
NETTING
Single Currency
No Margin
```

本任务必须完成：

```text
显式 Virtual Broker Partial Fill Schedule
maximum_fill_quantity 向 Fill Plan 的兼容归一化
跨 Bar Multi-Fill
可选同 Bar Multi-Fill
订单级 Fill Plan Authority
Fill Plan Checkpoint / Restore
Scheduler Pending Fill Restore
稳定 Broker Order 遍历顺序
Partial Fill 后 Cancel
Broker Execute 后 Publish 前恢复
Runtime Commit/Projection/Outbox 恢复
Checkpoint 覆盖部分 Fill 后继续
A→B→C Multi-Fill Restart Equivalence
旧 Partial Fill Integration Demo 更新
```

本任务不完成：

```text
SELL
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
Position Reservation 正式消费
MARKET Order 新语义
IOC
FOK
GTD 特殊终止
订单改单
真实订单簿
盘口深度
随机流动性
随机成交量
Futures
Margin
Paper Runtime Recovery
Live Runtime Recovery
Exactly-once
Subscriber ACK
Broker Fee Reconciliation
```

---

# 六、不可修改的核心架构

原则上不得修改：

```text
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/commit_coordinator.py
src/onlyalpha/execution/fill_identity.py
src/onlyalpha/execution/reducers/
src/onlyalpha/fee/accrual.py
src/onlyalpha/runtime/events/gate.py
src/onlyalpha/runtime/events/router.py
src/onlyalpha/runtime/recovery/finalizer.py
src/onlyalpha/runtime/recovery/outcome.py
```

必须保持：

```text
一个 Fill
=
一个不可变 Transaction
```

禁止：

```text
多个 Fill 合并为一个可变 Transaction
修改已 Commit Transaction
改变 Fill Identity 算法
改变 Fill Fingerprint 语义
改变 Fill Index 语义
新增 Multi-Fill Recovery Phase
修改 Event Gate Phase
修改 Outbox Delivery 语义
```

如果新测试发现上述模块存在真实缺陷，只允许做最小修复，并在最终报告中说明红色测试、根因和修复范围。

---

# 七、开始前必须重新审计的文件

至少读取：

```text
packages/fake/onlyalpha-plugin-broker-virtual/src/
onlyalpha_plugin_broker_virtual/
├── config.py
├── factory.py
├── matching.py
├── gateway.py
├── scheduler.py
├── stores.py
├── latency.py
├── slippage.py
└── descriptor.py
```

以及：

```text
packages/fake/onlyalpha-plugin-broker-virtual/tests/
```

Core 侧至少读取：

```text
src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/checkpoint/
src/onlyalpha/runtime/recovery/
src/onlyalpha/runtime/persistence/
src/onlyalpha/execution/
src/onlyalpha/broker/
```

重点读取现有测试：

```text
tests/integration/test_engine_recovery_same_bar_continuation.py
tests/integration/test_engine_recovery_multiple_continuations.py
tests/integration/test_engine_recovery_multi_boundary_tail.py
tests/integration/test_engine_recovery_three_stage_restart.py
tests/integration/test_engine_recovery_event_gate_three_stage_restart.py
tests/integration/test_engine_recovery_checkpoint_after_commit.py
tests/integration/test_engine_recovery_continuation_event_delivery.py
tests/integration/test_engine_recovery_finalization.py
```

旧场景：

```text
tests/integration_demo/scenarios/scenario_014_partial_fill.py
tests/integration_demo/scenarios/scenario_023_partial_fill_then_cancel.py
```

文档：

```text
docs/virtual_broker.md
docs/architecture.md
docs/execution.md
docs/execution_runtime_recovery.md
docs/roadmap.md
README.md
docs/adr/0049-partial-fill-order-authority-and-fill-identity.md
docs/adr/0050-incremental-multi-fill-reservation-and-accounting.md
```

重点搜索：

```bash
rg "maximum_fill_quantity"
rg "OnlyNextBarMatchingEngine"
rg "OnlyMatchingResult"
rg "PARTIALLY_FILLED"
rg "_accepted_bar"
rg "_bar_sequence"
rg "_trade_sequence"
rg "_source_sequence"
rg "_execute"
rg "PUBLISH_FILL"
rg "capture_checkpoint"
rg "restore_checkpoint"
rg "_resolve_scheduled_action"
rg "\"broker.virtual\""
rg "OnlyJsonRuntimeCheckpointParticipant"
rg "scenario_014"
rg "scenario_023"
rg "committed == \\(\\)"
```

---

# 八、预实施审计文档

新增：

```text
docs/reports/pr4_3_3_virtual_broker_multi_fill_recovery_audit.md
```

审计必须回答：

1. `maximum_fill_quantity` 当前如何产生 Partial Fill；
2. 当前每个 Bar 是否最多为每个订单产生一个 Fill；
3. 当前是否支持同 Bar 多 Fill；
4. 当前 Broker Order 如何保存 Filled Quantity；
5. 当前 Broker Order 是否显式保存 Remaining Quantity；
6. 当前 Trade ID、Venue Trade ID、Update ID 如何生成；
7. 当前 Source Sequence 如何推进；
8. 当前 Broker Execute 和 Broker Update Publish 是否分为两个阶段；
9. 当前 Broker Execute 后、Publish 前 Checkpoint 是否可以恢复；
10. 当前 Scheduler Payload 保存了哪些 Fill 数据；
11. 当前 Checkpoint 是否包含 Schema Version；
12. 当前 `broker.virtual` Participant Version 是多少；
13. 当前 Order Store 的遍历顺序是否依赖 Dict 插入顺序；
14. Checkpoint Restore 是否可能改变多订单撮合顺序；
15. 当前 Trade Query 顺序是否稳定；
16. 当前 Broker Account Store 如何消费部分成交的冻结资金；
17. Partial Fill 后 Cancel 当前如何释放剩余 Broker Reservation；
18. 当前 Integration Demo 中哪些断言已经过时；
19. 当前 Recovery Test Support 可以复用哪些故障 Store；
20. 当前是否已有相同 Bar 多 Transaction Continuation 测试；
21. 当前是否已有多 Boundary Transaction Tail Recovery；
22. PR4.3.3 是否需要新的 Recovery Phase；
23. PR4.3.3 是否需要修改 Commit Coordinator；
24. 本任务预计修改哪些生产文件；
25. 本任务明确不修改哪些文件。

审计完成前不得修改生产代码。

---

# 九、总体设计

实现以下正式链路：

```text
Virtual Broker Config
        │
        ▼
Fill Schedule Specification
        │
        ▼
Order Acceptance
        │
        ▼
Normalized Order Fill Plan
        │
        ▼
Virtual Fill Plan Store
        │
        ▼
Deterministic Bar Matching
        │
        ▼
Next Due Fill Step
        │
        ▼
Broker Execute
        │
        ▼
Broker Account / Order / Trade Projection
        │
        ▼
Scheduled BrokerTradeUpdate
        │
        ▼
Runtime ExecutionProcessor
        │
        ▼
Durable Multi-Fill Transaction
```

---

# 十、Fill Schedule 配置模型

## 10.1 建议配置格式

支持：

```yaml
brokers:
  - gateway_id: virtual-main
    plugin: virtual

    extensions:
      matching:
        type: NEXT_BAR

        partial_fill:
          mode: SCHEDULE
          dispatch_mode: ONE_PER_BAR

          steps:
            - bar_offset: 1
              ratio: "0.30"

            - bar_offset: 2
              ratio: "0.40"

            - bar_offset: 3
              ratio: "0.30"
```

明确数量形式：

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

---

## 10.2 正式模式

定义：

```python
class OnlyVirtualFillScheduleMode(StrEnum):
    WHOLE = "WHOLE"
    MAX_PER_BAR = "MAX_PER_BAR"
    SCHEDULE = "SCHEDULE"
```

定义：

```python
class OnlyVirtualFillDispatchMode(StrEnum):
    ONE_PER_BAR = "ONE_PER_BAR"
    ALL_DUE = "ALL_DUE"
```

语义：

### `WHOLE`

```text
每次满足价格条件时
一次成交全部 Remaining Quantity
```

### `MAX_PER_BAR`

兼容当前：

```text
maximum_fill_quantity
```

例如订单 1000、最大 300，归一化为：

```text
300 → 300 → 300 → 100
```

### `SCHEDULE`

显式配置：

```text
300 → 400 → 300
```

---

## 10.3 兼容要求

以下现有配置必须继续工作：

```yaml
maximum_fill_quantity: null
```

```yaml
maximum_fill_quantity: 300
```

建议内部统一归一化：

```text
null
→ WHOLE

300
→ MAX_PER_BAR
```

不得保留两条完全独立的 Partial Fill 执行链。

---

## 10.4 配置冲突

如果同时配置：

```text
maximum_fill_quantity
+
partial_fill.mode = SCHEDULE
```

必须 Fail Closed：

```text
VIRTUAL_FILL_POLICY_CONFLICT
```

如果 `MAX_PER_BAR` 同时配置不同的：

```text
maximum_fill_quantity
```

来源，也必须拒绝冲突值。

---

## 10.5 未知字段

Factory 必须继续拒绝：

```text
未知 extensions 字段
未知 matching 字段
未知 partial_fill 字段
未知 step 字段
```

不得静默忽略配置错误。

---

# 十一、Fill Schedule Domain

建议新增：

```text
packages/fake/onlyalpha-plugin-broker-virtual/src/
onlyalpha_plugin_broker_virtual/fill_plan.py
```

定义配置 Step：

```python
@dataclass(frozen=True, slots=True)
class OnlyVirtualFillScheduleStepSpec:
    bar_offset: int
    quantity: Decimal | None = None
    ratio: Decimal | None = None
```

不变量：

```text
bar_offset >= 1
quantity 和 ratio 必须且只能存在一个
quantity > 0
0 < ratio <= 1
```

归一化 Step：

```python
@dataclass(frozen=True, slots=True)
class OnlyVirtualFillPlanStep:
    step_index: int
    bar_offset: int
    quantity: OnlyQuantity
```

---

# 十二、Ratio 归一化

例如：

```text
Order Quantity = 1000
Ratio = 0.30 / 0.40 / 0.30
```

结果：

```text
300 / 400 / 300
```

如果订单数量为 101：

```text
30 / 40 / 31
```

建议算法：

1. 前 `N-1` 个 Step 使用 Quantity Precision 向下量化；
2. 最后一个 Step 接收全部 Remaining；
3. 最终严格校验所有 Step Quantity 之和等于 Original Quantity。

必须保证：

```text
sum(normalized step quantity)
==
order.quantity
```

不得通过独立四舍五入产生 Overfill 或 Underfill。

---

# 十三、Schedule 校验

显式 Schedule 必须满足：

```text
至少一个 Step
step_index 从 1 开始连续
bar_offset 非递减
所有 quantity > 0
归一化后总量 == Order Quantity
```

相同 `bar_offset` 仅允许在：

```text
dispatch_mode = ALL_DUE
```

时产生同 Bar 多 Fill。

如果：

```text
dispatch_mode = ONE_PER_BAR
```

而多个 Step 使用相同 Bar Offset，应明确：

* 拒绝配置；或
* 后续每个 Bar 顺序执行一个。

推荐直接拒绝，避免配置语义模糊。

---

# 十四、订单级 Fill Plan Authority

新增：

```python
class OnlyVirtualFillPlanStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
```

定义：

```python
@dataclass(frozen=True, slots=True)
class OnlyVirtualOrderFillPlan:
    order_id: OnlyOrderId
    venue_order_id: OnlyVenueOrderId

    plan_id: str
    plan_fingerprint: str

    original_quantity: OnlyQuantity
    accepted_bar_sequence: int

    mode: OnlyVirtualFillScheduleMode
    dispatch_mode: OnlyVirtualFillDispatchMode
    steps: tuple[OnlyVirtualFillPlanStep, ...]

    next_step_index: int
    status: OnlyVirtualFillPlanStatus
    version: int
```

---

# 十五、Fill Plan 不变量

必须保证：

```text
plan_id 以 VPLAN- 开头
plan_fingerprint 为稳定 SHA-256
original_quantity > 0
accepted_bar_sequence >= 0
steps 非空
next_step_index 范围为 [0, len(steps)]
version >= 1
```

总量：

```text
sum(step.quantity)
=
original_quantity
```

ACTIVE：

```text
next_step_index < len(steps)
```

COMPLETED：

```text
next_step_index == len(steps)
```

CANCELLED：

```text
next_step_index <= len(steps)
```

执行量：

```text
sum(steps[:next_step_index].quantity)
=
Broker Order filled_quantity
```

剩余量：

```text
sum(steps[next_step_index:].quantity)
=
Broker Order remaining_quantity
```

---

# 十六、Plan ID 与 Fingerprint

使用稳定 Canonical JSON 和 SHA-256。

参与字段：

```text
schema_version
gateway_id
account_id
order_id
venue_order_id
original_quantity
quantity_precision
mode
dispatch_mode
normalized_steps
```

建议：

```text
VPLAN-<sha256>
```

禁止：

```text
Python hash()
repr()
对象内存地址
当前系统时间
随机 UUID
```

Plan Identity 只属于 Virtual Broker 外部模拟状态。

它不替代 Runtime 的：

```text
Transaction ID
Fill Identity
Fill Fingerprint
Fill Index
```

---

# 十七、Fill Plan Store

新增：

```text
fill_plan_store.py
```

建议接口：

```python
class OnlyVirtualFillPlanStore:
    def save(self, plan: OnlyVirtualOrderFillPlan) -> None: ...
    def get(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan | None: ...
    def require(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan: ...
    def advance(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan: ...
    def cancel(self, order_id: OnlyOrderId) -> OnlyVirtualOrderFillPlan: ...
    def list(self) -> tuple[OnlyVirtualOrderFillPlan, ...]: ...
    def capture_checkpoint(self) -> object: ...
    def restore_checkpoint(self, payload: object) -> None: ...
```

要求：

```text
保存不可变 Plan Snapshot
按 Order ID 唯一
版本严格递增
COMPLETED/CANCELLED 不允许再次 advance
Checkpoint 顺序稳定
```

---

# 十八、Plan 创建时机

在 Broker Order Acceptance 阶段创建 Plan。

推荐顺序：

```text
1. 重新读取 Submitted Order
2. 验证订单仍为 SUBMITTED
3. 解析价格和资金需求
4. 归一化 Fill Plan
5. 验证 Plan
6. 冻结 Broker 资金
7. 保存 ACCEPTED Broker Order
8. 保存 Fill Plan
9. 保存 accepted_bar_sequence
10. 发布 Order Accepted Update
```

如果 Plan 创建或校验失败：

```text
不得冻结资金
不得保存 ACCEPTED Order
不得保存部分 Plan
```

不得出现：

```text
Order ACCEPTED
但无 Fill Plan
```

---

# 十九、稳定 Order Matching 顺序

当前 `OrderStore.open()` 不得继续依赖字典插入顺序。

正式顺序建议：

```python
sorted(
    open_orders,
    key=lambda order: (
        str(order.venue_order_id),
        str(order.order_id),
    ),
)
```

要求：

```text
Fresh Run
Checkpoint Capture
Checkpoint Restore
```

后的订单遍历顺序完全一致。

Trade Query 建议稳定排序：

```text
source_sequence
trade_id
```

Order Query 建议稳定排序：

```text
venue_order_id
order_id
```

---

# 二十、Bar Offset 语义

定义：

```text
elapsed_bar_offset
=
current_bar_sequence
-
accepted_bar_sequence
```

`bar_offset` 表示：

> 该 Step 最早允许执行的 Bar Offset。

如果到期 Bar 未满足价格条件，不丢弃 Step。

例如：

```text
Step 1 bar_offset = 1

Bar 1 未触价
Bar 2 未触价
Bar 3 触价
```

Step 1 在 Bar 3 执行。

禁止将未触价 Step 视为自动跳过。

---

# 二十一、Dispatch Mode

## 21.1 `ONE_PER_BAR`

每个订单每个 Bar 最多执行一个 Due Step。

适用于：

```text
MAX_PER_BAR
普通跨 Bar Schedule
```

例如：

```text
Bar 1 → 300
Bar 2 → 400
Bar 3 → 300
```

## 21.2 `ALL_DUE`

同一个 Bar 内按 Step Index 执行所有到期且价格满足的 Step。

例如：

```text
Step 1 bar_offset = 1 quantity = 300
Step 2 bar_offset = 1 quantity = 400
Step 3 bar_offset = 2 quantity = 300
```

结果：

```text
Bar 1
→ Fill 1 = 300
→ Fill 2 = 400

Bar 2
→ Fill 3 = 300
```

每个 Fill 必须拥有独立：

```text
Trade ID
Venue Trade ID
External Event ID
Broker Update ID
Source Sequence
Transaction ID
Fill Index
```

---

# 二十二、Gateway `on_bar()` 方案

推荐执行顺序：

```text
1. run_due()
2. bar_sequence += 1
3. 更新 Account Mark
4. 更新 Trading Day
5. 读取稳定排序后的 Open Orders
6. 对每个 Order：
   6.1 读取 Fill Plan
   6.2 检查状态 ACTIVE
   6.3 检查 Acceptance Bar 边界
   6.4 检查价格是否满足
   6.5 选择 Due Step
   6.6 执行一个或多个 Step
7. 更新 latest_bars
8. run_due()
```

不得使用：

```text
系统时间
sleep
随机数
线程竞态
非持久隐式状态
```

---

# 二十三、执行 Plan Step

将当前 `_execute()` 重构为类似：

```python
def _execute_plan_step(
    self,
    order: OnlyBrokerOrderSnapshot,
    plan: OnlyVirtualOrderFillPlan,
    step: OnlyVirtualFillPlanStep,
    raw_price: OnlyPrice,
    timestamp: OnlyTimestamp,
) -> None:
    ...
```

正式步骤：

```text
1. 重新读取最新 Order
2. 重新读取最新 Plan
3. 验证 Plan ACTIVE
4. 验证 Step 是 next_step_index
5. 验证 Step Quantity <= Remaining
6. 应用 Slippage
7. 生成稳定 Broker Fill Identity
8. 预计算 Account/Order/Trade/Plan After
9. 更新 Broker Account Store
10. 更新 Broker Order Store
11. 保存 Broker Trade Store
12. 推进 Fill Plan Cursor
13. Schedule PUBLISH_FILL
```

最终 Step：

```text
Order = FILLED
Plan = COMPLETED
```

中间 Step：

```text
Order = PARTIALLY_FILLED
Plan = ACTIVE
```

---

# 二十四、Broker 状态原子边界

Virtual Broker 当前不是数据库事务系统，但单线程方法内仍必须保持一致更新顺序。

任何可预见错误必须在状态修改前验证：

```text
Step Index
Quantity
Order Status
Plan Status
Remaining Quantity
Account Reservation
```

不得在更新 Account 后才发现 Plan 无效。

建议先构造全部 After Snapshot，再按固定顺序写入：

```text
Account
Order
Trade
Plan
Scheduler
```

如果生产方法内存在不可恢复异常，Gateway 应进入 FAILED，而不是继续产生后续 Fill。

---

# 二十五、Broker Fill Identity

当前 ID 格式可以继续使用：

```text
virtual-trade-XXXXXXXX
virtual-venue-trade-XXXXXXXX
virtual-fill-XXXXXXXX
virtual-update-XXXXXXXX
```

不需要修改 Runtime Fill Identity 算法。

必须通过以下条件保证重启稳定：

```text
稳定 Order Matching 顺序
稳定 Fill Step 顺序
持久化 Source Sequence
持久化 Trade Sequence
持久化 Scheduler Payload
持久化 Broker Order/Trade Store
持久化 Fill Plan Cursor
```

增加测试证明相同输入下：

```text
Fresh Baseline IDs
==
Restart Execution IDs
```

---

# 二十六、成交与发布的分离

必须明确三个阶段：

```text
PLANNED
→ BROKER_EXECUTED
→ PUBLISHED_TO_RUNTIME
```

Broker `_execute_plan_step()` 完成后：

```text
Broker Account 已更新
Broker Order 已更新
Broker Trade 已保存
Plan Cursor 已推进
```

随后才 Schedule：

```text
PUBLISH_FILL
```

因此可能存在 Checkpoint：

```text
Broker 已成交
Runtime 尚未收到 Fill
```

恢复时必须：

```text
只执行 PUBLISH_FILL
不得重新执行 Broker 成交
```

---

# 二十七、Scheduler Payload

当前 `PUBLISH_FILL` Payload 已保存完整 Fill JSON，应继续保留。

建议扩展为：

```json
{
  "type": "PUBLISH_FILL",
  "order_id": "...",
  "plan_id": "...",
  "plan_step_index": 1,
  "fill": "...",
  "sequence": 10,
  "timestamp_ns": 123
}
```

恢复时验证：

```text
Plan Cursor 已经越过该 Step
Trade Store 中存在该 Trade
Broker Order Filled Quantity 已包含该 Fill
Sequence <= Source Sequence Head
```

如果不一致：

```text
VIRTUAL_BROKER_SCHEDULED_FILL_AUTHORITY_CONFLICT
```

---

# 二十八、Checkpoint V2

## 28.1 Gateway Payload Schema

新增：

```json
{
  "schema_version": 2,
  "fill_plans": [],
  "accepted_bar": [],
  "account": {},
  "bar_sequence": 0,
  "connection_state": "...",
  "current_day": null,
  "latest_bars": [],
  "orders": [],
  "plugin_state": "...",
  "scheduler": {},
  "source_sequence": 0,
  "state_time_ns": 0,
  "trade_sequence": 0,
  "trades": [],
  "venue_order_sequence": 0
}
```

## 28.2 Participant Version

将 Runtime 注册：

```text
broker.virtual
version = 1
```

升级为：

```text
broker.virtual
version = 2
```

OnlyAlpha 当前采用严格 Participant Registry Fingerprint。

旧 Version 1 Checkpoint 应：

```text
Fail Fast
```

不得伪造旧订单的 Fill Plan。

---

# 二十九、Checkpoint Restore 顺序

推荐：

```text
1. 校验 Gateway schema_version
2. 恢复 Account Store
3. 恢复 Order Store
4. 恢复 Trade Store
5. 恢复 Fill Plan Store
6. 恢复 accepted_bar
7. 恢复 bar_sequence/current_day/latest_bars
8. 恢复 connection/plugin state
9. 恢复 source/trade/venue sequences
10. 恢复 Scheduler
11. 执行 Broker Authority Validation
```

Scheduler 必须在依赖状态恢复完成后恢复。

---

# 三十、Broker Restore Authority Validation

新增纯验证器，例如：

```python
class OnlyVirtualBrokerCheckpointAuthorityValidator:
    def validate(self, gateway: OnlyVirtualBrokerGateway) -> None:
        ...
```

至少验证：

## Plan 与 Order

```text
plan.original_quantity == order.quantity
```

```text
sum(executed steps) == order.filled_quantity
```

```text
sum(pending steps) == order.remaining_quantity
```

## Plan Status

```text
ACTIVE
→ Order ACCEPTED 或 PARTIALLY_FILLED
```

```text
COMPLETED
→ Order FILLED
```

```text
CANCELLED
→ Order CANCELLED
```

## Plan 与 Trade

```text
已执行 Step 数量
==
该订单 Broker Trade 数量
```

每个 Trade Quantity 必须与对应 Plan Step Quantity 一致。

## Scheduler

每个 `PUBLISH_FILL`：

```text
对应 Trade 已存在
Plan Cursor 已推进
Order Filled Quantity 已包含该 Fill
```

## Sequence

```text
Source Sequence Head
>= 所有 Order/Trade/Scheduled Fill Sequence
```

失败：

```text
VIRTUAL_BROKER_CHECKPOINT_AUTHORITY_CONFLICT
```

恢复失败必须 Fail Closed。

---

# 三十一、Partial Fill 后 Cancel

当前 Cancel 允许：

```text
ACCEPTED
PARTIALLY_FILLED
```

PR4.3.3 必须增加 Fill Plan 处理。

Cancel 顺序：

```text
1. 读取最新 Order
2. 读取 Fill Plan
3. 验证 Order 非终态
4. 释放 Broker 剩余 Reservation
5. Order → CANCELLED
6. Plan → CANCELLED
7. 保存 Order 和 Plan
8. 发布 Order Cancelled Update
```

未来所有 Pending Step 必须失效。

Scheduler 中如果存在尚未发布、但 Broker 已执行的 Fill：

```text
该 Fill 仍必须发布
```

因为成交事实已经发生。

只取消尚未 Broker Execute 的 Plan Step。

---

# 三十二、现有 Integration Demo 更新

必须更新：

```text
tests/integration_demo/scenarios/scenario_014_partial_fill.py
```

旧断言：

```python
committed == ()
```

已经失效。

新合同：

```text
Virtual Broker 产生 40/100 Partial Fill
→ Runtime 生成一个 Projection Ready Transaction
→ Order = PARTIALLY_FILLED
→ Filled = 40
→ Remaining = 60
→ Account Reservation = PARTIALLY_CONSUMED
→ Strategy Reservation = PARTIALLY_CONSUMED
→ Risk Active Count = 1
→ Fill Index = 1
```

更新：

```text
tests/integration_demo/scenarios/scenario_023_partial_fill_then_cancel.py
```

验证：

```text
部分成交保留
剩余订单取消
剩余 Broker Reservation 释放
剩余 Runtime Reservation 释放
Plan = CANCELLED
未来 Bar 不再成交
```

---

# 三十三、恢复方案

不得新增 Recovery Phase。

继续复用：

```text
Checkpoint Restore
→ Exact MarketData Replay
→ Stored Transaction Rehydration
→ Unprojected Transaction Recovery
→ Same-Bar / Later-Bar Continuation
→ Post-Recovery Authority Validation
→ Durable Finalization
→ Event Gate OPEN
```

PR4.3.3 只增加：

```text
Virtual Broker Fill Plan 状态
Broker Checkpoint Authority Validation
Multi-Fill Recovery 测试矩阵
```

---

# 三十四、故障边界一：Fill 尚未 Broker Execute

Checkpoint：

```text
Plan next_step_index = 0
Broker Order filled = 0
无 Trade
无 PUBLISH_FILL
```

恢复后：

```text
从 Step 1 正常执行
```

---

# 三十五、故障边界二：Broker Execute 后、Publish 前

Checkpoint：

```text
Plan next_step_index = 1
Broker Order filled = 300
Trade Store 存在 Fill 1
Scheduler 存在 PUBLISH_FILL 1
Runtime 尚无 Transaction 1
```

恢复后：

```text
不重新执行 Broker Fill
只恢复 PUBLISH_FILL
Runtime 正常 Commit Transaction 1
```

Broker Account 和 Position 不得重复增加。

---

# 三十六、故障边界三：Broker Update 已发布、Commit 前

如果 Runtime 尚无 Transaction：

```text
恢复并重放相同 Bar
→ 产生相同 Fill Identity
→ 正常 Commit
```

如果 Update 已存在于 Dedup/Queue Checkpoint，应根据当前正式 Execution Processor 合同恢复。

不得为此修改 Fill Identity。

---

# 三十七、故障边界四：Commit 后、Projection 前

Store：

```text
Transaction committed
projection_ready = false
```

恢复：

```text
重建相同 Prepared Transaction
验证 Stored Prepared
恢复剩余 Projection
标记 Projection Ready
```

不得重复：

```text
Position Quantity
Account Cash
Reservation Consumption
Fee Accrual
Risk Consumption
```

---

# 三十八、故障边界五：Projection Ready、Outbox 未投递

恢复：

```text
不重复 Projection
不重复 Broker Fill
Runtime Event Gate OPEN 后交付 Pending Outbox
继续后续 Fill Plan
```

保持：

```text
Outbox = at-least-once
Direct Event = best-effort
```

---

# 三十九、故障边界六：Checkpoint 已覆盖部分 Fill

## 覆盖 Fill 1

Checkpoint：

```text
Runtime Fill Index = 1
Broker Plan next_step_index = 1
Order remaining = 700
```

恢复后只产生：

```text
Fill 2
Fill 3
```

## 覆盖 Fill 1、2

恢复后只产生：

```text
Fill 3
```

---

# 四十、故障边界七：最终 Fill 后崩溃

恢复后必须保持：

```text
Broker Order = FILLED
Fill Plan = COMPLETED
Runtime Order = FILLED
Position = Full Quantity
Reservations = CONSUMED / RELEASED
Risk Active Count = 0
无 Pending Plan Step
无重复 Fill
```

---

# 四十一、同 Bar Multi-Fill

配置：

```yaml
dispatch_mode: ALL_DUE
steps:
  - bar_offset: 1
    quantity: "300"
  - bar_offset: 1
    quantity: "400"
  - bar_offset: 2
    quantity: "300"
```

第一个满足条件的 Bar 必须依次产生：

```text
Fill 1 = 300
Fill 2 = 400
```

要求：

```text
Fill Index = 1, 2
不同 Trade ID
不同 Venue Trade ID
不同 Update ID
不同 Transaction ID
连续 Source Sequence
连续 Execution Sequence
稳定 Projection 顺序
```

在 Fill 1 和 Fill 2 之间崩溃时，恢复后只能继续 Fill 2，不得重新执行 Fill 1。

---

# 四十二、A→B→C 三阶段恢复

建立无故障 Baseline：

```text
Fill 1 = 300
Fill 2 = 400
Fill 3 = 300
```

Engine A：

```text
在 Fill 1 的指定边界失败
```

Engine B：

```text
恢复 Fill 1
继续 Fill 2
在另一个边界失败
```

Engine C：

```text
恢复 Fill 2
继续 Fill 3
完成运行
```

最终要求：

```text
Baseline
==
A→B
==
A→B→C
```

---

# 四十三、最终等价性比较

必须比较 Runtime 正式 Authority：

```text
Order
Committed Transactions
Trades
Position
Allocation
Settlement
Fee Records
Order Fee Accrual
Account
Strategy Ledger
Account Cash Reservation
Strategy Cash Reservation
Risk Reservation
Risk Snapshot
Valuation
Canonical Business Projection
Result Fingerprint
Artifact Manifest
```

还应比较 Virtual Broker Projection：

```text
Broker Order Snapshot
Broker Trade Snapshots
Broker Position Snapshot
Broker Balance Snapshot
Fill Plan Final State
Source Sequence Head
Trade Sequence Head
Venue Order Sequence Head
```

Broker Projection 不得进入 Runtime Result Fingerprint。

---

# 四十四、事件等价性

不要求完整 Direct Event Stream 相等。

必须验证：

```text
每个 Projection Ready Transaction
拥有完整 Durable Outbox Intent
```

验证最终：

```text
Pending/Published Outbox 状态符合现有合同
```

不得要求：

```text
所有 Direct Event 次数完全一致
所有 Event 时间完全一致
Exactly-once Delivery
Subscriber ACK
```

---

# 四十五、测试故障注入

禁止增加生产配置：

```text
crash_after_fill
fail_after_fill
fault_switch
fault_injection
```

继续使用测试 Wrapper：

```text
OnlyFailOnceRuntimePersistenceStore
OnlyAfterCommitStore
OnlyFailNthProjectionTarget
OnlyFailNthDurablePublicationPort
自定义 Test Store Factory
自定义 Test Scheduler
```

故障注入必须位于测试代码。

---

# 四十六、测试工作包一：配置

新增：

```text
packages/fake/onlyalpha-plugin-broker-virtual/tests/
test_virtual_fill_schedule_config.py
```

覆盖：

1. 默认 WHOLE；
2. 旧 `maximum_fill_quantity` → MAX_PER_BAR；
3. 显式 SCHEDULE Quantity；
4. 显式 SCHEDULE Ratio；
5. ONE_PER_BAR；
6. ALL_DUE；
7. Quantity 和 Ratio 同时配置；
8. Quantity 和 Ratio 都未配置；
9. Ratio 非法；
10. Bar Offset 非法；
11. 空 Steps；
12. 未知字段；
13. 新旧配置冲突；
14. Factory Validation；
15. Entry Point 构造。

---

# 四十七、测试工作包二：Plan Normalization

新增：

```text
test_virtual_fill_plan_normalization.py
```

覆盖：

1. 1000 → 300/400/300；
2. 101 → 30/40/31；
3. Quantity Precision；
4. MAX_PER_BAR 1000/300；
5. WHOLE；
6. Sum 精确相等；
7. Overfill；
8. Underfill；
9. Step Index；
10. Stable Plan ID；
11. Stable Fingerprint；
12. 不使用 Python Hash；
13. Config 顺序稳定；
14. Serialize/Deserialize。

---

# 四十八、测试工作包三：Plan Store

新增：

```text
test_virtual_fill_plan_store.py
```

覆盖：

1. Save/Get/Require；
2. Duplicate Order；
3. Advance；
4. Version；
5. Complete；
6. Cancel；
7. Terminal Advance Reject；
8. Checkpoint Round-Trip；
9. Stable List Order；
10. Corrupt Payload Reject。

---

# 四十九、测试工作包四：Gateway Schedule

新增：

```text
test_virtual_fill_schedule_matching.py
test_virtual_fill_same_bar_schedule.py
test_virtual_fill_ordering.py
```

覆盖：

1. 跨 Bar 300/400/300；
2. Price 未触及时不丢 Step；
3. 最终 Filled；
4. MAX_PER_BAR 兼容；
5. WHOLE 兼容；
6. ALL_DUE 同 Bar两个 Fill；
7. 多 Order 稳定顺序；
8. Restart 前后 ID 稳定；
9. Source Sequence 稳定；
10. Trade Query 稳定排序。

---

# 五十、测试工作包五：Broker Checkpoint

新增：

```text
test_virtual_fill_plan_checkpoint.py
test_virtual_fill_publish_checkpoint.py
```

覆盖：

1. Fill 前 Checkpoint；
2. Fill 1 后 Checkpoint；
3. Fill 1、2 后 Checkpoint；
4. Completed Plan；
5. Cancelled Plan；
6. Broker Execute 后 Publish 前；
7. Scheduler Pending Fill；
8. Sequence Restore；
9. Plan/Order Conflict；
10. Plan/Trade Conflict；
11. Plan/Scheduler Conflict；
12. Schema Version Reject；
13. Participant Version 2。

---

# 五十一、测试工作包六：Partial Fill Cancel

新增：

```text
test_virtual_partial_fill_then_cancel.py
```

验证：

```text
Fill 1 已发生
剩余 Plan Cancelled
未来 Bar 不再 Fill
已有 Broker Trade 保留
剩余 Broker Frozen Cash 释放
Runtime Reservation 最终释放
```

---

# 五十二、测试工作包七：正式 Engine Multi-Fill

新增：

```text
tests/integration/test_engine_virtual_broker_multi_fill.py
```

要求通过真正的：

```text
Strategy
→ Order Submission
→ Virtual Broker
→ Broker Inbound Queue
→ ExecutionProcessor
→ Durable Transaction
```

自动运行：

```text
300 → 400 → 300
```

验证：

```text
3 Broker Trades
3 Committed Transactions
Fill Index 1/2/3
3 Projection Ready
Order Partial/Partial/Filled
Position 300/700/1000
Risk Active 1/1/0
最终 Reservation 终结
```

不得直接手工调用 `ExecutionProcessor.process()` 注入三个 Fill 代替 Virtual Broker。

---

# 五十三、测试工作包八：Same-Bar Multi-Fill

新增：

```text
tests/integration/test_engine_virtual_broker_same_bar_multi_fill.py
```

验证：

```text
同一 Bar 两个 Fill
两个独立 Transaction
连续 Source/Execution/Fill Index
Strategy 和 Result 观察顺序确定
```

---

# 五十四、测试工作包九：Recovery Matrix

新增：

```text
tests/integration/test_engine_recovery_multi_fill_before_commit.py
tests/integration/test_engine_recovery_multi_fill_after_commit.py
tests/integration/test_engine_recovery_multi_fill_projection_tail.py
tests/integration/test_engine_recovery_multi_fill_outbox.py
tests/integration/test_engine_recovery_multi_fill_checkpoint_continuation.py
tests/integration/test_engine_recovery_multi_fill_three_stage_restart.py
```

分别覆盖：

```text
Broker Fill 尚未执行
Broker Execute 后 Publish 前
Runtime Commit 前
Commit 后 Projection 前
Projection Ready 后 Outbox 前
Checkpoint 覆盖 Fill 1
Checkpoint 覆盖 Fill 1、2
A→B→C
```

---

# 五十五、测试工作包十：Architecture Gate

新增：

```text
tests/architecture/test_virtual_broker_multi_fill_recovery_architecture.py
```

至少检查：

1. Core 不包含 Virtual Broker 实现；
2. Fill Plan 位于插件包；
3. Fill Plan 不依赖 Runtime Manager；
4. Gateway 不导入 Runtime Order/Position/Account Manager；
5. Gateway 不访问 Execution Store；
6. Fill Plan 不替代 Runtime Fill Identity；
7. Transaction 仍不可变；
8. Commit Coordinator 未修改；
9. Recovery Phase 未新增；
10. Event Gate 未修改；
11. Runtime Reducer 未修改；
12. Fee Accrual 未修改；
13. 生产代码无 Fault Switch；
14. Open Order 排序稳定；
15. Plan ID 使用 SHA-256；
16. Broker Checkpoint Schema Version 为 2；
17. `broker.virtual` Participant Version 为 2；
18. 不实现 SELL/CLOSE；
19. 不实现 Margin；
20. 不实现订单簿。

---

# 五十六、文档

新增：

```text
docs/adr/0051-virtual-broker-partial-fill-plan-and-multi-fill-recovery.md
```

ADR 必须说明：

1. 当前 `maximum_fill_quantity` 的能力和限制；
2. 为什么增加显式 Fill Plan；
3. WHOLE、MAX_PER_BAR、SCHEDULE；
4. ONE_PER_BAR、ALL_DUE；
5. Ratio 归一化；
6. Plan ID/Fingerprint；
7. Plan Store；
8. Plan 与 Broker Order/Trade 的关系；
9. Broker Execute 与 Runtime Publish 的分离；
10. Stable Order Matching Order；
11. Checkpoint V2；
12. Participant Version 2；
13. Broker Restore Authority Validation；
14. Partial Fill 后 Cancel；
15. Recovery Matrix；
16. 为什么不新增 Recovery Phase；
17. 为什么不修改 Commit Coordinator；
18. PR4.3.3 的正式限制；
19. PR4.4 SELL/CLOSE 的后续范围。

更新：

```text
docs/virtual_broker.md
docs/architecture.md
docs/execution.md
docs/execution_runtime_recovery.md
docs/roadmap.md
README.md
```

Roadmap 标记：

```text
PR4.3.3
Virtual Broker Partial Fill Plan
与 End-to-End Multi-Fill Recovery
完成
```

---

# 五十七、建议生产文件

主要修改：

```text
packages/fake/onlyalpha-plugin-broker-virtual/src/
onlyalpha_plugin_broker_virtual/
├── config.py
├── factory.py
├── matching.py
├── gateway.py
├── scheduler.py
└── stores.py
```

建议新增：

```text
fill_plan.py
fill_plan_store.py
```

Core 预期只需要修改：

```text
src/onlyalpha/runtime/backtest/runtime.py
```

用于将：

```text
broker.virtual participant version
1 → 2
```

如果修改更多 Core 文件，最终报告必须解释必要性。

---

# 五十八、推荐实现顺序

## Commit 1：Audit 与 ADR

冻结配置、Plan、Checkpoint 和 Recovery 合同。

## Commit 2：Fill Plan Domain

实现：

```text
Schedule Mode
Dispatch Mode
Step Spec
Normalization
Plan
Plan ID/Fingerprint
Plan Store
```

## Commit 3：Factory 与 Config

实现配置解析、兼容和严格校验。

## Commit 4：Gateway Integration

实现：

```text
Acceptance 创建 Plan
Stable Order Sort
Due Step
Plan Step Execution
Plan Cancel
```

## Commit 5：Checkpoint V2

实现：

```text
Fill Plan Store Capture/Restore
Schema Version 2
Participant Version 2
Broker Authority Validation
Scheduler Pending Fill Validation
```

## Commit 6：Plugin Tests 与旧场景迁移

更新 `scenario_014`、`scenario_023`。

## Commit 7：Engine Multi-Fill

完成自动 300/400/300 正式纵切面。

## Commit 8：Recovery Matrix

完成 Broker、Commit、Projection、Outbox、Checkpoint 和 A→B→C。

## Commit 9：Architecture、Docs 与 Full Regression

---

# 五十九、必须执行的测试

至少执行：

```bash
uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_schedule_config.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_plan_normalization.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_plan_store.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_schedule_matching.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_same_bar_schedule.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_plan_checkpoint.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_publish_checkpoint.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_fill_ordering.py -q

uv run pytest \
  packages/fake/onlyalpha-plugin-broker-virtual/tests/test_virtual_partial_fill_then_cancel.py -q

uv run pytest tests/integration/test_engine_virtual_broker_multi_fill.py -q
uv run pytest tests/integration/test_engine_virtual_broker_same_bar_multi_fill.py -q

uv run pytest tests/integration/test_engine_recovery_multi_fill_before_commit.py -q
uv run pytest tests/integration/test_engine_recovery_multi_fill_after_commit.py -q
uv run pytest tests/integration/test_engine_recovery_multi_fill_projection_tail.py -q
uv run pytest tests/integration/test_engine_recovery_multi_fill_outbox.py -q
uv run pytest tests/integration/test_engine_recovery_multi_fill_checkpoint_continuation.py -q
uv run pytest tests/integration/test_engine_recovery_multi_fill_three_stage_restart.py -q

uv run pytest \
  tests/architecture/test_virtual_broker_multi_fill_recovery_architecture.py -q
```

---

# 六十、完整质量门禁

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

uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest tests/execution -q
uv run pytest tests/order -q
uv run pytest tests/position -q
uv run pytest tests/account -q
uv run pytest tests/strategy_ledger -q
uv run pytest tests/risk -q
uv run pytest tests/fee -q
uv run pytest tests/runtime/checkpoint -q
uv run pytest tests/runtime/recovery -q
uv run pytest tests/integration -q
uv run pytest tests/integration_demo -q
uv run pytest tests/architecture -q

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

# 六十一、完成标准

只有全部满足才能声明 PR4.3.3 完成：

1. 旧 `maximum_fill_quantity` 配置保持兼容；
2. 新增 WHOLE 模式；
3. 新增 MAX_PER_BAR 模式；
4. 新增 SCHEDULE 模式；
5. 新增 ONE_PER_BAR；
6. 新增 ALL_DUE；
7. 支持 Quantity Steps；
8. 支持 Ratio Steps；
9. Ratio 归一化总量严格守恒；
10. 新旧配置冲突 Fail Closed；
11. Fill Plan 为独立 Broker Authority；
12. Plan 有稳定 ID；
13. Plan 有稳定 Fingerprint；
14. Plan Cursor 严格推进；
15. Plan 可 Checkpoint/Restore；
16. Broker Checkpoint Schema 升级为 2；
17. `broker.virtual` Participant 升级为 2；
18. 旧不兼容 Checkpoint Fail Fast；
19. Restore 后 Plan 与 Order 一致；
20. Restore 后 Plan 与 Trade 一致；
21. Restore 后 Scheduler Pending Fill 一致；
22. Open Order 撮合顺序稳定；
23. Trade Query 顺序稳定；
24. 跨 Bar 300/400/300 自动运行；
25. 同 Bar Multi-Fill 自动运行；
26. 每个 Step 产生独立 Broker Fill；
27. 每个 Fill 产生独立 Runtime Transaction；
28. Fill Index 连续；
29. Source Sequence 连续；
30. Execution Sequence 连续；
31. Broker Execute 后 Publish 前可恢复；
32. Commit 前可恢复；
33. Commit 后 Projection 前可恢复；
34. Projection Ready 后 Outbox 前可恢复；
35. Checkpoint 覆盖 Fill 1 后从 Fill 2 继续；
36. Checkpoint 覆盖 Fill 1、2 后只执行 Fill 3；
37. 最终 Fill 后恢复不重复成交；
38. Partial Fill 后 Cancel 不执行剩余 Step；
39. Duplicate Fill 不重复记账；
40. Conflict Fill Fail Closed；
41. `scenario_014` 迁移为正式 Transaction；
42. `scenario_023` 验证 Plan Cancel；
43. A→B 与 Baseline 等价；
44. A→B→C 与 Baseline 等价；
45. Canonical Business Projection 等价；
46. Result Fingerprint 等价；
47. Artifact Manifest 等价；
48. Broker Final Projection 等价；
49. 不新增 Recovery Phase；
50. 不重构 Commit Coordinator；
51. 不修改 Event Gate；
52. 不修改 PR4.3.2 Accounting；
53. 不实现 SELL/CLOSE；
54. 不实现 Margin；
55. 不增加生产 Fault Switch；
56. Ruff、Mypy、Plugin、Integration、Recovery、Architecture 和 Full Test 全部通过。

---

# 六十二、禁止实现

以下任一情况视为任务失败：

```text
删除 maximum_fill_quantity 兼容
保留两条相互独立的 Partial Fill 执行链
使用随机 Fill Schedule
使用系统时间决定成交
使用 sleep
使用 Python hash() 生成 Plan ID
依赖 Dict 插入顺序撮合
Checkpoint Restore 后重新执行已经 Broker Execute 的 Fill
Checkpoint Restore 后丢失未发布 PUBLISH_FILL
取消订单后继续执行未发生 Plan Step
将 Broker Fill Plan 当作 Runtime Accounting Authority
修改 Runtime Fill Identity
修改 Fill Index 语义
将多个 Fill 合并为一个 Transaction
修改已 Commit Transaction
增加 Multi-Fill Recovery Phase
修改 Event Gate
修改 Recovery Outcome
重构 Commit Coordinator
增加生产 crash_after_fill
增加生产 fault_switch
直接修改测试对象私有状态
实现 SELL/CLOSE
实现 Futures/Margin
实现订单簿
伪造测试结果
```

---

# 六十三、最终交付报告

完成后输出结构化报告。

## 1. 基线

```text
实际 master commit
任务起始 commit
最终 commit
```

## 2. 修改前状态

说明：

```text
maximum_fill_quantity 已有能力
显式 Plan 缺失
Checkpoint Plan 缺失
旧 Integration Demo 过时
多订单排序风险
```

## 3. 配置

列出：

```text
WHOLE
MAX_PER_BAR
SCHEDULE
ONE_PER_BAR
ALL_DUE
```

及兼容策略。

## 4. Fill Plan

说明：

* Model；
* Invariants；
* ID；
* Fingerprint；
* Normalization；
* Store；
* Cursor。

## 5. Gateway

说明：

* Acceptance；
* Matching；
* Due Step；
* Stable Ordering；
* Execute；
* Publish；
* Cancel。

## 6. Checkpoint V2

说明：

* Payload；
* Participant Version；
* Restore 顺序；
* Authority Validation；
* 旧 Checkpoint 策略。

## 7. Recovery

逐项说明：

```text
Before Execute
Execute Before Publish
Before Commit
After Commit
Projection Tail
Outbox
Checkpoint Continuation
Final Fill
```

## 8. A→B→C

展示三阶段运行和最终等价性。

## 9. 旧场景迁移

说明：

```text
scenario_014
scenario_023
```

的新合同。

## 10. 未修改架构

明确：

```text
Transaction Identity
Fill Identity
Fill Index
PR4.3.2 Accounting
Commit Coordinator
Recovery Phase
Event Gate
Outbox Semantics
```

保持不变。

## 11. 测试结果

列出真实执行命令、通过数量和失败情况。

## 12. 未完成范围

明确：

```text
SELL/CLOSE
Position Reservation Consumption
Futures/Margin
Paper/Live Multi-Fill Recovery
Order Book Matching
Exactly-once
```

## 13. 下一步

明确：

```text
PR4.4
SELL / CLOSE Durable Transaction
```

---

# 六十四、最终目标现象

配置：

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

策略提交：

```text
LIMIT BUY 1000
```

自动结果：

```text
ACCEPTED

→ Fill 1 = 300
Order = PARTIALLY_FILLED
Position = 300
Transaction Count = 1
Risk Active Count = 1

→ Fill 2 = 400
Order = PARTIALLY_FILLED
Position = 700
Transaction Count = 2
Risk Active Count = 1

→ Fill 3 = 300
Order = FILLED
Position = 1000
Transaction Count = 3
Risk Active Count = 0
Fill Plan = COMPLETED
```

系统在任一边界崩溃：

```text
Broker Execute
Broker Publish
Runtime Commit
Projection
Outbox
Checkpoint
```

新 Engine 必须继续剩余 Fill，并最终满足：

```text
无故障 Baseline
==
一次 Restart
==
两次 Restart
```

PR4.3.3 完成后，OnlyAlpha 必须能够证明：

> 一个策略订单可以由 Virtual Broker 根据确定性、可持久的 Fill Plan 自动分多次成交；Broker 与 Runtime 可以在任意成交和 Durable Transaction 边界崩溃，并在新 Engine 中恢复到正确位置继续执行，最终业务 Authority、结果指纹和 Artifact 与无故障运行完全一致。
