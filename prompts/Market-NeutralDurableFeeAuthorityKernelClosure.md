# Codex 实施任务：PR4.1 Market-Neutral Durable Fee Authority Kernel Closure

工程：

```text
https://github.com/zongxin1993/OnlyAlpha
```

任务名称：

```text
PR4.1：Market-Neutral Durable Fee Authority Kernel Closure
PR4.1：市场中立 Durable 费用权威内核闭环
```

---

# 一、任务定位

本任务不是简单重构 `OnlyFeeEngine`，也不是增加几个费率枚举。

本任务必须从第一性原则出发，重新建立 OnlyAlpha 的交易费用领域：

```text
本地版本化费用规则
    ↓
订单费用合同绑定
    ↓
订单预估与资金预留
    ↓
真实 Fill 目标费用评估
    ↓
订单累计费用权威
    ↓
本 Fill 唯一费用增量
    ↓
Durable TRADE_FILL Transaction
    ↓
Fee Ledger / Account / Strategy Ledger / Settlement

券商实际费用证据
    ↓
Durable FEE_RECONCILIATION Transaction
    ↓
Matched / Adjustment / Trading Blocked
    ↓
Account / Strategy Ledger / Unallocated Fee Authority
```

PR4.1 完成后，OnlyAlpha 必须拥有：

1. 一个市场中立的本地费用计算内核；
2. 一个订单级累计费用权威；
3. 一个不可变的费用应用账本；
4. 一个标准化外部费用证据模型；
5. 一个 Durable 对账与差额调整入口；
6. 一套不会覆盖历史事实的费用恢复语义；
7. 一套能够支持股票、期货和数字货币交易费用的通用边界。

---

# 二、最高实施原则

实施优先级必须是：

```text
1. 业务语义正确
2. 权威唯一
3. 领域边界清晰
4. Durable Transaction 完整
5. 故障恢复确定
6. 多市场扩展不需要重写内核
7. 审计证据完整
8. 测试证明
9. 示例和文档
10. 历史兼容性
```

本任务不考虑历史兼容性。

当旧接口、旧测试、旧 Fixture、旧 Checkpoint、旧 Artifact 或旧示例与正确架构冲突时：

```text
删除旧接口
删除错误抽象
重写调用方
重写测试
提升 Schema
明确拒绝旧持久化
更新示例
```

禁止：

```text
Legacy Adapter
Deprecated Wrapper
新旧 DTO 双写
旧 Fee Engine 保留
旧 Checkpoint Migration
旧 Artifact Reader
兼容开关
按旧测试反向设计接口
```

不要为了让旧测试继续通过而保留错误抽象。

不要为了减少修改量，让一个 DTO 同时承担多个业务语义。

不要为了未来扩展创建没有当前业务使用者的空 Manager。

---

# 三、开始实施前的基线门禁

## 3.1 检查工作区

执行：

```bash
git status
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

不得覆盖用户现有未提交修改。

## 3.2 确认基线测试

执行：

```bash
uv sync --frozen --all-packages --all-groups
uv run python scripts/test_suite.py full
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py ashare
uv build --all-packages
```

如果基线存在与 PR4.1 无关的失败：

```text
在独立提交中修复
或
明确报告阻塞原因
```

不得把无关 CI 修复混入 Fee Kernel 业务提交。

不得以跳过测试作为绿色基线。

---

# 四、修改前强制审计

必须重新阅读最新 `master`，不能假设本提示词中的类名仍然完全准确。

至少阅读：

```text
AGENTS.md
README.md
docs/roadmap.md
docs/fee.md
docs/testing.md

docs/adr/
docs/reports/

src/onlyalpha/fee/
src/onlyalpha/order/
src/onlyalpha/execution/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/settlement/
src/onlyalpha/transaction/
src/onlyalpha/runtime/
src/onlyalpha/result/
src/onlyalpha/artifact/
src/onlyalpha/risk/

tests/fee/
tests/execution/
tests/account/
tests/recovery/
tests/architecture/
tests/integration/
tests/conformance/
packages/fake/onlyalpha-plugin-broker-virtual/
```

全仓搜索：

```text
OnlyFeeEngine
OnlyFeeCalculationRequest
OnlyFeeInstruction
OnlyFeeRateRule
OnlyFeeComponent
OnlyFeeBreakdown
OnlyFeeRecord
OnlyFeeReconciliationService
OnlyFeeAdjustmentInstruction

OnlyOrderFeeAccrual
ORDER_CUMULATIVE
reported_fee
reported_breakdown
broker_fee_reporting_mode

estimate_order
fee_reservation
authoritative_fee
incremental_fee
cumulative_fee

OnlyRuntimeOperationKind
ORDER_FEE_ACCRUAL
FEE
ACCOUNT
STRATEGY_LEDGER
SETTLEMENT
```

实施前输出审计报告，回答：

1. 当前唯一费用计算入口是什么；
2. 当前订单费用预估如何构造；
3. 当前是否伪造 Trade ID 进行 Order Estimate；
4. 当前 Market Fee 与 Broker Fee 如何解析；
5. 当前 Schedule 版本何时冻结；
6. 当前最低费用按 Fill 还是按 Order 累计；
7. 当前累计组件 Identity 包含哪些字段；
8. 当前 raw amount 是否依赖 metadata；
9. 当前 Account、Ledger、Settlement 分别消费什么费用对象；
10. 当前券商实际费用如何进入系统；
11. 当前对账是否 Durable；
12. 当前外部报告是否可以直接改变本地费用结果；
13. 当前 Checkpoint 是否保存费用累计权威；
14. 当前 Artifact 能否解释累计目标和本次增量；
15. 哪些旧接口必须删除；
16. 哪些模块不属于 PR4.1。

审计完成前，不得直接开始修改 Fee Rule。

---

# 五、第一性原则定义

## 5.1 费用不是一个金额

一项费用必须定义为：

```text
Fee Component
=
Authority
+
Rule Identity
+
Formula
+
Calculation Basis
+
Calculation Scope
+
Resolution Policy
+
Economic Direction
+
Bounds
+
Rounding
+
Currency
+
Effective Version
```

例如：

```text
股票监管税费
    Authority          = REGULATOR
    Formula            = Rate
    Basis              = NOTIONAL
    Scope              = FILL
    Resolution         = FILL_EFFECTIVE
    Direction          = CHARGE

券商最低佣金
    Authority          = BROKER
    Formula            = Rate
    Basis              = NOTIONAL
    Scope              = ORDER_CUMULATIVE
    Resolution         = ORDER_FIXED
    Direction          = CHARGE

