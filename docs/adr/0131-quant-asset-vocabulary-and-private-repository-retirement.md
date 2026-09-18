# ADR 0131: Quant Asset Vocabulary and Private Repository Retirement

- Status: Accepted
- Date: 2026-09-18
- Decision maker: repository owner
- Related: ADR 0110–0112, ADR 0129, ADR 0130
- Constitution Impact: NO

## Context

The numbered asset vocabulary (`L1`–`L4`) and package-shaped private examples obscured the product domain and preserved an obsolete
private-repository workflow after ADR 0129 made PostgreSQL the Private Asset authoring Authority. PA-2 also needs one native Alpha path
from immutable Revision source through Calculation, Catalog and Runtime authorities without a duplicate package implementation.

## Decision

The active quant-asset kinds are exactly:

```text
OPERATOR
INDICATOR
ALPHA
STRATEGY
```

Active code and contracts use `OnlyQuantAssetKind`, `PrivateAlpha*`, `PrivateStrategy*`, `private.alpha.*`, and the PostgreSQL tables
`private_alpha_*` / `private_strategy_*`. Calculation's scientific `FACTOR` kind remains valid and distinct from asset-kind vocabulary.
No compatibility aliases, dual parsers, legacy views or fallback loaders are retained during the development-unfrozen migration.

The external `OnlyAlpha-alpha` / `OnlyAlpha-strategies` repository model and package-shaped private examples are retired. Portable
non-production examples live under:

```text
examples/private-assets/alpha/<example>/asset.json + source.py
examples/private-assets/strategy/<example>/strategy.json
```

An example is import input, not Authority. Import strictly validates the bundle, uses the Private Asset Authority to create/save a Draft
and publish an immutable Revision, and returns the exact Revision reference. Strategy dependency example IDs resolve at import time to
exact imported Alpha Revision references. Import is explicit and idempotent; startup auto-import is forbidden.

Private Alpha execution follows one path:

```text
PrivateAlphaRevision
→ validated immutable Alpha Source Artifact
→ Alpha API facade over canonical value semantics
→ RESEARCH/TRADING Calculation registrations
→ snapshot-backed Alpha Provider
→ one Catalog Generation
→ exact Runtime Generation
```

Snapshot-backed Alpha Providers have no fabricated distribution identity. New Runtime creation re-anchors the exact database Revision;
historical Runtime rebuild uses only the exact immutable artifacts already bound by its manifest. Missing or corrupt artifacts fail
closed, and no current/latest/fall-forward lookup or adapter substitution is permitted.

## Migration semantics

Migration `0028_private_alpha_strategy_vocabulary` is transactional and forward-only. Because changing an Alpha ID or Revision payload
would change immutable identity, the development migration requires the old authoring tables to be empty and fails closed otherwise.
It then renames tables, columns, constraints and immutable-history triggers and installs the `private.alpha.*` identity constraint. This
precondition avoids silently rewriting immutable history; environments with unpublished development data must export/re-import through
the current Authority instead of receiving an identity-preserving fiction.

## Consequences

- Operator/Indicator remain public reusable plugin capabilities.
- Production Alpha/Strategy authoring remains PostgreSQL-native.
- Example availability does not imply imported database state.
- Runtime and Catalog identities remain distinct from authoring, repository and filesystem identity.
- Historical ADR and migration bodies retain their original terminology as historical evidence.
- PA-3 Strategy composition, PA-4 Registry/Search Projection, AI Alpha generation and final Web example UI remain deferred.

## Rejected alternatives

- Numbered active enum values or `OnlyQuantAssetLayer` compatibility aliases.
- Dual `private.factor.*` / `private.alpha.*` parsing.
- Compatibility views over numbered tables.
- Mandatory private Git repositories, editable installs, wheels or PR admission.
- Direct SQL seed import or startup auto-population.
- Executing example source directly from its repository path.
- Package-backed fallback for native Alpha execution.
- Historical rebuild from current database source, latest Revision, active Catalog or current adapter.
