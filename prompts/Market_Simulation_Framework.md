你现在负责在 OnlyAlpha 四仓 Workspace 中设计并实现正式的：

# OnlyAlpha Multi-Market Simulation Framework

中文名称：

# OnlyAlpha 多市场交易规则与仿真框架

本阶段第一个正式落地的市场为：

# China A-Share Market Profile

即：

# 中国 A 股市场规则配置

但架构必须从第一天起充分支持以下市场与结算模式：

```text
中国 A 股
港股
美股
中国期货
国际期货
现货加密货币
永续合约
交割合约
外汇
后续期权
```

必须支持并清晰区分：

```text
T+0 可卖
T+1 可卖
T+N 结算

现货持仓
保证金持仓
多头
空头
双向持仓
净持仓

24×7 市场
有交易日和交易时段的市场
跨午夜交易时段
日盘与夜盘
盘前、盘中、盘后

中央竞价市场
经纪商内部撮合
Bar 级模拟
后续 Tick / Order Book 模拟
```

本任务不能把 A 股的：

```text
T+1
100 股整手
涨跌停
卖出印花税
禁止裸卖空
```

等规则写入通用 Order、Position、Account、Broker 或 Engine。

这些规则必须由可版本化的市场配置和规则组件表达。

---

# 一、核心目标

当前 OnlyAlpha 已完成：

```text
Engine
Runtime
Cluster
Historical Data
Cache
Replay
Market Data Pipeline
Indicator
Factor
Strategy
Risk
Order
Virtual Broker
ExecutionProcessor
Position
Allocation
Ledger
Account
Results Framework
```

本任务要把当前基础：

```text
Next-Bar Virtual Broker
```

升级为：

```text
多市场通用仿真内核
    +
首个完整 A 股市场配置
```

最终架构应形成：

```text
Instrument Reference
        ↓
Market Profile Resolver
        ↓
Effective Market Rules
        ↓
Trading Calendar / Session State
        ↓
Pre-Trade Validation
        ↓
Risk / Margin / Reservation
        ↓
Matching Engine
        ├── Tradability
        ├── Price Rules
        ├── Quantity Rules
        ├── Position / Settlement Rules
        ├── Liquidity
        ├── Slippage
        ├── Fee
        └── Margin
        ↓
Broker Events
        ↓
ExecutionProcessor
        ↓
Order / Position / Ledger / Account
        ↓
Results Framework
```

完成后，框架必须能够表达：

```text
A 股：
    T+1 可卖
    涨跌停
    停牌
    整手
    零股清仓
    印花税
    最低佣金

美股：
    T+0 卖出
    盘前盘后
    碎股
    卖空
    Locate / Borrow
    PDT 等账户约束扩展

港股：
    T+0 交易
    每只证券不同 Board Lot
    碎股市场
    港币费用体系
    午间休市

期货：
    多空双向
    开仓和平仓
    平今和平昨
    保证金
    合约乘数
    夜盘
    涨跌停
    强平扩展

加密货币现货：
    24×7
    T+0
    Base / Quote 资产
    最小名义金额
    数量与价格步长
    Maker / Taker Fee

永续与交割合约：
    杠杆
    Initial / Maintenance Margin
    Funding
    Mark Price
    Liquidation
    Long / Short 或 Net Position Mode
```

---

# 二、Workspace 范围

Workspace 包含：

```text
OnlyAlpha/
OnlyAlpha-plugins/
OnlyAlpha-examples/
OnlyAlpha-workspace/
```

职责边界：

```text
OnlyAlpha
    通用市场规则领域模型
    Market Profile SPI
    Settlement / Position / Margin 模型
    Fee / Price / Quantity / Session / Liquidity / Slippage
    Matching Engine 通用边界
    Results Framework 集成
    A 股基础规则实现

OnlyAlpha-plugins
    交易所和供应商数据适配
    Tushare Reference Provider
    MiniQMT Reference Provider
    后续 Crypto Exchange / Futures Reference Provider
    不定义核心市场规则抽象

OnlyAlpha-examples
    多市场确定性场景
    A 股真实日线示例
    T+0 / T+1 对照示例
    现货 / 保证金对照示例

OnlyAlpha-workspace
    子模块版本集成
    统一环境
    跨仓验收
```

所有 OnlyAlpha 公共类型继续使用：

```text
Only*
```

前缀。

---

# 三、总体设计原则

必须遵守以下原则：

```text
1. 市场规则不是 A 股规则的集合，而是多市场能力模型
2. A 股只是第一个 Market Profile
3. Instrument 决定静态交易属性
4. Market Profile 决定市场制度
5. Effective Rule Set 决定某交易日实际生效规则
6. Trading Calendar 决定何时可以交易
7. Settlement Model 决定资产与资金何时可用
8. Position Model 决定净持仓、双向持仓和空头能力
9. Margin Model 决定保证金、杠杆和强平能力
10. Broker Matching 决定成交可能性
11. ExecutionProcessor 仍是唯一正式状态变更入口
12. Result Collector 只观察事实
13. Analytics 不参与撮合
14. Report 不重新计算费用和保证金
15. 所有规则按时间版本化
16. 所有金额、价格、数量和比例使用 Decimal 语义
17. 所有撮合顺序必须确定性
18. 所有规则决策必须可解释、可审计
```

禁止：

