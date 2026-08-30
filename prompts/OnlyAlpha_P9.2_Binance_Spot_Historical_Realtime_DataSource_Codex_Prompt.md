# OnlyAlpha P9.2 — Binance Spot Historical & Realtime DataSource
## Codex Implementation Task Prompt

> Task type: **P9.2 Product Increment Implementation**
>
> Project: `zongxin1993/OnlyAlpha`
>
> Stage authority: `project-state.toml`
>
> Current authorized increment:
>
> ```text
> P9.2
> Binance Spot Historical & Realtime DataSource
> IMPLEMENTATION READY
> ```
>
> This task must be implemented from first principles.
>
> The implementation MUST preserve OnlyAlpha's frozen engineering principles:
>
> ```text
> Correctness
> > Determinism
> > Uniqueness
> > Explicit Authority
> > Fail-Closed
> > Reproducibility
> > Market Neutrality
> > Provider Isolation
> > Maintainability
> > Performance
> > Convenience
> ```
>
> The objective is NOT to “connect Binance REST + WebSocket”.
>
> The objective is:
>
> > **Build OnlyAlpha's first trustworthy real-market-data ingress path, where Historical and Realtime Binance Spot facts converge into one provider-neutral canonical market-data model with unique identities, deterministic time semantics, explicit continuity scopes, exact coverage, gap detection, recoverable reconnect semantics, and no Binance-specific branching in Core consumers.**

---

# 1. Mandatory startup procedure

Before editing code:

1. Read current `master`.
2. Read `project-state.toml`.
3. Confirm:
   ```text
   last_verified_increment = P9.1
   next_authorized_increment = P9.2
   ```
4. Read the current implementations of:
   - `src/onlyalpha/data/`
   - `src/onlyalpha/cache/historical/`
   - `src/onlyalpha/plugin/data_source.py`
   - `src/onlyalpha/domain/market.py`
   - `src/onlyalpha/market/`
   - `packages/provider/onlyalpha-plugin-miniqmt/`
   - `packages/provider/onlyalpha-plugin-tushare/`
   - `packages/provider/onlyalpha-plugin-binance/`
   - `packages/market/onlyalpha-market-binance-spot/`
5. Read:
   - `docs/p9_binance_spot_golden_vertical_execution_plan.md`
   - `docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md`
   - `docs/reports/p9_1_binance_spot_market_product_reference_authority.md`
6. Use current source code as authority if any old prompt conflicts with current `master`.

Do NOT begin with a broad audit.

Perform only a bounded root-cause/design validation necessary for P9.2.

---

# 2. P9.2 first-principles statement

Market data correctness is not:

```text
API returned JSON
```

Market data correctness is:

```text
At time T,
for instrument I,
what market fact happened?

Is it unique?
Is it final?
Is it ordered?
Is anything missing?
Can a disconnect be recovered without silently losing facts?
```

The fundamental contract is:

```text
Canonical Market Fact
=
F(
    Venue Raw Fact,
    Market Reference,
    Normalization Contract
)
```

Therefore:

```text
same raw venue fact
+ same reference semantics
+ same normalization/data version

→ same canonical market fact
```

This must hold regardless of transport:

```text
REST
WebSocket
Recovery REST
Historical replay
```

---

# 3. Market-neutral architecture is mandatory

The implementation MUST preserve:

```text
Binance payload
→ Binance plugin adapter
→ provider-neutral Core DTO/domain
→ Core / Runtime
```

Provider-specific payloads must terminate inside the adapter.

Forbidden in stable Core:

```text
BinanceTrade
BinanceBar
BinanceKline
BinanceReferencePrice
BinanceSequence
BinanceTradeIdGap
BTCUSDT special cases
ETHUSDT special cases
Binance JSON field names
Binance SDK types
```

Core may only gain abstractions that are independently meaningful for:

```text
Binance
QMT
CTP
future crypto providers
future futures providers
```

Market neutrality does NOT mean every provider implements the same mechanics.

It means:

> Provider differences terminate at the adapter, while Core contracts remain provider-neutral.

---

# 4. Frozen authority model

The implementation MUST preserve this authority split:

```text
P9.1 Reference Authority
→ instrument / market semantics / trading rules

Binance Venue
→ raw external market fact authority

Binance P9.2 Adapter
→ provider raw → canonical normalization authority

P9.2 Continuity Layer
→ stream continuity / duplicate / gap / recovery-state authority

P9.2 Historical Cache
→ verified acquisition coverage cache
  NOT long-term production truth

P9.3 Market Data Revision Platform
→ durable production market-data authority
```

Do not turn P9.2 cache into a second durable production authority.

---

# 5. Scope summary

P9.2 MUST deliver:

```text
Historical:
- BTCUSDT 1m closed Bars
- ETHUSDT 1m closed Bars
- BTCUSDT raw Trades
- ETHUSDT raw Trades
- exact [start, end) range semantics
- local-first verified acquisition cache
- exact missing-range fetch
- strict validation
- deterministic normalization

Realtime:
- closed 1m Bar
- raw Trade
- realtime Market Reference
- reconnect detection
- duplicate detection
- out-of-order detection
- gap evidence
- historical recovery/backfill
- deterministic READY barrier

Architecture:
- provider-neutral Core
- Binance plugin through existing DataSource SPI
- Historical and Realtime use the same canonical semantics
```

---

# 6. Explicitly out of scope

DO NOT implement:

```text
P9.3:
- ClickHouse
- PostgreSQL market-data schema
- WAL
- durable Market Data Revision
- crash-restart persistent stream cursor
- HOT/COLD lifecycle
- database migration for market data

P9.4:
- Binance API key
- signatures
- private REST
- userDataStream
- account
- balance
- position
- orders
- broker
- reconciliation

Other:
- Binance Futures
- QMT implementation
- CTP implementation
- L2/depth unless a concrete current Core dependency proves it necessary
- SBE optimization
- distributed WS sharding
- Binance SDK
- CCXT
- universal JSON event framework
- second Engine
- second Runtime
- second MarketDataManager
```

Do not optimize unrelated performance warnings.

---

# 7. Implementation order

Implement in this strict order:

```text
P9.2-A
Market Fact Identity & Continuity Foundation

P9.2-B
Typed Historical Cache Closure

P9.2-C
Binance Historical Closed Bar

P9.2-D
Binance Historical Raw Trade

P9.2-E
Binance Realtime DataSource

P9.2-F
Continuity / Gap / Reconnect Recovery

P9.2-G
Realtime Market Reference Authority

P9.2-H
Plugin Composition / CI / Evidence Closure
```

Do not start with WebSocket transport before identity and continuity semantics are fixed.

---

# 8. P9.2-A — Stable Market Fact Identity

Current code mixes fact identity and source sequence. These are different concepts.

Identity asks:

```text
Is this the same market fact?
```

Sequence asks:

```text
Does this fact belong to a continuous ordered stream?
```

Do not use one as a substitute for the other.

Prefer a small Core module such as:

```text
src/onlyalpha/data/identity.py
```

or an equivalent existing appropriate location.

Provide canonical market-data identity creation.

### Bar identity

Conceptually:

```text
source
+ instrument
+ BAR
+ bar_type
+ bar_start
+ data_version
```

### Trade identity

Conceptually:

```text
source
+ instrument
+ TRADE
+ venue trade identity
+ data_version
```

### Market Reference identity

Conceptually:

```text
source
+ instrument
+ reference kind
+ venue effective/event timestamp
+ data version
```

Use existing canonical fingerprint primitives where appropriate.

Do not invent unstable random IDs.

---

# 9. `OnlyMarketDataUpdateId` must be fact-derived

The following style must not remain the canonical identity authority:

```text
miniqmt-live-1
binance-live-123
cache-42
```

Processing-order IDs are not fact identities.

Goal:

```text
REST Trade #N
WebSocket Trade #N
Recovery Trade #N
→ same canonical update_id
```

Likewise:

```text
REST closed Bar
WebSocket closed Bar
→ same canonical update_id
```

when they represent the same venue fact.

---

# 10. Explicit sequence semantics

Add a market-neutral sequence model.

Suggested concepts:

```text
OnlyDataSequenceScope
OnlyDataSequenceSemantics
```

Suggested semantics:

```text
UNKNOWN
MONOTONIC
CONTIGUOUS
```

Meaning:

### UNKNOWN

```text
sequence exists only as metadata
do not use it to prove continuity
```

### MONOTONIC

```text
current <= previous
→ stale / out-of-order

current > previous + 1
→ NOT automatically a gap
```

### CONTIGUOUS

```text
current <= previous
→ stale / out-of-order

current > previous + 1
→ gap evidence
```

This model MUST be provider-neutral.

---

# 11. Sequence scope

The continuity key MUST no longer be:

```text
(source_id, data_type)
```

At minimum, the semantic scope must distinguish:

### Trade

```text
source
+ instrument
+ data type
```

### Bar

```text
source
+ instrument
+ data type
+ bar type
```

The implementation may use an explicit value object.

Do not hard-code Binance-specific semantics into Core.

---

# 12. Upgrade `OnlyMarketDataInboundUpdate`

Extend the envelope only as necessary to express:

```text
fact identity
sequence
sequence scope
sequence semantics
data version
```

If serialization changes:

```text
schema_version = 2
```

