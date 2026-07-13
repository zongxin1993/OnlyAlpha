# OnlyAlpha Domain Conformance Demo 生成任务

## 1. 任务目标

为 OnlyAlpha 创建一套独立、可运行、可测试的 Domain Conformance Demo，用于验证当前 Domain 是否能够：

- 支持中国 A 股、A 股 ETF、港股、美股碎股、中国期货、期权、外汇、数字货币现货、线性永续和反向永续；
- 正确描述 Price、Quantity、Money、Currency、Instrument、Tick、Bar、Order、Trade、Position、Account、Fee、Margin 和 PnL；
- 保证精度、币种、时间、市场规则、序列化、历史版本和扩展能力；
- 在不依赖 Engine、Runtime、Gateway、Web、Storage、Backtest 的前提下独立工作。

本任务不是实现完整交易系统，而是建立一套自动化验收 Demo，逐项证明当前 Domain 是否合格。

最终应能通过以下命令得到清晰结论：

```bash
pytest -q tests/domain_conformance
python examples/domain_conformance/run_demo.py
```

输出必须包括：

- 通过能力；
- 失败能力；
- 尚未实现能力；
- Domain 成熟度评分；
- 一票否决项；
- 是否建议进入 Runtime 与 Backtest 阶段。

---

## 2. 必读内容

执行前必须阅读：

```text
AGENTS.md
docs/architecture.md
docs/domain_model.md
docs/instrument_model.md
docs/nautilus_research.md
docs/coding_style.md
docs/testing.md
docs/adr/
```

同时扫描当前 Domain 实现，并输出差距分析。

若项目尚未完成 Domain，只实现完成本 Demo 所需的最小 Domain，不要实现 Engine、Runtime、Gateway、Web、完整 Backtest 或真实交易。

---

## 3. 强制边界

Domain 不得依赖：

```text
engine
runtime
cluster
gateway
broker SDK
database
web
cache
storage
backtest
live
research
```

允许依赖：

```text
Python 标准库
decimal
datetime
enum
dataclasses
typing
自身 Domain 类型
```

必须增加 import 边界测试。

如果 Domain 需要外层模块才能创建 Instrument、Bar、Order、Trade、Position 或 Account，应视为设计失败，不得通过 Mock 掩盖。

---

## 4. 输出目录

建议创建：

```text
examples/domain_conformance/
├── README.md
├── run_demo.py
├── scenarios/
│   ├── a_share.py
│   ├── a_share_etf.py
│   ├── hong_kong_equity.py
│   ├── us_equity_fractional.py
│   ├── china_future.py
│   ├── option.py
│   ├── fx_pair.py
│   ├── crypto_spot.py
│   ├── crypto_linear_perpetual.py
│   └── crypto_inverse_perpetual.py
├── fixtures/
│   ├── instruments.py
│   ├── bars.py
│   ├── orders.py
│   └── accounts.py
└── reports/
    └── .gitkeep

tests/domain_conformance/
├── test_00_domain_boundaries.py
├── test_01_financial_value_types.py
├── test_02_instrument_model.py
├── test_03_precision_and_increment.py
├── test_04_market_rules.py
├── test_05_bar_model.py
├── test_06_tick_model.py
├── test_07_order_trade_position.py
├── test_08_account_money_pnl.py
├── test_09_serialization_roundtrip.py
├── test_10_historical_versions.py
├── test_11_multi_market_scenarios.py
├── test_12_extensibility.py
├── test_13_determinism.py
└── test_14_domain_score.py
```

若工程已有目录规范，可以调整路径，但测试职责不能省略。

---

## 5. 最低 Domain 类型要求

### 5.1 金融值对象

```text
OnlyPrice
OnlyQuantity
OnlyMoney
OnlyCurrency
OnlyRate
OnlyPercentage
OnlyMultiplier
```

要求：

- 默认不可变；
- 不使用裸 float 保存交易真值；
- 支持比较、hash、repr；
- 支持无损序列化；
- 构造时校验；
- 明确精度、单位和合法范围；
- 错误类型运算必须失败。

### 5.2 强类型标识符

```text
OnlyInstrumentId
OnlyVenueId
OnlyOrderId
OnlyTradeId
OnlyPositionId
OnlyAccountId
OnlyClusterId
OnlyRuntimeId
OnlyEngineId
OnlySymbol
OnlyRawSymbol
```

核心 API 不得全部使用普通字符串。

### 5.3 Instrument

```text
OnlyInstrument
OnlyEquity
OnlyETF
OnlyFuture
OnlyOption
OnlyFxPair
OnlyCryptoSpot
OnlyCryptoFuture
OnlyCryptoPerpetual
```

至少可表达：

