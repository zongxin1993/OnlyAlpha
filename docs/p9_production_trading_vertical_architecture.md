# P9 — Production Trading Vertical & Real Market Integration

> This document is the normative P9 design contract. P9 implementation work MUST conform to this document unless a later accepted ADR or an explicit update to this document changes the contract.
>
> Current implementation truth belongs to source, tests and executable behavior. This document defines the long-term production vertical and does not record milestone completion.

---

## 1. P9 mission

P9 answers one product question:

> Can one exact strategy be researched, frozen, backtested, promoted, run in realtime simulation, promoted again, and then executed safely against a real external venue while market data, execution facts, storage, recovery and operational permissions remain uniquely authoritative and reproducible?

The first reference market/provider is Binance. P9 MUST support both:

- Binance Spot;
- Binance USDⓈ-M Perpetual Futures.

The first reference instruments are intentionally small and explicit:

```text
Spot
- BTCUSDT
- ETHUSDT

USD-M Perpetual
- BTCUSDT
- ETHUSDT
```

The implementation MUST prove provider-neutral architecture so that later QMT, CTP, OKX or other adapters can reuse the same stable Core contracts instead of causing another Core rewrite.

P9 target vertical:

```text
Real Market / Provider
        ↓
Reference Data + Market Rules
        ↓
Historical + Realtime DataSource
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
LIVE_ELIGIBLE
        ↓
LIVE Observation
        ↓
Explicit Execution Permission
        ↓
Real Broker
        ↓
External Execution Facts
        ↓
Recovery / Reconciliation / Accounting
```

---

## 2. Permanent P9 architecture rules

These rules apply to every P9 sub-stage.

### 2.1 Provider != Domain

Provider-native DTOs terminate inside provider adapters.

```text
Binance DTO
QMT DTO
CTP DTO
    ↓
Provider Adapter
    ↓
OnlyAlpha Canonical Domain
```

No Binance enum, request object, JSON schema or SDK type may leak into stable Core contracts merely for implementation convenience.

### 2.2 Provider != internal semantic authority

The provider may be authoritative for external facts, but OnlyAlpha must bind those facts into explicit canonical evidence.

Examples:

- Binance `exchangeInfo` is the external current market-rule authority;
- a normalized immutable Market Reference Snapshot is the exact OnlyAlpha runtime binding;
- Binance is the external execution-fact authority;
- local durable execution evidence mirrors and reconciles those facts but cannot invent or overwrite them.

### 2.3 Runtime != Strategy

`BACKTEST`, `SIM`, and `LIVE` MUST NOT define different versions of the strategy.

```text
Strategy Revision
      ↓
Authoritative Resolver / Strategy Execution Plan
      ↓
Shared Trading Kernel
   ┌───────┬───────┬───────┐
   ↓       ↓       ↓
Backtest  SIM     LIVE
```

The same exact Strategy Revision under the same market-event and state inputs must produce the same decision semantics.

Execution reality may differ because of:

- fills;
- latency;
- partial fills;
- venue rejection;
- fees;
- slippage;
- network behaviour;
- broker/account state.

Decision semantics may not differ because of Runtime type.

### 2.4 Database != semantic truth by itself

A mutable database query is not a Research/Backtest semantic input.

```text
Mutable / repairable Market Data Store
        ↓
Verified sealed revision / manifest
        ↓
Dataset Materializer
        ↓
Immutable Dataset Snapshot
        ↓
Research / Backtest
```

PostgreSQL, ClickHouse and local files each have explicit responsibilities. No database becomes an accidental universal authority.

### 2.5 Web != Trading Authority

Web/API clients request operations and display projections. They do not become Strategy, Promotion, Broker or Execution-Permission authority.

### 2.6 No silent overwrite of durable facts

P9 prefers append-only evidence, immutable content and explicit superseding records.

Forbidden patterns include:

```text
fix history by UPDATE
replace sealed market data in place
mutate Strategy Revision
change an APPROVED PromotionRecord into REJECTED
pretend reconciliation never happened
```

New evidence creates new facts/revisions/records.

### 2.7 Unknown != failed

For real execution, an uncertain result is a first-class state.

```text
submit timeout
!=
order definitely rejected
```

`UNKNOWN` MUST be reconciled. It MUST NOT trigger blind resubmission.

### 2.8 Fail closed on new risk

Whenever required market data, broker facts, reconciliation or runtime authority cannot be proven current and coherent, new risk is disabled.

Fail closed means:

> execution permission closes for risk-increasing actions while the Runtime remains alive to process fills, cancellations, persistence and recovery.

It does NOT mean killing the process and losing observability.

### 2.9 Deterministic tests do not guess timing

Correctness tests MUST use deterministic barriers/fault injection for crash boundaries. `sleep()` may not be used to guess that execution has reached a required correctness state.

---

## 3. P9 scope and deliberate non-goals

P9 includes:

- first immutable Strategy Revision and Promotion authority;
- Binance Spot + USD-M Perpetual reference data;
- Binance historical/realtime DataSource;
- provider-neutral universal Market Data Platform;
- ClickHouse + PostgreSQL market-data persistence architecture;
- raw provider evidence + canonical market facts;
- append-only WAL/segment ingestion;
- Binance real Broker SPI implementation;
- Spot first, then Futures;
- real LIVE Runtime composition;
- observation-only LIVE;
- execution safety state and Kill Switch;
- full Research → Backtest → SIM → LIVE Testnet promotion vertical;
- Spot Testnet + Futures Testnet production closure and certification.

P9 deliberately does NOT require:

- QMT or CTP live trading implementation;
- support for every Binance symbol;
- Binance COIN-M Futures or delivery futures;
- multi-account portfolio authority;
- cross-market trading portfolio authority;
- Kubernetes;
- distributed scheduler;
- Kafka/Redis merely for architectural appearance;
- HFT-grade all-market full-depth trading;
- ML training platform;
- autonomous LLM authorization of LIVE trading;
- automatic Testnet → Mainnet promotion;
- exact modelling of every Binance VIP/BNB/referral/promotion fee rule in the first fee version.

P9 provider-neutral interfaces MUST nevertheless leave clean extension points for later providers and richer data families.

---

# 4. P9.0 — Strategy Revision & Promotion Foundation

## 4.1 Goal

Establish the immutable strategy product that every Trading Runtime consumes.

Research Candidate is not executable product authority.

Only this chain is legal:

```text
Research
   ↓
Candidate
   ↓
Explicit Freeze
   ↓
Immutable Strategy Revision
   ↓
Backtest / SIM / LIVE
```

A Candidate MUST NOT directly reach Backtest, SIM or LIVE.

## 4.2 Strategy Revision semantics

Strategy Revision freezes decision rules, not research results.

It MUST freeze every semantic input that determines signal generation, including at least:

```text
schema_version
Decision Graph
Calculation identities
Calculation semantic versions
Calculation implementation identities/fingerprints where required
Calculation parameters
Universe
Output bindings / roles
  - ELIGIBILITY
  - ENTRY
  - EXIT
signal semantics
```

