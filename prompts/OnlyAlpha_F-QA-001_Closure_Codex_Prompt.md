# Codex Task Prompt — Close F-QA-001 Before P9.K.5

## 0. Task Identity

Repository:

```text
https://github.com/zongxin1993/OnlyAlpha
```

Target branch:

```text
master
```

Expected task baseline:

```text
92a4bb3329f33897baa9bfcca596bfa4f8d41d6c
```

Current project state:

```text
P9.K.4 Closure-2 — DONE / VERIFIED
P9.K.5 — IMPLEMENTATION READY
P9.1+ — BLOCKED until P9.K closure
```

This task is **not P9.K.5 implementation**.

This task exists only to close the previously identified blocking quality finding:

```text
F-QA-001
Research Factor mandatory coverage gate is not closed
Severity: MAJOR
Status: NOT_RESOLVED
```

The task must follow the repository's current engineering contracts, especially:

```text
AGENTS.md
docs/engineering/convergent-audit-policy.md
docs/engineering/quality-system.md
docs/p9_k_stateful_kernel_protocol_boundary.md
docs/adr/0101-stateful-kernel-and-protocol-boundary.md
```

Repository source, current tests, current CI configuration, and active ADRs are authoritative.
Do not use this prompt to override current repository facts.

---

# 1. First Action — Freeze the Actual Baseline

Before modifying anything:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
```

Record:

```text
TASK_BASE_SHA=<actual HEAD>
TASK_BRANCH=<actual branch>
```

Expected:

```text
TASK_BRANCH=master
TASK_BASE_SHA=92a4bb3329f33897baa9bfcca596bfa4f8d41d6c
```

If HEAD differs:

1. do not blindly apply this prompt;
2. re-read the current versions of the files listed below;
3. verify whether F-QA-001 still exists;
4. continue only if the same current invariant violation is still present;
5. explicitly report the new `TASK_BASE_SHA`.

Do not mix evidence from different SHAs.

---

# 2. Governing Engineering Principle

This is a **convergent audit closure task**, not a redesign task.

Priority:

```text
Frozen contract
> reviewer preference

Evidence
> speculation

Invariant
> abstraction preference

Correctness
> elegance

Minimum sufficient mechanism
> architectural expansion
```

The objective is:

> Close one known mandatory verification gap with the minimum sufficient change, prove it on the current codebase, and stop.

Do not create new architecture because a small verification defect exists.

---

# 3. Existing Finding

## F-QA-001 — Research Factor mandatory coverage gate is not closed

The repository's quality system defines:

```text
python scripts/test_suite.py research-factor
python scripts/test_suite.py research-factor --coverage
```

as the canonical Research Factor semantic/execution closure lane.

The coverage contract for the owned P7.5 execution module and official Factor plugin is:

```text
100% line coverage
100% branch coverage
```

and this coverage gate is mandatory in normal CI/release/Final-SHA verification.

At the current baseline:

```text
main-lanes (research-factor)     PASS
Layered Quality / coverage      FAIL
Research Factor branch coverage FAIL
quality-gate                    FAIL
```

The known uncovered semantic branch is the fail-closed publication authorization path in:

```text
src/onlyalpha/research/calculation/execution.py
```

The relevant logic is conceptually:

```python
if (
    not isinstance(value, _OnlyVerifiedResearchCalculationExecution)
    or value.seal is not _VERIFIED_EXECUTION_SEAL
):
    raise OnlyResearchCalculationError(
        "RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED",
        ...
    )
```

This production behavior is correct and must remain.

The repository already contains a proving test in:

```text
tests/research/calculation/test_execution_evidence.py
```

including a case that proves unauthorized/public execution projection cannot mint semantic Execution Evidence, and checks:

```text
RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED
```

However the current `RESEARCH_FACTOR` lane in:

```text
scripts/test_suite.py
```

includes:

```text
tests/research/factor
packages/factor/onlyalpha-plugin-factors/tests
tests/research/calculation/test_execution.py
tests/architecture/test_research_factor_boundaries.py
tests/architecture/test_calculation_plugin_boundaries.py
```

but does not currently consume the relevant existing Execution Evidence authorization test.

The result is:

```text
correct production fail-closed branch
+
existing proving test
+
wrong canonical coverage ownership
=
mandatory 100% Research Factor coverage gate failure
```

---

# 4. Task Goal

Close F-QA-001 with the **smallest correct verification change**.

After this task:

```text
research-factor
→ PASS

