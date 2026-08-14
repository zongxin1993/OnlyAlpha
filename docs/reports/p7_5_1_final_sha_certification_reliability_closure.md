# P7.5.1 Final-SHA Certification Reliability Closure

- Date: 2026-08-14
- Starting SHA: `4ef8525231a28ba1ded32dfff70dae350b3d54ee`
- Ending SHA: created only after this report and all changes are committed; the external handoff and certification artifact must
  identify that immutable SHA to avoid a self-referential report commit
- Workspace version: `0.4.4` (unchanged; no public package, persistence schema, or product capability change)
- Environment: Darwin 24.6.0 arm64, Python 3.12.12, uv 0.10.5
- Local status at report completion: implementation and all locally executable mandatory gates verified
- Remote Final-SHA status: NOT EXECUTED; no authenticated GitHub CLI or available browser session

## Current Truth Revalidated

The audit reread the current `README.md`, `AGENTS.md`, roadmap, architecture, Runtime and quality-system documents; ADRs 0055,
0068 and 0071; the P6.5 Streaming checkpoint audit; current Streaming/SIM source, MarketData processor/queue, the complete SIM
execution integration file, related phase/lane/loader/recovery tests, test-lane runner, certification script, both quality workflows,
and `pyproject.toml`.

Authority answers:

- Streaming phase state is owned and mutated only by `OnlyStreamingPhaseController`.
- MarketData semantic state is mutated only through `OnlyStreamingSemanticLane`, which is the only Streaming caller of
  `MarketDataProcessor.process()`.
- `OnlyStreamingRecoveryLoader` owns external historical loading and strict fact validation; it does not apply semantic state.
- Runtime Persistence/Transaction Store remains the durable trading authority. The new diagnostics are process-local read-only
  projections and are neither durable nor a recovery authority.
- Failure occurred at the async verification watchdog boundary, not at a committed trading or continuity authority boundary.
- A successful recovery must remain equivalent to forward replay of exact missing facts plus the buffered realtime suffix through
  the same semantic lane, followed by continuity proof and a new `LIVE` phase revision.

## Original Failure

The Prompt records a mandatory Final-SHA `core-full` failure at:

```text
tests/integration/test_engine_sim_virtual_broker_execution.py
::test_engine_sim_gap_recovers_history_then_reconciles_trigger_once
```

The captured baseline was `LIVE` revision 4. The test submitted the closed-gap trigger and waited at most 10 seconds for a later
`LIVE` revision; the wait returned `None`. Other full-suite/CI runs of the same scenario succeeded, sometimes near or beyond that
budget.

Remote revalidation was attempted. `gh auth status` reported no authenticated hosts, the unauthenticated GitHub API returned 403,
and the browser runtime had no available session. Consequently, exact run/job IDs, runner image and full remote logs are not
independently asserted here; the historical remote failure details above remain Prompt-provided evidence.

## Failure Reproduction Matrix

All commands below ran against the untouched starting SHA before implementation:

| Matrix item | Command / configuration | Result | Target duration |
|---|---|---|---|
| A. isolated | direct pytest node | PASS 1/1 | 2.05s |
| B. repeated | direct pytest node in 10 fresh invocations | PASS 10/10 | 2.31–2.77s |
| C. complete file | direct pytest file | PASS 17/17 | 1.63s |
| D. canonical sim-recovery | `scripts/test_suite.py sim-recovery`, 4 workers | PASS 37/37 | not selected by marker |
| E. core-full single worker | `scripts/test_suite.py core-full --no-parallel` | PASS 1535, SKIP 1 | 1.66s |
| F. core-full xdist | `scripts/test_suite.py core-full`, 8 workers/worksteal | PASS 1535, SKIP 1 | 4.87s |
| G. certification-equivalent local lane | same canonical xdist core-full command used by workflow | PASS | 4.87s |

The duration increase under xdist proves scheduling/CPU contention can consume wall-clock budget, but neither configuration
changed the phase/continuity/trading result. The original failure could not be reproduced locally.

## Root Cause Classification

Classification: **Case B — test synchronization defect**.

Production synchronization invariants held in source, architecture gates and baseline executions. `Condition.wait_for()` already
checked state and monotonic revision, so there was no lost-notification correctness defect. The test nevertheless used a scattered
10-second timeout as its only completion observation and emitted only `None` on expiry. That value was shorter than the Runtime's
configured 30-second historical-operation budget and could not classify whether recovery was loading history, replaying it,
reconciling suffix input, verifying continuity, stopped, or failed.

Runner speed is not the root cause. It is only one way to expose the invalid watchdog assumption. Recovery correctness never
requires a scheduler to finish inside 10 seconds.

Targeted verification found one diagnostics-only race after the first implementation: STOP correctly revoked semantic permission,
but the returning recovery call stack could overwrite `STOP_CUTOFF` with `VERIFYING_CONTINUITY`. No late semantic mutation occurred.
An explicit post-suffix cutoff check now preserves both control behavior and a truthful diagnostic snapshot.

## Design Decision

