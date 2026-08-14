# OnlyAlpha 路线图

本文件只描述从当前实现迁移到目标架构的阶段、退出条件与非目标。当前事实以源码、正式测试和产品认证为准；目标 Runtime taxonomy 由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 冻结。

## 目标 Runtime taxonomy

```text
RESEARCH  Historical + Vectorized/Batch + Research-oriented
BACKTEST  Historical + Event-driven + Virtual Broker + Full Trading Kernel
SIM       Realtime + Event-driven + Virtual Broker + Full Trading Kernel
LIVE      Realtime + Event-driven + Real Broker + Full Trading Kernel
```

历史 `PAPER` 与 standalone `SHADOW` 不是目标 Runtime；P6.6 已从 active source、配置、Factory、测试 fixture 与 public contract 删除这些产品 spelling，且未保留 alias 或 wrapper。

## 当前产品事实（2026-08-14）

当前正式可用的完整产品纵切面是 Backtest 下的 `GENERIC_T0_CASH`、CASH、LIMIT、LONG/NETTING、BUY OPEN 与 SELL CLOSE，支持 Whole/Partial/Multi-Fill、Terminal Transaction、Memory/SQLite、Checkpoint/Restart/Forward Recovery、单/多 Cluster、Result/Analytics/Artifact/Report。

SIM 的当前正式范围是 `GENERIC_T0_CASH@1` 下的 realtime normal path、same-process continuity recovery 与 SQLite durable
checkpoint/new-process restart：`OnlySimRuntime` 使用 Live Clock、historical bootstrap/live handoff、Virtual Broker 和共享 Trading Kernel，
标准 Accepted/Trade fact 均进入 Broker Inbound Queue、Durable Transaction 与 Ordered Projection；unexpected gap、STALE 或 disconnect
会撤销新订单权限并确定性修复 continuity。checkpoint-enabled SIM 要求稳定 state root、Runtime State Lease、subscribe-first recovery、
Timer durable occurrence、post-recovery authority validation 和 verified recovery checkpoint。该范围不包含 Real Broker reconciliation、
24h soak、长期生产运维或 broad MiniQMT compatibility matrix。

当前实现状态：

- `BACKTEST` 已实现，是 primary Runtime；
- `SIM` 已有 canonical enum/config spelling、`LIVE_CLOCK` environment identity、专用 composition Factory 和可执行 realtime Virtual Broker normal path；
- `RESEARCH` 与 `LIVE` 是目标 Runtime，但当前 Factory 返回 unsupported；
- active Runtime taxonomy 只有 `RESEARCH / BACKTEST / SIM / LIVE`；
- historical Paper durable state 不会被转换为 SIM state，配置旧 spelling 会 fail closed。

Market Product plugin 或 identity 存在不代表产品可用。`CN_A_SHARE_CASH` plugin 已拥有版本化 Reference、Pre-Trade Rule 与 Production Fee Authority，其 Cash-Long economic shape 可由统一 Durable Kernel 识别。P4.3 的有限合同 `CN_A_SHARE_DURABLE_BACKTEST_V1` / `product_contract_version = "1"` 已完成 Product Conformance、恢复/确定性、静态/构建和同提交远端质量门禁，因此该有限产品为 **CERTIFIED**。这不升级完整 A 股市场范围，也不表示所有 A 股、Sim 或 Live 产品可用。

## 已完成阶段

- P7.4 — Research Job / Plan Contract & Deterministic Orchestration：exact immutable Plan、verified Result reuse、
  `RESULT_NOT_FOUND`-only execute、P7.2/P7.3 composition、phase-aware failure、re-entry recovery 与 same-job concurrency
  convergence 已本地实现并通过完整本地 release/coverage 门禁；Research Runtime 仍 unsupported，最终 SHA 远端认证仍待完成。

- P7.3 — Calculation Result Identity & Immutable Calculation Store：logical Result Content / Calculation Result identity、
  defensive durable admission、exact manifest、partition byte/semantic integrity、staged verified atomic publish、verified reload、
  idempotency 与 deterministic conflict 已本地实现；Research Runtime/Job、Parameter Sweep、Research Result/Artifact 和 API/Web
  不在本阶段，最终 SHA 远端认证仍待完成。

