# OnlyAlpha — P9.K.5 Closure + Functional Correctness / Coverage Evidence Separation

## Codex Engineering Task Prompt

---

# 0. Task Identity

Repository:

```text
https://github.com/zongxin1993/OnlyAlpha
```

Task:

```text
P9.K.5 Closure
+
Engineering Quality Rule Clarification:
Functional Correctness Evidence != Coverage Evidence
```

Expected repository state when this prompt was prepared:

```text
branch: master
HEAD:   12cb8dcfa145cdf887d75c7618c9318c086b387d
commit: Feat: P9.K.5 Idempotency, Long-running Operations & Recovery Closure
```

This SHA is informational only.

The repository at execution time is authoritative.

Before modifying anything:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

Record:

```text
TASK_BASE_SHA=<actual current HEAD>
TASK_BRANCH=<actual branch>
```

If `master` has advanced:

1. use current `master`;
2. re-read the governing documents below;
3. verify that P9.K.5 Closure is still applicable;
4. preserve newer accepted design decisions;
5. never blindly reset to the historical SHA above.

---

# 1. Governing Documents

Read before implementation:

```text
AGENTS.md

docs/engineering/quality-system.md
docs/engineering/convergent-audit-policy.md

docs/roadmap.md
docs/p9_k_stateful_kernel_protocol_boundary.md

docs/adr/0090-research-execution-attempt-lease-fencing-and-recovery.md
docs/adr/0101-stateful-kernel-and-protocol-boundary.md
docs/adr/0103-public-api-contract-governance.md
docs/adr/0104-product-command-idempotency-and-kernel-recovery-closure.md

docs/reports/p9_k5_idempotency_recovery_implementation.md

src/onlyalpha/kernel/host.py
src/onlyalpha/persistence/postgres/kernel_authority.py

tests/kernel/test_host.py
tests/architecture/test_p9_k5_recovery_closure.py

scripts/test_suite.py
```

Also inspect any newer documents that supersede these.

Authority order:

```text
current accepted ADR / frozen design
>
engineering quality system
>
current source + tests
>
current roadmap/report
>
historical prompt
>
old conversation
```

Do not let this prompt override a newer accepted repository contract.

---

# 2. First-Principles Goal

This task solves two concrete problems only.

## Problem A — Quality semantics are being interpreted inconsistently

OnlyAlpha already separates:

```text
canonical functional lane

and

canonical lane --coverage
```

The engineering quality system already states that full coverage verification is normally Phase/Certification evidence rather than ordinary Task inner-loop feedback.

However, P9.K.5 review/reporting has effectively treated:

```text
functional tests PASS
+
coverage threshold FAIL
```

as if:

```text
functional correctness FAIL
```

That is semantically wrong.

Coverage answers:

```text
which implementation paths were executed by the test set?
```

Coverage does NOT answer:

```text
is the business behavior correct?
is the invariant correct?
is the transaction correct?
is identity unique?
is recovery deterministic?
```

The engineering model must make this distinction explicit and consistent.

---

## Problem B — P9.K.5 contains one confirmed lifecycle ordering violation

ADR 0104 requires the production mutation-capable Product Kernel to hold its PostgreSQL mutation authority:

```text
before RECOVERING
```

Current implementation is conceptually:

```text
VERIFYING
→ transition RECOVERING
→ authority_guard.acquire()
→ recovery
→ READY
```

Required implementation is:

```text
VERIFYING
→ complete verifiers
→ authority_guard.acquire()
→ transition RECOVERING
→ recovery
→ READY
```

This is the actual P9.K.5 correctness defect to fix.

Do not redesign the rest of K5.

---

# 3. Mandatory Engineering Principle to Freeze

The following rule must become explicit repository policy.

## 3.1 Functional correctness evidence

Functional correctness is established through applicable evidence such as:

```text
behavior tests
invariant tests
architecture tests
contract tests
determinism tests
failure-path tests
real persistence/concurrency tests where required
```

