# ADR 0070: Generic T0 Cash Market Product and Canonical Market IR Authority

- Status: Accepted
- Date: 2026-08-11
- Scope: P5.2 concrete Market Product and canonical authority boundary

## Context

ADR 0069 established the Market Product composition contract, but its first `OnlyCompiledMarketPolicy` still copied liquidity, slippage and matching fields from the legacy `OnlyMarketProfile`. Those fields answer how a virtual execution venue simulates fills, not what economic rules a market imposes. Keeping them in the new IR would make a concrete Market Product depend on Backtest/Sim execution choices and would duplicate Virtual Broker authority.

The legacy Profile and `OnlyCompiledMarketRules` remain current production authorities until the P5.3 one-shot Runtime cutover, so P5.2 must correct only the new contract and build a replacement candidate without adding a mixed Runtime path.

## Decision

The canonical `OnlyCompiledMarketPolicy` contains only:

```text
OnlyCompiledInstrumentMarketTerms
Session Policy
Price Policy
Quantity Policy
Position Policy
Short Policy
Settlement Policy
Margin Policy
```

`OnlyCompiledInstrumentMarketTerms` is deliberately minimal: settlement currency, contract multiplier and canonical trading status (`TRADABLE`, `SUSPENDED`, `INACTIVE`). Concrete reference data remains opaque and plugin-owned. Market-specific concepts are interpreted by the concrete compiler rather than accumulated into a universal reference DTO.

Matching, slippage, simulation liquidity, latency, fill planning and fill scheduling are excluded from Market Product IR. They belong to Virtual Broker / Execution Simulation. Market Product may define market legality and economic settlement semantics; it does not define whether or how a simulated Broker fills an order.

`onlyalpha-plugin-generic-t0-cash` is the first concrete implementation:

- provider `onlyalpha-plugin-generic-t0-cash`;
- product `GENERIC_T0_CASH@1`;
- minimal typed config containing only `reference_resource_id`;
- plugin-owned immutable references and fail-closed instrument/day authority;
- pure deterministic Generic compiler;
- plugin-owned Generic Market Fee Pack;
- `onlyalpha.market_products` entry-point discovery.

The Core composition root owns only the neutral factory registry and discovery mechanism. It neither imports nor hard-registers the Generic package and has no missing-plugin fallback. The Generic package imports the stable plugin API and has no Runtime, Broker, Risk, trading Manager, A-share, legacy Profile or legacy compiler dependency.

## Economic Compatibility

`GENERIC_T0_CASH@1` preserves the legacy economics: Generic UTC day session, reference tick, no daily price limit or previous-close dependency, reference minimum/step/maximum quantity, fractional quantities, long-only positions, short selling disabled, immediate T0 settlement, no margin, and the existing Generic Market Fee result. Matching, slippage and bar-volume participation are intentionally not compared because they are not market economics.

A tests-only `TEST_T2_MARKET` compiles tick `0.25`, quantity step `7` and T+2 settlement through the same Core contract without adding a product branch to Core.

## Migration Boundary

P5.2 does not change the Trading Runtime production authority. Legacy Generic Profile, legacy compiler, Core Generic fee registration and existing Runtime market-rule composition remain until P5.3 can prepare both Generic and CN A-share bindings and cut over atomically. No bridge, adapter, alias, fallback or product-specific Runtime dispatch is introduced.

## Consequences

- Replacing Virtual Broker with a real Broker does not change Generic Market Product semantics.
- A CN A-share plugin can compile the same canonical IR without adding `if A-share` to Core.
- Simulation policy cannot re-enter Market Product without violating the IR shape and architecture guards.
- Core continues to own mutation, Fee application and Settlement execution; the plugin only supplies immutable authorities and compiled decisions.
