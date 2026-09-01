# OnlyAlpha Codex Task Prompt

## Task Title

**P9.U — Universal Spot/Futures Research & Backtest Semantic Closure**

---

## 0. Task Intent

This is an **architecture-level high-risk engineering task** for the OnlyAlpha repository.

The goal is **not** to "add Binance Futures support" as a provider feature.

The goal is to complete the first production-grade, market-agnostic trading semantic envelope in OnlyAlpha so that the same:

- Research framework
- Strategy semantics
- Dataset semantics
- Trading Kernel
- Portfolio path
- Risk path
- Order / Execution path
- Position authority
- Margin authority
- Account / Accounting authority
- Backtest Runtime
- Deterministic simulated execution path
- Persistence / Checkpoint / Replay / Evidence path

can correctly support both:

1. **Cash / Spot trading semantics**
2. **Margined Derivative / Futures trading semantics**

without introducing provider-specific or market-specific branches into Core.

Binance Spot and Binance USDⓈ-M Perpetual are only the first real provider/product implementations used to prove the architecture.

The architectural target is:

```text
New Market / New Broker / New Country / New Futures Exchange
                    ↓
          Plugin / Market Product
                    ↓
       Canonical OnlyAlpha Contracts
                    ↓
             Existing Core

Expected mature-state result:

Trading Kernel ΔLOC ≈ 0
```

This task must preserve the founding principles of:

- Uniqueness
- Determinism
- Market-agnostic Core
- Single Authority
- Reproducibility
- Fail-Closed
- Explicit Boundaries
- Recoverability
- Traceability

---

# 1. Mandatory Read Order

Before planning, editing code, creating tests, drafting ADRs, or changing contracts, read and understand repository context in this exact order:

1. `PROJECT_CONSTITUTION.md`
2. Relevant Architecture / public Contracts
3. Relevant Accepted ADRs
4. Current Roadmap / P9 execution documents
5. `AGENTS.md`
6. Current source code
7. Current tests
8. Current executable behavior

At minimum inspect the current implementations around:

```text
src/onlyalpha/domain/
src/onlyalpha/market/
src/onlyalpha/market/product/
src/onlyalpha/execution/
src/onlyalpha/transaction/
src/onlyalpha/order/
src/onlyalpha/position/
src/onlyalpha/margin/
src/onlyalpha/account/
src/onlyalpha/fee/
src/onlyalpha/broker/
src/onlyalpha/plugin/
src/onlyalpha/data/
src/onlyalpha/research/
src/onlyalpha/strategy/
src/onlyalpha/runtime/backtest/
src/onlyalpha/runtime/persistence/

packages/provider/onlyalpha-plugin-binance/
```

Also read the current tests for these subsystems.

Do not infer desired architecture from current implementation limitations.

Always separate:

```text
Normative Truth
= Constitution / Architecture / Contract / Accepted ADR

Implementation Truth
= current code / tests / runtime behavior
```

---

# 2. Owner-Level Sequencing Decision

The repository currently contains ADR 0099 with the post-Spot preferred sequence:

```text
Binance Spot
→ QMT Market Data
→ Binance USD-M Futures
→ ...
```

The repository owner is now explicitly changing the next engineering priority.

The new intended sequence is:

```text
Completed / existing Spot foundation
        ↓
Universal Spot/Futures Research + Backtest Semantic Closure
        ↓
Binance USD-M as first Futures conformance plugin
        ↓
Cross-market conformance
        ↓
later Web / SIM / LIVE / QMT / CTP / Agent work
```

This sequencing change:

```text
Constitution Impact = NO
```

because it does not weaken or reinterpret the Constitution.

Before implementation:

- determine the repository's ADR governance mechanism;
- add the minimum required sequencing ADR / execution-plan update;
- supersede only the sequencing part that conflicts with the new owner decision;
- do **not** weaken existing market-agnostic, authority, determinism, recovery, or safety requirements;
- if repository governance does not permit Codex to finalize an accepted ADR directly, create the correct `PROPOSED` ADR and report the exact owner action required before continuing;
- do not silently implement against a conflicting Accepted ADR.

Do not modify `PROJECT_CONSTITUTION.md`.

---

# 3. Formal Task Contract

## Goal

Complete the OnlyAlpha **universal Spot/Futures Research and Backtest semantic foundation** so that Cash/Spot and Margined Derivative/Futures trading are represented by one canonical model and executed by one shared Backtest/Trading Kernel path.

The implementation must prove that market/provider differences are compiled by Market Product / Plugin boundaries rather than embedded in Core.

---

## Modification Scope

Expected modification scope may include:

```text
domain
market
market/product
execution
transaction
order
position
margin
account
fee/accounting
broker canonical contracts
plugin SPI
data SPI
dataset / immutable evidence contracts
strategy execution-facing semantics
research input contracts
backtest runtime
simulated broker
runtime persistence
checkpoint / replay
Binance provider plugin
architecture / ADR / execution-plan documents
directly affected tests
```

