你现在负责 OnlyAlpha 的下一项核心架构收敛任务：

# OnlyAlpha Unified Fee Authority

中文名称：

# OnlyAlpha 统一费用权威来源

本任务必须从第一性原理出发，重新审计和收敛 OnlyAlpha 中所有与费用有关的配置、模型、计算、应用、累计、记录、对账和结果输出。

任务的最终目标不是让现有两个费用结果“暂时相等”，而是：

> 在 OnlyAlpha 中建立唯一、明确、可审计的费用权威链。每一笔成交的本地业务费用只能被计算一次、应用一次、累计一次，并以同一份标准 Fee Breakdown 驱动 Account、Strategy Ledger、Execution Result、Collector、Artifact 和 Performance。

同时必须保留外部 Broker 实际报告费用的能力，用于 Live/Paper/Reconciliation，但外部报告值与本地规则计算值必须属于不同的语义，不得继续混为同一个 `fee` 字段。

---

# 一、任务背景

当前工程中至少存在两条费用路径。

## 路径一：Broker 费用路径

```text
Virtual Broker Commission Model
→ Broker Fill / Broker Trade Fee
→ ExecutionProcessor
→ Account
→ Strategy Ledger
```

该路径实际影响账户和策略账本。

## 路径二：Market Profile 费用路径

```text
Market Profile Fee Model
→ Market Rule Engine
→ Fee Instruction
→ Fee Manager
→ Fee Facts
→ Collector / Artifact
```

该路径主要产生标准费用记录。

如果两条路径的模型、舍入、最低费用、费用类型或累计方式不同，会出现：

```text
Account fees
≠ Strategy Ledger fees
≠ Execution fee
≠ Fee Manager records
≠ Artifact fee facts
```

这不是普通计算错误，而是领域权威不明确。

本任务必须彻底解决。

---

# 二、第一性原理

开始设计前，必须接受以下基本事实。

## 2.1 成交事实和费用事实不同

一笔成交事实至少描述：

```text
成交标的
成交方向
开平语义
成交价格
成交数量
成交时间
成交场所
流动性角色
Broker 身份
```

费用事实描述：

```text
因该成交产生了什么费用
费用由谁收取
费用属于什么类型
计算基础是什么
费率是多少
最低费用如何累计
最终应计和实收是多少
```

Broker Trade 不应该因为方便而成为所有费用语义的唯一容器。

---

## 2.2 市场制度费用与 Broker 报告费用不是同一个概念

必须区分：

### Market/Venue/Regulatory Fees

例如：

```text
交易佣金规则
最低佣金
印花税
过户费
交易所费
监管费
Maker/Taker Fee
期货开仓费
期货平仓费
平今费
Funding
Borrow Fee
```

这些由：

```text
Market Profile
Venue Rules
Instrument Reference
Account Fee Schedule
```

共同决定。

### Broker-Reported Fees

真实 Broker 回报的：

```text
reported commission
reported tax
reported exchange fee
reported total fee
```

这是外部事实。

它可能：

```text
与本地规则一致
晚于成交回报到达
只有总费用没有 Breakdown
包含 Broker 特殊优惠
包含本地规则未知的费用
需要后续冲正
```

因此不能强制把两者合并为同一字段。

---

## 2.3 权威来源随运行模式不同，但业务接口必须统一

Backtest：

```text
本地 Fee Rule
是最终记账权威
```

Paper：

```text
本地 Fee Rule
是最终记账权威
```

Live：

可以采用以下明确策略之一：

```text
LOCAL_ESTIMATE_THEN_RECONCILE
BROKER_REPORTED_AUTHORITY
LOCAL_RULE_AUTHORITY
```

但无论采用哪种策略，ExecutionProcessor、Account、Ledger、Collector 使用的接口和事实模型必须一致。

禁止出现：

```python
if backtest:
    use_fee_manager()
elif live:
    use_trade.fee
```

正确方向是：

```text
Fee Resolution Policy
→ Authoritative Fee Application
```

---

## 2.4 一笔费用只能被应用一次

无论费用来自本地计算还是 Broker 报告，最终记账必须满足：

```text
一个 Fee Application ID
→ 一次 Account Mutation
→ 一次 Ledger Mutation
→ 一组 Fee Facts
```

重复 Broker Update、重放、恢复和 reconciliation 不能导致重复扣费。

---

## 2.5 Fee Breakdown 必须是一等领域事实

