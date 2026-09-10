# FP-BROKER-002 — Full-allocation sizing ignores execution costs

## Failure family

A sizing helper allocates nominal cash/notional using price alone and leaves no capacity for commission, fees, slippage or venue-required buffers.

## External / internal evidence

- RQAlpha issue #366: full-allocation stock order sizing could produce an insufficient-cash rejection because commission/slippage were not reflected in the quantity calculation.
  - https://github.com/ricequant/rqalpha/issues/366
- Evidence status: observed upstream execution/sizing defect with a concrete failure mechanism.

## Observed symptom

A caller requests an economically valid "use available cash" allocation, but the resulting order is rejected for insufficient funds or violates risk/cash constraints once execution costs are applied.

## Generalized root cause

Portfolio sizing and executable-order affordability were treated as identical. Nominal price exposure ignored the execution/cost envelope that determines whether the venue can actually accept/fill the request.

## Risk to OnlyAlpha

Backtest/SIM/LIVE semantic drift, repeated order rejection, incorrect cash reservation, and risk-limit breaches can occur when the same Strategy/Portfolio intent is translated differently across execution environments.

## OnlyAlpha invariant

A risk-increasing order admitted for execution must be demonstrably affordable under the bound fee/execution/reference contracts. "100% allocation" is a Portfolio intent, not permission to ignore execution costs or venue constraints.

## Required protection

- keep Strategy semantics separate from Portfolio sizing and Execution/Fee profiles;
- validate executable quantity against fee/slippage/reference rules before submit;
- use exact Decimal/quantized quantity and venue constraints;
- preserve the distinction between intended target exposure and resulting executable order quantity;
- fail closed when required cost/reference inputs are unknown.

## Required tests

- full-cash target with non-zero commission → generated quantity remains executable;
- market/slippage envelope increases required cash → risk-increasing quantity is reduced/rejected deterministically;
- same Strategy Revision with different Fee/Execution profiles produces different execution quantities without changing strategy identity;
- insufficient or unknown fee/reference inputs cannot silently assume zero cost in LIVE.

## Non-solutions / rejected shortcuts

Subtracting an arbitrary fixed percentage, retrying with a smaller order after venue rejection, or embedding broker-specific fee math inside Strategy logic does not preserve the boundary.

## Scope notes

Applies to Portfolio sizing, Execution admission, Fee models, Broker adapters and Backtest/SIM/LIVE profile compatibility. The exact cost model remains stage/provider specific.