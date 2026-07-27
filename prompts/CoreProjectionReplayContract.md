# OnlyAlpha PR1.1：完成 Core Projection Replay Contract，为 PR2 建立稳定事务输出边界

## 一、任务定位

以当前 OnlyAlpha `master` 最新代码为唯一事实源，完成 Prepared Execution Transaction 在进入 PR2 前的最后一次契约收敛。

当前已经存在：

```text
Deterministic Transaction ID
Deterministic Durable Event ID
Authority Hash / Payload Hash
Prepared Transaction Schema v2
Ordered Projection Contract
Precondition Contract
Memory / SQLite Transaction Store
Projection Ready Gate
```

但当前核心 Projection 仍主要是“成交变化摘要”，尚不能在空 Runtime 中无损重建真实 Manager 状态。

本 PR 必须解决：

```text
Committed Transaction
→ Ordered Projections
→ Empty Runtime State
→ Deterministicallytext
Committed Transaction
→ Ordered Reconstructed Manager Authority
```

本 PR 完成后，PR2 必须能够直接依赖稳定的 Projection、Precondition、State Hash 和 Economic Invariant Contract，实现 Generic T0 Cash Trade Pure Reducers 与 Transaction Planner，而不需要再次修改本 PR 建立的数据模型。

本任务不是临时补丁，不接受为后续遗留以下问题：

* Projection 只保存部分字段；
* Replay 依赖原 Manager；
* Replay 依赖 Broker SDK；
* Replay 依赖当前 Runtime 隐式状态；
* `expected_state_hash` 只是装饰字段；
* Fact 与 Projection 可以相互矛盾；
* 测试 Fixture 类型合法但经济不自洽；
* SQLite 存储失败被伪装成业务冲突；
* 为旧测试或示例保留错误接口。

---

# 二、第一性原则

## 2.1 Projection 是持久业务权威，不是 Mutation 摘要

每个 Projection 必须回答：

> 如果 Runtime 中不存在这个实体，仅依靠 Projection 能否创建正确实体？

以及：

> 如果 Runtime 中已经存在该实体，仅依靠 Before State、After State 和 Precondition 能否验证并安装状态？

若答案是否定的，Projection Contract 就没有完成。

Projection 必须包含：

```text
完整业务身份
完整权威 Before State
完整权威 After State
Expected Version
Result Version
Expected State Hash
Result State Hash
Projection Payload Hash
```

不允许只保存：

```text
quantity delta
cash delta
status delta
summary string
record count
owner_scope string
```

## 2.2 权威状态与派生分析必须分离

必须区分：

### 必须持久化的权威状态

例如：

* Order 生命周期状态；
* Position 数量 Bucket；
* Position 成本和累计费用；
* Allocation 状态；
* Account Cash、Margin、Sequence；
* Ledger Cash Entry、Fee Entry、Reservation；
* Settlement Instruction 和 Records；
* Risk Reservation；
* 最后成交顺序；
* Entity Version；
* 业务状态和质量标志。

### 可以重算的派生状态

例如：

* Win Rate；
* Profit Factor；
* 部分展示型汇总；
* 可从权威时间线确定性推导的报表指标。

不得把所有报表字段机械复制进 Projection。

但任何影响后续交易决策、风险检查、可用余额、可卖数量、会计结果、幂等和恢复的字段，都属于权威状态，必须可恢复。

## 2.3 Before State Hash 是并发与恢复前置条件

Prepared Transaction 必须证明：

```text
Reducer 读取的 Before State
=
Projection Apply 时 Manager 当前拥有的 State
```

因此每个有状态 Projection 必须存在：

```text
expected_state_hash
result_state_hash
```

Version 不能替代 State Hash。

两个不同状态可能错误地具有相同 Version；只检查 Version 不足以确保 Projection 基于正确的 Before Authority。

## 2.4 经济事实只能有一个真相

Fact Draft、各 Projection 和 Events 不得分别计算同一经济量后各自成立。

以下内容必须由同一规划结果产生并交叉校验：

```text
Fill Quantity
Fill Price
Cumulative Fill
Remaining Quantity
Gross Notional
Settled Notional
Fee Total
Fee Breakdown
Position Quantity Delta
Allocation Quantity Delta
Realized PnL Delta
Account Cash Delta
Ledger Cash Delta
Reservation Consumption
Margin Action
Settlement Dates
```

## 2.5 不保留错误接口

不要为了：

* 旧测试；
* 示例；
* Mock；
* Fixture；
* 减少修改；
* 历史文档；
* 公共导出稳定；