```text
把 T+1 字段写死在通用 Position 中
把 100 股整手写死在通用 Order Service
把 A 股涨跌停写进 Engine
把禁止卖空写死在通用 Broker
把交易日定义为自然日
假设所有市场每天都有开盘和收盘
假设所有市场只有一个日间 Session
假设所有持仓只有 Long
假设所有费用只按成交额比例计算
假设所有订单只能由 Bar 撮合
假设所有成交都立即完成资金和证券结算
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
OnlyAlpha/docs/runtime.md
OnlyAlpha/docs/instrument_model.md
OnlyAlpha/docs/results_framework.md
OnlyAlpha/docs/results_framework_handoff.md
OnlyAlpha/docs/adr/0023-backtest-results-framework.md
```

完整阅读核心代码：

```text
OnlyAlpha/src/onlyalpha/domain/
OnlyAlpha/src/onlyalpha/instrument/
OnlyAlpha/src/onlyalpha/calendar/
OnlyAlpha/src/onlyalpha/clock/
OnlyAlpha/src/onlyalpha/market_data/
OnlyAlpha/src/onlyalpha/order/
OnlyAlpha/src/onlyalpha/risk/
OnlyAlpha/src/onlyalpha/broker/
OnlyAlpha/src/onlyalpha/execution/
OnlyAlpha/src/onlyalpha/position/
OnlyAlpha/src/onlyalpha/ledger/
OnlyAlpha/src/onlyalpha/account/
OnlyAlpha/src/onlyalpha/runtime/
OnlyAlpha/src/onlyalpha/result/
OnlyAlpha/src/onlyalpha/collector/
OnlyAlpha/src/onlyalpha/analytics/
OnlyAlpha/src/onlyalpha/artifact/
OnlyAlpha/src/onlyalpha/report/
OnlyAlpha/tests/
```

阅读插件和示例：

```text
OnlyAlpha-plugins/packages/onlyalpha-plugin-virtual/
OnlyAlpha-plugins/packages/onlyalpha-plugin-tushare/
OnlyAlpha-plugins/packages/onlyalpha-plugin-miniqmt/

OnlyAlpha-examples/examples/tushare_daily_backtest/
OnlyAlpha-examples/src/onlyalpha_examples/
```

重点查找并复用：

```text
OnlyInstrument
OnlyEquity
OnlyETF
OnlyFuture
OnlyOption
OnlyCryptoSpot
OnlyCryptoFuture
OnlyCryptoPerpetual
OnlyFxPair

OnlyPrice
OnlyQuantity
OnlyMoney
OnlyCurrency
OnlyTradingCalendar
OnlyTradingDay
OnlyTradingSession

OnlyOrder
OnlyOrderRequest
OnlyOrderSide
OnlyPositionEffect
OnlyOrderType
OnlyTimeInForce

OnlyPosition
OnlyPositionAllocation
OnlyStrategyLedger
OnlyAccount
OnlyRiskReservation

OnlyVirtualBroker
OnlyBrokerUpdate
OnlyExecutionProcessor

OnlyBacktestResult
OnlyBacktestFacts
OnlyExecutionResultRecord
OnlyBacktestAnalysis
```

实际名称不同则以当前代码为准。

禁止建立重复领域模型。

---

# 五、修改前分析要求

开始编码前，必须先输出中文设计分析。

至少回答：

## 5.1 当前 Position 模型

确认是否支持：

```text
Long
Short
Net Position
Hedge Position
Position Side
Position Effect
Available Quantity
Frozen Quantity
Settlement Date
```

明确哪些已有，哪些不足。

## 5.2 当前 T+1 实现

说明当前 T+1：

```text
由 Position 实现
由 Trading Day Settlement 实现
由 Risk 实现
还是由 Account 实现
```

判断如何重构为通用 Settlement Model。

## 5.3 当前期货能力

检查：

```text
OnlyFuture
contract multiplier
margin
long / short
OPEN / CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

是否已经存在。

不得在不了解当前模型时新增平行类型。

## 5.4 当前加密资产能力

检查：

```text
base currency
quote currency
settlement currency
quantity precision
minimum notional
maker/taker fee
inverse / linear contract
funding
mark price
```

已有多少领域边界。

## 5.5 当前账户模型

确认当前 Account 是否只能表达：

```text
Cash Account
```

还是已经预留：

```text
Margin
Collateral
Debt
Available Margin
Maintenance Margin
Unrealized PnL
```

## 5.6 当前撮合模型

分析 Virtual Broker 是否假设：

```text
单一 Session
单一 Position Side
立即结算
仅 Bar 模型
固定费用
```

## 5.7 当前 Results Framework

分析如何增加：

```text
Settlement Facts
Margin Facts
Funding Facts
Borrow Facts
Market Rule Decisions
Position Side
Fee Breakdown
Liquidity Facts
```

分析后再实施。

---

# 六、总体模块结构

建议模块结构如下，但必须优先服从现有仓库组织：

```text
src/onlyalpha/
├── market/
│   ├── profiles/
│   ├── rules/
│   ├── sessions/
│   ├── settlement/
│   ├── position_mode/
│   ├── margin/
│   ├── fees/
│   ├── liquidity/
│   ├── slippage/
│   └── reference/
├── matching/
│   ├── models.py
│   ├── engine.py
│   ├── bar_model.py
│   └── state.py
```

推荐核心类型：

```text
OnlyMarketProfile
OnlyMarketProfileId
OnlyMarketProfileResolver
OnlyEffectiveMarketRules

OnlySettlementModel
OnlySettlementRule
OnlySettlementInstruction
OnlySettlementState