It MUST NOT include runtime result/environment facts such as:

```text
Dataset Snapshot
Research time range
return
Sharpe
trade records
signal time series
equity curve
Statistics results
capital
Portfolio Profile
Broker
Fee Model
Execution Profile
account
```

Dataset remains objective immutable input evidence, not part of Strategy identity.

A Run/Evidence may bind:

```text
strategy_revision_fingerprint
dataset_id
dataset_fingerprint
time_range
profile_fingerprint
```

but Dataset identity does not mutate Strategy Revision identity.

## 4.3 Strategy responsibilities vs runtime-profile responsibilities

```text
Strategy Revision
→ what / when to trade

Portfolio Profile
→ how much

Execution Profile
→ how to execute

Broker
→ where to execute

Fee Model
→ execution cost semantics
```

Do not create a new Strategy Revision merely because capital, broker or execution profile changes.

## 4.4 Canonical fingerprint

Strategy Revision MUST have one authoritative canonical fingerprint.

```text
same canonical semantics
→ same fingerprint

any strategy semantic change
→ new fingerprint
→ new Strategy Revision
→ new Research lineage
```

No Runtime-specific fingerprint algorithm is allowed.

## 4.5 Persistence

Recommended P9 authority model:

```text
PostgreSQL Strategy Catalog
→ index / identity / provenance

Immutable Semantic Store
→ canonical Strategy Revision content

Optional private Git export/archive
→ review / backup / human history only
```

Git MUST NOT become LIVE runtime authority.

Core store semantics should be equivalent to:

```text
put_once()
load_verified()
exists()
```

No `update()` of immutable Strategy Revision content.

## 4.6 Promotion

Promotion is append-only evidence, not a mutable `strategy.status` field.

Target progression:

```text
RESEARCH
   ↓
BACKTEST
   ↓
SIM
   ↓
LIVE_ELIGIBLE
```

`LIVE_ELIGIBLE` means admission, not an active LIVE process.

Actual execution remains:

```text
LIVE_ELIGIBLE
   ↓
Deployment
   ↓
LIVE Runtime
```

PromotionRecord must bind exact Strategy Revision identity and exact supporting evidence.

## 4.7 P9.0 implementation tasks

At minimum:

```text
P9.0.1 Strategy Domain Model
P9.0.2 Unique Candidate Freeze Service
P9.0.3 Immutable Strategy Store
P9.0.4 Canonical Strategy Fingerprint
P9.0.5 Promotion Domain / Append-only Records
```

## 4.8 P9.0 acceptance

P9.0 is complete only when:

- Candidate cannot execute directly;
- Freeze is the unique Candidate → Strategy Revision authority;
- immutable Strategy Revision can be verified by fingerprint;
- changing any strategy semantic field yields a new Revision identity;
- Dataset/capital/Broker/Fee/Execution do not contaminate Strategy identity;
- Backtest/SIM/LIVE resolve the same revision through one authoritative semantic path;
- Promotion facts are append-only and independently verifiable.

---

# 5. P9.1 — Crypto Market Product & Binance Reference Authority

## 5.1 Scope

P9.1 supports both product families but implements them as distinct market products:

```text
P9.1A Binance Spot
- BTCUSDT
- ETHUSDT

P9.1B Binance USD-M Perpetual
- BTCUSDT
- ETHUSDT
```

The first Futures product is USDⓈ-M perpetual only. COIN-M and delivery futures are later extension work.

## 5.2 Configuration vs external authority

Configuration decides what instruments OnlyAlpha wants.

`exchangeInfo` decides current venue rules.

```text
Configured Universe
      ↓
BTCUSDT / ETHUSDT
      ↓
Binance exchangeInfo
      ↓
Binance Reference Adapter
      ↓
Normalized Canonical Market Reference Snapshot
      ↓
fingerprint
      ↓
Market Product binding
```

The Runtime MUST NOT call `exchangeInfo` from arbitrary business paths.

## 5.3 Immutable Market Reference Snapshot

`exchangeInfo` is current external authority. Runtime reproducibility requires one normalized exact binding.

The Snapshot should capture relevant rules such as:

```text
instrument identity
market / instrument type
base asset
quote asset
margin asset where applicable
status
contract type
price tick size
quantity step size
minimum / maximum quantity
minimum notional / notional rules
supported order capabilities
supported TIF
trigger protection / relevant conditional-order rules
current provider/reference provenance
effective/captured time
canonical fingerprint
```

Unknown execution-relevant provider rules MUST fail closed for LIVE composition.

For USD-M Futures, precision convenience fields must not be used as substitutes for actual filter rules when the venue exposes authoritative tick/step filters.

## 5.4 Historical rule correctness

Research/Backtest MUST NOT claim historical market-rule exactness by blindly applying today’s `exchangeInfo` to old market data.

P9 first version may have limited historical reference coverage, but the architecture MUST support historical Market Reference Snapshots later.

Evidence must state exactly which reference snapshot was used.

## 5.5 Generic Crypto 24×7 semantics

Create provider-neutral crypto 24×7 calendar/session semantics reusable by future crypto venues.

Do NOT create duplicated `BinanceCalendar`, `OKXCalendar`, etc. when the semantics are generic.

But:

```text
24×7 calendar OPEN
!=
always tradable
```

Effective tradability requires at least:

```text
Calendar permits
AND Instrument status permits
AND Reference rules permit
AND Broker operational state permits
```

## 5.6 Spot vs perpetual semantic separation

```text
Crypto Spot
- CASH
- CRYPTO_SPOT
- base/quote asset

Crypto Perpetual
- DERIVATIVE
- CRYPTO_PERPETUAL
- LINEAR for first USD-M product
- margin asset
- leverage
- mark/index price
- funding
- long/short
```

Share generic crypto concepts. Do not hide futures semantics behind Binance-specific `if futures:` branches scattered through Core.

## 5.7 Fees

P9 first fee contract supports a generic maker/taker commission model with explicit limitations.

The first version does not claim exact support for every:

- VIP tier transition;
- BNB discount;
- referral rebate;
- campaign promotion;
- special account schedule;
- maker rebate.

Funding is not commission and must remain a separate semantic path.

## 5.8 Order capability semantics

P9 includes support for:

```text
MARKET
LIMIT
STOP
TAKE_PROFIT
TRAILING
OCO
```

OCO MUST NOT become a single `OrderType`.

It is an order group / contingency semantic:

```text
Single Order
- MARKET
- LIMIT
- STOP...
- TAKE_PROFIT...
- TRAILING...

Order Group / Contingency
- OCO
- future OTO / BRACKET style groups
```

Conditional orders must be represented provider-neutrally through trigger condition, trigger price, trigger price source, execution style and position effect.

## 5.9 P9.1 tasks

