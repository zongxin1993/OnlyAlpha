# Agent Factor Mining Architecture & Work Program

> Status: **L3 Work Program / Implementation Sequencing**  
> Scope: Agent-driven factor discovery and factor-pool research  
> Authority: subordinate to `PROJECT_CONSTITUTION.md`, public architecture/contracts, and Accepted ADRs  
> Initial planning baseline: `94c1b241ad638b3e904031121cbb68a638ae537c`  
> This document defines sequencing, implementation priorities, open-source lessons, and hard constraints. It is **not** a completion-status authority, runtime authority, Research truth, or permission to bypass per-task ADR/Task Contract requirements.

---

## 1. Purpose

OnlyAlpha already has the core boundaries required for controlled autonomous research:

```text
Dataset Snapshot
→ Calculation / Graph
→ Research
→ Immutable Evidence
→ Strategy Freeze
→ StrategyRevision
→ Backtest
→ Qualification
→ Promotion
```

Private L3/L4 asset identity, experiment provenance, immutable distributions, Catalog Generation, exact authoring execution generation, and evidence-backed Qualification/Promotion are now formalized by the current architecture and ADRs.

The next problem is therefore **not** “how to let an LLM write `factor.py`”.

The next problem is:

> How can OnlyAlpha add multiple candidate-generation/search methods while preserving one Research truth, one semantic identity system, deterministic evidence, strict admission, multiple-testing governance, and a permanent human LIVE boundary?

The target is an **Alpha Discovery Controller** whose search methods may evolve independently:

```text
LLM hypothesis search
symbolic graph search
evolutionary search
parameter search
factor-pool search
paper-driven search
future learned / RL search
        ↓
Experiment Proposal
        ↓
OnlyAlpha Research
        ↓
Immutable Evidence
        ↓
Qualification
```

Search proposes. OnlyAlpha proves.

---

## 2. Normative references and current boundaries

This work program must remain consistent with:

```text
PROJECT_CONSTITUTION.md
AGENTS.md
docs/agentic_alpha_discovery_architecture.md
docs/architecture.md
ADR 0115 — Private Quant Asset Identity, Version, Admission and Release Contract
ADR 0116 — Authoring Execution Generation and Research Binding
ADR 0117 — Immutable Distribution, Runtime Generation and New-Work Activation
ADR 0118 — Evidence-Backed Qualification and Promotion Authority
```

Permanent constraints inherited from those authorities include:

- Agent uses the formal OnlyAlpha API; direct production control through internal Python objects is not an alternate product path.
- Agent never owns LIVE activation, LIVE strategy change, or material LIVE risk authorization.
- Agent experiment identity is not Calculation identity, Provider identity, Catalog identity, or StrategyRevision identity.
- Generated source is not admitted source.
- Package release is not Catalog activation.
- Catalog activation affects new work only and never rebinds active Runs or StrategyRevisions.
- Research/Backtest Evidence remains the quantitative fact authority.
- Qualification decides whether exact evidence satisfies an exact policy; Agent confidence cannot declare PASS.
- Promotion remains separate from Qualification and runtime execution permission.
- No `latest`/nearest semantic resolution is authoritative.
- Search, randomness, model decisions, seeds, search budgets, and external responses that affect results must become explicit versioned inputs or facts.
- A new Agent feature must not create a second Factor status database, a second Research result store, a second strategy identity, or a second execution path.

If a future B3 task requires weakening these rules, it is a `PLAN_CONFLICT`, not an implementation shortcut.

---

## 3. Lessons from open-source systems

The projects below are architectural references, not production authorities inside OnlyAlpha.

### 3.1 RD-Agent / RD-Agent(Q)

Upstream reference:

- https://github.com/microsoft/RD-Agent

Useful ideas:

1. **R&D loop separation**

   RD-Agent explicitly separates proposing ideas (“R”) from implementing/testing them (“D”). The quant variant extends this into iterative factor/model research.

   OnlyAlpha adoption:

   ```text
   Research Planner
       ↓ proposes
   Experiment / Factor candidate
       ↓ executes
   OnlyAlpha Research
       ↓ evidence
   Evidence Analyst
       ↓ feedback
   next proposal
   ```

   The loop is valuable; RD-Agent’s result interpretation is not imported as OnlyAlpha Research authority.

