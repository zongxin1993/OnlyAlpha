# OnlyAlpha PR2：Generic T0 Cash Pure Reducers 与 Prepared Transaction Planner

## 一、任务目标

以当前 OnlyAlpha `master` 最新源码、测试、ADR 和正式领域模型为唯一事实源，实现第一条完整、确定、无副作用的 Trade Transaction Planning 链。

本 PR 必须将成交处理中的业务计算从当前 `OnlyExecutionProcessor` 的直接 Manager Mutation 中抽离出来，使系统具备以下能力：

```text
Broker Trade Update
+ Immutable Before States
+ Market / Fee / Settlement Instructions
→ Deterministic After States
→ Ordered Projections
→ Preconditions
→ Committed Fact Draft
→ Deterministic Durable Events
→ OnlyPreparedExecutionTransaction
```

本 PR 的核心结果是：

```python
class OnlyTradeExecutionTransactionPlanner:
    def prepare(
        self,
        context: OnlyTradeExecutionPlanningContext,
    ) -> OnlyPreparedExecutionTransaction:
        ...
```

Planner 必须是纯事务规划器：

* 不修改任何 Manager；
* 不写 Transaction Store；
* 不发布 Event；
* 不调用 Broker；
* 不读取系统当前时间；
* 不分配 Store Execution Sequence；
* 不依赖 Runtime 隐式状态；
* 不产生随机 ID。

完成后，相同完整 Planning Context 必须始终生成完全相同的 Prepared Transaction。

---

# 二、为什么必须实现本 PR

当前正式 Execution Trade 路径仍然是：

```text
Order Mutation
→ Position Mutation
→ Allocation Mutation
→ Settlement Mutation
→ Fee Mutation
→ Account Mutation
→ Strategy Ledger Mutation
→ Reservation Mutation
→ Risk Mutation
→ 最后写入旧 Journal
```

这种执行方式存在根本问题：

```text
业务状态已经部分改变
+
后续步骤失败
→ PARTIAL_MUTATION
→ RECONCILIATION_REQUIRED
```

系统无法通过普通异常回滚多个独立 Manager。

本 PR 必须把流程改造成：

```text
读取一致的 Before States
→ 完整计算所有 After States
→ 完整验证事务
→ 形成 Prepared Transaction
```

此阶段没有任何真实状态修改。

未来才能实现：

```text
Prepared Transaction Commit
→ Projection Apply
→ Projection Ready
→ Durable Outbox Delivery
```

因此 PR2 不是辅助重构，而是 OnlyAlpha 从 Manager：

```text
Prepared Transaction Commit
→ Projection Apply
→ Projection Ready
→ Durable Outbox Delivery
```

因此 PR2 不是辅助重构，而是 OnlyAlpha 从 Manager-before-Journal 转向 Commit-before-Mutation 的业务计算基础。

---

# 三、第一性原则

## 3.1 Reducer 是纯状态转换

每个 Reducer 必须满足：

```text
Before State
+ Immutable Authority Input
→ After State
+ Projection
+ Domain Result
```

Reducer 不得：

* import Manager；
* import Repository；
* import EventBus；
* import Transaction Store；
* 调用任何 Manager Mutation 方法；
* 读取系统时间；
* 查询 Broker；
* 查询 Runtime；
* 修改传入对象；
* 使用随机 UUID；
* 使用全局可变状态。

## 3.2 Planner 是事务编译器

Planner 的职责是：

1. 验证 Planning Context；
2. 构建统一 Planned Trade Authority；
3. 按固定依赖顺序调用 Reducer；
4. 汇总 After States；
5. 构造 Projection；
6. 构造 Preconditions；
7. 构造 Fact Draft；
8. 构造确定性 Durable Events；
9. 构造 Prepared Transaction；
10. 由现有 Prepared Transaction Contract 完成最终经济一致性验证。

Planner 不是：

* Manager；
* Runtime Service Container；
* Commit Coordinator；
* Store Adapter；
* Projection Applier；
* Event Publisher。

## 3.3 历史结果由 Projection 保存

首次成交计算时：

```text
Reducer 决定正确 After State
```

重放时：

```text
Projection Target 安装已提交 After State
```

重放不得重新运行 Reducer。

否则业务规则版本变化可能改变历史成交结果。

## 3.4 相同输入必须产生相同结果

在所有输入完全一致时：

```text
相同 Planning Context
→ 相同 Planned Trade
→ 相同 After States
→ 相同 Projections
→ 相同 Fact Draft
→ 相同 Preconditions
→ 相同 Event IDs
→ 相同 Authority Hash
→ 相同 Payload Hash
```

`prepared_at` 是 Planning Context 的显式字段。

若 `prepared_at` 不同：

```text
Authority Hash 必须相同
Payload Hash 可以不同
```

## 3.5 不保留错误接口

不要为了：

* 旧测试；
* 示例；
* Fixture；
* Mock；
* 减少修改；
* 旧 Prompt；
* 尚未接入生产；

保留 PR2 中被替代的实验接口。

禁止增加：

```text
Compatibility Reducer
Legacy Planner
Deprecated Alias
双写 Planner
unsafe_prepare
skip_validation
test_only 生产构造分支
```

