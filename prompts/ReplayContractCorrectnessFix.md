# OnlyAlpha PR1.1.1：修正 Replay Contract 业务正确性并解除 PR2 阻塞

## 一、任务目标

以当前 OnlyAlpha `master` 最新源码、测试和 ADR 为唯一事实源，完成 Core Projection Replay Contract 的正确性修复。

当前已经具备：

```text
Prepared Transaction Schema v3
Deterministic Transaction Identity
Deterministic Durable Event Identity
Authority Hash / Payload Hash
Replay-complete Execution State
Expected / Result State Hash
Economic Invariant Validator
Memory / SQLite Transaction Store
Store Error / Business Conflict 分类
```

但当前实现仍存在以下问题：

1. `OnlyAccountExecutionState.available_margin` 与真实 `OnlyAccountManager` 公式不一致；
2. Account Cash Reservation 校验弱于真实领域状态机；
3. Economic Invariant 没有按交易方向约束 Reservation 类型；
4. Margin Fact 没有与 Account Margin State Delta 完整对账；
5. Fee、Reservation、Risk 等子域 Scope 校验不完整；
6. 全 Projection Fixture 将结构覆盖与业务合法性混在一起；
7. Execution State Converter 缺少真实 Manager Snapshot 对等测试；
8. 最新代码尚不能证明 PR2 从真实 Snapshot 构建 Planning Context 时必然成功。

本 PR 必须完整解决以上问题。

完成后必须达到：

```text
真实 Manager Snapshot
→ Execution State
→ 完整字段与公式一致
→ State Hash 稳定
→ Prepared Transaction 经济自洽
```

并保证 PR2 可以直接实现：

```text
OnlyTradeExecutionPlanningContext
→ Pure Reducers
→ OnlyTradeExecutionTransactionPlanner
```

不得再次修改 PR1.1 已稳定的核心事务身份、Hash、Projection 顺序和 Store Schema，除非当前源码审计证明存在直接阻塞正确性的缺陷。

---

# 二、第一性原则

## 2.1 Execution State 必须忠实表达真实领域权威

Execution State 不是一套独立于 Manager 的第二种业务规则。

对于同一个领域实体：

```text
Manager Snapshot
Execution State
Projection Before / After State
```

必须共享相同的：

* 业务身份；
* 金额和数量公式；
* 状态机约束；
* Version 语义；
* 时间语义；
* Currency 和 Precision；
* Scope；
* 可用余额和可用数量定义。

禁止出现：

```text
Manager 接受的合法 Snapshot
→ Execution State 构造失败
```

也禁止：

```text
Manager 会拒绝的非法状态
→ Execution State 接受
```

## 2.2 Prepared Transaction 构造成功代表业务合法

不能再把 Prepared Transaction 当成单纯 Codec Envelope。

一旦 `OnlyPreparedExecutionTransaction` 构造成功，就必须表示：

```text
Fact
Projections
Reservations
Settlement
Fee
Margin
Risk
Events
```

在业务和 Scope 上自洽。

“仅用于覆盖全部类型”的 Fixture 不得绕过经济验证器构造一笔不可能发生的交易。

## 2.3 结构测试与业务场景测试必须分离

需要区分：

### Projection Codec Fixture

用于逐类型测试：

```text
Encode
Decode
Payload Hash
State Hash
Schema
Union Dispatch
```

它不一定需要组合为一个 Prepared Transaction。

### Business Transaction Fixture

必须代表真实合法交易，例如：

```text
GENERIC_T0_CASH
LIMIT BUY OPEN
单 Account
单 Cluster
CNY
无 Margin
```

不得将互相矛盾的 Projection 强行组成 Prepared Transaction。

## 2.4 PR2 必须以真实 Snapshot 为输入

PR2 的 Reducer 不会以测试手工构造的 State 为输入，而会从真实 Manager 读取 Snapshot。

因此本 PR 必须证明：

```text
真实 Manager Snapshot
→ only_*_execution_state()
```

对所有 PR2 涉及的领域都能无损转换。

## 2.5 不保留错误接口

不要为了旧测试、Fixture、示例、Prompt 或减少改动保留错误公式或错误 Fixture。

禁止增加：

```text
Compatibility Formula
Legacy Fixture
Deprecated Property
Business Validation Bypass
skip_economic_validation
unsafe_create
test_only_constructor
```

