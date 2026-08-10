# ADR 0067: CN A-Share Production Durable Backtest Product

Status: Accepted

Date: 2026-08-10

Decision baseline: `5d84bff253e4ca5f2905b1e022e84309b02697df`

Product contract: `CN_A_SHARE_DURABLE_BACKTEST_V1`

Product contract version: `"1"`

Conformance status at decision baseline: **NOT CERTIFIED**

## Context

OnlyAlpha already has versioned A-share Reference and Market Rule authorities, a Production A-share Market Fee Pack, explicit
Broker Fee Contracts, instruction-driven settlement, a market-neutral durable Accepted/Trade/Terminal kernel, Memory/SQLite
persistence, forward recovery, and deterministic Result/Artifact output. Component correctness does not establish that these
authorities compose into a correct product.

The existing A-share conformance test is a MiniQMT provider/data golden test using a test fee pack and a pre-production-fee date.
It must remain for its provider responsibilities, but it cannot certify a Production Trading Product. A finite product contract
is therefore required before implementation. This ADR accepts that contract; it does **not** record a conformance PASS.

## Decision

`CN_A_SHARE_DURABLE_BACKTEST_V1` is the first finite CN A-share Cash-Long durable Backtest product contract. This decision
accepts the boundary that implementation and conformance must satisfy; accepting the contract does not certify the product.
The identity is not a new Runtime, Registry, framework, capability DSL, provider SPI, or second composition root.

The product must enter through:

```text
Cluster Config
-> OnlyEngine
-> Runtime Planning / Assembly
-> Backtest Runtime
-> Reference / Market Rules
-> Strategy / Order / Risk / Reservation
-> Virtual Broker
-> Broker Inbound Queue / Execution Processor
-> Durable Accepted / Trade / Terminal / Settlement transactions
-> Ordered Projection
-> Result / Artifact / Report
```

No conformance helper may directly construct a prepared transaction, inject an economic Fill into the Execution Processor,
mature settlement, or mutate Account, Order, Position, Allocation, Ledger, Risk, Reservation, Fee, or Projection authority.

## Frozen supported surface

| Dimension | `CN_A_SHARE_DURABLE_BACKTEST_V1` claim |
|---|---|
| Manifest contract version | `product_contract_version = "1"` |
| Runtime | finite `BACKTEST` through `OnlyEngine.run()` |
| Market Profile | pinned `CN_A_SHARE_CASH@2025.1` only |
| Profile status | remains `EXPERIMENTAL`; this product does not promote the whole Profile family |
| Required conformance dataset | `CN_A_SHARE_PRODUCTION_V1_SYNTHETIC_BARS`, and only trading days `2026-01-05` and `2026-01-06` |
| Trading calendars | fixture-declared `CN_XSHG` and `CN_XSHE`, both with `Asia/Shanghai` venue time |
| Market fee coverage | both contract dates are within the Production Pack coverage beginning `2025-06-30` |
| Venues | XSHG and XSHE, represented only by the two contract instruments below |
| Instruments | `600000.XSHG` as active/non-suspended/non-ST SSE main-board ordinary `COMMON_STOCK`, and `000001.XSHE` as active/non-suspended/non-ST SZSE main-board ordinary `COMMON_STOCK`, using the fixture's day-effective Reference records |
| Currency | CNY |
| Account | `CASH` |
| Position | `LONG`, `NETTING` |
| Order type | `LIMIT` |
| Order semantics | `BUY OPEN`, `SELL CLOSE` |
| Broker lifecycle | `ACCEPTED`, `TRADE`, `CANCELLED`, `REJECTED`, `EXPIRED` |
| Fill | Whole, Partial, and Multi-Fill |
| Settlement | ordinary trading-day-based T+1 asset sellability; settlement maturity is durable |
| Persistence | MEMORY for product-semantics equivalence; SQLITE for durable close/reopen and recovery |
| Recovery | Checkpoint, restart with a new Engine/Runtime instance, and forward-only recovery |
| Output | deterministic Result and deterministic Artifact over projection-ready committed authority |

