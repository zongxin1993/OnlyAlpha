# ADR 0135: Chart-Centric Product-Driven Vertical Slice Development

- Status: Accepted
- Date: 2026-09-23
- Decision maker: repository owner
- Related: ADR 0092, ADR 0094, ADR 0103, ADR 0130
- Constitution Impact: NO

## Context

OnlyAlpha already has substantial Research, Backtest, Runtime, Product API and Web foundations, but continued backend-first horizontal
development risks producing a Web product that mirrors internal modules instead of the way an operator actually researches, validates and
trades. A backend capability being present does not prove that the corresponding product workflow is understandable, efficient or even
complete from a user's perspective.

The current P8.4 Web architecture was intentionally Research-first. It established important durable boundaries, especially that the
browser is Control + Presentation only and that scientific truth must come from formal Result/Artifact/Query authorities. Those
boundaries remain correct. What changes now is the product center and development sequence for future Web work.

OnlyAlpha needs the Web to become an active product specification and pressure test for Domain, Product API, lifecycle, status and
workflow design. Product behavior should therefore be completed as end-to-end user-visible vertical slices instead of implementing large
backend areas speculatively and attaching pages later.

TradingView Supercharts is used as the primary interaction reference for the chart-centric workstation because its symbol, timeframe,
chart, indicator, drawing, watchlist, replay and chart-trading interaction model is familiar and coherent. This is an interaction
reference, not a source-code, asset, branding or authority dependency.

## Decision

Future OnlyAlpha Web product development uses **Product-Driven Vertical Slice Development** with a **chart-centric workstation** as the
long-lived primary workspace.

The default product loop is:

~~~text
Reference Interaction
→ User Goal and Observable Behavior
→ UI/Product Slice
→ Product API / Authority Gap Analysis
→ Reuse Existing Capability or Add Minimum Missing Capability
→ Formal Versioned Product API
→ Browser Integration
→ Browser E2E
→ Real Operator Use / Dogfooding
→ Slice Closure
~~~

A feature is not considered product-complete because backend classes, routes or unit tests exist. It closes only when the intended user
workflow works through the formal product boundary and the visible loading, empty, error, degraded and success states are intentionally
handled.

### 1. Chart-centric primary workspace

The forward product center is a TradingView-like analysis and trading workspace, not an admin dashboard organized around backend
packages.

Conceptually:

~~~text
Top product controls
  symbol / timeframe / chart / indicator / replay / workspace actions
        │
        ▼
Primary chart workspace
        │
        ├── contextual tools / drawings
        ├── overlays / factors / strategy state
        ├── right-side watchlist / inspector / details
        └── bottom research / backtest / orders / positions / evidence surfaces
~~~

Research, Backtest, SIM and LIVE remain formal OnlyAlpha product concepts. They become workflows reachable from the common workspace
where that improves operator continuity; they do not become browser-owned semantics.

### 2. TradingView is a reference, not a clone contract

OnlyAlpha may intentionally reuse proven interaction patterns such as:

- symbol search and symbol switching;
- timeframe and chart controls;
- indicators and overlays;
- watchlists;
- drawing/tool interaction;
- replay workflows;
- chart-linked Research and Backtest actions;
- order/position visualization where formal trading capability exists;
- alerts, screeners and multi-chart workspaces when later slices require them.

OnlyAlpha must not copy proprietary source code, branding, icons, protected assets or undocumented private behavior. Product parity means
similar operator capability and workflow where it serves OnlyAlpha's scope, not pixel-perfect or feature-complete cloning of
tradingview.com.

### 3. UI first means product contract first, not browser authority

For a new Web capability, the team first defines the user-visible interaction and acceptance flow. That interaction then reveals what
formal Queries, Commands, projections or missing Kernel capability are actually required.

The browser must still follow:

~~~text
Web
→ versioned Product API
→ Application Command / Query boundary
→ canonical Authority
~~~

Forbidden shortcuts include:

~~~text
Web → direct PostgreSQL
Web → direct Store
Web → internal Python Core import
Web → duplicated Research/Trading calculation
Web → mutable local truth that replaces durable authority
~~~

If the desired product behavior cannot be expressed by the current Product API, the correct response is to evolve the canonical
Application/Product boundary, not to create a Web-only semantic path.

### 4. Backend scope is derived from the active product slice

