你现在负责在 OnlyAlpha 四仓 Workspace 中设计并实现：

# OnlyAlpha Versioned Market Profiles and Multi-Market Conformance Suite

中文名称：

# OnlyAlpha 版本化默认市场配置与多市场规则一致性回测套件

本任务必须合并完成以下两个目标：

```text
1. Versioned Default Market Profile Registry
   版本化默认市场配置注册与解析系统

2. Multi-Market Simulation Conformance Suite
   多市场仿真规则一致性回测套件
```

最终必须实现：

> 用户只需在配置中选择一个 Market Profile，系统便自动加载完整、版本化、可审计的默认市场规则；随后通过正式 OnlyAlpha Engine、确定性人造 Instrument、Reference、Bar 和 Order Action，对该 Profile 声明支持的市场规则进行完整回测验证。

---

# 一、长期架构约束

OnlyAlpha 的所有设计必须同时满足以下四个维度：

```text
1. 多市场适配性
2. Backtest / Paper / Live 语义一致性
3. 未来 Web/API/实时展示能力
4. 确定性、可诊断、可审计和可复现
```

必须充分考虑：

```text
中国 A 股
港股
美股
中国及国际期货
外汇
加密货币现货
永续合约
交割合约
后续期权
```

必须覆盖或预留：

```text
T+0
T+1
T+N

Long-only
Netting
Hedging

现货
保证金
多头
空头
双向持仓

多币种
Base / Quote / Settlement Currency

整数数量
碎股
Board Lot
Quantity Step
Minimum Notional

日盘
夜盘
跨午夜
盘前
盘后
24×7

涨跌停
动态 Tick Table
熔断
价格保护

按成交额费用
按数量费用
按合约费用
最低佣金
Maker / Taker
税费
Borrow Fee
Funding
```

禁止在通用核心中写死：

```text
A 股 T+1
100 股整手
所有市场 Long-only
所有市场只能现金账户
所有市场都有涨跌停
所有市场只有一个日间 Session
所有数量都是整数
所有费用都是 commission
交易日等于自然日期
成交后资产和资金立即全部可用
```

---

# 二、当前工程背景

Workspace 包含：

```text
OnlyAlpha/
OnlyAlpha-plugins/
OnlyAlpha-examples/
OnlyAlpha-workspace/
```

当前核心已经存在或已建立基础边界：

```text
Engine
Runtime
Cluster
Clock
Event Bus
Historical Replay
Historical Cache
Market Data Pipeline
Strategy
Risk
Order
Virtual Broker
ExecutionProcessor
Position
Allocation
Strategy Ledger
Account
Results Framework
Artifact
Report

OnlyMarketProfile
OnlyMarketProfileResolver
OnlySettlementModel
OnlyMarketPositionMode
OnlyPositionEffect
OnlyShortSellingRule
OnlyMarginModel
OnlyTradingSessionModel
OnlyPriceRule
OnlyQuantityRule
OnlyFeeModel
OnlyLiquidityModel
OnlySlippageModel
OnlyMatchingModel
```

已经存在基础 Profile：

```text
CN_A_SHARE_CASH
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
```

但是当前不能默认认为这些 Profile 已经完整接入：

```text
Runtime Config
Risk
Virtual Broker
ExecutionProcessor
Settlement State
Margin State
Collector
Results
正式 Engine Examples
```

本任务必须先审计当前代码，以实际实现为准。

不得建立重复领域模型。

---

# 三、仓库职责

## 3.1 OnlyAlpha

负责：

```text
Market Profile Registry
Profile Family / Version
Profile Resolver
Capability Model
Override Policy
Resolved Profile
Instrument Reference Port
Scenario Domain
Scenario Runner
Assertion Engine
Runtime Market Simulation Context
Pre-Trade Rule Integration
Match-Time Rule Integration
Settlement / Margin Integration
Result / Artifact / Fingerprint
Query DTO 基础
```

## 3.2 OnlyAlpha-plugins

负责：

```text
Tushare Reference Provider
MiniQMT Reference Provider
未来交易所 Reference Provider
供应商和交易所数据适配
```

不得在插件仓重新定义核心规则模型。

## 3.3 OnlyAlpha-examples

负责：

```text
正式 Engine 场景
默认 Profile 使用示例
多市场 Conformance Packs
Expected vs Actual Artifact
```

## 3.4 OnlyAlpha-workspace

负责：

```text
子模块版本同步
统一验收
跨仓测试
```

---

# 四、开始前必须阅读

完整阅读：

```text
OnlyAlpha/AGENTS.md
OnlyAlpha/HANDOFF.md
OnlyAlpha/README.md
OnlyAlpha/docs/roadmap.md
OnlyAlpha/docs/architecture.md
OnlyAlpha/docs/market_simulation_framework.md
OnlyAlpha/docs/market_profiles.md
OnlyAlpha/docs/settlement_model.md
OnlyAlpha/docs/position_modes.md
OnlyAlpha/docs/margin_model.md
OnlyAlpha/docs/trading_sessions.md
OnlyAlpha/docs/multi_market_fees.md
OnlyAlpha/docs/a_share_market_profile.md
OnlyAlpha/docs/results_framework.md
OnlyAlpha/docs/adr/0024-multi-market-simulation-framework.md
OnlyAlpha/prompts/Market_Simulation_Framework.md
```

