# OnlyAlpha Web Product Architecture

This document describes the target Web product shape that P8.4 should implement and that later Backtest/Sim/Live Web surfaces should reuse where compatible. It complements [ADR 0092](adr/0092-web-scientific-workstation-and-browser-authority-boundary.md), which owns the durable architectural constraints. Exact pixels, component names, colors, and implementation details remain adaptable unless explicitly frozen by an ADR.

## 1. Product role

OnlyAlpha Web is a **Scientific Quant Workstation**.

Its job is to let a user move through a repeatable quantitative workflow:

```text
Define
→ Run
→ Observe
→ Analyze
→ Compare
→ Iterate
```

The Web layer presents and controls existing authoritative domain/application boundaries. It must not become a second implementation of Research semantics.

The product should feel closer to a scientific/research workstation than to either a generic admin dashboard or a brokerage terminal clone:

- dense but readable;
- data-first;
- low-decoration;
- optimized for desktop research work;
- responsive when the viewport shrinks;
- explicit about exact identity, validation, and evidence;
- capable of growing into Backtest/Sim/Live without replacing the application shell.

## 2. Persistent application shell

The long-lived shell has five conceptual surfaces:

```text
┌──────┬──────────────────────────────────────────────────────────────────────┐
│      │ Product / Workspace header                                           │
│      ├──────────────────────────────────────────────────────────────────────┤
│      │ Product-local navigation                                             │
│      ├────────────────────────────────────────────┬─────────────────────────┤
│      │                                            │                         │
│      │                                            │ Contextual Inspector    │
│ Rail │             Central Workspace              │                         │
│      │                                            │                         │
│      │                                            │                         │
│      ├────────────────────────────────────────────┴─────────────────────────┤
│      │ Status Surface                                                        │
└──────┴──────────────────────────────────────────────────────────────────────┘
```

### 2.1 Global Product Rail

The left rail is intentionally narrow and expresses only top-level product domains.

P8 can expose only the domains that have real product value, for example:

```text
Research
Data
System
```

Future productization may add:

```text
Backtest
Sim
Live
```

without changing the shell model.

The rail is not a reflection of Python packages or database entities. `Dataset`, `Calculation`, `Statistics`, `ResearchResult`, `Artifact`, `ResearchRunAttempt`, `Worker`, `Scheduler`, migration tables, and stores must not become first-level navigation merely because they exist internally.

A compact rail in the rough range of 56–64 px is a reasonable implementation target, but the exact width is not frozen.

### 2.2 Product Workspace Navigation

Once a product domain is selected, a small product-local navigation layer selects the workflow surface.

For Research:

```text
New Research
Runs
Results
```

This separation lets the Global Product Rail stay stable even as each product gains more internal pages.

### 2.3 Central Workspace

The central workspace owns the majority of horizontal space. Charts, dense tables, expression builders, scientific plots, and candidate analysis must not be squeezed by permanent oversized navigation.

Layout priority is:

```text
Central Workspace
>
Contextual Inspector
>
Navigation
```

### 2.4 Contextual Inspector

The right-side Inspector is a persistent interaction pattern. It is contextual, collapsible, and presentation-state persistence is allowed.

Typical desktop width may be roughly 280–340 px, but this is not an architectural constant.

The Inspector never owns domain truth; it projects currently selected context.

### 2.5 Status Surface

A thin status surface can expose exact system context that is useful across pages, such as environment/version, current API connectivity, current Dataset/Run context when appropriate, and non-semantic operational health.

It must not become a place to invent business state that no authority owns.

## 3. Research information architecture

P8.4 uses this primary product structure:

```text
Research
├── New Research
├── Runs
└── Results
```

These are workflow surfaces rather than backend entity screens.

The intended loop is:

```text
New Research
      ↓
Submit
      ↓
Runs
      ↓
Completed Run
      ↓
Results
      ↓
Analyze / Compare
      ↓
Clone or modify intent
      ↓
New Research
```

## 4. New Research

### 4.1 Purpose

`New Research` is where user intent is expressed through a structured builder and deterministically resolved into the formal Research execution contract.

The page is not a raw Specification editor and not a multi-step wizard.

The conceptual composition is:

```text
Universe / Time
Calculations
  ├── Indicator
  └── Factor
Eligibility
Entry Decision
Exit Decision
Target
Statistics
```