期货按手手续费
    Authority          = VENUE
    Formula            = Per Unit
    Basis              = CONTRACTS
    Scope              = FILL
    Resolution         = FILL_EFFECTIVE
    Direction          = CHARGE

数字货币 Maker 返佣
    Authority          = VENUE
    Formula            = Rate
    Basis              = NOTIONAL
    Scope              = FILL
    Resolution         = FILL_EFFECTIVE
    Direction          = REBATE
```

## 5.2 本地计算事实和券商实际证据必须分离

本地 Fee Policy 产生：

```text
Local Fee Assessment
Local Fee Application
```

券商返回：

```text
External Fee Evidence
```

二者不能使用同一个 DTO。

券商报告不能作为 `OnlyFeeEngine` 的参数。

券商插件不得直接修改：

```text
Account
Strategy Ledger
Settlement
Fee Ledger
Order Fee Accrual
```

## 5.3 Target 和 Application 必须分离

Fee Engine 只计算：

```text
当前规则要求的目标费用
```

Fee Accrual Authority 才计算：

```text
本次真正需要应用的经济增量
```

对于 `FILL`：

```text
incremental = current_fill_target
```

对于 `ORDER_CUMULATIVE`：

```text
incremental
=
cumulative_target_after
-
cumulative_applied_before
```

下游只能消费 Application，不能消费 Target。

## 5.4 历史事实不可覆盖

禁止：

```python
old_fee_record.amount = broker_reported_amount
old_execution_fact.fee = broker_reported_amount
old_settlement_instruction.net_cash_flow = recalculated_value
```

最终经济事实必须是：

```text
Local Fee Application
+
External Fee Evidence
+
Reconciliation Decision
+
Fee Adjustment
=
Current Confirmed Fee
```

## 5.5 调整必须来自对账事务

不能提供：

```text
AccountManager.adjust_fee(...)
StrategyLedgerManager.adjust_fee(...)
BrokerPlugin.apply_fee(...)
```

正式入口只能是：

```text
OnlyExternalFeeEvidence
→ OnlyFeeReconciliationPlanner
→ FEE_RECONCILIATION Durable Transaction
```

---

# 六、PR4.1 实现范围

## 6.1 必须实现

```text
市场中立 Fee Domain
显式计算基础
显式公式
显式计算范围
显式版本解析策略
显式费用方向
显式舍入策略
显式 Bounds/Rounding Pipeline

版本化 Market/Broker Schedule
显式 Fee Policy Pack
显式 Order Fee Policy Binding

Order Fee Estimate
Order Funding Plan
Trade Fee Assessment
Order Fee Accrual
Fee Application Instruction
Fee Application Ledger

Durable TRADE_FILL 费用接线

External Fee Evidence
Durable Fee Reconciliation
Fee Adjustment
Account/Strategy Ledger/Unallocated Adjustment
Trading Block Gate

Checkpoint
Persistence
Recovery
Result
Artifact
多市场 Conformance Tests
```

## 6.2 不实现

```text
正式 CN_A_SHARE_CASH 费率包
真实券商网络连接
真实券商 Statement 下载
真实券商插件适配
A 股交易能力开放
中国期货正式产品费用
数字货币正式 VIP 阶梯费率
融资利息
融券费用
Funding Interval
账户日费
账户月费
多币种换汇
税务申报
```

PR4.1 提供市场中立内核和 Generic Conformance Pack。

正式 A 股 Fee Pack 留给 PR4.2。

---

# 七、多市场设计约束

## 7.1 通用内核不得识别具体市场

以下目录不得包含：

```text
CN_A_SHARE
SSE
SZSE
STAR
CHINEXT
具体印花税率
最低五元
BTC
某个期货交易所名称
```

适用目录：

```text
src/onlyalpha/fee/models.py
src/onlyalpha/fee/formula.py
src/onlyalpha/fee/policy.py
src/onlyalpha/fee/engine.py
src/onlyalpha/fee/accrual.py
src/onlyalpha/fee/reconciliation.py
```

禁止：

```python
if market_profile_id == "CN_A_SHARE_CASH":
    ...
```

## 7.2 当前支持的交易费用范围

PR4.1 正式支持：

```text
FILL
ORDER_CUMULATIVE
```

当前不支持：

```text
ACCOUNT_DAILY
ACCOUNT_MONTHLY
POSITION_DAILY
SETTLEMENT_BATCH
FUNDING_INTERVAL
```

遇到未实现范围必须返回明确 Unsupported，不能伪装支持。

## 7.3 币种边界

PR4.1 不实现 FX Conversion。

要求：

```text
Fee Component Currency
=
Settlement Cash Currency
=
Account Currency
```

否则：

```text
FEE_CURRENCY_CONVERSION_UNSUPPORTED
```

禁止隐式 1:1 换算。

## 7.4 多市场证明

必须使用至少三个 Generic Pack 证明内核无市场硬编码：

```text
Generic Cash
    NOTIONAL RATE

Generic Futures
    CONTRACTS PER_UNIT

Generic Crypto Spot
    NOTIONAL RATE
    MAKER / TAKER selector
    CHARGE / REBATE
```

这些 Pack 只用于架构与 Conformance，不代表真实产品费率。

---

# 八、核心领域模型

## 8.1 Calculation Basis

新增：

```python
class OnlyFeeCalculationBasis(StrEnum):
    NOTIONAL = "NOTIONAL"
    QUANTITY = "QUANTITY"
    CONTRACTS = "CONTRACTS"
```

固定费用不需要 Basis。

不要提前增加没有当前使用者的：

```text
PREMIUM
MARGIN_BALANCE
BORROW_BALANCE
CALENDAR_DAYS
TRADING_DAYS
```

## 8.2 Formula Terms

不要使用一个包含大量 Optional 字段的 Formula。

新增显式类型：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeRateTerm:
    basis: OnlyFeeCalculationBasis
    rate: Decimal
```

```python
@dataclass(frozen=True, slots=True)
class OnlyFeePerUnitTerm:
    basis: OnlyFeeCalculationBasis
    amount_per_unit: Decimal
```

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeFixedTerm:
    amount: Decimal
```

```python
OnlyFeeFormulaTerm = (
    OnlyFeeRateTerm
    | OnlyFeePerUnitTerm
    | OnlyFeeFixedTerm
)
```

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeFormula:
    terms: tuple[OnlyFeeFormulaTerm, ...]
```

公式结果：

```text
sum(term.evaluate(basis))
```

支持：

```text
Rate
Per Unit
Fixed
Rate + Per Unit
Rate + Fixed
```

要求：

```text
terms 非空
所有参数非负
全部使用 Decimal
禁止 Float
禁止依赖 Decimal 全局 Context
非法 Formula 在构造时失败
```

