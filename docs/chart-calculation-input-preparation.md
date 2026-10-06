# Chart calculation input preparation

The application preparation boundary consumes an immutable admitted chart operation, an explicit exact Runtime Generation
fingerprint and a worker identity. It prepares one instrument's native fixed-duration 15m LAST/RAW SESSION_START input.
It owns neither Market Data nor Dataset truth and does not admit a Specification, Research Run or Calculation execution.

`OnlyMarketDataProductService.plan_selection` resolves the exact Integration Revision, canonical source, binding fingerprint,
plugin-native construction and grid-aligned scope. This read-only planning method does not create/authenticate provider sessions,
open WAL, fetch reference instruments, acquire data or write Market Data authority. Derived resolution is rejected.

`OnlyChartCalculationPreparationService` verifies the supplied Runtime Generation against the Catalog Generation frozen in
 admission. Fresh work requires `ACTIVE_FOR_NEW_WORK` before claiming and again immediately before first binding
 `operation.reserved_run_id.value` through `OnlyRuntimeGenerationWorkAuthority.bind_work_exact`. A claim without a binding can recover
 only while its frozen generation remains eligible for new work. Activation change before binding commits definitive
 `CHART_RUNTIME_GENERATION_NOT_ELIGIBLE`; it never falls forward to another generation.
 Recovery of an exact active binding may continue in its historical READY/ACTIVE/DRAINING generation without consulting current
 activation. Reentry must provide the same fingerprint. Conflicting bindings, or inactive bindings for nonterminal/`INPUT_READY`
 preparation, require intervention and are never reactivated.

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

Pre-Run `FAILED` owns Runtime binding closure: append the failure under the current fence before idempotently releasing its exact work
with actor `chart-input-preparation-failed`. Return failure only after verifying an exact inactive binding, or proved UNBOUND when no
input pin was published. Lost/unavailable release responses leave the durable failure intact and report
`CHART_RUNTIME_BINDING_RELEASE_UNAVAILABLE`. Retry loads FAILED first and reconciles historical binding without reading current
activation, Catalog, Market Data or Dataset. Already-inactive bindings remain valid after generation retirement; historical assignment
is preserved. `INPUT_READY` retains active ownership for future T4/Research execution and its eventual terminal lifecycle.

Migration `0045_chart_calculation_input_preparation` is additive and follows checksummed history through `0044`. It performs no
translation of admitted facts. DDL and migration-ledger commit are atomic; failure rolls back and restart retries the same migration.
For rollback, stop preparation writers and retain facts plus a compatible reader, or forward-fix; never delete authority history.
