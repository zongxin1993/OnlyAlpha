# OnlyAlpha

OnlyAlpha 是一个独立开发的模块化量化交易核心，强调确定性、可测试边界和可扩展的多市场领域模型。当前采用模块化单体架构，以 `OnlyEngine` 统一协调 Runtime 与相互隔离的 Cluster。


## 工程结构



## 当前能力



## 快速开始

最低 Python 版本为 3.12。在仓库根目录执行：

开发验证：

```bash
uv sync --all-packages --all-groups
uv run onlyalpha --help
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
```

## 文档入口

- 总体设计：`docs/architecture.md`
- Engine 与 Runtime：`docs/engine.md`、`docs/runtime.md`
- 插件边界：`docs/plugin_system.md`
- 工作区职责：`docs/workspace_structure.md`
- 测试规范：`docs/testing.md`
- 回测结果：`docs/results_framework.md`
- 路线图：`docs/roadmap.md`
- 架构决策：`docs/adr/`
