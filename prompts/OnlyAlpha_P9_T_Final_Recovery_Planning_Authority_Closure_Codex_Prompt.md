# OnlyAlpha P9.T Final Recovery & Planning Authority Closure
## Codex Implementation Task Prompt

> Repository: `zongxin1993/OnlyAlpha`
>
> Task type: **High-risk bounded closure task**
>
> Objective: close the two remaining P9.T High findings without reopening P9.T architecture:
>
> 1. **Reference Continuity Closure** — Trade gaps must degrade only the realtime reference lane, must not incorrectly kill the whole Streaming Runtime, and buffered/recovery Trade facts must not be silently dropped.
> 2. **Planning Price Authority Closure** — one logical risk-increasing Order planning cycle must use one explicit deterministic planning price derived from the already captured immutable market snapshot / request price, and that exact price must be propagated consistently into Risk, fee estimation, cash reservation and margin reservation.
>
> This task is **not** Tick Strategy work, not a new Recovery framework, not a valuation redesign, and not a repository-wide audit.

---

# 0. Mandatory governance order

Before editing code, follow repository governance exactly.

Read and understand, in this order:

1. `PROJECT_CONSTITUTION.md`
2. directly relevant architecture and accepted ADRs, especially those governing:
   - Strategy Revision / Strategy fingerprint authority;
   - Streaming Runtime recovery;
   - market-data continuity;
   - market-data durability;
   - Order Intent durability;
   - Risk fail-closed semantics;
   - market / provider boundary;
3. `AGENTS.md`
4. current `master` source;
5. current directly relevant tests;
6. the previous P9.T implementation prompt if it is still present:
   - `prompts/OnlyAlpha_P9_T_Realtime_Trade_Reference_Foundation_Codex_Prompt.md`

Do not trust assumptions in this prompt over current repository truth.

If the requested closure conflicts with the Constitution, report:

```text
PLAN_CONFLICT
```

and stop.

Expected:

```text
Constitution Impact = NO
```

---

# 1. First-principles architecture

P9.T froze these permanent semantics:

```text
Strategy Decision Authority
=
1 Minute Closed Bar
```

and:

```text
Trade Tick
=
Trading Runtime realtime market reference
```

Therefore:

```text
Trade Tick
!=
Strategy Decision Trigger
```

The system now has two different market-data lanes:

```text
                    Canonical Market Data
                            │
             ┌──────────────┴──────────────┐
             │                             │
             ▼                             ▼
            BAR                          TRADE
             │                             │
             ▼                             ▼
     Decision Continuity           Reference Continuity
             │                             │
             ▼                             ▼
      Bar Pipeline / Strategy      Realtime Market State
                                           │
                                  Execution / Risk reference
```

These lanes have different failure consequences.

A Bar continuity failure may invalidate Strategy decision continuity.

A Trade continuity failure invalidates the current execution/risk reference but does **not** automatically invalidate:

- closed-Bar Strategy processing;
- fills;
- cancellation;
- reconciliation;
- persistence;
- recovery;
- risk-reducing operations.

This distinction is the central recovery invariant of this closure.

---

# 2. Root causes that must be fixed, not patched around

## 2.1 Root cause A — Streaming Runtime still contains a Bar-only recovery assumption

Before P9.T, this approximation was effectively true:

```text
Streaming GAP
≈
Bar GAP
```

After Trade became a first-class Runtime reference fact:

```text
Streaming GAP
=
Bar GAP
or
Trade GAP
```

The old assumption is no longer valid.

The current implementation must be inspected for behavior equivalent to:

```python
if result.status is GAP_DETECTED:
    _recover_gap(update)
```

combined with:

```python
if update is not Bar:
    fail Streaming Runtime
```

This is semantically wrong for reference-only Trade data.

Do not fix this by adding a second Binance/venue-specific Trade recovery implementation in Core.

---

## 2.2 Root cause B — normal streaming and recovery suffix processing have diverged

The normal worker path currently has a useful property:

```text
OnlyLiveBarFinalizer
BAR   -> finalize as needed
TRADE -> pass through unchanged
```

so both ultimately reach the sole semantic lane / `OnlyMarketDataProcessor`.

The recovery/catch-up path must not duplicate a reduced Bar-only version of this logic.

Any recovery code equivalent to:

```python
if not isinstance(payload, OnlyBarUpdate):
    continue
```

is invalid because it silently removes canonical Trade updates from Runtime reference processing.

