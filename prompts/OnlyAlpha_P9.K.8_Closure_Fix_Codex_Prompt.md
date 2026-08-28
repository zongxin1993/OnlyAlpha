# OnlyAlpha — P9.K.8 Closure Fix — Codex Implementation Prompt

## 0. Task Identity

**Repository:** `zongxin1993/OnlyAlpha`  
**Task:** `P9.K.8 Closure Fix`  
**Task type:** Narrow corrective closure / convergent re-audit fix  
**Parent:** `P9.K.8 — Seal Kernel`

This task resolves the concrete MAJOR findings discovered after the committed K8 HEAD. It is not P9.1 and must not expand scope.

## 1. Freeze Repository Truth

At task start:

```bash
git status --short
git rev-parse HEAD
```

Record:

```text
FIX_BASE_SHA = current immutable HEAD
```

Then read current repository authorities:

```text
project-state.toml
AGENTS.md
docs/engineering/quality-system.md
docs/engineering/convergent-audit-policy.md
docs/adr/0101-stateful-kernel-and-protocol-boundary.md
docs/p9_k_stateful_kernel_protocol_boundary.md
docs/reports/p9_k8_seal_kernel.md
tests/architecture/test_p9_k8_kernel_seal.py
tests/contracts/test_p9_k7_task_delta.py
src/onlyalpha/runtime/
tests/integration/
scripts/gateway_protocol.py
```

Truth order:

```text
current executable source / public interfaces
>
current tests / architecture gates
>
active ADR
>
current docs
>
reports
>
this prompt
```

If all findings below are already resolved with concrete evidence, STOP and report `P9.K.8 Closure Fix = ALREADY RESOLVED`.

## 2. Frozen K8 Results That Must Not Be Reopened

Preserve these already-correct outcomes:

```text
root `onlyalpha` no longer exposes Engine/Runtime/Cluster Product mutation constructors
`onlyalpha run` removed
`onlyalpha snapshot` removed
`onlyalpha-client` remains supported Product CLI/client
Web remains Product API client
Product clients have no Core local fallback
HTTP mutation routes remain Product Command/Query boundaries
standalone `onlyalpha-artifact-api` removed
KNOWN_MIGRATION_DEBT = 0
LEGACY_K8_TARGET = 0
Product Control Plane is the unique supported external mutation authority
```

Do not reopen any of these.

## 3. Concrete Findings to Fix

```text
MAJOR-01
Fresh-process Runtime/SIM recovery bootstrap is not deterministic because of a circular import path.

MAJOR-01B
SIM checkpoint completion test failed and must be classified as real runtime race, test observation race, or environment/CI timing issue without hiding the problem through timeout inflation.

MAJOR-02
K7 historical task-delta verification is incorrectly scoped from an old K7 base SHA to every future HEAD, so it blocks legitimate later development.

Closure action
project-state must follow executable evidence and may only return to VERIFIED after the fixes pass.
```

## 4. First-Principles Goal

A Stateful Quant Kernel must satisfy:

```text
1. Authority uniqueness
2. State determinism
3. Execution/bootstrap determinism
4. Verification convergence
```

Required system properties:

```text
same code
+ same environment
+ fresh process
→ same Runtime bootstrap result
```

```text
execution committed
→ contiguous projection-ready prefix
→ stable checkpoint barrier
→ durable checkpoint
```

```text
historical task evidence
→ immutable closed audit interval
```

```text
current Gateway compatibility
→ one current compatibility authority
```

No hidden state, no second authority, no timing guesswork.

## 5. Mandatory Invariants

### INV-FIX-01 — Preserve Unique Product Mutation Authority

The only supported Product mutation path remains:

```text
External Product Actor
→ Product Control Plane
→ Product Command
→ Stateful Kernel
```

Do not restore root Engine/Runtime/Cluster mutation exports or local Product fallback.

### INV-FIX-02 — Fresh-Process Runtime Bootstrap Determinism

Concrete imports required by internal/recovery execution must work in a clean interpreter, independent of:

```text
prior import order
pytest collection order
sys.modules warm state
root package side effects
another runtime being loaded first
```

At minimum verify affected SIM and Backtest concrete Runtime imports.

### INV-FIX-03 — Package Aggregators Are Not Hidden Dependency Containers

Internal dependencies should prefer:

```text
leaf module → leaf module
```

instead of broad `__init__.py` aggregators when those introduce package initialization side effects.

### INV-FIX-04 — No Broad Rewrite

Do not mass-move Runtime packages, rename the hierarchy, add generic DI, or rewrite Engine/Runtime. Resolve the concrete cycle with the smallest coherent dependency-boundary correction.

### INV-FIX-05 — Checkpoint Completion Is Causal

