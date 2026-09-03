# ADR 0112: Versioned Quant Asset Hot-Plug Generations

- Status: Accepted
- Date: 2026-09-03
- Related: ADR 0069, 0076, 0098, 0108, 0110, 0111

## Context

L1 Operator, L2 Indicator, L3 Factor and L4 Strategy authoring libraries evolve independently, with private L3/L4 changing most often
during Agent research. Installing or importing a package is not sufficient version management: mutable code replacement under an existing
identity would make Research, Freeze and replay depend on process timing and module cache state.

## Decision

All four layers expose an asset-management provider through the `onlyalpha.quant_assets` entry-point group. L1/L2/L3 providers carry their
existing exact Calculation registrations; `onlyalpha.calculations` remains the only Calculation execution SPI. L4 providers carry immutable
authoring resources and do not become an execution SPI.

Each provider declares `provider_id + provider_version + layer` and its owning
`distribution_name + distribution_version`. Installed discovery verifies the latter pair against entry-point metadata, so a provider cannot
silently claim a different package build. The catalog independently computes `content_fingerprint` from:

- exact Calculation type descriptors, backend kind, implementation fingerprints and state/checkpoint capabilities for L1/L2/L3;
- exact semantic asset version plus SHA-256, size and relative path of every L4 authoring resource.

The complete sorted provider set produces one immutable `catalog_generation_fingerprint`. A refresh constructs and validates the complete
candidate generation before taking the manager lock, then atomically switches the pointer used by new work. Holders of an earlier snapshot
continue using that snapshot. Failed refresh leaves the active generation unchanged. Prior generations remain addressable by fingerprint
inside the manager lifecycle.

The same `provider_id + provider_version` may never identify different content. Such drift fails closed. A content or implementation change
requires a new provider version; a semantic change also requires the corresponding Calculation semantic version or L4 asset semantic
version. No `latest` alias or lexical version ordering exists: consumers resolve exact identities or explicitly select a catalog generation.
Distribution identity is provenance in the catalog-generation identity, but is not provider content: repackaging byte-identical registered
implementations/resources under a new distribution version does not falsely trigger content drift. The repository's four reference/official
provider distribution versions participate in the existing workspace `version_sync.py` authority; external private repositories must
provide the equivalent release check in their own build pipeline.

Hot plug means adding/removing an admitted provider generation for **new** Research authoring and admission. It does not mean mutating Python
modules in place, replacing providers inside an active Run, or changing a frozen StrategyRevision. Package installation and process/worker
rollout remain Infrastructure concerns. Existing Strategy Revisions continue to require their exact implementation fingerprints; missing
historical artifacts fail closed.

Path and distribution loading from ADR 0111 converge to the same provider object. Explicit source providers are permitted in controlled
development/Agent admission. Production catalog discovery uses installed distribution metadata. Agent interaction with a running OnlyAlpha
deployment still uses the versioned Product API and cannot install code, refresh LIVE execution, or bypass Code Admission by Python import.

## Consequences

Agent-generated assets can be tested from a checkout, packaged, admitted as a new exact version and made available to new Research work
without changing Core calculation semantics. Catalog and content identities make updates observable and reproducible. L4 participates in
asset discovery while StrategyRevision remains the sole runtime Strategy authority.

## Rejected alternatives

- In-place `importlib.reload`, recursive directory watching or runtime `sys.path` mutation.
- Reusing one provider/semantic version after content changes.
- A second Calculation graph or execution SPI for asset management.
- Rebinding active Runs or Strategy Revisions to the current catalog.
- Letting Agent package changes directly alter LIVE behavior.
