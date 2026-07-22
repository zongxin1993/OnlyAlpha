# OnlyAlpha 统一 Fee 权威来源、实盘费用确认与对账闭环

你正在修改 OnlyAlpha 工程。请从第一性原则出发，完整解决当前费用来源不统一、Broker Fee 与 Market Fee 可能重复计算、账户扣费与结果事实可能不一致，以及实盘实际费用与本地模型费用发生偏差后无法可靠调账的问题。

本任务不是只增加几个枚举或数据类，也不是只修改 Virtual Broker 的固定佣金模型。必须完成正式的费用领域模型、费用计算链、Runtime 应用链、实盘确认链、对账链、调账链、结果事实、配置、场景、测试和文档，并迁移现有调用方。

必须以当前仓库实际代码为准。先阅读代码和测试，不得依赖过时设计文档猜测实现。

---

# 一、第一性原则

## 1. 费用的经济来源与记账权威不是同一个概念

费用可以来自多个来源：

1. 市场、交易所、监管、清算机构；
2. 券商、平台、账户合同；
3. 借券、融资、Funding、换汇等其他正式来源；
4. 券商后续结算、退费、补扣和调整。

这些来源可以分别定义规则，但不能分别修改 Runtime Account。

系统必须形成：

```text
多个 Fee Source
    ↓
唯一 Fee Resolution
    ↓
唯一 Fee Instruction
    ↓
ExecutionProcessor 一次性应用
    ↓
Account + StrategyLedger + Result Fact
```

禁止 MarketRuleEngine、Broker、AccountManager、StrategyLedgerManager、Collector 各自重新计算或各自扣费。

## 2. Backtest/Paper 与 Live 的权威来源不同

### Backtest/Paper

没有真实券商最终结算数据，因此：

```text
Market Fee Schedule
+
Broker Fee Schedule
→ OnlyFeeEngine 计算结果
→ 最终费用事实
```

在 Backtest/Paper 中，模型计算结果是最终权威费用。

### Live

本地模型不可能保证永远等于券商最终收费，因此：

```text
本地模型
    负责事前估算、风险预留和暂记

Broker 回报、账户快照、结算单
    负责外部确认

Reconciliation
    负责比较、解释和调账
```

Live 中不能把本地模型永久当成最终真相。

## 3. 历史事实不可变

已经产生的成交、暂记费用、确认费用不能被静默覆盖。

费用差异必须通过新的 Adjustment Fact 追加：

```text
原暂记费用：10.00
Broker 确认费用：12.00
Fee Adjustment：+2.00
最终费用：12.00
```

禁止：

```python
trade.fee = reported_fee
```

禁止直接修改历史 Fee Fact。

## 4. “费率为零”和“忽略费用”不是同一个状态

必须区分：

```text
NONE
    明确不建模该类费用

MODEL
    使用指定模型，模型费率可以合法为 0

DEFAULT
    使用 Market Profile 或 Broker Plugin 默认方案

REPORTED
    以 Broker 外部回报为最终来源
```

配置遗漏不能自动等价为零费率。

## 5. 所有金额必须可解释、可审计、可重放

每一笔最终费用都必须能够回答：

* 来自市场还是券商；
* 属于哪种费用；
* 使用哪个 Schedule 和版本；
* 是估算、暂记还是确认；
* 对应哪笔成交、订单、账户或交易日；
* 是否发生过调账；
* Broker 原始回报是什么；
* 最终 Account、Ledger 和 Result 为什么得到当前金额。

---

# 二、任务目标

完成统一费用体系，使以下不变量始终成立：

```text
Account 累计费用
=
StrategyLedger 累计费用之和或明确的归因关系
=
已应用 Fee Instruction 的净额
=
Fee Facts 与 Fee Adjustment Facts 的净额
=
Execution Result 中最终确认的费用
```

对于 Backtest/Paper：

```text
模型费用总额
=
账户实际扣费
=
Ledger 实际扣费
=
结果费用事实
```

对于 Live：

```text
本地暂记费用
+
后续调整
=
Broker 最终确认费用
```

任何不一致都必须产生正式 Reconciliation Result，不能静默修正。

---

# 三、阶段 0：全面审计当前实现

先全局阅读并建立审计报告，至少检查：

