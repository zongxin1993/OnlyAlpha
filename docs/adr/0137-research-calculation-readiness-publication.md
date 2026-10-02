# ADR 0137: Research Calculation Readiness Publication

- Status: Accepted
- Date: 2026-10-03
- Decision maker: repository owner
- Related: ADR 0070, 0073, 0074, 0135, 0136
- Constitution Impact: NO

## Context

Calculation-only Research publication preserves partial-window numeric semantics but does not yet carry point readiness.
Numeric zero, nullability and producer readiness are different facts. Reconstructing warmup in Query or Web would introduce
a second semantic authority; annotating a numeric-only cached Result would not prove an actual readiness execution.

## Decision

The exact registered RESEARCH Calculation backend produces values and readiness atomically from the same execution.
The executor validates complete output membership, row alignment and state/reason/value compatibility before sealing execution.
The readiness carrier and validator are structural contracts, not execution provenance or permission to publish caller-authored facts.

Readiness contract V1 has states `PARTIAL`, `READY`, `UNAVAILABLE` and reasons `NONE`, `WARMUP_INCOMPLETE`,
`VALUE_UNDEFINED`, `INPUT_UNAVAILABLE`, `DEPENDENCY_UNAVAILABLE`:

| State | Reason | Value |
|---|---|---|
| PARTIAL | WARMUP_INCOMPLETE | Nonnull, or null only for a nullable output |
| READY | NONE | Nonnull, including exact zero |
| READY | VALUE_UNDEFINED | Null, only for a nullable output |
| UNAVAILABLE | INPUT_UNAVAILABLE or DEPENDENCY_UNAVAILABLE | Null |

Every Definition output has exactly one state and reason per value row. State/reason arrays are non-null Arrow strings with
canonical enum spellings. Missing/malformed evidence is an error, never an invented UNAVAILABLE or READY observation.
Existing value type/nullability validation remains required independently of readiness validation.

Calculation Result V2 and Execution Evidence V2 use explicit version namespaces within their existing authorities:
`calculation-results/v2/sha256` and `calculation-execution-evidence/v2/sha256`. V2 content binds exact values and readiness;
Execution Evidence binds the sealed producer and exact implementation. V1 cannot satisfy readiness evidence. A valid V1 result
may only serve as an exact numeric parity comparison, not a readiness source. Corrupt existing authority fails closed.

Publication contract schema 1 requests exactly Calculation Result schema 2, Execution Evidence schema 2 and readiness contract 1.
This contract is non-semantic and is carried by Research Job Plan V2. Unsupported versions and unknown/missing fields are rejected.
Publication version is not Calculation semantic identity: Dataset Snapshot plus Calculation Graph with the existing RESEARCH
identity domain remains unchanged. Implementation identity, audit time, paths, compression and Job identity remain excluded.
V1 identities, paths, payloads and behavior remain unchanged.

The owner-authorized readiness foundation supports one TIME_SERIES node and only `onlyalpha.indicator.sma@1` as its production
readiness V1 registration. SMA values remain exactly equal to legacy execution; period 1 is READY from its first point, while
earlier samples for larger periods are PARTIAL/WARMUP_INCOMPLETE. Provider content changes require a new provider version and
immutable Catalog/Runtime Generation binding; no ambient fallback or in-place reload is admitted.

Product admission, Specification V3, Research Result V4, Artifact V2, Query/HTTP/OpenAPI and Web remain later separately
authorized work. This decision grants no chart Run admission, market acquisition, database schema or LIVE authority.

## Consequences and validation

Strict publication round trips and adversarial field/version mutations must reject coercion, including booleans as integers.
Readiness tests cover the full state/reason/nullability matrix, zero values, missing/extra outputs, malformed arrays and row mismatch.
Canonical execution and versioned publication must subsequently prove atomicity, exact numeric parity, corruption rejection,
immutable reuse and recovery without modifying V1 behavior.

Rejected alternatives are value truthiness as readiness, guessed row-index warmup outside the backend, V1 readiness shims,
fallback from V2 to V1, parallel numeric authority, speculative DAG/cross-section support and browser/HTTP evaluation.
