# P4.3 CN A-Share Production Durable Product Pre-Implementation Audit

- Date: 2026-08-10
- Audit status: **PRE-IMPLEMENTATION / PRODUCT NOT CERTIFIED**
- Product contract target: `CN_A_SHARE_DURABLE_BACKTEST_V1`
- Product contract version target: `"1"`

This report records the code and test surface before P4.3 implementation. It is not an implementation report and does not
promote `CN_A_SHARE_CASH`, Paper, or Live to a production-ready product.

## Baseline

- Prompt baseline: `5d84bff253e4ca5f2905b1e022e84309b02697df`.
- Actual implementation baseline: `5d84bff253e4ca5f2905b1e022e84309b02697df`.
- Baseline commit message: `Feat: Durable Broker-Driven Order Lifecycle Closure`.
- `git fetch origin master` completed successfully. Local `HEAD`, `master`, and the freshly fetched `origin/master` all resolve
  to the same SHA; `git rev-list --left-right --count master...origin/master` reports `0 0`.
- Baseline differences: none in the checked-out source. The user-supplied Prompt is an untracked input and is not current
  product evidence.
- Remote branch currentness: **VERIFIED** by the successful fetch and zero divergence above.
- Remote Layered Quality: **BLOCKED / NOT VERIFIED**. The GitHub Actions API returns HTTP 403 in the current environment, so
  `Layered Quality / quality-gate = success` cannot be established. Branch synchronization is not a substitute for that gate.

P4.3 therefore cannot be declared complete at this baseline, regardless of previously recorded local P4.2 gate results.

## Audit scope

The audit read the current public composition and mutable-authority path under `src/onlyalpha/runtime/backtest/` and
`src/onlyalpha/runtime/environment.py`; the Reference/Market/Fee/Settlement authorities; Order/Risk/Execution/Transaction;
Account/Strategy Ledger/Position; the Virtual Broker plugin; and the corresponding conformance, integration, execution,
recovery, and fixture tests required by the Prompt. It also searched `src/onlyalpha/execution/` for A-share/venue/T+1 branches
and searched the production path for Generic/T0 and compatibility residue. Findings below describe the baseline SHA, not an
unverified intended implementation.

## Ownership and failure model

- Runtime owns all mutable trading authority: Clock, queues, Account, Order, Position, Allocation, Reservations, Risk,
  Settlement, Fee application/accrual, Transaction Store, Applied Projection Ledger, Outbox, Checkpoint, and recovery state.
- Strategy, Factor, Indicator, DataSource, Broker Gateway, Collector, and Artifact writer do not own or directly mutate that
  authority. Strategy expresses intent through the order interface; plugins publish normalized input; result/output components
  are read-only consumers.
- The Runtime Transaction Store is the durable authority for committed Broker lifecycle and settlement-maturity facts. Applied
  Projection Ledger is the idempotent installation index, not the economic fact authority.
- Immutable Reference records, resolved Market Profile/rules, Market Fee Pack, Broker Fee Contract, fee binding, and Execution
  Support Decision are the versioned decision authorities consumed by a transaction; they are not mutable Managers.
- Composition, Reference/rule resolution, pre-trade, support admission, prepare/commit, projection, and recovery validation are
  distinct fail-closed boundaries. A failure must not fall back to Generic rules, zero/test fees, direct Manager mutation, or an
  empty Runtime.
- Recovery equivalence is not merely “the process continues.” It must equal uninterrupted execution in economic authority,
  committed facts and transaction order, fee/settlement history, Result, and Artifact fingerprints.

## Current product surface

The formally completed product surface at the actual baseline remains the `GENERIC_T0_CASH` Backtest surface documented by the
root engineering contract. `CN_A_SHARE_CASH` has production-grade component authorities, but the components have not yet been
certified together as one durable product.

The current A-share-capable composition path is:

```text
OnlyClusterRunConfig
-> OnlyEngine
-> OnlyRuntimePlanner
-> OnlyEngineRunAssembler
-> OnlyBacktestRuntimeFactory
-> A-share Reference Query by Instrument + TradingDay
-> OnlyMarketRuleEngine
-> OnlyBacktestRuntime / Cluster / Strategy
-> OrderService -> Risk -> Reservations -> Virtual Broker
-> Broker Inbound Queue -> OnlyExecutionProcessor
-> ORDER_ACCEPTED / TRADE_FILL / ORDER_TERMINAL transaction
-> Ordered Projection / Settlement
-> Projection-ready Result -> Artifact / Report
```

This is a viable composition path, not current product certification. The only test under
`tests/conformance/cn_a_share_cash/` is the MiniQMT golden test. It uses one XSHG instrument, January 2025 bars, and
`CN_A_SHARE_TEST_MARKET_FEE_PACK@1`; it primarily proves provider normalization, frozen data, Reference artifact, Engine
assembly, and repeated-run fingerprints. Its dates precede the production fee coverage start, it has no XSHG/XSHE production
fee comparison, and it does not prove BUY/T+1/SELL, terminal, SQLite restart, or forward recovery.

## Frozen P4.3 implementation target

The accepted Product Contract is deliberately narrower than the Profile and narrower than “ordinary A shares” in general:

| Target dimension | Frozen V1 value |
|---|---|
| Product identity | `CN_A_SHARE_DURABLE_BACKTEST_V1`; manifest `product_contract_version = "1"` |
| Profile | `CN_A_SHARE_CASH@2025.1`; `@2026.07` is excluded |
| Dataset | `CN_A_SHARE_PRODUCTION_V1_SYNTHETIC_BARS`; deterministic synthetic Bars, not exchange history |
| Dates | only `2026-01-05` and `2026-01-06` |
| Trading calendars | `CN_XSHG` and `CN_XSHE`, both `Asia/Shanghai` |
| Reference records | four records: one for each `(Instrument, TradingDay)` pair over `600000.XSHG` / SSE main board and `000001.XSHE` / SZSE main board, active, non-suspended ordinary CNY `COMMON_STOCK`, with day-effective `SCENARIO` provenance |
| Trading shape | `CASH` / `LONG` / `NETTING` / `LIMIT` / `BUY OPEN` / `SELL CLOSE` |
| Lifecycle | Accepted, Trade, Cancelled, Rejected, Expired; Whole, Partial, Multi-Fill; ordinary T+1 sellability |
| Durability | MEMORY semantics plus SQLITE checkpoint/restart/forward recovery |
| Output | deterministic Result, Artifact, transaction identities, facts, and canonical order |

This table freezes the implementation target; it is not a PASS record. It does not assert that every scenario is run for every
instrument, and no date/symbol/board/profile version outside the table inherits certification.

The explicit Broker Fee Authority selected by the contract is
`VIRTUAL:BACKTEST-ACCOUNT:COMMISSION@2025.01`, Broker `virtual`, exact Account `backtest-account`, CNY. Its immutable document
uses source `BROKER_CONTRACT:VIRTUAL:BACKTEST-ACCOUNT:COMMISSION:2025.01`, notional rate `0.0003`,
`ORDER_CUMULATIVE`/`ORDER_FIXED`, minimum CNY `5.00`, quantum `0.01`, `HALF_UP`, and `ROUND_THEN_BOUNDS`. The strict loader
computes the fingerprint for manifest verification. This Broker contract is independent of
`CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`; neither expected values nor the Market Pack can stand in for it.

## Current production authorities