完整阅读相关源码：

```text
OnlyAlpha/src/onlyalpha/config/
OnlyAlpha/src/onlyalpha/domain/
OnlyAlpha/src/onlyalpha/instrument/
OnlyAlpha/src/onlyalpha/calendar/
OnlyAlpha/src/onlyalpha/market/
OnlyAlpha/src/onlyalpha/runtime/
OnlyAlpha/src/onlyalpha/risk/
OnlyAlpha/src/onlyalpha/order/
OnlyAlpha/src/onlyalpha/broker/
OnlyAlpha/src/onlyalpha/execution/
OnlyAlpha/src/onlyalpha/position/
OnlyAlpha/src/onlyalpha/account/
OnlyAlpha/src/onlyalpha/result/
OnlyAlpha/src/onlyalpha/collector/
OnlyAlpha/src/onlyalpha/artifact/
OnlyAlpha/src/onlyalpha/report/
OnlyAlpha/src/onlyalpha/engine/
OnlyAlpha/src/onlyalpha/cli/
OnlyAlpha/tests/
```

阅读示例和插件：

```text
OnlyAlpha-examples/examples/
OnlyAlpha-examples/src/
OnlyAlpha-examples/tests/

OnlyAlpha-plugins/packages/onlyalpha-plugin-virtual/
OnlyAlpha-plugins/packages/onlyalpha-plugin-tushare/
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/
```

实际目录和类型名称不同时，以当前仓库为准。

---

# 五、编码前必须输出中文审计报告

开始修改前，先输出设计审计。

至少回答以下问题。

## 5.1 Market Profile 当前状态

确认：

```text
Profile 是否只是一份静态对象
是否支持同一 Profile 多版本
是否支持 effective_from / effective_to
是否支持按交易日自动解析版本
是否支持固定版本
是否有 Registry
是否有 Profile 状态
是否有 Capability Set
是否有 Override Policy
```

## 5.2 Runtime 当前接入状态

确认 Profile 是否已经参与：

```text
Runtime Factory
Risk
Order Validation
Virtual Broker
ExecutionProcessor
Settlement
Margin
Collector
Fingerprint
Artifact
```

不能把文档声明当成代码事实。

## 5.3 配置现状

确认当前配置是否：

```text
只能手工填写全部规则
已经允许 profile id
支持版本
支持 override
支持 Legacy 模式
```

## 5.4 Synthetic 能力

确认当前是否已经存在：

```text
Synthetic Data Source
Fake Data Source
Deterministic Strategy
Scenario Runner
Scenario DSL
Expected Result Assertions
```

优先复用已有能力。

## 5.5 Result 和 Artifact

确认当前能否稳定输出：

```text
Orders
Executions
Trades
Positions
Accounts
Settlements
Margin
Market Rule Decisions
Diagnostics
Fingerprints
```

## 5.6 Web 边界

确认是否已有：

```text
Application Service
Query DTO
分页接口
Run Summary View
Scenario Result View
```

本任务不得直接实现 Web Server，但要保留稳定读取边界。

---

# 六、总目标

完成后，用户最简配置应为：

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
```

系统自动解析完整默认规则：

```text
Profile Family
Profile Version
Trading Sessions
Settlement Model
Position Mode
Short Selling
Margin
Price
Quantity
Fee
Liquidity
Slippage
Matching
Capabilities
Override Policy
```

用户不需要手工配置：

```text
T+1
涨跌停比例
整手规则
税费结构
Long-only
禁止裸卖空
```

场景测试同样只指定：

```yaml
scenario:
  profile: CN_A_SHARE_CASH
```

不得在每个测试场景中重复填写完整市场制度。

---

# 七、版本化 Market Profile Registry

## 7.1 核心类型

实现或完善：

```text
OnlyMarketProfileRegistry
OnlyMarketProfileFamily
OnlyMarketProfileVersion
OnlyMarketProfileStatus
OnlyMarketCapabilitySet
OnlyMarketProfileOverridePolicy
OnlyMarketProfileRequest
OnlyResolvedMarketProfile
OnlyResolvedMarketRuleManifest
```

建议状态：

```text
EXPERIMENTAL
STABLE
DEPRECATED
REMOVED
```

## 7.2 Profile Family 和 Version

必须区分：

```text
Profile Family:
    CN_A_SHARE_CASH

Profile Version:
    CN_A_SHARE_CASH@2025.1
```

Profile Family 不是一份永不变化的静态对象。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketProfileVersion:
    profile_id: OnlyMarketProfileId
    version: str
    status: OnlyMarketProfileStatus
    effective_from: date
    effective_to: date | None
    profile: OnlyMarketProfile
    capability_set: OnlyMarketCapabilitySet
    override_policy: OnlyMarketProfileOverridePolicy
    source: str
    schema_version: str
    content_fingerprint: str
```

## 7.3 自动版本解析

默认配置：

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
```

应使用：

```text
AUTO_EFFECTIVE_DATE
```

根据：

```text
回测交易日
Instrument Reference
Venue
Profile Family
```

解析有效版本。

允许固定版本：

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
```

固定版本模式：

```text
PINNED_VERSION
```

## 7.4 时间范围

如果回测跨越多个 Profile 版本，应明确支持以下一种策略，并通过 ADR 固化：

