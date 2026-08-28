# P9 Binance Spot Golden Vertical — Execution Plan

> Status: **FROZEN CURRENT EXECUTION PLAN**
>
> Effective date: 2026-08-28
>
> Authority: this document is the current implementation plan for P9.1+ under ADR 0099.
>
> Relationship to earlier design: `docs/p9_production_trading_vertical_architecture.md` remains the broad P9 architecture reference. Where the older document requires Binance Spot and USDⓈ-M Futures to close in the same first implementation sequence, ADR 0099 and this document override that sequencing. All unchanged authority, determinism, Strategy Revision, Promotion, recovery, provider-neutrality and fail-closed rules remain binding.

---

## 1. Current starting point

The current repository control state has completed and verified P9.K.8 and authorizes P9.1 as the next engineering increment.

The next implementation objective is deliberately narrow:

> **Build the first complete production-shaped OnlyAlpha vertical on Binance Spot, using real durable databases and one immutable Strategy Revision from Research through Backtest, SIM and Binance Spot Testnet LIVE.**

This is not a provider breadth task. It is a vertical correctness task.

The first vertical MUST prove both:

```text
A. Trading Product Continuity
Research
→ Strategy Freeze
→ Backtest
→ SIM
→ LIVE

B. Production Data Continuity
Provider
→ WAL
→ ClickHouse/PostgreSQL
→ verified Market Data Revision
→ immutable Dataset Snapshot
→ Research/Backtest/Runtime consumption
```

If A is implemented without B, the vertical is incomplete.
If B is implemented without A, the vertical is incomplete.

---

# 2. Frozen first-release scope

## 2.1 Provider and market

```text
Provider: Binance
Market: Spot
Environment for certification: Binance Spot Testnet where venue execution is required
Reference symbols:
- BTCUSDT
- ETHUSDT
```

BTCUSDT is the primary end-to-end acceptance instrument. ETHUSDT exists to prove the implementation is not BTC-specific.

## 2.2 Runtime chain

The first complete chain is:

```text
Binance Spot Reference
        ↓
Historical + Realtime Market Data
        ↓
Durable Market Data Platform
        ↓
Immutable Dataset Snapshot
        ↓
Research
        ↓
Research Candidate
        ↓
Explicit Freeze
        ↓
Immutable Strategy Revision
        ↓
Backtest
        ↓
Human Promotion
        ↓
SIM
        ↓
Human Promotion
        ↓
LIVE_ELIGIBLE(TESTNET)
        ↓
LIVE Observation
        ↓
Explicit Execution Permission
        ↓
Binance Spot Testnet
        ↓
Order / Fill / Balance Facts
        ↓
Recovery / Reconciliation
        ↓
Certification
```

## 2.3 Explicit non-goals for the first Golden Vertical

Do not expand the active task scope to:

- Binance USDⓈ-M Futures provider implementation;
- COIN-M or delivery futures;
- QMT Market Bridge implementation;
- QMT Broker/LIVE;
- CTP;
- multi-exchange routing;
- multi-account portfolio authority;
- autonomous Mainnet promotion;
- complex strategy research;
- HFT/full-depth requirements beyond what is needed to prove the generic data model;
- Kafka/Redis/Kubernetes without a demonstrated first-principles requirement.

Provider-neutral Core abstractions may anticipate future markets when required for correctness, but speculative framework expansion is not a deliverable.

---

# 3. Permanent implementation rules

## 3.1 One semantic authority per fact

The implementation MUST preserve the existing OnlyAlpha authority model.

