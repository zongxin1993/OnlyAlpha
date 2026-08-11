# ADR 0068: Runtime Product Taxonomy and Trading Semantic Equivalence

Status: Accepted

Date: 2026-08-10

Implementation update: 2026-08-11 — P6.1 已实现本 ADR 的 Runtime control/semantic boundary：
Strategy-facing Context 与 shared Trading facade/Kernel 不再读取 `OnlyRuntimeMode`；Runtime product guard 保留在
operational `OnlyRuntime`/concrete Runtime。Streaming `STOP` 被定义为 future processing permission cutoff，不能
drain queue、flush pending Live Bar 或创造新的 Domain Fact。对应 AST architecture gate 与 shutdown tests 已建立。

Implementation update: 2026-08-11 — P6.2 已增加 canonical `SIM` enum/config spelling、`LIVE_CLOCK` environment
identity 和专用 `OnlySimRuntimeFactory`。Factory 以显式 `SIMULATED` capability、historical+live DataSource、simulated
Broker minimum capabilities、无 finite range/streaming checkpoint 为组合合同，并拒绝 Real Broker。当前合法组合仍返回
`SIM_EXECUTION_WIRING_PENDING`，不创建 Runtime；Trading Kernel、TradingFacade、Strategy Context、经济 authority、
Virtual Broker 与 MiniQMT 实现均未改变。可执行 SIM 留给 P6.3。

## Context

OnlyAlpha 需要同时支持两类目标不同的计算：一类以历史数据上的研究吞吐量为优先，另一类以可审计、可恢复且跨运行环境一致的交易语义为优先。把两类计算强制放入同一个由交易 Manager 定义的 Runtime 抽象，会让 Research 创建没有业务意义的 Account、Position、Broker 和 Transaction authority；把 Backtest、实时虚拟交易和实盘分别实现，又会产生多套经济真值。

当前源码不能直接作为长期产品分类。决策时的实现事实是：

| 源码 Runtime spelling | 当前实现事实 |
|---|---|
| `BACKTEST` | Factory、有限生命周期、Virtual Broker 和当前有限认证范围内的 durable trading path 已实现，是当前主要产品 Runtime |
| `PAPER` | 已实现受限 streaming/observation 与 Shadow execution，是未来 Sim Runtime 的迁移来源 |
| `LIVE` | Factory 已注册，但返回 `UNSUPPORTED_RUNTIME_TYPE` |
| `SHADOW` | Standalone Factory 已注册，但返回 `UNSUPPORTED_RUNTIME_TYPE` |
| `RESEARCH` | Factory 已注册，但返回 `UNSUPPORTED_RUNTIME_TYPE`，尚无正式研究工作流 |
| `SIM` | Enum、配置、environment identity 与 composition-validation Factory 已实现；execution wiring 尚未实现 |

`PAPER` 和 standalone `SHADOW` 的源码存在是 migration debt，不是长期兼容合同，也不能据此增加第五、第六种目标 Runtime。本 ADR 只决定目标架构、工程合同与迁移方向，不实施 Runtime 源码迁移。

当前 trading-shaped `OnlyRuntime` 基类、Cluster-only configuration/planning、legacy concrete Runtime exports、`OnlyRuntimeContext.mode`，以及 Position authority、Fee finality、compiled Market Rule identity 中少量 Runtime-mode branch 同样是实现债务。Durable Execution Capability Resolver 已经 mode-neutral，但本 ADR 不把尚未完成的全仓中立化伪写成当前实现事实。

## Decision

OnlyAlpha 的唯一目标 Runtime product taxonomy 是：

```text
RESEARCH
BACKTEST
SIM
LIVE
```

其中 Research Runtime 与 Trading Runtime 是两种不同的产品抽象：

```text
OnlyEngine
├── Research Runtime
│   └── Research Job / Research Plan
├── Backtest Runtime
│   └── Cluster workload(s)
├── Sim Runtime
│   └── Cluster workload(s)
└── Live Runtime
    └── Cluster workload(s)
```

Engine 负责产品生命周期、Runtime planning/grouping、composition、共享基础设施、资源引用、Session、Result 与 Artifact 聚合；Engine 不拥有交易经济状态。

## Runtime Taxonomy

| Runtime | Data | Execution | Clock | Broker | Account | Primary purpose |
|---|---|---|---|---|---|---|
| Research | Historical | Vectorized / Batch | Research job time range | None | No formal trading Account authority | 快速研究、因子/特征、参数搜索、统计和研究产物 |
| Backtest | Historical | Event-driven | Backtest Clock | Virtual Broker | Local virtual trading Account | 高保真历史交易验证 |
| Sim | Realtime | Event-driven | Live Clock | Local Virtual Broker | Local virtual trading Account | 实时虚拟交易验证 |
| Live | Realtime | Event-driven | Live Clock | Real Broker | Real Broker evidence + local canonical trading state | 生产实盘交易 |