2. **Feedback-driven evolution**

   Failed implementations and weak research outcomes should influence future proposals instead of being forgotten.

   OnlyAlpha adoption:

   - explicit Experiment lineage;
   - structured failure reason;
   - evidence references;
   - searchable prior explored regions;
   - novelty/duplicate checks before expensive execution.

3. **Role specialization without requiring immediate physical multi-agent complexity**

   RD-Agent demonstrates Research/Development specialization and model-cost specialization.

   OnlyAlpha adoption for the first generation:

   ```text
   one orchestrator
   + explicit logical roles
   + different model/tool policies per role
   ```

   Do not begin with many autonomous services, consensus protocols, or an Agent message bus unless real evidence later proves that a single orchestrator is insufficient.

4. **Factor/model co-optimization is a later stage**

   RD-Agent(Q) demonstrates value in alternating factor and model optimization.

   OnlyAlpha decision:

   - first close factor semantic discovery;
   - then factor-pool search;
   - then strategy discovery;
   - only later consider joint Factor/Model optimization.

### 3.2 AlphaGen

Upstream reference:

- https://github.com/ICT-FinD-Lab/alphagen

Useful ideas:

1. **Constrained formula search space**

   AlphaGen generates formulaic alphas from operators/features rather than requiring arbitrary source code for every candidate.

   This maps naturally to OnlyAlpha:

   ```text
   L1 Operators
   + L2 Indicators / stable financial primitives
   + canonical parameters
   → OnlyCalculationGraphDefinition
   ```

   Therefore symbolic graph composition is the preferred high-volume search path.

2. **External evaluator adapter**

   AlphaGen exposes an `AlphaCalculator` abstraction so its search can use another evaluation pipeline.

   OnlyAlpha adoption:

   > Search algorithms must be evaluator-independent. They produce candidate graph proposals and consume OnlyAlpha-owned evidence through formal APIs.

   AlphaGen/Qlib must not become a second Research execution authority.

3. **Single-factor and factor-pool objectives are different**

   AlphaGen evaluates single IC/RankIC, mutual IC between factors, and pool-level IC/RankIC.

   OnlyAlpha adoption:

   Factor mining must eventually answer two independent questions:

   ```text
   Is this factor individually informative?
   Does this factor add incremental information to the existing admitted/qualified pool?
   ```

   A highly predictive but highly redundant factor may be rejected; a modest standalone factor may be valuable if it materially improves the pool.

4. **RL is an optimization technique, not the initial architecture**

   AlphaGen uses reinforcement learning for formula search, and its repository also contains GP/DSO/LLM approaches.

   OnlyAlpha sequencing:

   ```text
   deterministic enumeration / bounded search
   → beam / evolutionary search
   → LLM-guided search
   → learned / RL search only after enough structured Evidence exists
   ```

   Do not introduce PPO/LSTM policy/checkpoint/reward-shaping infrastructure before the deterministic search/evidence contract is proven.

### 3.3 Qlib

Upstream reference:

- https://github.com/microsoft/qlib

Useful ideas:

1. **Expression-oriented factor construction**

   Qlib’s expression/data pipeline demonstrates that a large factor space can be represented as composable operations rather than one Python strategy class per idea.

   OnlyAlpha already has the canonical equivalent direction in `OnlyCalculationGraphDefinition` and L1/L2/L3 quant-asset layers.

2. **Loose coupling of data, learning, workflow, backtest, and analysis**

   OnlyAlpha should preserve the same separation principle while retaining its own stronger Authority/recovery/evidence contracts.

3. **Reusable experimental workflow**

   Qlib/RD-Agent show the value of a standard experiment execution/evaluation path.

   OnlyAlpha adoption:

   all Agent experiments must converge onto the normal OnlyAlpha Research API and Evidence path rather than an Agent-specific execution engine.

### 3.4 Explicit non-adoption decisions

The following are deliberately rejected as first-generation architecture:

```text
Qlib as OnlyAlpha production Research/Backtest authority
RD-Agent as a second orchestration/runtime truth
AlphaGen/Qlib direct database ownership inside OnlyAlpha
Agent-computed IC/RankIC as formal Evidence
one Python file per generated formula candidate
in-process dynamic module reload for Agent candidates
LLM confidence as Qualification outcome
automatic Agent-authorized LIVE progression
PPO/RL before deterministic search/evidence closure
```