```text
Strategy semantics
→ Immutable Strategy Revision

Research truth
→ immutable Research Result / Artifact

Historical research input
→ Immutable Dataset Snapshot

Raw market evidence
→ provider raw record / durable market evidence

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

No convenience database table, REST response, UI state or provider DTO may silently become a second authority.

## 3.2 Provider DTOs terminate at the adapter

```text
Binance payload
→ Binance adapter
→ provider-neutral canonical DTO/domain
→ Core
```

Binance-specific enums/JSON/SDK types must not leak into stable Core contracts merely for convenience.

## 3.3 Runtime does not redefine Strategy

```text
one Strategy Revision fingerprint
→ Backtest
→ SIM
→ LIVE
```

Backtest/SIM/LIVE may bind different runtime profiles, capital, broker, fee or execution configurations. They may not change decision semantics without creating a new Strategy Revision and restarting Research lineage.

## 3.4 Unknown is a first-class execution state

A submit timeout or lost command response is not proof of rejection.

```text
UNKNOWN
→ reconcile
→ establish venue fact
```

Never:

```text
UNKNOWN
→ blind retry with a new order identity
```

## 3.5 Fail closed on new risk

When market data, broker facts, reconciliation, persistence or required external authority cannot be proven coherent, risk-increasing execution closes.

The process remains alive to process:

- fills;
- cancellations;
- account events;
- persistence;
- reconciliation;
- recovery.

Fail closed does not mean fail dead.

## 3.6 Correctness tests use deterministic barriers

Crash-boundary certification must use deterministic fault-injection barriers. `sleep()` cannot be the proof that a process reached a particular correctness boundary.

---

# 4. Production Data Foundation starts now

The database layer is no longer deployment preparation. It becomes part of the product path during this sequence.

## 4.1 Authority split

### ClickHouse — high-volume market fact store

Primary responsibility:

```text
Raw provider market evidence where appropriate
Canonical Trade
Canonical Bar
Canonical Quote/L1
Order Book families when implemented
Future market-data families
```

ClickHouse MUST NOT become:

- Strategy authority;
- Promotion authority;
- Runtime lifecycle authority;
- scheduler authority;
- arbitrary universal metadata store.

### PostgreSQL — market-data control/provenance and operational metadata

Primary responsibility:

```text
source/provider metadata
capture_session
ingest_segment
coverage_manifest
market_data_revision
seal_record
recovery_record
schema/version registry
dataset provenance/index
other bounded operational/catalog state
```

PostgreSQL answers how a verified fact set was formed and which revision is authoritative for a consumer. It does not replace immutable Dataset/Strategy semantic artifacts.

### Append-only WAL — ingress durability boundary

Realtime provider callbacks MUST NOT depend synchronously on ClickHouse availability.

Required shape:

```text
Provider
→ Ingress
→ normalize/envelope
→ Append-only WAL
→ bounded batch writer
→ ClickHouse
→ verification
→ PostgreSQL manifest/revision commit
```

Database outage must not immediately erase incoming market evidence.

### Immutable Semantic Store

Continue using immutable semantic artifacts for:

```text
Dataset Snapshot
Strategy Revision
Research Evidence
Backtest Evidence
Promotion Evidence
certification bundles where applicable
```

## 4.2 Market history is append/revise, not silently overwrite

Forbidden as the normal correction model:

```text
UPDATE sealed historical truth in place
DELETE old evidence and pretend it never existed
rewrite a sealed partition without revision evidence
```

Preferred model:

```text
R1 sealed
↓
new correction/backfill evidence
↓
R2
↓
new verified manifest
```

Old evidence remains auditable.

## 4.3 Database lifecycle is part of implementation Definition of Done

P9.3 and later certification MUST cover:

- schema versioning/migrations;
- idempotent writes;
- duplicate handling;
- backfill/repair segments;
- coverage verification;
- revision composition;
- seal semantics;
- WAL replay;
- process restart recovery;
- ClickHouse HOT/COLD lifecycle;
- PostgreSQL backup/restore;
- critical ClickHouse/manifest backup strategy;
- integrity checks;
- storage/ingest/recovery metrics;
- bounded resource behaviour.

The production database design is not complete merely because containers are running or tables can accept inserts.

---

# 5. Stage plan

# P9.1 — Binance Spot Market Product & Reference Authority

## Goal

Make Binance Spot a deterministic OnlyAlpha Market Product before any trading runtime consumes it.

## Required implementation

At minimum:

```text
P9.1.0 Generic Crypto 24×7 semantics
P9.1.1 Binance Spot Reference adapter
P9.1.2 exchangeInfo normalization
P9.1.3 immutable Market Reference Snapshot
P9.1.4 reference fingerprint
P9.1.5 Spot order/TIF capability mapping needed by the first vertical
P9.1.6 basic maker/taker fee contract needed by the first vertical
```

Configuration decides which symbols OnlyAlpha wants. Binance reference data decides the venue's current rules.

For BTCUSDT/ETHUSDT the product must deterministically resolve at least:

- canonical instrument identity;
- provider/venue/market identity;
- base/quote asset;
- status/tradability inputs;
- price tick;
- quantity step;
- min/max quantity where relevant;
- min notional/notional rules;
- supported order types;
- supported time-in-force values;
- normalized reference provenance;
- canonical reference fingerprint.

Unknown execution-relevant rules must fail closed for LIVE composition.

## Exit criteria

P9.1 is complete only when Spot reference composition is deterministic, provider DTOs do not leak into Core, and BTCUSDT/ETHUSDT are data-driven rather than hard-coded special cases.

---

# P9.2 — Binance Spot Historical & Realtime DataSource

## Goal

Provide real Binance Spot historical and realtime data through provider-neutral OnlyAlpha contracts with continuity and recovery semantics.

## Historical first scope

```text
BAR/Kline
TRADE
```

Historical retrieval is local-first, but "rows exist" is not completeness.

```text
request
→ inspect verified local coverage
→ complete? use local
→ missing? calculate exact missing range
→ Binance REST backfill
→ validate
→ persist
→ re-verify
→ return qualified data only
```

## Realtime first scope

Required for the platform boundary:

```text
closed Kline/Bar
Trade
Quote/bookTicker if used by the canonical L1 path
```

Depth support may be implemented as a typed family if already required by architecture, but it must not block the first 1m-bar Golden Vertical unless a concrete dependency exists.

Closed bars are formal immutable Bar facts. Provisional open Binance klines must not masquerade as closed canonical bars.

## Recovery requirements

At minimum:

- reconnect detection;
- duplicate handling;
- out-of-order detection;
- gap evidence;
- historical backfill where the data family supports event/range recovery;
- state rebuild where only state continuity can be proven;
- READY only after the applicable recovery contract is satisfied.

## Exit criteria

The same canonical market-data interface must support later durable persistence and runtime consumption without Binance-specific branching in consumers.

---

# P9.3 — Production Data Foundation / Durable Market Data Platform

## Goal

Turn deployed PostgreSQL + ClickHouse into the authoritative production market-data foundation and connect Binance Spot realtime/historical flows to it.

## Required data families for the first vertical

Implement only the families actually needed for the first production path, while keeping the envelope extensible:

```text
raw_market_event / raw evidence representation
market_trade
market_bar
market_quote where enabled
```

Do not build one giant universal JSON market-data table as the canonical data model.

Use a stable envelope plus typed fact families.

## Required control entities

PostgreSQL should introduce/complete the smallest useful set, conceptually:

```text
market_source
capture_session
ingest_segment
coverage_manifest
market_data_revision
seal_record
recovery_record
schema_registry
dataset provenance/index integration
```

Exact names may follow existing repository conventions. Do not duplicate an existing authority under a new name.

## WAL

WAL must be segmented, bounded and recoverable.

A useful lifecycle is conceptually:

```text
OPEN
→ SEALED
→ DATABASE_WRITTEN
→ VERIFIED
→ COMMITTED
```

Restart must find and idempotently recover incomplete segments.

## HOT/COLD lifecycle

Use the existing deployment intent:

```text
NVMe HOT
→ recent/high-use ClickHouse data
→ WAL / critical operational paths

