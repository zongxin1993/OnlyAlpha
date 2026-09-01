# OnlyAlpha P9.T — Realtime Trade Reference Foundation
## Codex Implementation Task Prompt

> **Repository:** `zongxin1993/OnlyAlpha`  
> **Task type:** High-risk bounded implementation task  
> **Primary objective:** Promote existing canonical `Trade Tick` from “collectable / durable market fact” to a **Runtime-level realtime market reference input** for Execution / Risk / Valuation, while keeping Strategy semantics strictly **1 Minute Closed Bar only**.  
> **Do not turn this task into Tick Strategy support. Do not reopen unrelated architecture.**

---

# 0. Mandatory execution order

Before changing any code, follow repository governance exactly.

You **MUST** read and understand, in this order:

1. `PROJECT_CONSTITUTION.md`
2. Relevant architecture / contracts, at minimum:
   - `docs/market_data_source.md`
   - `docs/p9_binance_spot_golden_vertical_execution_plan.md`
   - `docs/p9_production_trading_vertical_architecture.md`
   - `docs/strategy_product_architecture.md`
3. Relevant accepted ADRs that directly govern:
   - Strategy Revision authority
   - Calculation / Strategy execution contract
   - Market-data durability / revision / recovery
   - Runtime recovery / deterministic state
   - Order Intent durability / execution authority
4. `AGENTS.md`
5. Current source code and directly relevant tests
6. Only after the above, freeze the Task Contract below and implement.

If this task conflicts with `PROJECT_CONSTITUTION.md`, do **not** reinterpret or weaken the Constitution.

Report:

```text
PLAN_CONFLICT
```

and stop implementation.

For a legal implementation task:

```text
Constitution Impact = NO
```

---

# 1. First-principles problem statement

The first production phase of OnlyAlpha has one explicit strategy decision granularity:

```text
1 Minute Closed Bar
```

This is the formal Strategy decision input.

The intended architecture is:

```text
1m Closed Bar
    ↓
Strategy Revision
    ↓
Strategy Decision
    ↓
Portfolio / Execution / Risk
    ↓
Order Intent
    ↓
Broker
```

`Trade Tick` and later `Quote/L1` are **not Strategy Decision Triggers** in this phase.

Their role is:

```text
Trade Tick / Quote / Market Reference
        ↓
Realtime Market State
        ↓
Execution / Risk / Valuation
```

Therefore:

```text
Strategy Decision Input
!=
Execution Market Reference
```

A Tick may affect:

- execution reference price;
- price protection;
- order admissibility;
- realtime risk validation;
- valuation;
- execution-quality evidence;

but it **MUST NOT** affect:

- Strategy Revision identity;
- Strategy fingerprint;
- whether the Strategy emitted ENTRY / EXIT;
- Strategy Calculation Graph semantics;
- Strategy callback frequency;
- Cluster decision dispatch frequency.

The central invariant is:

> For the exact same ordered 1-minute closed Bars, adding any number of valid Trade Tick events must not change Strategy Decisions.

---

# 2. Current repository truth that this task must preserve

Before implementing, verify these facts from current source rather than assuming file paths blindly.

The current repository already has important Tick foundations.

Expected existing capabilities include, or are conceptually equivalent to:

```text
OnlyTradeTick
OnlyTradeTickUpdate
OnlyMarketDataType.TRADE
historical tick/trade DataSource capability
live tick/trade DataSource capability
Binance Spot REST trade normalization
Binance Spot WebSocket trade normalization
Trade sequence / continuity support
Raw Provider Evidence
Canonical Market Fact
append-only market-data WAL
typed ClickHouse market_trade storage
PostgreSQL market-data revision / coverage / manifest
```

Do not rebuild these if they already exist and are correct.

Also verify the current key limitation:

```text
OnlyMarketDataProcessor
→ validates / deduplicates / sequence-checks non-Bar market data
→ but non-Bar payload currently terminates without becoming useful Trading Runtime state
```

The task is primarily a **controlled promotion of existing Trade facts into Runtime reference state**, plus production-grade Tick durability/drain where current implementation is insufficient for sustained Tick volume.

---

# 3. Frozen Task Contract

## 3.1 Goal

Implement a provider-neutral **Realtime Trade Reference Foundation** such that canonical Trade Tick facts:

```text
Provider
→ canonical normalization
→ durable WAL ownership
→ MarketData Queue
→ MarketDataProcessor
→ validated trusted Realtime Market State
→ immutable Market Snapshot
→ Execution / Risk / Valuation reference
```

while Strategy continues to execute only from:

```text
1 Minute Closed Bar
```

The same Trade facts must also continue to flow through the durable market-data path:

```text
WAL
→ finite sealed segments
→ asynchronous / bounded drain
→ ClickHouse
→ verification
→ PostgreSQL revision / manifest
```

No silent data loss is permitted.

---

## 3.2 Modification Scope

The expected modification scope is limited to the nearest stable boundaries necessary for this behavior.

Likely affected areas:

```text
MarketDataProcessor
Realtime market-state projection
Streaming Runtime market-data composition
Runtime market-data subscription planning
Market-data durable recorder / segment lifecycle
normal-operation durable drain orchestration
market-data health / backlog exposure
Execution market-reference read boundary
Risk market-reference read boundary, only where required
Order / execution evidence linkage, only where required for traceability
directly affected tests
directly affected architecture documentation
```

Do not assume exact filenames before reading current source.

---

## 3.3 Expected Impact Scope

This is a high-risk task because failure could affect:

```text
Market Data Authority
Persistence integrity
Recovery
Runtime determinism
Execution correctness
Risk fail-closed behavior
Traceability
Public/internal runtime contracts
```

Impact scope may expand only when a real dependency proves the original scope incomplete.

Expand only to the **nearest stable engineering boundary**.

Do not use this task as an excuse for repository-wide refactoring or a new architecture audit.

---

## 3.4 Required Behavior

The implementation MUST provide all of the following.

### A. Strategy remains BAR-only

The following semantics must remain unchanged:

```text
Strategy Revision market input
→ BAR

Observation admission
→ FINAL_ONLY

minimum formal Strategy decision granularity
→ 1 Minute Closed Bar
```

Do **not** add Tick Strategy support.

Do **not** create:

```text
Strategy.on_tick()
Strategy.on_trade()
Cluster.on_tick()
Cluster.on_trade()
TickStrategyDispatcher
TickCalculationGraph
Tick Strategy Revision schema
```

unless existing architecture unexpectedly proves such a change is unavoidable for the required behavior. If so, stop and report a design conflict instead of silently expanding scope.

Existing Strategy fingerprints MUST remain unchanged.

---

### B. Trade becomes a first-class Runtime reference fact

A valid canonical Trade Tick must no longer be semantically treated as “ignored” merely because it does not enter Strategy dispatch.

After normal validation:

```text
scope validation
source validation
instrument validation
lookahead validation
deduplication
sequence assessment
gap assessment
quality assessment
```

a valid Trade Tick should update a Runtime-owned realtime market-state projection.

Conceptually:

```text
TRADE
→ validated
→ trusted
→ realtime state updated
→ processing status = APPLIED
→ no Strategy dispatch
```

`APPLIED` must not imply Strategy execution.

For Trade:

```text
pipeline_result = None
strategy dispatches = empty
```

or the exact equivalent supported by the current result model.

Do not route Trade through the Bar Pipeline.

---

### C. Add one Runtime-wide realtime market-state authority

Implement one provider-neutral Runtime-owned projection concept equivalent to:

```text
OnlyRealtimeMarketStateStore
```

The exact name may differ if an existing abstraction already owns this responsibility.

The projection must be:

```text
Runtime-wide
provider-neutral
thread-safe where required by current Runtime model
deterministic
read-only to consumers
derived only from admitted canonical market facts
rebuildable
not a second durable Market Fact authority
```

It must **not** be Cluster-owned.

Do not repurpose a Cluster/Bar observation store if doing so would conflate:

```text
Strategy observation state
```

with:

```text
Runtime current market reference state
```

The state should support, for this task, at least:

```text
latest trusted Trade per required Runtime scope / instrument
```

Keep extension clean for future:

```text
Quote / L1
Reference Price
```

but do not implement speculative families in this task.

---

### D. Preserve exact market-fact evidence

The Runtime reference projection must not collapse a Trade into only:

```text
price = 100.03
```

A reference view / snapshot must retain enough canonical evidence to answer:

> Which exact market fact caused this reference value?

At minimum, where current contracts permit, preserve or bind:

```text
runtime_id
source_id
instrument_id
data_version
market-data update identity
source/provider sequence
event timestamp
observed/init timestamp
quality state
canonical Trade Tick
```

The exact authoritative identity must reuse existing market-data identity mechanisms.

Do not create a parallel Trade identity.

---

### E. Deterministic immutable Market Snapshot capture

Execution / Risk / Valuation must not independently read mutable “latest” state at different times during one logical order-planning operation.

Provide one explicit capture boundary concept equivalent to:

```text
Realtime Market State
        ↓
capture()
        ↓
Immutable Market Snapshot
```

For one logical planning cycle:

```text
Strategy Decision
+ one immutable Market Snapshot
+ Execution Profile
+ Risk policy
→ one deterministic planning result
```

If newer Trade Ticks arrive after capture, they affect future planning, not the already-started planning cycle.

Do not allow:

```text
Execution reads Tick T1
Risk reads Tick T2
Portfolio reads Tick T3
```

for one order-planning transaction unless the current architecture already has a stronger equivalent consistency contract.

---

### F. Strategy non-interference is a hard invariant

Trade Tick must never become a hidden Strategy admission condition.

Forbidden example:

```text
Strategy says ENTRY = true

if latest_trade > threshold:
    convert ENTRY to false
```

Correct separation:

```text
Strategy Decision
ENTRY = true

Execution / Risk
may refuse external risk increase
because reference is stale / unsafe / violates price policy

Strategy Decision remains ENTRY = true
```

This causal distinction must remain visible in evidence.

---

### G. Execution reference pricing must be explicit and deterministic

Do not scatter code such as:

```python
price = latest_tick.price + tick_size
```

through Broker, Strategy, or unrelated Managers.

Use or introduce one narrow Execution reference/pricing authority, conceptually equivalent to:

```text
Execution Price Resolver
```

Inputs should be explicit:

```text
Order / execution proposal
Execution Profile / versioned policy
Immutable Realtime Market Snapshot
Market Product / canonical market-rule inputs
```

Output should be a structured deterministic decision containing enough evidence to explain the result.

Conceptually:

```text
reference kind
reference market-data identity
reference price
price offset / policy parameters
relevant market-rule identity
resolved order price
policy identity / fingerprint
```

Do not hardcode Binance tick size or provider rules in Core.

Provider-changing rules stay behind Market Product / Plugin boundaries.

---

### H. Execution Profile owns “how to execute”

Reference-price choice belongs to Execution semantics, not Strategy identity.

For example, future policies may include:

```text
LAST_TRADE
BEST_BID
BEST_ASK
MID
```

This task only needs the Trade-based form required by current implementation.

The policy must be explicit and versioned/fingerprintable according to the current Execution Profile architecture.

Changing execution-price policy must not create a new Strategy Revision.

---

### I. Risk consumes the same immutable Market Snapshot

Where Risk requires a market reference for price protection or risk-increasing admission, it must use the same captured immutable snapshot used by the relevant execution-planning operation.

Risk may return explicit denial such as:

```text
REFERENCE_UNAVAILABLE
REFERENCE_STALE
REFERENCE_GAP_UNRESOLVED
REFERENCE_SOURCE_MISMATCH
REFERENCE_QUALITY_INVALID
ORDER_PRICE_DEVIATION_EXCEEDED
```

Use current error/failure vocabulary where already defined; do not create duplicates unnecessarily.

A Risk denial must not mutate the original Strategy Decision.

---

### J. Fail closed on unsafe market reference

Risk-increasing external execution may proceed only if all required reference conditions are proven.

Conceptually:

```text
source ready
AND required reference exists
AND source/instrument scope matches
AND quality is admitted
AND continuity is resolved
AND reference is fresh enough
```

If any required condition is unknown:

```text
no risk-increasing dispatch
```

The Runtime must stay alive for:

```text
observation
fills
cancellation
persistence
reconciliation
recovery
risk reduction
```

Do not kill the process merely because the reference is unavailable.

Do not silently fallback to old Bar close unless the exact Execution Policy explicitly declares such a fallback and the architecture permits it.

For this task, prefer:

```text
fallback = NONE
```

unless existing frozen contracts already define another safe behavior.

---

### K. Realtime state is not durable authority

Do not create a database table such as:

```text
current_market_state
```

and treat it as current operational truth.

The durable truth remains:

```text
Raw Provider Evidence
+
Canonical Market Facts
+
verified durable market-data records/revisions
```

Realtime market state is a rebuildable operational projection.

On restart:

```text
RealtimeMarketState = NOT_READY / EMPTY
```

until current market continuity / baseline has been re-established.

Do not load the last historical Tick from ClickHouse and immediately consider current market reference READY.

---

### L. Realtime execution must not query ClickHouse for “latest price”

Forbidden runtime integration pattern:

```text
Execution
→ SELECT latest trade FROM ClickHouse
```

Correct operational path:

```text
Provider
→ MarketData Queue
→ Processor
→ Realtime Market State
→ immutable snapshot
→ Execution / Risk / Valuation
```

ClickHouse remains:

```text
durability
historical query
revision
replay
research
audit
```

Database is persistence, not an implicit realtime integration API.

---

### M. Runtime subscription requirements must be compositional

Strategy requirements and Runtime reference requirements are different Authorities.

Implement or extend one explicit requirement-composition mechanism:

```text
Strategy Market Requirement
+
Execution Reference Requirement
+
Risk Reference Requirement
=
DataSource Subscription Requirement
```

For the first phase:

```text
Strategy:
1m BAR

Execution / Risk reference:
TRADE

Runtime subscription:
{BAR, TRADE}

Strategy dispatch:
BAR only
```

Do not add Trade to Strategy fingerprint merely because Runtime subscribes to Trade.

---

### N. Production Tick durability must use existing WAL authority

Preserve the existing durability principle:

```text
market fact accepted
only after WAL frame is durable
```

Do not weaken:

```text
append
→ fsync
→ durable ownership
```

for performance convenience.

Do not synchronously insert into ClickHouse from provider callbacks.

---

### O. Replace one-observation-per-segment behavior with bounded rolling segments if current source still does that

If the current durable recorder still performs:

```text
begin_segment
record one observation
seal
```

for each callback, change the recorder lifecycle while preserving WAL durability semantics.

Expected shape:

```text
open finite segment
↓
append Trade 1 + fsync
append Trade 2 + fsync
append Trade 3 + fsync
...
↓
rotation boundary
↓
seal
↓
open next segment
```

Rotation must be explicit and bounded using the minimum sufficient policies supported by current architecture, for example:

```text
max records
OR max bytes
OR max duration
OR scope change
OR clean shutdown
```

Do not add speculative complexity.

If one-open-segment WAL remains sufficient, do not redesign it into multi-writer/multi-open WAL without measured evidence.

Scope changes may seal and rotate.

Preserve existing segment identity / hash / crash-recovery semantics.

---

### P. Add or complete normal-operation durable drain

If normal operation currently leaves sealed WAL data without a production drain path, implement the minimum correct bounded drain mechanism:

```text
sealed WAL segment
↓
bounded drain worker/service
↓
typed ClickHouse fact write
↓
exact verification
↓
PostgreSQL manifest / revision commit
↓
GC eligibility
```

Reuse the existing recovery coordinator / ports where possible.

Do not create a second recovery/revision implementation.

Normal drain and crash recovery must converge on the same durable semantics.

---

### Q. Database outage semantics

If ClickHouse or PostgreSQL is unavailable:

```text
provider callback
→ may continue only while WAL capacity and safety permit
```

The system must expose explicit degraded persistence health / backlog.

Forbidden:

```text
silent Tick drop
pretend DB commit succeeded
overwrite durable history
```

When storage recovers:

```text
same sealed segments
→ idempotent drain
→ exact verification
→ deterministic manifest/revision convergence
```

WAL capacity exhaustion must be explicit and fail closed according to current recording health semantics.

---

### R. Traceability into Order Intent

If an Order price or Risk decision depends materially on a Trade reference, durable execution evidence must allow reconstruction of:

```text
Strategy Decision
↓
Execution policy/profile
↓
immutable Market Snapshot
↓
exact market-data reference identity
↓
reference Trade value
↓
resolved execution price / risk decision
↓
Order Intent
```

Do not merely persist the final `order.price` if doing so destroys causal explainability.

Choose the smallest existing authoritative execution-evidence extension:

- extend an existing versioned Order Intent evidence contract, or
- add one narrow typed pricing/reference evidence fact,

