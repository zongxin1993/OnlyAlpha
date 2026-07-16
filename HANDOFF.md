# OnlyAlpha 工程交接说明

> 更新时间：2026-07-16（Asia/Shanghai）
> 当前分支：`master`
> 当前基线提交：`a95d584`
> 工作区：包含尚未提交的 Cluster/Strategy/Factor/Indicator 架构重构；不要清理或覆盖这些变更。

## 1. 新会话阅读顺序

1. `AGENTS.md`：强制边界、Only 命名、文档、ADR 和 Vertical Slice 验收政策。
2. `docs/architecture_principles.md` 与 `docs/architecture.md`：当前稳定架构不变量。
3. `docs/adr/0020-cluster-strategy-factor-indicator-model.md`：本轮策略计算体系决策。
4. `docs/cluster.md`、`docs/strategy.md`、`docs/factor.md`、`docs/indicator.md`。
5. `docs/factor_pipeline.md`、`docs/indicator_registry.md`、`docs/cluster_lifecycle.md`、`docs/runtime_context.md`。
6. `docs/integration_vertical_slice.md` 与最新组件报告。

不要从旧报告或 roadmap 单独推断现状；工程代码、Accepted ADR 和本文件是当前入口。

## 2. 当前总体架构

OnlyAlpha 是模块化单体和 Pure Financial Domain 量化系统。当前正式关系为：

```text
OnlyEngine
└── many isolated OnlyRuntime
    └── many isolated OnlyCluster
        ├── exactly one OnlyStrategy
        ├── zero or more OnlyFactor
        │   └── one or more OnlyIndicator for computational Factors
        └── Cluster-scoped lifecycle, subscription and pipeline
```

固定计算/交易链：

```text
Run Config
→ Runtime/Cluster/Strategy/Factor Factory
→ Historical Replay
→ MarketData Pipeline + immutable Snapshot
→ Cluster Indicator Registry
→ Indicator
→ Factor dependency graph
→ Required Factor ready gate
→ Strategy
→ ctx.orders.submit
→ Risk
→ Virtual Broker
→ Execution Processor
→ Order / Position / Allocation
→ Strategy Ledger / Account
→ Event / Snapshot / Result
```

Cluster 是容器，不是策略。Strategy 读取 Factor 并拥有受限交易能力；Factor 组合 Indicator 但没有 orders/position/ledger/account/risk mutation；Indicator 是无交易副作用的底层计算单元，不接收 Runtime Context。

## 3. 本轮已完成内容

- 新增正式 `OnlyStrategy`、`OnlyTimeSeriesFactor`、`OnlyCrossSectionFactor`、统一 `OnlyIndicator` 抽象。
- 新增 Strategy/Factor/Indicator Config、Factory、Registry、强类型 ID、Snapshot、Score。
- Factor DAG 拒绝未知依赖、循环和非法阶段依赖；Cluster Pipeline 固定 `Indicator → Factor → Strategy`。
- Indicator 实例按 Runtime/Cluster/Factor/Indicator Scope 隔离；Factor 初始化时通过 Registry 创建。
- CrossSection Context 提供同一时点、稳定排序、expected/missing member 的不可变 Universe Snapshot。
- 标准库包含 MACD、RSI、EMA、SMA、ATR、Bollinger、Rolling Return、Rolling Volatility、ZScore。
- Runtime/Assembly 不再识别具体指标；Bar Subscription 不含 `indicator_ids`；Strategy Factory 不创建 Indicator。
- 通用 Result 改为 Strategy extension、Factor results 和 Indicator diagnostics，不写死 MACD。
- MACD Signal Factor 和 Strategy 已迁至 `examples/factors/`、`examples/strategies/`；核心只保留通用 MACD Indicator。
- Product 配置迁至 `examples/configs/backtest/macd/`，通用入口为 `examples/run.py`。
- ADR 0020、差距分析、架构文档和最终验收报告已更新。

## 4. Product MACD 当前事实

运行：

```text
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python -m examples.run --config examples/configs/backtest/macd/run.yaml
```

当前确定结果：