### 推荐策略

```text
运行过程中按 Trading Day 解析 Effective Version
```

也就是说：

```text
2024-12-31
→ CN_A_SHARE_CASH@2024.x

2025-01-02
→ CN_A_SHARE_CASH@2025.1
```

运行结果必须记录版本切换。

如果现阶段无法安全支持跨版本运行，可以暂时采用：

```text
单次 Run 必须落在一个 Profile Version 有效区间内
```

但必须：

```text
显式校验
显式报错
文档说明
不得静默选择错误版本
```

## 7.5 注册校验

Registry 注册时必须校验：

```text
同一 Family 的版本有效期不得重叠
Stable Profile 必须具有 Conformance Pack
Stable Profile 必须声明 Capability Set
Stable Profile 必须具有 Fingerprint
Profile ID 和 Version 组合唯一
Deprecated 版本仍可固定加载
Removed 版本不可新建运行
```

---

# 八、Profile Capability Set

实现：

```text
OnlyMarketCapabilitySet
```

至少包含：

```text
supports_intraday_resale
supports_t_plus_n
supports_short_selling
supports_borrow
supports_margin
supports_netting
supports_hedging
supports_fractional_quantity
supports_board_lot
supports_odd_lot
supports_minimum_notional
supports_multi_session
supports_cross_midnight_session
supports_24x7
supports_daily_price_limit
supports_dynamic_tick_table
supports_circuit_breaker
supports_partial_fill
supports_maker_taker
supports_contract_multiplier
supports_close_today
supports_funding
supports_liquidation
supports_multi_currency
```

要求：

> 一个 Capability 只有存在对应 Conformance Scenario 并通过测试，才能在 Stable Profile 中声明为 true。

禁止出现：

```text
Capability 声明支持
但没有行为测试
```

---

# 九、默认 Profile 的配置层次

必须明确三层规则来源。

## 9.1 Profile 默认制度

由 OnlyAlpha 内建：

```text
Session
Settlement
Position Mode
Short
Margin
Price
Quantity
Fee
Liquidity
Slippage
Matching
Capabilities
```

## 9.2 Instrument Reference

由具体 Instrument 提供：

```text
venue
board
st_status
tick_size
lot_size
quantity_step
minimum_quantity
minimum_notional
contract_multiplier
expiry
margin rate
fee tier
listing status
trading status
currency
base currency
quote currency
settlement currency
```

Profile 不能代替 Instrument Reference。

## 9.3 用户 Override

只允许覆盖仿真假设，不允许普通用户轻易篡改市场制度。

推荐允许：

```text
Liquidity participation rate
Slippage model
Matching model
Fee schedule selection
Strict mode
Pending order policy
Synthetic execution assumptions
```

默认禁止普通 Override：

```text
把 A 股 T+1 改成 T+0
打开 A 股裸卖空
取消期货保证金
把港股所有证券 lot size 改为统一值
给 Crypto 添加固定涨跌停
改变 Position Mode
改变 Settlement Family
```

这些需求必须使用：

```text
Custom Profile
```

---

# 十、配置模型

## 10.1 最简配置

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
```

## 10.2 固定版本

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
  version: "2025.1"
```

## 10.3 少量 Override

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH

  overrides:
    liquidity:
      maximum_participation_rate: "0.05"

    slippage:
      model: FIXED_TICKS
      ticks: 2
```

## 10.4 Legacy 兼容

旧配置未声明：

```yaml
market_simulation:
```

必须保持当前 Legacy 行为不变。

可映射到：

```text
LEGACY_CASH_NEXT_BAR
```

但不得静默让旧配置自动使用新的 A 股规则而改变历史测试结果。

## 10.5 配置中的 Decimal

所有：

```text
Price
Quantity
Rate
Fee
Margin
Participation
Slippage
```

必须使用字符串配置并解析为 Decimal。

---

# 十一、Resolved Market Profile

用户只写一行配置，但系统必须保存完整解析结果。

实现：

```text
OnlyResolvedMarketProfile
```

至少包含：

```text
requested_profile_id
requested_version
resolution_mode
resolved_profile_id
resolved_version
status
effective_from
effective_to
capabilities
reference_source
reference_version
reference_fingerprint
override_fingerprint
resolved_rules_fingerprint
schema_version
```

Artifact 输出：

```text
resolved_market_profile.json
market_rules_manifest.json
```

如果运行中出现版本变化，输出：

```text
market_profile_timeline.parquet
```

至少包含：

```text
sequence
trading_day
profile_id
profile_version
effective_from
effective_to
resolved_rules_fingerprint
```

---

# 十二、Runtime Market Simulation Context

实现或完善：

```text
OnlyMarketSimulationRuntimeContext
OnlyMarketProfileRuntimeResolver
OnlyInstrumentReferenceRuntimeService
OnlyPreTradeMarketRuleService
OnlyMatchTimeMarketRuleService
OnlySettlementService
OnlyMarginService
OnlyMarketRuleDecisionStore
```

Runtime 创建时装配一次：

```text
Config
→ Registry
→ Profile Resolver
→ Reference Provider
→ Runtime Context
```

Strategy 不得直接访问可变 Registry。

Risk、Broker 和 ExecutionProcessor 应通过受限接口使用已解析规则。

---

# 十三、Pre-Trade Rule Integration

Pre-Trade 只能使用当前已经知道的事实：

```text
Instrument 是否存在
Profile 是否适用
当前 Session 是否允许提交
Instrument 是否上市
是否退市
是否停牌
Order Type 是否支持
价格是否合法
Tick 是否对齐
数量是否合法
Lot 是否合法
Odd Lot 是否允许
Minimum Notional
Short 是否允许
T+1 可卖数量
可用现金
可用保证金
Position Effect
Reduce Only
```

返回标准：

```text
OnlyMarketRuleDecision
```

至少包含：

```text
decision_id
sequence
timestamp
trading_day
account_id
cluster_id
strategy_id
instrument_id
order_id
stage
rule_code
accepted
reason_code
message
profile_id
profile_version
reference_fingerprint
details
schema_version
```

阶段：

```text
PRE_TRADE
MATCH_TIME
POST_EXECUTION
SETTLEMENT
MARGIN
```

市场规则拒绝不得作为系统异常。

---

# 十四、Match-Time Rule Integration

Virtual Broker 必须使用已解析 Profile。

流程：

```text
收到 Bar
    ↓
