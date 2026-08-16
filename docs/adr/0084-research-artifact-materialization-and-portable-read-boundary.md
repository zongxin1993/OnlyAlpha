# ADR 0084: Research Artifact Materialization and Portable Read Boundary

- Status: Accepted
- Date: 2026-08-16

## Context

P7.8 established Research Result as the exact composition authority over verified Statistics Results. Future Query, API, and Web
consumers still lacked a stable package: reading execution stores directly would expose persistence internals and require all
Dataset, Calculation, Statistics, and Research Result authorities to remain online.

## Decision

`onlyalpha.research.artifact` owns a derived, immutable materialized read view. Statistics Result remains the semantic row
authority, and Research Result remains the exact composition authority. Materialization starts with
`ResearchResultStore.load_verified()`, follows only its exact canonical references, verified-loads every Statistics Result, and
copies those rows into one canonical `statistics.parquet` table. It never scans a Statistics Store to infer membership.

The published V1 package contains exactly `artifact_manifest.json` and `statistics.parquet`. The strict manifest embeds the complete
Statistics plans and identities needed to recompute every Statistics fingerprint, Statistics content fingerprint, Statistics Result
fingerprint, Research Result plan/content/result identity, and the Artifact logical content identity. A separate byte SHA256 protects
the physical Parquet file. Audit time, path, process identity, compression, and EXECUTED/REUSED disposition do not enter semantic
identity.

Generation is upstream-aware; published reads are self-contained. `OnlyParquetResearchArtifactStore` has no upstream Store
dependency, and `load_verified()` verifies the exact filesystem set, rejects symlinks, validates the strict manifest and Arrow
schema, verifies bytes and canonical rows, and reconstructs all embedded semantic linkages without accessing Dataset, Calculation,
Statistics, or Research Result persistence.

Publication uses a unique staging directory, Parquet round-trip verification, complete staged verification, and atomic directory
rename. Equal re-entry loads and reuses an existing verified Artifact. A different logical materialization at the same
profile/schema plus Research Result address fails with `DETERMINISTIC_ARTIFACT_CONFLICT`; corruption is never treated as missing,
deleted, repaired, or silently rebuilt.

Artifact introduces no Artifact Plan fingerprint or Artifact Result identity. It is disposable and rebuildable, but it is not an
execution, Statistics, or Research authority and provides no reverse import/restore path.

## Rejected Alternatives

- Letting Web read Statistics or Research Result stores directly would expose execution-plane persistence.
- Storing only references would not create a portable, self-contained read package.
- Treating copied rows as a second Statistics authority would violate ownership.
- A mutable Experiment database would create competing result and recovery state.
- Unifying Trading and Research artifacts would conflate different semantic roles.
- Adding Artifact Plan/Result identities would inflate identity without a new authority.
- Using Parquet bytes as semantic identity would bind semantics to physical encoding.
- Recomputing analytics during materialization would hide a new Analytics authority in the writer.
- Auto-rebuilding corrupt output would erase durable corruption evidence.
- Cross-Dataset merge would introduce undeclared alignment semantics.

## Consequences

Future read-only Query/API/Web layers can consume one immutable, portable public boundary while execution stores remain hidden.
Artifacts can be copied, cached, deleted, and rebuilt from verified upstream authority. P7.9 adds no Query service, HTTP API, Web UI,
new research analytics, Artifact import/restore, generic Artifact framework, Research Runtime activation, or Live capability.
