# PR3：A 股 Instruction-Driven Durable T+1 Settlement Authority Closure

## 1. PR3 的根本目标

PR3 不解决“如何增加一个 T+1 字段”，也不在现有 `settle()` 上增加条件判断。

PR3 必须解决的根本问题是：

> 一笔成交产生的资产和现金权利，在后续交易日达到生效条件时，如何通过唯一权威、确定性计划和 Durable Transaction，原子地改变 Settlement、Position、Allocation 和 Account 状态，并在任意故障与重启后得到完全相同的结果。

最终业务链路必须变成：

```text
Trade Fill
→ 生成不可变 Settlement Instruction
→ Durable Commit
→ Pending Settlement Authority
→ Trading Day Boundary
→ 查询到期 Instruction
→ 生成 Settlement Maturity Transaction
→ Durable Commit
→ 有序 Projection
    Position
    Allocation
    Settlement
    Account
→ Projection Ready
→ Durable Event / Artifact
→ Strategy 获得更新后的可卖数量和现金状态
```

PR3 完成后，以下情况必须由系统自然保证，而不是由测试代码手工调用：

```text
T 日买入
→ total_quantity 增加
→ unsettled_quantity 增加
→ sellable_quantity 不增加

T+1 第一个 Strategy Callback 之前
→ 对应 Instruction 成熟
→ unsettled_quantity 精确减少
→ settled_quantity 精确增加
→ sellable_quantity 增加

T 日卖出
→ Position 立即减少
→ 卖出所得资金立即可以继续交易
→ 但不能立即提现

T+1
→ 卖出所得资金转为可提现
```

---

# 2. 第一性原则

## 2.1 Settlement 是权利生效过程，不是 Position 的辅助函数

Settlement 的本质不是：

```python
position.settle()
```

而是：

```text
某个明确成交形成的权利或义务
在某个明确交易日
发生某个明确状态转换
```

因此每次结算成熟必须能回答：

```text
哪一条成交？
哪一条 Settlement Instruction？
哪一个 Account？
哪一个 Cluster？
哪一个 Position 生命周期？
哪一个 Allocation 生命周期？
成熟多少数量？
成熟多少现金？
在哪一个交易日生效？
依据哪个 Market Profile？
使用哪个 Reference 和 Compiled Rule？
是否已经执行过？
```

现有聚合式 `settle()` 无法回答这些问题。

## 2.2 Position 不决定何时结算

Position 只能持有状态：

```text
total
settled
unsettled
reserved
restricted
```

Position 不应知道：

```text
T+1
交易日历
节假日
Settlement Policy
Instruction 到期日
```

结算日期只能由 Market Settlement Policy 计算，由 Settlement Authority 保存，由 Maturity Planner 执行。

## 2.3 Runtime 只触发，不直接修改业务状态

Runtime 在交易日变化时只能做：

```text
发现交易日边界
→ 请求 Settlement Authority 查询到期 Instruction
→ 提交生成的 Durable Transaction
```

Runtime 不允许直接执行：

```python
position_manager.settle(...)
allocation_manager.settle(...)
settlement_manager.advance(...)
```

## 2.4 一次结算成熟必须是一个 Durable Operation

当前 Durable Transaction 只接受 Trade Fill 和 Order Terminal，并强制包含 Broker Gateway、Broker Update 和 Trade ID；这说明现有 Transaction Domain 实际上是“Broker Execution Transaction”，不能直接塞入 Settlement Maturity，否则只能伪造 Broker 身份。

PR3 不允许使用：

```text
fake_gateway_id
fake_broker_update_id
synthetic_trade_id
```

来伪装 Settlement Transaction。

必须抽取真正通用的 Runtime Durable Transaction Kernel。

## 2.5 不保留错误抽象

PR3 不提供：

```text
LegacySettlementAdapter
CompatibilitySettlementService
OldCheckpointReader
OldTransactionCodec
Dual Write
Old/New Mode Switch
```

现有测试、Fixture 和示例如果依赖错误边界，应全部删除或重写。

---

# 3. 当前实现中必须消除的问题

## 3.1 双重 Settlement Authority

当前 Runtime 同时存在：

```text
OnlySettlementService
OnlySettlementManager
```

`OnlySettlementService` 根据交易日变化遍历全部 Position 和 Allocation，将全部 unsettled 数量一次性成熟。

`OnlySettlementManager` 又独立保存每条 Settlement Instruction、到期日期、释放状态和记录。

这形成两个事实来源：

```text
Settlement Manager 认为 Instruction 是否成熟
Position Manager 认为数量是否成熟
```

PR3 必须删除其中一个权威。最终只能由 Settlement Instruction 驱动全部状态变化。

## 3.2 聚合式全部成熟

当前 Position Entity 的结算逻辑等价于：

```python
moved = unsettled_quantity
settled_quantity += moved
unsettled_quantity = 0
```

它无法区分不同成交、不同到期日和不同 Allocation。

PR3 必须改为：