A functional test result is judged by its assertions and behavior.

Example:

```text
54 functional tests PASS
```

means:

```text
those 54 tested behaviors PASS
```

It must not be rewritten as functional failure merely because a separate coverage calculation reports 78% branch coverage.

---

# 4. Coverage Evidence Semantics

Coverage is a separate quality dimension.

It measures:

```text
test execution reach
```

not:

```text
semantic correctness
```

Therefore:

```text
functional lane PASS
+
coverage threshold FAIL
```

must be represented as:

```text
Functional correctness evidence:
PASS

Coverage quality evidence:
FAIL / OPEN
```

Never represent this as:

```text
Functional correctness:
FAIL
```

unless a functional/invariant/contract test actually fails.

---

# 5. Do Not Create a Fourth Gate

OnlyAlpha formal quality levels remain exactly:

```text
Task Gate
Phase Gate
Certification Gate
```

Do NOT create names such as:

```text
Functional Gate
Coverage Gate
Closure Gate
Development Certification Gate
Quality Gate 4
```

as new formal quality levels.

“Functional correctness evidence” and “Coverage evidence” are evidence dimensions inside the existing Gate model.

This task clarifies evidence semantics.

It does NOT redesign the quality framework.

---

# 6. Task Gate Rule

For a normal implementation/correctness Task:

```text
Task Gate
```

must primarily answer:

> Did the changed behavior correctly implement the frozen contract over its actual Impact Scope?

Normal inner-loop verification should therefore prefer:

```text
scripts/test_suite.py <affected-lane>
```

rather than:

```text
scripts/test_suite.py <affected-lane> --coverage
```

unless one of these is true:

```text
1. the Task itself is a coverage-closure task;
2. the Task modifies coverage/test infrastructure;
3. the frozen Task acceptance criteria explicitly require local coverage;
4. a specific otherwise-unverifiable path requires targeted coverage evidence.
```

Do not use broad coverage calculation merely as a development feedback mechanism.

---

# 7. Phase / Certification Rule

Coverage remains valid and important engineering evidence.

Do NOT weaken it.

Existing thresholds remain unchanged unless a separately approved engineering decision changes them.

For example, do NOT change existing values such as:

```text
Research Command:
line >= existing threshold
branch >= existing threshold

Research PostgreSQL:
existing aggregate threshold
```

Coverage remains applicable where the existing Phase Gate or Certification Gate requires it.

Therefore:

```text
Task Complete
```

does NOT imply:

```text
Final-SHA Certified
```

Likewise:

```text
coverage evidence OPEN
```

does NOT imply:

```text
Task functional correctness FAILED
```

These are distinct statements.

---

# 8. Remote CI Rule

Remote full CI is not part of the normal repair inner loop.

Do NOT implement this workflow:

```text
edit
→ push
→ wait ~60 minutes
→ inspect CI
→ edit
→ push
→ wait ~60 minutes
```

The normal development loop should be:

```text
edit
→ targeted local functional verification
→ targeted static verification
→ fix
→ repeat locally
→ candidate implementation
```

Only when the applicable higher-level Gate requires broad/exact-SHA evidence should expensive CI/certification be consumed.

Do not block a normal Task correctness repair merely because a future remote coverage job has not yet executed.

Do not “wait for CI” inside this task.

---

# 9. Audit Severity Clarification

Update the convergent audit semantics only as much as necessary to remove ambiguity.

The existing rule:

```text
current Gate cannot safely pass
→ BLOCKER
```

must always mean:

```text
the current audit Scope's applicable Gate
and its required evidence
```

It must NOT mean:

```text
any red job anywhere in GitHub Actions
→ BLOCKER
```

Example:

```text
Audit Scope:
P9.K.5 Task Gate

functional K5 evidence:
PASS

branch coverage:
below Phase/Certification threshold
```

Correct audit interpretation:

```text
K5 functional correctness:
PASS

coverage evidence:
OPEN / FAIL for the Gate where it is required

coverage alone:
NOT a K5 Task correctness BLOCKER
```