```text
instrument_id
raw_symbol
venue
asset_class
instrument_type
base_currency
quote_currency
settlement_currency
margin_currency
price_precision
quantity_precision
price_increment
quantity_increment
minimum_quantity
maximum_quantity
minimum_notional
contract_multiplier
lot_size
activation_time
expiration_time
timezone
trading_calendar
status
version
effective_from
effective_to
```

不适用字段可以为空，但不得填入含义错误的假值。

### 5.4 市场规则

```text
OnlyMarketRule
OnlyTradingRule
OnlySettlementRule
OnlyLotSizeRule
OnlyPriceLimitRule
OnlyFeeSchedule
OnlyTradingCalendar
OnlyTickScheme
OnlyPriceLadder
```

Instrument 与 MarketRule 必须分离。

### 5.5 市场数据

```text
OnlyTick
OnlyQuoteTick
OnlyTradeTick
OnlyBar
OnlyBarSpecification
OnlyBarType
OnlyAggregationSource
OnlyAdjustmentType
```

### 5.6 交易对象

```text
OnlyOrderRequest
OnlyCancelRequest
OnlyOrder
OnlyTrade
OnlyPosition
OnlyAccount
OnlyAccountEquity
OnlyBalance
OnlyFee
OnlyCommission
OnlyMargin
OnlyPnL
```

---

## 6. 测试 00：Domain 依赖纯净性

扫描 Domain 源码，不得 import：

```python
FORBIDDEN_IMPORTS = {
    "onlyalpha.engine",
    "onlyalpha.runtime",
    "onlyalpha.cluster",
    "onlyalpha.gateway",
    "onlyalpha.storage",
    "onlyalpha.cache",
    "onlyalpha.web",
    "onlyalpha.api",
    "onlyalpha.backtest",
    "onlyalpha.live",
    "onlyalpha.research",
}
```

验收：

- Domain 可以独立导入；
- Domain 测试不初始化 Engine；
- 创建核心对象不需要 Gateway 或 Runtime。

权重：10 分。

---

## 7. 测试 01：金融值对象

以下操作必须失败：

```python
OnlyPrice("10.50") + OnlyMoney("100.00", CNY)
OnlyMoney("100.00", CNY) + OnlyMoney("100.00", USD)
```

以下对象不能被视为同类型等值：

```python
OnlyPrice("10.50")
OnlyQuantity("10.50")
```

还要验证：

- NaN 和 Infinity 被拒绝；
- Money 必须绑定 Currency；
- 负值是否允许由类型明确规定；
- 内部不保存裸 float；
- Decimal 精度不丢失；
- hash 和排序行为确定。

权重：15 分。

---

## 8. 测试 02：Instrument 描述能力

逐项创建并验证：

- A 股股票；
- A 股 ETF；
- 港股；
- 美股碎股；
- 中国期货；
- 期权；
- 外汇；
- Crypto Spot；
- Linear Perpetual；
- Inverse Perpetual。

不得在通用 Domain 中散落大量：

```python
if market == "CN":
    ...
elif market == "US":
    ...
```

权重：15 分。

---

## 9. 测试 03：Precision 与 Increment

必须区分：

```text
price_precision
price_increment
quantity_precision
quantity_increment
```

示例：

```text
price_precision = 2
price_increment = 0.05
```

`10.03` 小数位合法，但不符合 Tick。

至少提供：

```python
instrument.is_valid_price(...)
instrument.is_valid_quantity(...)
instrument.quantize_price(...)
instrument.quantize_quantity(...)
```

量化方法必须显式传入舍入策略。

禁止在核心代码中散落 `round()`。

权重：10 分。

---

## 10. 测试 04：MarketRule 分离

验证以下规则不写死在通用 Instrument 或 Engine：

- A 股 T+1；
- A 股涨跌停；
- 港股每手股数；
- 港股 Price Ladder；
- 美股碎股；
- 中国期货开仓、平仓和平今；
- 数字货币 minimum notional；
- 交易时段；
- 节假日；
- 盘前盘后；
- 夜盘；
- 手续费；
- 结算周期。

测试必须证明：

- 同一 `OnlyEquity` 抽象可以应用不同市场规则；
- 同一订单请求在不同规则下产生不同但确定的校验结果。

权重：10 分。

---

## 11. 测试 05：Bar 完整语义

`OnlyBar` 不得只有 OHLCV。

必须能够明确描述：

```text
instrument_id
bar_specification
open
high
low
close
volume
quote_volume
turnover
trade_count
open_interest
bar_start
bar_end
ts_event
ts_init
is_closed
revision
adjustment_type
trading_day
session_type
```

字段可以可选，但语义必须明确。

### 11.1 Bar Specification

至少表达：

