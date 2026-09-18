# ADR 0133: Private Strategy Definition and Research Composition Authority

- Status: Accepted
- Date: 2026-09-18
- Decision maker: repository owner
- Related: ADR 0129–0132
- Constitution Impact: NO

## Decision

`PrivateStrategyRevision` is the PostgreSQL-owned authoring identity and contains a strict, canonical Strategy Definition. Its
universe, market-input contract, calculation references, fixed parameter bindings, exact private Factor Revision dependencies,
eligibility, entry and exit semantics are Strategy-owned. V1 rejects sweep parameters and arbitrary JSON.

Research-only period, target calculations, statistics requests and presentation metadata are carried by a separate immutable Research
Context. Context never overrides Strategy semantics.

One `OnlyPrivateStrategyResearchComposer` deterministically lowers an exact Strategy Revision, exact Research Context and one exact
Catalog Generation into the existing authoring-neutral `OnlyResearchDefinition`. It re-anchors Strategy and Factor Revisions through
their owning authorities, requires exact RESEARCH capabilities and rejects latest/current/fall-forward resolution.

`OnlyPrivateStrategyResearchCompositionV1` is immutable lineage evidence. It proves the exact Strategy Revision, Context, Factor
Revision bindings, Catalog Generation and derived Research Definition fingerprint. It owns no statistics, Research Result,
Qualification or runtime identity. Composition storage is append-only and fingerprint verified.

The existing Research Run, Research Evidence and Strategy Freeze authorities remain unchanged in ownership. Strategy-authored Runs
carry the exact Composition fingerprint; existing Freeze remains the sole creator of `OnlyStrategyRevision`. A Private Strategy
Revision cannot directly enter Backtest, SIM or LIVE, and authoring provenance is excluded from runtime Strategy identity.

## Consequences

- Database JSON remains the physical Private Strategy storage format, but strict domain parsing is the semantic boundary.
- Composition can be independently re-derived from exact immutable inputs and fails closed on missing or mismatched authority data.
- A new checksummed migration stores Composition facts and the exact Research Context payload; no latest pointer is introduced.
- Private Strategy package/Git authoring, a second Strategy DSL, a second Research engine and a second runtime Strategy identity remain
  out of scope.
