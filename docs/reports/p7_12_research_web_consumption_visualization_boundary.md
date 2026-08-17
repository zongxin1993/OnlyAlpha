# P7.12 Research Web Consumption & Visualization Boundary

## Task Context

- Task Base SHA: `e76d5e111c6e9aa8dc1336d6aa2e817397c75b44`
- Completion HEAD: pending; implementation is in the current worktree and no implementation commit is created by this task
- Pre-existing dirty state: the user-provided untracked `prompts/P7.12ResearchWebConsumption&VisualizationBoundary.md` only
- Target version: `0.7.12`
- P7 milestone: `IN_PROGRESS`
- P7 Final Certification: `NOT COMPLETE`
- LIVE Runtime: `UNSUPPORTED`

## Frozen Task Contract

Goal: establish the first complete browser consumer vertical slice from an exact Research Result fingerprint through the portable
Research Artifact, transport-neutral Query service, versioned read-only HTTP API, validated Web read model, exact table, and an
explicitly lossy visualization projection.

Modification scope: the `onlyalpha-api` HTTP transport, deterministic API-v2 OpenAPI evidence, a private
`apps/onlyalpha-web` React application, focused Python and TypeScript contract/component/E2E tests, Web verification tooling,
impact-aware quality and CI/certification integration, synchronized 0.7.12 version metadata, ADR/current-truth documentation, and
this report.

Impact scope: the Research Query HTTP consumer contract, browser transport admission and presentation, workspace build/version
graph, and verification infrastructure. Statistics Result remains row authority, Research Result remains exact composition
authority, Artifact remains the portable immutable read boundary, and Query remains an ephemeral projection. Query Core integer,
Decimal, identity, filtering, and pagination semantics are unchanged.

Required behavior: API-v2-only product routes; canonical decimal strings for response timestamps/cursors and request time filters;
independent Query/API schema versions; deterministic generated OpenAPI and TypeScript transport types; strict Zod admission;
`bigint` Web time and exact Decimal text; URL-owned selection; bounded manual pagination; explicit missing/corrupt/invalid/
transport/contract/chart failures; exact table plus collision-safe Lightweight Charts projection; and operation with upstream
Research execution Stores unavailable.

Expected acceptance tests: Python API/OpenAPI and Query regression tests; TypeScript identity/time/Decimal/schema/client/query-key/
pagination/chart unit tests; user-visible component tests with MSW; a real FastAPI + built Web Playwright vertical slice; Web lint,
format, strict typecheck, coverage, and build; then the repository impact plan and its exact agent gate.

Expansion triggers: discovery of a formal external v1 consumer; any required change to Artifact, Statistics, Research Result, or
Query semantic identity; inability to preserve exact time without changing Core; new cross-package version authority; or changes to
verification infrastructure. Current repository inspection found no formal external v1 consumer, so v1 is superseded without a
compatibility wrapper. Required verifier/workflow changes deliberately trigger verification-infrastructure self-protection.

Out of scope: all Research producer semantics, new Statistics or analytics, Dataset/Calculation/Statistics/Research Result Store
access, Artifact catalog/latest/search, Research execution or Runtime control, authentication/RBAC, persistence/cache authority,
WebSocket/realtime features, Trading/Backtest/SIM/LIVE UI or control, and production reverse-proxy/deployment orchestration.

## Implementation and Evidence

## Implemented Architecture

The authority chain remains Statistics Result → exact Research Result composition → portable Research Artifact. Query Core is the
only semantic read boundary and still uses schema version 1, Python integers, Decimal, exact filtering, strict cursor semantics, and
the existing Artifact Reader Port. HTTP and Web add no authority, persistence, producer dependency, or recovery state.

`onlyalpha-api` now exposes only `/api/v2/research/artifacts/...`. `RESEARCH_API_SCHEMA_VERSION = 2` is independent from the unchanged
`RESEARCH_QUERY_SCHEMA_VERSION = 1`. Response `ts_event_ns` and `next_after_ts_event_ns`, and request `from/to/after`, are canonical
decimal strings. Router admission converts request strings directly to Python `int`; response DTOs convert Query integers directly
to strings. Decimal remains fixed decimal string and never passes through float.

FastAPI generates `contracts/research-api/v2/openapi.json` deterministically with sorted keys, stable indentation, and no runtime
metadata. `scripts/export_research_openapi.py write|check` owns Python export; `openapi-typescript` generates the checked-in transport
shape. `scripts/web_suite.py static` independently regenerates to a temporary file and byte-compares it, then runs Web lint, format,
and strict typecheck.

## Web Application

`apps/onlyalpha-web` is a private version-0.7.12 Node 24 application. Registry versions were queried on 2026-08-17 and exact direct
dependencies were pinned: React/React DOM 19.2.8, React Router 7.18.2, TanStack Query 5.101.4, Zod 4.4.3, Lightweight Charts 5.2.1,
Vite 8.2.1, and the exact lint/test/build toolchain recorded in `package.json`. TypeScript 7.0.2 was rejected after npm peer
resolution proved that current `openapi-typescript` requires TypeScript 5.x; stable 5.9.3 was selected rather than bypassing peer
contracts. `package-lock.json` is the exact resolved graph; no Yarn/pnpm/Bun lock or committed node_modules exists.

The module boundary is generated transport + Zod schemas/client/mapper, framework-free Research domain exact values, route-driven
feature pages, pure chart projection, and a single Lightweight adapter. ESLint restricted-import rules freeze Domain ↛ React/
TanStack/API/Lightweight, API ↛ features/charts, and pure charts ↛ HTTP/React/Lightweight. Features never call fetch directly.