| Authority | Current source and identity | Current semantics |
|---|---|---|
| Product entry | `OnlyEngine` | The only product-level entry; finite Backtests use `run()` and Runtime assembly is registry-driven. |
| A-share Reference | `OnlyAshareInstrumentReference` + `OnlyAshareReferenceRegistry`/Query | Immutable `[effective_from, effective_to)` records resolved by `Instrument + TradingDay`; exact exchange, COMMON_STOCK, board, lot, tick, ST, suspension, raw previous close, source/version/data version, and fingerprint; missing/ambiguous/conflicting records fail closed. |
| Market Profile | `CN_A_SHARE_CASH@2025.1` and `@2026.07` | `2025.1` is effective on `[2025-01-01, 2026-07-06)`; `2026.07` is effective from `2026-07-06`. Both remain `EXPERIMENTAL`. Auto-date and pinned-version resolution are explicit. |
| Market Rule | `OnlyMarketRuleEngine.evaluate_pre_trade()` | The sole pre-trade authority. Compiler combines resolved Profile and Reference into session, phase, price-band/tick, quantity, position, and settlement policies with fingerprints. `SELLABLE_POSITION` is evaluated before broker submission. |
| Market Fee | `CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30` | Ordinary CNY common-stock schedules for XSHG/XSHE. Complete verified coverage begins `2025-06-30`; earlier complete resolution fails closed. SELL stamp duty and venue transfer fees remain Market-owned components. |
| Broker Fee | `OnlyBrokerFeeContract` + strict document loader/registry | Config installs an immutable identity/version/fingerprint under `authorities.broker_fee_contracts`; Account selects it; Backtest assembly verifies Broker and Account compatibility; binding/resolution/assessment retain the authority proof. No P4.3-specific production Broker Contract exists yet. |
| Execution support | Execution Support Policy `2` | Market-neutral semantic admission for CASH + LIMIT + LONG + NETTING + no Margin + parity and exact BUY OPEN/SELL CLOSE Reservation shapes. Accepted, Trade, and Terminal are durable; market/profile identity is evidence, never permission. |
| Execution fact | Runtime Transaction Store, persistence schema `5` | Stable identity and payload conflict detection; immutable prepared/committed transaction; ordered absolute projection; durable Outbox; forward-only recovery. |
| Settlement | Compiled Trade Application Instruction -> Settlement Instruction -> `OnlySettlementAuthority` | A BUY under the A-share Profile creates pending asset availability; trading-day boundary creates a durable `SETTLEMENT_MATURITY` transaction. Runtime does not hard-code A-share T+1. |
| Virtual Broker lifecycle simulation | Virtual Broker config, normalized Broker updates, Fill Plan, scheduler, and external stores; descriptor checkpoint schema `2` | A valid baseline submission schedules Accept; Fill Plans provide deterministic Whole/Partial/Multi-Fill and cancel. There is no declarative submission-index plan for pre-ACK Reject or Accepted-to-Expire, and schema v2 binds no such plan fingerprint. |
| Result and Artifact | Projection-ready query -> Backtest Collector -> Result/Analytics/Artifact writer | Trades and Runtime transactions come from projection-ready committed authority. Fee, settlement, market-rule, profile, compiled-rule, and authority identities are emitted into deterministic Result/Parquet/JSON artifacts. |

## Current test-only authorities

| Test authority | Valid responsibility | Why it cannot certify P4.3 |
|---|---|---|
| `onlyalpha.fee.testing.only_cn_a_share_conformance_fee_pack()` / `CN_A_SHARE_TEST_MARKET_FEE_PACK@1` | Explicit test-only, generic 0.001 fee used by the existing MiniQMT golden test. Production defaults and public pack exports correctly exclude it. | It is prohibited from the Production Product Gate and has neither production fee components nor production coverage. |
| `tests/fixtures/miniqmt/cn_a_share_v1` | MiniQMT frozen provider/data contract and provenance. | One XSHG symbol; missing historical Reference resources; January 2025 dates; not a production economic lifecycle dataset. |
| `tests/fixtures/reference/cn_a_share_v1` and `cn_a_share_t1.yaml` | Reference parsing/resolution, four-board/ST/suspension cases, and scenario schema evidence. | Component/parser evidence does not prove the same Engine transaction lifecycle with production fees and recovery. |
| Generic T0 execution and integration harnesses | Strong proof of Accepted/Trade/Terminal, partial/multi-fill, exact close cost, Memory/SQLite codec, checkpoints, and forward recovery for the currently certified generic surface. | Cross-component reuse is evidence that the kernel exists; it does not prove A-share authority composition or A-share Result/Artifact history. |