Open-source implementations may be used as baselines, compatibility oracles, algorithmic references, and offline research comparisons, but not as competing canonical authorities.

---

## 4. Target factor-mining architecture

```text
                     Literature / Knowledge
                              │
                              ▼
                       Hypothesis Search
                              │
                              ▼
                         Search Router
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
     Catalog Reuse      Symbolic Graph       Parameter Search
          │                   │                   │
          └───────────────────┼───────────────────┘
                              │
                              ▼
                     Experiment Candidate
                              │
                      formal OnlyAlpha API
                              │
                              ▼
                     Dataset Snapshot
                              │
                              ▼
                      Research Runtime
                              │
                              ▼
                 Immutable Research Evidence
                              │
              ┌───────────────┼────────────────┐
              │               │                │
              ▼               ▼                ▼
           Effect         Stability        Redundancy
              │               │                │
              └───────────────┼────────────────┘
                              │
                              ▼
                        Qualification
                              │
                    ┌─────────┴─────────┐
                    │                   │
                 REJECT              APPROVE
                    │                   │
                    ▼                   ▼
          Experiment Memory       Asset Admission
                    │                   │
                    └──── feedback ─────┤
                                        ▼
                                Qualified Factor Pool
                                        │
                                        ▼
                                   Pool Search
                                        │
                                        ▼
                                Strategy Research
                                        │
                                        ▼
                                StrategyRevision
                                        │
                                     Backtest
                                        │
                                       SIM
```

This architecture deliberately separates:

```text
candidate generation
!=
research execution
!=
evidence
!=
qualification
!=
admission
!=
promotion
```

---

## 5. Search-method hierarchy

Agent/search logic must follow **reuse before generation**.

For each research idea:

```text
1. Does the Catalog already contain the required Factor/Calculation?
   YES → reuse exact semantic identity.

2. Can existing L1/L2 components express it as a canonical graph?
   YES → compose OnlyCalculationGraphDefinition.

3. Is the change only a parameter/sweep question?
   YES → use deterministic parameter search.

4. Is a reusable generic mathematical/financial capability actually missing?
   YES → propose an L1/L2 capability through its normal public admission path.

5. Is this genuinely a new hypothesis-bearing atomic L3 Factor?
   YES → isolated code-generation/admission workflow.
```

Code generation is the last path, not the default path.

The desired long-term distribution is approximately:

```text
most experiments      → graph composition / parameter variation
some experiments      → factor-pool combinations
few experiments       → genuinely new L3 executable code
```

---

## 6. First-generation Agent execution model

The first generation should be implemented as:

```text
OnlyAlpha-Agent service/node
        │
        ├── Research Planner role
        ├── Search Router role
        ├── Factor Designer role
        ├── Code Engineer role (only when required)
        └── Evidence Analyst role
```

These are logical roles, initially coordinated by one orchestrator.

Do not start with:

```text
many autonomous persistent agent processes
agent-to-agent consensus
agent event bus as business authority
independent agent databases containing factor truth
agent-specific Research runtime
```

Different roles may use different model classes and token budgets, but all formal state transitions remain explicit OnlyAlpha/API operations.

---

## 7. Experiment identity and provenance

Every candidate search/evaluation must have an explicit Experiment context.

The Experiment is mutable workflow provenance and must remain distinct from formal Factor/Provider/Strategy identities.

A reproducible experiment or experiment iteration should eventually bind, as applicable:

```text
experiment_id
parent_experiment_id / lineage
hypothesis identity/fingerprint
search algorithm identity/version
search-space fingerprint
search seed
search budget
model provider/model identifier
Agent workflow version
prompt-template fingerprint
input-context/reference fingerprints
candidate graph/source fingerprint
Catalog Generation
Dataset Snapshot
Research Run / Result fingerprints
Qualification Decision
failure / rejection reason
```

Natural-language chain-of-thought is not required or authoritative. The durable record is structured provenance, inputs, tool results, decisions, and Evidence references.

---

## 8. Knowledge and memory architecture

Do not build one undifferentiated vector database and call it “Agent memory”.

Two different memories are required.

### 8.1 Literature Knowledge

Purpose:

```text
semantic retrieval
paper/report discovery
economic rationale
known anomalies
citations
formula descriptions
```

A RAG/vector index is appropriate here.

It is advisory knowledge, not Research truth.