如果仓库中已有未完成、错误或重复的 PR2 原型，删除并统一所有调用方。

---

# 四、正式范围

## 4.1 本 PR 只支持一个生产纵切面

固定场景：

```text
Market Profile: GENERIC_T0_CASH
Order Type: LIMIT
Order Side: BUY
Offset: OPEN
Position Side: LONG
Position Mode: NETTING
Fill: 整单成交
Account: 单 Account
Cluster: 单 Cluster
Currency: 单币种
Margin: 无
Short Selling: 无
```

该场景必须覆盖：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
FEE
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

不得包含：

```text
POSITION_RESERVATION
MARGIN
MARGIN_RESERVATION
```

## 4.2 本 PR 不支持

```text
SELL
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
Partial Fill
多次成交累计
最低佣金跨 Fill 累计
Short Position
Hedging
Margin
Futures
Daily Mark-to-Market
Variation Margin
Margin Call
Forced Liquidation
多 Account
多 Currency
FX
Corporate Action
```

对于不支持的输入，必须返回稳定、明确的领域错误。

不得静默退化到错误行为。

---

# 五、实施前审计

开始修改前执行：

```bash
git status
git log -n 10 --oneline
git rev-parse HEAD

rg "class OnlyExecutionProcessor"
rg "def _trade"
rg "OnlyExecutionCommitContext"

rg "OnlyPreparedExecutionTransaction"
rg "OnlyCommittedExecutionFactDraft"
rg "OnlyExecutionPrecondition"
rg "OnlyExecutionProjectionOrder"

rg "OnlyOrderExecutionProjection"
rg "OnlyPositionExecutionProjection"
rg "OnlyAllocationExecutionProjection"
rg "OnlySettlementExecutionProjection"
rg "OnlyFeeExecutionProjection"
rg "OnlyAccountExecutionProjection"
rg "OnlyStrategyLedgerExecutionProjection"

rg "OnlyAccountCashReservationExecutionProjection"
rg "OnlyStrategyCashReservationExecutionProjection"
rg "OnlyRiskReservationExecutionProjection"
rg "OnlyRiskExecutionProjection"
rg "OnlyValuationExecutionProjection"

rg "only_order_execution_state"
rg "only_position_execution_state"
rg "only_allocation_execution_state"
rg "only_account_execution_state"
rg "only_strategy_ledger_execution_state"

rg "only_expected_execution_reservations"
rg "OnlyPreparedExecutionEconomicInvariantValidator"

rg "OnlyTradeExecutionPlanningContext"
rg "OnlyTradeExecutionTransactionPlanner"
rg "Reducer"
```

形成简短审计报告，至少回答：

1. 当前旧 Trade 路径的实际 mutation 顺序；
2. 每一步使用哪些 Before/After Snapshot；
3. 哪些业务计算当前隐藏在 Manager 内；
4. Position 和 Allocation 新建 ID 如何产生；
5. Fee Record Sequence 如何产生；
6. Settlement Record Sequence 如何产生；
7. Account、Ledger、Reservation、Risk 的真实 Before State 从哪里读取；
8. 当前 PR1.1.1 提供了哪些稳定 Execution State 和 Converter；
9. 是否已存在任何 PR2 原型；
10. 哪些原型需要删除而不是兼容。

不得只根据历史文档推断实现。

---

# 六、建议模块结构

可采用：

```text
src/onlyalpha/execution/
├── planning_context.py
├── planned_trade.py
├── planning_results.py
├── trade_planner.py
└── reducers/
    ├── order.py
    ├── position.py
    ├── allocation.py
    ├── settlement.py
    ├── fee.py
    ├── account.py
    ├── strategy_ledger.py
    ├── reservations.py
    ├── risk.py
    └── valuation.py
```

如果部分文件过小，可按职责合并：

```text
reducers/trade_state.py
reducers/trade_accounting.py
reducers/trade_reservations.py
```

不要创建大量只有转发函数的空壳文件。

不得把全部实现堆入一个数千行 Planner。

---

# 七、OnlyTradeExecutionPlanningContext

## 7.1 Context 作用

Planning Context 必须代表：

> 在一个明确逻辑时点，为一笔 Broker Trade Update 读取到的完整一致 Before Authority。

Planner 执行期间不得再查询 Manager。

建议模型：

```python
@dataclass(frozen=True, slots=True)
class OnlyTradeExecutionPlanningContext:
    update: OnlyBrokerTradeUpdate
    prepared_at: OnlyTimestamp

    position_scope: OnlyExecutionPositionScope
    trade_instruction: OnlyTradeApplicationInstruction
    fee_instruction: OnlyFeeInstruction

    order_before: OnlyOrderExecutionState
    position_before: OnlyPositionExecutionState | None
    allocation_before: OnlyAllocationExecutionState | None
    settlement_before: OnlySettlementExecutionState
    fee_before: OnlyFeeExecutionState
    account_before: OnlyAccountExecutionState
    strategy_ledger_before: OnlyStrategyLedgerExecutionState

    account_cash_reservation_before:
        OnlyAccountCashReservationExecutionState
    strategy_cash_reservation_before:
        OnlyStrategyCashReservationExecutionState
    risk_reservation_before:
        OnlyRiskReservationExecutionState
    risk_before: OnlyRiskExecutionState
    valuation_before: OnlyValuationExecutionState

    position_creation: OnlyPositionCreationAuthority | None
    allocation_creation: OnlyAllocationCreationAuthority | None
```

