# NautilusTrader 资产模型研究

## 1. 研究范围

本研究参考 NautilusTrader 官方 Value Types、Instruments、Crypto Perpetual 文档和公开仓库，日期为 2026-07-13。仅借鉴领域约束，不复制源码、API 或目录。

参考：

- <https://nautilustrader.io/docs/latest/concepts/value_types/>
- <https://nautilustrader.io/docs/latest/concepts/instruments/>
- <https://nautilustrader.io/docs/nightly/concepts/instruments/crypto_perpetual/>
- <https://github.com/nautechsystems/nautilus_trader>

## 2. 主要结论

NautilusTrader 将 Price、Quantity、Money 建模为不可变专用值类型，以缩放整数提供确定的定点语义；Quantity 非负，Money 绑定 Currency。Instrument 以 `InstrumentId(symbol, venue)` 关联行情、订单、持仓和核算，并显式保存 precision、increment、multiplier、lot、费用和限额。

Precision 是可表达/展示的小数位数，Increment 是场所允许的最小变动，两者不能互相推出。例如 precision=2 时 tick 仍可能为 0.05。构造或提交边界必须分别校验。

数字资产合约必须显式保存 base、quote、settlement 和 inverse 语义。线性合约通常以 quote 结算；反向合约通常以 base 计价/结算；quanto 以第三种币结算。Funding 是随时间发生的数据，不应被写成静态 Instrument 常量。

Instrument 定义错误会导致截断、错误名义价值或回测接受实盘会拒绝的订单。因此定义必须版本化，回测按事件时点选择有效版本，而不是用今天的规格解释历史。

## 3. 对照与决策

| 领域概念 | MyQuant | NautilusTrader | OnlyAlpha | 迁移方式 |
|---|---|---|---|---|
| Price/Quantity | float | 不可变定点值类型 | `OnlyPrice`/`OnlyQuantity` | 重新实现，当前用 Decimal |
| Money/Currency | float，币种语义弱 | Money 强制绑定 Currency | `OnlyMoney`/`OnlyCurrency` | 采用币种校验 |
| Instrument ID | 拼接字符串 | Symbol + Venue 强 ID | `OnlyInstrumentId` | 采用思想 |
| precision/increment | 分散或隐含 | 独立字段和校验 | 独立字段 | 采用 |
| Equity | 通用股票代码 | 具体 Instrument | `OnlyEquity` | 采用；与账户权益分离 |
| Future/Option | 非核心 | 专用合约类型 | 专用占位类型 | 仅预留，不实现定价 |
| Crypto | 无 | Spot/Future/Perpetual 分型 | 三种专用类型 | 仅预留 |
| inverse/quanto | 无 | 显式币种和 inverse 语义 | 文档约束，后续 ADR | 延后实现 |
| Instrument 历史 | 无统一版本 | 定义事件含时间 | version/effective interval | 采用 |
| 序列化 | DataFrame/可变对象 | 精度元数据随数据保存 | Decimal 字符串 + Schema 版本 | 后续实现 |

## 4. 采用、适配和拒绝

采用：不可变值对象、Currency 绑定、强类型 ID、precision/increment 分离、显式合约乘数和结算币、Instrument 时间版本、边界拒绝非法值。

适配：初始 Python 骨架使用 `Decimal`，不立即实现 Rust 级缩放整数；等性能和范围有测量依据后再评估内部整数表示。OnlyAlpha 保留市场规则服务，A 股手数、T+1、涨跌停不进入通用 Instrument 或 Engine。

暂不采用：完整跨语言对象系统、所有衍生品类型、Nautilus API 兼容、通过 symbol 猜测合约类型、为未来性能提前引入 Rust。

## 5. 计算语义

- 线性合约名义价值通常是 `数量 × 价格 × 乘数`，盈亏以 quote/settlement 表达。
- 反向合约涉及价格倒数，盈亏币种和数量语义不同，不能复用线性公式。
- Quanto 还需要固定/动态换算因子和第三结算币。

这些公式本轮不实现；未来必须以合约规格和官方场所规则为输入，并用固定 Decimal 样例测试，不能只增加布尔标志后复用未经验证的公式。

## 6. 风险与测试策略

风险包括 Decimal context/舍入不一致、序列化丢失尾随精度、跨币种误加、历史规格缺失、动态 tick scheme、极值溢出、错误使用当前 Instrument 回测历史。

测试必须覆盖 precision 与 increment 的反例、Currency 不匹配、不可变/哈希、序列化往返、A 股/ETF/期货/期权/FX/数字资产样例、linear/inverse/quanto 计算、Instrument 有效期边界和极值。本轮骨架只实现并测试最小 Price、Quantity、Money、Currency 约束；其余是后续明确验收项。