If the audit scope is instead:

```text
Final-SHA Certification
```

and coverage is mandatory there, then:

```text
coverage failure
→ Certification REJECTED
```

This distinction must be explicit.

---

# 10. Missing Evidence Semantics

Preserve the existing convergent-audit principle:

```text
NOT_VERIFIED
!=
automatic defect
```

Missing evidence blocks only when that evidence is required by the current Gate.

For example:

```text
Task Gate does not require repository-wide branch coverage
```

therefore:

```text
repository-wide branch coverage not executed
```

must not become:

```text
BLOCKER
```

for that Task.

---

# 11. Required Documentation Change

Inspect the current wording before editing.

The quality system already contains a `Coverage Placement` concept.

Do NOT duplicate it with a second parallel policy.

Instead strengthen/clarify the existing section so that the following distinctions are normative:

```text
Functional correctness evidence
!=
Coverage evidence

functional test PASS remains PASS independently of coverage %

coverage failure does not retroactively invalidate passing functional assertions

coverage blocks only the Gate in which coverage is explicitly mandatory

normal Task development inner loop does not use coverage by default

expensive exact-SHA CI is not ordinary local repair feedback
```

Likely file:

```text
docs/engineering/quality-system.md
```

Use the minimum sufficient edit.

---

# 12. Required Audit Policy Change

Inspect:

```text
docs/engineering/convergent-audit-policy.md
```

Add only the minimum clarification necessary.

At minimum make unambiguous:

```text
Finding severity is evaluated against the current audit Scope and applicable Gate.

A Phase/Certification coverage failure must not be promoted to a Task correctness BLOCKER when coverage is not required by that Task Gate.

A passing functional/invariant test remains positive correctness evidence even if a separate coverage threshold fails.
```

Do not alter:

```text
BLOCKER / MAJOR / MINOR / SUGGESTION
```

levels.

Do not introduce a new audit severity.

---

# 13. Do Not Modify Quality Infrastructure Unless Necessary

This task should normally NOT modify:

```text
scripts/test_suite.py
scripts/verify.py
scripts/certification.py

.github/workflows/*

coverage thresholds
coverage source ownership
pytest markers
```

The repository already structurally supports:

```text
lane
vs
lane --coverage
```

This task is primarily a semantics/documentation alignment plus P9.K.5 correctness closure.

If current code already supports the intended separation:

```text
leave it alone
```

Do not rewrite CI merely to produce green badges.

---

# 14. Forbidden Coverage Shortcuts

Absolutely forbidden:

```text
lower --cov-fail-under
remove branch coverage
remove modules from --cov
add pragma: no cover to avoid legitimate branches
exclude K5 production files
delete tests to manipulate denominator
change coverage ownership merely to pass CI
```

The point is:

```text
separate correctness from coverage
```

not:

```text
weaken coverage
```

Coverage debt may remain visible until the applicable Phase/Certification Gate closes it.

---

# 15. P9.K.5 Closure — Frozen Correctness Scope

Do not reopen or redesign the whole K5 implementation.

The following existing architecture remains frozen:

```text
Product Command ID
→ global operational command identity

product_command_receipt
→ sole active external retry binding authority

ResearchRun
→ long-running Research operation authority

Research Attempt / Lease / Fencing
→ Worker-owned physical execution recovery authority

Frozen Strategy Revision + Freeze Relation
→ semantic Strategy truth

PostgreSQL Strategy records
→ derived operational projection

PostgreSQL session advisory lock
→ V1 Product Kernel mutation authority
```

Do not create a second authority.

---

# 16. P9.K.5 Confirmed Defect

ADR 0104 requires:

```text
mutation authority held
before
RECOVERING
```

Current `OnlyAlphaKernelHost.start()` conceptually performs:

```text
BOOTING
→ booters

VERIFYING
→ verifiers

RECOVERING
→ authority acquire
→ recoverers

READY
```

This allows a temporary state:

```text
host.state == RECOVERING
AND
authority not yet held
```

That violates the frozen lifecycle contract.

---

# 17. Required Lifecycle Ordering

Implement the minimum fix.

Required startup sequence:

```text
CREATED
→ BOOTING
→ booters

→ VERIFYING
→ verifiers

→ authority_guard.acquire()

→ RECOVERING
→ recoverers

→ READY
```

In invariant form:

```text
state == RECOVERING
⇒
mutation authority already held
```

and:

```text
state == READY
⇒
mutation authority held
```

for a production host configured with a guard.

Do not add a new lifecycle state.

Do not add a RecoveryCoordinator.

Do not add a distributed lock abstraction beyond the existing Protocol.

---

# 18. Authority Acquisition Failure

Required semantics:

```text
VERIFYING completed
→ authority_guard.acquire()
→ failure
→ host FAILED
```

Must prove:

```text
host never executes any recoverer

host never reaches READY

no recovery side effect occurs
```

Preserve existing explainable failure semantics where compatible.

The failure should remain attributable to:

```text
phase = RECOVERING
step = mutation-authority-acquire
```

unless current frozen contracts require otherwise.

Do not expose infrastructure secrets in lifecycle errors.

---

# 19. Recovery Failure

Required:

```text
authority acquired
→ RECOVERING
→ recoverer fails
→ authority released
→ FAILED
```

Invariant:

```text
FAILED after startup failure
⇒
no owned mutation authority remains
```

Preserve current fail-closed behavior.

---

# 20. Draining Semantics

Do not regress shutdown ordering.

Required:

```text
READY
→ DRAINING
→ mutation admission closed
→ drainers execute while authority remains held
→ release authority
→ STOPPED
```

Invariant:

```text
drainer execution
⇒
guard still held
```

The guard must not be released before draining is complete.

---

# 21. Kernel Infrastructure Boundary

Do NOT import into `onlyalpha.kernel`:

```text
psycopg
FastAPI
Starlette
API DTOs
```

Keep:

```text
OnlyKernelAuthorityGuard
```

as the infrastructure-neutral capability contract.

Keep PostgreSQL implementation outside Kernel, e.g.:

```text
src/onlyalpha/persistence/postgres/kernel_authority.py
```

Do not move PostgreSQL knowledge into Kernel Host.

---

# 22. Required Temporal Test

Current tests prove that a recoverer sees:

```text
RECOVERING
+
guard held
```

That is not enough.

Add a test proving exact temporal ordering.

Conceptually:

```text
test_authority_is_acquired_before_entering_recovering
```

Record observations from:

```text
verifier
guard.acquire()
recoverer
drainer
guard.release()
```

Required evidence:

```text
verifier:
state == VERIFYING

guard.acquire():
state == VERIFYING

recoverer:
state == RECOVERING
guard.held == True

drainer:
state == DRAINING
guard.held == True
```

This is the central regression test for the defect.

Avoid sleeps.

Avoid timing-based probabilistic assertions.

Use deterministic observation/event ordering.

---

# 23. Required Acquisition-Failure Test

Strengthen or add a deterministic test proving:

```text
guard.acquire called while state == VERIFYING

guard.acquire raises

recoverer call count == 0

host.state == FAILED

failure.phase == RECOVERING

failure.step == mutation-authority-acquire
```

Do not merely assert that an exception occurred.

Prove absence of recovery work.

---

# 24. Preserve Existing K5 Invariants

This Closure must not change:

```text
same command id + same kind + same fingerprint
→ same current authoritative resource

same command id + different intent/kind
→ deterministic conflict

dangling/corrupt Receipt
→ fail closed

Product Command identity
→ never enters semantic fingerprints

Create Run + Receipt
→ atomic

keyed Cancel effect + Receipt
→ atomic

ResearchRun
→ remains operation authority

Worker Attempt/Lease/Fencing
→ unchanged

Strategy semantic truth
→ dominates PostgreSQL projection

recovery traversal
→ deterministic
```

