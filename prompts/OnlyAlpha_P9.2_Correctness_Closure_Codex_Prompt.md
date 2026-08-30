# OnlyAlpha P9.2 Correctness Closure
## Codex Implementation Task Prompt

> Project: `zongxin1993/OnlyAlpha`
>
> Task type: **Bounded P9.2 correctness closure**
>
> This is NOT a redesign of P9.2 and NOT an open-ended audit.
>
> Goal:
>
> ```text
> P9.2 current implementation
>     ↓
> close exact correctness gaps
>     ↓
> P9.2 TASK COMPLETE / VERIFIED
> P9.3 IMPLEMENTATION READY
> ```
>
> Engineering priority:
>
> ```text
> Correctness
> > Determinism
> > Uniqueness
> > Explicit Authority
> > Fail-Closed
> > Market Neutrality
> > Provider Isolation
> > Reproducibility
> > Maintainability
> > Performance
> > Convenience
> ```

---

# 1. First-principles objective

The current P9.2 implementation is substantially complete.

Do NOT reopen or redesign already-correct foundations such as:

```text
Market Fact Identity
Sequence Scope
Typed Historical Bar/Trade Cache
DataSource SPI
Provider-neutral Realtime Market Reference Authority
MiniQMT market-neutral sequence semantics
Historical/Realtime canonical models
```

This task must solve only three root problems:

```text
A. Semantic Fact Authority is not exact.
B. Continuity State Mutation Authority is not unique.
C. Verification/Test Support Authority is not deterministic.
```

Permanent target:

```text
Venue Protocol Fact
        ↓
One Exact Semantic Normalizer
        ↓
Canonical Market Fact
        ↓
Single-Writer Continuity Authority
        ↓
Deterministic Runtime State
        ↓
Canonical Verification
        ↓
VERIFIED
```

Compact principle:

> **One fact, one meaning. One state, one writer. One increment, one proof.**

---

# 2. Mandatory startup procedure

Before editing:

1. Read current `master`.
2. Record exact base SHA.
3. Read:
   - `project-state.toml`
   - current P9.2 report
   - Binance P9.2 provider implementation
   - `OnlyRealtimeMarketReferenceAuthority`
   - continuity coordinator / realtime DataSource resource
   - Binance provider tests
   - current quality-policy/workflow contracts
4. Confirm current progression authority still has:
   ```text
   P9.1 VERIFIED
   P9.2 current/authorized
   P9.3 not yet authorized
   ```
5. Reproduce current failures.
6. Do NOT perform a broad repository audit.

If `master` has moved, current source and machine evidence override stale descriptions, but preserve the root principles and task boundary below.

---

# 3. Explicit non-goals

DO NOT implement:

```text
P9.3:
- ClickHouse
- PostgreSQL market-data schema
- WAL
- durable Market Data Revision
- durable stream cursor
- crash-restart market-data recovery
- HOT/COLD lifecycle

P9.4:
- Binance API key
- signatures
- private REST
- userDataStream
- account
- balance
- positions
- orders
- Broker
- reconciliation

Other:
- Binance Futures
- QMT implementation
- CTP implementation
- L2/depth
- SBE
- distributed WS sharding
- actor framework
- event-sourcing framework
- async-runtime rewrite
- universal market-data framework
- unrelated performance optimization
```

Do not modify unrelated architecture unless it is directly required to close one of the three authority gaps.

---

# 4. Block A — Semantic Fact Authority Closure

## 4.1 Root problem

Current Binance P9.2 code treats Binance `avgPrice` as:

```text
OnlyMarketReferenceKind.VENUE_REFERENCE_PRICE
```

This is semantically wrong.

Freeze the distinction:

```text
Venue Reference Price
!=
Trade Average
!=
Last Trade
```

Equal numeric values do not imply equal facts.

A market fact is identified by meaning as well as value:

```text
Fact = (
    semantic kind,
    value,
    event/effective time,
    venue contract,
    source
)
```

---