不能继续只传递：

```python
fee: OnlyMoney
```

因为单个总额无法表达：

```text
Commission
Minimum Commission
Tax
Transfer Fee
Exchange Fee
Regulatory Fee
Maker/Taker
Open/Close/CloseToday Fee
Broker Adjustment
Fee Reversal
```

必须建立稳定、可版本化、可序列化的 Fee Breakdown。

---

# 三、开始前必须重新审计当前代码

不得直接编码。

首先重新阅读当前主分支所有费用相关实现。

至少审计：

```text
src/onlyalpha/market/
src/onlyalpha/broker/
src/onlyalpha/execution/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/order/
src/onlyalpha/result/
src/onlyalpha/artifact/
src/onlyalpha/runtime/
src/onlyalpha/config/
src/onlyalpha/scenario/
src/onlyalpha/application/

packages/**/broker/
packages/**/data_source/
tests/
examples/
```

重点搜索：

```text
fee
fees
commission
commission_model
fixed_commission
tax
stamp_duty
transfer_fee
exchange_fee
maker
taker
close_today
trade.fee
fill.fee
account.fees
ledger.fees
FeeInstruction
FeeManager
FeeRecord
FeeFact
```

必须输出：

```text
docs/reports/unified_fee_authority_audit.md
```

审计报告必须列出：

1. 每个费用相关类型；
2. 每个费用计算入口；
3. 每个费用应用入口；
4. 每个费用累计入口；
5. 每个费用结果输出入口；
6. 每个 Broker reported fee 入口；
7. 重复或冲突的费用模型；
8. 当前真正影响 Account 的路径；
9. 当前真正影响 Strategy Ledger 的路径；
10. 当前 Artifact 使用的路径；
11. Backtest、Paper、Live、Shadow 各自预期的费用权威；
12. 应删除、保留、重命名和迁移的接口。

审计必须基于实际源码，不得只复制旧文档。

---

# 四、建立明确的费用领域语言

必须建立或完善以下概念。

具体名称服从当前工程命名风格，但不得省略语义。

## 4.1 OnlyFeeType

至少考虑：

```text
COMMISSION
MINIMUM_COMMISSION_ADJUSTMENT
STAMP_DUTY
TRANSFER_FEE
EXCHANGE_FEE
REGULATORY_FEE
BROKER_FEE
MAKER_FEE
TAKER_FEE
OPEN_FEE
CLOSE_FEE
CLOSE_TODAY_FEE
BORROW_FEE
FUNDING_FEE
OTHER
ADJUSTMENT
REVERSAL
```

未实现的能力可以暂时不启用，但模型必须避免股票佣金专用化。

---

## 4.2 OnlyFeeComponent

建议字段：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeComponent:
    fee_type: OnlyFeeType
    amount: OnlyMoney
    calculation_basis: OnlyFeeCalculationBasis
    rate: Decimal | None
    quantity: OnlyQuantity | None
    notional: OnlyMoney | None
    source: OnlyFeeSource
    recipient: str | None
    metadata: OnlyJsonMapping
```

要求：

```text
amount 不得为 float
币种必须显式
金额方向必须有统一约定
字段必须可序列化
```

建议费用金额使用非负值，应用方向由 `OnlyFeeApplication` 决定。

---

## 4.3 OnlyFeeBreakdown

建议字段：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeBreakdown:
    components: tuple[OnlyFeeComponent, ...]
    total: OnlyMoney
    calculation_currency: OnlyCurrency
    rule_identity: OnlyFeeRuleIdentity
    fingerprint: str
```

必须保证：

```text
sum(component.amount) == total
```

该约束应由构造函数或专门 Factory 强制执行。

---

## 4.4 OnlyFeeSource

必须区分：

```text
LOCAL_MARKET_RULE
LOCAL_ACCOUNT_SCHEDULE
BROKER_REPORTED
VENUE_REPORTED
RECONCILIATION_ADJUSTMENT
MANUAL_ADJUSTMENT
```

禁止用一个含义不明的 `fee` 字段同时表示本地估算和 Broker 实收。

---

## 4.5 OnlyFeeApplication

建议建立：

```python
@dataclass(frozen=True, slots=True)
class OnlyFeeApplication:
    application_id: OnlyFeeApplicationId
    account_id: OnlyAccountId
    cluster_id: OnlyClusterId | None
    order_id: OnlyOrderId
    trade_id: OnlyTradeId
    breakdown: OnlyFeeBreakdown
    authority: OnlyFeeAuthority
    operation: OnlyFeeApplicationOperation
    sequence: int
    ts_event: OnlyTimestamp
```