Checkpoint completion must be grounded in:

```text
execution sequence
projection_ready
contiguous committed prefix
durable checkpoint
```

not in arbitrary wall-clock waiting.

### INV-FIX-06 — No Timeout Inflation as Primary Fix

Do not solve a race by changing `3s → 10s` unless evidence first proves the state transition itself is deterministic and the outer deadline alone was unrealistic.

### INV-FIX-07 — Historical Evidence Is a Frozen Interval

K7 historical evidence must validate:

```text
K7_TASK_BASE_SHA
→ K7_VERIFIED_CLOSURE_SHA
```

not:

```text
K7_TASK_BASE_SHA
→ current/future HEAD forever
```

### INV-FIX-08 — One Current Gateway Compatibility Authority

Current Gateway compatibility remains owned by:

```text
scripts/gateway_protocol.py verify
```

Do not duplicate that authority in the historical K7 delta test.

### INV-FIX-09 — Future Legitimate Development Must Not Be Frozen by K7

Future legal changes under `application/`, `runtime/`, `research/`, or `execution/` must not automatically fail a historical K7 proof merely because HEAD advanced.

### INV-FIX-10 — Semantic Preservation

Expected deltas:

```text
Product OpenAPI             = 0
Strategy/P9.0 semantics     = 0
Research identity/authority = 0
Gateway Proto               = 0
database schema             = 0
semantic fingerprint logic  = 0
```

### INV-FIX-11 — Project State Follows Evidence

```text
Evidence
→ verified state
```

Never the reverse.

## 6. F-K8-01 — Reproduce Fresh-Process Circular Import

Before editing, reproduce with clean interpreters, for example:

```bash
uv run python -c 'from onlyalpha.runtime.sim.runtime import OnlySimRuntime; print("SIM_IMPORT_OK")'

uv run python -c 'from onlyalpha.runtime.backtest.runtime import OnlyBacktestRuntime; print("BACKTEST_IMPORT_OK")'
```

Also reproduce the exact failing recovery test.

Record the actual traceback and dependency chain.

Inspect especially:

```text
onlyalpha.runtime.sim
onlyalpha.runtime.backtest
onlyalpha.runtime.streaming
onlyalpha.runtime.trading_facade
onlyalpha.runtime.checkpoint
```

Do not assume root cause from filenames.

## 7. Runtime Import Design Rule

Concrete implementation code should import concrete ownership modules directly.

Prefer:

```python
from onlyalpha.runtime.backtest.some_leaf_module import SomeType
```

over:

```python
from onlyalpha.runtime.backtest import SomeType
```

when the package `__init__.py` eagerly imports concrete Runtime constructors and participates in a cycle.

Inspect:

```text
runtime.sim.__init__
runtime.backtest.__init__
runtime.live.__init__
runtime.research.__init__
runtime.checkpoint.__init__
```

for eager aggregation that is part of the cycle.

## 8. Lazy Export vs Removing Aggregation

Do not mechanically make every package lazy.

Use:

```text
if constructor aggregation is not needed as a supported public surface
and internal callers can import the leaf module cleanly
→ remove eager aggregation
```

If a stable internal aggregation remains justified but eager import causes a cycle:

```text
→ use narrow lazy export only for the necessary symbol
```

Goal:

```text
package namespace ≠ dependency bootstrap mechanism
```

## 9. Permanent Fresh-Process Bootstrap Gate

Add a permanent test if no equivalent exists.

It must launch actual subprocesses / clean interpreters, for example:

```python
subprocess.run(
    [
        sys.executable,
        "-c",
        "from onlyalpha.runtime.sim.runtime import OnlySimRuntime",
    ],
    check=True,
)
```

Do not validate bootstrap only in the already-warmed pytest interpreter.

## 10. F-K8-01B — Classify SIM Checkpoint Failure

Treat it independently until evidence proves common root cause.

Run a classification matrix:

```text
A. failing test alone
B. repeated N times
C. serial execution
D. xdist/parallel execution if canonical
E. same test on known-good parent/base if available
```

Record:

```text
PASS/FAIL
elapsed time
actual execution state
actual projection-ready state
actual checkpoint sequence
```

Classify into exactly one of:

```text
real runtime synchronization race
test observation race
CI/resource timing issue with deterministic state contract
```

## 11. Checkpoint First-Principles Contract

Read actual checkpoint code before changing anything.

The authoritative transition must remain:

```text
committed execution
→ contiguous projection-ready transaction prefix
→ checkpoint capture
→ durable checkpoint
```

Do not introduce a second checkpoint authority.

Do not infer checkpoint completion solely from:

```text
order FILLED
sleep elapsed
polling eventually returned
```

## 12. If It Is a Real Runtime Race