删除错误测试和错误 Fixture，直接迁移所有使用方。

---

# 三、实施前重新审计

修改前执行：

```bash
git status
git log -n 10 --oneline
git rev-parse HEAD

rg "available_margin" src tests
rg "OnlyAccountExecutionState"
rg "only_account_execution_state"
rg "OnlyAccountReservation"
rg "OnlyAccountCashReservationExecutionState"

rg "OnlyPreparedExecutionEconomicInvariantValidator"
rg "_validate_cash_reservations"
rg "_validate_risk_reservations"
rg "_validate_scope"

rg "only_test_all_projection_types_transaction"
rg "only_test_generic_t0_cash_buy_open_transaction"
rg "only_test_generic_t0_cash_buy_open_projections"

rg "only_order_execution_state"
rg "only_position_execution_state"
rg "only_allocation_execution_state"
rg "only_strategy_ledger_execution_state"
rg "only_account_cash_reservation_execution_state"
rg "only_strategy_cash_reservation_execution_state"
rg "only_position_reservation_execution_state"
rg "only_risk_reservation_execution_state"
```

形成简短审计记录，必须说明：

1. Account Manager 的真实 Available Margin 公式；
2. Account、Ledger、Reservation 的真实状态约束；
3. Generic T0 Cash BUY OPEN 真实会产生哪些 Reservation；
4. Generic T0 Cash BUY OPEN 明确禁止哪些 Projection；
5. Margin Fact 与 Account State 应如何对账；
6. 当前 Fixture 中存在哪些业务矛盾；
7. 哪些 Converter 当前没有被真实 Snapshot 测试覆盖；
8. 哪些旧测试将在本 PR 删除或重写。

以当前源码为准，不机械照搬本提示词中的字段名和路径。

---

# 四、任务范围

## 4.1 本 PR 必须完成

```text
Account Execution State 公式修正
Ledger Execution State 公式复核与修正
Account Reservation 状态规则对齐
其他 Reservation 状态规则复核

交易方向与 Reservation Presence Matrix
Margin Fact / Account Margin Delta 对账
完整 Fee Scope 校验
完整 Settlement Scope 校验
完整 Reservation Scope 校验
完整 Risk Scope 校验

结构 Fixture 与业务 Fixture 分离
移除非法 All-Projections Prepared Transaction

真实 Manager Snapshot Converter Parity Tests
Generic T0 Cash BUY OPEN Manager Baseline Fixture
State Hash Parity Tests
经济矛盾故障测试
完整 CI 验证

ADR 和文档更新
旧错误测试、Fixture 和接口删除
```

## 4.2 本 PR 不包含

```text
Pure Reducer
Trade Planning Context
Transaction Planner
真实 Manager Projection Target
Commit Coordinator
ExecutionProcessor 主链切换
Runtime Store 装配
Full Replay Runtime
Futures Daily MTM
Live Runtime
```

不得提前在生产主链中双写 Prepared Transaction。

---

# 五、修正 Account Execution State

## 5.1 对齐 Available Cash

以真实 `OnlyAccountManager` 和 `OnlyAccountSnapshot` 为权威，确认：

```text
available_cash
=
cash_balance
- frozen_cash
- unsettled_cash
```

`OnlyAccountExecutionState.__post_init__()` 必须验证该公式。

所有 Money 必须使用 Base Currency。

## 5.2 修正 Available Margin

当前错误公式不得保留。

必须与真实 Account Manager 一致：

```text
available_margin
=
cash_balance
- frozen_cash
- unsettled_cash
- reserved_margin
- occupied_margin
```

如果当前领域定义在代码中还有其他明确扣减项，以真实 Account Manager 为准，同时更新 Execution State 和文档。

必须验证：

```text
available_margin.currency == base_currency
reserved_margin >= 0
occupied_margin >= 0
released_margin >= 0
```

是否允许 `available_margin < 0` 必须根据真实 Account 领域规则决定，不得自行假设。

如果真实 Account 允许负可用保证金以表示 Margin Call 状态，Execution State 不得擅自拒绝。

## 5.3 Equity 公式

确认真实 Account 的权威公式：

```text
equity
=
cash_balance
+ position_market_value
```

若 Unrealized PnL 已包含在 Position Market Value 中，不得重复计算。

Execution State 必须与真实 Snapshot 公式完全一致。

## 5.4 Converter