Only expand beyond this scope where a real dependency proves it necessary.

Do not start unrelated repository-wide refactors.

---

## Expected Impact Scope

This task touches high-risk architectural areas:

```text
canonical trading semantics
Authority
execution correctness
position state
margin state
account state
PnL/accounting
persistence
checkpoint/replay
public contracts
plugin boundaries
determinism
identity/fingerprints
research/backtest reproducibility
```

Treat it as a **high-risk task** under `AGENTS.md`.

A bounded Independent Review is required before completion.

---

## Required Behavior

The completed system must support, through canonical market-neutral semantics:

### Cash / Spot

```text
LONG
OPEN
CLOSE
NETTING
no margin
cash-for-asset exchange
fee accounting
```

### Margined Derivatives / Futures

```text
LONG
SHORT
OPEN
CLOSE
NETTING
HEDGING
CROSS margin
ISOLATED margin
margin reservation / consumption / release
realized PnL
unrealized PnL / valuation basis
REDUCE_ONLY semantics
reference prices
funding-rate facts
funding cashflows
futures settlement / daily mark-to-market vocabulary
```

Unsupported economic combinations must remain fail-closed.

---

## Acceptance Tests

The task is not complete until deterministic tests prove at least:

```text
Spot BUY OPEN
Spot SELL CLOSE
Spot SHORT rejected

Futures LONG OPEN
Futures LONG CLOSE
Futures SHORT OPEN
Futures SHORT CLOSE

partial fill correctness
duplicate fill idempotency
reduce-only cannot increase exposure

insufficient cash rejected
insufficient margin rejected

NETTING correctness
HEDGING correctness

CROSS margin correctness
ISOLATED margin correctness

realized PnL correctness
unrealized valuation correctness

funding payer correctness
funding receiver correctness

daily mark-to-market / settlement test fixture correctness

checkpoint → restore → continue
equals uninterrupted execution

same immutable inputs
→ same state
→ same evidence
→ same fingerprints

Binance Spot regression = 0

Binance USD-M conformance passes

non-Binance synthetic futures Market Product passes

no provider-specific Core branch required
```

---

## Out of Scope

Do not turn this task into total production trading closure.

The following are **not completion gates**:

```text
Binance Futures Mainnet execution
full LIVE Runtime certification
complete Binance liquidation emulation
COIN-M Futures
Options
full QMT integration
real CTP integration
Web productization
Agent implementation
production autonomous LIVE trading
```

Provider-specific liquidation behavior that is not correctly modeled must fail closed rather than be approximated.

---

## Stop Condition

Stop implementation when:

```text
Required Behavior implemented
+ Acceptance Tests PASS
+ affected canonical validation PASS
+ schema / fingerprint migrations correct
+ checkpoint / replay determinism PASS
+ Spot regression PASS
+ provider-neutral architecture PASS
+ bounded Independent Review complete
+ Critical findings = 0
+ High findings = 0
+ Constitution consistency PASS
```

Do not restart unlimited auditing after these conditions are satisfied.

---

## Constitution Impact

```text
NO
```

If implementation appears to require weakening or changing the Constitution:

```text
STOP
REPORT: PLAN_CONFLICT
```

---

# 4. Core Architecture Freeze

## 4.1 Never Create Separate Spot and Futures Kernels

Forbidden architecture:

```text
SpotBacktestEngine
FuturesBacktestEngine

SpotPositionManager
FuturesPositionManager

SpotExecutionEngine
FuturesExecutionEngine

if provider == "BINANCE"
if market == "BINANCE_USDM"
if exchange == "SHFE"
```

inside canonical Core business logic.

Required architecture:

```text
Strategy Revision
      ↓
Canonical Economic Intent
      ↓
Portfolio
      ↓
Risk
      ↓
Canonical Execution Intent
      ↓
Compiled Market Policy
      ↓
Trading Kernel
      ↓
Order / Position / Margin / Account
      ↓
Broker Port
```

Market/provider differences terminate before or at Plugin / Market Product / Broker Adapter boundaries.

---

# 5. Preserve and Strengthen Existing Market Product Architecture

The repository already contains the correct architectural direction around:

```text
OnlyResolvedMarketProductBinding

Reference Authority
Policy Compiler
Market Fee Pack
Composition Identity
```

and:

```text
OnlyCompiledMarketPolicy
```

Do not create a parallel second Market Profile authority.

The intended flow is:

```text
Provider Raw Reference
        ↓
Market Reference Authority
        ↓
Immutable Reference Snapshot
        ↓
Market Policy Compiler
        ↓
OnlyCompiledMarketPolicy
        ↓
OnlyMarketRuleEngine
        ↓
Trading Kernel
```

The Market Product composition fingerprint must remain part of reproducibility and persistence identity.

---

