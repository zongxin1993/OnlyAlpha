# Market Conformance Suite

正式链路为 `Pack → OnlyMarketScenarioRunner → OnlyEngine → standard facts → coverage → stability/release gate`。首个
`GENERIC_T0_CASH` Engine Scenario 已可运行并用于自动化 Pack Runner 测试；CN A-share、Futures、Crypto 与 Cross-Version 的完整
capability packs 尚未全部建立，因此不得将内建 Profile 标为 Stable。

Conformance Pack 将 Profile 与版本化 Scenario 列表绑定。正式完成条件是 Synthetic Reference/Bar 与 Deterministic Action Strategy 经 `Historical Replay → Pipeline → Strategy → Risk → Virtual Broker → ExecutionProcessor → Results` 运行；禁止 Runner 直接构造成交或修改 Position/Account。

当前已实现 Pack/Scenario 身份、Capability coverage gate、Scenario Domain/Parser、runtime-neutral planning、Assertion Core 和
input fingerprint。正式 Action Strategy、Engine Runner、Artifact 及 A 股/T0/Futures/Crypto/跨版本 Packs 尚未实现，因此没有
Profile 被标为 Stable。
