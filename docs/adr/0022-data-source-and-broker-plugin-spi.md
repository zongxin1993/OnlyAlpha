# ADR 0022: DataSource 与 Broker Plugin SPI

- Status: Accepted
- Date: 2026-07-18
- Modules: plugin, config, data, broker, runtime, engine, cli
- Numbering: 任务指定 0020，但该编号已用于 Cluster/Strategy/Factor/Indicator；因此使用下一个可用编号 0022。

## Context

原 DataSource/Broker Registry 只有 factory_id/create，配置以 type 选择，内建 Factory 返回具体配置，Runtime 再硬编码
Virtual Gateway。该边界无法支持独立外部插件、版本兼容、Capability dry-run、统一生命周期或可靠失败回滚。

## Decision

- 定义稳定 `onlyalpha.plugin.api`、Plugin API 1.0、Descriptor、结构化错误、Capability、Lifecycle 和 Health；
- 使用 `onlyalpha.data_sources`/`onlyalpha.brokers` Entry Point，确定性发现；
- 内建与外部插件统一通过现有 DataSource/Broker Factory Registry；
- 核心只解析 `plugin` 和公共字段，Factory 独占 extensions 解析；
- Runtime 启动前校验 Capability，并管理 initialize/connect/start/stop/close 与逆序回滚；
- Broker 回报继续只进入 BrokerInboundQueue 和 ExecutionProcessor；
- Engine Snapshot 和 dry-run 展示插件来源、版本、API、Capabilities、绑定、状态、Health 与引用计数。

## Rejected Alternatives

- 在 RuntimeAssembler 中硬编码 QMT/CTP/IBKR；
- DataSource/Broker 使用任意 class_path；
- 外部插件访问 Engine/Runtime 私有容器或 Manager；
- Broker 直接修改 Position/Ledger/Account；
- DataSource 与 Broker 使用两套发现机制；
- OnlyAlpha 核心依赖 OnlyAlpha-plugins。

## Consequences

插件配置统一使用 `plugin`；`type` 仅兼容到 0.2。Backtest Factory 负责基于明确 Runtime Plan 解析/校验/创建插件，Runtime
独占资源生命周期。真实 Broker/DataSource 仍由外部仓库实现。