The solution is to converge normal and recovery suffix admission semantics, not add more special-case duplication.

---

## 2.3 Root cause C — captured Trade reference is local to the reference gate

Current P9.T already captures one immutable realtime market snapshot and produces execution-reference evidence.

For a risk-increasing request, current semantics are conceptually:

```text
LIMIT:
resolved planning price = request.price

MARKET:
resolved planning price = trusted latest Trade
```

That is correct.

The remaining problem is that downstream operations may still independently resolve:

```text
order.price or current_bar.close
```

for:

- Account cash reservation;
- Strategy cash reservation;
- margin reservation;
- fee / funding estimation;
- Risk rules / market pre-trade rules for MARKET orders.

This creates multiple implicit price authorities inside one logical order-planning cycle.

The fix is **not** “replace every Bar price with Tick”.

The fix is:

```text
one Order Planning cycle
→ one explicit effective planning price
→ all price-dependent pre-dispatch consumers reuse it
```

---

# 3. Frozen Task Contract

## 3.1 Goal

Close P9.T by enforcing:

```text
Decision Continuity
!=
Reference Continuity
```

and:

```text
EffectivePlanningPrice
=
f(
    OrderRequest,
    ExecutionReferenceProfile,
    one immutable RealtimeMarketSnapshot
)
```

for the price-dependent risk-increasing order-planning path.

## 3.2 Modification Scope

Expected bounded scope:

```text
src/onlyalpha/runtime/streaming/runtime.py
src/onlyalpha/runtime/streaming/worker.py only if sharing semantics requires it
src/onlyalpha/execution/reference.py
src/onlyalpha/order/service.py
src/onlyalpha/order/cash_port.py
src/onlyalpha/order/margin_port.py
src/onlyalpha/runtime/runtime.py
src/onlyalpha/runtime/trading_facade.py
src/onlyalpha/strategy_ledger/order_port.py
src/onlyalpha/margin/order_port.py
src/onlyalpha/risk/contexts.py
src/onlyalpha/risk/service.py
src/onlyalpha/risk/rules/account.py
directly affected tests
directly affected long-lived architecture docs
```

Modify fewer files if current source supports a smaller correct solution.

Do not expand beyond the nearest stable boundary without a concrete dependency.

## 3.3 Expected Impact Scope

High-risk areas:

```text
Streaming recovery
Market-data continuity
Realtime reference trust
Order planning
Risk admission
Cash reservation
Margin reservation
Fee/funding estimation
Order Intent causal evidence
Compatibility
```

Do not reopen unrelated execution, persistence, Strategy, Broker or database architecture.

## 3.4 Explicit Out of Scope

Do not implement:

```text
Tick-driven Strategy
Strategy.on_tick
Cluster.on_tick
Tick Calculation Graph
Tick Strategy Revision
Strategy fingerprint changes

new provider-specific recovery logic in Core
second Binance recovery coordinator
new historical Trade engine in Streaming Runtime

Quote / L1
BEST_BID
BEST_ASK
MID
L2
order book
market making
HFT

Tick -> Bar aggregation
volume/tick/value Bars

Binance Futures
QMT
CTP

Backtest Tick execution simulation

new database schema unless a concrete compatibility defect proves it necessary
new persistence authority
new recovery framework

Broker redesign
repository-wide refactor

full Valuation redesign
Tick-driven valuation on every Trade
```

---

# 4. Authority model to preserve

## 4.1 Provider / DataSource Authority

Provider Adapter owns:

```text
provider transport
provider reconnect
provider-native sequence semantics
provider-native baseline
provider-native gap backfill
provider-native recovery proof
```

For Binance Spot, reuse the existing continuity coordinator and `_recover()` logic.

Core must not call Binance REST directly.

Core must not reimplement Binance trade-ID recovery.

## 4.2 Core Processor Authority

`OnlyMarketDataProcessor` owns provider-neutral verification:

```text
scope validation
dedup
stale/out-of-order assessment
sequence assessment
gap detection
quality admission
trusted realtime projection update
```

Core may independently detect a gap even if a Provider claimed continuity.

That is verification, not a second recovery authority.

## 4.3 Realtime Market State Authority

The existing Runtime-owned realtime projection remains the only current reference projection.

Do not create a second `latest_trade` store.

A Trade with unresolved continuity must not become trusted reference state.

The exact canonical fact identity must remain traceable.

## 4.4 Streaming Runtime Authority

Streaming Runtime owns consequences and orchestration:

```text
Bar gap
→ Decision-lane recovery

Trade gap
→ Reference lane becomes untrusted
→ risk-increasing execution fails closed
→ Runtime stays operational
```

Streaming Runtime does **not** own venue-specific Trade reconstruction.

## 4.5 Order Planning Authority

One Order submit operation owns one logical planning cycle.

For a reference-enabled risk-increasing order:

```text
timestamp
→ classify risk change once
→ capture one immutable realtime market snapshot once
→ validate reference
→ resolve one effective planning price
→ Risk
→ create/order fee estimate
→ margin reserve
→ cash reserve
→ durable Order Intent
```

No downstream component may independently re-read mutable “latest Trade”.

No downstream component may silently switch to `Bar.close` after a successful realtime reference plan.

---

# 5. Closure Workstream C1 — Reference Continuity

## 5.1 Typed gap consequence dispatch

Inspect the current Streaming Runtime callback that handles `GAP_DETECTED`.

Replace the Bar-only assumption with typed consequence routing.

Conceptually:

```python
if result.status is not GAP_DETECTED:
    return

if update.data_type is BAR:
    recover_decision_lane(update)
elif update.data_type is TRADE:
    degrade_reference_lane(update)
else:
    handle_according_to_explicit_data_contract()
```

Do not route Trade to the existing Bar recovery loader.

Do not fail the entire Runtime solely because a Trade reference gap exists.

## 5.2 Trade gap behavior

For a contiguous Trade scope:

```text
100
101
105
```

the Processor / realtime projection must retain the last trusted state and mark the relevant reference continuity unresolved.

Required consequences:

```text
Runtime state:
not FAILED solely due Trade gap

Strategy BAR lane:
continues according to existing Bar semantics

Realtime reference:
untrusted / unresolved

risk-increasing Order:
denied with existing reference-gap failure semantics

risk-reducing / safety path:
not blocked solely by missing Trade reference
```

Do not silently accept 105 as trusted current reference.

## 5.3 Recovery ownership

When the Provider/DataSource later supplies the exact missing canonical sequence:

```text
102
103
104
105
```

the same sole Processor must validate and apply it.

Do not mutate realtime state directly from Streaming Runtime.

Do not bypass `OnlyMarketDataProcessor`.

Do not call a provider-specific historical client from Core.

If the current generic source lifecycle already has a provider-neutral reconnect/resubscribe mechanism that naturally triggers provider continuity recovery, it may be reused.

Do **not** invent a new recovery Port solely for this closure unless current interfaces make restoration otherwise impossible and the dependency is proven.

## 5.4 Recovery / catch-up suffix processing

Fix any recovery suffix path that discards non-Bar updates.

The invariant is:

```text
normal streaming admission semantics
==
recovery/catch-up suffix admission semantics
```

for canonical Trade facts.

A preferred minimal structure is a shared internal helper that sends admitted updates through:

```text
finalization/pass-through
→ semantic lane
→ Processor
→ processing-result consequence handling
```

Bar-specific canonical sequencing may remain Bar-specific.

Trade must pass through unchanged and reach the Processor.

Do not duplicate Trade processing logic.

## 5.5 Secondary gaps during recovery

Bar and Trade secondary gaps have different consequences.

Bar secondary gap:
- preserve existing fail-closed Bar recovery semantics.

Trade secondary gap:
- keep the reference scope unresolved;
- do not advance trusted reference across the gap;
- do not silently drop the update;
- do not turn the whole Runtime into FAILED solely for reference continuity.

Do not recursively start venue-specific recovery in Core.

## 5.6 Restart behavior

Preserve:

```text
restart
→ realtime reference projection starts EMPTY / NOT READY
```

Do not restore an old last Trade as current truth from checkpoint or ClickHouse.

The Provider/DataSource must re-establish current live continuity/baseline.

---

# 6. Closure Workstream C2 — Planning Price Authority

## 6.1 Effective planning-price rule

For a risk-increasing request with realtime execution reference enabled:

```text
LIMIT:
effective_planning_price = request.price

MARKET:
effective_planning_price = accepted Trade reference price
```

Reuse the current execution-reference evidence.

Do not create a second pricing Authority.

Do not turn a MARKET request into a synthetic LIMIT order.

The resolved price is a deterministic planning/provisional price, not a venue-fill prediction.

## 6.2 Capture once

`OnlyExecutionReferencePlanningService.plan()` should remain the one snapshot capture point for this order-planning reference.

Do not capture again in:

```text
Risk
cash reservation
margin reservation
fee estimator
```

