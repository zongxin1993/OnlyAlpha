# OnlyAlpha P9.T Final Durable Drain Lifecycle Closure
## Codex Implementation Task Prompt

> **Repository:** `zongxin1993/OnlyAlpha`  
> **Observed audit baseline:** `master@99f71f7acd8603322df48d3ca2810c6d40e33801`  
> **Observed failing CI run:** Layered Quality `33461860922`  
> **Task type:** High-risk bounded correctness / lifecycle closure  
> **Primary finding:** `F-P9T-001 — Durable Market Data Drain Lifecycle Closure`  
> **Severity:** High / Stage Blocker  
> **Constitution impact:** MUST be `NO`  
> **Purpose:** Close the real lifecycle regression introduced with the P9.T normal-operation durable drain, restore the existing architecture contract, prove bounded shutdown and restart recovery, then STOP.  
> **This is not a new architecture phase. Do not reopen P9.T or P9.4A broadly.**

---

# 0. Mandatory governance order

Before planning, editing, refactoring, writing tests, or changing any lifecycle behavior, read the current repository in this exact authority order:

```text
1. PROJECT_CONSTITUTION.md
2. Relevant Architecture / public Contracts
3. Relevant Accepted ADRs
4. Roadmap / current P9.T context
5. AGENTS.md
6. Current source + tests + executable behavior
```

At minimum inspect the current versions of:

```text
PROJECT_CONSTITUTION.md
AGENTS.md

docs/market_data_source.md
docs/p9_binance_spot_golden_vertical_execution_plan.md
docs/p9_production_trading_vertical_architecture.md

relevant accepted ADRs governing:
- market-data durability / WAL
- market-data revision / recovery
- Runtime lifecycle / shutdown / recovery
- persistence authority
- deterministic recovery

src/onlyalpha/market_data/durable/drain.py
src/onlyalpha/market_data/durable/recorder.py
src/onlyalpha/market_data/durable/recovery.py
src/onlyalpha/market_data/durable/revision.py
src/onlyalpha/market_data/durable/wal.py
src/onlyalpha/market_data/durable/models.py

src/onlyalpha/runtime/sim/factory.py

src/onlyalpha/persistence/clickhouse/config.py
src/onlyalpha/persistence/clickhouse/client.py
src/onlyalpha/persistence/postgres/config.py
src/onlyalpha/persistence/postgres/market_data_catalog.py

tests/architecture/test_graceful_shutdown_boundaries.py
tests/market_data_durable/test_rolling_recorder_and_drain.py
directly related market-data recovery tests

scripts/verify.py
scripts/test_suite.py
quality-policy.toml
pyproject.toml
```

Also inspect any current file that directly owns the worker lifecycle or composes the recorder/drain if paths have changed.

Record the **current** HEAD before implementation.

The SHA above is only the audit baseline that exposed the defect. It is not an immutable task target.

If current HEAD has changed:

```text
reproduce / re-check F-P9T-001 on current HEAD
```

If the defect has already been correctly fixed and the affected gates are green:

```text
NO-OP
report evidence
STOP
```

Do not reintroduce work merely because this prompt describes an older baseline.

---

# 1. Constitution impact check

Before implementation answer:

```text
Does this task conflict with, weaken, reinterpret,
or require changing PROJECT_CONSTITUTION.md?
```

The only valid ordinary engineering answer is:

```text
NO
```

If the answer is `YES` or cannot be proven `NO`:

```text
PLAN_CONFLICT
STOP IMPLEMENTATION
```

Never modify:

```text
PROJECT_CONSTITUTION.md
its pinned fingerprint
```

to solve this task.

---

# 2. Current observed defect

On the audited baseline:

```text
master@99f71f7acd8603322df48d3ca2810c6d40e33801
```

the normal-operation market-data drain contains the equivalent of:

```python
threading.Thread(
    target=self._run,
    name="market-data-durable-drain",
    daemon=True,
)
```

and shutdown contains an unbounded equivalent of:

```python
worker.join()
```

The architecture regression test:

```text
tests/architecture/test_graceful_shutdown_boundaries.py
::test_onlyalpha_owned_threads_are_not_daemon_escape_hatches_and_joins_are_bounded
```

correctly rejects this.

Observed CI result on the audited baseline:

```text
architecture
→ FAIL

core-full
→ FAIL
```

Both failures converge to the same production source:

```text
src/onlyalpha/market_data/durable/drain.py
```

Do not classify this as an unrelated historical failure.

The drain implementation entered the affected history as part of P9.T realtime Trade reference / durable drain work, so this is an attributable current-stage regression.

---

# 3. First-principles analysis

## 3.1 Start from the real durable truth

The durable acceptance chain is:

```text
Provider Observation
        ↓
WAL append
        ↓
fsync
        ↓
sealed / recoverable WAL fact
```

Once the observation is durably owned by the WAL, the system has not yet necessarily converged to:

```text
ClickHouse
PostgreSQL
Revision / Manifest
GC
```

but the truth is no longer only in volatile memory.

Therefore:

```text
WAL durability
!=
database drain completion
```

and:

```text
database drain
is convergence work
not the primary acceptance authority
```

This distinction is essential.

---

## 3.2 Clean shutdown does not require full database convergence

The Constitution requires:

```text
Crash / Restart are normal lifecycle events

Durable facts
+ deterministic reconstruction
+ reconciliation where applicable
→ one authoritative state
```

Therefore a correct clean shutdown may legally end with:

```text
sealed uncommitted WAL backlog > 0
```

provided:

```text
the WAL is intact
the backlog is discoverable
the state is explicit
the next process uses the same recovery authority
the same facts converge exactly once / idempotently
```

It is **not** correct to define graceful shutdown as:

```text
process may exit
ONLY AFTER
all ClickHouse/PostgreSQL work finishes
```

because database/network availability is not a safe lifecycle precondition.

This is the first major design correction.

---

## 3.3 Why `daemon=True` is wrong

A daemon thread means process termination may discard that worker without a formal ownership handoff.

For a worker participating in durable state convergence, that creates an implicit lifecycle escape hatch:

```text
process exits
→ Python abandons worker
→ service never proves what work completed
```

Even if WAL prevents data loss, the component would still falsely outsource its lifecycle semantics to interpreter termination.

OnlyAlpha-owned production workers must have explicit ownership.

Therefore:

```text
daemon=True
→ forbidden
```

for this Core-owned drain worker.

---

## 3.4 Why unbounded `join()` is also wrong

The opposite mistake is:

```text
non-daemon thread
+
unbounded join
```

If ClickHouse, PostgreSQL, filesystem, DNS, socket, or another downstream operation stalls, Runtime shutdown can stall indefinitely.

That violates:

```text
Explicit Boundaries
Recoverability
Failure semantics
Lifecycle
```

An owned worker must have:

```text
explicit stop request
+
bounded wait
+
explicit timeout failure
```

---

## 3.5 Why `daemon=False + join(timeout=...)` alone is still insufficient

Do **not** mechanically patch:

```python
daemon=False
worker.join(timeout=5)
```

and declare closure.

Python cannot safely kill a running thread.

If the worker is inside an operation that itself has no operational bound, then after `join(timeout)`:

```text
stop() returns/raises
BUT
non-daemon worker remains alive
```

and process exit may still be delayed by the same worker.

Therefore the lifecycle proof has two layers:

```text
Layer A
owned thread shutdown wait is bounded

Layer B
the work unit executed by that thread has bounded / interruptible
operational behavior sufficient to converge after stop request
```

The current repository already contains explicit external I/O bounds in relevant persistence paths, including ClickHouse request timeout and PostgreSQL operational connection/statement/tcp bounds.

Inspect the actual current paths and prove they are the paths used by the drain.

Do not assume.

---

## 3.6 The deeper architectural mistake: "bounded" was underspecified

The original P9.T requirement said conceptually:

```text
sealed WAL
→ bounded normal-operation drain
```

The implementation bounded:

```text
in-memory queue capacity
```

but did not fully freeze:

```text
worker ownership
worker lifecycle
shutdown wait
current-work behavior
remaining-backlog behavior
timeout failure state
restart convergence
```

Therefore "bounded" was interpreted as a data-structure property rather than a lifecycle contract.

The closure must define both:

```text
bounded backlog signaling
AND
bounded lifecycle behavior
```

---

## 3.7 The in-memory queue is not a second durable authority

The sealed WAL is the durable backlog authority.

The in-memory queue is at most:

```text
normal-operation scheduling / wakeup state
```

It must never become:

```text
the only list of work that must survive
```

Therefore:

