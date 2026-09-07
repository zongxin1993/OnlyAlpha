# ADR 0121: Deterministic Symbolic Factor Search Authority Contract

- Status: Accepted
- Date: 2026-09-07
- Decision maker: repository owner through the B3.2 implementation authorization
- Related: ADR 0069, 0095, 0110, 0112, 0115, 0118, 0119, 0120

## Context

ADR 0120 records why a Search Candidate occurred, but deliberately owns neither a Search Space payload nor a method-specific Proposal.
B3.2 needs a finite, deterministic, non-adaptive symbolic search over one exact Quant Asset Catalog Generation without creating a
second mathematical graph, Candidate identity, Research executor, scientific-metric authority, Qualification outcome, or Factor
admission path.

Research Statistics accepts a feature only when the selected graph node is an existing `OnlyCalculationKind.FACTOR` whose selected
output has `FACTOR_VALUE` or `FACTOR_SCORE` semantics. ADR 0110 separately classifies reusable L1/L2 assets and hypothesis-bearing L3
Factors. Search therefore cannot make an L1/L2 output into a Factor by declaration.

## Decision

### Authority boundaries

The authority matrix is:

| Fact | Sole authority |
|---|---|
| legally explorable finite component/terminal/bound set | Symbolic Search Space V1 |
| deterministic proposal order | Deterministic Enumeration V1 |
| one method-specific proposed graph/output payload | Symbolic Graph Proposal V1 |
| calculation meaning, compatibility, DAG legality and graph identity | Calculation Definition and Graph |
| Research Candidate identity | ADR 0095 normal Research Specification Resolver |
| numeric scientific facts | Research Statistics |
| exact Candidate Evidence composition | Research Result |
| policy PASS/FAIL | QualificationDecision |
| Experiment and Iteration occurrence lineage | ADR 0120 Search Provenance |

The identity domains remain permanently distinct:

```text
Search Space fingerprint != Proposal fingerprint != Graph fingerprint != Candidate fingerprint
```

No `FormulaAST`, expression DSL, Formula fingerprint, second Graph, second Candidate constructor, or Search-owned metric/result is
introduced. Ephemeral generation states are not persisted authorities.

### Existing Factor semantic bridge

The admitted bridge is an exact L3 Calculation registration already present in the bound Catalog Generation. It must:

1. belong to an `L3_FACTOR` provider;
2. have native `OnlyCalculationKind.FACTOR` semantics;
3. expose an exact `FACTOR_VALUE` or `FACTOR_SCORE` output selected by the Search Space candidate-output contract;
4. have an exact RESEARCH backend and Definition resolver in the same Catalog Generation; and
5. receive upstream L1/L2 outputs only through its declared typed Calculation inputs.

ADR 0110's public, non-production contract witness is `example.factor.momentum@1`, supplied by the
`onlyalpha-example-alpha` L3 provider. The private parity witness is `private.factor.momentum@1`, supplied by the private L3 provider.
Both are hypothesis-bearing Factors rather than generic wrappers. A concrete Search Space must bind one exact admitted bridge and may
only explore graphs whose explicit candidate output is that bridge's formal Factor output. Search does not import either provider or
name either type as a fallback; the fixed Catalog Generation is the only resolution source.

An L1/L2-only graph is not a Research Factor. An Indicator cannot be relabelled, a dynamic Factor definition cannot be synthesized,
and arbitrary Python Factor generation is forbidden. If no qualifying bridge exists in the exact Catalog Generation, verification
fails closed.

### Symbolic Search Space V1

`OnlySymbolicFactorSearchSpaceV1` is immutable and content-addressed. It contains exactly:

```text
schema_version = 1
catalog_generation_fingerprint
component_instances
external_source_terminals
candidate_output_contract
complexity_constraints
search_space_fingerprint
```

It contains no metric, score, best/current Candidate, result, mutable cursor, latest pointer, or adaptive feedback.

