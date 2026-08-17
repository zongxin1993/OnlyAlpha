# ADR 0088: Research Specification and Deterministic Resolution Boundary

- Status: Accepted
- Date: 2026-08-17
- Related: ADR 0069, 0072–0076, 0079, 0082–0086

## Context

P7 established exact immutable Dataset, Calculation, Job/Sweep, Statistics, Research Result, Artifact and finite Runtime authorities. Its
application input is a manually composed `OnlyResearchWorkloadPlan`, which is intentionally exact but is not a portable user-intent
protocol. Web, HTTP, schedulers and future durable Research Runs need one versioned Core document that can be admitted without inventing
parallel Calculation, Statistics or Result semantics.

Research Calculation identity is Dataset-bound. Future Research-to-Backtest selection therefore cannot promote a
`calculation_fingerprint`; it must preserve the backend-neutral canonical Calculation Graph identity while keeping Dataset, Target and
Statistics as Research evaluation context.

## Decision

`OnlyResearchSpecification` schema v1 is the immutable portable request document. It contains exactly one lower-case SHA-256 Dataset
Snapshot reference, calculation-local symbolic IDs, existing serializable Graph Templates, optional finite explicit Sweep dimensions,
and Statistics specifications with symbolic Feature/Target selectors. It contains no run/runtime/engine/user/time/path/worker/database
state. Unknown fields and every schema version other than integer `1` fail closed. Dataset aliases, `latest`, fuzzy lookup, Python class
paths and hidden catalog resolution are forbidden.

Every template node uses existing exact `(kind, type_id, semantic_version)` references and the existing type-preserving Calculation scalar
codec. `OnlyCalculationRegistry` remains the sole type authority. Resolution separately proves exact semantic type existence and exact
RESEARCH backend availability, then complete Definition materialization continues exclusively through the type-owned
`rematerialize_definition()` contract. Backend provider identity does not enter Graph semantics.

Direct calculations and Sweep planning share one `OnlyResearchGraphTemplateMaterializer`. The existing public Graph Template remains in
`onlyalpha.research.sweep` for this increment because it is an established P7 serializable public contract and moving its error/public
boundary would add compatibility churn unrelated to semantic correctness. There is one implementation and one validation authority.
Materialization returns ephemeral `template_node_id -> node_fingerprint` evidence in addition to the existing canonical Graph; it adds no
fingerprint or store.

Statistics selectors are `(calculation_id, template_node_id, output_name)` and resolve to existing exact Feature/Target Series References.
Feature ports must be FACTOR `FACTOR_VALUE` or `FACTOR_SCORE`; Target ports must be TARGET `TARGET_VALUE`. Runtime execution retains
defensive verification. V1 expansion is exactly `BROADCAST_SINGLETON`: `1×1`, `N×1`, and `1×N` are allowed; `N×M` where both sides exceed
one is ambiguous and fails closed. Cartesian, zip and assignment joins are not inferred. The Result Plan is automatically composed from
all resolved Statistics identities.

`OnlyResearchSpecificationResolver` returns `OnlyResearchSpecificationResolution`, containing the request fingerprint, the existing
`OnlyResearchWorkloadPlan`, candidate lineage and Statistics lineage. Resolution evidence is ephemeral and is not a durable or semantic
authority. Runtime still executes only the workload. Stable resolver errors expose phase, code and detail while preserving the original
cause.

The Specification fingerprint is SHA-256 of the existing canonical JSON projection of the full request document. Symbolic ID changes may
change request identity while leaving resolved Graph, Calculation, Statistics and Result identities unchanged. Candidate lineage records:

```text
calculation_id + typed assignment
→ exact canonical Graph + graph_fingerprint
→ Dataset-bound Research calculation_fingerprint
→ exact Statistics references
```

The Graph fingerprint is the promotion-ready runtime-neutral candidate semantic identity. Research Calculation fingerprints remain
Dataset-bound; Target, Dataset, Statistics and Research Result are evaluation context and are not promoted as future Strategy semantics.

## Consequences and invariants

- Specification is request identity, never Result, Calculation, Job, Runtime or durable execution authority.
- Resolver performs pure deterministic compilation and does not load a filesystem Dataset.
- Exact type resolution and RESEARCH execution capability are separate fail-closed checks.
- Direct and Sweep materialization cannot drift because both call one materializer.
- The resolved execution contract remains `OnlyResearchWorkloadPlan`; no V2 execution plan exists.
- Same Graph on different Dataset Snapshots has equal Graph identity and different Research Calculation identity.
- Future promotion must preserve the exact selected Graph fingerprint and must not promote Research evaluation context.
- P8.0 owns no PostgreSQL, Run/Submission Store, scheduler, worker, lease, retry, API, Web, Dataset Catalog or Trading state.

## Rejected alternatives

Rejected alternatives include Web/Pydantic semantic DTOs in Core, duplicate Graph/template materialization, latest/friendly type lookup,
mutating resolved Definition parameters, exposing direct-jobs/sweeps as user protocol, persisting resolution evidence, using Dataset-bound
Calculation identity for promotion, implicit many-to-many Statistics joins, and user-authored Result membership.