but never create two parallel official pricing authorities.

Any persistent-format change is high-risk and must include compatibility judgment.

---

# 4. Explicit Out of Scope

The following are **NOT** part of this task.

Do not implement them.

```text
Tick-driven Strategy
Tick-driven Calculation Graph
Tick Strategy Revision
Strategy Revision schema migration for Tick input
Cluster.on_tick / Strategy.on_tick
Tick-specific Strategy Dispatcher

Quote / L1 implementation
unless required only as an interface extension with no production behavior

L2 order book
Depth snapshot/delta
queue position
market making
HFT architecture
SBE optimization
lock-free optimization without measured need

Trade Tick → Bar aggregation
Tick Bar
Volume Bar
Value/Notional Bar

Binance Futures
QMT
CTP

Backtest Tick execution simulation
historical Tick execution model

new database vendor
Kafka
Redis
distributed scheduler
Kubernetes
microservice split

Broker-specific Tick logic
Binance-specific market rules in Core

repository-wide cleanup
unrelated refactor
new generic framework merely for future flexibility
```

---

# 5. Target architecture

The intended end state is conceptually:

```text
                    External Market
                          │
                          ▼
                      Provider
                          │
                          ▼
                  Canonical Market Fact
                          │
                ┌─────────┴──────────┐
                │                    │
                ▼                    ▼
          Durable WAL          MarketData Queue
                │                    │
                ▼                    ▼
          Rolling Segment       Processor
                │                    │
                ▼          ┌─────────┴──────────┐
          Bounded DB Drain │                    │
                │          ▼                    ▼
                │         BAR                 TRADE
                │          │                    │
                │          ▼                    ▼
                │     Bar Pipeline       Realtime State
                │          │                    │
                │          ▼                    │
                │      Strategy                 │
                │          │                    │
                │      Decision                 │
                │          │                    │
                │          └──────────┬─────────┘
                │                     ▼
                │             Immutable Market Snapshot
                │                     │
                │              ┌──────┼──────┐
                │              ▼      ▼      ▼
                │          Execution Risk Valuation
                │              │
                │              ▼
                │          Order Intent
                │              │
                │              ▼
                │            Broker
                │
                ▼
           ClickHouse
                │
             verify
                │
                ▼
           PostgreSQL
          Revision / Manifest
```

No second Trading Kernel.

No second Market Fact authority.

No database-mediated realtime trading path.

---

# 6. Implementation sequence

Implement in bounded order.

## Phase 1 — Realtime Trade State Foundation

Inspect current source and implement the minimum necessary changes for:

```text
Trade Tick
→ Processor validation
→ trusted APPLIED state
→ Realtime Market State projection
```

Requirements:

- duplicate Trade does not mutate state;
- stale/out-of-order Trade does not mutate trusted state;
- unresolved gap does not mutate trusted state;
- valid Trade advances state deterministically;
- Bar path behavior is unchanged;
- Trade does not reach Strategy dispatcher.

Add focused tests immediately.

---

## Phase 2 — Runtime requirement composition

Extend Runtime composition so the system can express:

```text
Strategy requires BAR
Execution/Risk requires TRADE
```

and subscribe to the union without changing Strategy identity.

Do not duplicate DataSource subscriptions or introduce a second market-data queue.

Add tests proving:

```text
Runtime receives BAR + TRADE
Strategy receives BAR only
```

---

## Phase 3 — Immutable Market Snapshot boundary

Implement one deterministic capture abstraction over trusted realtime market state.

Requirements:

- immutable value;
- exact source/fact identity;
- deterministic fingerprint if current canonical identity rules require one;
- one logical planning operation uses one captured snapshot;
- later Trade arrival cannot mutate an already captured snapshot.

Add deterministic tests.

---

## Phase 4 — Durable rolling Tick path

Inspect current recorder / WAL / segment behavior.

If one event is currently sealed into one segment, implement bounded rolling segments without weakening per-record durability.

Do not redesign WAL beyond what the requirement proves necessary.

Add deterministic crash-boundary tests using barriers/fake clocks, not `sleep()`.

---

## Phase 5 — Normal-operation DB drain

Wire the existing fact store / catalog / revision / recovery authority into a normal production drain lifecycle.

Reuse existing durable ports and recovery semantics.

