# Domain Conformance 初始差距报告

> 本文件保留测试优先修复前的扫描基线。修复后的权威结果见
> `examples/domain_conformance/reports/domain_conformance.md`：97/100、无一票否决项。

- 扫描日期：2026-07-13
- 扫描范围：`src/onlyalpha/domain`、现有 Domain 单元测试、Domain/Instrument/架构 ADR 文档
- 阶段：修复前基线

## 结论

当前 Domain 具有良好的纯依赖边界、Decimal 值对象、强类型 ID、跨市场 Instrument 基础分型和不可变订单快照，但尚未满足 `prompts/domain_conformance.md`。估算基线为 **58/100**，存在“Bar 没有完整明确时间语义”一票否决项，不建议进入 Runtime 或 Backtest。

## 基线评分

| 维度 | 得分 | 满分 | 差距 |
|---|---:|---:|---|
| Domain 依赖纯净 | 10 | 10 | 已有 AST 边界测试 |
| 金融值对象与精度 | 13 | 15 | 缺少明确排序 API/量化策略 |
| Instrument 描述能力 | 12 | 15 | 缺 activation/status/timezone/calendar 引用和完整场景证明 |
| Precision 与 Increment | 4 | 10 | 只有校验，没有显式舍入量化 |
| MarketRule 分离 | 0 | 10 | MarketRule、Lot、Price Ladder、Fee、Settlement 均缺失 |
| Bar 与时间语义 | 3 | 15 | 无 BarSpecification、事件/初始化时间、修订、调整和 session 语义 |
| Order/Trade/Position | 5 | 8 | 状态机存在；缺 position 今昨仓/冻结量和幂等回报语义 |
| 序列化无损 | 4 | 5 | 基础递归序列化存在；缺新增类型与子类型系统验收 |
| 历史版本能力 | 1 | 4 | Instrument 有有效区间，但无纯历史查询集合和规则版本查询 |
| 可扩展性 | 2 | 3 | Instrument 可继承，但缺 OnlyBond 验收 |
| 确定性与基础一致性 | 4 | 5 | Decimal/JSON 确定；缺 fee/PnL/quantize 场景 |
| **总分** | **58** | **100** | 原型级，不应继续上层建设 |

## 一票否决项

- **存在**：`OnlyBar` 只有 start/end，没有独立 `ts_event`、`ts_init`、闭合状态、revision、trading_day、session 和明确 `[start, end)` 规格。

其余一票否决项当前未发现：Domain 无外层 import；值对象拒绝 float；Money 跨币种相加失败；Bar 有 InstrumentId；期货有 multiplier；Crypto 区分 linear/inverse；Instrument 有版本与有效时间。

## 必须先写失败测试的缺口

1. `OnlyInstrument.quantize_price/quantity` 必须显式接收 Decimal rounding mode。
2. `OnlyMarketRule` 组合对象必须支持 lot、settlement、price limit/ladder、minimum notional、fee 和 calendar，且同一 Equity 可应用不同规则。
3. `OnlyBarSpecification`、`OnlyBarType` 和完整 `OnlyBar` 时间/成交量/修订语义。
4. `OnlyQuoteTick` 与 `OnlyTradeTick` 必须分型并包含 event/init 时间、sequence、source。
5. `OnlyInstrumentCatalog` 必须按历史时点解析 Instrument 版本；FeeSchedule 同样有有效区间。
6. Position 必须能表达 total/available/frozen、today/yesterday、settlement currency 与 margin mode。
7. 十个目标市场的独立 scenario 必须不依赖 Engine/Gateway，并完成规则验证和序列化。
8. `OnlyDomainConformanceScore/Report`、CLI Demo 和 JSON/Markdown 报告必须可重复生成。

## 明确不在本任务实现

Engine、Runtime、Gateway、Web、Database、Storage、完整 Backtest、撮合、真实交易、外部行情、完整订单事件溯源。Conformance 场景只使用纯 Domain 对象和确定性输入。
