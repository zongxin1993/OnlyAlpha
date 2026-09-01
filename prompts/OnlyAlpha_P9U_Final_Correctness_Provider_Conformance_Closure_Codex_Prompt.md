# OnlyAlpha Codex Task Prompt

## Task Title

**P9.U Final Correctness & Provider Conformance Closure**

---

# 0. Mission

You are working on the OnlyAlpha repository after the initial implementation of:

```text
P9.U — Universal Spot/Futures Research & Backtest Semantic Closure
```

The current mainline already contains substantial and mostly correct universal Spot/Futures semantics.

This task is **NOT** a redesign of P9.U.

This task exists to close the remaining correctness, provider-conformance, authority, identity, and assembled-runtime gaps discovered by a bounded audit of the current mainline.

The current architectural direction is accepted.

Do not replace it with:

```text
Spot Engine
Futures Engine
Binance-specific Core
provider-aware Strategy
provider-aware Trading Kernel
```

The purpose of this task is to complete the authority chain:

```text
External Provider Reality
        ↓
Immutable Provider Evidence
        ↓
Normalized Reference Authority
        ↓
Effective Trading Composition
        ↓
Provider-neutral Compiled Market Policy
        ↓
Canonical Execution Intent
        ↓
One Trading Kernel
        ↓
Position / Margin / Account Authorities
        ↓
Deterministic Economic Facts
        ↓
Checkpoint / Replay
        ↓
Reproducible Evidence
```

The completion criterion is not:

```text
"Binance Futures test classes pass"
```

The completion criterion is:

```text
Binance Spot
+
Binance USD-M
+
Synthetic non-Binance Futures
```

must all prove the same canonical Core path, with no provider-specific Core branch and with deterministic/recoverable evidence.

---

# 1. Repository Baseline

Before implementation, verify the current mainline HEAD.

At the time this task was designed, the audited mainline HEAD was:

```text
b768155660aa71400f30ee570563f32d952ffb41
Feat: P9.U — Universal Spot/Futures Research & Backtest Semantic Closure
```

Do not assume this commit is still HEAD.

Always inspect current `master` / default branch first.

If mainline changed:

1. re-evaluate only the relevant changed impact scope;
2. do not restart a repository-wide audit;
3. preserve the Task Contract below unless a real normative conflict exists.

---

# 2. Mandatory Read Order

Follow root `AGENTS.md`.

Before planning or editing code, read:

1. `PROJECT_CONSTITUTION.md`
2. relevant Architecture / public Contracts
3. relevant Accepted ADRs
4. `docs/p9_universal_spot_futures_research_backtest_execution_plan.md`
5. `AGENTS.md`
6. current source
7. current tests
8. current executable behavior

At minimum inspect:

```text
docs/adr/0106-universal-spot-futures-research-backtest-sequencing.md
docs/p9_universal_spot_futures_research_backtest_execution_plan.md
docs/p9_production_trading_vertical_architecture.md

src/onlyalpha/domain/
src/onlyalpha/market/
src/onlyalpha/market/product/
src/onlyalpha/execution/
src/onlyalpha/transaction/
src/onlyalpha/order/
src/onlyalpha/position/
src/onlyalpha/margin/
src/onlyalpha/account/
src/onlyalpha/broker/
src/onlyalpha/data/
src/onlyalpha/research/
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/trading_facade.py
src/onlyalpha/runtime/persistence/

packages/market/onlyalpha-market-binance-spot/
packages/provider/onlyalpha-plugin-binance/

tests/conformance/
tests/execution/
tests/runtime/
```

Separate:

```text
Normative Truth
=
Constitution / Architecture / Contracts / Accepted ADR

Implementation Truth
=
current source / tests / runtime behavior
```

Do not weaken architecture to preserve a wrong current implementation.

---

# 3. Owner Decision

The owner-level decision remains:

