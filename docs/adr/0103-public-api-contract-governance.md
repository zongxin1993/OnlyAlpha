# ADR 0103: Public API Contract Governance

- Status: Accepted
- Date: 2026-08-26
- Task baseline: `d9713159eeb2e3dcc294d1dbd456e7332ef2cbac`
- Related: ADR 0087, ADR 0101

## Context

OnlyAlpha already derives a committed Research API v2 OpenAPI document from the canonical FastAPI Product application and derives the
Web TypeScript transport types from that document. Freshness checking proves that these projections match their sources, but it does not
by itself define the accepted historical baseline, exact contract revision, compatibility direction, breaking-change policy, or an
independent CI decision.

A baseline file changed in the same patch as the candidate could conceal a breaking change. Regenerating an old contract with a current
Python toolchain would also rewrite history. Public transport compatibility identity must remain separate from Dataset, Calculation,
Candidate, Strategy, Research Result, Artifact and Trading semantic identity.

## Decision

1. FastAPI Routes plus API DTOs are the single public API authoring authority.
2. `contracts/research-api/v2/openapi.json` is the one committed canonical v2 projection. It is not a second authoring source.
3. Canonical bytes are UTF-8 JSON with sorted object keys, two-space indentation, unescaped Unicode, LF line endings and exactly one
   trailing newline. Arrays are not reordered.
4. The exact contract revision is lowercase `SHA256(canonical OpenAPI bytes)`. It is computed externally and is not embedded in the
   document.
5. The accepted baseline is the committed canonical artifact at an immutable Git revision:
   `<BASE_SHA>:contracts/research-api/v2/openapi.json`. Historical source is never regenerated with the current toolchain.
6. Compatibility direction is old-v2-client to new-v2-server: old valid requests remain accepted and new responses remain consumable by
   clients generated from the accepted older v2 contract.
7. The v2 compatibility family permits only backward-compatible evolution. A breaking change requires an explicit new API major and
   continued support for the old family; no gate waiver flag is allowed.
8. `operationId` is public generated-client compatibility metadata and a change is breaking. Response enum expansion is breaking under
   the current strict old-client policy; request enum expansion remains compatible.
9. `scripts/openapi_contract.py` is the single governance implementation for deterministic render/write/check, structural and
   OnlyAlpha-policy lint, immutable Git comparison, exact SHA256 and generated-client freshness. The historical exporter command is a
   thin delegating wrapper only.
10. The generated Web client derives only from the canonical OpenAPI through the exactly locked `openapi-typescript` dependency. Formal
    governance uses the repository's locked Python and Node dependency graphs and does not resolve floating tools at runtime.
11. API major, contract fingerprint, `operationId`, HTTP route/method, request identity and Git baseline metadata never enter Dataset,
    Calculation, Candidate, Strategy, Research Result, Artifact or Trading semantic identity.

## Consequences

- A candidate contract and its accepted baseline cannot be made mutable together in one patch.
- Same routes, DTOs, locked dependency graph and API major produce the same canonical bytes and contract SHA256.
- v2 compatibility changes receive a deterministic mechanical verdict in a dedicated CI job.
- The existing public HTTP behavior, canonical v2 bytes, generated TypeScript bytes, Research/P9.0 semantics and persistence schema do
  not change as a consequence of governance.
- A future v3, external Python SDK, generic idempotency/recovery framework, or remote gateway protocol requires its own authorized task.

## Rejected alternatives

- A hand-maintained OpenAPI YAML/JSON authoring source beside FastAPI.
- A mutable `baseline.json`, `accepted.json`, or committed previous-contract copy.
- Regenerating historical source with current FastAPI/Pydantic versions.
- Git SHA or product release version as the exact contract fingerprint.
- Embedding the contract fingerprint into the document being hashed.
- `--accept-breaking`, `--force`, or similar formal-gate escape hatches.
- Floating `latest` lint/diff/client tools.
- Adding API compatibility metadata to semantic fingerprints.
