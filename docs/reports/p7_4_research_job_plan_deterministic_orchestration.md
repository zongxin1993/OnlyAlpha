# P7.4 Research Job / Plan Contract & Deterministic Orchestration

Date: 2026-08-14

## Baseline

- Starting SHA: `07c0767dee083e74e74eb4e9afc89447b6dbf5cd`
- Ending SHA: pending; this report is part of an uncommitted working tree based on the starting SHA
- Workspace version: `0.4.4`
- Environment: macOS, Python 3.12.12, `uv`, local workspace

No exact final-SHA external certification artifact exists for this working tree. This report therefore records local implementation
and verification only; it does not claim `CERTIFIED`, `ACCEPTED`, or `DONE`.

## Current Truth Revalidated

Before implementation, the current HEAD and contracts were re-read across `README.md`, `docs/roadmap.md`,
`docs/engineering/quality-system.md`, `AGENTS.md`, `pyproject.toml`, GitHub quality/certification workflows,
`scripts/test_suite.py`, `scripts/certification.py`, ADR 0068 and ADRs 0069/0070/0072/0073/0074, Calculation Core,
Research Dataset, Research Calculation/Result, Research Runtime Factory and Runtime inheritance boundaries, public exports, and
their formal tests.

The audit established:

- P7.3 was implemented locally at the starting SHA but had no exact-SHA remote certification artifact;
- Dataset Snapshot Store is the immutable verified Dataset authority;
- Calculation identity already binds exact Dataset Snapshot, canonical Calculation Graph, and RESEARCH backend semantics;
- `OnlyResearchCalculationExecutor` is the P7.2 deterministic execution authority;
- `OnlyParquetResearchCalculationResultStore` is the immutable P7.3 Result authority;
- `exists()` checks physical target existence only, while `load_verified()` establishes reusable authority;
- the Research Runtime Factory remains intentionally unsupported;
- `OnlyResearchRuntime` still inherits trading-shaped `OnlyRuntime` and remains composition debt, not a target design;
- the official Factor provider remains intentionally empty.

## Problem Closed

P7.4 upgrades separate verified Research primitives into one canonical exact single-job operation:

```text
Resolved Research Job
→ verified authority reuse attempt
→ RESULT_NOT_FOUND-only deterministic execution
→ immutable Calculation Result commit
→ explicit successful Job Outcome
```

Callers no longer need to invent their own cache-style existence checks, corruption fallback, result publication sequence, or
success provenance.

## Design Decisions

`OnlyResearchJobPlan` is immutable and contains only schema version, exact Dataset Snapshot fingerprint, and the current canonical
Calculation Graph. It contains no provider alias, latest/default lookup, path, store root, process, worker, wall clock, compression,
or execution setting.

No Job or Plan fingerprint was added. P7.4 v1 adds no semantic input beyond the existing Calculation identity, so a second hash
would duplicate authority. Invocation disposition remains operational provenance.

`OnlyResearchJobExecutor` calls `load_verified(calculation_fingerprint)` first. A verified Result returns `REUSED`; only stable
`RESULT_NOT_FOUND` enters P7.2 execution and P7.3 commit. `RESULT_CORRUPT`, `RESULT_INVALID`, linkage mismatch, and other Result read
failures stop at `RESULT_REUSE` without recomputation, repair, deletion, or overwrite.

Success returns immutable `SUCCEEDED` plus `EXECUTED` or `REUSED`, Calculation fingerprint, and Calculation Result fingerprint.
Failures raise phase-aware `OnlyResearchJobError` while preserving the underlying stable Dataset/Calculation/Result code and cause.

Recovery is deterministic re-entry. Before commit, rerunning computes again; after commit but before Outcome delivery, rerunning
verified-loads and reuses. No mutable Job database, scheduler state, checkpoint, lease, retry daemon, or global lock was added.

Concurrent same-job executions may duplicate ephemeral calculation but converge through the P7.3 atomic/idempotent/conflict
authority to one durable semantic Result. P7.4 does not replace the Store race contract.

The Job package imports no Trading Runtime, Cluster, Account, Broker, Order, Position, Allocation, Risk, Reservation, Fee,
Settlement, Trading Transaction/Projection, Strategy Ledger, or Runtime-mode authority. Research Runtime activation remains out of
scope.

## Production Changes

- `src/onlyalpha/research/job/plan.py`: exact immutable resolved Plan and reuse of Calculation identity.
- `src/onlyalpha/research/job/outcome.py`: validated successful status/disposition and authoritative identities.
- `src/onlyalpha/research/job/errors.py`: stable orchestration phases and error contract.
- `src/onlyalpha/research/job/executor.py`: verified reuse-or-execute orchestration and phase-aware propagation.
- `src/onlyalpha/research/job/__init__.py` and `src/onlyalpha/research/__init__.py`: public Research Job exports.
- `scripts/test_suite.py`: independent `research-job` lane and package-owned coverage target.
- GitHub quality/certification workflows: mandatory lane and coverage integration.
- Workspace release graph: synchronized from `0.4.3` to `0.4.4`.
- ADR 0075, README, Roadmap, AGENTS, Storage, and Quality System: current contract and boundaries.

