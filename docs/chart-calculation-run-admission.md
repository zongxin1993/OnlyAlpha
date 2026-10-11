# Typed Chart Research Run admission

## Authority and permissions

The internal `OnlyChartCalculationRunAdmissionService` consumes an authoritatively stored Chart compilation. It does not
compile again, select a current Registry, acquire input, create Scientific Candidates, execute Calculation backends or publish
Result/Evidence/Artifact. Generic Research admission remains Specification V1/V2 only. No HTTP/Web entry is added here.

A separate [exact hosted execution projection](chart-calculation-execution.md) may diagnose values/readiness without
claiming this Run or publishing any Result/Evidence/Artifact. It does not change the admission or legacy Worker permission table.

| Origin | Admission | Legacy Worker capability |
|---|---|---|
| `GENERAL` | Existing Research command and Novelty rules, Specification V1/V2 | Existing exact generation/provenance rules |
| `PRIVATE_STRATEGY` | Existing immutable Composition and Research command rules, Specification V1/V2 | Existing exact generation/provenance rules |
| `CHART_CALCULATION` | Internal verified T1/T2/D2 handoff, Specification V3 | None; Result Plan V4 execution requires separate authorization |

The original Product Admission/Receipt still identifies the Chart Operation. `reserved_run_id`, never the Operation UUID or a
retry-generated UUID, identifies the Research occurrence. The Run's `admission_resolution_fingerprint` is the frozen compilation
fingerprint: the compilation itself is the complete, immutable admission-resolution evidence, not a second resolution authority.

## Verification closure

Owning readers must verify the complete Product Admission/Receipt/Operation and either an intact reservation without a Run, or
one exact consumed Operation→Run relation without a reservation. Consumption requires the complete append-only `INPUT_READY`
preparation chain, exact revision/fence/pin, immutable Snapshot/materialization lineage and stored D2 compilation, including
Specification V3, Job V2, Result Plan V4, Graph/Calculation/output and implementation membership. Physical Dataset and original
Runtime binding/manifest verification occur through their formal ports, never a receiver Registry or database-as-integration API.

An expired preparation lease does not invalidate a terminal immutable `INPUT_READY` fact. A caller-authored, fingerprint-correct
alternative compilation is not admission evidence: the persistence entry compares it with the whole stored D2 compilation.

First handoff requires the original active `NEW_WORK` binding, owner `CHART_CALCULATION_INPUT`, and the exact validated generation
available for already-bound work (READY/ACTIVE/DRAINING). Activation switching does not redefine that work. RETIRED or inactive
binding cannot authorize first handoff. Historical committed replay verifies retained generation identity and the exact original
binding without activation, rebinding, release, compilation or execution permission.

## Atomic handoff and recovery

```text
global Product Command lock
  → verify whole T1/T2/D2 and check existing consumed relation
  → existing: exact historical replay, original queue timestamp retained
  → new: research_run ROW EXCLUSIVE table lock (before frontier, matching T1 SHARE ordering)
       → source-history frontier lock (before reservation uniqueness)
       → Runtime shared lifecycle proof lock
       → verify original binding and bound-generation availability
       → delete exactly one owned reservation
       → insert reserved Research Run QUEUED, revision 0, explicit Chart origin
       → insert immutable unique Operation↔Run/compilation/queue relation
       → PostgreSQL COMMIT, including source-history and deferred relation guards
       → release Runtime proof lock
  → independent post-commit exact authoritative read
```

The existing Research Run row is the queue. No second queue, receipt, Worker or Scheduler is introduced. Runtime shared proof
locking lasts through the actual database commit; Runtime lifecycle mutation requires its exclusive lock. Database locks are
acquired before this shared lock, and Runtime lifecycle writers must not acquire PostgreSQL locks inside an exclusive lock.

Same-operation concurrency serializes through the existing command lock. Run PK and unique relation endpoints arbitrate identity
conflicts. Reservation exclusion is transferred to the Run PK, using the unchanged unique-index reservation probe from migration
0044. Source-history writes are part of the same transaction. A rollback restores the reservation and publishes no Run/relation.

Lost acknowledgement or a silently unsuccessful context exit cannot prove admission. Only a complete post-commit reload proves
success. Missing/corrupt/unavailable composite proof fails closed; it never grants certified absence, blind retry, a second UUID,
Runtime release or compensation. Restart follows the same verified replay path. An explicitly authorized queued cancellation
uses the existing `QUEUED → CANCELLED` command, retains the immutable admission, and creates no execution Attempt.

## Worker and Novelty fences

### Immutable admission versus lifecycle values

The Chart Domain representation uses the existing Run enum and transition
authority; it does not confer database execution permission. Immutable admission
verification compares the original reserved Run, exact Specification/canonical
payload, frozen Compilation identity and origin, independently of later lifecycle
fields. The owning D3 relation separately verifies the original queue timestamp.
Missing optional Result/Artifact facts never negate the occurrence or its owner.

Chart lifecycle value shapes have exact revisions: QUEUED0, RUNNING1,
CANCEL_REQUESTED2, direct CANCELLED1, and execution terminal revision2 without a
cancel request or revision3 after one. Retry gaps and heartbeat do not change Run
revision; Attempt facts belong to their separate Authority. COMPLETED values need
Result/Artifact and exactly one selected Evidence reference. FAILED may retain an
already committed Result and selected Evidence; refs are locators, not scientific
verification. Other Chart states carry no finalized publication projection. An
absent Run ref is not a statement that immutable scientific facts do not exist.

Domain shape/admission validation does not prove Attempt ownership, lease,
authoritative history, scientific closure or terminal COMMIT. Current database
guards remain closed under migrations 0048/0049; owning historical readers remain
closed-first until the complete forward lifecycle/recovery boundary is delivered.
The generic Store still allows only Human cancellation intent, the legacy Worker
retains its Spec1/2 allowlist, and E1 `hold_queued_run` still requires QUEUED.

Claim SQL uses a positive origin-and-Specification capability allowlist before any Run/Attempt mutation, even when Runtime eligible
IDs explicitly contain Chart work. Expiry, heartbeat, cancellation recovery and direct finalization retain the same capability
fence. Under the current 0048/0049 database, durable Chart Runs cannot enter
RUNNING/CANCEL_REQUESTED/FAILED/COMPLETED merely because those Domain values are
representable. Legacy V1/V2 work is not starved by an older Chart row.

Chart operational occurrences are not scientific Novelty candidates. Both in-flight classification and post-cut freshness checks
exclude only verified typed Chart relations. Historical classification uses retained event origin/payload and exact immutable
occurrence ownership, not today's mutable status or absence of a Novelty row. Invalid unclassified legacy work remains blocking.
Freshness must first prove contiguous post-cut journal coverage through the locked current frontier; missing middle/tail/whole
suffix fails closed, never certifies irrelevance. Source cuts retain Chart facts; Memory reference readers verify retained Runtime
identity without granting execution eligibility.

Migration 0048 preserves 0001–0047 bytes/checksums and existing fact bytes; schema+ledger rollback is atomic and retry deterministic.
After admission facts exist, rollback requires disabling new writers and retaining compatible authority readers, restoring a
snapshot or forward-fixing—not deleting durable facts or disabling reservation exclusion.
