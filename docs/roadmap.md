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

## 当前产品事实（2026-08-10）

当前正式可用的完整产品纵切面是 Backtest 下的 `GENERIC_T0_CASH`、CASH、LIMIT、LONG/NETTING、BUY OPEN 与 SELL CLOSE，支持 Whole/Partial/Multi-Fill、Terminal Transaction、Memory/SQLite、Checkpoint/Restart/Forward Recovery、单/多 Cluster、Result/Analytics/Artifact/Report。

当前 legacy `PAPER` 路径已完成当前 Profile 下真实 MiniQMT 的 Historical/Open-Market Bootstrap、Historical-to-Live handoff、watermark、1m external bar、1m-to-3m aggregation、warmup/observation、Strategy intent、Shadow suppression、Reservation create/release 和 ordered shutdown。它仍是 read-only market observation + Shadow execution，只作为 Sim streaming migration baseline；reconnect、realtime gap recovery、streaming checkpoint/recovery、Real Broker submission/synchronization 与长期生产运行尚未闭环。

当前实现状态：

- `BACKTEST` 已实现，是 primary Runtime；
- `SIM` 尚无 enum、配置 spelling 或 Factory；
- `RESEARCH` 与 `LIVE` 是目标 Runtime，但当前 Factory 返回 unsupported；
- standalone `SHADOW` Factory 返回 unsupported，且不是目标 Runtime；
- `PAPER` 是待迁移并删除的旧源码路径。

所有内置 Market Profile 仍为 Experimental。`CN_A_SHARE_CASH` 已有版本化 Reference、Pre-Trade Rule 与 Production Fee Authority，其 Cash-Long economic shape 可由统一 Durable Kernel 识别。P4.3 的有限合同 `CN_A_SHARE_DURABLE_BACKTEST_V1` / `product_contract_version = "1"` 已完成 Product Conformance、恢复/确定性、静态/构建和同提交远端质量门禁，因此该有限产品为 **CERTIFIED**。这不升级完整 `CN_A_SHARE_CASH` Profile，也不表示所有 A 股、Sim 或 Live 产品可用。

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

此前建立且仍有效的内核包括统一 Market Runtime、版本化 A 股 Reference/Rule Decision、Prepared Transaction、Durable Commit、Ordered Projection、Projection Ready、完整 Long Close、多部分成交、Multi-Cluster Close Cost、Checkpoint 与因果 Forward Recovery。历史细节保存在 `docs/adr/` 与 `docs/reports/`。

## 当前阶段：P5

### Market Product Composition Authority Neutralization

P5.1 Core Market Product Contract & Composition Authority 已完成：Core 已提供市场中立的 provider/product identity、canonical config envelope、Reference/Policy ports、Factory、显式 fail-closed Registry、immutable resolved binding 与 effective composition identity，并以 ADR 0069 和静态门禁冻结依赖方向。

P5.2 Generic T0 Cash Plugin + Canonical Market IR 已完成：Canonical IR 已删除 matching、slippage 与 simulation liquidity，增加 minimal instrument economic terms；`onlyalpha-market-generic-t0-cash` 通过 `onlyalpha.market_products` discovery 提供 plugin-owned Reference Authority、pure Policy Compiler 与 Market Fee Pack，并通过 legacy economics conformance 和 tests-only T+2 third market extension proof。该完成状态不表示 Trading Runtime 已 cut over；legacy Generic/Profile/A-share production authority 仍保留到 P5.3 one-shot cutover。

P5 后续边界：

- P5.3：CN A-share Full Authority Migration + Trading Runtime cutover；
- P5.4：Identity hardening、失去职责的旧 API 删除与 certification。

P5 不提前实现 Sim、Research 或 Live，不增加市场专用 Engine、第二套经济 authority、compatibility adapter 或 implicit Generic fallback。P5.1 的 Registry 是唯一目标 Market Product factory lookup authority；当前 Profile Registry 只作为尚未 cutover 的历史生产实现保留。P5.3 必须同时准备 Generic 与 A-share binding 后一次切换，禁止按市场半切换。

## P6 — Sim Streaming Runtime Closure

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