# 5. Freeze `VENUE_REFERENCE_PRICE`

`OnlyMarketReferenceKind.VENUE_REFERENCE_PRICE` must mean only:

> the venue-declared reference-price fact.

It must NOT mean:

```text
average price
last price
mark price
index price
or any generic “reference-looking” price
```

Core remains market-neutral.

Binance-specific mapping stays in the Binance plugin.

---

# 6. Replace shape-based normalization with semantic normalization

Do not keep a broad normalizer that accepts unrelated payload shapes and turns them into one semantic kind.

Preferred provider functions:

```python
normalize_reference_price(...)
normalize_trade(...)
normalize_kline(...)
```

If future mark/index prices are required, give them separate semantic contracts.

Forbidden pattern:

```python
if "r" in raw:
    price = raw["r"]
elif "w" in raw:
    price = raw["w"]
elif "price" in raw:
    price = raw["price"]
# then emit VENUE_REFERENCE_PRICE
```

Invariant:

```text
One Venue Protocol Fact
→ One Explicit Normalizer
→ One Canonical Semantic Kind
```

---

# 7. Correct REST reference path

Replace the wrong semantic path:

```text
/api/v3/avgPrice
→ VENUE_REFERENCE_PRICE
```

with Binance's actual reference-price endpoint.

The client method should be semantically named, e.g.:

```python
reference_price(...)
```

Do not keep `average_price()` and reinterpret its result as venue reference price.

Naming is part of the semantic guard.

---

# 8. Correct WebSocket reference path

Replace:

```text
<symbol>@avgPrice
```

as the source of:

```text
VENUE_REFERENCE_PRICE
```

with the actual Binance reference-price stream.

Dispatch must be explicit:

```text
referencePrice event
→ normalize_reference_price()
```

An `avgPrice` event must NOT enter this path.

A negative regression test is mandatory.

---

# 9. Preserve unavailable / missing / stale / disconnected semantics

The implementation must distinguish:

```text
A. Venue explicitly reports reference price unavailable/null.
B. OnlyAlpha has not received a reference-price fact.
C. Existing reference fact is stale.
D. Transport is disconnected.
```

Do not collapse these into one ambiguous `None`.

Use the smallest provider-neutral representation that preserves the distinction.

Do not create a large new state framework.

---

# 10. Why explicit unavailable matters

If the venue explicitly reports no reference price:

```text
explicit unavailable
```

that is a real market fact.

A requirement such as:

```text
VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE
```

may then use the canonical Trade fallback.

But:

```text
network outage
no message
stale data
```

must NOT be interpreted as:

```text
venue explicitly has no reference price
```

Never transform data absence into business semantics.

---

# 11. Core remains the reference-resolution authority

Do NOT move fallback/business-rule resolution into the Binance plugin.

Correct boundary:

```text
Binance plugin
→ reports venue facts

OnlyRealtimeMarketReferenceAuthority
→ resolves provider-neutral P9.1 requirement
```

Provider answers:

```text
What happened?
```

Core answers:

```text
What evidence satisfies the requirement?
```

---

# 12. Trade fallback has one authority

Do NOT use Binance `/avgPrice` as a second fallback authority.

Trade-average fallback must derive from:

```text
canonical raw Trades
+
proven coverage
+
authoritative window
```

using the existing provider-neutral Core authority.

Therefore:

```text
venue reference explicitly unavailable
+ complete Trade window
→ deterministic OnlyAlpha VWAP / last-trade fallback
```

and:

```text
incomplete Trade evidence
→ MARKET_REFERENCE_UNAVAILABLE
```

Fail closed.

---

# 13. Block A tests

Add deterministic offline tests:

### A-T1
```text
referencePrice REST fixture
→ VENUE_REFERENCE_PRICE
```

### A-T2
```text
referencePrice WS fixture
→ VENUE_REFERENCE_PRICE
```

### A-T3
```text
same venue reference fact:
REST vs WS
→ same canonical semantic fact
```

