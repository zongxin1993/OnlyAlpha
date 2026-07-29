# ADR 0047: Post-Recovery Authority Validation and Finalization

- Status: Accepted
- Date: 2026-07-29

## Context

Exact causal replay proves that persisted execution tail entries were resolved at their original Broker Update points and that the
last MarketData boundary completed. It does not prove that every Runtime-owned authority agrees, that callback-created internal
work is quiescent, or that the new recovery checkpoint can be read back from durable storage. Therefore “replay completed” is not
equivalent to “Runtime stable and durable”.

The previous close-out called `on_recovery_complete()`, immediately marked Cluster `RECOVERED`, performed a shallow Runtime-private
check, and wrote a checkpoint without read-back. Validation or a wrapper exception after SQLite commit could consequently leave
ambiguous lifecycle state.

## Decision

Recovery now follows:

```text
Orchestrator outcome
→ RECOVERY_FINALIZING
→ completion callback
→ EventBus drain and quiescence
→ read-only authority validation
→ immutable checkpoint capture
→ durable write
→ latest-checkpoint read-back and full comparison
→ RECOVERED
→ READY
→ pending Outbox delivery
→ RUNNING
```

`RECOVERY_FINALIZING` separates an extension callback from permission to resume. The callback may update restored extension state
or publish internal facts, but success alone never marks the Cluster recovered. `mark_recovered_all()` is legal only after
validation and durable verification.

The Orchestrator owns checkpoint load/contract verification, participant restore, recovery planning, causal replay and an
immutable `OnlyRuntimeRecoveryOutcome`. The outcome identifies the restored checkpoint, diagnostic final head, persisted-tail and
continuation sequence ranges, exact final boundary and whether replay occurred. It does not validate all managers.

The Validator receives a narrow immutable context of query/snapshot Ports. It never receives `OnlyRuntimeServices`, reads private
manager containers, or mutates authority. It checks transaction sequence/readiness/identities, Outbox references and publication,
this recovery's applied-projection range, position/allocation, order/reservation, account/all ledgers, fee/settlement/margin,
broker/local open orders, queues, EventBus, cursor/result progress/processor sequence and clock. Existing Runtime ledger
reconciliation and manager snapshots remain the formula authorities; the Validator does not reimplement PnL, fee, margin,
settlement, position, account or risk reducers. Checks are canonically sorted by code/scope and SHA-256 fingerprinted as operational
diagnostics; that fingerprint is excluded from canonical business projection.

`OnlyInMemoryAppliedProjectionLedger` remains a discardable application index. The durable transaction store is the only
transaction authority. A new Engine need not reconstruct the checkpoint prefix in this in-memory ledger, so validation covers only
the current persisted-tail plus continuation range. No SQLite applied-ledger table is introduced.

The Checkpoint Service has one shared capture path plus explicit `capture()`, `write()` and `verify_durable()`. Ordinary per-Bar
checkpoints use capture/write. Post-recovery finalization additionally queries `latest_checkpoint(runtime_id)`, validates its
contract and compares runtime identity, checkpoint/covered sequence, schema/time, complete cursor, config and participant
fingerprints, aggregate hash, pending Outbox count and components.

If write raises after the expected checkpoint was committed, the current Engine fails closed with
`POST_RECOVERY_CHECKPOINT_COMMITTED_BUT_FINALIZATION_INTERRUPTED`. The committed checkpoint is retained: deleting it would discard a
valid durable authority boundary and create a wider replay window. A later Engine may restore it and continue without duplicate
business mutation. If latest does not equal expected, the error is a write failure. Callback, quiescence, validation, capture,
write, read-back or comparison failure always makes affected Clusters and Runtime failed; no recovered Outbox is delivered and no
Cluster resumes.

Outbox remains at-least-once and is delivered only by Runtime start after finalization has made Runtime READY. Exactly-once delivery
is not claimed.

## Consequences and remaining scope

This decision hardens Historical Backtest recovery only. Unified Recovery Event Gate and complete migration of direct event
publishers remain later work. Partial/Multi-Fill, SELL/CLOSE, formal Futures/Margin and non-trade transactions, Paper/Live recovery,
full Broker reconciliation, schema migration, distributed checkpoints, remote persistence and Web recovery control remain
unsupported.
