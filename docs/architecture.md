# OnlyAlpha Current Architecture

本文档描述当前系统如何组织，并标明当前实现与已接受目标架构之间的差距。历史阶段、PR 编号和完成记录由 `docs/adr/`、`docs/reports/` 与 Git history 保存，不在此维护。

Runtime 产品分类与迁移方向由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 决定；多市场
拓扑与异构生命周期由 [ADR 0080](adr/0080-multi-market-platform-and-heterogeneous-runtime-lifecycle.md) 决定；目标 Live
导入、人工操作和清仓控制由 [ADR 0081](adr/0081-live-genesis-manual-workload-and-liquidation-control.md) 决定。任何“目标”
描述都不是实现完成声明；当前能力必须由可执行源码、正式测试和产品认证证明。

## 1. Architecture Principles

OnlyAlpha 当前采用 Monorepo + 模块化单体 Core + 插件化 DataSource/Broker + 配置驱动 Engine/Runtime 组合。

核心不变量：

```text
One Engine → Multiple Runtime

One Engine → Concurrent Heterogeneous Runtime Sessions

One Trading Runtime → One Account + One Market Product + One Currency

Trading Runtime → Mutable Trading Authority Owner

One Domain → One Write Authority

Planner Calculates → Projection Installs

Commit Fact First → Project State Second

Historical Fact Immutable → Forward Recovery Only

Market Identity Is Evidence → Not Execution Permission

Runtime Type != Execution Permission

Unsupported or Ambiguous → Fail Closed
```

OnlyAlpha 是多市场平台：Domain 定义跨市场 canonical vocabulary，具体市场制度由 Market Product Plugin 拥有。Research 为研究
效率服务；Backtest、Sim、Live 为 Trading Semantic Equivalence 服务。架构复用不能产生第二套经济真值，也不能迫使 Research
经过 formal Trading Kernel。

## 2. Engine / Runtime Model

目标顶层模型：

```text
OnlyEngine
├── Research Runtime
│   ├── Research Job A
│   └── Research Job B
├── Backtest Runtime
│   ├── Cluster A
│   └── Cluster B
├── Sim Runtime
│   └── Cluster C
└── Live Runtime
    ├── Cluster D
    └── Manual Workload E
```

`OnlyEngine` 是唯一产品级入口。当前调用链为：

```text
CLI / Application
→ OnlyEngine
→ OnlyRuntimePlanner
→ OnlyEngineRunAssembler
→ Runtime Factory
→ OnlyRuntime
→ OnlyCluster
```

Engine 当前负责 Cluster Definition、配置/扩展验证、Runtime environment grouping、Runtime/Cluster Session、共享资源引用、装配、生命周期、Result/Artifact 聚合、`user_data` 布局和失败清理。Engine 不拥有 Order、Position、Account 或其他交易经济状态。

当前 `OnlyEngine.run()` 只接受有限 `BACKTEST`。Streaming 路径使用 `initialize/start/wait/stop/close`。目标 Research 仍由 Engine 管理产品生命周期，但使用 Research Job / Plan；当前以 Cluster config 为中心的入口不能被当作迫使 Research 交易化的长期接口合同。

目标 Engine 允许四种 Runtime Session 同时存在且生命周期独立。Research/Backtest 完成不得隐式停止 Sim/Live；一个 Runtime 的
start/stop/failure 不能成为另一个 Runtime 的 lifecycle command。Web/Application 未来通过 Engine 控制单个 Runtime；Engine 的
跨 Runtime Result/diagnostic aggregation 保持只读。当前 Engine 尚未实现四种 Runtime 的完整异构同时组合。

## 3. Runtime Product Taxonomy

唯一目标 Runtime vocabulary：

| Runtime | Data | Execution | Clock | Broker | Lifecycle |
|---|---|---|---|---|---|
| Research | Historical | Vectorized / Batch | Research Job range | None | Finite |
| Backtest | Historical | Event-driven | Backtest Clock | Virtual Broker | Finite |
| Sim | Realtime | Event-driven | Live Clock | Virtual Broker | Streaming |
| Live | Realtime | Event-driven | Live Clock | Real Broker | Streaming |

当前源码状态：