## 8.3 Basis Values

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeBasisValues:
    notional: OnlyMoney
    quantity: Decimal
    contracts: Decimal
```

Formula 只能读取自己声明的 Basis。

禁止使用：

```text
dict[str, Decimal]
Mapping[str, object]
```

作为正式领域输入。

## 8.4 Economic Direction

```python
class OnlyFeeEconomicDirection(StrEnum):
    CHARGE = "CHARGE"
    REBATE = "REBATE"
```

金额始终非负。

```text
CHARGE
    cash effect = -amount

REBATE
    cash effect = +amount
```

禁止使用负 Fee Amount 表示返佣。

## 8.5 Calculation Scope

```python
class OnlyFeeCalculationScope(StrEnum):
    FILL = "FILL"
    ORDER_CUMULATIVE = "ORDER_CUMULATIVE"
```

不能通过 minimum 是否为零推断 Scope。

## 8.6 Resolution Policy

```python
class OnlyFeeResolutionPolicy(StrEnum):
    FILL_EFFECTIVE = "FILL_EFFECTIVE"
    ORDER_FIXED = "ORDER_FIXED"
```

```text
FILL_EFFECTIVE
    每个 Fill 按成交交易日解析有效版本

ORDER_FIXED
    Order 接受时冻结精确版本
```

同一订单的 `ORDER_FIXED` Policy 不得在后续 Fill 中切换。

## 8.7 Rounding Policy

```python
class OnlyFeeRoundingMode(StrEnum):
    HALF_EVEN = "HALF_EVEN"
    HALF_UP = "HALF_UP"
    CEILING = "CEILING"
    FLOOR = "FLOOR"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeRoundingPolicy:
    quantum: Decimal
    mode: OnlyFeeRoundingMode
```

要求：

```text
quantum > 0
Policy 可稳定序列化
Policy 进入 Rule Fingerprint
```

## 8.8 Calculation Pipeline

```python
class OnlyFeeCalculationPipeline(StrEnum):
    BOUNDS_THEN_ROUND = "BOUNDS_THEN_ROUND"
    ROUND_THEN_BOUNDS = "ROUND_THEN_BOUNDS"
```

不要在 Engine 中写死 Minimum 和 Rounding 顺序。

## 8.9 Fee Rule

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeRule:
    rule_id: str

    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    economic_direction: OnlyFeeEconomicDirection

    formula: OnlyFeeFormula
    calculation_scope: OnlyFeeCalculationScope
    resolution_policy: OnlyFeeResolutionPolicy

    minimum: Decimal | None
    maximum: Decimal | None

    side: OnlyOrderSide | None
    offset: OnlyOffset | None
    liquidity_role: OnlyLiquiditySide | None

    rounding: OnlyFeeRoundingPolicy
    pipeline: OnlyFeeCalculationPipeline
```

校验：

```text
rule_id 非空
minimum >= 0
maximum >= 0
minimum <= maximum
Formula 非空
Rounding Quantum 有效
ORDER_CUMULATIVE Formula 必须对累计 Basis 单调非递减
```

---

# 九、Schedule、Registry 与 Pack

## 9.1 Schedule Identity

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeScheduleIdentity:
    schedule_id: str
    version: str
    fingerprint: str
```

Fingerprint 必须覆盖：

```text
Schedule ID
Version
Effective Range
Currency
Source
Rule Identity
Formula
Scope
Resolution
Direction
Bounds
Rounding
Pipeline
Selectors
```

## 9.2 Market 和 Broker Schedule

保留强类型：

```text
OnlyMarketFeeSchedule
OnlyBrokerFeeSchedule
```

不要用一个 `kind` 字符串弱化边界。

Market Schedule 包含：

```text
market
venue
instrument_class
```

Broker Schedule 包含：

```text
broker_id
account_scope
```

## 9.3 Registry

Registry 只负责：

```text
注册不可变版本
检测时间区间重叠
按交易日解析
按精确版本解析
验证 Fingerprint
```

Registry 不负责：

```text
自动安装默认规则
读取 Account
读取 Runtime
读取 Order
计算费用
```

删除隐式内置 Registry 安装函数。

## 9.4 Fee Policy Pack

```python
@dataclass(frozen=True, slots=True)
class OnlyFeePolicyPack:
    pack_id: str
    pack_version: str
    compatible_market_profiles: tuple[str, ...]
    market_schedules: tuple[OnlyMarketFeeSchedule, ...]
    fingerprint: str
```

Runtime 必须显式安装 Pack。

没有 Pack 时：

```text
FEE_PACK_NOT_INSTALLED
```

不能静默使用默认费率。

---

# 十、Order Fee Policy Binding

新增不可变订单费用绑定：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeePolicyBinding:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId

    market_profile_id: str
    market_profile_version: str

    order_fixed_schedules: tuple[OnlyFeeScheduleIdentity, ...]
    fill_effective_schedule_ids: tuple[str, ...]

    charge_currency: OnlyCurrency

    bound_at: OnlyTimestamp
    fingerprint: str
```

该 Binding 必须进入正式 Order Snapshot。

禁止使用 Runtime 私有字典保存。

同一订单：

```text
相同 Binding 重复安装
    IDEMPOTENT

不同 Binding 重复安装
    ORDER_FEE_BINDING_CONFLICT
```

后续 Fill 必须验证 `ORDER_FIXED` Schedule Fingerprint 未变化。

---

# 十一、拆分 Request

删除统一的：

```text
OnlyFeeCalculationRequest
```

## 11.1 Fee Subject

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeSubject:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId
    instrument_id: OnlyInstrumentId
```

## 11.2 Order Estimate Request

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeEstimateRequest:
    subject: OnlyFeeSubject

    side: OnlyOrderSide
    offset: OnlyOffset

    expected_basis: OnlyFeeBasisValues
    full_order_basis: OnlyFeeBasisValues

    expected_fill_count: int
    maximum_fill_count: int | None

    trading_day: OnlyTradingDay
    binding: OnlyOrderFeePolicyBinding
    policies: OnlyResolvedFeePolicySet
```

不能包含：

```text
trade_id
reported_fee
reported_breakdown
broker reporting mode
```

## 11.3 Trade Assessment Request

```python
@dataclass(frozen=True, slots=True)
class OnlyTradeFeeAssessmentRequest:
    subject: OnlyFeeSubject
    trade_id: OnlyTradeId

    fill_basis: OnlyFeeBasisValues
    cumulative_order_basis: OnlyFeeBasisValues

    trading_day: OnlyTradingDay
    liquidity_role: OnlyLiquiditySide | None

    local_finality: OnlyLocalFeeFinality

    binding: OnlyOrderFeePolicyBinding
    policies: OnlyResolvedFeePolicySet
```

