# OnlyAlpha 工程交接说明

> 更新时间：2026-07-17（Asia/Shanghai）
> 当前分支：`master`
> 当前基线提交：`2334f38`
> 工作区：包含尚未提交的 Engine/Cluster Config/CLI/user_data/Examples 系统重构；不要清理或覆盖这些变更。

## 1. 新会话阅读顺序

1. `AGENTS.md` 与 `docs/architecture_principles.md`。
2. `docs/adr/0021-engine-cluster-cli-and-user-data-layout.md`。
3. `docs/cli.md`、`docs/cluster_configuration.md`、`docs/user_data.md`、`docs/output_layout.md`。
4. `docs/engine.md`、`docs/runtime.md`、`docs/cluster.md`。
5. `docs/adr/0020-cluster-strategy-factor-indicator-model.md` 与 Strategy/Factor/Indicator 文档。
6. `docs/integration_vertical_slice.md`。
7. `docs/reports/engine_cluster_cli_userdata_refactor_report.md`。

ADR 0019 已被 ADR 0021 Supersede（任务建议复用 0019，但该编号已有 Accepted 决策，因此使用连续编号 0021）。

## 2. 当前产品入口

OnlyEngine 是唯一产品级运行入口。CLI 固定流程：

```text
CLI
→ OnlyEngine(OnlyEngineConfig)
→ engine.add_cluster_from_file(path)
→ engine.add_cluster(OnlyClusterRunConfig)
→ engine.validate() / engine.run()
```

正式命令：

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml
```

双 Cluster：

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --config examples/clusters/macd_fast/config.yaml
```

Dry-run：

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run onlyalpha run \
  --config examples/clusters/macd/config.yaml \
  --dry-run