The exact P8.4 Domain model for Universe/Eligibility/Decision remains future implementation work; the UI must not pre-empt that work with a private JSON schema.

### 4.2 Recommended desktop layout

```text
┌────────────────────────────────────────────┬───────────────────────────┐
│ New Research                               │ Research Inspector        │
│                                            │                           │
│ Universe                                   │ Summary                   │
│ ─────────────────────────────────────────  │                           │
│ Single | Pool | Market                     │ Universe                  │
│                                            │ CSI300                    │
│ Time                                       │                           │
│ 2024-01-01 → 2026-01-01                   │ Dataset                   │
│                                            │ resolving / resolved      │
│ Calculations                               │                           │
│ ─────────────────────────────────────────  │ Calculations              │
│ Momentum                                   │ Momentum(20)              │
│   window       20                          │ RSI(14)                   │
│   score        momentum_score              │                           │
│                                            │ Eligibility               │
│ RSI                                        │ price > 5                 │
│   period       14                          │                           │
│                                            │ Entry                     │
│ Eligibility                                │ RSI < 30 AND MOM > 0      │
│ ─────────────────────────────────────────  │                           │
│ price > 5                                  │ Statistics                │
│ liquidity > ...                            │ IC / Rank IC              │
│                                            │                           │
│ Entry / Exit                               │ Validation                │
│ ─────────────────────────────────────────  │ Valid / Problems          │
│ ...                                        │                           │
│                                            │ Exact Specification       │
│ Target / Statistics                        │ Read-only advanced view   │
│                                            │                           │
│                       Validate   Run ▶      │                           │
└────────────────────────────────────────────┴───────────────────────────┘
```

### 4.3 Builder semantics

The builder displays product semantics rather than transport/internal identities.

Prefer:

```text
Momentum
Window: 20
Primary Score: momentum_score
```

over presenting internal fields such as `calculation_id`, `template_node_id`, and output fingerprints as the normal authoring UX.

Exact identities remain available when useful in the Inspector.

### 4.4 Builder → Domain → Specification

The only acceptable semantic direction is:

```text
User Intent
→ Structured Builder
→ Formal versioned Domain/Product value
→ Deterministic validation/resolution
→ Exact Research Specification
→ Existing Research execution path
```

React state may temporarily represent fields while the user is editing, but it must not become an undocumented semantic language that the backend then tries to interpret.

### 4.5 Specification view

The Inspector may offer tabs such as:

```text
Summary | Specification | Identity
```

`Specification` can show the canonical exact document for advanced inspection.

P8.4 does not make raw JSON the ordinary editing surface. This avoids a second editable state that must be synchronized bidirectionally with the structured builder.

### 4.6 Validate vs Run

Validation and durable submission are distinct user actions/concepts.

```text
Builder
  ↓
Validate
  ↓
Domain / Resolution feedback
  ↓
Exact Specification
  ↓
Run Research
  ↓
Durable Research Run
```

Validation errors should map back to the relevant builder section whenever the formal error contract supports that precision. The UI should not reduce all domain admission failures to a generic `400 Bad Request` toast.

## 5. Runs

### 5.1 Purpose

`Runs` is the operational console over durable Research Run facts.

The primary presentation is a dense table, not a card wall.

Example:

```text
State        Submitted       Research              Duration      Result
──────────────────────────────────────────────────────────────────────
RUNNING      15:12:31        ETF Momentum          01:22         —
QUEUED       15:13:02        RSI Sweep             —             —
COMPLETED    15:04:20        IC Research           02:04         Open
FAILED       14:51:10        Factor Test           00:03         —
```

Only fields that are actually present in the authoritative operational projection may be shown as facts.

### 5.2 Run state

The public state set currently includes:

```text
QUEUED
RUNNING
CANCEL_REQUESTED
COMPLETED
FAILED
CANCELLED
```

Do not derive or display semantic percent-complete values until an accepted authority explicitly owns progress.

### 5.3 Run Inspector

Selecting a Run may populate the contextual Inspector with:

```text
State
Submitted / started / finished timestamps when available
Failure information
Exact Result reference
Exact Artifact reference
Run identity / revision
Approved diagnostics from the current public contract
```

Attempt/worker/lease internals should not automatically pollute the main table. If operational diagnostics later require a formal product surface, they should be introduced deliberately.

### 5.4 Browser lifecycle

