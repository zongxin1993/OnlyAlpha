# ADR 0130: Development-Stage Compatibility and Contract Evolution Policy

- Status: Accepted
- Date: 2026-09-17
- Decision maker: repository owner
- Related: ADR 0103, ADR 0109, ADR 0129
- Constitution Impact: NO

## Context

OnlyAlpha is in active development and has no supported external Product API consumer. Treating every unpublished internal or Product
contract revision as permanently compatibility-frozen creates duplicate API families, fallback loaders and legacy schemas that have no
current consumer while obscuring the current canonical architecture.

Compatibility and correctness are separate concerns. Breaking-change detection remains useful engineering evidence even when a contract
is not yet compatibility-frozen; detection must not silently become either automatic prohibition or an ad hoc waiver mechanism.

## Decision

Every governed contract family is explicitly either `DEVELOPMENT_UNFROZEN` or `COMPATIBILITY_FROZEN`. OnlyAlpha's Product API v2 is
currently `DEVELOPMENT_UNFROZEN`, recorded by its repository-owned compatibility policy.

Unless the repository owner explicitly marks a contract compatibility-frozen or externally supported during active development:

1. internal Python APIs, schemas, DTOs, runtime manifests and PostgreSQL data contracts do not require historical compatibility beyond
   the current architecture's migration, replay and integrity requirements;
2. Product API contracts may change incompatibly in their current major;
3. the current canonical contract is updated directly and all in-repository consumers migrate atomically;
4. obsolete internal fixtures, tests and loaders may be deleted or rewritten; and
5. compatibility layers and duplicate version families are not added by default.

The contract verifier continues deterministic rendering, canonical hashing, immutable-baseline comparison, structural and OnlyAlpha
policy lint, complete sorted breaking-diff classification and generated-client freshness checks. For a `DEVELOPMENT_UNFROZEN` family,
detected breaking changes are auditable but non-blocking. For a `COMPATIBILITY_FROZEN` family, they block unless an exact historical
authorization already accepted by repository governance applies. There is no command-line or environment-variable bypass.

Changing compatibility state is an owner-level governance decision and a reviewed repository change, not runtime configuration.

Exact identity, immutable facts and revisions, deterministic fingerprints, Research Evidence, Qualification, StrategyRevision,
Catalog Generation, Runtime Generation, fail-closed exact resolution, current persistence integrity and current replay requirements are
correctness obligations. They are not legacy compatibility and remain mandatory. `latest` or fall-forward resolution remains forbidden.

## Relationship to prior decisions

ADR 0103 remains authoritative for FastAPI Routes and DTOs as the Product API authoring authority, canonical OpenAPI bytes and SHA-256,
immutable Git comparison, compatibility analysis, structural/policy lint and generated TypeScript freshness. This ADR supersedes ADR
0103's old-client-to-new-server obligation, new-major requirement, old-family support requirement and automatic breaking-diff blocker
only for contract families explicitly marked `DEVELOPMENT_UNFROZEN`.

ADR 0109 remains the historical record of the A0 correction. This ADR supersedes its post-A0 Product API v2 freeze statement while the
family is `DEVELOPMENT_UNFROZEN`; its exact one-shot historical authorization remains valid evidence and is not generalized.

## Consequences

- Product API v2 may adopt PA-1's DB-native Research Authoring Provenance directly while retaining full breaking-diff visibility.
- A future owner decision can mark Product API v2 `COMPATIBILITY_FROZEN`; later breaking changes then become blockers again.
- External support or compatibility commitments must be explicit and cannot be inferred from an API major alone.
- This decision does not authorize unrelated scope changes or weaken current correctness, migration, security or Authority boundaries.

## Rejected alternatives

- V1/V2 dual-stack internal schemas or legacy fallback loaders by default.
- Preserving old API families or creating a new major solely for unpublished consumers.
- Compatibility adapters, deprecated transport shapes or historical fixture loaders without an explicit owner requirement.
- Migration shims whose only purpose is unpublished historical compatibility.
- `--force`, `--accept-breaking`, `--ignore-breaking` or environment-variable bypasses.
- Disabling breaking-change detection instead of separating detection from prohibition.