Fix the narrowest existing causal boundary, such as:

```text
post-commit transition
projection-ready transition
checkpoint trigger
stable Runtime barrier
checkpoint persistence acknowledgement
```

Do not add a second state machine or new durable table unless existing architecture proves it absolutely necessary. A new durable authority would be an unexpected scope expansion.

## 13. If It Is a Test Observation Race

Replace arbitrary polling/timing with the strongest existing deterministic signal:

```text
existing barrier
existing completion acknowledgement
durable checkpoint query condition
existing future/event/condition
```

Do not add production complexity solely for test convenience.

## 14. F-K8-02 — Fix K7 Historical Verification Scope

Inspect:

```text
tests/contracts/test_p9_k7_task_delta.py
```

Replace the conceptual anti-pattern:

```text
K7_TASK_BASE_SHA
→ current HEAD
```

with an immutable historical interval:

```text
K7_TASK_BASE_SHA
→ K7_VERIFIED_CLOSURE_SHA
```

Use the actual repository-confirmed K7 verified closure SHA. Do not guess it.

The historical question must be:

```text
Did K7 itself change protected semantics during K7?
```

not:

```text
Has any future task ever changed these directories?
```

## 15. Separate Historical Proof from Current Compatibility

Historical K7 test owns:

```text
K7 historical scope preservation
```

Gateway checker owns:

```text
current protocol compatibility
```

Expected lane structure:

```text
gateway_protocol.py verify
→ current compatibility

test_p9_k7_task_delta.py
→ immutable historical K7 evidence
```

Do not modify Proto just to satisfy the historical test.

## 16. Project-State Handling

Use repository-owned `project_state.py` behavior.

While MAJOR findings remain unresolved, project-state must not falsely authorize P9.1.

After evidence passes, restore through official tooling:

```text
P9.K.8 = TASK COMPLETE / VERIFIED
P9.K   = CLOSED
P9.1   = IMPLEMENTATION READY
```

Do not make README/roadmap competing state authorities.

## 17. Preserve K8 Seal After Every Fix

Re-run architecture gates and keep:

```text
root mutation constructor exports = 0
legacy root Product CLI commands = 0
Product client Core imports = 0
Web Core imports = 0
local fallback = 0
API mutation route raw capability = 0
KNOWN_MIGRATION_DEBT = 0
LEGACY_K8_TARGET = 0
standalone Product compatibility HTTP debt = 0
```

A Runtime bootstrap fix that reopens any of these is invalid.

## 18. Likely Minimal Scope

Likely affected areas:

```text
src/onlyalpha/runtime/**/__init__.py
src/onlyalpha/runtime/**/*.py
tests/integration/*
tests/runtime/*
tests/architecture/*
tests/contracts/test_p9_k7_task_delta.py
project-state.toml
scripts/project_state.py
K8 closure report
```

Not every listed file must change.

## 19. Explicitly Out of Scope

Do NOT implement:

```text
P9.1
Binance
QMT implementation
CTP
Broker
Portfolio
Risk
LIVE
new Product endpoint
new Product command/query
new DB table/migration
new Gateway RPC/Proto field
new Strategy identity
new Research identity
generic DI
large package relocation
Engine redesign
Runtime redesign
```

## 20. Implementation Order

### Phase A — Freeze and Reproduce

Record:

```text
FIX_BASE_SHA
current project-state
current CI failures
fresh-process import failure
SIM checkpoint classification baseline
K7 historical test failure
```

### Phase B — Fix Runtime Bootstrap

Resolve actual dependency cycle with smallest import-ownership change.

Immediately re-run fresh-process imports.

### Phase C — Classify/Fix Checkpoint Failure

Determine whether the defect is Runtime synchronization, test observation, or CI timing around an already deterministic contract.

Fix cause, not symptom.

### Phase D — Fix Historical K7 Audit Scope

Freeze K7 evidence to immutable base/closure SHAs.

Keep current Gateway compatibility authority separate.

### Phase E — Re-run K8 Seal

Prove no Product bypass returned.

### Phase F — Reconcile Project State

Only after all applicable evidence passes, re-close K8/P9.K and authorize P9.1.

## 21. Required Verification

At minimum run current canonical equivalents of:

```text
fresh-process Runtime import tests
focused failing SIM recovery tests
canonical sim-recovery lane
K0/K6/K8 architecture tests
canonical architecture lane
gateway_protocol.py verify
historical K7 contract tests
remote Gateway integration tests
canonical gateway-protocol lane
recovery lane if impacted
Ruff
Ruff format
mypy
Import Linter
build
version sync
project-state check
git diff --check
```

Targeted K8 tests should include:

