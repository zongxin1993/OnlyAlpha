# P7.6.1 Remote Quality Factor Resolver Verification Closure

## Baseline

- Starting SHA: `b7f30baac25b79649d7001fe6010555f8e91151c`
- Starting commit: `Feat: P7.6 — Deterministic Parameter Sweep & Multi-Job Composition`
- Branch: `master`
- Version: `0.4.4`
- Date: 2026-08-14
- Initial worktree: only the user-provided untracked
  `prompts/P7.6.1RemoteQualityFactorResolverVerificationClosure.md`

The Prompt was preserved unchanged and treated as implementation input, not repository authority.

## Remote Failure Evidence

The `Layered Quality` run `31799551798` for exact SHA
`b7f30baac25b79649d7001fe6010555f8e91151c` failed only in the coverage job's `Research Factor branch coverage` step.
All 51 tests passed, but the mandatory 100% gate rejected total coverage `99.66%`: statement coverage was `99.55%` and branch
coverage was `100.00%`. Local reproduction produced the same result and identified the sole missing statement as
`packages/factor/onlyalpha-plugin-factors/src/onlyalpha_plugin_factors/registration.py:117`, the official Factor Definition
Resolver's delegation to the type-owned full Definition resolver.

The same remote run recorded PASS for static, build, Semgrep, all main canonical lanes including normal `research-factor`, and
the non-coverage `quality-gate` dependencies. Later coverage steps were skipped after the Factor coverage failure, and the final
quality gate therefore failed closed.

## Root Cause

P7.6 added backend-neutral Definition re-materialization and registered `OnlyOfficialFactorDefinitionResolver` for the official
Momentum and Cross-Section Percentile Factors. Calculation Foundation verified the generic Registry contract, while downstream
Sweep tests verified composition through the resolver. The official Factor package did not directly verify its registered resolver
through `OnlyCalculationRegistry.rematerialize_definition()`.

That was a verification ownership gap: downstream composition coverage cannot substitute for the semantic type owner's direct
proof of its own complete Definition reconstruction contract.

## Implementation

- `packages/factor/onlyalpha-plugin-factors/tests/test_research_factors.py`
  - verifies every official registration has the exact RESEARCH backend and exact type-owned Definition resolver;
  - compares direct and Registry-re-materialized Momentum Definitions in full, including fingerprint;
  - compares direct and Registry-re-materialized Percentile Definitions in full and proves uppercase/default normalization;
  - proves binding changes and parameter changes independently propagate into Definition identity;
  - proves invalid parameters fail closed through Registry → Factor resolver → ParameterSchema.
- `README.md` and `docs/roadmap.md`
  - record the narrow P7.6.1 verification closure without upgrading Research product capability.

Production semantic changes: **NONE**.

No production source, public API, persistence schema, Calculation schema, Graph schema, Result schema, coverage threshold, ADR,
Runtime factory, execution policy, or supported Factor was changed.

## Semantic Invariants Verified

- Official parameterized Research Factor registration equals exact type definition + RESEARCH backend + Definition resolver.
- Momentum direct resolution equals Registry re-materialization across the complete immutable Definition and fingerprint.
- Cross-Section Percentile direct resolution equals Registry re-materialization across the complete immutable Definition and
  fingerprint.
- `lower_is_better` re-enters Factor-owned ParameterSchema normalization as `LOWER_IS_BETTER`; default `AVERAGE` remains resolved.
- Same parameters with different semantic upstream bindings produce different Definition fingerprints.
- Same bindings with different normalized parameters produce different Definition fingerprints.
- Warmup, missing policy, timestamp, numeric semantics, execution shape, input/output semantic types and extensions are preserved.
- Unknown Momentum parameters and invalid Percentile direction fail closed through the Registry resolver path.

## Local Verification

| Command | Result |
|---|---|
| `uv run python -m pytest packages/factor/onlyalpha-plugin-factors/tests --import-mode=importlib -q --tb=short --maxfail=1` | PASS — 20 tests |
| `uv run ruff check packages/factor/onlyalpha-plugin-factors/tests/test_research_factors.py` | PASS |
| `uv run ruff format --check packages/factor/onlyalpha-plugin-factors/tests/test_research_factors.py` | PASS |
| `uv run python scripts/test_suite.py research-factor` | PASS — 57 tests |
| `uv run python scripts/test_suite.py research-factor --coverage` | PASS — 57 tests; line 100.00%, branch 100.00% |
| `uv run python scripts/test_suite.py research-sweep` | PASS — 27 tests |
| `uv run python scripts/test_suite.py calculation` | PASS — 58 tests |
| `uv run python scripts/verify.py agent --base b7f30baac25b79649d7001fe6010555f8e91151c` | PASS — 9 release-static checks; research-sweep 27, research-factor 57, research-job 30 tests |

The impact-aware planner classified the change as `COMPONENT`. Build was not selected locally; the mandatory remote workflow owns
the independent build gate. Final remote evidence is recorded after the exact implementation tree is fixed.

## Identity Impact

- Calculation Definition identity changed? **NO**
- Graph identity changed? **NO**
- Calculation fingerprint changed? **NO**
- Result identity changed? **NO**
- Job identity changed? **NO**
- Sweep Cell identity changed? **NO**
- Semantic version changed? **NO**

## Remote Verification

- Final implementation SHA: pending immutable commit.
- Layered Quality: **NOT EXECUTED for the implementation tree**.
- Final-SHA Certification: not required for this same-P7 verification increment and not executed.

## Closure Status

P7.6.1 = **NOT VERIFIED** while remote `Layered Quality` is pending.