```text
P9.1.0 Generic Crypto 24×7 Semantics
P9.1.1 Binance Spot Reference Authority
P9.1.2 Binance USD-M Perpetual Reference Authority
P9.1.3 Immutable Reference Snapshot / Fingerprint
P9.1.4 Order Capability Contract
P9.1.5 Basic Fee Contract
```

## 5.10 P9.1 acceptance

For the four reference products OnlyAlpha must deterministically answer:

- exact instrument/market type;
- calendar semantics;
- current tradability inputs;
- tick size;
- step size;
- min quantity/notional;
- supported order/TIF capabilities;
- OCO/order-group capability;
- contract/margin semantics;
- current normalized reference fingerprint.

No BTC/ETH-specific Core hardcoding is allowed.

---

# 6. P9.2 — Binance Historical & Realtime DataSource

## 6.1 Goal

P9.2 is not “connect a WebSocket”. It establishes real provider data with explicit continuity, gap detection, recovery and canonical market-data boundaries.

## 6.2 Historical scope

First version supports:

```text
BAR / Kline
TRADE
```

for BTCUSDT/ETHUSDT Spot and USD-M perpetual.

Historical retrieval is local-first:

```text
request
  ↓
inspect local Historical Store/Cache authority
  ↓
verified complete?
  ├─ YES → use local
  └─ NO
       ↓
     compute missing ranges
       ↓
     provider backfill
       ↓
     validate
       ↓
     persist
       ↓
     verify again
       ↓
     return only qualified data
```

“Rows exist” is not sufficient. Qualified local data means coverage/schema/temporal or sequence continuity/data version/content verification requirements are satisfied.

Binance adapter MUST depend on a historical store/cache port, not ClickHouse SQL directly.

## 6.3 Realtime scope

First version accepts:

```text
kline
trade
aggTrade
bookTicker
depth
```

USD-M also collects:

```text
mark price
index price
funding rate
```

## 6.4 Canonical mappings

Provider DTOs terminate inside the plugin.

Conceptually:

```text
kline        → OnlyBar
trade        → OnlyTradeTick
aggTrade     → explicit aggregate-trade capability/evidence
bookTicker   → OnlyQuoteTick / L1
Depth        → provider-neutral OrderBook Snapshot/Delta
mark/index   → Reference Price
funding      → Funding Rate
```

Core must gain explicit provider-neutral market-data payload types where needed. Do not bury Depth/Mark/Index/Funding semantics in generic metadata.

At minimum P9.2 should establish formal types equivalent to:

```text
BOOK
REFERENCE_PRICE
FUNDING_RATE
```

plus snapshot/delta/reference/funding payloads.

## 6.5 `trade` vs `aggTrade`

They are different provider streams and MUST NOT simultaneously feed one canonical Trade authority, otherwise volume may be double-counted.

P9 first default canonical trade feed should prefer raw `trade` because it loses the least information.

`aggTrade` remains a supported separately identified stream for recording/research/use cases, but cannot silently merge into the same canonical trade lineage.

## 6.6 External vs internal Bars

Binance Kline is accepted as external provider Kline evidence.

OnlyAlpha also retains its own aggregation capability:

```text
Binance Kline
→ EXTERNAL BAR

Trade
→ OnlyAlpha deterministic aggregator
→ INTERNAL BAR
```

They are different evidence lineages.

A disagreement creates explicit data-quality conflict evidence; neither silently overwrites the other.

For realtime Binance kline, only a confirmed closed bar becomes the official immutable external Bar event for downstream canonical bar semantics. Provisional updates may remain provider-local/raw recording state.

## 6.7 Generic recovery contract

Strong recovery is a provider-neutral requirement:

```text
NORMAL
  ↓
GAP_DETECTED / DEGRADED
  ↓
RECOVERING
  ↓
VERIFYING
  ↓
READY
```

A reconnected socket alone is NOT successful recovery.

Untrusted continuation must not be released to strategy decision flow until the stream-specific recovery contract is satisfied.

Two distinct guarantees must be recognized:

```text
Event continuity
State continuity
```

Not every stream can reconstruct every missed event.

## 6.8 Recovery matrix

### Kline

Goal: range continuity.

Use historical REST/backfill to fill missing closed bars and verify boundaries before READY.

### Trade / AggTrade

Goal: event continuity where provider IDs/history allow it.

Use provider event identities/sequence/time windows to detect and backfill gaps. Merge deterministically.

### BookTicker

Goal: current-state consistency.

A disconnected interval may contain unrecoverable intermediate best-bid/ask changes. Recorder MUST mark an explicit incomplete interval instead of fabricating events.

### Depth

Goal: verified order-book state consistency.

Use the venue snapshot + buffered delta/update-ID algorithm. On sequence discontinuity the local book is invalid, must be discarded and rebuilt from a new verified snapshot/delta chain.

### Mark / Index

Goal: current-state consistency plus available historical repair.

### Funding

Goal: funding-event continuity/history.

## 6.9 Funding boundary

`FundingRate` is market/reference data.

It is not commission and not account cashflow by itself.

Later accounting may create `FundingCashflow` from the rate plus a held position across the funding boundary.

## 6.10 Binance provider package

One package, explicit internal product boundaries:

```text
plugs/onlyalpha-plugin-binance/
  common/
    auth / transport / websocket / clock / rate_limit / errors / normalization
  spot/
    reference / historical / streaming / broker
  usdm/
    reference / historical / streaming / broker / account_config
  data_source/
```

Shared infrastructure is shared. Spot and USD-M codec/subscription/account semantics stay explicit.

## 6.11 P9.2 tasks

```text
P9.2.0 Market Data Contract Extension
P9.2.1 Binance Transport Layer
P9.2.2 Historical BAR + TRADE
P9.2.3 Realtime Spot
P9.2.4 Realtime USD-M
P9.2.5 Recovery & Continuity
P9.2.6 External/Internal Bar Verification
```

## 6.12 P9.2 acceptance

Normal operation must produce canonical Spot/USD-M data for the required feeds.

Forced disconnect/gap scenarios must prove:

```text
detect
→ distrust
→ DEGRADED
→ reconnect/resubscribe
→ stream-specific recovery
→ verify
→ READY
→ resume trusted strategy delivery
```

---

# 7. P9.3 — Universal Market Data Platform

## 7.1 Goal

P9.3 builds a provider-neutral long-term market-data infrastructure, not a Binance database.

Future Binance/QMT/CTP adapters must all write through the same stable market-data contracts.

## 7.2 Storage engines

Frozen first architecture:

```text
ClickHouse
→ high-volume market facts / query plane

PostgreSQL
→ metadata / control / provenance / manifests / coverage / revisions
```

ClickHouse does NOT become Runtime control authority.

PostgreSQL does NOT store billions of ticks/depth rows.

## 7.3 Permanent retention policy

P9 design assumes long-term retention of all supported data families in the first production platform, including:

```text
Trade
Kline / Bar
BookTicker / Quote
Depth Snapshot / Delta
Mark Price
Index Price
Funding Rate
Instrument / Market Status
```

