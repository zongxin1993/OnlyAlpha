# ADR 0095: Scientific Result Evidence and Candidate Identity

- Status: Accepted
- Date: 2026-08-20
- Related: ADR 0074, 0083, 0084, 0085, 0088, 0089, 0093; P8.4.2

## Context

P8.4.1 could author and persist an exact Research Specification, but publication membership, Candidate product identity,
Published Variable/Signal lineage, and portable Graph/series evidence did not cross the complete Run→fresh Worker→Runtime→Result→Artifact→Query chain.
Candidate identity was constructed inside Definition resolution from `resolved_definition_fingerprint`, which is not persisted in a Run.

## Decision

Research Specification V1 remains byte/identity compatible. Specification V2 adds only scientific evidence request membership:

```text
candidate_calculation_id
published_series[calculation_id, template_node_id, output_name]
signals[eligibility, entry, exit]
```

Its fingerprint is the canonical SHA256 of the complete V2 document. Publication intent therefore changes Research product identity while an unchanged
Dataset+Graph Calculation identity remains reusable.

The sole Candidate identity constructor is `only_research_candidate_fingerprint()` with canonical payload:

```text
schema_version
specification_fingerprint
candidate_calculation_id
assignment
calculation_fingerprint
```

The Result Plan V2 owns exact Dataset, Calculation/Graph, Candidate→Statistics, Published Series, Signal, and Statistics membership. Research Result V2
contains only exact Calculation Result and Statistics Result references. Its content fingerprint hashes those canonical reference sets; its Result
fingerprint hashes Result Plan fingerprint plus Result content fingerprint. Timestamps never enter semantic identity.

Scientific Artifact V2 is profile `RESEARCH_SCIENTIFIC_V2` with exact `market.parquet`, `variables.parquet`, `signals.parquet`, `statistics.parquet`, and
`graphs.json`. Each section has separate logical fingerprint and byte SHA256. Artifact semantic identity hashes the Research Result identity and canonical
section path/row-count/logical-fingerprint evidence, excluding compression, path, byte hash, and audit time. Verified load is self-contained.

Query and HTTP remain Artifact-only projections. V1 scientific requests fail explicitly with `SCIENTIFIC_EVIDENCE_NOT_AVAILABLE`.

Internal Predicate registrations are installed whenever an exact Specification or Research Runtime Calculation registry is composed. Predicate remains
internal and does not become a public authoring catalog or a separate Registry/Runtime/Store.

## Consequences

- Run/PostgreSQL persists V2 through the existing canonical Specification payload; no evidence tables are added.
- Forward migration `0005_research_specification_v2_admission` only expands the existing Run version check from V1 to V1/V2; it adds no semantic column or table.
- Calculation Result and Statistics Result remain the only value authorities.
- Research Result remains the composition authority; Artifact remains a portable projection.
- V1 Specification, Result, Artifact, and their identities remain readable and unchanged.
- No ScientificEvidence, Candidate, Signal, Graph, or Predicate Result Store exists.
