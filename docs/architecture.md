# OnlyAlpha Architecture

本文档描述长期结构、依赖方向与 Authority 边界。当前实现事实必须由源码、测试和可执行行为判断；历史工程过程由 Git history
保存，不在架构文档维护进度或验收状态。

## Repository taxonomy and protocol boundary

```text
Web / Agent
    ↓ Product API (versioned OpenAPI contract in contracts/)
onlyalpha-http-server (replaceable HTTP component)
    ↓ Application Command / Query
src/onlyalpha (stateful Kernel and canonical semantics)
    ↓ stable Plugin SPI / ports
plugs/onlyalpha-plugin-* (concrete plugins)
    ↓
External market / provider / broker
```

`packages/` contains independently buildable non-plugin components such as the Web console,
HTTP server and Gateway protocol. Web is not a Plugin and the HTTP server is not the Kernel.
The Kernel remains transport-neutral and concrete-plugin-free; its internal deterministic
trading chain uses direct typed calls. Gateway protocol is an infrastructure/data-plane
contract, while OpenAPI is the Product control-plane contract. Plugins never own Core Authority.

Runtime 产品分类与迁移方向由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 决定；多市场
拓扑与异构生命周期由 [ADR 0080](adr/0080-multi-market-platform-and-heterogeneous-runtime-lifecycle.md) 决定；目标 Live
导入、人工操作和清仓控制由 [ADR 0081](adr/0081-live-genesis-manual-workload-and-liquidation-control.md) 决定。任何“目标”
描述都不是实现完成声明。

## 1. Architecture Principles

OnlyAlpha 采用 Monorepo + 模块化单体 Core + 插件化 DataSource/Broker + typed Engine/Runtime composition。

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

`OnlyEngine` 是 Kernel 内部 execution composition owner，不是外部产品入口。产品调用链为：

```text
Web / Agent
→ Versioned Product API
→ Product Command / Query
→ Application admission / Worker
→ OnlyEngine (internal)
→ Trading Runtime Planner / Research Workload Plan
→ OnlyEngineRunAssembler
→ Runtime Factory
→ Runtime Product
→ Trading Cluster or Research Job/Sweep
```

Engine 负责 Cluster Definition、typed specification/extension validation、Runtime environment grouping、Runtime/Cluster Session、共享资源引用、装配、生命周期、Result/Artifact 聚合、`user_data` 布局和失败清理。Engine 不拥有 Order、Position、Account 或其他交易经济状态。

当前 `OnlyEngine.run()` 只接受有限 `BACKTEST`。Streaming 路径使用 `initialize/start/wait/stop/close`。有限 Research 通过
`add_research_workload()` 注册，并由 `initialize/start/run_runtime/stop/close` 驱动；它使用 Research Job/Sweep Plan，不创建
Trading Cluster。P7.11 仍显式拒绝 Research 与 Trading 在同一 Engine 中混合，完整异构生命周期尚未实现。

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

`PAPER/SHADOW` 不是正式 Runtime vocabulary，不得作为 alias 或 wrapper 返回。Streaming phase 由唯一 controller 拥有；diagnostic
projection 不得反向驱动控制流，Recovery timeout 只作为 stuck-operation watchdog。具体决定见
[ADR 0077](adr/0077-streaming-recovery-verification-and-diagnostics.md)。

## 4. Research Runtime

