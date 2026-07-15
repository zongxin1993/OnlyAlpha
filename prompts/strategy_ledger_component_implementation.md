# OnlyAlpha StrategyLedgerManager 策略资金、收益、费用与净值归因组件实现任务

## 1. 任务目标

现在开始实现 OnlyAlpha 的 `StrategyLedgerManager` 及相关策略归因账组件。

当前工程已经确定采用双层持仓模型：

```text
OnlyPositionManager
    维护账户真实持仓

OnlyPositionAllocationManager
    维护各 Cluster 的持仓归因
```

本阶段需要在此基础上继续建立：

```text
OnlyStrategyLedgerManager
    维护各 Cluster 的虚拟资金、费用、收益、净值和资金占用
```

必须明确：

```text
券商真实账户账
    ≠
策略内部虚拟账
```

策略 Ledger 用于解决多个 Cluster 共用同一个券商账户时的：

* 初始资金分配；
* 虚拟现金；
* 订单资金预占；
* 成交现金流；
* 持仓市值；
* 已实现盈亏；
* 未实现盈亏；
* 手续费；
* 策略净值；
* 策略收益率；
* 高水位；
* 回撤；
* 策略级风险输入；
* 策略级绩效归因；
* 多策略收益独立计算。

本阶段最终需要建立：

```text
OnlyRuntime
├── OnlyPositionManager
├── OnlyPositionAllocationManager
└── OnlyStrategyLedgerManager
    ├── Cluster A Ledger
    ├── Cluster B Ledger
    └── Cluster C Ledger
```

每个 Cluster 必须有独立 Ledger。

策略只能通过只读：

```python
ctx.ledger
```

访问自身 Ledger Snapshot。

策略不得直接修改：

* 虚拟现金；
* 初始资金；
* 已实现盈亏；
* 未实现盈亏；
* 手续费；
* 净值；
* 预占资金；
* 外部现金流；
* 高水位；
* 回撤。

---

## 2. 核心设计原则

必须遵循：

```text
账户真实资金与策略虚拟资金分离

账户真实 Position 与 Cluster Allocation 分离

策略收益必须根据自身 Trade、Allocation 和费用计算

不得根据账户总收益按比例事后分配策略收益

每个 Runtime 拥有独立 StrategyLedgerManager

每个 Cluster 拥有独立 Strategy Ledger

Ledger 修改使用函数调用

Ledger Event 只表达已经发生的事实

EventBus 不驱动 Ledger 强顺序更新

策略只能读取 immutable Ledger Snapshot

策略不能直接修改 Ledger

回测、Paper 和 Live 使用相同 Ledger API

同一输入必须得到确定性结果
```

本阶段的主要关系：

```text
Trade
    ↓
PositionAllocationManager
    ↓
StrategyLedgerManager
    ↓
OnlyStrategyLedgerSnapshot
```

未来完整链路：

```text
OnlyExecutionProcessor
    1. OrderManager.apply_fill()
    2. PositionManager.apply_trade()
    3. PositionAllocationManager.apply_trade()
    4. StrategyLedgerManager.apply_trade()
    5. AccountManager.apply_trade()
    6. RiskService.consume_or_release_reservation()
    7. 发布事实 Event
```

当前阶段不实现完整 `OnlyExecutionProcessor`，但所有接口必须可以被它明确调用。

---

## 3. 本阶段实现范围

本阶段需要实现或完善：

```text
OnlyStrategyLedger
OnlyStrategyLedgerId
OnlyStrategyLedgerKey
OnlyStrategyLedgerStatus
OnlyStrategyLedgerManager

OnlyStrategyCapitalConfig
OnlyStrategyCapitalAllocationMode
OnlyStrategyCapitalAllocation
OnlyStrategyCapitalSnapshot

OnlyStrategyCashLedger
OnlyStrategyCashEntry
OnlyStrategyCashEntryId
OnlyStrategyCashEntryType

OnlyStrategyFeeLedger
OnlyStrategyFeeEntry
OnlyStrategyFeeType

OnlyStrategyPnLLedger
OnlyStrategyPnLSnapshot
OnlyStrategyEquitySnapshot
OnlyStrategyPerformanceSnapshot

OnlyStrategyLedgerSnapshot
OnlyStrategyLedgerMutationResult
OnlyStrategyLedgerQueryService
OnlyStrategyLedgerQueryView

OnlyStrategyCashReservation
OnlyStrategyCashReservationId
OnlyStrategyCashReservationState
OnlyStrategyCashReservationStage
OnlyStrategyCashReservationManager

OnlyStrategyValuationService
OnlyStrategyPerformanceService

OnlyStrategyLedgerEvent
OnlyStrategyLedgerEventPublisher

OnlyStrategyLedgerRepository
OnlyInMemoryStrategyLedgerRepository

OnlyStrategyLedgerRiskView
OnlyStrategyLedgerContextView
```

本阶段暂不完整实现：

* 完整 AccountManager；
* 券商真实现金账；
* 融资融券；
* 期货保证金；
* 期权保证金；
* 多币种账户；
* 外汇换算；
* 利息；
* 融资利息；
* 借券费用；
* Funding Rate；
* 分红；
* 红利税；
* 公司行动；
* 自动资金再平衡；
* 策略间资金转移；
* 真实券商账户同步；
* 完整 ExecutionProcessor；
* Web；
* 数据库具体实现。

但接口必须为这些能力保留清晰扩展点。

---

## 4. 执行前必须阅读

开始实现前必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/time_model.md
docs/clock.md
docs/event.md
docs/runtime_context.md
docs/runtime.md
docs/cluster.md
docs/order.md
docs/risk.md
docs/position.md
docs/testing.md
docs/coding_style.md
docs/architecture_principles.md
docs/adr/
```

重点检查当前已有：

```text
OnlyMoney
OnlyCurrency
OnlyPrice
OnlyQuantity
OnlyRate
OnlyPercentage

OnlyRuntimeId
OnlyClusterId
OnlyAccountId
OnlyInstrumentId
OnlyOrderId
OnlyTradeId