OnlyPositionMode
OnlyPositionAccountingModel
OnlyShortSellingRule
OnlyBorrowRule

OnlyMarginModel
OnlyMarginRequirement
OnlyMarginState
OnlyLiquidationRule

OnlyTradingSessionModel
OnlyTradingPhase
OnlyTradingPhaseRule

OnlyFeeModel
OnlyLiquidityModel
OnlySlippageModel
OnlyMatchingModel
```

---

# 七、Market Profile

## 7.1 OnlyMarketProfile

Market Profile 表达一类市场制度，而不是单个 Instrument。

建议：

```python
@dataclass(frozen=True, slots=True)
class OnlyMarketProfile:
    profile_id: OnlyMarketProfileId
    market: OnlyMarket
    venue: OnlyVenue | None
    asset_classes: tuple[OnlyAssetClass, ...]

    session_model: OnlyTradingSessionModel
    settlement_model: OnlySettlementModel
    position_model: OnlyPositionAccountingModel
    short_selling_rule: OnlyShortSellingRule
    margin_model: OnlyMarginModel | None

    price_rule: OnlyPriceRule
    quantity_rule: OnlyQuantityRule
    fee_model: OnlyFeeModel
    liquidity_model: OnlyLiquidityModel
    slippage_model: OnlySlippageModel
    matching_model: OnlyMatchingModel

    effective_from: date
    effective_to: date | None
    version: str
    source: str
    content_fingerprint: str
```

## 7.2 首批 Profile ID

至少预留：

```text
CN_A_SHARE_CASH
HK_EQUITY_CASH
US_EQUITY_CASH
CN_FUTURES
CRYPTO_SPOT
CRYPTO_PERPETUAL
CRYPTO_DELIVERY_FUTURE
FX_SPOT
```

本任务正式实现：

```text
CN_A_SHARE_CASH
```

同时至少实现用于架构验证的最小测试 Profile：

```text
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
```

这些 Generic Profile 用于证明核心没有被 A 股假设污染。

---

# 八、Settlement Model

这是本次架构最重要的部分之一。

必须区分：

```text
成交
资产记账
资产可用
资金记账
资金可用
最终清算
```

不得简单用一个 `T+1` 布尔值表达。

## 8.1 OnlySettlementModel

建议接口：

```python
class OnlySettlementModel(Protocol):
    def on_execution(
        self,
        context: OnlySettlementContext,
    ) -> OnlySettlementInstruction:
        ...

    def advance(
        self,
        state: OnlySettlementState,
        event: OnlySettlementAdvanceEvent,
    ) -> tuple[OnlySettlementEvent, ...]:
        ...
```

## 8.2 Settlement Dimension

至少区分：

```text
asset_settlement_lag
cash_settlement_lag
asset_availability_lag
cash_availability_lag
```

因为：

```text
可交易时间
法律结算时间
资金可提取时间
```

不是同一个概念。

## 8.3 支持的基础模式

至少实现抽象能力：

```text
IMMEDIATE
T_PLUS_ZERO
T_PLUS_ONE
T_PLUS_N
SESSION_END
NEXT_TRADING_DAY
```

## 8.4 A 股语义

A 股买入：

```text
成交后立即计入总持仓
当日不可卖
下一交易日转为可卖
```

A 股卖出资金：

```text
成交后账户现金如何记账
何时可再次交易
何时可提现
```

必须根据当前 OnlyAlpha 产品语义明确区分。

如果系统当前不模拟提现，只需表达：

```text
trade_available_cash
withdrawable_cash
```

的扩展边界，不必完整实现提现。

## 8.5 T+0 市场

Generic T0：

```text
买入后资产立即可卖
卖出后资金立即可用于交易
```

用于验证：

```text
同一交易日买入后卖出
```

能够成功。

## 8.6 期货

期货不存在股票式证券交收，主要是：

```text
Position 更新
Margin 更新
PnL 结算
Daily Settlement
```

因此不能强行套用 A 股 Asset Settlement。

需要允许：

```text
settlement_model = FUTURES_DAILY_MARK_TO_MARK
```

---

# 九、Position Accounting Model

必须区分：

```text
LONG_ONLY
NETTING
HEDGING
```

## 9.1 LONG_ONLY

适用于基础 A 股现货：

```text
Position >= 0
不允许建立负持仓
```

## 9.2 NETTING

适用于部分美股、外汇、加密衍生品：

```text
买卖改变一个净头寸
正数表示 Long
负数表示 Short
```

## 9.3 HEDGING

适用于允许同时持有多空方向的期货或交易所模式：

```text
Long Position
Short Position
分别记录
```

建议：

```text
OnlyPositionMode.LONG_ONLY
OnlyPositionMode.NETTING
OnlyPositionMode.HEDGING
```

不得只通过 `quantity` 正负值隐式猜测全部语义。

---

# 十、Position Effect

通用 Position Effect 至少需要支持：

```text
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
REDUCE_ONLY
AUTO
```

A 股现货：

```text
BUY 通常增加 Long
SELL 通常减少 Long
```

期货：

```text
BUY OPEN
SELL OPEN
BUY CLOSE
SELL CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

加密永续：

```text
OPEN
REDUCE_ONLY
NETTING AUTO
```

如果当前 `OnlyPositionEffect` 不完整，应兼容扩展。

不得用 A 股 BUY/SELL 逻辑解释期货所有订单。

---

# 十一、Short Selling 与 Borrow

