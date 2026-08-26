# P9.K.3 Unified Product HTTP Control Plane — Task Gate Report

- Date: 2026-08-26
- Environment: macOS arm64, Python 3.12, Node 24, temporary pinned `postgres:16.10`, PostgreSQL client 16
- `TASK_BASE_SHA`: `7a80bb405c43f8662d253a2264c044bb30a4379c`
- Implementation subject: dirty worktree based on `TASK_BASE_SHA`; closure SHA pending commit
- Gate: Task Gate with impact-aware `FULL_LOCAL`; no Final-SHA Certification requested or run

## Scope and implementation

The canonical `onlyalpha-api` production server now constructs one `OnlyResearchProductBoundary` from the same started
`OnlyAlphaKernelHost` that owns readiness and mutation admission. The HTTP mappings are:

```text
POST /api/v2/research/runs
→ OnlyCreateResearchRun
→ OnlyProductCommandDispatcher

POST /api/v2/research/runs/{run_id}/cancellation
→ OnlyCancelResearchRun
→ OnlyProductCommandDispatcher

GET /api/v2/research/runs/{run_id}
→ OnlyGetResearchRun
→ OnlyProductQueryDispatcher

GET /api/v2/research/runs
→ OnlyListResearchRuns
→ OnlyProductQueryDispatcher
```

The Run router no longer imports or directly invokes `OnlyResearchCommandService` or `OnlyResearchRunQueryService`. Dispatcher lookup
or composition failure has no legacy fallback. FastAPI continues to own only transport parsing/validation, explicit DTO/intent mapping,
response mapping, error mapping and OpenAPI projection.

`onlyalpha-artifact-api` remains a documented read-only migration-debt console entry. It constructs no Kernel Host, Product Command
boundary, mutation service, Engine, Runtime, or PostgreSQL writer and is not a second Product Control Plane.

ADR 0102 records PostgreSQL 16.10 as the current verified baseline and PostgreSQL 18.x as the future target. PostgreSQL 18 migration is
`PLANNED / NOT YET VERIFIED`; no image, client, SQL, migration, schema or UUID change is part of K3.

## Semantic deltas

- Public Research HTTP semantic delta: none.
- Canonical OpenAPI delta: none.
- Generated Web client delta: none.
- Database/schema/migration delta: none.
- Research idempotency, cancellation, ordering and cursor delta: none.
- Strategy/P9.0 semantic identity delta: none.
- K4/K5/K6/K7 implementation: not started.

## Invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K3-01 one Product HTTP Control Plane | PASS | `onlyalpha-api` is the sole mutation-capable server; one Host in `onlyalpha_api.main` |
| INV-K3-02 HTTP mutation uses Product Command | PASS | Create/Cancel route architecture guards and HTTP contract tests |
| INV-K3-03 Run reads use Product Query | PASS | Get/List route architecture guards and HTTP contract tests |
| INV-K3-04 transport-neutral Core/Commands/Queries | PASS | architecture lane, K3 recursive import guard, mypy/import-linter |
| INV-K3-05 public Research v2 semantics unchanged | PASS | research-command/query lanes; OpenAPI byte freshness; Web static/unit/E2E |
| INV-K3-06 no fallback mutation path | PASS | architecture source guard and unsupported-binding HTTP 500 test |
| INV-K3-07 one mutation-capable Host/no multi-worker | PASS | main composition architecture guard; no worker configuration surface |
| INV-K3-08 transport idempotency remains operational only | PASS | existing Research command semantics unchanged; research-command and FULL_LOCAL pass |
| Identity uniqueness | PASS | existing submission UUID4/key/fingerprint authority unchanged and tested |
| Determinism | PASS | canonical OpenAPI unchanged; query/order/cursor and full affected lanes pass |
| Durable authority | PASS | PostgreSQL Run/Attempt authority unchanged; real PG16 lanes pass |
| Persistence transactionality/idempotency | PASS | research-product-closure and research-postgres pass against PG16 |
| Public contract/schema | PASS | OpenAPI and generated TypeScript semantic delta zero |
| Fail-closed semantics | PASS | missing binding and pre-READY dispatch tests; no direct fallback |
| Research/Trading/Runtime boundary | PASS | architecture, core-full, recovery, sim-recovery and market lanes pass |

## Verification evidence

Required targeted gates:

```text
kernel:                    PASS — 41 passed
architecture:              PASS — 458 passed
research-command:          PASS — 47 passed
research-query:            PASS — 110 passed
OpenAPI freshness:         PASS — canonical bytes unchanged
web-static:                PASS
web-unit:                  PASS — 17 files / 85 tests
ruff:                      PASS
changed-file format:       PASS
Core mypy:                 PASS — 617 source files
API mypy:                  PASS — 17 source files
import-linter:             PASS — 3 kept / 0 broken
version sync:              PASS — 0.9.0
all-package build:         PASS
git diff --check:          PASS
```

Impact-aware local verification:

```text
uv run python scripts/verify.py agent --base 7a80bb405c43f8662d253a2264c044bb30a4379c

IMPACT VERIFIED
40 gates executed
```

The final run used the repository-tested PostgreSQL 16.10 server and client major 16. It passed all selected static/Web/build gates and
all selected lanes, including `research-product-closure` (19), `research-postgres` (92), `core-full` (2500), `recovery` (330),
`sim-recovery` (38), `ashare` (24), and `miniqmt-contract` (34). Full logs:

```text
test-results/verification/20260826T060147Z-7a80bb405c43-12211/
```

Initial FULL_LOCAL attempts correctly exposed local environment prerequisites: loopback binding required sandbox escalation, the
PostgreSQL DSN was initially absent, and the default `pg_dump` was major 18. The final authoritative run used a temporary `--rm`
`postgres:16.10` container and the installed PostgreSQL 16 client. The container was stopped/removed after verification. These setup
attempts are not reported as PASS evidence.

## Reverse audit

1. Canonical HTTP mutation routes directly call Research mutation services: **NO**.
2. Product Dispatcher plus legacy HTTP direct-service mutation path both exist: **NO**.
3. Research Run Get/List use Product Query Boundary: **YES**.
4. API DTO can become Domain/Persistence authority: **NO**.
5. `src/onlyalpha` imports FastAPI/Starlette/API DTO: **NO**.
6. Product Command/Query imports HTTP transport: **NO**.
7. Product Command can bypass Kernel READY: **NO**.
8. Dispatcher failure falls back to direct mutation: **NO**.
9. Product server constructs more than one mutation-capable Host: **NO**.
10. Production startup can configure multiple mutation-capable Uvicorn workers: **NO**.
11. K3 changed Research idempotency: **NO**.
12. K3 changed public HTTP route/DTO/error semantics: **NO**.
13. Canonical OpenAPI changed: **NO**.
14. PostgreSQL schema/migration changed: **NO**.
15. P9.0 semantic identity changed: **NO**.
16. K4/K5/K6/K7 was prematurely implemented: **NO**.
17. PostgreSQL 18 is future-only while 16.10 remains current verified truth: **YES**.

## Audit result

- Previous findings: none; this is the initial K3 implementation audit.
- BLOCKER: 0
- MAJOR: 0
- MINOR: 0
- SUGGESTION: 0
- Verdict: **GO — P9.K.3 DONE / VERIFIED (worktree)**
- Remote exact-SHA relevant gates: **NOT RUN**; Task Gate does not claim Final-SHA Certification.
- Next: **P9.K.4 — OpenAPI Contract Governance — IMPLEMENTATION READY**.

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
是否可进入下一阶段？ GO
```
