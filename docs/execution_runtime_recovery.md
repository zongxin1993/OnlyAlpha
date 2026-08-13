# Runtime Checkpoint and Continuous Backtest Recovery

OnlyAlpha uses one Runtime Persistence Store for three distinct authorities:

```text
latest complete Runtime checkpoint
+ durable execution transaction tail
+ durable at-least-once Outbox
= recoverable Runtime authority
```

The checkpoint is an immutable snapshot at a stable Bar boundary. It does not replace transactions. Transactions after the
checkpoint remain the execution tail, and the Outbox remains only the delivery intent for Projection Ready events.

## Lifecycle and barrier

Checkpoint-enabled Backtest follows `CREATED → INITIALIZING → RECOVERING → READY → RUNNING`. The Runtime creates an initial
checkpoint after Cluster initialization and queue draining. After every accepted Bar it completes market dispatch, runs the
deterministic broker, drains Broker inbound and EventBus work, verifies both inbound queues are empty, advances the exact replay
cursor, and atomically writes the checkpoint. A checkpoint failure fails processing and prevents later Bars.

The replay cursor is identified by source ID, data version, source sequence and update ID; event time is diagnostic only. It
therefore cannot skip same-timestamp updates and never uses transaction time as a resume boundary.

## Participant inventory

Runtime Checkpoint envelope schema is version 3. Participants use their explicitly registered schema version;
`broker.virtual` is version 3, while every other participant version comes from its formal registration rather than inference.
`capture_checkpoint()` returns canonical JSON-compatible owned state;
`restore_checkpoint()` validates and installs that same authority without business events.

| Component ID | Snapshot authority | Capability |
| --- | --- | --- |
| `runtime.progress` | Clock, timers, trading day, replay cursor and valuation heads | CHECKPOINTABLE |
| `data-source.<source-id>` | Historical source identity is validated by config/data version/cursor; no mutable replay state | STATELESS |
| `market-data.cache`, `.aggregation`, `.dedup`, `.sequence`, `.gap`, `.processor` | Market windows, aggregation state and processing/dedup heads | CHECKPOINTABLE |
| `market.rules` | Compiled identity plus deterministic order/match decision history | CHECKPOINTABLE |
| `account.authority`, `account.valuation-timeline` | Account authority and complete valuation history | CHECKPOINTABLE |
| `order.authority` | Orders, lifecycle/dedup indexes and ID/event sequence heads | CHECKPOINTABLE |
| `position.authority`, `allocation.authority`, `position-reservation.authority` | Position/allocation repositories, buckets, cycles, fingerprints and reservations | CHECKPOINTABLE |
| `strategy-ledger.authority` | Per-Cluster ledgers, reservations, entries and equity/valuation timelines | CHECKPOINTABLE |
| `risk.authority`, `settlement.authority`, `fee.authority`, `margin.authority` | Dynamic rule state, decisions, reservations, records and sequence heads | CHECKPOINTABLE |
| `execution.dedup`, `.sequence`, `.processor`, `.audit`, `.reconciliation` | Broker-update processing identity, diagnostics and recovery work | CHECKPOINTABLE |
| `broker.virtual` (v3) | Orders, account/positions, Fill Plans/cursors, pending scheduler work, submission controls and venue/update/trade sequences | CHECKPOINTABLE |
| `cluster.<id>.10.indicator.<factor>.<indicator>` | Declared rolling Indicator state and last snapshot | declared CHECKPOINTABLE or STATELESS |
| `cluster.<id>.20.factor.<factor>` | Declared Factor state, snapshot and trace | declared CHECKPOINTABLE or STATELESS |
| `cluster.<id>.30.strategy.<strategy>` | Declared Strategy counters, intent and signal history | declared CHECKPOINTABLE or STATELESS |
| `cluster.<id>.40.result-recorder`, `.90.factor-views` | Strategy result prefix and reconstructable factor views | CHECKPOINTABLE |

Participant IDs, schema versions and capabilities are sorted into the Registry fingerprint. SQLite assembly rejects any
DataSource, Broker, Strategy, Factor or Indicator without an explicit capability; it never infers state from Python attributes.

## Recovery order

1. Open and validate the schema-version-5 Runtime Persistence Store and stable Runtime identity. Schema 1–4 stores fail fast without
   migration, deletion or Memory fallback.
2. Load the latest complete checkpoint and verify aggregate/component hashes, schema versions, configuration fingerprint and
   Participant Registry fingerprint.
3. Restore every required participant in registry order. Strategy, Factor, Indicator and deterministic Broker capabilities must
   be explicitly declared.
4. Analyze the contiguous transaction tail. Projection Ready rows must form one prefix; unprojected rows form one suffix.
5. Replay exact MarketData after the checkpoint cursor. Before each record, enter a boundary identified by source ID, data
   version, update ID, source sequence and event time. Every Broker update enters ExecutionProcessor; each persisted Trade Fill or
   Order Terminal operation rebuilds the same Prepared contract and resolves the next causal session entry at that update point.
6. Rehydrate Ready entries through real Manager Projection Targets and recover unprojected entries through the formal Coordinator
   at their original causal points. Resolving the last persisted entry changes Execution phase to `TAIL_RESOLVED`; it does not end
   the Bar.
7. Continue the same Bar's Strategy and Broker work. New Trades after tail resolution use the ordinary Planner and
   `Coordinator.commit()`, receive contiguous Store-owned sequences, become Projection Ready and write durable Outbox rows.
   `ExecutionProcessor.replay()` suppresses immediate delivery, so these continuation rows remain pending during recovery.
8. Complete MarketData Result and Audit, observe checkpointable Result Progress, drain EventBus work, and only then let Runtime
   `after_market_processing()` confirm the exact boundary. An unresolved tail continues into the next boundary; a resolved tail
   ends causal replay only after the current boundary becomes `BOUNDARY_COMPLETED`.
