# P8.6 Final Closure

Date: 2026-08-22

## 1. Baseline

- Start SHA: `d18e350fc95ce5cb6fc52e3765aac594f7cc1053`
- Branch: `master`
- Start worktree: no tracked changes; `prompts/P8.6FinalClosure.md` was the only untracked user input.
- Release graph: `0.8.6`.
- Candidate Final SHA: not frozen; the local Full Phase Gate has passed and the candidate commit is the next immutable step.

## 2. Reproduced Deployment Blocker

Startup previously checked only local root usability. API `(DB1, root A)` and Worker `(DB1, root B)` could both pass, allowing the Worker
to commit Result/Artifact under `B`, finalize the Run in DB1, and leave the API reading the exact reference from `A` as not found. The
defect existed before semantic work admission and could not be repaired at Artifact lookup.

## 3. ADR

ADR 0096 freezes:

```text
One Research PostgreSQL deployment
<->
One immutable Research semantic-store namespace identity
```

`USER_DATA_ROOT/research/.onlyalpha-semantic-store.json` owns only stable namespace ID. Migration
`0007_research_deployment_semantic_store_binding` owns one PostgreSQL singleton compatibility binding. Path is not identity. Only explicit
operator initialization writes either fact; API/Worker startup is read-only and cannot repair or dynamically rebind. Restore preserves
both IDs and requires equality before service readiness.

## 4. Production Changes

- `research/operations/deployment.py`: typed immutable namespace identity, strict explicit init, frozen startup verification.
- `persistence/postgres/research_deployment_store.py` plus migration 0007: narrow operational binding; no semantic content.
- API/Worker composition: read-only coherence check before readiness/claim; incoherent API product routes return 503.
- `scripts/database.py initialize-deployment`: sole explicit writer and canonical directory initialization.
- User-data layout: one explicit `research_root`; all existing semantic store paths remain unchanged.

No Calculation, Specification, Candidate, Statistics, Research Result or Artifact identity changed. No semantic content moved to
PostgreSQL, and no registry, alternate Runtime, recovery Store or mutable checkpoint was added.

## 5. Deployment Coherence Tests

- DB X + API/Worker X executes successfully.
- DB X + API Y remains NOT READY and all Research product routes are blocked.
- DB X + Worker Y/missing/corrupt identity exits before presence or claim.
- Two Workers with X are concurrently compatible.
- Different local paths exposing one identity are compatible.
- Non-empty root without identity refuses adoption.
- Equal restore pair passes; restored DB X + store Y fails at deployment verification before semantic lookup.

## 6. Real Browser Product E2E

The mandatory harness starts PostgreSQL 16, migration plus explicit deployment init, a fixed immutable two-instrument Dataset, real API,
real Vite Web, real Worker, OnlyEngine/OnlyResearchRuntime and Chromium. The browser authors RSI Feature with finite period Sweep,
Rolling Return inputs, Momentum Factor, Eligibility, Entry, Exit, Forward Return Target and IC Statistics through the production Builder.

It submits one durable Run, observes QUEUED, reloads while the Worker is absent, closes the page, and only then releases a test-owned file
barrier that starts the Worker. A new page opens the same Run, observes COMPLETED, follows the exact Result reference, and compares real
Query DTO facts with the Artifact-backed Viewer. Mechanical evidence includes two Candidates, both instruments, one RSI Feature Decimal,
one Momentum Factor Decimal, ENTRY_SIGNAL points and IC Statistics points. The real spec contains no `page.route` or semantic mock.

## 7. Crash Boundary Matrix

| Boundary | Durable facts at SIGKILL | Recovery | Final semantic truth | Verdict |
|---|---|---|---|---|
| C1 claim, before Dataset/semantic work | RUNNING + ACTIVE Attempt | expire + fresh Attempt | control-equivalent Result/Artifact | PASS |
| C2 before Research Result commit | reusable lower immutable facts; no final Result/Artifact | deterministic re-entry | control-equivalent Result/Artifact | PASS |
| C3 Result committed, before Artifact commit | exact immutable Result bytes | verified reuse + Artifact materialize | Result bytes unchanged | PASS |
| C4 Artifact committed, before PostgreSQL complete | exact Result + Artifact, Run RUNNING | verified reuse + fenced complete | both byte sets unchanged | PASS |

Each proof uses a real subprocess, `SIGKILL`, a narrow test-owned wrapper at an existing production boundary, and an exact barrier file.
There is no sleep-based crash-point guess and no production test mode. Attempt 1 becomes EXPIRED, Attempt 2 SUCCEEDED, and stale Attempt 1
cannot finalize after recovery.

## 8. Restore Certification

The automated product test captures PostgreSQL at `Tdb`, copies the complete namespace at `Tfs >= Tdb`, restores into an isolated empty
PostgreSQL 16 database, verifies equal store/binding ID, exact completed Run, Research Result and Artifact, then starts a fresh API and
compares DTOs. Wrong namespace fails early. Missing Result, missing Artifact, corrupt Artifact and mismatched fingerprint continue to fail
through strict readers with no repair, overwrite or terminal reopen.

## 9. Authority Audit