字段名和实际类型以当前源码为准。

## 7.2 Context 必须验证

至少验证：

* Update 属于同一 Runtime；
* Gateway、Account、Order、Trade Scope 一致；
* Order 是 LIMIT；
* Order Side 是 BUY；
* Offset 是 OPEN；
* Position Side 是 LONG；
* Position Mode 是 NETTING；
* Fill Quantity 等于 Order Remaining Quantity；
* Fill 为整单成交；
* Profile 为 GENERIC_T0_CASH；
* Margin Instruction 不存在；
* Position Reservation 不存在；
* 所有 Currency 一致；
* `prepared_at >= update.ts_event`；
* Account、Ledger、Reservation 均处于可处理状态；
* Before State Version 和 Hash 可用；
* Position/Allocation 新建 Authority 在 `before=None` 时必须存在；
* 已存在 Position/Allocation 时不得提供新建 Authority。

## 7.3 Context 不得包含

* Manager；
* Repository；
* Callable；
* EventBus；
* Store；
* Broker Gateway；
* Runtime；
* Clock；
* 任意可变容器。

---

# 八、新实体 Creation Authority

## 8.1 Position Creation Authority

当前 Position 新建身份依赖 Position Key 和 Cycle。

建立显式不可变输入：

```python
@dataclass(frozen=True, slots=True)
class OnlyPositionCreationAuthority:
    position_id: OnlyPositionId
    cycle: int
```

要求：

* `cycle > 0`；
* Position ID 必须与当前正式 Position ID 规则一致；
* Position Key 必须来自 Planning Context；
* `position_before is None` 时必须存在；
* `position_before is not None` 时禁止存在。

Reducer 不得自行读取当前 Cycle，也不得随机生成 ID。

## 8.2 Allocation Creation Authority

建立等价类型：

```python
@dataclass(frozen=True, slots=True)
class OnlyAllocationCreationAuthority:
    allocation_id: ...
    cycle: int
```

字段必须与真实 Allocation Manager 的身份规则一致。

## 8.3 Context Reader 不属于本 PR 核心

本 PR 可以提供测试用 Context Factory 或正式只读 Builder Contract，但不得接入 ExecutionProcessor。

如果实现正式 Context Reader：

* 只允许读取 Snapshot；
* 不允许修改 Manager；
* 不允许写 Store；
* 不允许发布 Event；
* 必须在单线程 Runtime 边界中一次性读取完整集合。

---

# 九、OnlyPlannedTrade

建立统一、不可变的成交业务权威，避免每个 Reducer 重复解析 Broker Update。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyPlannedTrade:
    runtime_id: OnlyRuntimeId
    gateway_id: OnlyBrokerGatewayId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    instrument_id: OnlyInstrumentId

    side: OnlyOrderSide
    offset: OnlyOffset
    position_side: OnlyPositionSide
    position_mode: OnlyPositionMode

    quantity: OnlyQuantity
    price: OnlyPrice
    notional: OnlyMoney
    authoritative_fee: OnlyMoney

    ts_event: OnlyTimestamp
    ts_init: OnlyTimestamp
    source_sequence: int
    stable_order: ...
```

要求：

* Notional 使用当前正式合约乘数和货币量化规则；
* Fee 必须来自已经解析完成的 `OnlyFeeInstruction`；
* 不得由 Broker Report 重新定义本地权威 Fee；
* Settlement、Fee、Position、Account、Ledger Reducer 共用同一对象；
* 所有金额使用同一 Currency；
* 不重复解析 Side、Offset、Position Effect。

---

# 十、Reducer 统一契约

Reducer 应使用明确输入和结果 DTO。

推荐：

```python
class OnlyOrderTradeReducer:
    def reduce(
        self,
        before: OnlyOrderExecutionState,
        trade: OnlyPlannedTrade,
    ) -> OnlyOrderTradeReduction:
        ...
```

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderTradeReduction:
    after: OnlyOrderExecutionState
    projection: OnlyOrderExecutionProjection
    event_intents: tuple[OnlyExecutionEventIntent, ...]
```

所有 Reducer 必须满足：

```text
输入不可变
输出不可变
无外部副作用
失败不产生部分结果
```

Projection Identity 应由共享 Builder 创建，避免各 Reducer 重复实现：

* Entity Key；
* Expected Version；
* Result Version；
* Expected State Hash；
* Result State Hash；
* Projection Sequence；
* Payload Hash。

Projection Sequence 可由 Planner 在最终排序阶段安装，不要让多个 Reducer 各自猜测全局 Sequence。

---

# 十一、Order Reducer

输入：

```text
Order Before
Planned Trade
```

计算：

* Filled Quantity；
* Remaining Quantity；
* Average Fill Price；
* Status；
* Filled At；
* Updated At；
* Last External Sequence；
* Version；
* Fill Authority。

对于整单成交：

