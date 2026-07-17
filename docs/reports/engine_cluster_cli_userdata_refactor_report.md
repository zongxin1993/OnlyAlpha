# Engine、Cluster CLI 与 user_data 重构验收报告

## 结论

**ACCEPTED**

## 修改前 CLI / 修改后 CLI

修改前是单值 `--config → OnlyRunConfig → OnlyEngineRunService`。修改后统一为：

```text
onlyalpha run --config <cluster-1> [--config <cluster-2> ...]
→ OnlyEngine.add_cluster_from_file
→ OnlyEngine.add_cluster(OnlyClusterRunConfig)
→ OnlyEngine.run
```

CLI 还支持稳定的 `--config-dir`/`--config-glob`、`--user-data`、`--engine-id`、`--log-level`、`--dry-run`、
`--fail-fast` 与 `--no-fail-fast`。CLI 不装配具体 Runtime、Broker、DataSource 或算法组件。

## 单 Cluster 配置模型与多配置加载

- `OnlyClusterRunConfig` 强制一个文档一个 `cluster`，拒绝 `clusters[]`。
- YAML/JSON 与 Mapping 均进入同一标准化/引用校验链。
- `add_cluster_from_file()` 只读取/解析并委托强类型 `add_cluster(config)`。
- 显式配置保持顺序，目录/Glob 稳定排序，绝对路径去重。

## OnlyEngine 公共接口与状态机

正式接口包含 add/add-from-file/remove/start/pause/resume/validate/run/stop/snapshot。状态覆盖
CREATED、CONFIGURING、READY、RUNNING、STOPPING、STOPPED、FAILED。Handle 只暴露 Cluster/Runtime ID、状态和配置指纹。

加载先获取资源、完成 Factory/动态类装配验证，再提交 Registry；任一步失败均释放引用并恢复原 Engine 状态。运行中 Backtest
动态加入返回带稳定 `code` 的 `OnlyClusterLoadError`；当前阶段不伪装支持历史回放中途 Warmup。卸载通过结构化结果和
`OnlyClusterRemovalPolicy`，首阶段正式支持 STOP_ONLY，其他策略明确报告当前阶段不支持。

## Runtime Compatibility、Registry 与资源复用

Compatibility Key 包含 Runtime 类型、起止时间、Clock/Replay、Data Version、Broker 与 Account 环境。兼容的两个 MACD
Cluster 被合并到同一个 Backtest Runtime，实际复用同一 Synthetic Source、Virtual Broker、Account 与 Runtime 单写入者状态域；
Strategy、Factor、Indicator、Allocation、Ledger 和输出保持 Cluster 隔离。不兼容配置创建不同 Runtime。

Infrastructure Registry 管理 Calendar、Instrument、DataSource、Broker、Account 的 ID/Fingerprint。相同配置引用计数增加；
同 ID/不同配置返回 `RESOURCE_CONFIGURATION_CONFLICT`；卸载到最后一个引用时才释放。

## user_data 与 Output Layout

根目录优先级为 `--user-data > ONLYALPHA_USER_DATA > cwd/user_data`。`OnlyUserDataLayout` 与
`OnlyEngineResultExporter` 集中生成 `runs/<engine>/<run>/engine|clusters|runtimes|shared|logs`。每个 Cluster 有 source config、
normalized config、fingerprint、summary、orders、portfolio 与 report。run_id 唯一，绝对路径不进入业务指纹。

## Examples 清理与示例插件包

- `examples/` 只保留 README、`clusters/macd` 与 `clusters/macd_fast` 配置/合成市场文件；无 Python 文件和运行产物。
- MACD Strategy/Factor 迁入独立 editable 包 `plugins/onlyalpha_examples`。
- 核心仅保留通用 MACD Indicator。
- 原 Integration Demo 迁到 `tests/integration_demo`；其他仍有验证价值的 fixtures/support 迁到 tests。

## Synthetic、Virtual Broker 与完整交易链

单/双 Cluster 均通过正式链：Engine → Runtime Factory → Synthetic HistoricalDataSource → Replay/Clock → Pipeline → MACD
Indicator → Factor → Strategy → Risk/Order → Virtual Broker/Matching → Inbound Queue → ExecutionProcessor → Position/Allocation
→ Ledger/Account → Engine Result → user_data。未手工制造 Trade，未绕过 Manager。

多订单同一 Bar 暴露并修复了一个 Virtual Broker Snapshot 时序缺陷：延迟发布闭包此前读取“发布时”的最新账户状态，可能让早期
Trade 后的 Snapshot 包含后续 Trade。现在在成交时捕获不可变 Position/Account Snapshot，再按队列顺序发布。

## 测试、Vertical Slice 与确定性

- 新增 Config/Engine/CLI/Output/Product Integration 测试；事务回滚、重复 ID、资源冲突、引用计数、dry-run、路径优先级、
  单/双 Cluster、共享 Runtime、结果隔离和输出路径均覆盖。
- 全仓：`298 passed`。
- Integration：`58 passed`（并被最终全仓门禁覆盖）。
- Vertical Slice：34/34 PASS，入口为 `python -m tests.integration_demo.run_all`。
- 双 Cluster 同一共享 Runtime 重放：100/100 PASS，Engine 指纹
  `defb427576b6603226ce8c240289f95b5200742fa738458340930ff10e6f9b53`。
- 正式 CLI 单 Cluster、多 Cluster、dry-run 均成功。
- `ruff check .`、`ruff format --check .`（467 files）、`mypy src/onlyalpha`（293 files）均通过。

## Placeholder / Fake

没有新增未标明 Fake。Synthetic HistoricalDataSource 与 Virtual Broker 是正式、确定性的产品替身；Live/Paper 真实 SDK 仍未接入。

## 已知限制

- Backtest 回放中途动态加载/卸载不安全，当前返回结构化不支持；启动前 add/remove 完整可用。
- STOP_ONLY 之外的 Live/Paper 撤单等待策略只有正式枚举/API，尚无真实 Broker 生命周期实现。
- Live/Paper/Research 生产循环、多币种、保证金、Short/Hedging、持久化恢复不在本任务范围。
- `OnlyRunConfig`/`OnlyEngineRunService` 暂作为 Runtime 内部兼容层和历史测试入口保留，不再是 CLI 产品入口。

## 一票否决项审计

重复 `--config`、单 Cluster 文档、CLI→Engine、强类型 add、remove、事务回滚、资源冲突/引用计数、user_data、Examples
清理、插件迁移、Synthetic/Virtual Broker/ExecutionProcessor、双 Cluster 隔离、历史回归和确定性重放均通过；未触发一票否决项。