### 8.2 Experiment / Evidence Memory

Purpose:

```text
what hypotheses were tried
what parameter/search regions were explored
what exact Dataset/Catalog was used
what Evidence resulted
what was rejected and why
what factors were redundant
what Qualification decided
```

This must be a structured projection/index over authoritative OnlyAlpha Evidence and experiment provenance.

It must not copy dynamic IC/Sharpe values into a second truth store that can diverge from formal Evidence.

### 8.3 Failure is first-class knowledge

Rejected experiments are valuable and must remain discoverable.

The Agent should avoid repeating:

```text
exact duplicate semantics
already explored parameter regions
known failed hypothesis families
near-identical formulas
highly redundant factors
```

A future Novelty Gate should run before expensive Research execution.

---

## 9. Research evidence requirements before autonomous mining

ADR 0118 correctly establishes Qualification structure, but the initial metric vocabulary is intentionally narrow.

A production-useful factor-mining loop requires authoritative Research Evidence to expose richer metrics before the Agent is allowed to treat them as formal qualification criteria.

Target evidence families include:

```text
Effect
├── IC
├── RankIC
├── ICIR
├── RankICIR
└── direction / sign consistency

Coverage
├── observation count
├── instrument count
└── missing / invalid ratio

Stability
├── temporal slices
├── regime slices
└── universe slices

Robustness
├── parameter neighborhood
├── perturbation sensitivity
└── sub-period consistency

Redundancy
├── factor-to-factor correlation
└── incremental/pool contribution

Data integrity
├── timestamp/availability semantics
├── leakage/look-ahead checks
└── survivorship/missing-data controls when applicable

Multiple-testing governance
├── experiment family
├── candidates generated/evaluated
├── qualification attempts
└── search budget / seed / algorithm identity
```

These values must be produced by their owning Research/Statistics Evidence contracts.

Qualification must consume those exact metrics; it must not recompute IC/PnL/raw-bar statistics independently.

---

## 10. Multiple-testing and sealed holdout governance

Autonomous search creates a stronger data-snooping problem than manual research.

A repeatedly queried “test” set becomes training information for the Agent.

Therefore the target research lifecycle should distinguish:

```text
Exploration
Validation
Sealed Holdout
```

Rules:

- normal Agent search uses Exploration/Validation evidence;
- Sealed Holdout is not exposed as free iterative feedback;
- Holdout access is an explicit limited-budget qualification action;
- holdout evaluation count is recorded;
- a new search after seeing sealed evidence belongs to a new experiment family/governance context rather than pretending the holdout remains untouched;
- Qualification Policy must be able to fail closed when required multiple-testing/search-budget evidence is missing.

Exact statistical policy belongs to future accepted design, but the boundary is mandatory before large-scale autonomous mining.

---

## 11. Factor Pool architecture

OnlyAlpha factor discovery must not optimize only independent single-factor score.

The target pool layer evaluates:

```text
single-factor information
pairwise/mutual redundancy
pool-level prediction
marginal contribution of a candidate to the current pool
stability of the contribution
```

First implementation should prefer transparent deterministic algorithms, for example:

```text
greedy forward selection
bounded beam search
explicitly seeded evolutionary search
```

Later implementations may add learned/RL policies without changing the evaluator/evidence authority.

A Factor Pool is still a research product/composition until explicitly frozen into whatever future canonical strategy/factor-composition contract owns it. It must not become a hidden alternate StrategyRevision.

---

## 12. Model and cost routing

Not every Agent operation should use the strongest model.

Target routing:

```text
Strong reasoning model
→ literature synthesis
→ hypothesis creation
→ difficult semantic/code design

Medium model
→ experiment interpretation
→ bounded variations
→ code repair

Cheap model
→ classification
→ summarization
→ tagging
→ candidate formatting

No LLM
→ deterministic graph enumeration
→ parameter sweeps
→ factor correlation
→ pool selection algorithms
→ qualification evaluation
```

Model/provider/workflow selection that changes research decisions must be explicit provenance.

Token efficiency is an architectural concern, but never a reason to bypass Evidence or determinism.

---

## 13. Implementation path — B3 Agent Factor Mining

No B3 milestone is automatically authorized by this document. Before implementation, each milestone must be checked against then-current repository truth and executed under the normal Task Contract / ADR rules required by `AGENTS.md`.