No Dataset, Calculation, Result, Trading persistence, Checkpoint, Runtime, or product configuration schema changed.

## Tests Added

The P7.4 suite freezes:

- exact immutable Plan and Outcome validation;
- absence of duplicate Job/Plan identity;
- first `EXECUTED` result and repeated `REUSED` identity invariance;
- no Calculation invocation or repeated commit on verified reuse;
- fresh Store/Executor instance and fresh-process reuse;
- physical and path/linkage corruption fail-closed without mutation;
- explicit `RESULT_INVALID` not treated as a miss;
- Dataset verification, Calculation, and commit failures with no false authority;
- deterministic conflict propagation;
- commit-before/after-crash re-entry semantics;
- concurrent same-job convergence to one durable authority;
- unexpected boundary failures mapped to exact phases;
- Result authority linkage back to the exact Plan;
- Research Job import firewall, no Runtime-mode branch, and no copied canonical hashing;
- Research Runtime Factory remains unsupported;
- mandatory quality/certification lane and coverage presence.

## Local Quality Evidence

Actual successful commands and results:

- `uv run python scripts/test_suite.py research-job --coverage`: 30 passed; 100.00% lines and branches.
- `uv run python scripts/test_suite.py research-calculation --coverage`: 123 passed; 91.42% total coverage.
- `uv run python scripts/test_suite.py calculation --coverage`: 54 passed; 88.15% total coverage.
- `uv run python scripts/test_suite.py research-dataset --coverage`: 36 passed; 89.30% total coverage.
- `HYPOTHESIS_PROFILE=ci uv run python scripts/test_suite.py core-full --coverage`: 1503 passed, 1 skipped,
  486 deselected; 83.64% total coverage, 88.26% lines, 62.43% branches.
- `uv run python scripts/test_suite.py release`: all final-tree static and mandatory test lanes passed, including:
  - Ruff check and format: PASS;
  - Core mypy: 492 source files, PASS;
  - official Indicator/Factor and market/provider package mypy targets: PASS;
  - version sync at `0.4.4`: PASS;
  - research-job: 30 passed;
  - research-calculation: 123 passed;
  - calculation: 54 passed;
  - research-dataset: 36 passed;
  - core-full: 1504 passed, 1 skipped;
  - recovery: 328 passed;
  - sim-recovery: 37 passed;
  - A-share conformance: 24 passed;
  - MiniQMT contract: 34 passed;
  - the final combined command's build step was blocked by sandbox network access while resolving `hatchling`; the exact
    `UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv build --all-packages` command was immediately rerun with approved network access and all
    eight workspace sdist/wheel pairs built successfully at `0.4.4`.
- `uv sync --frozen --all-packages --all-groups`: PASS.
- `uv run lint-imports`: 3 contracts kept, 0 broken.
- targeted certification/lane/version architecture tests: PASS.
- `git diff --check`: PASS, including this report.

Not passed or not executable locally:

- Local Semgrep: FAIL before scanning because the installed binary could not create the system X509 authenticator from an empty
  trust-anchor store. This is an environment/tool startup failure and is not recorded as a scan PASS.
- CodeQL: NOT EXECUTED locally; the repository contract runs it in the remote exact-SHA certification workflow.
- Final-SHA certification verdict: NOT EXECUTED because no final committed subject SHA exists for this working tree.

## Remaining Non-goals and Debt

P7.4 does not implement Parameter Sweep, optimization, Factor research product semantics, forward return, IC/Rank IC/statistics,
Research Result, Research Artifact, Scheduler/Worker/Job database, distributed Research, Query/API/Web, Notebook integration,
Research Runtime activation, or `Engine.run(RESEARCH)`. The official Factor provider remains empty.

`OnlyResearchRuntime` remains a trading-shaped unsupported class. A future Research Runtime composition must extract a genuinely
Research-shaped lifecycle boundary before activation; P7.4 intentionally does not refactor the Runtime hierarchy.

## Certification State and Next-stage Readiness

State: `LOCALLY IMPLEMENTED / VERIFIED`; not `CERTIFIED / ACCEPTED / DONE`.

Readiness: `NOT READY` for certification or automatic next-stage execution until all changes, including this report, enter one
immutable final SHA and the remote Final-SHA Certification workflow produces successful static, build, canonical lane, coverage,
Semgrep, CodeQL, and verdict evidence for that exact SHA. P7.5 has not been started.
