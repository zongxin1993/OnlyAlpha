# P9.K.5 Idempotency, Long-running Operations & Recovery Closure — Implementation Evidence

- Date: 2026-08-27
- `TASK_BASE_SHA`: `7ee4a6f3661802f8121d084f2836df02128dc372`
- `TASK_IMPLEMENTATION_SHA`: `WORKTREE — NOT YET IMMUTABLE`
- Branch: `master`
- Migration: `0012_product_command_receipt`
- API compatibility baseline: `d9713159eeb2e3dcc294d1dbd456e7332ef2cbac`
- Release version: `0.9.5`
- Current status: `TASK COMPLETE / VERIFIED — HIGHER-LEVEL COVERAGE AND DEFERRED CI EVIDENCE OPEN`

The original sections below preserve the 2026-08-27 implementation evidence and its then-current classification. The Closure audit at
the end records the current Task-Gate verdict. It does not claim Final-SHA Certification or that deferred CI evidence passed.

## Authority map

| Fact | One authority |
|---|---|
| External Product Command retry binding | PostgreSQL `product_command_receipt` |
| Research long-running intent/outcome | PostgreSQL `research_run` |
| Research physical execution ownership/history | PostgreSQL `research_run_attempt` with ADR 0090 lease/fencing |
| Research semantic results/artifacts | Existing immutable verified semantic stores |
| Strategy semantic truth | Frozen Strategy Revision + Freeze Relation immutable namespace |
| Strategy operational projection | PostgreSQL Strategy catalog/freeze records, derived from semantic truth |
| Product Kernel mutation guard | One dedicated PostgreSQL advisory-lock session |

Migration 0012 backfills the exact P8 Create binding and drops the physical legacy `research_run_submission` table. Active production
readers and writers use only Product Command Receipt.

## Identity matrix

| Identity | Class | Inputs |
|---|---|---|
| Product Command ID | operational, global | canonical UUID4 supplied as Idempotency-Key |
| Command kind | operational | `CREATE_RESEARCH_RUN` or `CANCEL_RESEARCH_RUN` |
| Create command fingerprint | operational | exact historical canonical `{specification: strict specification}` |
| Cancel command fingerprint | operational | canonical `{run_id: exact target}` |
| ResearchRun ID | business resource | application-generated canonical UUID4 |
| Dataset/Calculation/Result/Artifact/Strategy fingerprints | semantic | unchanged existing semantic inputs only |

Actor, request ID, JWT, IP, HTTP route/method, API version, Git SHA and Product Command ID never enter semantic fingerprints.

## Transaction linearization points

### CreateResearchRun

One PostgreSQL transaction inserts the prepared QUEUED ResearchRun and resolved ProductCommandReceipt. If concurrent callers prepare
different Run UUIDs for the same Command ID, the losing transaction rolls back its provisional Run on the primary-key conflict, reloads
the winning Receipt and returns the winning current Run.

### Keyed CancelResearchRun

One PostgreSQL transaction checks for an existing global Receipt, row-locks the target Run, proves the legal state, applies the optional
QUEUED→CANCELLED or RUNNING→CANCEL_REQUESTED transition, and inserts the resolved Receipt. Already CANCEL_REQUESTED/CANCELLED state is
re-proved under the same lock before the first Receipt is inserted. COMPLETED/FAILED rejects without a successful Receipt. No-key v2
requests retain the prior natural Run-state idempotency path.

## Recovery matrix

| Scenario | Rule / proving evidence |
|---|---|
| K5-C1 Create response loss | test-only ASGI response drop; retry returns REUSED same Run |
| K5-C2 same Create ID, different intent | command fingerprint conflict; no second Run |
| K5-C3 process killed after durable Create | PostgreSQL subprocess named marker then SIGKILL; restart loads same Receipt/Run (CI REQUIRED) |
| K5-C4 keyed Cancel response loss | ASGI response drop; retry loads same current Run |
| K5-C5 Cancel ID retargeted | global Receipt conflict |
| K5-C6 Create/Cancel ID reuse | command-kind conflict |
| K5-C7 semantic Freeze before projection | existing projection-outage reconciliation test |
| K5-C8 partial compatible projection | existing partial projection convergence test |
| K5-C9 conflicting projection | existing fail-closed projection conflict test |
| K5-C10 mutation during RECOVERING | exact Event barrier; handler and durable adapter are not invoked |
| K5-C11 second Product Kernel | real PostgreSQL advisory-lock session test (CI REQUIRED) |
| K5-C12 physical inventory ordering | sorted verified Strategy inventory tests |
| K5-C13 dangling Receipt | strict replay raises integrity failure and creates no replacement |