### B3.0 — Rich Factor Research Evidence Contract

**Goal**

Make the deterministic Research system capable of producing the metrics required by factor mining and Qualification.

**Primary work**

```text
formal IC / RankIC Evidence
ICIR / RankICIR where semantics are frozen
coverage evidence
time-slice / sub-period stability evidence
factor-correlation evidence
basic parameter-neighborhood evidence
Evidence-owned scalar metric exposure for Qualification
```

**Hard constraints**

- Qualification does not become a statistics engine.
- No Agent implementation yet.
- No duplicated result truth.
- Same Dataset/Calculation/Statistics inputs reproduce the same Evidence.

**Gate**

OnlyAlpha can qualify a simple factor using meaningful exact Research metrics without Agent recomputation.

---

### B3.1 — Experiment & Search Provenance Contract

**Goal**

Create the minimum durable vocabulary required to explain an autonomous search loop.

**Primary work**

```text
Experiment / ExperimentIteration identity
parent lineage
search algorithm/version
search-space fingerprint
seed
search budget
candidate fingerprint
Catalog/Dataset/Research bindings
outcome/rejection classification
Agent/model/tool provenance fields where they affect decisions
```

**Hard constraints**

- Experiment identity does not become Factor/Provider/Strategy identity.
- Dynamic Research metrics remain Evidence references.
- Do not create a mutable production-factor status authority.

**Gate**

One scripted/fake Agent experiment can be replayed and its complete lineage can be explained from formal identifiers.

---

### B3.2 — Symbolic Factor Search MVP

**Goal**

Prove high-volume factor discovery without arbitrary code generation.

**Primary work**

```text
query exact L1/L2 Catalog
bounded legal graph grammar over existing components
canonical graph candidate generation
semantic duplicate elimination
complexity/depth/operator constraints
deterministic enumeration or explicit-seed bounded search
submit candidates through normal Research API
read immutable Evidence
```

**Initial restriction**

No new Python Factor code; use existing admitted operators/indicators only.

**Gate**

Given one fixed search specification and seed, the system produces the same candidate identities, executes them through normal Research, and produces traceable Evidence/Qualification outcomes.

---

### B3.3 — Parameter Search & Experiment Feedback Loop

**Goal**

Turn one candidate family into an iterative evidence-driven search loop.

**Primary work**

```text
coarse-to-fine deterministic sweeps
explicit seeded random/Bayesian/evolutionary option only when reproducible
parent-child experiment lineage
prior Evidence retrieval
failed-region suppression
search-budget accounting
next-round candidate planning
```

**Gate**

The loop can refine a factor parameter region using prior formal Evidence without hidden mutable state or unrecorded random decisions.

---

### B3.4 — Agent Orchestrator MVP

**Goal**

Introduce the first LLM-controlled proposal loop without expanding its authority.

**Roles**

```text
Research Planner
Search Router
Factor Designer
Evidence Analyst
```

**Primary work**

```text
OnlyAlpha-Agent service/package boundary
formal OnlyAlpha API client only
model/tool routing
structured hypothesis contract
Catalog-first reuse decisions
symbolic/parameter search invocation
Evidence interpretation
next-experiment proposal
```

**Explicitly out of scope**

```text
paper RAG
arbitrary production code generation
multi-agent distributed runtime
Factor Pool RL
Strategy mining
LIVE
```

**Gate**

Input one structured hypothesis; the Agent can produce/execute bounded graph experiments, inspect formal Evidence, and propose the next iteration without owning the evaluation result.

---

### B3.5 — Novelty & Experiment Memory

**Goal**

Prevent repeated expensive research and make failure knowledge reusable.

**Primary work**

```text
structured Experiment/Evidence index
exact semantic duplicate detection
parameter-region history
near-duplicate candidate retrieval
existing-factor redundancy lookup
known-failed hypothesis retrieval
novelty decision evidence/provenance
```

Optional semantic/vector search may assist retrieval but cannot define exact identity equality.

**Gate**

Known duplicate or already-explored candidates are rejected/skipped before Research with a traceable reason; historical failures remain discoverable without becoming a second Research truth.

---

### B3.6 — Isolated L3 Code Generation & Admission

**Goal**

Allow Agent generation only when a hypothesis cannot be expressed by existing L1/L2 composition.

**Primary work**

