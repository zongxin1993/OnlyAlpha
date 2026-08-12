# P6.5 Streaming Durable Checkpoint Pre-Implementation Audit

- Date: 2026-08-12
- Baseline: `9a3a6b2 Fix: Close streaming processing and stop authority`
- Scope: P6.5.0 contract and current-master audit
- Product capability at baseline: SIM realtime Virtual Broker normal path and same-process continuity recovery; SIM checkpoint/restart remains unsupported

## Authority answers

The Trading Runtime owns every mutable trading authority. The Runtime Persistence Store is the durable authority for committed
transactions, projection state, outbox and checkpoints. The current MarketData Processor owns normalized sequence/dedup/gap
decisions, but Streaming continuity is split across `OnlyStreamingRuntime`, `OnlyLiveBarFinalizer` and processor participants.
`OnlyStreamingProcessingLane` is currently the only serialized MarketData processor caller, but it does not serialize Timer
callbacks, checkpoint capture or recovery-exclusive semantic work. `OnlyLiveClock` owns scheduler mechanics and logical Timer
state together; there is no separate durable Runtime Timer authority. There is no cross-process Runtime state ownership lease.

The required P6.5 ownership target is therefore:

- Runtime Persistence Store: irreversible durable records and atomic checkpoint storage;
- Runtime-neutral Checkpoint Kernel: the last complete canonical world, without driver semantics;
- Runtime-neutral Recovery Kernel: local restore, transaction-tail session and common finalization;
- Backtest participants/driver: historical replay frontier and causal historical replay;
- Streaming Continuity Tracker: canonical closed-Bar frontier and bounded overlap protection;
- Streaming Semantic Lane: the sole permission to mutate one Streaming semantic world;
- Runtime Timer Registry: logical Timer definitions and occurrence frontier;
- Timer occurrence journal: durable admission of callbacks that formally started;
- Runtime State Lease: the sole active process writer for one stable Runtime state root.

## Durable, reconstructible and ephemeral state

Durable/checkpointable state includes trading authorities, cluster Strategy/Factor/Indicator state, canonical MarketData
processor state, the driver frontier participant, execution sequencing/dedup, committed transaction/projection frontier,
reservations, deterministic Virtual Broker state, fee/settlement/margin state, deterministic Result state, logical Timer state,
admitted Timer occurrences and compatibility fingerprints.

Reconstructible operational state includes subscriptions, worker instances, LiveClock scheduler registrations, buffered realtime
overlap and Virtual Broker process resources. Ephemeral state includes threads, locks, conditions, sockets, SQLite connections,
subscription IDs, inbound queues, partial live Bars, wall/monotonic clock readings, Streaming phase and process-local Runtime
instance identity. None of the ephemeral state may enter a checkpoint.

## Current root problems

1. Checkpoint schema 4 is Backtest-shaped: the common header and capture/restore contexts contain
   `OnlyBacktestReplayCursor`. The common codec and SQLite schema persist it directly.
2. The aggregate checkpoint projection omits `market_composition_fingerprint`, so a semantic header field is not protected by
   the aggregate SHA-256.
3. Persistence schema 6 stores `replay_cursor_payload` in the common checkpoint row. P6.5 requires an explicit 5/7 schema
   break and fail-closed rejection of old state.
4. Common recovery imports/types `OnlyBacktestRecoveryReplayResult` and restores using the Backtest cursor. Recovery is not
   split into local durable bootstrap, driver continuity and common finalization.
5. `OnlyTradingRuntimeFacade` owns Backtest replay cursor, replay progress/result state and historical recovery behavior in
   addition to common Trading composition and participants.
6. Streaming continuity has multiple mutable owners and an unbounded `_processed_bar_identities` full-history set.
7. `OnlyStreamingProcessingLane` serializes only `MarketDataProcessor.process()` plus result commit. LiveClock Timer callbacks can
   mutate Strategy and trading state on another scheduler thread, and checkpoint/recovery has no shared semantic barrier.
8. Timer definitions and scheduler mechanics are coupled in Clock implementations. No durable occurrence admission exists, so
   arbitrary Strategy mutation inside a crash-interrupted Timer callback cannot be recovered exactly.
9. SIM has no new-process recovery lifecycle, no subscribe-first restart path and no post-continuity verified checkpoint.
10. SQLite locking does not provide Runtime ownership. A second process can target the same Runtime state root without a
    fail-closed state lease.
11. Virtual Broker checkpoint schema is passed as a naked constructor value instead of being owned by the deterministic Broker
    component contract.
12. `scripts/test_suite.py` and CI have no `sim-recovery` lane.

## Confirmed P6.4 defect to close before schema work

The worker calls the Processing Lane with `_record_processing_result` as its commit callback, then calls
`_handle_worker_result`. The latter calls `_record_processing_result` again. Every normal live finalized Bar therefore advances
processing results, closed-Bar counts, derived counts, continuity state and observations twice. The reaction callback must only
react to `GAP_DETECTED`.

## Crash and recovery contract

A checkpoint is advertised only after one complete semantic action, contiguous Projection Ready execution prefix, stable
required event delivery and durable read-back verification. A crash before admission produces no action. A committed execution
tail is recovered forward. A durable-admitted Timer occurrence not covered by the checkpoint is replayed idempotently; downtime
Timer deadlines that were never admitted do not create hindsight callbacks. Partial live Bars and queued updates are discarded
as process state and repaired by subscribe-first historical recovery plus buffered realtime suffix reconciliation.

Recovery must retain the stable `runtime_id`, acquire the state lease, restore local durable state, subscribe realtime before
the historical query, repair continuity through the shared continuity recovery service, resolve the transaction tail, reconcile
the buffered suffix, validate all authorities, write and verify a recovery checkpoint, complete the recovery event gate and only
then grant LIVE Strategy intent permission. Existing accepted Virtual Broker work remains active and is never cancelled,
resubmitted or assigned a new identity by lifecycle code.

## Schema and compatibility decision

P6.5 will move Runtime Checkpoint schema from 4 to 5 and Runtime Persistence schema from 6 to 7. The common header will contain
only Runtime-wide durability metadata. `backtest.replay-frontier` and `streaming.continuity` will be driver participants. No
implicit migration, compatibility alias, empty-state fallback or memory fallback is permitted. Every mismatch must fail closed
with a stable diagnostic contract.

## Initial test lanes

- P6.5.0: targeted Streaming unit/architecture tests and SIM integration regression.
- P6.5.1: checkpoint/recovery targeted tests, full recovery lane and Backtest restart/determinism integration.
- P6.5.2-P6.5.4: new `sim-recovery` unit/integration/fault tests plus architecture and recovery lanes.
- Certification: Ruff, format, core and package mypy gates, fast, integration, recovery, core-full, ashare,
  miniqmt-contract, sim-recovery, all-package build and CI configuration audit.

No implementation evidence is claimed by this audit. SIM checkpoint remains fail closed until the complete P6.5.4 product
contract and P6.5.5 certification pass.