- Status：`COMPLETED`
- Generated/processed bars：720
- Orders/Trades：2/2
- Final equity：`998958.00 CNY`
- Determinism fingerprint：`bcc238d9724e49801a7ed4f148e3f3b64dad2da5bc827d0138a09e636b1a1d13`

完整配置链使用 Synthetic Historical Data Source、Next-Bar Virtual Broker、Risk、Execution Processor、Position、Allocation、Strategy Ledger 和 Account；没有真实交易或手工 Manager 旁路。

## 5. 当前测试与验收基线

2026-07-16 实际运行 `scripts/run_component_validation.sh`：

- `pytest -q`：282 passed；
- `pytest -q tests/integration`：55 passed；
- `python -m examples.integration_demo.run_all`：34/34 PASS；
- Product MACD replay：基线 + 100 次一致；
- Full Vertical Slice replay：基线 + 100 次一致；
- `ruff check .`：通过；
- `ruff format --check .`：526 files already formatted；
- `mypy src/onlyalpha`：289 source files，无问题。

运行 `uv` 时继续使用 `UV_CACHE_DIR=/tmp/onlyalpha-uv-cache`。测试是架构证据，不得删除、skip、xfail 或放宽正确预期。

## 6. 稳定边界

- Domain 不依赖 Runtime、Cluster、Gateway、DB、Web、Cache、EventBus 或 Backtest。
- 金融数值使用强类型 Decimal 语义；Money 绑定 Currency；不要在核心交易中使用裸 float。
- UTC 是绝对时间真值；TradingDay/Session 必须由 Venue Calendar 解释，不能对 UTC/local timestamp 直接 `date()`。
- Runtime 是 Order、Risk、Position、Allocation、Ledger、Account 与 Execution 的单写入者边界。
- Broker inbound queue 后只有 Execution Processor 能编排交易状态；Event 表达成功后的事实，不驱动状态机。
- Account Position = Cluster Allocation Sum + Unallocated；Cluster 不能卖其他 Cluster Allocation；A 股 T+1 由规则/Calendar 表达。
- Strategy Context 不暴露 Indicator mutation/Manager/Broker/EventBus；Factor Context 不暴露任何交易 mutation。
- 新市场、策略、Factor 或 Indicator 不得修改 Engine/Runtime 核心来识别具体算法。

## 7. 当前明确限制

- Live/Paper/Research 类型存在，但真实行情、券商 SDK 和生产研究工作流尚未接入。
- Product 装配首阶段只支持一个启用 Cluster、一个 Account/Data Source/Broker 组合；核心 Manager/Runtime 仍支持多 Cluster 隔离。
- 配置驱动的多 Instrument Universe 展开、生产级截面同步/停牌成分变更、CrossSection 历史版本尚待后续组件。
- Virtual Broker 和 Synthetic Data Source 是明确的确定性产品替身，不代表真实交易能力。
- 多币种、保证金、Short/Hedging、公司行动、持久化恢复和分布式并发不在当前完成范围。

## 8. 关键文件

- 策略体系：`src/onlyalpha/cluster/`、`src/onlyalpha/strategy/`、`src/onlyalpha/factor/`、`src/onlyalpha/indicator/`
- Product 装配：`src/onlyalpha/runtime/backtest/`、`src/onlyalpha/runtime/defaults.py`
- 示例：`examples/run.py`、`examples/configs/backtest/macd/`、`examples/factors/macd_signal/`、`examples/strategies/macd/`
- Integration：`examples/integration_demo/`、`tests/integration/`
- 决策：`docs/adr/0020-cluster-strategy-factor-indicator-model.md`
- 验收：`docs/reports/cluster_strategy_factor_indicator_refactor_report.md`

## 9. 后续工作建议

优先从“配置驱动的多 Instrument / CrossSection Universe 装配”作为独立组件任务开始，复用现有 Universe Snapshot、Factor DAG 和 Cluster Pipeline；必须新增正式数据同步边界、场景、Integration 测试、100 次重放和组件报告。不要在该任务中顺带接真实 Broker、多币种或分布式执行。

任何后续跨组件修改结束前仍必须运行：组件测试 → 直接上下游集成 → 全部历史 Integration/Demo → 确定性重放 → 全仓 pytest/Ruff/format/Mypy，并更新对应文档和 HANDOFF。