HDD COLD
→ older sealed bulk market history
```

OnlyAlpha consumers query logical tables/data APIs, not separate "hot table" vs "cold table" business paths.

## Dataset materialization

Research/Backtest MUST continue to use:

```text
Verified Market Data Revision
+ exact symbol/range/data-kind request
→ Dataset Materializer
→ Immutable Dataset Snapshot
→ fingerprint
```

Direct mutable ClickHouse queries are not the Research/Backtest reproducibility contract.

## Maintenance and recovery acceptance

P9.3 is not complete until at least one real Binance Spot dataset can survive:

- provider restart;
- OnlyAlpha restart;
- WAL replay;
- duplicate delivery;
- partial database write/retry;
- missing-range repair;
- backup/restore exercise for critical metadata;
- HOT/COLD movement without changing logical query semantics.

---

# P9.4 — Binance Spot Real Broker

## Goal

Implement a real Binance Spot Broker adapter whose command path is idempotent and whose fact path remains venue-authoritative.

## Required first scope

At minimum:

```text
connect/authenticate
query balances
submit order
cancel order
query open orders
query orders/trades as required for reconciliation
user/account/order execution stream
reconciliation lifecycle
```

Support the Spot order semantics required by the first vertical. Do not let advanced order breadth delay the first certification unless the canonical Core contract already requires the semantic for correctness.

## Identity and uncertainty

Required chain:

```text
OnlyAlpha OrderId
→ deterministic client-order identity
→ Binance clientOrderId
→ Binance venue orderId
```

The same logical submission must not generate a new idempotency identity after an uncertain response.

Formal submit outcomes must include an uncertain/UNKNOWN path.

## Broker readiness

```text
CONNECTED
!= READY
AUTHENTICATED
!= READY
```

Required lifecycle includes reconciliation before execution readiness.

Loss of the authoritative user/execution stream must remove normal execution readiness and trigger recovery/reconciliation.

## Exit criteria

The Broker must prove venue/local convergence without treating HTTP command responses as final execution facts.

---

# P9.5 — LIVE Runtime Composition & Safety

## Goal

Compose LIVE from the existing shared Trading Kernel rather than creating a second trading engine.

```text
Strategy Revision
→ authoritative execution plan
→ shared Trading Kernel
→ SIM uses simulated Broker
→ LIVE uses Binance Spot Broker
```

## Startup barriers

LIVE startup must be an explicit authority sequence, conceptually:

```text
Acquire runtime lease
→ load/verify durable runtime state
→ load exact Strategy Revision
→ verify required fingerprints/profiles
→ load Market Reference
→ connect/authenticate Broker
→ reconcile Broker
→ recover market data continuity
→ strategy warmup from verified history
→ observation-ready
→ explicit execution permission
→ trading-ready
```

Any failed barrier prevents normal risk-increasing execution.

## Execution permission

Do not reduce LIVE safety to one boolean.

The model must be able to represent at least the semantics of:

```text
OBSERVE_ONLY
REDUCE_ONLY where provably safe/applicable
FULL_EXECUTION
HALTED
```

The exact existing domain vocabulary should be reused if already established.

Recovery from degraded/halted state must not silently reopen FULL execution merely because the network recovered.

## Observation mode

Observation uses:

- real Binance market data;
- real Broker/account connection;
- real Strategy/Calculation/Risk path;
- no external risk-increasing submit.

It is not SIM and must not invent simulated fills.

## Exit criteria

LIVE can start, remain fail-closed during degraded authority, reconcile, recover and explicitly return to an allowed execution state without changing Strategy semantics.

---

# P9.6 — Research → Backtest → SIM → LIVE Full Vertical

## Goal

Prove product continuity with one exact Strategy Revision.

## Reference acceptance strategy

Use a deliberately simple deterministic strategy. Recommended baseline:

```text
Instrument: BTCUSDT
Market: Binance Spot
Input: 1m closed bars
Calculations: EMA20, EMA60
Entry: EMA20 crosses above EMA60
Exit: EMA20 crosses below EMA60
```

The exact final test strategy may use another equally simple definition if existing Calculation contracts make it materially cleaner. Do not spend this phase searching for alpha.

## Required chain

```text
Verified Market Data Revision
→ Immutable Dataset Snapshot
→ Research
→ Research Evidence
→ Candidate
→ explicit Freeze
→ Strategy Revision S1
→ Backtest with S1
→ Human Promotion
→ SIM with S1
→ Human Promotion
→ LIVE_ELIGIBLE(TESTNET)
→ LIVE Observation with S1
→ explicit execution approval
→ Spot Testnet execution with S1
```

At every runtime boundary:

```text
StrategyRevisionFingerprint = identical
```

Profiles may differ and must be separately fingerprinted/evidenced.

## Promotion

First-generation promotion remains explicit human authority.

Automated gate assessment may recommend. It does not authorize promotion by itself.

## Exit criteria

The first vertical is complete only when the chain can be traversed from Research to a real Spot Testnet venue execution without semantic rewriting of the Strategy.

---

# P9.7 — Spot Fault / Recovery / Certification Closure

## Goal

Prove the first Golden Vertical remains unique, deterministic and safe under failure.

## Mandatory fault classes

### Market data

At minimum:

- WebSocket disconnect;
- gap detection;
- duplicate event;
- out-of-order event;
- REST backfill temporary failure;
- restart during ingestion;
- WAL replay/recovery.

### Broker

At minimum:

- user/execution stream disconnect;
- REST submit timeout;
- accepted-by-venue but response lost/uncertain;
- duplicate callback/event;
- partial fill where applicable;
- cancel race;
- local/venue reconciliation mismatch;
- restart with open/recent orders.

### Storage

At minimum deterministic crash boundaries around:

```text
WAL before seal
after seal / before DB write
after DB write / before manifest commit
runtime intent durable / before submit
submit sent / response unknown
fill observed / before local durable projection completes
```

## Correctness invariants

Certification must verify facts, not just "process restarted":

- no duplicate external order for one logical order intent;
- deterministic client-order identity;
- no normal FULL execution before reconciliation;
- market-data readiness only after continuity/recovery contract;
- no unexplained open order after final reconciliation;
- balances/positions/orders converge to venue facts;
- no uncommitted WAL remains after controlled final drain, except explicitly evidenced failure;
- immutable evidence links exact code/config/Strategy/Data revisions used by certification.

## Certification environment

The mandatory first external execution certification is Binance Spot Testnet.

Testnet completion MUST NOT automatically enable Binance Mainnet.

Mainnet requires its own explicit deployment intent/profile, human approval, startup reconciliation and execution permission.

---

# 6. Task execution discipline

## 6.1 Implement, then prove; do not loop on open-ended audit

Each P9.x task should start from a bounded contract and end with objective evidence.

Expected pattern:

```text
read frozen contract
→ inspect current repository truth
→ implement missing capability
→ run targeted tests
→ run architecture/quality gates required for the changed boundary
→ produce evidence/report
→ close task when acceptance is satisfied
```

Do not repeatedly reopen architecture design merely because another stylistic improvement is possible.

A task remains blocked only for a concrete violated invariant, missing acceptance condition, unresolved correctness defect or incompatible repository fact.

## 6.2 Do not weaken existing gates to make new work pass

If an existing architecture/determinism/authority guard fails because new provider/database code violates a boundary, fix the implementation.

Do not remove the guard or add broad exceptions unless an explicit accepted design change proves the old invariant is wrong.

## 6.3 Scope must remain narrow per increment

Examples:

```text
P9.1 failure
→ fix reference/product semantics
→ do not start P9.2 as compensation

