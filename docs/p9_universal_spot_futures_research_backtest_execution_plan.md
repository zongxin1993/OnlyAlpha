# P9.U Universal Spot/Futures Research & Backtest — Execution Plan

This document describes only future construction order, dependencies, semantic boundaries, and stage boundaries. ADR 0106 determines its applicability. This document is not a Task Contract, task-status record, authorization mechanism, or acceptance authority; every implementation task is accepted only under the current context and root `AGENTS.md`.

## 1. Goal and exact scope

Close the minimum market-neutral semantic envelope needed for the same Research, Dataset, Strategy, Trading Kernel, deterministic simulated Broker, Position, Margin, Account, persistence, checkpoint/replay, and evidence paths to support:

```text
Cash / Spot
Linear Margined Perpetual Futures
Traditional Linear Futures daily mark-to-market conformance fixture
```

The first stage is Research and Backtest correctness. Real Binance Futures Mainnet execution, LIVE certification, provider-exact liquidation, COIN-M, Options, QMT, CTP, Web, and Agent work are outside this plan.

## 2. Universal versus provider boundary

Use the permanent classification rule:

```text
changes with market/provider/protocol
→ Plugin / Adapter / Gateway / Market Product

market-independent canonical economic meaning
→ Core
```

Universal Core owns canonical intent, deterministic ordering, position state, margin state, accounting cashflows, funding derivation, settlement transitions, recovery, identity, and evidence. Market Product compiles effective economic policies. Provider plugins own raw reference/protocol DTOs, endpoint behavior, leverage-bracket normalization, provider field mappings, and historical transport.

## 3. Semantic gap matrix

This matrix classifies architecture work; it is not a completion ledger.

| Semantic area | Classification | Existing anchor or required boundary |
| --- | --- | --- |
| Order side (`BUY`/`SELL`) | Existing canonical concept | `onlyalpha.domain.enums.OnlyOrderSide` |
| Position side (`LONG`/`SHORT`) | Existing canonical concept | `onlyalpha.position.enums.OnlyPositionSide` |
| Position mode (`NETTING`/`HEDGING`) | Existing canonical concept | `onlyalpha.position.enums.OnlyPositionMode`; remove duplicate `LONG_ONLY` authority from compiled semantics |
| Position effect | Existing but overlapping canonical concept | Normalize `OnlyOffset` compatibility into one execution-facing `OnlyPositionEffect` authority |
| Close scope (`ANY`/`TODAY`/`YESTERDAY`) | Missing universal canonical concept | Split close scope from position effect; preserve old offset decoding only at compatibility ingress |
| Exposure constraint (`NONE`/`REDUCE_ONLY`) | Missing universal canonical concept | Model independently from position effect and provider flags |
| Target exposure and flip planning | Existing partial concept requiring closure | Reuse position direction/flip policy; deterministically plan current-to-target transitions |
| Short policy | Existing canonical concept | `OnlyShortSellingRule`; fail closed when disabled or borrow cannot be proven |
| Market Product composition/fingerprint | Existing canonical concept | Extend `OnlyResolvedMarketProductBinding` and `OnlyCompiledMarketPolicy`; do not add a parallel profile |
| Instrument/contract terms | Existing canonical seed requiring closure | Extend compiled settlement currency, multiplier, contract/economic kind, and lifecycle terms without provider DTOs |
| Notional semantics | Existing canonical seed requiring closure | Compile linear notional and multiplier rules; provider contract representations stay outside Core |
| Order/TIF/effect capability policy | Missing universal policy coverage | Compile legal canonical request shapes before Broker submission |
| Cash exchange economics | Existing canonical path requiring regression preservation | Spot buy/open and sell/close remain supported without derivative branches |
| Fee policy and fee accounting | Existing canonical authority requiring derivative conformance | Commission remains separate from funding, margin reservation, and realized PnL |
| Margin requirement | Existing simple universal seed requiring closure | Replace fixed-rate-only authority with compiled one/tier schedule and explicit CROSS/ISOLATED scope |
| Margin reservation/release | Existing partial concept requiring closure | Margin is state reservation, not cashflow; partial fills consume/release proportionally |
| Futures long/short accounting | Missing universal executable coverage | Shared durable transaction path for open/close, realized PnL, fees, and margin |
| Unrealized valuation | Missing universal canonical concept | Compiled valuation basis consumes canonical reference prices |
| Reference price fact | Missing universal fact family | Canonical MARK/INDEX/SETTLEMENT identities, provenance, time, sequence, and version |
| Funding rate fact | Missing universal market fact | Immutable input; never mutates account directly |
| Funding cashflow | Missing universal accounting fact | Deterministically derived from rate, boundary position, valuation, multiplier, and policy |
| Account/equity/cashflow vocabulary | Existing authority requiring extension | Represent cash exchange, fee, realized PnL, funding, and variation margin as distinct canonical accounting facts |
| Daily mark-to-market | Existing vocabulary requiring executable closure | Shared settlement/accounting transition proven by a non-Binance fixture |
| Deterministic mixed-fact ordering | Missing universal ordering closure | Timestamp, canonical class priority, source sequence, and fact identity |
| Dataset Snapshot identity | Existing canonical authority requiring extension | Bind every economic fact family and Market Product composition used by Backtest |
| Strategy inputs vs kernel economic inputs | Missing universal requirements split | Strategy Revision declares decision inputs; Market Product independently supplies mandatory valuation/funding/settlement inputs |
| Historical DataSource SPI | Existing bar-oriented authority requiring extension | Add canonical fact-family requests; provider requests stay inside plugins |
| Backtest Runtime | Existing canonical concept | Extend the one `OnlyBacktestRuntime`; do not add Spot/Futures runtimes |
| Simulated Broker | Existing canonical concept requiring conformance extension | Own matching/fills only; never Position, Margin, or Account state |
| Canonical Broker request | Existing contract requiring semantic extension | Preserve side, position side/effect, close scope, exposure constraint, type, TIF, quantity, and price before provider translation |
| Execution support policy | Existing versioned authority requiring a new version | Existing v2 remains unchanged; certify only newly implemented shapes in the successor |
| Checkpoint/replay | Existing canonical authority requiring schema coverage | Persist all new position/margin/funding/settlement progress and reject incompatible state |
| Binance USD-M raw DTOs/endpoints | Provider-specific concept | Binance plugin only |
| Binance leverage brackets | Provider-specific input | Plugin compiles effective canonical margin tiers |
| Binance `positionSide`/`reduceOnly` fields | Provider-specific representation | Plugin translation from canonical intent only |
| Traditional exchange session/margin/close rules | Provider-specific input | Synthetic fixture compiles deterministic canonical policies without Core branches |
| Provider-exact liquidation | Out of scope | Maintenance breach without certified model fails closed |
| COIN-M, Options, QMT, CTP, Web, Agent, LIVE certification | Out of scope | Later work; no speculative abstraction required now |