解析 Reference / Profile Version
    ↓
解析 Session State
    ↓
建立 Instrument + Bar 共享 Liquidity State
    ↓
按稳定 Order Sequence 排序
    ↓
检查可交易性
    ↓
匹配参考价格
    ↓
检查 Price Limit / Price Protection
    ↓
分配共享流动性
    ↓
计算 Partial Fill
    ↓
应用 Slippage
    ↓
重新检查 Tick / Price Band / Limit Price
    ↓
计算 Fee
    ↓
产生 Broker Update
    ↓
产生 Market Rule Decisions
```

多个订单不得各自使用完整 Bar Volume。

所有结果必须确定性。

---

# 十五、Settlement Integration

必须区分：

```text
成交记账
总持仓
可用持仓
现金记账
可交易现金
可提现现金
法律结算
```

实现或完善：

```text
OnlySettlementManager
OnlySettlementRepository
OnlySettlementProcessor
OnlySettlementInstruction
OnlySettlementEvent
```

## 15.1 A 股 T+1

```text
T 日 BUY
    total quantity 增加
    available quantity 不增加

T 日 SELL
    因 available quantity 不足拒绝

下一 Trading Day
    available quantity 增加
```

## 15.2 T0

```text
BUY 后立即可卖
SELL 后资金立即可再次交易
```

## 15.3 T+N

至少通过 Generic Scenario 证明：

```text
availability day
legal settlement day
```

不是一个固定布尔值。

---

# 十六、Position Mode 与 Margin Integration

必须至少完成：

```text
LONG_ONLY
HEDGING
```

NETTING 可完整实现或保持明确的 Experimental 状态。

## 16.1 Futures

必须支持最小纵切面：

```text
BUY OPEN
SELL CLOSE

SELL OPEN
BUY CLOSE
```

验证：

```text
Long Position
Short Position
Contract Multiplier
Initial Margin
Maintenance Margin
Margin Occupation
Margin Release
```

不能把：

```text
SELL OPEN
```

当成股票 oversell。

## 16.2 Margin Service

实现或完善：

```text
OnlyMarginManager
OnlyMarginProcessor
OnlyMarginReservation
OnlyMarginChange
```

至少支持：

```text
Opening margin check
Margin reservation
Partial fill margin consumption
Close release
Insufficient margin rejection
```

---

# 十七、Fee Accumulator

实现：

```text
OnlyOrderFeeAccumulator
```

必须解决：

```text
一个订单多个 Fill
最低佣金不能每个 Fill 重复计算
```

推荐算法：

```text
每次 Fill 后：
    cumulative_required_fee
    minus cumulative_charged_fee
    equals current_fill_fee
```

支持：

```text
按成交额
按数量
按合约
固定费用
最低费用
买卖方向
Maker / Taker
OPEN / CLOSE / CLOSE_TODAY
```

所有 Fee Breakdown 必须保留组成。

---

# 十八、Scenario Domain

建立：

```text
OnlyMarketSimulationScenario
OnlyScenarioMetadata
OnlySyntheticInstrumentDefinition
OnlySyntheticReferenceDefinition
OnlySyntheticBarDefinition
OnlyScenarioAction
OnlyScenarioOrderAction
OnlyScenarioAdvanceAction
OnlyScenarioExpectedResult
OnlyScenarioExpectedDecision
OnlyScenarioExpectedState
OnlyScenarioExpectedArtifact
```

场景必须：

```text
确定性
可版本化
可独立运行
可通过正式 Engine 执行
可输出 Artifact
可在未来 Web 中展示
```

---

# 十九、Scenario DSL

建议使用 YAML。

示例：

```yaml
schema_version: "1"

scenario:
  id: cn_a_share_t1_same_day_sell_rejected
  version: "1"
  description: A 股买入后同一交易日不可卖
  profile: CN_A_SHARE_CASH
  profile_version: "2025.1"

runtime:
  initial_cash:
    currency: CNY
    amount: "100000"

instruments:
  - instrument_id: TEST.600000.XSHG
    asset_class: EQUITY
    venue: XSHG
    currency: CNY
    board: SSE_MAIN
    st_status: false
    tick_size: "0.01"
    lot_size: "100"
    trading_status: ACTIVE