`only_account_execution_state(snapshot)` 必须：

* 无损转换所有权威字段；
* 不自行重算成另一套语义；
* 不把 `None` Margin 字段错误转换成与 Snapshot 不一致的状态；
* 不丢失 Metadata、Quality Flags、External Sequence 和时间字段；
* 构造结果可直接通过 Execution State 校验。

增加双向字段对等断言，不要只断言构造成功。

---

# 六、复核 Strategy Ledger Execution State

以真实 Strategy Ledger Entity 和 Snapshot 为准，验证：

```text
cash_available
=
cash_balance
- cash_reserved
```

以及：

```text
equity
=
cash_balance
+ position_market_value
```

若真实 Ledger Equity 还包含其他权威项，以实际领域实现为准。

必须确认：

* `position_cost` 与 `position_market_value` 语义不同；
* Cash Entries 与 Fee Entries 完整保存；
* Last Trade Sequence 和 Stable Order 不丢失；
* `valuation_time` 的 Optional 语义与真实 Snapshot 一致；
* Converter 不伪造时间或 Sequence；
* Currency 全部与 Ledger Key Base Currency 一致。

增加真实 Ledger Snapshot 转换测试。

---

# 七、对齐 Account Cash Reservation 状态机

`OnlyAccountCashReservationExecutionState` 必须与真实 `OnlyAccountReservation` 完全一致。

规则至少包括：

## 非 RELEASED 状态

```text
consumed_amount + remaining_amount
=
reserved_amount
```

## RELEASED 状态

```text
consumed_amount + remaining_amount
<=
reserved_amount
```

差额表示已释放金额。

同时验证：

* 所有金额 Currency 一致；
* 所有金额非负；
* Version 正数；
* `updated_at >= created_at`；
* CONSUMED 状态要求 `remaining_amount == 0`；
* ACTIVE 状态不得出现已全部消费但仍标记 ACTIVE；
* RELEASED 状态不得恢复为 ACTIVE；
* Before/After 中 Reserved Amount 不得变化；
* Consumed Amount 单调增加；
* Remaining Amount 单调减少；
* Version 必须推进。

具体状态集合和规则以当前领域 Enum 与 Manager 为准。

不得在 Execution State 中定义与 Manager 不一致的新状态机。

---

# 八、复核其他 Reservation 状态

逐项审计并对齐：

```text
OnlyStrategyCashReservationExecutionState
OnlyPositionReservationExecutionState
OnlyMarginReservationExecutionState
OnlyRiskReservationExecutionState
```

必须验证以下共同规则：

```text
Before / After Reservation ID 不变
Scope 不变
Original Authority 不变
Consumed 单调增加
Remaining 单调减少
Version 正确推进
updated_at 不回退
终态不能回到活动状态
```

## Strategy Cash Reservation

必须验证：

```text
consumed + remaining = reserved
```

或按真实 RELEASED 语义允许已释放差额。

同时验证：

* Estimated Notional；
* Estimated Fee；
* Ledger Key；
* Order ID；
* Stage；
* State；
* Metadata。

## Position Reservation

必须验证：

```text
0 <= remaining_quantity <= original_quantity
```

并检查：

* Position Side；
* Position Mode；
* Settlement Bucket；
* Stage；
* State；
* Account/Cluster/Instrument Scope。

## Margin Reservation

必须与真实 Margin Manager 的金额守恒一致。

不要只检查：

```text
remaining + occupied + released <= original
```

如果真实模型要求等于，则必须使用等于。

## Risk Reservation

必须检查：

```text
consumed_quantity + remaining_quantity
=
reserved_quantity
```

存在 Notional 时：

```text
consumed_notional + remaining_notional
=
reserved_notional
```

并验证 Currency、Scope、Release Reason 与状态一致。

---

# 九、建立 Reservation Presence Matrix

新增正式纯领域规则，不能只写在测试中。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionReservationPresence:
    require_account_cash: bool
    require_strategy_cash: bool
    require_position: bool
    require_margin: bool
    require_risk: bool
```

或等价枚举/纯函数：

```python
def only_expected_execution_reservations(
    *,
    market_profile_id: str,
    side: OnlyOrderSide,
    offset: OnlyOffset,
    position_effect: OnlyPositionEffect,
    margin_instruction_present: bool,
) -> OnlyExecutionReservationPresence:
    ...
