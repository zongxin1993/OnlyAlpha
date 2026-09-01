# ADR 0106 — Universal Spot/Futures Research and Backtest Sequencing

- Status: **ACCEPTED**
- Date: 2026-09-01
- Decision maker: repository owner
- Scope: post-Spot P9 engineering sequence through Research/Backtest Futures conformance
- Supersession: only the Research/Backtest provider-scope restrictions and provider sequencing identified precisely below
- Does not supersede: the Spot Golden Vertical decision, P9.0 Strategy Revision/Promotion semantics, provider-neutral Core boundaries, authority, determinism, recovery, fail-closed safety, or the long-term QMT/CTP/LIVE goals

## Context

`docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md` selected Binance Spot as the first Golden Vertical and preferred QMT Market Data before Binance USD-M Futures. The next increment instead closes the universal Spot/Futures Research and Backtest semantic envelope before another provider-oriented vertical.

This is a sequencing change, not a product-scope reduction. Binance Spot remains the first Golden Vertical. QMT Market Data, later LIVE work, QMT Broker, and CTP remain long-term work. The change brings forward the canonical economic semantics required to prove that Spot and Futures are configurations of one Trading Kernel rather than separate engines.

The decision conforms to `PROJECT_CONSTITUTION.md`: universal trading semantics remain in Core; provider and venue rules remain in Market Product, Plugin, Adapter, or Gateway boundaries.

## Decision

After the existing Spot foundation, use this construction order:

```text
Existing Spot foundation
→ Universal Spot/Futures Research + Backtest semantic closure
→ Binance USD-M Research/Backtest conformance plugin
→ Cross-market conformance with a synthetic non-Binance Futures product
→ later Web / SIM / LIVE / QMT / CTP / Agent work
```

The subordinate future construction and dependency plan is:

```text
docs/p9_universal_spot_futures_research_backtest_execution_plan.md
```

This ADR determines the applicability of that plan. The plan is not a Task Contract, task-status record, authorization mechanism, or acceptance authority.

## Precise supersession

This ADR supersedes only these parts of `docs/adr/0099-binance-spot-first-golden-vertical-and-provider-sequencing.md`:

- section 1's prohibition on Futures entering active product scope before the full Spot Golden Vertical, solely for universal Research/Backtest semantics and Binance USD-M Research/Backtest conformance;
- section 2's P9.1+ Spot-only restriction, solely to admit the bounded P9.U Research/Backtest scope;
- section 8's preference for QMT Market Data before Binance USD-M, replacing it with the sequence in this ADR.

It also supersedes only these corresponding L3 sequencing statements in `docs/p9_binance_spot_golden_vertical_execution_plan.md`:

- section 1's exclusion of Binance Futures, solely for the bounded P9.U Research/Backtest scope;
- section 5's post-Spot provider order.

The original documents remain historical decision records and must not be rewritten. An acceptance change adds only a `Superseded in part by ADR 0106` cross-reference identifying the clauses above.

Binance Spot remains the first production/LIVE Golden Vertical. This decision does not authorize a Binance USD-M LIVE vertical, alter Spot LIVE requirements, or declare the Spot Golden Vertical complete. It only permits the universal semantics and Research/Backtest conformance work after the existing Spot foundation.

## Boundary decisions

The sequence must preserve these authorities:

```text
Strategy Revision
→ immutable strategy meaning

Market Product
→ compiled market/economic policy and composition identity

Trading Kernel
→ universal deterministic state transitions

Position / Margin / Account
→ their respective canonical mutable-state authorities

Broker
→ execution observations; never account or position authority

Dataset Snapshot
→ immutable Research/Backtest input identity

Provider Plugin
→ provider DTOs, protocol, reference normalization, and provider-field translation
```

There must remain one Backtest Runtime and one Trading Kernel. No Spot/Futures engine split and no provider-specific Core branch is authorized.

## Compatibility and migration constraints

- Existing `OnlyOffset` compatibility may remain only as an input/serialization compatibility surface normalized into one canonical execution intent.
- Semantic changes to public snapshots, persisted state, Dataset manifests, broker requests, compiled policy fingerprints, or execution support decisions require explicit schema/version increments and deterministic migration or fail-closed rejection.
- Existing Spot behavior must remain a regression contract.
- Provider-exact liquidation is not inferred or approximated; unsupported behavior fails closed.

## Consequences

### Benefits

- establishes universal derivative economics before provider-specific expansion;
- makes Binance USD-M a conformance implementation rather than Core architecture;
- provides a non-Binance Futures proof against provider leakage;
- keeps later SIM/LIVE work on the same canonical semantics already exercised by Backtest.

### Costs and risks

- touches high-risk public contracts, execution, accounting, persistence, and identity surfaces;
- requires explicit compatibility migrations and bounded Independent Review;
- delays the previously preferred QMT Market Data sequencing point without removing that target.

## Acceptance record

On 2026-09-01 the repository owner explicitly authorized continuation after reviewing the proposed sequencing gate. The accepted decision applies only to the precise partial supersession above. Historical decisions remain unchanged except for non-destructive cross-references.