| Runtime | Current implementation status | Target treatment |
|---|---|---|
| `BACKTEST` | 已实现，是当前主要产品 Runtime | 保留并继续使用完整 Trading Kernel |
| `LIVE` | Factory 注册但返回 unsupported | 后续实现目标 Live Runtime |
| `RESEARCH` | Factory 注册但返回 unsupported | 后续实现目标 Research Runtime |
| `SIM` | realtime Virtual Broker、gap/reconnect、durable checkpoint 与 new-process restart 已实现 | 保持 shared Trading Kernel 与 recovery contract |

历史 `PAPER/SHADOW` active package、Factory、配置与 public export 已删除，没有 alias 或 wrapper。

P6.2 已建立 SIM operational composition contract：SIM 使用 `LIVE_CLOCK`、streaming lifecycle、显式
`SIMULATED` execution capability、恰好一个同时支持 historical/live bars 的 DataSource、恰好一个声明
`simulated_execution` 与最小订单/query 能力的 Broker，并拒绝有限 start/end range、checkpoint 与 Real Broker。
Runtime environment identity 保留 `SIM` product identity，因此不会与 BACKTEST grouping/fingerprint 混同。

P6.3 在该合同上增加 `OnlySimRuntime -> OnlyStreamingRuntime -> OnlyTradingRuntimeFacade -> OnlyTradingKernel` 的
可执行组合。Factory 通过正式 SPI 创建 DataSource/Broker，通过显式 `OnlyDeterministicBrokerDriver` 推进 Virtual Broker，
并为 SIM 创建独立 MarketData/Broker Inbound Queue 与 Runtime Persistence。标准 causal path 是 Bar N 的 Strategy intent
在 dispatch 后得到 Accepted 且不在同一 Bar 成交；Bar N+1 先运行 Broker matching，再运行 Strategy，Trade 经
Execution Processor、Durable Transaction 与 Ordered Projection 更新共享交易 authority。Runtime stop 不取消 Accepted
order，也不创造 terminal/trade fact。

当前 SIM 已完成 realtime normal path 与 P6.4 same-process continuity recovery。Unexpected gap 在 MarketData Pipeline 前
fail closed；Streaming Runtime 独占 `DEGRADED/RECOVERING/CATCH_UP/LIVE` transition、Recovery Plan 与 confirmed frontier，
Historical DataSource 只提供事实，Worker 仍是唯一语义 consumer。Recovered fact 进入同一 Processor/Pipeline/Broker hooks，
既有订单可推进但新 Strategy submit 被抑制；reconnect 只恢复 transport，必须经 historical repair、buffered catch-up 与 LIVE
proof 才恢复交易权限。P6.5 已闭合 Streaming checkpoint/new-process restart；长期生产运行仍未闭环，Runtime Persistence
的 Durable Transaction 也不等于 Streaming Checkpoint。

Streaming phase 的唯一 mutable owner 是 `OnlyStreamingPhaseController`，其单调 revision 也是异步验证的正式同步点。
`OnlyStreamingRecoveryDiagnostics` 只是从 Phase Controller、Recovery Plan、Semantic Lane、Worker/Driver、Continuity 与 Inbound
Queue 组合出的 immutable projection；diagnostic stage 只说明 recovery 停在 history loading、replay、suffix reconciliation 或
continuity verification 的哪一步，禁止反向驱动控制流。Recovery timeout 是按配置派生的 stuck-operation watchdog，不进入
continuity correctness。具体决定见 [ADR 0077](adr/0077-streaming-recovery-verification-and-diagnostics.md)。

## 4. Research Runtime

Research Runtime 的目标边界是 Historical + Vectorized/Batch + Research-oriented。它拥有 dataset、calculation、job progress、Research Result 和 Artifact state，不拥有 formal trading Account、Position、Order、Broker、Risk Reservation 或 durable Trading Transaction authority。

目标研究链：

```text
Historical Dataset
→ Vectorized Indicator
→ Factor / Feature
→ Parameter Sweep
→ Statistics
→ Immutable Research Result / Artifact
→ Query / API
→ Web / Notebook / CLI
```

Research 可复用 MarketData Domain、Instrument、Reference、Calendar、canonical data model 和无交易副作用的 Indicator/Factor 定义。Research Job / Plan 描述 Dataset、Universe、Time Range、计算定义、Parameter Grid、Statistics 与 Output，不伪装成 Trading Cluster。

