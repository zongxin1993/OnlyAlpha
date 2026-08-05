# ADR 0046: Recovery Tail Resolution and Exact Replay Boundary

- Status: Accepted
- Date: 2026-07-29

## Context

ADR 0045 established causal Ready rehydration and unprojected recovery at the original Broker Update point, but
`OnlyExecutionRecoverySession.complete` still meant only that the persisted tail index was exhausted. Backtest Replay then used
that boolean to call `complete_boundary()` after a single-record replay returned. The Execution Session therefore owned a
MarketData boolean and the product path conflated persisted-tail resolution with completion of the current Bar.

If the last persisted fill was resolved before Strategy dispatch, Strategy could observe the restored Position, Account and
Ledger and submit a new order. A deterministic Broker could fill that order later in the same Bar. The new Trade was sent to
`require_expected()` while no persisted entry remained and was incorrectly rejected as `RECOVERY_TRANSACTION_MISSING`.

## Decision

1. Execution recovery has one formal phase: `MATCHING_PERSISTED_TAIL → TAIL_RESOLVED`, or irreversible `FAILED`. Tail resolution
   is not a MarketData completion fact.
2. `decide(update, prepared)` returns exactly one of `REHYDRATE_READY`, `RECOVER_UNPROJECTED` or `COMMIT_CONTINUATION`. While the
   tail is still matching, a missing or out-of-order transaction continues to fail closed; it cannot bypass the persisted plan.
3. Once the tail is resolved, a new Trade is a continuation. It uses the ordinary Planning Context, Planner and
   `OnlyRuntimeTransactionCoordinator.commit()`, so the Runtime Persistence Store assigns the next sequence, writes the transaction
   and durable Outbox, applies the formal projections and marks Projection Ready.
4. A continuation is recorded in the Recovery Session only to validate contiguous sequence, Runtime scope and unique transaction,
   Broker Update and Trade identities. The Runtime Persistence Store remains the authority.
5. Continuation processing status is ordinary `APPLIED`. It is not Duplicate, Ready rehydration or unprojected recovery.
   `ExecutionProcessor.replay()` forces delivery intent to `NONE`, so its durable Outbox remains pending during causal replay.
6. Execution recovery imports no Runtime or Backtest type. Exact replay identity belongs to
   `OnlyBacktestRecoveryBoundary(source_id, data_version, update_id, source_sequence, ts_event)` and
   `OnlyBacktestRecoverySession` composes the Execution Session.
7. Boundary identity is not a timestamp. Same-timestamp updates remain distinct through source ID, data version, update ID and
   source sequence. Scope must match the checkpoint cursor and sequence must move forward.
8. Backtest phase is `MATCHING_PERSISTED_TAIL`, `TAIL_RESOLVED_BOUNDARY_OPEN`, `BOUNDARY_COMPLETED` or `FAILED`. A completed Bar may
   lead to another boundary while the tail is unresolved; resolving the tail leaves the current boundary open.
9. Only Runtime `after_market_processing()` may observe boundary completion, after MarketData Audit append, Result Progress
   observation and EventBus drain. Recovery Replay enters the exact record boundary and stops only after that callback confirms it.
10. Ordinary per-Bar checkpoint writes remain suppressed while the composed Backtest Session is active, including after its phase
    becomes `BOUNDARY_COMPLETED`. The existing `_recover_runtime()` path creates the post-recovery checkpoint.
11. RECOVERING Strategy order commands and timers are allowed because causal replay must execute the remainder of the Bar. This
    does not add a separate product entry or give Strategy access to Runtime managers.

## Consequences

Same-Bar continuation, multi-boundary tail and three-continuation Engine restart scenarios now compare equal to their no-failure
canonical business projections. Old `complete`, `boundary_complete`, `_boundary_complete`, `complete_boundary()`,
`require_complete()`, `require_expected()` and `resolve()` Recovery Session APIs are removed without compatibility wrappers.

This ADR implements only PR4.2.2a phase, boundary and continuation transaction semantics. Unified Recovery Event Gate,
Post-Recovery Authority Validator redesign and Recovery Finalizer remain PR4.2.2b/PR4.2.2c work. Partial/Multi-Fill,
SELL/CLOSE, Futures/Margin, non-trade transaction recovery, Paper/Live recovery, exactly-once Outbox, full Broker
reconciliation, schema migration and distributed checkpointing remain out of scope.