Raw provider evidence is also retained long-term.

Retention may later gain tiering/compression/cold-storage mechanics without changing authority semantics.

## 7.4 Raw Provider Evidence + Canonical Market Facts

Both are first-class durable evidence.

```text
Layer 1 — RAW PROVIDER EVIDENCE
“What did the provider actually send?”

Layer 2 — CANONICAL MARKET FACT
“How did OnlyAlpha normalize the provider evidence?”

Layer 3 — IMMUTABLE DATASET SNAPSHOT
“What exact data did this Research/Backtest use?”
```

Raw evidence allows a later normalizer version to rebuild canonical history without pretending old normalized facts never existed.

Raw evidence must preserve actual provider payload/evidence, not Python `repr()`/pickle of SDK objects.

A raw envelope should preserve enough provenance to verify:

```text
source/provider
venue/market/stream
provider event type/id/sequence
provider/event time
receive time
ingest time
payload codec/schema
raw payload
raw hash
capture/session identity
```

## 7.5 Stable Envelope + Typed Facts

Do NOT build one universal JSON market table whose meaning is recovered through `if type == ...`.

Use:

```text
Stable Market Event Envelope
+
Typed Fact families
```

The stable envelope includes cross-cutting identity/provenance/time/quality/revision fields.

Typed facts remain strongly modelled.

The database/API design MUST account for common future market-data families even when P9 does not implement all of them:

```text
Trade
- trade
- aggregate trade
- block/negotiated trade

Quote / L1

Order Book
- Snapshot
- Delta
- L2
- future L3/order-by-order

Bar
- time
- future tick/volume/value bars

Reference Price
- mark
- index
- settlement
- previous settlement
- indicative
- future NAV/IOPV where applicable

Derivatives Data
- funding
- future open interest
- future liquidation
- future volatility/Greeks

Market Statistics

Order Flow
- future add/modify/cancel/transaction

Market State
- trading status
- auction/session/halt/maintenance
```

P9 implements only the required first families. Future additions should primarily add a typed payload/table rather than rewrite DataSource, Historical API or Dataset architecture.

## 7.6 Append-only WAL/Segment write path

Realtime provider callbacks MUST NOT synchronously depend on ClickHouse inserts.

Required shape:

```text
Provider
  ↓
Ingress
  ↓
Raw + Canonical event
  ↓
Append-only durable WAL / spool
  ↓
bounded queue
  ↓
batch writer
  ↓
ClickHouse
  ↓
verification
  ↓
PostgreSQL Manifest/Coverage commit
```

Database outage and market-stream outage are different failure domains.

A ClickHouse outage must not silently corrupt trading or force provider callback blocking.

WAL/spool has explicit bounded capacity and degraded/error behaviour. Silent unrecorded dropping is forbidden.

## 7.7 Segment protocol

Use finite immutable segments, not one endless log file.

A segment should have evidence equivalent to:

```text
segment_id
source / market / stream
schema_version
first/last event
first/last provider sequence where meaningful
record_count
content_hash
```

Lifecycle may be modelled as:

```text
OPEN
→ SEALED
→ STORE_WRITTEN
→ VERIFIED
→ COMMITTED
```

Crash/restart reprocesses unfinished segments idempotently.

## 7.8 No in-place historical overwrite

Historical repair never mutates sealed facts in place.

Example:

```text
Revision R1
Segments A B C D

C later proven incomplete/wrong
      ↓
new correction/repair segment C2
      ↓
Revision R2
Segments A B C2 D
```

R1 remains reproducible.

Backfill is append, not rewrite.

Provider corrections/normalizer changes create new evidence/revision, not edited past truth.

## 7.9 Seal and Manifest Revision

A time/data partition may progress conceptually through:

```text
OPEN
→ INGESTING
→ RECONCILING
→ COMPLETE
→ SEALED
```

`SEALED` means the specific revision passed its declared coverage/schema/sequence/hash/quality checks.

A sealed revision never becomes open again. New evidence creates a new revision.

PostgreSQL owns the catalog/manifest facts that select exact segment sets.

Do not depend on non-deterministic background merge timing in ClickHouse as semantic authority.

## 7.10 ClickHouse table family

Prefer typed tables such as:

```text
market_raw_event
market_trade
market_bar
market_quote
market_book_snapshot
market_book_delta
market_reference_price
market_funding_rate
market_status

future:
market_open_interest
market_liquidation
...
```

Tables share stable identity/time/source/provenance/revision/segment fields but remain optimized for their data shape.

## 7.11 PostgreSQL catalog family

Keep the catalog small and control-oriented, conceptually including:

```text
market_source
capture_session
ingest_segment
market_data_revision
coverage_manifest
seal_record
schema_registry
recovery_event
```

Exact schema is designed Domain First during implementation.

## 7.12 Historical data convergence

Realtime ingest and REST/historical backfill MUST converge into the same canonical storage semantics.

Provenance remains explicit, e.g.:

```text
REALTIME_STREAM
REST_BACKFILL
REPAIR
```

Overlapping realtime/backfill must deduplicate deterministically without losing provenance.

## 7.13 Dataset materialization remains immutable

Research/Backtest never consume the mutable recorder tail as semantic truth.

```text
sealed Market Data Revision / Manifest
    + exact instruments/time/data kinds
    ↓
Dataset Materializer
    ↓
Immutable Dataset Snapshot
    ↓
fingerprint
    ↓
Research / Backtest
```

The existing Dataset Snapshot authority remains the formal research input boundary.

## 7.14 P9.3 tasks

```text
P9.3.0 Universal Market Data Storage Contract
P9.3.1 Raw Provider Evidence Model
P9.3.2 Canonical Typed Market Fact Model
P9.3.3 Append-only WAL / Segment Protocol
P9.3.4 ClickHouse Durable Fact Storage
P9.3.5 PostgreSQL Catalog / Manifest / Coverage
P9.3.6 Revision / Correction / Backfill / Seal Protocol
P9.3.7 Historical Query & Coverage Service
P9.3.8 Immutable Dataset Materialization Integration
P9.3.9 Crash / Replay / Corruption / Gap Certification
```

## 7.15 P9.3 acceptance

Must prove at minimum:

- recording does not synchronously block provider callbacks on DB writes;
- kill after WAL append/before DB commit recovers;
- kill after DB write/before local checkpoint/manifest safely deduplicates;
- DB outage produces explicit degraded recording state and later drains correctly;
- realtime + backfill overlap does not duplicate semantic events;
- gap repair produces new append-only evidence/revision;
- sealed manifest fingerprint is stable and verified;
- repeated Dataset materialization from the same sealed revision produces the same Dataset fingerprint;
- Research never consumes mutable `latest` recorder state as formal input.

Permanent rule:

> No overwrite, no silent correction, no mutable historical truth.

---

# 8. P9.4 — Binance Real Broker

## 8.1 Sequence

Implement the Broker vertical in this order:

```text
P9.4A Spot
then
P9.4B USD-M Futures
```

Do not interleave two half-complete brokers.

## 8.2 Environment model

Testnet and Mainnet are environments, not separate broker implementations.

```text
BinanceBroker
  ├─ environment: TESTNET / MAINNET
  └─ product: SPOT / USDM
```

Environment may change endpoint/credentials/execution permission identity. It may not create different order state/reconciliation/domain semantics.

P9 certification runs on Testnet. Mainnet remains explicit human deployment.

## 8.3 Order contract completion

P9.4 must complete provider-neutral broker/order semantics required by P9.1:

```text
MARKET
LIMIT
STOP
TAKE_PROFIT
TRAILING
OCO
```

Advanced fields must become explicit domain semantics, not `metadata["binance_x"]` hacks.

Examples:

```text
trigger price
trigger price source
trailing offset/rate
position effect
position side
reduce-only
close-position
```

OCO remains an Order Group/Contingency and should have group submission/cancellation semantics rather than masquerading as one order type.

## 8.4 Broker capability admission

Runtime must know before execution whether a Broker supports the exact requested capabilities.

Spot capability set grows beyond simple Market/Limit to include conditional/group semantics.

Futures capability includes at least:

```text
short/long semantics
position side
reduce-only
position mode
margin mode
leverage
```

Unsupported required capability fails before execution.

## 8.5 Deterministic client order identity

There must be deterministic mapping:

```text
OnlyOrderId
    ↓
OnlyClientOrderId
    ↓
Binance clientOrderId
```

Same OnlyOrderId must map to the same external client correlation identity.

The exchange-generated venue order identity is separate:

```text
OnlyOrderId
ClientOrderId
VenueOrderId
```

All are persisted; none substitutes for another.

## 8.6 Real order state includes UNKNOWN

Submission outcome is not binary.

```text
CREATED
  ↓
SUBMITTING
  ├─ definitive reject → REJECTED
  ├─ definitive acknowledgement → ACKED
  └─ uncertain outcome → UNKNOWN
```

`UNKNOWN` is a real execution state.

The only legal resolution is authoritative query/User Stream/reconciliation.

Forbidden:

```text
timeout
→ generate new clientOrderId
→ retry blindly
```

## 8.7 Command response != execution fact

```text
Command side
OnlyAlpha Intent → Venue request

Fact side
Venue order/trade/account event → Canonical Broker Fact
```

HTTP/command success does not by itself mean filled.

The external venue is authoritative for:

- accepted/rejected status;
- venue order status;
- fill quantity/price;
- trade identity;
- venue commission facts;
- external balance/position facts.

OnlyAlpha is authoritative for local Strategy/Risk/Order Intent and local durable orchestration evidence.

## 8.8 Reconciliation is a protocol

Reconciliation is not an optional helper.

A real Broker becomes READY only after authoritative convergence.

Required startup/recovery shape:

```text
connect
authenticate
execution permission closed
query account
query balances
query positions
query open orders
query relevant historical orders/trades
compare local durable evidence
resolve UNKNOWN/missing external facts
persist reconciliation evidence
verify convergence
READY
```

`CONNECTED != READY`.

`AUTHENTICATED != READY`.

User/account stream loss revokes READY and new-risk permission until reconnection + reconciliation succeeds.

## 8.9 Reconciliation never rewrites external facts

Example:

```text
Local projection: ACKED
Venue after restart: FILLED + Trade T100
```

Do not hide the discrepancy with an in-place status repair.

Create reconciliation observation/evidence, ingest missing canonical venue facts, update derived local projection from durable facts.

## 8.10 Spot first version

Spot must provide complete operational facts required for real execution:

```text
connection/authentication
balances
orders/open orders/order history
trades
fee evidence
user/account stream
order updates
trade/fill updates
balance/account updates
recovery/reconciliation
```

## 8.11 USD-M first version

P9 USD-M Broker supports all of:

```text
One-way mode
Hedge mode
Cross margin
Isolated margin
Leverage configuration
Long/Short
Position side
Reduce-only
Close-position
Conditional orders
Recovery/Reconciliation
```

Position mode, margin mode and leverage are account/instrument configuration facts, not random fields on every order.

Use an explicit configuration port/service, conceptually:

```text
query/set position mode
query/set margin mode
query/set leverage
```

Account configuration changes have the same external-fact discipline as orders:

```text
local configuration intent
→ venue request
→ venue confirmation
→ canonical configuration fact
```

No local assumption of success.

P9 default safety policy should verify venue configuration and fail closed rather than silently changing critical account settings during ordinary LIVE startup. Any configuration mutation is explicit operator/admin intent.

## 8.12 Secrets

API keys/secrets remain operational secrets.

They MUST NOT enter:

```text
Strategy Revision
Dataset
Research Artifact
Market Data Snapshot
canonical fingerprints
Git history
normal logs
```

## 8.13 P9.4 tasks

```text
P9.4.0 Real Broker Contract Completion
P9.4.1 Binance Broker Common Infrastructure
P9.4.2 Spot Account & User Stream
P9.4.3 Spot Order Execution
P9.4.4 Spot Recovery & Reconciliation
P9.4.5 Spot Testnet Certification
P9.4.6 USD-M Account Configuration
P9.4.7 USD-M Execution
P9.4.8 USD-M Recovery & Reconciliation
P9.4.9 USD-M Testnet Certification
```

## 8.14 P9.4 acceptance

Certification must cover normal and dangerous paths, including:

```text
MARKET/LIMIT
partial fill
cancel
STOP/TAKE_PROFIT/TRAILING/OCO
invalid quantity/tick/notional
insufficient balance
submit timeout / UNKNOWN
response lost after venue acceptance
User Stream disconnect
process crash around submit/ack/fill
duplicate submit attempt
duplicate broker event
REST/User Stream temporary disagreement
restart with open order
restart after fill not yet consumed locally
```

Core invariant:

> Intent is local; execution fact is external. Unknown execution state is reconciled, never blindly retried.

---

# 9. P9.5 — LIVE Runtime & Safety

## 9.1 Core rule

LIVE is not a new trading engine.

The current shared Trading/Streaming Kernel remains the trading semantic authority.

```text
Strategy Revision
     ↓
Shared Trading Kernel
     ├─ Backtest + historical DataSource + virtual Broker
     ├─ SIM + realtime DataSource + simulated Broker
     └─ LIVE + realtime DataSource + real Broker
```

Do not create `SimTradingKernel` and `LiveTradingKernel` with diverging strategy/economic semantics.

## 9.2 LIVE startup is an authority-barrier protocol

Required sequence:

```text
Acquire Runtime Lease
        ↓
Load + verify durable Runtime state
        ↓
Load exact Strategy Revision
        ↓
Verify Strategy / Market Product / relevant Profile fingerprints
        ↓
Connect + authenticate Broker
        ↓
Broker reconciliation
        ↓
Connect Market Data
        ↓
Market Data recovery / continuity verification
        ↓
Deterministic Strategy warmup
        ↓
Verify all required authorities
        ↓
OBSERVATION ready
        ↓
Explicit Execution Permission Gate
        ↓
FULL LIVE execution when authorized
```