当前已实现 immutable Dataset Snapshot、batch/vectorized Calculation、Calculation Result、Research Job、Factor/Feature/Score、Sweep，
以及 Research-only Target/Forward Return、exact alignment、IC/Rank IC 和 immutable Statistics Result。统一 Factor semantic 仍以
`TIME_SERIES/CROSS_SECTION` 表达数学 execution shape，以 `RESEARCH/TRADING` 表达物理 backend；Runtime type 不进入 Factor identity。
Evaluation 只允许消费 verified Feature/Target Result，Evaluation → Feature dependency 在 Calculation Graph construction 时 fail closed。
当前 Research Factory 仍明确 unsupported；P7.8 已实现 composition-only immutable Research Result，P7.9 已实现只复制该 Result
精确选择的 Statistics rows、可脱离全部上游 Store 自验证的 immutable Research Artifact。Artifact 不是新的 Statistics 或 Research
authority；完整 finite Runtime lifecycle、Query/API 与 Web workflow 尚未实现。
当前 trading-shaped `OnlyRuntime` 基类不能反向定义未来 Research ownership。

## 5. Trading Runtime

Backtest、Sim、Live 是 Trading Runtime。每个实例独占其 mutable trading authorities，并通过同一语义核心处理 Strategy、Market Rule、Risk、Reservation、Order、Broker facts、Transaction、Projection、Position、Allocation、Account、Ledger、Fee、Settlement、Result 和 Recovery。

P6.0 已将这个共享语义边界固化为 Runtime-neutral `OnlyTradingKernel`：Kernel config 不含 Runtime mode，Kernel 通过 builder 创建并唯一持有 Position、Allocation、Reservation、Account、Strategy Ledger、Settlement、Margin 与 Fee authorities，随后一次性安装 Order/Risk/Execution/Transaction/Projection 和共享 MarketData/Strategy processing graph。`OnlyRuntime` 只保留 identity、lifecycle、plugin resource 与 operational state，并通过临时兼容 delegate 暴露既有管理查询；这些 delegate 不是新的 Service Locator 合同。

当前组合和依赖方向为：

```text
OnlyBacktestRuntime ──→ OnlyTradingRuntimeFacade ──→ OnlyTradingKernel
        │
        └── OnlyBacktestDriver (historical plan / finite termination)

OnlyStreamingRuntime ─→ OnlyTradingRuntimeFacade ──→ OnlyTradingKernel
        │
        └── OnlyStreamingMarketDataDriver
            (subscription / worker / stop coordination)
```

`runtime/streaming` 不再导入或继承 concrete Backtest Runtime；`runtime/trading` 也不依赖 Backtest、Paper、Streaming、Live/Sim 或 `OnlyRuntimeMode`。Historical replay/checkpoint policy 仍由 Backtest facade/driver 组合，subscribe-first bootstrap、warmup/handoff、watermark/catch-up、live finalization 与 worker shutdown 仍在 Streaming facade/driver，均未进入 Kernel。

三者追求 Trading Semantic Equivalence，不追求 Driver Implementation Equivalence：

| Driver boundary | Backtest | Sim | Live |
|---|---|---|---|
| MarketData | Historical Replay | Realtime | Realtime |
| Clock | Backtest Clock | Live Clock | Live Clock |
| Broker | Virtual Broker | Virtual Broker | Real Broker |
| Lifecycle | Finite | Streaming | Streaming |

Runtime type 可以参与 Driver 选择、Runtime identity、planning/grouping 和 lifecycle composition，但不能决定经济能力、市场合法性或 Execution permission。Trading Kernel 只消费 normalized domain input、normalized broker facts、market instructions 与 economic context。Strategy 和交易经济逻辑不得按 Runtime type 分支。

P6.1 将 Runtime Control Plane 与 Trading Semantic Plane 固化为正式边界：

```text
Runtime Control Plane
Runtime type / Factory / Driver / Clock / Lifecycle / Operational status / Persistence identity
        │
        └── normalized Market Facts / Broker Facts
                         │
                         ▼
Trading Semantic Plane
Strategy / Market Policy / Risk / Reservation / Order / Execution / Transaction /
Position / Allocation / Fee / Settlement / Account / Strategy Ledger
```

