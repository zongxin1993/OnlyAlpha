# OnlyAlpha 路线图

本文件只描述从当前实现迁移到目标架构的阶段、退出条件与非目标。当前事实以源码、正式测试和产品认证为准；目标 Runtime taxonomy 由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 冻结。

## 目标 Runtime taxonomy

```text
RESEARCH  Historical + Vectorized/Batch + Research-oriented
BACKTEST  Historical + Event-driven + Virtual Broker + Full Trading Kernel
SIM       Realtime + Event-driven + Virtual Broker + Full Trading Kernel
LIVE      Realtime + Event-driven + Real Broker + Full Trading Kernel
```

`PAPER` 与 standalone `SHADOW` 不是目标 Runtime。当前源码中的相关类型是 migration debt，不是长期兼容合同。

## 当前产品事实（2026-08-12）

当前正式可用的完整产品纵切面是 Backtest 下的 `GENERIC_T0_CASH`、CASH、LIMIT、LONG/NETTING、BUY OPEN 与 SELL CLOSE，支持 Whole/Partial/Multi-Fill、Terminal Transaction、Memory/SQLite、Checkpoint/Restart/Forward Recovery、单/多 Cluster、Result/Analytics/Artifact/Report。

SIM 的当前正式范围是 `GENERIC_T0_CASH@1` 下的 realtime normal path：`OnlySimRuntime` 使用 Live Clock、historical bootstrap/live handoff、Virtual Broker 和共享 Trading Kernel，标准 Accepted/Trade fact 均进入 Broker Inbound Queue、Durable Transaction 与 Ordered Projection。SIM 的 Runtime Persistence 可使用 Memory 或 SQLite，且与 disabled streaming checkpoint 正交。该范围不包含 realtime gap recovery、reconnect、streaming checkpoint/restart 或长期生产运行。

当前 legacy `PAPER` 路径已完成当前 Market Product binding 下真实 MiniQMT 的 Historical/Open-Market Bootstrap、Historical-to-Live handoff、watermark、1m external bar、1m-to-3m aggregation、warmup/observation、Strategy intent、Shadow suppression、Reservation create/release 和 ordered shutdown。它仍是 read-only market observation + Shadow execution，只作为 Sim streaming migration baseline；reconnect、realtime gap recovery、streaming checkpoint/recovery、Real Broker submission/synchronization 与长期生产运行尚未闭环。

当前实现状态：

- `BACKTEST` 已实现，是 primary Runtime；
- `SIM` 已有 canonical enum/config spelling、`LIVE_CLOCK` environment identity、专用 composition Factory 和可执行 realtime Virtual Broker normal path；
- `RESEARCH` 与 `LIVE` 是目标 Runtime，但当前 Factory 返回 unsupported；
- standalone `SHADOW` Factory 返回 unsupported，且不是目标 Runtime；
- `PAPER` 是待迁移并删除的旧源码路径。

Market Product plugin 或 identity 存在不代表产品可用。`CN_A_SHARE_CASH` plugin 已拥有版本化 Reference、Pre-Trade Rule 与 Production Fee Authority，其 Cash-Long economic shape 可由统一 Durable Kernel 识别。P4.3 的有限合同 `CN_A_SHARE_DURABLE_BACKTEST_V1` / `product_contract_version = "1"` 已完成 Product Conformance、恢复/确定性、静态/构建和同提交远端质量门禁，因此该有限产品为 **CERTIFIED**。这不升级完整 A 股市场范围，也不表示所有 A 股、Sim 或 Live 产品可用。

## 已完成阶段