Do not modify those paths without a concrete failing functional test.

---

# 25. Previous Coverage Finding — Correct Interpretation

Previous audit identified coverage failures such as:

```text
research-command functional tests:
PASS

research-command branch coverage:
below threshold

research-postgres functional tests:
PASS

research-postgres aggregate coverage:
below threshold
```

Do not falsify those historical results.

Do not claim coverage passed.

Instead correct the Gate interpretation.

For P9.K.5 Task-level correctness:

```text
functional tests PASS
```

is positive correctness evidence.

The coverage shortfall belongs to:

```text
Phase / Certification quality evidence
```

where the repository requires that threshold.

Update the K5 report so this distinction is explicit.

A useful representation is conceptually:

```text
Functional correctness evidence:
PASS

Coverage evidence:
OPEN / below current higher-level threshold

Task correctness blocking:
NO

Phase/Certification blocking when applicable:
YES
```

This is an evidence classification, not a new Gate.

---

# 26. Previous Finding Tracking

If the implementation report or audit report records:

```text
F-K5-001
coverage / Layered Quality failure
```

do NOT say:

```text
RESOLVED because coverage now passes
```

unless it actually passes.

Instead preserve historical truth and state clearly:

```text
The underlying coverage evidence remains open.

Its classification as a P9.K.5 Task correctness blocker was invalid under the clarified Gate scope.

It remains applicable only to a Gate that explicitly requires the coverage threshold.
```

Use existing audit terminology as closely as possible.

Do not invent a fake PASS.

For:

```text
F-K5-002
authority acquired after RECOVERING
```

this task must actually fix the code and prove it with tests.

Only then mark it:

```text
RESOLVED
```

---

# 27. P9.K.5 Task Completion Semantics

Align K5 status with the formal quality model.

P9.K.5 is a Task / Increment correctness closure.

It must not require a repository-wide Final-SHA Certification merely to begin P9.K.6 unless an authoritative current Phase contract explicitly says so.

After this Closure, K5 may be considered Task-complete when:

```text
applicable frozen K5 invariants PASS

confirmed lifecycle defect RESOLVED

affected functional tests PASS

affected architecture/contract checks PASS

BLOCKER == 0 for the K5 Task Gate

MAJOR == 0 for the K5 Task Gate
```

Coverage that belongs only to later Phase/Certification verification must not block K6.

Do NOT claim:

```text
Final-SHA Certification ACCEPTED
```

unless that workflow has actually been completed successfully.

---

# 28. K6 Entry Rule

After K5 Task-level convergent audit:

```text
BLOCKER == 0
MAJOR == 0
applicable K5 invariants PASS
required K5 Task evidence sufficient
```

the audit result should be:

```text
GO
```

and:

```text
P9.K.6 — External Client Migration
```

may begin.

Do not wait for a ~60-minute remote coverage/full-certification run merely because such evidence will eventually be required at a higher Gate.

If current repository documents explicitly define P9.K.5 itself as a Phase/Certification boundary, stop and report that concrete conflict instead of silently changing it.

Otherwise follow the formal Task Gate semantics from `quality-system.md`.

---

# 29. Functional Verification — No Coverage

The correctness repair loop must NOT use `--coverage`.

Run the smallest sufficient set derived from actual Impact Scope.

At minimum, after changing Kernel Host:

```bash
uv run pytest tests/kernel/test_host.py -q
```

Then canonical Kernel functional lane:

```bash
uv run python scripts/test_suite.py kernel
```

Run the targeted K5 architecture guard if the current file still exists:

```bash
uv run pytest tests/architecture/test_p9_k5_recovery_closure.py -q
```

Because this is a K5 closure, also run the existing Research Command functional lane unless current dependency inspection proves it completely unaffected:

```bash
uv run python scripts/test_suite.py research-command
```

Do NOT append:

```text
--coverage
```

for Task correctness acceptance.

---

# 30. Product Closure Functional Regression

