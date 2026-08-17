# P8.0 Research Specification & Resolution Boundary — Implementation Report

- Date: 2026-08-17
- Task base SHA: `6b051705c7638dc3acb02dde430c3c2348121811`
- Authority: local implementation evidence; not P8 certification

## Goal and scope

Establish a portable, strict, versioned Research request document and a pure deterministic compiler into the existing P7
`OnlyResearchWorkloadPlan`. Preserve every existing Dataset, Calculation, Job/Sweep, Statistics, Result, Artifact and Runtime authority.

The implementation adds Specification schema/identity, stable errors, exact type/backend admission, symbolic series resolution,
singleton Statistics broadcasting and ephemeral candidate lineage. It extracts the P7 Sweep graph materialization algorithm into one
shared materializer used by Direct and Sweep paths.

## Architecture and identity

```text
OnlyResearchSpecification (canonical request SHA)
  → exact Calculation Registry admission
  → shared Graph Template Materializer / existing Sweep Planner
  → existing Job and Sweep Plans
  → symbolic Feature/Target selectors to existing exact Series References
  → BROADCAST_SINGLETON Statistics Plans
  → automatically composed existing Research Result Plan
  → existing OnlyResearchWorkloadPlan
```

Specification identity includes symbolic IDs and the complete request document. Graph identity excludes symbolic IDs, Dataset and backend
provider implementation. Research Calculation identity remains Dataset-bound. Resolution evidence maps calculation ID and typed assignment
to exact Graph/node/Calculation/Statistics identities but is ephemeral and has no store or fingerprint.

## Files

- `src/onlyalpha/research/specification/`: schema, stable error boundary and resolver.
- `src/onlyalpha/research/workload.py`: canonical application composition ownership; Runtime path re-exports the same class.
- `src/onlyalpha/research/runtime_errors.py`: shared Research plan/runtime failure authority; Runtime path re-exports it.
- `src/onlyalpha/research/sweep/materialization.py`: unique materialization implementation and symbolic-node evidence.
- `src/onlyalpha/research/sweep/planning.py`: delegates every cell to the shared materializer.
- `tests/research/specification/`: schema, typed serialization, identity, fresh-process, admission, Sweep, Statistics and lineage tests.
- `tests/runtime/research/test_product.py`: full manual-vs-Specification Runtime equivalence.
- `tests/architecture/test_research_specification_boundaries.py`: dependency and implementation uniqueness gates.
- `docs/adr/0088-research-specification-and-resolution-boundary.md`: stable architectural decision.

## Verification

Task Gate planning used:

```text
uv run python scripts/verify.py plan --base 6b051705c7638dc3acb02dde430c3c2348121811
```

The plan selected `FULL_LOCAL` because new Specification paths fail closed as unknown impact and an architecture test is shared test
infrastructure. No `scripts/test_suite.py`, `scripts/verify.py`, CI matrix or coverage-infrastructure file was modified, so this was impact
escalation rather than verification-infrastructure self-change.

Focused coverage command passed 90 tests with:

```text
Specification + shared Materializer: 100% line, 100% branch
```

Final verification used:

```text
uv run python scripts/verify.py agent --base 6b051705c7638dc3acb02dde430c3c2348121811
```

Result: `IMPACT VERIFIED`; 31 gates passed. Evidence:
`test-results/verification/20260817T044837Z-1aaff921dc6b-13379/`.

This included release static checks, Web static/unit/build/E2E, all selected Research/Calculation lanes, `core-full` (1995 collected),
recovery, Sim recovery, A-share, MiniQMT contract and build. Web E2E required running outside the filesystem sandbox solely to bind its
localhost test server.

During verification, the broad Research architecture gate correctly rejected a Resolver-to-Runtime reverse dependency. Ownership of the
application `OnlyResearchWorkloadPlan` and shared Research execution errors was moved to `onlyalpha.research`, with the existing Runtime
imports retained as re-exports. A concurrently landed P7 Final Certification documentation update had also left its truth-consistency test
asserting P7.12; that test was updated to the certified P7/current P8 state before the final successful gate.

## Known limitations and out of scope

V1 supports one exact Dataset Snapshot, finite explicit candidates and singleton-only Statistics broadcasting. It deliberately has no
Dataset availability load, catalog/alias, many-to-many join, durable resolution store, Research Run, database, scheduler/worker, API/Web,
Backtest promotion implementation or Strategy definition. Graph Template remains publicly owned by the P7 Sweep package for compatibility;
the materialization implementation is nevertheless singular and shared.