Each `OnlySymbolicComponentInstanceV1` binds an exact Calculation type reference and exact normalized parameters. Instances are a
finite, duplicate-free set sorted by their canonical descriptor. Parameter validation and normalization are performed only through
the existing `OnlyParameterSchema`/Definition resolver authority. Parameter ranges, mutation and inferred neighborhoods are absent.

Each external terminal binds an exact source identifier plus its existing Calculation-compatible output contract. This is a binding
surface, not a second Dataset schema. Final validity is decided by Calculation graph construction and normal Research resolution.

The candidate-output contract names an exact Factor component instance and output name. It is never inferred from node position or
ordering.

Complexity V1 freezes positive `max_nodes`, positive `max_depth`, and positive `max_occurrences_per_component`. Finite terminals,
finite component instances and these bounds make the search finite. Complexity is measured from the materialized canonical Graph:
node count, longest dependency depth and occurrences of each exact component-instance descriptor. Alias/text size is irrelevant.

### Exact Catalog Generation closure

The Search Space and ADR 0120 Experiment must bind the same exact Catalog Generation fingerprint. Verification resolves every
component in that exact generation and proves:

- exact kind, type ID and semantic version;
- provider layer is L1 Operator or L2 Indicator, except the single exact L3 Factor bridge;
- exact RESEARCH backend registration exists;
- fixed parameters normalize to the persisted assignment exactly; and
- the candidate output is the bridge's native Factor output.

L4 assets and generic enumeration of L3 Factors are forbidden. Provider discovery order, filesystem order and a current/latest
generation cannot affect closure.

### Typed graph generation

Generation connects external terminal outputs and previously materialized Calculation outputs to declared Calculation inputs using
existing type, nullability, dimension, semantic-type and unit compatibility. The prefilter is advisory. Every attempted node is
re-materialized through the exact existing Definition resolver, and `OnlyCalculationGraphDefinition` is the final authority for
dependencies, cycles, outputs, compatibility, Target restrictions, duplicate semantic nodes, canonical ordering and Graph identity.
Disagreement fails closed.

The formal Proposal is emitted only when the complete graph includes the explicit Factor bridge/output required by the Search Space.

### Symbolic Graph Proposal V1

`OnlySymbolicGraphProposalV1` contains exactly:

```text
schema_version = 1
search_space_fingerprint
canonical_graph_definition
candidate_output_reference(node_fingerprint, output_name)
proposal_fingerprint
```

Proposal identity hashes the complete payload in its own domain. The candidate output must resolve exactly in the Graph and retain
native Factor semantics. Proposal identity is Search provenance and never substitutes for Graph or Candidate identity.

Search Space and Proposal stores are immutable, canonical-JSON, content-addressed, put-once stores with exact verified loads.
Identical recommit returns `REUSED`; different content under an occupied identity, corruption, unsafe paths and unknown schemas fail
closed. No update, delete/recreate, latest, nearest, fuzzy or Store-scan lookup is public.

ADR 0120 SearchSpace and Iteration Proposal references become complete only when kind, schema version and fingerprint exact-load the
corresponding B3.2 authority. Missing, corrupt or mismatched references fail closed.

### Deterministic Enumeration V1

The only B3.2 algorithm is:

```text
algorithm_id = DETERMINISTIC_ENUMERATION
algorithm_semantic_version = 1
randomness_mode = NONE
seed = null
```

For each structural layer the stable semantic order is:

1. increasing materialized canonical node count;
2. increasing longest dependency depth;
3. canonical component-instance descriptor order;
4. canonical input-binding descriptor order; and
5. Graph fingerprint, then candidate node fingerprint/output name as tie-breakers.

Enumeration never depends on mapping/set insertion, Python hash randomization, object identity, provider/filesystem discovery order,
thread completion, Research completion, Evidence or Qualification. Changing this order requires a new algorithm semantic version.

