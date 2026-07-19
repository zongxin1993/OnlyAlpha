# OnlyAlpha

OnlyAlpha 是一个独立开发的模块化量化交易核心，强调确定性、可测试边界和可扩展的多市场领域模型。当前采用模块化单体架构，以 `OnlyEngine` 统一协调 Runtime 与相互隔离的 Cluster。

Backtest、Paper、Live 和 Shadow 共用同一套版本化 Market Rules：必填 `market` → Profile Registry →
Compiler → `OnlyMarketRuleEngine` → 受限 Runtime Ports。市场制度不属于 Broker 或仿真专用配置。

## 三仓职责

- `OnlyAlpha`：核心框架、领域模型、运行时、内建基础实现和公共 SPI；
- `OnlyAlpha-plugins`：官方 Strategy、Factor、扩展组件、真实 DataSource、Broker 和 Cluster 配置；
- `OnlyAlpha-examples`：官方教程、示例入口、运行说明和生成结果。

三个项目独立发布，核心仓不反向依赖另外两个仓库。完整边界见 `docs/workspace_structure.md`。

## 当前能力

- 唯一产品链：CLI → `OnlyEngine` → `OnlyClusterRunConfig[]` → `OnlyRuntimePlanner` → `OnlyRuntimeSession` → `OnlyRuntime.run()`；
- Engine / Runtime / Cluster 生命周期、兼容性分组和多 Cluster 隔离；
- Strategy / Factor / Indicator 分层与受限 Runtime Context；
- Synthetic Historical Replay、Virtual Broker 和基础 Next-Bar 撮合；
- Risk、Order、ExecutionProcessor、Position、Allocation、Strategy Ledger 与 Account；
- DataSource / Broker Plugin SPI 和真实 Entry Point 发现；
- 单 Cluster、多 Cluster及固定输入的确定性重放。
- 标准回测事实、结构化诊断、FIFO Analytics、原子 JSON/Parquet Artifact、CLI/Console/Markdown Report 和三层内容指纹。

## 当前限制

已有 Tushare 日线与 CACHE_ONLY 示例，但尚未形成完整 A 股交易规则、复权与公司行为、完整费用税费和成交量约束。回测报告目前覆盖基础收益、FIFO 交易、回撤和交易统计，不包含高级风险、归因或图表。Paper、Live、Research 仍只有架构边界；测试不会连接真实券商或启动真实交易。

## 快速开始

最低 Python 版本为 3.12。在仓库根目录执行：

开发验证：

```bash
uv sync --dev
uv run onlyalpha --help
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

从 Workspace 根目录可使用 `uv run --directory OnlyAlpha pytest -q` 验证核心仓独立性。

## 文档入口

- 总体设计：`docs/architecture.md`
- Engine 与 Runtime：`docs/engine.md`、`docs/runtime.md`
- 插件边界：`docs/plugin_system.md`
- 工作区职责：`docs/workspace_structure.md`
- 测试规范：`docs/testing.md`
- 回测结果：`docs/results_framework.md`
- 路线图：`docs/roadmap.md`
- 架构决策：`docs/adr/`