```text
after.filled_quantity = before.quantity
after.remaining_quantity = 0
after.status = FILLED
```

验证：

* Order 非终态；
* Fill Quantity 等于 Before Remaining；
* Instrument、Account、Cluster 一致；
* Broker Sequence 不回退；
* Price 和 Quantity Precision 正确；
* After Version 正确推进；
* 原始订单字段不可改变。

输出：

```text
OnlyOrderExecutionProjection
ORDER_FILLED Event Intent
```

---

# 十二、Position Reducer

输入：

```text
Position Before | None
Planned Trade
Position Creation Authority | None
Settlement Instruction
```

Generic T0 BUY OPEN：

```text
before = None 或已有 LONG NETTING Position
quantity 增加
T0 可用 Bucket 按正式 Profile 规则更新
realized_pnl_delta = 0
fees 累加
average_open_price 重算
last_trade_sequence 更新
last_trade_order 更新
version 推进
```

如果 `before=None`：

* 使用 Position Creation Authority；
* 创建确定性 Position ID；
* Version 从 0 到 1；
* Opened At 使用明确交易时间；
* Status 为 OPEN。

如果已有 Position：

* Position ID 和 Key 不变；
* Version 加一；
* Average Open Price 使用当前正式算法。

不要在 Reducer 内重新解释 Market Profile。

Settlement Bucket 必须来自已解析的 Trade Instruction。

输出：

```text
OnlyPositionExecutionProjection
POSITION_OPENED 或 POSITION_INCREASED Event Intent
realized_pnl_delta
```

---

# 十三、Allocation Reducer

输入：

```text
Allocation Before | None
Planned Trade
Allocation Creation Authority | None
Settlement Instruction
```

职责：

* 更新 Cluster 级持仓；
* 保证 Account/Cluster/Instrument/Side/Mode Scope 一致；
* 更新 Quantity Bucket；
* 更新 Average Open Price；
* 更新 Fee；
* 更新 Last Trade；
* 推进 Version。

对于新 Allocation：

```text
before=None
expected_version=0
result_version=1
```

输出：

```text
OnlyAllocationExecutionProjection
Allocation After State
```

---

# 十四、Settlement Reducer

输入：

```text
Settlement Before State
OnlySettlementRuntimeInstruction
当前 Trading Day
```

不得重新计算：

* Asset Available Date；
* Trade Cash Available Date；
* Withdrawable Date；
* Legal Settlement Date。

这些均由 Market Rule Instruction 决定。

计算：

* Pending Settlement；
* 当前时点 Availability 状态；
* Settlement Record；
* Record Sequence；
* Result State。

Sequence 必须由 Settlement Before State 中的权威 Head 确定。

不得读取 `len(manager.records)`。

输出：

```text
OnlySettlementExecutionProjection
Settlement Event Intents
```

---

# 十五、Fee Reducer

输入：

```text
Fee Before State
OnlyFeeInstruction
Instrument ID
```

不得：

* 调用 Fee Resolver；
* 重新读取 Market Profile；
* 重新解释 Broker Fee；
* 重新计算 Fee Schedule。

计算：

* Fee Records；
* Record Sequence；
* Instruction Idempotency；
* Fee After State；
* Authoritative Fee Total；
* Fee Breakdown。

Sequence 必须由 Fee Before State 确定。

输出：

```text
OnlyFeeExecutionProjection
Fee Event Intents
```

---

# 十六、Account Reducer

输入：

```text
Account Before
Planned Trade
Position Realized PnL Delta
Settlement Cash Instruction
Fee Total
```

Generic T0 BUY OPEN 应计算：

```text
cash_delta = -(notional + fee)
fees_delta = fee
realized_pnl_delta = 0
```

并更新：

* Cash Balance；
* Frozen Cash；
* Unsettled Cash；
* Available Cash；
* Realized PnL；
* Fees；
* Equity；
* Updated At；
* Last External Sequence；
* Version。

注意：

* Reservation 的消费和释放由 Reservation Reducer表示；
* Account Projection 保存最终 Account 权威状态；
* 不允许 Account Reducer 自行修改 Reservation State；
* Account Cash 与 Reservation Frozen Cash 的最终公式必须保持一致。

输出：

```text
OnlyAccountExecutionProjection
Account Event Intents
```

---

# 十七、Strategy Ledger Reducer

输入：

```text
Ledger Before
Planned Trade
Allocation Before
Allocation After
Fee Records / Fee Total
Strategy Cash Reservation Before
```

计算：

* Cash Balance；
* Cash Reserved；
* Cash Available；
* Position Cost；
* Position Market Value；
* Realized PnL；
* Fees；
* Equity；
* Cash Entries；
* Fee Entries；
* Last Trade Sequence；
* Last Trade Stable Order；
* Updated At；
* Version。

必须使用与 Account 相同的成交 Notional 和 Fee Authority。

禁止 Account 和 Ledger 各自独立重算 Fee。

输出：

```text
OnlyStrategyLedgerExecutionProjection
Ledger Event Intents
```

---

# 十八、Account Cash Reservation Reducer

输入：

```text
Account Cash Reservation Before
Planned Trade
Order After
```

实际消费：

```text
notional + authoritative_fee
```

整单成交时：