```text
candidate worktree/source bundle
non-production candidate provider
engineering validation
unit/contract/determinism checks
Research/Trading equivalence when applicable
Research Evidence
PR-based private-asset admission
provider/semantic version enforcement
immutable release / Catalog Generation for new work
```

Reuse ADR 0115–0117; do not create a second Agent-specific admission system.

**Gate**

An Agent-generated L3 candidate can move from isolated experiment to formal admitted asset only through the same private-asset lifecycle as human-authored assets.

---

### B3.7 — Factor Pool Evaluation & Selection

**Goal**

Move from “best individual factor” to “best incremental factor collection”.

**Primary work**

```text
mutual factor correlation/evidence
normalized combination semantics
pool-level evaluation
marginal contribution evidence
simple greedy forward selection
bounded beam/evolutionary alternative
pool experiment lineage
```

**Gate**

The system can reject a high standalone-score redundant factor and retain a lower standalone-score factor when the latter provides reproducible incremental pool value.

---

### B3.8 — Literature / RAG Hypothesis Discovery

**Goal**

Add paper/report-driven hypothesis generation after the execution/evidence loop is already stable.

**Primary work**

```text
literature ingestion/retrieval
citation/provenance
structured hypothesis extraction
economic-rationale field
required-data/operator mapping
known-caveat/leakage-risk extraction
existing Experiment/Factor lookup before proposal
```

**Gate**

A paper-derived hypothesis becomes only an Experiment Proposal; all factor semantics, Research, Evidence, Qualification and admission continue through existing authoritative paths.

---

### B3.9 — Learned Search Policy / RL (Optional Later Stage)

**Goal**

Use accumulated structured experiment history to improve search efficiency.

Potential methods:

```text
multi-armed bandit search routing
learned operator/parameter proposal
reinforcement-learning formula policy
experience-conditioned candidate ranking
```

**Preconditions**

- large clean structured Experiment/Evidence corpus;
- stable reward/evidence semantics;
- explicit search-budget governance;
- deterministic replay of environment/evaluation inputs;
- baseline deterministic/beam/evolutionary methods already measured.

RL is not required for initial Agent Factor Mining success.

---

## 14. Deliberate sequencing

The intended order is:

```text
B2.5 Evidence-backed Qualification
        ↓
B3.0 Rich Research Evidence
        ↓
B3.1 Experiment/Search provenance
        ↓
B3.2 Symbolic Factor Search MVP
        ↓
B3.3 Parameter/feedback loop
        ↓
B3.4 LLM Agent Orchestrator MVP
        ↓
B3.5 Novelty / Experiment Memory
        ↓
B3.6 L3 Code Generation / Admission
        ↓
B3.7 Factor Pool Search
        ↓
B3.8 Literature / RAG
        ↓
B3.9 learned / RL search if justified
```

This order is intentional.

It ensures that when an LLM is introduced, deterministic search, Evidence, provenance, and Qualification already exist. When code generation is introduced, graph reuse and private-asset admission already exist. When RAG is introduced, the system already knows how to avoid duplicate experiments. When RL is introduced, there is already a trustworthy historical dataset of structured search decisions and outcomes.

---

## 15. First end-to-end MVP definition

The first useful Factor Mining MVP should be intentionally small.

Input:

```text
one manually supplied structured hypothesis
one fixed Dataset/Universe/Target specification
existing admitted L1/L2 Catalog
```

System:

```text
Catalog query
→ generate 10–100 bounded legal graph candidates
→ deterministic duplicate removal
→ OnlyAlpha Research
→ immutable factor Evidence
→ exact Qualification
→ next-round bounded proposal
```

Output:

```text
qualified/rejected candidate identities
exact Evidence references
complete Experiment lineage
search budget
rejection reasons
```

The MVP explicitly does **not** require:

```text
paper search
RAG
new Factor Python code
multi-agent runtime
Factor Pool RL
strategy generation
SIM/LIVE
```

If this MVP cannot be made deterministic, reproducible and explainable, adding more LLM autonomy is prohibited.

---

## 16. Acceptance invariants for every B3 milestone

Every milestone must preserve the following properties where relevant:

### Uniqueness

```text
Experiment identity != Factor identity
Factor semantic identity != implementation identity
Provider/Catalog identity != StrategyRevision
Agent memory != Research Evidence authority
```

### Determinism

Same exact:

```text
search specification
+ search algorithm/version
+ seed
+ Catalog Generation
+ Dataset Snapshot
+ Research configuration
```

must reproduce the same deterministic candidate/evaluation path, except for explicitly recorded external/LLM decisions which themselves become exact inputs/facts.

### Fail-closed

Unknown/missing:

```text
metric semantics
candidate dependency
Catalog generation
Dataset binding
Evidence binding
qualification policy
historical exact implementation
```

must not silently fall forward or guess.

### Traceability

For an admitted/qualified factor, the system must be able to reconstruct conceptually:

```text
source hypothesis / search context
→ Experiment
→ candidate semantic identity
→ Catalog/Dataset
→ Research Run
→ Evidence
→ Qualification Decision
→ admission / Provider generation when applicable
```

### LIVE boundary

No B3 task grants LIVE permission. Agent Factor Mining may eventually reach Backtest/SIM only through existing formal promotion boundaries. LIVE remains explicit human authority.

---

## 17. Architecture anti-patterns

Reject any implementation that introduces one of the following without an explicit higher-authority redesign:

```text
agent_result.db as a second quantitative truth
factor.status = PRODUCTION as mutable authority
Agent directly writing PostgreSQL/ClickHouse business state
Agent importing internal Kernel objects for normal product control
Agent recomputing official IC/RankIC from raw bars
LLM-generated string formula executed with eval()
Python module path as Factor semantic identity
latest Factor/provider/model resolution
in-place importlib.reload hot plug
unbounded random search with unrecorded seed/budget
using sealed holdout repeatedly as ordinary feedback
releasing every experiment as a Provider version
one strategy.py per factor experiment
Agent self-approving Qualification/Promotion
Agent acquiring LIVE credentials or execution permission
```

---

## 18. Repository boundaries

Long-term physical/logical direction:

```text
OnlyAlpha
→ stable Kernel, Calculation/Research/Evidence/Qualification/API contracts

OnlyAlpha-alpha
→ private admitted L3 Factors

OnlyAlpha-strategies
→ private L4 authoring assets

OnlyAlpha-Agent
→ high-change research orchestration, search methods, literature/knowledge adapters
```

OnlyAlpha-Agent should depend on the formal public API/client and authoring workflows, not on private internal Kernel implementation imports.

Search algorithms belong with the Agent/research-control side unless they are proven generic deterministic quantitative semantics needed independently of Agent orchestration.

---

## 19. Development discipline

For every B3 milestone:

1. read current `PROJECT_CONSTITUTION.md` first;
2. inspect current repository truth rather than assuming this work program is implementation truth;
3. identify whether a new public contract/architecture decision is actually required;
4. freeze the task-specific Required Behavior and Acceptance Tests;
5. implement only the minimum dependency-complete scope;
6. use deterministic tests/fake clocks/barriers/fault injection rather than timing guesses;
7. perform bounded independent review for high-risk Authority/identity/evidence changes;
8. stop at the milestone Hard Stop and do not silently continue into the next B3 stage.

This work program may be revised as implementation truth evolves, but it may not weaken the Constitution or accepted higher-level architecture to make an implementation easier.

---

## 20. Success criterion for the Agent Factor Mining program

The program is successful when a new alpha idea can move through this chain without modifying OnlyAlpha Core for ordinary factor research:

```text
Human / Paper / Agent hypothesis
        ↓
Search / Composition / isolated L3 candidate
        ↓
Experiment identity + exact provenance
        ↓
OnlyAlpha Research API
        ↓
Immutable Evidence
        ↓
Evidence-backed Qualification
        ↓
Private L3 admission when required
        ↓
Factor Pool / Strategy Research
        ↓
StrategyRevision
        ↓
Backtest / SIM under existing promotion rules
```

and the system can answer, for every accepted result:

```text
What hypothesis produced it?
What exact candidate semantics were tested?
Which Catalog Generation and Dataset Snapshot were used?
How many candidates were searched before it was found?
Which model/search algorithm/seed made the proposal?
What exact Research Evidence supports it?
Why did Qualification approve or reject it?
Is it redundant with existing factors?
Can the experiment and quantitative result be reproduced?
```

The desired long-term property is:

> Agent intelligence and search sophistication may change rapidly, while OnlyAlpha’s quantitative facts, identities, evidence, admission and runtime authorities remain stable.
