# P7.10.x Research Result Coverage & Current-Truth Closure

## 1. Current Truth

- Base branch: `master`
- Base SHA: `724a777e6bdcd41d0e504fa45de81c071955b2dc`
- Resulting SHA: no new immutable SHA; this report describes the uncommitted task worktree on the base SHA
- Latest commit: `P7.10.1 quality/dependency closure`
- Version: `0.7.10`
- Environment: macOS, Python 3.12.12, pytest 9.1.1, Coverage.py 7.15.2
- P7 state: `IN_PROGRESS`; P7 Final Certification is `NOT COMPLETE`
- Current semantic increment: `P7.10 — VERIFIED LOCALLY`; this P7.10.x maintenance closure is not a semantic increment
- Initial working tree: the user-provided P7.10.x Prompt was the only pre-existing untracked path
- Initial Layered Quality: the local canonical Research Result coverage step reproduced the known failure; remote exact-SHA workflow
  state could not be queried from the restricted environment

## 2. Root Cause

The failure reproduced with all 28 existing Research Result tests passing while total pytest-cov coverage was 82.84%, line coverage
was 86.65%, and branch coverage was 70.00%. Missing evidence concentrated in strict Plan/Manifest/Outcome parsing, physical
corruption, upstream referential integrity, admission error normalization, staged publication, rename failure, and race convergence.
The same baseline persisted on the current pytest 9.x lock, so the dependency upgrade was not the root cause. No production defect
was proven; this was a defensive correctness-evidence gap.

## 3. Contract Gaps Found

- exact lower-case SHA256, mapping/list/integer/datetime, nested schema, canonical membership, and Outcome validation;
- symlink, malformed JSON, non-object JSON, unexpected/missing files, and path identity corruption;
- Statistics logical identity, Statistics Result identity, single-Dataset, manifest Dataset linkage, content, and Result linkage;
- wrong admission type, ordinary exception normalization, and formal upstream error preservation;
- stage read-back failure, rename failure, same-result race reuse, concurrent equal publication, staging cleanup, deterministic
  conflict, and existing/corrupt authority immutability.

## 4. Changes Made

### Production

Production semantic changes: **NONE**.

### Tests

Added parameterized model/serialization validation and expanded assembler/store destructive-path evidence. Failure tests assert stable
error codes plus negative durable state: absent targets, cleaned staging, unchanged corrupt/existing bytes, and one converged
authority.

### Verification Infrastructure

No verification script, workflow, lane, threshold, or coverage configuration changed.

### Documentation

Corrected active README and roadmap P6 certification wording. Historical P6 reports remain unchanged because their pending verdicts
were accurate when written.

## 5. Research Result Coverage

Before:

- total: 82.84%
- line: 86.65%
- branch: 70.00%
- tests: 28 passed

After:

- total: 99.77%
- line: 99.70%
- branch: 100.00%
- tests: 93 passed

Threshold unchanged: **YES** (`line >= 95%`, `branch >= 90%`). Coverage exclusions added: **NO**.

## 6. Correctness Evidence

Missing remains `RESEARCH_RESULT_NOT_FOUND`; malformed or tampered durable state is `RESEARCH_RESULT_CORRUPT` and is never rebuilt
or overwritten. Admission rejects malformed callers with `RESEARCH_RESULT_INVALID`. Exact upstream logical/Result identities and one
Dataset Snapshot are revalidated. Manifest Dataset/content/Result linkages fail closed. Equal re-entry and race losers reuse one
verified authority; differing deterministic content conflicts without changing existing bytes. Stage verification and rename
failure publish no target and leave no staging directory.

## 7. Architecture Review

- Business semantic change? **NO**
- Research authority ownership change? **NO**
- Dataset identity change? **NO**
- Statistics identity change? **NO**
- Calculation identity change? **NO**
- Artifact contract change? **NO**
- Query contract change? **NO**
- API route change? **NO**
- Runtime activation? **NO**
- Engine lifecycle change? **NO**
- Trading economics change? **NO**
- Coverage threshold weakened? **NO**
- Security gate weakened? **NO**

## 8. Documentation Closure

`README.md` and the active P6.6 roadmap heading now record P6 as `DONE / CERTIFIED`. P7 remains `IN_PROGRESS`, the current semantic
increment remains P7.10, Research and Live Runtime factories remain unsupported, Web UI/Scheduler/Optimizer remain unimplemented,
P7 Final Certification remains incomplete, and P8 is not declared ready. Historical evidence documents were intentionally preserved.

## 9. Verification

Targeted:

- `uv run python scripts/test_suite.py research-result --coverage` — PASS, 93; total 99.77%, line 99.70%, branch 100.00%
- `uv run python scripts/test_suite.py research-result` — PASS, 93
- Research Result architecture and test-lane contracts — PASS, 19

Affected:

- `uv run python scripts/verify.py agent --base 724a777e...` — `IMPACT VERIFIED`, 6 gates; Ruff, format, Mypy, Research Query 72,
  Research Artifact 53, Research Result 93
- Logs: `test-results/verification/20260816T095811Z-724a777e6bdc-8176/`

Broad:

- `core-full --coverage` — PASS, 1,926 passed / 1 skipped; total 84.45%
- Calculation 58, Research Calculation 127, Research Factor 57, Research Evaluation 96, Research Result 93, Research Artifact 53,
  Research Query 72, Research Job 30, Research Sweep 27, and Research Dataset 36 coverage lanes — all PASS
- `uv build --all-packages` — PASS for all 10 workspace distributions

Remote:

- Not executed for this uncommitted worktree. GitHub Actions status lookup was unavailable in the restricted environment.

## 10. Remaining Issues

### Blocking

- No immutable resulting SHA exists yet, so exact-SHA Layered Quality, dependency audit, Semgrep, CodeQL, and quality-gate evidence
  cannot exist for this worktree.

### Non-blocking

- The unchanged dependency lock retains the P7.10.1 dependency closure; no dependency or security configuration changed.

### Pre-existing

- None observed outside the known Research Result coverage failure, which is locally closed.

### Remote CI Pending

- Commit/push and exact resulting-SHA Layered Quality plus CodeQL remain required before claiming a restored clean development
  baseline.

## 11. Final Verdict

`LOCAL VERIFIED — REMOTE QUALITY GATE PENDING`

This verdict is **NOT** P7 Final-SHA Certification.