```text
src/onlyalpha/market/
src/onlyalpha/fee/
src/onlyalpha/broker/
src/onlyalpha/execution/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/order/
src/onlyalpha/risk/
src/onlyalpha/result/
src/onlyalpha/scenario/
src/onlyalpha/conformance/
src/onlyalpha/runtime/
packages/
examples/
tests/
```

搜索所有：

```text
fee
fees
commission
commission_model
fixed_commission
stamp_duty
transfer_fee
exchange_fee
trade.fee
reported_fee
apply_fee
fee_instruction
fee_manager
```

必须识别并记录：

1. 当前 Virtual Broker 如何计算 Commission；
2. Broker Fill/Trade 中 Fee 字段如何产生；
3. ExecutionProcessor 如何使用 Fee；
4. Account 和 StrategyLedger 实际扣的是哪个 Fee；
5. MarketRuleEngine 和 FeeManager 计算了什么；
6. Collector 输出的 Fee Fact 来自哪里；
7. 是否存在同一笔成交重复扣费；
8. 是否存在 Fee Fact 与账户费用不一致；
9. 当前配置如何表达零费率；
10. MiniQMT 或其他真实 Broker 是否返回 Fee；
11. 当前 Account Reconciliation 是否比较费用；
12. 当前结果指纹是否包括 Fee 和 Adjustment；
13. 当前 Scenario/Conformance 对 Fee 验证到什么程度。

生成：

```text
docs/reports/unified_fee_authority_audit.md
```

报告必须包含：

* 当前调用链；
* 当前权威来源；
* 重复计算点；
* 状态修改点；
* 数据模型冲突；
* 需要删除或迁移的旧接口；
* 实施计划；
* 风险和兼容性影响。

不得在未完成审计前直接堆叠新实现。

---

# 四、正式费用领域模型

根据当前项目命名规范实现或整理以下正式模型。名称可根据现有代码适配，但语义不得缺失。

## 1. 费用来源

```python
class OnlyFeeAuthority(Enum):
    MARKET = ...
    VENUE = ...
    REGULATOR = ...
    CLEARING = ...
    BROKER = ...
    PLATFORM = ...
    FINANCING = ...
    BORROW = ...
    FUNDING = ...
    OTHER = ...
```

## 2. 费用类型

至少支持：

```python
class OnlyFeeType(Enum):
    STAMP_DUTY = ...
    TRANSFER_FEE = ...
    EXCHANGE_FEE = ...
    CLEARING_FEE = ...
    REGULATORY_FEE = ...
    BROKER_COMMISSION = ...
    PLATFORM_FEE = ...
    CONTRACT_FEE = ...
    OPEN_FEE = ...
    CLOSE_FEE = ...
    CLOSE_TODAY_FEE = ...
    MAKER_FEE = ...
    TAKER_FEE = ...
    BORROW_FEE = ...
    FINANCING_FEE = ...
    FUNDING = ...
    FX_CONVERSION_FEE = ...
    OTHER = ...
```

## 3. 费用状态

```python
class OnlyFeeStatus(Enum):
    ESTIMATED = ...
    PROVISIONAL = ...
    CONFIRMED = ...
    ADJUSTED = ...
    REVERSED = ...
```

## 4. 配置模式

```python
class OnlyFeeConfigurationMode(Enum):
    NONE = ...
    MODEL = ...
    DEFAULT = ...
    REPORTED = ...
```

## 5. Broker 回报能力

```python
class OnlyBrokerFeeReportingMode(Enum):
    NONE = ...
    COMMISSION_ONLY = ...
    DETAILED = ...
    ALL_IN = ...
    DEFERRED_STATEMENT = ...
```

语义必须明确：

* `COMMISSION_ONLY`：Broker 只回报券商佣金，市场费用仍由 Market Schedule 计算；
* `DETAILED`：Broker 回报拆分费用；
* `ALL_IN`：Broker 回报已包含全部费用，不得再重复叠加 Market Fee；
* `DEFERRED_STATEMENT`：成交时无最终费用，等待结算单；
* `NONE`：Broker 不回报费用。

## 6. Fee Component

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeComponent:
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    amount: OnlyMoney
    status: OnlyFeeStatus
    source_id: str
    schedule_id: str | None
    schedule_version: str | None
    effective_date: date | None
    metadata: Mapping[str, object]