1. 消费成交总成本；
2. 如果 Reservation Remaining 仍有余额，释放剩余；
3. After State 进入正式终态；
4. Consumed 和 Released 必须金额守恒；
5. Version 正确推进。

必须与 Account After 的 Frozen Cash、Cash Balance 保持一致。

输出：

```text
OnlyAccountCashReservationExecutionProjection
Reservation Event Intents
```

---

# 十九、Strategy Cash Reservation Reducer

输入：

```text
Strategy Cash Reservation Before
Planned Trade
Order After
```

使用与 Account Reservation 完全相同的消费金额权威：

```text
notional + fee
```

更新：

* Consumed；
* Remaining；
* Released；
* Stage；
* State；
* Updated At；
* Version；
* Metadata 保持。

必须与 Ledger After 的：

```text
cash_reserved
cash_available
cash_entries
```

保持一致。

输出：

```text
OnlyStrategyCashReservationExecutionProjection
```

---

# 二十、Risk Reservation Reducer

输入：

```text
Risk Reservation Before
Planned Trade
Order After
```

更新：

* Consumed Quantity；
* Remaining Quantity；
* Consumed Notional；
* Remaining Notional；
* State；
* Version；
* Updated At。

整单成交后，根据当前正式 Risk Reservation 状态机进入正确终态。

验证：

* Account；
* Cluster；
* Instrument；
* Order；
* Currency；
* Quantity；
* Notional；
* Scope 全部一致。

输出：

```text
OnlyRiskReservationExecutionProjection
```

---

# 二十一、Risk State Reducer

输入：

```text
Risk Before
Position After
Account After
Ledger After
Risk Reservation After
Planned Trade
```

只计算 PR2 所需的 Post-Trade Risk State。

不得：

* 重新运行 Pre-Trade Risk Pipeline；
* 调用 Risk Manager；
* 查询 Market Data；
* 产生新的交易决策。

更新内容以当前 `OnlyRiskExecutionState` Contract 为准。

输出：

```text
OnlyRiskExecutionProjection
Risk State Updated Event Intent
```

---

# 二十二、Valuation Reducer

第一版只处理交易后同步估值。

输入：

```text
Valuation Before
Position After
Allocation After
Account After
Ledger After
Planned Trade Price
```

不得读取新行情。

使用成交价格作为本事务明确的估值输入，或严格复用当前 Baseline 中已有的估值语义。

输出：

```text
OnlyValuationExecutionProjection
```

必须与 Account、Ledger After 的 Market Value、Unrealized PnL 和 Equity 一致。

---

# 二十三、Event Intent 与 Durable Event

## 23.1 Reducer 只输出 Event Intent

建立：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionEventIntent:
    component: OnlyExecutionProjectionComponent
    event_type: OnlyEventType
    payload: object
    source: OnlyEventSource
```

Reducer 不直接生成随机 Event ID。

## 23.2 Planner 统一生成 Event

Planner 在 Transaction ID 已确定后：

```text
transaction_id
+ event_sequence
+ event_type
→ deterministic event_id
```

必须使用当前正式：

```text
OnlyExecutionTransactionEventFactory
```

Event 顺序必须固定且有文档。

建议按 Projection Order 和同组件内部固定顺序排序。

不得依赖：

* Reducer 注册顺序；
* 字典顺序；
* 类名排序；
* Set 遍历。

---

# 二十四、Projection Identity Builder

建立单一 Builder，例如：

```python
class OnlyExecutionProjectionBuilder:
    def build(
        self,
        *,
        component: OnlyExecutionProjectionComponent,
        entity_key: str,
        before: object | None,
        after: object,
        projection_sequence: int,
        payload: object,
    ) -> OnlyExecutionProjection:
        ...
```

或等价纯函数。

职责：

* Expected Version；
* Result Version；
* Expected State Hash；
* Result State Hash；
* Projection Sequence；
* Payload Hash。

不要在每个 Reducer 重复实现 Hash 和 Version 逻辑。

Projection Payload Hash 应在完整 Projection Payload 可用后计算。

---

# 二十五、Precondition 生成

Planner 必须从最终 Projection 自动生成 Preconditions。

规则：

```text
每个 Projection 恰好一个 Precondition
```

内容：

```text
component
entity_key
expected_version
expected_state_hash
```

新实体：

```text
before=None
expected_version=0
expected_state_hash=hash(None)
```

不得由调用方手工传入 Preconditions。

不得允许 Projection 和 Precondition 漂移。

---

# 二十六、Fact Draft 生成

Planner 必须从统一 Reduction Results 构造：

```text
OnlyCommittedExecutionFactDraft
```

Fact 不得通过再次读取 Before Context 或重复计算业务量构造。

Fact 应直接消费已经生成的权威结果：

* Planned Trade；
* Order Reduction；
* Position Reduction；
* Allocation Reduction；
* Fee Reduction；
* Account Reduction；
* Ledger Reduction；
* Settlement Reduction；
* Reservation Reductions；
* Risk Reduction；
* Valuation Reduction。

必须保证：

```text
Fact Fee
=
Fee Projection Total
=
Account Fee Delta
=
Ledger Fee Delta
```

```text
Fact Cash Delta
=
Account Cash Delta
=
Ledger Cash Delta
```

```text
Fact Position Delta
=
Position Projection Delta
=
Allocation Projection Delta
```

最终仍由现有 Economic Invariant Validator 进行强校验。

---

# 二十七、Planner 编排顺序

建议固定为：

```text
1. Validate Planning Context
2. Build Planned Trade
3. Reduce Order
4. Reduce Position
5. Reduce Allocation
6. Reduce Settlement
7. Reduce Fee
8. Reduce Account
9. Reduce Strategy Ledger
10. Reduce Account Cash Reservation
11. Reduce Strategy Cash Reservation
12. Reduce Risk Reservation
13. Reduce Risk State
14. Reduce Valuation
15. Build Fact Draft
16. Assign Projection Sequence
17. Build Projection Identities and Payload Hashes
18. Build Preconditions
19. Build Transaction ID
20. Build Durable Events
21. Build Prepared Transaction
```

如实际依赖要求 Reservation 在 Account/Ledger 前先计算，可以调整计算顺序。

但最终 Projection 顺序必须严格遵循现有正式 `OnlyExecutionProjectionOrder`。

不要创建第二套 Projection 顺序。

---

# 二十八、错误模型

新增稳定错误类型，例如：

```python
class OnlyTradeExecutionPlanningError(ValueError):
    code: OnlyTradeExecutionPlanningErrorCode
