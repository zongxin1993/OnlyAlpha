# P7.8 Research Result Authority & Deterministic Output Closure

## Task Context

- Base branch: `master`
- Task Base SHA: `a5709f5569f10dd7f67e167167cde67836baa5fb`
- Resulting HEAD: unchanged base SHA plus the current uncommitted P7.8 worktree; no implementation commit was created by this task
- Version: `0.7.8`
- P7 state: `IN_PROGRESS`; P7 Final Certification is `NOT COMPLETE`

The only pre-existing dirty-worktree item was the untracked P7.8 prompt. It was preserved. Current truth confirmed P7.7 as the latest
prior verified increment, Research and Live factories as unsupported, Statistics Result as the highest durable Research output
authority, and Sweep Outcome as ephemeral invocation evidence.

## Frozen Task Contract

Goal: create a deterministic, immutable, machine-readable Research Result composition authority.

Expected modification scope: `onlyalpha.research.result`, its tests and architecture boundary, canonical lane/Impact Resolver/static
verification, three-Gate quality documentation, ADR/report/current-truth documentation, and synchronized 0.7.8 metadata.

Impact scope: Research Result, the Statistics Result public consumer boundary, Dataset identity linkage, Research/Trading firewall,
serialization/persistence, verification infrastructure, and quality contracts. Trading Kernel, Broker, Position, Account, Risk,
Settlement, SIM, Backtest, Live implementation, Artifact, Query/API/Web, optimizer, and cross-Dataset composition are out of scope.

The expected acceptance plan remained valid. Evaluation/Job/Sweep full lanes were not required for A/B/C because no producer public
contract changed. Verification infrastructure changes require one final FULL_LOCAL self-verification.

## Architecture Implemented

`OnlyResearchResultPlan` canonicalizes a non-empty duplicate-free set of exact Statistics logical fingerprints. The assembler
verified-loads every Statistics Result, validates exact logical/result linkage, enforces one Dataset Snapshot, and emits references
without copying rows. Plan, Content, and Result fingerprints are separate. Created time, physical root, serialization layout, and
EXECUTED/REUSED evidence are excluded from semantic identity.

`OnlyJsonResearchResultStore` is keyed by Plan fingerprint. It uses staging, exact read-back, atomic rename, verified upstream
referential integrity, idempotent REUSED outcomes, deterministic conflict, and corruption/missing separation. Existing corrupt
authority is never overwritten. ADR 0083 freezes the composition-only ownership and Research/Trading firewall.

## Verification Evidence

- Block A: `.venv/bin/pytest tests/research/result/test_plan.py tests/research/result/test_identity.py -q` — 8 passed.
- Block B/C: `.venv/bin/pytest tests/research/result -q` — 25 passed before architecture-lane composition.
- Block D targeted: `.venv/bin/pytest tests/architecture/test_agent_verification.py tests/architecture/test_test_lane_contract.py tests/architecture/test_certification_contract.py tests/architecture/test_research_result_boundaries.py -q` — 50 passed.
- Canonical lane: `UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run --offline python scripts/test_suite.py research-result` — 28 passed.
- Affected Ruff/Format/Mypy and version sync — passed; scoped mypy checked 9 selected source files.
- Final FULL_LOCAL: `UV_CACHE_DIR=/tmp/onlyalpha-uv-cache UV_OFFLINE=1 uv run --offline python scripts/verify.py agent --base a5709f5569f10dd7f67e167167cde67836baa5fb` — PASS, 23 gates. This included 9 repository static checks, Research Result 28, Research Evaluation 96, Research Sweep 27, Research Factor 57, Research Job 30, Research Calculation 127, Calculation 58, Research Dataset 36, core-full 1732, recovery 330, sim-recovery 38, A-share 24, MiniQMT contract 34, and workspace build. Full logs: `test-results/verification/20260815T070350Z-a5709f5569f1-45655/`.

The first Block A `uv run` attempt was prevented before test collection by sandbox network restrictions. The existing workspace
environment and offline uv cache were then used; this did not expand semantic verification scope.

## Expansion and Explicit Non-Execution

Expansion beyond A/B/C was limited to the expected verification-infrastructure FULL_LOCAL closure and package metadata version/build
checks. No Statistics, Dataset, Calculation, Job, or Sweep public authority was modified.

Not executed as P7.8 Task Gate requirements: repository-wide/full Research coverage, P7 Phase Gate, Nightly Heavy Quality,
Final-SHA Certification, or remote CI. FULL_LOCAL is a task-level self-change firewall, not a Phase or Certification verdict.

## Remaining P7 Scope

Research Artifact, read-only Query/API/Web consumption, finite Research Runtime lifecycle, and P7 Phase/Final-SHA Certification remain
open. Research and Live Runtime factories remain unsupported.