`Runtime Type != Execution Permission`，`Lifecycle Command != Domain Fact`。`OnlyRuntime` 与 concrete Runtime
保留 product compatibility guard；`OnlyTradingRuntimeFacade`、Trading Kernel、Strategy-facing `OnlyRuntimeContext`
及交易经济包不读取 `OnlyRuntimeMode`。Position authority、Fee finality、compiled Market Rule identity 与 Durable
Execution Capability 均由显式经济 authority 决定，当前生产路径已经 mode-neutral，并由 AST architecture gate 固化。

Streaming `STOP` 表示撤销未来处理权限，不是推进 market event time 或 flush pending market state。进入
`STOPPING` 后 Worker 不 drain inbound queue、不 close pending Live Bar，也不开始新的 MarketData processing/result
callback；未处理输入的 checkpoint/restart/gap recovery 仍属于后续阶段。

Backtest 具备完整正式 durable trading product path。SIM 已具备 realtime Virtual Broker、gap/reconnect、durable checkpoint
与 new-process restart，Accepted/Trade 经相同 Durable Transaction 与 Ordered Projection。Live 尚未具备 durable outbound
Broker command、同步、对账和长期恢复闭环。

## 6. Cluster / Strategy / Factor / Indicator

Cluster 是 Trading Runtime workload：

```text
One Strategy
+ Zero or more Factors
+ Indicator Scope
+ Subscription Scope
+ Strategy Ledger Scope
```

Cluster 是隔离容器，不是 Strategy，也不是 Research Job。它不拥有 Account/Position Manager、Broker 或 Clock，不访问其他 Cluster 私有 Order/Allocation/Ledger，不直接修改 Runtime state。

同一行情时间片的交易计算顺序显式固定为：

```text
MarketData Validate / Process
→ Cache / Aggregation
→ Indicator
→ Time-Series Factor
→ Cross-Section Factor
→ Factor Snapshot / Score
→ Strategy
→ Market Rule / Risk / Order
```

Indicator 和 Factor 没有交易权限。Strategy 只通过受限 Context 读取 immutable Snapshot，并通过正式订单接口表达 intent；它不能创建 Fill、模拟 Broker 回报或维护平行账户真值。

### 6.1 Target LIVE Manual Workload

目标 `MANUAL` workload 只存在于 LIVE，与 Strategy Cluster 并列但不伪装成 Strategy。它拥有独立 workload identity、Allocation、
Ledger、operator provenance、permission 与 audit，mutable authority 仍由 Live Runtime 独占。人工订单从 authenticated
Application/API 经 Engine 进入同一 Market Rule、Risk、Reservation、Order、Broker、Durable Transaction 与 Ordered Projection
链。Backtest、Sim、Research 不接受产品级交互式人工交易。

## 7. Runtime Environment Composition

当前组合链：

```text
OnlyClusterRunConfig
→ OnlyRuntimeEnvironmentBuilder
→ immutable environment identity / resource claims
→ OnlyRuntimePlanner
→ OnlyRuntimePlan
→ OnlyEngineRunAssembler
→ Runtime Factory
```

`OnlyRuntimeEnvironmentBuilder` 是 Runtime-shared semantics 的唯一投影，涵盖 clock/replay、DataSource、Broker、Account、Market/fee/reference 和 persistence。Planner 只按相同 environment 分组、生成稳定 Runtime identity 并验证 representative config；Assembler 只经 Factory Registry 选择具体 Runtime。

`OnlyInfrastructureRegistry` 只校验 canonical claim、检测 key/fingerprint 冲突、引用计数和归零释放。相同逻辑资源 ID 配置冲突必须 fail closed，不得通过创建第二个 Runtime 产生两个 mutable global authority。详见 [ADR 0064](adr/0064-runtime-environment-composition-authority.md)。

## 8. Market Product Composition

P5.3 已在 P5.1/P5.2 合同上完成 Generic 与 CN A-share Trading Runtime one-shot cutover。唯一生产组合链是：

```text
OnlyMarketProductConfig
→ OnlyMarketProductFactoryRegistry
→ selected OnlyMarketProductFactory
→ OnlyResolvedMarketProductBinding
→ Trading Runtime composition
```

