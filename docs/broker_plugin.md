# Broker Plugin SPI

外部 Broker Factory 实现 `OnlyBrokerGatewayFactory`，返回基于现有标准 Broker Ports 的 Gateway。Backtest Gateway 额外实现
确定性的 `on_bar()`/`run_due()` 驱动接口。CreateRequest 提供 Clock、EventBus、有界 BrokerInboundQueue、Runtime/Account
标识、初始资金、Logger，以及真实 side-effecting Broker 可要求的 Runtime-owned `OnlyBrokerCommandEvidenceStore`。该 Port
只保存 command protocol evidence，不拥有 Order projection truth；无需外部命令持久化的现有 Factory 可以忽略这个可选依赖。

Broker Capability 覆盖 submit/cancel/query/live/simulated execution。Backtest 在 create 前强制要求
`simulated_execution`。供应商对象必须在插件内转换为 `OnlyBrokerInboundUpdate`：

```text
Broker Plugin -> BrokerInboundQueue -> ExecutionProcessor -> Order/Position/Ledger/Account
```

插件不得直接访问或修改 Manager、Strategy、Factor 或 Cluster Pipeline。

生产 Broker Factory 必须通过 `onlyalpha.brokers` entry-point group 加载，并在配置校验阶段声明所需 capability 与 durability
依赖。Provider 凭据、endpoint、签名、错误码和 user stream wire contract 全部留在插件内；Core/Runtime 只消费 canonical
Broker Port、Update、receipt 与 readiness 语义。