Research Runtime 的正式边界是 Historical + Vectorized/Batch + Research-oriented。它只拥有有限执行状态；Dataset、Calculation、
Statistics、Research Result 与 Artifact 仍由既有 immutable content-addressed Store 拥有，不属于 Runtime mutable authority。它不拥有
formal trading Account、Position、Order、Broker、Market Product、Risk Reservation、checkpoint 或 durable Trading Transaction authority。

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
RESEARCH Calculation backend provider 可以在一个 Worker process 生命周期内复用；`execute(definition, inputs)` 必须只由声明的
semantic inputs 确定，不能读取前一次 execution 留下的 mutable state。每次 execution 的 mutable state 只能是 `execute()` local，
或属于该次调用独占创建的对象。该 lifecycle contract 不新增 provider factory/session/pool，也不进入任何 semantic identity。
P7.11 已激活 finite Research Factory：Runtime 从 exact verified Dataset Snapshot 开始，按 Direct Job、Sweep、Statistics、Result、
Artifact 与 final verified load 顺序编排既有 authority，并使用 verified immutable authority + deterministic re-entry 恢复；不创建
Runtime checkpoint 或 workload semantic fingerprint。P7.8 已实现 composition-only immutable Research Result，P7.9 已实现只复制该 Result
精确选择的 Statistics rows、可脱离全部上游 Store 自验证的 immutable Research Artifact。P7.10 已在 Artifact 之上实现无状态、
transport-neutral Query Model/Service，并由独立 `onlyalpha-http-server` package 提供三个 exact-identity GET endpoint。Artifact 不是新的
Statistics 或 Research authority，Query Result 只是 ephemeral projection。P7.12 将 HTTP transport 独立升级为 schema v2，以 canonical
decimal string 表达纳秒和 cursor，并建立 `packages/onlyalpha-web-console` browser consumer：OpenAPI generated type + Zod admission 后映射为
`bigint`/exact Decimal text，URL 拥有 selection，TanStack Query 只拥有 disposable cache，Lightweight Charts 只消费显式 lossy projection。
Web 仅调用 same-origin read-only API，不读取 Artifact path/Parquet/Store，不访问或控制 Research Runtime。P8.2 已在 Runtime 外建立
PostgreSQL operational Scheduler/Worker：Run 是总体 intent/outcome，Attempt 是 lease-governed execution ownership/history；claim、heartbeat、
expiry 与 finalization 均为短事务并使用 exact Attempt/Worker fencing。Worker 重新 verified-load Dataset、复核 admission evidence，随后只经
`OnlyEngine → OnlyResearchRuntime` 执行。恢复不保存 semantic progress，而由新 Attempt 对既有 immutable authorities deterministic re-entry
与 verified reuse。`CANCEL_REQUESTED` 的 expired/no-ACTIVE recovery 不创建新 Attempt：Application reconciliation 从 resolved exact
Result Plan 对 Result + Artifact 做 non-mutating verified inspection，complete/absent/corrupt 分别原子投影为
`COMPLETED/CANCELLED/FAILED`；Scheduler 与 PostgreSQL adapter 保持 semantics-blind。P8.3 已在独立 Command/Application boundary 上
增加 UUID4 submission retry identity、PostgreSQL Run+submission 原子提交、Run exact read/keyset projection 与 cancellation CAS，并由
full Research API 组合独立 Artifact/Run Router；portable Artifact API 仍不依赖 PostgreSQL。Research YAML、P8.4 Studio 页面、
Trading/Live Web control 与完整 mixed Runtime lifecycle 尚未实现。

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

ADR 0110 freezes the quantitative asset boundary without adding execution frameworks:

```text
L1 Mathematical Operator → L2 Financial Indicator → Feature
→ L3 Alpha Factor → Factor Value/Score
→ L4 Strategy → Signal/Selection/Rank
→ Portfolio/Risk/Execution
```

Calculation and its Graph remain the only calculation abstraction and DAG authority. L1/L2 are public reusable capabilities;
production L3/L4 are private, while the main repository keeps only two non-production reference libraries. Feature remains an
output port, Factor carries a hypothesis, and immutable StrategyRevision remains runtime Strategy authority. Generic
cross-sectional rank/percentile is L1 mathematics rather than an Alpha hypothesis. Target and Research statistics remain
orthogonal evaluation infrastructure.

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

Indicator 和 Factor 没有交易权限。P9.0 Closure 后，生产 Strategy 不再是可子类化 Python callback，也不再接收订单、仓位、
账户、风险或 Broker Context。唯一执行链是 `strategy_fingerprint → load_verified StrategyRevision → TRADING Calculation graph →
StrategyDecision`。Cluster Factory 只把 resolved `OnlyStrategyExecutionPlan` 交给 Cluster，Cluster 内部唯一
`OnlyRevisionStrategyAdapter` 同步产生 `ELIGIBILITY/ENTRY/EXIT`，并通过 `OnlyClusterPipelineResult.strategy_decision` 显式交付。
`StrategyDecision` 不是 Order Intent；Portfolio/Position Policy、Risk 与 Order 仍是下游独立权威。

Trading Resolver 只验证 Revision 已绑定的 exact TRADING implementation，不导入或要求 RESEARCH runtime backend。Research Calculation
在读取 Dataset 行前冻结 exact per-node implementation plan，并把 Result producer provenance 发布为独立 immutable Execution Evidence；
Calculation Result identity 不包含 implementation identity。Completed Run 持有 exact Evidence fingerprints，legacy Run 缺少 provenance
时不可 Freeze。Freeze 阶段只从 Run-linked Evidence 读取 historical RESEARCH implementation，并由 actual-backend Equivalence Evidence
V2 验证 exact node + Research/Trading pair + system profile/corpus；current RESEARCH Registry 不得重解释历史事实。P9.0 BAR admission 只允许
`FINAL_ONLY + RAW_ONLY`。Calculation registration 显式声明 `STATELESS/CHECKPOINTABLE`；Promotion 顺序只由
`previous_record_fingerprint` 链重建，audit timestamp 不参与语义排序。

