# ADR 0092: Web Scientific Workstation and Browser Authority Boundary

- Status: Accepted
- Date: 2026-08-18
- Related: ADR 0085, 0088, 0089, 0090, 0091; P8.4 Research Studio Web

## Context

P7 established the immutable Research Result / Artifact read plane and a read-only browser consumer. P8.0-P8.3 established strict Research Specification, durable Research Run authority, PostgreSQL operational state, reliable Scheduler/Worker execution, and the Research Command API. P8.4 now introduces the first daily-use Web-native Research product surface.

If UI implementation starts from whatever backend endpoints already exist, the browser can accidentally become a second Research semantic plane, product navigation can mirror internal packages instead of user workflows, and later Backtest/Sim/Live productization can force a second application shell. These are structural sources of expensive UI/API/Domain rework.

The Web product therefore needs an explicit long-lived product and authority contract before P8.4 page implementation.

## Decision

### Product identity

OnlyAlpha Web is a **Scientific Quant Workstation**. It is not a generic administration console, a collection of unrelated dashboards, a broker-terminal clone, or a Web IDE.

The primary product workflow is:

```text
Define
→ Run
→ Observe
→ Analyze
→ Compare
→ Iterate
```

Pages and navigation are organized around user product workflows, not backend entities or package names.

### Persistent workstation shell

Desktop Web uses one persistent application shell with these conceptual regions:

```text
Global Product Rail
+
Product Workspace Navigation
+
Central Workspace
+
Contextual Inspector
+
Status Surface
```

The Global Product Rail represents only top-level product domains. Internal entities such as Dataset, Calculation, Statistics, Artifact, Run Attempt, Worker, Scheduler, Store, or migration tables do not become top-level navigation merely because they exist in the backend.

The shell is intended to remain reusable when Backtest, Sim, and Live receive formal Web product surfaces. Those future products must not be pre-declared as completed capabilities merely because the shell can represent them.

### Research product information architecture

The first Research product structure is:

```text
Research
├── New Research
├── Runs
└── Results
```

`New Research` is a structured Research Builder. `Runs` is a durable operational console. `Results` is a scientific Research workspace over exact immutable evidence.

### Builder, not wizard or JSON editor

Research authoring uses a structured builder that expresses user intent such as Universe, time selection, registered Calculation/Indicator/Factor choices, Eligibility, Entry/Exit Decision expressions, Target, and Statistics.

The required direction is:

```text
User Intent
→ Structured Builder
→ Formal versioned Domain/Product Contract
→ Exact Research Specification
→ Existing deterministic resolution/execution path
```

The browser must not invent a private Research JSON language. Canonical Research Specification may be shown as a read-only advanced view, but editable raw JSON is not the primary authoring authority and must not require bidirectional synchronization with the builder.

### Browser authority boundary

The browser is always:

```text
Control + Presentation Client
```

and never:

```text
Research Semantic Authority
```

The browser may perform presentation-only operations such as layout, sorting visible rows, display filtering, formatting, chart zoom/pan, selected tab, column visibility, series visibility, and explicitly lossy plotting projection.

The browser must not create or replace authoritative Factor Score, Feature value, Signal, Eligibility result, Target, IC/RankIC, Statistics, candidate ranking, Research Result, or Artifact truth. If a scientific visualization needs evidence that current Result/Artifact contracts do not expose, the authoritative Result/Artifact/Query contract must evolve rather than moving semantic computation into React.

### Immutable Result read boundary

Scientific Result pages consume verified Result/Artifact-derived read models. The browser must not bypass the Research Result/Artifact boundary by independently reading Dataset, Calculation Store, Statistics Store, Parquet paths, or internal storage and reconstructing a new Research truth.

The target direction remains:

```text
Research Result
→ Verified / Portable Artifact
→ Read Model
→ Query API
→ Browser
```

### Operational truth in Runs