bars:
  - sequence: 1
    instrument_id: TEST.600000.XSHG
    ts_event: 2025-01-02T07:00:00Z
    open: "10.00"
    high: "10.20"
    low: "9.90"
    close: "10.10"
    volume: "100000"

  - sequence: 2
    instrument_id: TEST.600000.XSHG
    ts_event: 2025-01-03T07:00:00Z
    open: "10.20"
    high: "10.30"
    low: "10.00"
    close: "10.20"
    volume: "100000"

actions:
  - id: buy_on_first_bar
    trigger:
      bar_sequence: 1
    order:
      side: BUY
      order_type: MARKET
      quantity: "100"

  - id: sell_same_day
    trigger:
      after_action: buy_on_first_bar
    order:
      side: SELL
      order_type: MARKET
      quantity: "100"

expected:
  orders:
    total: 2
    filled: 1
    rejected: 1

  decisions:
    - rule_code: ASSET_AVAILABILITY
      reason_code: ASSET_NOT_AVAILABLE_T1
      accepted: false

  final_position:
    instrument_id: TEST.600000.XSHG
    total_quantity: "100"
    available_quantity: "100"
```

场景不得重复定义：

```text
T+1
涨跌停
A 股费用
Long-only
禁止裸卖空
```

这些必须来自默认 Profile。

---

# 二十、Deterministic Action Strategy

实现测试专用策略：

```text
OnlyDeterministicActionStrategy
```

职责：

```text
根据 Scenario Action 在指定确定性边界提交订单
不计算指标
不根据收益动态决策
不包含市场规则
不绕过 Strategy Context
```

支持触发：

```text
Before Bar
On Bar
After Bar
After Action
After Execution
On Trading Day
On Session Phase
```

如果复杂触发会破坏正式策略 API，应优先使用最小、明确、可审计的 Action Scheduler。

---

# 二十一、Synthetic Data 与 Reference

实现或复用：

```text
OnlySyntheticHistoricalDataSource
OnlySyntheticInstrumentReferenceProvider
OnlySyntheticTradingCalendar
OnlySyntheticScenarioLoader
```

必须支持：

```text
任意 OHLCV
零成交量
有限成交量
跨午夜
周末
停牌
价格恰好涨停
价格距离涨停一个 Tick
缺失 Bar
多 Instrument
不同 Volume Unit
```

Synthetic 数据必须通过正式：

```text
Historical Replay
Market Data Pipeline
Strategy Dispatcher
Virtual Broker
ExecutionProcessor
Results Framework
```

不得直接调用 Broker 内部函数构造成交。

---

# 二十二、Assertion Engine

实现：

```text
OnlyScenarioAssertionEngine
OnlyScenarioAssertionResult
OnlyScenarioAssertionFailure
OnlyScenarioRunResult
```

至少支持验证：

## 22.1 行为

```text
Order Count
Order Status
Reject Reason
Execution Count
Execution Price
Execution Quantity
Unfilled Reason
```

## 22.2 状态

```text
Position
Available Quantity
Frozen Quantity
Cash
Available Cash
Settlement
Margin
Reservation
```

## 22.3 财务

```text
Notional
Fees
Realized PnL
Unrealized PnL
Equity
Margin
```

## 22.4 审计

```text
Market Rule Decisions
Diagnostics
Profile Version
Reference Fingerprint
Result Fingerprint
Artifact Fingerprint
```

## 22.5 恒等式

验证：

```text
ending equity
=
initial equity
+ realized pnl
+ unrealized pnl
- fees
± deposits/withdrawals
```

期货和多币种场景按对应 Account Model 使用正式恒等式。

---

# 二十三、Conformance Pack

实现：

```text
OnlyMarketConformancePack
OnlyMarketConformanceRegistry
```

至少注册：

```text
OnlyCnAShareCashConformancePack
OnlyGenericT0CashConformancePack
OnlyGenericMarginFuturesConformancePack
OnlyGenericCryptoSpotConformancePack
```

未来预留：

```text
OnlyUsEquityConformancePack
OnlyHkEquityConformancePack
OnlyCnFuturesConformancePack
OnlyCryptoPerpetualConformancePack
OnlyFxSpotConformancePack
OnlyOptionConformancePack
```

要求：

```text
Stable Profile
    必须绑定 Conformance Pack

Experimental Profile
    可以只有部分 Scenario

Deprecated Profile
    仍必须保留历史回归