保留不完整 Projection 或兼容接口。

禁止增加：

```text
LegacyProjection
CompatibilityProjection
DeprecatedAlias
旧字段 Property
新旧字段双写
Replay Adapter for obsolete schema
```

删除旧模型后，直接修改所有调用方、测试、文档和导出。

---

# 三、实施前必须重新审计

修改代码前执行：

```bash
git status
git log -n 10 --oneline
git rev-parse HEAD

rg "OnlyOrderExecutionProjection"
rg "OnlyPositionExecutionProjection"
rg "OnlyAllocationExecutionProjection"
rg "OnlyAccountExecutionProjection"
rg "OnlyStrategyLedgerExecutionProjection"

rg "OnlyCashReservationExecutionProjection"
rg "OnlyPositionReservationExecutionProjection"
rg "OnlyMarginReservationExecutionProjection"
rg "OnlyRiskReservationExecutionProjection"

rg "OnlyExecutionPrecondition"
rg "expected_state_hash"
rg "OnlyInMemoryExecutionProjectionState"
rg "OnlyExecutionProjectionTarget"

rg "OnlyOrderSnapshot"
rg "OnlyPositionSnapshot"
rg "OnlyPositionAllocationSnapshot"
rg "OnlyAccountSnapshot"
rg "OnlyStrategyLedgerSnapshot"
rg "OnlyAccountReservation"
rg "OnlyStrategyCashReservation"
rg "OnlyPositionReservation"

rg "OnlyExecutionTransactionConflict"
rg "sqlite3.IntegrityError"
rg "OnlySqliteExecutionTransactionStore"

rg "only_test_execution_projections"
rg "only_test_prepared_execution_transaction"
```

形成简短审计记录，逐项说明：

1. 当前每个 Projection 缺少哪些真实 Manager 权威字段；
2. 哪些字段可重算，哪些字段必须持久化；
3. 当前 `expected_state_hash` 是否参与 Apply；
4. 当前 Fixture 存在哪些 Fact/Projection 矛盾；
5. 当前 SQLite 如何分类唯一键冲突与普通写入错误；
6. 哪些旧 API 会被本 PR 删除。

不得依据本提示词假设当前代码结构，必须读取实际实现。

---

# 四、任务范围

## 4.1 本 PR 必须完成

```text
完整 Order Replay State
完整 Position Replay State
完整 Allocation Replay State
完整 Account Replay State
完整 Strategy Ledger Replay State

完整 Account Cash Reservation Replay State
完整 Strategy Cash Reservation Replay State
完整 Position Reservation Replay State
完整 Margin Reservation Replay State
完整 Risk Reservation Replay State

Canonical State Hash
Precondition State Hash 强制化
Projection Result State Hash
State Hash Apply Contract

Transaction Economic Invariant Validator
经济自洽 Generic T0 Cash Fixture
结构覆盖 All Projection Types Fixture

SQLite Store Error Taxonomy
Memory / SQLite 错误契约一致性

Codec Schema 更新
Store Contract 更新
Projection Reference State 更新
Architecture Tests
文档与 ADR
旧接口删除
完整 CI 验证
```

## 4.2 本 PR 不包含

```text
Trade Pure Reducer
Trade Planning Context
Transaction Planner
真实 Manager Projection Target
Commit Coordinator
ExecutionProcessor 主链切换
Runtime Store 装配
Full Replay Service
Paper / Live Runtime
Futures Daily MTM
```

不得为了演示调用新 Projection，提前在 Processor 中双写新旧事务。

---

# 五、建立统一 Replay State 原则

## 5.1 Replay State 命名

为核心领域建立不可变 Replay State，例如：

```python
OnlyOrderExecutionState
OnlyPositionExecutionState
OnlyAllocationExecutionState
OnlyAccountExecutionState
OnlyStrategyLedgerExecutionState
```

Reservation 使用：

```python
OnlyAccountCashReservationExecutionState
OnlyStrategyCashReservationExecutionState
OnlyPositionReservationExecutionState
OnlyMarginReservationExecutionState
OnlyRiskReservationExecutionState
```

命名必须表达：

> 这是 Execution Projection 持久化的领域权威状态。

不要使用含义模糊的：

```text
ReplayData
ProjectionData
StatePayload
ManagerDump
```

## 5.2 Replay State 与 Snapshot 的关系

优先复用现有不可变 Snapshot，前提是 Snapshot：