```text
queue full
process stop
worker timeout
queue loss
```

must not make a WAL-sealed segment unrecoverable.

If current normal-operation behavior uses a queued segment only as a wakeup and `recover_all()` discovers the actual WAL backlog, preserve that property unless a smaller correct change is proven.

If changing to segment-specific processing, explicitly preserve:

```text
queue-overflow segment
→ still discoverable from WAL
→ later normal drain or restart recovery
→ deterministic convergence
```

Do not create an in-memory truth list.

---

# 4. Root-cause classification

Classify the defect as follows.

## Root Cause A — lifecycle contract missing from drain service

Current drain code has operational behavior but no sufficiently explicit one-way lifecycle contract.

The service needs to distinguish at least conceptually:

```text
NEW / NOT_STARTED
RUNNING
STOPPING
STOPPED
FAILED_STOP / FAILED
```

Exact public enum is **not required**.

Prefer private state/flags if sufficient.

Do not create a new public contract just for symmetry.

---

## Root Cause B — shutdown incorrectly coupled to convergence

Current SIM composition performs the equivalent of:

```text
drain.stop()
drain.drain_pending()
```

during close.

That makes normal Runtime shutdown attempt synchronous persistence convergence after worker shutdown.

From first principles this is unnecessary and can make shutdown duration proportional to durable backlog / database condition.

The correct ownership rule is:

```text
Recorder.close()
→ seal non-empty tail
→ WAL owns remaining truth

Drain.stop()
→ stop normal-operation worker within bounded lifecycle semantics

Remaining sealed WAL
→ recovered by the existing Recovery Coordinator on next startup
```

Do not require the database backlog to be empty before Runtime close is considered semantically safe.

If current architecture has an explicit operator command for synchronous draining, keep that separate from normal Runtime lifecycle.

---

## Root Cause C — no regression proving blocked-worker shutdown

Existing durability tests prove:

```text
database failure keeps WAL
recovery later converges
```

but the audited baseline did not prove:

```text
worker is blocked / slow
+
shutdown requested
→ bounded lifecycle result
→ no false STOPPED state
→ no concurrent fallback recovery
→ durable backlog remains recoverable
```

That missing evidence allowed the defect through.

---

## Root Cause D — normal operation and crash recovery authority are correctly shared, but lifecycle ownership is not

Do not replace:

```text
OnlyMarketDataRecoveryCoordinator
```

with another worker-specific persistence/recovery implementation.

The right architecture is still:

```text
normal drain
        ┐
        ├→ same Recovery / Revision authority
restart ┘
```

The problem is worker lifecycle, not recovery authority.

---

# 5. Frozen Task Contract

## 5.1 Goal

Close `F-P9T-001` so that:

```text
1. the durable drain worker is explicitly owned;
2. no daemon escape hatch exists;
3. shutdown wait is bounded;
4. timeout is explicit and fail-closed;
5. no false STOPPED state is published;
6. no concurrent second recovery path is started as a timeout workaround;
7. remaining sealed WAL stays authoritative and recoverable;
8. restart converges through the existing recovery coordinator;
9. architecture/core/recovery regression gates return green;
10. no unrelated P9.T redesign occurs.
```

---

## 5.2 Modification Scope

Expected modification scope is deliberately narrow.

Likely files:

```text
src/onlyalpha/market_data/durable/drain.py
src/onlyalpha/runtime/sim/factory.py

tests/market_data_durable/test_rolling_recorder_and_drain.py
tests/architecture/test_graceful_shutdown_boundaries.py
directly related recovery/lifecycle regression tests
```

Only if actual dependency proof requires it, narrowly extend to:

```text
src/onlyalpha/market_data/durable/recovery.py
src/onlyalpha/market_data/durable/models.py

directly affected persistence timeout wiring/tests
directly affected architecture documentation
```

Do not modify a file merely because it is adjacent.

---

## 5.3 Expected Impact Scope

This is a high-risk task because a bad fix can affect:

```text
durable market-data integrity
normal-operation persistence convergence
shutdown correctness
restart recovery
thread ownership
Runtime lifecycle
single Recovery Authority
determinism
```

Expand impact only to the nearest stable boundary proven by real dependencies.

---

## 5.4 Constitution Impact

```text
NO
```

This task restores existing constitutional requirements:

```text
Explicit Boundaries
Recoverability
Fail-Closed
Single Authority
Determinism
Traceability
```

