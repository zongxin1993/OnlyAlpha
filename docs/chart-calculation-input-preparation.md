# Chart calculation input preparation

The application preparation boundary consumes an immutable admitted chart operation, an explicit exact Runtime Generation
fingerprint and a worker identity. It prepares one instrument's native fixed-duration 15m LAST/RAW SESSION_START input.
It owns neither Market Data nor Dataset truth and does not admit a Specification, Research Run or Calculation execution.

`OnlyMarketDataProductService.plan_selection` resolves the exact Integration Revision, canonical source, binding fingerprint,
plugin-native construction and grid-aligned scope. This read-only planning method does not create/authenticate provider sessions,
open WAL, fetch reference instruments, acquire data or write Market Data authority. Derived resolution is rejected.

`OnlyChartCalculationPreparationService` verifies the supplied Runtime Generation against the Catalog Generation frozen in
 admission. Fresh work requires `ACTIVE_FOR_NEW_WORK` before claiming and again immediately before first binding
 `operation.reserved_run_id.value` through `OnlyRuntimeGenerationWorkAuthority.bind_new_work_exact`. The Runtime Authority compares
 the expected active generation, verifies its exact validation evidence and appends `RuntimeWorkBound` under one exclusive lock;
 activation cannot interleave between comparison and binding. Existing `bind_work_exact` historical semantics remain unchanged.
 A claim without a binding can recover
 only while its frozen generation remains eligible for new work. Activation change before binding commits definitive
 `CHART_RUNTIME_GENERATION_NOT_ELIGIBLE`; it never falls forward to another generation.
 Recovery of an exact active binding may continue in its historical READY/ACTIVE/DRAINING generation without consulting current
 activation. A binding without a preparation claim is an orphan/conflict, never adopted or released by this service.
 Reentry must provide the same fingerprint. Conflicting bindings, or inactive bindings for nonterminal/`INPUT_READY`
  preparation, require intervention and are never reactivated.

Binding adoption and release require `OnlyRuntimeWorkBindingEvidence`, reconstructed from the verified Runtime event chain:
one original binding event, canonical event fingerprint/sequence, original audit actor, current active state, exact work/generation,
`NEW_WORK` event family and stable owner `CHART_CALCULATION_INPUT`. The atomic API persists owner in the event's existing `reason`;
actor may change on retry, but owner and original event evidence cannot. `RuntimeExactWorkBound`, another owner, or legacy ownerless
new-work history cannot satisfy chart ownership. Historical APIs and event bytes remain unchanged; missing ownership proof is never
backfilled or inferred from equal UUID text.

For admitted SMA period `p`, display support `[s,e)` requires materialization support `[s-(p-1)*900000000000,e)` in nanoseconds.
Selection requires one exact sealed Revision with precisely this scope. Missing coverage yields durable
`CHART_SEALED_COVERAGE_UNAVAILABLE`; preparation never starts acquisition or composes several Revisions. Official exact reads verify
Revision, Coverage Manifest, Seal, segments, physical partition proofs and the canonical closed Bar grid before pin publication.

The immutable input pin includes operation/intent ownership, exact Integration reference and canonical source selection, binding,
display range, materialization scope, construction recipe/fingerprint/alignment/data version, full Revision/Manifest/Seal evidence,
physical proofs, exact Runtime Generation and reserved work identity. Its canonical content fingerprint excludes worker/lease timing.
Stored evidence is verified again against the exact official authorities on reentry; latest Revision is consulted only before pin.

Preparation persists separate append-only, hash-chained facts in PostgreSQL. The original admitted operation stays unchanged.
Each fact has a monotonic revision. Claim increments the fence; heartbeat keeps the fence. PostgreSQL `clock_timestamp()` coordinates
leases, bounded to two minutes. A live claim belongs to one worker; an expired claim cannot be renewed. Pin, failure and ready
publication require that worker, fence, generation and an unexpired lease in a short serialized transaction. No transaction spans
Dataset work. Stale semantic work may finish, but cannot publish operational progress.
Immediately after Runtime binding, the current fence commits `RUNTIME_BOUND`, containing the exact immutable original binding
event reference (without mutable activity). All subsequent facts inherit this reference; current evidence must match every field.
No Market Data/Dataset read is permitted before this commit. A bounded heartbeat then verifies the PostgreSQL fence and lease.
Once this reference is persisted, missing Runtime evidence is a conflict requiring intervention, never permission to rebind,
append preparation progress, or infer a terminal failure. The returned current claim supplies the expected relation at the binding
boundary, even if the initial read was stale. Only reference-free recovery may adopt an exact chart-owned late Runtime append.
A stale worker stops if another fence is materializing; if the durable state is FAILED it reconciles terminal
ownership, and if INPUT_READY it returns only after exact active binding/pin verification. No second lease Authority is introduced.