这是目标产品合同，不是当前实现完成度声明。只有源码、正式测试和产品认证已经证明的能力才能作为当前产品能力发布。

## Research Boundary

Research Runtime 拥有 research execution state、dataset state、calculation state、Research Result 和 Artifact state。Research Job / Research Plan 可以描述 Dataset、Universe、Time Range、Indicator/Factor/Feature definitions、Parameter Grid、Statistics specification 与 Output specification。

Research 可以复用 MarketData Domain、Instrument、Reference、Calendar、canonical data model，以及没有交易副作用的 Indicator/Factor 定义。它不承担正式 Order lifecycle、Broker lifecycle、Risk reservation、Trading Position/Account authority、Durable Broker Fact 或 Trading Transaction Projection。

Research 不得为了父类对称或代码复用而实例化 Trading Authorities，也不要求伪装成 Strategy/Cluster trading workload。本 ADR 不提前定义 Research Job 的生产代码框架。

## Trading Runtime Boundary

Backtest、Sim 和 Live 是 Trading Runtime。每个 Trading Runtime 是其 mutable trading authorities 的唯一所有者，包括 Order、Position、Allocation、Account、Strategy Ledger、Risk、Reservation、Settlement、Fee、Execution Processor、Runtime Transaction Store、Applied Projection Ledger 和 Outbox。

Cluster 是 Trading Runtime workload：一个 Strategy、零个或多个 Factors、Indicator scope、Subscription scope 和 Strategy Ledger scope。Cluster 不拥有 Account、Position、Broker 或 Runtime Clock，也不直接修改 Runtime state。

正式交易链保持：

```text
MarketData
→ Indicator / Factor
→ Strategy
→ Market Rule
→ Risk
→ Reservation
→ Order
→ Broker
→ Normalized Broker Fact
→ Durable Transaction
→ Ordered Projection
→ Position / Allocation / Account / Ledger / Fee / Settlement
→ Result
```

## Backtest / Sim / Live Semantic Equivalence

Backtest、Sim 和 Live 追求 **Trading Semantic Equivalence**，而不是 Driver Implementation Equivalence。

主要允许变化的外围 Driver 是：

| Boundary | Backtest | Sim | Live |
|---|---|---|---|
| MarketData Driver | Historical Replay | Realtime | Realtime |
| Clock Driver | Backtest Clock | Live Clock | Live Clock |
| Broker Adapter | Virtual Broker | Virtual Broker | Real Broker |
| Lifecycle Driver | Finite | Streaming | Streaming |

三者应共享 Strategy、Market Rule、Risk、Order、Reservation、Execution Support、Execution Processor、Transaction Kernel、Position、Allocation、Account、Strategy Ledger、Fee、Settlement、Result semantics 和 Recovery semantics。

`Runtime Type != Execution Permission`。Runtime type 可以参与 Driver 选择、Runtime identity、planning/grouping 和生命周期组合，但不能成为经济能力、市场合法性或交易规则 authority。进入 Trading Kernel 的输入必须是 normalized domain input、normalized broker facts、market instructions 和 economic context，而不是 Runtime name。Strategy 和交易经济逻辑不得按 Runtime type 分支，也不得创建 Runtime-specific duplicate economic authorities。

`Lifecycle Command != Domain Fact`。Start/stop/subscription/reconnect 等属于 Runtime Control Plane；它们只能控制
系统是否继续接收和处理事实，不能被解释为 market-time evidence，也不能自行 close Bar、创建 Broker Fact 或推进交易状态。

Sim 必须走完整 Trading Kernel，但绝不能向 Real Broker 提交订单或依赖真实资金产生交易结果。Live 在共享交易语义之上增加 durable Broker outbound command、idempotency、ACK/Reject/Unknown、query/synchronization、reconciliation、reconnect、long-running recovery 和生产运维能力。

## Finite vs Streaming Lifecycle

目标生命周期分为：

```text
Finite:    RESEARCH, BACKTEST
Streaming: SIM, LIVE
```

Backtest 的有限回放由 Backtest Clock 驱动。Research 的结束边界由 Research Job / Plan 定义。Sim 和 Live 使用显式 `initialize/start/wait/stop/close` 生命周期，并必须处理 watermark、gap recovery、reconnect、checkpoint、restart 和长期运行诊断。