It does not change product goals.

---

# 6. Required design

## 6.1 Worker ownership

The Core-owned durable drain worker MUST be:

```text
non-daemon
explicitly started
explicitly stopped
owned by exactly one drain service instance
```

Do not use:

```python
daemon=True
```

Do not rely on interpreter exit as cleanup.

---

## 6.2 One-way lifecycle

The same drain service instance should not silently resurrect after stop.

Required semantic shape:

```text
NEW
  ↓ start
RUNNING
  ↓ stop request
STOPPING
  ├→ worker exits → STOPPED
  └→ bounded wait expires → explicit FAILED/timeout condition
```

A later call to `start()` after a completed stop must not create a second worker on the same service object.

Prefer:

```text
raise stable lifecycle error
```

over silent restart.

Do not introduce a public lifecycle enum unless the existing architecture requires one.

---

## 6.3 Bounded stop

Use a named, explicit operational timeout.

Conceptually:

```python
_JOIN_TIMEOUT_SECONDS = ...
```

or an equivalent injected/configured bound already consistent with repository conventions.

Shutdown must:

```text
set stop intent
wake an idle worker if needed
capture the worker reference
wait with a timeout
verify thread liveness
```

Do not use unbounded:

```python
worker.join()
```

If the worker is still alive after the bound:

```text
do not set worker = None
do not report STOPPED
do not run a concurrent synchronous drain fallback
record stable lifecycle failure
raise an explicit error
```

Use an existing error type/taxonomy if appropriate.

Otherwise use a narrow stable code equivalent to:

```text
MARKET_DATA_DRAIN_STOP_TIMEOUT
```

Do not invent a large new hierarchy.

---

## 6.4 Stop retry / idempotency semantics

`stop()` must be safe to call more than once.

But idempotency must not mean:

```text
first stop timed out
second stop returns success without checking worker
```

Required semantic behavior:

```text
once stop is requested
→ no restart / no new worker

if prior stop already completed
→ later stop is a no-op

if prior stop timed out and worker is still alive
→ later stop may re-observe / bounded-wait the same worker

when that worker has actually exited
→ state can converge to STOPPED
```

Do not lose the worker reference while it is alive.

---

## 6.5 Idle worker must wake promptly on stop

An idle worker must not require an arbitrary sleep to notice shutdown.

The current queue timeout may be retained only if it provides a clearly bounded, acceptable stop latency.

Prefer an existing `Event` / `Condition` / explicit wake mechanism if a minimal change makes ownership clearer.

Do not add `sleep()` loops.

Correctness tests must use:

```text
Event
Condition
Barrier
controlled fake
```

not wall-clock sleeping.

---

## 6.6 Current work vs remaining backlog

On stop:

```text
do not start new drain work after stop intent
```

The worker may either:

```text
finish the current bounded recovery work unit
```

or follow an existing safe cooperative boundary.

It does **not** need to drain the entire WAL backlog before exiting.

Remaining backlog is valid because:

```text
WAL is durable authority
```

This is the central shutdown invariant.

---

## 6.7 Remove unbounded synchronous shutdown drain from normal Runtime close

Inspect current SIM composition.

On the audited baseline the composition has the equivalent of:

```python
def close_drain() -> None:
    drain.stop()
    drain.drain_pending()
```

Do not preserve this pattern blindly.

Normal Runtime close should not force all database convergence after stopping the worker.

Preferred semantics:

```text
OnlyDurableMarketDataRecorder.close()
    ↓
seal non-empty tail
    ↓
on_sealed schedules/wakes normal drain while lifecycle permits
    ↓
on_close requests bounded drain stop
    ↓
remaining sealed WAL is intentionally left recoverable
```

Then on new process startup the already-existing path:

```text
OnlyMarketDataRecoveryCoordinator.recover_all()
```

owns convergence before normal drain begins.

If current source has changed, preserve this invariant using the smallest current equivalent.

Do not delete `drain_pending()` if it remains useful as a deterministic test/operator helper.

But normal product shutdown must not use an unbounded full-backlog drain.

---

## 6.8 `drain_pending()` concurrency rule

If `drain_pending()` remains:

```text
it must never race the background worker over the same Recovery Authority
```

Define a clear contract.

Preferred:

```text
drain_pending()
→ deterministic non-threaded helper
→ legal only when worker is not running
```