---

# 十二、本地费用最终性

```python
class OnlyLocalFeeFinality(StrEnum):
    ESTIMATED = "ESTIMATED"
    MODEL_PROVISIONAL = "MODEL_PROVISIONAL"
    MODEL_CONFIRMED = "MODEL_CONFIRMED"
```

语义：

```text
Backtest
    MODEL_CONFIRMED

Paper
    MODEL_CONFIRMED

Live
    MODEL_PROVISIONAL
```

删除本地记录中的：

```text
ADJUSTED
REVERSED
```

调整和冲回必须是独立事实，不能修改本地费用记录的状态。

---

# 十三、Fee Engine

新的 `OnlyFeeEngine` 必须是纯领域服务。

不能导入：

```text
Runtime Manager
Account Manager
Order Manager
Broker Plugin
External Fee Evidence
Reconciliation
Clock
Persistence Store
```

算法：

```text
Selector Match
→ Select Basis
→ Evaluate Formula
→ Apply Pipeline
→ Produce Target Component
```

## 13.1 Target Component

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeTargetComponent:
    identity: OnlyFeeComponentIdentity

    raw_amount: OnlyMoney
    bounded_amount: OnlyMoney
    target_amount: OnlyMoney

    local_finality: OnlyLocalFeeFinality
```

禁止继续把 `raw_amount` 放入 metadata。

## 13.2 Assessment

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeAssessment:
    assessment_id: str
    subject: OnlyFeeSubject
    trade_id: OnlyTradeId | None

    components: tuple[OnlyFeeTargetComponent, ...]

    total_charges: OnlyMoney
    total_rebates: OnlyMoney

    policy_fingerprint: str
    local_finality: OnlyLocalFeeFinality
```

---

# 十四、订单费用预估

订单预估必须区分：

```text
Expected Fee
Maximum Fee
Reservation Fee
```

## 14.1 Split-insensitive Rule

例如：

```text
NOTIONAL RATE
QUANTITY PER_UNIT
CONTRACTS PER_UNIT
```

可以基于完整订单 Basis 估算。

## 14.2 Split-sensitive Rule

例如：

```text
FILL Fixed Fee
FILL Minimum Fee
FILL Maximum Fee
```

如果缺少 `maximum_fill_count`，不得伪造最大值：

```text
FEE_ESTIMATE_MAXIMUM_FILL_COUNT_REQUIRED
```

## 14.3 Estimate Result

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeEstimate:
    expected: OnlyFeeAssessment
    maximum: OnlyFeeAssessment

    reservation_charge: OnlyMoney
    estimated_rebate: OnlyMoney

    assumptions_fingerprint: str
```

Reservation 只能使用 Maximum Charge。

不能用预计 Rebate 降低资金预留。

---

# 十五、Order Funding Plan

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFundingPlan:
    order_id: OnlyOrderId

    principal_reservation: OnlyMoney
    fee_reservation: OnlyMoney
    total_reservation: OnlyMoney

    binding_fingerprint: str
    estimate_fingerprint: str
```

只生成一次 Funding Plan。

Account Reservation 和 Strategy Ledger Reservation 必须共同消费该 Plan。

禁止两者分别调用 Fee Engine。

必须满足：

```text
Account Fee Reservation
=
Strategy Fee Reservation
=
Funding Plan Fee Reservation
```

---

# 十六、Fee Component Identity

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeComponentIdentity:
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    source_id: str

    schedule_id: str
    schedule_version: str
    schedule_fingerprint: str

    rule_id: str
    rule_fingerprint: str

    calculation_scope: OnlyFeeCalculationScope
    resolution_policy: OnlyFeeResolutionPolicy
    economic_direction: OnlyFeeEconomicDirection
```

Component Identity 必须稳定排序和序列化。

禁止依赖 Mapping 插入顺序。

---

# 十七、Order Fee Accrual Authority

删除：

```text
OnlyOrderFeeAccrualExecutionState
```

替换为：

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeComponentAccrual:
    identity: OnlyFeeComponentIdentity

    cumulative_raw_amount: OnlyMoney
    cumulative_target_amount: OnlyMoney
    cumulative_applied_amount: OnlyMoney
```

```python
@dataclass(frozen=True, slots=True)
class OnlyOrderFeeAccrualState:
    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    order_id: OnlyOrderId

    currency: OnlyCurrency

    cumulative_fill_quantity: OnlyQuantity
    cumulative_fill_notional: OnlyMoney

    cumulative_charges: OnlyMoney
    cumulative_rebates: OnlyMoney

    order_fixed_policy_fingerprint: str

    components: tuple[OnlyOrderFeeComponentAccrual, ...]

    fill_count: int
    last_trade_id: OnlyTradeId
    updated_at: OnlyTimestamp
    version: int
```

## 17.1 FILL 算法

```text
incremental = current target

raw after
    = raw before + current raw

target after
    = target before + current target

applied after
    = applied before + current target
```

## 17.2 ORDER_CUMULATIVE 算法

```text
incremental
=
current cumulative target
-
cumulative applied before
```

```text
raw after
    = current cumulative raw

target after
    = current cumulative target

applied after
    = applied before + incremental
```

负增量：

```text
FEE_ACCRUAL_NEGATIVE_INCREMENT
```

不得通过负增量退款。

同一订单 Order-fixed Policy 变化：

```text
ORDER_CUMULATIVE_FEE_POLICY_CHANGED
```

---

# 十八、Fee Application Instruction

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationComponent:
    identity: OnlyFeeComponentIdentity

    amount: OnlyMoney
    economic_direction: OnlyFeeEconomicDirection

    fill_raw_amount: OnlyMoney

    cumulative_raw_after: OnlyMoney
    cumulative_target_after: OnlyMoney
    cumulative_applied_before: OnlyMoney
    cumulative_applied_after: OnlyMoney
```

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationInstruction:
    application_id: str

    subject: OnlyFeeSubject
    trade_id: OnlyTradeId

    components: tuple[OnlyFeeApplicationComponent, ...]

    total_charges: OnlyMoney
    total_rebates: OnlyMoney
    signed_cash_effect: Decimal

    accrual_before_fingerprint: str | None
    accrual_after_fingerprint: str

    local_finality: OnlyLocalFeeFinality
    idempotency_key: str
```

这是本 Fill 唯一费用经济命令。

以下组件只能消费该 Instruction：