* 不包含 Manager；
* 不包含 Repository；
* 不包含 Publisher；
* 不包含 Callable；
* 不包含 Broker SDK；
* 可 Canonical 编码；
* 字段全部具有稳定业务语义；
* 不混合大量可重算展示字段。

如果现有 Snapshot 满足要求，可以直接作为 Projection 的 Before/After。

如果现有 Snapshot 包含不适合持久事务的字段，应建立专用 Execution State，并提供纯函数转换：

```python
def only_order_execution_state(snapshot: OnlyOrderSnapshot) -> OnlyOrderExecutionState:
    ...

def only_position_execution_state(snapshot: OnlyPositionSnapshot) -> OnlyPositionExecutionState:
    ...
```

转换函数不得访问 Manager 或 Runtime。

---

# 六、Order Projection 完整化

当前 Order Projection 不能只保存 Fill 摘要。

修改为类似：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    before: OnlyOrderExecutionState
    after: OnlyOrderExecutionState
    fill: OnlyOrderFill
    broker_update_id: OnlyBrokerUpdateId
```

`OnlyOrderExecutionState` 至少包含：

```text
order_id
request_id
client_order_id
venue_order_id

runtime_id
cluster_id
account_id
instrument_id

side
offset
order_type
time_in_force

quantity
price
stop_price
expire_time

status
filled_quantity
remaining_quantity
average_fill_price

created_at
updated_at
submitted_at
accepted_at
cancel_requested_at
cancelled_at
filled_at
rejected_at
expired_at
failed_at

version
last_external_sequence
rejection
failure
tags
metadata
```

验证：

* Before/After Scope 一致；
* Quantity 不变；
* Filled Quantity 单调增加；
* Remaining Quantity 与原始 Quantity 一致；
* Average Fill Price 合法；
* After Version 等于 Identity Result Version；
* Before Version 等于 Expected Version；
* Fill 属于该 Order；
* Fill 后状态与数量相符；
* Broker Update ID 非空；
* External Sequence 不回退。

不得保留旧字段：

```text
before_status
after_status
before_filled_quantity
after_filled_quantity
before_average_fill_price
after_average_fill_price
external_update_id: str
```

---

# 七、Position Projection 完整化

修改为：

```python
@dataclass(frozen=True, slots=True)
class OnlyPositionExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    before: OnlyPositionExecutionState | None
    after: OnlyPositionExecutionState
    realized_pnl_delta: OnlyMoney
```

必须支持 `before=None`，因为 Generic T0 Cash BUY OPEN 会创建新 Position。

`OnlyPositionExecutionState` 至少包含：

```text
position_id
完整 OnlyPositionKey

status
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
last_trade_order
quality_flags
broker_available_quantity
```

验证：

* `before=None` 时 Expected Version 必须为 0；
* 新 Position 的 Result Version 必须为 1；
* `before!=None` 时 Scope 与 Position ID 不变；
* After Version 与 Result Version 一致；
* Settled + Unsettled = Total；
* Quantity Precision 一致；
* T0 BUY OPEN 后数量进入 Market Rule 指定 Bucket；
* Realized PnL 累计关系正确；
* Fee 累计关系正确；
* Closed 状态与数量为零一致；
* Last Trade Sequence 不回退。

删除旧的摘要字段 Projection。

---

# 八、Allocation Projection 完整化

修改为：

```python
@dataclass(frozen=True, slots=True)
class OnlyAllocationExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    before: OnlyAllocationExecutionState | None
    after: OnlyAllocationExecutionState
    realized_pnl_delta: OnlyMoney
```

`OnlyAllocationExecutionState` 至少包含：

```text
allocation_id
完整 OnlyPositionAllocationKey

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
last_trade_order
```

验证规则与 Position 对齐。

不能继续只保存 `allocation_key: str`。

---

# 九、Account Projection 完整化

修改为：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    before: OnlyAccountExecutionState
    after: OnlyAccountExecutionState
```

`OnlyAccountExecutionState` 至少包含：

```text
runtime_id
account_id
gateway_id
account_type
base_currency
status

cash_balance
available_cash
frozen_cash
unsettled_cash

position_market_value
realized_pnl
unrealized_pnl
fees
equity

created_at
updated_at
valuation_time

version
last_external_sequence
quality_flags

reserved_margin
occupied_margin
released_margin
available_margin
```

Account Reservation 不要同时嵌入 Account State 和独立 Reservation Projection。

必须选择单一权威：

```text
Account State 保存 Account 自身现金和保证金
Reservation Projection 保存 Reservation Entity
```

Account State 中不应重复持久化 Reservation Tuple，避免双 Authority。