Run pages display only facts owned by the durable operational authority. They may show `QUEUED`, `RUNNING`, `CANCEL_REQUESTED`, `COMPLETED`, `FAILED`, and `CANCELLED` plus exact stored metadata/references.

The Web must not manufacture a percentage progress bar or inferred semantic phase when no authoritative progress fact exists.

### URL and client state

Shareable/refreshable product selection belongs in the URL whenever practical, including Run identity, Result identity, Statistics identity, and comparable page-level selections.

Local browser state is limited to disposable presentation preferences such as inspector open/closed state, selected visual tab, theme, panel sizing, chart viewport, or column layout. React memory/cache must not be the only authority for durable Research Definition, Run state, Result, or Artifact facts.

### Contextual Inspector

The right-side Inspector is a stable workstation concept rather than a page-specific decoration. Its content changes by context:

- New Research: definition summary, validation, dataset resolution, exact Specification/identity;
- Runs: state, timestamps, failure, result/artifact references, diagnostics appropriate to the current public contract;
- Results: dataset/result/artifact identity and selected scientific context.

The Inspector may be collapsed and its presentation preference may be persisted locally, but it never owns semantic truth.

### Responsive product policy

OnlyAlpha Web is desktop-first and responsive, not feature-identical at every viewport.

Desktop supports the full workstation and Research authoring experience. Tablet may collapse the Inspector into a drawer. Mobile prioritizes Run observation, Results, and basic scientific consumption; full complex Research authoring is not a P8.4 requirement.

### Visual system

The visual direction is professional, dense, scientific, and low-decoration. Data surfaces favor high information density, stable numeric alignment, thin boundaries, restrained status color, and design tokens. UI/navigation typography and quantitative data/identity typography may use different roles.

Theme/color/spacing values are implementation details, but components must not depend on scattered hard-coded theme colors that prevent later Light/Dark/System support.

## Consequences

- P8.4 Domain/API work is derived from explicit user Research intent rather than from arbitrary React state or existing endpoint shapes.
- Product navigation remains stable as internal architecture evolves.
- Backtest/Sim/Live can later enter the same workstation shell without forcing a second Web architecture.
- Missing scientific evidence becomes a Result/Artifact/Query contract problem, not an excuse for browser-side semantic recomputation.
- Research Builder, Runs, and Results can evolve independently while sharing one interaction model: product navigation → central workspace → contextual inspector.
- P8.4 implementation may change exact widths, spacing, typography, tab labels, or component placement without superseding this ADR, provided the product/authority contracts remain intact.

## Rejected alternatives and non-goals

Rejected:

- backend-package/entity navigation as the primary information architecture;
- a large permanent sidebar containing every Dataset/Calculation/Statistics/Worker/Store concept;
- a multi-step wizard as the only Research authoring model;
- raw JSON as the normal Research builder authority;
- browser-side recomputation of Research semantics from upstream stores;
- inferred/fake Run progress percentages;
- dashboard-card proliferation as the main Research product surface;
- P8.4 building an embedded IDE, production code admission, or LLM-controlled Research semantic authority;
- requiring full complex Research authoring on mobile;
- copying terminal visual effects such as CRT/scanline/HUD decoration as an architectural requirement.

## Validation

P8.4 implementation reviews must verify at least:

1. Research product navigation remains `New Research / Runs / Results` unless a later accepted ADR changes it.
2. New Research state has a formal path to a versioned Domain/Product contract and exact Specification; no private UI-only semantic language becomes authoritative.
3. Run screens expose only durable operational facts and do not invent progress.
4. Scientific charts/tables can trace displayed semantic values to Result/Artifact/Query evidence.
5. Browser code contains no new authoritative Factor/Statistics/Signal/Candidate calculation path.
6. shareable page identity is represented by routes/URL where practical, while local state stays presentation-only.
7. responsive behavior preserves the workstation model without requiring feature parity on mobile.
