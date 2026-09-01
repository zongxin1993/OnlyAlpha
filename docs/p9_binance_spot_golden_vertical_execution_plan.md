# P9 Binance Spot Golden Vertical — Execution Plan

> Sequencing note: [ADR 0106](adr/0106-universal-spot-futures-research-backtest-sequencing.md) supersedes section 1's Binance Futures exclusion only for bounded universal Research/Backtest semantics and Binance USD-M Research/Backtest conformance, and supersedes section 5's post-Spot provider order. Binance Spot remains the first production/LIVE Golden Vertical; the original plan text is retained as historical context.

本文档只定义 P9 Binance Spot Golden Vertical 的未来建设顺序、依赖关系与长期实现边界，不记录工程完成状态、当前 Increment、验收结论或下一步授权状态。

ADR 0099 冻结 Binance Spot 为第一条 Golden Vertical。更广泛的生产交易架构见 `docs/p9_production_trading_vertical_architecture.md`；本文件只收敛 Binance Spot 的实现顺序。

---

## 1. Golden Vertical 目标

第一条完整纵切面必须同时证明：

```text
Trading Product Continuity
Research
→ Strategy Freeze
→ Backtest
→ SIM
→ LIVE
```

以及：

```text
Production Data Continuity
Provider
→ ingress durability / WAL
→ ClickHouse + PostgreSQL
→ verified Market Data Revision
→ immutable Dataset Snapshot
→ Research / Backtest / Runtime consumption
```

只有交易链或只有数据链都不能构成完整生产纵切面。

第一阶段范围：

```text
Provider: Binance
Market: Spot
Reference instruments: BTCUSDT, ETHUSDT
Execution integration environment: Binance Spot Testnet when real venue proof is required
```

BTCUSDT 用于主要端到端场景；ETHUSDT 用于证明实现不是 instrument-specific special case。

明确不扩展到 Binance Futures、QMT Broker/LIVE、CTP、多交易所路由、多账户 Portfolio Authority、自动 Mainnet promotion、Kafka/Redis/Kubernetes 等没有当前第一性需求的能力。

---

## 2. 永久实现约束

### 2.1 One semantic authority per fact

```text
Strategy semantics
→ immutable Strategy Revision

Research truth
→ immutable Research Result / Artifact

Historical research input
→ immutable Dataset Snapshot

Canonical market facts
→ verified Market Data Revision / Manifest

External execution facts
→ Binance venue

Local execution intent and recoverable runtime state
→ durable Trading Runtime evidence

Promotion authority
→ append-only Promotion Record

LIVE execution permission
→ durable LIVE safety state
```

数据库表、REST response、UI state、Provider DTO 不得静默成为第二 Authority。

### 2.2 Provider DTO terminates at adapter

```text
Binance payload
→ Binance adapter
→ provider-neutral canonical DTO/domain
→ Core
```

Binance enum、JSON、SDK type 不得为便利泄漏到稳定 Core Contract。

### 2.3 Runtime does not redefine Strategy

```text
one Strategy Revision fingerprint
→ Backtest
→ SIM
→ LIVE
```

Runtime 可以绑定不同 capital、Portfolio Profile、Execution Profile、Broker 与 fee configuration，但不得改变 decision semantics。

### 2.4 UNKNOWN is first-class

Submit timeout 或 response 丢失不是 rejection 证明：

```text
UNKNOWN
→ reconcile
→ establish venue fact
```

禁止 blind retry 生成新的 order identity。

### 2.5 LIVE fails closed on new risk

Market Data、Broker、Persistence、Reconciliation 或其他必要 Authority 无法证明 coherent 时，关闭 risk-increasing execution；进程继续处理 fill、cancel、account event、persistence、reconciliation 与 recovery。

### 2.6 Deterministic correctness proof

Crash/recovery、并发和 READY cutover 必须使用 deterministic barrier / event / fake clock / fault injection。`sleep()` 不能作为 correctness proof。

---

## 3. Production Data Foundation

数据库在本纵切面中属于正式产品路径，不是部署准备。

### ClickHouse

用于高吞吐 typed market facts，例如：

```text
Trade
Bar
Quote/L1
future order-book families when required
```

不得成为 Strategy、Promotion、Runtime lifecycle 或任意 metadata 的万能 Authority。

### PostgreSQL

用于 market-data control / provenance / operational metadata，例如：

```text
source/provider metadata
capture session
ingest segment
coverage manifest
market data revision
seal/recovery record
schema registry
dataset provenance/index
```

### Append-only WAL

Realtime callback 不同步依赖 ClickHouse 可用性：

```text
Provider
→ Ingress
→ canonical envelope
→ append-only WAL
→ bounded batch writer
→ ClickHouse
→ verification
→ PostgreSQL manifest/revision commit
```

### Immutable semantic store

继续承载 Dataset Snapshot、Strategy Revision、Research Evidence、Backtest Evidence 与 Promotion Evidence 等 immutable semantic artifacts。

历史市场事实采用 append/revise：

```text
R1 sealed
→ correction/backfill evidence
→ R2
→ new verified manifest
```

禁止把 sealed history 静默原地改写成新的“真相”。

---

## 4. 建设顺序

### P9.1 — Binance Spot Market Product & Reference Authority

目标：在任何交易 Runtime 消费之前，把 Binance Spot 的 execution-relevant market semantics 收敛成 deterministic Market Product。

主要能力：

- generic crypto 24×7 semantics；
- Binance Spot Reference adapter；
- `exchangeInfo` normalization；
- immutable Market Reference Snapshot 与 fingerprint；
- BTCUSDT/ETHUSDT data-driven instrument composition；
- price tick、quantity step、notional、order type、TIF、fee 等第一条纵切面需要的 venue rules；
- unknown execution-relevant rule 对 LIVE composition fail closed。

