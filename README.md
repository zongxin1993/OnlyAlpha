# OnlyAlpha

OnlyAlpha 是 MyQuant 的重构版本，目标是建设一个模块化、可扩展、可测试，并能够逐步支持多市场、多资产类别的量化交易与投研平台。

## 目录

```text
OnlyAlpha/
├── AGENTS.md
├── README.md
├── docs/
│   ├── architecture.md
│   ├── migration.md
│   ├── engine.md
│   ├── runtime.md
│   ├── cluster.md
│   ├── event.md
│   ├── instrument_model.md
│   ├── nautilus_research.md
│   ├── gateway.md
│   ├── storage.md
│   ├── research.md
│   ├── web_api.md
│   ├── concurrency.md
│   ├── coding_style.md
│   ├── testing.md
│   ├── roadmap.md
│   └── adr/
└── src/
```

当前仓库已包含 Phase 0 文档与 Phase 1 最小骨架。骨架不包含真实策略、撮合或券商连接，`OnlyLiveRuntime` 也不会启动真实交易。

开发验证：

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy
```

## 初始目标

第一阶段聚焦中国 A 股，但底层模型必须能够扩展到：

- 中国期货；
- 港股；
- 美股；
- 外汇；
- 期权；
- 数字货币现货；
- 数字货币交割和永续合约。

## 首次执行

Codex 首次进入工程时应：

1. 阅读 `AGENTS.md`；
2. 分析 `/home/zongxin/workspace/MyQuant`；
3. 研究 NautilusTrader 的资产和值对象设计；
4. 完成文档；
5. 创建最小可运行骨架；
6. 建立测试；
7. 暂不迁移真实交易功能。
