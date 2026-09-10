# FP-DATA-001 — Reconnect duplicates, stale state and transient invalid observations

## Failure family

A reconnect replays duplicate events, preserves stale pre-disconnect state, or exposes transient placeholder values before the recovered stream is verified.

## External / internal evidence

- TqSdk issue #72: reconnect caused duplicate notify identity and broke notification watching.
  - https://github.com/shinnytech/tqsdk-python/issues/72
- TqSdk issue #73: reconnect required stale position/notify state cleanup to avoid already-closed positions and duplicate notifications.
  - https://github.com/shinnytech/tqsdk-python/issues/73
- TqSdk issue #74: Kline `last_id` could transiently become `-1` during reconnect before returning to the correct value.
  - https://github.com/shinnytech/tqsdk-python/issues/74
- Evidence status: observed upstream reconnect defects.

## Observed symptom

After reconnect, consumers may see a duplicated event, an already-invalid position/state, or a temporary sentinel value that is later corrected.

## Generalized root cause

Provider transport recovery and canonical state recovery were not separated. Event identity, stale-state invalidation and recovery staging were insufficiently explicit.

## Risk to OnlyAlpha

Duplicate or transient observations can produce a second canonical fact, alter a Calculation/Strategy decision, corrupt replay determinism, or make LIVE act on data that was never verified as current.

## OnlyAlpha invariant

Reconnect must not make duplicated, stale, or transiently invalid provider state authoritative.

For the same authoritative provider event identity, OnlyAlpha produces at most one effective canonical fact. State that cannot be proven current remains invalid/degraded until recovery verification completes.

## Required protection

- explicit provider-event identity / sequence semantics;
- duplicate detection at the nearest stable ingestion boundary;
- stale-state invalidation on connection-generation changes where required by the provider contract;
- recovery buffers/snapshots that do not leak unverified intermediate state;
- explicit quality/recovery state carried separately from canonical payload values.

## Required tests

- replay the final pre-disconnect event after reconnect → exactly one effective canonical observation;
- reconnect with stale pre-disconnect state → stale state cannot become current authority without reconciliation;
- provider emits a temporary sentinel/placeholder during recovery → strategy-facing authoritative stream does not observe it as valid state;
- recorded realtime stream and replay converge after duplicate/reconnect handling.

## Non-solutions / rejected shortcuts

Clearing all state blindly, accepting the latest message by wall-clock arrival, or sleeping until the provider "probably stabilized" does not prove identity or state correctness.

## Scope notes

Applies to market data, broker/account streams, QMT/CTP gateways and other diff/stateful provider protocols. Exact invalidation/recovery mechanics remain provider-specific behind their adapter contracts.