If the current repository still defines:

```text
research-product-closure
```

as the relevant K5/P8 durable product regression lane, run:

```bash
uv run python scripts/test_suite.py research-product-closure
```

Again:

```text
functional assertions only
```

No coverage calculation is needed for this Task acceptance.

---

# 31. PostgreSQL Functional Evidence

Inspect actual Impact Scope.

The expected production code change is:

```text
src/onlyalpha/kernel/host.py
```

The PostgreSQL advisory guard implementation itself should remain unchanged.

Therefore do NOT automatically require the entire real PostgreSQL suite just because PostgreSQL is conceptually involved.

If:

```text
persistence/postgres code
migration
transaction code
guard adapter
```

is modified, then real PostgreSQL testing becomes part of current Impact Scope.

If no PostgreSQL production code changes, do not reopen all previously proven PostgreSQL semantics.

If a local PostgreSQL DSN is already available and the relevant targeted test is cheap, it may be run as additional evidence.

But:

```text
missing local PostgreSQL environment
```

must not automatically trigger:

```text
wait for remote CI
```

when the changed code does not require a new persistence proof.

Follow impact-aware verification.

---

# 32. Static Verification

Run appropriate static checks after functional correctness passes.

At minimum for changed Python:

```bash
uv run ruff check <changed-python-files>
uv run ruff format --check <changed-python-files>
```

Run relevant mypy scope if Kernel typing changed:

```bash
uv run mypy src/onlyalpha
```

Also:

```bash
git diff --check
```

Do not run repository-wide expensive checks without an Impact Scope reason.

---

# 33. Coverage Commands Are Explicitly Out of the Inner Loop

Do NOT use as iterative repair criteria:

```bash
uv run python scripts/test_suite.py research-command --coverage
uv run python scripts/test_suite.py research-postgres --coverage
uv run python scripts/test_suite.py core-full --coverage
```

Do not add tests whose sole rationale is:

```text
move number from 78% to 85%
```

Tests should exist to prove behavior/invariants.

Coverage can later reveal under-tested areas during its applicable higher-level Gate, but it is not the semantic oracle for this Closure.

---

# 34. Remote CI Is Not a Completion Dependency for This Repair Loop

Do not:

```text
push intermediate fix
wait for GitHub Actions
inspect 60-minute result
repeat
```

Do not write documentation such as:

```text
TASK BLOCKED waiting for remote CI
```

merely because coverage/full CI has not run.

This task should be completed from current repository + local sufficient evidence.

Existing remote evidence may be referenced as historical context but must not substitute for tests needed by the actual changed path.

---

# 35. No Unnecessary New Tests

Do not increase test count merely because coverage is low.

For every new test, be able to state:

```text
Invariant / behavior proved:
Why existing tests did not prove it:
Why this test belongs to current Impact Scope:
```

The mandatory new tests in this task are specifically justified by the lifecycle defect:

```text
authority acquire occurs before RECOVERING
authority acquire failure executes zero recovery work
```

Other tests require concrete evidence.

---

# 36. Documentation Status Update

After functional repair succeeds, update:

```text
docs/reports/p9_k5_idempotency_recovery_implementation.md
```

Preserve historical evidence.

Do not erase the fact that the previous SHA had coverage failures.

Add a Closure section containing at minimum:

```text
Closure base SHA
Closure implementation SHA / worktree state

F-K5-002:
RESOLVED

Functional correctness:
PASS

Kernel functional lane:
PASS

K5 targeted architecture:
PASS

Research Command functional lane:
PASS

Product closure lane:
PASS
(if executed)

Coverage evidence:
separate higher-level evidence
previous shortfall remains historical/open until applicable Gate reruns

Remote exact-SHA certification:
NOT CLAIMED unless actually performed
```

Do not write `CI PASS` without evidence.

---

# 37. Roadmap Update

Inspect current roadmap wording.

If K5 is still marked as blocked solely because coverage/full remote CI was not complete, align it with the formal quality model.