```

必须使用不可变、Decimal 基础的金额类型。

## 7. Fee Breakdown

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeBreakdown:
    currency: OnlyCurrency
    components: tuple[OnlyFeeComponent, ...]
    total: OnlyMoney
    status: OnlyFeeStatus
```

构造时必须验证：

```text
total == sum(components.amount)
所有 Component 币种一致
金额精度合法
不允许重复的唯一费用 Component
```

## 8. Fee Calculation Request

至少包含：

```text
runtime_id
cluster_id
account_id
order_id
trade_id
instrument
market/profile identity
trading day
side
offset
liquidity role
price
quantity
notional
contract multiplier
currency
broker identity
broker fee reporting mode
broker reported fee
```

Fee Engine 不能通过读取 Runtime Manager 私有状态拼装隐式输入。

## 9. Fee Instruction

实现正式不可变指令：

```python
OnlyFeeInstruction
```

必须包含：

```text
instruction_id
runtime_id
cluster_id
account_id
order_id
trade_id
fee_breakdown
calculation_source
created_at
idempotency_key
```

只有该指令可以驱动 Account 和 Ledger 的费用修改。

## 10. Fee Adjustment

实现：

```python
OnlyFeeAdjustmentInstruction
```

至少包含：

```text
adjustment_id
related_trade_id 或 settlement scope
account_id
cluster_id 可选
currency
previous_amount
reported_amount
adjustment_amount
reason
external_reference
created_at
idempotency_key
```

Adjustment 可以是正数、负数或反向冲销，但必须使用明确语义，不能依赖符号猜测原因。

---

# 五、Market Fee Schedule

市场、交易所、监管、清算费用必须放入版本化的 Market Fee Schedule。

实现或整理：

```text
OnlyMarketFeeSchedule
OnlyMarketFeeScheduleId
OnlyMarketFeeScheduleVersion
OnlyMarketFeeScheduleRegistry
OnlyMarketFeeScheduleResolver
```

Schedule 必须支持：

```text
market
venue
instrument class
effective_from
effective_to
buy/sell
open/close/close_today
maker/taker
percentage fee
per-unit fee
minimum fee
maximum fee
rounding mode
currency
source
version
fingerprint
```

Market Profile 不应把所有费率散落在 Profile 顶层，而应引用 Schedule Identity。

例如：

```text
CN_A_SHARE_CASH
    → CN_A_SHARE_STANDARD_FEES@版本
```

需要提供基础内建模板，但不能把模板写死为不可替换常量。

用户应能够：

1. 使用内建默认 Schedule；
2. 通过 Registry 注册自定义 Schedule；
3. 在配置中指定 Schedule ID；
4. 按交易日解析有效版本；
5. 在 Artifact 中记录实际使用版本和 Fingerprint。

禁止用户为了更改费率直接修改 Core 源码。

---

# 六、Broker Fee Schedule

券商合同收费必须与 Market Fee Schedule 分开。

实现或整理：

```text
OnlyBrokerFeeSchedule
OnlyBrokerFeeScheduleId
OnlyBrokerFeeScheduleVersion
OnlyBrokerFeeScheduleRegistry
OnlyBrokerFeeScheduleResolver
```

至少支持：

```text
broker/provider identity
account scope
effective_from/effective_to
commission rate
minimum commission
per-share/per-contract fee
platform fee
rounding mode
currency
source
version
fingerprint
```

Broker 插件可以：

* 提供默认 Schedule；
* 声明 `DEFAULT`；
* 接收用户指定 Schedule；
* 声明 `REPORTED`；
* 声明 Broker Fee Reporting Mode。

不能让 Broker Plugin 直接修改 Runtime Account。

---

# 七、OnlyFeeEngine：唯一费用解析器

实现正式：

```python
class OnlyFeeEngine:
    def estimate(...) -> OnlyFeeBreakdown: ...
    def resolve_trade_fee(...) -> OnlyFeeBreakdown: ...
    def reconcile_reported_fee(...) -> OnlyFeeReconciliationResult: ...
```

## 估算阶段

下单前调用：

```text
Market Fee Schedule
+
Broker Fee Schedule
+
保守 Reservation Policy
→ ESTIMATED Fee Breakdown
```

用于 Risk 和资金预留。

必须支持：

```text
expected_fee
maximum_fee
reservation_fee
```

预留费用不得简单等于最可能费用。需要考虑：

* 最低佣金；
* 四舍五入；
* 安全缓冲；
* 部分成交；
* 多次成交导致的最低佣金语义；
* Broker 无法立即确认费用。

