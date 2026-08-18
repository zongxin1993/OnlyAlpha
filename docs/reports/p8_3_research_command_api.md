# P8.3 Research Command API — Implementation Report

- Date: 2026-08-18
- Version: `0.8.3`
- `TASK_BASE_SHA`: `dc64567e0069678859abf3d51deaed0a8c3753d9`
- Working implementation: intentional dirty Task worktree; no commit/PR created
- Authority: local Task Gate evidence, including PostgreSQL 16.10; not P8 Final-SHA certification

## Result and authority boundaries

P8.3 implements the durable Research Run write/control HTTP boundary. Core `onlyalpha.research.command` owns application-level submission
retry interpretation, cancellation re-interpretation and operational read projection. `OnlyResearchSpecification`/Resolver remains the
request semantic authority, `ResearchRun` remains the lifecycle authority, PostgreSQL remains the Run/Attempt operational authority, the
Execution Store alone owns claim/lease/fence/finalization, and immutable Stores remain Dataset/Result/Artifact authorities.

The API never starts Scheduler, Worker, Runtime or Engine, never mutates Attempt/lease/fence, and never returns Result/Artifact content.
Portable Artifact Query remains a PostgreSQL-free App Factory and console entry.

## Idempotency, atomicity and reads

Submission requires a canonical UUID4 `Idempotency-Key`. The command fingerprint covers canonical strict Specification JSON. Same key +
same command returns the existing Run without repeating resolution or Dataset verification; same key + different command conflicts;
different keys create distinct Runs for the same Specification.

Migration `0004_research_run_submission_and_read_projection.sql` adds `research_run_submission` and the descending Run read index. Run and
submission mapping commit in one transaction. A unique-key race rolls the entire losing transaction back, reloads the winner and compares
the command fingerprint, so no orphan Run remains. Published 0001–0003 bytes were not modified.

Run list order is `(queued_at DESC, run_id DESC)` with a strict versioned canonical JSON/base64url cursor. Cancellation uses only Domain
successors and bounded revision/state CAS reload: QUEUED becomes CANCELLED, RUNNING becomes CANCEL_REQUESTED, already requested/cancelled
is idempotent, and completed/failed conflicts.

## HTTP, composition and Web contract

The full local API exposes:

- `POST /api/v2/research/runs` — `202`, required `Idempotency-Key`, `Location`;
- `GET /api/v2/research/runs/{run_id}` — `200` exact operational DTO;
- `GET /api/v2/research/runs?limit=&cursor=` — `200` lightweight keyset page;
- `POST /api/v2/research/runs/{run_id}/cancellation` — `200` persisted Run.

Run errors use stable `{error:{phase,code,detail}}` transport and distinguish invalid input, missing Dataset/Run, idempotency/terminal
conflict, Store unavailability and corrupt authority. `onlyalpha-api --user-data-root` reads `ONLYALPHA_POSTGRES_DSN`, checks schema
compatibility only and binds loopback by default. `onlyalpha-artifact-api --artifact-root` is the portable GET-only server.

OpenAPI v2 and generated TypeScript are synchronized. Web Zod admission keeps revision as canonical string then maps it to `bigint`; the
client exposes submit/get/list/cancel methods and stable query keys. No P8.4 page or form was added.

## Verification evidence

- `research-command --coverage`: PASS — 23 tests; 96.71% lines, 88.00% branches, 96.01% combined.
- `research-run --coverage`: PASS — 45 tests; 100% lines/branches.
- `research-query --coverage`: PASS — 77 tests; 99.42% lines, 100% branches.
- `research-dataset`: PASS — 36 tests.
- PostgreSQL 16.10 `research-postgres --coverage`: PASS — 57 tests; 84.67% lines, 75.00% branches, 82.91% combined. Matching 16.10
  container clients proved backup and isolated restore.
- Web static/OpenAPI/generated contract: PASS.
- Web unit coverage: PASS — 24 tests; 100% statements/functions/lines, 93.75% branches.
- Web production build: PASS (existing chunk-size advisory only).
- Version sync set/check: PASS — workspace graph `0.8.3`.

Final `verify.py agent --base dc64567e...`: PASS — `IMPACT VERIFIED`, 36/36 gates. It included ten release-static commands, Web
static/unit/build/E2E, every canonical lane, PostgreSQL 16.10, `core-full` (2104 collected), recovery (330), SIM recovery (38), A-share
(24), MiniQMT contract (34) and all-package build. Evidence:
`test-results/verification/20260818T051259Z-dc64567e0069-74505/`. No remote Final-SHA certification was performed; P8 remains IN_PROGRESS.

Earlier full-gate attempts transparently exposed and closed three integration omissions before the successful run: the constrained
PostgreSQL client PATH omitted Node, the E2E server still imported the replaced Artifact App Factory name, and typed Dataset errors briefly
changed existing Runtime failure codes. The final implementation preserves Runtime codes and maps HTTP-specific codes only at admission.

## Deviations and remaining scope

The existing API package used one small Artifact router rather than the prompt's suggested nested directory. P8.3 keeps that router and
adds separate Run files/App factories, preserving the same boundary with less unrelated churn. The existing Dataset Store had one broad
error type; typed not-found/corrupt subclasses were added because the HTTP contract must distinguish absence from corruption.

Specification V1 still references an exact Dataset Snapshot and Calculation/Statistics plans; it does not express the P8.4 product-level
Universe Builder, Eligibility Builder, or Decision/Signal expression. Those require a formal future Specification evolution. P8.4 pages,
multi-user authentication/RBAC, streaming push, progress percentage, pause/resume/delete/manual retry and public deployment remain out of
scope.