No partial startup may become FULL execution-ready.

## 9.3 Readiness is derived from explicit facts

Avoid one opaque boolean.

Conceptually track facts such as:

```text
PersistenceReady
StrategyReady
MarketReferenceReady
MarketDataReady
BrokerReady
BrokerReconciled
RuntimeRecovered
StrategyWarm
```

Trading readiness is a deterministic conjunction of required facts plus execution permission.

## 9.4 Observation-only LIVE

P9 requires a formal LIVE observation mode.

Observation mode uses:

```text
real market data
real broker connection
real account/balances/positions
real order/trade stream
real Strategy Revision
real Calculation / Decision / Risk path
```

but sends no external order.

When the strategy would submit, the Runtime records explicit `would-submit`/denied-by-permission evidence.

Observation mode MUST NOT replace the real Broker with a simulated Broker. That would be SIM, not LIVE observation.

## 9.5 Execution permission is not bool

P9 requires explicit safety permissions equivalent to:

```text
OBSERVATION_ONLY
REDUCE_ONLY
FULL_EXECUTION
HALTED
```

Semantics:

```text
OBSERVATION_ONLY
→ no external strategy order submission

REDUCE_ONLY
→ only provably non-risk-increasing actions

FULL_EXECUTION
→ normal admitted strategy execution

HALTED
→ strategy automatic external execution disabled
```

Runtime type remains distinct from permission.

## 9.6 Degraded state policy

Market-data gap, broker degradation or incomplete reconciliation uniformly disables new risk.

The Runtime remains alive to continue:

- broker event consumption;
- fill/accounting updates;
- persistence;
- cancellation/reconciliation;
- recovery.

Risk-reducing actions are allowed only when the system can prove the action does not increase exposure relative to reconciled authoritative position state.

Do not infer “reduce risk” from BUY/SELL direction alone.

If position truth itself is uncertain, permission may collapse to cancel-only behaviour until reconciliation restores certainty.

## 9.7 Kill Switch

P9 requires an independent durable Kill Switch.

Trigger semantics begin with:

```text
BLOCK NEW RISK
→ cancel pending risk-increasing orders where safe/possible
→ assess/reconcile
→ optional controlled flatten policy
```

Kill Switch MUST NOT always mean “market sell everything”. Flattening is a separate explicit safety policy because a venue/data/liquidity fault may make immediate indiscriminate liquidation unsafe.

Kill Switch is latched.

Recovery does not automatically restore FULL execution.

Required path:

```text
TRIGGERED / HALTED
→ operator acknowledgement
→ reconciliation
→ verification
→ OBSERVATION
→ explicit execution re-enable
```

## 9.8 Different degraded authorities remain distinguishable

`MarketData DEGRADED` and `Broker DEGRADED` both close new risk but have different remaining trusted facts and legal operations.

Do not collapse all failures into one undifferentiated `system_degraded` flag.

## 9.9 Operational evidence

LIVE startup/recovery/safety actions are durable immutable operational evidence, not transient logs.

Examples:

```text
LIVE_RUNTIME_STARTED
BROKER_RECONCILIATION_STARTED / COMPLETED
MARKET_DATA_RECOVERY_STARTED / COMPLETED
EXECUTION_PERMISSION_CHANGED
RUNTIME_DEGRADED
KILL_SWITCH_TRIGGERED
REDUCE_ONLY_ENTERED
RECOVERY_COMPLETED
```

Use the existing Runtime persistence/durable transaction authority rather than creating a second competing LIVE audit truth.

Permission state itself must survive restart. A HALTED process cannot reboot into FULL execution by default.

## 9.10 Deterministic warmup

Strategy calculations requiring history must warm from verified Market Data Platform / Historical Store data and then bridge exactly into realtime continuity.

```text
verified history
→ exact warmup
→ verify historical-last ↔ realtime-first continuity
→ realtime calculation continuation
```

Warmup completion alone does not authorize trading.

## 9.11 P9.5 tasks

```text
P9.5.0 LIVE Runtime Composition
P9.5.1 Execution Permission Model
P9.5.2 Startup & Recovery Barrier
P9.5.3 Observation-only LIVE
P9.5.4 Degraded Safety Policy
P9.5.5 Risk-reducing Execution Contract
P9.5.6 Kill Switch
P9.5.7 Immutable Operational Evidence & Certification
```

## 9.12 P9.5 acceptance

P9.5 must prove both:

```text
correct state → execution can proceed
incorrect/uncertain state → unsafe execution cannot proceed
```

A successful Testnet order alone is insufficient.

---

# 10. P9.6 — Full Promotion Vertical

## 10.1 Goal

P9.6 proves that Research → Backtest → SIM → LIVE is one product lineage, not four unrelated workflows.

## 10.2 All P9 promotions are human-authorized

First P9 version requires explicit human approval at every stage transition.

```text
Research → Backtest       HUMAN APPROVAL
Backtest → SIM            HUMAN APPROVAL
SIM → LIVE_ELIGIBLE       HUMAN APPROVAL
```

Automated Gate Assessment may calculate metrics and produce PASS/FAIL recommendations, but:

```text
Gate Assessment PASS
!=
Promotion APPROVED
```

Future Agent/automation may recommend. It does not become Promotion Authority in P9.

## 10.3 Strategy Revision continuity is absolute

Across one promotion lineage:

```text
Research
Backtest
SIM
LIVE
```

must all bind the exact same Strategy Revision fingerprint.

Any change to:

- Decision Graph;
- Calculation identity/version/implementation;
- Calculation parameters;
- Universe;
- output binding/role;
- signal semantics;

creates a new Strategy Revision and restarts from Research.

No “small parameter tweak” preserves prior promotion evidence.

## 10.4 Runtime Profiles may differ

Backtest, SIM and LIVE are allowed to use different runtime/environment profiles.

For example:

```text
Backtest
capital = large historical test capital
broker = virtual historical broker
execution = historical model

SIM
capital = simulated realtime capital
broker = simulated realtime broker

LIVE
capital = actual deployment allocation
broker = Binance real broker
execution = real venue execution
```

This does not change Strategy identity.

But every Profile must be canonicalized/fingerprinted and displayed in Promotion evidence.

## 10.5 Profile Diff

Promotion review must display exact source-stage vs target-stage environment differences.

Classification rule:

```text
Strategy semantic difference
→ HARD REJECT / new Research lineage

Operational/Profile difference
→ explicit diff + human review/approval
```

P9 does not need an overengineered policy DSL to express thousands of compatibility rules. Canonical profile identity and explicit human-visible diff are sufficient for first version.

## 10.6 Invalidation scope

A change invalidates only the stages that depend on it.

### Strategy Revision change

