# ADR 0110: Four-Layer Quant Asset Model and Local Example Boundary

- Status: Accepted
- Date: 2026-09-03
- Related: ADR 0020, 0021, 0069 (Calculation), 0070 (Calculation), 0076, 0098, 0108

## Context

OnlyAlpha's one Calculation abstraction currently exposes reusable financial Indicators and an official Factor package containing
both a hypothesis-bearing Momentum calculation and generic cross-sectional percentile mathematics. That placement conflates
reusable mathematics with private Alpha hypotheses. Older decisions also place examples in separate repositories, while the main
repository now needs executable, non-production references that prove the same public integration boundary future private assets
will use.

## Decision

Quantitative assets have four semantic responsibility layers:

1. **L1 Mathematical Operator** is a deterministic transformation meaningful without financial context.
2. **L2 Financial Indicator** is a deterministic Calculation with stable financial/descriptive meaning and no predictive Target
   hypothesis.
3. **L3 Alpha Factor** is a hypothesis-bearing Calculation or canonical Calculation composition used to explain or predict a
   Research Target.
4. **L4 Strategy** is a canonical decision asset combining admitted Features, Factors and eligibility/selection logic into
   deterministic signal, selection or rank semantics.

L1 and L2 are public reusable OnlyAlpha capabilities. Production L3 and L4 assets belong in future private repositories. The main
repository keeps exactly two local non-production reference libraries: `examples/onlyalpha-example-alpha/` for L3 and
`examples/onlyalpha-example-strategies/` for L4. The L3 example is deliberately loaded through the public
`onlyalpha.calculations` SPI; this Accepted architecture decision is the explicit exception to the default concrete-plugin
placement rule. It proves extraction to a private distribution without changing Core. Example packages are never default
production dependencies or runtime authorities.

Calculation remains the only calculation engineering abstraction and `OnlyCalculationGraphDefinition` remains the only DAG
authority. No Operator, Indicator, Factor or Strategy graph is added. Feature remains a Calculation output port identified by
`node_fingerprint + output_name`; it receives no store or identity authority. Factor remains hypothesis-bearing. Runtime Strategy
authority remains the immutable `StrategyRevision` created by verified Research Candidate Freeze, never a callback or an example
file name.

L1 reuses the existing deterministic non-FACTOR Calculation path and the `onlyalpha.operator.*` type-id namespace. No
`OnlyCalculationKind.OPERATOR` is added because kind is a persisted and Product API compatibility surface. A Definition-owned
execution shape distinguishes time-series and cross-section mechanics independently from Factor hypothesis semantics.

The public dependency direction is:

```text
OnlyAlpha public Calculation contracts
        ↑
L1 Operators
        ↑
L2 Indicators
        ↑
L3 Alpha assets
        ↑
L4 Strategy authoring assets
```

Core imports no concrete layer implementation. L1 cannot depend on L2/L3/L4; L2 cannot depend on L3/L4; public L1/L2 cannot depend
on examples; production runtime cannot use an example filesystem path as Strategy authority.

The official `onlyalpha-plugin-factors` distribution is retired. `onlyalpha.factor.momentum@1` and
`onlyalpha.factor.cross_section_percentile@1` are removed from the active official catalog and are not aliased. The new identities
are `example.factor.momentum@1` for the L3 example and `onlyalpha.operator.cross_section_percentile@1` for generic L1 mathematics.
Persisted facts referencing retired identities require the exact historical package/version to replay and otherwise fail closed.

`onlyalpha-plugin-indicators` remains the public L2 library and keeps its existing semantic identities. `onlyalpha-plugin-targets`
remains orthogonal public Research evaluation infrastructure. IC/RankIC remain Research statistics, while Portfolio, Risk and
Execution remain downstream authorities rather than additional asset layers.

The Agent's primary creation/search domain is L3/L4. It may query and compose L1/L2. A missing reusable primitive or financial
indicator must be proposed and admitted independently into L1/L2; it cannot be hidden inside a Factor or Strategy.

## Relationship to earlier decisions

ADR 0076 remains authoritative for the single Calculation/Graph model, deterministic cross-section execution, Factor Value/Score
ports and Research result authority. This ADR supersedes only its classification of generic percentile/ranking as an Alpha Factor:
generic rank/normalization is L1 mathematics, while an L3 Factor may consume it and expose its own `FACTOR_SCORE` port.

This ADR supersedes only the repository/example placement clauses in ADR 0020, ADR 0021 and related old example documentation.
Their Core dependency, Cluster, Engine-internal composition and authority rules remain in force subject to later Accepted ADRs.
It clarifies ADR 0069/0070 by replacing the official empty/public Factor extension point with public L1/L2 packages plus an
external-style local L3 reference.

## Consequences

OnlyAlpha publicly owns reusable mathematics and stable financial knowledge, while proprietary hypotheses and strategies can move
to private distributions without Core changes. Semantic identity migration is explicit. The example Momentum RESEARCH/TRADING
implementations must satisfy the same manifest, equivalence, Freeze and Backtest admission contracts as any future private Factor.
The example Strategy library contains authoring data only and cannot call Engine, write a database or mint Strategy Revisions.

## Rejected alternatives

- Four execution frameworks or four DAG authorities.
- A new `OnlyCalculationKind.OPERATOR` or Product API major solely for layer labeling.
- Keeping generic ranking under Factor semantics.
- Silently reinterpreting or aliasing retired Factor identities.
- Making examples production dependencies or callback Strategy authorities.
- Adding a Feature Store, Factor Registry database, Strategy Git authority, new DSL, Engine or Research Runtime.
