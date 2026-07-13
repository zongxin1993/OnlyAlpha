# ADR-0006：MarketRule 分离与行情事实时间语义

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：domain.market_rules、domain.market、domain.catalog

## 背景

Conformance 扫描发现 Instrument 只能表达静态场所规格，无法独立组合 A 股 T+1、港股手数/价格阶梯、碎股、最低名义金额、费用和交易日历；旧 Bar/Tick 也缺少完整事件时间与数据类型语义。

## 决策

- Instrument 保持版本化产品规格；MarketRule 组合 lot、settlement、price limit、tick scheme、minimum notional、fee schedule 和 calendar。
- 订单验证是纯函数：显式接收 Instrument 与 OrderRequest，返回不可变 ValidationResult。
- QuoteTick 与 TradeTick 分型，共享 `ts_event`、`ts_init`、sequence 和 source。
- Bar 由 BarType/BarSpecification 标识，区间固定为 `[bar_start, bar_end)`，并保存事件/初始化时间、成交量维度、闭合状态、revision、adjustment、trading day 和 session。
- InstrumentCatalog 按 timezone-aware as-of 时间解析唯一有效历史版本。

## 结果

市场差异不会进入 Engine 或通用 Instrument 分支。规则对象可随历史时间独立版本化。Domain 只定义数据事实和纯校验，不实现行情订阅、撮合或完整 Bar 聚合器。

## 验证

`tests/domain_conformance` 验证依赖边界、十个市场、量化舍入、规则组合、Bar/Tick 时间语义、订单状态、PnL、序列化、历史版本、扩展性和确定性。