The Web domain validates exact lower-case SHA256, maps timestamp text directly to branded `bigint`, and keeps Decimal as branded
canonical string. TanStack Query cache is disposable, uses infinite stale time for immutable success, disables focus refetch/default
retry, and is not persisted. URL routes own exact selection; there is no global client-state library.

The UI implements `/research`, exact Artifact overview + Statistics catalog, and exact Statistics detail. Series pagination uses a
bounded two-row first page in the current UI and manual Load More. Page merge requires strictly increasing timestamps and an exact
cursor/content match. The exact table displays UTC projection, raw ns, exact Decimal/NULL, sample count, and status.

Pure chart projection maps ns to seconds and Decimal text to finite numbers only. NULL is whitespace. Duplicate/out-of-order exact
time, second-resolution collisions, unsafe chart time, and non-finite numeric projection return `CHART_PROJECTION_ERROR`; no point is
merged/dropped/synthesized and the exact table remains available. The React Lightweight Charts adapter owns create/update/
ResizeObserver/remove lifecycle and renders TradingView attribution.

## Quality Integration and Verification Evidence

The Web verification surface is `web-static`, `web-unit`, `web-build`, and `web-e2e`; it is evidence inside existing Task/Phase/
Certification gates, not a new gate level. Web-only impact stops at the API boundary. API/OpenAPI transport changes select Query +
Artifact regression and all Web checks. Verifier/workflow self-change expands to the complete local gate. Layered Quality and
Final-SHA Certification use Node 24 + `npm ci`; Final-SHA verdict now requires a `web` gate. CodeQL includes Python and JavaScript/
TypeScript.

Focused evidence before final impact closure:

- `research-query --coverage`: 73 passed; total line 99.76%, branch 98.68%; Query Core schema remained 1.
- `research-artifact`: passed the portable-boundary regression lane.
- Vitest: 21 unit/component/MSW tests passed.
- Web critical-module coverage: statements/lines/functions 100%, branches 92.85% (thresholds 95% line, 90% branch).
- `npm run check`: ESLint, Prettier, strict TypeScript, Vitest, and production Vite build passed.
- Vite production build: 175 modules; HTML 0.52 kB, CSS 3.03 kB, JS 563.98 kB (175.48 kB gzip); a non-blocking chunk-size
  optimization warning remains and no speculative code-splitting framework was added.
- Real Playwright E2E: 1 passed against built Vite preview → same-origin proxy → real FastAPI → portable Artifact. The fixture reused
  P7.10 support and made Dataset/Calculation/Statistics/Research Result roots unavailable before serving; browser opened the exact
  result, catalog, chart and table, refreshed the direct detail URL without losing selection, then loaded the second cursor page.
- `npm ci --ignore-scripts --offline` rebuilt 332 packages exactly from `package-lock.json`; npm reported zero known vulnerabilities.
- OpenAPI write/check + temporary TypeScript regeneration byte check passed.
- `scripts/version_sync.py check`: consistent at 0.7.12.
- Architecture/verification/version-tool focused regression: 57 passed.

The first E2E sandbox attempt was correctly blocked from binding loopback and was rerun with explicit approval. The first browser
assertion found Lightweight Charts' internal accessibility table in addition to the exact table; the locator was narrowed to the
table containing `Raw ts_event_ns`, after which the real vertical slice passed. These were not treated as green attempts.

## Final Impact Verification

`uv run python scripts/verify.py plan --base e76d5e111c6e9aa8dc1336d6aa2e817397c75b44` selected
`VERIFICATION_INFRASTRUCTURE`: all release/Web checks, all 16 canonical lanes, and all-package build. No manual narrowing occurred.

The approved loopback-capable final command
`uv run python scripts/verify.py agent --base e76d5e111c6e9aa8dc1336d6aa2e817397c75b44` passed 31/31 gates:

- 10 release static checks, including all required Mypy scopes and version sync;
- web-static, web-unit, web-build, web-e2e;
- Research Runtime 65, Query 73, Artifact 53, Result 93, Evaluation 96, Sweep 27, Factor 57, Job 30,
  Research Calculation 127, Calculation 58, Research Dataset 36;
- core-full 1,961 collected (1,960 passed, 1 skipped), recovery 330, SIM recovery 38, A-share 24, MiniQMT contract 34;
- all-package workspace build at 0.7.12.

The canonical lanes collected 3,102 tests. Machine-readable result is `VERIFICATION_PASSED`; full logs and manifest are in
`test-results/verification/20260817T005056Z-e76d5e111c6e-57191/`.

Verdict: `P7.12 — VERIFIED LOCALLY`. This is local development evidence, not Final-SHA Certification, remote CI, CodeQL, or
`ACCEPTED` evidence. Completion HEAD remains the unchanged Task Base SHA plus the current P7.12 worktree; no commit was created.

## Remaining P7 Scope

P7 milestone remains `IN_PROGRESS`. P7 Final-SHA Certification is `NOT COMPLETE`; no remote CI/CodeQL result is claimed here. The
next semantic direction is P7 Final Closure and exact Final-SHA Certification. Research YAML/CLI, Scheduler/Optimizer, Catalog/
latest/search, new Statistics, authentication, deployment orchestration, Research execution control, Trading/SIM/LIVE Web, mixed
heterogeneous lifecycle, and LIVE Runtime remain out of scope; LIVE is still `UNSUPPORTED`.