P9.3 database issue
→ fix durability/authority
→ do not bypass storage with CSV just to demo P9.6

P9.4 Broker uncertainty issue
→ fix reconciliation/idempotency
→ do not mark LIVE complete because happy-path orders work
```

## 6.4 Project control state remains governed by project-state.toml

Current increment progression must continue through the repository's existing project-state authority workflow.

Do not create a second manually maintained current-status authority in this document.

This document defines the execution contract and sequencing. `project-state.toml` defines which increment is currently authorized/active/verified.

---

# 7. QMT boundary frozen for the later extension

QMT is intentionally outside the active Spot implementation, but its future integration boundary is already frozen enough to prevent architectural drift.

## 7.1 Runtime constraint

Future QMT provider code executes inside the QMT application-provided Python runtime:

```text
Python 3.6.8
```

Do not assume the deprecated MiniQMT/external-modern-Python integration model.

## 7.2 QMT bridge responsibilities

The QMT-side bridge should remain minimal:

```text
QMT API callbacks/commands
→ lightweight DTO normalization
→ bounded local queue/spool where required
→ versioned wire protocol
→ OnlyAlpha-side gateway
```

It should not own:

- Strategy;
- Research;
- Risk authority;
- Portfolio authority;
- Promotion;
- Dataset authority;
- PostgreSQL/ClickHouse business logic;
- modern OnlyAlpha Core imports.

## 7.3 Cross-runtime protocol rule

```text
QMT Python 3.6.8 objects
!= OnlyAlpha Core domain objects
```

Use an explicit, versioned wire protocol/DTO contract between the QMT process and OnlyAlpha server-side gateway.

The wire format should favor simplicity and Python 3.6 compatibility. The final transport choice must be justified from actual QMT runtime capabilities rather than framework preference.

---

# 8. Preferred sequencing after Spot Golden Vertical

After P9.7 Spot certification, the default strategic order is:

```text
1. QMT Market Data Bridge
   - A-share + ETF
   - historical + realtime
   - QMT internal Python 3.6.8
   - validates second-provider/process boundary