```text
Fee Ledger
Account Reducer
Strategy Ledger Reducer
Settlement Planner
Committed Fact Builder
Result Collector
Artifact Writer
```

---

# 十九、Fee Application Ledger

删除旧简单 Fee Record。

新增：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeApplicationRecord:
    record_id: str
    application_id: str

    runtime_id: OnlyRuntimeId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId
    instrument_id: OnlyInstrumentId
    order_id: OnlyOrderId
    trade_id: OnlyTradeId

    component_identity: OnlyFeeComponentIdentity

    fill_raw_amount: OnlyMoney
    cumulative_raw_after: OnlyMoney
    cumulative_target_after: OnlyMoney
    cumulative_applied_before: OnlyMoney

    incremental_amount: OnlyMoney
    cumulative_applied_after: OnlyMoney

    local_finality: OnlyLocalFeeFinality
    sequence: int
```

单条记录必须能够解释：

```text
费用来源
计算公式
计算基础
规则版本
舍入规则
原始金额
累计目标
此前已应用
本次应用
本地最终性
```

---

# 二十、TRADE_FILL Durable 接线

推荐 Projection 顺序：

```text
1. ORDER
2. POSITION
3. ALLOCATION
4. SETTLEMENT
5. MARGIN
6. ORDER_FEE_ACCRUAL
7. FEE_LEDGER
8. ACCOUNT
9. STRATEGY_LEDGER
10. ACCOUNT_CASH_RESERVATION
11. STRATEGY_CASH_RESERVATION
12. POSITION_RESERVATION
13. MARGIN_RESERVATION
14. RISK_RESERVATION
15. RISK
16. VALUATION
```

重命名：

```text
FEE
→ FEE_LEDGER

OnlyOrderFeeAccrualExecutionProjection
→ OnlyOrderFeeAccrualProjection

OnlyFeeExecutionProjection
→ OnlyFeeApplicationProjection
```

同一 Fill 必须满足：

```text
Application Charges
=
Fee Ledger Charge Delta
=
Account Charge Delta
=
Strategy Ledger Charge Delta
=
Settlement Charge Effect
=
Committed Fact Charges

Application Rebates
=
Fee Ledger Rebate Delta
=
Account Rebate Delta
=
Strategy Ledger Rebate Delta
=
Settlement Rebate Effect
=
Committed Fact Rebates
```

任何不一致必须在 Prepare 阶段失败。

---

# 二十一、Account、Strategy Ledger 与 Settlement

## 21.1 Account

```text
CHARGE:
    cash delta = -amount
    cumulative fees += amount

REBATE:
    cash delta = +amount
    cumulative rebates += amount
```

## 21.2 Strategy Ledger

按真实 Component 类型和方向生成 Entry。

禁止把所有费用统一映射为 `COMMISSION`。

## 21.3 Settlement

买入：

```text
net cash flow
=
-gross notional
-total charges
+total rebates
```

卖出：

```text
net cash flow
=
gross notional
-total charges
+total rebates
```

Settlement 不得导入 Fee Engine 或 Fee Schedule。

---

# 二十二、外部券商费用证据

## 22.1 Evidence Mode

```python
class OnlyExternalFeeEvidenceMode(StrEnum):
    COMMISSION_ONLY = "COMMISSION_ONLY"
    DETAILED = "DETAILED"
    ALL_IN = "ALL_IN"
    ORDER_CUMULATIVE = "ORDER_CUMULATIVE"
    DEFERRED_STATEMENT = "DEFERRED_STATEMENT"
```

## 22.2 Evidence Scope

```python
class OnlyExternalFeeEvidenceScope(StrEnum):
    TRADE = "TRADE"
    ORDER = "ORDER"
    STATEMENT = "STATEMENT"
```

## 22.3 Evidence Model

```python
@dataclass(frozen=True, slots=True)
class OnlyExternalFeeEvidence:
    evidence_id: str

    broker_id: str
    account_id: OnlyAccountId

    scope: OnlyExternalFeeEvidenceScope
    mode: OnlyExternalFeeEvidenceMode

    external_reference: str
    report_version: str
    content_fingerprint: str

    trade_id: OnlyTradeId | None
    order_id: OnlyOrderId | None
    statement_scope: str | None

    reported_total: OnlyMoney | None
    reported_components: tuple[OnlyExternalFeeComponent, ...]

    effective_at: OnlyTimestamp
    received_at: OnlyTimestamp
```

范围校验：

```text
TRADE
    必须有 trade_id

ORDER
    必须有 order_id

STATEMENT
    必须有 statement_scope
```

Evidence 是不可变事实，不是命令。

---

# 二十三、Evidence 幂等与修订

Evidence Identity 至少包含：

```text
broker_id
account_id
external_reference
report_version
content_fingerprint
```

相同 Reference、Version、Content：

```text
DUPLICATE_EVIDENCE
```

相同 Reference、Version、不同 Content：

```text
EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT
```

券商修订报告必须使用新的 `report_version`。

禁止覆盖旧 Evidence。

---

# 二十四、Durable Fee Reconciliation

在 Runtime Operation 中新增：

```python
class OnlyRuntimeOperationKind(StrEnum):
    TRADE_FILL = "TRADE_FILL"
    ORDER_TERMINAL = "ORDER_TERMINAL"
    SETTLEMENT_MATURITY = "SETTLEMENT_MATURITY"
    FEE_RECONCILIATION = "FEE_RECONCILIATION"
```

不要新增一个可以绕开对账直接执行的公开 `FEE_ADJUSTMENT` Operation。

调整必须是 `FEE_RECONCILIATION` 的可选 Projection。

---

# 二十五、Reconciliation Authority

## 25.1 状态

```python
class OnlyFeeReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    RECONCILED_WITH_ADJUSTMENT = "RECONCILED_WITH_ADJUSTMENT"
    INCOMPLETE_EXTERNAL_DATA = "INCOMPLETE_EXTERNAL_DATA"
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    UNEXPLAINED_DIFFERENCE = "UNEXPLAINED_DIFFERENCE"
    TRADING_BLOCKED = "TRADING_BLOCKED"
```

## 25.2 Decision

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationDecision:
    reconciliation_id: str
    evidence_id: str

    scope: OnlyExternalFeeEvidenceScope

    local_model_amount: OnlyMoney | None
    prior_adjustments: OnlyMoney
    current_effective_amount: OnlyMoney | None
    reported_authoritative_amount: OnlyMoney | None

    difference: OnlyMoney | None

    reason: OnlyFeeDifferenceReason | None
    status: OnlyFeeReconciliationStatus

    adjustment: OnlyFeeAdjustment | None
```

## 25.3 当前有效费用

