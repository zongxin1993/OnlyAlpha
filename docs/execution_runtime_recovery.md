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

Every current component uses participant schema version 1. `capture_checkpoint()` returns canonical JSON-compatible owned state;
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
| `broker.virtual` | Orders, account/positions, pending scheduler work and venue/update/trade sequences | CHECKPOINTABLE |
| `cluster.<id>.10.indicator.<factor>.<indicator>` | Declared rolling Indicator state and last snapshot | declared CHECKPOINTABLE or STATELESS |
| `cluster.<id>.20.factor.<factor>` | Declared Factor state, snapshot and trace | declared CHECKPOINTABLE or STATELESS |
| `cluster.<id>.30.strategy.<strategy>` | Declared Strategy counters, intent and signal history | declared CHECKPOINTABLE or STATELESS |
| `cluster.<id>.40.result-recorder`, `.90.factor-views` | Strategy result prefix and reconstructable factor views | CHECKPOINTABLE |

Participant IDs, schema versions and capabilities are sorted into the Registry fingerprint. SQLite assembly rejects any
DataSource, Broker, Strategy, Factor or Indicator without an explicit capability; it never infers state from Python attributes.

## Recovery order

1. Open and validate the schema-version-2 Runtime store and stable Runtime identity.
2. Load the latest complete checkpoint and verify aggregate/component hashes, schema versions, configuration fingerprint and
   Participant Registry fingerprint.
3. Restore every required participant in registry order. Strategy, Factor, Indicator and deterministic Broker capabilities must
   be explicitly declared.
4. Analyze the contiguous transaction tail. Projection Ready rows must form one prefix; unprojected rows form one suffix.
5. Replay only enough MarketData after the checkpoint cursor to reproduce every tail Broker update. Existing transaction IDs are
   resolved without recommit and historical Direct Events are not republished.
6. Rehydrate the Ready prefix through real Manager Projection Targets, then recover the unprojected suffix through the formal
   Coordinator.
7. Persist a new stable checkpoint, deliver pending Outbox records, and continue ordinary Replay from the recovered cursor.

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
does not delete the previous complete checkpoint. SQLite schema version 1 is unsupported and is never migrated automatically.

`MEMORY` requires checkpoint to be disabled and is not restartable.

## Current limits

The formal committed transaction path remains Generic T0 Cash LIMIT BUY OPEN whole fills. Partial/Multi Fill, SELL/CLOSE,
Futures/Margin transactions, non-trade transactions, Paper/Live recovery, exactly-once Outbox, schema migration, distributed
checkpointing and remote stores remain outside this phase.