If called while worker is alive / stopping, fail explicitly rather than creating concurrent recovery.

Do not use it as a timeout fallback.

---

## 6.9 External I/O bound proof

Before selecting a join bound, inspect the real normal drain call graph.

Prove the current drain path uses bounded external operations.

At the audited baseline verify at least:

```text
ClickHouse
→ explicit HTTP request timeout

PostgreSQL
→ operational DSN with connect / statement / lock / tcp user timeouts
```

Do not weaken those bounds.

Do not add giant timeouts merely to make shutdown tests pass.

If the worker can remain inside one `recover_all()` call for an amount of work that makes bounded shutdown impossible even though individual I/O calls are bounded, implement the **smallest** recovery work-boundary correction.

Permitted direction only if proven necessary:

```text
normal-operation worker
→ one bounded/cooperative recovery unit
→ check stop
→ next unit
```

Requirements for such a change:

```text
same OnlyMarketDataRecoveryCoordinator authority
same revision/manifest semantics
same idempotency
same WAL discovery
same crash recovery behavior
no second persistence state machine
```

Do not automatically add a new recovery API unless this proof shows it is required.

---

## 6.10 Preserve WAL discovery when the in-memory queue is full

Current design intentionally permits:

```text
queue full
→ health DEGRADED
→ sealed WAL remains authoritative
```

That is acceptable only if the segment is still discoverable for later convergence.

Add/retain proof that:

```text
segment sealed successfully
+
normal drain scheduling queue cannot accept its notification
→ segment remains in WAL
→ later normal recovery opportunity OR next restart
→ same segment converges
```

Never change to:

```text
queue entry missing
→ durable segment forgotten forever
```

---

## 6.11 Failure state semantics

Normal database outage:

```text
WAL preserved
drain health = DEGRADED
last error explicit
Runtime does not pretend database convergence
```

Lifecycle stop timeout is stronger than a normal transient drain failure.

Use the existing health model where possible.

A stop timeout should be visible as an explicit failure condition, not overwritten immediately by a later unrelated successful operation while the worker is still alive.

Do not create a second health Authority.

---

## 6.12 Thread-safe service state

Lifecycle and health state are read/written from multiple threads.

Ensure the relevant mutable fields are synchronized by the existing lock/condition or an equivalent minimal mechanism:

```text
worker reference
stop intent
lifecycle flags/state
last error where required
```

Do not rely on accidental CPython scheduling as the contract.

Avoid over-locking database work.

Locks should protect lifecycle state, not surround long external I/O.

---

# 7. Required invariants after implementation

Freeze these invariants before coding.

## I1 — WAL Authority

```text
If a segment was successfully sealed,
its recoverability does not depend on the in-memory drain queue.
```

## I2 — No daemon escape

```text
Core-owned durable drain worker is never daemon.
```

## I3 — Bounded lifecycle wait

```text
stop() has an explicit bounded wait.
```

## I4 — No false stop

```text
worker still alive
→ service cannot claim STOPPED
→ worker reference cannot be discarded
```

## I5 — No concurrent recovery fallback

```text
stop timeout
→ no second drain/recover_all launched concurrently
```

## I6 — Shutdown does not require DB empty

```text
clean close may leave sealed WAL backlog
without losing correctness.
```

## I7 — Restart convergence

```text
remaining WAL
→ same Recovery Coordinator
→ deterministic idempotent convergence
```

## I8 — No second Authority

```text
normal drain
and
crash recovery
share the existing recovery/revision authority.
```

## I9 — No silent restart

```text
stopped service instance
→ cannot create a new worker through start()
```

## I10 — Failure remains explicit

```text
database outage / queue pressure / stop timeout
→ visible state
→ never false success
```

---

# 8. Mandatory regression tests

Use deterministic synchronization only.

No `sleep()`.

No retry-until-green.

No oversized timeout.

## T1 — Architecture regression

The existing test must pass without weakening it:

```text
tests/architecture/test_graceful_shutdown_boundaries.py
::test_onlyalpha_owned_threads_are_not_daemon_escape_hatches_and_joins_are_bounded
```

Do not modify this test merely to allow the current implementation.

Only change it if independent evidence proves the rule itself is incorrect; this task does not currently authorize that.

---

## T2 — Idle start/stop

Prove:

```text
start
→ worker alive and non-daemon

stop
→ worker exits
→ bounded
→ no pending lifecycle ambiguity
```