验证：

* Scope 不变；
* Currency 不变；
* Version 正确推进；
* Cash Balance 不能为负；
* Available Cash 公式一致；
* Equity 公式一致；
* Margin 公式一致；
* Last External Sequence 不回退；
* Trade 后费用、PnL、Cash 与 Fact 一致。

---

# 十、Strategy Ledger Projection 完整化

修改为：

```python
@dataclass(frozen=True, slots=True)
class OnlyStrategyLedgerExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    before: OnlyStrategyLedgerExecutionState
    after: OnlyStrategyLedgerExecutionState
```

Ledger Execution State 必须包含影响后续交易和恢复的权威字段：

```text
ledger_id
完整 Ledger Key
status

initial_capital
external_cash_flow

cash_balance
cash_reserved
cash_available

position_cost
position_market_value
realized_pnl
unrealized_pnl
fees
equity

cash_entries
fee_entries

created_at
updated_at
valuation_time

version
last_trade_sequence
last_trade_order
quality_flags
```

Reservation Entity 由独立 Strategy Cash Reservation Projection 保存，不要同时嵌入 Ledger State。

以下字段如可由权威时间线确定性重建，可以不进入 Ledger Transaction State：

```text
win_rate
profit_factor
maximum_drawdown
return_since_start
daily_return
```

但必须在 ADR 中明确列出哪些字段是派生状态，以及未来恢复如何重建。

---

# 十一、Reservation Projection 完整化

## 11.1 Account Cash Reservation

建立：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountCashReservationExecutionProjection:
    identity: OnlyExecutionProjectionIdentity
    before: OnlyAccountCashReservationExecutionState | None
    after: OnlyAccountCashReservationExecutionState
```

State 至少包含：

```text
reservation_id
runtime_id
account_id
order_id

reserved_amount
consumed_amount
remaining_amount
state

created_at
updated_at
version
```

删除通用：

```text
owner_scope
before: OnlyMoney
after: OnlyMoney
```

## 11.2 Strategy Cash Reservation

单独建立：

```python
OnlyStrategyCashReservationExecutionProjection
OnlyStrategyCashReservationExecutionState
```

State 至少包含：

```text
reservation_id
完整 Ledger Key
order_id

estimated_notional
estimated_fee
reserved_amount
consumed_amount
remaining_amount

state
stage
created_at
updated_at
version
metadata
```

不得继续让 Account 和 Strategy 共用同一个 Cash Reservation Projection 类。

## 11.3 Position Reservation

State 至少包含：

```text
reservation_id
runtime_id
account_id
cluster_id
instrument_id
position_side
position_mode
order_id

quantity
remaining_quantity
settlement_bucket
stage
state

created_at
updated_at
version
```

## 11.4 Margin Reservation

必须对齐真实 Margin Reservation Manager 状态。

不得只保存几个金额 Delta。

State 至少应包含：

```text
reservation identity
runtime/account/instrument/order scope
currency
original reserved amount
remaining reserved amount
occupied amount
released amount
maintenance amount
state / stage
timestamps
version
```

字段以当前真实 Manager 为准。

## 11.5 Risk Reservation

必须对齐真实 Risk Reservation Entity。

至少保存：

```text
reservation identity
runtime/cluster/account/instrument/order scope
quantity authority
notional authority
consumed quantity
consumed notional
remaining quantity
remaining notional
state
timestamps
version
```

禁止 Risk Projection 与 Risk Reservation Projection 双写同一 Reservation Authority。

---

# 十二、统一 State Hash

## 12.1 实现 Canonical State Hash

新增唯一入口：

```python
def only_execution_state_hash(
    state: OnlyDomainModel | None,
) -> str:
    ...
```

要求：

* `None` 使用固定 Canonical 表达；
* SHA-256 小写十六进制；
* Decimal 使用字符串；
* Timestamp 使用 Unix Nanoseconds；
* Enum 使用 `.value`；
* Identifier 使用规范字符串；
* Tuple 保持顺序；
* Mapping 按 Key 排序；
* 不使用 `repr()`；
* 不使用 Pickle；
* 不使用对象地址；
* 不依赖 Python Hash。

## 12.2 Projection Identity 增加 Result State Hash

修改为：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionProjectionIdentity:
    component: OnlyExecutionProjectionComponent
    entity_key: str

    expected_version: int
    result_version: int

    expected_state_hash: str
    result_state_hash: str

    projection_sequence: int
    payload_hash: str
```

删除 `OnlyExecutionPrecondition.expected_state_hash: Optional` 的宽松语义。

