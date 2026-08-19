# ADR 0094: Web Visualization Renderer Boundaries

- Status: Accepted
- Date: 2026-08-19
- Related: ADR 0092, 0093; P8.4 Research Studio Web
- Supersedes: the statement in `docs/web-product-architecture.md` §13 that the exact chart library is freely adaptable without an ADR. Renderer replacement now requires explicit architecture review because the three renderer families and their ownership boundaries are intentionally frozen here.

## Context

OnlyAlpha Web must present several fundamentally different visualization problems:

1. financial time-series evidence such as K-line, volume, Indicator/Feature overlays, Factor Score panels, and Entry/Exit markers;
2. scientific/statistical analysis such as Scatter, Distribution, Quantile, Heatmap, and candidate parameter surfaces;
3. semantic/execution graph inspection for Research/Decision Graphs.

Trying to force all three classes through one renderer would either reduce product quality or couple product semantics to a chart library. The browser also must remain Control + Presentation and may not use visualization-library transforms to become a second Research/Statistics authority.

## Decision

OnlyAlpha Web uses three renderer families with explicit ownership boundaries.

```text
OnlyAlpha Visualization
│
├── Financial Time-Series
│      └── TradingView Lightweight Charts
│
├── Scientific / Statistical
│      └── Apache ECharts
│
└── Semantic / Execution Graph
       └── Graphviz via @viz-js/viz
```

The renderer choice is presentation infrastructure. Domain and API contracts must remain OnlyAlpha-owned.

### Financial Time-Series: TradingView Lightweight Charts

TradingView Lightweight Charts is the standard financial/time-series renderer for:

```text
K-line / OHLC
Volume
price overlays
Indicator panels
Factor Score panels
Target time-series presentation where appropriate
Entry / Exit markers
```

The existing Web already depends on `lightweight-charts` and has an OnlyAlpha chart wrapper. P8.4 should evolve that technical choice into a formal adapter rather than importing the library directly throughout feature pages.

Recommended data direction:

```text
Verified Artifact Evidence
        ↓
Research Query API
        ↓
Exact Web Admission
        ↓
OnlyAlpha Chart Projection
        ↓
OnlyAlpha Lightweight Charts Adapter
        ↓
TradingView Lightweight Charts
```

Candidate selection changes which exact evidence projection is shown; the browser never recalculates the candidate's Indicator, Factor, Eligibility, or Signal.

### Scientific / Statistical: Apache ECharts

Apache ECharts is the default scientific/statistical renderer for:

```text
Scatter
Distribution / Histogram presentation
Box / Quantile presentation
Heatmap
IC / RankIC comparison
one-dimensional candidate metric curves/scatter
multi-dimensional candidate exploration
Parallel Coordinates
```

Default candidate visualization policy:

```text
1 sweep dimension
→ Scatter / Line-style metric view

2 sweep dimensions
→ Heatmap as Candidate Surface V1

3+ sweep dimensions
→ Parallel Coordinates + Candidate Table
```

P8.4 does not introduce 3D candidate surfaces as a default product primitive. A specialized renderer such as Plotly may be considered later only when a proved use case needs real 3D scientific visualization.

ECharts data transforms, regression, aggregation, binning, or statistical helpers must not replace OnlyAlpha Statistics authority. Presentation-only lossy binning is allowed only when explicitly labeled as presentation and is not persisted or promoted as Research truth.

### Semantic / Execution Graph: Graphviz

Graphviz is the renderer for read-only DAG inspection.

P8.4 and later Web surfaces should support two conceptual graph levels:

```text
Semantic Graph
→ user-readable Calculations / Eligibility / Entry / Exit / Target / Statistics relationships

Exact Graph
→ exact resolved Calculation/Decision topology, identities, parameters, ports, and role-bearing terminals
```

Graph visualization is not the authoring authority.

```text
Structured Builder
→ Semantic Definition
→ Server/Domain Resolver
→ Exact Graph Authority
→ Graph Projection DTO
→ Web Graphviz Adapter
→ DOT
→ @viz-js/viz
→ SVG
```

Graphviz DOT, SVG, node position, colors, shapes, clusters, and layout are presentation facts only. Runtime must never parse DOT as the strategy/Research execution authority.

Graphviz is intended as a `Graph Inspector`, not a P8 node editor. P8 must not reintroduce arbitrary DAG authoring merely because the exact graph can be visualized.

### Graph interaction

Graph nodes/edges should use stable projection IDs so Web can support:

```text
click node
→ Contextual Inspector
→ semantic reference
→ exact type/version
→ parameters
→ inputs/outputs
→ published output role
→ candidate identity when applicable
→ exact fingerprints when appropriate
```

A large Sweep must not render every candidate graph simultaneously. The intended model is:

```text
Definition/Semantic Graph
+ Candidate Table / ECharts comparison
+ one selected candidate's Exact Graph
```

### Renderer adapters are OnlyAlpha-owned boundaries

Feature/page code should not spread direct renderer-library imports across the application.

Target organization is conceptually:

```text
visualization/
├── model/
│   ├── financial.ts
│   ├── scientific.ts
│   └── graph.ts
│
├── financial/
│   └── lightweight/
│
├── scientific/
│   └── echarts/
│
└── graph/
    └── graphviz/
```

Exact paths are adaptable. The invariant is:

```text
API DTO
!=
Renderer input model
```

OnlyAlpha projection/admission code must stand between transport DTOs and third-party renderer objects.

### Exact values and lossy presentation

Exact Decimal and nanosecond timestamp semantics remain outside chart libraries. Browser conversion to JavaScript number or chart timestamp is an explicit presentation projection.

```text
Exact domain value
→ admitted presentation projection
→ renderer
```

Renderer output must never flow backward and become Result/Statistics/Signal authority.

## Consequences

- Each visualization library is used where its domain model is strongest.
- Financial time-series UX does not dictate scientific-statistics UX.
- ECharts is not forced to become the K-line engine, and Lightweight Charts is not forced to render heatmaps/scientific parameter spaces.
- Graphviz provides explainability/auditability without turning Web into a node-based strategy IDE.
- Future library replacement remains localized behind OnlyAlpha-owned projection/adapter boundaries.
- Scientific evidence gaps remain Result/Artifact/Query contract problems, not reasons for chart-side semantic computation.

## Rejected alternatives

Rejected:

- one universal chart library for all OnlyAlpha visualization needs;
- full TradingView Charting Library as the default P8 research renderer;
- React/ECharts calculating authoritative Factor/Signal/IC/RankIC results;
- Graphviz DOT as execution authority;
- editable Graphviz/node-editor strategy authoring in P8;
- rendering all Sweep candidate graphs at once;
- importing chart libraries directly in every product page.

## Validation

Web implementation must verify:

1. Lightweight Charts receives only admitted time-series presentation models.
2. ECharts receives only admitted scientific presentation models and does not create persisted Research truth.
3. Graphviz receives only Graph Projection DTOs derived from authoritative semantic/exact graphs.
4. feature pages do not own renderer-specific semantic computation.
5. graph visualization is read-only in P8.
6. exact Decimal/time identities remain recoverable outside lossy chart projections.
7. candidate visualization uses Table/ECharts for candidate spaces and Graphviz only for one definition/selected exact graph.
