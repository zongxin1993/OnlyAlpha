# ADR 0044: Runtime Checkpoint and Continuous Engine Restart

- Status: Accepted
- Date: 2026-07-29

## Context

The former restart path could rebuild only the authority immediately before one first transaction. It could not represent Ready
history, multiple tail transactions, rolling Strategy/Factor/Indicator state, Broker scheduling, open orders, MarketData windows
or a precise replay boundary. Its transaction event time was also not a valid MarketData identity.

## Decision

1. The single-transaction bootstrap is removed. Recovery starts from a complete Runtime checkpoint and an ordered transaction
   tail, without compatibility aliases.
2. A checkpoint is the Runtime authority at one stable Bar boundary; the transaction tail is durable execution after that
   boundary; the Outbox is only Projection Ready delivery intent.
3. Checkpoints are captured after each full Bar because that is the first boundary where Clock, market state, Broker queues,
   projections, EventBus and strategy callbacks can be jointly stable.
4. Replay resumes by source ID, data version, source sequence and update ID. Transaction time and event time alone are ambiguous.
5. Ready tail transactions are rehydrated because their Manager effects occurred after the checkpoint and cannot be skipped merely
   because their durable rows are Ready.
6. Recovery Replay rebuilds deterministic post-checkpoint market and Broker context only until all original tail updates have been
   resolved; ordinary Replay then continues and may create new transactions.
7. Strategy, Factor, Indicator and deterministic Broker components must explicitly declare checkpoint capability. Unknown
   components cannot be silently treated as stateless.
8. Persistence is named Runtime Persistence Store because it owns checkpoints, transactions, Projection state and Outbox in one
   database and one Runtime identity.
9. SQLite schema version 2 adds Runtime metadata plus checkpoint header/component tables.
10. Schema version 1 is rejected. There is no automatic migration or fallback.
11. Participant identity, schema version, capability and ordering form a stable registry fingerprint stored in metadata and every
    checkpoint header.
12. Header and all components are written in one SQLite transaction after canonical payload and aggregate hashes are sealed.
13. Retention is performed inside that same transaction; a failed insertion preserves every prior complete checkpoint.
14. Runtime lifecycle includes `RECOVERING` between initialization and readiness. Any restore, replay, rehydration, Coordinator or
    Outbox failure prevents `READY`.
15. Recovery Replay recognizes existing tail updates before the ordinary ExecutionProcessor. It advances deterministic sequence
    heads but neither recommits those transactions nor republishes their historical Direct Events.
16. This decision does not add Partial/Multi Fill, SELL/CLOSE, Futures/Margin or non-trade transaction semantics; Paper/Live
    recovery; exactly-once Outbox; schema migration; distributed checkpointing; remote stores; or Web state management.

## Consequences

SQLite checkpoint mode requires a complete participant set and fails assembly otherwise. The database path is stable at
`user_data/state/engines/<engine-id>/runtimes/<runtime-id>/runtime.sqlite3`; Run artifact IDs never participate in state identity.
Memory mode remains non-restartable and requires checkpoint disabled. A new Engine can use only the same product configuration
and user-data root to restore rolling state, open Broker work, multiple Ready/unprojected tail transactions, exact replay progress,
new post-restart decisions and baseline-equivalent final results.