必须建立通用边界：

```text
OnlyShortSellingRule
OnlyBorrowAvailability
OnlyBorrowReservation
OnlyBorrowFeeModel
```

本任务不必完整实现真实融券，但必须支持：

```text
DISABLED
ENABLED_WITH_BORROW
ENABLED_UNRESTRICTED
```

A 股基础 Profile：

```text
short_selling = DISABLED
```

Generic Margin Profile：

```text
short_selling = ENABLED_UNRESTRICTED
```

美股未来可扩展：

```text
Locate
Easy-to-Borrow
Hard-to-Borrow
Borrow Rate
Recall
```

结果框架预留：

```text
borrow_quantity
borrow_fee
short_rejection_reason
```

---

# 十二、Margin Model

必须建立通用保证金边界，不要求本任务完整实现生产级强平。

核心类型：

```text
OnlyMarginModel
OnlyMarginRequirement
OnlyMarginState
OnlyCollateralState
OnlyLiquidationRule
```

至少表达：

```text
initial_margin
maintenance_margin
available_margin
used_margin
margin_ratio
leverage
collateral
```

## 12.1 Cash Account

A 股基础账户：

```text
margin_model = None
或 OnlyCashAccountMarginModel
```

禁止透支。

## 12.2 Generic Futures

实现最小验证模型：

```text
initial_margin = notional × initial_margin_rate
maintenance_margin = notional × maintenance_margin_rate
```

支持：

```text
Long
Short
Contract Multiplier
```

## 12.3 Crypto Perpetual 扩展

预留：

```text
Cross Margin
Isolated Margin
Mark Price
Liquidation Price
Funding
Inverse Contract
Linear Contract
```

本任务不需全部实现，但领域模型不能阻止后续接入。

---

# 十三、Trading Session Model

必须支持：

```text
单 Session
多 Session
午间休市
跨午夜 Session
24×7
盘前
正常交易
盘后
集合竞价
不可交易阶段
```

核心类型：

```text
OnlyTradingPhase
OnlyTradingSessionDefinition
OnlyTradingSessionModel
OnlyTradingSessionState
```

`OnlyTradingPhase` 至少支持：

```text
PRE_OPEN
OPENING_AUCTION
CONTINUOUS
MIDDAY_BREAK
CLOSING_AUCTION
POST_MARKET
CLOSED
```

## 13.1 A 股

至少能够表达：

```text
开盘前
上午连续交易
午间休市
下午连续交易
收盘
```

当前日线策略在 Session Close 决策的兼容语义必须保留。

## 13.2 港股

架构应能表达：

```text
午间休市
不同交易阶段
```

## 13.3 美股

架构应能表达：

```text
Pre-Market
Regular
After-Hours
```

## 13.4 中国期货

必须支持跨午夜：

```text
Night Session
Day Session
同一 Trading Day 映射
```

不能使用自然日期作为唯一交易日依据。

## 13.5 Crypto

支持：

```text
24×7 CONTINUOUS
```

但仍应有：

```text
maintenance window
exchange outage
```

扩展能力。

---

# 十四、Instrument Reference

实现或扩展：

```text
OnlyInstrumentReferenceSnapshot
OnlyInstrumentReferenceProvider
OnlyInstrumentReferenceRepository
```

通用字段至少包括：

```text
instrument_id
asset_class
venue
market_profile_id
currency
base_currency
quote_currency
settlement_currency

listing_time
delisting_time
status

price_precision
quantity_precision
tick_size
quantity_step
minimum_quantity
maximum_quantity
minimum_notional
maximum_notional
lot_size

contract_multiplier
contract_type
expiry
settlement_type
margin_currency

board
st_status
trading_calendar_id

effective_from
effective_to
source
source_version
content_fingerprint
```

字段根据资产类型可为空，但语义必须明确。

禁止用股票代码前缀代替正式 Reference。

---

# 十五、价格规则

通用价格规则需要支持：

```text
Tick Size
Dynamic Tick Table
Price Precision
Price Bands
Daily Price Limit
Circuit Breaker
Minimum / Maximum Price
```

核心类型：

```text
OnlyPriceRule
OnlyTickSizeRule
OnlyPriceBandRule
OnlyPriceLimitRule
OnlyCircuitBreakerRule
```

A 股第一阶段正式支持：

```text
主板普通股票 10%
ST / *ST 5%
创业板 20%
科创板 20%
```

但实现必须以 Profile + Reference 驱动。

未来市场：

```text
美股：
    无 A 股式固定日涨跌停
    有 LULD / Circuit Breaker 扩展

港股：
    不同价格档位 Tick Table
    VCM 扩展

期货：
    合约每日涨跌停
    可能随交易日动态变化

Crypto：
    通常无固定日涨跌停
    有 Exchange Price Protection
```

不得把 `limit_up` 和 `limit_down` 作为所有市场都必须存在的非空字段。

---

# 十六、数量规则

核心类型：

```text
OnlyQuantityRule
OnlyLotSizeRule
OnlyQuantityStepRule
OnlyMinimumNotionalRule
OnlyOddLotRule
```

必须支持：

```text
固定 Lot
每个 Instrument 不同 Lot
可碎股
不可碎股
数量步长
最小名义金额
```

## 16.1 A 股

```text
买入按整手
卖出允许符合规则的零股清仓
```

## 16.2 港股

Board Lot 必须来自每个 Instrument Reference，不能写死为统一数值。

## 16.3 美股