- P0 — Test Baseline & Feedback Loop Closure：正式 test lanes、metrics、分层 marker 与质量门禁。
- P1 — Fee Authority Integrity Closure：Market Fee Pack 与 Broker Fee Contract 独立版本化 authority。
- P2 — Fee Reconciliation Semantic Closure：Evidence、Policy、Correction、Blocker 与 Recovery 语义。
- P2.1 — Reconciliation Composition Stabilization：统一 Policy Registry、Currency identity 与 Broker optional port。
- P3 — CN A-Share Production Fee Product：普通 CNY A 股印花税、过户费、Broker Contract Snapshot 与 Recovery/Reconciliation 兼容性。
- P4-0 — Runtime Composition & Execution Hygiene Closure：canonical Runtime Environment、全局 mutable identity 冲突、单一 Component Registry ownership、staged/atomic Cluster composition、Execution 历史路径删除与 CI 工具链确定性。
- P4.1 — Durable Execution Capability Semantic Authority：Market identity 退出 permission authority；唯一 pure Resolver 按 immutable economic shape、精确 Reservation shape 与 Account/Ledger parity 决定支持，并把版本化 proof 写入 committed fact。
- P4.2 — Durable Broker-Driven Order Lifecycle Closure：`ORDER_ACCEPTED`、`TRADE_FILL`、`ORDER_TERMINAL` 统一进入 Prepared Transaction / Durable Commit / Ordered Projection / Forward Recovery；BUY OPEN 与 SELL CLOSE 的 Accepted、Cancel、Reject、Expire 显式声明全部受影响 authority，旧 direct lifecycle mutation 和 Reservation 协调旁路已删除。
- P4.3 — CN A-Share Production Durable Product Conformance：**DONE / CERTIFIED**。有限 `CN_A_SHARE_DURABLE_BACKTEST_V1` 已完成 Production Authority、BUY OPEN、T+1、SELL CLOSE、Whole/Partial/Multi-Fill、Terminal、Memory/SQLite、多实例 Forward Recovery、Result/Artifact Determinism 与同提交远端质量证明。
- P5 — Market Product Composition Authority Neutralization：**DONE / CERTIFIED**。Core Market Product Contract、Generic T0 Canonical IR、CN A-share plugin authority/runtime cutover、strict formal identity、recovery composition identity 与 workspace release dependency graph 已由正式门禁冻结；认证只在包含最终报告的提交通过同 SHA `Layered Quality / quality-gate` 后成立。

此前建立且仍有效的内核包括统一 Market Runtime、版本化 A 股 Reference/Rule Decision、Prepared Transaction、Durable Commit、Ordered Projection、Projection Ready、完整 Long Close、多部分成交、Multi-Cluster Close Cost、Checkpoint 与因果 Forward Recovery。历史细节保存在 `docs/adr/` 与 `docs/reports/`。

## 当前阶段：P6 — Sim Streaming Runtime Closure

### P6.0 — Trading Runtime Kernel Extraction（完成）

共享 mutable trading authorities 已从 `OnlyRuntime` 提升到 Runtime-neutral `OnlyTradingKernel`；Backtest 与 legacy Streaming 现在是同一 Trading facade/Kernel 的 sibling composition，不再存在 `Streaming -> Backtest Runtime` implementation dependency。Backtest finite execution 由 `OnlyBacktestDriver` 驱动，Streaming 的 subscription/worker/termination 由 `OnlyStreamingMarketDataDriver` 驱动，并已有 AST architecture gates 固化 dependency direction 与 mode-neutral Kernel config。

P6.0 只完成 ownership/dependency inversion，未改变 Order、Position、Allocation、Fee、Settlement、Transaction、Projection 或 Recovery 经济语义，也未实现 SIM/LIVE、删除 PAPER/SHADOW、补齐 streaming reconnect/gap recovery/checkpoint。

### P6.1 — Runtime Control Boundary & Trading Semantic Neutralization（完成）

Runtime product compatibility guard 已移动到 operational `OnlyRuntime` boundary；Strategy-facing Context、Runtime
logger、`OnlyTradingRuntimeFacade` 和 Trading Kernel 不再依赖 `OnlyRuntimeMode`。Fee、Market Rule、Position、Risk、
Order、Execution、Settlement、Account 与 Strategy Ledger 的 mode-neutral 现状由 AST architecture gate 固化。