当前 `OnlyEngine.run()` 仍只支持有限 `BACKTEST`；该事实不表示 Research 需要经过 Backtest 或 Trading Cluster，也不表示 Research 产品入口已经实现。

## Cluster vs Research Job

Cluster 只属于 Trading Runtime workload model。它承载交易 Strategy 及其 Factor/Indicator、订阅和 Ledger scope。

Research Job / Research Plan 属于 Research Runtime。它承载数据集、研究计算和输出规范，不拥有 Broker、Order、Reservation 或交易账务。纯 Indicator/Factor 定义可以跨边界复用，但 Runtime orchestration 和 mutable authority 不复用。

## Paper Migration

当前 `PAPER` 是 Legacy Streaming Implementation / Sim Migration Source。可迁移能力包括 LiveClock、Historical/Open-Market Bootstrap、Historical-to-Live handoff、Realtime MarketData Queue、aggregation、warmup、observation 和 streaming lifecycle。

迁移必须：

```text
Current PAPER streaming infrastructure
→ retain and clean useful streaming boundaries
→ replace Shadow execution with Virtual Broker
→ enter the full Trading Kernel
→ expose the target SIM Runtime
→ migrate config and tests
→ delete PAPER Runtime spelling and implementation
```

不得保留 `PAPER -> SIM` alias、deprecated spelling、legacy wrapper 或并行 `PAPER + SIM` 产品路径。

## Shadow Boundary

Standalone `SHADOW` 不是目标 Runtime。当前 Shadow Factory 和 Paper 内的 Shadow execution 是待迁移实现债务。若 Shadow 语义未来仍有价值，只能作为明确受限的 internal execution capability，不能拥有独立 Runtime product、交易 authority 或长期 public Runtime vocabulary。

Sim 不是 Shadow：Sim 必须通过 Virtual Broker 产生标准 Accepted/Trade/Terminal facts 并运行完整 durable trading path。

## Vectorization Boundary

Vectorized execution 只属于 Research。正式 Backtest 必须保持 Historical + Event-driven + Virtual Broker + Full Trading Kernel；其优先目标是交易保真度，不是单作业最大吞吐量。

需要提高总吞吐量时，可以并行运行多个完整、事件驱动的 Backtest job。Distributed Backtest 不得以 vectorized trading approximation 替换 canonical trading semantics。“Vectorized Backtest”不再是目标产品或 Roadmap 名称。

## Rejected Alternatives

1. 保留 `PAPER` 作为第五种长期 Runtime。
2. 保留 standalone `SHADOW` Runtime。
3. 仅把 `PAPER` 重命名为 `SIM`，但保留 Shadow execution 和不完整交易语义。
4. 新建一套不与 Backtest 共享 Trading Kernel 的 Sim Trading Engine。
5. 新建 `SimOrderManager`、`SimPositionManager`、`LiveOrderManager`、`BacktestAccountManager` 等 Runtime-specific economic authority。
6. 允许 Strategy 根据 Runtime type 编写不同交易逻辑。
7. 允许 Execution 根据 Runtime type 决定 economic support 或 permission。
8. 为了复用 Trading Runtime，强制 Research 创建 Account、Position、Broker 或 Transaction Manager。
9. 将正式 Backtest 改为 vectorized trading approximation。
10. 为旧 `PAPER` / `SHADOW` 保留 compatibility alias 或 wrapper 作为长期 public API。

## Consequences

- 产品文档、工程合同和 Roadmap 只有 `RESEARCH/BACKTEST/SIM/LIVE` 四种目标 Runtime。
- 当前源码中的 `PAPER/SHADOW` 必须始终带明确历史或迁移语义；它们不能获得新的产品依赖。
- Research 与 Trading Runtime 不再以“所有 Runtime 拥有相同 Manager”为抽象目标。
- Backtest 的 event-driven durable trading path 保持 canonical；向量化研究不能冒充正式 Backtest。
- Sim 的实现必须复用 Virtual Broker 和完整 Trading Kernel，而不是扩展当前 Shadow execution。
- Live 的实现以 durable outbound command、Broker synchronization/reconciliation 和长期恢复为前置条件。
- Alpha 阶段优先完成架构迁移并删除旧接口，不承诺永久兼容旧 Runtime spelling。

## Migration Notes

本 ADR 的原始决策不直接修改 `OnlyRuntimeMode`、Runtime factories、配置 schema、Factory registration 或生产行为；
后续 implementation updates 与 Roadmap 记录实际迁移。源码迁移按 Roadmap 执行：