9. Produce an immutable Recovery Outcome, move Clusters to `RECOVERY_FINALIZING`, call `on_recovery_complete()`, drain internal
   events, and validate transaction, Outbox, recovery projection range, manager, Broker and Runtime-boundary authority through
   read-only Ports. Finalizer preflight diagnoses non-empty Broker/MarketData inbound queues separately from pending EventBus
   work. `OnlyRuntimeTransactionOutboxKey(runtime_id, execution_sequence, event_sequence)` is the durable Outbox idempotency
   identity; it is validated independently from each Event's `event_id` and has no second string idempotency key.
10. Capture and write the post-recovery checkpoint, read it back through `latest_checkpoint()` and compare the complete header,
    aggregate hash and components. Only then mark Clusters `RECOVERED` and Runtime `READY`.
11. Deliver pending Outbox records, resume recovered Clusters without repeating `on_start()`, and continue ordinary Replay from
    the verified cursor.

Tail gaps, Ready-after-unready ordering, transaction hash conflicts, cursor mismatch, unknown/missing participants and partial or
corrupt checkpoints fail fast. Recovery never deletes or rewrites historical transactions.

## Store and configuration

```yaml
runtime:
  persistence:
    backend: SQLITE
    checkpoint:
      enabled: true
      retain_last: 2
```

The single file is
`user_data/state/engines/<engine-id>/runtimes/<runtime-id>/runtime.sqlite3`. Checkpoint header, components, transactions and
Outbox share the same connection and identity. Retention happens in the same transaction as insertion, so a failed new write
does not delete the previous complete checkpoint. SQLite Runtime Persistence schema version 5 supports discriminated
`TRADE_FILL` and `ORDER_TERMINAL` rows plus the current checkpoint/outbox contract; versions 1–4 are unsupported and are never
migrated automatically. Runtime Checkpoint envelope schema is version 3. Virtual Broker checkpoint schema is also version 3,
but remains an independently versioned participant contract.

`MEMORY` requires checkpoint to be disabled and is not restartable.

## Current limits

PR4.2.2b adds read-only post-recovery authority validation, `RECOVERY_FINALIZING`, fail-closed finalization and durable checkpoint
read-back. A commit-then-raise failure retains the checkpoint for the next Engine while preventing the current Engine from READY,
Outbox delivery or Cluster resume. Its validation closure checks cross-object Runtime, Account, Cluster, Instrument, Order,
Currency and Transaction scope for Outbox, Reservations, Fee, Settlement and Margin authorities. It relies on each Domain model
for internal amount, quantity and lifecycle invariants and does not rerun Fee, Settlement or Margin calculations. PR4.2.2c adds
the unified Runtime Event Router and Recovery Event Gate. Recovery bootstrap Direct events are discarded; historical Direct
events are suppressed during replay/finalization and never replayed; continuation transaction events remain pending in the
durable Outbox until finalization succeeds and Runtime is OPEN. The Gate is operational-only and is excluded from checkpoint and
business fingerprints. Direct delivery remains best-effort and Outbox delivery remains at-least-once. The formal committed transaction
path supports incremental Generic T0 Cash LIMIT BUY OPEN Fill transactions. PR4.3.2 makes Reservation, Fee, Account, Ledger and
Risk accounting incremental and checkpoints Order Fee Accrual authority. PR4.3.3 adds checkpointable Virtual Broker Fill Plans
and proves restart recovery across execute-before-publish, Commit, Projection, Outbox, partial-plan checkpoint and A→B→C
boundaries without a new Recovery Phase. PR4.4.2 extends that exact recovery protocol to multi-fill Long Close and durable
Cancel/Reject/Expire `ORDER_TERMINAL` operations. Close Fill 1/2 checkpoints, execute-before-publish, Commit, mid-Projection,
Outbox and A→B→C failures are compared with a no-fault baseline. Short/Hedging, Futures/Margin transactions, exactly-once
Outbox, full Broker reconciliation, schema migration, distributed checkpointing and remote stores remain outside this phase.
SIM streaming recovery is implemented through the same forward-recovery invariants and its dedicated recovery lane.

## Event delivery failure semantics

PR4.2.2c failure hardening freezes two distinct boundaries. Before Runtime Event Router OPEN, failure is completely silent:
staged bootstrap events are discarded, EventBus has no queued or dispatched work, pending Outbox is untouched, Cluster
start/resume is not attempted and `RUNTIME_STARTED` is absent. Bootstrap flush is one atomic EventBus batch, so capacity or scope
failure cannot enqueue a prefix.

After OPEN, an accepted bootstrap event or successful Outbox prefix retains its publication status and may be drained once during
stop/close cleanup. Later failure still sets Runtime and Gate to FAILED, prevents `RUNTIME_STARTED`, and must not leave a Cluster
incorrectly RUNNING. Cleanup is idempotent and does not retry the failed or untouched Outbox suffix.

Outbox `published` means only that EventBus accepted the event and the local Store completed `mark_published`; there is no
Subscriber ACK or delivery watermark. Consequently Outbox is at-least-once, while Direct delivery is best-effort. Historical
Direct events produced during recovery/finalization are suppressed permanently. Exactly-once, Direct Durable Journal and remote
EventBus remain outside the implemented contract.
# Multi-Cluster Close 恢复

恢复不重新选择成本。Attributed Close 结论已经冻结在 Projection Before/After、Committed Fact、authority hash 和 payload hash 中。Post-recovery validation 同时校验 Position/Allocation 的数量与精确累计成本聚合；Strategy Ledger timeline checkpoint 按 Runtime 全局 sequence 恢复。