操作至少考虑：

```text
ACCRUE
CHARGE
ADJUST
REVERSE
```

首期可以只正式支持 `CHARGE`，但接口不得阻止后续冲正。

---

# 五、定义唯一权威链

任务完成后的正式路径必须为：

```text
Broker Trade Fact
+ Market / Venue / Instrument / Account Context
+ Fee Resolution Policy
        ↓
Authoritative OnlyFeeBreakdown
        ↓
OnlyFeeApplication
        ↓
ExecutionProcessor
        ├── Account Manager
        ├── Strategy Ledger Manager
        ├── Fee Manager
        ├── Execution Fact
        └── Audit/Event
        ↓
Collector
        ↓
Result / Artifact / Analytics
```

核心原则：

> Account、Strategy Ledger、Fee Manager、Execution Fact 和 Collector 必须消费同一个 `OnlyFeeApplication` 或同一份不可变 `OnlyFeeBreakdown`。

禁止各组件自行重新计算费用。

---

# 六、费用计算职责边界

## 6.1 Market Profile / Fee Rule

负责定义：

```text
适用费用类型
费率
最低费用规则
买卖方向差异
开平差异
Maker/Taker
场所和市场制度
有效日期和版本
```

不负责：

```text
修改账户
修改 Ledger
保存运行状态
处理重复 Broker Update
写 Artifact
```

---

## 6.2 Instrument Reference

负责提供：

```text
venue
asset class
currency
contract multiplier
board
fee category
instrument-specific fee metadata
```

不负责计算最终费用。

---

## 6.3 Account Fee Schedule

用于表达账户、券商或客户级差异：

```text
broker discount
commission tier
minimum commission
account-specific schedule
VIP rate
```

必须明确它与 Market Profile Fee Rule 的合并顺序。

推荐：

```text
Market/Venue mandatory fees
+
Account/Broker commercial schedule
=
Resolved Local Fee Rule
```

监管税费不能被普通 Broker discount 覆盖。

---

## 6.4 Broker Gateway

Broker 负责：

```text
报告 Broker 原始成交
报告 Broker 原始费用
报告费用调整或冲正
```

Broker 不负责：

```text
直接修改 Runtime Account
直接修改 Strategy Ledger
决定 Backtest 最终费用权威
生成本地 Market Fee Facts
```

Virtual Broker 可以模拟 Broker reported fee，但该费用必须明确标记：

```text
source = BROKER_REPORTED
```

不能再直接作为未区分来源的本地账户费用。

---

## 6.5 ExecutionProcessor

ExecutionProcessor 是费用应用的唯一正式入口。

职责：

```text
接收 Broker Trade Update
去重和排序
解析权威 Fee Breakdown
生成 Fee Application
一次性更新 Account
一次性更新 Strategy Ledger
一次性登记 Fee Manager
写入 Execution Audit
发布标准事件
```

不负责：

```text
硬编码 A 股费用
硬编码 Futures Fee
自行读取 Profile ID 分支
```

---

## 6.6 Fee Manager

Fee Manager 只维护：

```text
Fee Application
Fee Component
累计已计费用
累计已收费用
Adjustment
Reversal
查询和标准记录
```

Fee Manager 不应再次调用 Fee Rule 重新计算。

如果当前 `FeeManager` 同时计算和记录，必须拆分：

```text
Fee Resolver / Calculator
Fee Manager / Store
```

---

## 6.7 Account Manager

Account Manager 只应用：

```text
authoritative fee cash delta
```

不得根据 Trade 自行重新计算费用。

---

## 6.8 Strategy Ledger

Strategy Ledger 使用与 Account 相同的 Fee Application。

如果 Shared Account 中一个 Trade 属于某个 Cluster：

```text
Account 扣减完整权威费用
该 Cluster Ledger 扣减相同归属费用
```

如果未来一个 Trade 跨多个 Cluster 分配，应由 Allocation 层生成明确 Fee Allocation，不能简单平均。

---

## 6.9 Collector

Collector 只投影正式 Fee Application 和 Fee Records。

不得：

```text
根据成交额重新计算费率
把 Broker reported total 当作权威费用
从 Account fees 反推出 Fee Breakdown
```

