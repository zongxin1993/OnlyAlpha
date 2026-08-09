# OnlyAlpha 路线图

## 当前产品事实（2026-08-09）

OnlyAlpha 当前正式可用的完整产品纵切面是 Backtest 下的 `GENERIC_T0_CASH`、CASH、LIMIT、LONG/NETTING、BUY OPEN 与
SELL CLOSE，支持 Whole/Partial/Multi-Fill、Terminal Transaction、Memory/SQLite、Checkpoint/Restart/Forward Recovery、
单/多 Cluster、Result/Analytics/Artifact/Report。

Paper 已完成真实 MiniQMT 当前 Profile 的 Historical Bootstrap、Open-Market Bootstrap、Historical→Live Handoff、1m 外部
Bar 与 3m 内部聚合、Warmup/Observation、Shadow Execution Suppression、Reservation 生命周期和有序停止。Paper 仍是只读
市场观察与 Shadow Execution，不具备生产恢复、真实 Broker 提交或长期运行闭环。

`LIVE`、Standalone `SHADOW` 和 `RESEARCH` Runtime Factory 仍不可用。所有内置 Market Profile 仍为 Experimental。
`CN_A_SHARE_CASH` 已有版本化 Reference、Pre-Trade Rule 与 Production Fee Authority。其 Cash-Long 经济 shape 可由统一
Durable Kernel 识别，但完整产品纵切面与 Conformance 仍未完成，因此不得声明 A 股 Durable Product 已开放。

## 已完成阶段

- P0 — Test Baseline & Feedback Loop Closure：正式 test lanes、metrics、分层 marker 与质量门禁。
- P1 — Fee Authority Integrity Closure：Market Fee Pack 与 Broker Fee Contract 独立版本化 authority。
- P2 — Fee Reconciliation Semantic Closure：Evidence、Policy、Correction、Blocker 与 Recovery 语义。
- P2.1 — Reconciliation Composition Stabilization：统一 Policy Registry、Currency identity 与 Broker optional port。
- P3 — CN A-Share Production Fee Product：普通 CNY A 股印花税、过户费、Broker Contract Snapshot 与 Recovery/Reconciliation
  兼容性。
- P4-0 — Runtime Composition & Execution Hygiene Closure：canonical Runtime Environment、全局 mutable identity 冲突、
  单一 Component Registry ownership、staged/atomic Cluster composition、Execution 历史路径删除与 CI 工具链确定性。
- P4.1 — Durable Execution Capability Semantic Authority：Market identity 退出 permission authority；唯一 pure Resolver 按
  immutable economic shape、精确 Reservation shape 与 Account/Ledger parity 决定支持，并将版本化 proof 写入 committed fact。
- P4.2 — Durable Broker-Driven Order Lifecycle Closure：`ORDER_ACCEPTED`、`TRADE_FILL`、`ORDER_TERMINAL` 统一进入
  Prepared Transaction / Durable Commit / Ordered Projection / Forward Recovery；BUY OPEN 与 SELL CLOSE 的
  Accepted、Cancel、Reject、Expire 均显式声明 Order、Cash/Position、Allocation、Reservation、Ledger 与 Risk Authority，旧的
  direct lifecycle mutation 和 Reservation 协调旁路已删除。

此前完成且仍有效的内核包括：统一 Market Runtime、版本化 A 股 Reference/Rule Decision、Prepared Transaction、Durable
Commit、Ordered Projection、Projection Ready、完整 Long Close、多部分成交、Multi-Cluster Close Cost、Checkpoint 与因果
Forward Recovery。阶段细节保存在 `docs/adr/` 与 `docs/reports/`，不在本文件重复维护历史“当前状态”。

## 下一阶段

P4.3 — Residual Planner Semantic Cleanup 与 CN A-share 产品 Conformance 接入。

P4 只应处理 Market Instruction、Production Fee、Settlement、Account/Position Shape 与 Canonical Durable Trading Kernel 的
capability-driven 接入，包括 A 股 BUY OPEN、SELL CLOSE 与 T+1 产品 Conformance；不再重做 Runtime grouping、Account identity、
Registry ownership、Composition atomicity 或 legacy execution cleanup。

## 后续阶段

- Reference Provider neutralization 与更广 A 股规则覆盖；
- Paper reconnect、realtime gap recovery、streaming checkpoint/restart；
- Durable Broker outbound command、Broker account/order/trade/position synchronization；
- Live Runtime 与生产运维；
- Research 工作流、Web、更多市场产品；
- Multi-account、Multi-broker、Multi-data-source 产品；
- Futures/Margin durable product、Vectorized/Distributed backtest。

领域对象、Profile、Factory、Manager、测试 Fixture 或单组件测试的存在不代表对应产品已经可用。