## Public compatibility

- Cancel `Idempotency-Key` is optional; old valid v2 requests remain valid.
- Canonical OpenAPI SHA256: `6a66fde2dba23fe6770bc5b27031337d95bf4b987b0ca946903c1a7c89b95d1e`.
- Immutable baseline SHA256: `c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e`.
- Mechanical compatibility: `COMPATIBLE`, zero breaking changes.
- Generated TypeScript freshness: PASS.

## Verification evidence

### Local PASS

```text
targeted K5/HTTP/Strategy/architecture/OpenAPI: 132 passed
kernel canonical lane:                         43 passed
research-command canonical lane:               54 passed
strategy canonical lane:                       98 passed
architecture canonical lane:                  478 passed
OpenAPI baseline compatibility:                COMPATIBLE / 0 breaking
Ruff / Ruff format:                            PASS
Core and API mypy:                             PASS
version sync 0.9.5:                            PASS
git diff --check:                              PASS
budgeted local verification static checks:     10 PASS
```

The first two budgeted local attempts exposed and then closed one format issue and one API mypy variable-inference issue. The final run
returned exit code `3`, correctly meaning `LOCAL_PASS_CI_REQUIRED`. Manifest:
`test-results/verification/local-budget/20260827T132457Z-7ee4a6f36618-68674/manifest.json`.

### CI REQUIRED

The complete required impact plan is 129 units and defers 30 commands, including real `research-postgres`,
`research-product-closure`, Web checks/build/E2E, build, broader Research lanes, core-full, recovery, sim-recovery, A-share and MiniQMT
contract proof. These are not reported as PASS.

The local real PostgreSQL targeted attempt was `NOT EXECUTED` because `ONLYALPHA_TEST_POSTGRES_DSN` is unavailable. It failed at the
canonical environment precondition before running a test, so migration/backfill/concurrency/process-crash/advisory-lock evidence remains
CI REQUIRED.

## Invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K5-001 one external command authority | PASS (code) / CI REQUIRED (DB) | 0012 backfill/drop; production code-search guard |
| INV-K5-002 command ID global | PASS (local) / CI REQUIRED (concurrency) | kind/fingerprint conflict tests; UUID PK |
| INV-K5-003 operational identity only | PASS | semantic-module architecture guard |
| INV-K5-004 Create fingerprint bytes preserved | PASS | exact legacy-shape unit test and backfill |
| INV-K5-005 Receipt is binding | PASS | immutable model/schema without lifecycle state |
| INV-K5-006 ResearchRun remains operation | PASS | no ProductOperation introduced |
| INV-K5-007 effect + Receipt atomic | PASS (code) / CI REQUIRED (real DB) | one transaction per accepted command |
| INV-K5-008 Receipt reloads current resource | PASS | replay tests |
| INV-K5-009 dangling/corrupt fails closed | PASS (local) / CI REQUIRED (DB corruption) | strict decoder and dangling test |
| INV-K5-010 physical execution not exactly-once | PASS | ADR 0090 unchanged |
| INV-K5-011 Worker recovery ownership | PASS | no Worker protocol changes |
| INV-K5-012 semantic truth dominates projection | PASS | existing reconciler reused |
| INV-K5-013 deterministic recovery traversal | PASS | verified sorted inventory |
| INV-K5-014 mutation impossible before READY | PASS | RECOVERING Event barrier, zero handler calls |
| INV-K5-015 one mutation-capable Kernel | PASS (code) / CI REQUIRED (real DB) | session advisory guard |
| INV-K5-016 Kernel infrastructure-neutral | PASS | architecture lane; psycopg adapter outside Kernel |

## Remaining status

This was the pre-Closure implementation status on 2026-08-27. No K6/K7/K8 work was introduced, and the listed deferred evidence was not
fabricated as PASS.

## 2026-08-28 Closure — Functional Correctness / Coverage Evidence Separation

- Closure base SHA: `12cb8dcfa145cdf887d75c7618c9318c086b387d`
- Audit head SHA: `12cb8dcfa145cdf887d75c7618c9318c086b387d` plus the recorded dirty Closure worktree
- Closure implementation: `WORKTREE — NOT YET IMMUTABLE`
- Audit scope: `P9.K.5 Closure Task Gate`
- Release version: `0.9.5` (version graph PASS)

