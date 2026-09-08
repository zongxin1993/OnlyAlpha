# ADR 0104: Product Command Idempotency and Kernel Recovery Closure

- Status: Accepted
- Date: 2026-08-27 (amended 2026-09-08 for immutable Product Command Admission Authority)
- Task: P9.K.5
- Related: ADR 0090, ADR 0091, ADR 0097, ADR 0101, ADR 0103, ADR 0124

## Context

Research Create used PostgreSQL `research_run_submission` as a command-specific retry authority, cancellation relied only on natural Run
state idempotency, Strategy Freeze could commit immutable semantic truth before its PostgreSQL projection, and the Product Kernel had a
RECOVERING lifecycle phase without production recovery work or a durable single-mutation-authority guard. These gaps left response-loss,
restart and concurrent Product Kernel scenarios insufficiently closed.

ADR 0124 later introduced Search Product commands whose Search facts and PostgreSQL Product records cannot share one transaction. If a
Search effect becomes durable before its Receipt, Search history can prove the semantic effect but cannot prove which externally chosen
Product Command ID and canonical intent caused it: Product identity is intentionally excluded from Search identity. Strict global
same-ID/different-intent conflict therefore requires an immutable Product-side admission fact before cross-authority semantic work.

## Decision

1. Canonical UUID4 `OnlyProductCommandId` is the one global external Product Command identity.
2. PostgreSQL `product_command_admission` is the sole Product Command identity-binding Authority. One immutable row binds the globally
   unique command ID to exactly one command kind and canonical operational fingerprint before any cross-authority semantic effect may
   execute. Same ID with another kind or fingerprint always conflicts, including when no Receipt exists.
3. PostgreSQL `product_command_receipt` is the sole accepted-outcome and replay-binding Authority. A Receipt binds one exact admitted
   Product Command to the current authoritative resource reference. Its copied command kind and fingerprint must equal the Admission;
   those fields are integrity projections, not a second command-intent Authority. A Receipt is not a workflow or lifecycle state machine.
4. Admission and Receipt own different facts. An Admission proves only immutable command identity reservation; it does not prove that an
   effect occurred, authorize blind execution, represent pending/running/completed state, or substitute for a Receipt. A Receipt cannot
   exist without an exact matching Admission. Missing, corrupt, or mismatched pairs fail closed and are never repaired by replacement.
5. Before keyed mutation, the Product boundary validates and canonicalizes the complete intent, then insert-or-exact-loads Admission.
   Uniqueness loss reloads and verifies the winner. Only the exact admitted intent may proceed to current-state execution admission or
   historical-effect verification. Receipt lookup/replay occurs only after Admission verification.
6. Existing same-PostgreSQL commands may commit `Admission + business effect + Receipt` atomically. Cross-authority commands commit
   Admission first, then one independently authoritative semantic effect, then Receipt. An Admission-without-Receipt retry must prove the
   exact current precondition before new work or prove the exact already-durable effect before Receipt repair; uncertainty fails closed.
7. Migration 0012 remains the historical Receipt migration. A later explicitly authorized migration must create the Admission relation,
   deterministically backfill exactly one Admission from every valid Receipt, reject conflicting/corrupt legacy bindings, and make every
   new Receipt reference an exact matching Admission. Migration, compatibility-window, rollback and restart details remain deferred to
   that implementation contract.
8. Create preserves the exact historical fingerprint of canonical `{specification: ...}`. Keyed Cancel fingerprints only canonical
   `{run_id: ...}`. Transport, actor, API and request metadata remain outside semantic identities.
9. Create commits `Admission + ResearchRun + Receipt` atomically. Keyed Cancel commits Admission, the accepted Run transition (or
   re-proved already-cancelled state), and Receipt atomically. A uniqueness loser rolls back its provisional business effect and reloads
   and verifies the winning Admission and Receipt.
10. Cancel's `Idempotency-Key` remains optional for v2 compatibility. Without it, existing natural Run-state idempotency remains active;
   with it, the global Product Command binding applies.
11. Receipt replay loads the current ResearchRun. A mismatched, malformed or dangling Admission/Receipt fails closed and cannot create a
   replacement.