OnlyPositionSnapshot
OnlyPositionAllocationSnapshot
OnlyPositionAllocationManager
OnlyPositionValuation
OnlyRiskReservation
OnlyPositionReservation
OnlyOrderSnapshot
OnlyClockView
OnlyMarketDataSnapshot
```

同时分析旧工程：

```text
/home/zongxin/workspace/MyQuant
```

重点分析：

* 策略初始资金；
* 策略资金分配；
* 策略收益统计；
* 手续费统计；
* 已实现与未实现盈亏；
* 持仓市值；
* 策略净值；
* 策略收益率；
* 最大回撤；
* 多策略共享账户；
* 回测与实盘收益差异；
* 重启后的收益恢复；
* 资金预占；
* 撤单后的资金释放。

只参考行为，不直接复制旧架构。

---

## 5. 先创建差距分析

创建：

```text
docs/strategy_ledger_component_analysis.md
```

至少分析：

### 5.1 当前收益和资金模型

| 模块 | 当前职责 | 当前问题 | 目标类型 |
| -- | ---- | ---- | ---- |

### 5.2 当前资金更新链

画出：

```text
Order
→ Reservation
→ Trade
→ Position
→ Cash
→ PnL
→ Equity
→ Performance
```

检查：

* 是否将账户资金和策略资金混用；
* 是否按账户总收益比例分配策略收益；
* 是否根据账户平均成本计算策略收益；
* 是否手续费无法归属到 Cluster；
* 是否多个 Cluster 共用一个可变收益对象；
* 是否订单提交后没有资金预占；
* 是否撤单后没有释放；
* 是否同一 Trade 被重复计入；
* 是否回测和实盘使用两套收益公式；
* 是否净值计算缺少统一来源；
* 是否现金视图和 PnL 视图无法对账；
* 是否 Context 暴露可变 Ledger。

### 5.3 当前依赖

列出：

```text
Order
Trade
Position Allocation
Position Valuation
Market Data
Clock
Risk
Account
Currency
Fee
Cash Flow
```

标明：

* 已实现；
* 可复用；
* 需要定义 Port；
* 本阶段明确不支持。

完成分析后再开始修改代码。

---

## 6. 每个 Runtime 一个 StrategyLedgerManager

结构：

```text
OnlyEngine
├── OnlyLiveRuntime
│   └── OnlyStrategyLedgerManager
├── OnlyPaperRuntime
│   └── OnlyStrategyLedgerManager
└── OnlyBacktestRuntime
    └── OnlyStrategyLedgerManager
```

每个 Runtime 内：

```text
OnlyStrategyLedgerManager
├── Cluster A Ledger
├── Cluster B Ledger
└── Cluster C Ledger
```

禁止：

* Engine 使用一个全局可变 LedgerManager；
* 每个 Cluster 自己维护无法审计的普通资金变量；
* Runtime 之间共享 Ledger；
* Cluster 直接修改 Ledger；
* StrategyLedgerManager 修改券商真实账户状态。

---

## 7. Strategy Ledger 的定位

`OnlyStrategyLedger` 表示：

> 某个 Cluster 在某个 Runtime、Account 和 Base Currency 下的内部虚拟资金与收益账。

建议唯一键：

```text
runtime_id
account_id
cluster_id
base_currency
```

定义：

```text
OnlyStrategyLedgerKey
```

字段建议：

```text
runtime_id
account_id
cluster_id
base_currency
```

如果未来一个 Cluster 可操作多个账户，应为不同账户建立独立 Ledger，或增加显式 Portfolio Ledger 聚合层。

第一版建议：

```text
一个 Cluster
绑定一个默认 Account
对应一个 Strategy Ledger
```

---

## 8. Strategy Ledger 核心字段

建议 `OnlyStrategyLedger` 内部至少维护：

```text
ledger_id
runtime_id
account_id
cluster_id
base_currency
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

net_pnl
equity
high_water_mark
drawdown
maximum_drawdown

created_at
updated_at
valuation_time

version
last_trade_sequence
quality_flags
metadata
```

需要明确哪些是核心状态，哪些是派生状态。

建议核心可变状态：

```text
initial_capital
external_cash_flow
cash_balance
cash_reserved
realized_pnl
fees
high_water_mark
maximum_drawdown
```

建议派生或估值状态：

```text
cash_available
position_cost
position_market_value
unrealized_pnl
net_pnl
equity
drawdown
```

不要让多个可写字段互相失去一致性。

---

## 9. Ledger 内部可变与外部 Snapshot

采用：

> 内部受控可变实体，外部只暴露 immutable Snapshot。

禁止外部：

```python
ledger.cash_balance = ...
ledger.realized_pnl = ...
ledger.equity = ...
ledger.fees = ...
ledger.high_water_mark = ...
```

必须通过领域方法：

```python
ledger.apply_trade(...)
ledger.apply_fee(...)
ledger.reserve_cash(...)
ledger.release_cash(...)
ledger.consume_cash_reservation(...)
ledger.apply_external_cash_flow(...)
ledger.apply_valuation(...)
ledger.close(...)
```

所有修改返回：

```text
OnlyStrategyLedgerMutationResult
```

查询返回：

```text
OnlyStrategyLedgerSnapshot
```

---

## 10. 资金分配模式

定义：

```text
OnlyStrategyCapitalAllocationMode
├── FIXED_CAPITAL
├── EQUITY_PERCENTAGE
└── SHARED_POOL
```

第一版完整实现：

```text
FIXED_CAPITAL
```

### 10.1 FIXED_CAPITAL

Cluster 初始化时配置固定虚拟资金：

```yaml
clusters:
  - id: strategy_a
    capital_allocation:
      mode: FIXED_CAPITAL
      amount:
        value: "500000"
        currency: CNY
```

含义：

* 策略初始虚拟资金固定；
* 用于收益和风险归因；
* 不代表券商存在真实子账户；
* 不允许策略自行修改。

### 10.2 EQUITY_PERCENTAGE

预留：

```text
账户权益百分比分配
```

需要未来定义：

* 计算基准；
* 再平衡时点；
* 百分比变化；
* 多策略总比例约束。

本阶段只定义接口，不完整实现。

### 10.3 SHARED_POOL

预留：

```text
多个策略共享账户资金池
```

第一版不实现。

---

## 11. 初始资金与外部现金流

定义：

```text
OnlyStrategyCapitalAllocation
OnlyStrategyCapitalSnapshot
OnlyStrategyCashFlow
```

必须区分：

```text
initial_capital
external_cash_flow
trading_pnl
```

外部现金流可能包括：

```text
DEPOSIT
WITHDRAWAL
CAPITAL_ALLOCATION_INCREASE
CAPITAL_ALLOCATION_DECREASE
MANUAL_ADJUSTMENT
```

第一版只完整支持：

```text
INITIAL_ALLOCATION
MANUAL_ADJUSTMENT
```

但手工调整必须：

* 由 Runtime 管理接口调用；
* 有审计；
* 不能由策略调用；
* 不计入交易收益；
* 影响收益率计算基准时必须有明确公式。

---

## 12. 策略现金账

定义：

```text
OnlyStrategyCashLedger
OnlyStrategyCashEntry
OnlyStrategyCashEntryId
OnlyStrategyCashEntryType
```

现金 Entry 类型至少：

```text
INITIAL_ALLOCATION
ORDER_RESERVATION
ORDER_RESERVATION_RELEASE
BUY_SETTLEMENT
SELL_SETTLEMENT
FEE
EXTERNAL_DEPOSIT
EXTERNAL_WITHDRAWAL
MANUAL_ADJUSTMENT
```

本阶段完整支持：

```text
INITIAL_ALLOCATION
ORDER_RESERVATION
ORDER_RESERVATION_RELEASE
BUY_SETTLEMENT
SELL_SETTLEMENT
FEE
MANUAL_ADJUSTMENT
```

每个 Entry 必须包含：

```text
entry_id
runtime_id
account_id
cluster_id
currency
amount
entry_type

