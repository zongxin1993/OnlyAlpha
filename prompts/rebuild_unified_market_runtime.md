你现在负责在 OnlyAlpha 核心仓中重新设计并实现任务 1：

# OnlyAlpha Unified Market Runtime Integration

中文名称：

# OnlyAlpha 统一市场规则运行时集成

本任务不是在当前设计上简单增加若干适配器，而是要纠正现有 Market Profile 接入方向，建立一套适用于：

```text
Backtest
Paper
Live
Shadow
```

的统一市场规则运行时架构。

最终目标是：

> 市场规则属于市场本身，而不是属于回测或仿真。所有 Runtime 模式使用同一套 Market 定义、规则解析、规则决策、结算、保证金、费用和持仓语义；不同 Runtime 模式之间只允许数据源、Broker Gateway、时间驱动方式和外部状态权威不同。

---

# 一、必须遵守的核心设计结论

本任务必须严格按照以下结论实施。

## 1. 删除 Simulation 概念

当前存在：

```python
OnlyMarketSimulationConfig
```

该命名和抽象需要删除。

原因：

```text
T+1
涨跌停
交易时段
整手
最小名义金额
做空
保证金
手续费
结算
```

这些都是市场规则，不是回测仿真规则。

Backtest、Paper 和 Live 都必须理解同一套市场制度。

新的配置名称应为以下之一：

```text
OnlyMarketConfig
```

优先使用：

```text
OnlyMarketConfig
```

除非当前工程命名约束明确要求使用：

```text
OnlyMarketProfileConfig
```

配置路径建议为：

```yaml
market:
  profile: CN_A_SHARE_CASH
```

禁止继续使用：

```yaml
market_simulation:
```

---

## 2. 不保留 Legacy 双路径

OnlyAlpha 当前仍处于早期开发阶段。

本任务不允许为了旧测试、旧接口或旧示例保留：

```text
if market is None:
    legacy path
else:
    new market path
```

如果旧类型、旧接口、旧字段与新设计表达相同业务概念，应：

```text
删除旧类型
迁移调用方
修改测试
修改示例
修改文档
```

禁止通过兼容层长期保留重复语义。

允许的临时迁移仅限：

```text
同一提交或同一任务阶段内的机械迁移
```

最终提交中不得存在两个正式路径。

---

## 3. Profile 不是 Runtime 组件依赖

以下组件不得直接依赖：

```text
OnlyMarketProfile
OnlyResolvedMarketProfile
OnlyMarketProfileRegistry
```

包括：

```text
Risk
Virtual Broker
ExecutionProcessor
Position
Account
Settlement
Margin
Collector
Strategy
```

Profile 是配置模型和规则来源。

正确流程是：

```text
Market Config
    ↓
Market Profile Registry
    ↓
Resolved Market Profile
    ↓
Market Rule Compiler
    ↓
OnlyMarketRuleEngine
    ↓
Runtime Components
```

Runtime 启动后，各业务组件只依赖受限的 Market Rule Port 或 Instruction Port。

---

## 4. Runtime 使用 Rule Engine，不使用 Profile

实现统一运行时对象：

```text
OnlyMarketRuleEngine
```

它是 Runtime 级不可变或受控可变的市场规则入口。

Runtime 组件不应自行解释 Profile 数据。

禁止：

```python
if profile.profile_id == CN_A_SHARE_CASH:
    ...
```

禁止：

```python
if resolved_profile.settlement_model.t_plus_days == 1:
    ...
```

禁止各组件直接读取 Profile 字段后自行实现规则。

必须通过明确的规则接口获取：

```text
Decision
Instruction
Policy
Effective Rule
```

---

# 二、开始前必须重新审计当前实现

修改代码前，必须阅读并输出中文审计报告。

至少阅读：

```text
AGENTS.md
HANDOFF.md
README.md
docs/architecture.md
docs/runtime.md
docs/market_simulation_framework.md
docs/versioned_market_profile_registry.md
docs/market_profile_configuration.md
docs/market_profiles.md
docs/settlement_model.md
docs/margin_model.md
docs/position.md
docs/position_modes.md
docs/order.md
docs/virtual_broker.md
docs/account.md
docs/results_framework.md
docs/adr/0024-multi-market-simulation-framework.md
docs/adr/0025-versioned-market-profile-and-conformance.md
```

完整阅读源码：

