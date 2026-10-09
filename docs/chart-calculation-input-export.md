# Verified sealed Chart input export

`OnlyChartCalculationInputExportService` is a read-only Application composition over existing owning readers. It exports
the original immutable input of one admitted Chart operation, not a new source, execution eligibility or Run outcome.
It creates no admission, Preparation, Compilation, Materialization, Snapshot, Runtime binding or Market Data fact.

## Owning relations

The caller supplies only an exact `OnlyProductCommandId`. The T1 reader verifies the Operation, Command admission/receipt
and reserved Run relation. The T2 reader verifies the append-only Preparation chain. Only `INPUT_READY` is applicable;
absent, materializing and failed Preparation cannot issue a publication input. The D2 reader verifies the original
operation/preparation revision and fence, Pin identity, immutable Compilation and complete frozen resolution.

The shared `OnlyChartCalculationInputVerifier.verify_frozen()` verifies the original Runtime binding reference, historical
Generation/Catalog relation, exact Dataset physical/logical content and Materialization identity, Revision bindings,
materializer/version, request, construction, Definition and provenance. An inactive original binding may prove historical
input without becoming execution permission. No optional D3 Run or terminal publication is required to prove that input
occurred. Cancellation and failed downstream work do not erase the immutable input or grant a new Work.

The exporter reads the original Integration Revision, verifies its exact Integration/type/descriptor identity and derives
the complete original `OnlyIntegrationRuntimeBindingV1`. It never performs new-work Integration admission, accesses a
credential, chooses the current Revision or calls a Provider. Current Integration lifecycle and current activation are not
historical input selectors. The canonical binding payload uses the same identity domain as the owning Runtime resolver.

The historical Market Data reader resolves only the pinned Revision. Manifest, Revision, Seal and the ordered complete
physical proofs must equal the original Pin. Every retained Segment's metadata must match its physical proof and original
Integration binding, source, instrument, construction and scope. The exact historical read verifies original physical facts
and coverage. Native Bar-to-Arrow projection must equal the complete verified Dataset table, including all values and axes;
no materialization, Calculation, repair, replacement or acquisition is performed during export.

## Issued input versus retained representation

The successful export issues a private, process-local `_OnlyVerifiedSealedChartPublicationInput`. Independent issuance
records bind its retained bytes, original Result Plan, Graph and Generation to a callback that repeats the owning reads.
The consumer check requires the actual issued instance, unchanged context and exact expected identities, then re-verifies
the original owning chain. Copies, replacements, in-place mutation, caller-constructed instances and parsed portable DTOs
are not issued inputs. The narrowly internal issuer has one production composition caller: this Application exporter.
This is a trusted in-process boundary, not protection against arbitrary malicious Python already running inside the process.

`OnlyRetainedSealedChartInputEvidenceV1` is a separate neutral representation. Its schema 1 retains:

- exact source reference and server-derived source selection;
- complete original Integration Runtime Binding payload and its fingerprint;
- exact native source scope/construction, Manifest, Revision and Seal;
- ordered complete Segment metadata and all physical partition proofs;
- Materialization semantic payload and original materialization ID;
- exact Dataset Snapshot fingerprint.

Operational Operation/Run UUIDs, display range, Preparation lease/fence and mutable Work state do not enter this portable
representation. Integration UUIDs are original source identity, not browser/operational ownership. Necessary timestamps
inside original Segment metadata and Seal remain unchanged because they are part of those retained proof structures.
Materialization audit time is not its semantic payload.

Parsing rejects unknown/missing fields, explicit null mandatory members, duplicates, unsupported versions, booleans as
integers and noncanonical nested representations. Manifest/Revision/Seal and physical proof identities are rebuilt using
the owning pure contracts. `verify_snapshot()` proves exact Materialization request/construction, native coverage,
Definition, count and provenance relationships. The caller's Snapshot reader still owns verification of full partition
values and logical/physical content; this DTO is not a substitute for that reader.

Native source consistency requires BAR-only canonical partitions and enough physical BAR occurrences. Aggregate count
alone is insufficient: each required closed 15m interval must be assignable to a Segment whose footprint covers that
entire interval and whose canonical BAR capacity is not exhausted. Positive footprints are native-grid aligned. An
earliest-ending-footprint allocation proves this necessary feasible-support relation; duplicate occurrences may remain
unused. A temporal gap, insufficient local capacity or zero-count footprint cannot stand for a missing interval. The
existing admitted Chart support limit of 672 points bounds this portable check. This is consistency of the retained
attestation, not verification of unretained physical rows; live issuance still requires the exact owning physical read.

Portable parsing imports no Application, Runtime, persistence adapter, Provider, Registry or materializer. Internal
coherence of copied attestations is not cryptographic authenticity, fresh execution permission, a terminal Run state or
permission to restore a missing upstream authority. Neither the constructor nor parser invokes the issuance hook.

## Failure and replay semantics

Missing Operation, non-ready Preparation or missing Compilation raises an explicit Chart error. Missing, corrupt or
unavailable required upstream facts propagate the owning read failure; none becomes certified absence, an empty proof,
successful reuse or permission to repair/reselect. A complete different exact relation is rejected. There is no retry,
fallback, latest lookup, absence certificate, durable issuance inventory or reverse import facility.

Repeated export of unchanged original facts produces the same retained bytes. Later Source revisions, unrelated activation
and release of the original binding do not change those bytes. Source loss blocks live consumer revalidation even if a
previously published portable copy remains independently readable.
