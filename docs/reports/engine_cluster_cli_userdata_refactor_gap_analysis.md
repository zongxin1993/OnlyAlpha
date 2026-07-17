# Engine、Cluster CLI 与 user_data 重构差距分析

## 当前事实

- 产品 CLI 为单值 `--config`，直接调用 `OnlyEngineRunService`。
- `OnlyRunConfig` 的一个文档可包含 `clusters[]`；Backtest Factory 当前只接受一个启用 Cluster。
- `OnlyEngine` 仅持有 Runtime 字典，不负责配置、Cluster 或共享资源生命周期。
- Runtime 结果输出默认使用 `root/engine_id/runtime_id/run_id`，尚无统一 `user_data/runs/...` 边界。
- 示例 Strategy/Factor 与 Integration Demo 位于 `examples/`。

## 复用边界

本次保留并复用已验证的 `OnlyEngineRunAssembler`、Runtime Factory、Cluster Factory、Synthetic
HistoricalDataSource、Virtual Broker、Historical Replay 与 Execution Processor。新 Engine 在这些正式接口之上协调
单 Cluster 配置，不复制或绕过交易链。

## 必须修复

1. 引入强类型 `OnlyClusterRunConfig`，拒绝 `clusters[]`，一个文档只解析一个 `cluster`。
2. CLI 支持重复 `--config`、稳定目录/Glob 展开、user_data、dry-run 与 fail-fast。
3. `OnlyEngine` 成为配置加载、Cluster 注册、Runtime 分组、共享资源冲突/引用计数和运行结果汇总入口。
4. 增加事务性 add/remove API 和结构化状态/结果；Backtest 运行中动态加入明确报告不支持。
5. 集中 user_data 路径与 Engine/Cluster 输出，不让 Runtime 或 CLI 拼路径。
6. 示例 Python Strategy/Factor 迁到独立插件包，产品配置迁到 `examples/clusters/`。
7. 增加单/多 Cluster、dry-run、资源冲突、引用计数、输出隔离和确定性测试。

## 有意保留的兼容层

`OnlyRunConfig` 与 `OnlyEngineRunService` 暂保留为 Runtime 装配内部兼容层及历史测试入口，但不再是 CLI 产品入口。
兼容层不得接受新的单 Cluster 产品文档，也不得被 CLI 直接调用。