```text
src/onlyalpha/config/
src/onlyalpha/market/
src/onlyalpha/runtime/
src/onlyalpha/risk/
src/onlyalpha/broker/
src/onlyalpha/execution/
src/onlyalpha/order/
src/onlyalpha/position/
src/onlyalpha/account/
src/onlyalpha/collector/
src/onlyalpha/result/
src/onlyalpha/artifact/
tests/
```

重点确认：

```text
OnlyMarketSimulationConfig 的全部引用
OnlyMarketRule 的全部引用
OnlyResolvedMarketProfile 的全部引用
Virtual Broker 内部写死的 T+1 行为
Virtual Broker 内部账户/持仓状态
Risk 对旧 Market Rule Mapping 的依赖
ExecutionProcessor 的 Trade 应用流程
Position 当前如何区分 LONG/SHORT/OPEN/CLOSE
Settlement 当前是否真正改变可用状态
Margin 是否只有模型，没有状态生命周期
Collector 当前标准事实来源
```

审计报告必须明确：

```text
重复概念
错误边界
应删除接口
应保留模型
应迁移调用点
```

不得直接开始编码。

---

# 三、重新定义领域层级

本任务必须明确以下五层。

## 3.1 Market Profile 层

职责：

```text
保存市场默认规则定义
保存版本
保存有效期
保存 Capability
保存 Override Policy
保存规则来源和 Fingerprint
```

主要类型可以保留：

```text
OnlyMarketProfile
OnlyMarketProfileVersion
OnlyMarketProfileRegistry
OnlyMarketProfileRequest
OnlyResolvedMarketProfile
```

这些类型不进入 Risk、Broker、Execution 等核心业务组件。

---

## 3.2 Market Rule Compilation 层

新增：

```text
OnlyMarketRuleCompiler
OnlyMarketRuleCompilationContext
OnlyCompiledMarketRules
```

职责：

```text
Resolved Profile
+ Instrument Reference
+ Venue Reference
+ Trading Day
+ Runtime Mode
→ 可执行规则集合
```

编译结果必须：

```text
不可变
确定性
可 Fingerprint
不包含 Runtime Manager
不包含 Broker Store
不包含 Position Manager
不包含 Account Manager
```

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyCompiledMarketRules:
    identity: OnlyCompiledMarketRuleIdentity
    order_policy: OnlyOrderMarketPolicy
    price_policy: OnlyPriceMarketPolicy
    quantity_policy: OnlyQuantityMarketPolicy
    session_policy: OnlySessionMarketPolicy
    position_policy: OnlyPositionMarketPolicy
    settlement_policy: OnlySettlementMarketPolicy
    margin_policy: OnlyMarginMarketPolicy
    fee_policy: OnlyFeeMarketPolicy
    liquidity_policy: OnlyLiquidityMarketPolicy
    matching_policy: OnlyMatchingMarketPolicy
```

实际名称以工程风格为准。

---

## 3.3 Runtime Market Rule Engine 层

新增：

```text
OnlyMarketRuleEngine
```

它是 Runtime 内统一的市场规则服务。

职责：

```text
按 Instrument
按 Venue
按 Trading Day
解析并缓存 Compiled Market Rules

执行 Pre-Trade 决策

执行 Match-Time 决策

生成 Position Instruction

生成 Settlement Instruction

生成 Margin Instruction

生成 Fee Instruction

生成 Market Rule Decision
```

它不负责：

```text
保存订单
保存持仓
保存账户
改变现金
改变保证金
执行成交
写 Artifact
```

---

## 3.4 Runtime 业务组件层

包括：

```text
Risk
Broker
ExecutionProcessor
Position
Settlement
Margin
Account
Collector
```

它们只消费 Rule Engine 提供的：

```text
Decision
Instruction
Policy Port
```

不得消费 Profile。

---

## 3.5 Result 与审计层

负责记录：

```text
Resolved Market Identity
Compiled Rule Fingerprint
Market Rule Decisions
Settlement Records
Margin Records
Fee Breakdown
Profile Timeline
```

不得重新执行市场规则。

---

# 四、配置重新设计

## 4.1 删除旧配置

删除：

```text
OnlyMarketSimulationConfig
market_simulation
```

删除所有解析、导出、测试和文档引用。

## 4.2 新配置

新增：

```python
OnlyMarketConfig
```

建议结构：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketConfig:
    profile: OnlyMarketProfileId
    version: str | None = None
    overrides: OnlyJsonMapping = ...
```