Test deterministically.

---

## T3 — Stop is idempotent

Prove:

```text
stop
stop
stop
```

does not:

```text
start another worker
raise after already-completed clean stop
mutate durable truth
```

---

## T4 — Restart of same service object is rejected

Prove:

```text
start
stop
start
→ explicit lifecycle rejection
```

unless current higher-level public contract already requires restartability.

If it does, stop and justify before implementing a different state machine.

Do not silently preserve accidental restartability.

---

## T5 — Blocked recovery does not produce false STOPPED

Use a controlled fake recovery boundary:

```text
worker enters recovery
→ Event marks entered
→ recovery waits on Event
→ stop requested
```

Prove:

```text
bounded stop timeout occurs
worker reference remains
service exposes failure
no drain_pending/recover_all fallback runs concurrently
```

Then release the fake recovery and prove the same worker exits and a subsequent stop/observation can converge lifecycle state safely.

The test must not leave a non-daemon thread alive at test completion.

---

## T6 — Clean shutdown with undrained tail remains recoverable

Create:

```text
record
→ seal tail during recorder.close
→ prevent database convergence
→ close drain
```

Assert:

```text
sealed WAL still exists
no false DB commit
```

Create a new WAL/recovery process boundary and prove:

```text
recover_all()
→ same segment
→ exact convergence
→ WAL becomes GC eligible according to existing semantics
```

This is the core recoverability proof.

---

## T7 — Database failure during normal drain

Preserve and strengthen the existing test:

```text
database unavailable
→ worker/drain cannot commit
→ sealed WAL remains
→ health DEGRADED
```

Then:

```text
database restored
→ same recovery authority
→ idempotent convergence
```

No duplicate canonical fact.

---

## T8 — Queue pressure cannot lose durable backlog

With deliberately tiny in-memory drain capacity:

```text
seal more segments than scheduling queue can hold
```

Prove:

```text
all sealed segments remain discoverable in WAL
```

and eventually:

```text
normal drain or fresh-process recovery
→ all authoritative segments converge
```

The in-memory queue must not be the recovery truth.

---

## T9 — No concurrent background + synchronous recovery

Instrument the fake Recovery Coordinator with a deterministic mutual-exclusion counter.

Prove the maximum concurrent invocation caused by one drain service is:

```text
1
```

especially around:

```text
stop
timeout
close
drain_pending
```

---

## T10 — Shutdown does not require backlog == 0

Create multiple durable sealed segments, stop the worker before all are drained, and prove:

```text
stop can complete safely
AND
WAL backlog remains
AND
fresh recovery converges it
```

Do not assert that clean shutdown must empty WAL.

---

## T11 — Existing crash-boundary recovery remains unchanged

Run directly affected existing tests for:

```text
C1 ... C7 market-data crash boundaries
idempotent restart
revision/manifest consistency
WAL GC eligibility
```

No recovery weakening is allowed.

---

## T12 — Existing P9.T Trade reference behavior remains unchanged

Because this drain was introduced in the P9.T path, run the nearest affected tests proving:

```text
Trade durability still works
Trade reference correctness unchanged
Strategy remains Bar-only
```

Do not redesign Strategy / Risk / execution reference in this task.

---

# 9. Implementation sequence

Follow this order.

## Phase A — Reproduce and freeze scope

1. Read current authority documents.
2. Record current HEAD.
3. Reproduce the architecture failure on current HEAD.
4. Confirm exact offending lifecycle code.
5. Confirm no newer correct fix already exists.
6. Freeze the Task Contract above.
7. `Constitution Impact = NO`.

Do not perform a repository-wide audit.

---

## Phase B — Make worker ownership explicit

Implement the smallest correct lifecycle changes:

```text
non-daemon ownership
one-way lifecycle
explicit stop intent
bounded join
liveness verification
no false worker cleanup
```

Do not yet redesign recovery.

Run the direct lifecycle tests.

---

## Phase C — Remove shutdown/database convergence coupling

Inspect product composition.

Change normal Runtime close so that:

```text
seal durable tail
→ stop worker
→ leave remaining WAL recoverable
```

Do not synchronously empty the entire durable backlog as a normal shutdown requirement.

Keep deterministic non-threaded drain helpers only if they remain useful and safe.

---

## Phase D — Prove work-unit boundedness