Streaming stop 已定义为 processing permission cutoff：`STOPPING` 在 shutdown action 前建立，Worker 不再 drain
pending queue、不 flush pending Live Bar，future-event wait 可中断，且 stop 后不会开始新的 MarketData processor/result
callback。P6.1 不实现 SIM、Virtual Broker streaming wiring、gap/reconnect recovery 或 streaming checkpoint/restart。

### P6.2 — SIM Runtime Product Identity & Composition Contract（DONE / CERTIFIED）

SIM 已成为 canonical Runtime product identity，配置 parser、Runtime environment、Planner grouping 与默认 Runtime
Factory Registry 均能识别它。`OnlySimRuntimeFactory` 只负责 deterministic fail-closed composition validation：要求显式
`SIMULATED` execution capability、无 finite range、checkpoint disabled、恰好一个 historical+live DataSource、一个 Account，
以及恰好一个声明 `simulated_execution` 和 submit/cancel/query minimum capabilities 的 Broker。Real Broker、SHADOW/LIVE
execution capability、缺失/多余组件和不完整 capability 均以稳定 SIM-specific code 拒绝。

P6.2 当时不创建空壳 `OnlySimRuntime`，不包装 PAPER/Backtest/Shadow，也不修改 Trading Kernel、TradingFacade、Strategy
Context、Virtual Broker、MiniQMT 或任何交易经济/恢复权威。该阶段合法组合仍以
`SIM_EXECUTION_WIRING_PENDING` fail closed；后续 P6.3 已替换这个临时边界。P6.2 基线提交
`b2f5df9a2c6138b720f8a3a3a54e803d0d7584f0` 已通过同 SHA 的 static、build、core-full、recovery、ashare、
miniqmt-contract、quality-gate 与 Nightly Exhaustive 认证。

### P6.3 — SIM Realtime Virtual Broker Execution Wiring（DONE）

P6.3 已组合正式 `OnlySimRuntime -> OnlyStreamingRuntime -> OnlyTradingRuntimeFacade -> OnlyTradingKernel` 路径。
SIM Factory 创建 Live Clock、MarketData/Broker Inbound Queue，通过 SPI 解析 historical+live DataSource 与 simulated
Broker，并要求 Broker 提供显式 deterministic driver；缺失该能力会以稳定 SIM-specific code fail closed。SIM 不导入或包装
PAPER、Backtest、Shadow，也没有新增 SIM 专用经济 authority。

当前因果顺序由正式集成测试冻结：

```text
Bar N enters normalized realtime pipeline
→ Strategy creates order
→ Virtual Broker publishes Accepted after dispatch
→ ORDER_ACCEPTED durable commit / ordered projection
→ no same-bar fill
→ Bar N+1 broker matching runs before Strategy
→ TRADE_FILL durable commit / ordered projection
```

停止 Runtime 只是 future processing permission cutoff，不会把 Accepted order 自动取消或创造额外交易事实。P6.3 只关闭
realtime normal path，不包含 gap/reconnect/checkpoint/restart；`OnlyEngine.run()` 仍只接受有限 BACKTEST，SIM 使用
`initialize/start/wait/stop/close`。

### P6.4 — Realtime Gap + Reconnect Recovery（下一阶段）

P6.4 将定义唯一 realtime gap authority、重连后的 provider/broker catch-up 边界、确定性去重与 fail-closed 恢复语义。
在这些正式合同与测试完成前，不得把 P6.3 normal path 描述为 long-running production-ready SIM。

P6 不是新建一套与 Backtest 分离的 Sim 系统。它迁移并清理当前 `PAPER` 的 useful streaming infrastructure：