# 6. Canonical Trading Intent Must Have One Authority

Current code contains overlapping concepts such as:

```text
OnlyOffset
OnlyPositionEffect
```

Do not allow these to become two permanent authorities for the same economic meaning.

Design and implement one canonical execution-facing semantic representation.

The conceptual dimensions should be orthogonal:

```text
OrderSide
    BUY
    SELL

PositionSide
    LONG
    SHORT

PositionEffect
    OPEN
    CLOSE
    AUTO

CloseScope
    ANY
    TODAY
    YESTERDAY

ExposureConstraint
    NONE
    REDUCE_ONLY
```

Names may differ if current repository conventions justify it, but the semantics must remain equivalent and non-overlapping.

Examples:

```text
Spot Buy
BUY + LONG + OPEN

Spot Sell
SELL + LONG + CLOSE

Futures Long Open
BUY + LONG + OPEN

Futures Long Close
SELL + LONG + CLOSE

Futures Short Open
SELL + SHORT + OPEN

Futures Short Close
BUY + SHORT + CLOSE

CTP-style Close Today
SELL + LONG + CLOSE + TODAY

Reduce-only Short Close
BUY + SHORT + CLOSE + REDUCE_ONLY
```

Do not encode provider field names in Core.

---

# 7. Compatibility Migration for Existing Offset Semantics

Do not perform an unnecessary destructive rewrite.

If `OnlyOffset` is already widely used:

1. preserve compatibility where required;
2. normalize it into the new canonical execution intent;
3. ensure downstream new code consumes one canonical semantic representation;
4. version public snapshots / serialization / fingerprints where meaning changes;
5. plan removal only when the compatibility surface is safely migrated.

Do not maintain two equal-authority semantic paths.

---

# 8. Strategy Must Express Economic Intent, Not Provider Operations

A strategy must not depend on:

```text
Binance positionSide
Binance reduceOnly
CTP OffsetFlag
QMT-specific fields
```

Avoid a permanent design where raw `SELL` ambiguously means either:

```text
close long
```

or:

```text
open short
```

depending on the market.

That would allow a plugin to reinterpret Strategy semantics.

Prefer an execution-facing strategy/portfolio intent that expresses desired exposure or target position, conceptually:

```text
LONG
FLAT
SHORT
```

or another deterministic target-exposure representation consistent with current Strategy Revision design.

The planner should convert:

```text
Current Position
+
Target Exposure
+
Position Mode
+
Market Policy
+
Flip Policy
```

into canonical execution intents.

Example:

```text
Current = FLAT
Target  = SHORT

Market short capability = enabled

→ SELL + SHORT + OPEN
```

For a long-only Spot market:

```text
Target = SHORT
→ fail closed
```

The plugin must never redefine the meaning of the Strategy Revision.

---

# 9. Normalize Position Mode Semantics

Avoid redundant authorities such as:

```text
LONG_ONLY as a Position Mode
```

if the same meaning is already expressible as:

```text
PositionMode = NETTING
ShortPolicy = DISABLED
```

Target conceptual structure:

```text
PositionMode:
    NETTING
    HEDGING

ShortPolicy:
    DISABLED
    ENABLED_WITH_BORROW
    ENABLED_UNRESTRICTED
```

Examples:

```text
Binance Spot
NETTING + short disabled

A-share cash
NETTING + short disabled

US margin equity
NETTING + borrow-constrained short

Binance USD-M one-way
NETTING + short enabled

Binance USD-M hedge mode
HEDGING + short enabled
```

Migrate carefully and preserve compatibility where required.

---

# 10. Extend Compiled Market Policy Into Complete Economic Policy

Do not create a new parallel policy authority.

Extend the existing `OnlyCompiledMarketPolicy` architecture as necessary to express all universal economics needed by Spot/Futures.

Expected semantic areas:

```text
instrument terms
session policy
price policy
quantity policy
order capability policy
position policy
short policy
settlement policy
margin policy
valuation policy
periodic cashflow / funding policy
notional policy
dynamic price requirements
```

Only add a Core concept when it is truly universal.

Provider-specific representations stay in the plugin.

---

# 11. Order Capability Policy

Market Product must be able to deterministically declare what execution semantics are legal.

Canonical policy should be able to constrain at least:

```text
supported order types
supported TIF
supported position effects
supported close scopes
reduce-only capability
possibly market/limit behavior required by current scope
```

The Runtime must reject an unsupported canonical request before handing invalid semantics to a provider.

---

# 12. Margin Must Be a Canonical Economic Model

Current simple fixed-rate margin behavior is not sufficient as the permanent abstraction.

Build a generic compiled margin policy capable of representing simple and tiered margin rules.

Conceptually:

```text
OnlyCompiledMarginPolicy

margin mode
    CROSS
    ISOLATED

collateral currency

requirement schedule
    tier(s)

initial requirement
maintenance requirement
valuation basis
```