1. P5 继续完成 Market Product Composition Authority Neutralization。
2. P6 将当前 PAPER streaming 基础设施迁移到 Sim，接入 Virtual Broker 与完整 Trading Kernel，补齐 gap/reconnect/checkpoint/restart，随后删除 PAPER 和 standalone SHADOW，不保留 wrapper。
3. P7 实现 Vectorized Research Runtime、Research Result/Artifact 与只读 Web query boundary。
4. P8 实现 durable Broker outbound command、idempotency、query、synchronization 和 reconciliation。
5. P9 在 P8 基础上完成 Live Runtime foundation 与长期运行边界。

迁移完成前，当前 Factory/enum/config 的实际可用性仍以源码和正式测试为准；目标 Runtime 名称不能作为实现完成声明。

## Validation / Architecture Guards

工程合同和后续可自动化门禁必须保证：

```text
Allowed target runtimes: RESEARCH, BACKTEST, SIM, LIVE
No new PAPER runtime product or dependency
No new standalone SHADOW runtime product or dependency
No vectorized canonical Backtest
No Runtime-specific duplicate economic authority
No Strategy Runtime-type branching
No Execution Runtime-mode permission branching
SIM never submits to a Real Broker
RESEARCH never instantiates Trading Authorities for structural symmetry
```

文档审查必须区分 active architecture、migration statement 和 immutable historical ADR/report。旧词出现在历史记录中不是自动失败；它出现在 active architecture 中且没有明确历史/迁移限定时必须失败。

## Superseded / Clarified ADR References

- [ADR 0001](0001-engine-runtime-cluster.md) 的 `Engine -> Runtime -> workload` 分层继续有效。本 ADR 澄清：Trading Runtime 使用 Cluster；Research Runtime 使用 Research Job / Plan，不必拥有 Cluster trading workload。
- [ADR 0019](0019-runtime-agnostic-config-factory-and-output.md) 已由 ADR 0021 supersede，保持历史不变；其中五种源码 spelling 和 unsupported Factory 是当时实现事实，不再定义目标 taxonomy。
- [ADR 0020](0020-cluster-strategy-factor-indicator-model.md) 的 Cluster/Strategy/Factor/Indicator 决策继续有效。本 ADR 澄清它主要是 Trading Runtime workload model；Research 可以复用纯 Indicator/Factor 定义而不进入 Strategy/Cluster trading semantics。
- [ADR 0021](0021-engine-cluster-cli-and-user-data-layout.md) 的 OnlyEngine 产品入口、Cluster config、Runtime planning/grouping、Session、资源与 `user_data` 决策继续有效；其 Runtime vocabulary 被本 ADR 部分替代。
- [ADR 0026](0026-unified-market-runtime-rules.md) 的 unified Market Rule authority 继续有效；其 `Backtest/Paper/Live/Shadow` vocabulary 被 `BACKTEST/SIM/LIVE` Trading Runtime taxonomy 部分替代，Research 不承担正式交易 Market Rule lifecycle。
- [ADR 0027](0027-deterministic-multi-market-scenario-framework.md) / [ADR 0028](0028-multi-market-conformance-and-profile-stability.md) 的 Scenario/Conformance 决策继续有效；其中 `PAPER/LIVE/SHADOW` capability vocabulary 只记录当时源码状态，其 taxonomy 部分由本 ADR 替代。
- [ADR 0031](0031-unified-fee-authority-and-reconciliation.md) 的 immutable fee authority 继续有效；其按 Backtest/Paper/Live label 推断 confirmed/provisional 的表述被后续 explicit fee evidence/reconciliation authorities 与本 ADR 的 `Runtime Type != Execution Permission` 原则替代。
- [ADR 0064](0064-runtime-environment-composition-authority.md) 的 Runtime Environment、composition、identity 和 resource authority 决策继续有效；该 ADR 的历史 scope 不因本决策重写。
- [ADR 0065](0065-durable-execution-capability-semantic-authority.md) / [ADR 0066](0066-durable-broker-driven-order-lifecycle.md) 的 market-neutral `OnlyExecutionCapabilityResolver` 和 durable lifecycle admission 继续有效，并构成本 ADR `Runtime Type != Execution Permission` 的直接先例。
- [ADR 0067](0067-cn-a-share-production-durable-backtest-product.md) 的 `CN_A_SHARE_DURABLE_BACKTEST_V1` 有限 Backtest 产品合同及其认证语义继续有效；本决策不扩大或削弱该合同。
- 其他早期 ADR 中的 `PAPER`、`SHADOW` 或 `Paper/Live` 表述保留为历史实现/范围记录；自本 ADR 起，它们不再具有目标 Runtime taxonomy authority。
