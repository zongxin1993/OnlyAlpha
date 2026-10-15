# DataSource Plugin SPI

外部 DataSource Factory 实现 `OnlyDataSourceFactory`：提供 Descriptor，解析自身 `extensions`，校验
`OnlyDataSourceCreateRequest`，创建实现 `OnlyDataSource` 的资源。CreateRequest 只提供 Clock、EventBus、Instrument/Calendar
映射、Universe/Coverage、Runtime/DataVersion、配置目录和 Logger，不暴露 Engine 或 Runtime 容器。

Capability 包含 historical/live bar/tick 与 reference data 能力。Backtest 在 create 前强制要求 `historical_bars`。
内建 Synthetic 的市场文件和随机种子只由其 Factory 解析，通用配置 Parser 不理解这些字段。


`OnlyMarketDataInboundUpdate.ingress_observation` and `OnlyRealtimeBarPreviewV1.ingress_observation` optionally carry
`OnlyRealtimeIngressObservation`: the producer runtime identity, actual nullable provider event UTC ns and actual nullable ingress UTC ns
for that same native inbound occurrence. This is ephemeral display telemetry, excluded from canonical update equality, serialization,
identity, WAL and replay. Normalized/clamped fact timestamps are not substitutes. Providers attach it only to the actual incoming
occurrence after durable admission; recovered siblings, historical reconstruction, derived outputs and new occurrences must not inherit it.
The Product projection verifies its producer runtime and exact native source/instrument/bar type against its stream session. Consumers
must not use it as ordering, research, strategy, risk or trading input. Missing observation does not invalidate an otherwise valid fact.