Closing or refreshing the browser must not affect server execution. Reloading the Runs page reconstructs the view from durable server authority.

## 6. Results

### 6.1 Purpose

`Results` is a scientific Research workspace, not an Artifact-file browser.

Users should find results in research terms such as Research intent, Universe, period, Calculation/Factor/Target context, Statistics, and completion time while exact fingerprints remain available for audit and deep linking.

### 6.2 Result Detail information architecture

The target product structure is:

```text
Overview
Chart
Statistics
Candidates
Exact Data
```

This is an information architecture target; a P8.4 sub-increment may implement only tabs for which current Result/Artifact evidence exists.

The UI must hide or defer unsupported scientific views rather than synthesizing data in the browser.

### 6.3 Overview

Overview answers: "what exactly was researched?"

It can contain user-readable context such as:

```text
Universe
Period
Calculations / Factor
Target
Statistics
```

and advanced exact identity in the Inspector:

```text
Dataset Snapshot fingerprint
Specification fingerprint
Research Result fingerprint
Artifact fingerprint
```

### 6.4 Chart Workspace

The long-term chart model is multi-panel and evidence-driven:

```text
Price / historical market context
────────────────────────────────
Indicator overlays
────────────────────────────────
Selected Feature / Indicator panel
────────────────────────────────
Factor Score panel
────────────────────────────────
ENTRY / EXIT markers when formally produced
```

The browser may convert exact values to chart-compatible values only as an explicit presentation projection. It must not recalculate signals or factor/statistics truth.

### 6.5 Statistics Workspace

The conceptual model is:

```text
Statistics Catalog
      +
Selected Statistic Workspace
```

Potential evidence-backed views include:

```text
Summary
Series
Distribution
Scatter
Quantile
Heatmap
```

A view exists only when the immutable read contract supplies the required facts.

### 6.6 Candidate master-detail

Cross-sectional research benefits from a master-detail model:

```text
Candidate Table
      +
Selected Candidate Inspector
```

For example:

```text
Symbol       Score      Target      Rank
600519       2.31       1.8%        1
000858       2.18       1.4%        2
```

The candidate Inspector can expose only evidence-backed Price/Feature/Score/Eligibility/Signal/Target fields.

### 6.7 Exact Data

`Exact Data` is a first-class long-term surface because OnlyAlpha values deterministic, auditable research.

Presentation operations may include:

```text
sort
filter visible rows
column visibility
copy
export when implemented
```

These operations do not create new Research semantic facts.

## 7. Browser authority and data flow

The browser is a control/presentation client.

Allowed browser work includes:

```text
routing
component layout
local panel state
query caching
formatting
safe exact-value admission
chart zoom/pan
selected series visibility
presentation sorting/filtering
lossy plotting projection
```

Forbidden as a replacement for backend authority:

```text
Factor Score calculation
Feature semantic calculation
Eligibility evaluation
Entry/Exit Signal generation
Target generation
IC / RankIC calculation
Statistics generation
Candidate semantic ranking
Research Result composition
Artifact composition
```

The scientific consumption chain stays:

```text
Research Result
→ Verified Portable Artifact
→ Read Model
→ Query API
→ Web
```

If the browser needs K-line, Feature, Factor Score, Signal, cross-sectional candidate, scatter, quantile, or heatmap data that the current Artifact cannot prove, P8.4 must evolve the authoritative Result/Artifact/Query contract first.

## 8. Routing and state ownership

Page-level identity should be encoded in routes where practical.

Recommended shape:

```text
/research/new
/research/runs
/research/runs/:runId
/research/results
/research/results/:researchResultFingerprint
/research/results/:researchResultFingerprint/statistics/:statisticsFingerprint
```

Exact route spelling can evolve, but URL-owned selection is preferred for shareable/refreshable context.

### Browser-local state

Suitable local state:

```text
Inspector open/closed
selected presentation tab
column widths / visibility
theme
chart viewport
panel sizing
```

Not suitable as the only authority:

```text
submitted Research Definition
Run lifecycle state
Research Result
Artifact content/identity
semantic Statistics/Factor/Signal truth
```

TanStack Query or equivalent caches are disposable projections, not authorities.

## 9. Responsive behavior

Responsive design does not require identical feature capability on every device.

Recommended behavior:

| Viewport | Product behavior |
|---|---|
| >= 1440 px | full workstation + visible Inspector |
| 1024–1439 px | compact rail + collapsible Inspector |
| 768–1023 px | main workspace + Inspector drawer |
| < 768 px | Runs/Results/basic viewing first; complex authoring optional/deferred |

On mobile, a bottom navigation may replace the desktop rail if implementation benefits from it. This is a presentation choice, not an authority change.

## 10. Visual system

The product visual direction is:

```text
Professional
Scientific
Dense but readable
Low decoration
Data first
Desktop first
Responsive
```

Avoid making terminal aesthetics themselves the product architecture. CRT scanlines, HUD overlays, glow, and decorative gradients are not requirements.

### Typography roles

A sensible role split is:

```text
UI / headings / navigation → sans-serif
Quantitative values / timestamps / fingerprints → monospace
```

Numeric surfaces should favor tabular-number alignment.

### Design tokens

Theme-sensitive styles should be expressed through shared tokens rather than scattered hard-coded colors.

At minimum the system should be able to represent:

```text
surface.canvas
surface.panel
surface.elevated
text.primary
text.secondary
text.muted
border.default
border.strong
accent
status.running
status.completed
status.failed
status.cancelled
status.warning
chart.price
chart.feature
chart.score
chart.entry
chart.exit
```

Exact token names can differ in implementation.

The architecture should allow `System`, `Light`, and `Dark` modes even if Dark receives the most visual tuning first.

## 11. Frontend package boundaries

The current Web source tree should evolve toward feature ownership rather than one giant components directory.

A target shape is:

```text
app/
    shell/
    router/
    providers/
    theme/

features/
    research/
        new/
        runs/
        results/

domain/
    research/

api/
    research/

components/
    workspace/
    inspector/
    table/
    chart/
    form/

shared/
```

Responsibilities:

```text
Feature → owns workflow and page composition
Domain  → owns admitted client-side value models/projections
API     → owns transport clients and DTO admission
Shared  → owns reusable presentation primitives
```

Do not create a second client semantic model that competes with the canonical server contracts.

## 12. Future product growth

The shell is deliberately compatible with later product domains:

```text
Research Workspace
Backtest Workspace
Sim Workspace
Live Workspace
```

This is only an information architecture capability. It does not imply those products are implemented or certified.

A future Mission Control/Home page becomes useful only after several products have meaningful, evidence-backed surfaces. P8.4 should not manufacture a dashboard full of placeholders simply to make the application appear larger.

Command Palette/keyboard-first navigation may also be added later, for example to open Research, Run, Result, Dataset, or system views. It is not a P8.4 semantic prerequisite.

## 13. Frozen vs adaptable decisions

### Frozen by ADR 0092

The following require an explicit architecture decision to reverse:

- Scientific Quant Workstation product identity;
- persistent workstation shell concept;
- product-domain navigation rather than backend-entity navigation;
- Research primary workflow `New Research / Runs / Results`;
- structured Builder rather than raw JSON as normal Research authoring authority;
- browser = Control + Presentation, never Research Semantic Authority;
- scientific Result views consume Result/Artifact/Query evidence rather than reconstructing truth from internal stores;
- Runs show authoritative operational facts and do not manufacture progress;
- contextual Inspector as a stable workstation concept;
- desktop-first responsive policy without mandatory mobile feature parity;
- URL-owned shareable page selection where practical.

### Adaptable without a new ADR

These can change through normal product implementation and review:

- exact rail/Inspector width;
- spacing and radius values;
- exact fonts;
- accent color;
- exact tab wording;
- button placement;
- animation details;
- whether the Inspector is a drawer at a particular breakpoint;
- exact component library;
- exact command-palette implementation;
- exact table/chart library, provided authority boundaries remain intact.

## 14. P8.4 implementation guidance

P8.4 should not start by drawing all final screens against ad-hoc JSON. The recommended sequence is:

```text
1. Freeze/implement Research Studio semantic product contracts
2. Add discovery/read contracts needed by structured authoring
3. Implement New Research + Runs on the formal contracts
4. Evolve Result/Artifact/Query evidence for scientific views
5. Expand Results workspace only as evidence becomes available
```

Every UI feature should be traceable to one of three ownership classes:

```text
User intent owned by a formal versioned product/domain contract
Operational fact owned by Research Run/PostgreSQL operational authority
Scientific fact owned by immutable Result/Artifact authorities
```

If ownership cannot be identified, the feature is not ready to implement.