---

# 七、运行模式费用策略

实现明确配置：

```text
OnlyFeeAuthorityPolicy
```

至少支持以下语义。

## 7.1 LOCAL_RULE_AUTHORITY

适用于：

```text
Backtest
Paper
```

流程：

```text
本地规则计算
→ 本地费用权威
→ Broker reported fee 仅作诊断
```

---

## 7.2 BROKER_REPORTED_AUTHORITY

适用于特定 Live Broker。

流程：

```text
Broker reported fee
→ 最终权威
```

如果 Broker 成交回报暂时没有费用：

```text
不得静默记为零
```

必须明确：

```text
PENDING_BROKER_FEE
```

或使用其他正式待结算状态。

---

## 7.3 LOCAL_ESTIMATE_THEN_RECONCILE

推荐用于大多数 Live 模式。

流程：

```text
成交到达
→ 本地 Fee Estimate
→ Account/Ledger 暂记

Broker Fee 到达
→ 比较实际与估算
→ 生成 Adjustment 或 Reversal
→ Account/Ledger/FeeManager 同步调整
```

必须防止：

```text
估算扣一次
Broker reported 再扣一次
```

差额应为：

```text
broker_reported_total - already_applied_authoritative_total
```

---

# 八、最低费用与多 Fill 累计

必须正式解决：

```text
一个订单多次成交
最低佣金不能每次 Fill 重复收取
```

建议使用 Order-level Fee Accumulator。

状态至少包含：

```text
order_id
fee_rule_identity
cumulative_notional
cumulative_quantity
cumulative_required_fee
cumulative_applied_fee
component-level cumulative totals
```

每次 Fill 的费用增量：

```text
current_fill_fee_delta
=
cumulative_required_fee_after_fill
-
cumulative_applied_fee_before_fill
```

必须覆盖：

```text
单 Fill
多 Fill
最后一笔触发最低费用
部分成交后撤单
订单跨多个 Bar 成交
重复 Trade Update
乱序 Trade Update
```

同一订单不同费用组件需要分别累计。

例如：

```text
Commission 有 minimum
Stamp Duty 无 minimum
Transfer Fee 按成交额
```

不能先把所有费用合并后再套最低费用。

---

# 九、舍入与精度规则

费用计算必须明确以下顺序：

```text
原始计算基础
→ 费率计算
→ 费用组件舍入
→ 最低费用调整
→ Breakdown 合计
→ Account Currency 应用
```

必须定义：

```text
每个组件舍入还是总额舍入
币种 precision
ROUND_HALF_UP / ROUND_HALF_EVEN 等模式
最小货币单位
负费用或返佣规则
```

不得依赖 Python 默认 Decimal Context。

不得使用 float。

费用舍入规则应进入：

```text
Fee Rule Identity
Fee Breakdown Fingerprint
Result Fingerprint
```

---

# 十、货币与多币种

当前即使主要使用单币种，也必须避免把费用系统锁死为单币种。

必须明确：

```text
trade currency
fee currency
account base currency
settlement currency
```

如果费用币种与账户币种不同：

```text
没有显式 FX Rate 时不得自动转换
```

首期可显式返回：

```text
FEE_CURRENCY_CONVERSION_REQUIRED
```

不得偷偷使用 1:1。

---

# 十一、Broker Reported Fee 模型

审计当前：

```text
OnlyBrokerTradeSnapshot
OnlyBrokerTradeUpdate
OnlyBrokerOrderSnapshot
MiniQMT Trade Callback
Virtual Broker Trade
```

如果已有：

```python
fee: OnlyMoney
```

必须决定：

### 推荐方案

重命名为：

```text
reported_fee_total
reported_fee_breakdown
```

并明确：

```text
该值是外部事实
不是 Runtime 权威应用结果
```

如果 Broker 不提供费用：

```text
None
```

比错误地填零更准确。

不要为了旧接口兼容保留两个含义相同的字段。

迁移全部插件和测试后删除旧字段。

---

# 十二、Execution Fact 与 Fee Fact

## 12.1 Execution Fact

Execution Fact 应保留：

```text
trade identity
price
quantity
notional
reported broker fee
authoritative applied fee
fee application id
fee authority
```

不要只有单一 `fee`。

---

## 12.2 Fee Fact

每个 Fee Fact 至少包含：