Core 只定义市场中立的 Plugin/Product identity、不可变配置 envelope、Reference/Policy ports、Factory、fail-closed Registry、minimal canonical instrument terms 和 immutable Binding。Concrete Market Product Plugin 拥有具体市场知识并向下依赖 Core Contract；Core 不依赖具体市场 package。Binding 携带 provider/product evidence、resolved reference authority、pure policy compiler、immutable Market Fee Pack 和 effective composition identity，不暴露 Runtime mutable manager。

Product identity 是 evidence，不是行为选择器。Composition fingerprint 在 resolution 后基于 effective product/reference/compiler/fee/config authorities 生成，不直接 fingerprint raw YAML；Runtime type 不进入 Market Product economic contract。Market Product 与 Broker、DataSource、Risk、Execution Support 正交，Research 不要求 Market Product Binding。详见 [ADR 0069](adr/0069-market-product-contract-and-composition-authority.md)。

Canonical `OnlyCompiledMarketPolicy` 只包含：

```text
Instrument Market Terms
+ Session / Price / Quantity
+ Position / Short / Settlement / Margin
```

`Matching / Slippage / Simulation Liquidity / Latency / Fill Plan / Fill Schedule` 不属于 Market Product IR；它们属于 Virtual Broker / Execution Simulation。该边界由 [ADR 0070](adr/0070-generic-t0-cash-market-product-and-canonical-market-ir.md) 和静态门禁冻结。

`onlyalpha-market-generic-t0-cash` 与 `onlyalpha-market-cn-ashare` 通过 `onlyalpha.market_products` entry point 自动发现，各自拥有 plugin-local Reference、deterministic Reference Authority、pure Policy Compiler 和 Market Fee Pack。Core composition root 只持有 neutral `OnlyMarketProductFactoryRegistry`，没有 concrete import、hard registration 或 Generic fallback。tests-only `TEST_T2_MARKET` 以 tick `0.25`、quantity step `7`、T+2 证明同一 IR 不依赖 Generic branch。

当前生产组合已经是：

```text
OnlyMarketProductConfig
→ Factory Registry
→ Plugin-owned Reference / Compiler / Fee Pack
→ Resolved Binding
→ OnlyMarketRuleEngine
→ Restricted Decision / Instruction
```

Resolution 在 Runtime Factory 之上执行一次，Backtest/SIM Factory 只消费 Binding。旧 Profile Registry、Core A-share Reference/Rules、legacy concrete compiler 与 concrete fee registry selection 已删除；没有 adapter、fallback、compatibility wrapper 或按 product ID dispatch 的 Runtime branch。

市场合法性与执行实现能力仍是两个 Authority：

Plugin-owned Reference 提供证券事实，Plugin-owned Compiler 提供版本化制度并在 evaluate 前解析最终 Session/Price/Quantity/Settlement policy。Execution Support 根据规范化 economic shape 判断 Kernel 是否支持，不根据市场名、Product ID 或 Runtime type 决定权限。

Market Fee Pack 与 Broker Fee Contract 是独立 authority；Order binding、fee resolution proof、order cumulative accrual 和 Fee Application Ledger 保持可审计。Market Rule Authority、Execution Support Authority、Fee Authority 与 Settlement Authority 不互相替代。

Market Product plugin 的存在不升级产品范围。`CN_A_SHARE_DURABLE_BACKTEST_V1` 只认证有限 Backtest surface，不代表完整 A 股市场、Sim 或 Live 稳定。

当前 Trading Runtime 产品拓扑只允许一个 Account、一个 resolved Market Product 和一个 Account currency。市场或币种不兼容的
Cluster 由 Planner 拆分到不同 Runtime；多市场通过同一 Engine 下多个隔离 Runtime 实现。跨市场 Result/Analytics/Artifact/Web
汇总不拥有交易写权限。单 Runtime 多市场、多币种、FX valuation、跨市场资金共享和组合保证金是未来新合同，不是当前隐含能力。

只有某市场的 Research、Backtest、Sim、Live 四种产品纵切面均由正式入口和认证证据闭环后，平台才能声明“正式支持该市场”。
有限、版本化的 Runtime 产品可以独立认证，但必须使用精确产品合同名称，不能扩大为整个市场支持声明。

## 9. MarketData Boundary

正式行情路径：

```text
DataSource
→ MarketData Inbound Queue
→ Sequence / Dedup / Gap / Quality
→ Audit
→ Pipeline
→ Cache / Aggregation
→ Runtime consumers
```