The fixture Bars are deterministic synthetic market data, not exchange history. Its four Reference records provide exactly one
day-effective record for each contract `(Instrument, TradingDay)` pair. They are formal inputs to the Production Reference
Registry/Query path, but their `SCENARIO` provenance and exact effective intervals remain visible. The V1 claim is limited to
these records and dates. It does not silently extend to another symbol, date, board, Reference state, or to the Cartesian
product of every scenario and every instrument; the Product Gate must state which contract scenario supplies each required
proof.

The Product Contract version, Market Profile version, Reference data version/fingerprint, Market Fee Pack version, Broker Fee
Contract version/fingerprint, Execution Support Policy version, and persistence/transaction schema versions are independent
authorities. None is an alias for another.

`CN_A_SHARE_CASH@2026.07` is not certified by this V1 contract. Certifying it requires explicit conformance evidence and an
intentional contract/manifest decision; effective-date resolution alone cannot silently broaden V1.

## Required production authorities

Every certified run must bind and preserve, directly or through existing facts and manifests:

1. An immutable `OnlyAshareInstrumentReference` record resolved by `(Instrument, TradingDay)`, including venue/exchange,
   COMMON_STOCK type, board, lot, tick, ST/suspension state, official raw previous close, effective interval,
   source/source-version/data-version, record fingerprint, and Registry fingerprint. Bar close is not Reference authority.
2. `CN_A_SHARE_CASH@2025.1`, its resolved/compiled rule fingerprint, and the exact Reference fingerprint. Market Rule remains
   the sole authority for session, phase, price, quantity, and sellable-position legality.
3. `CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`. The Production Product Gate may not import or install
   `CN_A_SHARE_TEST_MARKET_FEE_PACK`, `only_cn_a_share_conformance_fee_pack`, a Generic/zero Market fee, or a fallback pack.
4. The explicit immutable Broker Fee Contract
   `VIRTUAL:BACKTEST-ACCOUNT:COMMISSION@2025.01`, bound to Broker `virtual`, currency CNY, and exact Account
   `backtest-account`. Its schedule is effective from `2025-01-01` and applies `BROKER_COMMISSION` at notional rate `0.0003`,
   `ORDER_CUMULATIVE` calculation scope, `ORDER_FIXED` resolution, CNY `5.00` minimum, CNY `0.01` quantum, `HALF_UP`, and
   `ROUND_THEN_BOUNDS`. Its source is
   `BROKER_CONTRACT:VIRTUAL:BACKTEST-ACCOUNT:COMMISSION:2025.01`. The strict document loader computes the canonical
   fingerprint; the conformance manifest records and verifies that computed fingerprint rather than copying an unverified
   literal into this ADR. Expected values may not replace the Authority document.
5. Execution Support Policy `2`, admitting the exact CASH/LIMIT/LONG/NETTING/no-Margin BUY OPEN and SELL CLOSE Reservation
   shapes. Market identity remains evidence, not execution permission. A different Policy version requires an explicit Product
   Contract/manifest decision and complete conformance evidence; semantic similarity cannot silently broaden V1.
6. The Runtime Transaction Store as durable fact authority, ordered absolute projections, Applied Projection Ledger as
   idempotent index, durable Outbox intent, checkpoint participants, and forward-recovery validation.

Market fees and Broker fees remain separate authorities and separate result components. SELL stamp duty, venue transfer fee,
and Broker commission must be traceable by schedule/rule identity and incremental amount. Minimum commission is
`ORDER_CUMULATIVE`; it must not be charged independently on each Fill.

For the two contract dates in 2026, the selected Production Market Pack resolves SELL-only stamp duty at `0.0005` and bilateral
XSHG/XSHE transfer fee at `0.00001`, each as a per-Fill Market component with CNY-cent `HALF_UP` rounding. These values remain
Market Fee schedules, not terms copied into the Broker contract or Strategy assertions.

## Market-neutral Virtual Broker simulation contract

Product Reject and Expire evidence must still originate at the Virtual Broker and enter the normalized Broker Inbound Queue.
The Virtual Broker therefore has one narrowly scoped, deterministic simulation control surface:

```text
extensions.simulation.submissions:
  - submission_index: <positive, one-based Virtual Broker submission index>
    action: REJECT_BEFORE_ACCEPTED | ACCEPT_THEN_EXPIRE
    rejection_code: <optional stable Broker rejection code>
    reason: <optional diagnostic reason>
```