An exact duplicate is only the same canonical Graph fingerprint plus the same candidate node fingerprint and output name. Duplicate
ephemeral construction paths collapse before Proposal persistence and before an ADR 0120 Iteration occurrence is created. No algebraic,
correlation, embedding or other heuristic equivalence exists in V1.

The first `N` unique Proposals are behavior. `proposal_limit` truncates that deterministic prefix. Search-space exhaustion and limit
completion are distinct structured outcomes.

### Budgets and non-adaptive execution

ADR 0120 budget dimensions remain separate:

```text
proposal_limit                 = maximum unique formal Proposals
research_evaluation_limit      = maximum Candidates sent through normal Research
qualification_attempt_limit    = maximum exact Research Results sent to Qualification
```

Proposal generation is complete and reproducible without executing Research. Research and Qualification results cannot enter
enumerator state or change a later Proposal. Evidence-driven parameter/search feedback belongs to B3.3.

### Normal Research and Qualification path

One Experiment binds one exact Dataset Snapshot and fixed Research evaluation template: Target semantics, Statistics membership,
Evidence membership and candidate-output interpretation. Candidate substitution produces a normal Research Definition/Specification;
the existing Resolver alone constructs Candidate identity. The normal Research command/runtime produces the immutable Research Result.
Search neither reads raw Parquet nor computes metrics.

An exact Research Result may be sent to the existing Qualification evaluator within budget. Search records only its exact
QualificationDecision reference through ADR 0120 and never copies PASS/FAIL. The closure-patch Candidate/Research locator/Result/
FreezeRelation subject chain remains mandatory. Qualification has no path back into enumeration.

### Structured failure boundary

B3.2 uses stable failure classifications for invalid space, missing Catalog component/backend, forbidden layer, invalid parameter,
illegal graph, invalid candidate output, exhaustion, each exhausted budget, and unrepresentable hypotheses. Missing capability never
generates or admits a new Operator, Indicator or Factor and never refreshes the Catalog.

## Consequences

Given the same exact Catalog Generation, Search Space, Deterministic Enumeration V1 implementation, `NONE` randomness contract and
budget, a fresh process produces the same ordered Proposal and Graph fingerprints. Evaluated Proposals retain a complete trace through
the normal Candidate, Research, Qualification and ADR 0120 authorities.

The first search spaces are intentionally constrained by admitted hypothesis-bearing Factor bridges. General formula-to-Factor
semantics would require a separately admitted L3 semantic contract and cannot be inferred by Search.

## Rejected alternatives

- Indicator-to-Factor relabelling or acceptance of an Indicator as a Research feature.
- A generic dynamic/unadmitted Factor wrapper or arbitrary generated Python Factor.
- Proposal fingerprint, Graph fingerprint or Search Space fingerprint as Candidate identity.
- A text/eval formula DSL, second AST/Graph or independent compatibility engine.
- Unbounded parameter ranges, mutation, seeded random, beam, evolutionary, genetic, RL or LLM search in B3.2.
- Evidence-adaptive ordering, ranking, top-k, best Candidate, Pareto front or Factor Pool.
- Search-owned Research execution, scientific metrics, Qualification comparison, status database or latest lookup.

## Out of scope

```text
B3.3 adaptive parameter search or Evidence feedback
Agent/LLM/model routing, RAG or literature retrieval
new L1/L2/L3 code or admission
Factor Pool, candidate ranking or novelty memory
HTTP/OpenAPI/Web
Backtest, SIM, LIVE, Broker or Trading Kernel changes
```

## Constitution consistency

Constitution Impact: **NO**.

This decision strengthens deterministic explicit inputs, one identity per authority, exact immutable evidence, traceability and
fail-closed behavior. It leaves Calculation, Candidate, Research, Qualification, Strategy, Promotion and LIVE authorities unchanged;
keeps Core market-agnostic; gives Agent no production or LIVE authority; and requires no Constitution change.