```

该规则不得 import Manager、Runtime、Store 或 EventBus。

## PR2 首期场景必须明确

对于：

```text
GENERIC_T0_CASH
BUY
OPEN
无 Margin
```

必须满足：

```text
Account Cash Reservation：恰好一个
Strategy Cash Reservation：恰好一个
Position Reservation：禁止
Margin Reservation：禁止
```

Risk Reservation 是否必须存在，依据当前 Risk 订单预留主链决定。

如果当前产品主链一定创建 Risk Reservation，则必须要求恰好一个；否则必须明确允许缺失的条件。

## SELL CLOSE

即使本 PR 不实现 PR2 SELL Reducer，也必须建立正确验证规则：

```text
Account Cash Reservation：禁止
Strategy Cash Reservation：禁止
Position Reservation：必须
Margin Reservation：按 Market Instruction
```

## 禁止模糊行为

不得允许：

```text
BUY OPEN + Position Reservation
Cash Trade 无 Margin Instruction + Margin Projection
同一种 Reservation 多条
未知 Reservation 被静默忽略
```

---

# 十、补齐 Economic Invariant Validator

更新 `OnlyPreparedExecutionEconomicInvariantValidator`。

## 10.1 Reservation Presence

根据交易属性调用 Presence Matrix，验证：

* 必须存在的 Projection 恰好一个；
* 禁止存在的 Projection为零；
* 不允许重复同 Component；
* Reservation Scope 与 Fact 一致。

## 10.2 Account Cash Reservation

验证：

```text
after.consumed - before.consumed
=
BUY OPEN 实际消耗金额
```

实际消耗应使用统一权威：

```text
settled_notional + authoritative_fee_total
```

或当前业务实际定义。

不要仅依赖 `-fact.cash_delta`，除非 `cash_delta` 明确定义为 Reservation Consumption。

同时验证：

```text
reservation.order_id = fact.order_id
reservation.runtime_id = fact.runtime_id
reservation.account_id = fact.account_id
reservation.currency = fact.currency
```

## 10.3 Strategy Cash Reservation

验证：

```text
reservation.key.runtime_id = fact.runtime_id
reservation.key.account_id = fact.account_id
reservation.key.cluster_id = fact.cluster_id
reservation.key.base_currency = fact.currency
reservation.order_id = fact.order_id
```

Consumption 与 Account Reservation 以及交易总成本一致。

## 10.4 Position Reservation

仅在 Close/Sell 类交易允许。

验证：

```text
consumed quantity
=
fill quantity
```

并验证：

* Runtime；
* Account；
* Cluster；
* Instrument；
* Position Side；
* Position Mode；
* Order ID。

## 10.5 Risk Reservation

验证：

* Runtime；
* Account；
* Cluster；
* Instrument；
* Order；
* Quantity；
* Notional；
* Currency；
* Consumption；
* Final State。

不能只检查 Order ID 和金额。

## 10.6 Fee Scope

必须完整；

* Final State。

不能只检查 Order ID 和金额。

## 10.6验证：

```text
instruction.runtime_id = fact.runtime_id
instruction.cluster_id = fact.cluster_id
instruction.account_id = fact.account_id
instruction.order_id = fact.order_id
instruction.trade_id = fact.trade_id
```

每条 Fee Record 也必须一致。

## 10.7 Settlement Scope

必须完整验证：

```text
account
instrument
order
trade
currency
quantity
cash amount
availability dates
legal settlement date
```

Settlement Record Scope 也必须一致。

## 10.8 Risk State Scope

必须验证：

```text
cluster_id
account_id
instrument_id
order_id
quantity exposure
notional currency
```

Risk State 不得属于另一个交易 Scope。

## 10.9 Margin 与 Account State 对账

有 Margin Instruction 时，验证：

```text
Account.reserved_margin Delta
=
Fact.reserved_margin_delta
```

```text
Account.occupied_margin Delta
=
Fact.occupied_margin_delta
```

```text
Account.released_margin Delta
=
Fact.released_margin_delta
```

```text
Account.after.maintenance / available margin
```

必须与 Margin Projection 和 Margin Reservation 一致。

无 Margin Instruction 时：

```text
禁止 Margin Projection
禁止 Margin Reservation Projection
Fact 所有 Margin 字段必须为空
Account Margin 状态不得因本交易变化
```

## 10.10 Cross-domain Scope

建立单一 Scope 验证入口，不要把 Scope 检查散落为重复条件。

建议提取：

```python
@dataclass(frozen=True, slots=True)
class OnlyExecutionAuthorityScope:
    runtime_id: ...
    gateway_id: ...
    account_id: ...
    cluster_id: ...
    instrument_id: ...
    order_id: ...
    trade_id: ...
    currency: ...