research-factor --coverage
→ PASS
→ 100% required line/branch coverage

Layered Quality coverage
→ no longer fails on Research Factor coverage

quality-gate
→ can become green if no unrelated current failure exists
```

No semantic/product architecture change is expected.

---

# 5. Required Pre-Implementation Audit

Before editing, inspect at minimum:

```text
docs/engineering/convergent-audit-policy.md
docs/engineering/quality-system.md

scripts/test_suite.py

src/onlyalpha/research/calculation/execution.py

tests/research/calculation/test_execution.py
tests/research/calculation/test_execution_evidence.py

packages/factor/onlyalpha-plugin-factors/tests/

.github/workflows/
```

Also inspect any helper used by `scripts/test_suite.py` to construct the coverage command.

Confirm with current evidence:

1. which exact source file(s) are measured by `research-factor --coverage`;
2. the exact current coverage threshold;
3. the exact uncovered line/branch;
4. which existing test proves that branch;
5. why that test is not currently selected by the canonical Research Factor lane;
6. whether adding the narrow test path is sufficient;
7. whether a broader test-directory addition would introduce unnecessary scope/runtime.

Do not edit until this causal chain is understood.

---

# 6. Invariants

## INV-QA-001 — Production semantics are already correct

Rule:

```text
Unauthorized or fabricated public Research execution projections
must not mint authoritative Execution Evidence.
```

Expected:

```text
invalid/unsealed value
→ RESEARCH_EXECUTION_PUBLICATION_UNAUTHORIZED
→ fail closed
```

The task must not weaken or bypass this behavior.

---

## INV-QA-002 — Canonical lane must prove the code it owns

Rule:

```text
If Research Factor coverage owns a semantic branch,
the canonical Research Factor coverage lane must execute
the test that proves that branch.
```

Coverage must represent semantic evidence, not threshold gaming.

---

## INV-QA-003 — 100% mandatory gate remains unchanged

Do not modify:

```text
100% line threshold
100% branch threshold
```

Do not change the quality contract to make CI green.

---

## INV-QA-004 — No duplicate semantic test implementation unless required

If the repository already has the correct proving test:

```text
reuse it
```

Do not copy the same test into another directory only to satisfy coverage unless there is concrete repository ownership evidence proving reuse is impossible or architecturally incorrect.

---

## INV-QA-005 — Minimal impact

The likely correct change is limited to canonical lane selection/ownership.

Do not modify production code unless current repository evidence proves the known diagnosis is wrong.

---

# 7. Preferred Implementation

First evaluate the minimum change:

```text
scripts/test_suite.py
```

Specifically `OnlyTestLane.RESEARCH_FACTOR`.

Prefer adding the **narrowest existing test target** that proves the missing semantic branch, for example the appropriate existing test file/test node from:

```text
tests/research/calculation/test_execution_evidence.py
```

The exact test path/node must be selected from current repository evidence.

Choose the smallest target that:

1. closes the missing branch;
2. preserves semantic ownership;
3. does not create duplicate test logic;
4. does not significantly broaden the lane without reason;
5. remains deterministic.

If the whole file is required because multiple branches in the owned execution path belong together, justify that from actual coverage evidence.

Do not mechanically follow this prompt's example if current source/tests prove a narrower or slightly different existing target is correct.

---

# 8. Explicit Forbidden Changes

Do **not** solve this task by:

```text
lowering coverage thresholds
```

Do **not** add:

```python
# pragma: no cover
```

to the uncovered production path.

Do **not**:

```text
delete the fail-closed branch
weaken validation
change error semantics
change Evidence identity
change Research Result identity
change Calculation identity
change Strategy identity
change Factor identity
change canonical serialization/fingerprint behavior
```

Do **not** redesign:

```text
OnlyResearchCalculationExecutor
Execution Evidence
Research Factor architecture
Research Calculation architecture
Kernel
Product Command
P9.K.5
```

Do **not** introduce:

```text
new generic test framework
new coverage framework
new registry/factory/manager abstraction
new duplicate canonical lane
```

Do **not** make unrelated formatting/refactor changes.

Do **not** start:

```text
P9.K.5
Product Command Receipt
global Idempotency infrastructure
Kernel recovery composition
K6/K7/K8
```

inside this task.

---

# 9. Required Verification

Use the repository's existing canonical commands.

At minimum run:

```bash
uv run python scripts/test_suite.py research-factor
```

and:

```bash
uv run python scripts/test_suite.py research-factor --coverage
```

The second command must satisfy the existing mandatory line/branch coverage contract.

Then run the smallest impact-aware static/architecture verification required by the actual changed file.

Because this task changes verification infrastructure / canonical test ownership, also inspect the repository's current Task Gate rules for verification-infrastructure changes and obey them exactly.

Expected candidates include:

```bash
uv run ruff check scripts/test_suite.py
uv run ruff format --check scripts/test_suite.py
uv run python scripts/version_sync.py check
git diff --check
```

If current engineering rules require a wider local verification set because `scripts/test_suite.py` is verification infrastructure, run that required existing gate rather than inventing a new one.

Do not silently skip a required gate because it is slow.

Do not run redundant repository-wide suites unless current impact rules require them.

---

# 10. Coverage Evidence

The final implementation report must include the actual before/after evidence.

Before:

```text
Research Factor coverage: FAIL
```

After:

```text
Research Factor coverage: PASS
Line coverage:   <actual>
Branch coverage: <actual>
```

If the repository still reports less than the required threshold after the minimal lane change:

1. do not lower the threshold;
2. inspect the newly reported uncovered branch;
3. determine whether it belongs to the same existing semantic invariant;
4. reuse existing tests where possible;
5. only add a new test if a real currently-unproved invariant remains.

Do not add speculative tests merely to increase a percentage.

---

# 11. CI / Exact-SHA Closure

After the local Task Gate is green:

1. create the minimal commit;
2. record:

```text
TASK_IMPLEMENTATION_SHA=<commit sha>
```

3. push through the repository's normal workflow;
4. inspect GitHub CI for the exact implementation SHA.

Required remote evidence must include, where applicable:

```text
research-factor                PASS
coverage                       PASS
quality-gate                   PASS
architecture                   PASS
static                         PASS
version sync                   PASS
```

If `quality-gate` fails only because of an unrelated current repository problem:

- report it separately;
- do not mutate unrelated code inside this task;
- classify whether it is a new blocking current-Gate issue under the convergent audit policy.

Do not claim completion from a different SHA.

---

# 12. Previous Finding Closure Rule

The final report must explicitly preserve the original finding identity:

```text
F-QA-001
```

Status may only become:

```text
RESOLVED
PARTIALLY_RESOLVED
NOT_RESOLVED
REGRESSED
```

Expected successful outcome:

```text
F-QA-001 — RESOLVED
```

Do not rename it into another finding.

---

# 13. Required Final Report

Produce a concise Markdown report with:

## A. Baseline

```text
TASK_BASE_SHA
TASK_IMPLEMENTATION_SHA
branch
```

## B. Root Cause

Explain the exact causal chain:

```text
owned production branch
→ existing proving test
→ canonical lane did not select it
→ mandatory coverage failure
```

## C. Changes

List exact files changed and why.

Expected ideal scope:

```text
scripts/test_suite.py
```

If anything else changes, explain why it was necessary.

## D. Invariant Results

Use:

| Invariant | Status | Evidence |
|---|---|---|
| INV-QA-001 | PASS/FAIL | ... |
| INV-QA-002 | PASS/FAIL | ... |
| INV-QA-003 | PASS/FAIL | ... |
| INV-QA-004 | PASS/FAIL | ... |
| INV-QA-005 | PASS/FAIL | ... |

## E. Verification

Include exact commands and actual result counts/coverage.

## F. Finding Status

```text
F-QA-001: RESOLVED / ...
```

## G. Scope Confirmation

Explicitly state whether any of these changed:

```text
Research semantics
Execution Evidence semantics
fingerprint/identity semantics
PostgreSQL schema
OpenAPI
Kernel
P9.K.5
```

Expected:

```text
NO
```

## H. GO / NO-GO

Apply:

```text
BLOCKER == 0
MAJOR == 0
required current-Gate evidence sufficient
→ GO
```

Expected if the task succeeds:

```text
GO → P9.K.5
```

This GO means:

> F-QA-001 is closed and the repository may begin P9.K.5.

It does **not** mean P9.K.5 itself is complete.

---

# 14. Stop Condition

Once:

```text
F-QA-001 = RESOLVED
research-factor --coverage = PASS
required exact-SHA CI = PASS
BLOCKER = 0
MAJOR = 0
```

stop.

Do not continue searching for optional refactors.

Do not begin P9.K.5 in the same task.

Do not create new abstractions.

The correct terminal result is:

```text
F-QA-001 CLOSED
↓
GO
↓
P9.K.5 may begin as a separate task
```