order_id
trade_id
reservation_id

ts_event
ts_init
sequence
correlation_id
causation_id
metadata
```

现金账必须可重放。

---

## 13. 现金余额语义

第一版 Long-only 股票/ETF 中：

```text
cash_balance
    策略内部虚拟现金余额

cash_reserved
    已为未完成订单预占的虚拟现金

cash_available
    cash_balance - cash_reserved
```

要求：

```text
cash_available >= 0
```

除非未来显式支持融资。

第一版不允许：

```text
negative cash
```

资金不足应由 Risk 提前拒绝，但 Ledger 仍必须保护底层不变量。

---

## 14. 策略现金预占

定义：

```text
OnlyStrategyCashReservation
OnlyStrategyCashReservationId
OnlyStrategyCashReservationState
OnlyStrategyCashReservationStage
OnlyStrategyCashReservationManager
```

用途：

* 买入订单通过 Risk 后立即预占虚拟现金；
* 避免同一个 `on_bar` 内连续订单超额；
* 撤单、拒单、过期、失败后释放；
* 成交时按成交金额和费用消费。

建议 Reservation 字段：

```text
reservation_id
runtime_id
account_id
cluster_id
order_id
currency

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

状态：

```text
ACTIVE
PARTIALLY_CONSUMED
CONSUMED
RELEASED
FAILED
```

Stage 可以复用执行阶段：

```text
LOCAL_ONLY
SENT_TO_BROKER
BROKER_ACKNOWLEDGED
RELEASE_PENDING
RELEASED
```

---

## 15. Reservation 创建时点

推荐完整链：

```text
ctx.orders.submit()
→ Risk ACCEPT
→ 创建 OnlyOrder
→ 创建 Risk Reservation
→ 创建 Position Reservation（卖单）
→ 创建 Strategy Cash Reservation（买单）
→ ExecutionService
```

第一版 Strategy Cash Reservation 重点支持买单。

同一回调内：

```text
初始可用资金 100000

订单 A 60000
→ 通过
→ 预占 60000

订单 B 60000
→ 可用仅剩 40000
→ Risk 拒绝
```

必须完整测试。

---

## 16. Trade 输入

定义或复用标准化：

```text
OnlyTrade
```

StrategyLedgerManager 不接受：

* 券商原始结构；
* 普通字典；
* 裸 float；
* 无 Cluster 归属的模糊成交。

至少需要：

```text
trade_id
venue_trade_id
order_id
cluster_id
runtime_id
account_id
instrument_id

side
position_side
offset

price
quantity
fee

trade_currency
fee_currency

ts_event
ts_init
external_sequence
metadata
```

如果 `cluster_id` 缺失，应通过：

```text
order_id
→ OrderManager
→ OrderSnapshot.cluster_id
```

恢复。

无法恢复归属的 Trade：

* 不得计入任意 Cluster Ledger；
* 必须进入未来 Account/Unallocated Ledger；
* 当前阶段返回明确错误或 Unallocated 结果。

---

## 17. 买入成交更新

第一版 Long-only 股票/ETF：

```text
买入成交
```

需要更新：

```text
消费 Strategy Cash Reservation
减少 cash_balance
增加 Position Allocation 成本
记录 fee
更新 unrealized/realized 相关输入
更新 Ledger version
```

推荐现金流：

```text
cash_outflow
=
trade_notional
+
fee
```

其中：

```text
trade_notional
=
price × quantity × multiplier
```

必须使用精确金融数值。

如果手续费币种和 Base Currency 不同：

* 第一版返回明确 `UNSUPPORTED_CURRENCY_CONVERSION`；
* 不得默认汇率为 1；
* 不得静默忽略费用。

---

## 18. 卖出成交更新

卖出成交需要：

```text
增加 cash_balance
记录 fee
读取 PositionAllocation 已实现盈亏
更新 realized_pnl
更新净值
释放或消费 Position Reservation
```

推荐现金流：

```text
cash_inflow
=
trade_notional
-
fee
```

StrategyLedger 不应重新独立计算 Position 成本。

已实现盈亏应来自：

```text
OnlyPositionAllocationMutationResult
```

或统一的成交处理结果。

这样避免 Position Allocation 和 Ledger 使用两套成本算法。

推荐输入：

```text
OnlyStrategyTradeAccountingInput
```

包含：

```text
trade
allocation_mutation
realized_pnl_delta
position_cost_delta
fee
cash_delta
```

---

## 19. Position Allocation 是策略成本权威

必须固定：

```text
OnlyPositionAllocation
    是策略持仓数量和持仓成本的权威来源

OnlyStrategyLedger
    是策略现金、费用、收益和净值的权威来源
```

StrategyLedger 不维护另一套独立可变平均持仓价。

Ledger 通过 `OnlyPositionAllocationSnapshot` 获取：

```text
quantity
average_open_price
realized_pnl
fees
```

避免双重真值。

---

## 20. 已实现盈亏

策略已实现盈亏必须来自自身 Allocation。

例如：

```text
Cluster A:
买入 100 @ 10
卖出 40 @ 12
```

已实现盈亏：

```text
(12 - 10) × 40 × multiplier
```

Cluster B 的成本不得影响 Cluster A。

`realized_pnl` 必须累计：

```text
realized_pnl += realized_pnl_delta
```

重复 Trade 不得重复累计。

---

## 21. 未实现盈亏

未实现盈亏基于：

```text
Cluster Position Allocation
+
最新 Mark Price
+
OnlyPnLModel
```

定义：

```text
OnlyStrategyValuationService
```

输入：

```text
OnlyPositionAllocationSnapshot[]
OnlyMarketDataSnapshot / Mark Price View
OnlyInstrumentView
OnlyPnLModel
```

输出：

```text
OnlyStrategyValuation
```

至少包含：

```text
cluster_id
ts_event
position_market_value
position_cost
unrealized_pnl
valuation_currency
price_versions
quality_flags
```