```

各 Projection 显式映射到 Scope 后统一比较。

---

# 十一、拆分测试 Fixture

## 11.1 保留合法 Generic T0 Business Fixture

保留并强化：

```python
only_test_generic_t0_cash_buy_open_transaction()
```

该 Fixture 必须代表真实合法业务：

```text
GENERIC_T0_CASH
LIMIT BUY OPEN
LONG / NETTING
单 Account
单 Cluster
CNY
完整成交
无 Margin
无 Position Reservation
```

必须包含：

* 完整 Order Before/After；
* Position Before 为 None；
* Allocation Before 为 None；
* Account Before/After；
* Ledger Before/After；
* Settlement；
* Fee；
* Account Cash Reservation；
* Strategy Cash Reservation；
* Risk 和 Risk Reservation按真实主链规则；
* Preconditions；
* Deterministic Events。

## 11.2 删除非法 All-Projections Prepared Transaction

删除或重构：

```python
only_test_all_projection_types_transaction()
```

不得再把以下内容强行组合成一笔 BUY OPEN：

```text
Position Reservation
Margin Projection
Margin Reservation
```

推荐改为：

```python
only_test_projection_codec_cases()
    -> tuple[OnlyExecutionProjection, ...]
```

每个 Projection 独立用于 Codec 和 Union 测试。

也可以建立多个合法事务：

```text
Generic T0 BUY OPEN
Generic T0 SELL CLOSE
Margin Trade
```

但不要为了覆盖类型伪造业务。

## 11.3 Codec 测试

Codec 测试不应要求 15 种 Projection 必须同时存在于一笔 Prepared Transaction。

应逐 Projection 测试：

```text
Projection Encode
Projection Decode
Payload Hash
Before/After State Hash
Type Envelope
```

Prepared Transaction 测试只使用合法业务组合。

---

# 十二、真实 Manager Snapshot Parity Tests

这是本 PR 的核心验收项。

新增独立测试模块，例如：

```text
tests/execution/test_execution_state_snapshot_parity.py
```

测试不得只手工构造 Snapshot。

必须通过真实 Manager、Entity 或正式 Repository API 生成状态。

## 12.1 Order

通过真实 Order 组件建立 Accepted Order Snapshot，然后转换：

```python
state = only_order_execution_state(snapshot)
```

逐字段验证完全一致。

## 12.2 Position

使用真实 Position Manager 生成或应用一笔 T0 BUY OPEN，获取 Snapshot，验证转换结果。

同时覆盖：

```text
不存在 Position → Before None
已存在 Position → 完整 State
```

## 12.3 Allocation

通过真实 Allocation Manager 生成 Snapshot，验证：

* Allocation ID；
* Key；
* Quantity Buckets；
* Average Price；
* Fees；
* Version；
* Last Trade。

## 12.4 Account

通过真实 Account Manager 创建现金账户，验证：

```text
cash_balance
available_cash
frozen_cash
unsettled_cash
available_margin
equity
```

至少覆盖：

### 普通现金账户

```text
cash = 100
frozen = 0
unsettled = 0
reserved margin = 0
occupied margin = 0
available margin = 100
```

### 存在冻结和保证金

验证真实 Manager 公式。

## 12.5 Strategy Ledger

通过真实 Ledger Manager 获取 Snapshot，验证：

* Cash；
* Reserved；
* Available；
* Cost；
* Market Value；
* Entries；
* Equity；
* Version；
* Last Trade。

## 12.6 Reservations

通过真实 Reservation Manager 创建、消费和释放 Reservation，分别转换：

```text
Account Cash
Strategy Cash
Position
Risk
```

如果 Margin Reservation 当前没有正式领域 Entity Converter，则必须明确建立并测试对应正式转换函数，不能用手工状态代替。

## 12.7 State Hash

真实 Snapshot 转换为 State 后：

```text
相同 Snapshot → 相同 State Hash
任一权威字段变化 → State Hash 变化
Mapping 顺序变化 → State Hash 不变
```

---

# 十三、PR2 Baseline Transition Test

本 PR 不实现 Pure Reducer，但必须建立一个确定性的 PR2 Baseline。

使用真实 Manager 生成 Generic T0 Cash BUY OPEN 的 Before 和旧主链执行后的 After：

```text
真实 Before Snapshots
→ 当前稳定 Trade 行为
→ 真实 After Snapshots
→ 转换为 Execution States
```

验证它们能够组成合法：

```text
Fact Draft
Projections
Preconditions
Prepared Transaction
```

允许测试辅助代码根据真实 Before/After State 构造 Projection，但不得加入生产 Reducer。

该测试用于证明：

> PR2 只需要把当前已知正确的 Before→After 计算移入 Pure Reducer，不需要再次修改 Contract。

不得在生产代码中执行新旧路径双写。

---

# 十四、错误与边界测试

必须增加以下失败测试。

## Account

* 错误 Available Cash；
* 错误 Available Margin；
* 错误 Equity；
* Currency 不一致；
* Version 非法。

## Reservation

* 非 RELEASED 状态金额不守恒；
* Consumed 回退；
* Remaining 增加；
* Reserved Amount 改变；
* Version 不推进；
* 终态恢复为 Active；
* Scope 改变。

## Presence Matrix

* BUY OPEN 含 Position Reservation；
* BUY OPEN 缺 Account Cash Reservation；
* BUY OPEN 缺 Strategy Cash Reservation；
* 无 Margin Instruction 含 Margin Projection；
* SELL CLOSE 含 Cash Reservation；
* SELL CLOSE 缺 Position Reservation；
* 同类型 Reservation 重复。

## Scope

* Fee Account 错误；
* Fee Order 错误；
* Fee Trade 错误；
* Settlement Account 错误；
* Reservation Cluster 错误；
* Risk Instrument 错误；
* Currency 错误。

## Margin

* Fact Delta 与 Account State 不一致；
* Margin Projection 与 Margin Reservation 不一致；
* Maintenance Margin 不一致；
* 无 Margin 时 Account Margin 状态变化。

---

# 十五、删除和迁移

删除：

```text
错误的 available_margin 公式
弱化的 Account Reservation 守恒规则
非法 All-Projections Prepared Transaction Fixture
允许 BUY OPEN Position Reservation 的测试
允许 Margin Fact 与 Account State 不一致的测试
只使用手工 State 而不验证真实 Snapshot 的假覆盖
```

更新：

```text
src/onlyalpha/execution/execution_state.py
src/onlyalpha/execution/economic_invariants.py
tests/execution/factories/transaction_factory.py
tests/execution/test_execution_projection_contract.py
tests/execution/test_execution_economic_invariants.py
tests/execution/test_prepared_execution_transaction.py
tests/architecture/*
docs/adr/0036-core-projection-replay-completeness.md
docs/execution_projection_contract.md
docs/execution_prepared_transaction.md
```

具体路径以当前项目为准。

不保留：

```text
旧 Fixture Alias
兼容 Helper
skip_validation 参数
unsafe 构造入口
```

---

# 十六、架构门禁

增加或更新 Architecture Tests，确保：

* Economic Invariant 不 import Manager；
* Presence Matrix 不 import Manager；
* Execution State 不持有 Manager；
* Converter 只接受领域 Snapshot/Entity；
* 测试 Fixture 不包含 Validation Bypass；
* 不存在非法 All-Projections Transaction；
* 不存在旧 Available Margin 公式；
* 不存在 Compatibility Alias；
* 不存在 `skip_economic_validation`；
* 不存在 Production 双写路径；
* PR1.1.1 不修改 ExecutionProcessor Trade 主链。

---

# 十七、工程门禁

至少运行：

```bash
uv lock --check
uv sync --frozen --all-packages --all-groups

uv run ruff check src tests examples packages
uv run ruff format --check src tests examples packages

uv run mypy src/onlyalpha

uv run pytest tests/execution/test_execution_state_snapshot_parity.py -q
uv run pytest tests/execution/test_execution_projection_contract.py -q
uv run pytest tests/execution/test_execution_economic_invariants.py -q
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

禁止：

```text
skip
xfail
放宽断言
删除关键测试
异常吞噬
测试专用 Production 分支
Validation Bypass
Compatibility Wrapper
```

无法运行外部服务测试时，必须明确列出未执行项目和原因。

---

# 十八、验收标准

PR1.1.1 只有满足以下全部条件才算完成。

## State Parity

* 真实 Order Snapshot 可无损转换；
* 真实 Position Snapshot 可无损转换；
* 真实 Allocation Snapshot 可无损转换；
* 真实 Account Snapshot 可无损转换；
* 真实 Ledger Snapshot 可无损转换；
* 真实 Reservation Entity 可无损转换；
* 所有公式与 Manager 完全一致。

## Account Correctness

* Available Cash 正确；
* Available Margin 正确；
* Equity 正确；
* Margin 状态正确；
* Converter 不伪造字段。

## Reservation Correctness

* 状态机与真实 Manager 一致；
* 金额和数量守恒；
* Scope 不变；
* Version 和时间正确推进；
* Presence 与交易方向一致。

## Economic Integrity

* BUY OPEN 只包含合法 Reservation；
* SELL CLOSE 规则明确；
* Margin Presence 与 Fact 一致；
* Margin Delta 与 Account State 一致；
* Fee、Settlement、Risk、Reservation Scope 完整验证；
* 所有错误组合都会被拒绝。

## Fixture Integrity

* Generic T0 Cash Fixture 业务合法；
* Codec Projection Cases 与业务 Transaction 分离；
* 不存在非法 All-Projections Prepared Transaction；
* PR2 Baseline 使用真实 Manager Snapshot。

## CI

* Ruff 通过；
* Format Check 通过；
* Mypy 通过；
* Core Tests 通过；
* Architecture Tests 通过；
* Integration/Scenario/Conformance 通过；
* 插件离线测试通过；
* Build Smoke 通过。

---

# 十九、PR2 Go 判定

任务完成后必须增加明确测试或文档证明：

```text
真实 Generic T0 Cash Before Snapshots
→ Execution Before States
→ 合法 Expected After States
→ Ordered Projections
→ Preconditions
→ State Hash
→ Fact Draft
→ Prepared Transaction
```

并确认 PR2 不需要再次修改：

```text
Only*ExecutionState
Only*ExecutionProjection
OnlyExecutionPrecondition
OnlyExecutionProjectionIdentity
OnlyPreparedExecutionEconomicInvariantValidator
Reservation Presence Matrix
State Hash Contract
```

如果测试仍暴露 Contract 缺字段或公式不一致，必须在本 PR 内解决，不能留给 PR2。

---

# 二十、最终交付报告

完成后输出：

## 1. 修改前问题

列出：

* Account Margin 公式问题；
* Reservation 状态问题；
* Presence Matrix 缺失；
* Scope 校验缺失；
* Fixture 业务矛盾；
* Snapshot Parity 缺失。

## 2. 修正后的领域公式

明确列出：

```text
Account Available Cash
Account Available Margin
Account Equity
Ledger Cash Available
Ledger Equity
各 Reservation 守恒关系
```

## 3. Presence Matrix

列出 BUY OPEN、SELL CLOSE、Margin/Futures 的 Reservation 规则。

## 4. Scope 和经济验证

列出新增的全部跨组件检查。

## 5. Fixture 调整

说明：

* 删除了什么非法 Fixture；
* Codec 如何逐类型测试；
* Generic T0 Fixture 如何保证业务自洽。

## 6. Snapshot Parity

列出每个真实 Manager/Entity 的转换测试结果。

## 7. 删除内容

列出旧公式、旧测试、旧 Fixture、Alias 和绕过接口。

## 8. 测试结果

提供真实命令、测试数量和结果。

## 9. PR2 就绪结论

明确说明：

```text
PR2 可以开始
```

或者列出仍存在的真实阻塞项。

不得在问题未解决时仅根据测试数量声称 PR2 Ready。

---

# 最终目标

PR1.1.1 完成后，OnlyAlpha 必须满足：

```text
真实领域状态
=
Execution Replay State
```

以及：

```text
Prepared Transaction 构造成功
=
交易事实、状态变化、Reservation、Fee、Settlement、Margin 和 Risk 全部自洽
```

并保证 PR2 可以只关注：

```text
纯 Before → After 计算
```

而不再承担 Projection Contract 修复。

不要为了旧测试、旧 Fixture、旧示例或减少修改保留任何错误实现。