```text
OnlyAlpha Core owns universal and stable trading/economic semantics.

All market/provider/broker/protocol/rule differences belong to
Plugin / Adapter / Gateway / Market Product boundaries.

Spot and Futures must be configurations of the same Trading Kernel.

Research and Backtest must share the same universal economic path.

Adding a new market inside the supported semantic envelope
should approach:

Core ΔLOC = 0
```

Constitution Impact:

```text
NO
```

If this task appears to require weakening or modifying the Constitution:

```text
STOP
REPORT: PLAN_CONFLICT
```

Do not modify `PROJECT_CONSTITUTION.md`.

---

# 4. Formal Task Contract

## Goal

Close all remaining P9.U correctness and conformance gaps so that:

```text
Binance Spot
Binance USD-M
Synthetic non-Binance Futures
```

can be assembled through normal OnlyAlpha contracts and prove one universal Research/Backtest/Trading Kernel architecture.

## Modification Scope

Expected scope may include:

```text
market product discovery/factory
Binance USD-M market product package
Binance provider USD-M reference capture
provider raw DTO normalization
funding reference normalization
margin requirement canonical model
effective trading profile
position mode / short-policy semantic cleanup
dataset/evidence identity
checkpoint/replay
provider contract tests
assembled conformance tests
directly affected docs/ADR cross references
directly affected packaging / entry points
```

Only modify other subsystems if direct dependencies prove it necessary.

Do not begin unrelated refactors.

## Expected Impact Scope

This remains a high-risk task because it touches:

```text
provider boundary
market product authority
identity/fingerprint
economic correctness
margin
funding
position mode
dataset/replay
checkpoint/recovery
public contracts
plugin discovery
```

Perform a bounded Independent Review before closure.

## Required Behavior

After completion:

1. Binance USD-M Market Product is discoverable and assembled by normal OnlyAlpha plugin mechanisms.
2. USD-M market reference is derived from immutable provider evidence rather than manually supplied fixtures in product flow.
3. all behavior-affecting reference coverage participates in authority identity.
4. funding accounting uses the exact authoritative funding-boundary reference evidence available from Binance.
5. funding schedule is provider-derived rather than permanently hardcoded to 8 hours.
6. Binance index-price historical requests use correct provider wire contracts.
7. Binance margin brackets compile losslessly into a universal canonical requirement function.
8. runtime-effective position mode and margin mode have exactly one authority.
9. `NETTING/HEDGING` and `CROSS/ISOLATED` are tested as assembled universal runtime semantics where in scope.
10. duplicated `LONG_ONLY` position-mode authority is removed from canonical compiled semantics.
11. canonical target-exposure planning has a defined execution-facing integration boundary without provider reinterpretation.
12. Spot regression remains zero.
13. checkpoint/replay remains deterministic.
14. provider-specific concepts remain outside Core.

## Acceptance

Required final state:

```text
Critical = 0
High = 0
```

and all required conformance/validation evidence passes.

## Out of Scope

Do not expand into:

```text
Binance Futures LIVE mainnet certification
full LIVE Runtime
provider-exact liquidation
COIN-M
Options
QMT
CTP real integration
Web
Agent
new strategy DSL
complete Portfolio redesign
repository-wide architecture cleanup
```

## Stop Condition

Stop when:

```text
all required behavior complete
+ direct acceptance tests pass
+ affected validation passes
+ provider assembled conformance passes
+ checkpoint/replay equality passes
+ Spot regression passes
+ bounded Independent Review complete
+ Critical = 0
+ High = 0
```

Do not continue with unlimited re-auditing after this.

---

# 5. HIGH-1 — Binance USD-M Market Product Assembly Closure

Current audited state showed Binance USD-M DataSource classes and a USD-M policy compiler, but no normal `onlyalpha.market_products` entry-point assembly equivalent to Binance Spot.

## Root Cause

A Python implementation exists, but unit-test constructability was mistaken for product conformance.

## Required Fix

Prefer the architectural separation:

```text
packages/
├── market/
│   ├── onlyalpha-market-binance-spot/
│   └── onlyalpha-market-binance-usdm/
│
└── provider/
    └── onlyalpha-plugin-binance/
```

The USD-M Market Product package should own:

```text
normalized USD-M reference contracts
reference authority
policy compiler
market product factory
composition identity
```

The Binance provider package should own:

```text
HTTP / WebSocket
provider DTOs
raw endpoint behavior
normalization/capture
provider errors
broker field translation
```

The final normal runtime path must support:

```text
entry point discovery
→ MarketProductFactory
→ reference authority
→ policy compiler
→ ResolvedMarketProductBinding
→ BacktestRuntime
```

Direct construction of a compiler may remain in unit tests but cannot be the final conformance path.

---

# 6. HIGH-2 — Immutable Binance USD-M Reference Authority

Current audited flow allowed normalized USD-M reference fields such as tick size, quantity step and margin tiers to be manually supplied.

This does not prove real provider conformance.

## Root Cause

The boundary:

```text
Provider Reality
→ Immutable Reference
```

was incomplete.

## Required Flow

Create a provider reference capture path conceptually equivalent to:

```text
Binance Raw Evidence
        ↓
Provider DTO validation
        ↓
immutable raw evidence hash
        ↓
normalized Binance USD-M reference snapshot
        ↓
reference publication/store
        ↓
Market Product reference authority
```

Do not expose raw provider JSON to Core.

Capture only information required by current Research/Backtest scope.

---

# 7. Split Public Market Reference From Account-Effective Trading Profile

Do not put all Binance Futures information into one reference object.

Two distinct authorities exist.

## Public Market Reference

Examples:

```text
contract specification
instrument status
tick size
quantity step
minimum quantity
maximum quantity
notional filters
margin asset
funding schedule
public contract metadata
```

## Account-Effective Trading Profile

Examples:

```text
position mode
margin mode
effective account margin profile
requested leverage where applicable
account-specific bracket modifiers where applicable
```

These must not be merged because:

```text
what the market is
!=
how this account is configured to trade it
```

The final composition should look like:

```text
Public Market Reference
+
Provider Capability Envelope
+
Requested Trading Profile
+
Account-effective inputs
        ↓
Effective Trading Profile
        ↓
CompiledMarketPolicy
```

---

# 8. HIGH-3 — Authority Identity Must Determine Behavior

Audit found behavior-affecting reference coverage information could influence `resolve(as_of=...)` without being fully represented in the identity used to describe the authority.

## Required Principle

Any field that changes observable authority behavior must participate in an appropriate authority identity.

## Required Design

Separate at least:

```text
ContentFingerprint
```

from:

```text
Authority/CoverageFingerprint
```

`ContentFingerprint` represents normalized economic content.

`AuthorityFingerprint` must include all behavior-affecting coverage/provenance inputs, as applicable:

```text
content_fingerprint
coverage_start
coverage_end
observed_at / published_at
provider/source revision
normalizer semantic version
provider schema semantic version
```

Do not include irrelevant wall-clock noise.

Do include all values that alter `resolve()` behavior.

Required invariant:

```text
same authority fingerprint
+
same resolve parameters
=
same resolve result
```

Add deterministic/property-like tests.

---

# 9. HIGH-4 — Funding Exact Provider Evidence

Do not discard authoritative economic evidence from the provider and later reconstruct it from a sampled data family.

If the provider funding-history source record supplies the exact funding-boundary mark/reference price used for the funding event, preserve it.

## Required Canonical Result

One provider funding record should be able to produce immutable canonical facts equivalent to:

```text
FundingBoundaryMarkPriceFact
FundingRateFact
```

with shared lineage such as:

```text
provider_evidence_id
source_record_hash
source sequence
data version
funding boundary timestamp
```

Ensure canonical replay ordering makes the required reference price available before funding accounting is applied.

Do not teach Core Binance funding DTOs.

---