Inspect actual ClickHouse/PostgreSQL call paths and timeout configuration.

If current worker behavior is sufficiently bounded after lifecycle changes, do not add abstractions.

If not:

```text
implement the smallest cooperative/bounded recovery work boundary
inside the existing recovery authority
```

Do not create a second recovery engine.

---

## Phase E — Add deterministic regression evidence

Implement T1–T12 as applicable to the actual source.

Tests must reproduce the old failure and prove the corrected lifecycle.

---

## Phase F — Impact-aware validation

Follow `AGENTS.md`.

Start with targeted validation.

Then use the repository's actual `scripts/verify.py` interface to select affected validation.

Do not guess or modify the selector.

At minimum execute directly affected equivalents of:

```text
targeted durable drain tests
targeted recorder/recovery tests
targeted graceful-shutdown architecture test

affected ruff check
affected ruff format --check
affected mypy

nearest affected canonical lane
architecture lane
recovery lane
```

Because the audited regression also broke `core-full`, after targeted/impact-aware tests are green, execute:

```text
core-full
```

to prove the exact known regression is closed.

If this closure is the final blocker for the P9.T milestone, execute the applicable Major Milestone Phase Gate **once** according to `quality-policy.toml` and current governance.

Do not run the full repository Phase Gate repeatedly during development.

---

## Phase G — One bounded Independent Review

Perform exactly one focused review after implementation.

Review only:

```text
Modification Scope
+ actual Impact Scope
+ directly related Constitution/Architecture invariants
```

Then STOP.

Do not use review to reopen P9.T, Binance, Web, Futures, LIVE, or unrelated technical debt.

---

# 10. Bounded Independent Review questions

Answer each explicitly.

1. Can the durable drain worker still be abandoned through `daemon=True`?
2. Can Runtime shutdown wait forever on the drain worker?
3. Can `stop()` report success while its worker is alive?
4. Can a timed-out stop discard the worker reference?
5. Can a timed-out stop start a second synchronous recovery path concurrently?
6. Does normal clean shutdown still require the full ClickHouse/PostgreSQL backlog to become empty?
7. Can a sealed WAL segment be lost because the in-memory scheduling queue is full?
8. Can stopping with pending backlog lose a segment?
9. Does fresh-process recovery use the same `OnlyMarketDataRecoveryCoordinator` authority?
10. Can normal drain and restart recovery create different durable semantics for the same WAL facts?
11. Is any new public lifecycle/persistence contract introduced unnecessarily?
12. Are ClickHouse/PostgreSQL operations used by the worker operationally bounded?
13. Can the service restart the same worker instance after stop without an explicit contract?
14. Are lifecycle fields accessed without synchronization?
15. Did any test, quality rule, architecture assertion, timeout policy, or CI gate get weakened to hide the defect?
16. Did this task accidentally change Strategy, Risk, Order, Broker, Binance, or execution-reference semantics?
17. Does the final solution preserve exact WAL/revision/recovery idempotency?
18. Are Critical = 0 and High = 0 inside the actual scope?

Fix Critical/High findings inside scope.

Medium/Low findings do not automatically expand this task.

---

# 11. Explicitly forbidden shortcuts

Do not solve this task with any of the following:

```text
delete/disable test_graceful_shutdown_boundaries
change architecture test to allow daemon=True
skip / xfail the failure
remove the architecture lane
remove core-full coverage of this test
increase timeout until CI happens to pass
sleep() in tests
retry-until-green
catch and ignore join timeout
set worker=None while worker is alive
switch back to daemon thread after timeout
force-kill Python thread
synchronously drain all DB backlog during every shutdown
create a second MarketDataRecoveryCoordinator implementation
create a second DB truth
silently drop WAL backlog
treat queue contents as durable authority
modify PROJECT_CONSTITUTION.md
weaken AGENTS.md / quality-policy.toml / scripts/test_suite.py
```

---

# 12. Out of scope

Do not implement:

```text
P9.5 LIVE Runtime Safety
Binance Futures
new Broker work
new market-reference types
Quote/L1
Tick Strategy
valuation redesign
WAL redesign without direct proof
new database
new persistence architecture
async ClickHouse/PostgreSQL rewrite
multiprocessing rewrite
generic thread framework
repository-wide lifecycle refactor
all daemon threads in external provider packages
unrelated performance optimization
unrelated CI cleanup
```