### Previous findings status

| Finding | Status | Closure |
|---|---|---|
| F-K5-001 — coverage / Layered Quality failure | PARTIALLY_RESOLVED | Historical coverage shortfall remains open and is not claimed as PASS. Its classification as a K5 Task correctness blocker is resolved: coverage blocks only a Gate where that threshold is mandatory. |
| F-K5-002 — authority acquired after entering RECOVERING | RESOLVED | `OnlyAlphaKernelHost.start()` now acquires the guard after verifiers while state remains `VERIFYING`, then transitions to `RECOVERING`. Deterministic tests prove ordering and zero recovery work on acquisition failure. |

### Functional correctness evidence

```text
targeted Host/lifecycle/K5 architecture: 29 passed — LOCAL PASS
kernel canonical functional lane:         45 passed — LOCAL PASS
research-command functional lane:         54 passed — LOCAL PASS
```

`research-product-closure` was attempted without coverage. Eight environment-independent tests passed; eleven PostgreSQL-backed tests
were `NOT EXECUTED` because `ONLYALPHA_TEST_POSTGRES_DSN` was unavailable. The PostgreSQL adapter, migration and transaction paths were not
modified by this Closure, so the missing environment is not reclassified as a K5 lifecycle functional failure and is not reported as
PASS.

### Static and impact-aware evidence

```text
changed Python Ruff / format:              LOCAL PASS
Core mypy:                                 LOCAL PASS — 619 source files
version graph 0.9.5:                       LOCAL PASS
budgeted local verification static checks: 10 LOCAL PASS
budgeted local verification result:        CI REQUIRED — exit code 3 semantics
```

Impact manifest:
`test-results/verification/local-budget/20260828T000811Z-12cb8dcfa145-58427/manifest.json`.
The fail-closed unknown-path plan retained 30 broad commands under `deferred_to_ci`; none is reported as PASS. Directly applicable K5
functional evidence was executed separately above.

### Coverage evidence

No coverage command was run for this Closure. The historical Research Command / Research PostgreSQL coverage shortfall remains
`OPEN` for a Phase/Certification Gate that mandates it. Passing functional assertions remain `PASS`; coverage does not retroactively
rewrite them as functional failure. Remote exact-SHA Certification is `NOT EXECUTED / NOT CLAIMED`.

### Closure invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| authority acquired after verification and before RECOVERING | PASS | temporal Host regression test observes `acquire` in `VERIFYING` |
| RECOVERING implies guard held | PASS | recoverer observes `RECOVERING` and held guard |
| acquisition failure executes no recovery and reaches FAILED | PASS | zero recoverer calls; `RECOVERING / mutation-authority-acquire` failure evidence |
| recovery failure releases authority | PASS | existing Kernel functional regression |
| draining retains authority until drainers finish | PASS | drainer and release observations both occur in `DRAINING`, held before release |
| Kernel remains infrastructure-neutral | PASS | targeted K5 architecture test and kernel lane |
| Product Command / ResearchRun / Worker / Strategy authorities unchanged | PASS | no production change outside Kernel lifecycle; research-command lane PASS |
| uniqueness chain unchanged | PASS | no command identity, Receipt, persistence constraint or semantic identity change |
| deterministic recovery traversal unchanged | PASS | no inventory/reconciler change; K5 architecture evidence PASS |
| public API / schema unchanged | PASS | no API DTO, OpenAPI, migration or persistence adapter change |
| higher-level coverage threshold | NOT_VERIFIED | not executed; historical shortfall remains open |
| exact-SHA Certification | NOT_VERIFIED | not executed and not claimed |

### Focused convergent audit verdict

```text
BLOCKER:   0
MAJOR:     0
MINOR:     0
SUGGESTION: 0

GO — P9.K.6 may begin.
```

No new findings were identified. There is no non-blocking implementation debt introduced by this Closure; the historical higher-level
coverage evidence and the broad budget-deferred CI plan remain explicitly tracked as open evidence, not defects in the exercised K5
behavior. No K6/K7/K8 functionality, PostgreSQL adapter/migration, Product Command identity, Strategy identity, Research Worker protocol,
public API, coverage threshold, lane, workflow or version change was introduced.

This is a Task-Gate review verdict, not a fourth Gate and not Final-SHA `ACCEPTED`.