`expected_state_hash` 必须是必填字段。

## 12.3 Precondition

修改：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionPrecondition:
    component: OnlyExecutionProjectionComponent
    entity_key: str
    expected_version: int
    expected_state_hash: str
```

要求：

```text
Precondition.expected_version
=
Projection.identity.expected_version
```

```text
Precondition.expected_state_hash
=
Projection.identity.expected_state_hash
```

## 12.4 Projection 构造验证

每个 Projection 必须验证：

```text
hash(before) = expected_state_hash
hash(after) = result_state_hash
before.version = expected_version
after.version = result_version
```

对于新实体：

```text
before = None
expected_version = 0
expected_state_hash = hash(None)
```

---

# 十三、Projection Apply Contract 收紧

更新 `OnlyExecutionProjectionTarget` 和参考实现。

Apply 必须检查：

```text
Component
Entity Key
Execution Sequence
Payload Hash
Expected Version
Expected State Hash
Result Version
Result State Hash
```

状态增加：

```text
APPLIED
IDEMPOTENT
VERSION_CONFLICT
STATE_CONFLICT
PAYLOAD_CONFLICT
INVALID_COMPONENT
```

语义：

### APPLIED

```text
当前 Version = Expected Version
当前 State Hash = Expected State Hash
```

安装 After State。

### IDEMPOTENT

相同 Execution Sequence、相同 Projection Payload Hash，状态不变。

### PAYLOAD_CONFLICT

相同 Execution Sequence、不同 Payload Hash。

### VERSION_CONFLICT

当前 Version 与 Expected Version 不一致。

### STATE_CONFLICT

当前 Version 正确，但当前 State Hash 与 Expected State Hash 不一致。

### INVALID_COMPONENT

Target 与 Projection Component 不一致。

参考 `OnlyInMemoryExecutionProjectionState` 必须真正保存 State Hash，而不仅保存 Version 与 Applied Hash。

---

# 十四、Transaction Economic Invariant Validator

新增正式纯验证器，例如：

```python
class OnlyPreparedExecutionEconomicInvariantValidator:
    def validate(
        self,
        prepared: OnlyPreparedExecutionTransaction,
    ) -> None:
        ...
```

或等价纯函数。

不得 import Manager、Runtime、Store、EventBus。

Prepared Transaction 构造时必须调用。

## 14.1 通用验证

至少验证：

### Order

```text
Fact Order ID = Order Projection Order ID
Fact Fill Quantity = Order Fill Quantity
Fact Fill Price = Order Fill Price
Fact Order Status After = Order After Status
Fact Cumulative Fill = Order After Filled Quantity
Fact Remaining Quantity = Order After Remaining Quantity
```

### Position

```text
Position Quantity Delta
=
After Total Quantity - Before Total Quantity
```

方向和 Offset 必须与 Position 增减一致。

### Allocation

```text
Allocation Quantity Delta
=
After Total Quantity - Before Total Quantity
```

Cluster、Account、Instrument 必须一致。

### Fee

```text
Fact Authoritative Fee Total
=
Fee Projection Authoritative Total
=
Fee Breakdown Total
=
Fee Record Sum
```

### Account

```text
Fact Account Cash Delta
=
Account After Cash Balance - Account Before Cash Balance
```

```text
Fact Account Fee Delta
=
Account After Fees - Account Before Fees
```

```text
Fact Account Realized PnL Delta
=
Account After Realized PnL - Account Before Realized PnL
```

### Ledger

```text
Fact Ledger Cash Delta
=
Ledger After Cash Balance - Ledger Before Cash Balance
```

```text
Fact Ledger Fee Delta
=
Ledger After Fees - Ledger Before Fees
```

```text
Fact Ledger Realized PnL Delta
=
Ledger After Realized PnL - Ledger Before Realized PnL
```

### Settlement

Fact Settlement Instruction、Trade、Order、Account、Instrument、日期必须一致。

### Margin

Fact 无 Margin Instruction 时：

```text
不得存在 Margin Projection
不得存在 Margin Reservation Projection
```

Fact 有 Margin Instruction 时必须存在对应 Projection。

### Reservation

Fact、Order Fill、Reservation Before/After 必须一致。

### Scope

所有 Projection 必须与 Fact 的：

```text
runtime
gateway
account
cluster
order
trade
instrument
currency
```

保持一致。

---

# 十五、两个独立测试 Fixture

## 15.1 结构覆盖 Fixture

建立：

```python
only_test_all_projection_types_transaction()
```

用途：

* Codec；
* Projection Union；
* Schema；
* 所有类型 Round-Trip。

它可以覆盖 Margin、Risk 等全部 Projection，但仍必须满足基础类型和 Hash 合法性。

不得将它用于证明 Generic T0 Cash 经济语义。

## 15.2 经济自洽 Fixture

建立：

```python
only_test_generic_t0_cash_buy_open_transaction()
```

固定场景：

```text
Market Profile: GENERIC_T0_CASH
Order: LIMIT
Side: BUY
Offset: OPEN
Position: LONG / NETTING
Account: 单账户
Cluster: 单 Cluster
Currency: CNY
Margin: 无
Partial Fill: 第一版可选择整单成交
```

它必须：

* Fact Draft 与所有 Projection 完全一致；
* 无 Margin Projection；
* 无 Position Reservation；
* 有 Account Cash Reservation；
* 有 Strategy Cash Reservation；
* Position `before=None`；
* Allocation `before=None`；
* Order、Account、Ledger Before 均真实完整；
* Settlement 为 T0；
* Fee 可以为零或非零，但全链必须一致；
* Events 使用确定性 ID；
* Preconditions 带真实 State Hash。

PR2 后续必须直接复用该 Fixture 的领域语义。

---

# 十六、SQLite 异常分类

新增：

```python
class OnlyExecutionTransactionStoreError(RuntimeError):
    ...