Runtime-readable Strategy authority 固定为 `strategy/frozen-revisions`。`OnlyStrategyRevision(...)` 仍是 Domain constructor，但只有
verified Freeze 可获得内部 publisher capability；Runtime、Cluster、Backtest、SIM 与 Promotion 只接收 reader capability。旧 raw
`strategy/revisions` namespace 不会被自动信任、复制或用于 Runtime resolution。

### 6.1 Target LIVE Manual Workload

目标 `MANUAL` workload 只存在于 LIVE，与 Strategy Cluster 并列但不伪装成 Strategy。它拥有独立 workload identity、Allocation、
Ledger、operator provenance、permission 与 audit，mutable authority 仍由 Live Runtime 独占。人工订单从 authenticated
Application/API 经 Engine 进入同一 Market Rule、Risk、Reservation、Order、Broker、Durable Transaction 与 Ordered Projection
链。Backtest、Sim、Research 不接受产品级交互式人工交易。

## 7. Runtime Environment Composition

Kernel 内部组合链：

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

`onlyalpha-plugin-generic-t0-cash` 与 `onlyalpha-plugin-cn-ashare` 通过 `onlyalpha.market_products` entry point 自动发现，各自拥有 plugin-local Reference、deterministic Reference Authority、pure Policy Compiler 和 Market Fee Pack。Core composition root 只持有 neutral `OnlyMarketProductFactoryRegistry`，没有 concrete import、hard registration 或 Generic fallback。tests-only `TEST_T2_MARKET` 以 tick `0.25`、quantity step `7`、T+2 证明同一 IR 不依赖 Generic branch。

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

Observation 是只读诊断，不成为交易 authority，不能阻塞核心 Runtime，停止后不得继续增长。Research Artifact 与 Trading Result
是不同 DTO/语义；P7.12 Research Web 的数据读取只通过 HTTP v2 Query/API 消费 immutable Artifact projection。Exact nanosecond 使用
`bigint`，Decimal 使用 string；chart seconds/number 是可失败、不可反向传播的 presentation projection。

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

Quantitative capability dependencies follow ADR 0110: L1 Operators may depend only on public Calculation contracts; L2 Indicators
may depend on Core contracts and L1; L3 Alpha may depend on public L1/L2; L4 authoring assets may reference admitted L1/L2/L3
identities. Core imports none of their concrete implementations, public packages do not depend on examples, and examples are not
default production dependencies.

ADR 0111 gives private L3/L4 libraries a source/editable development mode and a uv/pip distribution mode. Production Calculation
discovery continues to use installed entry-point metadata only. L4 checkout roots and package resources are interchangeable sources of
the same Product authoring document before Freeze; no filesystem path participates in StrategyRevision or Runtime identity.

ADR 0112 defines the common `onlyalpha.quant_assets` management SPI. Each L1-L4 distribution contributes a versioned, content-addressed
provider to one immutable catalog generation. Refresh validates a complete generation and atomically publishes it for new work; existing
work retains its prior snapshot. This management catalog does not replace Calculation Graph, `onlyalpha.calculations`, Product API, Freeze
or StrategyRevision authorities.

ADR 0115 separates the complete private-asset lifecycle: Git commit and deterministic experiment identity are authoring provenance;
positive-integer asset versions identify immutable L3/L4 semantics; implementation fingerprints identify exact executable code;
positive-integer provider versions identify admitted content; immutable CalVer distributions identify released artifacts; Catalog
Generation selects an exact provider set for new work; Research Evidence owns outcomes; and verified Freeze alone creates the
StrategyRevision used at runtime. These identities cannot substitute for one another. Production private namespaces are
`private.factor.*` and `private.strategy.*`; no `latest` aliases exist.

Private release/admission gates reject semantic or provider drift and prevent release artifact overwrite. Experiments use explicit
isolated source revisions and non-production candidate providers, never normal installed production entry points. Hot plug and rollback
create/select isolated process generations for new work; they never reload modules or rebind an active Run/StrategyRevision. Missing exact
historical artifacts fail closed rather than falling forward. Dynamic Research outcomes remain in OnlyAlpha Evidence, not private source
status files or registries.

