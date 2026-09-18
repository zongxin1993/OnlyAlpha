# ADR 0132: Canonical Quant Asset Vocabulary Finalization

- Status: Accepted
- Date: 2026-09-18
- Decision maker: repository owner
- Related: ADR 0110–0112, ADR 0129–0131
- Constitution Impact: NO

## Context

ADR 0131 established the PostgreSQL-native private-asset authoring boundary but used `ALPHA` as the private quant-asset kind. That
name conflicts with the canonical domain vocabulary: a production private predictive asset is a Factor, while financial alpha remains
a valid product and research concept.

## Decision

The only active quant-asset vocabulary is:

```text
OPERATOR
INDICATOR
FACTOR
STRATEGY
```

`FACTOR` is the sole asset and Calculation identity for the private predictive asset. Active private Factor types, provider sources,
runtime bindings, API fields, examples and PostgreSQL tables use Factor terminology and the `private.factor.*` namespace. Strategy
authoring remains PostgreSQL-native and produces `PrivateStrategyRevision`; it is not a package-backed Catalog provider.

This ADR supersedes only the ALPHA asset-kind, private-alpha identity and private-alpha persistence portions of ADR 0131. ADR 0131
remains historical evidence for the migration and continues to govern the PostgreSQL-native authoring and private-repository retirement
decisions that are not changed here.

There are no active Alpha asset aliases, dual parsers, fallback loaders, or package-backed Private Strategy authoring resources.
Portable examples are import/demo seeds only and do not execute directly or become Provider authority.

## Consequences

- `OnlyQuantAssetKind.FACTOR` and `OnlyPrivateAssetKind.FACTOR` are the active Factor identities.
- Native Factor execution closes through the exact DB Revision, Source Artifact, Provider Snapshot, Catalog and Runtime contracts.
- The Factor API delegates overlapping stateless semantics to the canonical `onlyalpha.calculation` authority.
- Historical ADR wording, product branding, financial alpha, alpha discovery, and unrelated market/governance layer names remain valid.
- Existing immutable Alpha-era database history is never silently rewritten; the forward development migration fails closed for non-empty
  legacy tables and requires export/reset/re-import through the current Authority.

## Rejected alternatives

- Keeping `ALPHA` as an asset-kind alias or accepting both `private.alpha.*` and `private.factor.*`.
- Retaining Strategy resource/package Providers as a second authoring Authority.
- Letting a Factor implementation own duplicate arithmetic or predicate semantics.