Historical 与 Realtime 复用 Domain Bar/Tick。历史数据由 Replay Service 推进 Backtest Clock；DataSource 不直接推进 Runtime 时间。只有成功进入正式 Pipeline 的数据可以推进 processed watermark。

SIM 的 product-neutral Streaming control plane 具备 subscribe-first bootstrap、isolated historical worker、Historical replay、
warmup、Historical-to-Live handoff、realtime queue、aggregation、continuity 和 ordered shutdown。Provider raw、worker
accepted、replay attempted/processed/rejected、pipeline last successful bar 与 historical watermark 是不同事实，不能互相替代。

## 10. Broker Boundary

Broker Gateway 是外部适配器和事实入口，不是本地账务权威：

```text
Order Service
→ Broker Execution Service
→ Broker Gateway
→ External System
→ Normalized Broker Update
→ Broker Inbound Queue
→ ExecutionProcessor
```

Gateway 和 SDK callback 不持有或修改 Runtime Manager。重复、乱序和迟到 update 通过正式 identity、sequence、dedup 与 reconciliation 处理。

Virtual Broker 是独立 Broker plugin，负责 deterministic matching、Accepted/Trade/Terminal、whole/partial/multi-fill、slippage、fill plan 和 checkpointable external execution state；它不修改 Account、Position、Risk 或正式 Fee authority。Backtest 与目标 Sim 使用 Virtual Broker。Sim 永远不能解析或提交到 Real Broker。

目标 Live 使用 Real Broker，并在启用真实资金前补齐 durable outbound command、idempotency、ACK/Reject/Unknown、Broker query/synchronization、reconciliation、reconnect 和 long-running recovery。

### 10.1 Target LIVE Genesis and Liquidation

Live 首次 Open 不假设空账户。目标组合从 exact Broker evidence 以 immutable/versioned/idempotent genesis transactions 导入
Cash、Position/cost basis、Open Order、Pending Settlement 和 Broker/Account identity，并在 Open 前验证 schema、fingerprint、
aggregate 与 reconciliation。历史成交和资金流水只保存为 evidence attachments；Broker Snapshot 不覆盖本地 committed history。

Live 清仓支持单 Runtime 和 Engine 下全部 Live Runtime 两个 scope。全量请求由 Engine parent request 冻结 target set，每个 Runtime
持有独立 durable child request；父级只编排和聚合，不构成跨 Runtime transaction。清仓立即禁止新开仓，但 Runtime 继续处理行情、
撤单、平仓、Broker facts 与恢复；未经授权人工复位不恢复开仓。close intent 仍经过完整交易链并保持原 Allocation/Ledger 归属。

默认执行层级为对手一价、显式支持的市价执行、显式斩仓价。等待、重报、滑点和斩仓算法尚未冻结，必须在实现时由 versioned
policy、Market Product instruction 和 Broker capability 明确。结果允许 partial/block，不允许用 submitted order 冒充 flat position。

## 11. Order / Risk / Reservation

正式下单顺序：

```text
Strategy Intent
→ Market Rule Validation
→ Risk Evaluation
→ Reservation
→ Order Creation
→ Broker Submission
```

所有订单在创建前经过 Market Rule 和 Risk。Cash、Position 与 Risk Reservation 是正式交易权威；partial/multi-fill 按 Fill 增量消费，未完成部分继续保留，最终 Fill 或 Cancel/Reject/Expire 只释放 remaining authority。

Gateway、Strategy、Manager 间 cleanup 或 Event handler 均不能旁路正式 Reservation/Terminal transaction。重复 update 不得重复消费；Recovery 必须与连续运行等价。

## 12. Durable Execution Kernel

当前正式交易主链：

```text
Normalized Broker Fact
→ Immutable Planning Context
→ Pure Planner
→ Prepared Runtime Transaction
→ Transaction Store Commit
→ Runtime Sequence Gate
→ Ordered Projection Targets
→ Projection Ready
→ Durable Outbox
```

核心合同：

```text
One Fill
= One Immutable Prepared Transaction
= One Committed Transaction
```