- 1 分钟 Last Price Bar；
- 5 分钟 Bid Bar；
- 日线 Session Bar；
- Tick Bar；
- Volume Bar；
- Notional Bar。

### 11.2 时间语义

必须明确：

- bar_start；
- bar_end；
- ts_event；
- ts_init；
- 区间是 `[start, end)` 还是其他；
- 时区；
- trading_day；
- session_type。

测试：

- 09:30:00；
- 09:30:59.999；
- 09:31:00；
- A 股午休；
- 期货夜盘；
- 跨时区；
- 夏令时；
- 实时与离线聚合一致。

### 11.3 成交量语义

区分：

- base volume；
- quote volume；
- turnover；
- trade count；
- open interest。

### 11.4 修订

明确支持或拒绝：

- 更新中的 Bar；
- 已关闭 Bar；
- 迟到 Tick；
- revision。

权重：15 分。

---

## 12. 测试 06：Tick

Trade Tick 至少包含：

```text
instrument_id
price
quantity
aggressor_side
trade_id
ts_event
ts_init
sequence
source
```

Quote Tick 必须明确 Bid/Ask，不能与 Trade Tick 混淆。

验证：

- 事件时间和接收时间；
- 顺序号；
- 重复事件；
- 精度；
- Instrument 关联；
- 无损序列化。

---

## 13. 测试 07：Order、Trade、Position

### 13.1 Order

至少表达：

```text
order_id
client_order_id
account_id
instrument_id
side
order_type
quantity
price
time_in_force
status
filled_quantity
average_fill_price
created_at
updated_at
```

验证：

- 非法状态迁移被拒绝；
- 部分成交；
- 完全成交；
- 撤单；
- 拒单；
- 重复回报幂等；
- 乱序回报有明确约束。

### 13.2 Trade

至少表达：

```text
trade_id
order_id
account_id
instrument_id
price
quantity
side
fee
ts_event
ts_init
```

### 13.3 Position

至少验证：

- A 股可用数量、冻结数量；
- 期货多空方向；
- 今仓、昨仓；
- 美股碎股；
- Crypto 逐仓和全仓扩展能力；
- realized PnL；
- unrealized PnL；
- settlement currency。

权重：8 分。

---

## 14. 测试 08：Account、Money、PnL

验证：

- 多币种余额；
- Base Currency；
- Account Equity；
- Available Balance；
- Frozen Balance；
- Margin；
- Fee；
- Commission；
- Realized PnL；
- Unrealized PnL；
- 汇率换算必须显式；
- `OnlyEquity` 与 `OnlyAccountEquity` 不混淆。

---

## 15. 测试 09：无损序列化

所有核心对象必须通过：

```text
对象 -> dict/JSON -> 对象
```

满足：

```python
restored == original
```

重点检查：

- Decimal 不转 float；
- 时区不丢失；
- Currency 不丢失；
- Enum 可恢复；
- Instrument 子类型可恢复；
- Bar Specification 可恢复；
- Version 可恢复；
- 可选字段语义不变化。

Domain 本身不得依赖数据库。

权重：5 分。

---

## 16. 测试 10：历史版本

验证：

- Instrument 可以版本化；
- Tick Size 可以变化；
- Lot Size 可以变化；
- Fee Schedule 可以变化；
- Security Status 可以变化；
- effective_from；
- effective_to；
- 可以按历史时点获取有效版本。

历史回测不得只能使用当前最新 Instrument。

权重：4 分。

---

## 17. 测试 11：逐市场完整场景

每个场景必须完成：

```text
创建 Currency
创建 Instrument
创建 MarketRule
创建 Price
创建 Quantity
校验订单
创建 Tick
创建 Bar
创建 Order
创建 Trade
更新 Position
计算 Fee
计算 PnL
序列化
反序列化
```

### 17.1 A 股股票

验证 CNY、整数股、买入整手、卖出零股规则、T+1、涨跌停、午休和复权元数据。

### 17.2 A 股 ETF

验证与普通股票不同的交易或结算规则可以独立配置。

### 17.3 港股

验证 HKD、每只股票不同 lot size、Price Ladder 和交易时段。

### 17.4 美股碎股

验证 USD、小数数量、盘前盘后和卖空扩展能力。

### 17.5 中国期货

验证整数手、contract multiplier、margin、expiry、夜盘、开平仓和平今、多空双向。

### 17.6 期权

验证 Call/Put、Strike、Expiry、Exercise Style、Settlement Type、Underlying 和 Multiplier。

### 17.7 外汇

验证 Base/Quote Currency、Pip、Lot 和显式汇率换算。

### 17.8 Crypto Spot

验证 Base/Quote、小数数量、Step Size、Minimum Notional、Maker/Taker Fee 和 24x7 Calendar。

### 17.9 Linear Perpetual

