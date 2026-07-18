# OnlyAlpha 工程交接说明

> 更新时间：2026-07-18（Asia/Shanghai）
> 当前分支：`master`
> 工作区：包含未提交的 Engine/配置/输出接口唯一性清理和此前用户变更；不要清理或覆盖。

## 1. 必读顺序

1. `AGENTS.md`、`docs/architecture_principles.md`。
2. `docs/architecture/interface_uniqueness.md`、`docs/workspace_structure.md`。
3. `docs/adr/0021-engine-cluster-cli-and-user-data-layout.md`。
4. `docs/engine.md`、`docs/runtime.md`、`docs/cluster_configuration.md`、`docs/output_layout.md`。
5. `docs/integration_vertical_slice.md`、`docs/reports/post_refactor_cleanup_report.md`。

## 2. 唯一产品入口

```text
CLI
→ OnlyEngine(OnlyEngineConfig)
→ add_cluster_from_file()/add_cluster()
→ validate()/initialize()/start()/run()/stop()
→ OnlyUserDataLayout
```

不存在字符串 Engine 构造、外部 Runtime 注册入口、Runtime 级产品 RunService、旧多 Cluster 产品配置或独立 Runtime 输出器。
Engine 实例只能运行一次；`STOPPED`/`FAILED` 后需创建新实例。

## 3. 配置与输出

- 一个文档只定义一个 `OnlyClusterRunConfig`；多 Cluster 使用多个配置文件。
- DataSource/Broker 唯一插件字段为 `plugin`；`type` 只允许作为 `runtime.type` 或组件 extensions 内部字段。
- `OnlyOutputConfig` 只含 `formats`、`overwrite`。
- 产品输出固定为 `<user_data_root>/runs/<engine_id>/<run_id>/`，只经 `OnlyUserDataLayout`。

## 4. 三项目边界

- `OnlyAlpha`：核心库、CLI、Domain、Engine/Runtime/Cluster 容器、通用端口和基础设施；不得包含示例专用策略或配置。
- `OnlyAlpha-examples`：示例专用 Strategy/Factor、示例 Cluster 配置、教程和工作流；只消费公开 API。
- `OnlyAlpha-plugins`：可复用或面向产品的 Strategy/Factor/扩展与 DataSource/Broker 适配器；不得导入核心私有 Manager。

依赖方向为 `OnlyAlpha-examples → OnlyAlpha-plugins → OnlyAlpha`（示例也可直接依赖核心），核心不得反向依赖。当前 examples
含 MACD 示例代码和配置；plugins 尚无实际实现。迁移时按“示例专用留 examples、可复用进 plugins”，禁止复制源码跨仓。

## 5. 当前验证基线

- 全仓 Pytest：335 tests 通过。
- Integration Demo：35/35 PASS。
- 100 次确定性重放：通过。
- 单 Cluster、多 Cluster CLI：COMPLETED。
- Core dry-run 与 OnlyAlpha-examples 配置 dry-run：valid=true。
- Ruff check/format：通过。
- Mypy：305 source files，无问题。

## 6. 稳定架构边界

- Runtime 是 Order/Risk/Position/Allocation/Ledger/Account/Execution 单写入者边界。
- Cluster 是一个 Strategy、零或多个 Factor 的隔离容器；Factor 创建 Indicator 且不能交易。
- Broker 回报只通过有界队列与 ExecutionProcessor 改变交易状态。
- 所有非源码产物进入 user_data；核心测试产物使用临时目录。
- 同一能力只能有一个公开接口、一个生命周期、一个 Factory/Registry 创建路径和一个输出路径。

后续跨组件修改继续执行：组件测试 → 直接集成 → 全仓 Pytest → Integration Demo → 100 次重放 → CLI → Ruff/Format/Mypy，
并更新 ADR、集成报告和本文件。