第一版只支持单 Base Currency、Linear PnL。

---

## 22. 净值计算

第一版必须同时支持两种视图。

### 22.1 Cash View

```text
equity
=
cash_balance
+
position_market_value
```

### 22.2 PnL View

```text
equity
=
initial_capital
+
external_cash_flow
+
realized_pnl
+
unrealized_pnl
-
fees
```

必须检查：

```text
equity_by_cash_view
==
equity_by_pnl_view
```

允许精度范围内误差，但必须使用金融精度而不是普通 float 误差。

如果不一致：

```text
Ledger → RECONCILING 或 ERROR
```

并生成明确差异。

不得静默选择其中一个值。

---

## 23. Net PnL

第一版定义：

```text
net_pnl
=
realized_pnl
+
unrealized_pnl
-
fees
```

未来扩展：

```text
+ dividends
+ funding
+ interest_income
- borrow_cost
- financing_interest
- taxes
```

本阶段不要把未实现项目写死为永远不存在，应保留扩展字段或 Adjustment Ledger。

---

## 24. 收益率

定义：

```text
OnlyStrategyReturnMethod
```

至少预留：

```text
SIMPLE_RETURN
TIME_WEIGHTED_RETURN
MONEY_WEIGHTED_RETURN
```

第一版完整实现：

```text
SIMPLE_RETURN
```

在无外部现金流情况下：

```text
return_since_start
=
(equity - initial_capital) / initial_capital
```

如果存在外部现金流：

* 必须明确第一版限制；
* 可以只输出 `return_since_start=None` 并标记 unsupported；
* 或使用调整后的简单收益；
* 不得错误套用未调整公式。

推荐第一版：

```text
无外部现金流
    支持 SIMPLE_RETURN

存在外部现金流
    标记需要 TWR/MWR，暂不输出误导值
```

---

## 25. 高水位与回撤

必须实现：

```text
high_water_mark
drawdown
maximum_drawdown
```

关系：

```text
high_water_mark
=
max(previous_high_water_mark, current_equity)
```

```text
drawdown
=
(current_equity - high_water_mark) / high_water_mark
```

```text
maximum_drawdown
=
min(previous_maximum_drawdown, current_drawdown)
```

注意：

* 回撤通常为零或负数；
* 必须明确项目统一符号语义；
* 或使用正数 drawdown magnitude，但全工程必须统一。

建议：

```text
drawdown <= 0
maximum_drawdown <= 0
```

并在文档中固定。

---

## 26. 日内盈亏

定义接口和字段：

```text
OnlyStrategyDailyPnL
OnlyStrategyTradingDaySnapshot
```

第一版可以实现：

```text
day_start_equity
current_equity
daily_pnl
daily_return
```

Trading Day 必须由：

```text
OnlyTradingCalendar
```

推导。

不得使用 UTC 日期直接划分交易日。

不同 Instrument 可能属于不同交易日语义。

第一版单市场 A 股可绑定 Cluster 主交易日 Calendar。

多市场 Cluster 需要未来 Portfolio Trading Day Policy。

---

## 27. 手续费归因

定义：

```text
OnlyStrategyFeeLedger
OnlyStrategyFeeEntry
OnlyStrategyFeeType
```

Fee 类型预留：

```text
COMMISSION
EXCHANGE_FEE
STAMP_DUTY
TRANSFER_FEE
REGULATORY_FEE
BROKER_FEE
BORROW_FEE
FINANCING_INTEREST
FUNDING_FEE
OTHER
```

第一版完整支持：

```text
COMMISSION
STAMP_DUTY
TRANSFER_FEE
OTHER
```

Trade 已能关联 Cluster 时，费用直接归入对应 Ledger。

禁止：

* 将多个 Cluster 费用平均分配；
* 忽略手续费；
* 将手续费隐式加入 Position 平均价；
* 重复 Trade 重复计费。

---

## 28. 多币种边界

Strategy Ledger 必须包含：

```text
base_currency
```

第一版只完整支持：

```text
所有 Trade、Fee、Position Valuation
均与 Ledger Base Currency 相同
```

如果币种不同：

```text
返回明确 UnsupportedCurrencyConversion
```

定义未来 Port：

```text
OnlyFxRateView
OnlyCurrencyConversionService
```

不得：

* 假设汇率为 1；
* 用裸 float 汇率；
* 静默丢弃外币费用；
* 把不同币种 Money 直接相加。

---

## 29. Strategy Ledger Status

定义：

```text
OnlyStrategyLedgerStatus
├── CREATED
├── ACTIVE
├── RECONCILING
├── SUSPENDED
├── CLOSED
└── ERROR
```

语义：

```text
CREATED
    已创建但尚未激活

ACTIVE
    可以正常更新和查询

RECONCILING
    现金、持仓或净值存在差异

SUSPENDED
    暂停交易和资金变更

CLOSED
    Ledger 已结束

ERROR
    状态损坏或无法安全更新
```

Ledger 为 `RECONCILING` 或 `ERROR` 时，Risk 应默认阻止新订单。

---

## 30. 幂等

必须按以下标识去重：

```text
trade_id
fee_entry_id
cash_entry_id
reservation_id
valuation_version
external_cash_flow_id
```

重复 Trade：

* cash 不变化；
* realized_pnl 不变化；
* fee 不变化；
* equity 不变化；
* version 不增加；
* 不生成 Event。

重复 Reservation 释放：

* 不重复增加 cash_available；
* version 不重复增加。

---

## 31. 乱序处理

第一版采用严格模式。

同 Cluster Ledger 更新顺序：

```text
external_sequence
→ ts_event
→ stable_id
```

发现旧 Trade 或旧 Cash Entry：

```text
STALE
RECONCILIATION_REQUIRED
```

第一版不自动重算完整 Ledger 历史。

回测输入必须有序。

实盘迟到数据未来通过 Ledger Replay/Reconciliation 修复。

---

## 32. Strategy Ledger Manager

定义：

```text
OnlyStrategyLedgerManager
```

职责：

* 创建 Ledger；
* 初始化资金；
* 注册 Cluster；
* 注销 Cluster；
* 处理 Trade Accounting；
* 处理 Fee；
* 创建和释放现金预占；
* 应用估值；
* 生成 Snapshot；
* 维护索引；
* 保证幂等；
* 保证 Runtime 和 Cluster Scope；
* 提供 Risk View；
* 提供 Context Query View；
* 生成 Mutation Result。

建议接口：

