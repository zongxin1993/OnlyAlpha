# OnlyAlpha 路线图

本文件只描述从当前实现迁移到目标架构的阶段、退出条件与非目标。当前事实以源码、正式测试和产品认证为准；目标 Runtime
taxonomy 由 [ADR 0068](adr/0068-runtime-product-taxonomy-and-trading-semantic-equivalence.md) 冻结，多市场/异构 Runtime 拓扑由
[ADR 0080](adr/0080-multi-market-platform-and-heterogeneous-runtime-lifecycle.md) 冻结，Live 人工控制由
[ADR 0081](adr/0081-live-genesis-manual-workload-and-liquidation-control.md) 冻结。

## 目标 Runtime taxonomy

```text
RESEARCH  Historical + Vectorized/Batch + Research-oriented
BACKTEST  Historical + Event-driven + Virtual Broker + Full Trading Kernel
SIM       Realtime + Event-driven + Virtual Broker + Full Trading Kernel
LIVE      Realtime + Event-driven + Real Broker + Full Trading Kernel
```

目标 `OnlyEngine` 可以同时持有四类 Runtime Session，且各 Runtime 生命周期独立。当前 Trading 产品采用
`One Runtime = One Account = One Market Product = One Currency`；多市场由 Engine 下多个隔离 Runtime 组合，跨市场汇总只读。

历史 `PAPER` 与 standalone `SHADOW` 不是目标 Runtime；P6.6 已从 active source、配置、Factory、测试 fixture 与 public contract 删除这些产品 spelling，且未保留 alias 或 wrapper。

## 当前状态

```text
Current Milestone: P7
Milestone State: IN_PROGRESS
Current Increment: P7.10 — VERIFIED LOCALLY
Latest Verified Increment: P7.10
P7 Final Certification: NOT COMPLETE
Next Semantic Direction: Research Web consumption/visualization and finite Research Runtime lifecycle remain open
```

`VERIFIED` 表示 increment 所要求的 targeted/affected verification 已完成；`CERTIFIED` 只表示 exact immutable SHA 的正式
certification artifact 为 `ACCEPTED`。P7.6.2 修改验证基础设施本身，因此是显式高风险 checkpoint；只有 Layered Quality、CodeQL、
Nightly Heavy Quality 与 Final-SHA Certification 的实际聚合结果全部成功后才能从上述进行中状态升级为 `VERIFIED`。这不会使 P7
milestone 自动变为 `CERTIFIED`。

## 当前产品事实（2026-08-15）

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

Market Product plugin 或 identity 存在不代表产品可用。`CN_A_SHARE_CASH` plugin 已拥有版本化 Reference、Pre-Trade Rule 与 Production Fee Authority，其 Cash-Long economic shape 可由统一 Durable Kernel 识别。P4.3 的有限合同 `CN_A_SHARE_DURABLE_BACKTEST_V1` / `product_contract_version = "1"` 已完成 Product Conformance、恢复/确定性、静态/构建和同提交远端质量门禁，因此该有限产品为 **CERTIFIED**。这不升级完整 A 股市场范围，也不表示所有 A 股、Sim 或 Live 产品可用；在 A 股 Research/Backtest/Sim/Live 四种正式产品全部闭环前，不得声称 OnlyAlpha 已正式支持整个 A 股市场。

## 已完成阶段

- P7.6 — Deterministic Parameter Sweep & Multi-Job Composition：backend-neutral full Definition re-materialization、serializable
  Graph Template、finite typed Cartesian planning、existing Graph/Job identity、JobExecutor-only sequential execution 与 deterministic
  partial re-entry 已本地实现并通过 affected canonical/coverage gates；Research Runtime 仍 unsupported，P7 Final Closure certification
  仍待完成。

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

## P6 — Historical Implemented Stage（非当前 Milestone）

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

### P6.6 — Runtime Taxonomy Migration & Legacy Removal（DONE / CERTIFIED）

P6.6 已将 active Runtime enum、config vocabulary、Factory Registry 与 public exports 一次性切换为
`RESEARCH / BACKTEST / SIM / LIVE`，删除 `runtime/paper`、`runtime/shadow`、Shadow execution suppression、旧
acceptance runner/config 和相关 product tests。通用 subscription、bootstrap/handoff、watermark、continuity、gap/reconnect、
timer、checkpoint 与 recovery 继续由 product-neutral `runtime/streaming` 拥有；Virtual Broker、persistence、state lease 与
SIM composition 继续由 `runtime/sim` 拥有。未修改 checkpoint/persistence schema，也不支持 Paper durable state 自动转换。