Expose the resolved planning price from the existing result/evidence in the smallest compatible way.

## 6.3 Classify risk change once

Within `OnlyOrderService.submit()`:

- build the initial immutable Risk context;
- classify `OnlyOrderRiskChange` once;
- reuse it for reference gating and other affected gates.

Avoid repeated semantic classification.

## 6.4 Propagate planning price into Risk

Current MARKET Risk paths may fall back to:

```text
context.market_data.primary_bar.close
```

Add the narrowest explicit planning-price input to the immutable Risk evaluation context.

Recommended concept:

```python
@dataclass(frozen=True, slots=True)
class OnlyRiskEvaluationContext:
    ...
    order_planning_price: OnlyPrice | None = None
```

Exact naming may differ.

For a reference-enabled risk-increasing request:

```text
order_planning_price
=
reference_plan.evidence.resolved_order_price
```

Price precedence:

```text
request.price
or explicit order_planning_price
or legacy Bar fallback only for existing non-reference compatibility paths
```

A reference-enabled risk-increasing MARKET order must never silently use Bar close after accepted reference planning.

## 6.5 Risk rules affected

Inspect and update only rules that actually consume price.

At minimum check:

```text
OnlyAvailableBalanceRiskRule
OnlyRiskService market pre-trade rule construction
```

A MARKET risk-increasing order must use the propagated planning price for:

```text
cash notional
market-rule price validation
price-related market limits/rules
```

Do not change unrelated rules.

## 6.6 Risk rejection traceability

If a downstream Risk rejection materially depends on propagated planning price, preserve enough evidence to explain it.

Prefer existing Risk `details` fields.

Where directly applicable include:

```text
planning_price
market_snapshot_fingerprint
market_update_id
execution_profile_fingerprint
```

using existing accepted reference-plan evidence.

Do not duplicate the canonical Trade object in Risk state.

For accepted Orders, durable Order Intent remains the authoritative causal evidence.

## 6.7 Fee estimation

Avoid changing `OnlyOrderManager` if `OnlyOrderService` can adapt/curry the fee factory.

Preferred pattern:

```python
manager_fee_factory = (
    lambda order, ts: runtime_fee_factory(order, ts, planning_price)
)
```

Runtime fee resolution:

```text
LIMIT:
order.price

MARKET + accepted realtime reference:
explicit planning price

legacy non-reference mode:
existing explicit compatibility fallback only
```

Do not re-read mutable latest Trade.

Do not silently use Bar close in a reference-enabled risk-increasing MARKET cycle.

## 6.8 Cash reservation

Extend the narrow reservation Port additively/backward-compatibly, conceptually:

```python
reserve(
    order,
    timestamp,
    *,
    planning_price: OnlyPrice | None = None,
)
```

Update:

```text
OnlyOrderCashReservationPort
OnlyRuntimeCompositeCashReservationAdapter
OnlyRuntimeAccountCashReservationAdapter
OnlyOrderStrategyCashReservationAdapter
```

Price precedence:

```text
1. order.price
2. explicit planning_price
3. legacy reference callback only for explicitly compatible non-reference paths
```

For a reference-enabled risk-increasing MARKET order, #3 must never be reached.

Do not store a global mutable planning price.

## 6.9 Margin reservation

Apply the same bounded pattern to:

```text
OnlyOrderMarginReservationPort
OnlyOrderMarginReservationAdapter
```

Do not re-read realtime market state inside the adapter.

## 6.10 Funding-plan consistency

The fee/funding plan installed on the Order must use the same effective planning price that Account/Strategy cash reservation later verifies.

Preserve:

```text
funding_plan.principal_reservation
==
calculated reservation principal
```

Add a test where Bar close differs from Trade reference and prove there is no mixed-price planning.

---

# 7. Valuation boundary — explicit non-expansion rule

Valuation is a separate logical operation.

Correct principle:

```text
one logical operation
→ one immutable market snapshot / one explicit mark policy
```

not:

```text
all Runtime operations
→ one global universal snapshot
```

For this closure:

- preserve existing closed-Bar Strategy semantics;
- preserve existing Bar-based valuation policy unless a directly affected correctness defect proves otherwise;
- document that policy explicitly;
- do not silently substitute Trade into valuation code;
- do not introduce Tick-driven valuation on every Trade;
- do not couple Valuation semantics to `OnlyExecutionReferenceProfile`.

The realtime market state remains available to future Valuation policy work.