支持碎股扩展：

```text
quantity_precision > 0
lot_size 不必为整数股
```

## 16.4 Crypto

通常使用：

```text
quantity_step
minimum_quantity
minimum_notional
```

## 16.5 Futures

通常：

```text
整数合约
quantity_step = 1 contract
```

---

# 十七、Fee Model

核心模型必须支持多种计费维度：

```text
按成交额比例
按成交数量
按合约张数
最低费用
固定费用
买卖方向差异
Maker / Taker
开仓 / 平仓差异
平今 / 平昨差异
交易所费用
监管费用
印花税
过户费
借券费
Funding
```

核心类型：

```text
OnlyFeeModel
OnlyFeeSchedule
OnlyFeeRule
OnlyFeeCalculationContext
OnlyFeeBreakdown
OnlyOrderFeeAccumulator
```

`OnlyFeeBreakdown` 至少包含通用结构：

```text
commission
exchange_fee
clearing_fee
regulatory_fee
tax
transfer_fee
borrow_fee
funding_fee
other_fee
total_fee
currency
rule_version
components
```

其中 `components` 应允许扩展，但标准核心字段仍需稳定。

## 17.1 A 股正式支持

```text
佣金
最低佣金
卖出印花税
过户费
```

## 17.2 美股预留

```text
Commission
SEC Fee
TAF
Exchange Fee
Liquidity Rebate / Fee
```

## 17.3 港股预留

```text
Broker Commission
Stamp Duty
Trading Fee
Transaction Levy
Settlement Fee
```

## 17.4 Futures 预留

```text
Per Contract Fee
OPEN
CLOSE
CLOSE_TODAY
CLOSE_YESTERDAY
```

## 17.5 Crypto

```text
Maker Fee
Taker Fee
Fee Tier
Fee Currency
Funding Fee
```

费用必须基于 Execution，而非 Order Request。

最低佣金不能对每个部分成交重复收取。

---

# 十八、Liquidity Model

通用流动性模型必须支持：

```text
Unlimited
Bar Volume Participation
Tick Liquidity
Order Book
Exchange Reported Fill
```

核心类型：

```text
OnlyLiquidityModel
OnlyLiquidityState
OnlyLiquidityDecision
OnlyBarLiquidityState
```

第一阶段实现：

```text
UNLIMITED
BAR_VOLUME_PARTICIPATION
```

必须支持同一 Instrument、同一 Bar 内多个订单共享流动性。

不得每个订单都独立使用完整 Bar Volume。

## 18.1 不同资产的 Volume 语义

必须确认：

```text
股票 volume = 股数还是手数
期货 volume = 单边还是双边口径、合约张数
Crypto volume = Base Asset 还是 Quote Asset
```

标准化后才能进入 Liquidity Model。

不能把不同数据源 Volume 直接当同一种单位。

Reference 或 Bar Metadata 必须明确：

```text
volume_unit
```

---

# 十九、Slippage Model

支持：

```text
NONE
FIXED_TICKS
BASIS_POINTS
VOLUME_IMPACT
```

第一阶段实现前三个。

滑点结果：

```text
reference_price
raw_slippage_price
final_execution_price
slippage_amount
slippage_cost
clamped
```

滑点后必须重新验证：

```text
Tick Size
Price Band
Daily Limit
Order Limit Price
```

不同市场价格保护由 Profile 决定。

---

# 二十、Matching Model

Matching Model 与 Market Profile 分离。

核心类型：

```text
OnlyMatchingModel
OnlyMatchingContext
OnlyMatchDecision
OnlyMatchOutcome
OnlyUnfilledReason
```

首批支持：

```text
NEXT_BAR_OPEN
NEXT_BAR_CLOSE
BAR_TOUCH
```

当前正式兼容：

```text
NEXT_BAR_OPEN
```

未来扩展：

```text
Tick
Order Book
Exchange Native Fill
```

不得在通用 Broker 中假设所有市场都是 Next-Bar。

---

# 二十一、Pre-Trade 与 Match-Time 边界

## 21.1 Pre-Trade Validation

只能使用当前已知信息：

```text
Instrument 是否存在
当前交易阶段
订单类型是否合法
价格是否合法
数量是否合法
Short Selling 是否允许
可用持仓
可用资金
Margin
Settlement Availability
T+1
```

## 21.2 Match-Time Validation

可以使用当前撮合 Bar/Tick：

```text
实际成交参考价格
价格带
涨跌停锁定
流动性
滑点
订单剩余数量
```

禁止 Risk 使用未来 Bar。

---

# 二十二、A 股正式 Profile

实现：

```text
OnlyCnAShareCashMarketProfile
```

或者由通用配置构造：

```text
CN_A_SHARE_CASH
```

至少支持：

```text
Long-only
禁止普通裸卖空
证券 T+1 可卖
现金账户
交易日历
日间 Session
停牌
主板 10%
ST 5%
创业板 20%
科创板 20%
整手买入
零股清仓
佣金
最低佣金
卖出印花税
过户费
Bar Volume Participation
Next-Bar Open
```

必须明确本阶段未完整覆盖：

```text
新股上市初期特殊价格规则
退市整理期
北交所
可转债
融资融券
集合竞价详细撮合
盘中临时停牌
历史所有税费版本
```

遇到未覆盖规则时：

```text
严格模式返回明确错误或 Warning
不得静默套用普通主板规则
```

---

# 二十三、Generic T0 Profile

实现测试用途：