```

保留：

```python
class OnlyExecutionTransactionConflict(...):
    ...
```

## 16.1 冲突

仅以下情况抛出 `OnlyExecutionTransactionConflict`：

```text
Transaction ID 重复但 Authority 不同
Trade Key 重复但 Authority 不同
Update Key 重复但 Authority 不同
Idempotency Index 指向不同事务
```

## 16.2 Store Error

以下情况必须抛出 `OnlyExecutionTransactionStoreError`：

```text
SQLite Trigger Abort
Disk / I/O Error
Database Locked 超出策略
Malformed Database
非业务唯一键 Integrity Failure
Schema Failure
Outbox Insert Failure
Serialization Persistence Failure
```

保留原异常：

```python
raise OnlyExecutionTransactionStoreError(...) from exc
```

## 16.3 SQLite Commit 流程

`sqlite3.IntegrityError` 后只能在确认是业务唯一键冲突时进行幂等查询。

如果不存在匹配业务幂等事务，不能统一转换成 Conflict，应转换成 Store Error。

Memory Store 的内部写入异常也应转换为 Store Error，除非是明确业务冲突。

---

# 十七、Codec 与 Schema

本次 Projection Contract 是不兼容修改。

提升 Prepared/Committed Transaction Schema Version，例如：

```text
schema_version = 3
```

不兼容 Schema v2，不做隐式迁移。

更新 Codec 支持：

* 所有新 Execution State；
* 新 Reservation Projection；
* State Hash；
* 新 Apply Status；
* 新 Projection Identity；
* 新 Precondition；
* 新 Fixture；
* 新 Transaction Invariant。

要求：

* 所有 State 完整 Round-Trip；
* After Decode 后重新验证 Hash；
* Projection Payload Hash 覆盖 Before/After State；
* State Hash 不包含 Projection Envelope；
* Payload Hash 不包含自身；
* 不使用 Pickle；
* 不使用反射式 `Any` 恢复核心状态。

---

# 十八、删除旧接口

删除：

```text
旧摘要型 OnlyOrderExecutionProjection 字段
旧摘要型 OnlyPositionExecutionProjection 字段
旧摘要型 OnlyAllocationExecutionProjection 字段
旧平铺型 OnlyAccountExecutionProjection 字段
旧平铺型 OnlyStrategyLedgerExecutionProjection 字段

通用 OnlyCashReservationExecutionProjection
owner_scope: str
Reservation Money Delta 摘要模型

Optional expected_state_hash
不包含 result_state_hash 的 Projection Identity