Provider DTO 不进入 Core；Market Product 通过 canonical contract 暴露语义。

### P9.2 — Binance Spot Historical & Realtime DataSource

目标：通过 provider-neutral OnlyAlpha DataSource contract 提供 Binance Spot historical/realtime facts，并具有 continuity/recovery semantics。

历史第一范围：

```text
Bar/Kline
Trade
```

历史读取采用 verified local coverage + exact missing-range backfill，不把“数据库有 rows”视为 completeness。

实时第一范围：

```text
closed Bar
Trade
provider-neutral realtime Market Reference
```

需要时再增加 canonical L1/Quote；不因 speculative breadth 阻塞第一条 1m-bar vertical。

READY 只能在对应 baseline、subscription、continuity/recovery proof 成立后产生。

### P9.3 — Durable Market Data Platform

目标：把 PostgreSQL + ClickHouse + WAL 连接成正式 durable market-data foundation。

第一纵切面只实现真实需要的 typed families，例如：

```text
raw/provider evidence envelope
market_trade
market_bar
market_quote when required
```

控制面建立最小充分的 source/capture/segment/coverage/revision/seal/recovery/schema/provenance entities，不重复已有 Authority。

WAL 必须 segmented、bounded、restart-recoverable；partial write、duplicate delivery、restart、replay、repair 与 revision commit 必须 deterministic/idempotent。

HOT/COLD storage 只影响物理生命周期，不创建两套业务查询语义。

Research/Backtest 消费路径保持：

```text
Verified Market Data Revision
+ exact request
→ Dataset Materializer
→ immutable Dataset Snapshot
```

### P9.4 — Binance Spot Real Broker

目标：实现 venue-authoritative、idempotent、可 reconciliation 的真实 Binance Spot Broker adapter。

第一范围：

```text
connect/authenticate
query balances
submit order
cancel order
query orders/trades needed for reconciliation
user/account/order execution stream
reconciliation lifecycle
```

Order identity 保持：

```text
OnlyAlpha OrderId
→ deterministic client-order identity
→ Binance clientOrderId
→ Binance venue orderId
```

HTTP command response 不是最终 execution fact。Broker CONNECTED/AUTHENTICATED 也不自动等于 READY；执行 readiness 依赖 reconciliation 与 authoritative execution stream continuity。

### P9.5 — LIVE Runtime Composition & Safety

目标：在共享 Trading Kernel 上组合 LIVE，不创建第二交易引擎。

启动 barrier 依次证明 durable runtime state、Strategy Revision、required fingerprints/profiles、Market Reference、Broker auth/reconciliation、Market Data recovery、strategy warmup 与 execution permission。

执行许可必须能表达至少以下语义或等价现有 Domain vocabulary：

```text
OBSERVE_ONLY
REDUCE_ONLY when provably safe
FULL_EXECUTION
HALTED
```

网络恢复不能自动静默恢复 FULL execution。

Observation 使用真实 market data、真实 account/Broker、真实 Strategy/Calculation/Risk path，但不产生 risk-increasing external submit；它不是 SIM，也不生成 simulated fills。

### P9.6 — Research → Backtest → SIM → LIVE Vertical

目标：使用同一个 immutable Strategy Revision 证明产品连续性。

Reference strategy 保持故意简单、deterministic，例如 BTCUSDT 1m closed bars 上 EMA20/EMA60 cross。此阶段不做 alpha research。

链路：

```text
Verified Market Data Revision
→ immutable Dataset Snapshot
→ Research
→ Candidate
→ explicit Freeze
→ immutable Strategy Revision
→ Backtest
→ explicit Promotion
→ SIM
→ explicit Promotion / LIVE eligibility
→ LIVE observation
→ explicit execution permission
→ Binance Spot Testnet
```

必须机械证明 Runtime 不修改 Strategy fingerprint。

### P9.7 — Fault / Recovery / Conformance Closure

目标：证明 Golden Vertical 在真实故障边界下仍保持 Authority、determinism、recoverability 与 fail-closed semantics。

覆盖按实际实现选择的关键故障，包括：

- provider disconnect/reconnect；
- market-data gap/backfill/rebuild；
- WAL partial/incomplete segment；
- ClickHouse/PostgreSQL transient failure；
- process restart；
- broker submit UNKNOWN；
- execution stream interruption；
- reconciliation divergence；
- crash-before/after durable boundary；
- duplicate callback/delivery；
- stale/invalid Market Reference；
- execution permission degradation/recovery。

Correctness proof 使用 deterministic barriers；真实 Testnet/数据库/Docker 环境只在其属于不可替代行为证明时使用。

---

## 5. 后续 Provider 顺序

第一条 Binance Spot vertical 的 Core contract 被证明后，再按实际需求扩展 Provider。长期优先顺序保持：

```text
Binance Spot complete vertical
→ QMT market data
→ Binance USD-M Futures
→ QMT Broker/LIVE
→ CTP
```

该顺序是建设依赖，不是完成状态表。任何新 Provider 必须复用已有 canonical Domain、Trading Kernel、Strategy Revision 与 Authority 模型。

---

## 6. 工程验收引用

本计划不定义每步 Task Gate、完成状态或质量报告。

所有任务统一遵守根目录 `AGENTS.md`：

```text
Task Contract
→ implementation
→ Impact-Aware validation
→ high-risk bounded Independent Review when required
→ Stop Condition
→ STOP
```

当前工程实际到达哪一能力必须从当前源码、当前测试和当前可执行行为重新判断，不能从本 Roadmap 推断。
