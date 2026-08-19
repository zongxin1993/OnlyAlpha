# P8.4 Research Studio Architecture

> Status: **P8.4.0 Foundation Implemented / Verified Locally; later P8.4 increments remain Target Design**
>
> This document refines the P8.4 direction from `docs/roadmap.md`, `docs/web-product-architecture.md`, ADR 0092, ADR 0093, and ADR 0094. It does not claim P8.4 is implemented. Exact class/file names may change during implementation, but authority boundaries, semantic roles, and exit conditions described here require explicit review to change.

P8.4.0 repository fact: `onlyalpha.research.definition` now owns the strict Definition V1 contract and deterministic resolution into the existing
Specification/Workload path. Boolean lowering uses a narrow internal `OnlyCalculationKind.PREDICATE` with RESEARCH-only registrations, the existing
Calculation Registry/Graph/Executor/Result authority, and explicit Eligibility/Entry/Exit terminals. No Predicate Runtime, Predicate Store, Web/API,
Artifact evidence expansion, or Trading backend was introduced. “Verified locally” is an increment-level affected-test statement, not P8 certification.

## 1. P8.4 objective

P8.4 is not “build React screens for P8.3”. It is the first Web-native product layer that lets a user express research intent in product terms and deterministically lower that intent into the existing exact Research execution path.

Target chain:

```text
User Research Intent
        ↓
Structured Research Builder
        ↓
OnlyResearchDefinition
        ↓
Definition Resolution
        ↓
Exact Dataset Snapshot
+
Exact Candidate Space
+
Exact Decision/Calculation Graph
+
Exact Targets / Statistics
        ↓
OnlyResearchSpecification
        ↓
Existing Specification Resolver
        ↓
OnlyResearchWorkloadPlan
        ↓
P8.3 Research Command API
        ↓
Run / Scheduler / Worker
        ↓
OnlyEngine → OnlyResearchRuntime
        ↓
Immutable Result / Artifact
        ↓
Query API
        ↓
Scientific Workstation
```

The new Web path is a product input path, not a second Research semantic plane.

## 2. Primary architecture rule

P8.4 introduces a formal authoring contract above the current execution-level Specification:

```text
Research Definition
→ what the researcher wants

Research Specification
→ exactly what OnlyAlpha executes

Research Workload
→ runtime composition contract
```

The browser must not translate private React JSON ad hoc into Calculation Graphs or Workloads.

The server/domain resolver owns the deterministic lowering.

## 3. Product information architecture

Research remains:

```text
Research
├── New Research
├── Runs
└── Results
```

The user loop is:

```text
Define
→ Validate / Resolve
→ Run
→ Observe
→ Analyze
→ Compare
→ Iterate
```

New Research is a **Builder, not a wizard and not a node editor**.

Frozen Builder sections:

```text
1. Universe & Data
2. Calculations
3. Eligibility
4. Signals
   ├── Entry Signal
   └── Exit Signal
5. Targets
6. Statistics
```

The same work context remains revisitable; sections may collapse but are not a one-way wizard.

## 4. Research Definition V1

Conceptual top-level model:

```text
OnlyResearchDefinition
├── universe
├── calculations[]
├── eligibility?
├── signals
│   ├── entry?
│   └── exit?
├── targets[1..N]
└── statistics[]
```

The contract must be:

```text
immutable
versioned
strict
canonical
serializable
fingerprintable
unknown-field fail-closed
```

Display names, panel state, colors, graph positions, selected UI tabs, and other presentation metadata do not participate in semantic identity unless a later ADR explicitly promotes them to domain facts.

## 5. Universe and Dataset resolution

Formal user selection types:

```text
SingleInstrument
ExplicitInstrumentSet / RegisteredPool
RegisteredUniverse
```

“Full market” is represented by a registered Universe such as `CN_A_SHARE_ALL`, not a fourth fundamental type.

User-facing selection combines:

```text
Universe
+
Time Range
+
Bar/Frequency
+
Source / registered source policy
+
Adjustment when applicable
```

Resolution direction:

```text
Universe Selection
→ exact instrument set
→ existing OnlyResearchDatasetDefinition
→ verified immutable Dataset Snapshot
```

The Definition stores user intent; exact Research execution consumes the resolved Dataset Snapshot fingerprint.

P8.4.0 must not become a Historical Data Platform. If required exact data cannot be resolved through the admitted Dataset authority, resolution fails explicitly rather than silently downloading/mutating data as a hidden side effect.