### A-T4
```text
avgPrice fixture
→ MUST NOT become VENUE_REFERENCE_PRICE
```

### A-T5
```text
explicit null/unavailable reference
→ explicit unavailable semantic state
```

### A-T6
```text
missing reference message
!=
explicit unavailable reference
```

### A-T7
```text
explicit unavailable reference
+ complete Trade coverage
→ deterministic fallback
```

### A-T8
```text
explicit unavailable reference
+ incomplete Trade coverage
→ fail closed
```

---

# 14. Block B — Single-Writer Continuity Authority

## 14.1 Root problem

Current continuity state may be mutated by more than one execution thread.

A single coordinator object is not enough.

Required invariant:

```text
One Continuity Timeline
→ One Mutation Authority
```

Authoritative state includes:

```text
state
recovery buffer
dedup
sequence
baseline
gap state
recovery status
READY transition
```

---

# 15. Deterministic state-machine rule

The model must satisfy:

```text
S(n+1) = F(S(n), E(n))
```

with an explicit event order.

The final result must not depend on:

```text
OS thread scheduling
timing luck
sleep duration
```

Principle:

> **I/O may be concurrent. Authority mutation must be serialized.**

---

# 16. Preferred fix — Single Writer

Preferred design:

```text
WS Reader --------\
REST Recovery -----\
Baseline Loader ----> Continuity Event Queue
Lifecycle Events ---/          |
                               v
                    Single Continuity Owner
                               |
                  state / buffer / dedup / sequence
                               |
                               v
                           READY proof
```

Only the continuity owner may mutate authoritative continuity state.

I/O workers may only submit events/results.

---

# 17. Keep the implementation bounded

Do NOT introduce:

```text
actor framework
new async runtime
event sourcing
distributed queue
```

A minimal implementation such as:

```text
queue.Queue
+
one continuity worker
```

is sufficient if compatible with current code.

Solve mutation ownership, not concurrency in general.

---

# 18. Continuity event model

Use a small internal event union/dataclass, conceptually:

```text
RealtimeFactReceived
BaselineEstablished
RecoveryFactsReceived
RecoveryFailed
TransportDisconnected
SubscriptionEstablished
BufferOverflow
```

Keep it inside the Binance provider unless a truly market-neutral Core contract already exists.

Do not leak Binance-specific recovery mechanics into Core.

---

# 19. READY must not be an external command

Avoid an unrestricted:

```python
coordinator.ready()
```

that lets another thread simply declare the state.

READY must be reached only when the state machine proves:

```text
transport connected
subscription established
baseline established
no unresolved gap
no recovery in flight
buffer reconciled
continuity proven
```

External code supplies evidence/events.

The authority itself decides READY.

---

# 20. READY invariant

Make this an explicit invariant:

```text
READY
⇒
recovery buffer empty
AND
no unresolved gap
AND
no pending recovery
AND
baseline established
AND
continuity proven
```

A state satisfying:

```text
READY
AND
unreconciled buffered fact exists
```

must be structurally unreachable.

---

# 21. Startup transitions

Desired semantics:

```text
DISCONNECTED
→ CONNECTING
→ CONNECTED
→ RECOVERING
→ READY
```

Initial subscription must not do:

```text
CONNECTED
→ READY
```

without baseline/reconciliation proof.

---

# 22. Gap transition

Normal:

```text
READY
+ valid fact
→ accept
```

Gap:

```text
READY
+ gap
→ RECOVERING
```

Immediately.

New realtime facts while recovering:

```text
→ bounded recovery buffer
```

---

# 23. Recovery transition

When recovery facts arrive:

```text
normalize
→ canonical identity
→ dedup
→ sequence reconciliation
→ merge buffered realtime facts
→ prove continuity
```

Then:

```text
proof complete
→ READY
```

Else:

```text
remain RECOVERING / FAILED
```

Never warn-and-continue as READY.

---

# 24. Disconnect transition

Any disconnect from READY/RECOVERING must immediately invalidate READY.

There must be no reachable authority state where:

```text
transport disconnected
AND
READY
```

---

# 25. Recovery buffer overflow

Keep recovery bounded.

Overflow must become a state-machine transition:

```text
RECOVERY_BUFFER_OVERFLOW
→ FAILED / NOT READY
```

Never silently drop market facts.

Never let a background worker fail while the authoritative state still says READY.

---

# 26. Alternative only if Single Writer is impractical

If bounded current-code constraints make a dedicated single owner impractical, use one coordinator-level lock.

But it must protect the full semantic transition:

```text
observe state
+
buffer mutation
+
dedup
+
sequence
+
recovery bookkeeping
+
READY proof
+
state transition
```

Do not add unrelated fine-grained locks to individual fields.

Goal:

```text
atomic semantic transition
```

not merely absence of Python data races.

---

# 27. Block B deterministic tests

No `sleep()` correctness tests.

Use barriers/events/fake transports.

### B-T1 — READY cutover race
Force a realtime fact to arrive during RECOVERING→READY cutover.

Assert:

```text
fact is reconciled
AND
READY has no unreconciled fact
```

### B-T2 — READY buffer invariant
```text
state == READY
→ recovery buffer empty
```

### B-T3 — Gap invalidates READY
```text
READY + gap
→ RECOVERING
```

### B-T4 — Disconnect invalidates READY
```text
READY + disconnect
→ not READY
```

### B-T5 — Interleaving determinism
Run both:

```text
recovery result first
then WS facts
```

and:

```text
WS facts first
then recovery result
```

Final canonical sequence/state must be identical.

### B-T6 — Duplicate recovery fact
```text
REST recovery fact N
+
WS buffered fact N
→ one canonical accepted fact
```

### B-T7 — Buffer overflow
```text
capacity exceeded
→ fail closed
```

---

# 28. Block C — Canonical Test Support Authority

## 28.1 Root problem

Current Binance tests use sibling-test imports such as:

```python
from test_data_source import _bar_type
```

This depends on implicit `sys.path`/working-directory behavior and fails under:

```text
pytest --import-mode=importlib
```

Do NOT weaken CI.

Fix the test dependency graph.

---

# 29. Establish explicit test support

Preferred structure:

```text
packages/provider/onlyalpha-plugin-binance/tests/
├── conftest.py
├── support.py
├── test_data_source.py
├── test_historical_data.py
├── test_continuity.py
└── ...
```

Use:

```text
conftest.py
```

for pytest fixtures.

Use:

```text
support.py
```

for reusable constructors/helpers.

A test module must not be another test module's utility library.

---

# 30. Test dependency direction

Correct:

```text
support / fixtures
    ↓
test modules
```

Forbidden:

```text
test_continuity
    ↓
test_data_source
```

All canonical test modules must be independently collectible.

---

# 31. Do not shrink verification

Forbidden fixes:

```text
remove Binance tests from core-full
remove Binance tests from recovery lanes
change canonical import mode
skip failing modules
special-case CI collection
```

The test code must adapt to the canonical verification environment.

---

# 32. Add cheap collection verification

Before expensive test lanes run:

```text
pytest --collect-only
--import-mode=importlib
```

for Binance tests.

If compatible with current quality architecture, add a low-cost canonical collection guard without creating a second test-discovery authority.

---

# 33. Block C evidence

Must prove:

```text
Binance collect-only under importlib   PASS
full Binance offline tests             PASS
canonical workspace collection         PASS
no sibling-test implicit imports       PASS
```

---

# 34. Block D — Verification and Closure

Do not change `project-state` early.

Closure sequence:

```text
1. targeted semantic tests
2. targeted continuity/race tests
3. Binance package tests
4. multi-market regressions
5. static / architecture
6. affected canonical lanes
7. Layered Quality
8. CodeQL
9. bounded Independent Review
10. P9.2 closure report
11. project-state transition
```

---

# 35. Phase 1 — Semantic verification

Run:

```text
reference REST normalization
reference WS normalization
REST/WS semantic convergence
avgPrice negative semantic guard
explicit-unavailable semantics
missing vs explicit-unavailable
Trade fallback
incomplete Trade coverage fail-closed
```

Do not run broad CI until this layer passes.

---

# 36. Phase 2 — Continuity verification

Run deterministic tests for:

```text
READY cutover
gap transition
disconnect
recovery merge
duplicate recovery
buffer overflow
different I/O interleavings
```

No correctness proof may depend on `sleep()`.

---

# 37. Phase 3 — Binance package verification

Run:

```text
collect-only under importlib
all Binance offline tests
Binance market package tests
mypy/static
ruff
```

---

# 38. Phase 4 — Multi-market regression

Because shared continuity/Core contracts may change, run affected existing paths:

```text
MiniQMT
Tushare
Generic T0
CN A-share
recovery
sim-recovery
```

Prove that Binance mechanics did not leak into provider-neutral Core.

---

# 39. Architecture invariants

Confirm/add bounded tests proving:

```text
Core does not import Binance provider
Core does not contain Binance protocol-field assumptions
avgPrice cannot become VENUE_REFERENCE_PRICE
READY implies no unresolved recovery
Binance tests collect under canonical import environment
```

Do not create broad speculative architecture checks unrelated to this closure.

---

# 40. Layered Quality

The exact closure SHA must have:

```text
Layered Quality
→ PASS
```

Do not accept:

```text
mostly green
known expected failure
```

Closure means current mandatory quality authority is green.

---

# 41. CodeQL

The exact closure SHA must have:

```text
CodeQL
→ PASS
```

Use current project policy as authority.

Do not resurrect deprecated Final-SHA Certification if current repository policy has removed it.

---

# 42. Bounded Independent Review

After tests are green, perform exactly one bounded review over:

```text
closure delta
+
directly touched shared authority
```

Review questions:

```text
1. Is VENUE_REFERENCE_PRICE sourced only from actual venue reference price?
2. Can avgPrice still enter that semantic kind?
3. Is explicit unavailable distinct from missing/stale/disconnected?
4. Is continuity state mutated by one authority?
5. Can READY coexist with pending/unreconciled facts?
6. Are recovery interleavings deterministic?
7. Do Binance tests collect under canonical CI rules?
8. Did this closure introduce P9.3/P9.4 scope creep?
```

Required result:

```text
Critical = 0
High = 0
```

Once answered, stop reviewing.

Do NOT restart a full-repository audit.

---

# 43. P9.2 closure report

Update the canonical P9.2 report after executable evidence is final.

Record:

```text
base SHA
closure SHA

root causes:
- semantic authority drift
- multi-writer continuity authority
- hidden test import dependency

fixes:
- exact referencePrice semantic path
- single-writer / atomic continuity transitions
- explicit test support

verification:
- targeted semantic tests
- targeted concurrency tests
- Binance offline tests
- multi-market regressions
- static
- architecture
- affected lanes
- Layered Quality
- CodeQL
- Independent Review

remaining Critical = 0
remaining High = 0
```

The report documents evidence.

It is not a second verdict authority.

---

# 44. Project-state transition

Only after all mandatory evidence is green, use the canonical state-transition mechanism.

Target:

```text
last_verified_increment = "P9.2"
last_verified_name = "Binance Spot Historical & Realtime DataSource"
last_verified_state = "TASK COMPLETE / VERIFIED"

next_authorized_increment = "P9.3"
next_authorized_name = "Production Data Foundation / Durable Market Data Platform"
next_authorized_state = "IMPLEMENTATION READY"
```

Do not hand-edit projected README/roadmap state if project tooling owns those projections.

---

# 45. Permanent engineering invariants

Leave behind these three rules.

## Invariant 1 — Exact Provider Semantics

```text
Provider Adapter
normalizes by venue semantic fact,
not by JSON shape.
```

## Invariant 2 — Single-Writer Authority

```text
I/O may be concurrent.
Authoritative state mutation is serialized.
```