Provider package daemon/thread behavior is outside this task unless a direct dependency proves it blocks this Required Behavior.

---

# 13. Compatibility requirements

This closure should normally avoid changing:

```text
public Python API
Provider/Broker SPI
wire protocol
Strategy Revision fingerprint
Order snapshot
Order Intent persistent schema
Market Fact identity
WAL persistent format
PostgreSQL schema
ClickHouse schema
Runtime checkpoint format
```

If any such change becomes necessary:

```text
STOP
prove why the current stable boundary cannot express the Required Behavior
classify compatibility impact
add migration/consumer evidence
```

Do not silently introduce a breaking change.

---

# 14. Expected final architecture

Normal operation:

```text
Provider observation
        ↓
WAL append + fsync
        ↓
Durable acceptance
        ↓
rolling segment
        ↓
seal
        ↓
normal-operation scheduling signal
        ↓
┌─────────────────────────────────────┐
│ OnlyMarketDataDrainService          │
│                                     │
│ owned non-daemon worker             │
│ explicit lifecycle                  │
│ bounded shutdown wait               │
└─────────────────┬───────────────────┘
                  ↓
       Existing Recovery Authority
                  ↓
        ClickHouse exact facts
                  ↓
          exact verification
                  ↓
 PostgreSQL manifest / revision commit
                  ↓
          WAL GC eligibility
```

Shutdown:

```text
stop provider production
        ↓
Recorder.close()
        ↓
seal durable tail
        ↓
request drain worker stop
        ↓
bounded wait
        ├── worker exits
        │      ↓
        │   clean lifecycle stop
        │
        └── timeout
               ↓
          explicit failure
          no false STOPPED
          no second recovery worker

remaining sealed WAL is valid durable backlog
```

Restart:

```text
new process
    ↓
open WAL
    ↓
existing OnlyMarketDataRecoveryCoordinator.recover_all()
    ↓
same exact durable convergence
    ↓
start normal-operation drain
```

The key equation is:

```text
Safe shutdown
=
durable truth preserved
+ explicit worker ownership
+ bounded lifecycle wait
+ deterministic restart recovery
```

NOT:

```text
Safe shutdown
=
database backlog must be empty
```

---

# 15. Stop Condition

This task is complete only when all are true:

```text
Required Behavior implemented

AND

existing architecture regression PASS

AND

targeted lifecycle tests PASS

AND

durable recorder/drain/recovery tests PASS

AND

affected static/type checks PASS

AND

architecture lane PASS

AND

recovery lane PASS

AND

core-full PASS for the known regression

AND

applicable one-time final Phase Gate PASS
if this is the actual P9.T milestone closure

AND

Constitution consistency PASS

AND

bounded Independent Review complete

AND

current-scope Critical = 0

AND

current-scope High = 0
```

Then:

```text
STOP
```

Do not continue into a new feature.

Do not create a completion report, audit report, final-SHA certification file, progress file, or new historical prompt inside the repository.

---

# 16. Required Codex final response

At the end report only the bounded task result:

```text
1. Current HEAD audited
2. Constitution Impact
3. Frozen Task Contract
4. Root cause confirmed
5. Actual files changed
6. Worker lifecycle design implemented
7. Shutdown/backlog semantics
8. Recovery Authority preservation
9. Compatibility judgment
10. Tests / validation actually executed
11. Known architecture/core/recovery gate results
12. Bounded Independent Review result
13. Critical count
14. High count
15. Stop Condition
16. Current Beijing time
```

Do not claim PASS for checks that were not executed.

Do not treat pending CI as PASS.

Do not expand scope because Medium/Low findings exist.

---

# 17. Final implementation instruction

This is a **closure task**, not an architecture exploration.

The intended correction is conceptually small:

```text
make the durable drain worker explicitly owned
+
remove daemon escape
+
bound stop waiting
+
do not fake STOPPED on timeout
+
do not synchronously require all DB convergence at Runtime shutdown
+
leave remaining truth in WAL
+
recover it through the same existing Recovery Authority
+
prove the lifecycle with deterministic tests
```

Do not merely make the architecture test green.

Fix the lifecycle semantics that the architecture test is protecting.

Use the smallest correct implementation, validate only the real impact scope, perform one bounded Independent Review, satisfy the Stop Condition, output the current Beijing time as required by `AGENTS.md`, and STOP.