对账不能永远只比较原始本地费用。

定义：

```text
current effective fee
=
sum(local fee applications in scope)
+
sum(previous fee adjustments in scope)
```

新调整：

```text
new adjustment
=
reported authoritative fee
-
current effective fee
```

这样可以正确处理：

```text
重复报告
订单累计报告
券商后续修订
前一次已补扣
后续退款
```

---

# 二十六、不同 Evidence Mode 的对账语义

## 26.1 COMMISSION_ONLY

只比较本地：

```text
BROKER_COMMISSION
```

不得把市场税费加入比较对象。

## 26.2 DETAILED

按稳定 Component Identity 对账：

```text
Fee Type
Authority
External Component ID
Currency
```

## 26.3 ALL_IN

比较 Scope 内的全部本地费用与券商总费用。

禁止再次叠加本地 Market Fee。

## 26.4 ORDER_CUMULATIVE

Reported Amount 表示订单累计费用。

比较：

```text
reported cumulative amount
与
当前订单累计有效费用
```

不得把累计值当作本次增量直接记账。

## 26.5 DEFERRED_STATEMENT

本地 Live Fee 保持 `MODEL_PROVISIONAL`。

Statement 到达后再生成确认或调整事实。

---

# 二十七、Fee Adjustment

```python
class OnlyFeeAdjustmentDirection(StrEnum):
    SUPPLEMENTAL_CHARGE = "SUPPLEMENTAL_CHARGE"
    REFUND = "REFUND"
```

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeAdjustment:
    adjustment_id: str

    direction: OnlyFeeAdjustmentDirection
    amount: OnlyMoney

    account_id: OnlyAccountId
    cluster_id: OnlyClusterId | None

    order_id: OnlyOrderId | None
    trade_id: OnlyTradeId | None
    statement_scope: str | None

    evidence_id: str
    reconciliation_id: str
    reason: OnlyFeeDifferenceReason
```

金额保持非负。

方向决定有符号经济影响。

---

# 二十八、对账差异处理

## 28.1 完全一致

```text
Local = Reported
→ MATCHED
→ 不修改 Account
→ 仍然 Durable Commit Evidence 和 Decision
```

## 28.2 本地少收

```text
Local Effective = 5.00
Reported = 5.23
Adjustment = Supplemental Charge 0.23
```

## 28.3 本地多收

```text
Local Effective = 5.00
Reported = 4.80
Adjustment = Refund 0.20
```

## 28.4 重大未知差异

```text
reason = UNKNOWN
abs(difference) > materiality threshold
```

结果：

```text
TRADING_BLOCKED
```

禁止创建 `OTHER` Fee 强制平账。

---

# 二十九、Statement Scope 和无法归属的调整

如果 Trade 或 Order 能明确找到 Cluster：

```text
同时调整 Account 和 Strategy Ledger
```

如果 Statement Scope 无法可靠归属 Cluster：

```text
只调整 Account
记录为 UNALLOCATED_EXTERNAL_FEE
不得猜测分摊给 Strategy
```

新增显式账户级权威，例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyUnallocatedExternalFeeState:
    account_id: OnlyAccountId
    cumulative_charges: OnlyMoney
    cumulative_refunds: OnlyMoney
    version: int
```

Account 与 Strategy Ledger 的一致性定义必须变为：

```text
Account economic result
=
sum(strategy ledger results)
+
unallocated external adjustments
+
其他明确账户级权威
```

不得用未知差异破坏现有 Parity 后继续运行。

---

# 三十、FEE_RECONCILIATION Projection 顺序

推荐：

```text
1. EXTERNAL_FEE_EVIDENCE
2. FEE_RECONCILIATION
3. FEE_ADJUSTMENT_LEDGER（可选）
4. ACCOUNT（可选）
5. STRATEGY_LEDGER（可选）
6. UNALLOCATED_EXTERNAL_FEE（可选）
7. RECONCILIATION_RISK_GATE
8. VALUATION（可选）
```

新增对应：

```text
Projection Component
Projection Order
Projection Model
Projection Target
Codec
State Hash
Checkpoint
Recovery
```

任何 Manager 都不得绕过 Transaction Coordinator 安装结果。

---

# 三十一、Trading Block Gate

`TRADING_BLOCKED` 必须阻止：

```text
新开仓
增加现有风险
增加资金占用
```

必须允许：

```text
查询
撤单
平仓
降低风险
继续提交外部证据
完成对账
```

不要把 Trading Block 简化为 Runtime 全部停止。

Risk Gate 必须有：

```text
明确状态
明确原因
Evidence ID
Reconciliation ID
版本
Checkpoint
恢复语义
```

---

# 三十二、Persistence 与 Schema

PR4.1 是破坏性 Schema 升级。

重新审计当前 Schema 后提升版本。

当前基线若为 Runtime Transaction Schema 5，PR4.1 应升级到 6。

必须升级：

```text
Runtime Transaction Schema
Checkpoint Schema
Fee Ledger Schema
Order Snapshot Schema
Result Schema
Artifact Schema
```

旧版本：

```text
明确拒绝
Fail Closed
稳定错误码
```

禁止：

```text
旧字段填默认值
隐式转换
双写
自动迁移
兼容 Reader
```

建议错误：

```text
UNSUPPORTED_RUNTIME_TRANSACTION_SCHEMA
UNSUPPORTED_FEE_CHECKPOINT_SCHEMA
UNSUPPORTED_ORDER_FEE_BINDING_SCHEMA
UNSUPPORTED_FEE_ARTIFACT_SCHEMA
```

---

# 三十三、Recovery 要求

## 33.1 TRADE_FILL

覆盖：

```text
Commit 后故障
Order Fee Accrual Projection 后故障
Fee Ledger Projection 后故障
Settlement Projection 后故障
Account Projection 后故障
Strategy Ledger Projection 后故障
Reservation Projection 后故障
Ready 前故障
Outbox 前故障
```

## 33.2 FEE_RECONCILIATION

覆盖：

```text
Evidence Projection 后故障
Decision Projection 后故障
Adjustment Ledger 后故障
Account Adjustment 后故障
Strategy Ledger Adjustment 后故障
Unallocated Fee Projection 后故障
Risk Gate 后故障
Ready 前故障
Outbox 前故障
```

要求：

```text
Committed Transaction 永不回滚
只允许 Forward Recovery
重复执行幂等
State Hash 不一致 Fail Closed
```

最终：

```text
连续运行
==
A→B→C Restart
```

---

# 三十四、Result 与 Artifact

新增或重建：

