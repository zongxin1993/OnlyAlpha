# OnlyAlpha

**OnlyAlpha** 是面向个人与小型团队的模块化多市场量化交易工程。目标是在保持工程边界清晰、结果确定、状态可恢复和交易语义一致的前提下，为 **Research、Backtest、SIM、LIVE** 提供统一基础设施。

```text
Research optimizes research efficiency.
Backtest / SIM / LIVE share one trading semantic core.
```

长期优先级：

```text
Correctness
> Architecture Consistency
> Verifiability
> Recoverability
> Maintainability
> Performance
> Automation
```

## 产品架构

OnlyAlpha 使用一套 canonical Domain 与 Trading Kernel，不按市场复制 Engine、Runtime 或经济 Manager。

```text
Human → Web ───────────────┐
                          ├→ Versioned Product API → Stateful Kernel
Agent / Automation ───────┘                            │
                                                      ├→ Research Runtime
                                                      ├→ Backtest Runtime
                                                      ├→ SIM Runtime
                                                      └→ LIVE Runtime
                                                            ↓
                                        Market Product / DataSource / Broker plugins
```

正式 Runtime vocabulary：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

Trading Runtime 保持：

```text
One Trading Runtime
= One Account authority
= One resolved Market Product
= One Account currency
```

市场特性通过 versioned Market Product、DataSource、Broker 等插件边界进入。Core 不依赖具体 Provider；Web/UI 只作为消费者，不成为资金、仓位、订单、风险或执行 Authority。

## Strategy Product

OnlyAlpha 的目标不是维护 Runtime-specific 策略副本，而是让同一个 immutable Strategy Revision 在 Backtest、SIM、LIVE 中保持同一策略语义。

```text
Human / LLM Agent
→ Research Draft / Experiment
→ Research Evidence
→ Freeze immutable Strategy Revision
→ Backtest
→ SIM
→ LIVE
```

Strategy fingerprint 是策略身份。Strategy Revision 固定策略语义，不包含资金规模、Broker、费用结果或真实执行权限。Runtime 绑定 Portfolio / Execution Profile、数据时态、Broker、Lifecycle 与 Execution Permission，但不得重新定义 Strategy。

详细设计见 [`docs/strategy_product_architecture.md`](docs/strategy_product_architecture.md)。

## Trading Semantic Core

Backtest、SIM 与 LIVE 共享正式 Trading Kernel。允许的主要 Runtime 差异位于：

```text
Clock Driver
MarketData Driver
Broker Adapter
Lifecycle Driver
```

进入 Trading Semantic Plane 后，共享 Strategy、Market Rule、Risk、Reservation、Order、Execution、Fee、Position、Allocation、Account、Settlement、Durable Transaction 与 Recovery semantics。

核心不变量：

```text
One Domain → One Write Authority
Planner Calculates → Projection Installs
Commit Fact First → Project State Second
Historical Fact Immutable → Forward Recovery Only
Market Identity Is Evidence → Not Execution Permission
Unsupported / Ambiguous → Fail Closed
```

外部 venue 是 execution fact authority；OnlyAlpha 负责 intent、policy、promotion、reconciliation 与本地可恢复状态。UNKNOWN submit outcome 是一等状态，禁止 blind retry 创建第二订单身份。

## Research

Research 使用 immutable、content-addressed 的输入与输出 Authority，并通过有限 Runtime、Query/API 和 Web 消费链组合。

```text
Historical Dataset Snapshot
→ Calculation / Factor / Feature
→ Sweep / Evaluation
→ Research Result
→ Research Artifact
→ Query / HTTP API
→ Research Web
```

Research consumer plane 只读；Web 不成为 Research execution authority，也不成为 Trading authority。

## Production Data

生产市场数据目标采用明确 Authority 分工：

```text
Provider
→ ingress durability / WAL
→ canonical typed market facts
→ ClickHouse high-volume fact store
→ PostgreSQL provenance/control metadata
→ verified Market Data Revision
→ immutable Dataset Snapshot
```

历史事实采用 append/revise 模型，不通过静默覆盖 sealed truth 来“修正历史”。Research/Backtest 的可复现输入是 immutable Dataset Snapshot，而不是对 mutable database 的任意直接查询。

## 工程验收

每个工程任务的唯一验收规则定义在 [`AGENTS.md`](AGENTS.md)。

核心模型：

```text
Task Contract
→ Implement
→ Impact-Aware Validation
→ High-risk bounded Independent Review when required
→ Stop Condition
→ STOP
```

当前工程状态不由 README、Roadmap、质量报告、历史 CI、旧 Prompt 或状态文件记录。判断当前工程必须直接读取当前源码、当前测试和当前可执行行为，并对照长期 ADR / Architecture / Contract。

机器职责：

- [`quality-policy.toml`](quality-policy.toml)：持续 CI 与 Major Milestone Phase Gate 的 gate 集合；
- [`scripts/test_suite.py`](scripts/test_suite.py)：canonical test lanes；
- [`scripts/verify.py`](scripts/verify.py)：当前工作区的 Impact-Aware 验证选择器；
- [`pyproject.toml`](pyproject.toml)：测试、静态检查、类型与 package 配置。

不使用 Exact-SHA / Final-SHA 工程认证，不维护每个 Increment 的 VERIFIED/READY/COMPLETE 状态，不在仓库保存每步质量/审计/closure 报告。

## Roadmap

Roadmap 只描述未来建设顺序与依赖，不承担工程进度 Authority。Binance Spot 仍是第一条 production/LIVE Golden Vertical；在
provider vertical 继续扩展前，先闭合 universal Spot/Futures Research 与 Backtest semantics，具体 sequencing 由
[`ADR 0106`](docs/adr/0106-universal-spot-futures-research-backtest-sequencing.md) 决定。

计划顺序：

```text
Existing Spot foundation
→ Universal Spot/Futures Research + Backtest semantics
→ Binance USD-M Research/Backtest conformance
→ Synthetic non-Binance Futures conformance
→ later Web / SIM / LIVE / QMT / CTP / Agent work
```

后续 Provider 扩展遵循相同 Core/Plugin 边界，不因接入 Binance、QMT、CTP 或其他 venue 而复制第二套交易核心。

## 开发

Python 要求以根目录 [`pyproject.toml`](pyproject.toml) 为准。推荐使用 `uv` 管理 workspace 与环境。

常用入口：

```bash
uv sync
uv run python scripts/verify.py plan
uv run python scripts/verify.py run
uv run python scripts/test_suite.py --help
```

`verify.py` 只选择和执行当前工作区的影响验证，不是任务完成 Authority；实际验收范围仍必须遵守 `AGENTS.md` 的 Task Contract、Impact Scope、风险分级与 Stop Condition。

## 文档入口

- [`AGENTS.md`](AGENTS.md) — 工程任务与验收规则
- [`docs/architecture.md`](docs/architecture.md) — 系统架构
- [`docs/strategy_product_architecture.md`](docs/strategy_product_architecture.md) — Strategy Product
- [`docs/p9_production_trading_vertical_architecture.md`](docs/p9_production_trading_vertical_architecture.md) — Production Trading Vertical
- [`docs/p9_binance_spot_golden_vertical_execution_plan.md`](docs/p9_binance_spot_golden_vertical_execution_plan.md) — Binance Spot 建设顺序
- [`docs/adr/`](docs/adr/) — 长期设计决策

## License

MIT