Once foundational Kernel capability exists, backend work for Web productization should normally be justified by a current vertical slice.

The default rule is:

~~~text
Current Product Slice needs it
→ implement the minimum complete canonical capability

Current Product Slice does not need it
→ do not add speculative backend surface
~~~

Exceptions are independently justified correctness work such as Authority repair, data corruption prevention, security, recovery,
reconciliation, deterministic identity, required infrastructure or an explicitly owner-approved non-Web roadmap task.

This rule limits speculative breadth; it does not weaken Constitution, canonical trading semantics or existing correctness obligations.

### 5. One slice closes end to end before product breadth expands

A normal Web product slice should include, as applicable:

1. a concrete user goal;
2. interaction/reference definition;
3. visible states and error/degraded behavior;
4. exact existing Product API reuse;
5. explicit missing Product API/Authority gap, if any;
6. minimal backend implementation for that gap;
7. browser integration through generated/formal API clients;
8. targeted frontend and backend tests;
9. at least one browser-level E2E path for the main workflow;
10. dogfooding/review against the intended interaction before moving on.

Large horizontal batches such as "implement all alert backend infrastructure now, add UI later" are not the default productization model.

### 6. Renderer decisions remain separate

This ADR does **not** change ADR 0094.

The currently accepted renderer boundary remains:

~~~text
Financial time-series → TradingView Lightweight Charts
Scientific/statistical → Apache ECharts
Semantic/execution graph → Graphviz / @viz-js/viz
~~~

Using TradingView Advanced Charts, Trading Platform or another renderer requires a separate explicit architecture and licensing review.
The development mode must not smuggle a renderer replacement into a feature implementation.

### 7. Relationship to ADR 0092

ADR 0092 remains authoritative for:

- browser Control + Presentation ownership;
- no browser-side Research/Statistics authority;
- immutable Result/Artifact/Query read boundaries;
- durable Run truth;
- URL/shareable identity principles;
- responsive workstation principles;
- low-decoration, data-first visual direction.

This ADR supersedes ADR 0092 only where ADR 0092 freezes "New Research / Runs / Results" as the forward primary product navigation or
treats the Research Studio layout as the permanent center of later Backtest/SIM/LIVE productization. Those surfaces remain valid
implemented capabilities, but future product organization is chart-centric and workflow-driven.

## Consequences

- Web becomes a primary product-discovery and architecture-pressure-test surface rather than a final skin over completed backend modules.
- Product navigation follows operator workflows instead of internal package/entity taxonomy.
- Missing Web capability is classified as presentation work, Product API gap or canonical Authority gap before implementation.
- Backend scope is less likely to grow through speculative abstractions with no current user workflow.
- Existing Research/Backtest/SIM/LIVE authorities are preserved and surfaced through a common interaction model.
- Older P8.4 Research Studio implementation may be reused, moved, reduced or replaced as the chart-centric workspace evolves; unpublished
  internal compatibility is not a constraint under ADR 0130 unless explicitly frozen.
- Current implementation truth must still be inspected before each slice; roadmap order does not imply a capability already exists.

## Rejected alternatives

- Continue backend-first horizontal expansion and postpone product integration.
- Treat the existing P8.4 Research navigation as the permanent top-level user workflow.
- Build an admin dashboard that exposes backend entities one-for-one.
- Reproduce tradingview.com pixel-for-pixel or copy proprietary assets/implementation.
- Let React compensate for missing canonical APIs by reading stores or recomputing semantics.
- Replace Lightweight Charts implicitly because TradingView is the product interaction reference.
- Implement many future backend capabilities before a real product slice needs them.

## Validation

Future Web/Product reviews must verify:

1. the task names a concrete operator workflow, not only a backend component;
2. Product/API gaps are explicit before new backend surface is added;
3. Web accesses canonical facts only through formal Product APIs;
4. the browser does not become Research, Trading, Runtime or persistence Authority;
5. the main slice is exercised end to end at browser level where technically practical;
6. loading, empty, invalid, unavailable and degraded states are intentional rather than accidental;
7. no speculative backend abstraction is introduced without a current consumer or separate approved requirement;
8. ADR 0094 renderer boundaries remain unchanged unless separately superseded;
9. current Product/API/Kernel behavior is inspected rather than inferred from the desired UI;
10. closure means the user-visible workflow is usable, not merely that underlying endpoints exist.