but existing `schema_version = 1` data/fixtures/checkpoints must remain readable where the project currently promises compatibility.

Do not silently break existing MiniQMT/Tushare tests.

---

# 13. Deduplicator redesign

The deduplicator must stop inventing a second identity model.

Preferred authority:

```text
update.update_id
```

Do not independently reconstruct Bar keys and non-Bar keys inside the deduplicator.

Goal:

```text
same fact
→ same update_id
→ duplicate
```

---

# 14. SequenceTracker redesign

The tracker must use explicit sequence scope.

Pseudo-semantics:

```text
UNKNOWN
→ no sequence continuity decision

MONOTONIC
→ <= previous => stale
→ otherwise accept

CONTIGUOUS
→ <= previous => stale
→ > previous + 1 => gap
```

Checkpoint serialization must preserve the explicit scope.

---

# 15. Multi-symbol regression is mandatory

Tests MUST prove:

```text
BTCUSDT trade 100
ETHUSDT trade 900
BTCUSDT trade 101
```

does NOT create:

```text
fake BTC gap
fake ETH stale
cross-symbol contamination
```

Likewise Bar continuity must be isolated by:

```text
instrument
bar type
```

---

# 16. MiniQMT compatibility requirement

Do NOT redesign MiniQMT around Binance semantics.

MiniQMT may use provider-generated sequence semantics different from Binance.

The new Core model must allow MiniQMT to explicitly declare its sequence semantics.

Existing MiniQMT behavior must remain compatible unless a real correctness bug is proven.

---

# 17. P9.2-B — Typed Historical Cache Closure

Current historical cache API is named generically but is Bar-specific.

P9.2 requires:

```text
BAR
TRADE
```

Forbidden design:

```text
MarketDataCache[object]
payload: dict
type: string
```

Correct structure:

```text
Shared Historical Cache Correctness
- inspect
- exact missing ranges
- coverage
- manifest
- hashing
- atomicity
- cache policy
- corruption detection

Typed Families
- Bar
- Trade
```

---

# 18. Historical cache API shape

A preferred minimal public API:

```python
load_bars(...)
load_trades(...)
```

Existing:

```python
load(...)
```

may remain as a Bar compatibility path if needed for current providers.

Do not force a large breaking rewrite if a small typed extension solves the problem.

---

# 19. Historical cache key families

Prefer explicit typed keys:

```text
OnlyHistoricalBarCacheKey
OnlyHistoricalTradeCacheKey
```

Common identity:

```text
source_id
instrument_id
dataset_type
data_version
schema_version
time_semantics_version
compatibility_profile_id
```

Bar-specific:

```text
bar_type
adjustment mode
adjustment reference
```

Trade-specific:

```text
no fake bar_type
no fake adjustment fields
```

Avoid invalid states such as `bar_type=None` for Trade.

---

# 20. DataVersion is part of cache identity

The normalized cache identity MUST change if the normalization contract changes.

Conceptually:

```text
Provider
+ Instrument
+ Data Family
+ Market Semantics
+ DataVersion
+ Time Semantics Version
+ Compatibility Profile
```

Therefore:

```text
Normalizer V1 cache
must not silently satisfy
Normalizer V2 request
```

---

# 21. Physical partitioning may differ by family

Do not force Bar and Trade into the same physical partition model.

Reasonable:

```text
Bars:
coarse partition

Trades:
daily/monthly partition appropriate for higher volume
```

But both must share:

```text
manifest semantics
content hash
atomic publication
coverage proof
```

---

# 22. Historical cache correctness tests

Tests for both families must cover:

```text
full local hit
partial local hit
exact missing range
force refresh
cache-only failure
empty-but-resolved range
provider validation failure
corrupt partition
manifest mismatch
atomic write
deterministic read order
content fingerprint stability
```

---

# 23. Binance DataSource plugin structure

Add a narrow provider implementation under:

```text
packages/provider/onlyalpha-plugin-binance/
└── src/onlyalpha_plugin_binance/
    └── spot/
        ├── reference/          # P9.1 frozen
        └── data_source/
            ├── config.py
            ├── factory.py
            ├── resource.py
            ├── historical.py
            ├── websocket.py
            ├── normalize.py
            └── continuity.py
```

File names may be adjusted if current repository conventions suggest a smaller structure.

Do not create unnecessary layers.

---

# 24. Plugin module responsibilities

## `config.py`

Provider operational settings only.

Allowed:

```text
environment
REST base
WS base
timeout
max response bytes
max WS message bytes
bounded reconnect backoff
recovery buffer limits
```

Forbidden:

```text
symbol list
bar list
strategy configuration
runtime universe duplication
```

What data is requested is already owned by OnlyAlpha composition.