```python
settled_quantity += maturity_quantity
unsettled_quantity -= maturity_quantity
```

并要求：

```text
maturity_quantity <= unsettled_quantity
```

## 3.3 Settlement 成熟不在 Durable Transaction 中

现有 Commit Coordinator 和 Projection Applier 已经具备：

```text
先 Commit
按 Execution Sequence 串行
Projection 哈希校验
幂等安装
中途失败后 Forward Recovery
Projection Ready
Durable Outbox
```

这些机制本身可以复用。

但目前日切 Settlement 不进入这条链，因此 Position、Allocation 和 Settlement 状态不是一个 Durable Operation。

## 3.4 Settlement Instruction 缺少最终业务归属

当前 `OnlySettlementRuntimeInstruction` 主要包含：

```text
account
instrument
order
trade
quantity
cash
availability dates
```

它没有冻结：

```text
cluster_id
position_id
position_cycle
allocation_id
allocation_cycle
```

成交所属 Position 和 Allocation 不能在成熟日重新查询或猜测，必须在 Trade Fill Transaction 中冻结。

## 3.5 现金模型没有区分交易可用与可提现

当前 Account Cash 只有：

```text
cash_balance
available_cash
frozen_cash
unsettled_cash
```

并通过简单公式计算 Available Cash。

A 股卖出资金通常存在两个不同状态：

```text
可用于继续买入
可从证券账户提现
```

PR3 必须把这两个概念建模为不同权威。

---

# 4. 目标架构

## 4.1 抽取通用 Durable Transaction Kernel

新增包：

```text
src/onlyalpha/transaction/
    enums.py
    facts.py
    transaction.py
    identity.py
    projection.py
    projection_builder.py
    projection_applier.py
    projection_targets.py
    applied_projection.py
    coordinator.py
    recovery.py
    persistence_ports.py
    codec.py
```

将以下“实际上属于 Runtime Transaction”的能力从 `execution` 包移出：

```text
OnlyPreparedExecutionTransaction
OnlyCommittedExecutionTransaction
OnlyExecutionCommitCoordinator
OnlyExecutionProjectionApplier
OnlyExecutionProjectionComponent
OnlyExecutionPrecondition
OnlyAppliedProjectionLedger
Transaction Store Ports
Projection Ready / Failed 状态
```

重命名为：

```text
OnlyPreparedRuntimeTransaction
OnlyCommittedRuntimeTransaction
OnlyRuntimeTransactionCoordinator
OnlyRuntimeProjectionApplier
OnlyRuntimeProjectionComponent
OnlyRuntimePrecondition
OnlyAppliedRuntimeProjectionLedger
```

`execution` 包只保留：

```text
Trade Fill Fact
Order Terminal Fact
Trade Planner
Terminal Planner
Fill Identity
Broker Update Normalization
Execution Capability
```

`settlement` 包新增自己的：

```text
Settlement Maturity Fact
Settlement Maturity Planner
Settlement Identity
Settlement Projections
```

通用 Transaction Kernel 的 Operation Kind：

```python
class OnlyRuntimeOperationKind(StrEnum):
    TRADE_FILL = "TRADE_FILL"
    ORDER_TERMINAL = "ORDER_TERMINAL"
    SETTLEMENT_MATURITY = "SETTLEMENT_MATURITY"
```

不得保留旧的 `OnlyExecutionOperationKind` 别名。

## 4.2 通用 Transaction 不再强制 Broker 身份

新的 Transaction Scope：

```python
@dataclass(frozen=True, slots=True)
class OnlyPreparedRuntimeTransaction:
    transaction_id: str
    runtime_id: OnlyRuntimeId
    operation_kind: OnlyRuntimeOperationKind
    operation_identity: str
    account_id: OnlyAccountId | None
    effective_time: OnlyTimestamp
    prepared_at: OnlyTimestamp
    fact_draft: OnlyRuntimeFactDraft
    projections: tuple[OnlyRuntimeProjection, ...]
    outbox_events: tuple[OnlyEvent, ...]
    preconditions: tuple[OnlyRuntimePrecondition, ...]
    authority_hash: str
    payload_hash: str
```

Broker 信息只存在于 Trade Fill 和 Order Terminal Fact 内，不进入通用 Transaction 的必填字段。

Store 唯一约束：

```text
(runtime_id, transaction_id)
(runtime_id, operation_kind, operation_identity)
(runtime_id, runtime_sequence)
```

Trade Fill 的 `fill_identity` 只是：

```text
operation_identity
```

的一种具体形式。

Settlement Maturity 则使用自己的稳定身份。

---

# 5. Settlement Domain 重构

## 5.1 删除旧模型

删除：

```text
OnlySettlementRuntimeInstruction
OnlySettlementService
OnlyT1SettlementRule
_OnlyPendingSettlement
OnlySettlementManager.advance()
OnlyPositionManager.settle()
OnlyPositionAllocationManager.settle()
```

删除生产代码中的所有直接 Settlement Bucket 迁移入口。

## 5.2 Settlement Policy 只计算制度日期

