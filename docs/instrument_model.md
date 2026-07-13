# 跨市场资产与 Instrument 模型

## 1. 目标

第一阶段支持中国 A 股，设计必须预留：

- 中国期货；
- 港股；
- 美股；
- 外汇；
- 期权；
- 数字货币现货；
- 交割合约；
- 永续合约。

## 2. 金融数值

至少定义：

```text
OnlyPrice
OnlyQuantity
OnlyMoney
OnlyCurrency
OnlyRate
OnlyPercentage
OnlyMultiplier
```

这些对象应：

- 不可变；
- 明确精度；
- 明确舍入；
- 支持序列化；
- 支持哈希；
- 构造时校验；
- 禁止错误类型混用。

## 3. 禁止无约束 float

核心交易真值不得直接依赖二进制浮点。

优先：

- 整数缩放；
- Decimal；
- 定点数。

不得用 float `%` 判断 Tick 对齐。

## 4. Currency 与 Money

`OnlyMoney` 必须绑定 `OnlyCurrency`。

不同币种不能直接相加。

跨币种必须显式使用：

```text
OnlyExchangeRate
OnlyFxConversionService
```

## 5. Instrument 标识

建议：

```text
OnlyInstrumentId = OnlySymbol + OnlyVenue
```

示例：

```text
600000.XSHG
000001.XSHE
AAPL.XNAS
0700.XHKG
IF2603.CFFEX
BTCUSDT.BINANCE
```

内部使用强类型对象，不依赖手工拼接字符串。

## 6. Instrument 基础字段

```text
instrument_id
raw_symbol
display_name
asset_class
instrument_type
venue
exchange
base_currency
quote_currency
settlement_currency
price_precision
quantity_precision
price_increment
quantity_increment
minimum_quantity
maximum_quantity
minimum_notional
maximum_notional
contract_multiplier
lot_size
activation_time
expiration_time
trading_calendar
timezone
status
metadata
version
effective_from
effective_to
```

## 7. 类型

```text
OnlyEquity
OnlyEtf
OnlyFund
OnlyFuture
OnlyOption
OnlyFxPair
OnlyCryptoSpot
OnlyCryptoFuture
OnlyCryptoPerpetual
OnlyIndex
OnlyCommodity
OnlySyntheticInstrument
```

## 8. Precision 与 Increment

必须区分：

- `price_precision`；
- `price_increment`；
- `quantity_precision`；
- `quantity_increment`。

例如两位小数不代表 `0.01` 是合法 Tick。

## 9. 舍入

定义：

```text
OnlyRoundingMode
OnlyPriceQuantizer
OnlyQuantityQuantizer
OnlyMoneyQuantizer
```

默认优先拒绝非法值，而不是静默修正。

## 10. A 股规则

需要表达：

- 上交所和深交所；
- 股票、ETF、基金、指数；
- 人民币报价；
- 最小价格变动；
- 买入单位；
- 卖出零股；
- T+1；
- 涨跌停；
- ST；
- 停牌；
- 除权除息；
- 复权；
- 交易时段；
- 集合竞价；
- 手续费；
- 印花税；
- 过户费。

这些规则必须通过：

```text
OnlyMarketRule
OnlyTradingRule
OnlySettlementRule
OnlyPriceLimitRule
OnlyLotSizeRule
OnlyFeeSchedule
```

表达，不写死在 Engine。

## 11. Equity 与账户权益

固定区分：

```text
OnlyEquity
OnlyAccountEquity
OnlyEquityCurve
```

## 12. Future

至少包含：

```text
underlying
contract_code
contract_multiplier
quote_currency
settlement_currency
margin_currency
initial_margin_rate
maintenance_margin_rate
expiration_time
last_trade_time
delivery_type
settlement_type
```

盈亏必须考虑合约乘数。

## 13. Option

至少包含：

```text
underlying
strike_price
expiration_time
option_kind
exercise_style
settlement_type
contract_multiplier
```

## 14. Crypto

必须区分：

```text
OnlyCryptoSpot
OnlyCryptoFuture
OnlyCryptoPerpetual
```

并表达：

- base；
- quote；
- settlement；
- margin；
- linear；
- inverse；
- quanto；
- funding；
- maker/taker fee；
- expiry。

不得仅从 Symbol 推断合约语义。

## 15. 动态更新

Instrument 规格会变化。

需要：

```text
instrument_version
effective_from
effective_to
updated_at
source
```

回测必须使用历史时点有效的规格。

## 16. 测试

覆盖：

- A 股；
- ETF；
- 港股手数；
- 美股碎股；
- 中国期货；
- 线性永续；
- 反向永续；
- 外汇；
- 期权；
- 非法 Tick；
- 非法 Step；
- 最小金额；
- 多币种；
- 序列化；
- 极值。