```bash
uv run pytest   tests/architecture/test_p9_k0_product_surfaces.py   tests/architecture/test_p9_k6_external_client_boundary.py   tests/architecture/test_p9_k8_kernel_seal.py   -q
```

plus any new fresh-process bootstrap regression test.

## 22. Semantic Delta Proof

Before closure prove:

```text
Product OpenAPI delta              = 0
Strategy/P9.0 semantic delta       = 0
Research identity delta            = 0
Gateway Proto delta                = 0
database migration delta           = 0
semantic fingerprint delta         = 0
```

Import topology changes are allowed. Business semantic changes are not expected.

## 23. Re-Audit Known Findings

### F-K8-01 Runtime Bootstrap

RESOLVED requires:

```text
fresh-process import PASS
canonical relevant recovery path PASS
no K8 Product-seal regression
```

### F-K8-01B Checkpoint Completion

RESOLVED requires:

```text
root cause classified
deterministic completion condition established
targeted test stable
no arbitrary sleep-based masking
```

If conclusively proven to be non-regression/environment-only, document the evidence.

### F-K8-02 Historical K7 Verification

RESOLVED requires:

```text
historical range is immutable and closed
future/current HEAD is no longer historical end boundary
current Gateway compatibility remains separately enforced
gateway-protocol lane PASS
```

## 24. Gate Rule

GO iff:

```text
BLOCKER = 0
MAJOR   = 0

K8 core invariants PASS
fresh-process Runtime bootstrap PASS
SIM recovery impacted tests PASS
Gateway current compatibility PASS
K7 historical evidence PASS
no frozen design/ADR violation
Task-Gate evidence sufficient
```

MINOR/SUGGESTION do not block.

Once GO conditions are satisfied, STOP. Do not invent optional improvements.

## 25. Expected Final State

Only after closure:

```text
P9.K.8 = TASK COMPLETE / VERIFIED
P9.K   = CLOSED
P9.1   = IMPLEMENTATION READY
```

Then STOP. Do not start P9.1 in this task.

## 26. Healthy Diff Shape

Expected:

```text
small Runtime import-boundary correction
small deterministic checkpoint/test correction if evidence requires
historical K7 verification-boundary correction
fresh-process regression gate
project-state/report closure update
```

Suspicious:

```text
new framework
new protocol
new database model
new Product endpoint
large Runtime rewrite
mass package move
P9.1 code
```

If the suspicious pattern appears, reassess scope.

## 27. Final Codex Response Format

```text
P9.K.8 Closure Fix

FIX_BASE_SHA:
FINAL_SHA / WORKTREE:

F-K8-01 Runtime bootstrap:
- root cause:
- fix:
- fresh-process evidence:
- status:

F-K8-01B SIM checkpoint:
- classification:
- root cause:
- fix:
- deterministic evidence:
- status:

F-K8-02 K7 historical verification:
- old scope:
- corrected immutable range:
- current Gateway compatibility authority:
- status:

K8 seal preservation:
- root mutation exports: 0
- root run/snapshot: 0
- client Core imports: 0
- local fallback: 0
- KNOWN_MIGRATION_DEBT: 0
- LEGACY_K8_TARGET: 0

Semantic deltas:
- Product OpenAPI:
- Strategy/P9.0:
- Research identity:
- Gateway Proto:
- DB schema:
- fingerprints:

Verification:
- fresh-process imports: PASS/FAIL
- sim-recovery: PASS/FAIL
- recovery: PASS/FAIL/N/A
- K8 architecture: PASS/FAIL
- gateway-protocol: PASS/FAIL
- static: PASS/FAIL
- Import Linter: PASS/FAIL
- mypy: PASS/FAIL
- build: PASS/FAIL
- version sync: PASS/FAIL
- project-state: PASS/FAIL
- git diff --check: PASS/FAIL

Audit:
BLOCKER = N
MAJOR = N
MINOR = N
SUGGESTION = N

Verdict:
GO / NO-GO

If GO:
P9.K.8 = TASK COMPLETE / VERIFIED
P9.K   = CLOSED
P9.1   = IMPLEMENTATION READY
```

## 28. Mandatory Stop Condition

When:

```text
F-K8-01 = RESOLVED
F-K8-01B = RESOLVED or conclusively classified non-regression
F-K8-02 = RESOLVED
BLOCKER = 0
MAJOR = 0
all applicable K8 invariants PASS
```

STOP.

Do not do extra cleanup.
Do not start P9.1.

## 29. Engineering Definition

> This closure fix restores deterministic Runtime bootstrap, establishes a causally defined recovery/checkpoint completion contract, freezes K7 historical audit evidence to its own immutable interval, preserves one current Gateway compatibility authority, and re-closes P9.K.8 without reopening any Product mutation bypass or changing business semantics.
