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

### Interface research and presentation discipline

AGENTS.md §3.3.2 governs every new or changed user-facing interface. Before implementation, inspect actual relevant quantitative /
financial product screens, official screenshots or interaction demonstrations. Use references matched to the task: TradingView for
chart/watchlist interaction, QuantConnect for research/backtest organization, and the owner's selected conversation reference for
chat research. Reuse applicable prior research. Record sources, observed layout and actions, information hierarchy, adopted/rejected
patterns and their OnlyAlpha application in the active task context; do not create another progress or acceptance report. If visual
evidence is unavailable, disclose that gap instead of claiming that documentation-only research proves the interface.

Default screens expose the current user's task, meaningful financial/quantitative information, state and next action. Put connection
and model configuration in settings. Keep advanced options, code, logs, schemas and exact diagnostic identities behind discoverable
details. Use natural language and ordinary quantitative vocabulary, not internal type names, fingerprints, revision hashes, leases,
raw exception messages or error codes. An internal word translated literally is not necessarily understandable product copy.

Errors explain what happened, whether the requested action took effect and how to continue. An unconfirmed result stays visibly
unconfirmed and offers observation of the original operation; it never becomes a generic failure with a blind retry. Concision must
preserve relevant source/sample conditions, costs and limits, permission scope, risks, confirmation subjects and irreversible effects.
OnlyAlpha authorities retain exact identity and provenance; presentation simplification changes no safety or correctness semantics.

Validate hierarchy, readable typography, spacing, alignment, scrolling, narrow screens, keyboard/focus and natural copy in the real
Shipping Web flow. A rendered component or a green test suite alone cannot establish usability.

### Reuse mature components and confirm feature choices

AGENTS.md §3.4.1 requires active web research and owner confirmation before selecting or implementing each new feature.
Evaluate existing project components first, then mature third-party UI components and established projects / platform tools for
generic capabilities such as user management, authentication, release version management and deployment. Do not rebuild their
internals when they already meet the current need. Native / standard-library capabilities remain preferred where sufficient.

Bring a sourced comparison and a concrete recommendation to the owner: requirement coverage, boundary fit, maintenance maturity,
license, security/privacy, stack compatibility, integration and ongoing cost, and the minimum OnlyAlpha-specific work. UI research
also inspects actual screens under §3.3.2. Research is bounded to the feature and its real impact; unavailable sources are a gap,
not a completed selection. Previously approved scope/choices need no repeat approval; new features and material selection changes
need explicit confirmation before implementation, dependency installation or service introduction. Custom implementation requires
evidence that existing capabilities and mature alternatives cannot satisfy the necessary requirements, and owner confirmation.

Reuse never transfers OnlyAlpha business authority to a component or platform: authentication does not confer business or LIVE
authorization, and deployment/release tooling cannot redefine semantic versions, fact identities or Runtime Generation. Preserve
formal API boundaries, permissions, deterministic behavior, recovery, traceability and fail-closed semantics. Integrate only what
the current workflow needs; this rule neither requires a heavyweight platform nor authorizes a repository-wide replacement effort.

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

### 8.1 One business acceptance surface: Shipping Web UI

`AGENTS.md` §3.3.1 owns the mandatory acceptance rule. All business product testing,
verification and acceptance use the normal Shipping Web UI workflow, exactly as an
ordinary operator uses it. The browser is the **only user-action entry point for
business acceptance**, not the only engineering test layer and not a new Authority.

Start at the normal product entry, use discoverable navigation and controls, enter
the same user inputs, and observe the same visible results, errors and recovery.
Do not replace a user step with a direct API call, database seed, SDK/Python action,
injected React/browser state, hidden test button, fixture-only page or test shortcut.
If a supported normal deep link is the user's intended entry, exercise that same
entry; a test-only route is not equivalent. Accessibility/test locators may identify
real controls without creating special product behavior.

Normal UI → formal Product API → canonical Authority → UI projection must be real.
Mocked API responses, a controlled renderer/backend fixture, precomputed results,
component tests and endpoint PASS remain technical evidence only. They do not certify
that an operator can complete the business workflow. Controlled external payloads
and hermetic data remain valid inputs when they reach the real owning application;
they never certify current market freshness, a real account or deployment transport.

Preparation may establish the task's explicit existing conditions, such as an
admitted dataset or initialized isolated environment. It must not silently perform
an operation within the user's goal. For example, a source-management slice must
create/configure/publish through its real UI; pre-seeding that Source and testing only
the final screen cannot close that slice. Infrastructure provisioning, deterministic
Kernel tests and safety diagnostics keep their own entry points and evidence scope.

When the UI cannot express a required action, record the concrete presentation,
Query, Command, Domain, Authority or Infrastructure gap and leave product acceptance
open. Do not certify the workflow from endpoint availability or weaken backend checks.
This rule does not retroactively promote earlier fixture PASS into product evidence.

### 8.2 User convenience and workflow parity

Define acceptance from the user's goal, not from an implementation checklist:

- The entry and next action are discoverable without developer knowledge.
- Defaults reduce unnecessary input but do not grant implicit permission.
- Labels explain user concepts; normal operation does not require internal IDs,
  database queries, console scripts or switching to engineering tools.
- Each meaningful operation has visible loading, success and actionable failure;
  empty, stale/degraded and permission-denied states are not disguised as ready.
- Corrections, cancellation and supported recovery stay in the normal UI; UNKNOWN
  remains explicit and never becomes an automatic/blind resubmission.
- Keyboard/focus behavior and the slice's declared viewports remain usable.
- The active Task Contract states the ordinary steps, necessary inputs, visible
  feedback and evidence-based interaction/latency budgets. Dogfooding uses this
  exact path; minimum clicks or a green automation run alone do not prove usability.

Kernel validation remains centered on deterministic transitions, unique identity
and Authority, integrity, traceability, recovery and fail-closed behavior. Frontend
unit/contract/renderer/security regressions also remain required where impacted;
neither layer substitutes for the business UI acceptance above.

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