# 10. Funding Authority Separation

Preserve:

```text
FundingRateFact
        +
exact funding-boundary valuation fact
        +
position held at boundary
        +
contract multiplier
        +
compiled funding policy
        ↓
FundingCashflow
```

Never:

```text
Funding = Fee
```

Never allow a provider FundingRate DTO to mutate account state directly.

Reuse the existing pending economic fact / idempotent recovery architecture instead of creating a second accounting path.

---

# 11. Provider Funding Semantic Discriminators

If current provider data contains semantic discriminators such as funding `rateType`, do not silently normalize all values into identical semantics.

For the current bounded scope:

```text
known supported regular type
→ normalize

known unsupported special semantic
→ fail closed

unknown semantic
→ fail closed
```

Do not create speculative universal Core concepts unless the new economic meaning is genuinely required by current project scope.

---

# 12. HIGH-5 — Funding Schedule Must Be Provider-Derived

Do not permanently hardcode an 8-hour funding interval as the authoritative Binance rule.

Required path:

```text
Binance protocol defaults
+
provider funding-info adjustments
        ↓
Normalized FundingScheduleReference
        ↓
CompiledFundingPolicy
```

If a provider default is used, bind it to an explicit provider semantic version so the result remains reproducible.

Core should consume only provider-neutral values such as:

```text
interval_seconds
boundary rule
valuation reference kind
sign convention
```

---

# 13. HIGH-6 — Provider HTTP Contracts Must Stay Explicit

Do not allow generic transport reuse to erase differences between provider endpoints.

Prefer explicit provider methods such as:

```text
contract_klines(symbol, ...)
mark_price_klines(symbol, ...)
index_price_klines(pair, ...)
```

Share only genuinely identical private pagination/transport helpers.

Principle:

```text
reuse implementation
but do not merge distinct protocol semantics
```

Add hermetic recorded/provider-contract tests asserting:

```text
endpoint
parameter names
pagination
response shape validation
normalization
```

for each data family independently.

---

# 14. HIGH-7 — Separate Capability Envelope From Effective Runtime Mode

Do not mix:

```text
What can this provider/market support?
```

with:

```text
What is this run actually using?
```

Formalize:

```text
Provider/Market Capability Envelope
```

and:

```text
Effective Trading Profile
```

Capability may contain sets:

```text
supported_position_modes
supported_margin_modes
supported order shapes
```

Effective Trading Profile must contain exactly one effective value:

```text
position_mode = NETTING | HEDGING
margin_mode   = CROSS | ISOLATED
```

Compilation:

```text
Capability Envelope
+
Requested Trading Profile
+
Account-effective constraints
        ↓ validate
Effective Trading Profile
        ↓
CompiledMarketPolicy
```

A single compiled policy/run must not carry contradictory effective mode authorities.

---

# 15. Effective Trading Profile Is Run Semantics

Changing:

```text
NETTING → HEDGING
```

or:

```text
CROSS → ISOLATED
```

must not create a new Strategy Revision.

But it must produce a different runtime/economic identity.

Ensure effective trading profile semantics participate in the appropriate market composition/run fingerprint.

Required principle:

```text
same Strategy Revision
+
different effective trading profile
=
different Run semantics / evidence identity
```

---

# 16. Universal Margin Requirement Function Closure

Do not add Binance wire fields such as `cum` directly to Core.

The universal economic concept is:

```text
Notional → Required Initial Margin
Notional → Required Maintenance Margin
```

Represent this as a deterministic provider-neutral piecewise function capable of expressing both simple fixed-rate futures and Binance effective bracket semantics.

Conceptually:

```text
OnlyCompiledMarginRequirementCurve

segments:
    lower_bound
    upper_bound
    initial_slope
    initial_intercept
    maintenance_slope
    maintenance_intercept
```

For segment `i`:

```text
InitialMargin(N)      = aᵢ * N + bᵢ
MaintenanceMargin(N) = cᵢ * N + dᵢ
```