```

错误码至少覆盖：

```text
UNSUPPORTED_MARKET_PROFILE
UNSUPPORTED_ORDER_TYPE
UNSUPPORTED_ORDER_SIDE
UNSUPPORTED_OFFSET
UNSUPPORTED_POSITION_SIDE
UNSUPPORTED_POSITION_MODE
PARTIAL_FILL_UNSUPPORTED
MARGIN_UNSUPPORTED
POSITION_RESERVATION_FORBIDDEN
SCOPE_MISMATCH
CURRENCY_MISMATCH
MISSING_BEFORE_STATE
MISSING_CREATION_AUTHORITY
UNEXPECTED_CREATION_AUTHORITY
STALE_EXTERNAL_SEQUENCE
INVALID_ORDER_STATE
INVALID_RESERVATION_STATE
REDUCTION_INVARIANT_FAILED
```

错误必须：

* 稳定；
* 可测试；
* 不包含随机信息；
* 不返回部分 Prepared Transaction。

---

# 二十九、与旧 Manager 逻辑的关系

## 29.1 不复制容易漂移的计算

优先抽取共享纯函数：

* Average Fill Price；
* Position Average Open Price；
* Position Realized PnL；
* Allocation Cost；
* Account Cash Delta；
* Ledger Cash Delta；
* Reservation Consumption；
* Money/Quantity Quantization。

旧 Manager 和新 Reducer可以共同使用这些纯函数。

## 29.2 不在本 PR 重构全部 Manager

本 PR 不应把 Manager 改造成 Reducer Wrapper。

只允许抽取：

```text
无副作用
明确输入
明确输出
纯领域计算
```

## 29.3 测试对照旧路径

测试中允许：

```text
相同真实 Before State
├── 旧 Manager Mutation Path
└── 新 Reducer Path
```

然后比较 After State。

禁止生产代码同时执行两套路径。

---

# 三十、测试 Fixture

建立正式 PR2 Fixture Factory，例如：

```text
tests/execution/factories/trade_planning_factory.py
```

提供：

```python
only_test_generic_t0_trade_planning_context()
only_test_generic_t0_planned_trade()
only_test_generic_t0_expected_reductions()
only_test_generic_t0_prepared_transaction()
```

要求：

* 使用当前真实 Execution State；
* 不使用 Manager 作为 Planner 输入；
* 不使用随机 UUID；
* 不使用系统时间；
* 支持字段覆盖；
* 经济完全自洽；
* 不依赖 Legacy Journal Fixture；
* 不依赖旧 Execution Processor 私有方法。

---

# 三十一、单 Reducer 测试

每个 Reducer 必须覆盖：

## 正常路径

* Before → After；
* Projection；
* Version；
* State Hash；
* Payload Hash；
* Event Intent；
* 输入不变。

## 确定性

同一输入重复执行：

```text
输出完全相等
```

## 非法输入

* Scope 错误；
* Currency 错误；
* Version 错误；
* Sequence 回退；
* 状态非法；
* Precision 错误；
* 缺 Creation Authority；
* 多余 Creation Authority。

---

# 三十二、Planner 测试

## 32.1 完整交易

验证 Generic T0 Cash BUY OPEN 生成完整 Prepared Transaction。

必须包含：

```text
ORDER
POSITION
ALLOCATION
SETTLEMENT
FEE
ACCOUNT
STRATEGY_LEDGER
ACCOUNT_CASH_RESERVATION
STRATEGY_CASH_RESERVATION
RISK_RESERVATION
RISK
VALUATION
```

必须不包含：

```text
POSITION_RESERVATION
MARGIN
MARGIN_RESERVATION
```

## 32.2 Projection 顺序

严格匹配现有正式 Projection Order。

## 32.3 Preconditions

每个 Projection 恰好一个 Precondition，Version 和 State Hash 一致。

## 32.4 Fact 一致性

所有 Fact Delta 与 Projection 一致。

## 32.5 Event

* Event Sequence 连续；
* Event ID 确定性；
* Event Scope 一致；
* Event Type 顺序固定；
* 不存在随机 ID。

## 32.6 Hash

相同 Context：

```text
Transaction ID 相同
Authority Hash 相同
Payload Hash 相同
Encoded Payload 相同
```

仅改变 `prepared_at`：

```text
Authority Hash 相同
Payload Hash 不同
```

---

# 三十三、Manager 无副作用测试

执行 Planner 前后，真实 Manager 状态必须完全不变：

```text
Order Manager
Position Manager
Allocation Manager
Account Manager
Strategy Ledger Manager
Settlement Manager
Fee Manager
Risk Manager
Reservation Managers
```

验证方式：

1. 读取真实 Snapshot；
2. 构造 Planning Context；
3. 调用 Planner；
4. 再读取 Snapshot；
5. 逐字段比较。

同时验证：

```text
Store 无记录
EventBus 无事件
Legacy Journal 无记录
```

---

# 三十四、旧路径等价性测试

这是 PR2 最重要的业务正确性测试。

使用同一个 Baseline：

```text
Generic T0 Cash
LIMIT BUY OPEN
整单成交
```

执行：

## 路径 A

当前旧 Trade Mutation Path，获取真实 After Snapshots。

## 路径 B

从相同 Before Snapshots 构造 Planning Context，调用 Pure Reducers。

比较：

```text
Order After
Position After
Allocation After
Settlement After
Fee After
Account After
Strategy Ledger After
Account Cash Reservation After
Strategy Cash Reservation After
Risk Reservation After
Risk After
Valuation After
```

允许忽略的字段必须极少，并在测试中明确解释。

不得通过宽松 Mapping 比较隐藏差异。

该对照只能存在于测试。

---

# 三十五、确定性压力测试

同一 Planning Context 重复调用至少 100 次：

```text
所有 Reduction 相同
Prepared Transaction 相同
Encoded Payload 相同
Transaction ID 相同
Event IDs 相同
Authority Hash 相同
Payload Hash 相同
```

可同时测试：

* Mapping 输入顺序变化；
* Metadata 构造顺序变化；
* Reducer 实例重建；
* Planner 实例重建。

结果必须不受对象实例影响。

---

# 三十六、故障测试

为每个阶段制造错误：

```text
Order Reduction Failure
Position Reduction Failure
Allocation Reduction Failure
Settlement Reduction Failure
Fee Reduction Failure
Account Reduction Failure
Ledger Reduction Failure
Reservation Reduction Failure
Risk Reduction Failure
Valuation Reduction Failure
Prepared Transaction Invariant Failure
```

每次必须证明：

```text
无 Prepared Transaction
Manager 不变
Store 不变
EventBus 不变
Journal 不变
```

不得返回部分 Projection 或部分 Event。

---

# 三十七、架构边界测试

增加 AST 或等价 Architecture Tests，确保：

* `planning_context.py` 不 import Manager；
* `planned_trade.py` 不 import Manager；
* `trade_planner.py` 不 import Manager；
* Reducers 不 import Manager；
* Reducers 不 import Store；
* Reducers 不 import EventBus；
* Planner 不 import Store；
* Planner 不 import EventBus；
* Planner 不 import Runtime；
* Planner 不 import Broker Gateway；
* Planner 不调用系统时间；
* Planner 不使用 UUID4；
* Planner 不调用 `OnlyEventId.new()`；
* Planner 不调用旧 Journal；
* Planner 不调用 `apply_trade()`；
* Planner 不调用 `reserve()`、`consume()`、`release()`；
* 生产代码不存在新旧路径双写；
* 不存在 Validation Bypass；
* 不存在 Compatibility Planner。

---

# 三十八、公共 API

正式导出：

```text
OnlyTradeExecutionPlanningContext
OnlyPlannedTrade
OnlyPositionCreationAuthority
OnlyAllocationCreationAuthority
OnlyTradeExecutionTransactionPlanner
OnlyTradeExecutionPlanningError
OnlyTradeExecutionPlanningErrorCode
OnlyExecutionEventIntent
```

Reducer 是否公开，应根据当前包边界决定。

优先让 Reducer 保持内部实现，只公开 Planner 和不可变输入输出 Contract。

删除所有被替代的 PR2 原型导出。

不要删除当前正式 Processor 仍依赖的 Legacy Journal API，本 PR 不做主链切换。

---

# 三十九、文档与 ADR

新增或更新：

```text
docs/execution_trade_planning.md
docs/execution_prepared_transaction.md
docs/adr/0037-generic-t0-cash-pure-trade-planner.md
```

ADR 必须说明：

1. 为什么 Manager-before-Journal 不安全；
2. 为什么 Planner 必须无副作用；
3. 为什么首先支持 Generic T0 Cash BUY OPEN；
4. 为什么不在本 PR 接入 Store；
5. 为什么不在本 PR实现 Projection Target；
6. Creation Authority 的作用；
7. Planned Trade 的唯一权威；
8. Reducer 与 Projection Replay 的边界；
9. Event Intent 与 Durable Event 的边界；
10. 旧路径等价性测试只存在于测试；
11. 当前不支持的交易类型；
12. PR3、PR4、PR5 的后续职责。

不得声称：

```text
Commit-before-Mutation 已进入正式 Runtime
Manager Projection Apply 已完成
ExecutionProcessor 已切换
Full Replay 已完成
```

---

# 四十、删除和清理

删除：

* 未完成或重复的 Planner 原型；
* 未完成或重复的 Reducer 原型；
* 旧 PR2 Fixture；
* 仅为示例保留的错误 Planner 接口；
* Validation Bypass；
* Compatibility Alias；
* 测试专用生产分支。

更新：

* Public Export；
* Tests；
* Docs；
* ADR；
* Type Hints；
* Prompt 中失效的 PR2 类名。

不要为了旧示例或测试保留接口。

---

# 四十一、工程门禁

至少执行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run pytest tests/execution/test_trade_planning_context.py -q
uv run pytest tests/execution/test_trade_reducers.py -q
uv run pytest tests/execution/test_trade_transaction_planner.py -q
uv run pytest tests/execution/test_trade_planner_manager_parity.py -q
uv run pytest tests/execution/test_trade_planner_determinism.py -q
uv run pytest tests/architecture/test_trade_planning_boundaries.py -q

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
异常吞噬
测试专用 Production 分支
Validation Bypass
Compatibility Wrapper
```