配置：

```yaml
market:
  profile: CN_A_SHARE_CASH
```

固定版本：

```yaml
market:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
```

有限覆盖：

```yaml
market:
  profile: CN_A_SHARE_CASH

  overrides:
    liquidity:
      maximum_participation_rate: "0.05"

    slippage:
      model: FIXED_TICKS
      ticks: "1"
```

所有 Decimal 必须使用字符串。

---

## 4.3 Market 必须是 Runtime 必填配置

正式 Runtime 配置中：

```text
market
```

应为必填。

不存在 Market 缺失时自动进入旧逻辑。

测试需要显式选择测试市场，例如：

```text
GENERIC_T0_CASH
```

不要为了减少测试修改而让 Market 可选。

---

# 五、Composition Root 与 Runtime Factory

## 5.1 OnlyComponentFactoryRegistries

当前只有：

```text
data_sources
brokers
clusters
```

重新设计后，Composition Root 至少应具备：

```text
market_profile_registry
market_rule_compiler
```

例如：

```python
@dataclass(frozen=True, slots=True)
class OnlyComponentFactoryRegistries:
    data_sources: OnlyDataSourceFactoryRegistry
    brokers: OnlyBrokerFactoryRegistry
    clusters: OnlyClusterFactory
    market_profiles: OnlyMarketProfileRegistry
    market_rule_compiler: OnlyMarketRuleCompiler
```

如果 Compiler 不适合放在 Registry 容器，可以放入：

```text
OnlyEngineServices
```

但职责必须明确。

---

## 5.2 Runtime Factory 职责

Runtime Factory 只负责：

```text
读取 OnlyMarketConfig
解析 Profile
构建 Rule Engine
构建 Broker
构建 Runtime
注入 Rule Engine
注册 Instrument
```

Runtime Factory 不得：

```text
判断 T+1
判断涨跌停
计算手续费
计算保证金
判断做空
```

---

## 5.3 Profile Resolution 时点

Backtest：

```text
可以按 Run 起始 Trading Day 解析初始版本
```

但必须考虑跨版本回测。

建议 Runtime Rule Engine 支持按：

```text
profile family
instrument id
trading day
reference fingerprint
override fingerprint
```

缓存 Compiled Rules。

禁止只在 Runtime 启动时解析一次然后假定全回测区间规则永远不变。

---

# 六、OnlyMarketRuleEngine 接口设计

需要建立明确 Port，不允许出现一个无限膨胀的通用方法。

建议至少拆分以下接口。

## 6.1 Pre-Trade Port

```text
OnlyPreTradeMarketRulePort
```

输入：

```text
Order Intent
Instrument Reference
Trading Day
Session State
Current Position Availability
Current Cash Availability
Current Margin Availability
```

输出：

```text
OnlyMarketOrderDecision
```

至少包括：

```text
accepted
reason_code
rule_code
normalized_price
normalized_quantity
position_effect
required_cash
required_position
required_margin
```

Pre-Trade 不得读取未来 Bar。

---

## 6.2 Match-Time Port

```text
OnlyMatchTimeMarketRulePort
```

输入：

```text
Accepted Order
Current Bar or Market Snapshot
Shared Liquidity State
Compiled Rules
```

输出：

```text
OnlyMarketMatchDecision
```

至少包括：

```text
matched
unfilled_reason
reference_price
fill_price
fill_quantity
liquidity_side
remaining_liquidity
```

Match-Time 负责：

```text
交易状态
价格触达
涨跌停锁定
流动性
部分成交
滑点
Limit Price
最终 Tick 校验
```

---

## 6.3 Trade Instruction Port

```text
OnlyTradeInstructionPort
```

成交确定后生成：

```text
OnlyTradeApplicationInstruction
```

至少包含：

```text
position_instruction
settlement_instruction
margin_instruction
fee_instruction
cash_instruction
```

ExecutionProcessor 只应用这些 Instruction。

---

## 6.4 Settlement Port

```text
OnlySettlementRulePort
```

负责生成：

```text
OnlySettlementInstruction
```

例如：

```text
asset_available_on
cash_trade_available_on
cash_withdrawable_on
legal_settlement_on
```

Settlement 规则不能直接修改 Position 或 Account。

---

## 6.5 Margin Port

```text
OnlyMarginRulePort
```

负责生成：

```text
OnlyMarginInstruction
```

例如：