```

---

# 二十四、A 股 Conformance Pack

至少覆盖：

```text
正常买入
正常卖出
T 日买入后同日卖出被拒绝
下一交易日可卖
非整手买入拒绝
零股全量清仓允许
零股部分卖出拒绝
主板 10%
ST 5%
创业板 20%
科创板 20%
涨停买入不成交
跌停卖出不成交
低于涨停一个 Tick 可成交
高于跌停一个 Tick 可成交
停牌新订单拒绝
停牌已有订单策略
最低佣金
卖出印花税
过户费
部分成交
跨 Bar 完成
多个订单共享流动性
价格 Tick 对齐
历史 Profile Version 解析
Unknown Board strict error
```

必须明确本阶段未覆盖的真实市场细节。

不得声称全部 A 股制度已经生产级完成。

---

# 二十五、Generic T0 Conformance Pack

至少覆盖：

```text
同一 Trading Day 买入后卖出
卖出资金立即复用
T0 与 T1 使用同一 Settlement 接口
```

---

# 二十六、Generic Futures Conformance Pack

至少覆盖：

```text
BUY OPEN Long
SELL CLOSE Long
SELL OPEN Short
BUY CLOSE Short
合约乘数
整数合约
保证金充足
保证金不足
开仓占用保证金
部分成交占用保证金
平仓释放保证金
每张合约手续费
夜盘跨自然日
正确 Trading Day
CLOSE_TODAY
CLOSE_YESTERDAY 扩展边界
```

如果本阶段未完整实现：

```text
CLOSE_TODAY
CLOSE_YESTERDAY
```

必须：

```text
Capability=false
Scenario 标记 expected unsupported
文档说明
```

---

# 二十七、Generic Crypto Spot Conformance Pack

至少覆盖：

```text
24×7
周末交易
小数数量
Quantity Step
Minimum Quantity
Minimum Notional
Tick Size
T0
Base / Quote 资产变化
Taker Fee
部分成交
无固定日涨跌停
```

---

# 二十八、其他市场的架构验证 Scenario

增加最小 Experimental 场景：

## 28.1 Generic US Equity

```text
T0
Fractional Quantity
Short Enabled
Pre-Market
Regular
After-Hours
```

## 28.2 Generic HK Equity

```text
Instrument-specific Board Lot
Midday Break
Odd Lot 扩展
```

这些场景用于验证架构。

不得将其标记为：

```text
正式美股支持
正式港股支持
```

---

# 二十九、Profile 默认值原则

必须遵守：

```text
市场制度默认值
    由 Profile 决定

Instrument 差异
    由 Reference 决定

仿真假设
    可由有限 Override 决定

策略参数
    不属于 Market Profile
```

示例：

```text
A 股 T+1
    Profile

某股票属于 ST
    Reference

最大成交量参与率 5%
    Override

MACD 参数
    Strategy Config
```

不得混淆。

---

# 三十、首批 Profile 稳定性

建议状态：

```text
CN_A_SHARE_CASH@2025.1
    STABLE，前提是正式纵切面和 Conformance Pack 全部通过

GENERIC_T0_CASH@1
    STABLE

GENERIC_MARGIN_FUTURES@1
    STABLE 或 EXPERIMENTAL，由实际完成度决定

GENERIC_24X7_CRYPTO_SPOT@1
    STABLE 或 EXPERIMENTAL，由实际完成度决定

US_EQUITY_CASH
    EXPERIMENTAL

HK_EQUITY_CASH
    EXPERIMENTAL

CN_FUTURES
    EXPERIMENTAL

CRYPTO_PERPETUAL
    EXPERIMENTAL
```

不得为了显示进度而错误标记 STABLE。

---

# 三十一、Results Framework 集成

继续扩展现有 Result，不建立平行结果体系。

新增或完善：

```text
OnlyScenarioRunRecord
OnlyScenarioAssertionRecord
OnlyMarketProfileResolutionRecord
OnlySettlementResultRecord
OnlyMarginResultRecord
OnlyMarketRuleDecisionResultRecord
```

Artifact 至少输出：

```text
scenario_summary.json
scenario_assertions.parquet
resolved_market_profile.json
market_rules_manifest.json
market_profile_timeline.parquet
orders.parquet
executions.parquet
positions.parquet
settlements.parquet
margin.parquet
market_rule_decisions.parquet
diagnostics.json
manifest.json
```

没有记录时保持零行稳定 Schema。

---

# 三十二、Scenario Result

实现稳定 DTO：

```text
OnlyScenarioRunView
```

至少包含：

```text
schema_version
scenario_id
scenario_version
profile_id
profile_version
profile_status
run_id
status
assertion_count
passed_count
failed_count
first_failure
started_at
completed_at
result_fingerprint
artifact_fingerprint
```

时间字段不进入确定性结果指纹。

这个 DTO 将来可直接供 Web 使用。

---

# 三十三、Web Query Foundation

本任务不实现：

```text
FastAPI
WebSocket
SSE Server
前端页面
数据库
权限系统
```

但必须为未来 Web 建立稳定查询边界。

实现或预留：

```text
OnlyMarketProfileView
OnlyMarketProfileVersionView
OnlyMarketCapabilityView
OnlyScenarioSummaryView
OnlyScenarioAssertionView
OnlyMarketRuleDecisionView
OnlySettlementView
OnlyMarginView
```

Query Port：

```text
OnlyMarketProfileQueryService
OnlyScenarioQueryService
```

至少支持概念接口：

```text
list_profiles(...)
get_profile(...)
list_profile_versions(...)
resolve_profile(...)
list_scenarios(...)
get_scenario_run(...)
list_scenario_assertions(...)
list_market_rule_decisions(...)
```

要求：

```text
分页
过滤
稳定排序
schema_version
不直接暴露内部可变 Domain 对象
```

---

# 三十四、Fingerprint

必须纳入：

```text
Scenario Definition
Scenario Version
Profile Family
Resolved Profile Version
Capability Set
Instrument Reference
Override
Session
Settlement
Position Mode
Short Rule
Margin
Price
Quantity
Fee
Liquidity
Slippage
Matching
Synthetic Bars
Actions
Expected Assertions
Actual Standard Facts
```

排除：

```text
run_id
墙钟时间
临时目录
PID
hostname
绝对路径
traceback
```

要求：

```text
相同 Scenario + 相同 Profile Version
    重复运行指纹一致