## `factory.py`

Responsibilities:

```text
OnlyDataSourceFactory SPI
parse config
capability validation
resource construction
```

Follow current Tushare/MiniQMT SPI patterns.

## `historical.py`

Responsibilities:

```text
REST request planning
pagination
exact range mapping
historical Bar acquisition
historical Trade acquisition
```

No Runtime logic.

## `websocket.py`

Transport only:

```text
connect
receive
ping/pong
close
server shutdown handling
bounded reconnect transport
message-size bounds
```

It must NOT normalize Bars/Trades.

## `normalize.py`

Pure normalization functions.

Examples:

```text
REST Kline → OnlyBar
WS closed Kline → OnlyBar

REST raw Trade → OnlyTradeTick
WS raw Trade → OnlyTradeTick

referencePrice raw fact → provider-neutral Market Reference fact
```

No network calls.

## `continuity.py`

Responsibilities:

```text
stream state
buffer
duplicate reconciliation
gap evidence
recovery orchestration
READY barrier
```

## `resource.py`

Implements:

```text
OnlyDataSource
OnlyHistoricalDataSource
OnlyMarketDataGateway
OnlyReferenceDataSource
OnlyPluginResource
```

Composition/lifecycle only.

---

# 25. Register Binance through existing SPI

Update package entry points:

```toml
[project.entry-points."onlyalpha.data_sources"]
binance = "onlyalpha_plugin_binance.spot.data_source.factory:factory"
```

or the exact convention used by the current repository.

Core must never import:

```text
onlyalpha_plugin_binance
```

---

# 26. DataSource capabilities

P9.2 Binance should advertise capabilities equivalent to:

```text
historical_bars = true
historical_ticks = true
live_bars = true
live_ticks = true
live_reconnect = true
supports_runtime_checkpoint = STATELESS
```

Use actual current capability schema.

Do not falsely advertise unsupported quote/depth/private capabilities.

---

# 27. Why STATELESS is correct in P9.2

P9.2 owns:

```text
in-process disconnect/reconnect recovery
```

P9.3 owns:

```text
WAL
durable cursor
process crash recovery
persistent market-data revision
```

Do not create ad hoc persistent stream-state authority in P9.2.

---

# 28. P9.2-C — Historical Closed Bar

Mandatory first scope:

```text
BTCUSDT
ETHUSDT
1m
RAW
UTC
closed Bars only
```

Use public Binance Spot REST.

P9.2 does NOT require bulk archive ingestion.

REST correctness first.

Bulk archive ingestion can be a later P9.3 ingestion optimization.

---

# 29. Historical Bar flow

```text
OnlyHistoricalBarRequest
        ↓
OnlyAlpha [start,end)
        ↓
inspect verified local cache
        ↓
complete?
├─ yes → return local
└─ no
   ↓
calculate exact missing ranges
   ↓
Binance REST Kline
   ↓
normalize
   ↓
strict validate
   ↓
persist
   ↓
reinspect
   ↓
return only if qualified
```

Never treat “rows exist” as coverage proof.

---

# 30. Bar canonical time semantics

OnlyAlpha Bar interval is:

```text
[bar_start, bar_end)
```

For Binance 1m Kline:

```text
bar_start = venue open time
bar_end   = bar_start + 1 minute
ts_event  = bar_end
```

Do NOT use the venue's inclusive millisecond close timestamp as the Core interval endpoint.

Core interval semantics are mathematical half-open intervals.

---

# 31. Closed Bar rule

Historical provider must only publish complete closed Bars.

Realtime WebSocket:

```text
x=false
→ provisional provider state
→ NOT canonical closed Bar

x=true
→ canonical closed Bar
```

Do not masquerade an updating Kline as a final Bar.

---

# 32. Historical vs Realtime Bar equivalence

Hard invariant:

```text
same Binance closed Kline

REST path
WS x=true path

→ same OnlyBar
→ same semantic identity
```

Ignore transport observation metadata when comparing canonical fact semantics.

---

# 33. Historical range authority

Core authority:

```text
[start, end)
```

Create one Binance range mapper.

Do NOT independently encode provider boundary conversion in:

```text
paginator
normalizer
cache
```

After fetch, final acceptance must satisfy the canonical range.

---

# 34. Pagination correctness

Bar pagination must have:

```text
bounded page size
monotonic cursor
duplicate detection
no-progress detection
out-of-range rejection
```

If provider response does not move the cursor:

```text
FAIL
```

Do not infinite-loop.

---

# 35. Open current Bar cannot close historical coverage

If current 1m Bar is not final:

```text
requested range including that Bar
→ range remains incomplete
```

Do not use provisional venue rows to claim verified historical coverage.

---

# 36. P9.2-D — Historical Raw Trade