An unlisted submission has the existing `ACCEPT` behavior. Duplicate or non-positive indices, unknown fields/actions, and
non-canonical invalid values fail closed. The normalized, submission-index-sorted plan has a stable SHA-256 fingerprint. The
control is market-neutral: it selects an external lifecycle outcome by submission index and does not inspect Market Profile,
venue, instrument, T+1, fee, Account economics, or Runtime Managers.

`REJECT_BEFORE_ACCEPTED` is delivered at the normal acceptance-due callback as a standard Rejected update. It creates no
Virtual Fill Plan and no Virtual Broker hold. `ACCEPT_THEN_EXPIRE` first performs the ordinary acceptance transition, creates
the Fill Plan and Virtual Broker hold, publishes the standard Accepted update, then releases only the remaining Virtual Broker
hold, moves the external Order/Plan to Expired, and publishes the standard Expired update. Stable source sequencing makes
Accepted precede Expired. Runtime Reservations are released only by the canonical durable Terminal transaction; the plugin
never mutates a Runtime authority.

The simulation plan is part of deterministic input and recovery compatibility. Virtual Broker checkpoint schema v3 must retain
all existing external Order/Trade/Fill-Plan/Scheduler cursors and additionally bind the simulation-plan fingerprint. Every
pending submission action freezes its selected simulation action; restore verifies that action against the configured plan.
Schema mismatch, plan-fingerprint mismatch, or scheduled-action conflict fails closed. There is no silent v2 migration or
fallback to Accept. The Runtime registers the Broker participant using descriptor-declared checkpoint schema version `3`.

## Settlement contract

T+1 is produced only by the authority chain:

```text
Resolved Profile + Reference
-> Compiled Trade Application Instruction
-> TRADE_FILL transaction
-> immutable Settlement Instruction / pending asset
-> trading-day boundary
-> SETTLEMENT_MATURITY transaction
-> sellable/trade-available Position and Allocation authority
```

A BUY on day D creates Position quantity but does not make that quantity sellable on D. A same-day SELL must fail at the Market
Rule `SELLABLE_POSITION` boundary and must not reach the Virtual Broker or create Accepted/Trade/Terminal Broker facts. After the
next legal trading-day maturity, the exact due quantity becomes sellable and SELL CLOSE may proceed through the same
market-neutral execution kernel.

No A-share, venue, or `T_PLUS_ONE` branch may be added to `src/onlyalpha/execution/` to achieve this behavior.

## Durable lifecycle and economic contract

Accepted, every Fill, Terminal, and Settlement Maturity are separate immutable Runtime transactions with stable operation
identity, payload conflict detection, execution sequence, complete projections/preconditions, projection-ready state, and
Outbox intent where applicable.

- Whole/Partial/Multi-Fill updates increment Order, Position, Allocation, Account, Strategy Ledger, Reservations, Risk, Fee,
  Settlement, and valuation authority exactly once.
- SELL CLOSE uses Allocation as Cluster cost-attribution authority and Position as Account aggregate authority. Released cost and
  realized PnL are calculated once before commit and consumed unchanged by every projection/fact.
- Cancel/Reject/Expire release only the exact remaining Reservation authority. Previously committed Fills, fees, settlement
  instructions, cost, and PnL never roll back.
- Duplicate Accepted/Fill/Terminal facts are idempotent. The same identity with a different normalized payload fails closed and
  cannot overwrite historical authority.

## Persistence and recovery guarantee

MEMORY certification proves that product economics do not depend on SQLite. It does not claim process-surviving Memory storage.

SQLITE certification proves atomic durable transactions/outbox/checkpoints, close and reopen with stable Runtime identity, a new
Engine/Runtime instance, exact market-data cursor continuation, participant schema validation, committed-tail resolution,
ordered projection completion, derived-index rebuild, aggregate validation, and continuation delivery only after Runtime open.

The required recovery equivalence is:

```text
same config + dataset + authorities + Broker simulation
-> uninterrupted run U
==
same input -> Engine A -> restart -> Engine B -> restart -> Engine C
```