12. Frozen Strategy inventory is strict, verified and canonically sorted. Startup RECOVERING invokes the existing per-Strategy projection
   reconciler through `reconcile_all()`; PostgreSQL projection never repairs immutable semantic truth.
13. The production mutation-capable Product Kernel holds one PostgreSQL session advisory lock from before RECOVERING until after mutation
   admission closes and draining completes. A second process fails startup. This is a V1 single-authority guard, not leader election or HA.
14. Research Attempt/Lease/Fencing and deterministic semantic re-entry remain owned by the existing Worker protocol in ADR 0090.

### Product Command Admission V1

The transport-neutral immutable value is conceptually:

```text
OnlyProductCommandAdmissionV1
  schema_version = 1
  command_id: OnlyProductCommandId
  command_kind: OnlyProductCommandKind
  command_fingerprint: canonical lower-case SHA-256
```

`command_id` is its canonical identity and PostgreSQL primary key. Insert of exact same content is reuse; the same ID with another
kind, fingerprint, schema, malformed value, or unsupported value is conflict. Admission contains no outcome, status, lifecycle phase,
attempt, lease, owner, mutable timestamp, HTTP metadata, actor identity, or Search fact. Observation time may exist only as
non-identity operational telemetry outside this Authority.

### Migration and compatibility contract

The future migration is additive and phased:

```text
precondition:
  migration 0012 is applied
  every existing Receipt exact-loads and has canonical ID/kind/fingerprint

phase 1:
  create product_command_admission without changing Receipt meaning
  transactionally backfill one V1 Admission from every existing Receipt
  identical retry/restart is a no-op; any conflict aborts the migration

phase 2:
  deploy Admission-aware writers that insert/verify Admission before mutation
  keep existing Receipt kind/fingerprint columns as integrity projections

phase 3:
  after every supported writer is Admission-aware, enforce that each Receipt
  has exactly one matching Admission and reject Admission-bypassing writers
```

The migration never rewrites or deletes a Receipt or business fact. Before phase-3 enforcement, rollback may restore the old binary
while leaving the additive Admission rows intact. After enforcement, an Admission-unaware binary is incompatible and startup/mutation
must fail closed; rollback requires restoring a compatible schema/application pair or a forward fix, never deleting Admissions.
Crash/restart repeats the transactional backfill and verification deterministically.

## Rejected alternatives

- A generic ProductOperation/workflow table or mutable Admission/Receipt lifecycle states.
- Two Authorities for Product Command intent or two Authorities for accepted outcome.
- Treating Admission-without-Receipt as proof that semantic work occurred or as authorization for blind retry.
- Cached mutable HTTP response bodies as command truth.
- Separate database transactions for Admission, same-PostgreSQL business effect, and Receipt when one atomic transaction is available.
- Redis, queue, workflow engine, distributed election or multi-master Kernel.
- Whole-Kernel serialization or moving Research Worker recovery into Kernel Host.
- Projection-to-semantic repair.

## Consequences

- Same command ID, kind and fingerprint converges to one immutable Admission and one accepted outcome when execution succeeds.
- Reusing a command ID across kinds or canonical intents conflicts globally.
- Response loss and process restart do not duplicate ResearchRun or cancellation effects.
- Cross-authority commands can retain strict identity conflict after Receipt loss because Admission survives independently of outcome.
- Strategy projection gaps converge deterministically at startup; conflict or corrupt inventory prevents READY.
- Production mutation is unavailable outside READY or after loss of the PostgreSQL guard.
- Migration execution remains an explicit operator responsibility; Kernel startup only verifies schema compatibility.

## Invariants

- One external Product Command ID has exactly one immutable Admission and at most one durable Receipt.
- Admission is the sole command ID/kind/fingerprint Authority; Receipt is the sole accepted-outcome/replay Authority.
- Every Receipt exact-matches one Admission; an Admission alone never certifies an effect.
- Admission, Receipt and same-database accepted business effect share one transaction linearization point for existing atomic commands.
- Operational command identity never changes Research or Strategy semantic fingerprints.
- ResearchRun remains the long-running Research operation authority.
- Immutable Strategy semantic truth dominates PostgreSQL projection.
- Recovery traversal is verified and sorted.
- At most one intentionally active mutation-capable Product Kernel exists per operational database.