Use terminology consistent with `quality-system.md`.

Conceptually:

```text
P9.K.5
Task Complete
Functional correctness closure complete

Higher-level coverage/certification evidence:
tracked separately
```

Then allow:

```text
P9.K.6
next authorized increment
```

Do not claim a higher certification level than actually achieved.

---

# 38. Version Policy

This is a correctness closure of P9.K.5.

Do NOT create:

```text
0.9.6
```

merely because a closure commit is added.

Retain the current P9.K.5 release mapping unless repository authority has changed it.

Expected:

```text
0.9.5
```

If version files are touched for another reason, use the repository's version-sync mechanism.

Otherwise only verify existing consistency when appropriate.

---

# 39. Modification Scope

Expected production modification:

```text
src/onlyalpha/kernel/host.py
```

Expected tests:

```text
tests/kernel/test_host.py
```

Expected engineering documentation:

```text
docs/engineering/quality-system.md
docs/engineering/convergent-audit-policy.md

docs/reports/p9_k5_idempotency_recovery_implementation.md
docs/roadmap.md
```

Conditional only if current evidence requires:

```text
tests/architecture/test_p9_k5_recovery_closure.py
```

Do not modify unrelated production modules.

---

# 40. Explicit Out of Scope

Do NOT implement:

```text
P9.K.6 functionality
P9.K.7
P9.K.8

new ProductOperation
new workflow engine

Redis
Kafka
NATS
Temporal
Celery
etcd
Consul

leader election
HA
multi-master Kernel

new migration

Research Worker redesign
Attempt/Lease/Fencing redesign

Strategy fingerprint changes
Strategy Revision identity changes

Research semantic fingerprint changes

OpenAPI v3
new public API

coverage threshold reduction
coverage exclusion hacks

CI redesign
repository restructuring
```

---

# 41. Functional Acceptance Criteria

The P9.K.5 Closure is functionally accepted only if all applicable items pass.

## AC-FUNC-001 — Correct authority ordering

```text
authority_guard.acquire()
occurs after verification
and before transition to RECOVERING
```

PASS required.

---

## AC-FUNC-002 — RECOVERING invariant

```text
host.state == RECOVERING
⇒
guard already held
```

PASS required.

---

## AC-FUNC-003 — Recovery executes under authority

Every recoverer observes:

```text
state == RECOVERING
guard held
```

PASS required.

---

## AC-FUNC-004 — Acquisition failure fail-closed

If authority cannot be acquired:

```text
recoverer calls == 0
READY never reached
host → FAILED
```

PASS required.

---

## AC-FUNC-005 — Recovery failure releases authority

```text
acquire success
→ recoverer failure
→ FAILED
→ authority released
```

PASS required.

---

## AC-FUNC-006 — Draining retains authority

```text
DRAINING
→ drainers execute
→ authority remains held
→ release only after draining
```

PASS required.

---

## AC-FUNC-007 — Kernel boundary

Kernel remains free of:

```text
psycopg
FastAPI
Starlette
API DTO
```

PASS required.

---

## AC-FUNC-008 — K5 identity/authority regressions

No regression in:

```text
Product Command identity
Receipt replay
ResearchRun authority
fail-closed behavior
Strategy projection recovery
Worker fencing ownership
```

Applicable targeted functional lanes PASS.

---

## AC-FUNC-009 — No uniqueness regression

```text
no second command retry authority
no second Research operation authority
no duplicate Strategy semantic authority
```

PASS required.

---

## AC-FUNC-010 — No determinism regression

```text
recovery ordering remains canonical
operational command identity remains outside semantic fingerprints
```

PASS required.

---

# 42. Engineering Policy Acceptance Criteria

## AC-POLICY-001

Repository explicitly states:

```text
Functional correctness evidence != Coverage evidence
```

PASS.

## AC-POLICY-002

Repository explicitly states:

```text
passing functional assertions remain PASS independently of coverage percentage
```

PASS.

## AC-POLICY-003