## 成交阶段

### Backtest/Paper

Fee Engine 计算：

```text
Market Components
+
Broker Components
→ CONFIRMED Fee Breakdown
```

### Live 且 Broker 不立即返回完整费用

生成：

```text
PROVISIONAL Fee Breakdown
```

### Live 且 Broker 回报详细费用

根据 Reporting Mode 解析：

* `COMMISSION_ONLY`：Broker Commission + 本地 Market Fee；
* `DETAILED`：使用 Broker 明细并进行合理校验；
* `ALL_IN`：使用 Broker All-in，总费用不得再次叠加；
* `DEFERRED_STATEMENT`：暂记本地模型；
* `NONE`：暂记本地模型。

Fee Engine 必须防止重复计费。

---

# 八、ExecutionProcessor 成为唯一应用入口

重构正式交易链：

```text
Broker Trade Update
    ↓
ExecutionProcessor
    ↓
MarketRule / Trade Instruction
    ↓
OnlyFeeEngine
    ↓
OnlyFeeInstruction
    ↓
AccountManager
StrategyLedgerManager
FeeManager / Fee Ledger
Collector
```

只有 ExecutionProcessor 或其受控事务服务可以协调应用 Fee Instruction。

必须保证：

1. Account 费用更新一次；
2. StrategyLedger 费用更新一次；
3. Fee Fact 记录一次；
4. 相同 idempotency key 重放不重复扣费；
5. 中途失败时整体回滚或进入明确 reconciliation 状态；
6. Collector 不重新计算；
7. AccountManager 不读取 Market Profile；
8. StrategyLedgerManager 不读取 Broker Config；
9. Broker 不直接调用 AccountManager；
10. MarketRuleEngine 不直接扣款。

---

# 九、迁移 Broker Trade Fee

检查当前 `trade.fee`、Broker Fill Fee 和所有 Commission Model。

目标语义：

```text
Broker Trade Update 中的 fee
    = Broker 原始回报
    ≠ 自动等于 Runtime 最终费用
```

建议迁移为明确字段：

```text
reported_fee
reported_fee_breakdown
fee_reporting_mode
fee_external_reference
```

如果为兼容必须暂时保留 `fee`，也必须降级为 Broker 原始字段，并在文档中声明弃用，随后迁移全部调用方并删除旧接口。

不要保留两套长期接口。

---

# 十、Virtual Broker 迁移

当前 Virtual Broker 内部的固定佣金模型不能继续独立决定 Runtime Account 的最终费用。

重构后：

1. Virtual Broker 继续负责撮合、订单、成交和 Broker 侧模拟；
2. Virtual Broker 可以模拟 Broker Fee Schedule 或 Broker Reported Fee；
3. Virtual Broker 生成标准 Broker Fee Report；
4. Runtime Fee Engine 决定最终 Fee Instruction；
5. Runtime Account 只由 ExecutionProcessor 更新。

必须支持配置：

```yaml
broker:
  plugin: virtual.broker
  fees:
    mode: DEFAULT
```

```yaml
broker:
  plugin: virtual.broker
  fees:
    mode: NONE
```

```yaml
broker:
  plugin: virtual.broker
  fees:
    mode: MODEL
    schedule: custom-broker-fees
```

`NONE` 表示明确不建模 Broker Fee，不等于遗漏配置。

---

# 十一、Live Fee Reconciliation

实现：

```text
OnlyFeeReconciliationService
OnlyFeeReconciliationResult
OnlyFeeReconciliationStatus
OnlyFeeDifferenceReason
```

状态至少包括：

```text
MATCHED
ADJUSTMENT_REQUIRED
RECONCILED_WITH_ADJUSTMENT
INCOMPLETE_EXTERNAL_DATA
DUPLICATE_REPORT
UNEXPLAINED_DIFFERENCE
TRADING_BLOCKED
```

差异原因至少包括：

```text
MINIMUM_COMMISSION
ROUNDING
BROKER_RATE_MISMATCH
MARKET_SCHEDULE_OUTDATED
ALL_IN_REPORT
DEFERRED_FEE
REFUND
SUPPLEMENTAL_CHARGE
UNKNOWN
```

正式流程：

