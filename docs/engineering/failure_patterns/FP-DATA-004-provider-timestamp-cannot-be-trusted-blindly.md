# FP-DATA-004 — Provider timestamps cannot be trusted blindly

## Failure family

A provider/broker emits timestamps that are malformed, outside the expected market/session window, inconsistent with sequence/state, or otherwise invalid for canonical trading semantics.

## External / internal evidence

- RedTorch operational documentation reports that broker/exchange holiday testing can push erroneous time data and break data filtering, requiring operational intervention.
  - https://github.com/sun0x00/redtorch
- Northstar documentation warns that strategy logic should use Tick-carried timestamps for replay correctness and that server-clock errors affect market-data reception.
  - https://github.com/dromara/northstar
- Evidence status: upstream operational experience/documented failure risk rather than an OnlyAlpha reproduction.

## Observed symptom

Market data may be accepted into the wrong session/day, replay and realtime decisions diverge, bars are bucketed incorrectly, or a malformed provider timestamp poisons ordering/filtering logic.

## Generalized root cause

External timestamps were treated as self-validating truth without checking provider schema, timezone, session/reference semantics, sequence relationships and clock provenance.

## Risk to OnlyAlpha

Ordered-fact determinism, trading-calendar semantics, bar aggregation, Dataset correctness, recovery and LIVE decision timing can all be corrupted by one invalid temporal fact.

## OnlyAlpha invariant

Every canonical temporal field has explicit semantics and provenance. Provider timestamps are authoritative only for the temporal fact their provider contract actually defines, and execution-relevant invalid/ambiguous timestamps fail closed before becoming canonical strategy-facing observations.

## Required protection

- typed distinction among event/provider/receive/ingest/decision time;
- explicit timezone and trading-session interpretation at provider/reference boundaries;
- validation against schema/range/session/sequence constraints where meaningful;
- preserve raw provider timestamp evidence when canonical normalization rejects or transforms it;
- never substitute local wall clock for event time silently.

## Required tests

- provider timestamp outside legal schema/range → rejected/quarantined with raw evidence preserved;
- timezone/session-boundary conversion is deterministic across replay and realtime;
- server receive clock differs from provider event time → canonical ordering semantics remain explicit;
- malformed timestamp during provider maintenance/holiday simulation cannot create a valid strategy-facing market fact.

## Non-solutions / rejected shortcuts

Blindly trusting provider time, replacing every bad timestamp with `now()`, or using host-local timezone defaults hides the defect instead of preserving temporal semantics.

## Scope notes

Applies to Market Data, Broker facts, QMT/CTP/Binance gateways, replay, bar aggregation and any future point-in-time data source. Provider-specific tolerances belong in the adapter/reference contract.