```text
Current PAPER streaming infrastructure
→ Realtime MarketData + LiveClock
→ Historical bootstrap where needed
→ Historical-to-Realtime handoff + Watermark
→ Gap detection / Gap recovery / Reconnect
→ Streaming checkpoint / Restart
→ Virtual Broker
→ Full Trading Kernel
→ SIM Runtime
```

Sim 必须产生标准 Accepted/Trade/Terminal facts，复用 Backtest 的 Market Rule、Risk、Reservation、Order、Execution Processor、Transaction、Position、Allocation、Account、Strategy Ledger、Fee、Settlement、Result 与 Recovery semantics，并永远不向 Real Broker 发单。

P6 退出条件：

- `SIM` 通过正式配置、Factory 与 Engine streaming lifecycle 可用；
- 当前 Shadow suppression 被 Virtual Broker + full Trading Kernel 替代；
- realtime gap/reconnect/checkpoint/restart 的失败与恢复边界闭环；
- `PAPER` Runtime 和 standalone `SHADOW` Runtime 源码、配置、测试与 public spelling 被删除；
- 不保留 alias、deprecated spelling 或 compatibility wrapper。

## P7 — Vectorized Research Runtime

P7 实现 Research，不实现“Vectorized Backtest”：

```text
Historical Dataset
→ Vectorized Indicator
→ Factor / Feature
→ Parameter Sweep
→ Statistics
→ Research Result
→ Research Artifact
→ Query / API
→ Web Visualization
```

Research Job / Plan 不伪装成 Trading Cluster，也不为结构对称创建 Account、Position、Order、Broker、Reservation 或 Transaction Manager。Web 只读取 immutable Research Result / Artifact，不操作 Runtime internal mutable state。

P7 退出条件包括稳定 Research Job/Plan contract、deterministic dataset/calculation identity、可序列化 Result/Artifact、只读 Query/API 和 Web boundary。

## P8 — Durable Broker Outbound Command and Synchronization

P8 为目标 Live 建立外部执行前置能力：

- durable outbound Broker command；
- submission idempotency 与 retry policy；
- ACK / Reject / Unknown 状态；
- Broker query；
- Account / Order / Trade / Position synchronization；
- local canonical state 与 Broker evidence reconciliation；
- reconnect 后的 gap detection/recovery；
- command、fact、checkpoint 与 recovery identity。

Broker snapshot/evidence 不能覆盖 committed local history；差异必须通过正式 reconciliation fact/policy 表达。

## P9 — Live Runtime Foundation

P9 在 P8 和共享 Trading Kernel 上组合：

```text
Realtime MarketData
+ LiveClock
+ Real Broker Adapter
+ Durable Broker Command
+ Broker Facts / Synchronization / Reconciliation
+ Long-running Checkpoint / Recovery
+ Production Operations
→ LIVE Runtime
```

Live 不能通过 Runtime-mode economic branch、Broker direct Manager mutation 或复用 legacy Shadow path 实现。真实资金提交必须保留独立 manual/safety gate，并通过正式产品验收后才可启用。

## 后续候选

在 P5–P9 闭环后再评估：

- Multi-account；
- Multi-broker；
- Multi-data-source；
- 更广 A 股产品；
- Futures / Margin；
- Crypto；
- Distributed Research；
- Distributed Event-driven Backtest。

Distributed Event-driven Backtest 只表示并行执行多个完整 Backtest job，不得用 vectorized approximation 替换 canonical trading semantics。

## Roadmap 门禁

- 领域对象、Profile、Factory、Manager、Fixture 或单组件测试存在，不代表产品可用；
- Target architecture 与 current implementation 必须分开陈述；
- Backtest 保持 event-driven，Research 才允许 vectorized execution；
- Backtest/Sim/Live 共享一个 trading semantic core；
- Runtime Type 不是 Execution Permission；
- 不创建 Runtime-specific duplicate economic authority；
- 不新增 `PAPER` 或 standalone `SHADOW` 产品依赖；
- 不以永久兼容层代替迁移和删除。