```

`--config` 可重复；另有 `--config-dir`、`--config-glob`、`--user-data`、`--engine-id`、`--log-level`、
`--fail-fast/--no-fail-fast`。路径顺序和去重确定，不依赖文件系统枚举顺序。

## 3. 单 Cluster 配置与 Engine

- 一个 YAML/JSON 文档只能定义一个顶层 `cluster`，禁止产品文档使用 `clusters[]`。
- 强类型入口为 `OnlyClusterRunConfig`；`OnlyRunConfig`/RunService 只作为 Runtime 内部兼容层和历史测试入口保留。
- `add_cluster_from_file()` 是文件适配器，核心业务位于 `add_cluster(config)`。
- Engine 提供 add/remove/start/pause/resume/validate/run/stop/snapshot 与不可变 Cluster Handle。
- 加载是事务性的：动态类、Factory 或资源校验失败会完整释放引用并恢复 Engine 状态。
- Backtest 回放中途动态 add/remove 当前明确返回结构化“不支持当前 Runtime 阶段”；启动前 add/remove 可用。

## 4. Runtime 与共享基础设施

Runtime Compatibility Key 包含 Runtime 类型、起止时间、Clock/Replay、Data Version、Broker 和 Account 环境。

兼容 Cluster 实际共享同一 Backtest Runtime、Synthetic Source、Virtual Broker 与 Account；不兼容配置创建独立 Runtime。
共享 Runtime 内 Order/Position/Account 仍是单写入者真值，Strategy、Factor、Indicator、Allocation、Ledger 和输出按 Cluster 隔离。

Infrastructure Registry 按 ID/Fingerprint 管理 Calendar、Instrument、DataSource、Broker、Account：

- 同 ID/同配置复用并增加引用计数；
- 同 ID/不同配置拒绝为 `RESOURCE_CONFIGURATION_CONFLICT`；
- 最后一个 Cluster 卸载后才释放资源。

双 Cluster 同 Bar 验证发现并修复 Virtual Broker 延迟 Snapshot 闭包读取未来账户状态的问题：现在成交时捕获不可变
Position/Account Snapshot，再按队列顺序发布。

## 5. user_data 与目录边界

根目录优先级：

```text
--user-data > ONLYALPHA_USER_DATA > cwd/user_data
```

正式布局为 `user_data/runs/<engine_id>/<run_id>/`，包含 manifest、engine、clusters、runtimes、shared、logs。
每个 Cluster 有独立配置、指纹、summary、orders、portfolio 和 report。输出路径/run_id 不进入业务确定性指纹。

`examples/` 当前只包含 README 和：

- `examples/clusters/macd/`
- `examples/clusters/macd_fast/`

Examples 无 Python 文件。示例 MACD Strategy/Factor 位于独立包 `plugins/onlyalpha_examples`；核心只保留通用 MACD Indicator。
原 Integration Demo 已迁到 `tests/integration_demo/`，运行入口为 `python -m tests.integration_demo.run_all`。

## 6. 完整交易链

```text
CLI → Engine → Cluster Config → Runtime Factory → shared Backtest Runtime
→ Synthetic HistoricalDataSource → Historical Replay → Backtest Clock
→ MarketData Processor/Pipeline → MACD Indicator → MACD Signal Factor → MACD Strategy
→ Order → Risk → Virtual Broker → Matching → Broker Inbound Queue
→ ExecutionProcessor → Position → Allocation → Strategy Ledger → Account
→ Engine Result → user_data
```

没有 CLI 手工装配、手工 Trade 或 Manager 旁路。

## 7. 当前验收基线

2026-07-17 最终实际结果：

- `pytest -q`：298 passed；
- `pytest -q tests/integration`：58 passed（最终全仓门禁已包含）；
- `python -m tests.integration_demo.run_all`：34/34 PASS；
- 双 Cluster 共享 Runtime 确定性重放：100/100 PASS；
- Engine 指纹：`defb427576b6603226ce8c240289f95b5200742fa738458340930ff10e6f9b53`；
- CLI 单 Cluster、多 Cluster、dry-run：全部成功；
- `ruff check .`：通过；
- `ruff format --check .`：467 files already formatted；
- `mypy src/onlyalpha`：293 source files，无问题。

验证脚本已更新为 `tests.integration_demo` 入口。测试是架构证据，不得删除、skip、xfail 或放宽正确预期。

## 8. 稳定边界

- Domain 不依赖 Runtime、Cluster、Gateway、DB、Web、Cache、EventBus 或 Backtest。
- UTC 是绝对时间真值；TradingDay/Session 必须由 Venue Calendar 解释。
- 金融数值使用强类型 Decimal 语义，Money 必须绑定 Currency。
- Runtime 是 Order/Risk/Position/Allocation/Ledger/Account/Execution 单写入者边界。
- Broker inbound queue 后只有 ExecutionProcessor 能编排交易状态。
- Cluster 是容器：一个 Strategy、零或多个 Factor；Factor 创建 Indicator 且不能交易。
- 新市场、策略、Factor、Indicator 不得要求 Engine/Runtime 识别具体算法。
- 所有非源码运行产物必须进入 user_data，不得写入 src/examples/tests。

## 9. 当前限制与后续建议

- Live/Paper/Research 类型存在，但真实行情、券商 SDK 和生产循环尚未接入。
- Backtest 回放中途动态 Warmup/安全卸载未实现；Live/Paper 的 CANCEL_AND_WAIT 等策略只有正式枚举/API。
- 多币种、保证金、Short/Hedging、公司行动、持久化恢复和分布式并发不在当前范围。
- 运行中动态 Cluster 是下一独立组件；不要绕过结构化不支持结果强行修改 Runtime 内部 Registry。
- 后续仍应优先推进配置驱动的多 Instrument/CrossSection Universe 装配，并复用当前 Engine/Registry/user_data 边界。

任何跨组件修改结束前继续运行：组件测试 → 直接集成 → 全仓 pytest → 34 场景 → 100 次重放 → Ruff/Format/Mypy，
并更新 ADR、组件报告和本文件。
