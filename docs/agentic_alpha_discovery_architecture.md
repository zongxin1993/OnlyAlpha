# Agentic Alpha Discovery Architecture

> Status: **Long-Term Target / Reference Architecture**
>
> This document refines the LLM/Agent direction in `docs/strategy_product_architecture.md`. It does not claim autonomous factor mining, Research → Backtest promotion, Sim promotion, or Live deployment is currently implemented. Each executable milestone must be redesigned against then-current repository truth and frozen by ADR before implementation.

## 1. Product target

OnlyAlpha can evolve from a human-operated quantitative research workstation into a controlled **Autonomous Alpha Research Platform** without turning an LLM into Research or Trading authority.

The target product relationship is:

```text
Human Quant Research
        +
Agentic Alpha Discovery
        ↓
      OnlyAlpha
```

OnlyAlpha owns deterministic facts and execution. Agents own proposal, orchestration, coding drafts, experiment planning, evidence interpretation, and promotion recommendations.

Core principle:

```text
Agent proposes and orchestrates.
OnlyAlpha proves and executes.
```

## 2. Why the architecture can support autonomous research

The long-term architecture separates high-change research components from stable execution infrastructure.

```text
Stable Kernel
├── Dataset identity / verification
├── Calculation semantic contracts
├── Decision Graph resolution
├── Research Runtime
├── Trading Kernel
├── Result / Artifact authorities
├── Run / Scheduler / Worker
└── Promotion / permission boundaries when implemented

High-change Domain Plugins
├── Indicators
├── Factors
├── Targets
└── Statistics Methods

External Integrations
├── Data Provider adapters
└── Broker adapters
```

Most new alpha ideas should not require a new strategy runtime class. They should be expressible by:

```text
new or existing Indicator / Factor
+
parameters / sweep
+
Eligibility
+
Entry / Exit expressions
+
Target / Statistics
→ Research Definition / Decision Graph
```

This makes a future Agent manageable: it does not need to understand internal Scheduler leases, PostgreSQL recovery, Trading Kernel managers, or Artifact filesystem layout. It can operate through formal product/API contracts.

## 3. Authoring-channel neutrality

Human and machine authors must produce the same canonical contracts.

```text
Web Builder
      │
Python / SDK ──→ Research / Decision Definition
      │
LLM / Agent
      │
      ▼
Same Resolution / Admission / Execution / Evidence Boundaries
```

There is no Agent-specific Research language and no hidden Web-only strategy schema.

A Definition created by an Agent must be admitted exactly like one created by a human.

## 4. Target autonomous discovery loop

The long-term loop is:

```text
Literature / Research Sources
        ↓
Literature Agent
        ↓
Structured Hypothesis
        ↓
Capability / Catalog Check
   ┌───────────────┴───────────────┐
   │                               │
Existing Component          Missing Component
   │                               │
   │                         Factor/Indicator
   │                          Engineer Agent
   │                               │
   │                         Isolated Sandbox
   │                               │
   │                         Static / Unit /
   │                         Contract / Identity /
   │                         Determinism Checks
   │                               │
   └───────────────┬───────────────┘
                   ↓
           Exact Registered Capability
                   ↓
           Research Designer Agent
                   ↓
           Research Definition
                   ↓
              OnlyAlpha Run
                   ↓
          Immutable Research Evidence
                   ↓
          Research Qualification Gate
                   ↓
             Backtest Candidate
                   ↓
               Backtest
                   ↓
          Backtest Qualification Gate
                   ↓
              SIM Candidate
                   ↓
                  SIM
                   ↓
           SIM Qualification Gate
                   ↓
             Human Live Approval
```

P8 implements only the Web-native Research foundation required by the early part of this chain.

## 5. Literature and hypothesis extraction

A future Literature Agent may search sources such as academic papers, preprints, public factor literature, authorized research reports, internal research history, and registered factor catalogs.

Its output is a structured proposal, not Research truth.

Conceptual proposal fields:

```text
source references
hypothesis
expected economic rationale
required data
formula / transformation intent
parameter ranges
intended Universe
expected horizon
known caveats
possible leakage risks
related existing factors
```

The proposal itself does not become an admitted Calculation Definition until Code/Contract Admission succeeds.

## 6. Reuse before generation

The Agent must query the registered Calculation/Research catalog before generating code.

Example:

```text
paper hypothesis
→ short-term reversal
→ requires rolling return
```

If `rolling_return` already exists, the preferred action is composition:

```text
existing Calculation
+
parameter sweep
+
Decision/Research Definition
```

not generating another near-duplicate plugin.

This keeps the semantic catalog small, reusable, and auditable.

## 7. Generated code is quarantined until admission

If a required atomic capability does not exist, an Agent may generate an Indicator/Factor/Target/Statistics implementation only inside an isolated development/admission environment.

The environment must have no Live Broker credentials or implicit production registration authority.

Target admission sequence:

```text
Generated Draft
→ format/lint/type/static validation
→ unit tests
→ semantic contract tests
→ deterministic identity tests
→ Research backend tests
→ cross-backend equivalence tests where a Trading backend exists
→ leakage / causal dependency checks where applicable
→ package/content evidence
→ explicit Code Admission
→ exact registered semantic version
```

The exact security sandbox is future implementation work, but the authority rule is permanent:

```text
Agent-generated source
!= admitted plugin
```

## 8. Research Designer Agent

Once capabilities are admitted, a Research Designer Agent may create the same formal Research Definition used by Web.

Example:

```text
Universe: CSI300

Calculations:
  Reversal.window = [5, 10, 20]
  Momentum.window = [20, 40]

Eligibility:
  admitted price/liquidity conditions

Entry:
  Reversal.score > threshold
  AND Momentum.score > 0

Targets:
  ForwardReturn5D
  ForwardReturn20D

Statistics:
  admitted IC / RankIC bindings
```

The server/domain resolver, not the Agent, determines the exact Dataset Snapshot, candidate space, graph, Specification, and Workload.

## 9. Agent API surface should be narrow

A future autonomous Agent should primarily consume formal application/product interfaces such as:

```text
Discovery / Catalog API
Definition Resolve API
Research Command API
Research Result / Artifact Query API
future Backtest Command/Result API
future Promotion API
```

It should not directly manipulate:

```text
PostgreSQL tables
Scheduler leases
Worker internals
content-addressed stores
Parquet paths
Broker credentials
Trading Kernel mutable managers
```

This keeps Agent failure isolated from core authority.

## 10. Research evidence is machine-readable authority

The Agent may interpret OnlyAlpha evidence but must not recreate it independently.

Wrong:

```text
Agent downloads raw bars
→ computes its own IC
→ declares factor qualified
```

Correct:

```text
OnlyAlpha Dataset / Calculation / Statistics
→ immutable Result / Artifact
→ Query API
→ Agent reads exact evidence
```

An Agent explanation is commentary. The underlying Artifact/Result remains the fact.

## 11. Qualification must prevent an automatic overfitting machine

Autonomous factor generation makes multiple-testing and data-mining risk more severe, not less severe.

A Research Gate must therefore be richer than a single threshold such as:

```text
IC > X
```

Long-term qualification dimensions may include:

```text
Effect Strength
├── IC
├── RankIC
└── conditional outcomes when formally supported

Stability
├── temporal stability
├── regime stability
└── Universe stability

Coverage
├── observation count
└── instrument count

Robustness
├── parameter neighborhood
├── sub-period tests
├── out-of-sample tests
└── perturbation sensitivity

Redundancy
├── correlation with existing factors
└── incremental information

Data Integrity
├── missing-value behavior
├── survivorship controls
├── leakage / look-ahead checks
└── timestamp/availability semantics

Multiple-Testing Governance
└── experiment family / search-budget evidence
```

Exact metrics/policies are future Statistics/Product decisions, not P8 requirements.

## 12. Gate authority belongs to OnlyAlpha policy, not LLM confidence