ADR 0116 closes the execution side of candidate provenance. An Authoring Execution Generation binds the exact Snapshot, candidate
executable content, Candidate Provider and complete Catalog generation to one process-lifetime Calculation composition. The independent
`packages/onlyalpha-authoring-execution-worker/` component verifies that generation before it may register presence or claim work. Normal
Research Workers claim only unbound Runs; an authoring Worker claims only Runs bound to its exact generation fingerprint, with the filter
inside the existing transactional Attempt authority. Git/path/artifact loading remains outside Core, active Runs are never rebound, and
Evidence can cross admission only when executable Provider content remains identical. Release, Catalog activation, Strategy promotion and
LIVE authorization remain separate authorities.

ADR 0117 closes the admitted distribution-to-runtime boundary. A locator-independent Distribution Artifact manifest binds exact wheel
bytes, source revision, Provider content, asset inventory, implementation fingerprints and tested Core execution identity. The independent
`packages/onlyalpha-runtime-generation-manager/` component verifies a content-addressed artifact set, installs it into a clean isolated
environment and recomputes installed Provider, Catalog and implementation closure, including Core-owned built-in implementations, before
producing an immutable RuntimeGeneration. The resulting immutable RuntimeGeneration Validation Evidence is the only proof accepted for a
`PREPARING → READY` transition. A validated environment carries a non-identity operational seal; a formal Worker must verify that seal,
the exact retained wheel bytes, installed file hashes and recomputed Provider/Catalog/implementation closure before it becomes claim-capable.

One append-only hash-chained generation ledger is the durable operational Authority for READY, `ACTIVE_FOR_NEW_WORK`, DRAINING/RETIRED
and immutable work bindings. Activation and rollback are expected-current compare-and-set transitions; a Run reads the pointer once and
retains its exact binding. Restart replays the committed facts rather than inspecting newest packages or process order. Historical
StrategyRevision resolution matches exact RESEARCH/TRADING implementation fingerprints and fails closed when unavailable or ambiguous.
`CatalogGeneration != RuntimeGeneration`, `StrategyRevision != RuntimeGeneration`, artifact identity excludes its locator, and neither
release nor activation grants Agent or LIVE authority.

Core exposes only the stable `onlyalpha.runtime_generation_work_authority` port and installed entry-point group needed by formal Research
and Backtest admission/claim paths. The runtime-generation-manager supplies the sole concrete binding/activation Authority; Core workers do
not import that infrastructure implementation. Formal admission binds the existing Product Run ID before durable queue acceptance, while
claim predicates select only IDs bound to the process generation and execution rechecks the same immutable binding. Run stores remain the
Run lifecycle Authorities and never become a second RuntimeGeneration-binding store.
If a Worker is started without both RuntimeGeneration arguments, it enters an explicit lifecycle-only no-claim composition: health,
presence and shutdown remain operable, but the authority returns no eligible work and all bind/require operations fail closed. Supplying
only one argument is invalid; formal claim capability always requires the pair and successful hosted-generation verification.

### Public Example / Private Asset Contract Parity

`examples/onlyalpha-example-alpha` and `examples/onlyalpha-example-strategies` are the public executable reference consumers of the L3
and L4 private-asset contracts. They are compatibility witnesses, not source mirrors, semantic authorities or runtime authorities. A
public-contract change affecting L3/L4 authoring, discovery, execution, Research, Evidence or Freeze must keep the corresponding example
executable in the same public change. A private capability that cannot be expressed and verified through that public contract and example
fails closed as an example-contract coverage gap; no hidden private-only Core integration path is permitted.

Public examples and `OnlyAlpha-alpha` / `OnlyAlpha-strategies` satisfy the same provider-neutral conformance suite against the exact Core
revision they target. Parity means equal public SPI/protocol requirements and observable contract behavior. Provider IDs, asset IDs,
source code, hypotheses and Factor/Strategy semantics intentionally differ. Public CI proves the example subjects without private secrets;
private certification selects the private subjects in its own environment and must not claim compatibility without executable evidence.
For any Core change touching Calculation SPI, `onlyalpha.quant_assets`, Catalog discovery, Research specification/API/provenance,
authoring execution, Strategy resources, Freeze or StrategyRevision admission, `PRIVATE_ASSET_IMPACT = YES`.