Use repository naming/style as appropriate.

The semantic model must remain provider-neutral.

---

# 17. Margin Curve Invariants

Core validates universal mathematical properties, not Binance DTO details.

At minimum:

```text
segments ordered
segments non-overlapping
valid domain covered
no ambiguous segment selection
required margin >= 0
maintenance <= initial where required
canonical identity deterministic
equivalent semantics → equivalent identity
semantic change → new identity
```

The Binance Market Product/compiler must prove provider bracket data compiles into an equivalent canonical curve.

---

# 18. Margin Conformance Tests

Test exact requirement boundaries:

```text
tier boundary - epsilon
tier boundary
tier boundary + epsilon
```

Preserve and extend durable tests for:

```text
open
partial open
partial close
full close
multiple opening reservations
long PnL
short PnL
maintenance requirement
checkpoint / restore
```

Do not regress the existing proportional release behavior based on original occupied-margin authorities.

---

# 19. Semantic Uniqueness — Remove `LONG_ONLY` As A Position Mode Authority

Canonical position mode should converge to:

```text
NETTING
HEDGING
```

Long-only market behavior belongs to short policy:

```text
PositionMode = NETTING
ShortPolicy = DISABLED
```

Do not preserve two canonical ways to express the same trading constraint.

Keep migration bounded; do not rewrite unrelated market models.

---

# 20. Canonical Target Exposure Integration Boundary

The existing target-exposure planner is directionally correct.

Define the product-facing architecture:

```text
Strategy Revision
        ↓
Economic Target
        ↓
Portfolio / Sizing
        ↓
Canonical Intent Planner
        ↓
OnlyExecutionIntent
        ↓
Order Planning
```

A provider must never interpret a raw `SELL` as either close-long or open-short.

For this closure:

1. define the authoritative integration boundary;
2. ensure futures-capable product paths preserve canonical economic intent;
3. retain `OnlyOffset` as compatibility ingress only;
4. downstream new authoritative logic consumes `OnlyExecutionIntent`.

Do not redesign the full Strategy or Portfolio framework.

---

# 21. Preserve `OnlyOffset` Only As Compatibility

Required direction:

```text
legacy input
    OnlyOffset
        ↓
normalization
        ↓
OnlyExecutionIntent
        ↓
authoritative downstream logic
```

Do not maintain Offset and canonical PositionEffect/CloseScope as equal authorities.

Version serialization/snapshots if meaning changes.

---

# 22. Synthetic Futures Is The Anti-Binance Proof

Keep and strengthen the hermetic non-Binance Futures Market Product.

Its purpose is to prove:

```text
Futures semantics
!=
Binance semantics
```

Extend synthetic conformance as needed to cover:

```text
NETTING + CROSS
NETTING + ISOLATED
HEDGING + CROSS
HEDGING + ISOLATED
```

without provider branches.

Synthetic Futures must use the same:

```text
BacktestRuntime
Trading Kernel
Position Authority
Margin Authority
Account Authority
checkpoint/replay architecture
```

---

# 23. Required Test Layers

Do not treat unit tests as provider closure.

## Layer 1 — Universal Semantic Tests

No Binance dependency.

Cover:

```text
ExecutionIntent
TargetExposure
Position
Margin
Funding
Settlement
ReduceOnly
NETTING
HEDGING
CROSS
ISOLATED
identity
checkpoint/recovery
```

Purpose:

```text
Does Core implement universal economics correctly?
```

## Layer 2 — Provider Contract Tests

Use deterministic recorded provider-response fixtures.

Cover raw USD-M contracts needed by current scope, including:

```text
instrument/reference metadata
funding schedule information
funding history
contract kline
mark-price kline
index-price kline
margin/account bracket inputs if applicable
```

Verify:

```text
endpoint
parameter names
response shape
semantic discriminator behavior
normalization
raw evidence identity
normalized identity
fail-closed behavior
```

Purpose:

```text
Does Binance raw reality compile correctly?
```

## Layer 3 — Assembled Runtime Conformance

This is the final Acceptance Authority.

Use normal assembly:

```text
entry point discovery
        ↓
DataSourceFactory
        ↓
MarketProductFactory
        ↓
ResolvedMarketProductBinding
        ↓
BacktestRuntime
        ↓
TradingKernel
```

Do not construct final conformance by directly instantiating a USD-M compiler.

Purpose:

```text
Does the actual OnlyAlpha product path work?
```

---

# 24. Final Cross-Market Conformance Matrix

At minimum prove:

| Capability | Binance Spot | Binance USD-M | Synthetic Futures |
|---|---:|---:|---:|
| LONG OPEN | PASS | PASS | PASS |
| LONG CLOSE | PASS | PASS | PASS |
| SHORT OPEN | explicit fail-closed | PASS | PASS |
| SHORT CLOSE | explicit fail-closed | PASS | PASS |
| REDUCE_ONLY | canonical/N/A | PASS | PASS |
| NETTING | PASS | PASS | PASS |
| HEDGING | N/A | PASS if declared supported | PASS |
| CROSS | N/A | PASS | PASS |
| ISOLATED | N/A | PASS if declared supported | PASS |
| Funding | N/A | PASS | N/A |
| Daily variation margin | N/A | N/A | PASS |
| Partial fill | PASS | PASS | PASS |
| Duplicate fill | PASS | PASS | PASS |
| Duplicate economic fact | PASS | PASS | PASS |
| Checkpoint recovery | PASS | PASS | PASS |
| Deterministic replay | PASS | PASS | PASS |

`N/A` must mean explicit unsupported capability with fail-closed behavior where requested, not silent omission.

---

# 25. Recovery Equality

For derivative assembled conformance prove:

```text
Run A:
start → all events → final world
```

is canonically equal to:

```text
Run B:
start
→ partial events
→ checkpoint
→ simulated process stop
→ restore
→ remaining events
→ final world
```

Compare all relevant state authorities:

```text
Orders
Positions
Allocations
Margin reservations
Account
Strategy ledger
Funding applications
Settlement applications
Execution transaction ledger
Economic facts
Dataset/replay cursor
Evidence/fingerprint outputs
```

Required:

```text
World A == World B
```

---

# 26. Provider Boundary Assertions

Before closure prove:

1. no Binance-specific branch exists in Trading Kernel business logic;
2. no Binance wire DTO leaks into Core canonical contracts;
3. provider API changes remain isolated to Binance provider/market packages;
4. removing Binance plugin does not make Core unable to express Futures;
5. Synthetic Futures requires no Binance code;
6. USD-M product assembly is discoverable and not dependent on direct test constructors.

---

# 27. Identity Assertions

Prove:

```text
same provider evidence
→ same normalized reference
→ same authority identity

different behavior-affecting reference
→ different authority identity

same effective trading profile
→ same profile identity

different position/margin mode
→ different run/composition identity

same immutable Backtest inputs
→ same final evidence fingerprint
```

Do not put non-semantic wall-clock noise into identity unless that value changes authority behavior.

---

# 28. Fail-Closed Requirements

Fail closed for at least:

```text
unknown provider reference semantic
unknown funding rate type
missing required exact funding reference
missing effective margin profile
unsupported position mode
unsupported margin mode
invalid provider reference coverage
ambiguous authority
unsupported liquidation path
incompatible persisted schema
```

Never silently substitute:

```text
trade price for required mark price
sampled mark kline for exact funding mark when exact evidence exists
default funding interval when a provider override applies
NETTING when HEDGING was requested
CROSS when ISOLATED was requested
```

---

# 29. Implementation Sequence

Do the work in bounded dependency order.

Avoid another single giant closure change if possible.

## P9.UC1 — USD-M Market Product Assembly Closure

Implement:

```text
market package
factory
entry point
resolved binding
assembly tests
package metadata
version sync
```