Profile Version 改变
    指纹改变

Override 改变
    指纹改变

Reference 改变
    指纹改变

Expected Result 改变
    Assertion Definition Fingerprint 改变
```

---

# 三十五、CLI

优先复用：

```text
onlyalpha run
```

正式场景必须能通过 Engine 执行。

可以增加：

```bash
onlyalpha market profiles
onlyalpha market profile show CN_A_SHARE_CASH
onlyalpha market profile resolve CN_A_SHARE_CASH --date 2025-01-02
onlyalpha market conformance run CN_A_SHARE_CASH
onlyalpha market scenario run path/to/scenario.yaml
```

但不得建立绕过 Engine 的第二套回测执行器。

推荐关系：

```text
Scenario CLI
    ↓
生成正式 Engine Config
    ↓
OnlyEngine
    ↓
Runtime
```

---

# 三十六、Examples

新增：

```text
OnlyAlpha-examples/examples/market_conformance/
├── cn_a_share_cash/
├── generic_t0_cash/
├── generic_margin_futures/
├── generic_crypto_spot/
├── generic_us_equity/
└── generic_hk_equity/
```

每个目录包含：

```text
README.md
scenario yaml
最小运行配置
预期结果说明
```

必须通过正式命令运行。

---

# 三十七、Tushare 验收

Synthetic Conformance 全部完成后，再更新真实示例：

```text
OnlyAlpha-examples/examples/tushare_daily_backtest/
```

配置只需：

```yaml
market_simulation:
  profile: CN_A_SHARE_CASH
```

不得再手工重复：

```text
T+1
lot size
price limit
A 股费用
```

验证：

```text
Profile 自动加载
Instrument Reference 正确解析
Online
CACHE_ONLY
结果一致
规则指纹一致
Artifact 完整
```

在线和 CACHE_ONLY 配置除 Token/Cache Policy 外必须一致。

如果在线服务不可用：

```text
只报告 Cache 验收
不得虚构在线结果
```

---

# 三十八、测试分类

建议测试分层：

```text
Unit
    Registry
    Resolver
    Capability
    Override
    Scenario Parser
    Assertion Engine

Component
    Pre-Trade
    Match-Time
    Settlement
    Margin
    Fee Accumulator

Runtime
    Profile → Risk → Broker → Execution → State

Conformance
    完整 Scenario Pack

Regression
    Stable Profile 历史版本

Artifact
    Schema
    Fingerprint
    Query DTO
```

---

# 三十九、核心测试要求

至少覆盖：

## Registry

```text
版本注册
有效期重叠拒绝
自动版本解析
固定版本解析
Deprecated 可固定加载
Removed 拒绝
未知 Profile
未知 Version
```

## Override

```text
允许的 Override 成功
禁止的 Override 拒绝
Override Fingerprint
```

## Capability

```text
Stable Profile capability 与 Scenario 对应
声明但无 Scenario 时门禁失败
```

## Scenario

```text
YAML Schema
Decimal
UTC
稳定顺序
非法触发
未知 Instrument
未知 Action
```

## Runtime

```text
Legacy 不变
Profile opt-in 生效
Profile 规则进入 Risk
Profile 规则进入 Broker
Settlement 生效
Margin 生效
Facts 生效
```

## Determinism

```text
重复运行结果一致
不同 Profile 结果不同
不同 Version 结果不同
不同 Override 结果不同
```

---

# 四十、禁止事项

禁止：

```text
让每个场景手写完整市场规则
把 Profile 退化为普通 YAML 字典
把 Instrument Reference 塞进 Profile
让普通 Override 改变 Settlement/Position Mode 等市场制度
在 Scenario Runner 中直接伪造成交
绕过 Engine
绕过 Risk
绕过 Virtual Broker
绕过 ExecutionProcessor
在 Assertion Engine 中重新计算业务状态
为了测试方便直接修改 Position/Account
把 Stable 标记用于未通过 Conformance 的 Profile
把 Experimental Profile 描述成正式市场支持
让 Web Query DTO 直接引用内部可变对象
用 float 处理金额、价格、数量和比例
```

---

# 四十一、实施阶段

严格分阶段执行。

## Stage 1：现状审计

输出：

```text
Profile
Registry
Runtime
Config
Synthetic
Results
Web Query
```

审计报告。

## Stage 2：ADR 与设计

新增 ADR，明确：

```text
Profile Family / Version
Auto / Pinned Resolution
Stable / Experimental
Override Policy
Capability / Conformance 绑定
Scenario Runner 必须经过 Engine
```

## Stage 3：Registry

实现：

```text
Versioned Registry
Resolver
Status
Capability
Override Policy
Resolved Manifest
```

## Stage 4：Runtime 配置接入

实现：

```text
market_simulation.profile
version
overrides
Legacy compatibility
```

## Stage 5：Runtime 纵切面

接入：

```text
Risk
Broker
ExecutionProcessor
Settlement
Margin
Fee Accumulator
Collector
```

## Stage 6：Scenario Framework

实现：

```text
DSL
Parser
Synthetic Source
Deterministic Strategy
Runner
Assertion Engine
```

## Stage 7：Generic Packs

完成：

```text
T0
Futures
Crypto
```

## Stage 8：A 股 Pack

完成正式基础 A 股规则验证。

## Stage 9：Experimental Market Validation

完成：

```text
Generic US
Generic HK
```

架构测试。

## Stage 10：Results / Artifact / Query DTO

完成稳定输出。

## Stage 11：Examples

通过正式 CLI 执行。

## Stage 12：Tushare

完成真实 Profile 自动加载验收。

## Stage 13：文档、门禁、交接

---

# 四十二、文档要求

新增或更新：

```text
docs/versioned_market_profile_registry.md
docs/market_profile_configuration.md
docs/market_profile_capabilities.md
docs/market_conformance_suite.md
docs/market_scenario_dsl.md
docs/market_profile_override_policy.md
docs/web_market_profile_query_models.md
docs/adr/xxxx-versioned-market-profile-and-conformance.md
HANDOFF.md
docs/roadmap.md
AGENTS.md
```

文档必须说明：

```text
正式支持
Experimental
接口预留
未实现
```

不得混淆。

---

# 四十三、质量门禁

执行真实命令：

```bash
uv run --directory OnlyAlpha pytest -q
uv run --directory OnlyAlpha ruff check .
uv run --directory OnlyAlpha ruff format --check .
uv run --directory OnlyAlpha mypy
git -C OnlyAlpha diff --check