```text
GENERIC_T0_CASH
```

语义：

```text
24 小时或简单日间 Session
Long-only
买入后立即可卖
卖出资金立即可交易
无涨跌停
可配置 Lot
简单比例 Fee
```

用途：

```text
验证 Settlement 不是写死 T+1
验证同一 Trading Day 买入后卖出
```

---

# 二十四、Generic Futures Profile

实现最小测试用途：

```text
GENERIC_MARGIN_FUTURES
```

至少支持：

```text
Long / Short
OPEN / CLOSE
NETTING 或 HEDGING 中至少一种
Contract Multiplier
Initial Margin
Maintenance Margin
Per-Contract Fee
T+0
Daily Session
```

不要求本阶段实现完整强平，但必须计算：

```text
used_margin
available_margin
```

并在保证金不足时拒绝开仓。

---

# 二十五、Generic Crypto Spot Profile

实现测试用途：

```text
GENERIC_24X7_CRYPTO_SPOT
```

至少支持：

```text
24×7
T+0
Base / Quote Currency
Quantity Step
Minimum Notional
Maker / Taker Fee 结构
无固定日涨跌停
```

当前 Bar 撮合可以统一使用 Taker Fee。

用于证明：

```text
Calendar 不依赖交易日休市
Quantity 不依赖整数股
Fee 不依赖证券税费
```

---

# 二十六、Virtual Broker 重构

推荐流程：

```text
receive market event
    ↓
resolve Instrument Reference
    ↓
resolve Market Profile
    ↓
resolve Effective Rules
    ↓
resolve Session / Trading Phase
    ↓
build Liquidity State
    ↓
select due orders by stable sequence
    ↓
for each order:
    validate tradability
    validate settlement availability
    validate position mode
    validate short / margin
    validate quantity
    validate price
    evaluate price protection
    allocate liquidity
    calculate partial fill
    apply slippage
    calculate fee
    emit Broker Updates
    emit Rule Decision Facts
```

Broker 不直接修改：

```text
Position
Ledger
Account
Settlement State
Margin State
```

仍由 ExecutionProcessor 或专门的正式状态处理器更新。

如需新增：

```text
OnlySettlementProcessor
OnlyMarginProcessor
```

必须明确执行顺序和不变量。

---

# 二十七、ExecutionProcessor 扩展

ExecutionProcessor 需要能够消费：

```text
Position Side
Position Effect
Settlement Instructions
Margin Changes
Fee Breakdown
```

建议处理顺序：

```text
Broker Execution
    ↓
Order State
    ↓
Position Accounting
    ↓
Settlement State
    ↓
Margin State
    ↓
Allocation
    ↓
Strategy Ledger
    ↓
Account
    ↓
Invariants
    ↓
Facts
```

必须避免：

```text
部分成交释放全部 Reservation
平仓错误使用其他订单 Reservation
期货 Short 被当成股票负持仓错误
T+1 与 T+0 共用同一个 available_quantity 更新逻辑
```

---

# 二十八、Results Framework 集成

扩展现有标准事实，不建立新结果框架。

## 28.1 Order Record

至少增加：

```text
market_profile_id
market_profile_version
position_side
position_effect
settlement_model_id
margin_model_id
validation_decisions
```

## 28.2 Execution Record

增加：

```text
position_side
position_effect
reference_price
execution_price
contract_multiplier
notional
fee_breakdown
slippage
liquidity
market_profile_id
rule_set_id
settlement_instruction_id
margin_change
```

## 28.3 Settlement Record

新增：

```text
OnlySettlementResultRecord
```

至少包含：

```text
sequence
account_id
instrument_id
execution_id
asset_quantity
cash_amount
trade_time
asset_available_time
cash_available_time
settlement_time
status
settlement_model_id
```

输出：

```text
settlements.parquet
```

## 28.4 Margin Record

新增可选：

```text
OnlyMarginResultRecord
```

至少包含：

```text
sequence
account_id
instrument_id
position_side
initial_margin
maintenance_margin
used_margin
available_margin
margin_ratio
```

输出：

```text
margin.parquet
```

Cash Profile 可生成零行稳定 Schema。

## 28.5 Market Rule Decision

继续使用：

```text
market_rule_decisions.parquet
```

## 28.6 Fee Analytics

按通用 Component 汇总：

```text
commission
tax
exchange_fee
clearing_fee
regulatory_fee
transfer_fee
borrow_fee
funding_fee
other_fee
total_fee
```

---

# 二十九、Fingerprint

必须把以下稳定身份纳入结果指纹：

```text
Instrument Reference Identity
Market Profile Identity
Effective Rule Set
Session Model
Settlement Model
Position Mode
Short Selling Rule
Margin Model
Fee Schedule
Liquidity Model
Slippage Model
Matching Model
```

修改以下任意配置必须导致结果指纹变化：

```text
T+0 / T+1
Position Mode
Margin Rate
Fee Rate
Lot Size
Minimum Notional
Price Limit
Trading Session
Participation Rate
Slippage
Maker / Taker
```

仍然排除：

```text
run_id
墙钟时间
绝对路径
PID
hostname
traceback
```

---

# 三十、配置模型

建议：

```yaml
market_simulation:
  enabled: true

  profile:
    id: CN_A_SHARE_CASH
    version: "2025.1"

  reference:
    provider: static
    strict: true

  matching:
    model: NEXT_BAR_OPEN

  liquidity:
    model: BAR_VOLUME_PARTICIPATION
    maximum_participation_rate: "0.10"

  slippage:
    model: FIXED_TICKS
    ticks: 1

  settlement:
    override: null

  fees:
    schedule: CN_A_SHARE_2025
```

