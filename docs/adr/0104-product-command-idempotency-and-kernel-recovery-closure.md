# ADR 0104: Product Command Idempotency and Kernel Recovery Closure

- Status: Accepted
- Date: 2026-08-27
- Task: P9.K.5
- Related: ADR 0090, ADR 0091, ADR 0097, ADR 0101, ADR 0103

## Context

Research Create used PostgreSQL `research_run_submission` as a command-specific retry authority, cancellation relied only on natural Run
state idempotency, Strategy Freeze could commit immutable semantic truth before its PostgreSQL projection, and the Product Kernel had a
RECOVERING lifecycle phase without production recovery work or a durable single-mutation-authority guard. These gaps left response-loss,
restart and concurrent Product Kernel scenarios insufficiently closed.

## Decision

1. Canonical UUID4 `OnlyProductCommandId` is the one global external Product Command identity.
2. PostgreSQL `product_command_receipt` is the sole active retry binding authority. Migration 0012 deterministically backfills existing
   Create records and retires the physical legacy submission table.
3. A receipt is an immutable binding from command ID, kind and canonical operational fingerprint to the current authoritative resource
   reference. It is not a workflow or lifecycle state machine.
4. Create preserves the exact historical fingerprint of canonical `{specification: ...}`. Keyed Cancel fingerprints only canonical
   `{run_id: ...}`. Transport, actor, API and request metadata remain outside semantic identities.
5. Create commits `ResearchRun + Receipt` atomically. Keyed Cancel commits the accepted Run transition (or re-proved already-cancelled
   state) and Receipt atomically. A uniqueness loser rolls back its provisional business effect and reloads the winning Receipt.
6. Cancel's `Idempotency-Key` remains optional for v2 compatibility. Without it, existing natural Run-state idempotency remains active;
   with it, the global Product Command binding applies.
7. Receipt replay loads the current ResearchRun. A mismatched, malformed or dangling Receipt fails closed and cannot create a replacement.
8. Frozen Strategy inventory is strict, verified and canonically sorted. Startup RECOVERING invokes the existing per-Strategy projection
   reconciler through `reconcile_all()`; PostgreSQL projection never repairs immutable semantic truth.
9. The production mutation-capable Product Kernel holds one PostgreSQL session advisory lock from before RECOVERING until after mutation
   admission closes and draining completes. A second process fails startup. This is a V1 single-authority guard, not leader election or HA.
10. Research Attempt/Lease/Fencing and deterministic semantic re-entry remain owned by the existing Worker protocol in ADR 0090.

## Rejected alternatives

- A generic ProductOperation table or receipt lifecycle states.
- Two active Create retry authorities.
- Cached mutable HTTP response bodies as command truth.
- Separate database transactions for business effect and Receipt.
- Redis, queue, workflow engine, distributed election or multi-master Kernel.
- Whole-Kernel serialization or moving Research Worker recovery into Kernel Host.
- Projection-to-semantic repair.

## Consequences

- Same command ID, kind and fingerprint converges to one current authoritative ResearchRun.
- Reusing a command ID across kinds or canonical intents conflicts globally.
- Response loss and process restart do not duplicate ResearchRun or cancellation effects.
- Strategy projection gaps converge deterministically at startup; conflict or corrupt inventory prevents READY.
- Production mutation is unavailable outside READY or after loss of the PostgreSQL guard.
- Migration execution remains an explicit operator responsibility; Kernel startup only verifies schema compatibility.

## Invariants

- One external Product Command ID has exactly one durable Receipt.
- Receipt and same-database accepted business effect share one transaction linearization point.
- Operational command identity never changes Research or Strategy semantic fingerprints.
- ResearchRun remains the long-running Research operation authority.
- Immutable Strategy semantic truth dominates PostgreSQL projection.
- Recovery traversal is verified and sorted.
- At most one intentionally active mutation-capable Product Kernel exists per operational database.