只检查 Version 的参考 Projection State
旧 Fixture Factory
经济不自洽的 Prepared Fixture
```

删除对应：

* Re-export；
* Codec 分支；
* Tests；
* Docs；
* 示例；
* Prompt 中失效接口名。

不保留 Alias、Wrapper 或兼容构造函数。

Legacy Runtime Journal 不属于本 PR 范围，若当前 Processor 仍使用，不得误删。

---

# 十九、架构边界

增加 Architecture Tests，确保：

* Execution State 不 import Manager；
* Projection 不 import Manager；
* State Hash 不 import Manager；
* Economic Invariant 不 import Manager；
* Codec 不 import Manager；
* Transaction Store 不 import Manager；
* Fixture 不 import Legacy Journal Fixture；
* Fixture 不 import Legacy Outbox Fixture；
* Projection 不包含 `Any`；
* Projection 不使用松散 `dict[str, object]` 作为权威状态；
* 不存在 `owner_scope`；
* 不存在旧摘要字段；
* 不存在 Optional State Hash；
* 不存在兼容 Alias；
* SQLite Store Error 与 Conflict 类型独立；
* Core Transaction 模块不 import Runtime/EventBus。

---

# 二十、测试要求

## 20.1 State Hash

覆盖：

1. 相同 State 得到相同 Hash；
2. `None` Hash 固定；
3. 任一权威字段改变，Hash 改变；
4. Mapping 顺序不影响 Hash；
5. Metadata 是否影响 Hash与 ADR 一致；
6. Timestamp Nanosecond 改变时 Hash 改变；
7. Decimal 精度不会通过 Float 丢失；
8. Codec Round-Trip 后 State Hash 不变。

## 20.2 Projection

每种核心 Projection测试：

* Before/After Scope；
* Version；
* State Hash；
* Payload Hash；
* 新实体；
* 已存在实体；
* 非法状态；
* Currency；
* Quantity Precision；
* Timestamp；
* Last Sequence；
* Round-Trip。

## 20.3 Apply Contract

覆盖：

```text
APPLIED
IDEMPOTENT
VERSION_CONFLICT
STATE_CONFLICT
PAYLOAD_CONFLICT
INVALID_COMPONENT
```

重点测试：

```text
相同 Version
+ 不同 State Hash
→ STATE_CONFLICT
```

## 20.4 Economic Invariant

逐项制造错误：

* Fill Quantity 不一致；
* Fill Price 不一致；
* Cumulative Fill 不一致；
* Position Delta 不一致；
* Allocation Delta 不一致；
* Fee Total 不一致；
* Account Cash Delta 不一致；
* Ledger Cash Delta 不一致；
* Realized PnL 不一致；
* Margin Presence 不一致；
* Reservation Consumption 不一致；
* Scope 不一致。

必须全部被拒绝。

## 20.5 Generic T0 Fixture

测试：

```text
Prepared Encode / Decode
Store Commit
Committed Encode / Decode
SQLite Close / Reopen
Projection 顺序
State Hash
Economic Invariant
Deterministic Identity
Deterministic Events
```

## 20.6 Store Error

Memory 与 SQLite 覆盖：

* 真实幂等；
* Authority Conflict；
* Outbox Failure；
* Trigger Abort；
* Rollback 后 Sequence 仍从 1 开始；
* Store Error 保留 Cause；
* Store Error 不被误判为 Conflict；
* 失败后无部分 Transaction；
* 失败后无部分 Outbox；
* 失败后无部分 Index。

---

# 二十一、文档与 ADR

更新或新增：

```text
docs/execution_projection_contract.md
docs/execution_prepared_transaction.md
docs/execution_transaction_store.md
docs/adr/0036-core-projection-replay-completeness.md
```

ADR 必须明确：

1. Projection 保存完整权威状态；
2. 哪些字段属于权威；
3. 哪些字段属于可重算派生值；
4. State Hash 与 Version 的关系；
5. `before=None` 的新实体语义；
6. Reservation 不得使用通用 Owner Scope；
7. Economic Invariant 的职责；
8. Store Error 与 Business Conflict 的区别；
9. Schema v3 不兼容 v2；
10. PR2 可以依赖的稳定接口。

文档必须明确说明仍未完成：

```text
Pure Reducers
Transaction Planner
Manager Projection Targets
Commit Coordinator
Processor Switch
Full Replay Runtime
```

不能声称本 PR 已解决 Manager-before-Journal。

---

# 二十二、工程门禁

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run pytest tests/execution/test_execution_projection_contract.py -q
uv run pytest tests/execution/test_prepared_execution_transaction.py -q
uv run pytest tests/architecture/test_prepared_execution_boundaries.py -q

uv run pytest tests/execution -q
uv run pytest tests/architecture -q
uv run pytest tests/integration -q
uv run pytest tests/scenarios -q
uv run pytest tests/conformance -q

uv run pytest tests -q \
  -m "not external and not requires_network and not requires_tushare and not requires_local_qmt"
```

插件离线测试：

