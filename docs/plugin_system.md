# OnlyAlpha Plugin System

OnlyAlpha 核心定义 DataSource/Broker 插件 SPI、API Version、Descriptor、Capability、Lifecycle、Registry 和 Entry Point
发现。外部插件只依赖 `onlyalpha.plugin.api` 及明确公开的领域/Port，不依赖 Engine、Runtime、Assembler 或 Manager 私有状态。

```text
Cluster Config
-> Plugin Descriptor
-> Factory Registry
-> Factory.parse_config()
-> Capability Validation
-> Factory.create()
-> Runtime lifecycle
```

内建 `synthetic`、`virtual` 与外部插件使用同一条链。Broker 回报只能进入 Runtime-owned 有界 inbound queue，再由
ExecutionProcessor 修改 Order/Position/Ledger/Account。核心不依赖 `OnlyAlpha-plugins`。

内建 `scenario-exact` 遵循相同 DataSource Factory、生命周期和 SPI，只提供 exact input，不建立第二套 Replay。