```python
create_ledger(...)
activate_ledger(...)
close_ledger(...)

apply_trade(...)
apply_fee(...)
apply_external_cash_flow(...)
apply_valuation(...)

reserve_cash(...)
release_cash_reservation(...)
consume_cash_reservation(...)

get_snapshot(...)
require_snapshot(...)
list_ledgers(...)
list_active_ledgers(...)
get_by_cluster(...)
```

---

## 33. Strategy Ledger Manager 不负责

不得负责：

* 创建 Order；
* 风控审批；
* 决定成交；
* 修改账户真实现金；
* 修改账户 Position；
* 修改 Position Allocation；
* 调用 Gateway；
* 查询券商；
* 修改 MarketData；
* 管理 Cluster 生命周期。

---

## 34. Strategy Accounting 输入

为了避免多个组件重复计算，建议定义：

```text
OnlyStrategyTradeAccountingInput
```

至少包含：

```text
trade
order_snapshot
position_allocation_before
position_allocation_after
position_allocation_mutation
realized_pnl_delta
position_cost_delta
fee_entries
cash_reservation
ts_event
sequence
```

这样 Ledger 不需要重新推断：

* Trade 属于哪个 Cluster；
* 成交是开仓还是平仓；
* 已实现盈亏是多少；
* Position 成本如何变化。

此对象未来由 `OnlyExecutionProcessor` 构造。

当前阶段由测试和 Demo 构造。

---

## 35. Strategy Equity Snapshot

定义不可变：

```text
OnlyStrategyEquitySnapshot
```

字段至少：

```text
runtime_id
account_id
cluster_id
base_currency

ts_event
ts_init
trading_day
version

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
net_pnl

equity
high_water_mark
drawdown
maximum_drawdown

return_since_start
daily_pnl
daily_return

quality_flags
metadata
```

必须可序列化和可比较。

---

## 36. Strategy Performance Snapshot

定义：

```text
OnlyStrategyPerformanceSnapshot
```

第一版至少包含：

```text
cluster_id
ts_event

equity
net_pnl
return_since_start
daily_pnl
daily_return
drawdown
maximum_drawdown

trade_count
winning_trade_count
losing_trade_count
win_rate

gross_profit
gross_loss
profit_factor

fees
```

Sharpe、Sortino、Calmar 等统计可以预留，但不要求本阶段完整实现。

复杂绩效统计未来可进入独立 Analytics 组件。

不要让 StrategyLedgerManager 演变为完整投研统计平台。

---

## 37. Trade 统计边界

Ledger 可以维护基本累计：

```text
trade_count
winning_trade_count
losing_trade_count
gross_profit
gross_loss
```

但需要明确：

* 是按 Fill；
* 按 Order；
* 还是按完整 Position 生命周期。

第一版建议：

```text
交易胜负统计
基于完整 Position Allocation 生命周期
```

如果当前 Position 组件尚未提供 Closed Position Result，则先只实现：

```text
trade_count
realized_pnl_delta_count
```

并在文档中标明限制。

不要将每个 Fill 简单视为一笔完整交易。

---

## 38. ctx.ledger 接口

策略通过：

```text
ctx.ledger
```

读取自身 Ledger。

类型：

```text
OnlyStrategyLedgerContextView
```

建议接口：

```python
ctx.ledger.snapshot()
ctx.ledger.equity
ctx.ledger.cash_balance
ctx.ledger.cash_available
ctx.ledger.cash_reserved

ctx.ledger.realized_pnl
ctx.ledger.unrealized_pnl
ctx.ledger.net_pnl
ctx.ledger.fees

ctx.ledger.return_since_start
ctx.ledger.drawdown
ctx.ledger.maximum_drawdown
```

策略不能：

```python
ctx.ledger.set_cash(...)
ctx.ledger.deposit(...)
ctx.ledger.withdraw(...)
ctx.ledger.reset_pnl(...)
ctx.ledger.reserve_cash(...)
ctx.ledger.apply_trade(...)
ctx.ledger.apply_fee(...)
```

所有修改只能由 Runtime 内部服务调用。

---

## 39. Risk 集成

提供只读：

```text
OnlyStrategyLedgerRiskView
```

至少支持：

```text
equity
cash_available
cash_reserved
net_pnl
daily_pnl
drawdown
maximum_drawdown
ledger_status
```

Risk 可实现未来规则：

```text
OnlyStrategyAvailableCapitalRiskRule
OnlyStrategyDailyLossRiskRule
OnlyStrategyMaxDrawdownRiskRule
OnlyStrategyMinimumEquityRiskRule
OnlyStrategyCashReservationRiskRule
```

当前阶段至少将 View 接入 Risk Context。

如果 Ledger 状态为：

```text
RECONCILING
ERROR
SUSPENDED
```

Risk 默认 Fail Closed。

---

## 40. Position 集成

StrategyLedger 读取：

```text
OnlyPositionAllocationQueryView
OnlyPositionValuation
```

不得读取账户合并 Position 成本作为策略收益依据。

必须使用：

```text
Cluster Position Allocation
```

计算：

* Position Cost；
* Position Market Value；
* Unrealized PnL；
* Strategy Exposure。

---

## 41. Order 和 Reservation 集成

买单通过 Risk 后：

```text
Order Created
→ Strategy Cash Reservation ACTIVE
```

订单：

```text
REJECTED
CANCELLED
EXPIRED
FAILED
```

时：

```text
释放未消费 Reservation
```

成交时：

```text
消费 Reservation
```

部分成交：

```text
PARTIALLY_CONSUMED
```

Reservation 估算金额与实际成交金额不一致时：

* 实际消耗按成交；
* 多余部分保持或释放；
* 不足部分必须检查；
* 不得让 cash_available 变负；
* 异常进入 `RECONCILING`。

---

## 42. 估算费用与实际费用

Reservation 可以使用：

```text
estimated_fee
```

实际成交后使用：

```text
actual_fee
```

如果：

```text
actual_fee < estimated_fee
```

释放差额。

如果：

```text
actual_fee > estimated_fee
```

需要：

* 检查剩余 cash_available；
* 足够则补充消耗；
* 不足则 Ledger 进入 `RECONCILING/ERROR`；
* 不得静默出现负现金。

---

## 43. Event

定义事实事件：

```text
OnlyStrategyLedgerCreatedEvent
OnlyStrategyLedgerActivatedEvent
OnlyStrategyLedgerClosedEvent

OnlyStrategyCashReservedEvent
OnlyStrategyCashReservationReleasedEvent
OnlyStrategyCashReservationConsumedEvent

OnlyStrategyTradeAppliedEvent
OnlyStrategyFeeAppliedEvent
OnlyStrategyCashFlowAppliedEvent

OnlyStrategyValuationUpdatedEvent
OnlyStrategyEquityUpdatedEvent
OnlyStrategyDrawdownUpdatedEvent

OnlyStrategyLedgerReconciliationStartedEvent
OnlyStrategyLedgerReconciledEvent
OnlyStrategyLedgerErrorEvent
```