P6 Final Hardening 进一步关闭了 Engine multi-Runtime start 的 partial-start world、Streaming processing diagnostics 无界增长，以及 certification report 的 self-reference cycle。Development Quality 与 Final-SHA Certification 已分离；后者以不可变 `subject_sha` 为对象，强制 static/build/canonical lanes/branch coverage/Semgrep/CodeQL 全部真实成功并输出外部 evidence artifact。Major Milestone 只能在对应 final SHA 的完整 local lanes 与该 remote artifact 均取得真实证据后升级为 `DONE / CERTIFIED`；同一 Major Milestone 内的 implementation increment 以实际 affected verification 达到 `VERIFIED` 后即可继续，不能冒充 `ACCEPTED`。

## P7 — Vectorized Research Runtime

### P7.0 — Calculation Definition & Plugin Boundary（VERIFIED increment）

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

### P7.5.1 — Final-SHA Certification Reliability & Streaming Recovery Verification Closure（VERIFIED increment）

P7.5 Final-SHA `core-full` 暴露的 SIM gap-recovery timeout 已归类为 test synchronization defect：Phase Controller、Semantic Lane、
Recovery Loader 与 forward-replay production invariants 保持成立，但原测试用短于 configured historical-operation budget 的 10 秒
常量表达 recovery completion，且 timeout 只显示 `None`。P7.5.1 增加 formal phase-revision wait、统一 operational watchdog、immutable
recovery diagnostics/stage，以及 secondary-gap、blocked history STOP、catch-up STOP、reconnect 和 exactly-once regression；diagnostic
stage 不参与 Runtime 决策，持久化/Checkpoint/交易语义均未改变。

该 increment 的实现与本地验证证据已经完成，可声明 `VERIFIED`，但没有 remote exact-SHA artifact，不能声明
`CERTIFIED / ACCEPTED`。独立 Final-SHA Certification 不再是进入同一 P7 milestone 后续 increment 的默认 gate；其完整 authority
保留到 P7 Final Closure 或显式 certification checkpoint。

### P7.5.2 — Agent Verification Efficiency & Impact-Aware Quality Gate（VERIFIED increment）

P7.5.2 在不改变 Runtime、canonical lane、coverage 或 Final-SHA authority 的前提下，增加 deterministic change-set resolver、explicit
impact rules、fail-closed escalation、compact local runner、完整日志和 local verification manifest。Planner 只引用
`scripts/test_suite.py` 的 canonical lane/check identity；unknown path 与 verification infrastructure self-change 自动升级，纯 docs/prompt
change 不运行无关 Runtime lanes。该机制只优化 development feedback，不能裁剪 Final-SHA mandatory matrix，也不能产生
`CERTIFIED / ACCEPTED` verdict。

Implementation report 已记录 targeted tooling/architecture tests、static checks、全部 canonical lanes 与 all-package build 的真实本地
PASS evidence，因此 P7.5.2 达到 `VERIFIED`，P7.6 可以开始。该结论不是 `CERTIFIED / ACCEPTED`；P7 Major Milestone 仍必须在
P7 Final Closure 对一个 exact immutable SHA 执行完整 Final-SHA Certification，取得 `ACCEPTED` 后才可进入 P8。

### P7 Quality Gate Granularity Closure（VERIFIED）

P7 内部 increment 与 Major Milestone gate 已正式分离：P7.x → 下一个 P7.x 要求前一个 increment `VERIFIED`；P7 → P8 要求 P7
`ACCEPTED`。Final-SHA Certification 的 exact-SHA、static/build/canonical lanes/coverage/Semgrep/CodeQL 与 fail-closed authority 均未改变，
默认 cadence 调整为 P7 Final Closure；release、高风险 authority 变更等边界仍可使用显式 certification checkpoint。本 closure 是
governance-docs-only increment，以 current evidence 和最窄文档验证达到 `VERIFIED`，不要求 standalone Final-SHA Certification。

### P7.6 — Deterministic Parameter Sweep & Multi-Job Composition（VERIFIED increment）

