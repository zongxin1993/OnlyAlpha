# ADR 0074: Calculation Result Identity and Immutable Calculation Store

Status: Accepted

Date: 2026-08-14

## Context

ADR 0073 established deterministic, ephemeral Research Calculation execution over a fully verified Dataset Snapshot and a
canonical Calculation Graph. The execution object is immutable in memory, but it is not a durable authority: it cannot be stably
referenced after process exit, independently checked for physical or semantic tampering, or used to detect two different outputs
claimed for the same Calculation identity.

## Decision

Calculation identity remains the frozen P7.2 canonical SHA-256 over Dataset Snapshot fingerprint, Calculation Graph fingerprint
and exact `RESEARCH` backend kind. P7.3 adds two separate identities. A partition semantic fingerprint binds node fingerprint,
instrument identity, canonical event-time axis, exact logical Arrow fields and logical values. The global Result Content
fingerprint binds the canonical ordered set of logical partitions. The Calculation Result fingerprint binds result schema version,
Calculation fingerprint and Result Content fingerprint. Paths, Parquet bytes and settings, creation time and process or software
metadata are excluded from all semantic identities.

`calculation_fingerprint` is the immutable Store primary key. One Calculation may have exactly one canonical Result Content.
Recommitting the same Calculation and content verifies and reuses the existing authority. A different valid candidate for the same
Calculation fails closed as `DETERMINISTIC_RESULT_CONFLICT`. An existing corrupt authority fails as `RESULT_CORRUPT`; it is never
deleted, repaired or overwritten.

The logical partition authority is `(node_fingerprint, instrument_id)`. Partitions, output fields and rows have explicit canonical
ordering. The manifest is an exact, versioned, fail-closed persisted contract. It embeds the exact Calculation Graph contract and
records Dataset/Graph/Calculation, partition semantic, Result Content and Calculation Result identities, row counts, safe relative
paths, physical byte SHA-256 and provenance-only creation time. Commit requires an explicitly injected UTC audit-time authority;
the Store never reads the system clock directly.

Durable admission does not trust a hand-constructed execution dataclass. The Store verifies the referenced Dataset through the
Dataset Snapshot Store, recomputes Calculation linkage from the supplied canonical Graph, and requires the complete node by actual
Dataset-instrument product with exact timestamp axes and Definition-owned output contracts. Unknown, duplicate, partial,
noncanonical or incompatible output fails before persistence.

Commit writes a sibling staging directory, writes each `(node, instrument)` table, reads it back and checks exact logical equality,
writes the manifest, fully verifies the staged authority, and atomically renames it to the final target. Rename races verify the
winner: equal content is idempotent and different content is a deterministic conflict. Partial staged state is never a committed
Result and staging cleanup is best effort.

The public read path is verified. It checks target/path identity, exact manifest and Graph schemas, verified Dataset linkage,
partition completeness, safe paths, byte hashes, exact Arrow fields, row counts, timestamp axes, Definition output contracts,
partition semantic hashes and both global identities before returning an immutable Result. It never repairs, casts, sorts, fills,
recomputes a Calculation or falls back to Historical Cache.

## Invariants Introduced

1. Calculation fingerprint and Calculation Result fingerprint are distinct authorities.
2. Result Content identity describes canonical logical values, not physical bytes.
3. `calculation_fingerprint` is the durable primary key.
4. The same Calculation has exactly one canonical Result Content.
5. Same-Result recommit is idempotent; different-Result recommit is a deterministic conflict.
6. The Store is immutable and has no update, delete, overwrite, refresh, invalidation or eviction semantics.
7. Publication is staged, fully verified and atomic.
8. Byte SHA-256 detects physical corruption only; semantic fingerprints detect logical tampering.
9. Formal load is always verified and corruption fails closed without fallback.
10. P7.3 does not activate Research Runtime or add Job, Plan, Sweep, Research Result, Artifact, API or cache products.
11. Dataset and Calculation Result remain separate domain stores; no generic immutable-store abstraction is introduced.

## Consequences

Deterministic P7.2 output can now survive process boundaries as an immutable, independently verifiable Research Calculation fact.
Verification intentionally rereads the Dataset authority and every Result partition; correctness and forensic preservation take
priority over read performance. Physical encoding, compression, row-group sizing and Store root may change without changing Result
semantic identity.

## Rejected Alternatives

Rejected alternatives include Parquet bytes as Result identity, result fingerprint as the directory key, a mutable
Calculation-to-latest mapping, storing multiple competing outputs, overwrite or repair of corrupt targets, unverified public load,
cache-style recomputation or eviction, reuse of Trading persistence, a generic immutable-store framework and activation of a
Research Runtime or scheduler.