正确顺序：

```text
函数调用
→ 修改 Ledger
→ 更新版本和索引
→ 生成 MutationResult
→ 发布 Event
```

EventBus 不负责修改 Ledger。

---

## 44. Event Publisher Port

定义：

```text
OnlyStrategyLedgerEventPublisher
```

提供：

```text
OnlyNoOpStrategyLedgerEventPublisher
OnlyInMemoryStrategyLedgerEventPublisher
OnlyRuntimeStrategyLedgerEventPublisherAdapter
```

Ledger Entity 不直接依赖完整 EventBus。

Manager 或 Application 层负责发布 Mutation Result 中的 Event。

---

## 45. Repository 抽象

定义：

```text
OnlyStrategyLedgerRepository
OnlyStrategyCashEntryRepository
OnlyStrategyFeeEntryRepository
```

第一版提供内存实现：

```text
OnlyInMemoryStrategyLedgerRepository
```

不实现具体数据库。

Repository 保存：

* Snapshot；
* Cash Entry；
* Fee Entry；
* Reservation DTO；
* Event 或 Replay Entry。

不暴露可变 Ledger 实体。

---

## 46. 序列化与重放

以下对象必须无损序列化：

```text
OnlyStrategyLedgerSnapshot
OnlyStrategyEquitySnapshot
OnlyStrategyPerformanceSnapshot

OnlyStrategyCashEntry
OnlyStrategyFeeEntry
OnlyStrategyCashReservation

OnlyStrategyTradeAccountingInput
OnlyStrategyLedgerMutationResult DTO
OnlyStrategyLedgerEvent
```

必须保持：

* Money；
* Currency；
* Decimal；
* UTC 时间；
* Trading Day；
* Enum；
* ID；
* version；
* sequence；
* quality_flags；
* metadata。

禁止将 Decimal 转为 float。

必须提供确定性重放：

```text
Initial Capital
→ Cash Reservation
→ Trade
→ Fee
→ Valuation
→ Snapshot
```

序列化后重新执行，结果必须一致。

---

## 47. 并发策略

第一版明确：

```text
每个 Runtime 使用单写入者串行修改 Strategy Ledger。
```

未来：

```text
Gateway Callback
→ Runtime Inbound Queue
→ ExecutionProcessor
→ Position Allocation
→ StrategyLedgerManager
```

禁止：

* Gateway 线程直接修改 Ledger；
* Cluster 线程直接修改 Ledger；
* 多个 Event Handler 并行修改同一 Ledger；
* 估值线程覆盖交易更新。

估值更新也必须进入 Runtime 受控顺序。

---

## 48. 推荐目录

根据当前工程结构调整，但建议：

```text
src/onlyalpha/strategy_ledger/
├── __init__.py
├── identifiers.py
├── enums.py
├── keys.py
├── capital.py
├── cash.py
├── fees.py
├── reservations.py
├── pnl.py
├── valuations.py
├── equity.py
├── performance.py
├── entities.py
├── snapshots.py
├── results.py
├── manager.py
├── query.py
├── views.py
├── risk_view.py
├── accounting_inputs.py
├── repositories.py
├── events.py
├── publisher.py
├── ports.py
├── serialization.py
└── exceptions.py
```

不得将 Strategy Ledger 混入 Position、Account 或 Risk 模块内部。

---

## 49. 最小 Demo

创建：

```text
examples/strategy_ledger_demo/
├── README.md
├── initial_capital_demo.py
├── buy_trade_demo.py
├── sell_trade_demo.py
├── multi_cluster_ledger_demo.py
├── cash_reservation_demo.py
├── equity_valuation_demo.py
├── drawdown_demo.py
├── replay_demo.py
└── context_ledger_demo.py
```

### 49.1 初始资金

```text
Cluster A = 500000 CNY
Cluster B = 300000 CNY
```

验证 Ledger 独立。

### 49.2 买入成交

Cluster A：

```text
initial cash = 100000
buy 1000 @ 10
fee = 5
```

期望：

```text
cash_balance = 89995
position_cost = 10000
fees = 5
```

### 49.3 估值

Mark Price = 11：

```text
position_market_value = 11000
unrealized_pnl = 1000
equity = 100995
```

并验证 Cash View 与 PnL View 一致。

### 49.4 卖出

卖出 400 @ 12，Fee=3：

* 现金增加；
* 已实现盈亏来自 Allocation；
* 剩余未实现盈亏正确；
* B Ledger 不变化。

### 49.5 多 Cluster

A、B 共用账户、交易同一 Instrument。

验证：

* Position 账户总仓位可以合并；
* A、B Ledger 完全独立；
* A、B 使用各自 Allocation 成本；
* 收益不能使用账户合并均价。

### 49.6 连续订单预占

A 可用资金 100000：

```text
订单 1 预占 60000
订单 2 再请求 60000
```

订单 2 应由 Risk 拒绝或 Reservation 创建失败。

### 49.7 Drawdown

净值序列：

```text
100000
110000
99000
105000
```

验证：

* High Water Mark；
* Current Drawdown；
* Maximum Drawdown。

### 49.8 Replay

相同 Entry 序列重放，最终 Snapshot 完全一致。

---

## 50. 必须新增的测试

建议创建：

```text
tests/strategy_ledger/
├── test_strategy_ledger_key.py
├── test_strategy_ledger_creation.py
├── test_strategy_ledger_initial_capital.py
├── test_strategy_ledger_runtime_isolation.py
├── test_strategy_ledger_cluster_isolation.py
├── test_strategy_ledger_snapshot_immutability.py

├── test_strategy_cash_entry.py
├── test_strategy_cash_balance.py
├── test_strategy_cash_available.py
├── test_strategy_cash_negative_rejected.py
├── test_external_cash_flow.py

├── test_cash_reservation_create.py
├── test_cash_reservation_release.py
├── test_cash_reservation_consume.py
├── test_cash_reservation_partial_consume.py
├── test_cash_reservation_idempotency.py
├── test_cash_reservation_actual_fee_adjustment.py
├── test_consecutive_order_cash_reservation.py

├── test_buy_trade_accounting.py
├── test_sell_trade_accounting.py
├── test_partial_sell_trade_accounting.py
├── test_trade_fee_accounting.py
├── test_duplicate_trade.py
├── test_stale_trade.py
├── test_trade_without_cluster_rejected.py

├── test_realized_pnl_from_allocation.py
├── test_unrealized_pnl_from_allocation.py
├── test_strategy_cost_not_account_cost.py
├── test_position_market_value.py
├── test_linear_valuation.py

├── test_equity_cash_view.py
├── test_equity_pnl_view.py
├── test_equity_views_reconcile.py
├── test_equity_reconciliation_failure.py

├── test_net_pnl.py
├── test_simple_return.py
├── test_return_with_external_cash_flow_unsupported.py
├── test_high_water_mark.py
├── test_drawdown.py
├── test_maximum_drawdown.py
├── test_daily_pnl_trading_day.py

├── test_fee_ledger.py
├── test_fee_types.py
├── test_fee_duplicate.py
├── test_fee_currency_mismatch.py

├── test_ctx_ledger_read_only.py
├── test_risk_ledger_view.py
├── test_ledger_status_blocks_risk.py

├── test_strategy_ledger_serialization.py
├── test_strategy_ledger_events_after_mutation.py
├── test_strategy_ledger_replay.py
└── test_strategy_ledger_determinism.py
```

