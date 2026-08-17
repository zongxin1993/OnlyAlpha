# P8.0.1 Research Specification Engineering Closure & Verification Integration

- Date: 2026-08-17
- Task base SHA: `5450590a3c93005462e9abfc64fd3785d46b2be7`
- Current implementation HEAD: `5450590a3c93005462e9abfc64fd3785d46b2be7` with an intentional dirty Task worktree
- Authority: local Task Gate implementation evidence; not P8 Final-SHA certification

## Task Gate

Goal: turn the accepted P8.0 Specification semantic boundary into an exact typed, independently testable, impact-aware and mandatory
verification boundary without changing P8.0 semantics.

Modification scope: Resolution typing, canonical test/coverage lane, impact resolver, verification contract tests, normal CI, release lanes,
Final-SHA Certification matrix and current-truth documentation.

Impact scope: Specification itself; the shared WorkloadPlan consumer boundary; exact upstream Calculation, Dataset identity, Sweep,
Evaluation, Result Plan and Job semantics; Research Runtime equivalence evidence.

Required behavior: exact `OnlyResearchWorkloadPlan` output, 100% line/branch Specification coverage, component-scoped known impact, transitive
consumer propagation, fail-closed unknown impact, verification-infrastructure self-escalation and mandatory CI/certification evidence.

Expected acceptance: `research-specification`, its coverage command, affected Ruff/Format/Mypy, architecture/verification/certification
contracts, deterministic planning and the verification-infrastructure full local agent gate.

Expansion triggers: a changed semantic fingerprint, new authority, persistence/recovery boundary, unknown impact path or a real regression in
the full-local gate. None was required.

Out of scope: PostgreSQL, Run/Submission state, scheduler/worker/lease/retry/cancellation, API/Web control, Dataset catalog, promotion,
Strategy/Sim/Live changes, multi-lock dependency audit and P8.0 semantic redesign.

## Known gaps at the base

- `OnlyResearchSpecificationResolution.workload` escaped as `object` despite the ADR requiring `OnlyResearchWorkloadPlan`.
- Specification had no canonical lane or independent coverage authority.
- Specification source, tests, WorkloadPlan and its architecture test were unknown/shared verification impact.
- Sweep, Calculation, Dataset identity, Evaluation contract and Result Plan changes did not select Specification consumer evidence.
- PR/main/release/Final-SHA matrices and coverage omitted the public Specification compiler boundary.

## Type and authority closure

`OnlyResearchSpecificationResolution.workload` is now exactly `OnlyResearchWorkloadPlan`, verified through `typing.get_type_hints()` and
Mypy. Consumers directly access `direct_jobs`, `sweeps`, `statistics_plans` and `result_plan` without a cast or defensive `isinstance()`.

`src/onlyalpha/research/workload.py` remains the canonical owner. Specification compiles to that Runtime-independent application contract;
the Research Runtime consumes it. No Runtime, database, Run, store, checkpoint or second semantic authority was introduced.

## Canonical lane and coverage

`research-specification` owns:

- `tests/research/specification` for schema, serialization, identity, admission, resolution and lineage;
- `tests/architecture/test_research_specification_boundaries.py` for the Research/operational/trading firewall and single Materializer;
- the exact Runtime node proving full manual-P7-versus-resolved-workload equivalence.

Coverage owns only `src/onlyalpha/research/specification`; Sweep Template/Materializer remains under `research-sweep`. The formal threshold is
100% line and 100% branch. Local evidence: 34 passed, lines 100.00%, branches 100.00%.

## Impact and transitive dependency mapping

- Specification source/tests/exact architecture test → `research-specification`, STATIC, COMPONENT.
- `research/workload.py` → `research-specification` + `research-runtime`, STATIC, COMPONENT.
- Sweep/Materializer → existing Runtime/Sweep/Job consumers + `research-specification`.
- Research Calculation and Calculation Foundation → their existing consumers + `research-specification`.
- Factor provider and Research Job contracts → their existing consumers + `research-specification`.
- Dataset `strict.py`/`manifest.py` identity/admission → `research-specification`; Dataset physical store changes do not reverse-propagate.
- Evaluation Definition/Plan/Reference → `research-specification`; Statistics Result Store physical changes do not reverse-propagate.
- Result Plan → `research-specification`; Result/Artifact Store and Query implementation do not reverse-propagate.

The exact Specification architecture test is excluded from the generic `tests/architecture/**` FULL_LOCAL fallback and is owned by the
component rule, which also requests Import Linter. Unknown production paths still select `FULL_LOCAL`, and changes to `scripts/test_suite.py`,
`scripts/verify.py`, workflow files or verification contract tests still select the complete release lanes/checks.

## CI, release and certification integration

`research-specification` is in deterministic `RELEASE_LANES` order. Both PR and main canonical matrices in `quality.yml` include the lane,
and normal coverage runs its mandatory coverage command. `certification.yml` includes the lane in the exact-SHA matrix and independently
requires `research-specification --coverage`. Contract tests freeze both workflow obligations.

## Semantic identity and Runtime equivalence

No Specification serialization, Specification fingerprint, Graph fingerprint, Dataset-bound Calculation fingerprint, Statistics
fingerprint, Research Result fingerprint, Artifact content identity or determinism algorithm changed. Existing identity regressions and the
full Runtime equivalence regression are mandatory members of the new lane and passed.

## Verification

- Initial plan at the Task base: `DOCS_ONLY` for the user-provided untracked Prompt.
- `research-specification`: 34 passed.
- `research-specification --coverage`: 34 passed; line 100.00%; branch 100.00%.
- Verification/lane/certification/layering contract tests: 70 passed.
- Affected Ruff and Ruff Format: passed.
- Affected Mypy: passed for Specification, WorkloadPlan and Research Runtime consumers.
- Final plan: `VERIFICATION_INFRASTRUCTURE`, complete release lanes/checks selected.
- Final `scripts/verify.py agent`: `IMPACT VERIFIED`, 32 gates executed. It passed all release static checks, Web static/unit/build/E2E,
  17 canonical lanes, `core-full` (2001 collected), recovery (330 collected), Sim recovery, A-share, MiniQMT contract and all-package build.
  Evidence: `test-results/verification/20260817T061335Z-5450590a3c93-31052/`.

## Final Task Gate verdict

`TASK COMPLETE — P8.0.1 ENGINEERING CLOSED LOCALLY / P8.1 READY`. The exact type, canonical ownership, verification graph, CI and
Final-SHA mandatory integration are complete, and verification-infrastructure self-change passed the full-local closure. This verdict is
local Task Gate evidence; it does not claim P8 certification or implement P8.1.
