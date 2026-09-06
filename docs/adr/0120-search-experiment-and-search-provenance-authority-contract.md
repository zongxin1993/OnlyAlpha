# ADR 0120: Search Experiment and Search Provenance Authority Contract

- Status: Accepted
- Date: 2026-09-06
- Decision maker: repository owner through the B3.1 implementation authorization
- Related: ADR 0072, 0083, 0095, 0115, 0118, 0119

## Context

B3.0 answers what exact scientific Evidence a Candidate has and whether that exact frozen Candidate satisfies an exact Qualification
Policy. It does not explain why a Candidate occurred: which search experiment, algorithm implementation, search space, random input,
budget, Catalog Generation, Dataset Snapshot, prior iteration result, proposal, decision workflow, Research Result, Qualification
Decision, failure, or stop condition caused it.

OnlyAlpha therefore needs the minimum durable provenance vocabulary required to explain and replay an autonomous search loop before
any search algorithm or Agent is introduced. This provenance must remain distinct from the private authoring workflow identity defined
by ADR 0115 and from every existing quantitative, evidence, qualification, strategy, promotion, and runtime authority.

## Decision

### Identity domains and sole authority

OnlyAlpha introduces one new formal authority:

```text
Search Experiment Provenance Authority
```

It owns only hypothesis and search context provenance; search algorithm identity and version; immutable search-space, randomness,
budget, Catalog Generation, and Dataset Snapshot bindings; Search Iteration occurrence and parent-result lineage; Proposal and
decision/model/tool provenance; exact Candidate, Research Result, and Qualification Decision references; and search-workflow failure
classification.

The identities are permanently separate:

```text
Search Experiment
!= ADR 0115 Authoring Experiment
!= Search Iteration
!= Proposal
!= Candidate
!= Calculation
!= Factor
!= Provider
!= Catalog Generation
!= StrategyRevision
```

A future workflow may connect Search Experiment, Search Iteration, Proposal, ADR 0115 Authoring Experiment, source admission, and an
admitted Factor only through exact typed references. No reference transfers identity or authority.

The authority matrix is:

| Fact | Sole authority |
|---|---|
| Search hypothesis/context | Search Experiment Provenance |
| Search algorithm/version/implementation/seed/budget | Search Experiment Provenance |
| Iteration parent lineage and Proposal occurrence | Search Experiment Provenance |
| Candidate mathematical identity | existing Candidate / Calculation authority |
| Factor mathematical semantics | Calculation / Quant Asset authority |
| Available asset set | Catalog Generation authority |
| Research data input | Dataset Snapshot authority |
| Research numeric statistics | Research Statistics authority |
| Candidate Evidence membership | Research Result V2 authority |
| Qualification PASS/FAIL | QualificationDecision authority |
| Private source-development context | ADR 0115 Authoring Experiment authority |
| Asset admission | Quant Asset / Catalog Admission authority |
| Strategy identity | StrategyRevision authority |
| Progression | Promotion authority |
| LIVE permission | explicit human LIVE authority |

Search provenance may reference these authorities, but never copies, recalculates, supersedes, or resolves them approximately.

### Append-only durable shape

A Search Experiment grows only by appending immutable records:

```text
OnlySearchExperimentManifestV1
+ OnlySearchIterationPlanV1
+ OnlySearchIterationResultV1
+ OnlySearchIterationPlanV1
+ OnlySearchIterationResultV1
+ ...
```

There is no rewritable aggregate, historical update, failed-iteration deletion, manifest overwrite, or formal mutation API. One
Iteration Plan has at most one terminal Result. Failed and skipped Iterations remain durable provenance.

### Experiment manifest

`OnlySearchExperimentManifestV1` has schema version 1 and binds:

```text
parent_experiment_fingerprint | null
hypothesis
search_algorithm_binding
search_space_reference
randomness_mode
seed
search_budget
catalog_generation_fingerprint
dataset_snapshot_fingerprint
workflow_binding
decision_engine_binding
experiment_fingerprint
```

Changing any decision-affecting semantic input creates a new Search Experiment. Materially changing Dataset, Catalog Generation,
Search Space, algorithm semantics, decision model/workflow, or future sealed-holdout exposure must start a new Experiment, which may
name the old Experiment through `parent_experiment_fingerprint`.

The immutable hypothesis value is `OnlySearchHypothesisV1` with schema version 1, a statement, ordered stable source references, and a
hypothesis fingerprint. Initial typed source kinds may include `PUBLICATION`, `PRIOR_EXPERIMENT`, and `RESEARCH_NOTE`; they are provenance
labels only and do not implement literature retrieval or RAG. Hypothesis identity is not Factor, Candidate, Research Evidence, or
Qualification identity.

### Algorithm, search-space, randomness, budget, and decision provenance