Use:

```text
OnlyTradeTick
```

as canonical domain.

Canonical Trade MUST represent one raw venue trade.

Forbidden:

```text
aggTrade
→ OnlyTradeTick
```

Aggregated trade may only serve as an index/locator if necessary.

---

# 37. Historical trade acquisition

If raw historical trade retrieval is ID-based:

```text
requested [start,end)
        ↓
time-range locator
        ↓
approx raw trade IDs
        ↓
raw historical trades
        ↓
filter exact [start,end)
```

Canonical facts MUST come from raw trades.

Locator rows must not be emitted.

---

# 38. Trade normalization

Map venue raw trade to:

```text
trade_id
price
quantity
ts_event
aggressor_side
```

Use venue-provided maker/aggressor semantics.

Do not infer aggressor from price movement.

Binance-specific trade-ID recovery logic stays in plugin.

---

# 39. Historical vs Realtime Trade equivalence

Hard invariant:

```text
same raw venue trade

historical REST
realtime WS
recovery REST

→ same OnlyTradeTick
→ same update_id
```

---

# 40. Event time vs observation time

Realtime:

```text
ts_event
→ venue event time

ts_init
→ OnlyAlpha observation/ingress time
```

Historical deterministic replay:

```text
ts_event
→ venue event time

ts_init
→ deterministic replay semantics
```

Acquisition timestamp belongs in provenance/manifest metadata, not fact identity.

---

# 41. P9.2-E — Public WebSocket

Do not use Binance SDK or CCXT.

Use a small transport implementation/dependency.

Transport responsibilities:

```text
connect
receive
ping/pong
close
server shutdown
bounded reconnect
message-size bound
```

Transport must not understand canonical Bar/Trade semantics.

---

# 42. Initial connection scope

First vertical:

```text
BTCUSDT:
trade
kline_1m
market reference

ETHUSDT:
trade
kline_1m
market reference
```

Do not design distributed stream sharding.

Use a simple bounded combined connection unless current provider protocol strongly requires another minimal structure.

---

# 43. Connection state semantics

Add/use:

```text
DISCONNECTED
CONNECTING
CONNECTED
RECOVERING
READY
FAILED
```

`RECOVERING` is market-neutral if needed.

Meanings:

```text
CONNECTED
→ transport exists

RECOVERING
→ transport exists
  but continuity is not yet proven

READY
→ required subscription/recovery contract satisfied
```

---

# 44. `CONNECTED != READY`

Never:

```text
socket connected
→ READY
```

READY requires:

```text
subscription established
baseline known
backfill complete
buffer reconciled
duplicates resolved
continuity proven
```

---

# 45. Startup race

Handle the race between historical baseline and realtime subscription.

Use:

```text
connect/start realtime buffering
↓
establish baseline
↓
reconcile buffered facts
↓
prove continuity
↓
READY
```

No silent gap window.

---

# 46. P9.2-F — Bar gap recovery

Example:

```text
last accepted:
10:00–10:01

new:
10:03–10:04
```

Missing:

```text
10:01–10:02
10:02–10:03
```

Recovery:

```text
detect gap
↓
RECOVERING
↓
buffer newer realtime
↓
historical exact backfill
↓
same normalizer
↓
validate
↓
merge
↓
dedup
↓
publish deterministic order
↓
READY
```

If gap cannot be proven repaired:

```text
remain NOT READY
```

---

# 47. Trade gap recovery

Core must not know Binance trade-ID arithmetic.

Core owns:

```text
identity
sequence scope
sequence semantics
generic continuity result
```

Binance plugin owns:

```text
venue trade cursor
historical raw-trade recovery
```

Recovery:

```text
last accepted cursor
↓
disconnect/gap
↓
buffer WS facts
↓
fetch missing raw trades
↓
same normalizer
↓
merge by canonical identity
↓
prove boundary
↓
READY
```

---

# 48. Recovery buffer must be bounded

Configure at least one hard bound:

```text
max events
and/or
max bytes
```

Overflow:

```text
RECOVERY_BUFFER_OVERFLOW
→ FAILED / NOT READY
```

Never drop facts and pretend continuity.

---

# 49. Bounded operations

All operations must be bounded:

```text
connect timeout
HTTP timeout
REST response size
WS message size
REST page size
reconnect backoff
max backoff
recovery buffer
```

A long-lived retry lifecycle is allowed.

An individual unbounded operation is not.

---

# 50. P9.2-G — Realtime Market Reference Authority

P9.1 already emits dynamic requirements whose authority is:

```text
REALTIME_MARKET_REFERENCE
```

P9.2 must implement that missing fact authority.

Do not leave P9.1 dynamic requirements unresolved.

---