uv run --directory OnlyAlpha-plugins pytest -q
uv run --directory OnlyAlpha-plugins ruff check .
uv run --directory OnlyAlpha-plugins ruff format --check .
uv run --directory OnlyAlpha-plugins mypy
git -C OnlyAlpha-plugins diff --check

uv run --directory OnlyAlpha-examples pytest -q
uv run --directory OnlyAlpha-examples ruff check .
uv run --directory OnlyAlpha-examples ruff format --check .
uv run --directory OnlyAlpha-examples mypy
git -C OnlyAlpha-examples diff --check
```

运行所有正式 Conformance Packs。

不得虚构测试结果。

---

# 四十四、完成标准

以下全部满足才算完成：

```text
Versioned Profile Registry
Profile Family / Version
AUTO_EFFECTIVE_DATE
PINNED_VERSION
Stable / Experimental / Deprecated
Capability Set
Override Policy
Resolved Profile Manifest

最简配置：
    market_simulation.profile

Legacy 行为不变

Profile 正式进入：
    Runtime
    Risk
    Broker
    ExecutionProcessor
    Settlement
    Margin
    Result

Scenario DSL
Synthetic Reference
Synthetic Bars
Deterministic Action Strategy
Scenario Runner
Assertion Engine
Conformance Pack

A 股完整基础 Pack
Generic T0 Pack
Generic Futures Pack
Generic Crypto Pack
US/HK Experimental 验证

Fee Accumulator
Partial Fill
Shared Liquidity

Settlement Records
Margin Records
Market Rule Decisions
Scenario Assertions
Artifact
Fingerprint

Query DTO / Query Port
正式 Examples
Tushare Profile 自动加载
三仓门禁
文档
ADR
HANDOFF
ROADMAP
```

---

# 四十五、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

说明原有 Profile、Runtime 和测试缺口。

## 2. Profile Registry

说明：

```text
Family
Version
Status
Effective Date
Resolution Mode
```

## 3. 默认配置

展示最简配置和 Override。

## 4. Capability

列出每个 Profile 的能力矩阵。

## 5. Runtime Integration

说明规则如何进入：

```text
Risk
Broker
Execution
Settlement
Margin
Result
```

## 6. Scenario Framework

说明 DSL、Synthetic Source、Action Strategy 和 Assertion Engine。

## 7. Conformance Results

逐个报告：

```text
CN_A_SHARE_CASH
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
Generic US
Generic HK
```

## 8. A 股规则

列出通过和未覆盖规则。

## 9. Generic Futures

列出多空、保证金和跨午夜结果。

## 10. Crypto

列出 24×7、小数数量和最小名义金额结果。

## 11. Artifact 和 Fingerprint

列出文件、Schema 和确定性验证。

## 12. Web Query Foundation

说明稳定 DTO 和分页边界。

## 13. Tushare

列出真实验收结果。

## 14. 质量门禁

列出真实命令和结果。

## 15. 未完成项

不得把 Experimental 或接口预留写成正式支持。

---

# 四十六、最终目标

最终目标是：

> 建立一个版本化、默认可用、配置简洁、规则完整、可审计的 Market Profile 系统。用户只需选择 Profile，系统便能自动解析对应交易日、交易所和 Instrument 的有效市场规则；同时通过确定性人造行情和正式 Engine 回测，对每个 Profile 声明支持的结算、价格、数量、持仓、卖空、保证金、费用、流动性、滑点和撮合能力进行一致性验证。

并且确保：

> 只有通过对应 Conformance Pack 的能力，才能被 Stable Profile 声明为正式支持；回测、Paper、Live 和未来 Web 使用同一套 Profile 身份、规则版本、标准事实、结果 DTO 和审计模型。