[ADR 0077](../adr/0077-streaming-recovery-verification-and-diagnostics.md) establishes:

1. monotonic phase revision as the formal async synchronization point;
2. continuity proof plus a new `LIVE` revision as completion semantics;
3. one operational watchdog derived from the configured historical-operation budget plus the existing five-second
   scheduling/notification grace;
4. an immutable diagnostic projection with explicit recovery stage;
5. STOP cutoff precedence for semantic processing and diagnostic progress.

The diagnostic stage never controls production behavior. No Manager, durable authority, schema, test-only mutation hook, retry,
sleep, flaky marker, lane change, or timeout-based business rule was added.

## Production Changes

- Added immutable `OnlyStreamingRecoveryDiagnostics` and diagnostic-only `OnlyStreamingRecoveryStage`.
- Added a non-blocking Semantic Lane diagnostic snapshot so a stuck semantic action cannot block its own watchdog evidence.
- Added `OnlyStreamingPhaseController.wait_for_revision()` and the Runtime wrapper.
- Centralized the existing historical budget plus grace as `streaming_recovery_watchdog_seconds` and reused it for worker shutdown.
- Recorded deterministic recovery stages around plan install, external load, same-lane replay, suffix reconciliation and continuity
  verification.
- Preserved `STOP_CUTOFF` after blocked load/catch-up returns.

## Test Changes

- Gap and reconnect tests first observe a formal phase revision, then wait for the later `LIVE` revision with the shared watchdog.
- Watchdog failures include the complete immutable diagnostics representation.
- Added a real buffered secondary-gap regression that must enter `FAILED`, never `LIVE`.
- Strengthened blocked historical-I/O and blocked catch-up STOP tests with stage, plan and lane-cutoff evidence.
- Added phase-revision and architecture gates for single phase ownership and diagnostic non-authority.

## Invariants Revalidated

- **Single Semantic Writer:** normal realtime, recovery replay and suffix catch-up still call only `OnlyStreamingSemanticLane`.
- **External I/O != Semantic Authority:** the Loader still only returns validated facts.
- **Recovery Is Forward Replay:** no recovery-only manager mutation or state patch exists.
- **Phase Single Authority:** only the Phase Controller owns `_phase`; revision is monotonic and condition-notified.
- **STOP Precedence:** lane revocation and `STOPPING` prevent any later semantic action; late batches are discarded.
- **Timeout != Business Semantics:** timeout is only a stuck-operation watchdog; continuity proof determines completion.
- **No Duplicate Trading Progress:** the gap scenario still proves one Accepted, one Trade, two Projection Ready transactions and
  exactly one application of the original trigger after repair.

## Verification Evidence

Completed after implementation:

| Command / gate | Result |
|---|---|
| `uv sync --frozen --all-packages --all-groups` | PASS |
| repository Ruff check + format check | PASS, 1186 files formatted |
| Core mypy | PASS, 493 files |
| Indicator/Factor and all configured package mypy commands | PASS |
| import-linter | PASS, 3 contracts |
| version sync | PASS at 0.4.4 |
| final targeted phase/lane + architecture + complete SIM integration file | PASS, 34 tests |
| gap recovery, 10 fresh post-change invocations | PASS 10/10, 2.31–3.13s |
| `sim-recovery`, two consecutive post-change runs before final diagnostic hardening | PASS 37/37 both runs |
| `core-full` post-change | PASS 1537, SKIP 1; target 4.17s |
| `recovery` post-change | PASS 330 |
| release research-factor / research-job / research-calculation | PASS 51 / 30 / 123 |
| release calculation / research-dataset | PASS 54 / 36 |
| final release core-full / recovery / sim-recovery | PASS 1537+1 skip / 330 / 38 |
| release ashare / miniqmt-contract | PASS 24 / 34 |
| all-package build | PASS, 8 package sdists and wheels |
| core-full mandatory branch coverage | PASS, total 83.68%; lines 88.29%; branches 62.57% |
| calculation coverage | PASS, total 88.15% |
| research-calculation coverage | PASS, total 87.49% |
| research-factor coverage | PASS, 100% |
| research-job coverage | PASS, 100% |
| research-dataset coverage | PASS, total 89.30% |
| Semgrep rule tests | PASS 4/4 |
| Semgrep source/package scan including untracked source | PASS, 0 findings |

The first sandboxed release aggregate reached its final build step after every test lane passed, then could not resolve isolated
`hatchling` because sandbox networking was prohibited. The exact all-package build was rerun with approved dependency access and
passed. This is recorded as an environment retry of the build command, not a test rerun or a relaxed gate.

Local CodeQL is NOT EXECUTED because no CodeQL CLI is installed. It remains a mandatory remote Final-SHA job. No unexecuted
command is represented as PASS.

## Exact-SHA Certification

Status: **NOT EXECUTED**.

An immutable final commit, push/remote visibility, a manually dispatched `Final-SHA Certification` workflow, every mandatory
successful gate, and the resulting evidence artifact with `verdict = ACCEPTED` are still required. Layered Quality or local PASS
cannot substitute for that artifact. P7.6 must not start from this report alone.