A future move to Trade-based valuation requires a separate explicit Valuation Policy / Authority.

Therefore:

```text
Valuation redesign = OUT OF SCOPE
```

---

# 8. Medium finding — do not expand it

Current support for:

```text
LAST_TRADE
```

plus:

```text
reference admission
price-deviation protection
provisional MARKET planning price
causal evidence
```

is sufficient.

Do not add:

```text
BEST_BID
BEST_ASK
MID
offset ticks
passive/aggressive execution
repricing
chasing
```

in this closure.

---

# 9. Mandatory acceptance tests

## 9.1 Strategy non-interference

Same ordered Closed Bars with and without arbitrary valid Trades must produce identical Strategy semantics and Strategy fingerprint.

## 9.2 Trade gap does not kill Runtime

For actual Streaming Runtime:

```text
Trade 100
Trade 101
Trade 105
```

assert:

```text
Runtime != FAILED solely due Trade gap
reference unresolved
Bar Strategy lane still operational
```

## 9.3 Risk-increasing fails closed during gap

Assert:

```text
risk-increasing submit
→ REFERENCE_GAP_UNRESOLVED
```

or exact existing canonical failure.

## 9.4 Exact recovery restores trust

Feed:

```text
102
103
104
105
```

through the real affected Streaming path.

Assert latest trusted Trade = 105 and gap cleared.

## 9.5 Recovery/catch-up does not drop Trade

Place Trade facts in the buffered/recovery suffix and prove each admitted fact reaches the sole Processor.

## 9.6 Bar recovery unchanged

Existing Bar-gap recovery tests stay green and retain current strictness.

## 9.7 No second provider recovery Authority

Prove Core does not directly implement/call provider-specific historical Trade reconstruction.

## 9.8 Snapshot isolation

Capture at Trade 100, then publish 101/102/103 before downstream reservation work.

The existing planning cycle must remain bound to Trade 100.

## 9.9 LIMIT authority

Given:

```text
Trade = 100
LIMIT BUY = 95
```

all principal/fee/margin calculations use 95.

Trade is reference/protection only.

## 9.10 MARKET planning authority

Given:

```text
Closed Bar = 98
Trusted Trade = 100
MARKET BUY
```

with accepted realtime reference, applicable:

```text
Risk notional
market pre-trade
fee/funding
Account cash
Strategy cash
margin
Order Intent evidence
```

must use 100, not 98.

## 9.11 No Bar fallback after reference failure

Missing/stale/gapped/invalid/wrong-source reference for risk-increasing MARKET must fail closed, never continue with Bar close.

## 9.12 Risk-reducing safety path

Missing realtime Trade must not by itself block required risk reduction.

Preserve current explicit safe compatibility semantics where needed.

## 9.13 Order Intent traceability

Prove accepted Order Intent resolves to:

```text
snapshot fingerprint
exact market update id
Trade id / sequence
reference price
resolved planning price
Execution Profile fingerprint
```

## 9.14 Risk rejection traceability

If reference admission passes but a later price-dependent Risk rule rejects, the rejection/audit must expose the effective planning price and sufficient reference identity through existing details/evidence mechanisms.

---

# 10. Compatibility requirements

Explicitly judge:

```text
Strategy Revision fingerprint
Order snapshot
Order Intent persistent format
Risk checkpoint
Runtime checkpoint
reservation Protocol call sites
Backtest behavior
Bar-only behavior
SIM behavior
```

Prefer:

- additive optional keyword args;
- default `None` for new transient context values;
- OrderService adapter/curry instead of changing OrderManager semantics;
- no realtime state checkpoint;
- no persistent schema migration unless strictly necessary.

If persistent format changes, provide deterministic compatibility tests.

---

# 11. Determinism requirements

Tests must be:

```text
deterministic
hermetic
offline-first
```

Use fake clocks, fake sources, canonical recorded updates, barriers and fault injection.

Do not use sleeps, public network, retry-until-green, weakened assertions, skip or xfail.

---

# 12. Implementation sequence

## Phase A — bounded baseline

Confirm current master and confirm only the two Highs remain.

Freeze actual scope.

Do not restart repository-wide audit.

## Phase B — typed gap consequences

Implement BAR vs TRADE gap routing.

Add tests.

## Phase C — suffix convergence

Remove Bar-only Trade discard in catch-up/recovery.

Use the sole semantic Processor path.

Add tests.

## Phase D — planning-price propagation

Reuse the already captured execution-reference plan.

Propagate one planning price through:

```text
Risk
fee/funding
cash
margin
```

without new market-state reads.

## Phase E — traceability

Ensure accepted intent evidence remains exact.

Ensure downstream price-dependent Risk rejection remains explainable.

## Phase F — compatibility/docs

Update only long-lived docs directly affected.

Document:

```text
Decision Continuity != Reference Continuity
LIMIT planning price = order price
MARKET risk-increasing planning price = accepted execution reference
Valuation is a separate explicit mark policy
```

Do not create completion reports.

---

# 13. Validation

Following `AGENTS.md`, run only Impact-Aware validation:

```text
targeted unit tests
targeted Streaming Runtime recovery tests
targeted execution-reference tests
targeted Risk tests
targeted fee/cash/margin tests
targeted Order Intent durability tests
ruff check
ruff format --check
mypy
nearest affected canonical lane
```

Run broader tests only if actual dependency impact proves it necessary.

Do not modify quality policy, CI thresholds or test discovery to get green.

---

# 14. Bounded Independent Review

Perform exactly one focused review after implementation.

Questions:

1. Can Trade gap still kill Runtime solely because it is non-Bar?
2. Can recovery/catch-up discard Trade?
3. Did Core create a second provider-specific Trade recovery authority?
4. Can gapped Trade become trusted?
5. Can reference-enabled risk-increasing MARKET still use Bar close after accepted reference?
6. Can Risk use one price while fee/cash/margin use another?
7. Can any downstream component re-read mutable latest state after capture?
8. Is LIMIT price still authoritative?
9. Are risk-reducing safety paths preserved?
10. Did Strategy semantics/fingerprint change?
11. Did Bar recovery weaken?
12. Did Valuation scope accidentally expand?
13. Is Order Intent exact reference traceability intact?
14. Are price-dependent Risk rejections explainable?
15. Did compatibility scope exceed the nearest stable boundary?

Fix Critical/High findings only within scope.

Do not restart a full audit.

---

# 15. Stop Condition

Complete only when:

```text
Required Behavior implemented
AND mandatory acceptance tests PASS
AND direct Impact Scope validation PASS
AND Constitution consistency PASS
AND bounded Independent Review complete
AND Critical = 0
AND High = 0
```

Then stop.

Do not continue for future Quote, Futures, valuation enhancement, cleanup, new abstractions or additional audits.

---

# 16. Expected final architecture

```text
                    Canonical Market Data
                            │
             ┌──────────────┴──────────────┐
             │                             │
             ▼                             ▼
            BAR                          TRADE
             │                             │
             ▼                             ▼
     Decision Continuity           Reference Continuity
             │                             │
             ▼                             ▼
         Strategy                  Realtime Market State
             │                             │
             │                    immutable capture
             │                             │
             └──────────────┬──────────────┘
                            ▼
                     Order Planning
                            │
                ┌───────────┴────────────┐
                │                        │
              LIMIT                    MARKET
                │                        │
        request.price          trusted Trade reference
                │                        │
                └───────────┬────────────┘
                            ▼
                 Effective Planning Price
                            │
            ┌───────────────┼─────────────────┐
            ▼               ▼                 ▼
          Risk          Fee/Funding       Cash/Margin
            │               │                 │
            └───────────────┼─────────────────┘
                            ▼
                    Durable Order Intent
                            │
                            ▼
                          Broker
```

Recovery:

```text
BAR GAP
→ Decision-lane recovery

TRADE GAP
→ Reference unresolved
→ risk-increasing fail closed
→ Runtime continues safety/observation paths
→ exact canonical sequence restores trust
```

---

# 17. Final Codex delivery format

Report:

```text
1. Current master / commit audited
2. Frozen Task Contract
3. Actual files changed
4. Reference Continuity closure result
5. Planning Price Authority closure result
6. Compatibility judgment
7. Tests / validation executed
8. Independent Review result
9. Critical / High count
10. Stop Condition result
```

Do not create a repository completion-report file.

---

# Final instruction

This is a closure task, not architecture exploration.

The intended fix is deliberately small:

```text
separate Bar continuity consequence from Trade reference consequence
+
stop dropping Trade in recovery suffix
+
propagate one already-resolved planning price through price-dependent pre-dispatch consumers
```

Do not build a second Trade recovery engine.

Do not replace every Bar price with Tick.

Do not change Strategy semantics.

Do not redesign Valuation.

Implement the smallest deterministic solution, prove the actual affected paths, perform one bounded Independent Review, and stop.