Market Rule 层不再生成带 Account、Order、Trade 等 Runtime 身份的 Instruction。

Market Rule Compiler 只输出纯制度计划：

```python
@dataclass(frozen=True, slots=True)
class OnlyCompiledSettlementPolicy:
    policy_id: str
    asset_booking_lag: int
    asset_trade_availability_lag: int
    cash_booking_lag: int
    cash_trade_availability_lag: int
    cash_withdrawal_lag: int
    legal_settlement_lag: int
```

调用接口：

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementScheduleRequest:
    side: OnlyOrderSide
    trading_day: OnlyTradingDay

@dataclass(frozen=True, slots=True)
class OnlySettlementSchedule:
    asset_booked_on: OnlyTradingDay
    asset_trade_available_on: OnlyTradingDay
    cash_booked_on: OnlyTradingDay
    cash_trade_available_on: OnlyTradingDay
    cash_withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
    policy_id: str
```

Market Rule Engine 只决定日期，不决定 Position、Allocation 或 Account 身份。

## 5.3 Settlement Instruction 由 Trade Planner 创建

只有 Trade Planner 同时知道：

```text
成交身份
Position After
Allocation After
Cluster
Account
Fee
Net Cash Flow
Compiled Rules
Reference Fingerprint
```

因此 Trade Planner 必须创建最终 Instruction。

建议模型：

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementInstruction:
    instruction_id: OnlySettlementInstructionId

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId

    position_id: OnlyPositionId
    position_cycle: int
    allocation_id: OnlyPositionAllocationId
    allocation_cycle: int

    side: OnlyOrderSide
    trade_quantity: OnlyQuantity
    gross_notional: OnlyMoney
    net_cash_flow: OnlyMoney

    trading_day: OnlyTradingDay
    schedule: OnlySettlementSchedule

    market_profile_id: str
    market_profile_version: str
    compiled_rule_fingerprint: str
    reference_fingerprint: str

    content_fingerprint: str
```

Instruction ID：

```text
SINS-
SHA256(
    runtime
    account
    order
    trade
    position_id
    allocation_id
    quantity
    schedule
    compiled_rule_fingerprint
)
```

同一 `instruction_id` 对应不同内容时必须 Fail Closed：

```text
SETTLEMENT_INSTRUCTION_IDENTITY_CONFLICT
```

## 5.4 明确资产腿和现金腿

不要继续把资产与现金混成一个模糊的 Settlement 状态。

建议定义：

```python
class OnlySettlementLegDirection(StrEnum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyAssetSettlementLeg:
    direction: OnlySettlementLegDirection
    quantity: OnlyQuantity
    booked_on: OnlyTradingDay
    trade_available_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
```

```python
@dataclass(frozen=True, slots=True)
class OnlyCashSettlementLeg:
    direction: OnlySettlementLegDirection
    legal_amount: OnlyMoney
    account_availability_amount: OnlyMoney
    booked_on: OnlyTradingDay
    trade_available_on: OnlyTradingDay
    withdrawable_on: OnlyTradingDay
    legal_settlement_on: OnlyTradingDay
```

`legal_amount` 用于记录市场法律结算金额。

`account_availability_amount` 用于改变 Account 资金可用状态，应使用扣除手续费和税费后的实际资金影响。

## 5.5 Instruction Authority 状态

```python
class OnlySettlementInstructionStatus(StrEnum):
    PENDING = "PENDING"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    COMPLETED = "COMPLETED"
```

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementInstructionSnapshot:
    instruction: OnlySettlementInstruction

    asset_booked: bool
    asset_trade_available: bool
    cash_booked: bool
    cash_trade_available: bool
    cash_withdrawable: bool
    legal_settled: bool

    status: OnlySettlementInstructionStatus
    version: int
    last_maturity_identity: str | None
```

状态不能存储为自由字符串。

---

# 6. A 股 Settlement Policy

## 6.1 买入

T 日买入成交：

```text
Position.total                + quantity
Position.unsettled            + quantity
Position.settled              不变
Position.sellable             不变

Account.ledger_cash           - 成交金额 - 费用
Account.order_reserved_cash   消费对应 Reservation
Account.trade_available_cash  根据 Reservation 消费后的余额更新
```

Instruction：

```text
asset_booked_on          = T
asset_trade_available_on = T+1 trading day
cash_booked_on           = T
cash_trade_available_on  = T
cash_withdrawable_on     = T
legal_settlement_on      = T+1 trading day
```

买入资产在 T 日已经进入总持仓，但处于 unsettled，不可卖。

## 6.2 卖出

T 日卖出成交：

```text
Position.total                  - quantity
Position.settled                - quantity
Position Reservation            按 Fill 消费