---

# 四十二、验收标准

PR2 只有同时满足以下条件才算完成。

## Planning Context

* 包含完整 Before Authority；
* 不包含 Manager、Runtime、Store 或 EventBus；
* 所有 Scope 和 Currency 明确；
* Creation Authority 明确；
* 不支持场景被稳定拒绝。

## Pure Reducers

* 所有 Reducer 无副作用；
* 所有输入不可变；
* 所有输出确定；
* 不读取系统时间；
* 不生成随机 ID；
* 不调用 Manager；
* 与旧主链 After State 一致。

## Planner

* 只消费 Planning Context；
* 生成完整 Prepared Transaction；
* 不写 Store；
* 不修改 Manager；
* 不发布 Event；
* 不调用旧 Journal；
* 不返回部分结果。

## Transaction 完整性

必须包含：

```text
Fact Draft
Ordered Projections
Preconditions
Deterministic Events
Transaction ID
Authority Hash
Payload Hash
```

## 业务一致性

以下必须完全一致：

```text
Fill Quantity
Fill Price
Notional
Fee
Position Delta
Allocation Delta
Account Cash Delta
Ledger Cash Delta
Reservation Consumption
Settlement State
Risk Exposure
Valuation
```

## 确定性

相同 Context：

```text
Encoded Prepared Transaction 字节级相同
```