# 51. Add provider-neutral market reference fact

Do NOT create a Core Binance type.

Prefer:

```text
OnlyMarketReferenceKind
OnlyMarketReferenceTick
```

Initial kind:

```text
VENUE_REFERENCE_PRICE
```

Suggested fields:

```text
instrument_id
reference_kind
price: OnlyPrice | None
ts_event
ts_init
sequence
source
```

`None` may represent an explicit venue fact:

```text
reference currently unavailable
```

This is not the same as:

```text
no message received
```

---

# 52. Extend market-data envelope

Add if required:

```text
OnlyMarketDataType.MARKET_REFERENCE
OnlyMarketReferenceUpdate
```

Update serialization/compatibility carefully.

Do not create a separate Binance-only runtime pipeline.

---

# 53. Realtime reference authority is Core

Implement a market-neutral authority in an appropriate Core module, for example:

```text
src/onlyalpha/market/realtime_reference.py
```

Conceptual API:

```text
ingest_trade
ingest_reference
resolve(requirement, instrument, as_of)
```

Output should explain:

```text
resolved value
evidence kind
coverage/window
as_of
```

---

# 54. P9.1 requirement drives resolution

Provider plugin only supplies facts.

The Core authority interprets provider-neutral P9.1 requirements such as:

```text
VENUE_REFERENCE_PRICE
VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE
```

Do not evaluate Binance trading legality inside the plugin.

---

# 55. VWAP fallback requires continuity proof

Never:

```text
some recent trades
→ calculate VWAP
```

For a required N-minute window:

```text
[as_of-Nm, as_of]
```

must be proven complete.

Otherwise:

```text
MARKET_REFERENCE_UNAVAILABLE
```

Fail closed.

---

# 56. Zero-minute reference window

If requirement semantics mean:

```text
window = 0
```

resolve using the last valid Trade fact.

Do not invent an arbitrary averaging window.

---

# 57. Market-reference warmup

Derive required Trade warmup from the compiled P9.1 requirement.

Conceptually:

```text
max required trade window
↓
historical Trade warmup
+
buffered realtime Trade
+
venue reference state
↓
reference authority ready
```

Do not hard-code a fixed warmup if the Market Product already defines it.

---

# 58. Reference reconnect

If there is both a public snapshot and a realtime reference stream:

```text
reconnect
↓
buffer reference updates
↓
load current reference snapshot
↓
merge by event/effective time
↓
rebuild state
↓
READY
```

Do not accept an arbitrary first frame as proof of recovery.

---

# 59. Quote/bookTicker scope

Default:

```text
MANDATORY:
- closed Bar
- raw Trade
- Market Reference

OPTIONAL:
- Quote/bookTicker

OUT:
- Depth/L2
```

Only implement Quote if a current canonical consumer proves the need.

Do not broaden scope for feature completeness.

---

# 60. Reuse existing Binance environment and HTTP

Centralize provider URLs.

Reuse the bounded public HTTP client.

Do not create multiple HTTP clients for:

```text
reference
historical
recovery
```

unless a concrete protocol difference requires it.

No credentials in P9.2.

---

# 61. DataSource lifecycle

Recommended semantics:

```text
initialize
→ config validated

connect
→ transport connected

authenticate
→ no-op/accepted for public source
→ does NOT imply READY

start
→ worker active

subscribe
→ desired streams
→ initial recovery
→ READY

disconnect
→ stop publication
→ DISCONNECTED

stop
→ deterministic shutdown
```

Respect existing Plugin lifecycle contracts.

---

# 62. Subscription authority

Do not duplicate symbols in Binance config.

Authoritative requested data comes from:

```text
OnlyDataSourceCreateRequest
OnlyMarketDataSubscriptionRequest
coverage
instruments
bar_types
universes
```

Rule:

```text
OnlyAlpha decides WHAT
Binance plugin decides HOW
```

---

# 63. No durable checkpoint

P9.2 stays process-restart `STATELESS`.

Do not implement:

```text
durable WS cursor
WAL
persistent stream checkpoint
```

That belongs to P9.3.

---

# 64. Deterministic recovery tests

Do not use:

```python
sleep(...)
```

Use:

```text
Fake REST
Fake WebSocket
Deterministic Clock
Explicit recovery barriers
Injected gap/disconnect events
```

---

# 65. Required characterization tests

## C1 Bar convergence

```text
same venue closed Kline:
REST vs WS
→ same OnlyBar
→ same update_id
```

## C2 Trade convergence

```text
same raw venue Trade:
historical REST vs WS vs recovery REST
→ same OnlyTradeTick
→ same update_id
```

## C3 Open Kline

```text
x=false
→ not canonical closed Bar
```

## C4 Multi-symbol sequence isolation

