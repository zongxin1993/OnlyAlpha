# Deterministic Multi-Market Scenario Framework 修改前审计

日期：2026-07-19。结论来自当前源码，不以旧提示或旧交接声明代替实现证据。

## 正式执行链

```text
OnlyClusterRunConfig
→ OnlyEngine.add_cluster
→ OnlyRuntimePlanner.plan
→ OnlyEngineRunAssembler.build
→ OnlyRuntimeFactoryRegistry
→ OnlyBacktestRuntimeFactory.create
→ OnlyBacktestRuntime.run
→ OnlyBacktestRunPlan.execute
→ Historical DataSource / Replay / MarketDataProcessor / Pipeline
→ Cluster / Factor / Strategy / ctx.orders
→ Risk / Virtual Broker / inbound queue / OnlyExecutionProcessor
→ Position / Allocation / Ledger / Account / Settlement / Margin
→ OnlyBacktestResultCollector
→ OnlyBacktestResult / Analytics / Artifact Writer
```

`OnlyEngine.run()` 是产品纵切面。`OnlyBacktestRuntime.process_bar()` 是单记录正式 Replay facade，但不能代替 Scenario
Runner 的 Engine 验收。

## 可复用能力

- `OnlyInMemoryHistoricalDataSource`、内建 Synthetic DataSource 与 Historical Replay；
- `OnlyInMemoryReferenceDataSource`、正式 `OnlyInstrument`/`OnlyTradingCalendar`；
- Strategy/Factor/Cluster Factory、Runtime Factory Registry、Planner 与 Assembler；
- `OnlyBacktestResult`、标准 Result records、Collector、Analytics 和 Artifact Writer；
- `OnlyMarketProfileRegistry`、Compiler、`OnlyMarketRuleEngine`；
- Conformance Pack/Scenario 的身份和 capability coverage gate。

## 修改前缺失能力

修改前不存在产品级 Scenario Domain、Parser、Planner、Action port/strategy、Runner、Assertion、Scenario Artifact 和
Scenario fingerprint。Collector 也未完整投影 profile timeline、compiled identity、market decisions、settlement、margin、
fee accumulator。现有 Config Instrument parser 只装配 Equity/ETF，尽管 Domain 已有 Futures/Crypto 类型。

## 错误、重复或边界问题

- `tests/integration_demo` 大量直接驱动 `runtime.process_bar()`：保留为组件/历史纵切面测试，但不得充当新 Scenario Runner；
- production 包中的 `OnlyNoOpExecutionReconciliationPort` 无任何调用方且注明 test-only：删除实现和公开导出；
- 旧报告仍保留 `market_simulation` 历史叙述：仅作为审计记录保留；产品 Config 已明确拒绝旧 key；
- Assertion 不得读取 Manager 或按 profile 重算规则；缺事实应修 Collector；
- 不得将现有 Conformance 身份模型描述为可运行的 Conformance Pack。

## 任务 1 未收口

- Futures HEDGING 双向 Position 与正式 SELL OPEN/BUY CLOSE 纵切面未完成；
- Margin 尚未与 Account 形成完整事务链；
- Collector 缺完整 Profile timeline、compiled identity、market decision、settlement、margin 和 fee 投影；
- Profile 按 Trading Day 解析已在 Rule Engine 中存在，但标准 timeline 尚未封存；
- Generic Futures/Crypto 的 Domain/Profile 存在不等于产品 Config、Runtime 和 Engine 已正式支持。

这些缺口必须在正式组件修复，Scenario 层不会伪造 Fill、Position、Margin、Settlement 或 Fee。