An Agent can recommend qualification, but policy decides.

```text
Agent: "the candidate looks strong"
Policy: OOS_FAILED
Result: candidate does not advance
```

Future qualification should be explicit, versioned, reproducible, and evidence-backed.

The Agent may not rewrite the gate because it dislikes the result.

## 13. Research → Backtest promotion

A qualified Research candidate must not be reimplemented as a new handwritten Backtest strategy.

Target direction:

```text
Qualified Research Candidate
→ exact Decision Definition / Graph
→ Freeze immutable Strategy Revision
→ Backtest
```

The promoted decision fingerprint/identity is preserved.

Backtest adds trading concerns such as:

```text
Portfolio / Position Policy
Sizing
Risk
Fee / Cost model
Execution Profile
Virtual Broker
```

but does not silently alter the researched Entry/Exit condition.

If decision semantics change, a new Research/Strategy Revision is required.

## 14. Backtest qualification

Backtest qualification is distinct from Research qualification.

Future policy may inspect evidence such as:

```text
out-of-sample return
risk-adjusted metrics
max drawdown
turnover
fee/cost sensitivity
trade count
exposure
capacity proxies
sub-period stability
execution robustness
```

Again, the Agent interprets; formal policy decides.

## 15. SIM qualification

A Backtest-qualified Strategy Revision may be admitted to SIM under controlled policy.

SIM proves realtime operational behavior that historical Backtest cannot fully prove, such as:

```text
live data availability
incremental/vector semantic equivalence in practice
signal timing
runtime stability
reconnect/recovery behavior
virtual execution behavior
latency distributions
realistic slippage observations where supported
```

SIM may be highly automated because it does not have real execution permission.

## 16. LIVE remains a separate permission boundary

At least for the first generations of Agentic Alpha Discovery:

```text
SIM_QUALIFIED
→ Human Approval
→ LIVE Candidate / Deployment
```

An Agent must not autonomously grant itself real-money execution permission.

This remains consistent with:

```text
Runtime Type
!= Execution Permission
```

Future automation of Live governance would require an explicit security/risk architecture decision and is not implied by this target.

## 17. Factor / component provenance

Every generated or Agent-assisted semantic component should be traceable.

Conceptual provenance:

```text
component semantic identity
source = HUMAN / AGENT / MIXED
source literature references
hypothesis
Agent/model/workflow version
source/package content fingerprint
exact semantic version
test/admission evidence
Research experiments
qualified Result/Artifact references
Backtest evidence when promoted
SIM evidence when promoted
```

Chat history or Agent hidden state is never durable semantic authority.

## 18. Factor Registry lifecycle

A long-term component/research registry may expose explicit lifecycle states such as:

```text
PROPOSED
IMPLEMENTED
ADMITTED
RESEARCHED
QUALIFIED
BACKTESTED
SIM_CANDIDATE
SIM_RUNNING
SIM_QUALIFIED
LIVE_CANDIDATE
```

Exact names/state machine are future design work. The important rule is that lifecycle is evidence-driven and historical evidence is immutable.

## 19. Alpha Knowledge Base

Autonomous research should not rediscover the same failed idea forever.

Long-term OnlyAlpha may build an evidence-backed Alpha Knowledge Base containing:

```text
Hypothesis families
Literature links
Registered Calculations
Experiment lineage
Datasets used
Parameter regions tested
Successful/failed candidates
Factor redundancy/correlation evidence
Regime behavior
Qualification decisions
```

Agents should query this history before starting new experiments.

The Knowledge Base is an index/projection over authoritative evidence, not permission to rewrite prior Result/Artifact facts.

## 20. Graph explainability for Agent-generated research

Graphviz inspection is especially important when a machine authors the Definition.

A human should be able to inspect:

```text
Agent Research Proposal
→ Semantic Decision Graph
→ selected exact Candidate Graph
→ Result Chart / Exact Data / Statistics
```

This provides an auditable answer to:

> What exactly did the Agent ask OnlyAlpha to execute?