Generic Futures 示例：

```yaml
market_simulation:
  profile:
    id: GENERIC_MARGIN_FUTURES

  margin:
    initial_rate: "0.10"
    maintenance_rate: "0.08"

  position:
    mode: HEDGING
```

Generic Crypto 示例：

```yaml
market_simulation:
  profile:
    id: GENERIC_24X7_CRYPTO_SPOT

  fees:
    maker_rate: "0.0002"
    taker_rate: "0.0005"

  quantity:
    minimum_notional: "10"
```

所有 Decimal 以字符串配置。

---

# 三十一、测试矩阵

必须增加以下测试。

## 31.1 T+1

```text
A 股 T 日买入
总持仓增加
可卖数量不增加
T 日卖出拒绝
T+1 可卖
```

## 31.2 T+0

```text
Generic T0 T 日买入
同日卖出成功
```

两者使用相同通用 Position/Settlement 基础类型。

## 31.3 24×7

```text
Crypto 周末和自然日边界仍可交易
不依赖传统 Trading Day 休市
```

## 31.4 跨午夜 Session

```text
期货夜盘属于正确 Trading Day
```

## 31.5 Long / Short

```text
Futures SELL OPEN 建立 Short
BUY CLOSE 平 Short
```

不能触发股票式 oversell。

## 31.6 Netting / Hedging

如果本任务实现 HEDGING：

```text
同时持有 Long 和 Short
```

如果只实现 NETTING：

```text
反向成交正确减少、平仓和反手
```

必须明确当前完成哪种。

## 31.7 Margin

```text
保证金充足时开仓
保证金不足时拒绝
平仓释放保证金
```

## 31.8 Contract Multiplier

验证期货：

```text
notional = price × quantity × multiplier
```

全部使用 Decimal。

## 31.9 Fractional Quantity

Crypto 或美股 Generic：

```text
0.001 数量合法
```

A 股：

```text
0.001 股非法
```

## 31.10 Minimum Notional

Crypto：

```text
订单名义金额低于最小值时拒绝
```

## 31.11 Board Lot

港股式测试 Profile：

```text
Instrument A lot=100
Instrument B lot=500
```

证明 Lot 来自 Reference。

## 31.12 A 股规则

覆盖：

```text
主板
ST
创业板
科创板
涨停买入
跌停卖出
停牌
整手
零股
费用
```

## 31.13 Partial Fill

```text
一个订单跨多个 Bar 成交
Reservation / Margin / Settlement 正确
```

## 31.14 Fee Model

覆盖：

```text
A 股税费
每张合约费用
Maker/Taker 结构
最低佣金累计
```

## 31.15 Result / Artifact

验证：

```text
settlements.parquet
margin.parquet
market_rule_decisions.parquet
```

稳定 Schema。

## 31.16 Fingerprint

不同 Profile、Settlement 或 Margin 配置必须得到不同指纹。

相同配置重复运行必须一致。

---

# 三十二、确定性示例

新增：

```text
OnlyAlpha-examples/examples/market_profiles/
```

至少包含：

```text
cn_a_share_t1/
generic_t0_cash/
generic_futures_margin/
generic_crypto_spot_24x7/
```

全部通过：

```text
onlyalpha run
```

执行。

不得绕过正式 Engine。

每个示例 README 必须说明：

```text
市场 Profile
Session
Settlement
Position Mode
Fee
Quantity Rule
Matching Model
预期结果
```

---

# 三十三、真实 Tushare 验收

更新：

```text
OnlyAlpha-examples/examples/tushare_daily_backtest/
```

显式使用：

```text
CN_A_SHARE_CASH
```

在线和 CACHE_ONLY 配置除：

```text
Token
Cache Policy
```

外必须完全一致。

验证：

```text
Bars
Signals
Orders
Executions
Trades
Settlements
Fees
Positions
Available Quantity
Ending Equity
Rule Decisions
Result Fingerprint
Analysis Fingerprint
Artifact Content Fingerprint
```

全部一致。

如果在线服务不可用：

```text
使用已有 Cache
不得虚构在线结果
```

---

# 三十四、兼容性

不得破坏：

```text
现有 A 股 Tushare 回测
现有 MiniQMT
现有 Historical Cache
现有 Strategy API
现有 Results Framework
现有 CLI JSON
现有 Artifact
现有 Fingerprint
```

旧配置未声明 Profile 时：

```text
保持 Legacy 模式
```

或映射到明确：

```text
LEGACY_CASH_NEXT_BAR
```

不得静默改变既有测试结果。

---

# 三十五、禁止事项

禁止：

```text
把所有市场都抽象成股票
把所有 Position 都设计为 Long-only
把 T+1 设计成 Position 的固定布尔字段
把交易日等同自然日期
把期货 Short 当成负股票
把 Crypto 24×7 强行放入工作日 Calendar
把港股 Board Lot 写死为 100
把美股默认禁止碎股写死在核心
把期货手续费强行按成交额比例计算
把 Maker/Taker 写入通用 Order Side
把 Margin 状态塞入 CashBalance 的任意字段
把 Settlement 和 Availability 混为一个时间
把所有市场都要求 limit_up / limit_down
把所有市场都要求整数 Quantity
把所有费用转为一个 commission 字段后丢失组成
```