Equality covers Order, Position, Allocation, Account, all Strategy Ledgers, Fee accrual/application, cash/position/risk
Reservations, Risk, Settlement, Runtime transactions, committed facts, Applied Projection Ledger, Outbox state, Result, Artifact,
transaction identities, and economic ordering. Recovery consumes persisted historical facts and authority proof; it does not
re-run today's Market Rule or Fee Pack to re-authorize/reprice committed history. Only forward recovery is supported.

## Meaning of Production

“Production” in this contract means:

- the real Engine composition root and production Runtime authority path are used;
- Reference, Market Rule, Market Fee, Broker Fee, settlement, durable execution, persistence, and output authorities are
  versioned, immutable/auditable where required, and fail closed;
- the complete supported economic lifecycle, durability, recovery, and determinism claims pass one formal Product Gate;
- the fixture declares provenance and fingerprints, and any deterministic synthetic market bars are labeled as synthetic.

It does not mean real-money trading, a real Broker connection, a claim that synthetic bars are exchange history, Paper/Live
operational readiness, or universal China-market coverage.

## Certification rule

Certification proves only the frozen surface above. It requires the exact 2026-01-05/06 fixture and Reference records, XSHG and
XSHE evidence; BUY OPEN; same-day SELL rejection; durable T+1 maturity; SELL CLOSE; Whole/Partial/Multi-Fill; component-level
production fees and cumulative minimum
commission; Cancel/Reject/Expire; MEMORY and SQLITE; true multi-instance/fault-point forward recovery; duplicate/conflict
handling; and deterministic Result/Artifact and canonical transaction history.

Certification exists only when the product tests, required repository lanes/static/build gates, and the remote final
`Layered Quality / quality-gate` all pass on the same final commit. At this ADR's decision baseline, the Product Gate was not
implemented and remote workflow status could not be read because the GitHub Actions API returned HTTP 403, so
`CN_A_SHARE_DURABLE_BACKTEST_V1` was **NOT CERTIFIED**. This historical statement must not be used as a substitute for checking
the latest conformance report and final-commit quality gate.

## Explicitly unsupported

This contract does not cover:

- `CN_A_SHARE_CASH@2026.07`, every A-share board/regime, BSE, B shares, ETFs, bonds, convertible bonds, options, futures, crypto,
  Stock Connect, IPO/first-day or delisting regimes, after-hours fixed-price, block trading, advanced auction execution, or
  corporate actions;
- Margin, Short, Hedging, multi-account, multi-broker, multi-data-source, vectorized, or distributed products;
- Paper streaming recovery, Live Runtime, real Broker outbound command durability/retry/idempotency, Broker state
  synchronization, or long-running operations;
- exactly-once subscriber delivery, durable direct-event journal, or external Subscriber ACK/watermark;
- a Stable promotion for the whole `CN_A_SHARE_CASH` Profile;
- Product Framework, Market Product Registry, capability DSL, provider/compiler SPI, or P5 composition neutralization.

## Consequences

P4.3 should primarily compose and prove existing authorities. A production-kernel change is allowed only when conformance exposes
a market-neutral invariant defect; its owner, failure boundary, and regression proof must be explicit. No A-share-specific
planner, reducer, projection target, fee calculation, settlement shortcut, direct Manager write, compatibility wrapper, or
fallback authority is acceptable.

The existing MiniQMT and Reference golden tests remain because Provider/Data Conformance is not Product Conformance. Existing
fault-injection, Runtime persistence, Result, Artifact, and CI lanes are reused. Profile status remains `EXPERIMENTAL`; only this
finite product identity may eventually be certified.

## Rejected alternatives

- Treating component test success as product success leaves composition and authority interaction unproved.
- Reusing the test fee pack or zero Broker fees changes the product economics and invalidates “Production.”
- Directly injecting Fill/Settlement/Manager state bypasses the product entry and durable protocol.
- Routing Execution by `CN_A_SHARE_CASH` conflates market legality with kernel implementation support.
- Promoting the entire Profile to Stable overstates a contract that intentionally excludes many market regimes.
- Creating a Product Registry/framework before a second product requires it adds a parallel authority without current need.