## Required 21-point audit answers

### 1. Current A-share Product composition path

The formal Engine path already reaches the common Backtest Runtime and Virtual Broker. Backtest Factory contains a localized
`CN_A_SHARE_CASH` branch only to construct the Reference provider from the A-share Registry; the compiled rules and durable
execution kernel are otherwise shared. There is no dedicated Production A-share product harness or product manifest.

### 2. Current Reference source

`OnlyClusterRunConfig.reference_data.ashare_instruments` is parsed into the immutable Registry/Query. Source is explicit per
record (`CONFIG`, `MINIQMT`, `TUSHARE`, `GOLDEN_DATASET`, or `SCENARIO`); Runtime does not infer historical facts from symbol
prefixes or Bars. The existing conformance test supplies a `GOLDEN_DATASET` record rather than a production-product fixture.

### 3. Current effective Reference semantics

Resolution is exactly one record for `(Instrument, TradingDay)` over a left-closed/right-open interval. Venue/exchange,
COMMON_STOCK type, board, lot size, price tick, ST, suspension, official previous close, and provenance are mandatory and
fingerprinted. Registry fingerprint participates in Runtime grouping, checkpoint validation, and Reference artifacts.

### 4. Current Market Profile versions

`CN_A_SHARE_CASH@2025.1` covers `[2025-01-01, 2026-07-06)` and `@2026.07` covers `[2026-07-06, +infinity)`. Both are
`EXPERIMENTAL`; no current test justifies promoting the entire Profile family to `STABLE`.

### 5. Current Production Fee Pack identity

`CN_A_SHARE_PRODUCTION_MARKET_FEES@2025.06.30`. It is installed by default composition and remains distinct from every Broker
Fee Contract.

### 6. Current Production Fee coverage window

Complete ordinary XSHG/XSHE common-stock coverage begins on `2025-06-30`. There is no “latest” selector and no verified complete
coverage before that day. Any P4.3 dataset day must be at or after this boundary and within every other selected authority's
effective interval.

### 7. Current Broker Contract path

Closed-schema config document -> `OnlyBrokerFeeContractDocumentLoader` -> Engine atomic authority installation -> Registry ->
Account `(contract_id, contract_version)` selection -> Backtest Factory compatibility validation -> fee binding/resolution ->
per-fill assessment/accrual/application. The current A-share golden test inherits a simulation-zero contract and does not provide
the explicit CNY rate/minimum contract required by P4.3. The repository has an integration-test document using the chosen
`VIRTUAL:BACKTEST-ACCOUNT:COMMISSION@2025.01` identity and required economics, which proves the loader/composition path but is
not yet a Product-owned manifest/Authority document or lifecycle proof.

### 8. Current BUY OPEN path

Market-rule decision -> Risk -> Account/Strategy cash Reservations -> local Order -> Broker submission -> normalized Accepted ->
durable `ORDER_ACCEPTED` -> normalized Fill -> durable `TRADE_FILL` -> Position/Allocation/Account/Ledger/Fee/Settlement/Risk
projections. This is strongly tested on Generic T0, but not with Production A-share Reference + rules + both fee authorities in
one product run.

### 9. Current SELL CLOSE path

Market-rule decision and sellable quantity -> Risk -> Position/Allocation Reservation -> Broker Accepted -> durable
`ORDER_ACCEPTED` -> Fill -> durable `TRADE_FILL` with one close-cost/PnL authority consumed by Position, Allocation, Account,
Ledger, and Fact. The generic kernel is covered; an A-share T+1-matured Engine slice is absent.