验证 Settlement Currency、Margin Currency、Funding、Linear 和无到期日。

### 17.10 Inverse Perpetual

验证 Inverse、PnL 公式差异，以及 Settlement Currency 与 Quote Currency 不同。

---

## 18. 测试 12：扩展能力

在测试目录定义示例新资产：

```text
OnlyBond
```

只允许：

- 新增 OnlyBond；
- 新增 Bond Rule；
- 新增序列化注册；
- 新增测试。

不应修改：

```text
OnlyEngine
OnlyRuntime
OnlyCluster
OnlyEventBus
OnlyBar
OnlyOrder
```

如果新增 Bond 需要修改大量核心类，应判定扩展性不足。

权重：3 分。

---

## 19. 测试 13：确定性

相同输入多次执行，结果必须一致。

至少验证：

- Money 运算；
- Price Quantization；
- Bar 聚合；
- Fee；
- PnL；
- 序列化；
- Hash；
- 排序。

测试不得依赖：

- 当前系统时间；
- 本地时区；
- 随机顺序；
- float 漂移。

权重：5 分。

---

## 20. 测试 14：自动评分

实现：

```text
OnlyDomainConformanceScore
OnlyDomainConformanceReport
```

评分：

| 维度 | 分数 |
|---|---:|
| Domain 依赖纯净 | 10 |
| 金融值对象与精度 | 15 |
| Instrument 描述能力 | 15 |
| Precision 与 Increment | 10 |
| MarketRule 分离 | 10 |
| Bar 与时间语义 | 15 |
| Order/Trade/Position | 8 |
| 序列化无损 | 5 |
| 历史版本能力 | 4 |
| 可扩展性 | 3 |
| 确定性与基础一致性 | 5 |
| 总分 | 100 |

结论：

```text
90-100：可以进入 Runtime 与 Backtest
80-89：基本可用，但必须修复高风险项
70-79：仅适合作为原型
低于 70：不建议继续建设上层架构
```

---

## 21. 一票否决项

以下任一项存在，必须判定“不通过”：

- Money、Price、Quantity 使用裸 float；
- Price、Money、Quantity 可以错误混用；
- 不同 Currency 的 Money 可以直接相加；
- Bar 没有 InstrumentId；
- Bar 没有明确时间语义；
- Instrument 与 MarketRule 严重混合；
- Domain import Engine、Runtime 或 Gateway；
- Decimal 序列化后变为 float；
- 期货不能描述 Contract Multiplier；
- Crypto 无法区分 Linear 与 Inverse；
- Instrument 无版本和生效时间；
- 回测和实盘计划使用不同 Domain 对象；
- 新增市场需要修改 Engine 核心。

---

## 22. Demo 输出

`run_demo.py` 应逐项输出：

```text
[PASS] DOMAIN_BOUNDARY
[PASS] VALUE_TYPES
[PASS] A_SHARE
[PASS] A_SHARE_ETF
[PASS] HK_EQUITY
[FAIL] US_FRACTIONAL
       reason: quantity_increment does not support decimal shares
...

Domain Conformance Score: 87/100
Status: CONDITIONALLY_ACCEPTED
Blocking Issues:
- Historical Instrument lookup missing
Recommendation:
- Do not start Live Runtime yet
- Fix historical versioning first
```

同时生成：

```text
examples/domain_conformance/reports/domain_conformance.json
examples/domain_conformance/reports/domain_conformance.md
```

报告至少包含：

- Git commit；
- Python 版本；
- 测试总数；
- 通过数；
- 失败数；
- 跳过数；
- 各维度得分；
- 一票否决项；
- 未支持能力；
- 推荐下一步。

---

## 23. 实现顺序

严格按以下顺序：

1. 扫描当前 Domain；
2. 输出差距分析；
3. 创建测试骨架；
4. 先写失败测试；
5. 最小化实现；
6. 每完成一个维度立即运行测试；
7. 完成逐市场 Demo；
8. 完成评分；
9. 生成报告；
10. 更新 README；
11. 总结未通过项。

不得为了测试通过而：

- 降低断言；
- 删除失败场景；
- 使用 Mock 绕过领域约束；
- 将复杂规则写死在测试；
- 将市场差异堆入 Engine；
- 用 float 替代 Decimal；
- 忽略时区；
- 忽略历史版本。

---

## 24. 最终交付

完成后必须列出：

- 新增文件；
- 修改文件；
- 测试通过数；
- 测试失败数；
- 跳过数；
- Domain 得分；
- 一票否决项；
- 未支持的市场能力；
- 是否建议进入 Runtime；
- 是否建议进入 Backtest；
- 潜在破坏性设计问题。

当前任务只做 Domain Conformance Demo，不实现真实交易和完整上层系统。