Account.ledger_cash             + net proceeds
Account.trade_available_cash    + net proceeds
Account.unsettled_receivable    + net proceeds
Account.withdrawable_cash       不变
```

Instruction：

```text
asset_booked_on          = T
asset_trade_available_on = T
cash_booked_on           = T
cash_trade_available_on  = T
cash_withdrawable_on     = T+1 trading day
legal_settlement_on      = T+1 trading day
```

T+1：

```text
Account.unsettled_receivable - net proceeds
Account.withdrawable_cash    + net proceeds
```

## 6.3 交易日推进

所有 T+N 日期必须由版本化 `OnlyTradingCalendar` 推进。

禁止：

```python
day + timedelta(days=1)
```

必须：

```python
calendar.advance_trading_day(day, lag)
```

周五成交应在下一个正式交易日成熟，而不是周六。

---

# 7. Account Cash Authority 重构

删除当前：

```text
cash_balance
available_cash
frozen_cash
unsettled_cash
```

替换为语义明确的：

```python
@dataclass(frozen=True, slots=True)
class OnlyAccountCashBalance:
    ledger_cash: OnlyMoney
    trade_available_cash: OnlyMoney
    withdrawable_cash: OnlyMoney
    order_reserved_cash: OnlyMoney
    unsettled_receivable_cash: OnlyMoney
```

现金账户基础不变量：

```text
ledger_cash >= 0
order_reserved_cash >= 0
unsettled_receivable_cash >= 0

trade_available_cash
    = ledger_cash - order_reserved_cash

withdrawable_cash
    = ledger_cash
      - order_reserved_cash
      - unsettled_receivable_cash

0 <= withdrawable_cash <= trade_available_cash <= ledger_cash
```

PR3 不保留旧字段 property，也不提供序列化兼容。

所有 Account、Risk、Order、Strategy Ledger、Result 和 Artifact 对旧字段的引用全部修改。

---

# 8. Settlement Maturity Transaction

## 8.1 Maturity Identity

一次成熟操作的稳定身份：

```text
SMAT-
SHA256(
    runtime_id
    instruction_id
    effective_trading_day
    transition_set
    instruction_before_fingerprint
)
```

模型：

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementMaturityIdentity:
    runtime_id: OnlyRuntimeId
    instruction_id: OnlySettlementInstructionId
    effective_on: OnlyTradingDay
    transitions: tuple[OnlySettlementTransitionKind, ...]
```

Transition Kind：

```python
class OnlySettlementTransitionKind(StrEnum):
    ASSET_TRADE_AVAILABLE = "ASSET_TRADE_AVAILABLE"
    CASH_TRADE_AVAILABLE = "CASH_TRADE_AVAILABLE"
    CASH_WITHDRAWABLE = "CASH_WITHDRAWABLE"
    LEGAL_SETTLED = "LEGAL_SETTLED"
```

相同 Identity 重复提交：

```text
DUPLICATE
```

相同 Identity 不同 Payload：

```text
SETTLEMENT_MATURITY_IDENTITY_CONFLICT
```

## 8.2 Maturity Fact

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementMaturityFactDraft:
    maturity_identity: str
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId

    instruction_id: OnlySettlementInstructionId
    source_order_id: OnlyOrderId
    source_trade_id: OnlyTradeId

    effective_on: OnlyTradingDay
    processed_at: OnlyTimestamp

    transitions: tuple[OnlySettlementTransitionKind, ...]

    asset_available_delta: OnlyQuantity
    cash_trade_available_delta: OnlyMoney
    cash_withdrawable_delta: OnlyMoney

    position_id: OnlyPositionId
    allocation_id: OnlyPositionAllocationId

    instruction_version_before: int
    instruction_version_after: int

    compiled_rule_fingerprint: str
    reference_fingerprint: str
```

Committed Fact 再增加：

```text
runtime_sequence
committed_at
```

## 8.3 Maturity Planner 输入

```python
@dataclass(frozen=True, slots=True)
class OnlySettlementMaturityPlanningContext:
    instruction_before: OnlySettlementInstructionSnapshot
    position_before: OnlyPositionSnapshot
    allocation_before: OnlyPositionAllocationSnapshot
    account_before: OnlyAccountSnapshot
    effective_on: OnlyTradingDay
    processed_at: OnlyTimestamp
```

Planner 必须是纯函数：

```text
输入不可变 Snapshot
→ 输出 Prepared Runtime Transaction
```

不得直接访问 Manager。

## 8.4 Projection 集合

买入资产 T+1 成熟：

```text
Position Projection
    settled += quantity
    unsettled -= quantity

Allocation Projection
    settled += quantity
    unsettled -= quantity

Settlement Projection
    asset_trade_available = true
    legal_settled = true

Account Projection
    若没有现金变化则不生成
```

卖出资金 T+1 成熟：

```text
Settlement Projection
    cash_withdrawable = true
    legal_settled = true

Account Projection
    unsettled_receivable -= net proceeds
    withdrawable_cash += net proceeds