Stop when normal discovery/assembly works.

## P9.UC2 — Immutable Binance USD-M Reference Authority

Implement:

```text
provider raw reference capture
raw evidence hashing
normalized market reference snapshot
reference publication/store if consistent with existing architecture
coverage identity
authority fingerprint
```

Do not mix account-effective private margin state with public market reference.

## P9.UC3 — Funding Exactness Closure

Implement:

```text
exact funding-boundary mark evidence
funding-rate fact
funding schedule reference
provider semantic discriminator validation
deterministic lineage
```

Reuse existing economic-fact recovery infrastructure.

## P9.UC4 — Universal Margin Requirement Function Closure

Upgrade canonical margin representation only as needed to exactly represent:

```text
Synthetic Futures
Binance USD-M effective margin input
```

Use a universal deterministic piecewise requirement function.

Version/migrate affected state explicitly.

## P9.UC5 — Effective Position/Margin Mode Closure

Separate capability envelope from effective profile.

Make effective:

```text
position_mode
margin_mode
```

part of runtime composition identity.

Prove no silent fallback.

## P9.UC6 — Semantic Uniqueness Cleanup

Bounded cleanup:

```text
remove duplicate LONG_ONLY authority
formalize TargetExposure → Intent integration boundary
retain Offset only as compatibility ingress
```

Do not redesign Strategy/Portfolio broadly.

## P9.UC7 — Cross-Market Evidence Closure

Run final:

```text
Binance Spot
Binance USD-M
Synthetic Futures
```

assembled conformance.

Run checkpoint/recovery equality.

Run affected validation.

Perform bounded Independent Review.

Stop when:

```text
Critical = 0
High = 0
```

---

# 30. Packaging / Dependency Direction

If a new package or entry point is introduced, maintain:

```text
workspace configuration
lock file
version sync
package metadata
entry-point discovery tests
distribution smoke
```

Do not introduce circular dependencies.

Core must never import concrete Binance implementations.

Preferred direction remains:

```text
Core contracts
↑
Market Product

Core Plugin SPI
↑
Provider Plugin
```

Use explicit normalized contracts at boundaries rather than implementation cross-imports that collapse ownership.

---

# 31. Schema / Fingerprint Version Discipline

If semantic meaning changes, explicitly version affected contracts such as:

```text
market reference snapshot
authority identity
compiled market policy
margin requirement curve
effective trading profile
dataset/economic binding
checkpoint state
broker/order schemas
```

Never reuse an old semantic version while changing meaning.

Historic persisted state must either:

```text
migrate deterministically
```

or:

```text
fail closed as incompatible
```

No silent reinterpretation.

---

# 32. Validation

Follow `AGENTS.md`.

At minimum execute actual validation for:

1. targeted unit tests for each closure task;
2. provider contract tests;
3. Market Product discovery/assembly tests;
4. affected Ruff checks;
5. affected Ruff format checks;
6. affected mypy;
7. package/version/lock validation;
8. nearest affected canonical test lanes;
9. cross-market conformance;
10. checkpoint/recovery tests;
11. architecture/import-boundary checks;
12. bounded Independent Review.

Do not claim PASS because test files exist.

Report commands actually executed and their results.

Do not run expensive unrelated repository-wide jobs unless the true Impact Scope requires them.

---

# 33. Independent Review Scope

Review only Modification Scope + real Impact Scope.

Search specifically for:

```text
Binance leakage into Core
duplicate market authority
duplicate position-mode authority
provider DTO leakage
manual reference fixtures in product path
behavior outside identity
funding mark approximation
funding schedule hardcoding
incorrect provider endpoint parameters
lossy margin-bracket compilation
silent NETTING/CROSS fallback
missing checkpoint state
replay nondeterminism
schema/fingerprint silent incompatibility
Spot regression
```

Do not restart an unrelated repository-wide audit.

---

# 34. Forbidden Fixes