```text
Broker Fee Report / Settlement Statement
    ↓
归一化
    ↓
按 trade/account/trading_day 匹配
    ↓
与本地 Fee Ledger 比较
    ↓
生成 Reconciliation Result
    ↓
需要时生成 Fee Adjustment Instruction
    ↓
ExecutionProcessor 应用
```

## 处理策略

### 微小且可解释

自动 Adjustment，记录审计，继续交易。

### 明显但来源明确

自动 Adjustment，产生 Warning，并标记 Fee Model 可能过期。

### 重大且无法解释

不能使用 `OTHER` Fee 静默抹平。

必须：

```text
阻止新增风险订单
允许查询和撤单
按风险策略决定是否允许降风险平仓
拉取全量 Account/Position/Order/Trade/Fee Snapshot
进入 RECONCILIATION_REQUIRED
产生高等级诊断
```

---

# 十二、Account Reconciliation

Fee Reconciliation 必须接入 Account Reconciliation。

比较：

```text
cash
available cash
frozen cash
unsettled cash
equity
margin
position
cumulative fees
daily fees
```

如果 Account 差异可由 Fee Adjustment 精确解释：

```text
生成 Fee Adjustment
→ Account 差异归零
```

如果不能解释：

```text
不得直接覆盖本地 Account
不得制造虚假 Fee
进入 Account Reconciliation Required
```

Broker Account 是 Live 外部权威事实，本地 Account 是低延迟运行镜像；两者必须可以对账，但不能无审计地互相覆盖。

---

# 十三、费用版本化和指纹

每一笔 Fee Component、Fee Instruction 和 Adjustment 必须记录：

```text
market_fee_schedule_id
market_fee_schedule_version
market_fee_schedule_fingerprint
broker_fee_schedule_id
broker_fee_schedule_version
broker_fee_schedule_fingerprint
profile_id
profile_version
effective_date
calculation_timestamp
source
```

旧 Schedule 不得原地修改。

费率变化必须新建版本，并保留旧成交对旧版本的绑定。

Result Fingerprint 和 Artifact 必须包含：

* 使用的 Fee Schedule；
* Fee Facts；
* Fee Adjustments；
* Reconciliation Results；
* Broker Fee Reporting Mode。

---

# 十四、Result、Collector 和 Artifact

Collector 只能收集正式事实，不得自行推导费率。

新增或完善：

```text
Fee Component Fact
Fee Breakdown Fact
Fee Instruction Fact
Fee Adjustment Fact
Fee Reconciliation Fact
Fee Schedule Timeline Fact
```

Artifact 至少输出：

```text
fees
fee_adjustments
fee_reconciliations
fee_schedule_timeline
```

结果汇总必须区分：

```text
market fees
broker fees
other fees
provisional fees
confirmed fees
adjustments
net total fees
```

Backtest 最终结果不允许存在未确认 Provisional Fee。

Live 结果可以存在 Provisional Fee，但必须显式显示。

---

# 十五、配置设计

配置必须能表达：

```yaml
market:
  profile: CN_A_SHARE_CASH
  fees:
    mode: DEFAULT
```

```yaml
market:
  profile: CN_A_SHARE_CASH
  fees:
    mode: MODEL
    schedule: custom-cn-fees
```

```yaml
market:
  profile: CN_A_SHARE_CASH
  fees:
    mode: NONE
```

```yaml
broker:
  plugin: miniqmt.broker
  fees:
    mode: REPORTED
    reporting_mode: COMMISSION_ONLY
```

```yaml
broker:
  plugin: virtual.broker
  fees:
    mode: MODEL
    schedule: virtual-standard
    reservation_policy: CONSERVATIVE
```

缺少配置时必须：

* 使用明确的 DEFAULT；
* 或配置校验失败。

不得无声退化为零费率。

完全忽略费用时产生诊断：

```text
MARKET_FEES_DISABLED
BROKER_FEES_DISABLED
```

---

# 十六、必须删除或迁移的旧设计

完成后全局检查并清除：

1. Broker Fill Fee 直接作为 Account 最终扣费；
2. Virtual Broker 直接修改 Runtime Account；
3. Market Fee 只写 Result、不影响 Account；
4. Collector 重新计算费用；
5. AccountManager 重新解释费率；
6. StrategyLedgerManager 独立计算佣金；
7. 多个组件各自持有不同 Fee Total；
8. 使用 `0` 同时表示零费率和未配置；
9. 修改历史 Trade Fee；
10. 不带版本的全局固定费率；
11. `OnlyFixedCommissionModel` 作为 Runtime 最终费用权威；
12. 同一概念的新旧接口长期并存。

