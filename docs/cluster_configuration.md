# Internal Runtime Specification

`OnlyClusterRunConfig` 是 Kernel 内部 immutable typed composition value，显式携带 Runtime、Strategy Revision、Market Product、
reference data、universe、data source、account、broker、risk、time range、persistence/recovery 和 output semantics。

它不是用户配置文档，也不是 Product admission contract。`OnlyEngine.add_cluster(config)` 只供 Worker、Scenario、测试和明确的内部
composition owner 使用；Engine 不接受文件路径。

正式 Product Runtime creation 必须遵循：

```text
Web / Agent
→ versioned Product API request
→ validation and canonical domain specification
→ persistence / admission
→ scheduler / worker / internal typed composition
→ distinct Runtime instance identity and lifecycle
```

测试可以从 `tests/fixtures/` 解析 legacy JSON/YAML 以证明现有 Kernel semantics；这些 fixture 不进入 Product API，不成为
Runtime Authority。Deployment YAML/ENV 只允许配置 infrastructure，不允许隐式承载 Trading semantic configuration。