## 无副作用

Planner 前后：

```text
所有 Manager Snapshot 完全相同
Store 完全相同
EventBus 完全相同
Legacy Journal 完全相同
```

## 清理

* 无 PR2 旧原型；
* 无 Alias；
* 无 Wrapper；
* 无生产双写；
* 无 Validation Bypass；
* 无测试专用生产逻辑。

---

# 四十三、最终交付报告

完成后输出：

## 1. 修改前 Trade 路径

列出旧路径的 Manager Mutation 顺序和风险。

## 2. Planning Context

列出完整字段、来源和权威意义。

## 3. Planned Trade

说明统一成交权威如何生成。

## 4. Reducers

逐项列出：

```text
输入
输出
计算职责
禁止职责
```

## 5. Creation Authority

说明 Position 和 Allocation 新实体 ID 如何确定。

## 6. Projection 与 Precondition

说明 Sequence、Version、State Hash 和 Payload Hash 如何生成。

## 7. Event

说明 Event Intent 如何转为 Deterministic Durable Event。

## 8. 旧路径等价性

提供真实测试结果，证明：

```text
旧 Manager After State
=
新 Reducer After State
```

## 9. 无副作用证明

提供 Planner 前后 Snapshot、Store、EventBus、Journal 不变的测试结果。

## 10. 确定性证明

提供重复运行测试和 Hash 结果。

## 11. 删除内容

列出所有删除的 PR2 原型、Alias、Fixture 和绕过接口。

## 12. 测试结果

提供真实命令、通过数量和未执行原因。

## 13. 下一阶段

明确下一步为：

```text
PR3：真实 Manager Projection Targets
```

不得声称已经完成：

```text
Store Commit Coordinator
ExecutionProcessor Switch
Legacy Journal Removal
Full Runtime Replay
```

---

# 最终目标

PR2 完成后，OnlyAlpha 必须第一次具备：

```text
真实 Broker Trade Update
+ 完整 Immutable Before Authority
→ 完整、确定、无副作用、可持久化的 Prepared Execution Transaction
```

并保证：

```text
Planner 只负责计算
Store 只负责持久化
Projection Target 只负责安装状态
Commit Coordinator 只负责事务编排
ExecutionProcessor 只负责接入 Runtime 主链
```

不要为了扩大功能范围引入 SELL、CLOSE、Partial Fill、Margin 或 Futures。

不要为了旧测试、旧示例或减少改动保留任何错误接口。