Useful resolution states for product/API projection are conceptually:

```text
UNRESOLVED
RESOLVABLE
RESOLVED
INVALID
```

Exact names are adaptable.

## 6. Calculation Instance model

The user does not edit Calculation Graph nodes directly. The user declares reusable Calculation Instances derived from registered semantic Calculation Definitions.

```text
Registered Calculation Definition
        ↓
Calculation Instance
        ↓
Typed Parameters
        ↓
Published Outputs
        ↓
Eligibility / Signals / Statistics
```

Conceptual fields:

```text
instance_key
exact calculation type reference
parameter bindings
allowed configurable input bindings where the registered Definition exposes them
published outputs
primary output for UX default when appropriate
```

`instance_key` is the stable Definition-local semantic reference, for example:

```text
rsi_fast
rsi_slow
momentum
```

Display name is not semantic identity.

```text
display_name != instance_key
```

## 7. Catalog authority

The existing Calculation Registry remains the semantic Calculation authority.

P8.4 must not create a second registry for RSI/MACD/Factor parameter schemas.

The product/discovery layer may project authoring metadata such as:

```text
title
description
category
authoring visibility
recommended presentation mode
```

but this metadata must not mutate Calculation semantic identity.

The browser must not hard-code the authoritative parameter schema for registered Calculations.

## 8. Parameter model

Every authorable parameter is one of:

```text
Fixed(value)
Sweep(finite explicit values)
```

Formal semantic Sweep values are finite and exact. A Web convenience editor may accept `start / stop / step`, but server/domain resolution must canonicalize that input into an explicit finite value set before it participates in exact identity.

Recommended V1 constraints:

```text
Fixed
→ exactly one normalized value

Sweep
→ at least two distinct normalized values
```

Sweep order is not semantic identity. Equivalent sets must canonicalize to the same representation.

P8.4 V1 supports finite Cartesian Product only.

Not P8.4 V1:

```text
zip sweep
conditional sweep
dependent sweep
random search
Bayesian optimization
adaptive optimization
```

## 9. Published Outputs and logical variable references

Only explicitly published Calculation outputs may enter downstream Research product semantics and later Artifact evidence.

Conceptually:

```text
Indicator
→ 1..N Published Features
→ optional Primary Feature as UX default

Factor
→ 1..N Published Scores/outputs
→ optional Primary Score as UX default
```

Internal temporary Calculation outputs do not leak into the Web reference vocabulary.

Downstream references are logical and Definition-local:

```text
rsi_fast.value
momentum.score
```

The authoring model must not require the browser to know:

```text
node_fingerprint
calculation_fingerprint
```

Those are resolution results.

A typed `ResearchVariableRef`-style abstraction may expose semantic roles such as:

```text
FEATURE
SCORE
ELIGIBILITY
ENTRY_SIGNAL
EXIT_SIGNAL
TARGET
```

Role vocabulary may be split into narrower domain types if implementation clarity is better; the invariant is that roles remain explicit.

## 10. Global Candidate Space

Current P8.0 Specification Sweep behavior expands Calculations independently. P8.4 authoring requires a Definition-level Research candidate model when multiple Calculation parameters are swept together.

Example:

```text
RSI.period      = [7, 14, 21]
Momentum.window = [10, 20]
```

Target candidate space:

```text
3 × 2 = 6 Research Candidates
```

The global candidate assignment is the exact binding of all swept dimensions for one Research candidate.

Signals and other downstream candidate-relative facts bind to that same global assignment.

A preferred implementation direction is a candidate Decision/Calculation Graph Template whose sweep dimensions belong to one composed graph so the existing graph/sweep materialization machinery can produce exact candidate-relative topology without a second join system.

## 11. Candidate identity

A candidate is not merely a tuple such as `period=14, window=20` detached from context.

Candidate identity belongs to an exact resolved Research context and should be derived from canonical evidence such as:

```text
candidate schema/version
resolved Research/Definition identity
exact Dataset Snapshot identity when required by the chosen identity model
canonical global parameter assignment
```

The final exact formula must be frozen by implementation ADR/tests, but two requirements are non-negotiable:

1. deterministic equivalent input produces the same candidate identity;
2. semantically different Research contexts must not accidentally collapse into one candidate merely because parameter values match.

## 12. Eligibility, Entry, and Exit