### 10. Current T+1 settlement path

Resolved Profile -> compiled settlement policy -> Trade Application Instruction -> immutable Settlement Instruction -> pending
asset quantity -> trading-day boundary -> durable `SETTLEMENT_MATURITY` transaction -> Position/Allocation sellable quantity and
Settlement projection. Component and generic recovery tests exist, but the A-share product has no same-day rejection plus D+1
maturity and SELL proof.

### 11. Current whole-fill path

Virtual Broker's default normalized Fill Plan is one next-bar whole Fill. Execution creates one immutable Trade transaction and
projection-ready committed fact. No current Production A-share test asserts the complete authority result.

### 12. Current partial-fill path

Virtual Broker supports bounded-per-bar and explicit scheduled Fill Plans. Every Fill gets its own identity, fill index,
transaction, incremental projections, fee application, and remaining Reservations. Generic product/integration tests cover it;
P4.3 product proof does not yet exist.

### 13. Current multi-fill path

Virtual Broker persists a deterministic Fill Plan/cursor and emits multiple normalized Trade updates. Runtime applies exact
incremental Position, Allocation, cash, fee, settlement, and Risk changes. Generic multi-fill and restart tests exist, including
SELL CLOSE; Production A-share BUY/SELL and minimum-commission multi-fill scenarios are missing.

### 14. Current terminal path

Cancel, Reject, and Expire updates are admitted by Execution Support Policy 2 and become durable `ORDER_TERMINAL` transactions.
BUY releases only remaining cash/Risk authority; SELL releases only remaining Position/Allocation/Risk authority; committed
fills never roll back. Virtual Broker currently provides ordinary Accepted/Trade/Cancel. Its rejection paths are incidental
submission/readiness/account or acceptance-time plan/reserve failures rather than a declarative exact-scenario contract, and it
does not emit Expired. Expire proof is therefore normalized-update/component coverage. A Product-Gate broker-driven matrix is
absent; manually calling the Execution Processor or constructing a terminal update would violate the Product Gate.

### 15. Current Memory/SQLite recovery path

Both backends implement the same Runtime Persistence Store contract and transaction codec. MEMORY proves in-process product
semantics but cannot survive creation of a fresh process/store. SQLITE binds stable Runtime/config identity, atomically stores
transactions/outbox/checkpoints, reopens across Engine instances, restores participants, causally replays market data, resumes
projection tails, rebuilds indexes, validates aggregates, and then opens. Existing restart/fault coverage uses the generic
product, not the Production A-share lifecycle. The Virtual Broker participant currently uses checkpoint schema `2`, which
persists connection/plugin state, external Account/Order/Trade stores, Fill Plans/cursors, Bar cursor/latest Bars, sequences,
and scheduled actions and validates their aggregate consistency. It has no submission-simulation identity to persist or
validate because that control surface does not yet exist.

### 16. Current Result / Artifact path

Collector reads only projection-ready committed records for Trades and Runtime transaction history, plus read-only snapshots and
formal rule/fee/settlement queries. Engine computes the Result fingerprint, writes staged verified JSON/Parquet artifacts and an
artifact-content fingerprint, then emits reports. Existing schemas already expose most required authority proof; no parallel
A-share Result model is needed. Product identity/contract and dataset proof are not yet bound into one P4.3 conformance manifest.

### 17. Current cn_a_share conformance tests

`tests/conformance/cn_a_share_cash/test_miniqmt_golden.py` contains the current formal A-share conformance file. It validates
MiniQMT manifest/bar contract, tamper rejection, Engine/Virtual-Broker smoke, Reference artifact, and repeat determinism. It is a
provider/data golden gate, not a Production Trading Product gate. Other A-share tests cover Reference, rules, fees, config,
architecture, and scenario parsing separately.

