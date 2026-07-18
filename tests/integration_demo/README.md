# OnlyAlpha Integration Demo

`OnlyIntegrationEnvironment` 是所有场景共享的正式纵向集成环境。场景按编号顺序运行，后续场景复用并检查前序场景建立的
Runtime、Cluster、行情、订单、风控、持仓、Allocation、Strategy Ledger、Account 与事件状态，不得直接修改 Manager
内部容器。

运行完整场景：

```bash
uv run python -m tests.integration_demo.run_all
```

当前共 35 个场景。001-034 保留既有行情到资金账本的完整链路；035 使用安装后的独立测试 distribution，经真实 Entry
Point 发现 `test-external-data` 和 `test-external-broker`，并验证 Registry、Capability、Lifecycle、BrokerInboundQueue、
ExecutionProcessor 与 user_data 输出。外部服务边界由确定性的 Test DataSource/Test Broker 实现明确替代，核心交易链不使用
旁路或内部状态注入。