```text
reserve
consume
release
maintenance_required
currency
amount
```

Margin Rule 不能直接修改 Account。

---

## 6.6 Fee Port

```text
OnlyFeeRulePort
```

负责生成：

```text
OnlyFeeInstruction
OnlyFeeBreakdown
```

必须支持：

```text
Commission
Minimum Commission
Stamp Duty
Transfer Fee
Maker Fee
Taker Fee
Contract Fee
Close Today Fee
```

---

# 七、Risk 边界

Risk 是 Pre-Trade Orchestration Owner。

Risk 负责：

```text
调用 Market Rule Engine
调用账户级风险规则
调用策略级风险规则
调用权限规则
合并 Decision
建立 Reservation
生成 Risk Audit
```

Risk 不负责：

```text
解释 Profile
撮合
应用 Settlement
应用 Margin
计算最终成交费用
修改 Position
修改 Account
```

---

## 7.1 删除旧 Market Rule Mapping

当前存在：

```text
OnlyMarketRuleRiskMappingView
dict[OnlyInstrumentId, OnlyMarketRule]
```

如果其业务能力与新的 Market Rule Engine 重复，应删除。

不得同时保留：

```text
旧 OnlyMarketRule
新 OnlyMarketRuleEngine
```

如果旧 `OnlyMarketRule` 只表达 Instrument 基础约束，应将其字段迁移到：

```text
Instrument Reference
Compiled Market Rules
```

然后删除旧类型。

---

## 7.2 Risk 调用方式

建议：

```python
market_decision = market_rule_engine.evaluate_pre_trade(
    request=order_request,
    context=market_context,
)
```

然后 Risk Pipeline 合并：

```text
Market Rule Decision
Account Risk Decision
Strategy Risk Decision
Permission Decision
Kill Switch
```

最终仍输出统一：

```text
OnlyRiskDecision
```

但必须保留 Market Decision 的独立审计身份。

---

# 八、Broker 边界

Virtual Broker 是模拟外部 Broker/Venue。

职责：

```text
接收已通过 Pre-Trade 的订单
维护 Broker 订单生命周期
按 Bar/Market Snapshot 撮合
执行 Latency
执行 Match-Time Rules
生成 Broker Updates
生成 Broker Trade Update
```

不负责：

```text
Runtime 账户最终真值
Runtime 持仓最终真值
法律结算
策略 Ledger
Risk State
Profile 解析
```

---

## 8.1 删除写死的 T+1

当前 Virtual Broker 中按 Trading Day 固定调用：

```text
account_store.settle()
```

并发布：

```text
t-plus-one-settlement
```

应删除。

是否 T+1、T+0 或 T+N 由：

```text
OnlySettlementInstruction
```

决定。

Broker 不能根据日期变化自行推断结算制度。

---

## 8.2 Broker Store 的边界

必须明确 Broker Store 是：

```text
模拟外部 Broker Snapshot
```

而不是 Runtime 权威状态。

可保留：

```text
Broker Order Store
Broker Trade Store
Broker Account Snapshot
Broker Position Snapshot
```

用于：

```text
查询
对账
模拟外部系统
```

但 Runtime 真值由：

```text
ExecutionProcessor
→ Position Manager
→ Account Manager
→ Settlement Manager
→ Margin Manager
```

维护。

---

## 8.3 Matching 模型来源

Virtual Broker 不应自行从旧 Config 决定：

```text
Matching
Commission
Slippage
T+1
```

应由 Market Rule Engine 提供 Match-Time Policy。

允许 Broker Config 继续定义：

```text
latency
connectivity
failure injection
broker-specific technical limits
```

市场制度不属于 Broker Config。

---

# 九、ExecutionProcessor 边界

ExecutionProcessor 是 Runtime 内 Broker Update 的唯一正式业务应用入口。

它负责按确定顺序应用：

```text
Order Update
Position Instruction
Settlement Instruction
Margin Instruction
Fee Instruction
Account Cash Flow
Strategy Ledger
Risk Reservation
Invariant
Event
Audit
```

不得在 Position、Account 或 Broker 中建立旁路。

---

## 9.1 Trade 应用流程

建议顺序：

```text
1. Validate Broker Update
2. Deduplicate / Sequence
3. Update Order
4. Build Trade Application Instruction
5. Apply Position Instruction
6. Apply Settlement Instruction
7. Apply Margin Instruction
8. Apply Fee Instruction
9. Apply Account Cash Flow
10. Apply Strategy Ledger
11. Consume / Release Reservations
12. Refresh Risk State
13. Check Invariants
14. Publish Facts
15. Commit Audit
```