Only the committed pin can construct `OnlySealedMarketDataMaterializationPlan`. The official
`OnlySealedMarketDataDatasetMaterializer.materialize_with_lineage` produces and verifies Snapshot and lineage using its existing
immutable stores. Dataset Definition selects event timestamps `[start,end)`; the plan's end is exactly one microsecond beyond
support end to include the last closed Bar at `e`. Market Data scope and input pin are not cropped or extended.

`MATERIALIZING_INPUT` is nonterminal. `INPUT_READY` records the input-selection fingerprint through its embedded immutable pin,
Snapshot fingerprint, Dataset materialization identity, exact generation/work identity, revision and fence. `FAILED` records a stable
failure code. Terminal facts cannot transition back into preparation. Before accepting ready reentry, the service verifies the same
pin and official Dataset publications. Snapshot and lineage are separate immutable commits: process loss after either resumes from
the same pin and verified reuse. A lost PostgreSQL acknowledgement is reconciled by `load_verified` and exact preparation reentry,
never by selecting latest or allocating another work identity. Unexpected dependency/process failures leave the existing claim for
lease recovery rather than manufacturing successful completion.

Pre-Run failure ordering is `FAILURE_DECIDED` under the current PostgreSQL fence, exact Runtime closure, then `FAILED` carrying the
immutable closure reference. The durable decision freezes the classified failure reason and prohibits further input progress,
including after backend/session loss. A PostgreSQL lock alone is not a cross-authority durable boundary. Retry of a decision finishes
the same Runtime close and FAILED without Market/Dataset reads; it never infers failure from inactivity or pin absence.
PRE_BIND decisions require no persisted binding reference; POST_BIND decisions require one. Invalid phase transitions append no fact.
The Runtime Authority atomically verifies the owner, releases matching active NEW_WORK, and appends `RuntimeNewWorkClosed`.
Owner plus reason are canonical values in the existing event reason field. All first-binding API families reject a closed identity;
historical assignments remain readable and closure does not count as active work. Release-before-closure crashes recover from the
durable failure decision; ordinary release cannot manufacture a failure.
An unbound closure may verify an exact historically validated RETIRED generation; PREPARING, REJECTED and missing/corrupt generations
remain invalid. Closure grants no execution or binding eligibility and never reactivates a retired generation.
Failure phase is an explicit closed classification:
`CHART_RUNTIME_GENERATION_NOT_ELIGIBLE` is PRE_BIND and normally requires proved UNBOUND. A late chart-owned NEW_WORK binding from
a stale worker is compensatable: release active or accept inactive. Foreign/EXACT bindings conflict and are never released.
`CHART_SEALED_COVERAGE_UNAVAILABLE` is POST_BIND and requires exact chart-owned NEW_WORK evidence, active or inactive; UNBOUND conflicts.
Unknown failure codes fail closed until their producer ordering is explicitly classified. Verified FAILED requires the exact closure
and, for POST_BIND, the persisted original binding reference. Lost/unavailable closure responses preserve the durable decision and report
`CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE`; they do not manufacture FAILED. Retry verifies terminal references without reading current
activation, Catalog, Market Data or Dataset. Already-inactive bindings remain valid after generation retirement; historical assignment
is preserved. `INPUT_READY` retains active ownership for future T4/Research execution and its eventual terminal lifecycle.

Migration `0045_chart_calculation_input_preparation` is additive and follows checksummed history through `0044`. It performs no
translation of admitted facts. DDL and migration-ledger commit are atomic; failure rolls back and restart retries the same migration.
For rollback, stop preparation writers and retain facts plus a compatible reader, or forward-fix; never delete authority history.

Migration `0046_chart_calculation_runtime_binding_relation` additively permits `RUNTIME_BOUND` and `FAILURE_DECIDED`; 0045 is unchanged.
New preparation facts use schema 2 with binding/closure references and the durable failure decision. Schema 1 bytes/fingerprints remain
valid and decode with no new references. A V1 unpinned MATERIALIZING_INPUT history may append explicit V2 relation facts; V1 pinned or
terminal history is readable but cannot silently acquire missing proof or qualify as verified-ready/closure-certified failure.
Mixed V1→V2 history is forward-only; migration performs no data rewrite and uses the existing atomic checksummed migration ledger.