Do not solve findings with shortcuts such as:

```python
if provider == "BINANCE":
    ...

if instrument_type == CRYPTO_PERPETUAL:
    # Binance-specific accounting behavior
```

Do not:

- put `/fapi/*` concepts in Core;
- add `BinanceCum` or Binance bracket DTO fields to canonical Core objects;
- add `BINANCE_HEDGE_MODE` to Core;
- move Account authority into a plugin;
- move Margin authority into Simulated Broker;
- infer missing exact provider evidence;
- preserve duplicate authorities for convenience;
- weaken assertions;
- xfail real regressions;
- use sleeps or retry-until-green;
- rewrite unrelated modules;
- introduce speculative Options/COIN-M abstractions;
- begin LIVE implementation.

---

# 35. Definition of Done

The task is complete only when this statement is true:

```text
A Binance USD-M Backtest can be configured and assembled through
normal OnlyAlpha Runtime contracts.

Its provider rules are captured as immutable evidence,
compiled into provider-neutral canonical policy,
executed through the same Trading Kernel,
and persisted/replayed deterministically.

A synthetic non-Binance Futures market uses the same Core
without any provider-specific branch.

Spot remains unchanged.

Critical = 0.
High = 0.
```

---

# 36. Expected Final Architecture

```text
                        ONLYALPHA CORE
                             │
                 Universal Trading Semantics
                             │
            ┌────────────────┼────────────────┐
            │                │                │
         Research         Backtest        Future SIM/LIVE
                             │
                     One Trading Kernel
                             │
               Position / Margin / Account
                             │
                 Canonical Market Policy
                             │
                Effective Trading Profile
                             │
                Market Product Composition
                             │
       ┌─────────────────────┼──────────────────────┐
       │                     │                      │
Binance Spot          Binance USD-M          Synthetic Future
Market Product        Market Product         Market Product
       │                     │
       └──────────── Binance Provider ──────────────
                     raw external world
```

---

# 37. Final Decision Rule

For every field or behavior ask:

```text
Can this change because the provider,
broker, venue, regulation, protocol,
account configuration, or market rule changes?
```

If YES:

```text
Provider / Adapter / Gateway / Market Product / Effective Profile
```

Then ask:

```text
What is the stable universal economic meaning?
```

Only that stable meaning may enter Core.

Examples:

```text
Binance positionSide
→ Provider

PositionSide
→ Core

Binance fundingIntervalHours
→ Provider Reference

FundingPolicy.interval_seconds
→ Core canonical value

Binance leverage-bracket DTO
→ Provider

Piecewise required-margin function
→ Core

Binance index-price request parameter
→ Provider

ReferencePriceKind.INDEX
→ Core
```

The task succeeds when provider variability is absorbed at the boundary and universal deterministic semantics remain stable.

---

# 38. Final Report Format

When complete, return:

## 1. Mainline Baseline

Actual starting HEAD.

## 2. Changes By Closure Task

```text
UC1
UC2
UC3
UC4
UC5
UC6
UC7
```

## 3. Authority Changes

Explain final ownership for:

```text
market reference
effective trading profile
compiled market policy
position
margin
account
funding
dataset/evidence
```

## 4. Schema / Fingerprint Changes

List all version increments and migrations.

## 5. Provider Boundary Evidence

Explain why Binance-specific behavior remains outside Core.

## 6. Conformance Matrix

Report actual PASS/FAIL/N/A.

## 7. Recovery / Determinism Evidence

Report uninterrupted versus checkpoint/restore equality.

## 8. Validation Commands

List actual commands executed and results.

## 9. Independent Review Findings

Report:

```text
Critical
High
Medium
Low
```

## 10. Final Gate

Only declare:

```text
P9.U CLOSED
```

when:

```text
Critical = 0
High = 0
```

Otherwise declare:

```text
P9.U NOT CLOSED
```

and list only concrete remaining blockers.

Do not produce another speculative unlimited audit.