A single fixed percentage is just a one-tier policy.

A provider such as Binance may compile leverage brackets into this canonical policy.

A traditional futures market may compile exchange/broker margin rates into the same canonical model.

Core must not know Binance leverage bracket DTOs.

---

# 13. Leverage Is Not the Core Economic Authority

Do not make:

```text
leverage = 10
```

the principal universal accounting model.

Instead:

```text
Provider Account / Contract Configuration
        ↓
Plugin / Market Product Compiler
        ↓
Effective Initial Margin Requirement
Effective Maintenance Margin Requirement
        ↓
Core
```

If leverage is useful as configuration or evidence, retain it at the appropriate contract boundary, but canonical risk/accounting decisions must be driven by effective economic requirements.

---

# 14. Separate Cash Exchange From Margined Derivative Economics

Do not encode:

```text
BUY always requires full notional cash
```

as a permanent universal rule.

Required universal economic distinction:

```text
Cash Exchange
vs
Margined Derivative
```

Cash exchange example:

```text
BUY

cash -= notional
asset position += quantity
fee -= commission
```

Margined derivative open example:

```text
OPEN

cash does not exchange full notional
margin is reserved/used
position quantity changes
fee is charged
```

Refactor pre-trade funding requirements so the result is produced by canonical compiled economic policy, not by hardcoded Spot assumptions.

A decision should be able to derive:

```text
required_cash
required_position
required_margin
```

from the effective canonical market/economic policy.

---

# 15. Margin Reservation Is Not Cashflow

Preserve this distinction:

```text
Margin reservation / used margin
≠
cash expense
```

Account and Margin authorities must remain separate but consistent.

Expected account/economic vocabulary must be able to represent at least:

```text
deposit
withdrawal
trade notional exchange
fee
realized PnL
funding cashflow
variation margin / settlement where applicable
```

Do not force derivative PnL/funding into `TRADE_BUY` / `TRADE_SELL`.

Version schema/serialization where necessary.

---

# 16. Futures Position Accounting

The same durable transaction path must support:

## Long Open

```text
BUY + LONG + OPEN
→ pre-trade risk
→ margin requirement
→ margin reservation
→ order
→ fill
→ long position increase
→ used margin increase
→ commission
→ account/equity update
```

## Short Open

```text
SELL + SHORT + OPEN
→ same generic path
```

## Long Close

```text
SELL + LONG + CLOSE
→ quantity reduction
→ cost basis
→ realized PnL
→ proportional margin release
→ fee
→ account update
```

## Short Close

```text
BUY + SHORT + CLOSE
→ same generic path
```

Partial fills must proportionally consume/release reservations.

Duplicate fills must produce zero duplicate economic effect.

---

# 17. REDUCE_ONLY Semantics

`REDUCE_ONLY` must be modeled as an exposure constraint, not as a provider flag.

Invariant:

```text
A reduce-only execution must never increase absolute exposure.
```

It must fail closed if the requested execution could:

- open a new position;
- cross through zero into the opposite side;
- increase the targeted leg in hedge mode;
- otherwise increase risk/exposure.

Provider plugins translate the canonical constraint into provider parameters when the provider has such a field.

---

# 18. NETTING and HEDGING

Support both canonical position modes.

## NETTING

One net economic position per account/instrument scope.

The planner and position authority must deterministically handle:

```text
flat → long
flat → short
long → smaller long
long → flat
short → smaller short
short → flat
```

Position flips must obey explicit `OnlyPositionFlipPolicy` or its canonical successor.

No implicit flip semantics.

## HEDGING

Long and short legs may coexist independently.

Orders must identify the intended `PositionSide`.

Do not infer hedge-leg ownership from BUY/SELL alone.

---

# 19. CROSS and ISOLATED Margin

## CROSS

A shared account collateral pool backs eligible positions.

The Margin authority must derive:

```text
collateral
used initial margin
maintenance margin
available margin
```

at the appropriate account scope.

## ISOLATED

Maintain a distinct margin bucket per canonical isolation scope, normally position/instrument/leg depending on the normalized model.

The plugin defines concrete market rules.

Core owns canonical margin state.

Do not allow Binance plugin code to become the canonical margin ledger.

---

# 20. Reference Price Facts

Introduce or complete canonical reference-price semantics.

Do not conflate:

```text
trade price
mark price
index price
settlement price
```

Create/extend a canonical fact family conceptually equivalent to:

```text
ReferencePriceFact

instrument_id
kind
    MARK
    INDEX
    SETTLEMENT
value
event time
source identity
source sequence
data version
fact identity
```

Provider-specific names stay in plugins.

---

# 21. Funding Rate and Funding Cashflow Are Different Authorities

Required split:

```text
FundingRateFact
= Market Fact

FundingCashflow
= Accounting Fact
```

A FundingRate fact must not directly mutate account state.

Accounting derives a FundingCashflow from immutable inputs such as:

```text
funding rate
position held at funding boundary
canonical valuation price
contract multiplier
funding policy
timestamp / boundary rule
```

Do not model funding as commission.

Ensure payer/receiver sign conventions are explicit and deterministic.

---

# 22. Traditional Futures Daily Mark-to-Market

Binance USD-M Perpetual must not become the definition of "Futures".

Use the existing futures settlement vocabulary where appropriate and ensure the canonical model can represent traditional futures daily mark-to-market / variation-margin semantics.

A real CTP integration is out of scope, but a non-Binance deterministic test Market Product must prove the generic model.

---

# 23. Synthetic Non-Binance Futures Conformance Product

Create a hermetic test-only or reference conformance Market Product that does not access the network.

Example characteristics:

```text
TEST venue
Linear Future
Long + Short
NETTING
Cross Margin
Daily Mark-to-Market
No Funding
Expiration
deterministic trading session
deterministic fee model
deterministic margin model
```

Optionally add targeted fixtures for:

```text
HEDGING
ISOLATED margin
Close Today / Close Yesterday
```

This test product exists to catch accidental Binance-specific assumptions.

Core must not require modification to support it.

---

# 24. Research Must Consume Canonical Facts

Research must not depend on provider DTOs.

Research / factor input contracts may consume canonical data families such as:

```text
Bar
Trade
Quote
ReferencePrice
FundingRate
```

A strategy that only needs 1-minute bars should still be able to run without provider-specific futures concepts.

If a strategy explicitly needs funding or basis data, the Strategy Revision input contract must declare those inputs.

---

# 25. Separate Strategy Inputs From Kernel Economic Inputs

This distinction is mandatory.

Backtest data requirements are:

```text
Strategy Market Inputs
+
Kernel Economic Inputs
```

Example:

A Strategy Revision requires only:

```text
1m Bar
```

But a perpetual Market Product may require for correct accounting:

```text
Mark Price
Funding Rate
```

The Runtime must derive those extra economic data requirements from the effective Market Product.

Do not require the strategy author to request economic data that exists only to make the Trading Kernel correct.

Missing required kernel economic facts must fail closed.

---

# 26. Extend Historical Data SPI Canonically

Current Backtest flow is strongly oriented around historical bars.

Extend the DataSource SPI using canonical fact requests rather than provider-specific request classes.

The abstraction must be able to retrieve required historical fact families such as:

```text
BAR
REFERENCE_PRICE
FUNDING_RATE
SETTLEMENT
```

Add only the minimum families actually required by this task.

Forbidden Core interfaces:

```text
BinanceFundingRequest
BinanceMarkPriceRequest
```

Such provider DTOs may exist only inside the Binance plugin.

---

# 27. Dataset Snapshot / Immutable Evidence

Research and Backtest must remain reproducible from immutable inputs.

Extend Dataset Snapshot / manifest semantics as required so a Futures backtest can bind immutable revisions/fingerprints for:

```text
historical bars
reference prices
funding rates
instrument reference
calendar/session reference
market-product composition
canonical ordering/version
other economic fact families actually used
```

The formal Backtest identity must be reconstructable from:

```text
Kernel version
Strategy Revision
Dataset Snapshot
Runtime configuration
Market Product composition fingerprint
initial state
ordered canonical facts
```

Do not allow a mutable provider/database query to become the only semantic definition of a result.

---

# 28. Preserve One Backtest Runtime

Do not create:

```text
OnlyFuturesBacktestRuntime
OnlySpotBacktestRuntime
```

Use one:

```text
OnlyBacktestRuntime
OnlyBacktestRuntimeFactory
```

with different:

```text
Market Product
Dataset Snapshot
Account configuration
Strategy Revision
Simulated Broker configuration
```

The existing DataSource SPI + Broker SPI + Market Product assembly direction should be retained.

Refactor only where current Spot assumptions block universal semantics.

---

# 29. Generic Simulated Broker Boundary

Backtest must use a generic deterministic simulated Broker.

Do not use the Binance real Broker for backtesting.

Required boundary:

```text
Historical DataSource
        ↓
Canonical Market Facts

Market Product
        ↓
Canonical Market Policy

Generic Simulated Broker
        ↓
deterministic execution observations / fills

Trading Kernel
        ↓
Position / Margin / Account / Accounting
```

The Simulated Broker may own matching/execution simulation.

It must **not** become Position, Margin, or Account authority.

---

# 30. Broker Canonical Contract

Extend the canonical Broker order contract only with universal semantics actually required to translate orders correctly across providers.

The canonical broker-facing request must be able to preserve execution intent such as:

```text
side
position side
position effect
close scope
exposure constraint / reduce-only
order type
TIF
quantity
price
```

Do not include fields named after Binance or CTP wire parameters.

Provider mappings happen in plugin code.

Examples:

```text
Canonical Intent
→ Binance USD-M positionSide / reduceOnly / API fields

Canonical Intent
→ CTP Direction / OffsetFlag

Canonical Intent
→ future providers
```

---

# 31. Execution Capability Resolver

Preserve the current idea of an explicit deterministic support authority.

Do not simply delete unsupported checks.

Current execution support policy is intentionally limited.

Introduce a new explicit policy version when semantics expand.

Conceptually:

```text
Execution Support Policy v3
```

must explicitly certify newly supported shapes.

Examples:

```text
Cash + Long + Netting
Margined Derivative + Long + Netting
Margined Derivative + Short + Netting
Margined Derivative + Hedging
Open + Margin
Close + Margin Release
Reduce Only
```

Invalid or unimplemented combinations remain unsupported.

Do not silently mutate the meaning of an existing support-policy fingerprint/version.

---

# 32. Event Ordering Determinism

Futures introduces multiple canonical facts at possibly identical timestamps.

Define and test a deterministic canonical event ordering rule.

Ordering must not depend on:

```text
database row order
dict iteration order
wall clock
network completion order
Python incidental ordering
```

A stable order may use concepts such as:

```text
event timestamp
canonical event-class priority
provider/source sequence
canonical fact identity
```

Use the repository's existing event identity/order model where possible.

Critical boundary cases include:

```text
position open at funding timestamp
position close at funding timestamp
mark price and fill same timestamp
settlement boundary and trade same timestamp
```

The same immutable input set must always produce the same result.

---

# 33. Margin Breach / Liquidation

Do not invent inaccurate provider liquidation behavior.

If:

```text
maintenance requirement breached
```

and the effective Market Product does not provide a certified canonical liquidation model:

```text
FAIL CLOSED
```

The backtest must not silently continue as though liquidation cannot happen.

Use an explicit unsupported/failure result appropriate to current runtime architecture.

A complete provider-exact liquidation implementation is outside this task unless it becomes strictly necessary for a required conformance scenario and can be modeled generically.

---

# 34. Binance Plugin Role

Binance is a plugin implementation, not the architecture.

Expected internal plugin structure may evolve toward:

```text
onlyalpha_plugin_binance/
│
├── common/
│
├── spot/
│   ├── reference
│   ├── policy compiler
│   ├── historical datasource
│   ├── realtime datasource
│   └── broker
│
└── usdm/
    ├── reference
    ├── policy compiler
    ├── historical datasource
    ├── realtime datasource
    └── broker
```

Reuse only genuinely provider-common transport/auth/protocol infrastructure.

Do not force Spot and USD-M to share logic that is not actually common.

Do not copy USD-M rules into Core.

---

# 35. Binance USD-M Scope For This Task

For Research + Backtest conformance, prioritize:

```text
instrument / exchange reference
historical Kline
Mark Price history / reference
Index Price history / reference where needed
Funding Rate history
contract filters
margin-related reference required by compiled policy
canonical policy compilation
provider field translation tests
```

Real LIVE private execution is not the stage completion gate.

Broker contract changes needed for future USD-M correctness may be implemented now, but do not expand this task into full production LIVE certification.

---

# 36. Account / Position / Margin / Accounting Authority

Authority must remain explicit:

```text
Market Product
→ market/economic rules

Simulated/Real Broker
→ execution observations / external facts

Position component
→ canonical position state

Margin component
→ canonical margin state

Account/Accounting
→ canonical cash/equity/cashflow state
```

Never allow:

```text
Plugin maintains one margin truth
Core maintains another margin truth
```

or:

```text
Simulated Broker owns account state
```

or:

```text
Market Product mutates trading state
```

---

# 37. Persistence / Checkpoint / Replay

Any new semantic state required for Futures must participate in durable state and checkpoint/replay correctness.

Potential examples:

```text
position side / hedge leg
position effect
margin reservation state
cross/isolated margin state
valuation basis
funding boundary progress
funding cashflows
settlement progress
```

Required invariant:

```text
run from start to finish
==
run → checkpoint → crash → restore → continue
```

for the same immutable input sequence.

If schemas change:

- increment schema versions;
- add deterministic migration where required;
- reject unsupported incompatible state;
- never reinterpret old serialized state silently.

---

# 38. Identity / Fingerprint Discipline

Any semantic change affecting canonical identity must be versioned.

Examples may include:

```text
Order snapshot schema
Execution support policy version
Market policy fingerprint payload
Dataset manifest version
Checkpoint schema
Broker canonical request schema
Account/margin ledger schema
```

Never preserve an old version number while changing its meaning.

Equivalent semantics must converge to the same canonical identity.

Semantic change must create a new identity.

---

# 39. Required Conformance Matrix

Implement deterministic tests covering at least the following.

## Spot

```text
BUY OPEN long
SELL CLOSE long
SHORT rejected
cash conservation
fee accounting
```

## Futures Long