```text
invalidate Research lineage + Backtest + SIM + LIVE approval
restart Research
```

### Backtest Profile change

```text
keep Strategy/Research
rerun Backtest
invalidate downstream SIM/LIVE promotion
```

### SIM Profile change

```text
keep Strategy/Research/valid Backtest
rerun SIM
invalidate LIVE approval
```

### LIVE Deployment Profile change

```text
keep Strategy/Research/Backtest/SIM evidence
require new LIVE deployment approval
```

## 10.7 LIVE eligibility is scoped

`LIVE_ELIGIBLE` does not mean “this strategy may run anywhere forever”.

Eligibility binds at least:

```text
Strategy Revision fingerprint
Target environment
Target Live Deployment Profile fingerprint
Promotion evidence
```

A Testnet approval cannot authorize Mainnet.

Major changes to capital/account/broker/leverage/risk/execution deployment intent require a new target deployment approval.

Dynamic external facts such as current balance, market status or current reference snapshot are verified by LIVE startup/reconciliation rather than forcing the entire Research chain to rerun.

## 10.8 PromotionRecord is immutable evidence

A PromotionRecord should bind concepts equivalent to:

```text
promotion_id
strategy_revision_id/fingerprint
from_stage
to_stage
source evidence id/fingerprint
source profile fingerprint
target profile fingerprint
gate assessment fingerprint
decision
approver
reason
created_at
previous/superseded record linkage
record fingerprint
```

An approval is not mutated in place. Revocation/supersession creates a new record.

## 10.9 First system-certification strategy

Use a deliberately simple deterministic `BTCUSDT 1m` strategy such as an EMA-cross/threshold strategy.

Purpose:

```text
SYSTEM_CERTIFICATION
```

not alpha quality.

The purpose is to verify semantic continuity:

```text
same Strategy Revision
→ Research
→ Freeze
→ Backtest
→ SIM
→ LIVE Observation
→ LIVE Testnet execution
```

A weak-return strategy can still be suitable for system certification if it deterministically exercises the required path.

## 10.10 P9.6 tasks

```text
P9.6.0 Promotion Authority & Immutable Record
P9.6.1 Stage Evidence Bundle
P9.6.2 Strategy Revision Continuity Guard
P9.6.3 Stage Profile Fingerprints & Diff
P9.6.4 Promotion Invalidation Rules
P9.6.5 Human Promotion Workflow
P9.6.6 BTCUSDT 1m Full Vertical
```

## 10.11 P9.6 acceptance

The complete Testnet chain must be demonstrable:

```text
Recorded / Historical Data
→ Immutable Dataset
→ Research
→ Human approval
→ Strategy Revision
→ Backtest
→ Human approval
→ SIM
→ Human approval
→ LIVE_ELIGIBLE(TESTNET)
→ LIVE Observation
→ Explicit Execution Permission
→ Binance Testnet Order
→ Venue Fill
→ Portfolio / Accounting
```

Every stage exposes exact fingerprints and lineage evidence.

---

# 11. P9.7 — Production Closure & Certification

## 11.1 Goal

P9.6 proves the vertical can run.

P9.7 proves the vertical remains explainable, deterministic and safe across faults, crashes, duplicate events, gaps and recovery.

P9 final certification requires BOTH:

```text
Binance Spot Testnet
+
Binance USD-M Futures Testnet
```

## 11.2 Mainnet boundary

Mainnet is not part of automatic P9 certification.

```text
TESTNET
→ system certification environment

MAINNET
→ explicit human-approved deployment environment
```

`P9 CERTIFIED` MUST NOT automatically enable Mainnet execution.

## 11.3 Mandatory fault classes

### Market Data faults

At minimum:

```text
WebSocket disconnect
Kline gap
Trade sequence gap
duplicate event
out-of-order event
Depth sequence break
Depth snapshot/delta resync
BookTicker interruption
Mark/Index/Funding interruption
provider reconnect
backfill temporary failure
```

### Broker faults

At minimum:

```text
User Data Stream disconnect
REST timeout
submit timeout with venue acceptance
response loss after venue acceptance
duplicate callback
REST/User Stream temporary disagreement
UNKNOWN order
partial fill
cancel race
reconciliation mismatch
```

### Process/storage crash boundaries

Use deterministic named crash points around critical semantic boundaries, such as:

```text
before/after durable Order Intent
submit sent / response missing
venue accepted / local unknown
before/after ACK durable
partial fill before local consumption
fill before Portfolio commit
Portfolio commit before projection
WAL before seal
ClickHouse write before Manifest commit
```

Exact implementation names may differ, but the semantic boundaries must be explicit.

## 11.4 Deterministic barrier requirement

Correctness certification MUST NOT rely on `sleep()` timing guesses.

Required shape:

```text
process reaches named deterministic barrier
→ test harness observes barrier
→ inject fault / SIGKILL
→ restart
→ recover/reconcile
→ verify invariants
```

## 11.5 Fault test success means invariant convergence

A restarted process is not enough.

For execution crash cases verify, as applicable:

```text
same OnlyOrderId
same deterministic clientOrderId
no duplicate external order
venue order discovered/reconciled
local durable evidence converges
position converges
account converges
FULL execution remains closed until reconciliation
no unexplained UNKNOWN state remains
```

For market-data/storage cases verify exact gap/revision/WAL/manifest invariants.

## 11.6 Immutable Certification Bundle

P9 certification output must be an immutable evidence bundle that records at least:

```text
certification id/schema
exact code SHA/build identity
Strategy Revision id/fingerprint
Research evidence fingerprint
Backtest evidence fingerprint
SIM evidence fingerprint
Promotion Record fingerprints
Market Reference fingerprints
Market Data revision/manifest fingerprints
Dataset fingerprint
DataSource/Broker plugin identities
Spot Testnet environment identity
USD-M Testnet environment identity
normal vertical test results
fault injection results
crash-boundary results
recovery/reconciliation results
architecture/authority audit results
final verdict
bundle SHA256
```

Final verdict is binary and explicit:

```text
ACCEPTED
or
REJECTED
```

A green CI check without the immutable bundle is not sufficient final certification authority.

## 11.7 Real external evidence vs controlled fault evidence

Certification should distinguish:

```text
REAL_EXTERNAL_EVIDENCE
- actual Testnet connection/order/fill/account/User Stream behaviour

CONTROLLED_FAULT_EVIDENCE
- forced response loss
- network cut
- deterministic crash boundaries
- duplicate/out-of-order injection
- storage failure injection
```

Do not misrepresent controlled injection as naturally observed venue behaviour, and do not use normal Testnet success as a substitute for dangerous-path testing.

## 11.8 Soak tests

Long-running soak tests are required as prepared/manual validation capability but are NOT a mandatory every-commit/automatic P9 CI gate.

The repository must provide executable test cases, metrics, expected thresholds and reporting for at least practical durations such as:

```text
1h smoke soak
6h short soak
24h standard soak
72h+ extended soak
```