如果旧类型已无必要，迁移调用方后删除，不要保留双路径。

---

# 十七、测试要求

## 1. 单元测试

覆盖：

* Market Fee Schedule；
* Broker Fee Schedule；
* 买卖方向；
* OPEN/CLOSE/CLOSE_TODAY；
* 百分比费率；
* 每股/每合约费用；
* 最低费用；
* 最高费用；
* 四舍五入；
* 零费率；
* NONE/MODEL/DEFAULT/REPORTED；
* Fee Breakdown 合计；
* Schedule 版本解析；
* Broker Reporting Mode；
* Fee Adjustment 正负方向；
* idempotency。

## 2. Backtest 场景

至少新增：

### A 股

* 买入：无印花税，有 Broker Commission；
* 卖出：印花税 + Broker Commission；
* 最低佣金；
* 自定义 Market Schedule；
* Broker Fee 为 NONE；
* 所有 Fee 为 NONE。

验证：

```text
Account fees
=
Ledger fees
=
Fee Facts
```

### 期货

* OPEN；
* CLOSE；
* CLOSE_TODAY；
* 每合约费用；
* Broker Commission；
* Partial Fill；
* Cancel 后释放预留费用。

### Crypto

* Maker；
* Taker；
* 零 Broker Fee；
* 不得重复叠加 All-in Broker Fee。

## 3. Live/Paper 对账模拟

至少覆盖：

1. 模型费用等于 Broker 回报；
2. 最低佣金导致 Broker 更高；
3. Broker 回报更低；
4. Broker 退费；
5. Broker 补扣；
6. Broker Commission Only；
7. Broker Detailed；
8. Broker All-in；
9. Deferred Statement；
10. 重复 Fee Report；
11. 乱序 Fee Report；
12. 无法匹配 Trade；
13. 重大未知 Account 差异；
14. Adjustment 重放幂等；
15. Runtime 重启后继续对账。

## 4. 事务测试

模拟以下失败：

```text
Account 已更新、Ledger 更新失败
Ledger 已更新、Collector 失败
Adjustment 应用中断
重复 Broker 回报
```

系统必须保持一致或进入明确的 Reconciliation Required，不能部分静默成功。

## 5. 确定性测试

相同 Backtest 输入运行两次：

```text
Fee Components 相同
Fee Instructions 相同
Fee Facts 相同
Account/Ledger 相同
Result Fingerprint 相同
Artifact Fingerprint 相同
```

---

# 十八、正式不变量

实现自动检查：

```text
FEE_BREAKDOWN_TOTAL_MATCHES_COMPONENTS
ACCOUNT_FEES_MATCH_APPLIED_INSTRUCTIONS
LEDGER_FEES_MATCH_ATTRIBUTED_INSTRUCTIONS
RESULT_FEES_MATCH_FEE_FACTS
NO_DUPLICATE_FEE_APPLICATION
NO_DOUBLE_COUNTED_ALL_IN_FEE
NO_UNCONFIRMED_FEE_IN_FINAL_BACKTEST
NO_ACTIVE_FEE_RESERVATION_AFTER_RUNTIME_CLOSE
FEE_ADJUSTMENT_NET_MATCHES_REPORTED_TOTAL
```

多 Cluster 情况必须验证费用归因和 Shared Account 总额一致。

---

# 十九、架构边界测试

增加 Import/Dependency Gate，确保：

```text
Broker Plugin
    不依赖 AccountManager、StrategyLedgerManager、Collector

Market Profile
    不修改账户

AccountManager
    不依赖 Broker Plugin、Market Profile 具体实现

StrategyLedgerManager
    不重新计算 Fee

Collector
    不依赖 Fee Schedule Resolver

OnlyFeeEngine
    不依赖 Runtime 私有 Manager

Scenario
    不直接写 Fee、Account 或 Ledger 状态

CLI
    不直接操作 FeeManager 内部状态
```

---

# 二十、文档和 ADR

新增 ADR：

```text
docs/adr/xxxx-unified-fee-authority-and-reconciliation.md
```

内容必须包括：