Graphviz remains read-only presentation; the canonical Definition/Graph authorities remain server/domain values.

## 21. Long-term Web product shape

The persistent Scientific Quant Workstation can gradually support:

```text
Research
Backtest
SIM
LIVE
Data
System
```

Research remains the discovery workspace.

A future Agent surface should be integrated into the same workstation rather than becoming an unrelated chatbot product. Useful Agent UI may include:

```text
Research proposals
source literature/provenance
planned experiments
running jobs
qualification outcomes
candidate promotion queue
human approval queue
```

The Agent is another producer/operator of formal product commands, not an alternate semantic backend.

## 22. Long-term engineering work distribution

If the architecture succeeds, change frequency should move toward the edges.

### Low-frequency, stability-oriented work

```text
Core Domain
Calculation semantic framework
Decision Graph framework
Research Runtime
Trading Kernel
Dataset identity
Run/Scheduler/Worker
Result/Artifact authority
Promotion/security boundary
```

### Frequent alpha research development

```text
Indicators
Factors
Targets
Statistics Methods
research compositions / Definitions
```

### Frequent external maintenance

```text
Data Provider adapters
Broker adapters
external API compatibility
```

Most ordinary strategy ideas should become Graph/Definition composition rather than a new Runtime-specific strategy Python class.

## 23. Developer roles

Even in a single-person project, useful conceptual roles are:

```text
Kernel Developer
→ Runtime / Graph / Trading / authority infrastructure

Quant Component Developer
→ Indicator / Factor / Target / Statistics

Integration Developer
→ Data Provider / Broker

Quant Researcher
→ Builder / Definition / Sweep / analysis

Research Agent
→ automated proposal/orchestration through the same public contracts
```

One person or Agent may perform multiple roles, but authority boundaries remain separate.

## 24. Agent security invariants

Future Agent implementation must preserve:

```text
Agent cannot bypass Code Admission
Agent cannot mutate immutable evidence
Agent cannot directly grant Live permission
Agent cannot bypass Market Rules / Risk / Broker capability
Agent cannot make fuzzy "latest" semantic version resolution authoritative
Agent cannot treat its natural-language reasoning as durable strategy fact
Agent cannot silently change a promoted Decision Definition
Agent cannot use hidden future data in a causal Decision Graph
```

## 25. P8 boundary

P8.4 should make future Agent work possible by delivering machine-readable, channel-neutral Definition/Resolution contracts and evidence-backed Web/API surfaces.

P8 does **not** implement:

```text
autonomous literature search
Agent-generated production plugins
Agent Code Admission
Research qualification policy engine
Research → Backtest automatic promotion
Backtest Web product
SIM promotion
Agent-controlled SIM deployment
Agent-controlled LIVE deployment
Alpha Knowledge Base
```

These remain long-term targets.

## 26. Final target architecture

```text
                     Knowledge Sources
                            │
                      Research Agents
                            │
                Proposal / Code / Definition
                            │
                            ▼
                  OnlyAlpha Admission Layer
                            │
      ┌─────────────────────┼──────────────────────┐
      │                     │                      │
      ▼                     ▼                      ▼
Stable Kernel        Domain Components        Integrations
Research/Trading     Indicator/Factor         Data/Broker
Graph/Authorities    Target/Statistics        Adapters
      │                     │                      │
      └─────────────────────┼──────────────────────┘
                            ▼
                  Canonical Decision Graph
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
       Research          Backtest           SIM
          │                 │                 │
          ▼                 ▼                 ▼
      Evidence          Evidence          Evidence
          │                 │                 │
          └────── Qualification / Promotion ──┘
                            │
                            ▼
                       Human Approval
                            │
                            ▼
                           LIVE
```

The architectural advantage is not that an LLM becomes trusted. The advantage is that OnlyAlpha becomes strict enough that an untrusted, creative automated researcher can safely propose large numbers of experiments while deterministic infrastructure decides what is valid, what happened, and what is allowed to advance.
