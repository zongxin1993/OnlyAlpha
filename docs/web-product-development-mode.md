# Web Product Development Mode

This document defines the default execution method for OnlyAlpha Web productization after the foundational Kernel, Research, Backtest and
Product API capabilities exist. ADR 0135 owns the architectural decision; this document is the working playbook.

## 1. Goal

Build OnlyAlpha as a coherent operator product by completing one user-visible workflow at a time.

The product development unit is not:

~~~text
backend module
API endpoint
React page
database table
~~~

It is:

~~~text
one complete user goal
→ formal product boundary
→ observable browser behavior
~~~

The Web is therefore both a client and a pressure test for Domain, API, lifecycle and state design.

## 2. Product reference model

Use TradingView Supercharts as the primary interaction reference for the chart-centric workstation:

~~~text
symbol
timeframe
chart
indicator / factor
drawing
watchlist / details
replay
research
backtest
orders / positions
alerts
screening
multi-chart
~~~

OnlyAlpha does not attempt to clone every TradingView product. Community, social, Pine ecosystem, proprietary assets and unrelated
features are outside the reference contract unless separately required.

The target is:

~~~text
proven chart-centric interaction model
+
OnlyAlpha Research / Backtest / SIM / LIVE authorities
~~~

## 3. Mandatory development loop

Every normal product slice follows:

~~~text
1. Reference
   What proven interaction are we using or deliberately rejecting?

2. User Goal
   What can the operator accomplish after this slice?

3. Observable Behavior
   What is visible, clickable, editable, loading, empty, failed or degraded?

4. UI/Product Slice
   Build or define the interaction without inventing backend semantics.

5. Gap Analysis
   What exact Product Query / Command / projection already exists?
   What exact capability is missing?

6. Minimal Canonical Backend
   Reuse current capability first.
   Add only the smallest complete missing Authority/API capability.

7. Formal Integration
   Web uses the versioned Product API / generated client.
   No direct DB/store/internal-Core path.

8. E2E
   Exercise the main user workflow through a real browser path.

9. Dogfood / Review
   Use the feature as an operator and identify workflow/API/domain friction.

10. Close or Repair
   Close only when the workflow is actually usable.
   Otherwise fix the model before expanding breadth.
~~~

## 4. Product Slice Contract

Before implementing a Web product slice, the active Task Contract should additionally state:

~~~text
Product Slice
Reference Interaction
User Goal
Primary User Flow
Visible States
Existing Product API
Missing Product API / Authority Capability
E2E Acceptance
Out of Scope
~~~

### Product Slice

One bounded operator capability, for example:

~~~text
Symbol + historical/realtime chart
Add Momentum factor to current chart
Run Research from selected chart context
Backtest one frozen Strategy Revision and overlay trades
Observe SIM position and orders on chart
~~~

Avoid slices such as:

~~~text
Improve Web
Finish Research UI
Build trading backend
Add all alerts
~~~

because they do not define an observable closure boundary.

### Reference Interaction

Record which interaction pattern is being used and what OnlyAlpha intentionally changes.

Reference does not create product Authority. It is UX evidence.

### Visible States

At minimum consider:

~~~text
loading
ready
empty
invalid input
permission denied
backend unavailable
degraded / stale where relevant
retry/recovery where relevant
~~~

Do not design only the happy path.

### Existing Product API

List the exact formal Queries/Commands/projections already available. Prefer reuse.

### Missing Product API / Authority Capability

If the UI needs something that does not exist, classify the gap before coding:

~~~text
PRESENTATION_GAP
QUERY_GAP
COMMAND_GAP
DOMAIN_GAP
AUTHORITY_GAP
INFRASTRUCTURE_GAP
~~~

A UI inconvenience is not automatically a reason to create a new Authority.

## 5. Default product sequence

The following is the preferred productization sequence. It is direction, not implementation status, and must not be used as proof that a
capability exists.

~~~text
W0  Workspace shell
    chart-centric layout, product controls, panels, responsive desktop baseline

W1  Symbol + K-line + realtime
    search/switch instrument, historical bars, realtime update, loading/recovery states