Product semantics:

```text
Eligibility
→ whether an observation/instrument qualifies

Entry Signal
→ entry/buy research condition is true

Exit Signal
→ exit/sell research condition is true
```

Research signals are not Orders.

```text
ENTRY_SIGNAL
!= BUY Order

EXIT_SIGNAL
!= SELL Order
```

Research records these facts. Backtest/Sim/Live may later consume the same signal through trading policy and the Trading Kernel.

Eligibility is not automatically combined with Entry/Exit by the compiler.

## 13. Boolean expression grammar

First version expression AST:

```text
AND
OR
NOT
Comparison
```

Comparison operators:

```text
==
!=
<
<=
>
>=
```

Operands:

```text
DatasetFieldRef
Published ResearchVariableRef
TypedLiteral
```

Type admission is strict. A suggested conservative V1 policy:

```text
DECIMAL / INTEGER
→ equality + ordering

STRING
→ equality / inequality

BOOLEAN
→ equality / inequality
```

No implicit arbitrary string/number coercion.

No arbitrary Python/JavaScript expression evaluation.

## 14. Boolean AST canonicalization

Canonical identity must not depend on cosmetic Builder ordering.

For commutative associative operators such as AND/OR, implementation should normalize structure so equivalent expressions such as:

```text
A AND B
B AND A
(A AND B) AND C
A AND (B AND C)
```

can converge to one canonical semantic representation where safe.

P8.4.0 does not need a general Boolean optimizer. Structural canonicalization is sufficient; algebraic rewrites such as constant folding and global common-subexpression optimization are not required unless later profiling justifies them.

## 15. Expression lowering and Decision Graph

The AST is not executed by React and does not create a new Predicate Runtime.

Required direction:

```text
Eligibility / Entry / Exit AST
        ↓
Canonicalization
        ↓
Semantic Type Admission
        ↓
Deterministic Lowering
        ↓
Internal Calculation Graph primitives
        ↓
Role-bearing terminal
        ↓
Existing Calculation execution infrastructure
```

Representative rule:

```text
RSI.value < 30
AND
Momentum.score > 0
```

lowers conceptually to:

```text
RSI ───────────────→ LT 30 ──┐
                              AND → ENTRY_SIGNAL
Momentum.score ────→ GT 0 ───┘
```

Primitive nodes are compiler/runtime internals, not normal catalog authoring items.

If a truthful Boolean semantic requires a new narrow Calculation kind such as `PREDICATE`, it must still reuse Calculation Definition/Registry/backend/executor/identity infrastructure. Do not create `PredicateEngine`, `PredicateStore`, or a second recovery system.

## 16. Signal execution semantics

For Research, the exact meaning of:

```text
if RSI < 30 and Momentum.score > 0:
    emit entry signal
```

is naturally represented as an authoritative Boolean series:

```text
ENTRY_SIGNAL[t] = condition[t]
```

Research may calculate the whole series using vectorized/batch Arrow operations.

A future incremental Trading execution may evaluate the same semantic graph as events arrive.

The semantic contract is invariant; only the execution strategy differs.

## 17. Decision Graph and cross-Runtime reuse

The reusable long-term decision semantic is:

```text
Calculations
+
Eligibility
+
Entry Signal
+
Exit Signal
```

Research adds scientific evaluation around it:

```text
Universe / Dataset
+
Decision Graph
+
Candidate Sweep
+
Targets
+
Statistics
```

A future Backtest adds trading policy around the same exact decision semantics:

```text
Historical Dataset
+
Exact Decision Graph
+
Portfolio / Position Policy
+
Sizing / Risk
+
Execution Profile
+
Virtual Broker
```

SIM/LIVE reuse the same decision semantics with realtime data and appropriate broker/execution permissions.

Target execution taxonomy:

```text
RESEARCH
→ batch / vectorized

BACKTEST
→ historical incremental / event-driven

SIM
→ realtime incremental / event-driven

LIVE
→ realtime incremental / event-driven
```

The same admitted observations and exact decision semantics must produce equivalent shared outputs. Vectorization is an optimization, not a different strategy algorithm.

Shared Decision semantics must be causal; future-looking Targets remain Research evaluation semantics and are not valid dependencies for a decision intended to be promoted toward realtime trading.

## 18. Targets

Research Definition supports `1..N` explicit Target Instances.

Example:

```text
forward_return_5d
forward_return_20d
```

P8.4 V1 does not make Target itself sweepable. Multiple horizons are multiple explicit Target Instances, not a hidden Target Sweep.

A Primary Target may exist for UI default selection only; Statistics bindings remain explicit.

## 19. Statistics

Long-term product direction is broader than the current execution contract:

```text
Research Variable
× Target
× Statistic
```

where a Research Variable may eventually include:

```text
Feature
Factor Score
Entry Signal
Exit Signal
```

However P8.4 must not pretend unsupported Statistics exist.

Current admitted execution capabilities such as IC/RankIC remain authoritative. If a Signal × Target statistic is not implemented, resolution returns a typed incompatibility rather than calculating it in Web/ECharts.

Catalog/discovery should expose capability/compatibility with reasons where practical.

## 20. Definition Resolution result

Conceptual `OnlyResearchDefinitionResolution` should provide enough exact evidence for Web validation and P8.3 submission:

```text
definition_fingerprint
resolved_dataset
candidate_space
resolved/published variables
exact Research Specification
specification_fingerprint
OnlyResearchWorkloadPlan or equivalent exact workload evidence
structured validation diagnostics
```

Resolution is deterministic evidence, not a new mutable database authority.

## 21. Validation lifecycle in Web

Recommended UI lifecycle:

```text
DIRTY
→ RESOLVING
→ VALID / INVALID
→ SUBMITTING
→ ACCEPTED
```

Any semantic edit after successful resolution returns the Builder to `DIRTY`.

Run is enabled only for the exact unchanged authoritative resolution being submitted.

Validation and durable Run submission remain separate concepts.

## 22. Discovery and Resolution API boundary

P8.4 should keep distinct API responsibilities rather than one God client/service.

Conceptual boundaries:

```text
ResearchDiscoveryApi
→ registered Universe / Calculation / Target / Statistics authoring metadata

ResearchDefinitionApi
→ resolve/validate Definition into exact Dataset/Candidates/Specification

ResearchCommandApi
→ existing durable Run submit/read/list/cancel

ResearchArtifactApi
→ immutable Result/Artifact scientific read plane
```

A shared HTTP transport is fine; semantic ownership stays separated.

A target Definition resolution endpoint is conceptually:

```text
POST /api/v2/research/definitions/resolve
```

Exact URL and DTO are implementation details until frozen by API contract tests.

## 23. Scientific Result evidence requirement

The current Artifact/Query plane is sufficient for existing Statistics evidence but not all target Studio views.

P8.4 must extend immutable evidence before displaying unsupported semantic facts.

Long-term Studio Artifact evidence should be able to prove:

```text
Market Evidence
→ exact required OHLCV/time-series subset

Variable Evidence
→ published Features / Scores / Targets only

Signal Evidence
→ candidate / instrument / time / eligibility / entry / exit

Candidate Evidence
→ stable candidate identity + canonical assignments + lineage

Statistics Evidence
→ existing and future admitted Statistics
```

Possible physical tables are implementation choices such as:

```text
market.parquet
variables.parquet
signals.parquet
candidates.parquet
statistics.parquet
```

The Artifact remains a portable immutable read view, not a replacement semantic authority.

## 24. Web visualization architecture

Renderer responsibilities are frozen by ADR 0094:

```text
Financial Time-Series
→ TradingView Lightweight Charts

Scientific / Statistical
→ Apache ECharts

Semantic / Exact DAG
→ Graphviz via @viz-js/viz
```

### Lightweight Charts

Use for:

```text
K-line
Volume
Indicator overlays/panels
Factor Score panels
Entry/Exit markers
```

### ECharts

Use for:

```text
Scatter
Distribution
Quantile / Box presentation
Heatmap
IC/RankIC comparisons
Candidate parameter analysis
Parallel Coordinates
```

Candidate presentation default:

```text
1 sweep dimension → scatter/line-style metric view
2 sweep dimensions → heatmap
3+ dimensions → parallel coordinates + table
```

### Graphviz

Use as a **read-only Graph Inspector**, not authoring authority.

Support two conceptual views:

```text
Semantic Graph
→ user-readable decision/research relationships

Exact Graph
→ exact resolved candidate execution topology and identities
```

Large Sweep spaces use Candidate Table/ECharts for comparison and only one selected candidate's Exact Graph at a time.

## 25. Graph authoring vs graph inspection