2. Binance USDⓈ-M Futures
   - long/short
   - one-way/hedge
   - cross/isolated
   - leverage
   - mark/index/funding
   - reduce-only
   - validates derivatives semantics

3. QMT Broker / LIVE
   - orders/trades/account/positions
   - A-share/ETF market rules
   - reconciliation

4. CTP
   - Linux-native futures provider
   - reuses the established provider-neutral platform
```

This order is a default execution decision, not an excuse to pre-build all future abstractions during the Spot task.

---

# 9. Golden Vertical final Definition of Done

The Binance Spot Golden Vertical is accepted only when all of the following are true:

## Strategy/Product

- one immutable Strategy Revision is created through the legal Research → Candidate → Freeze path;
- the exact Strategy fingerprint is used by Backtest, SIM and LIVE;
- no runtime-specific strategy implementation exists;
- promotion records are explicit and immutable/append-only according to existing authority rules.

## Market data

- BTCUSDT/ETHUSDT Spot reference rules are normalized and fingerprinted;
- historical/realtime data enter through provider-neutral contracts;
- gaps/duplicates/out-of-order conditions are evidenced;
- verified data can materialize immutable Dataset Snapshots.

## Persistence

- realtime ingress is protected by durable WAL semantics;
- ClickHouse is the high-volume market fact store;
- PostgreSQL controls coverage/revision/seal/provenance metadata;
- correction/backfill creates explicit evidence/revision rather than silent historical overwrite;
- backup/restore and restart recovery have been exercised;
- HOT/COLD lifecycle works without application-level dual-table semantics.

## Broker/LIVE

- Spot Testnet order/cancel/fill/balance paths work;
- deterministic client-order identity prevents blind duplicate submit;
- UNKNOWN is reconciled;
- Broker must reconcile before READY;
- LIVE has observation-only and explicit execution permission;
- loss of required authority fails closed on new risk;
- crash/restart converges to venue facts.

## Certification

- deterministic fault-injection tests cover the defined critical boundaries;
- final evidence identifies exact code, Strategy, Market Reference, Dataset/Market Data Revision and runtime profile identities;
- certification is for Binance Spot Testnet only unless a later explicit Mainnet deployment approval exists.

---

# 10. Immediate next action

The current repository authorizes P9.1.

Therefore the next implementation task should be generated and executed against:

> **P9.1 — Binance Spot Market Product & Reference Authority**

It must use this document, ADR 0099, the existing P9 architecture, current ADRs and current repository truth as its design basis.

It must not start Binance Futures, QMT or P9.2 implementation before the P9.1 acceptance contract is satisfied and the project-state authority explicitly advances the next increment.