### 18. Current use of test-only fee authority

The test pack is correctly isolated in `onlyalpha.fee.testing` and explicitly installed by the MiniQMT golden test. Production
defaults, examples, and public production pack exports do not select it. P4.3 must add a guard that its product harness has no
reference to the test pack or helper while retaining the valuable provider golden test.

### 19. Current production conformance gaps

There is no frozen product dataset/manifest within production fee coverage, no two-venue Product Gate, no explicit versioned
non-zero Broker Contract, no end-to-end BUY/same-day rejection/T+1/SELL proof, no product-level partial/multi-fill fee proof, no
complete Cancel/Reject/Expire product matrix, no A-share SQLite A->B->C recovery equivalence, and no deterministic Result plus
Artifact comparison over the recovered canonical history. The baseline Virtual Broker also lacks a market-neutral deterministic
submission plan for pre-ACK Reject/Accepted-to-Expire and the corresponding checkpoint v3 compatibility/fingerprint proof. The
remote final quality gate is also not verified.

### 20. Current generic/T0 naming residue

The formal projection-target factory is still named `only_create_generic_t0_execution_projection_targets`, and production
docstrings in `execution/projection_targets.py` and BUY reducers describe a “Generic T0” authority even though Policy 2 and the
planner/projection semantics are market-neutral CASH/LONG/NETTING lifecycle semantics. Test fixtures with genuinely Generic T0
inputs may retain descriptive names; production semantic names and obsolete “legacy” comparison terminology should not survive
without an actual independent responsibility.

### 21. Any hidden product-specific branch in Execution

No. A source audit found none of `CN_A_SHARE`, `Ashare`, `Shanghai`, `Shenzhen`, `XSHG`, `XSHE`, or `T_PLUS_ONE` in
`src/onlyalpha/execution/`. Execution routes by immutable semantic shape and compiled instructions. The existing A-share branch in
Backtest Factory is a Reference-composition concern explicitly deferred for neutralization to P5; it must not migrate into
Execution during P4.3.

## Current lifecycle and missing product proofs

| Lifecycle boundary | Existing implementation authority | Missing P4.3 proof |
|---|---|---|
| Composition | Engine/Planner/Assembler/Backtest Factory; production Market Fee Pack already installed | Frozen product manifest, explicit Broker Contract, both venues, production-date guard, no test fee |
| Broker simulation | Virtual Broker normalized Accepted/Trade/Cancelled path and checkpoint v2 | Closed `extensions.simulation.submissions` plan for `REJECT_BEFORE_ACCEPTED` / `ACCEPT_THEN_EXPIRE`, stable plan fingerprint, normalized terminal updates, and fail-closed checkpoint v3 restore |
| Pre-trade | Reference + Profile + compiled Market Rule; Risk consumes its Decision | A-share BUY acceptance, same-day SELL `SELLABLE_POSITION` rejection before Broker, D+1 SELL acceptance |
| Accepted/Trade | Policy 2, pure planners, Transaction Store, ordered projections | Same Production A-share run covering BUY and SELL, whole/partial/multi-fill, duplicate/conflict |
| Fees | Production Market Pack, Broker Contract, binding, cumulative accrual | Component-level BUY/SELL amounts, SELL-only stamp duty, venue transfer fees, 0.03%/CNY 5 cumulative Broker commission |
| Settlement | Instruction-driven T+1 and durable maturity transaction | D fill -> unavailable -> D+1 maturity -> sellable, with idempotent recovery |
| Terminal | Durable Cancel/Reject/Expire planners and exact remaining release | Broker-driven BUY/SELL partial cancel, BUY reject, SELL reject-before-ACK, Expire in the Product Gate |
| Persistence/recovery | MEMORY/SQLITE Store, checkpoint registry, causal replay, forward projection, validation | A-share SQLite stored/mid-projection/outbox faults and true Engine A->B->C versus uninterrupted equality |
| Output | Projection-ready Collector and atomic Artifact writer | Product/dataset identity, authority-manifest cross-check, repeated and recovered Result/Artifact fingerprints |