```text
fee_schedules.parquet
fee_policy_packs.parquet
order_fee_bindings.parquet
order_fee_estimates.parquet
order_funding_plans.parquet
order_fee_accruals.parquet
fee_applications.parquet

external_fee_evidence.parquet
fee_reconciliations.parquet
fee_adjustments.parquet
unallocated_external_fees.parquet

runtime_transactions.parquet
```

Fee Application 输出：

```text
formula
basis
scope
resolution policy
direction
raw amount
bounded amount
target amount
incremental amount
cumulative target
cumulative applied
schedule fingerprint
rule fingerprint
local finality
```

Reconciliation 输出：

```text
evidence identity
scope
mode
local model amount
prior adjustments
current effective amount
reported amount
difference
reason
status
adjustment identity
```

所有 Decimal 必须稳定序列化。

禁止使用自由 Mapping 作为长期正式 Artifact Schema。

---

# 三十五、删除清单

直接删除或替换：

```text
OnlyFeeRateRule
OnlyFeeCalculationRequest
OnlyFeeInstruction

OnlyFeeComponent 的 raw_amount metadata 语义
OnlyFeeStatus.ADJUSTED
OnlyFeeStatus.REVERSED

OnlyFeeConfigurationMode.DEFAULT
OnlyFeeConfigurationMode.REPORTED

OnlyFeeAdjustmentInstruction
OnlyFeeReconciliationService
OnlyFeeReconciliationResult

OnlyOrderFeeAccrualExecutionState
OnlyOrderFeeAccrualExecutionProjection
OnlyFeeExecutionProjection

only_builtin_market_fee_schedule_registry
only_builtin_broker_fee_schedule_registry

OnlyMarketFeeScheduleResolver 别名
OnlyBrokerFeeScheduleResolver 别名
```

替换为：

```text
OnlyFeeRule
OnlyFeeFormula
OnlyFeeBasisValues
OnlyOrderFeeEstimateRequest
OnlyTradeFeeAssessmentRequest
OnlyFeeAssessment
OnlyOrderFeePolicyBinding
OnlyOrderFeeAccrualState
OnlyFeeApplicationInstruction
OnlyFeeApplicationRecord

OnlyExternalFeeEvidence
OnlyFeeReconciliationDecision
OnlyFeeAdjustment
```

不保留兼容别名。

---

# 三十六、建议文件结构

```text
src/onlyalpha/fee/
    models.py
    basis.py
    formula.py
    rounding.py
    policy.py
    schedules.py
    registry.py
    packs.py
    binding.py
    estimate.py
    assessment.py
    accrual.py
    application.py
    ledger.py
    evidence.py
    reconciliation.py
    adjustment.py
    invariants.py
```

Generic Pack：

```text
src/onlyalpha/fee/packs/
    __init__.py
    generic_t0_cash.py
    generic_margin_futures.py
    generic_crypto_spot.py
```

禁止创建职责模糊的：

```text
fee_utils.py
fee_helper.py
fee_common.py
legacy_fee.py
compat_fee.py
```

---

# 三十七、建议实施顺序

## Commit 0：绿色基线

修复所有与 PR4.1 无关的基线失败。

确认：

```text
full
recovery
ashare
build
```

通过。

## Commit 1：ADR 与审计报告

新增：

```text
Market-Neutral Durable Fee Authority
Local Fee and External Evidence Separation
Order-Cumulative Fee Authority
Durable Fee Reconciliation
```

## Commit 2：Formula、Basis、Direction、Rounding

删除 `OnlyFeeRateRule`。

建立市场中立费用语言。

## Commit 3：Schedule、Registry、Pack

分离 Generic Pack 和 Core。

删除隐式默认 Registry。

## Commit 4：Binding、Estimate、Funding Plan

把 Fee Binding 进入 Order Snapshot。

完成安全 Reservation。

## Commit 5：Assessment、Accrual、Application

完成 Target/Application 分离和订单累计增量。

## Commit 6：TRADE_FILL Durable 接线

完成 Fee Ledger、Account、Ledger、Settlement、Fact 一致性。

## Commit 7：External Fee Evidence

完成不可变 Evidence Authority 和 Persistence。

## Commit 8：FEE_RECONCILIATION

完成 Matched、Adjustment、Unallocated 和 Trading Block。

## Commit 9：Recovery、Artifact、架构扫描

完成故障矩阵、A→B→C、Parquet 和旧接口删除。

不要把全部修改压缩成一个巨大提交。

---

# 三十八、测试矩阵

## 38.1 Formula

```text
Rate × Notional
Per Unit × Quantity
Per Unit × Contracts
Fixed
Rate + Per Unit
Rate + Fixed
Selector Match
Selector Mismatch
```

## 38.2 Rounding

```text
HALF_EVEN
HALF_UP
CEILING
FLOOR

BOUNDS_THEN_ROUND
ROUND_THEN_BOUNDS
```

## 38.3 Rule Validation

```text
空 Rule ID
空 Formula
负 Rate
负 Per Unit
负 Fixed
minimum > maximum
无效 Quantum
非法 Scope/Resolution 组合
```

## 38.4 Registry

```text
同 ID/Version 重复
时间范围重叠
精确版本解析
按交易日解析
Fingerprint 冲突
```

## 38.5 Multi-market Kernel

```text
Generic Cash:
    NOTIONAL RATE

Generic Futures:
    CONTRACTS PER_UNIT

Generic Crypto:
    Maker/Taker
    Charge/Rebate
```

## 38.6 Estimate

```text
Split-insensitive Rate
Order-cumulative Minimum
Fill Fixed Fee
maximum_fill_count
缺少 maximum_fill_count
Reservation 不使用 Rebate
```

## 38.7 Accrual

```text
FILL 每次增加
ORDER_CUMULATIVE 首次补足
目标不变时增量为零
目标上升时只补差额
目标下降 Fail Closed
Order-fixed Policy 变化 Fail Closed
```

## 38.8 Local Durable Parity

```text
Fee Ledger
Account
Strategy Ledger
Settlement
Committed Fact
Result
```

完全一致。

## 38.9 External Evidence

```text
TRADE
ORDER
STATEMENT

COMMISSION_ONLY
DETAILED
ALL_IN
ORDER_CUMULATIVE
DEFERRED_STATEMENT
```

## 38.10 Reconciliation

```text
Local == Reported
Local < Reported
Local > Reported

Duplicate Evidence
Evidence Conflict
Revised Report
Previous Adjustment Exists
Unknown Material Difference
Statement Unallocated Adjustment
```

## 38.11 Recovery

对每个 Projection 注入故障。

验证不重复：

```text
收费
返佣
补扣
退款
Evidence
Decision
Trading Block
```

## 38.12 Determinism