```text
BTC stream cannot affect ETH stream
```

## C5 Duplicate convergence

```text
same fact from two transports
→ exactly one accepted fact
```

## C6 Bar recovery

```text
10:00
10:03
+
backfill 10:01,10:02

→ 10:00,10:01,10:02,10:03
→ READY
```

## C7 Trade recovery

Inject a deterministic Trade-ID gap and prove exact recovery.

## C8 Recovery failure

```text
unproven recovery
→ NOT READY
```

## C9 Buffer overflow

```text
→ fail closed
```

## C10 Historical exact range

All records satisfy canonical `[start,end)`.

## C11 Provisional Bar

Current open Bar cannot satisfy historical coverage.

## C12 Cache versioning

```text
V1 normalized cache
!=
V2 request
```

## C13 Venue reference

Venue reference available:

```text
→ resolve venue reference
```

## C14 Reference fallback

Reference unavailable + complete Trade window:

```text
→ deterministic fallback
```

## C15 Incomplete reference evidence

```text
→ unavailable
```

---

# 66. Provider-boundary architecture tests

Tests must prove:

```text
Core does not import onlyalpha_plugin_binance

Core does not contain Binance payload-field assumptions

Binance DTOs terminate inside adapter

Binance DataSource is loaded through existing SPI

Core consumers receive only provider-neutral market facts
```

---

# 67. Hard-coded symbol guard

Core business code must not hard-code:

```text
BTCUSDT
ETHUSDT
```

Allowed only in:

```text
fixtures
tests
sample config
P9.2 scoped integration evidence
```

---

# 68. Multi-market regression

Must verify existing paths:

```text
Generic T0
CN A-share
Tushare
MiniQMT
```

especially after changes to:

```text
identity
sequence
historical cache
connection state
market-reference payload
```

Do not make existing providers conform to Binance mechanics.

---

# 69. External Binance contract tests

Optional external tests may verify:

```text
REST:
- ping
- klines
- raw historical trade path
- reference price

WS:
- trade
- closed kline
- market reference
```

Mark:

```text
external
requires_network
requires_binance_public
```

Do not use live Binance availability as the sole correctness proof.

Offline fixtures are canonical for deterministic implementation correctness.

---

# 70. Quality-system integration

Use current repository quality authority.

Do not reintroduce retired Final-SHA Certification.

Do not create second handwritten lists for:

```text
pytest targets
mypy targets
CI gates
```

Add new code/tests to the existing canonical discovery surfaces.

---

# 71. Suggested affected file surface

Core:

```text
src/onlyalpha/data/identity.py
src/onlyalpha/data/identifiers.py
src/onlyalpha/data/enums.py
src/onlyalpha/data/models.py
src/onlyalpha/data/processor.py
src/onlyalpha/data/historical/*
src/onlyalpha/cache/historical/*
src/onlyalpha/domain/market.py
src/onlyalpha/market/realtime_reference.py
```

Provider:

```text
packages/provider/onlyalpha-plugin-binance/
  pyproject.toml
  src/onlyalpha_plugin_binance/descriptor.py
  src/onlyalpha_plugin_binance/spot/data_source/*
  tests/*
```

Modify other files only when directly required.

---

# 72. Do not over-generalize

Forbidden unless current architecture proves necessity:

```text
provider DSL
distributed stream framework
generic event sourcing
new persistence layer
new scheduler
new async runtime abstraction
universal record registry
```

Core additions should be limited to reusable concepts:

```text
stable fact identity
sequence scope
sequence semantics
typed historical families
market-neutral reference fact
recovery state semantics
```

---

# 73. Verification order

First run targeted tests:

```text
1. identity
2. sequence
3. processor/dedup
4. Bar cache
5. Trade cache
6. Binance normalizers
7. Historical Bar
8. Historical Trade
9. WS fixtures
10. continuity/recovery
11. realtime reference
12. DataSource factory/resource
13. architecture boundary
14. MiniQMT/Tushare regressions
15. static/mypy
```

Only then run broader canonical lanes.

---

# 74. Required canonical verification

Before closure, run all affected mandatory current quality gates.

At minimum expect:

```text
static
architecture
core-full
relevant provider/data-source lanes
MiniQMT regression
build
quality-gate
CodeQL
```

Use `quality-policy.toml` and current workflow contracts as authority.

---

# 75. P9.2 report

Create the canonical report:

```text
docs/reports/p9_2_binance_spot_historical_realtime_data_source.md
```

Record:

```text
task base SHA
final HEAD
scope
Core changes
plugin changes
identity model
sequence model
historical cache model
Historical Bar evidence
Historical Trade evidence
Realtime Bar evidence
Realtime Trade evidence
Market Reference evidence
recovery evidence
multi-market regression evidence
CI evidence
deferred P9.3/P9.4 scope
```