---

## 51. 核心验收场景

### 51.1 Cluster 独立资金账

A、B 共用一个 Account。

必须拥有独立：

```text
cash
position value
realized pnl
unrealized pnl
fees
equity
drawdown
```

### 51.2 策略成本独立

A 买入 100 @ 10。

B 买入 100 @ 12。

账户平均价可以为 11。

但：

```text
A Ledger 必须使用 A Allocation 成本 10
B Ledger 必须使用 B Allocation 成本 12
```

### 51.3 资金预占

同一个 `on_bar` 连续下单必须看到最新预占。

### 51.4 收益视图一致

必须满足：

```text
cash + market_value
==
initial_capital + external_cash_flow + realized_pnl + unrealized_pnl - fees
```

不一致必须显式报错。

### 51.5 幂等

重复 Trade、Fee、Reservation 不重复影响 Ledger。

### 51.6 Scope

Cluster A 不能读取 Cluster B Ledger。

Runtime A 不能读取 Runtime B Ledger。

### 51.7 Risk

Risk 可以读取策略：

```text
cash_available
equity
daily_pnl
drawdown
```

但不能修改 Ledger。

### 51.8 确定性

相同初始资金、Trade、Fee、Valuation 序列执行 100 次：

* Cash；
* PnL；
* Equity；
* High Water Mark；
* Drawdown；
* Version；
* Event 顺序；
* Snapshot；

完全一致。

---

## 52. Context 集成

将：

```text
ctx.ledger
```

加入：

```text
OnlyClusterContext
OnlyBarContext
OnlyTimerContext
```

必须绑定：

```text
runtime_id
account_id
cluster_id
```

策略只能读取自身 Ledger。

禁止：

```text
ctx.strategy_ledger_manager
ctx.ledger_manager
ctx.ledger.apply_trade()
ctx.ledger.reserve_cash()
ctx.ledger.set_equity()
```

---

## 53. Risk 集成顺序

未来订单提交链建议：

```text
ctx.orders.submit()
→ Request Validation
→ RiskService.evaluate_order()
    ├── Position Risk
    ├── Strategy Ledger Risk
    └── Account Risk
→ ACCEPT
→ Order 创建
→ Risk Reservation
→ Position Reservation
→ Strategy Cash Reservation
→ Execution
```

本阶段需要：

* 实现 `OnlyStrategyLedgerRiskView`；
* 接入 Risk Context；
* 提供可用资金、净值、日亏损、回撤；
* 不需要在本阶段实现全部新 Risk Rule；
* 至少提供示例 Rule 或集成测试。

---

## 54. Position 集成顺序

成交记账必须依赖 Position Allocation 更新结果：

```text
PositionAllocationManager.apply_trade()
    ↓
OnlyPositionAllocationMutationResult
    ↓
StrategyLedgerManager.apply_trade_accounting()
```

禁止 StrategyLedgerManager 自己维护另一套 Position Cost Basis。

---

## 55. 文档输出

创建或更新：

```text
docs/strategy_ledger.md
docs/position.md
docs/risk.md
docs/order.md
docs/runtime_context.md
docs/cluster.md
docs/event.md
docs/architecture.md
docs/testing.md
docs/architecture_principles.md
```

`docs/strategy_ledger.md` 至少包含：

1. Strategy Ledger 组件边界；
2. 账户真实账和策略虚拟账的区别；
3. Ledger Key；
4. 初始资金；
5. Capital Allocation；
6. Cash Ledger；
7. Fee Ledger；
8. Reservation；
9. Trade Accounting；
10. Position Allocation 依赖；
11. Realized PnL；
12. Unrealized PnL；
13. Equity；
14. Cash View 与 PnL View；
15. Return；
16. High Water Mark；
17. Drawdown；
18. Trading Day；
19. Multi-currency 边界；
20. Context API；
21. Risk 集成；
22. Event；
23. Repository；
24. Replay；
25. 并发；
26. Demo；
27. 已知限制。

---

## 56. ADR

创建：

```text
docs/adr/0011-strategy-ledger-capital-pnl-and-equity.md
```

至少记录：

### 背景

多个 Cluster 共用一个券商账户时，券商只提供账户真实资金和总持仓，无法直接表达每个策略的独立资金、费用、收益、净值和回撤。

### 决策

* 每个 Runtime 一个 StrategyLedgerManager；
* 每个 Cluster 一个独立 Strategy Ledger；
* 策略虚拟账与券商真实账户账分离；
* Strategy Position Cost 来自 Position Allocation；
* 不根据账户总收益按比例分配策略收益；
* 第一版使用 Fixed Capital；
* 买入订单通过后创建 Cash Reservation；
* Trade、Fee 和 Valuation 通过函数调用更新 Ledger；
* 外部只获得 immutable Snapshot；
* 同时计算 Cash View 和 PnL View，并要求一致；
* 第一版实现单币种、Linear PnL、Simple Return 和 Drawdown；
* Event 只通知已发生事实；
* 本阶段不实现完整 AccountManager。

### 拒绝方案

* 将策略收益直接放入 AccountManager；
* 使用账户合并平均价计算策略收益；
* 按仓位比例事后分摊账户收益；
* Cluster 自己维护普通 cash/pnl 变量；
* 不做现金预占；
* 只保存最终净值而不保存可重放账目；
* Event Handler 并行修改 Ledger；
* 策略直接修改初始资金或 PnL。

---

## 57. Architecture Principles 新增规则

加入：

