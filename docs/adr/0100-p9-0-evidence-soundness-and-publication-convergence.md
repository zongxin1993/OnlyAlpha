# ADR 0100: P9.0 Evidence Soundness and Publication Convergence

- Status: Accepted
- Date: 2026-08-25

## Context

P9.0 already separated Calculation semantics, Result content, Research producer provenance,
RESEARCH/TRADING equivalence evidence, Candidate Freeze, Strategy Revision identity, and
PostgreSQL operational records. Three remaining gaps could still turn a claim or a partial
publication into authority: a caller-built Research execution projection could mint producer
Evidence, a fixed six-observation equivalence corpus could miss parameter-dependent state
transitions, and a frozen Revision could survive while its only Freeze proof existed in an
unavailable PostgreSQL projection.

## Decision

1. `OnlyResearchCalculationExecution` is a public data projection, not Evidence authority.
   Only the authoritative Research Calculation Executor may mint the private, module-sealed
   verified-execution capability after exact implementation planning, actual provider execution,
   and successful output assembly. Admission-grade Execution Evidence publication requires that
   capability and exact Result/Graph/Dataset/node linkage. The public Research surface exposes a
   read authority and no public Evidence writer.

2. Calculation equivalence remains a finite, deterministic, system-owned engineering admission
   contract, not a mathematical proof over every input. Production accepts only an exact node.
   The system derives its profile and materialized corpus from the resolved Definition, including
   minimum observations, exact period/warmup parameters, rolling-window eviction, recursive
   state, first-ready, and post-ready observations. Callers cannot inject a runner, profile,
   corpus, expected output, comparison, or tolerance.

3. Strategy executable semantic truth is the verified Strategy Revision plus at least one
   immutable verified `OnlyStrategyFreezeRelation`. A relation binds the sole
   `strategy_fingerprint` to the exact Candidate, Research Result, Research Execution Evidence,
   Admission Evidence, and Equivalence Evidence. Actor, time, comment, and PostgreSQL row identity
   are audit projection metadata and do not change either Strategy identity or relation identity.

4. Semantic publication writes the immutable Freeze relation before making the Revision readable.
   A Revision without a valid relation is not executable. One Revision may have multiple relations,
   so different Candidates may converge on the same `strategy_fingerprint` without creating a
   second Strategy identity.

5. PostgreSQL `strategy_catalog` and Freeze rows are operational/query projections. Projection
   failure does not roll back immutable semantic truth and does not create another semantic truth.
   Reconciliation verified-loads semantic Revision/relations and idempotently converges missing
   projection rows. Conflicting projection content fails closed. Filesystem/PostgreSQL 2PC, XA,
   pseudo-atomic rollback, and semantic repair from PostgreSQL are forbidden.

6. Runtime, Cluster, Backtest, and SIM retain only the read-only Strategy capability. They do not
   receive semantic publishers, PostgreSQL projection writers, reconciliation, or repair powers.
   Promotion ordering remains the `previous_record_fingerprint` predecessor chain, and Strategy
   checkpoint state contracts remain unchanged.

## Consequences

- A caller-constructed or mutated execution DTO cannot mint Research producer Evidence.
- Two actually executed implementations may produce the same Result identity and distinct
  Execution Evidence identities; actual output drift remains a deterministic Result conflict.
- A backend divergence at first-ready, rolling eviction, after warmup, or in a later recursive
  transition is inside the certification horizon and rejects admission.
- A complete semantic Freeze remains executable during PostgreSQL outage and can reconstruct its
  projection. A stray or partially published Revision fails closed.
- `strategy_fingerprint` remains the sole Strategy execution identity, while Freeze remains the
  sole Candidate-to-Strategy transition authority.