## Interfaces to remove or rename during P4.3

Removal is semantic cleanup, not a compatibility exercise. Git history is the compatibility record.

1. Replace the production name `only_create_generic_t0_execution_projection_targets` with a market-neutral name describing the
   Runtime execution projection target registry; remove the old symbol and error text without an alias.
2. Remove “Generic T0” from production reducer/projection docstrings where the code now implements the accepted CASH/LONG/NETTING
   instruction shape rather than a Profile-specific algorithm.
3. Remove or rename test-only `legacy` terminology only where both compared sides already invoke the same canonical durable
   path. Do not delete economic assertions or immutable recovery evidence.
4. If implementation discovers another no-responsibility compatibility wrapper, delete it only after migrating formal callers
   and adding a source guard. No `legacy_ashare`, `ashare_v1_compat`, `generic_t0_compat`, or fallback authority may be added.

## Interfaces and evidence to keep

- `OnlyEngine` -> Runtime Planner -> Assembler -> Backtest Factory remains the sole product path.
- `OnlyAshareInstrumentReference`, Registry/Query, current localized Backtest Reference composition, Market Profile Registry,
  Compiler, and `OnlyMarketRuleEngine` remain the correct owners. Reference composition neutralization is P5.
- Market-neutral Execution Capability Resolver/Policy 2, Accepted/Trade/Terminal planners, Runtime Transaction Store, ordered
  Projection, Outbox, Checkpoint, and forward recovery remain shared authorities; no A-share planner is needed.
- Production Market Fee Pack and explicit Broker Fee Contract remain independent. The test fee helper remains in
  `onlyalpha.fee.testing` solely for tests that genuinely require it.
- A narrowly scoped market-neutral Virtual Broker submission simulation may be added because Product Reject/Expire must enter
  through normalized Broker updates. Its only actions are `REJECT_BEFORE_ACCEPTED` and `ACCEPT_THEN_EXPIRE`, selected by a
  positive one-based submission index; unlisted submissions retain Accept. The closed canonical plan and SHA-256 fingerprint
  become Broker checkpoint compatibility input. Checkpoint schema advances from v2 to v3 and rejects old/mismatched plan or
  scheduled-action authority rather than silently accepting it. This is plugin simulation state, not an A-share rule or Runtime
  economic write API.
- MiniQMT and Reference golden datasets/tests remain because provider normalization, provenance, tamper detection, and Reference
  stability are responsibilities distinct from Product Conformance.
- Existing fault-injection and recovery infrastructure must be reused; no second recovery or CI framework is justified.
- Existing Result, Analytics, Artifact, and Report schemas remain the output path. Add only proof that is genuinely absent from
  existing facts/manifests.

## Explicit non-scope

P4.3 does not implement or certify:

- the entire China A-share market or every `CN_A_SHARE_CASH` regime;
- BSE, B shares, ETF-specific semantics, convertible bonds, bonds, options, futures, crypto, Stock Connect, IPO/first-day,
  delisting, after-hours fixed-price, block trading, advanced auction behavior, or corporate-action processing;
- Margin, Short, Hedging, multi-account, multi-broker, or multi-data-source products;
- Paper streaming checkpoint/recovery, Live Runtime, real Broker command durability, retry/idempotency, Broker synchronization,
  or long-running production operations;
- Market Product Composition Neutralization, generic Reference Provider SPI, Market Compiler SPI, Product Registry/DSL/plugin
  framework, vectorized/distributed Backtest, or Web/API product work.

The target is one finite Backtest product contract and one conformance harness. `CN_A_SHARE_CASH` remains `EXPERIMENTAL`; a
passing local component or product test, without the complete required lanes and remote Layered Quality success on the final
commit, is not P4.3 completion.