Repository explicitly states:

```text
coverage failure blocks only a Gate where that coverage is mandatory
```

PASS.

## AC-POLICY-004

Repository explicitly states:

```text
coverage is not the default Task repair inner loop
```

PASS.

## AC-POLICY-005

Repository explicitly states:

```text
remote full CI is not ordinary iterative repair feedback
```

PASS.

## AC-POLICY-006

Formal Gate hierarchy remains:

```text
Task
Phase
Certification
```

No fourth Gate introduced.

PASS.

## AC-POLICY-007

Existing coverage thresholds are unchanged.

PASS.

---

# 43. Task-Level Verification Commands

Derive exact commands from current repository.

Expected minimum set:

```bash
uv run pytest tests/kernel/test_host.py -q

uv run python scripts/test_suite.py kernel

uv run pytest tests/architecture/test_p9_k5_recovery_closure.py -q

uv run python scripts/test_suite.py research-command
```

And, when still applicable and available:

```bash
uv run python scripts/test_suite.py research-product-closure
```

Static:

```bash
uv run mypy src/onlyalpha
git diff --check
```

Plus relevant Ruff/format checks.

Do not automatically execute coverage variants.

---

# 44. Final Convergent Audit

After implementation, perform a focused Task-Gate audit.

Freeze:

```text
AUDIT_BASE_SHA
AUDIT_HEAD_SHA
Scope = P9.K.5 Closure Task Gate
```

Track previous findings.

Expected outcome if implementation is correct:

```text
F-K5-002
RESOLVED

F-K5-001
not a Task correctness blocker under clarified Gate scope;
underlying higher-level coverage evidence remains open unless separately verified
```

Invariant matrix must distinguish:

```text
PASS
FAIL
NOT_VERIFIED
```

Do not interpret:

```text
higher-level coverage not rerun
```

as:

```text
K5 invariant FAIL
```

---

# 45. GO Criteria for P9.K.6

Give:

```text
GO → P9.K.6
```

when:

```text
BLOCKER == 0
MAJOR == 0

applicable K5 invariants == PASS

confirmed lifecycle defect == RESOLVED

required K5 Task functional evidence == PASS

required K5 Task architecture/contract evidence == PASS
```

Do NOT require:

```text
remote 60-minute CI completion
repository-wide coverage completion
Final-SHA Certification
```

unless current authoritative repository rules explicitly classify P9.K.5 as such a higher-level boundary.

Do not claim higher-level certification that has not occurred.

---

# 46. Final Report Required From Codex

At completion output:

```text
1. TASK_BASE_SHA
2. TASK_HEAD / worktree state
3. Files changed
4. Quality-policy clarification
5. P9.K.5 lifecycle defect root cause
6. Exact production fix
7. Tests added/modified and what invariant each proves
8. Functional verification commands + results
9. Static verification results
10. Coverage status, explicitly separate from functional correctness
11. Previous findings status
12. Invariant matrix
13. Out-of-scope confirmation
14. Final Task Gate verdict:
    GO / NO-GO
15. Whether P9.K.6 may begin
```

Do not report a coverage percentage unless it was actually measured.

Do not claim remote CI success unless it actually occurred.

Do not wait for future CI.

---

# 47. Final Engineering Principle

The implementation and documentation must converge on:

```text
Correctness is proved by behavior and invariants.

Coverage measures how much implementation was exercised;
it does not determine whether an exercised behavior is correct.

Task development should use the smallest sufficient functional evidence.

Coverage remains valuable higher-level quality evidence
without becoming the default repair feedback loop.

A red coverage threshold must never erase a green functional test result.

One fact
→ one authority

Same intent
→ deterministic identity

Retry / restart
→ one converged outcome

Recovery
→ authority before mutation/reconciliation

Corruption / ambiguity
→ fail closed

Minimum sufficient verification
→ fast local feedback

Expensive certification
→ only at the Gate where it belongs
```

Implement exactly that model.

Do not redesign beyond it.