相同输入运行至少 100 次：

```text
Assessment bytes
Application bytes
Evidence identity
Reconciliation decision
Transaction payload
Artifact fingerprint
```

必须完全一致。

---

# 三十九、架构门禁

禁止生产代码出现：

```text
OnlyFeeRateRule
OnlyFeeCalculationRequest
OnlyFeeInstruction
OnlyFeeReconciliationService

reported_fee
reported_breakdown
broker_fee_reporting_mode

default_commission
fixed_commission
fee_per_fill_minimum

recalculate_fee_in_account
recalculate_fee_in_ledger
recalculate_fee_in_settlement

legacy_fee
compat_fee
```

验证依赖边界：

```text
Fee Engine 不导入 Runtime Manager
Fee Engine 不导入 Broker Plugin
Account 不导入 Fee Schedule
Strategy Ledger 不导入 Fee Schedule
Settlement 不导入 Fee Engine
Broker Plugin 不导入 Account Manager
Broker Plugin 不导入 Strategy Ledger Manager
Generic Fee Core 不导入具体 Fee Pack
```

---

# 四十、质量门禁

执行：

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts
uv run mypy src/onlyalpha
```

插件静态检查：

```bash
uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-tushare/pyproject.toml \
  packages/provider/onlyalpha-plugin-tushare/src/onlyalpha_plugin_tushare

uv run mypy \
  --config-file packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml \
  packages/provider/onlyalpha-plugin-miniqmt/src/onlyalpha_plugin_miniqmt
```

测试：

```bash
uv run python scripts/test_suite.py fast
uv run python scripts/test_suite.py integration
uv run python scripts/test_suite.py full
uv run python scripts/test_suite.py recovery
uv run python scripts/test_suite.py ashare
uv run python scripts/test_suite.py release
uv build --all-packages
```

不得通过：

```text
skip
xfail
放宽断言
删除有效测试
增加 sleep
吞异常
```

掩盖失败。

未执行的命令必须标记：

```text
NOT EXECUTED
```

不能伪造 PASS。

---

# 四十一、完成标准

只有全部满足才算完成：

```text
[ ] Fee Core 不包含具体市场逻辑
[ ] Formula 不再由 Optional 字段组合表达
[ ] Basis、Scope、Resolution、Direction 显式
[ ] Rounding 和 Pipeline 进入 Fingerprint

[ ] Order Estimate 与 Trade Assessment 完全分离
[ ] External Evidence 与 Fee Engine 完全分离
[ ] Broker Report 不再直接成为 Fee Breakdown

[ ] Runtime 显式安装 Fee Pack
[ ] Core 不自动安装默认费用
[ ] Generic Cash/Futures/Crypto 证明多市场能力

[ ] Order Snapshot 包含 Fee Policy Binding
[ ] Order Funding Plan 是唯一 Reservation 费用来源
[ ] Account 与 Strategy 使用相同 Funding Plan

[ ] Fee Assessment 只表示 Target
[ ] Fee Application 只表示本次增量
[ ] FILL 增量正确
[ ] ORDER_CUMULATIVE 增量正确
[ ] Policy 变化 Fail Closed

[ ] Fee Ledger、Account、Ledger、Settlement、Fact 完全一致
[ ] Charge 与 Rebate 方向明确
[ ] 历史 Fee Application 不可覆盖

[ ] External Fee Evidence 是不可变事实
[ ] FEE_RECONCILIATION 是正式 Durable Operation
[ ] MATCHED 也形成 Durable 事实
[ ] Supplemental Charge 正确
[ ] Refund 正确
[ ] ORDER_CUMULATIVE Evidence 不重复收费
[ ] 修订报告只产生新差额
[ ] Statement 无法归属时不猜测 Cluster
[ ] 未知重大差异进入 Trading Block

[ ] Checkpoint/Restart 不重复收费、退款或调整
[ ] A→B→C 与连续运行一致
[ ] 旧接口、旧 Schema、旧测试和兼容路径已删除
[ ] 全部质量门禁通过
```

---

# 四十二、明确不允许的结果

以下任一情况出现，PR4.1 视为失败：

```text
Fee Engine 中存在 market_profile_id if/elif
A 股费率被写入通用 Core
Broker Report 继续作为 Fee Calculation Request 字段
Account Manager 可以直接调整费用
历史 Fee Record 被覆盖
最低佣金按每个 Fill 重复计算
跨日订单静默切换 Order-fixed Broker Policy
Statement Adjustment 被猜测分摊到某个 Cluster
重大未知差异被写入 OTHER Fee 强制平账
重启后重复补扣或退款
旧接口通过 Alias 保留
旧 Schema 被隐式兼容
```

---

# 四十三、最终交付报告

完成后必须输出：

## 1. 修改前审计

说明：

```text
原费用计算入口
原 Request 混合问题
原累计费用权威
原外部报告路径
原对账非 Durable 问题
```

## 2. 第一性原则决策

说明：

```text
Fee Policy 负责什么
Fee Engine 负责什么
Order Binding 负责什么
Accrual Authority 负责什么
Application 负责什么
External Evidence 负责什么
Reconciliation 负责什么
Adjustment 负责什么
```

## 3. 删除内容

列出所有删除的：

```text
类
方法
别名
旧 Schema
旧测试
旧 Fixture
旧示例
```

## 4. 修改文件

逐文件说明职责和关键变化。

## 5. 完整数据流

```text
Order Accepted
→ Binding
→ Estimate
→ Funding Plan
→ Fill
→ Assessment
→ Accrual
→ Application
→ TRADE_FILL Transaction
→ External Evidence
→ FEE_RECONCILIATION
→ Match / Adjustment / Trading Block
```

## 6. 测试结果

表格列出：

```text
Static
Fast
Integration
Full
Recovery
A-share
Multi-market Conformance
Determinism
Build
Release
```

## 7. 未完成范围

明确列出：

```text
正式 CN_A_SHARE_CASH Fee Pack
真实 Broker Adapter
真实 Statement 下载
正式期货和数字货币 Fee Pack
多币种转换
账户周期费用
```

---

# 四十四、最终原则

本任务不追求：

```text
最少代码修改
旧测试原样通过
旧接口继续存在
旧 Checkpoint 继续恢复
用一个佣金常量快速实现
```

本任务追求：

```text
一个市场中立本地费用权威
一个订单累计费用权威
一个不可变费用应用账本
一个外部券商证据权威
一个 Durable 对账入口
一条完整经济数据流
所有历史事实不可覆盖
任意故障后结果完全一致
```

当历史兼容和正确架构冲突时：

```text
选择正确架构。
```