```

同一 Transaction 只包含发生变化的 Projection。

## 8.5 Preconditions

每个 Projection 都必须携带：

```text
component
entity_key
expected_version
expected_state_hash
```

成熟计划完成后，任何状态被其他事务修改都必须导致：

```text
PRECONDITION_CONFLICT
```

不得重新读取最新状态后静默重算。

---

# 9. Projection 顺序

通用 Projection Component 建议顺序：

```python
class OnlyRuntimeProjectionOrder(IntEnum):
    ORDER = 10
    POSITION = 20
    ALLOCATION = 30
    SETTLEMENT = 40
    FEE = 50
    ACCOUNT = 60
    STRATEGY_LEDGER = 70
    RESERVATION = 80
    RISK = 90
    VALUATION = 100
```

Settlement Maturity Transaction 的典型顺序：

```text
1. Position
2. Allocation
3. Settlement
4. Account
```

这不是数据库意义上的瞬间同时写入，而是：

```text
Transaction 先 Durable Commit
→ Projection 顺序安装
→ 任一步失败 Runtime 立即 Fail Closed
→ 禁止继续处理 Bar、Order 或 Strategy
→ Recovery 从 Durable Transaction 继续安装
→ 全部完成后标记 Projection Ready
```

现有 Projection Target 已具备 Expected/Result Hash、Applied Ledger 和幂等恢复机制，可以在重命名和泛化后继续使用。

---

# 10. Settlement Authority

新增：

```python
class OnlySettlementAuthority:
    def register(
        self,
        instruction: OnlySettlementInstruction,
    ) -> None: ...

    def require(
        self,
        instruction_id: OnlySettlementInstructionId,
    ) -> OnlySettlementInstructionSnapshot: ...

    def due_transitions(
        self,
        through: OnlyTradingDay,
    ) -> tuple[OnlySettlementDueTransition, ...]: ...

    def restore_runtime_authority(
        self,
        snapshot: OnlySettlementInstructionSnapshot,
    ) -> None: ...
```

`due_transitions()` 必须：

```text
只读
确定性排序
无状态修改
```

排序：

```text
effective_on
instruction_id
transition_kind
```

只有 Projection Target 可以安装新的 Settlement Snapshot。

禁止：

```python
settlement_authority.advance(day)
```

因为 `advance()` 同时“判断”和“修改”，会绕过 Durable Transaction。

---

# 11. Runtime 交易日边界

新增：

```python
class OnlyRuntimeTradingDayBoundaryCoordinator:
    def process_boundary(
        self,
        previous_day: OnlyTradingDay,
        current_day: OnlyTradingDay,
        timestamp: OnlyTimestamp,
    ) -> OnlyTradingDayBoundaryResult:
        ...
```

执行顺序：

```text
1. 验证 current_day > previous_day
2. 查询所有 effective_on <= current_day 的未完成 Transition
3. 按确定性顺序逐条创建 Maturity Transaction
4. 每条提交 Runtime Transaction Coordinator
5. 每条必须达到 PROJECTION_READY
6. 任意失败：
   - 停止后续 Settlement
   - 不分发当前 Bar
   - 不调用 Strategy
   - Runtime 进入 FAILED 或 RECOVERING_REQUIRED
7. 全部成功：
   - 允许 Valuation
   - 允许 Risk Snapshot
   - 允许 Strategy Callback
```

Backtest 的首根新交易日 Bar：

```text
Bar 输入
→ 解析 Trading Day
→ Settlement Boundary
→ Market Valuation
→ Risk Snapshot
→ Strategy Callback
```

不能先执行 Strategy 再 Settlement。

Paper/Live 后续也必须复用同一个 Boundary Coordinator，不能各自实现日切逻辑。

---

# 12. 跳日和恢复语义

假设 Runtime 从交易日 T 直接恢复到 T+3：

```text
Instruction effective_on = T+1
processed_on = T+3
```

必须保留两个日期：

```text
effective_on
processed_on
```

系统应按原始 `effective_on` 生成身份，而不是把权利生效日改成 T+3。

若一条 Instruction 有多个不同到期日，应按到期日分别形成 Maturity Transaction：

```text
T   CASH_TRADE_AVAILABLE
T+1 ASSET_TRADE_AVAILABLE
T+1 CASH_WITHDRAWABLE
T+1 LEGAL_SETTLED
```

相同日期的多个 Transition 可以合并成一条 Transaction。

---

# 13. Multi-Fill 与 Multi-Cluster

## 13.1 每个 Fill 一条 Instruction

一张订单产生三个 Fill：

```text
300
400
300
```

必须产生三条 Settlement Instruction。

不得只为 Order 产生一条聚合 Instruction。

原因是每个 Fill 具有独立：

```text
trade_id
price
fee
net cash flow
position/allocation delta
transaction identity
```

## 13.2 精确 Allocation 归属

Cluster A 和 Cluster B 同时持有同一证券时：

```text
Cluster A Fill
→ 只能成熟 Cluster A Allocation