`OnlySearchAlgorithmBindingV1` binds an `algorithm_id`, `algorithm_semantic_version`, exact `implementation_fingerprint`, and
`source_revision`. Algorithm semantic version, executable implementation fingerprint, and source revision are distinct facts and all
enter Experiment identity.

B3.1 records only an immutable search-space reference:

```text
search_space_kind
search_space_schema_version
search_space_fingerprint
```

It defines no Search DSL, graph grammar, operator enumeration, or parameter grammar.

Randomness mode is exactly `NONE` or `SEEDED`. `NONE` requires a null seed; `SEEDED` requires an exact integer seed. Boolean seeds,
implicit seeds, unrecorded system-time seeds, and unrecorded random state are invalid.

The immutable Search Budget has three separate positive, non-boolean integer dimensions:

```text
proposal_limit
research_evaluation_limit
qualification_attempt_limit
```

This contract records the budget and whether an Iteration reached Research or Qualification. It does not add a scheduler, reservation
service, ranking policy, parallel allocator, or global Store scan.

Every Experiment has an explicit workflow identity/version. Decision mode is exactly `DETERMINISTIC`, `HUMAN`, or `MODEL_ASSISTED`.
Model-assisted mode additionally requires exact provider, model, model-version, prompt-template fingerprint, and tool-policy
fingerprint bindings. The Iteration Plan preserves exact ordered decision-input context fingerprints, ordered tool-result
fingerprints, and one decision-output fingerprint. B3.1 invokes no model.

Formal persisted schemas never contain chain of thought, hidden reasoning, an internal reasoning transcript, or equivalent fields.
They record structured inputs, exact reference and tool-result fingerprints, decision-output fingerprint, Evidence references, and
stable failure codes. Free-form diagnostics, when present operationally, are non-authoritative and excluded from semantic identity.

### Iteration and Proposal occurrence

One Search Iteration is exactly one Proposal occurrence. A batch producing N proposals produces N Iteration Plans. Repeating the same
Proposal in several Iterations preserves one `proposal_fingerprint`, while each Plan has a different identity because occurrence
context, including `iteration_index`, is identity-bearing.

Proposal identity is not Candidate identity. A Proposal is what a search method proposed in its vocabulary and may fail without
producing a Candidate. B3.1 persists only:

```text
proposal_kind
proposal_schema_version
proposal_fingerprint
```

There is no arbitrary proposal payload or generic `dict[str, object]` Proposal authority. Method-specific proposal contracts belong to
later milestones.

`OnlySearchIterationPlanV1` has schema version 1 and binds:

```text
experiment_fingerprint
iteration_index
parent_iteration_result_fingerprint | null
proposal_kind
proposal_schema_version
proposal_fingerprint
decision_input_context_fingerprints
decision_tool_result_fingerprints
decision_output_fingerprint
iteration_plan_fingerprint
```

The optional parent names an exact already-committed terminal Iteration Result, never merely a Plan. V1 permits zero or one parent and
permits several later Plans to branch from one Result. Unknown, self, cross-Experiment, cyclic, or unterminated-Plan parents fail
closed. Consuming only already-committed immutable Results structurally prevents cycles.

### Iteration Result and workflow disposition

`OnlySearchIterationResultV1` has schema version 1 and binds:

```text
iteration_plan_fingerprint
candidate_fingerprint | null
research_attempted
research_result_fingerprint | null
qualification_attempted
qualification_decision_fingerprint | null
disposition
failure_code | null
iteration_result_fingerprint
```

Disposition is workflow classification only. V1 uses `SKIPPED`, `FAILED`, `CANDIDATE_BOUND`,
`RESEARCH_EVIDENCE_RECORDED`, and `QUALIFICATION_DECISION_RECORDED`. It never describes a Factor as good, bad, production,
approved, best, or active.

Stable failure codes initially include:

```text
SEARCH_INVALID_PROPOSAL
SEARCH_BUDGET_EXHAUSTED
CANDIDATE_BINDING_FAILED
RESEARCH_SUBMISSION_FAILED
RESEARCH_EXECUTION_FAILED
RESEARCH_EVIDENCE_UNAVAILABLE
QUALIFICATION_NOT_ATTEMPTED
DECISION_PROVENANCE_INVALID
```

Failure text is non-authoritative operational diagnostics and is not part of the formal semantic record.

The Result contains only exact references to an existing Candidate, Research Result, and Qualification Decision. It contains no IC,
RankIC, information ratio, coverage, stability, correlation, neighborhood, Sharpe, generic score, or other Research numeric fact. It
contains no Qualification outcome. Consumers load the exact referenced authorities to inspect scientific values or PASS/FAIL.

### Canonical identity

All three primary objects and their supporting immutable values use the existing canonical JSON and lower-case SHA-256 fingerprint
utilities. No parallel hashing implementation or logical/content/result fingerprint trio is introduced.

