# ADR 0026: Unified Market Runtime Rules

- Status: Accepted
- Date: 2026-07-19
- Modules: config, market, runtime, risk, broker, execution, settlement, margin, result
- Supersedes in part: ADR 0024, ADR 0025

## Decision

OnlyAlpha 只保留一套 Market Rules。`market` 是 Backtest、Paper、Live 和 Shadow 的必填配置，不存在
`market_simulation` 或缺省 Legacy 路径。Runtime 模式只在数据源、Broker Gateway、时间驱动、外部状态权威和
失败模式上不同。

Profile family/version/registry/resolved profile 是版本化配置来源，不是 Runtime 组件依赖。Composition Root
按 Instrument Reference、Venue、Trading Day 和 Runtime Mode 调用 `OnlyMarketRuleCompiler`，得到不可变且可指纹的
`OnlyCompiledMarketRules`。`OnlyMarketRuleEngine` 是 Runtime 唯一市场规则入口，并按交易日缓存编译结果。

Runtime 组件只使用受限 Port：Risk 调用 Pre-Trade；Virtual Broker 调用 Match-Time 并仅应用
Settlement Instruction；ExecutionProcessor 消费 Trade/Position/Settlement/Margin/Fee/Cash Instruction；各 Manager
只维护状态；Collector 只读正式事实。

## Consequences

Profile 版本按 Trading Day 重新解析；编译指纹包含 Profile、Reference、Override、Instrument、Venue、Trading Day
和 Runtime Mode。不得在 Broker、Execution、Position 或 Account 中按 Profile ID、市场名或资产类别分支。

Scenario YAML DSL、Conformance Packs、US/HK packs、Tushare 自动 Profile 加载和 Web/CLI market commands 不在本次范围。