Prove:

```text
WAL durable
→ ClickHouse
→ exact verify
→ PostgreSQL revision
```

and:

```text
crash / restart
→ same result
```

---

## Phase 6 — Execution / Risk reference integration

Introduce or adapt the narrowest correct Market Snapshot read boundary for execution planning.

Implement explicit Trade-based execution reference policy only to the degree required by current product path.

Ensure:

```text
Strategy Decision is unchanged
```

when Execution or Risk rejects for reference reasons.

Tie material reference evidence into the existing durable execution causal chain.

Do not redesign Broker.

---

## Phase 7 — Architecture documentation correction

Update only directly affected long-lived architecture documentation.

At minimum inspect:

```text
docs/market_data_source.md
```

If it still claims capabilities are unimplemented when current source implements them, correct it.

Document the two distinct lanes:

```text
Decision Lane
BAR
→ Pipeline
→ Strategy

Reference Lane
TRADE
→ Realtime Market State
→ Execution / Risk / Valuation
```

Do not add task-completion reports, status files, certification manifests, or historical prompts to the repository.

---

# 7. Required invariants and tests

The following tests are mandatory where current architecture makes them applicable.

## 7.1 Strategy Non-Interference — highest-priority regression test

Construct two deterministic runs with the exact same ordered 1-minute closed Bars.

Run A:

```text
BAR only
```

Run B:

```text
same BARs
+
many valid Trade Tick events interleaved
```

Assert exact Strategy semantic equivalence:

```text
Strategy fingerprint
decision count
decision time
instrument
eligibility
entry
exit
observation identity/fingerprint where Bar-derived
```

must be identical.

If adding Tick changes Strategy output, the implementation is wrong.

---

## 7.2 Valid Trade projection

Given:

```text
Trade 100
Trade 101
Trade 102
```

assert:

```text
trusted latest = 102
```

and all updates are admitted through the one Processor boundary.

---

## 7.3 Duplicate Trade

Given:

```text
100
101
101 duplicate
```

assert:

```text
duplicate does not mutate trusted state
```

and duplicate status/evidence is explicit.

---

## 7.4 Out-of-order / stale Trade

Given an authoritative ordering where:

```text
102 accepted
101 arrives later
```

assert:

```text
101 does not replace trusted 102
```

and status is explicit.

---

## 7.5 Gap Fail-Closed

Given:

```text
100
101
105
```

when the sequence contract proves 102–104 are missing:

```text
105 must not become trusted current reference
```

until recovery contract is satisfied.

After deterministic recovery:

```text
102
103
104
105
```

trusted state may advance according to the canonical continuity rules.

Do not invent sequence guarantees for providers/streams that do not have them.

---

## 7.6 Snapshot Isolation

Capture:

```text
S1 at Trade 100
```

then process:

```text
101
102
103
```

Assert all consumers using S1 still observe exactly Trade 100.

---

## 7.7 Reference freshness / readiness fail-closed

With:

```text
missing reference
stale reference
unresolved gap
invalid quality
wrong instrument/source
```

assert:

```text
risk-increasing execution is denied
```

while Runtime remains operational for safety paths.

Use fake clock / deterministic timestamps.

---

## 7.8 Restart safety

After restart:

```text
old historical/latest persisted Trade
```

must not automatically make current realtime reference READY.

Assert current reference remains unavailable until fresh continuity/baseline is proven.

---

## 7.9 WAL durability

Prove a canonical Trade is not considered durably accepted before the current WAL durability boundary.

Do not weaken existing fsync contract.

---

## 7.10 Rolling segment correctness

Prove:

```text
multiple same-scope Trade records
→ one finite segment
```

under configured bounded rotation.

Also prove scope changes / shutdown rotate deterministically.

---

## 7.11 Crash boundaries

Use deterministic barriers/fault injection for at least the real affected boundaries equivalent to:

```text
after frame write before fsync
after fsync before seal
during seal metadata transition
after seal before ClickHouse
after ClickHouse before verification/catalog
after verification/catalog before GC
```

Reuse existing crash-boundary infrastructure where possible.

No `sleep()` as a correctness proof.

---

## 7.12 Database outage

With ClickHouse or PostgreSQL unavailable:

```text
WAL retains authoritative durable backlog
no silent loss
health becomes explicitly degraded
```

When restored:

```text
drain converges idempotently
no duplicate canonical fact
same verified revision semantics
```

---

## 7.13 Traceability

For an execution price decision that uses Trade:

prove the durable chain can resolve:

```text
Order / Order Intent
→ execution reference decision
→ immutable Market Snapshot
→ exact Trade market-data identity
→ canonical Trade fact
```

Do not accept logs-only proof.

---

## 7.14 Backward compatibility

Where persistent/public contracts are changed, add exact compatibility tests.

At minimum verify:

- existing Strategy Revision fingerprints are unchanged;
- existing Bar Strategy behavior is unchanged;
- existing Bar-only Runtime tests still pass;
- existing market-data durable formats remain readable or migrate deterministically;
- checkpoint/recovery compatibility is explicitly judged if touched.

Do not silently introduce a breaking change.

---

# 8. Determinism requirements

Correctness tests MUST be:

```text
deterministic
hermetic
offline-first
```

Prefer:

```text
recorded provider payload
fake clock
contract fake
local ephemeral DB
fault injection
deterministic barrier
```

Forbidden:

```text
sleep() timing guesses
retry-until-green
random execution order
public internet dependency for ordinary acceptance
live Binance account dependency unless strictly unavoidable
weakened assertions
skip/xfail of current real failures
exception swallowing
```

Real Binance / real DB / Docker tests are required only if they are the only valid proof of a Required Behavior.

Do not use a mock to claim proof of behavior that inherently requires the real integration layer.

---

# 9. Performance requirement

This is **not an HFT task**.

Performance objective is:

```text
no silent loss
bounded memory
bounded WAL
bounded queues
no synchronous ClickHouse dependency in provider callback
sustained realistic Trade Tick ingestion
recoverable backpressure
deterministic behavior
```

Do not introduce:

```text
lock-free structures
SBE
shared-memory optimization
custom networking
busy polling
CPU pinning
microsecond trading architecture
```

without measured evidence that the Required Behavior cannot otherwise be met.

Add a focused benchmark or throughput regression only if the current test framework has a stable home for it.

Performance evidence must not replace correctness evidence.

---

# 10. Architecture boundaries

## Core may own

Universal concepts such as:

```text
canonical Trade fact
realtime reference state semantics
immutable market snapshot
reference freshness/admissibility semantics
execution reference decision semantics
deterministic projection
fail-closed state transitions
traceability identity
```

## Plugin must own

Anything that changes because of provider/venue rules:

```text
Binance JSON
WebSocket stream names
REST endpoints
venue trade IDs parsing
provider reconnect mechanics
provider-specific sequence guarantees
price/quantity rule extraction
Binance-specific error semantics
```

No:

```python
if provider == "BINANCE":
```

in canonical Core trading semantics.

---

# 11. Authority table

Preserve these Authorities:

```text
Strategy semantics
→ immutable Strategy Revision

Strategy identity
→ Strategy fingerprint

External market observation
→ provider evidence

Canonical normalized market fact
→ OnlyAlpha canonical Market Fact

Current realtime reference
→ Runtime deterministic projection of admitted canonical facts

Historical / durable market-data selection
→ verified Market Data Revision / Manifest

Execution policy
→ Execution Profile / canonical execution policy

Order Intent
→ durable Trading Runtime evidence

External execution fact
→ venue

Risk decision
→ Risk authority

Database
→ persistence, NOT realtime trading integration authority
```

Do not create parallel truths.

---

# 12. Compatibility judgment

This task touches high-risk boundaries.

For every changed public or persistent contract, explicitly document in implementation notes:

```text
Backward compatible?
Forward compatible?
Migration required?
Old readers?
Old writers?
Checkpoint impact?
Persistent data impact?
Affected consumers?
Failure behavior?
Retry/restart behavior?
```

Do not create a migration unless the current persisted contract truly requires one.

Prefer no schema migration when existing `market_trade` / durable canonical fact storage already satisfies the requirement.

---

# 13. Validation plan

Follow `AGENTS.md` Impact-Aware validation.

At minimum execute:

```text
direct targeted tests
affected Ruff check
affected Ruff format --check
affected mypy
nearest affected canonical lane
architecture / Constitution consistency check
```

Because this is high-risk, also execute only the directly relevant:

```text
market-data durability/recovery tests
runtime streaming/recovery tests
execution/reference tests
risk fail-closed tests
persistent compatibility tests if needed
```

Do not automatically run the entire repository test matrix unless real Impact Scope proves it necessary.

Do not modify:

```text
PROJECT_CONSTITUTION.md
quality-policy.toml
scripts/verify.py
scripts/test_suite.py
test discovery
coverage threshold
CI conditions
lint/mypy ignores
```

to make this task pass.

---

# 14. Bounded Independent Review

After implementation and primary validation, perform exactly one focused Independent Review.

Review scope:

```text
Modification Scope
+
real Impact Scope
+
directly relevant Constitution / Architecture invariants
```

Review questions:

1. Did Tick accidentally become a Strategy Decision input?
2. Did Strategy fingerprint or Bar semantics change?
3. Is there exactly one realtime reference projection Authority?
4. Can Execution/Risk observe different mutable market states inside one planning cycle?
5. Can stale/gapped/unknown reference permit new risk?
6. Does restart ever treat historical last Tick as current READY state?
7. Does any realtime execution path query ClickHouse for “latest”?
8. Can provider callback silently lose Tick because DB is down?
9. Was WAL durability weakened for performance?
10. Is rolling-segment recovery deterministic?
11. Was a second persistence/revision authority created?
12. Are provider-specific semantics leaking into Core?
13. Can a material order price be traced to exact reference fact and policy?
14. Were unrelated components changed without a proven dependency?

If the review finds Critical/High issues inside scope, fix them and rerun only affected validation.

Do not restart a full repository audit.

---

# 15. Stop Condition

This task is finished when and only when:

```text
Required Behavior implemented
AND
Acceptance Tests PASS
AND
Baseline Validation PASS
AND
real Impact Scope validation PASS
AND
Constitution consistency PASS
AND
bounded Independent Review completed
AND
Critical = 0
AND
High = 0
```

Then:

```text
STOP
```

Do not continue because:

```text
“could refactor more”
“could generalize more”
“future Quote would be cleaner”
“Futures will need this later”
“there are Medium/Low issues”
“coverage could be higher”
“another audit may find something”
```

Record remaining Medium/Low findings only if useful; do not expand the task.

---

# 16. Expected implementation result

At task completion, the system should prove this exact separation:

```text
                      1m CLOSED BAR
                            │
                            ▼
                    Strategy Revision
                            │
                            ▼
                    Strategy Decision
                            │
                            │
                            ├─────────────────────────────┐
                            │                             │
                            │                             ▼
                            │                    Immutable Market Snapshot
                            │                             ▲
                            │                             │
                            │                    Realtime Trade State
                            │                             ▲
                            │                             │
                            │                     Canonical Trade Tick
                            │
                            └──────────────┬──────────────┘
                                           ▼
                                Execution / Risk
                                           │
                                           ▼
                                      Order Intent
                                           │
                                           ▼
                                         Broker
```

And durable data must independently prove:

```text
Provider
→ Raw + Canonical Trade evidence
→ WAL durable
→ finite rolling segment
→ bounded asynchronous drain
→ ClickHouse market_trade
→ exact verification
→ PostgreSQL Market Data Revision / Manifest
```

The core product invariant is:

> **OnlyAlpha gains Tick-level realtime market awareness without becoming a Tick-driven Strategy engine.**

---

# 17. Final delivery format

When done, report concisely:

```text
1. What changed
2. Why each changed module was necessary
3. Exact Authority / boundary preserved
4. Compatibility judgment
5. Tests executed and result
6. Independent Review result
7. Remaining non-blocking findings, if any
```

Do not create a repository completion-report file.

Do not create a new progress Authority.

Do not claim broader milestone completion beyond the exact implemented behavior.

---

# Final instruction to Codex

Do not merely audit this task.

Inspect first, then implement the smallest correct solution.

If current source already contains part of the requested behavior, preserve and extend it rather than duplicating it.

If current code differs from assumptions in this prompt, use:

```text
PROJECT_CONSTITUTION.md
→ relevant Architecture / Accepted ADR
→ current source truth
→ AGENTS.md
```

to resolve the correct implementation boundary.

Do not weaken Required Behavior to fit current code.

Do not broaden the task to speculative architecture.

Solve the concrete problem, prove it deterministically, perform one bounded review, and stop.