```text
fee_application_id
fee_component_id
account_id
cluster_id
order_id
trade_id
instrument_id
fee_type
source
authority
operation
amount
currency
rate
notional
quantity
rule_id
rule_version
sequence
ts_event
schema_version
```

必须能从 Fee Facts 精确重建：

```text
每笔成交总费用
每个订单累计费用
账户总费用
Cluster 总费用
每种费用类型总额
```

---

# 十三、必须成立的财务恒等式

完成后必须通过以下恒等式。

## 13.1 单笔成交

```text
authoritative_trade_fee
=
sum(authoritative_fee_components)
```

## 13.2 账户

```text
account_total_fees
=
sum(applied account fee applications)
```

## 13.3 Strategy Ledger

对于单 Cluster Trade：

```text
ledger_total_fees
=
sum(applied cluster fee applications)
```

## 13.4 Result

```text
result_fee_total
=
sum(fee facts)
=
account_total_fees
```

## 13.5 Execution

```text
sum(execution.authoritative_fee)
=
sum(fee facts linked to executions)
```

## 13.6 Reconciliation

Live 模式：

```text
local_estimate
+ reconciliation_adjustments
=
broker_reported_authoritative_total
```

所有恒等式必须使用 Decimal 和显式 Currency。

---

# 十四、修改范围

重点修改但不限于：

```text
src/onlyalpha/market/
src/onlyalpha/execution/
src/onlyalpha/broker/
src/onlyalpha/account/
src/onlyalpha/strategy_ledger/
src/onlyalpha/result/
src/onlyalpha/artifact/
src/onlyalpha/runtime/
src/onlyalpha/config/
src/onlyalpha/scenario/
src/onlyalpha/application/
packages/provider/onlyalpha-plugin-miniqmt/
packages/provider/onlyalpha-plugin-tushare/
tests/
examples/
```

Virtual Broker、MiniQMT Broker 以及未来 Broker Plugin 必须使用相同公共费用接口。

---

# 十五、应删除的设计

如果实际代码中存在以下设计，完成迁移后删除：

```text
Broker Commission Model 直接决定 Runtime Account fee
Trade.fee 同时表示 reported 和 authoritative fee
FeeManager 再次独立计算费用
Account 从 Trade 自行读取 fee 并扣款
Ledger 从 Trade 自行读取 fee 并扣款
Collector 从成交重新推导 Fee
Backtest 使用专用 fixed_commission 路径
按 Runtime Mode 写死费用逻辑
按 Profile ID 写死费用逻辑
兼容旧 fee 字段的双路径
```

不保留旧接口兼容。

---

# 十六、配置设计

费用配置应归属于明确层级。

建议：

```yaml
market:
  profile: CN_A_SHARE_CASH

account:
  fee_schedule:
    schedule_id: default-cn-equity
    overrides:
      commission_rate: "0.0003"
      minimum_commission: "5.00"

runtime:
  fee_authority:
    policy: LOCAL_RULE_AUTHORITY
```

约束：

```text
Market Profile
    定义市场和监管费用规则

Account Fee Schedule
    定义账户商业费率和优惠

Runtime Fee Authority Policy
    定义本地规则与 Broker 报告的权威关系
```

不要把全部费用字段重新塞回 Virtual Broker Config。

所有 Decimal 必须使用字符串。

---

# 十七、首批必须支持的市场费用

## 17.1 A 股

至少支持：

```text
Commission
Minimum Commission
Sell-side Stamp Duty
Transfer Fee
```

必须验证：

```text
BUY
SELL
单 Fill
多 Fill
部分成交
最低佣金
ST 与非 ST 不影响费用错误串联
```

---

## 17.2 Generic T0 Cash

至少支持：

```text
Commission
无最低费用或 Profile 定义的最低费用
```

用于证明 Core 不硬编码 A 股税费。

---

## 17.3 Generic Futures

至少支持：

```text
OPEN Fee
CLOSE Fee
CLOSE_TODAY Fee 扩展接口
Contract-based Fee
Notional-based Fee
```

如果 CLOSE_TODAY 尚未正式启用，必须保留模型和显式 Unsupported Capability，不得错误退化成 CLOSE。

---

## 17.4 Crypto Spot

至少支持：

```text
Maker Fee
Taker Fee
Fee Currency
Minimum Fee 扩展
```

如果当前 Bar Broker 不能区分 Maker/Taker，应使用明确的 Liquidity Role Policy，不得任意猜测。