Cluster B Fill
→ 只能成熟 Cluster B Allocation
```

Instruction 必须冻结 `allocation_id + allocation_cycle`。

成熟时发现：

```text
Allocation 不存在
Allocation ID 不同
Allocation Cycle 不同
unsettled 数量不足
```

必须 Fail Closed，不能重新分配到当前 Allocation。

## 13.3 Position 生命周期

Position 全部关闭后重新开仓会产生新的 Position Cycle。

旧 Instruction 不允许成熟到新 Position。

因此必须验证：

```text
position_id
position_cycle
```

而不是只验证：

```text
account + instrument
```

---

# 14. Checkpoint、Persistence 与 Recovery

## 14.1 不兼容升级

直接提升：

```text
Runtime Persistence Schema: 3 → 4
Runtime Checkpoint Schema: 下一正式版本
Transaction Codec Schema: 重建
Artifact Schema: 重建
```

旧 Schema 一律拒绝：

```text
RUNTIME_PERSISTENCE_SCHEMA_UNSUPPORTED
CHECKPOINT_SCHEMA_UNSUPPORTED
```

不写 migration。

## 14.2 Store 重构

将旧的：

```text
execution_transactions
execution_projections
execution_outbox
execution_projection_state
```

改名为：

```text
runtime_transactions
runtime_transaction_projections
runtime_transaction_outbox
runtime_projection_state
```

清除数据库中对 Broker Update 和 Trade ID 的通用强制约束。

Operation-specific 查询由独立索引承担：

```text
Trade Fill:
    fill_identity

Order Terminal:
    terminal_identity

Settlement:
    maturity_identity
