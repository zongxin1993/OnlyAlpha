# ADR 0065: Durable Execution Capability Semantic Authority

Status: Accepted

Date: 2026-08-09

## Context

Durable admission was granted by `market_profile_id == "GENERIC_T0_CASH"`. Processor routing, Runtime planning-context capture,
Trade Planner, and Terminal Planner independently called the same function, while the Trade Planner also repeated a profile
constant gate. Market product identity therefore acted as execution permission and support was not a unique authority.

Market capability and execution implementation capability answer different questions. Market capability describes what compiled
market rules permit. Execution implementation capability describes which frozen economic operation shapes the current canonical
transaction kernel has implemented and verified. A market feature flag cannot prove kernel support.

## Decision

`OnlyExecutionCapabilityResolver` is the sole durable admission authority. It is stateless, pure, deterministic, fail closed,
and receives one immutable `OnlyExecutionSupportContext`. It has no Manager, Registry, Broker, configuration, or plugin
dependency. The Processor captures immutable authority, projects one context, resolves once, freezes the typed decision into the
planning context, and routes only by that decision. Trade and Terminal planners reject a wrong decision as an internal routing
invariant and never re-resolve support.

The support context consists only of operation kind, Account type, Order type/side/offset, Position side/effect/mode, Margin
presence, Account/aggregate-Strategy-Ledger parity, and an exact Reservation authority shape. BUY OPEN requires Account Cash +
Strategy Cash + Risk. SELL CLOSE requires Position + Risk. Unexpected authorities fail closed because they indicate semantic
drift.

Policy version 1 supports:

- `TRADE_FILL`: CASH + LIMIT + LONG + NETTING + no Margin + parity + exact BUY OPEN or SELL CLOSE Reservation shape;
- `ORDER_TERMINAL`: the exact SELL CLOSE Position + Risk shape only.

BUY OPEN terminal remains explicitly unsupported because its Account Cash, Strategy Cash, Risk Reservation, Risk, and Order
projections are not yet one prepared terminal transaction. Margin, Short, Hedging, Market orders, SELL OPEN, BUY CLOSE, unresolved
effects, parity failure, and incorrect Reservation shapes remain unsupported.

Trade settlement support is instruction-shaped, not T0/T1-named. The existing `OnlyTradeApplicationInstruction` freezes a
representable trading-day-based settlement schedule, so no product or settlement-name permission field is added.

Every committed Trade and Terminal fact persists policy version, admitted capability, and the canonical semantic-decision
fingerprint. Recovery treats committed facts as historical authority and does not re-run today's Resolver to re-authorize them.

## Market identity boundary

**Market identity is evidence, not permission.**

Profile/version, market/venue, compiled-rule fingerprint, and reference fingerprint remain in instructions, facts, artifacts,
and recovery proofs. They identify which rules produced the operation but cannot grant durable admission. Product certification
and end-to-end conformance remain separate from kernel semantic support.

## Consequences

Two different markets that produce the same frozen economic shape receive the same support decision. The same market producing
different shapes can receive different decisions. Capability policy evolves through an explicit trusted-code policy version,
not a profile mapping, dynamic DSL, Registry, provider plugin, or compatibility wrapper.

Deleting the old function and Planner gates is intentionally source incompatible for internal callers. Git history is the only
compatibility record. A future capability may be opened only after its complete prepared transaction, projections, recovery,
and conformance are implemented.

## Rejected alternatives

- Profile-to-shape mappings preserve the same identity-as-permission defect.
- Market capability flags cannot establish OnlyAlpha implementation support.
- Planner-side re-resolution creates a second authority and can drift from routing.
- Resolver access to Managers makes admission depend on mutable timing and breaks deterministic recovery.
- Declaring BUY OPEN terminal support before implementing its atomic projections opens an unsafe capability.