---

# 十八、测试设计

必须新增完整测试矩阵。

## 18.1 Fee Rule Unit Tests

覆盖：

```text
单组件
多组件
最低费用
方向差异
Offset 差异
Maker/Taker
Contract Multiplier
舍入
不同币种
Fingerprint
```

---

## 18.2 Fee Accumulator Tests

覆盖：

```text
单 Fill
多 Fill
部分成交后撤单
重复 Fill
乱序 Fill
最低佣金增量
多个费用组件独立累计
```

---

## 18.3 Execution Integration Tests

验证同一 Fee Application 被：

```text
Account
Ledger
Fee Manager
Execution Fact
Collector
```

一致消费。

---

## 18.4 Broker Reported Fee Tests

覆盖：

```text
无 reported fee
reported fee 与 estimate 相同
reported fee 大于 estimate
reported fee 小于 estimate
reported fee 延迟到达
重复 reported fee
fee reversal
```

---

## 18.5 Scenario Tests

正式通过 OnlyEngine 增加：

```text
CN_A_SHARE_FEE_SINGLE_FILL
CN_A_SHARE_FEE_MULTI_FILL_MINIMUM
GENERIC_T0_FEE
GENERIC_FUTURES_OPEN_CLOSE_FEE
GENERIC_CRYPTO_MAKER_TAKER_FEE
BROKER_FEE_RECONCILIATION
```

Scenario 不得重新计算费用，只断言标准事实。

---

## 18.6 Invariant Tests

必须断言：

```text
Account fees == Fee Facts total
Ledger fees == allocated Fee Facts total
Execution fee == linked Fee Facts total
无重复 Fee Application
无 orphan Fee Application
无未知 Currency 自动换算
```

---

## 18.7 Determinism Tests

相同输入重复运行，以下必须一致：

```text
Fee Breakdown
Fee Application ID
Fee Facts
Account fees
Ledger fees
Result fingerprint
Artifact fingerprint
```

---

# 十九、跨模块依赖边界

增加架构门禁，保证：

```text
broker 不 import account manager
broker 不 import strategy ledger manager
account 不 import market fee calculator
ledger 不 import market fee calculator
collector 不 import fee rule
scenario assertion 不 import fee calculator
plugin 不 import execution concrete implementation
```

允许：

```text
ExecutionProcessor
→ Fee Resolution Port
→ Fee Application Port

Account / Ledger
→ Fee Application DTO

Collector
→ Fee Query View
```

---

# 二十、迁移策略

严格按以下阶段执行。

## Stage 1：费用全链审计

生成审计报告和当前数据流图。

## Stage 2：领域模型

建立：

```text
Fee Type
Fee Source
Fee Authority
Fee Component
Fee Breakdown
Fee Application
Fee Adjustment
```

## Stage 3：Fee Resolver

收敛 Market、Venue、Instrument、Account Schedule。

## Stage 4：ExecutionProcessor

建立唯一 Fee Application 流程。

## Stage 5：Account 和 Ledger

删除从 `trade.fee` 自行扣款的旧路径。

## Stage 6：Fee Manager

改为只记录和累计 Fee Application。

## Stage 7：Broker 模型

区分 Broker Reported Fee 与 Runtime Authoritative Fee。

## Stage 8：Virtual Broker

删除其对 Runtime 最终费用的权威职责。

## Stage 9：MiniQMT Broker

映射 reported fee；供应商未提供时必须为 None 或 Pending。

## Stage 10：Collector 和 Artifact

统一输出 Fee Application 和 Breakdown。

## Stage 11：Scenario 和 Conformance

建立跨市场费用证据。

## Stage 12：删除旧接口

删除旧 `trade.fee` 双义路径、旧 Commission 权威路径和兼容分支。

## Stage 13：文档和交接

更新所有正式说明。

---

# 二十一、文档要求

新增：

```text
docs/unified_fee_authority.md
docs/fee_domain_model.md
docs/fee_runtime_flow.md
docs/fee_reconciliation.md
docs/adr/xxxx-unified-fee-authority.md
docs/reports/unified_fee_authority_audit.md
```

更新：

```text
README.md
AGENTS.md
HANDOFF.md
docs/architecture.md
docs/runtime.md
docs/virtual_broker.md
docs/execution_processor.md
docs/account.md
docs/strategy_ledger.md
docs/results_framework.md
docs/market_profiles.md
docs/market_conformance_suite.md
```

