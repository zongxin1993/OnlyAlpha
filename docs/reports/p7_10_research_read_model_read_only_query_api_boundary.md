# P7.10 Research Read Model & Read-only Query/API Boundary

## Task Context

- Task Base SHA: `3758e54a3c01cd5c3ceef257510b5a5437966af5`
- Completion HEAD: unchanged Task Base SHA plus the current uncommitted P7.10 worktree; no implementation commit was created
- Dirty state: the user-provided untracked P7.10 Prompt was the only pre-existing change and remains preserved; all other listed
  changes belong to this task
- Version: `0.7.10`
- Increment state: `P7.10 — VERIFIED LOCALLY` after the Task Gate evidence below
- P7 milestone: `IN_PROGRESS`; P7 Final Certification is `NOT COMPLETE`

## Frozen Task Contract

Goal: establish the single stable, stateless, deterministic consumer chain from verified portable Research Artifact through a
transport-neutral Query model/service to a versioned read-only HTTP API.

Modification scope: `onlyalpha.research.query`, the independent `onlyalpha-api` package, focused Query/API/architecture tests,
canonical lane and impact-aware quality integration, synchronized 0.7.10 workspace metadata/lock, ADR/current-truth documentation,
and this report. Upstream Artifact/Result/Evaluation implementation and all Trading/Runtime semantics were unchanged.

Impact scope: Artifact consumer contract, verified read semantics, Query filtering/pagination/Decimal/timestamp/error contracts,
public Research exports, API/OpenAPI transport, workspace dependency/build/version graph, Research/Trading firewall, and quality
infrastructure. Required behavior included exact addressing, Summary/Catalog/Series, `[from,to)`, strict timestamp cursor, stable
pagination, missing/corrupt separation, portable/fresh-process operation, three GET endpoints, and no semantic recomputation.

Expansion triggers were any change to Artifact/Statistics/Research Result public authority, serialization/Decimal/timestamp semantics,
existing Protocols, package discovery, quality infrastructure, or newly discovered consumer dependencies. Actual expansion stopped at
the nearest stable boundaries: P7.9 Artifact regression, workspace package graph, and the required FULL_LOCAL self-verification for
quality-infrastructure changes.

Out of scope remained Research/Live Runtime activation, Web UI, authentication/RBAC/TLS/CORS platform, Trading/Runtime control API,
Artifact catalog/search/latest, Query cache, mutable state, Scheduler/workers, Optimizer/ranking, new Statistics/Analytics, Dataset or
execution-Store API, raw Parquet download, and cross-Artifact/Dataset analytics.

## Architecture and Authority

Statistics Result remains rows semantic authority; Research Result remains exact composition authority; Research Artifact remains a
portable immutable materialized read view. Query Result is an ephemeral deterministic projection and HTTP is only its transport
representation. No Query fingerprint, Store, cache, index, latest pointer, recovery state, or reverse execution-plane dependency was
introduced.

Core `OnlyResearchQueryService` depends only on `OnlyResearchArtifactReader.load_verified()`. It projects a schema-v1 immutable
Artifact Summary, canonical exact Statistics Catalog with complete Feature/Target/Definition/Numeric descriptors, and Statistics
Series Pages. Filtering uses UTC nanosecond `[from,to)`, cursor comparison is strict `>`, and `limit + 1` derives stable `has_more` and
the non-terminal cursor. Decimal remains `Decimal` in Core.

The independent `onlyalpha-api` package owns FastAPI, Pydantic, Uvicorn, and ASGI test dependencies. Three GET routes under `/api/v1`
serialize Decimal as exact strings, preserve event time as nanosecond integers, serialize audit time as UTC `Z`, and map invalid,
missing, unknown Statistics, and corrupt Artifact to stable 400/404/500 bodies. Only the server composition root constructs the
concrete Parquet Artifact Store from an explicit `--artifact-root`; routes never inspect files or Parquet.

ADR 0085 freezes exact addressing, no Catalog/latest/recomputation/cache, transport isolation, pagination/serialization/error
semantics, corruption fail-closed, and unsupported Research/Live Runtime state.

## Package and Dependency Changes

`packages/api/onlyalpha-api` joined the uv workspace at exact version 0.7.10 and depends on exact `onlyalpha==0.7.10`. Direct bounded
production dependencies are FastAPI, Pydantic, and Uvicorn; direct dev dependencies include HTTPX/HTTPX2 required by the current
Starlette TestClient and pytest. All workspace distribution versions and exact internal pins were synchronized by
`scripts/version_sync.py`; `uv.lock` was regenerated.

## Verification Evidence

- Focused Query Core: Mypy passed; initial contract/service suite 29 passed.
- Focused Query/API: strict API-package Mypy passed; combined Query/API suite 35 passed before defensive coverage expansion.
- Architecture/quality contract tests: 44 passed.
- `research-query` canonical coverage lane: 72 passed; line 100.00%, branch 100.00%.
- `research-artifact` producer/consumer regression: 53 passed.
- `scripts/version_sync.py check`: workspace release graph consistent at 0.7.10.
- `uv build --package onlyalpha-api`: built `onlyalpha_api-0.7.10.tar.gz` and wheel.
- Impact plan: `VERIFICATION_INFRASTRUCTURE`; release static + all 15 canonical lanes + all-package build.
- Final impact-aware verification: recorded below after execution.

The initial online lock and isolated build attempts were blocked by the filesystem/network sandbox; approved network execution then
resolved real package versions and completed lock/build. The first Query coverage run was a real failed gate (88.77% total,
line 93.37%, branch 63.51%); defensive constructor/error branches were tested, and the rerun reached line/branch 100% without lowering
thresholds.

## Final Impact Verification

The first terminal-state sandbox run passed 25 gates and failed only the final all-package build because isolated hatchling resolution
could not access PyPI; it recorded a real failed manifest and was not treated as green. The same complete command was then rerun with
approved network access:

`UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python scripts/verify.py agent --base
3758e54a3c01cd5c3ceef257510b5a5437966af5` passed all 26 planned gates: 10 release static checks; Research Query 72,
Research Artifact 53, Research Result 28, Research Evaluation 96, Research Sweep 27, Research Factor 57, Research Job 30,
Research Calculation 127, Calculation 58, Research Dataset 36, core-full 1,863, recovery 330, SIM recovery 38, A-share 24,
MiniQMT contract 34; and all-package build. The canonical lanes collected 2,873 tests. Full logs:
`test-results/verification/20260816T071119Z-3758e54a3c01-57390/`.

Verdict: `IMPACT VERIFIED`. This is local development verification only and does not constitute Final-SHA Certification.

## Remaining P7 Scope

Research Web consumption/visualization, finite Research Runtime lifecycle, and P7 Final Closure/Final-SHA Certification remain open.
Research Runtime is unsupported, Live Runtime is unsupported, and Web UI is not implemented. This report records Task Gate evidence,
not `CERTIFIED`, `ACCEPTED`, or Final-SHA evidence.
