# ADR 0128: Multi-Subject Research Action Authorization Composition

- Status: Accepted
- Date: 2026-09-16
- Related: ADR 0088, 0089, 0095, 0104, 0124–0127
- Constitution Impact: NO

## Context

A legal Research Specification can resolve to one or more canonical Evaluation Intent Subjects. The original Read-to-Act path
persisted one Decision and one subject guard per Product Command, so it could not authorize a multi-Candidate Specification without
either selecting one representative subject or broadening one subject's authorization. Both would violate exact scientific identity
and deterministic admission.

## Decision

`OnlyExactEvaluationIntentSubjectV1` remains the sole scientific evaluation-intent equality. `resolve_all()` derives the complete,
unique tuple ordered by subject fingerprint. `OnlyResearchEvaluationSubjectSetV1` is only a command-scoped composition identity; it
does not redefine equality or own scientific facts.

Each subject retains one immutable Decision V2. One Product Command owns one immutable Decision Group V1 containing the canonical
ordered Decision bundles and binding the exact Specification and complete subject-set fingerprint. Its action predicate is derived:
the unchanged Research action is actionable if and only if every member outcome is `ADMIT`. `REUSE`, `SUPPRESS`, `REVIEW`,
`FAIL_CLOSED`, a missing/corrupt member, subject mismatch, or incomplete/stale/unavailable member proof blocks the whole action. The
group introduces no new Novelty Policy judgment.

Research Submit V4 binds the group fingerprint. Admission V2 persists one aggregate parent and one immutable member row per subject.
The parent, complete member set, one Research Run, and Product Receipt commit in the existing PostgreSQL transaction. One Run keeps
exactly one Runtime Work Binding; all subjects must bind the same Runtime Generation or admission fails closed.

Concurrency is guarded per subject, not per set. PostgreSQL advisory transaction locks are acquired for every member in ascending
subject-fingerprint order before conflict/freshness checks. Overlapping sets therefore serialize on every shared member without a
deadlock ordering cycle; disjoint sets do not conflict merely because unrelated source history advanced.

Migration 0025 is forward-only. Historical Decision V1/V2, Submit V3, Admission V1, Query V3, and Projection V7 remain readable with
their original meanings and fingerprints. Released historical Runtime bindings are never silently reactivated; a retry fails closed
with an explicit recovery-required error unless an exact committed Receipt already proves the authoritative Run.

Production composition must provide Product Command, Novelty Decision, Memory projection, and Runtime generation authorities.
Ungated behavior is available only through the explicit test/historical constructor flag and is not enabled by the production root.

## Rejected alternatives

- One representative Decision for an N-subject Run: broadens authorization beyond its exact subject.
- A subject-set-only advisory lock: misses partial overlaps such as `[A,B]` and `[B,C]`.
- Partial execution of admitted members: mutates the frozen Specification and Result Plan.
- Reinterpreting Decision V2 or Admission V1 in place: breaks historical replay.
- Automatic Decision creation inside Research admission: creates a second Policy evaluator at the action boundary.

## Consequences

Multi-Candidate Product, Symbolic Search, and Parameter Search retain the shared Research command seam and create at most one unchanged
Run only after complete per-subject authorization. The additional composition and normalized persistence are essential complexity for
cardinality, concurrency, replay, and recovery; no new scientific, Run, Runtime, or Product Command authority is introduced.