Accepted、每个 Trade Fill、Terminal 和 Settlement Maturity 在其受支持 economic shape 内形成独立 immutable durable operation。Terminal 不伪造 Trade，不产生 Trade PnL/Settlement，并只释放剩余 authority。Commit 后不得修改事实，也不得 fallback 到 legacy multi-manager mutation。

当前完整产品范围仍受正式 Capability 与产品合同限制；Domain enum、Profile 或 Planner 类型存在不等于 durable product 已支持。

## 13. Transaction / Projection

Planner 在 commit 前冻结 before/after state、economic fact、cost、fee、settlement、reservation/risk delta、ordered projections、payload hash 与 authority proof。Projection 只验证 expected version/hash 并安装 Planner 已决定的 after-state；不得重新计算 PnL、released cost、Fee、Settlement 或 attribution。

Transaction Store 是 Runtime transaction history 的 durable authority。Applied Projection Ledger 只是可重建的 projection progress/idempotency index，不是交易事实来源。固定原则：

```text
One Projection Component
→ One Mutable Authority
```

Outbox intent 与 transaction 一起持久化，只有 Projection Ready 且 Runtime event gate 允许时才发布。Event 通知已经发生的事实，不负责核心状态迁移。

## 14. Authority Ownership

OnlyAlpha 遵守 `One Domain → One Write Authority`：

| Domain / fact | Write authority |
|---|---|
| Runtime Transaction History | Transaction Store |
| Projection Progress | Applied Projection Ledger |
| Order | Order Authority |
| Position | Position Authority |
| Cluster Position/Cost Attribution | Allocation Authority |
| Account | Account Authority |
| Strategy Capital/PnL | Strategy Ledger Authority |
| Risk | Risk Authority |
| Risk Reservation | Risk Reservation Authority |
| Cash Reservation | Cash Reservation Authority |
| Position Reservation | Position Reservation Authority |
| Settlement | Settlement Authority |
| Market Fee / Broker Fee Application | Fee Authorities / Ledgers |

Trading Runtime 拥有这些 mutable authority；Cluster、Strategy、Factor、DataSource 和 Broker Gateway 只能通过受限 Port/Query 访问各自允许的边界。Account 是 Runtime 账户级聚合真值，Allocation/Strategy Ledger 是 Cluster scope 的归因权威，但 Manager 仍由 Runtime 独占。

Position 与 Allocation 的数量、精确累计成本、released cost 和 realized PnL 必须由同一 prepared economic decision 驱动。Account、Ledger 与 committed fact 消费同一结果，不能分别重算。

## 15. Persistence / Checkpoint / Recovery

Runtime Persistence Store 当前支持 Memory 与 SQLite。Persistence 提供 durable storage，不重新决定经济语义。Checkpoint 在明确完成边界原子创建并读回验证，包含精确 MarketData cursor、participant schema/version、authority/config fingerprints 和稳定序列化，不包含 secret 或不稳定对象地址。

恢复顺序：

```text
Restore Durable State
→ Validate Authority
→ Resolve Transaction Tail
→ Resume Ordered Projection
→ Rebuild Derived Index
→ Validate Aggregate
→ Open Runtime
→ Deliver Continuation Events
```

OnlyAlpha 只支持 Forward Recovery。Committed fact 不删除、不回滚、不按当前规则重算；失败 projection 不跳过；schema/identity/fingerprint 不兼容时 fail closed。

Backtest 与 SIM 均具备各自 lifecycle 下的 durable checkpoint/restart/recovery 产品闭环并共享 forward recovery semantics；Live 与长期生产 recovery 仍是后续任务。

## 16. Result / Analytics / Artifact

Trading Result 的逐笔事实只来自 Projection Ready committed query：

```text
Projection Ready Committed Fact
→ Canonical Result
→ Analytics
→ Artifact / Report
```

Collector 是只读消费者，不从 Broker、EventBus 或最终 Manager snapshot 反推交易历史。Result/Artifact 必须稳定序列化、保持 Cluster/Runtime scope、使用 canonical Decimal/Enum/Timestamp，并通过 manifest、relative path 与 fingerprint 表达 provenance。

Observation 是只读诊断，不成为交易 authority，不能阻塞核心 Runtime，停止后不得继续增长。目标 Research Artifact 与 Trading
Result 是不同 DTO/语义；Web 的数据读取只能通过 Query/API 消费 immutable result/artifact/observation。