- P7.2 — Research Calculation Backend & Deterministic Execution：verified Arrow Dataset admission、exact RESEARCH backend、显式
  source binding、instrument-isolated canonical DAG execution、官方 Indicator Decimal batch backend、Trading↔Research exact
  characterization、ephemeral output 与 process-independent identity 已本地实现；durable Result authority 后续已由 P7.3 实现，
  最终 SHA 远端认证仍待完成。

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

### P6.4 — Realtime Market Continuity & Same-Process Recovery（实现完成）

P6.4 已完成 continuity assess/commit 分离、unexpected-gap admission cutoff、`DEGRADED/RECOVERING` phase、Calendar-aware historical repair、recovery sequence normalization、同一 MarketData Pipeline replay、恢复期 Strategy 新订单抑制、既有 Virtual Broker order 推进、buffered suffix catch-up、STALE/disconnect 触发、MiniQMT same-process reconnect 与显式 LIVE resume proof。恢复失败一律进入 `FAILED`，不会自动取消订单或创造 synthetic terminal trading fact；Stop 在 blocked historical I/O 返回后仍拥有 processing cutoff authority。

该阶段仍不包含 streaming checkpoint、new-process restart、Real Broker reconciliation 或 long-running operations；这些分别属于 P6.5 及后续阶段。P6.4 只有 final SHA 的 static、build、core-full、recovery、ashare、miniqmt-contract 与 quality-gate 全部成功后才能标记 `DONE / CERTIFIED`。

### P6.5 — Streaming Durable Checkpoint & New-Process Recovery（实现完成）

Runtime lifecycle 已分为 `initialize = local durable bootstrap` 与 `start = external driver recovery + common finalization`。
SIM Factory 正式接受 `MEMORY + checkpoint=false`、`SQLITE + checkpoint=false` 和带稳定 state root 的
`SQLITE + checkpoint=true`；checkpoint-enabled SIM 通过 Runtime State Lease 保持 single writer。

Streaming restart 先订阅并 buffer realtime evidence，再按 checkpoint continuity frontier 做 historical repair、transaction-tail/Timer
恢复、buffered suffix merge 和 continuity proof。恢复期 Strategy normal trading permission 关闭；post-recovery authority validation、
checkpoint atomic write 与 reread verification 完成后才恢复 Cluster、Timer 和 LIVE admission。Closed-Bar/Timer checkpoint cadence 位于
唯一 Semantic Lane exclusivity 内，physical MarketData queue empty 不再是 realtime quiescence invariant，partial live Bar 和 transport
queue 永不 durable。独立 `sim-recovery` lane 已接入 PR/master/release gates。

P6.5 只有 final SHA 的 static、build、fast、integration、core-full、recovery、sim-recovery、ashare、miniqmt-contract 与
quality-gate 全部成功后才能标记 `DONE / CERTIFIED`。

P6 不是一套与 Backtest 分离的 Sim 系统。最终 ownership 为：