---

# 三十六、文档要求

新增：

```text
docs/market_simulation_framework.md
docs/market_profiles.md
docs/settlement_model.md
docs/position_modes.md
docs/margin_model.md
docs/trading_sessions.md
docs/multi_market_fees.md
docs/a_share_market_profile.md
docs/adr/xxxx-multi-market-simulation-framework.md
```

文档必须包含市场能力矩阵：

```text
能力                 A股   港股   美股   期货   Crypto Spot   Perpetual
T+0/T+1
Long
Short
Netting
Hedging
Margin
24×7
Multi-session
Fractional Qty
Lot Size
Minimum Notional
Price Limit
Maker/Taker
Funding
```

明确：

```text
当前正式实现
当前仅有接口
未来扩展
```

不得把预留能力写成已经完成。

---

# 三十七、路线图更新

本任务完成后：

```text
Phase 2C：A 股市场规则
```

可标记：

```text
A 股基础 Profile 已完成
```

同时新增：

```text
Multi-Market Simulation Foundation
```

标记：

```text
核心抽象和 Generic Profile 验证完成
```

但不得声称：

```text
港股正式支持
美股正式支持
期货正式生产可用
加密永续正式支持
```

因为本任务只要求这些市场驱动架构设计，并通过最小 Generic Profile 验证边界。

---

# 三十八、实施顺序

严格分阶段进行。

## Stage 1：现状审计

```text
Position
T+1
Account
Margin
Future
Crypto
Calendar
Broker
Results
```

## Stage 2：ADR 和能力矩阵

先确定：

```text
Market Profile
Settlement
Position Mode
Margin
Session
```

边界。

## Stage 3：核心领域模型

实现：

```text
OnlyMarketProfile
OnlySettlementModel
OnlyPositionMode
OnlyMarginModel
OnlyTradingSessionModel
```

## Stage 4：Generic Profiles

实现：

```text
GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT
```

通过测试证明没有 A 股硬编码。

## Stage 5：A 股 Profile

实现完整基础规则。

## Stage 6：Virtual Broker 和 ExecutionProcessor

完成规则编排和正式状态更新。

## Stage 7：Results Framework

接入：

```text
Settlement
Margin
Rule Decisions
Fee Components
```

## Stage 8：Examples

四类 Profile 正式运行。

## Stage 9：Tushare

在线与 CACHE_ONLY 验收。

## Stage 10：文档和门禁

---

# 三十九、质量门禁

执行：

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

不得虚构跨平台验证结果。

---

# 四十、完成标准

以下全部完成才算任务完成：

```text
多市场 Market Profile 抽象
Settlement Model
T+0 / T+1 / T+N 能力
资产可用与法律结算分离
Position LONG_ONLY / NETTING / HEDGING 边界
Short Selling Rule
Margin Model
多 Session / 跨午夜 / 24×7 Session Model
通用 Price / Quantity / Fee / Liquidity / Slippage / Matching

GENERIC_T0_CASH
GENERIC_MARGIN_FUTURES
GENERIC_24X7_CRYPTO_SPOT

CN_A_SHARE_CASH 正式 Profile
A 股停牌
涨跌停
整手
零股
费用
T+1

Virtual Broker 集成
ExecutionProcessor 集成
Reservation / Settlement / Margin 不变量

Settlement Result Records
Margin Result Records
Market Rule Decision Records
Artifact 和 Fingerprint 扩展

四类确定性示例
Tushare 在线/CACHE_ONLY
测试
文档
ADR
HANDOFF
ROADMAP
```

---

# 四十一、最终报告格式

完成后输出中文报告。

## 1. 修改前审计

说明当前系统中的 A 股假设和多市场缺口。

## 2. 能力矩阵

对比：

```text
A 股
港股
美股
期货
Crypto Spot
Perpetual
```

标明：

```text
已实现
Generic 验证
仅预留
```

## 3. Market Profile

说明 Profile 解析、版本和指纹。

## 4. Settlement

说明：

```text
T+0
T+1
T+N
Asset Availability
Cash Availability
Legal Settlement
```

## 5. Position 与 Short

说明：

```text
LONG_ONLY
NETTING
HEDGING
Borrow
```

## 6. Margin

说明 Cash、Futures 和 Perpetual 的扩展边界。

## 7. Trading Session

说明多 Session、跨午夜和 24×7。

## 8. Price / Quantity / Fee

说明不同市场如何使用同一通用接口。

## 9. Broker 与 ExecutionProcessor

说明正式处理顺序和不变量。

## 10. Results Framework

说明 Settlement、Margin 和 Rule Decision 输出。

## 11. A 股 Profile

说明本阶段实际完成的规则和未覆盖规则。

## 12. Generic Profile 验收

列出 T0、Futures、Crypto 的真实测试结果。

## 13. Tushare 验收

列出在线和 CACHE_ONLY 结果及指纹。

## 14. 质量门禁

列出真实命令和结果。

## 15. 未完成项

不得把接口预留写成正式市场支持。

---

# 四十二、最终目标

最终目标是：

> 以 A 股作为第一个正式市场 Profile，建立一个不被 A 股 T+1、整手、涨跌停和税费规则绑定的多市场仿真内核，使 OnlyAlpha 能够在同一组领域边界下表达 T+0、T+1、现货、卖空、保证金、多空双向、跨午夜交易时段和 24×7 市场，并为港股、美股、期货、加密货币和后续期权提供可验证的长期架构基础。