## 4. Dependency sequence

### P9.U0 — Sequencing and architecture freeze

- dependency: an accepted ADR 0106 must make this sequence applicable;
- freeze the semantic uniqueness and universal/provider classification above in the applicable architecture context.

### P9.U1 — Canonical semantic uniqueness

- establish one execution-facing intent authority;
- make close scope and exposure constraint orthogonal;
- retain `OnlyOffset` only as normalized compatibility input;
- complete deterministic target-exposure and flip planning.

### P9.U2 — Compiled economic policy

- extend the existing compiled Market Product policy with order capability, margin schedule/mode, valuation, funding, settlement, and kernel economic-data requirements;
- version canonical policy identity.

### P9.U3 — Durable economics

- support long/short open/close, NETTING/HEDGING, CROSS/ISOLATED, proportional reservation/release, realized/unrealized PnL, fees, funding, settlement, partial fills, duplicate idempotency, and reduce-only;
- introduce a successor execution-support policy version;
- version and migrate or fail closed on changed durable schemas.

### P9.U4 — Canonical data and immutable evidence

- add Reference Price and Funding Rate facts;
- separate Strategy inputs from kernel economic inputs;
- extend historical requests, Dataset manifests, canonical ordering, and fingerprints.

### P9.U5 — Generic Backtest conformance

- exercise Spot and synthetic non-Binance Futures through the same Runtime, Kernel, simulated Broker, Position, Margin, Account, checkpoint/replay, and evidence path.

### P9.U6 — Binance USD-M conformance plugin

- normalize USD-M reference, historical bars, Mark/Index prices, funding, filters, and margin inputs;
- translate canonical broker semantics into provider fields;
- keep real private execution/LIVE certification outside this plan.

### P9.U7 — Cross-market closure

- run the deterministic Spot, Binance USD-M, and synthetic Futures matrix;
- prove uninterrupted execution equals checkpoint/restore/continue;
- perform the bounded high-risk Independent Review.

## 5. Verification dependency

Each implementation stage defines its ephemeral Task Contract in the active development context and follows root `AGENTS.md`. This plan does not duplicate or replace those acceptance rules.