P7.6 将 exact Dataset Snapshot、parameterized Graph Template 与 finite explicit parameter space 确定性编译为 ordered existing
Calculation Graph / Research Job Plans。Calculation Registry 的 backend-neutral Definition resolver 会完整重建 parameter-derived warmup、
source binding、default 与 cross-parameter constraint；禁止 parameter-only replacement。TemplateNodeId 只作为 template-local topology 与
parameter target，不进入 materialized Calculation identity，alias 继续 presentation-neutral。

Candidate 与 dimension 均 canonicalize，Cartesian cardinality 在执行前确定；duplicate normalized candidate、duplicate target 和 duplicate
materialized calculation identity fail closed。Cell identity 继续是 existing `calculation_fingerprint`，不创建 Trial/Cell/Sweep fingerprint。
Executor v1 sequential fail-fast 且只调用 `OnlyResearchJobExecutor`；partial recovery 通过同一 deterministic plan 的 verified
`REUSED/EXECUTED` 收敛，corrupt Result 不重算、不覆盖、不修复。Sweep Outcome 只是 ephemeral invocation evidence，没有 Sweep Store、
Trial DB、checkpoint、scheduler 或 worker pool。`research-sweep` canonical lane 与 impact-aware/future P7 Final Certification matrix 已纳入。
Research Runtime Factory 仍 intentionally unsupported；Statistics/Optimization/Experiment/Web 不属于本 increment。

### P7.6.1 — Remote Quality Factor Resolver Verification Closure（VERIFIED increment）

P7.6.1 不增加 Research capability，也不改变任何 Calculation/Factor/Graph/Result/Job/Sweep identity。它补齐 official Factor
owner lane 对 P7.6 Definition Resolver 的直接 semantic verification：所有 official Factor registration 必须携带 exact
RESEARCH backend 与 exact type-owned resolver；Momentum 与 Cross-Section Percentile 的 direct resolution 和 Registry
re-materialization 必须保持完整 Definition/fingerprint 等价，parameter normalization、upstream binding identity propagation、
parameter identity propagation 与 invalid semantic request fail-closed 均由 Factor plugin 自己验证。Production semantics、semantic
version 和 100% research-factor line/branch coverage gate 均未改变。最终状态取决于 immutable implementation SHA 的远端
`Layered Quality`；exact implementation SHA `6bcce0b5708d6bca00a7c4204f0e8f61d4d0b591` 的 run `31804158921` 已整体
GREEN，coverage 与 final quality-gate PASS。本 increment 达到 `VERIFIED`，不单独要求 Final-SHA Certification。

### P7.6.2 — Quality Infrastructure Closure（VERIFIED increment）

P7.6.2 不增加 Research 或 Trading capability。它修复验证系统本身：ASV benchmark definition 先经 `asv check`，GitHub fresh
runner 非交互创建 run-local machine identity，并在同一 runner/environment 中使用正式 `asv continuous` 比较 `HEAD^` 与 `HEAD`；
pytest-benchmark、ASV comparison、subject/parent SHA、ASV version 和 machine identity 均保存为实际 artifact。`--quick` 不再作为
正式 performance evidence，performance failure 保持 blocking。

Dependency security 以 root `uv.lock` 为唯一 resolved dependency audit input，使用固定 OSV-Scanner `2.5.0`，未批准 finding 与 scanner
infrastructure failure 均 fail closed。Dependency audit 是 Layered Quality aggregate gate 与 Final-SHA verdict 的 mandatory dependency，
evidence 记录 subject SHA、lock digest、scan time、scanner version、findings 与 exceptions；当前 exceptions 为 `NONE`。

本 increment 属于显式高风险 infrastructure checkpoint。implementation SHA
`f37e2dde0bb78c713054d6aed4a188ee2d39e2cf` 合并后的 exact subject
`b3a4a0da76b35646a1da28a3f72861cb7a23178a` 已通过 Layered Quality `31857857900`、CodeQL `31857857896`、
Final-SHA Certification `31859600423` 与 Nightly Heavy Quality `31862902178`；Nightly exhaustive/formal/mutation/performance
全部成功，因此状态为 `VERIFIED`。P7 仍保持 `IN_PROGRESS`，P7 Final Certification 仍为 `NOT COMPLETE`。