## Invariant 3 — Canonical Test Collection

```text
Every canonical test module
collects independently
under the canonical pytest import environment.
```

---

# 46. Forbidden shortcut fixes

Do NOT:

```text
only change one URL and stop
```

without semantic regression guards.

Do NOT:

```text
use avgPrice as VENUE_REFERENCE_PRICE
```

or as a competing canonical fallback authority.

Do NOT:

```text
teach Core Binance-specific avg/reference semantics
```

Do NOT:

```text
add random independent locks to state fields
```

Do NOT:

```text
rewrite the DataSource to asyncio
```

Do NOT:

```text
skip Binance tests
```

Do NOT:

```text
reduce canonical verification scope
```

Do NOT:

```text
start P9.3 implementation
```

during this task.

---

# 47. Definition of Done — Semantic Authority

All must pass:

```text
actual venue referencePrice
→ VENUE_REFERENCE_PRICE                PASS

avgPrice
→ cannot masquerade as reference       PASS

explicit unavailable reference
→ preserved                            PASS

missing/stale/disconnected
→ not interpreted as explicit null     PASS

Trade fallback
→ canonical Trade authority only       PASS

incomplete fallback evidence
→ fail closed                          PASS
```

---

# 48. Definition of Done — State Authority

All must pass:

```text
continuity mutation
→ one authoritative writer             PASS

READY
→ proof-derived transition             PASS

READY + pending buffer
→ impossible                           PASS

gap
→ invalidates READY                    PASS

disconnect
→ invalidates READY                    PASS

same ordered events
→ same final state                     PASS

different I/O interleavings
→ same canonical result                PASS

buffer overflow
→ fail closed                          PASS
```

---

# 49. Definition of Done — Verification Authority

All must pass:

```text
Binance importlib collect-only         PASS
all Binance offline tests              PASS
no sibling-test implicit imports       PASS
canonical verification scope intact    PASS
multi-market affected regressions      PASS
static                                 PASS
architecture                           PASS
Layered Quality                        PASS
CodeQL                                 PASS
```

---

# 50. Definition of Done — Closure

Required final state:

```text
Critical findings = 0
High findings = 0

P9.2 report = CLOSED

project-state:
P9.2 = TASK COMPLETE / VERIFIED
P9.3 = IMPLEMENTATION READY
```

---

# 51. Stop condition

When all conditions pass:

STOP.

Do NOT:

```text
re-audit all P9.2
re-design Identity/Sequence
re-design Historical Cache
begin P9.3 database work
begin Binance Broker work
begin LIVE runtime work
```

This closure is intentionally bounded.

---

# 52. Required final Codex output

Return an evidence-based summary:

```text
P9.2 CORRECTNESS CLOSURE RESULT
===============================

Base SHA:
Closure SHA:

Semantic Authority
------------------
Reference REST path:
Reference WS path:
avgPrice negative guard:
Unavailable/missing distinction:
Trade fallback:
Status:

State Authority
---------------
Mutation ownership:
READY invariant:
Gap recovery:
Disconnect recovery:
Interleaving determinism:
Buffer overflow:
Status:

Verification Authority
----------------------
Binance collect-only:
Binance offline tests:
Multi-market regressions:
Static:
Architecture:
Layered Quality:
CodeQL:
Status:

Independent Review
------------------
Critical:
High:

Project State
-------------
last_verified_increment:
next_authorized_increment:

Remaining blockers:
- NONE / exact blockers only

VERDICT:
P9.2 VERIFIED / NOT VERIFIED
```

Do not use vague language such as:

```text
mostly done
looks good
probably fixed
```

---

# 53. Final engineering target

The closure must establish:

```text
Venue Fact
    ↓
One Semantic Interpretation
    ↓
Canonical Market Fact
    ↓
One State Mutation Authority
    ↓
Deterministic Runtime State
    ↓
One Verification Path
    ↓
VERIFIED
```

The standard for closing P9.2 is:

> **One fact, one meaning. One state, one writer. One increment, one proof.**
