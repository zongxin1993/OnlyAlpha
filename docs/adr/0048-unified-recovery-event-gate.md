# ADR 0048: Unified Recovery Event Gate

- Status: Accepted
- Date: 2026-07-29

## Context

`ExecutionProcessor.replay()` forces its delivery intent to `NONE`, but this controls only the immediate Execution Delivery
Coordinator call. Order, Risk, MarketData result facts and Runtime lifecycle bypassed it, while manager direct batches and the
durable Outbox each held their own EventBus writer. Causal replay could therefore rebuild correct internal authority while
republishing historical non-durable facts.

EventBus must remain a bounded scoped FIFO queue and handler dispatcher. Teaching it Runtime or recovery state would reverse the
dependency direction and mix transport with product lifecycle. The synchronous MarketData and execution pipelines already own
business state transitions, so a second internal EventBus would add another ordering authority without solving publication.

## Decision

The existing EventBus is the Runtime's externally observable event plane. Every business publisher now targets one of three low
level ports, implemented by the single `OnlyRuntimeEventRouter`:

- `EXTERNAL_DIRECT`: non-durable, best-effort facts;
- `DURABLE_OUTBOX`: Projection Ready committed-transaction events;
- `LIFECYCLE`: Runtime lifecycle facts such as `RUNTIME_STARTED`.

The Router validates Runtime scope before consulting `OnlyRuntimeRecoveryEventGate`. The Gate begins in `BOOTSTRAPPING`, not
`OPEN`, because Account and Ledger facts are produced before the Runtime knows whether it is fresh or will restore a checkpoint.
Its legal lifecycle is `BOOTSTRAPPING → READY_BLOCKED → OPEN` for fresh start or
`BOOTSTRAPPING → RECOVERING → FINALIZING → READY_BLOCKED → OPEN` for recovery, with fail-closed transitions to `FAILED` and then
`CLOSED`.

Direct facts in `BOOTSTRAPPING` and `READY_BLOCKED` enter an event-capacity-bounded FIFO staging buffer. Fresh start flushes the
buffer only after plugin start and Router open. Discovery of a checkpoint discards the entire bootstrap buffer because those
temporary authorities will be replaced by checkpoint restore. Direct facts in `RECOVERING` and `FINALIZING` are `SUPPRESSED`,
sampled in bounded operational diagnostics, and never delivered later. Gate phase, staging, counters and samples are neither
checkpoint participants nor business projection/fingerprint fields.

Durable and lifecycle routes are rejected outside `OPEN`; they are never staged or suppressed. A recovery continuation is an
ordinary committed transaction whose delivery intent is already persisted in the Runtime Outbox. After finalization validation,
checkpoint durable verification and Router open, Runtime start drains that Outbox before Cluster resume and `RUNTIME_STARTED`.
Outbox remains at-least-once: only `PUBLISHED` permits `mark_published()`.

Order, Risk and Execution depend only on publication protocols in `onlyalpha.event.ports`; they do not import Router, Gate or
EventBus. Account, Position, Allocation, Ledger, Valuation and Settlement managers still write the existing Execution Event
Buffer. Finalizer retains raw EventBus drain/quiescence access but owns neither Gate transitions nor durable delivery. Runtime's
public `event_bus` now returns `OnlyEventBusSubscriptionView`, which supports subscription and diagnostics but exposes no publish,
dispatch, drain or close authority.

## Reliability contract and consequences

Recovery no longer actively republishes historical Direct events, and discarded/suppressed events are never flushed. Direct
events can still be lost across a crash. Without a durable Direct journal, delivery watermark and subscriber ACK, Direct delivery
cannot simultaneously guarantee both no duplicates and no loss.

Durable Outbox delivery remains at-least-once, not exactly-once. This decision does not add a Direct replay API, remote bus,
subscriber ACK, exactly-once delivery, a new persistence table/schema, another EventBus, Paper/Live recovery, Partial/Multi-Fill,
SELL/CLOSE, formal Futures/Margin transactions or non-trade transactions. Recovery Outcome, causal session, exact boundary,
Finalizer phase, authority validation, checkpoint schema, transaction authority, canonical business projection and result
fingerprint are unchanged.

## Failure boundaries

Failure before Router `OPEN` is completely silent: the Gate and Runtime fail closed, bootstrap staging is discarded, EventBus
queue and dispatch results remain empty, pending Outbox is not attempted, Clusters are not started/resumed, and
`RUNTIME_STARTED` is not published. Historical Direct events suppressed in `RECOVERING` or `FINALIZING` are permanently
discarded and are never compensated after OPEN.

Router bootstrap flush uses EventBus atomic batch enqueue. The transport first verifies that it is accepting, validates every
scope and checks aggregate capacity, then appends the whole batch. REJECT and FAIL_RUNTIME policies support this operation;
DROP_LOW_PRIORITY rejects it because replacement would not have an unambiguous atomic contract. Thus a failed Router open leaves
no partial bootstrap prefix in the queue.

Failure after Router `OPEN` is different. Bootstrap events or a successful Durable Outbox prefix may already have been accepted
by EventBus and can be drained once during cleanup. They must not be described as never published, removed retroactively, or
dispatched twice. The Runtime still becomes FAILED, no Cluster may be reported RUNNING after a failed start/resume, and
`RUNTIME_STARTED` is not published.

An Outbox record's `published` flag means EventBus accepted the event and local `mark_published()` completed. It does not mean a
subscriber acknowledged or processed it. Outbox remains at-least-once. Direct events remain best-effort and can be lost in a
failure window. Subscriber ACK, delivery watermark, Direct durable journal, exactly-once and remote EventBus are not implemented.