Experiment identity includes exactly its schema version and the semantic inputs listed in the Experiment contract. Plan identity
includes exactly its schema version and the occurrence, parent, proposal, and ordered decision-provenance inputs listed in the Plan
contract. Result identity includes exactly its schema version and the terminal bindings, attempted flags, disposition, and failure code
listed in the Result contract.

Operational facts never affect semantic identity, including wall clock, creation/update timestamp, host, PID, container, path, HTTP
request, temporary workspace, worker, display label, UI state, or log message.

### Exact external-reference verification

Where an existing authority has an exact verified reader, Search provenance verifies exact Dataset Snapshot, Catalog Generation,
Candidate, Research Result, and Qualification Decision references through injected protocols. It does not import producer
implementation internals, recompute Research contents, or re-execute Qualification.

Until B3.2 defines Proposal and Search Space authorities, B3.1 validates their kind, schema version, and lower-case SHA-256 syntax only.
It does not invent a generic authority.

A missing, corrupt, identity-mismatched, or unsupported-schema required reference fails closed with a stable domain error. There is no
fallback to latest, equivalent, nearest, best, or fuzzy resolution.

### Persistence

Search provenance persistence is content-addressed, put-once, verified-load, append-only, and fail-closed. Its public operations are:

```text
commit_experiment()
load_experiment_verified()
commit_iteration_plan()
load_iteration_plan_verified()
commit_iteration_result()
load_iteration_result_verified()
```

The same fingerprint and identical canonical content returns `REUSED`. The same fingerprint with different semantic content, including
a second different terminal Result for one Plan, returns a conflict and never overwrites authority. Unknown schema versions,
discriminants, formal enum values, unexpected files, unsafe symlinks/physical aliases, non-canonical bytes, and fingerprint mismatches
fail closed.

The Store is exact identity persistence, not Experiment Memory or a scheduler. It has no authoritative latest, nearest, similar, best,
failed-region, novelty, vector-search, candidate-ranking, update, replace, or delete-and-recreate API.

## Consequences

Given one exact Iteration Result fingerprint, a fresh process can reconstruct the immutable parent-result chain to the Experiment and
its Hypothesis, algorithm, search-space, randomness, budget, Catalog, Dataset, Proposal occurrences, Candidate bindings, Research Result
references, Qualification Decision references, and failures. The reconstruction performs exact verified loads without recalculating
Research or Qualification.

Search implementations remain free to evolve behind this stable provenance contract. Existing Research Statistics, Research Result,
Candidate, Calculation, Factor, Provider, Catalog, Qualification, StrategyRevision, Promotion, and ADR 0115 Authoring Experiment
identities and meanings remain unchanged.

## Rejected alternatives

- Reusing or reinterpreting ADR 0115 Authoring Experiment as Search Experiment.
- A mutable universal SearchExperiment aggregate or overwritten Experiment JSON.
- Proposal identity as Candidate identity or an arbitrary generic Proposal payload.
- Dynamic Research metrics or Qualification PASS/FAIL copied into Search provenance.
- A mutable Factor status, production-factor list, or Agent-owned quantitative truth database.
- Hidden randomness, implicit seed, decision-affecting unversioned models, or persisted chain of thought.
- Latest, nearest, fuzzy, best, or Store-scan resolution as formal authority.
- A Search DSL, Symbolic Search, Parameter Search, Search scheduler, Agent, Experiment Memory, vector database, RAG, or literature
  retrieval in B3.1.
- Recomputing Research facts or re-executing Qualification during provenance verification.
- Silent overwrite, repair, deletion, or best-effort parsing of corrupt/unknown immutable records.

## Out of scope

This decision does not implement or authorize:

```text
Symbolic, parameter, beam, evolutionary, Bayesian, or learned search
Search execution, scheduling, allocation, candidate ranking, or best-candidate selection
LLM calls, Agent orchestration, model routing, code generation, or L3 admission
Novelty Gate, Experiment Memory, vector database, RAG, or literature retrieval
Factor Pool or multiple-testing/sealed-holdout policy
Research metric calculation or Research Result redesign
Qualification evaluation or Qualification Decision redesign
HTTP, OpenAPI, Web, Backtest, SIM, LIVE, Broker, or Market Data work
```

## Constitution consistency

Constitution Impact: **NO**.

This decision strengthens Uniqueness by separating identity domains and keeping one authority per fact; Determinism by making every
decision-affecting input explicit and canonically fingerprinted; Reproducibility and Traceability through immutable parent-result
lineage and exact Evidence references; Fail-Closed behavior through exact verified loads and put-once storage; and Explicit Boundaries
by preventing Search provenance from becoming Research, Qualification, Strategy, Promotion, Agent, or LIVE authority. It remains
market-agnostic, changes no Trading Kernel semantics, grants no Agent or LIVE authority, and requires no Constitution change.