```text
open
partial open
close
partial close
realized PnL
margin reservation
margin release
fee
```

## Futures Short

```text
open
partial open
close
partial close
realized PnL
margin reservation
margin release
fee
```

## Reduce Only

```text
valid reduction
oversized reduction
cross-zero attempt
flat-position reduce-only
hedged-leg correctness
```

## Position Modes

```text
NETTING
HEDGING
flip policy behavior
```

## Margin

```text
CROSS
ISOLATED
insufficient margin
tier boundary if tiered policy is implemented
maintenance requirement calculation
```

## Funding

```text
long pays
long receives
short pays
short receives
zero position
open exactly at boundary
close exactly at boundary
duplicate funding fact
```

## Reference / Valuation

```text
Mark price drives unrealized valuation where policy requires it
trade price is not silently substituted when reference is required
missing mark/reference fact fails closed
```

## Settlement

```text
daily mark-to-market deterministic fixture
settlement state restoration
```

## Idempotency

```text
duplicate fill
duplicate provider/source event
replayed immutable fact
```

must not create double economic effects.

## Recovery

```text
checkpoint restore
replay
state fingerprint equality
evidence equality
```

## Cross-Provider Architecture

```text
Binance Spot
Binance USD-M
Synthetic non-Binance futures product
```

must all use the same Core semantic path.

---

# 40. Architecture Assertions

Before declaring completion, prove these assertions.

## Assertion 1

No Binance USD-M branch exists in canonical Core business logic.

## Assertion 2

Backtest Runtime does not know Binance-specific semantics.

## Assertion 3

Strategy semantics are not reinterpreted by provider plugins.

## Assertion 4

Changing Spot → Futures does not replace the Trading Kernel.

## Assertion 5

Market differences enter through canonical Market Product / Plugin contracts.

## Assertion 6

The synthetic non-Binance futures product requires no Core special case.

## Assertion 7

Deleting the Binance plugin leaves the Core model able to express:

```text
LONG
SHORT
OPEN
CLOSE
NETTING
HEDGING
Margin
PnL
Funding
Settlement
Reference Price
Reduce Only
```

## Assertion 8

Existing Spot semantics and tests do not regress.

## Assertion 9

No new parallel Authority was introduced for:

```text
execution intent
market policy
position
margin
account
dataset semantics
```

---

# 41. Anti-Patterns / Forbidden Implementations

Do not implement any of the following as a shortcut:

```python
if provider == "binance":
    ...

if market == "futures":
    ...

if instrument_type == CRYPTO_PERPETUAL:
    # provider/product-specific accounting hack
```

unless the branch is operating purely on a universal canonical semantic distinction and would remain correct for every market with that same economic property.

Do not:

- duplicate Market Product authority;
- duplicate Position authority;
- duplicate Margin authority;
- duplicate Account authority;
- use provider DTOs inside Core;
- let Strategy inspect provider identity;
- let Backtest use real-provider private execution semantics as its matching engine;
- use mutable database queries as formal Dataset Snapshot identity;
- silently drop Funding/Mark data because a Strategy did not request it;
- assume BUY always consumes full notional cash;
- treat Funding as Fee;
- treat Margin reservation as Cashflow;
- allow `REDUCE_ONLY` to increase exposure;
- silently approximate liquidation;
- weaken tests because implementation is difficult;
- use `sleep()` to prove correctness;
- use retry-until-green;
- skip/xfail real regressions;
- perform unrelated repository-wide cleanup;
- repeatedly re-audit already closed unrelated work.

---

# 42. Implementation Sequence

Follow dependency order.

Do not start with Binance USD-M endpoint coding.

## P9.U0 — Sequencing / Architecture Freeze

Deliver:

- sequencing ADR / execution plan update;
- semantic gap matrix;
- exact first-stage scope;
- explicit universal-vs-provider classification.

The semantic gap matrix must classify every needed concept into:

```text
Existing canonical concept
Missing universal canonical concept
Provider-specific concept
Out of scope
```

---

## P9.U1 — Canonical Semantic Uniqueness Closure

Resolve:

```text
OrderSide
PositionSide
PositionEffect
Offset overlap
CloseScope
ReduceOnly
PositionMode
ShortPolicy
Target exposure / planning semantics
```

Do not expand provider code yet.

---

## P9.U2 — Market Product Economic Policy Closure

Extend the existing compiled policy model to cover the universal economic requirements actually needed for:

```text
Spot
Linear Perpetual Futures
Traditional Linear Futures test fixture
```

including:

```text
order capability
margin
valuation/reference price
funding
settlement / daily MTM
```

---

## P9.U3 — Durable Execution / Position / Margin / Accounting Closure

Make the universal executable path real.

Implement and test:

```text
Long open/close
Short open/close
Netting
Hedging
Cross
Isolated
Margin reservation
Margin release
Realized PnL
Unrealized valuation
Funding cashflow
Reduce-only
partial fills
duplicate fills
```