### P7.7 — Research Target & Statistics Semantic Closure（VERIFIED increment）

P7.7 已在不改变既有 Indicator/Factor/Graph fingerprints 的前提下增加 `TARGET` Calculation kind；官方 Target plugin 提供
RESEARCH-only `onlyalpha.target.forward_return@1`，使用 Dataset-owned adjustment、explicit price source binding、canonical
per-instrument bar offset、原 observation axis 与 insufficient-future NULL policy。Target Graph 与 Feature Graph 独立；Target V1 只可
直接消费 Dataset source，Indicator/Factor 不可消费 Target，Target 也不可消费任何 Calculation node。

Research Evaluation Plane 通过 exact Feature/Target series reference verified-load 两个 Calculation Result，要求完全相同 Dataset
Snapshot，并按 instrument + timestamp 做 deterministic pairwise alignment。IC 与 AVERAGE-tie Rank IC 使用 explicit Decimal(38)、
1e-12、ROUND_HALF_EVEN semantics，输出 value/sample_count/status。Statistics/Result Content/Statistics Result identities 分层，
immutable Parquet authority 使用 staged read-back、atomic publication、verified reuse、deterministic conflict 与 corruption fail-closed。
单一 `research-evaluation` lane 强制 line >=95%、branch >=90%，并进入 Layered Quality、release 与 Final-SHA canonical gates。

P7.7 不实现 Optimizer、Research Result/Artifact、Query/API/Web，也不激活 Research 或 Live Runtime。verification subject
`ea0bcf8628435b12125c6e67f481ad2c1be575ac` 已通过 Layered Quality `31865555598` 与独立 CodeQL `31865555591`；前者的
static、dependency audit、Semgrep、build、mandatory lanes、coverage、recovery 与 aggregate quality-gate 全部成功，因此本
increment 达到 `VERIFIED`。P7 仍保持 `IN_PROGRESS`，P7 Final Certification 仍为 `NOT COMPLETE`。

### P7.8 — Research Result Authority & Deterministic Research Output Closure（VERIFIED locally）

P7.8 建立最终 machine-readable Research output composition authority。versioned Plan 只包含 canonical、去重的 Statistics logical
fingerprints；Assembler 对每项调用 Statistics Result Store `load_verified()`，记录 exact Statistics/Statistics Result fingerprint pair，
并要求所有成员属于同一 exact Dataset Snapshot。Plan、Content、Research Result 三层 identity 分离，created_at、physical root 与
EXECUTED/REUSED invocation evidence 均不进入 semantic identity。

Immutable JSON Store 以 Plan fingerprint 为 durable key，使用 staging read-back、atomic publication、verified load、referential
integrity、idempotent REUSED、deterministic conflict 与 corruption fail-closed；它不复制 Statistics rows。`research-result` canonical
lane、Research/Trading firewall、consumer-aware Impact Resolver、scoped Task static verification 与三层 Gate Task Contract 已建立。
本 increment 的本地 Task Gate evidence 记录在 P7.8 report；P7 仍为 `IN_PROGRESS`，Final Certification 未完成。Research Artifact、
Query/API/Web、Optimizer、跨 Dataset composition 与 Research/Live Runtime activation 仍未实现。

### P7.9 — Research Artifact Materialization & Portable Read Boundary（VERIFIED locally）

P7.9 在 Research execution plane 与未来 consumer plane 之间建立首个稳定读取边界。Research Result 继续拥有 exact Statistics
composition，Statistics Result 继续拥有 rows semantic；Artifact 只复制 Research Result 精确选择的 rows，形成严格且不可变的
`artifact_manifest.json` 与 canonical `statistics.parquet` 派生视图。

Materializer 只从 verified Research Result 开始并 verified-load 每个 exact Statistics reference。Artifact logical content fingerprint
与 Parquet byte SHA 分层，created_at、物理路径和 compression 不进入 semantic identity。Store 使用 staged read-back 与 atomic directory
publication，equal re-entry 为 REUSED，deterministic conflict 与 existing corruption 均 fail closed。已发布 Artifact 的
`load_verified()` 不依赖 Dataset、Calculation、Statistics 或 Research Result Store，并独立重证 Statistics Plan/content/result、
Research Result plan/content/result 与 Artifact content linkage。`research-artifact` canonical lane、consumer-aware impact propagation
和 Research/Trading firewall 已建立。

