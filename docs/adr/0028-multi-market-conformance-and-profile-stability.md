# ADR 0028: Multi-Market Conformance and Profile Stability

- Status: Accepted incrementally
- Date: 2026-07-19
- Modules: scenario, market.conformance, collector, artifact, application, cli

## Decision

Conformance Pack 是版本化 Scenario binding 与 capability requirement，不包含市场规则。Pack Runner 只能调用公开
`OnlyMarketScenarioRunner`；Scenario Runner 只能通过 `OnlyEngine` 装配正式 Runtime。Coverage 仅来自 required Scenario 的
正式 PASSED 结果。Stability Evaluator 只聚合 Profile、Pack run 和质量门禁，不运行 Scenario，也不修改 Registry。

Collector 只从正式 Manager snapshot、audit 和 Rule Engine query projection 生成事实；Assertion 不解释市场规则。CLI 只调用
Scenario Runner/Application Query，JSON DTO 不暴露 Path、Enum 实现或内部对象。BACKTEST 当前可自动执行；PAPER/LIVE/SHADOW
共享 Action/Command 但明确返回 capability error。

## Consequences

旧的“Scenario 名称即 coverage”与仅身份 Pack 被删除，不保留兼容分支。Profile 只有在 Pack、coverage、determinism、Artifact
和质量门禁全部通过后才有资格由源码变更设为 Stable。当前仍未通过完整 Futures/Cross-Version Pack 的 Profile 保持
Experimental。