需要明确事务失败时的处理策略。

---

## 9.2 ExecutionProcessor 不知道具体市场

禁止：

```python
if market == "CN_A_SHARE":
```

禁止：

```python
if settlement_days == 1:
```

ExecutionProcessor 只执行 Instruction。

---

# 十、Position 边界

Position Manager 只负责：

```text
数量
方向
成本
已实现盈亏
未实现盈亏
Position Side
Position Effect
Settlement Bucket
```

Position Manager 不负责：

```text
决定能否卖出
决定是否 T+1
决定是否允许 Short
决定 Margin Rate
解析 Profile
```

---

## 10.1 Position Instruction

新增或完善：

```text
OnlyPositionInstruction
```

至少包含：

```text
instrument_id
position_side
position_effect
quantity
price
settlement_bucket
source_order_id
source_trade_id
```

支持：

```text
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
NET
```

未完成能力必须显式拒绝，不允许错误退化。

---

# 十一、Settlement 边界

Settlement 必须是正式 Runtime Manager，而不是简单的 Result Record。

新增或完善：

```text
OnlySettlementManager
OnlySettlementInstruction
OnlySettlementRecord
OnlySettlementProcessor
```

职责：

```text
登记待结算资产
登记待结算现金
推进 Trading Day
更新 available quantity
更新 available cash
更新 withdrawable cash
生成 Settlement Record
```

不负责：

```text
决定规则
计算撮合
更新订单
```

---

## 11.1 四维结算语义

必须区分：

```text
booked quantity
available quantity
trade-available cash
withdrawable cash
legal settlement
```

不能只用：

```text
settled / unsettled
```

一个布尔值表达全部状态。

---

# 十二、Margin 边界

Margin 必须是正式状态 Manager。

新增或完善：

```text
OnlyMarginManager
OnlyMarginInstruction
OnlyMarginReservation
OnlyMarginRecord
OnlyMarginProcessor
```

职责：

```text
预占
占用
部分成交调整
撤单释放
平仓释放
维持保证金状态
```

不负责：

```text
决定 Margin Rate
决定 Position Effect
撮合
更新订单
```

Margin Rate 和规则来自 Market Rule Engine。

---

# 十三、Fee 边界

已存在的：

```text
OnlyOrderFeeAccumulator
```

必须接入正式 Trade 应用链。

要求：

```text
一个订单多个 Fill
最低佣金只按累计应收计算一次
```

Fee Rule 负责：

```text
计算累计应收费
```

Fee Accumulator 负责：

```text
累计应收 - 累计已收
```

ExecutionProcessor 负责：

```text
应用本次 Fee Delta
```

---

# 十四、Collector 边界

Collector 只读取正式 Runtime 状态和标准事实。

Collector 不得：

```text
重新计算市场规则
根据 Profile 推断 Settlement
根据交易重新推导 Margin
根据订单重新计算 Fee
```

Collector 输出：

```text
Market Profile Resolution Record
Compiled Market Rule Identity
Market Rule Decisions
Settlement Records
Margin Records
Fee Breakdowns
Orders
Executions
Positions
Accounts
Diagnostics
```

---

# 十五、Market Rule Decision

建立统一：

```text
OnlyMarketRuleDecision
```

至少包含：

```text
decision_id
sequence
runtime_id
account_id
cluster_id
instrument_id
order_id
trade_id
timestamp
trading_day
stage
rule_code
accepted
reason_code
message
profile_id
profile_version
compiled_rules_fingerprint
details
schema_version
```

阶段：

```text
PRE_TRADE
MATCH_TIME
TRADE_APPLICATION
SETTLEMENT
MARGIN
FEE
```

记录策略：

```text
拒绝必须记录
改变最终行为的接受决策必须记录
普通无影响通过可按配置记录
```

---

# 十六、必须删除的重复和错误设计

本任务需要主动搜索并处理以下内容：

```text
OnlyMarketSimulationConfig
market_simulation
Legacy market path
Optional market config
OnlyMarketRule 与新规则重复部分
Virtual Broker 写死的 T+1
Virtual Broker 写死的 settled position 语义
Broker Config 中属于市场制度的 commission/slippage/matching
Risk 中旧 MarketRule Mapping
Runtime register_instrument(market_rule=...)
各组件直接读取 Profile
各组件按 Profile ID 分支
```