Private Git admission uses the repository-tracked commit and pre-push hooks to invoke one canonical local `local_strict_gate.py` on the
exact clean candidate commit. The gate proves semantic/provider transition correctness, formatting, static quality, tests, wheel build,
clean isolated installation and provider discovery; the Strategies repository additionally proves its installed Resolve → Research →
Freeze lifecycle. Agents may never use `--no-verify`, and a bypassed hook is not an admission result. Remote code-quality CI and required
status checks are intentionally inactive for these two private development repositories. Gitea carries only the candidate branch and PR
transport; it does not become admission, semantic, Evidence, merge, release, Catalog or LIVE authority. The separate release gate accepts
only clean admitted `master` to create a new immutable wheel/tag/manifest. `master` means admitted source, not an active Catalog or
production release, and Git metadata never participates in asset, Provider, Evidence or StrategyRevision identity.

ADR 0113 freezes the common L1 algebra policy: Decimal precision/quantization, inclusive complete windows, null propagation,
deterministic invalid-domain nulls, population statistics, average-tie normalized ranks, and exact RESEARCH/TRADING/checkpoint
equivalence. Cross-section L1 remains RESEARCH-only until a separate trading-plane contract exists. Public L2 WMA, ROC, windowed VWAP,
OBV and Stochastic retain explicit financial inputs and do not create a second Feature or calculation authority.

## 18. Public vs Internal API

正式外部 Product 使用入口为：

```text
Human → Web
Agent / Automation → canonical versioned Product API
→ HTTPS / JSON
→ onlyalpha-http-server
→ Product Command / Query
→ Stateful Kernel / Application authority
```

仓内不提供 Python Product SDK 或 Product CLI。Machine consumers 直接遵循 canonical OpenAPI contract；transport implementation
不得拥有 Research admission、command identity、lifecycle 或 retry authority，也不得在 HTTP failure 后 fallback 到 local Engine。

`onlyalpha.engine`、`onlyalpha.config`、`onlyalpha.domain.*`、`onlyalpha.strategy`、`onlyalpha.factor`、`onlyalpha.indicator` 与
`onlyalpha.plugin.api` 是内部工程组合或插件边界，不作为外部 Product control contract。P9.K.8 已从根包及 broad
`onlyalpha.engine/runtime/cluster` broad aggregators 不暴露 mutation constructors；root Product CLI 不存在。

Runtime Planner、Environment Builder、Assembly Plan、Assembler、Session、Manager、Registry 内部容器、ExecutionProcessor 内部步骤、Projection applier、Recovery orchestration state 和 persistence schema 属于内部实现。

具体 Engine/Runtime/Cluster implementation modules 只供内部、测试、scenario、operator 或 composition owner 使用；broad aggregators
不再提供这些 mutation constructors。`onlyalpha.config` 的 Assembly DTO 仍是内部组合值，不是外部 Product mutation contract。直接 Engine
Scenario 与 fixture 只位于工程验证语义，不能成为 Product API/CLI。历史 Paper/Shadow Runtime 不存在 compatibility alias。

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
OnlyEngine planning / lifecycle / aggregation (internal)
        ↑
Stateful Kernel / Application Command + Query
        ↑
Product HTTP Adapter
        ↑
OpenAPI-derived Web / external API consumers

Concrete plugins → public Plugin API / Ports
```

Domain 不依赖 Core 外层。Core 不依赖具体 Provider/Broker SDK。Strategy/Factor 不依赖 Engine、Gateway 或 mutable Manager。Research 与 Trading Runtime 可以复用纯 Domain/definition，但不通过互相实例化对方的 mutable authority 复用。

## 20. Product Admission Boundary

正式 Product commands/queries 只能经版本化 API。Runtime specification 是 immutable、canonical semantic input；Runtime instance
拥有不同的 run/runtime identity、lifecycle、worker、checkpoint/recovery state 和 result references。Specification fingerprint 不得
替代 instance identity，文件路径、ENV、HTTP metadata 和 idempotency key 不得污染 trading semantic identity。

Backtest Product 的 operator deployment 输入只保留 Market Product 配置与 instrument/reference resources。Portfolio、Risk、Execution、
initial Account、Strategy、Dataset 与 Kernel identities 分别来自已 admission 的唯一 authority；Worker 从这些 authority 从零构造内部
`OnlyClusterRunConfig`，不得复制完整 operator deployment document。`OnlyBacktestExecutionSemanticBinding` 是 durable Specification 与
Admission Resolution 的 canonical immutable projection，不是第二 Authority，并明确排除 Run/Attempt/Worker/path/poll interval 等 operational
identity。Worker 每次 Attempt 都重新解析 authority 并在 Engine 启动前 fail closed 于 `EXECUTION_SEMANTIC_DRIFT`。

当前支持到何种 Runtime/product depth 必须由源码与测试判断；本架构文档不维护阶段完成状态。未来建设顺序见
[Roadmap](roadmap.md)。
