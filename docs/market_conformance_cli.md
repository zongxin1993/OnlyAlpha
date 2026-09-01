# Market Scenario Verification

Market Scenario 是 deterministic test harness，不是 Product CLI 或 Product API。验证通过 `pytest` 的 scenario/conformance lanes
执行；Parser、Planner、Runner、assertions 和 artifacts 仅证明 Kernel semantics、recovery 与 fail-closed behavior。

Scenario DataSource 不注册到默认 Product composition。Scenario runner 在验证边界显式注入 exact deterministic DataSource，避免
测试能力成为生产 Runtime admission 或第二 Product Authority。