```bash
uv run pytest packages/fake/onlyalpha-plugin-broker-virtual/tests -q

uv run pytest packages/provider/onlyalpha-plugin-tushare/tests -q \
  -m "not external and not requires_network and not requires_tushare"

uv run pytest packages/provider/onlyalpha-plugin-miniqmt/tests -q \
  -m "not external and not requires_network and not requires_local_qmt"
```

执行：

```text
Wheel Build
Sdist Build
Twine Check
Clean Install
Entry Point Smoke
Integration Demo
Scenario Suite
Conformance Suite
```

禁止通过以下方式制造绿色：

```text
skip
xfail
删除关键测试
放宽断言
平台绕过
异常吞噬
测试专用 Production 分支
Compatibility Wrapper
```

---

# 二十三、验收标准

PR1.1 只有同时满足以下条件才算完成。

## Replay Completeness

* Order Projection 可创建和恢复完整 Order；
* Position Projection 可创建和恢复完整 Position；
* Allocation Projection 可创建和恢复完整 Allocation；
* Account Projection 可恢复完整 Account 权威；
* Ledger Projection 可恢复完整 Ledger 权威；
* 所有 Reservation Projection 与真实 Entity 对齐；
* Projection 不依赖 Manager 或 Runtime。

## State Integrity

* 每个 Projection 有 Expected State Hash；
* 每个 Projection 有 Result State Hash；
* Precondition State Hash 必填；
* Apply 检查 Version 和 State Hash；
* 新实体使用 `before=None` 和固定 Null State Hash。

## Economic Integrity

* Fact 与 Projection 必须经济一致；
* Generic T0 Cash Fixture 完全自洽；
* Margin、Fee、Reservation Presence 与 Fact 一致；
* 所有错误组合都会被拒绝。

## Store

* Conflict 与 Store Error 完全区分；
* Memory/SQLite 行为一致；
* 失败无部分写入；
* Sequence 不因失败跳号；
* Cause 保留；
* SQLite 重启和损坏检测通过。

## 清理

* 旧摘要 Projection 删除；
* 旧通用 Cash Reservation Projection 删除；
* `owner_scope` 删除；
* Optional State Hash 删除；
* 旧 Fixture 删除；
* 无 Alias；
* 无 Wrapper；
* 无双写；
* Public API 只导出当前正式 Contract。

## PR2 Readiness

PR2 必须能够直接使用：

```text
Only*ExecutionState
Only*ExecutionProjection
OnlyExecutionPrecondition
only_execution_state_hash
OnlyPreparedExecutionEconomicInvariantValidator
only_test_generic_t0_cash_buy_open_transaction
```

实现：

```text
Generic T0 Cash Planning Context
→ Pure Reducers
→ Transaction Planner
```

而不需要再次修改本 PR 的核心数据模型。

---

# 二十四、最终交付报告

完成后输出：

## 1. 修改前的问题

逐项说明哪些 Projection 无法恢复真实 Manager。

## 2. 权威状态边界

列出每个 Execution State 持久化字段，以及明确排除的派生字段。

## 3. State Hash Contract

说明：

```text
Expected State Hash
Result State Hash
Null State Hash
Apply 检查顺序
```

## 4. Economic Invariant

列出全部跨 Projection 校验。

## 5. Store Error Taxonomy

说明：

```text
OnlyExecutionTransactionConflict
OnlyExecutionTransactionStoreError
```

各自触发条件。

## 6. 删除内容

列出所有删除的旧 Projection、字段、Alias、Fixture 和导出。

## 7. 测试结果

提供真实执行命令、通过数量和未执行原因。

## 8. PR2 就绪证明

使用 Generic T0 Cash Fixture 证明：

```text
完整 Before States
→ 合法 After States
→ Ordered Projections
→ Preconditions
→ State Hash
→ Fact Draft
→ Deterministic Events
→ Prepared Transaction
```

不得声称已经实现 Reducer、Planner、Projection Target 或 Processor 切换。

---

# 最终目标

PR1.1 完成后，OnlyAlpha 必须满足：

```text
Prepared Transaction
=
完整业务事实
+ 完整可重放状态变换
+ 可验证 Before Authority
+ 可验证 After Authority
+ 跨组件经济一致性
```

并保证：

```text
同一 Committed Transaction
→ 从空状态重复 Replay
→ 得到字节级一致的领域权威状态
```

本 PR 必须彻底稳定 PR2 的输出契约。

不要留下“后续 PR2 再补字段”“Manager Target 阶段再决定”“先用字符串占位”“测试先通过再说”等尾巴。

不要为了旧测试、旧示例、旧接口或减少改动保留错误设计。