如果确认内容重复，应删除，不要加 Deprecated 注解后长期保留。

---

# 十七、首批正式 Runtime 纵切面

任务 1 必须使用正式 Runtime 完成以下四个纵切面。

暂时不实现 Scenario YAML DSL。

可通过直接构造正式 Config、Runtime、Instrument、Bar 和测试 Strategy 完成。

---

## 17.1 CN_A_SHARE_CASH

验证：

```text
T 日 BUY 100
→ 成交
→ total quantity = 100
→ available quantity = 0

T 日 SELL 100
→ Pre-Trade Reject
→ ASSET_NOT_AVAILABLE_T1

下一 Trading Day
→ Settlement Manager 推进
→ available quantity = 100

再次 SELL 100
→ 成交
```

同时验证：

```text
Profile 没有进入 Risk
Profile 没有进入 Broker
只有 Rule Engine 被使用
```

---

## 17.2 GENERIC_T0_CASH

验证：

```text
BUY
→ 成交
→ 当日 available quantity 增加

同 Trading Day SELL
→ 成交

卖出现金
→ 当日 trade-available
```

---

## 17.3 GENERIC_MARGIN_FUTURES

验证：

```text
SELL OPEN
→ 创建 Short
→ Margin Reservation
→ Fill 后 Margin Occupation

BUY CLOSE
→ Short 减少
→ Margin Release
```

同时验证：

```text
ExecutionProcessor 没有 Futures 分支
Position Manager 没有 Profile 分支
```

---

## 17.4 GENERIC_24X7_CRYPTO_SPOT

验证：

```text
周末 Bar 可交易
小数数量合法
quantity step 生效
minimum notional 生效
T0 生效
无固定日涨跌停
```

---

# 十八、测试要求

## 18.1 配置迁移测试

验证：

```text
market 必填
market_simulation 被拒绝
OnlyMarketSimulationConfig 不再存在
Decimal 必须字符串
未知 Profile 拒绝
未知 Version 拒绝
```

---

## 18.2 依赖边界测试

增加架构测试或 import 约束，保证：

```text
risk 不 import market.profile
broker 不 import market.profile
execution 不 import market.profile
position 不 import market.profile
account 不 import market.profile
settlement 不 import market.profile
margin 不 import market.profile
collector 不执行业务规则
```

允许：

```text
runtime composition
market compiler
market rule engine
```

依赖 Profile。

---

## 18.3 Runtime 测试

验证：

```text
Market Config
→ Registry
→ Resolver
→ Compiler
→ Rule Engine
→ Runtime
```

完整链路。

---

## 18.4 确定性测试

相同：

```text
Config
Profile Version
Reference
Bars
Orders
```

重复运行应得到相同：

```text
Decision
Fill
Settlement
Margin
Fee
Position
Account
Fingerprint
```

---

## 18.5 删除验证

必须确认：

```text
grep OnlyMarketSimulationConfig
grep market_simulation
grep legacy market
grep register_instrument.*market_rule
```

正式源码和正式配置中不再存在旧路径。

历史 ADR 可保留旧名称作为历史说明，但必须标注已被新 ADR supersede。

---

# 十九、阶段划分

严格按以下阶段实施。

## Stage 1：审计与删除计划

输出：

```text
重复模型表
旧接口引用表
删除清单
迁移清单
组件边界图
```

## Stage 2：新 ADR

新增 ADR：

```text
Unified Market Runtime Rules
```

明确：

```text
Market 不是 Simulation
Profile 不是 Runtime Dependency
Rule Engine 是唯一运行时入口
不保留 Legacy 双路径
```

并将 ADR 0024/0025 中冲突内容标记为：

```text
Superseded in part
```

## Stage 3：配置迁移

完成：

```text
OnlyMarketConfig
market
删除 OnlyMarketSimulationConfig
删除 market_simulation
```

## Stage 4：Compiler 与 Rule Engine

实现：

```text
OnlyMarketRuleCompiler
OnlyCompiledMarketRules
OnlyMarketRuleEngine
各受限 Port
```

## Stage 5：Runtime Factory

完成：

```text
Registry
Resolver
Compiler
Rule Engine
Runtime Injection
```

## Stage 6：Risk

删除旧 Mapping，接入 Pre-Trade Rule Port。

