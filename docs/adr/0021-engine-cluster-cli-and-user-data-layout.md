# ADR 0021: Engine、单 Cluster 配置、CLI 与 user_data

- Status: Accepted
- Date: 2026-07-17
- Modules: cli, engine, config, runtime, output, examples, plugins
- Numbering: 任务建议使用 0019，但 0019 已是 Accepted 决策；本 ADR 使用下一个连续编号并 Supersede 0019 的产品入口/输出部分。

## Context

原 CLI 以单个 `OnlyRunConfig(clusters[])` 直接调用 RunService；Engine 主要管理 Runtime；Examples 中有大量 Python
Demo，输出缺少统一 user_data 边界。该结构不能让一个 Engine 从多个独立 Cluster 文档协调生命周期与资源。

## Decision

- 一个配置文件定义一个 Cluster，产品类型为 `OnlyClusterRunConfig`；旧 `OnlyRunConfig` 只保留为 Runtime 内部兼容 DTO。
- CLI 支持重复 `--config`，只构造 OnlyEngine 并调用其公共接口。
- OnlyEngine 是唯一产品入口，管理 Cluster Handle、状态、Runtime 兼容性规划与运行汇总。
- `add_cluster(config)` 是核心接口；`add_cluster_from_file(path)` 是文件适配器。
- Engine 提供动态 add/remove/start/pause/resume API。首阶段 Backtest 回放中动态变更返回明确不支持状态。
- 加载按事务执行；资源冲突或注册失败释放已经获取的引用，不留下活动 Cluster。
- Calendar、Instrument、DataSource、Broker、Account 由 Infrastructure Registry 按 ID、Fingerprint 和引用计数协调。
- 相同 ID/相同配置复用逻辑资源；相同 ID/不同配置返回 `RESOURCE_CONFIGURATION_CONFLICT`。
- Runtime 使用包含类型、时间、Clock/Replay、Data Version、Broker/Account 环境的 Compatibility Key 分组。
- 所有产品产物统一写入 `user_data/runs/<engine>/<run>/...`，Cluster 是一级结果边界。
- Examples 只保留 Cluster 配置和 README；示例 Strategy/Factor 位于独立 `onlyalpha_examples` 插件。
- 回测继续使用正式 Synthetic Source、Historical Replay、Virtual Broker Queue 和 ExecutionProcessor 链。

## Rejected alternatives

- CLI 直接调用 Backtest RunService 或创建 Runtime/Broker/DataSource；
- 一个文档定义整个 Engine 的多个 Cluster；
- Engine 只保存 Runtime 字典；
- 运行时卸载直接删除 Cluster 对象；
- 后加载资源覆盖同 ID 的已有配置；
- 每个组件自行拼接输出路径；
- Examples 保留 Python 产品脚本；
- 将示例 Strategy/Factor 放入核心包；
- 为新入口复制或绕过现有交易链。

## Consequences

产品入口是破坏性变更，但底层 `OnlyRunConfig`/RunService 兼容层暂保留以保护 Runtime 测试。Compatible Backtest Cluster
共享同一 Runtime 和 Gateway；不兼容配置使用独立 Runtime。Live/Paper 安全动态撤单/等待属于后续实现。

## Validation

单/多 Cluster CLI、dry-run、资源冲突、引用计数、输出隔离、完整 Synthetic/Virtual Broker 回测、历史 Vertical Slice、
100 次确定性重放、全仓 Pytest、Ruff、Format 与 strict Mypy 共同验证。