W2  Core chart interaction
    timeframe, chart type, crosshair, zoom/pan, viewport/history loading

W3  Indicator / Factor
    catalog search, parameters, overlay/pane, exact identity and errors

W4  Watchlist
    lists, add/remove/reorder, quote state, symbol-to-chart navigation

W5  Drawing tools
    only after a renderer/interaction path is explicitly supported

W6  Research on chart
    create/resolve/run Research from chart context; inspect exact evidence

W7  Strategy + Backtest
    frozen Strategy Revision, backtest intent, result, trade/signal overlays, evidence

W8  Replay
    deterministic historical event/bar replay appropriate to supported data contracts

W9  Orders / Positions / SIM / LIVE surfaces
    only for formally implemented Runtime/Broker capability and explicit execution permission

W10 Alerts
    user-defined observable conditions with durable lifecycle if formalized

W11 Screener
    cross-sectional discovery over formal data/query capability

W12 Multi-chart workspace
    synchronized or independent chart contexts without duplicating semantic authority
~~~

The owner may reorder slices. Reordering does not change the development method.

## 6. Backend implementation rule

During productization:

~~~text
needed by active slice
→ implement minimum complete canonical capability

not needed by active slice
→ do not build speculatively
~~~

This does not block independently necessary work for:

- data integrity;
- Authority correctness;
- security;
- deterministic identity;
- persistence/recovery/reconciliation;
- production safety;
- CI/quality infrastructure;
- an explicitly approved non-Web roadmap unit.

## 7. Web Authority rules

Permanent rules:

~~~text
Web = Control + Presentation
Web != Research Authority
Web != Trading Authority
Web != Runtime Authority
Web != Persistence Authority
~~~

Allowed:

- product navigation;
- temporary incomplete form/draft state;
- presentation sorting/filtering/layout;
- chart viewport and visible series state;
- submitting formal Commands;
- reading formal Query projections.

Forbidden:

- direct database writes;
- reconstructing scientific truth from internal stores;
- calculating authoritative Factor/Signal/IC/RankIC in the browser;
- changing Strategy/Run/Promotion state without a formal Command;
- inferring unavailable durable progress and presenting it as fact.

## 8. E2E closure

For a normal Web vertical slice, browser E2E should prove the main path wherever the environment is reasonably automatable.

A slice is not closed by:

~~~text
API returns 200
component renders
unit tests pass
~~~

alone.

Closure should prove:

~~~text
operator intent
→ browser action
→ formal Product API
→ canonical application behavior
→ authoritative result/state
→ browser projection
~~~

Risk-specific backend tests remain required when the slice changes correctness-sensitive behavior.

## 9. Design and finish quality

OnlyAlpha keeps its existing product direction:

- desktop-first and responsive;
- professional and low-decoration;
- high information density without visual clutter;
- thin boundaries and restrained status color;
- chart/data-first rather than dashboard-card-first;
- exact identity/evidence available without dominating the primary workflow.

For design-sensitive changes, existing repository design tooling and surface briefs remain applicable. Product-driven development does not
mean accepting lower visual quality; it means judging visual quality inside a real user workflow.

## 10. Relationship to existing Web implementation

The existing P8.4 Research Studio is implementation truth and reusable code, not the permanent future navigation contract.

Reuse it when it fits:

~~~text
Research Builder
Run list/detail
Result/evidence views
Inspectors
visualization adapters
generated API client
~~~

Move, reduce or replace its page organization when a chart-centric slice proves a better product workflow.

Under ADR 0130, unpublished internal Web/API structure does not require compatibility preservation unless explicitly frozen. Current
canonical correctness, identity, evidence and Authority rules remain mandatory.

## 11. Stop condition for each slice

Stop the slice when:

~~~text
user goal works end to end
AND formal Authority/API boundaries are preserved
AND required visible states are intentional
AND targeted tests pass
AND required browser E2E passes
AND no Critical/High finding remains in the real impact scope
~~~

Then return to product use and choose the next slice. Do not automatically continue into the next W-stage.