## Stage 7：Broker

删除 T+1 和市场制度硬编码，接入 Match-Time Rule Port。

## Stage 8：Execution

接入：

```text
Position Instruction
Settlement Instruction
Margin Instruction
Fee Instruction
```

## Stage 9：Managers

完成：

```text
Settlement Manager
Margin Manager
Fee Accumulator Integration
```

## Stage 10：Collector

从正式状态生成标准事实。

## Stage 11：四个纵切面

完成 A 股、T0、Futures、Crypto 正式 Runtime 测试。

## Stage 12：文档和门禁

更新所有文档、HANDOFF 和 Roadmap。

---

# 二十、本任务明确不做

暂时不实现：

```text
Scenario YAML DSL
Scenario Parser
Deterministic Action Strategy 通用框架
Conformance Packs
US/HK Experimental Packs
CLI market commands
Web Query DTO
OnlyAlpha-examples 大规模场景
Tushare Profile 自动加载
Plugins 修改
完整三仓门禁
```

但本任务必须为后续 Scenario Framework 提供稳定 Runtime 能力。

---

# 二十一、完成标准

以下全部满足才算完成：

```text
OnlyMarketSimulationConfig 已删除
market_simulation 已删除
OnlyMarketConfig 已成为正式必填配置
不存在 Legacy Market 路径

Profile 仅存在于：
    Config
    Registry
    Resolver
    Compiler
    Audit Identity

Runtime 组件只依赖：
    OnlyMarketRuleEngine
    或受限 Rule Port

旧 OnlyMarketRule 重复接口已删除或完成明确迁移

Virtual Broker 不再写死：
    T+1
    settled position
    commission
    slippage
    matching market policy

Risk 使用 Pre-Trade Rule Port
Broker 使用 Match-Time Rule Port
ExecutionProcessor 使用 Trade Instructions
Position 不解释市场制度
Settlement Manager 正式改变可用状态
Margin Manager 正式维护 Margin 生命周期
Fee Accumulator 正式接入多 Fill
Collector 只收集正式事实

CN_A_SHARE_CASH 纵切面通过
GENERIC_T0_CASH 纵切面通过
GENERIC_MARGIN_FUTURES 纵切面通过
GENERIC_24X7_CRYPTO_SPOT 纵切面通过

重复运行确定性通过
依赖边界测试通过
核心全量测试通过
Ruff 通过
Mypy 通过
git diff --check 通过
```

---

# 二十二、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

列出：

```text
错误抽象
重复类型
错误职责
写死市场逻辑
```

## 2. 删除内容

列出删除的：

```text
OnlyMarketSimulationConfig
market_simulation
Legacy Path
旧 Market Rule 接口
旧测试
旧文档引用
```

## 3. 新架构

展示：

```text
Market Config
→ Profile Resolver
→ Compiler
→ Rule Engine
→ Runtime Components
```

## 4. 组件边界

分别说明：

```text
Runtime Factory
Market Rule Engine
Risk
Broker
ExecutionProcessor
Position
Settlement
Margin
Account
Collector
```

## 5. Rule Ports

列出：

```text
Pre-Trade
Match-Time
Trade Instruction
Settlement
Margin
Fee
```

## 6. Runtime 纵切面

报告：

```text
CN_A_SHARE_CASH
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
```

## 7. 状态一致性

说明：

```text
Position
Available Position
Cash
Available Cash
Margin
Fee
Reservation
```

## 8. 确定性

报告重复运行结果和 Fingerprint。

## 9. 质量门禁

列出真实执行命令和结果。

## 10. 未完成项

不得把后续 Scenario、Conformance、US/HK、Tushare 或 Web 写成已完成。

---

# 二十三、最终架构原则

本任务最终必须满足：

> OnlyAlpha 中不存在“仿真市场规则”和“真实市场规则”两套体系，只有统一的 Market Rules。

> Backtest、Paper、Live 和 Shadow 使用相同的市场规则语义；差异仅存在于数据来源、Broker Gateway、时间驱动、外部状态权威和失败模式。

> Market Profile 是版本化配置来源，OnlyMarketRuleEngine 是唯一 Runtime 市场规则入口。

> Risk、Broker、Execution、Position、Settlement、Margin 和 Account 都不得通过 Profile ID、市场名称或资产类别硬编码业务规则。

> 旧接口如果与新接口表达相同业务语义，应被删除，而不是以兼容名义长期保留。