---

# 76. Project-state transition

Only after required P9.2 verification is green:

Use the canonical project-state script.

Target:

```text
last_verified_increment = "P9.2"
last_verified_name = "Binance Spot Historical & Realtime DataSource"
last_verified_state = "TASK COMPLETE / VERIFIED"

next_authorized_increment = "P9.3"
next_authorized_name = "Production Data Foundation / Durable Market Data Platform"
next_authorized_state = "IMPLEMENTATION READY"
```

Do not hand-edit README/roadmap projections.

---

# 77. Definition of Done — Architecture

```text
provider-neutral Core                       PASS
Binance DTO isolation                       PASS
existing DataSource SPI                     PASS
no second Engine/Runtime/DataManager         PASS
no Binance branching in Core consumers      PASS
```

---

# 78. Definition of Done — Identity

```text
one venue fact → one canonical identity      PASS
REST/WS/recovery convergence                 PASS
identity != sequence                         PASS
multi-symbol isolation                       PASS
```

---

# 79. Definition of Done — Historical

```text
BTCUSDT 1m closed Bar                        PASS
ETHUSDT 1m closed Bar                        PASS
BTCUSDT raw Trade                            PASS
ETHUSDT raw Trade                            PASS
exact [start,end)                            PASS
local-first cache                            PASS
exact missing ranges                         PASS
strict validation                            PASS
coverage proof                               PASS
DataVersion cache isolation                  PASS
```

---

# 80. Definition of Done — Realtime

```text
closed Bar                                   PASS
raw Trade                                    PASS
Market Reference                             PASS
duplicate detection                          PASS
out-of-order detection                       PASS
gap detection                                PASS
reconnect                                    PASS
historical recovery                          PASS
bounded buffering                            PASS
READY only after proof                       PASS
```

---

# 81. Definition of Done — Realtime Reference

```text
P9.1 dynamic requirement consumed            PASS
venue reference path                         PASS
trade-window fallback                        PASS
coverage proof for fallback                  PASS
incomplete evidence fails closed             PASS
```

---

# 82. Definition of Done — Multi-market compatibility

```text
MiniQMT                                      PASS
Tushare                                      PASS
Generic/CN market paths                      PASS
Core remains market-neutral                  PASS
```

---

# 83. Definition of Done — Verification

```text
targeted tests                               PASS
identity/sequence                            PASS
historical cache                             PASS
Binance offline                              PASS
continuity/recovery                          PASS
reference authority                          PASS
multi-market regression                      PASS
static                                       PASS
architecture                                 PASS
core-full                                    PASS
build                                        PASS
Layered Quality                              PASS
CodeQL                                       PASS
```

---

# 84. Stop condition

Once:

```text
P9.2 = TASK COMPLETE / VERIFIED
P9.3 = IMPLEMENTATION READY
```

STOP.

Do not continue into:

```text
database
WAL
Broker
private Binance API
LIVE
```

Do not start another open-ended P9.2 audit.

---

# 85. Required final Codex output

Return:

```text
P9.2 IMPLEMENTATION RESULT
==========================

Base SHA:
Final HEAD:

Core:
- Fact identity:
- Sequence semantics:
- Historical cache:
- Market reference:

Binance DataSource:
- Historical Bar:
- Historical Trade:
- Realtime Bar:
- Realtime Trade:
- Market Reference:
- Recovery:

Architecture:
- Provider isolation:
- DataSource SPI:
- Multi-market regression:

Verification:
- targeted:
- static:
- architecture:
- core-full:
- build:
- quality-gate:
- CodeQL:

Project State:
- last_verified_increment:
- next_authorized_increment:

Remaining blockers:
- NONE / exact blockers only

VERDICT:
P9.2 VERIFIED / NOT VERIFIED
```

Never use vague verdicts such as:

```text
basically done
looks ready
probably okay
```

---

# 86. Final engineering target

After P9.2:

```text
              Venue-specific protocols
           ┌──────────┼──────────┐
           ▼          ▼          ▼
        Binance      QMT        CTP
           │          │          │
           └──── Provider Adapters ────┐
                                       ▼
                         Canonical Market Facts
                         ├─ OnlyBar
                         ├─ OnlyTradeTick
                         └─ Market Reference
                                       │
                         Stable Fact Identity
                                       │
                         Explicit Continuity
                                       │
                         Historical / Realtime
                                       │
                              OnlyAlpha Core
```

The permanent success criterion is:

> **After P9.2, adding QMT or CTP market data should primarily require a new provider adapter and provider-specific recovery contract—not another redesign of OnlyAlpha's Core market-data model.**
