# ADR 0136: Calculation-only Research Publication

- Status: Accepted
- Date: 2026-10-01
- Decision maker: repository owner
- Related: ADR 0074, 0075, 0083, 0084, 0086, 0095, 0114, 0135
- Constitution Impact: NO

## Context

A chart Indicator needs an exact registered Calculation over immutable input, not a synthetic Target or fabricated Statistics.
Research Result V1/V2 require nonempty Statistics membership. The finite Research Runtime publishes through Result and Artifact.
Bypassing that lifecycle in HTTP or calculating official values in the browser would introduce another authority. The owner approved
a versioned calculation-only composition contract preserving existing V1/V2 semantics and identities.

## Decision

### Result composition

`onlyalpha.research.result` remains the sole composition authority. Result Plan/Result V3 are explicitly calculation-only:

- one exact Dataset Snapshot;
- canonical, unique, nonempty Calculation/Graph and published series membership;
- existing Calculation/node/output references, with at least one published series for every Calculation;
- no Statistics, Candidate or Signal members, including Candidate ownership on a published series.

Existing Plan/Result types carry the new schema discriminant. V1/V2 validation, serialization and fingerprint payloads are unchanged.
V3 Plan identity hashes its complete canonical plan. V3 content identity hashes exact verified Calculation logical/Result pairs and
the empty Statistics set. V3 Result identity hashes its version, Plan and content. Dataset+Graph+RESEARCH remains Calculation
semantic identity; Provider/Catalog/implementation binding remains execution provenance. Request, Runtime, audit and display
identities never replace these identities.

Assembly and every verified Result load prove exact Dataset, Calculation, Result, Graph, node and output linkage. Missing/corrupt
upstream proof is an error, not an empty result or certified absence. Empty Statistics under V3 means Statistics were not requested;
it does not prove scientific rejection or historical absence.

### Artifact projection

`RESEARCH_CALCULATION_V1` (Artifact schema 1, embedded Result schema 3) is a separate profile in the existing Scientific Artifact
materializer/model/store. It reuses exact market/variable/graph rows, canonical Decimal strings, section logical fingerprints,
byte hashes and series-axis verification. The section set is unchanged; Statistics/Signal sections are typed empty sections, not
fabricated facts. Existing Scientific V2/V3 profiles and identities are unchanged. Artifact identity includes exact profile/version
and Result identity. Profile-specific storage prevents coercion to an existing profile. Query is Artifact-only and never evaluates.

### Lifecycle and recovery

The existing Engine-hosted finite RESEARCH Runtime executes Dataset verification, Jobs, Result assembly/commit, Artifact
materialization/commit and final verified loads. V3 workload closure requires exact Job/Result Calculation and Graph membership,
with no Statistics plans. No new runtime vocabulary, calculator, execution store or durable Runtime state is introduced.

COMPLETED requires both final publications. Failure/cancellation may leave valid upstream facts; these do not prove completed
publication. Exact workload re-entry uses immutable verified reuse. Corruption fails closed and is never rebuilt over. Jobs retain
their exact Execution Evidence requirement even when numeric Result reuse is possible.

### Chart boundary

The first integration uses registered `onlyalpha.indicator.sma@1`, Native 15m, sealed closed Bars and server batch recomputation.
Preview is explicitly unsupported. Stream close is not a Seal. Materialization must prove exact Integration Revision/source,
instrument, semantic/construction, range, Revision/Seal and Snapshot linkage. Renderer Bars are not input; multiple pages are not
assumed to be one materializable Revision. Partial-window values preserve existing PARTIAL_WINDOW/PARTIAL semantics. Readiness is
separate from numeric value: zero is not unavailable and partial is not ready.

Browser state owns placement, visibility and incarnation, not numeric or market truth. Response admission binds chart context,
normalized parameters, output, incarnation and request generation. Hiding/removing does not reacquire prices or restart streams.

## Compatibility and verification

Unsupported versions/profiles are rejected, not coerced. No compatibility shim is introduced. Product API/operational persistence
admission requires atomic consumer changes and relevant contract tests before Web use. Required evidence includes:

- unchanged V1/V2 identity and nonempty Statistics validation;
- V3 strict shape, duplicate, wrong-family and Dataset/Calculation/Result/Graph/node/output mutations;
- deterministic output and unchanged immutable input after repeated evaluation;
- final-publication failure, exact re-entry and corrupt-existing fail-closed;
- Artifact byte/logical integrity, exact axes and self-contained query;
- Product authorization/idempotency and browser current-context isolation before chart closure.

## Rejected alternatives and consequences

Relaxing V1/V2 changes old contracts. Dummy Statistics/Targets manufacture scientific claims. HTTP evaluation bypasses Engine;
browser SMA creates a second numeric implementation; stream/page-as-sealed-input erases proof. Calculation Result owns values,
Result owns publication membership and Artifact/Query/API/Web project them. This adds no Statistics, Candidate, Freeze, Strategy or
LIVE authority, workspace persistence, factor mining, incremental/preview execution or performance-gate change.