Upgrade execution support policy version.

---

## P9.U4 — Research / Data / Dataset Closure

Extend immutable canonical data support for Futures economic facts.

Implement:

```text
ReferencePrice facts
FundingRate facts
Kernel economic data requirements
historical DataSource SPI
Dataset Snapshot manifest extensions
deterministic fact ordering
```

---

## P9.U5 — Generic Backtest Closure

Use the existing single Backtest Runtime architecture.

Prove:

```text
Spot
Synthetic Futures
```

using the same:

```text
Runtime
Trading Kernel
Generic Simulated Broker
Position
Margin
Account
Evidence
```

---

## P9.U6 — Binance USD-M Conformance Plugin

Implement the first real Futures provider/product plugin.

At minimum complete the Research/Backtest-facing requirements.

Provider-specific protocol and mappings stay inside the plugin.

---

## P9.U7 — Cross-Market Conformance / Final Closure

Run the full deterministic matrix against:

```text
Binance Spot
Binance USD-M
Synthetic non-Binance Futures
```

Perform bounded Independent Review.

Do not expand into QMT / CTP / Web / Agent after acceptance is met.

---

# 43. Validation Rules

Follow `AGENTS.md`.

At minimum run:

1. directly targeted tests;
2. affected Ruff check;
3. affected Ruff format check;
4. affected mypy where relevant;
5. nearest affected canonical test lane;
6. architecture / Constitution consistency checks;
7. high-risk专项 deterministic tests;
8. bounded Independent Review.

Do not automatically run every expensive repository-wide job unless the real Impact Scope requires it.

Use deterministic barriers, fake clocks, explicit event injection, and fault injection.

Never use sleeps as correctness evidence.

---

# 44. Independent Review Scope

Review only:

```text
Modification Scope
+
real Impact Scope
+
directly relevant Constitution / architecture invariants
```

Review specifically for:

```text
provider-specific Core leakage
duplicate semantic authority
duplicate state authority
illegal state transitions
margin/account conservation bugs
PnL sign errors
funding sign errors
position-side ambiguity
reduce-only violations
replay nondeterminism
schema/fingerprint silent incompatibility
checkpoint restore divergence
hidden mutable-input dependencies
fail-open behavior
Spot regression
```

Do not restart a general repository audit.

---

# 45. Required Final Report

At task completion, report only useful engineering facts.

Include:

## A. What Changed

Summarize by subsystem.

## B. Canonical Semantics Added / Changed

List the final authoritative model.

## C. Compatibility / Schema / Fingerprint Changes

List all version increments and migrations.

## D. Provider Boundary Proof

Explain why Binance-specific behavior remains in the plugin.

## E. Conformance Results

Report:

```text
Spot
Binance USD-M
Synthetic Futures
```

test results.

## F. Determinism / Recovery Evidence

Report checkpoint/replay equality evidence.

## G. Remaining Explicit Out-of-Scope Work

Only true follow-up items.

## H. Blocking Findings

Must be:

```text
Critical = 0
High = 0
```

to close.

Do not produce repeated speculative audit lists after Stop Condition is satisfied.

---

# 46. Final Engineering Target

When this task is complete, the architecture should effectively look like:

```text
                       OnlyAlpha Core
                            │
              Universal Trading Semantics
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
     Research            Backtest          future SIM/LIVE
                            │
                     Trading Kernel
                            │
             Position / Margin / Account
                            │
                  Canonical Broker Port
                            │
             Canonical Market Product
                            │
          ┌─────────────────┼─────────────────┐
          │                 │                 │
   Binance Spot       Binance USD-M      Future Plugins
      Plugin              Plugin
```

The primary architecture KPI is:

```text
Adding another market within the already-covered semantic envelope
must not require changes to the Trading Kernel.
```

The task is successful only if **Spot and Futures are two configurations of one canonical economic/trading model**, not two separate engines.

---

# 47. Most Important Decision Rule

For every implementation decision ask:

```text
Will this behavior change because the market,
exchange, broker, provider, regulation,
protocol, or vendor API changes?
```

If YES:

```text
Plugin / Adapter / Gateway / Market Product
```

If NO, ask:

```text
Is this a genuinely universal trading/economic concept?
```

Only if YES may it enter Core.

If a new market exposes a previously missing universal concept, Core may evolve once.

If a provider API differs, Core must not change.

---

# 48. Execution Instruction

Do not merely write a design document.

Implement the task in dependency order, keeping each change bounded and testable.

Do not optimize for the smallest diff if the smallest diff preserves a wrong abstraction.

Do not over-engineer speculative future products.

Use the minimum canonical abstractions necessary to correctly and deterministically support:

```text
Spot
Linear Perpetual Futures
Traditional Linear Futures conformance fixture
```

while preserving future provider independence.

Correctness, uniqueness, determinism, and authority boundaries take precedence over implementation convenience.