```text
Product-neutral Streaming control plane
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

### P6.6 — Runtime Taxonomy Migration & Legacy Removal（实现完成，待 final SHA 远端认证）

P6.6 已将 active Runtime enum、config vocabulary、Factory Registry 与 public exports 一次性切换为
`RESEARCH / BACKTEST / SIM / LIVE`，删除 `runtime/paper`、`runtime/shadow`、Shadow execution suppression、旧
acceptance runner/config 和相关 product tests。通用 subscription、bootstrap/handoff、watermark、continuity、gap/reconnect、
timer、checkpoint 与 recovery 继续由 product-neutral `runtime/streaming` 拥有；Virtual Broker、persistence、state lease 与
SIM composition 继续由 `runtime/sim` 拥有。未修改 checkpoint/persistence schema，也不支持 Paper durable state 自动转换。

P6 Final Hardening 进一步关闭了 Engine multi-Runtime start 的 partial-start world、Streaming processing diagnostics 无界增长，以及 certification report 的 self-reference cycle。Development Quality 与 Final-SHA Certification 已分离；后者以不可变 `subject_sha` 为对象，强制 static/build/canonical lanes/branch coverage/Semgrep/CodeQL 全部真实成功并输出外部 evidence artifact。阶段只能在对应 final SHA 的完整 local lanes 与该 remote artifact 均取得真实证据后升级为 `DONE / CERTIFIED`；Repository 当前已进入 P7，但没有 exact-SHA external artifact 时仍只声明本地实现/验证事实。

## P7 — Vectorized Research Runtime

### P7.0 — Calculation Definition & Plugin Boundary（ACCEPTED locally）

P7.0 已建立 Runtime-independent `OnlyIndicatorDefinition` / `OnlyFactorDefinition`、canonical calculation DAG、稳定
semantic fingerprint 以及 exact `type_id + semantic_version + backend` Registry。现有 MACD、EMA、SMA、RSI、ATR、
Bollinger、Rolling Return、Rolling Volatility 与 ZScore trading backend 已从 Core 迁移到独立 workspace plugin；Core
不反向 import concrete calculation plugin。Trading composition 由 config normalization 进入 Definition/Graph/Registry，
并保持原有 Decimal、warmup、timestamp、snapshot/checkpoint 语义。Research backend、Calculation Store 与 Research Job
不属于本阶段。P7.0.1 已补齐 exact/fail-closed Definition schema v2 / Graph schema v1、完整 DAG semantic port compatibility、backend-neutral Registry、
固定版本 reference、Factor semantic identity 边界和官方 Indicator plugin-owned characterization/coverage。最终 SHA 的
Layered Quality、CodeQL 与 Semgrep 仍需远端证据，因此这里只声明本地验收事实。

### P7.1 — Research Dataset Snapshot & Deterministic Dataset Identity（Implemented locally）

已实现 Historical Closed Bar Dataset v1、resolved Definition、exact columnar schema、provider/path/partition-independent identity、
immutable content-addressed Parquet Store、strict materialization、provenance 分离与 Research/Trading architecture firewall。Historical
Cache 仍是 acquisition optimization，不是 Dataset authority。P7.1 本身未实现 Research Runtime、Research Calculation backend、
Calculation Store、Research Result 或 Artifact；Research Calculation backend 后续已由 P7.2 实现，其余能力当前仍未实现。
P7.1 只有在 exact final-SHA remote certification 完成后才能标记 CERTIFIED。

### P7.2 — Research Calculation Backend & Deterministic Execution（Implemented locally / closure verified）

已实现 verified Dataset admission、exact `kind + type_id + semantic_version + RESEARCH` backend resolution、显式且无 coercion 的
Historical Bar source binding、instrument-isolated canonical DAG execution、严格 output validation、fresh-process determinism 与
只包含 Dataset Snapshot、Calculation Graph、RESEARCH backend kind 的 calculation fingerprint。官方 Indicator plugin 为受支持的
semantic versions 提供独立 Decimal Research backend，并以 Trading↔Research characterization 冻结语义；ATR `@1` 保持原定义且
无 Research registration，ATR `@2` 显式声明 high/low/close 并支持两类 backend。Research Runtime Factory 仍 intentionally
unsupported，官方 Factor plugin 仍为空，输出仍是 ephemeral execution object。

该段描述 P7.2 当时的边界；P7.5 已在不改变 P7.2 Calculation identity 的前提下提供正式 Factor/Scorer，并将内部执行
升级为 semantic-node-first。

### P7.3 — Calculation Result Identity & Immutable Calculation Store（Implemented locally）

已实现 Result Content fingerprint、Calculation Result fingerprint、`calculation_fingerprint` durable primary key、exact/versioned
manifest、`(node_fingerprint, instrument_id)` logical partition、Parquet byte hash、logical semantic hash、defensive execution
admission、verified Dataset/Graph linkage、staged read-back verification 与 atomic rename。已有相同结果幂等复用，已有不同结果
以 `DETERMINISTIC_RESULT_CONFLICT` 拒绝；corrupt target 不覆盖、不修复，正式读取只提供 verified path。physical root、
compression、row-group 与 `created_at` 不进入 semantic identity。

P7.3 没有激活 Research Runtime，也没有实现 Research Job/Plan、Parameter Sweep、Factor Research、Research Result/Artifact、
Query/API/Web 或 mutable Calculation Cache。Calculation Result、Research Result 与 Research Artifact 继续保持不同 authority；
exact final-SHA remote certification 尚未发生，因此当前只声明 implemented locally。

### P7.4 — Research Job / Plan Contract & Deterministic Orchestration（Implemented and verified locally）

已实现只包含 exact Dataset Snapshot fingerprint 与 canonical Calculation Graph 的 immutable resolved Plan，并复用现有
`calculation_fingerprint` 作为单作业完整语义 identity，不创建重复 Job/Plan fingerprint。正式 orchestrator 先调用 Result
Store `load_verified()`：verified authority 返回 `REUSED`，只有 `RESULT_NOT_FOUND` 进入 P7.2 deterministic execution 与 P7.3
immutable commit；corrupt/invalid、Dataset verification、calculation、commit 和 deterministic conflict 均按明确 phase 保留稳定
code 并 fail closed。成功 Outcome 只表达 `SUCCEEDED + EXECUTED/REUSED + Calculation/Result identity`。

恢复采用 deterministic re-entry：commit 前中断允许相同 Job 重算，commit 后 Outcome 前中断通过 verified reuse 收敛；并发
相同 Job 依赖 P7.3 atomic/idempotent/conflict authority 收敛，不增加 Job DB、lease 或 global lock。Research Job package 不导入
Trading authorities，不激活 Research Runtime Factory。Parameter Sweep、Statistics、Factor Research product、Research Result/
Artifact、Scheduler/Distributed Research、Query/API/Web 均不在 P7.4。

### P7.5 — Factor / Feature / Score Semantic Closure & Deterministic Factor Execution（Implemented and verified locally）

已冻结 Indicator、Feature、Raw Factor Value 与 Factor Score 边界：Feature 只是既有 Calculation node/output port，不创建新
identity/store/job；`FACTOR_VALUE` 保留原始研究值，`FACTOR_SCORE` 是 machine-readable 的 Decimal `[0,1]` semantic。
Scorer 继续使用 `FACTOR + CROSS_SECTION` Calculation 表达，direction 与 average-tie method 是 exact semantic parameters。

官方 Factor plugin 已提供 RESEARCH-only Momentum TIME_SERIES Factor 与 Cross-Section Percentile Scorer。Momentum 的两个
Rolling Return 依赖全部显式位于 canonical Graph；Factor backend 不隐藏 Indicator execution。Research executor 已从
instrument-first 升级为 semantic-node-first：TIME_SERIES node 按 stable instrument/event-time 执行，CROSS_SECTION node 按
exact timestamp 与 sorted instrument axis 执行；null、tie、singleton、direction、Decimal quantum/rounding 与 alignment failure
均有固定合同。最终输出仍 materialize 为 P7.3 `(node_fingerprint, instrument_id)` partition，P7.2 Calculation、P7.3 Result 与
P7.4 Job authority 均未复制或改写。

P7.5 专属 `research-factor` lane 覆盖物理 order/partition independence、fresh-process identity、旧 Indicator graph/result golden
identity、Result verified reload、Job `EXECUTED -> REUSED`、score range 与 architecture firewall；新增执行/Factor narrow modules
执行 100% line/branch coverage gate。当前只声明本地实现与验证；没有新 working tree 对应的 exact final-SHA remote artifact。
Parameter Sweep、Forward Return/IC/Statistics、Research Result/Artifact、Scheduler/Distributed Research、Query/API/Web 与
Research Runtime activation 仍未实现。

P7 实现 Research，不实现“Vectorized Backtest”：

```text
Historical Dataset
→ Vectorized Indicator
→ Factor / Feature
→ Factor Value / Cross-Section Score
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
