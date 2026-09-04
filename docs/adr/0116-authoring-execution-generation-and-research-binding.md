# ADR 0116: Authoring Execution Generation and Research Binding

- Status: Accepted
- Date: 2026-09-04
- Related: ADR 0075, 0086, 0088, 0090, 0108, 0110, 0111, 0112, 0115

## Context

ADR 0115 binds a private candidate's Git Snapshot, Provider content and Catalog generation into durable Research authoring
provenance. That linkage does not by itself prove execution: the normal Research Worker resolves Calculations from the Provider set
installed when its process starts, while an isolated candidate loader currently exits after producing a descriptor. A Run could
therefore carry exact candidate provenance while being executed by another process generation.

The missing fact is neither Calculation semantics nor another Research result. It is the immutable process-composition fact that
selects which exact executable Provider set may claim and execute a Run.

## Decision

OnlyAlpha defines an immutable **Authoring Execution Generation**. Its fingerprint derives from the exact source Snapshot,
candidate artifact/content, Candidate Provider identity/content, complete Catalog generation and the OnlyAlpha execution-contract
version. Operational paths, hostnames, PIDs, branch names and worker IDs are excluded.

The authorities remain separate:

| Fact | Authority |
|---|---|
| source revision/tree | Git Snapshot |
| candidate executable content | verified candidate artifact/Provider content |
| authoring execution generation | generation admission service |
| Run/Attempt/lease | existing Research Product/PostgreSQL authority |
| Research Result/Evidence | existing immutable Research stores |
| StrategyRevision | verified Strategy Freeze |
| Runtime Catalog activation | deployment/Catalog authority |

A Product Research Run carrying authoring provenance must bind one exact execution-generation fingerprint. A normal production
Research Worker may claim only Runs without an authoring generation. An authoring Worker may claim only Runs whose generation
fingerprint equals its verified process generation. Claim filtering occurs inside the existing transactional Attempt authority;
claiming first and rejecting later is forbidden because it would consume another generation's retry budget.

`packages/onlyalpha-authoring-execution-worker/` is the independently buildable non-plugin component that verifies and hosts one
authoring process generation. Git/source-path and candidate-artifact handling terminate in this component and the private authoring
repositories. Core receives only the stable generation identity and claim selector; it never imports private assets, scans Git,
mutates `sys.path`, or resolves a path as semantic identity.

Controlled local Research may build the generation from an exact clean source checkout as allowed by ADR 0111. Distributed or
production-like deployment uses an immutable content-addressed artifact. Both modes must produce the same Provider content and
Catalog generation identities. The operational locator is never part of semantic or generation identity.

The Worker validates its generation before presence registration or claim. It then establishes one immutable Calculation registry
for its process lifetime. Restart reconstructs the same generation from its immutable manifest and exact source/artifact; missing,
dirty, mismatched or corrupt input fails before claim. Active Runs are never rebound. A new generation is available only to new
Runs.

Admission may reuse Research Evidence only when the materialized/admitted candidate has the same semantic identities and executable
Provider content fingerprint as the researched generation. Any content drift requires a new generation, Run and Evidence. Release,
Catalog activation and Strategy promotion remain separate transitions.

Research-to-Runtime continuity means preserving the exact StrategyRevision, Calculation semantic identities, implementation
fingerprints and Catalog binding across a new immutable Runtime generation. It never means promoting a worktree, reusing the
authoring process as LIVE, mutating modules in place, or granting an Agent activation authority.

## Consequences

An Evidence reference now has a causal execution binding rather than only a matching provenance assertion. Normal and authoring
Workers can safely share the existing Run/Attempt tables because the transactional claim predicate prevents cross-generation
execution. The new component adds deployment and artifact-lifecycle work, but creates no second Calculation SPI, Research engine,
Run store or Evidence authority.

## Rejected alternatives

- Trusting client-supplied provenance without a Worker generation check.
- Claiming any Run and failing it after discovering a generation mismatch.
- Loading Git paths or arbitrary Python modules in Core or the HTTP server.
- `PYTHONPATH` mutation, `importlib.reload`, or active-process module replacement.
- Treating the authoring Worker, worktree, PR or artifact path as StrategyRevision or Runtime authority.
- Automatically promoting Research PASS to Catalog, SIM or LIVE activation.