文档必须明确：

```text
谁计算
谁决定权威
谁应用
谁记录
谁对账
谁只提供外部事实
```

---

# 二十二、质量门禁

必须真实执行：

```text
uv sync --all-groups --all-packages

uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
git diff --check
```

同时显式运行所有 Package 测试：

```text
Core tests
Virtual Broker tests
MiniQMT tests
Tushare tests
Scenario tests
Conformance tests
Examples tests
```

不得因为根 pytest 配置只包含 `tests/` 而漏掉 `packages/`。

如真实 MiniQMT 环境可用，执行其非破坏性集成测试。

不得虚构在线或实盘费用结果。

---

# 二十三、完成标准

只有以下全部满足才算完成：

```text
费用计算权威唯一
费用应用入口唯一
费用标准事实唯一

Market Profile Fee Rule 已进入正式链
Account Fee Schedule 已进入正式链
Fee Authority Policy 已实现

Broker reported fee 与 authoritative fee 已分离
Virtual Broker 不再决定 Runtime 最终费用
Account 不再从含义不明的 trade.fee 自行扣款
Ledger 不再从含义不明的 trade.fee 自行扣款
Fee Manager 不再独立重新计算费用

Fee Breakdown 是不可变一等事实
Fee Application 可幂等
最低费用多 Fill 累计正确
Adjustment / Reversal 模型存在
Live Reconciliation Policy 明确

Account fees
=
Ledger allocated fees
=
Execution authoritative fees
=
Fee Facts total

A 股费用场景通过
Generic T0 费用场景通过
Generic Futures 费用场景通过
Crypto Spot 费用场景通过
Broker reconciliation 场景通过

重复运行确定性通过
Artifact 一致
所有插件测试通过
所有架构门禁通过

旧费用双路径已删除
旧兼容接口已删除
文档已更新
HANDOFF 已更新
```

---

# 二十四、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

列出所有费用入口、应用入口和冲突路径。

## 2. 第一性原理决策

说明：

```text
费用是什么
权威是什么
Broker Reported 和 Runtime Applied 的区别
```

## 3. 删除内容

列出删除的：

```text
旧 Commission 权威路径
旧 trade.fee 双义字段
旧 Account/Ledger 扣费路径
旧兼容分支
```

## 4. 新费用链

展示：

```text
Trade
→ Fee Resolution
→ Fee Breakdown
→ Fee Application
→ Account/Ledger/FeeManager
→ Collector/Artifact
```

## 5. 模块边界

分别说明：

```text
Market Profile
Account Fee Schedule
Broker
ExecutionProcessor
Fee Resolver
Fee Manager
Account
Ledger
Collector
```

以及每个模块不负责什么。

## 6. 运行模式

说明：

```text
Backtest
Paper
Live
Shadow
```

各自使用的 Fee Authority Policy。

## 7. 多市场验证

报告：

```text
A 股
T0 Cash
Futures
Crypto Spot
```

## 8. 财务恒等式

列出每项恒等式的真实测试结果。

## 9. Broker Reconciliation

说明估算、实收、调整和冲正流程。

## 10. Artifact 和 Determinism

列出 Fee Schema、指纹和重复运行结果。

## 11. 质量门禁

列出实际执行命令、退出码和结果。

## 12. 明确未完成

不得把 Funding、Borrow、完整多币种 FX、完整期货交易所费率等未实现能力写成完成。

---

# 二十五、最终架构原则

最终实现必须满足：

> Broker 产生成交事实和 Broker 报告费用，不直接决定 Runtime 本地账本的最终费用。

> Market/Venue/Instrument/Account Fee Rules 产生本地费用计算结果。

> Fee Authority Policy 决定本地计算值和 Broker 报告值之间谁是当前权威。

> ExecutionProcessor 是 Fee Application 的唯一正式应用入口。

> Account、Strategy Ledger、Fee Manager、Execution Fact、Collector 和 Artifact 消费同一份 Fee Application。

> 任何费用调整必须通过明确的 Adjustment 或 Reversal，不允许直接覆盖历史记录。

> 多 Fill、重复回报、乱序回报和 Runtime 重放不能造成重复扣费。

> Backtest、Paper、Live、Shadow 共享同一费用领域模型和应用接口，只允许权威策略不同。

> 不为旧费用接口保留兼容路径；重复或双义模型必须删除。
