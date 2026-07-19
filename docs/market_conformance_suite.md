# Market Conformance Suite

Conformance Pack 将 Profile 与版本化 Scenario 列表绑定。正式完成条件是 Synthetic Reference/Bar 与 Deterministic Action Strategy 经 `Historical Replay → Pipeline → Strategy → Risk → Virtual Broker → ExecutionProcessor → Results` 运行；禁止 Runner 直接构造成交或修改 Position/Account。

当前已实现 Pack/Scenario 身份和 Capability coverage gate；Scenario DSL、正式 Engine Runner、Assertion Engine 及 A 股/T0/Futures/Crypto/US/HK Packs 尚未实现，因此没有 Profile 被标为 Stable。

