# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary user is the owner/operator of a personal quantitative trading system.
Small teams are a secondary audience. LLM Agents and automation assist with
Research, Backtest, SIM and Evidence analysis through the formal Product API;
they do not own LIVE authority.

## Product Purpose

OnlyAlpha is a modular, multi-market quantitative trading system that carries a
quantitative idea from Research through Backtest, SIM and LIVE while preserving
clear engineering boundaries, deterministic results, recoverable state and one
consistent trading semantic core.

Success means that the same canonical intent and strategy meaning can be
understood, verified, replayed and operated across the research-to-trading
lifecycle without hidden authority or untraceable state changes.

## Positioning

OnlyAlpha uses a market-agnostic canonical Domain and Trading Kernel behind a
versioned Product API. Immutable Strategy Revisions preserve one strategy
meaning across Backtest, SIM and LIVE; changing market/provider rules terminate
at explicit plugin, adapter or gateway boundaries.

## Operating Context

OnlyAlpha runs as a long-lived stateful server system. Operators use the Web
console and Product API for normal interaction. Agents and automation use the
same formal API for permitted research workflows. The system recovers durable
state on restart, reconciles external execution facts, and keeps Research,
Backtest, SIM and LIVE within the same canonical lifecycle vocabulary.

## Capabilities and Constraints

- Research uses immutable, content-addressed inputs and outputs, including Dataset Snapshots, Research Results and Evidence.
- Backtest, SIM and LIVE share the Trading Kernel and canonical trading semantics.
- Web is a display, input/management and command-submission surface, never a trading or Research authority.
- Agents may assist with Factor, Research, Backtest, SIM and Evidence work, but never activate or authorize LIVE.
- Core remains market-agnostic; provider, venue, broker, regulatory and protocol differences stay behind plugin, adapter and gateway boundaries.
- Important facts are deterministic, append-only or revisioned, traceable and recoverable after crash or restart.
- Unknown execution outcomes fail closed and are not converted into blind retries.

## Brand Commitments

The product name is OnlyAlpha. No additional visual, voice, legal, proof-asset or brand constraints are confirmed.

## Evidence on Hand

- `README.md` — product architecture, lifecycle, Research and trading-core description.
- `PROJECT_CONSTITUTION.md` — durable product purpose and non-negotiable boundaries.
- `docs/architecture.md` and `docs/adr/` — architecture and accepted local design decisions.
- `packages/onlyalpha-http-server/` — Product API transport.
- `packages/onlyalpha-web-console/` — Web console.

## Product Principles

- Correctness and authority boundaries outrank convenience and automation.
- Determinism, reproducibility and traceability are product behavior, not optional diagnostics.
- Durable facts and recovery must preserve one authoritative state across restarts.
- A changing external market world must not destabilize the canonical internal trading world.