The Builder does not become a node editor in P8.

Correct direction:

```text
Builder
→ Research/Decision Definition
→ Resolver
→ Exact Graph
→ Graph Projection
→ Graphviz
```

Incorrect direction:

```text
User edits DOT/nodes
→ DOT becomes strategy authority
```

Graph visualization is for explainability, audit, and debugging.

## 26. Recommended implementation increments

### P8.4.0 — Research Definition & Decision Graph Foundation

Implement:

```text
Research Definition V1
Universe selection contracts
Calculation Instance
Fixed / Sweep parameters
Published Outputs
Research variable references
Global Candidate Space
Eligibility / Entry / Exit typed AST
Decision Graph lowering
Targets
Statistics compatibility admission
Definition → exact Specification → existing Workload equivalence
```

Exit condition:

```text
pure domain/programmatic Definition
→ deterministic exact Dataset
→ deterministic Candidate Space
→ deterministic exact Specification
→ existing Workload
```

No large React implementation is required for this increment.

### P8.4.1 — Discovery & Resolution API

Implement authoritative catalogs/discovery, Definition validation/resolution HTTP, compatibility reasons, exact Dataset resolution projection, candidate count, and exact Specification preview.

### P8.4.2 — Scientific Result Evidence

Extend Result/Artifact/Query evidence for market, published variables, signals, candidates, and exact-data projections without browser reconstruction from raw stores.

### P8.4.3 — Research Studio & Runs Web

Implement persistent workstation shell, New Research Builder, Inspector, Validate/Run, Run list/detail/cancel, and durable refresh/reconnect behavior.

### P8.4.4 — Scientific Viewer & Graph Inspector Closure

Implement evidence-backed Result tabs, Lightweight Charts financial workspace, ECharts scientific workspace, Candidate views, Exact Data, and Graphviz Semantic/Exact Graph Inspector.

## 27. End-to-end semantic scenarios

### Scenario A — Single instrument signal research

```text
Universe: 510300
Calculation: RSI(14)
Entry: RSI < 30
Exit: RSI > 70
Target: ForwardReturn
Statistic: supported admitted statistic
```

Expected product closure:

```text
Builder
→ Resolve
→ Run
→ immutable Result/Artifact
→ K-line + RSI + Entry/Exit markers
→ exact Graph inspection
```

### Scenario B — Cross-sectional factor sweep

```text
Universe: CSI300
Momentum.window = [10, 20, 40]
Eligibility: price/liquidity admitted conditions
Targets: Return5D + Return20D
Statistics: IC / RankIC
```

Expected closure:

```text
3 exact Research candidates
→ Result/Artifact
→ candidate comparison
→ Factor Score
→ IC/RankIC
→ exact evidence
→ selected candidate Exact Graph
```

## 28. Architecture gates

P8.4 must fail review if it introduces any of the following:

```text
Web imports server/core calculation implementations
Web computes authoritative Factor/Statistics/Signal truth
Web directly parses internal Artifact Parquet files
Definition depends on React/HTTP
Command API executes Runtime directly
Definition Resolver mutates Run authority
Artifact Query depends on PostgreSQL operational authority
Eligibility / Entry / Exit roles collapse
Research Signal depends on Position / Order / Account
arbitrary Python/string eval expression authority
arbitrary Calculation DAG authoring in P8
Graphviz DOT becomes execution authority
Research and Trading define separate signal logic for the same promoted decision
```

## 29. P8.4 non-goals

P8.4 does not implement:

```text
Strategy Revision authority
Research → Backtest promotion product
Backtest/Sim/Live Web productization
Position/Portfolio/Order/Fill/Broker semantics inside Research
arbitrary Python/IDE production code admission
LLM/Agent autonomous code registration
LLM/Agent automatic promotion
optimizer/Bayesian/random search
full Historical Data Platform
SSE/WebSocket as a mandatory first Run transport
fake percentage progress
editable node-graph strategy IDE
```

These remain future architecture directions and must not be smuggled into P8 through Web convenience features.

## 30. P8.4 completion principle

The most important equivalence is:

```text
Research Definition
→ Exact Specification
→ Existing Workload
→ Existing Runtime
```

must preserve the same authoritative Result/Calculation/Statistics identities that the equivalent exact existing Specification path would produce.

P8.4 succeeds when the Web becomes a better authoring/control/presentation client **without creating a new Research truth**.