24h/72h tests may be run manually on local/integration infrastructure.

Soak validation should monitor at least:

```text
Market Data
- reconnect/gap/recovery counts
- recovery latency
- event rate
- duplicate/out-of-order count
- WAL/queue depth
- ClickHouse writer backlog

Broker
- user stream reconnects
- reconciliation count
- UNKNOWN count
- order/trade/position/balance divergence

Runtime
- RSS / memory growth slope
- thread/task count
- queue depth
- event/decision/persistence latency

Storage
- WAL disk use
- uncommitted segment count
- ClickHouse ingest latency
- PostgreSQL connection/manifest backlog
```

A soak run ends with an explicit reconciliation/drain/coverage verification, not merely “process is still alive”.

## 11.9 Authority audit

P9.7 must explicitly re-audit uniqueness:

```text
Strategy semantics
→ Strategy Revision

Research truth
→ immutable Research Result / Artifact

Historical Research input
→ immutable Dataset Snapshot

Raw provider market evidence
→ raw provider records

Canonical historical market facts
→ exact Market Data Revision / Manifest

External execution facts
→ venue

Local execution intent/runtime state
→ durable Trading Runtime evidence

Promotion authority
→ append-only human PromotionRecord

LIVE execution permission
→ durable LIVE Safety State
```

No pair of components may compete for the same fact authority.

## 11.10 Architecture boundary audit

Certification rejects architectural leakage such as:

```text
Binance DTO/import leaked into Core
provider directly writing ClickHouse SQL as its domain API
ClickHouse becoming Research semantic truth
Broker modifying Strategy semantics
LIVE-specific signal calculation
SIM-specific strategy interpretation
Web directly enabling Broker execution without the Runtime gate
Promotion bypass
Research Candidate directly reaching Trading Runtime
mutable Strategy Revision
in-place historical market overwrite
HTTP response treated as fill truth
sleep-based crash correctness test
```

## 11.11 P9.7 tasks

```text
P9.7.0 Conformance Contract & Invariants
P9.7.1 Spot Full-Vertical Conformance
P9.7.2 USD-M Full-Vertical Conformance
P9.7.3 Market Data Fault Evidence
P9.7.4 Broker Fault & Reconciliation Evidence
P9.7.5 Deterministic Crash-Boundary Evidence
P9.7.6 Storage / WAL / Revision Recovery Evidence
P9.7.7 Architecture & Authority Audit
P9.7.8 Manual Soak Test Suite
P9.7.9 Composed Phase Gate
```

## 11.12 Production vertical acceptance properties

The production vertical must eventually prove through the applicable Phase Gate and current repository behavior:

> OnlyAlpha has a production-grade Binance Spot + USD-M Futures Research → Strategy Revision → Backtest → SIM → LIVE Testnet vertical, a provider-neutral Market Data Platform, real Broker integration, deterministic reconciliation/recovery, human Promotion, and fail-closed LIVE safety. Mainnet remains an explicit human-approved deployment phase and is not automatically authorized by Testnet evidence.

---

# 12. Stage dependency graph

P9 implementation is intentionally sequential where semantics depend on earlier authority.

```text
P9.0 Strategy / Promotion Foundation
        │
        ├───────────────┐
        │               │
        ▼               ▼
P9.1 Market Product   Strategy consumers
        │
        ▼
P9.2 Binance DataSource
        │
        ▼
P9.3 Market Data Platform
        │
        ├──────────────→ Dataset / Research / Backtest
        │
        ▼
P9.4 Real Broker
        │
        ▼
P9.5 LIVE Runtime
        │
        ▼
P9.6 Full Promotion Vertical
        │
        ▼
P9.7 Production Closure / Certification
```

Implementation may prepare independent mechanical pieces in parallel, but no later stage may weaken or bypass an earlier authority merely to unblock integration.

---

# 13. Engineering implementation policy for every P9.x task

Every P9.x Codex/implementation task MUST begin by reading current repository truth and this document.

It MUST then:

1. identify existing reusable authorities/contracts before adding new ones;
2. define the exact missing durable/domain fact first;
3. modify the smallest stable Core boundary necessary;
4. keep provider code outside stable Core semantics;
5. keep one authority for each fact;
6. avoid permanent compatibility wrappers where migration/deletion is appropriate;
7. add deterministic identity/fingerprint rules before persistence/API convenience;
8. add failure and recovery semantics before claiming product readiness;
9. keep bounded queues/resources and explicit backpressure policies;
10. add architecture tests for forbidden dependency directions;
11. avoid token/CI waste: slow external/soak work belongs in explicit integration/manual/certification lanes rather than every lightweight unit lane;
12. never declare a major milestone certified from local tests alone.

Default engineering preference remains:

```text
simple explicit domain model
> magical abstraction

one stable port
> provider-specific shortcuts

immutable evidence
> mutable repair

deterministic barrier
> timing guess

fail closed
> silent fallback
```

---

# 14. Required P9 evidence lineage

By P9 completion, the system should be able to explain one LIVE Testnet decision from first principles:

```text
Why did this order exist?
        ↓
Order Intent
        ↓
Decision / Signal
        ↓
Exact Strategy Revision
        ↓
Decision Graph + Calculation versions + parameters
        ↓
Research lineage / immutable evidence

What data caused it?
        ↓
Realtime canonical market event
        ↓
provider raw evidence / sequence / reference snapshot

Why was it allowed to execute?
        ↓
PromotionRecord
        +
LIVE Deployment Profile
        +
Execution Permission
        +
MarketDataReady
        +
BrokerReconciled

What actually happened?
        ↓
Venue execution fact
        ↓
canonical Broker fact
        ↓
durable Runtime transaction
        ↓
Portfolio / Accounting projection
```

If this chain cannot be reconstructed, P9 is not complete.

---

# 15. Frozen P9 summary

```text
P9.0
Immutable Strategy Revision + append-only Promotion foundation

P9.1
Generic Crypto semantics + Binance Spot/USD-M Reference authority

P9.2
Binance historical/realtime DataSource + strong stream-specific recovery

P9.3
Universal append-only Market Data Platform
ClickHouse facts + PostgreSQL manifests + immutable Dataset Snapshot boundary

P9.4
Binance Spot first, then USD-M real Broker
UNKNOWN state + deterministic client identity + authoritative reconciliation

P9.5
Shared-kernel LIVE Runtime
Observation / Reduce-only / Full / Halt + Kill Switch + fail-closed new risk

P9.6
Human-approved Research → Backtest → SIM → LIVE_ELIGIBLE vertical
same Strategy Revision fingerprint through every stage

P9.7
Spot + USD-M Testnet production closure
fault/crash/recovery certification + immutable final evidence bundle
manual long-duration soak suite prepared but not an every-commit hard gate
```

This document is the default task-selection and design authority for all P9 implementation prompts. A P9.x implementation that contradicts these invariants must stop and update the architecture contract explicitly rather than silently introducing a second interpretation.
