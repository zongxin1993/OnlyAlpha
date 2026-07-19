# ADR 0027: Deterministic Multi-Market Scenario Framework

- Status: Accepted incrementally
- Date: 2026-07-19
- Modules: scenario, config, engine, result, artifact

## Decision

Scenario 是 `OnlyEngine` 外层的确定性验证设施，不是第二套 Runtime。Scenario Document 只描述人工 Reference、人工 Market
Data、运行模式无关 Action 和 Expected Fact。Parser 复用正式 Market Config 与 Reference 解析语义；Planner 将 Action 投影为
相同 Command DTO；Runner 只能通过 Engine、Planner、Assembler、Runtime Factory 和 `Runtime.run()` 执行。

市场规则仍只有 `OnlyMarketRuleEngine` 一套。Synthetic 只表示输入人工构造。Assertion 只比较标准事实，不计算 T+1、费用、
保证金、撮合或其他制度。PAPER/LIVE/SHADOW 在自动执行能力完成前可解析和规划，但必须显式返回 capability error，不能降级为
BACKTEST。

## Consequences

Scenario 包不得依赖 Manager concrete class、Broker fill constructor 或 Backtest 私有 Context。交易内核缺口在 Position、Margin、
Account、ExecutionProcessor 或 Collector 修复。A 股、T0 Cash、Futures、Crypto Spot 使用同一 Domain/Action/Assertion；市场差异
只能来自 Profile、Reference 和正式 Runtime facts。

当前增量已交付 Domain、严格 Parser、runtime-neutral planning、Assertion 和 fingerprint；Engine Runner、Action Strategy、全量
Collector/Artifact 与五个正式场景仍是明确未完成门禁，不因本 ADR 的 Accepted 状态而被视为生产支持。