目标 Web 同时是 authenticated control client：生命周期和 LIVE Manual/Liquidation 请求经 Application/API → OnlyEngine → target
Runtime Command boundary，必须具有 authorization、stable request identity、idempotency 和 audit。Web 不访问 Manager、Broker SDK
或 Persistence，也不成为 Runtime control/economic authority。

## 17. Plugin Boundaries

Core 位于 `src/onlyalpha/`，只依赖公共 Port、Plugin API 和 Domain DTO，不导入具体插件。插件依赖方向固定为：

```text
Concrete DataSource / Broker Plugin
→ onlyalpha.plugin.api + public Domain / Port
→ Core orchestration
```

Virtual Broker、Tushare 和 MiniQMT 位于各自 distribution。插件必须提供稳定 descriptor/capability/config/lifecycle，把 SDK 异常转换为可诊断错误，并将 callback 数据标准化后送入 Runtime queue；不得在 import 时访问外部环境、泄漏 SDK 对象或持有 Runtime Manager。

缺失或不兼容插件必须明确失败，Core 不提供隐藏 Synthetic/Virtual/Placeholder fallback。

## 18. Public vs Internal API

稳定使用入口优先为：

```text
onlyalpha.engine
onlyalpha.config
onlyalpha.domain.*
onlyalpha.strategy
onlyalpha.factor
onlyalpha.indicator
onlyalpha.plugin.api
```

Runtime Planner、Environment Builder、Assembly Plan、Assembler、Session、Manager、Registry 内部容器、ExecutionProcessor 内部步骤、Projection applier、Recovery orchestration state 和 persistence schema 属于内部实现。

当前根包和 `onlyalpha.runtime` 仍导出部分具体目标 Runtime 类；`onlyalpha.config` 仍导出 Assembly DTO，`onlyalpha.cluster`
仍导出 `OnlyClusterManager`。这些是当前可导入事实和待收紧 API debt，不自动构成长久稳定合同。历史 Paper/Shadow Runtime
导出已删除，不存在 compatibility alias。

## 19. Dependency Direction

逻辑依赖方向：

```text
Domain / canonical value objects
        ↑
Ports / public contracts
        ↑
MarketData, Market Rule, Risk, Order, Execution authorities
        ↑
Trading Runtime orchestration      Research Runtime orchestration
        ↑                                  ↑
OnlyEngine planning / lifecycle / aggregation
        ↑
Application / CLI / API

Concrete plugins → public Plugin API / Ports
```

Domain 不依赖 Core 外层。Core 不依赖具体 Provider/Broker SDK。Strategy/Factor 不依赖 Engine、Gateway 或 mutable Manager。Research 与 Trading Runtime 可以复用纯 Domain/definition，但不通过互相实例化对方的 mutable authority 复用。

## 20. Current Product Capability Boundary

截至 2026-08-10，当前正式完整产品纵切面是 Backtest 下的有限 Cash-Long durable surface：

```text
Runtime          : BACKTEST
Market Product   : GENERIC_T0_CASH@1
Account Type     : CASH
Order Type       : LIMIT
Position Side    : LONG
Position Mode    : NETTING
Open / Close     : BUY OPEN / SELL CLOSE
Fill             : Whole / Partial / Multi-Fill
Terminal         : Cancel / Reject / Expire
Cluster          : Single / Multi-Cluster
Persistence      : Memory / SQLite
Recovery         : Checkpoint / Restart / Forward Recovery
```

`CN_A_SHARE_DURABLE_BACKTEST_V1` 是已认证的有限 A 股 Backtest 产品合同；它不升级完整 A 股市场范围，也不证明所有 A 股产品或实时 Runtime 可用。

当前未完成项：

- `RESEARCH`：目标 Runtime，Factory unsupported；Dataset/Calculation/Job/Factor/Sweep/Target/Statistics/Research Result 与 portable
  Research Artifact 已实现，Query/API/Web 与产品 Runtime lifecycle 尚未实现；
- `LIVE`：目标 Runtime，Factory unsupported，durable outbound Broker command、同步/对账与长期恢复尚未实现；
- `SIM`：当前认证不覆盖 Real Broker、长期生产运维、24h soak 或 broad MiniQMT compatibility matrix。

从当前实现到目标架构的阶段与删除条件见 [Roadmap](roadmap.md)。