本 increment 的本地 Task Gate evidence 记录在 P7.9 report；P7 仍为 `IN_PROGRESS`，Final Certification 未完成。Query Service、
API、Web、Optimizer、新 Statistics/Analytics、Artifact import/restore、跨 Dataset composition 与 Research/Live Runtime activation
仍未实现。

### P7.10 — Research Read Model & Read-only Query/API Boundary（VERIFIED locally）

P7.10 以 portable Research Artifact 为唯一 upstream read boundary。Core `onlyalpha.research.query` 只依赖最小
`OnlyResearchArtifactReader.load_verified()` Port，提供 versioned immutable Summary、exact Statistics Catalog 与 Series Page；
支持 UTC nanosecond `[from,to)`、strict `after` cursor、稳定分页，并保持 Decimal，不建立 Query fingerprint、Store、cache、latest
pointer 或任何 durable authority。

独立 workspace package `onlyalpha-api` 通过 FastAPI/Pydantic/Uvicorn 暴露三个 `/api/v1` GET endpoint。Decimal 无损编码为字符串，
事件时间保留 exact int64 nanosecond；invalid、missing、corrupt 分别映射稳定 machine code 与 400/404/500。API routes 不读取
Manifest/Parquet，也不访问 Dataset、Calculation、Statistics Result 或 Research Result Store。`research-query` canonical lane、
architecture firewall、consumer-aware impact propagation、workspace build/version graph 已建立。

本 increment 的本地 Task Gate evidence 记录在 P7.10 report；P7 仍为 `IN_PROGRESS`，Final Certification 未完成。Web UI、
Research Runtime lifecycle、Optimizer、新 Statistics/Analytics、Artifact catalog/search 与 Research/Live Runtime activation 仍未实现。

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
- Live 首次 Open 的 immutable/versioned/idempotent genesis import；
- Cash、Position/cost basis、Open Order、Pending Settlement 与 Broker/Account evidence verification；
- 历史成交和资金流水 evidence attachment，不伪造本地历史交易。

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

P9 还必须完成：

- authenticated Web/Application → Engine → single Runtime lifecycle control；
- 只属于 LIVE 的 first-class `MANUAL` workload、Allocation、Ledger、operator permission 与 audit；
- 人工订单复用 Market Rule/Risk/Reservation/Order/Broker/Durable Transaction 全链；
- 单 Live Runtime 与全部 Live Runtime liquidation；
- Engine parent liquidation request + Runtime-local durable child request；
- liquidation 后禁止重新开仓，直至授权人工显式复位；
- 对手一价 → 显式市价 → 显式斩仓价的 versioned execution policy 与 Broker/Market capability gate；
- partial/blocked/unknown/recovery 的真实结果语义，不以 submitted order 冒充 flat position。

## P10 — Multi-Market Product Expansion

P10 及后续市场阶段在共享 Domain、Market Product SPI、Calculation、Trading Kernel、Result 和 Recovery authority 上逐市场闭环：

```text
Market Domain/Reference
→ Market Product / DataSource / Broker
→ Research
→ Backtest
→ Sim
→ Live
→ Product Conformance
```

一个市场只有 Research、Backtest、Sim、Live 四种产品均形成正式入口、恢复/确定性与认证证据后，才能声明 OnlyAlpha 正式支持
该市场。阶段中允许发布精确命名、版本化、有限的 Research/Backtest/Sim/Live 产品，但不得扩大产品口径。

当前每个 Trading Runtime 只支持一个 Account、一个 Market Product 和一个 currency。港股、美股、Crypto 等市场先以独立 Runtime
接入同一 Engine；单 Runtime 多市场、多币种、FX valuation、跨市场资金共享与组合保证金需要未来独立 ADR 和产品阶段。

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
- 一个 Trading Runtime 只绑定一个 Account、Market Product 和 currency；
- 四类 Runtime 可以在一个 Engine 中同时存在且生命周期独立；
- 跨市场汇总只读，不成为交易 authority；
- 四种 Runtime 未闭环时，不声称正式支持整个市场；
- Web/Manual/Liquidation 不绕过 Engine、Risk、Broker 或 Durable Transaction；
- 不新增 `PAPER` 或 standalone `SHADOW` 产品依赖；
- 不以永久兼容层代替迁移和删除。