```text
Rule: 券商真实账户账与策略虚拟资金账必须分离。

Rule: 每个 Runtime 拥有独立 OnlyStrategyLedgerManager。

Rule: 每个 Cluster 拥有独立 Strategy Ledger。

Rule: Strategy PnL 必须基于自身 Trade、Fee 和 Position Allocation。

Rule: Strategy Ledger 不使用账户合并成本计算策略收益。

Rule: 策略资金预占必须在订单提交执行前完成。

Rule: Strategy Ledger 修改使用函数调用。

Rule: Strategy Ledger Event 只通知已经发生的事实。

Rule: Cluster 只能通过 ctx.ledger 读取 immutable Snapshot。

Rule: Cluster 不能修改 Ledger。

Rule: Cash View 和 PnL View 必须可对账。

Rule: 不同币种 Money 不得直接相加。

Rule: 重复 Trade、Fee 和 Reservation 必须幂等。

Rule: Ledger 为 RECONCILING 或 ERROR 时 Risk 默认 Fail Closed。

Rule: 回测、Paper 和 Live 使用相同 Strategy Ledger API。
```

---

## 58. 实现顺序

严格按以下顺序：

1. 扫描当前策略资金和收益实现；
2. 创建差距分析；
3. 定义 Ledger ID、Key、Status；
4. 定义 Capital Allocation；
5. 实现 Fixed Capital；
6. 实现 Strategy Ledger Snapshot；
7. 实现 Cash Ledger 和 Cash Entry；
8. 完成初始资金和现金测试；
9. 实现 Cash Reservation；
10. 完成连续订单预占测试；
11. 定义 Trade Accounting Input；
12. 实现买入成交记账；
13. 实现卖出成交记账；
14. 接入 Position Allocation Mutation；
15. 实现 Fee Ledger；
16. 完成手续费归因测试；
17. 实现 Strategy Valuation；
18. 实现 Unrealized PnL；
19. 实现 Equity Cash View；
20. 实现 Equity PnL View；
21. 完成双视图对账测试；
22. 实现 Simple Return；
23. 实现 High Water Mark 和 Drawdown；
24. 实现 StrategyLedgerManager；
25. 实现 Query 和 Context View；
26. 接入 Risk View；
27. 实现 Event 和 Publisher；
28. 实现 Repository 抽象和内存实现；
29. 完成序列化和 Replay；
30. 创建 Demo；
31. 更新文档；
32. 创建 ADR；
33. 运行全部测试；
34. 输出验收报告。

---

## 59. 验收标准

完成后必须满足：

* 每个 Runtime 有独立 StrategyLedgerManager；
* 每个 Cluster 有独立 Ledger；
* 策略虚拟账与账户真实账分离；
* 初始资金类型安全；
* Cluster 不能修改 Ledger；
* ctx.ledger 只读；
* 买入现金扣减正确；
* 卖出现金增加正确；
* 手续费正确归因；
* Cash Reservation 正确；
* 连续订单考虑最新预占；
* Reservation 幂等；
* Strategy Cost 来自 Position Allocation；
* 已实现盈亏正确；
* 未实现盈亏正确；
* Cash View 正确；
* PnL View 正确；
* 两种 Equity View 可以对账；
* Net PnL 正确；
* Simple Return 正确；
* High Water Mark 正确；
* Drawdown 正确；
* Maximum Drawdown 正确；
* 重复 Trade 不重复记账；
* 重复 Fee 不重复记账；
* 乱序输入被检测；
* 不同 Cluster 状态隔离；
* 不同 Runtime 状态隔离；
* Risk 可以读取 Ledger View；
* Ledger 异常时 Risk Fail Closed；
* 序列化无损；
* Replay 确定；
* 文档、测试、Demo、ADR 完整。

---

## 60. 一票否决项

存在以下任一项，不得标记完成：

* 将策略虚拟资金直接混入 AccountManager；
* 多个 Cluster 共用一个可变 Ledger；
* Cluster 自己维护无法审计的 cash/pnl 变量；
* 使用账户合并平均价计算策略收益；
* 按账户总收益比例分摊策略收益；
* 买单不进行 Strategy Cash Reservation；
* 重复 Trade 重复扣减现金；
* 重复 Fee 重复累计；
* Cash View 与 PnL View 不一致但不报错；
* Strategy Ledger 使用裸 float；
* 不同币种 Money 直接相加；
* 策略可以修改初始资金；
* 策略可以重置 PnL；
* 策略可以直接调用 apply_trade；
* Query 返回可变 Ledger；
* EventBus Handler 承担 Ledger 状态机；
* Gateway 回调线程直接修改 Ledger；
* Runtime 之间共享可变 Ledger；
* Cluster 可以读取其他 Cluster Ledger；
* 不使用 Position Allocation 成本；
* 外部现金流被错误计入交易收益；
* 相同输入产生不同结果；
* 本阶段实现未经要求的完整 AccountManager 或真实券商同步。

---

## 61. 最终交付报告

完成后必须输出：

```text
新增文件
修改文件
Strategy Ledger 组件边界
账户真实账与策略虚拟账区别
Ledger Key 和所有权
Capital Allocation 设计
Fixed Capital 实现
Cash Ledger 设计
Cash Entry 类型
Cash Reservation 设计
Reservation 生命周期
Trade Accounting 输入
买入成交记账
卖出成交记账
Position Allocation 集成
Fee Ledger
Realized PnL
Unrealized PnL
Position Market Value
Equity Cash View
Equity PnL View
双视图对账结果
Net PnL
Return
High Water Mark
Drawdown
Maximum Drawdown
Daily PnL
ctx.ledger API
Risk Ledger View
Event 设计
Repository 和 Replay
测试通过数
测试失败数
测试跳过数
确定性测试结果
Demo 运行结果
已知限制
一票否决项
是否建议进入 AccountManager
是否建议进入 ExecutionProcessor
是否建议进入 ExecutionSimulator
```

最终结论：

```text
ACCEPTED
CONDITIONALLY_ACCEPTED
REJECTED
```

当前任务只实现：

```text
Strategy Ledger Domain
StrategyLedgerManager
Capital Allocation
Cash Ledger
Fee Ledger
Cash Reservation
Trade Accounting
PnL
Valuation
Equity
Return
Drawdown
Snapshot
Query
ctx.ledger
Risk Ledger View
Event
Repository
Replay
测试
Demo
文档
ADR
```

不要在本任务中实现：

* 完整 AccountManager；
* 真实券商现金同步；
* 多币种转换；
* 融资融券；
* 期货保证金；
* Funding Rate；
* 利息；
* 分红；
* 自动资金再平衡；
* 策略间资金转移；
* 完整 ExecutionProcessor；
* Matching Engine；
* Web；
* 数据库具体实现；
* 真实交易。