| Fact | Authority | Verdict |
|---|---|---|
| Dataset | immutable Dataset Snapshot Store | unchanged / PASS |
| Calculation semantics | Calculation contract and registered composition | unchanged / PASS |
| Statistics | immutable Statistics Result Store | unchanged / PASS |
| Research Result | immutable Research Result Store | unchanged / PASS |
| Artifact | immutable portable Artifact Store | unchanged / PASS |
| Run | PostgreSQL `research_run` | unchanged / PASS |
| Attempt/lease | PostgreSQL + server clock | unchanged / PASS |
| Semantic namespace ID | root immutable metadata, explicit operator writer | new single authority / PASS |
| Deployment binding | PostgreSQL singleton, explicit operator writer | new single authority / PASS |
| Browser state | disposable client state | unchanged / PASS |

## 10. Determinism / Reproducibility Audit

Fixed Dataset bytes, exact Definition/Specification, stable plugin composition and explicit policy produce identical semantic identities
across control and all four recovered runs. Operational Attempt/Worker UUIDs and timestamps differ by design; Dataset, Calculation,
Candidate, Statistics, Research Result and Artifact identities converge. Namespace growth does not change its identity.

## 11. Tests and Gates

Completed focused evidence:

- `research-product-closure`: 19 passed, including real Chromium and C1-C4 SIGKILL.
- `research-postgres`: 81 passed against PostgreSQL 16.10 with PostgreSQL 16 client, including backup/restore.
- focused deployment/health/architecture: 34 passed.
- deployment real-process matrix: 5 passed.
- API mypy: 17 source files, no issues; focused Core mypy passed.

Local certification environment:

- macOS, Python 3.12.12, uv 0.10.5, Node.js 26.7.0, npm 11.19.0 and Playwright 1.62.1;
- PostgreSQL server 16.10 in the isolated `onlyalpha-p86-pg` container and PostgreSQL 16 client tools;
- fixed offline Dataset; no Tushare, QMT, realtime market data or mutable online dependency.

Mandatory coverage was run without threshold reductions:

| Surface | Result |
|---|---:|
| repository `core-full` | 83.96% |
| calculation | 88.35% |
| research-calculation | 88.32% |
| research-definition | 83.88% |
| research-factor | 100% |
| research-evaluation | 95.38% |
| research-result | 95.32% total / 96.69% lines / 91.67% branches |
| research-artifact | 95.07% total / 96.30% lines / 91.58% branches |
| research-query | 98.02% |
| research-command | 95.57% total / 87.23% branches |
| research-runtime | 97.81% |
| research-specification | 100% lines / branches |
| research-run | 100% |
| research-execution | 95.44% |
| research-job | 100% |
| research-sweep | 95.86% |
| research-dataset | 88.47% total / 72.14% branches |
| research-postgres | 83.47% |

Local Semgrep rule tests passed `4/4`; the tracked-source scan covered 669 files with zero findings. The exact-SHA workflow will rerun
Semgrep after every candidate file is tracked. OSV dependency audit and Python/JavaScript-TypeScript CodeQL remain mandatory remote
evidence and are not substituted by local claims.

## 12. Full Phase Gate

`PASS` on 2026-08-22 using the canonical command:

```bash
uv run python scripts/test_suite.py release
```

The release command passed Ruff, format checking, all configured mypy surfaces, version synchronization, Web static/unit/build/mock E2E,
every canonical Research lane, real PostgreSQL product closure, `core-full`, recovery, SIM recovery, A-share conformance, MiniQMT contract
and all-package build. Notable aggregate lane results were:

- `core-full`: 2258 passed, 1 skipped;
- `recovery`: 330 passed;
- `sim-recovery`: 38 passed;
- `ashare`: 24 passed;
- `miniqmt-contract`: 34 passed;
- `research-calculation`: 133 passed;
- `research-dataset`: 37 passed;
- `calculation`: 59 passed.

Independent post-gate checks also passed:

```bash
uv run lint-imports
uv run python scripts/version_sync.py check
git diff --check
```

Import Linter analyzed 633 files and 4918 dependencies: all three contracts were kept, with zero broken contracts. The workspace release
graph is consistent at `0.8.6`. Performance warnings emitted by timed tests were diagnostic and did not relax or bypass any required gate.

## 13. Candidate Final SHA

Not frozen in this report revision. The local Phase Gate is complete; after this report is finalized, all candidate files will be committed
together, the exact 40-character SHA captured, and no implementation/workflow/lockfile change will be admitted without a new candidate and
complete recertification.

## 14. Exact-SHA Certification

- Workflow/run ID: pending.
- Artifact: pending.
- Verdict: `REJECTED` until exact-SHA certification returns `ACCEPTED`.

## 15. Remaining Risks

- Remote Final-SHA jobs, including the authoritative CodeQL and dependency audit, remain external evidence and cannot be projected before completion.
- Filesystem snapshot creation/retention remains deployment tooling; OnlyAlpha does not create a second backup authority.

## 16. Milestone Verdict

`P8 = IN_PROGRESS / REJECTED`

This verdict may change to `DONE / CERTIFIED` only after Full Phase Gate, clean immutable candidate SHA and exact-SHA artifact verdict
`ACCEPTED`.
