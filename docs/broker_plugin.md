# Broker Plugin SPI

外部 Broker Factory 实现 `OnlyBrokerGatewayFactory`，返回基于现有标准 Broker Ports 的 Gateway。Backtest Gateway 额外实现
确定性的 `on_bar()`/`run_due()` 驱动接口。CreateRequest 只提供 Clock、EventBus、有界 BrokerInboundQueue、Runtime/Account
标识、初始资金和 Logger。

Broker Capability 覆盖 submit/cancel/query/live/simulated execution。Backtest 在 create 前强制要求
`simulated_execution`。供应商对象必须在插件内转换为 `OnlyBrokerInboundUpdate`：

```text
Broker Plugin -> BrokerInboundQueue -> ExecutionProcessor -> Order/Position/Ledger/Account
```

插件不得直接访问或修改 Manager、Strategy、Factor 或 Cluster Pipeline。
