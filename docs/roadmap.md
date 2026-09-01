# OnlyAlpha 建设地图

本文件只描述长期建设顺序、依赖和退出性质，不记录当前 milestone、increment、完成百分比、验证状态或下一任务授权。当前实现事实
必须由源码、测试和可执行行为判断。

## Runtime taxonomy

```text
RESEARCH  Historical + Vectorized/Batch + Research-oriented
BACKTEST  Historical + Event-driven + Virtual Broker + Full Trading Kernel
SIM       Realtime + Event-driven + Virtual Broker + Full Trading Kernel
LIVE      Realtime + Event-driven + Real Broker + Full Trading Kernel
```

Backtest、SIM、LIVE 共享一个 Trading Kernel 和同一交易语义。`PAPER` 与 standalone `SHADOW` 不属于正式 vocabulary。

## 永久建设依赖

```text
Canonical Domain / Identity / Authority
→ immutable Dataset and Strategy Revision evidence
→ universal Trading Kernel semantics
→ versioned Market Product / DataSource / Broker plugins
→ durable Runtime admission, execution, recovery and reconciliation
→ versioned Product API
→ Web / Agent consumers
```

每一层只能依赖其下层稳定 contract。Provider、venue、broker、regulation 或 protocol 的变化停留在 Plugin/Adapter/Gateway，不能
推动 Core 增加 provider branch。

## Spot / Futures Research 与 Backtest sequence

[ADR 0106](adr/0106-universal-spot-futures-research-backtest-sequencing.md) 决定以下顺序：

```text
Existing Spot foundation
→ universal Spot/Futures Research + Backtest semantic closure
→ Binance USD-M Research/Backtest conformance plugin
→ synthetic non-Binance Futures conformance
→ later Web / SIM / LIVE / QMT / CTP / Agent work
```

该 sequencing 不改变 Binance Spot 第一条 production/LIVE Golden Vertical，也不删除 QMT Market Data、QMT Broker、CTP 或 LIVE 的
长期目标。不得创建 Spot/Futures 两套 Engine 或 provider-specific Trading Kernel。

## Research / Strategy / Promotion

```text
immutable Dataset Snapshot
→ versioned Calculation / Factor / Feature
→ deterministic Research Run and Result
→ exact Evidence
→ Freeze immutable Strategy Revision
→ Backtest evidence
→ SIM evidence
→ explicit human-authorized LIVE promotion
```

同一 Strategy Revision 跨 Runtime 保持相同语义。Portfolio Profile、Execution Profile、Runtime Permission 和 capital binding 不进入
Strategy identity。Agent 可执行 Research、Backtest、SIM 和 evidence analysis，但永远不拥有 LIVE Authority。

## Product control plane

Product capabilities 按以下依赖进入版本化 API：

```text
canonical application authority
→ durable/idempotent Command or read-only Query
→ API DTO mapping
→ governed OpenAPI projection
→ Web / Agent consumer
```

Runtime specification 与 Runtime instance 必须分离。Product Runtime 不从 YAML/JSON/ENV 或 direct Python Engine construction admission。
Long-running work 在 durable admission 后脱离 HTTP request lifetime，由 Kernel/Worker/Runtime lifecycle authority 执行和恢复。

## Production execution sequence

每条真实市场纵切面依次证明：

```text
Market Product and reference authority
→ Historical and Realtime DataSource
→ durable market-data facts and immutable Dataset materialization
→ Broker/Gateway protocol and UNKNOWN-submit handling
→ Risk/Execution/Account/Position reconciliation
→ SIM continuity and recovery
→ LIVE fail-closed permission and human authorization
→ restart, fault, conformance and traceability closure
```

外部 venue 拥有 execution facts；OnlyAlpha 拥有 intent、policy、strategy identity、promotion、reconciliation 与本地 recoverable state。

## Infrastructure sequence

Infrastructure 建设围绕 node identity、versioned interfaces、compatibility、health、upgrade/rollback、persistence topology、observability、
failure domains 和 lifecycle。具体 Docker/Kubernetes/database 技术不成为产品 Identity 或 Trading Authority。跨节点通信使用明确协议，
Database 不是默认 integration API。

## Roadmap constraints

- Roadmap 不授权修改 Constitution、Architecture 或 public Contract。
- 当前能力、PASS、READY、COMPLETE、CERTIFIED 或 Next Task 不写入本文件。
- Research/Backtest 正式 evidence 必须绑定 immutable inputs。
- correctness proof 使用 deterministic barrier、event、fake clock 或 fault injection，不使用 sleep 证明正确性。
- Breaking public/persistence change 必须显式版本化、迁移或 fail closed。
- 当一个建设单元满足当前 Task Contract 和 Impact-Aware validation 后停止，不因 speculative risk 扩大范围。
