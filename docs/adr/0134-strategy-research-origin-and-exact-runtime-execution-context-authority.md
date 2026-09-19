# ADR 0134: Strategy Research Origin and Exact Runtime Execution Context Authority

- Status: Accepted
- Date: 2026-09-19
- Related: ADR 0116–0117, 0129–0133
- Constitution Impact: NO

## Decision

Strategy Research origin is a durable `OnlyResearchOriginKind.PRIVATE_STRATEGY` fact on the Research Run and is derived by the Private Strategy Product path. It is never inferred from Factor authoring provenance. A private Strategy origin requires the exact immutable `PrivateStrategyResearchComposition` reference; a General Run cannot carry that reference.

`OnlyAuthoringExecutionGeneration` remains scoped to the executable provenance of one Private Factor candidate. It is not a Strategy origin, Strategy Generation, or complete multi-Factor execution context.

Strategy Research execution authority is the exact Runtime Generation selected by the Product intent and bound to the resulting Research work item. Its immutable Catalog Generation and implementation/artifact set are the sole execution capability set. The Composition Catalog fingerprint must equal the exact Runtime Catalog fingerprint, and every Strategy Factor dependency must be contained by exact `private_factor_bindings` using Factor ID and Revision identity plus source, provider snapshot, research implementation and trading implementation evidence.

The existing Runtime Generation supports zero, one, or many private Factor bindings. Zero-Factor Strategies use the public-only Catalog and do not require a fake Authoring Generation. Binding order is canonical and does not affect Runtime identity. Existing Catalog, Runtime, Research Command/Admission, and generation-hosted Definition Resolver authorities remain the only authorities; no Strategy-specific Generation or second Research Resolver is introduced.

Freeze selects Strategy behavior from the durable Run origin, verifies the Composition and exact Runtime context, and remains the sole creator of `OnlyStrategyRevision`. No latest/current/fall-forward Runtime or Catalog resolution is permitted.

## Consequences

- Research Run persistence adds one forward-only origin discriminator; migration `0030` remains unchanged.
- Product v2 Private Strategy Research intent carries `runtime_generation_fingerprint`; Factor authoring generation is not required for Strategy Research.
- Exact Definition resolution crosses the existing generation-hosted execution seam and returns a strict DTO containing the resolved Research Specification and admission evidence.
- Historical multi-Factor Runtime rebuild remains artifact- and manifest-only.