```

## 14.3 Recovery 矩阵

必须覆盖：

```text
Instruction 注册 Transaction 已 Commit，未 Projection
Position Projection 完成后故障
Allocation Projection 完成后故障
Settlement Projection 完成后故障
Account Projection 完成后故障
Projection 全部完成但 Ready 标记失败
Ready 后 Outbox 未发送
Outbox 已发送后重启
Maturity 前重启
Maturity 当日首 Bar 前重启
跳过多个交易日恢复
同一 Maturity 重复提交
同一 Identity 不同 Payload
```

恢复原则：

```text
Committed Transaction 永远不回滚
未完成 Projection 只向前恢复
已应用 Projection 根据 Applied Ledger 返回 IDEMPOTENT
状态哈希不同必须 Fail Closed
全部 Projection 完成后才能恢复 Runtime OPEN
```

---

# 15. 删除清单

PR3 必须物理删除以下边界，而不是标记 Deprecated：

```text
src/onlyalpha/position/settlement.py
OnlySettlementService
OnlyT1SettlementRule
OnlyPositionManager.settle
OnlyPositionAllocationManager.settle
OnlySettlementManager.advance
_OnlyPendingSettlement
OnlySettlementRuntimeInstruction
OnlyExecutionOperationKind
OnlyPreparedExecutionTransaction
OnlyCommittedExecutionTransaction
OnlyExecutionCommitCoordinator
OnlyExecutionProjection*
```

后半部分用新的 Runtime Transaction 名称替代。

还必须删除所有生产代码中的：

```text
settle_account(
settlement_service
position_manager.settle(
allocation_manager.settle(
settlement_manager.advance(
```

架构测试应扫描并保证这些标识不再出现。

---

# 16. 文件级实施方案

## 16.1 Transaction Kernel

移动并重构：

```text
src/onlyalpha/execution/transaction.py
    → src/onlyalpha/transaction/transaction.py

src/onlyalpha/execution/commit_coordinator.py
    → src/onlyalpha/transaction/coordinator.py

src/onlyalpha/execution/projection.py
    → src/onlyalpha/transaction/projection.py

src/onlyalpha/execution/projection_applier.py
    → src/onlyalpha/transaction/projection_applier.py

src/onlyalpha/execution/applied_projection.py
    → src/onlyalpha/transaction/applied_projection.py

src/onlyalpha/execution/persistence_ports.py
    → src/onlyalpha/transaction/persistence_ports.py
```

同步修改：

```text
Memory Store
SQLite Store
Recovery Orchestrator
Checkpoint Participant
Outbox Publisher
Event Gate
Result Collector
Artifact Writer
```

## 16.2 Settlement

重建：

```text
src/onlyalpha/settlement/models.py
src/onlyalpha/settlement/identity.py
src/onlyalpha/settlement/authority.py
src/onlyalpha/settlement/facts.py
src/onlyalpha/settlement/planner.py
src/onlyalpha/settlement/projections.py
src/onlyalpha/settlement/projection_targets.py
src/onlyalpha/settlement/query.py
```

删除或完全替换：

```text
src/onlyalpha/settlement/manager.py
src/onlyalpha/position/settlement.py
```

## 16.3 Market

修改：

```text
src/onlyalpha/market/models.py
src/onlyalpha/market/runtime_rules.py
src/onlyalpha/market/ashare_rules.py
```

删除 Runtime 业务身份相关的 Settlement Instruction 构建。

只保留 Settlement Schedule 编译。

## 16.4 Execution

修改：

```text
src/onlyalpha/execution/trade_planner.py
src/onlyalpha/execution/terminal_planner.py
src/onlyalpha/execution/processor.py
src/onlyalpha/execution/projection_targets.py
src/onlyalpha/execution/recovery.py
```

Trade Planner 创建最终 Settlement Instruction。

Execution Processor 只处理 Broker Update，不处理 Settlement Maturity。

## 16.5 Position

修改：

```text
src/onlyalpha/position/models.py
src/onlyalpha/position/entities.py
src/onlyalpha/position/manager.py
src/onlyalpha/position/allocation_manager.py
```

只允许以下路径改变 settled/unsettled：

```text
Trade Projection
Settlement Maturity Projection
Recovery Authority Restore
```

普通 Manager API 不公开 Bucket 修改方法。

## 16.6 Account

修改：

```text
src/onlyalpha/account/models.py
src/onlyalpha/account/manager.py
src/onlyalpha/account/views.py
src/onlyalpha/account/reservations.py
src/onlyalpha/risk/rules/account.py
src/onlyalpha/strategy_ledger/*
```

统一使用：

```text
ledger_cash
trade_available_cash
withdrawable_cash
order_reserved_cash
unsettled_receivable_cash
```

## 16.7 Runtime

修改：

```text
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/backtest/runtime.py
src/onlyalpha/runtime/recovery/*
src/onlyalpha/runtime/checkpoint/*
```

新增 Trading Day Boundary Coordinator。

删除 Runtime 内直接调用 Settlement Manager/Position Manager 的日切代码。

---

# 17. 实施顺序

## Commit 1：ADR 与破坏性边界冻结

新增：

```text
ADR: Durable Runtime Transaction Kernel
ADR: Instruction-Driven Settlement Authority
```

明确：

```text
不兼容
不迁移
不保留旧名称
不保留双权威
不允许 Fake Broker Identity
```

## Commit 2：抽取 Runtime Transaction Kernel

完成全部命名和包迁移。

先保证现有 Trade Fill 和 Order Terminal 继续通过新 Kernel 工作。

这不是兼容层，而是直接修改所有调用方。

## Commit 3：重建 Settlement Domain

实现：

```text
Settlement Schedule
Settlement Instruction
Settlement Snapshot
Settlement Authority
Maturity Identity
Maturity Fact
```

删除旧 Service 和 Advance API。

## Commit 4：Trade Fill 接入新 Instruction

Trade Planner 在同一个 Durable Transaction 中提交：

```text
Position
Allocation
Settlement Instruction
Account
其他现有 Projection
```

确保 Instruction 身份包含最终 Position/Allocation Identity。

## Commit 5：Account Cash Authority 重构

一次性修改所有生产代码、测试、Result 和 Artifact。

不保留旧字段。

## Commit 6：Maturity Planner 和 Projection

实现纯 Planner、Projection、Target 和 Preconditions。

## Commit 7：Runtime Day Boundary 接线

保证 Settlement 在新交易日第一根 Bar 的 Strategy Callback 前完成。

## Commit 8：Persistence 和 Recovery

提升 Schema，重建 SQLite 表和所有 Recovery Fixture。

## Commit 9：Artifact 和 Acceptance Pack

增加：

```text
settlement_instructions.parquet
settlement_maturities.parquet
runtime_transactions.parquet 中的 SETTLEMENT_MATURITY
```

并完成端到端 A 股 T+1 场景。

---

# 18. 测试方案

## 18.1 领域单元测试

必须覆盖：

```text
A 股买入资产 T+1
A 股卖出资金 T 日交易可用
A 股卖出资金 T+1 可提现
周五到下周交易日
法定节假日
跳过多个交易日
同日多 Instruction
多到期日 Transition
Instruction Identity 稳定性
Identity Conflict
数量不足
生命周期 ID 冲突
```

## 18.2 Transaction 测试

```text
Settlement Maturity Prepared Transaction 哈希稳定
Projection 顺序稳定
Precondition 精确
Duplicate 返回 Already Ready
相同 Identity 不同 Payload 冲突
每个 Projection 中间点故障
Forward Recovery
Outbox 恢复
```

## 18.3 Multi-Fill

```text
BUY 1000
Fill 300
Fill 400
Fill 300

T 日：
    unsettled = 1000
    settled = 0

T+1：
    三条独立 Maturity Transaction
    settled = 1000
    unsettled = 0
```

每条 Transaction 必须保持独立 `instruction_id` 和 `maturity_identity`。

## 18.4 Multi-Cluster

```text
Cluster A buy 600
Cluster B buy 400

T 日：
    Account unsettled = 1000
    Allocation A unsettled = 600
    Allocation B unsettled = 400

T+1：
    Account settled = 1000
    Allocation A settled = 600
    Allocation B settled = 400
```

注册顺序改变不能改变最终 Canonical Projection。

## 18.5 A→B→C Recovery

建立故障矩阵：

```text
A：正常运行到 T 日成交后
B：在 T+1 Maturity Transaction 不同投影点故障
C：新 Engine 恢复并继续
```

要求：

```text
C 的最终业务 Projection
==
无故障连续运行结果
```

比较范围：

```text
Position
Allocation
Account
Settlement
Runtime Transaction
Outbox
Result
Artifact Fingerprint
```

## 18.6 架构测试

禁止源码出现：

```text
OnlySettlementService
OnlyT1SettlementRule
OnlySettlementManager.advance
OnlyPositionManager.settle
OnlyPositionAllocationManager.settle
OnlyExecutionCommitCoordinator
OnlyPreparedExecutionTransaction
OnlySettlementRuntimeInstruction
fake settlement broker update
```

并验证：

```text
settled_quantity 的生产修改点只有 Trade Reducer、
Settlement Maturity Reducer 和 Recovery Restore。
```

---

# 19. 验收场景

## 场景一：当日买入不可卖

```text
09:35 买入 1000 股并成交

total       = 1000
unsettled   = 1000
settled     = 0
sellable    = 0
```

同日卖出应得到：

```text
SELL_QUANTITY_EXCEEDS_AVAILABLE
```

## 场景二：次交易日自动可卖

T+1 第一根 Bar 进入 Strategy 前：

```text
Settlement Maturity Transaction 已 Projection Ready

total       = 1000
unsettled   = 0
settled     = 1000
sellable    = 1000
```

Strategy 在 `on_bar()` 中提交卖出应通过 Pre-Trade Position 检查。

## 场景三：卖出资金可交易但不可提现

卖出获得净资金 10,000：

```text
T 日成交后：

ledger_cash                  +10000
trade_available_cash         +10000
unsettled_receivable_cash    +10000
withdrawable_cash            不变
```

T+1：

```text
unsettled_receivable_cash    -10000
withdrawable_cash            +10000
```

## 场景四：重启不重复结算

T+1 成熟后重启任意次数：

```text
Position 不重复增加 settled
Allocation 不重复增加 settled
Cash 不重复转为 withdrawable
Settlement Record 不重复
Maturity Fact 不重复
```

## 场景五：故障中间态不可继续交易

如果 Position Projection 成功、Allocation Projection 失败：

```text
Runtime 立即停止业务推进
不执行 Strategy
不处理下一根 Bar
不接受新 Order
```

重启后从 Durable Transaction 继续 Projection，完成后才进入 OPEN。

---

# 20. PR3 完成标准

只有以下条件全部满足，PR3 才能标记完成。

```text
[ ] 只有一个 Settlement Authority
[ ] Settlement 日期只来自 Compiled Market Policy
[ ] Trade Planner 创建最终 Settlement Instruction
[ ] Instruction 冻结 Position 和 Allocation 生命周期身份
[ ] 不存在 Position/Allocation 公共 settle API
[ ] 不存在 Settlement Manager mutable advance API
[ ] Settlement Maturity 是正式 Durable Operation
[ ] Transaction Kernel 不依赖 Broker 身份
[ ] 买入资产 T+1 精确成熟
[ ] 卖出资金交易可用和可提现明确分离
[ ] Position、Allocation、Settlement、Account 同属一个 Transaction
[ ] 新交易日 Strategy Callback 前完成到期 Settlement
[ ] Multi-Fill 每 Fill 独立 Instruction
[ ] Multi-Cluster 精确归属
[ ] Duplicate 幂等
[ ] Identity Conflict Fail Closed
[ ] Commit/Projection 各故障点可 Forward Recovery
[ ] A→B→C 结果与连续运行完全一致
[ ] SQLite/Checkpoint 旧 Schema 明确拒绝
[ ] 旧接口、旧类型、旧测试和旧 Fixture 已删除
[ ] Artifact 能追踪 Instruction → Maturity → Projection
```

---

# 21. 明确不在 PR3 范围内

PR3 不实现：

```text
A 股 Durable Trade Capability 开放
真实 Broker 下单
集合竞价撮合
动态价格笼子
涨跌停封板流动性
最低佣金跨 Fill 累计
公司行为结算
分红
送转股
配股
融资融券
港股 T+2
期货每日盯市
跨币种 Settlement
```

但 PR3 的抽象必须允许未来通过新的 Settlement Policy 和 Maturity Projection 扩展这些市场，而不再重写 Runtime 日切。

---

# 22. 最终结果

PR3 完成后，OnlyAlpha 的结算边界应清晰为：

```text
Market Profile
    只定义 Settlement Policy

Market Rule Compiler
    只计算交易日计划

Trade Planner
    创建最终 Settlement Instruction

Settlement Authority
    保存 Instruction 和成熟状态

Trading Day Boundary Coordinator
    发现到期 Transition

Settlement Maturity Planner
    生成不可变 Durable Transaction

Runtime Transaction Kernel
    Commit、Projection、Recovery、Outbox

Position / Allocation / Account
    只安装 Projection，不决定 Settlement
```

最终工程现象是：

> A 股 T+1 不再是一组散落在 Position、Runtime 和 Settlement Manager 中的条件分支，而成为一条可审计、可恢复、可重放、可验证、具有唯一身份和明确责任边界的 Durable Business Transaction。
