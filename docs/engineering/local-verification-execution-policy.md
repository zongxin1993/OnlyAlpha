# Local Verification Execution Policy

This document defines how developers and AI agents execute OnlyAlpha verification locally. It does not create a new quality gate and does not change canonical test semantics.

Formal acceptance levels remain:

```text
Task Gate
Phase Gate
```

The source of canonical lane semantics remains:

```text
scripts/test_suite.py
```

The source of impact selection remains:

```text
scripts/verify.py
```

The budgeted local execution policy is:

```text
scripts/local_verify.py
```

## 1. First principle

The objective is not to run fewer proofs. It is to put each proof at the correct authority boundary.

```text
Targeted local feedback
+
Affected local proof when affordable
+
Required heavy proof in GitHub CI
+
Nightly heavy quality
```

A required test that is deferred to CI is not considered passed locally. It must remain explicit as `CI_REQUIRED` until GitHub provides real evidence.

## 2. Four execution levels

These are execution levels, not five formal quality gates.

### Level 0 — Inner-loop targeted verification

Immediately after an edit, run the smallest direct test set that can expose the current implementation error.

Default pytest shape:

```bash
uv run pytest <direct-targets> -q --tb=short --maxfail=1
```

Use targeted Ruff/Mypy only for changed Python surfaces when useful.

Do not start with repository-wide pytest.

### Level 1 — Impact-aware local verification

After targeted tests are stable:

```bash
uv run python scripts/local_verify.py plan --base <TASK_BASE_SHA>
uv run python scripts/local_verify.py run --base <TASK_BASE_SHA>
```

`scripts/local_verify.py` does not select semantic impact itself. It consumes the full required plan produced by `scripts/verify.py`.

The default deterministic scheduling budget is `10` cost units. Cost units are an execution heuristic, not a quality threshold and not a wall-clock guarantee.

If the complete impact plan fits inside the budget, it is executed locally.

If the plan exceeds the budget:

- low-cost static/preflight proof may run locally;
- expensive required commands remain listed under `deferred_to_ci`;
- the command exits with code `3`;
- the result is `LOCAL_PASS_CI_REQUIRED` or `LOCAL_DEFERRED_TO_CI`;
- the agent must not report those deferred commands as passed.

### Level 2 — PR / main CI

GitHub CI owns broad parallel proof that is inefficient to repeat in the agent's local context.

Typical examples:

```text
core-full
full coverage
recovery
sim-recovery
research-postgres
web E2E
all-package build
security/static matrix
```

A local budget defer never removes these requirements from the impact plan.

### Level 3 — Nightly heavy quality

Long-running or statistically expensive proof remains outside the ordinary local loop:

```text
mutation
exhaustive
formal
performance
long integration matrices
```

These jobs are not ordinary local completion criteria unless the task explicitly changes their authority or the user explicitly requests them.

## 3. Default prohibitions for agents

Agents must not run the following locally by default:

```text
scripts/test_suite.py release
core-full
core-full --coverage
all Research lanes as a bundle
recovery + sim-recovery as a routine pair
exhaustive
mutation
performance
full Playwright E2E
```

These may be run locally only when one of the following is true:

1. the user explicitly requests full local verification;
2. the task contract explicitly requires it;
3. a CI-only failure must be reproduced locally and narrower reproduction has failed;
4. `scripts/local_verify.py run --full-local ...` is an intentional explicit opt-in.

## 4. Explicit full-local opt-in

The escape hatch is deliberate:

```bash
uv run python scripts/local_verify.py run \
  --base <TASK_BASE_SHA> \
  --full-local
```

`--full-local` executes the complete impact plan selected by `scripts/verify.py`. It must never become the default agent command.

## 5. Concise-output rule

Local verification is failure-first.

Successful command stdout should remain out of the conversational context whenever possible. Full logs belong in `test-results/verification/`.

Failure output should contain only enough context to identify the first real failure:

```text
gate
command
exit code
short traceback/diagnostic
full log path
```

Do not copy thousands of passing test lines into an agent conversation.

## 6. Coverage policy

Coverage is evidence, not an inner-loop default.

For ordinary local work:

- docs-only change: no runtime coverage;
- test-only change: no automatic whole-repository coverage;
- production source change: affected package/lane coverage only when the Task Contract requires it;
- `core-full --coverage`: GitHub CI by default.

Coverage thresholds must never be lowered to make local verification cheaper.

## 7. Docs-only and metadata-only changes

When the impact planner proves a change is documentation-only, do not run runtime suites merely because the repository is large.

Status/roadmap metadata changes should run the exact contract/architecture test that owns the invariant, then use the impact planner.

## 8. Unknown and verification-infrastructure changes

Unknown impact and verification-infrastructure self-change remain fail-closed in `scripts/verify.py`: the required impact set is broad/full.

The local budget does not narrow that required set. It changes only where the proof executes.

For an over-budget plan:

```text
required plan = full
local execution = budgeted
remaining proof = CI_REQUIRED
```

This distinction preserves safety while preventing verification tooling from consuming a full repository test cycle every time it changes.

## 9. Exit codes

`scripts/local_verify.py run` uses:

```text
0 = all required local impact commands passed inside the budget
1 = local verification failed
2 = invalid plan/input
3 = local budget exceeded; required proof explicitly deferred to CI
```

Exit code `3` is not PASS.

An agent receiving `3` should proceed to PR/CI only if the targeted/local work is otherwise ready, and must report the deferred gates as not yet verified.

## 10. Task completion rule

A Task may use CI to close required heavy evidence.

The final report must separate:

```text
Local PASS
CI PASS
NOT EXECUTED
CI REQUIRED
```

Never write:

```text
all tests passed
```

when the local policy deferred any required command and CI has not yet confirmed it.

## 11. Invariants

This policy must preserve:

- canonical lane semantics have one owner: `scripts/test_suite.py`;
- impact selection has one owner: `scripts/verify.py`;
- local cost policy does not duplicate paths/markers/coverage rules;
- required impact union is never reduced by a budget;
- unknown impact is never interpreted as no impact;
- local defer is explicit and machine-readable;
- CI/Phase evidence is never fabricated from local planning.