* 为什么区分 Fee Source 与 Fee Authority；
* 为什么 Market Fee 和 Broker Fee 分开定义；
* 为什么只有 Fee Engine 统一解析；
* 为什么只有 ExecutionProcessor 应用；
* Backtest/Paper/Live 的权威差异；
* 为什么历史事实不可修改；
* 为什么使用 Adjustment；
* Broker Reporting Mode；
* Account Reconciliation；
* Schedule 版本化；
* 已拒绝的替代方案。

更新：

```text
README
HANDOFF
architecture
market profile 文档
broker plugin 文档
backtest 文档
live runtime 设计文档
scenario/conformance 文档
examples README
```

文档必须反映实际完成的代码，不得描述尚未实现的能力为已完成。

---

# 二十一、执行顺序

严格按以下顺序执行：

```text
1. 审计当前 Fee 全链
2. 明确现有重复真相和迁移清单
3. 建立统一领域模型
4. 建立 Market Fee Schedule
5. 建立 Broker Fee Schedule
6. 建立 OnlyFeeEngine
7. 接入下单前 Fee Reservation
8. 接入 ExecutionProcessor 唯一应用链
9. 迁移 Virtual Broker
10. 迁移 Account、Ledger、Collector
11. 实现 Fee Adjustment
12. 实现 Fee Reconciliation
13. 接入 Account Reconciliation
14. 完成 Result/Artifact
15. 完成 Scenario/Conformance
16. 删除旧接口
17. 全量测试和质量门禁
18. 更新文档和 HANDOFF
```

不得跳过旧代码迁移，也不得用兼容层长期保留两套费用链。

---

# 二十二、质量门禁

必须执行仓库实际支持的全部质量命令，并至少包括：

```text
pytest Core
pytest 所有 packages
ruff check .
ruff format --check .
mypy Core
mypy 所有插件
git diff --check
```

必须实际运行：

* A 股 Fee 场景；
* 期货 Fee 场景；
* Crypto Fee 场景；
* Fee Reconciliation 场景；
* 多 Cluster Fee 归因；
* 同输入两次确定性验证。

如果某个命令因环境限制无法运行，必须明确记录：

* 未运行的命令；
* 原因；
* 已采取的替代验证；
* 剩余风险。

不得虚构测试通过。

---

# 二十三、硬性完成标准

只有同时满足以下条件，任务才算完成：

1. Market Fee 与 Broker Fee 分别定义；
2. OnlyFeeEngine 是唯一合并解析器；
3. ExecutionProcessor 是唯一费用应用协调入口；
4. Account、Ledger、Fee Facts 金额完全一致；
5. Backtest/Paper 不再依赖 Broker Fill Fee 作为独立最终真相；
6. Live 支持 Estimated、Provisional、Confirmed、Adjusted；
7. Broker 实际费用差异可通过不可变 Adjustment 修正；
8. 未知重大差异可触发 Reconciliation Required 和交易阻断；
9. All-in Broker Fee 不会重复叠加 Market Fee；
10. Schedule 全部版本化并进入 Artifact；
11. `0` 与 `NONE` 语义分离；
12. 重复和乱序 Fee Report 幂等；
13. 旧费用链已删除；
14. 全部测试和质量门禁通过；
15. 文档与实际代码一致。

如果任一硬条件未满足，最终报告必须明确写：

```text
任务未完成
```

不能写“基本完成”“主体完成”或把剩余关键问题推迟为后续工作。

---

# 二十四、最终报告格式

完成后输出：

## 1. 审计结果

当前旧费用链、双重真相和删除项。

## 2. 第一性原则

最终 Fee Authority 和运行模式差异。

## 3. 新领域模型

新增类型、职责和不变量。

## 4. Market Fee

Schedule、版本、模板和自定义方式。

## 5. Broker Fee

Schedule、Reporting Mode 和插件接口。

## 6. Fee Engine

估算、解析、合并和防重复逻辑。

## 7. Runtime 交易链

ExecutionProcessor 如何统一应用。

## 8. Live 对账

Broker 确认、Adjustment、Account Reconciliation 和阻断策略。

## 9. 迁移和删除

删除的旧接口和所有调用方迁移情况。

## 10. 场景和 Conformance

实际运行的场景及结果。

## 11. 质量结果

逐条列出测试、ruff、mypy、format、diff-check 的真实结果。

## 12. 剩余限制

只能列非阻塞限制。任何硬性标准未完成都必须将任务标记为未完成。
