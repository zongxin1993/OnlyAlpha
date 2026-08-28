# P9.K.6 External Client Migration — Implementation and Task-Gate Evidence

- Date: 2026-08-28
- Branch: `master`
- `TASK_BASE_SHA`: `39c8dbf6f78f174dfd896057b0490dedf432b5ea`
- `IMPLEMENTATION_SHA`: `WORKTREE — NOT YET IMMUTABLE`
- Release version: `0.9.6`
- Gate: P9.K.6 Task Gate; no Phase Gate or Final-SHA Certification claim
- Governing contract: ADR 0101, `docs/p9_k_stateful_kernel_protocol_boundary.md`, K6 frozen Prompt, K0 authority contract

## Task contract

Goal: migrate every supported external Product Actor to the governed Product Control Plane without changing current Research business
semantics or introducing a second authority.

Modification scope: one separate Python Product client package, deterministic canonical OpenAPI projection, Product client CLI, focused
client/API integration and architecture gates, external-surface classification, and Product/internal/operator documentation separation.

Impact scope: Product HTTP consumer boundary, workspace packaging/version graph, OpenAPI client projection, Research Run HTTP tests,
Web contract verification, K0 surface inventory projections, examples and documentation.

Expansion triggers were a canonical OpenAPI change, Product route/DTO change, persistence change, or any need to modify Kernel/Research/
Strategy semantics. None occurred. K7 remote protocol, K8 hard seal, new business endpoints, migrations and retry policy remained out of
scope.

## Authority graph

Before:

```text
Web → HTTP Product API → Product Command/Query → Kernel/Application authority
External Python / root CLI / public example → OnlyEngine / Runtime
```

After K6:

```text
Web / Python / Agent / Automation / Notebook / Product CLI
→ canonical OpenAPI-derived client
→ HTTPS / JSON
→ Product HTTP Adapter
→ Product Command / Query
→ Stateful Kernel / existing Application authority
```

The temporary root `OnlyEngine` exports and `onlyalpha run/snapshot` remain explicit `LEGACY_K8_TARGET` debt only. They are no longer
documented as normal Product usage and did not cause `/engine/run`, `/engine/snapshot`, or another Product path to be added.

## Current external surface inventory

The machine-readable closure is `docs/architecture/p9_k6_external_client_contract.toml`. It reclassifies every K0 external surface and
adds the official Python/Product CLI surfaces. Unknown and unclassified surfaces are zero.

| Surface family | K6 classification | Decision |
|---|---|---|
| `onlyalpha-client` Python facade | `PRODUCT_API_CLIENT` | Official Python/Agent/automation/notebook Product boundary |
| `onlyalpha-client research create/get/list/cancel` | `PRODUCT_API_CLIENT` | Product CLI through the same client and HTTP contract |
| `apps/onlyalpha-web` | `PRODUCT_API_CLIENT` | Retain canonical generated TypeScript + strict admission path |
| `onlyalpha-api` | `PRODUCT_CONTROL_PLANE` | Retain as the single mutation-capable Product HTTP adapter |
| root `onlyalpha run/snapshot` | `LEGACY_K8_TARGET` | Preserve temporarily; remove from Product documentation; seal in K8 |
| root `onlyalpha scenario validate/run` | `TEST / SCENARIO` | Retain deterministic test composition |
| root `onlyalpha operations status/run` | `OPERATOR / INFRASTRUCTURE` | Retain exact read-only PostgreSQL diagnostics |
| Research Worker / provider doctor / database tooling | `OPERATOR / INFRASTRUCTURE` | Retain narrow non-Product authority |
| `onlyalpha-artifact-api` | `READ_ONLY_COMPATIBILITY_SURFACE` | Retain temporarily with mutation capability fixed at zero; K8 owner |
| `examples/product/research_client.py` | `PRODUCT` | Teach only the Product API client |
| `examples/internal/committed_execution_report.py` | `INTERNAL` | Explicitly label direct Engine composition as internal |
| fixture/baseline scripts and tests | `TEST / SCENARIO` | Retain direct composition outside Product semantics |

The contract contains the complete per-command CLI table and exact operator direct-access allowlist. No CLI command is `UNKNOWN` or
`UNCLASSIFIED`.

## Python client boundary

Physical package: `packages/client/onlyalpha-client`.

Dependency graph:

```text
onlyalpha-client → httpx
onlyalpha-client -X→ onlyalpha / onlyalpha-api / Kernel / Runtime / Application / Persistence
```

The thin facade owns base URL, headers, timeout, HTTP request construction, transport failure, strict success-response admission and
stable API error projection. It does not construct semantic fingerprints, Research admission, lifecycle state, persistence, command
receipts or business retry. Mutation calls execute exactly once per method invocation; callers supply and retain idempotency keys.

Supported current authoritative operations are exactly Create/Get/List/Cancel Research Run. No future Backtest/SIM/LIVE/Strategy API
was invented.

## Canonical OpenAPI to Python generation

```text
FastAPI Routes + API DTO
→ contracts/research-api/v2/openapi.json
→ scripts/openapi_clients.py write/check
→ generated/contract.py
→ thin onlyalpha-client facade
```

- Canonical input: `contracts/research-api/v2/openapi.json`
- Generator: repository-local deterministic generator version `1`
- Exact formatter: Ruff `0.15.22` from the locked Python 3.12 toolchain
- Projection selection: every operation tagged `research-runs` plus the complete transitive component-schema closure
- Nondeterministic inputs: none; no timestamp, host, path, Git SHA, build ID, UUID or environment ordering enters output
- Python projection SHA256: `33f8dc35c843e5c375f5f6664286d101f85b0d835f2f5647ea3bffd68ca39fde`
- Freshness: PASS by regenerate-to-temporary-tree exact byte comparison

This is a projection consumer of K4's accepted contract, not another OpenAPI source or compatibility approval authority.

## Contract and Web identity

| Artifact | Base SHA256 | Worktree SHA256 | Delta |
|---|---|---|---|
| canonical OpenAPI | `6a66fde2dba23fe6770bc5b27031337d95bf4b987b0ca946903c1a7c89b95d1e` | same | 0 bytes |
| generated TypeScript | `066c94d1e9c1008fcfccb1545bb2c85b587bd991783b3a53e322726e357eee94` | same | 0 bytes |

Web remains an HTTP-only Product client. Static contract freshness, ESLint, Prettier and TypeScript passed; 17 Vitest files / 85 tests
passed; the production Web build passed. No Web/Kernel dependency or handwritten alternate schema was introduced.

## Client/server integration evidence

The client tests use both `httpx.MockTransport` for transport boundary characterization and the actual FastAPI Product app factory with
the real Product Command/Query dispatch path.

| Scenario | Evidence/result |
|---|---|
| Create Research | client → FastAPI → Product Command → existing admission/store; PASS |
| Get Research | exact Run projection returned; PASS |
| List Research | existing ordering/page projection consumed without reinterpretation; PASS |
| Cancel Research | client → Product Command Dispatcher → existing cancellation authority; PASS |
| response lost after Create commit | first call becomes transport failure; explicit same-key retry returns `REUSED`; one Run/Receipt; PASS |
| same key, different command | Create key reused for Cancel returns HTTP 409 / `RESEARCH_SUBMISSION_KEY_CONFLICT`; one authority; PASS |
| server unavailable | one transport attempt, `OnlyAlphaTransportError`, no implicit retry or local fallback; PASS |
| malformed success/error response | fail closed as `OnlyAlphaProtocolError`; PASS |

## Architecture invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K6-01 supported external actors have Product API path | PASS | Python facade, Product CLI, Web, Agent/automation/notebook package path |
| INV-K6-02 external Python does not own lifecycle | PASS | package metadata/import AST and no-constructor gates |
| INV-K6-03 one official Python Product client | PASS | one `onlyalpha-client` package; repository inventory |
| INV-K6-04 client has zero Core dependency | PASS | metadata plus source import checks |
| INV-K6-05 canonical OpenAPI sole schema authority | PASS | one canonical contract; generated schema closure; no handwritten DTO authority |
| INV-K6-06 deterministic projection | PASS | exact generator/formatter and byte-for-byte freshness check |
| INV-K6-07 client is thin transport adapter | PASS | source review and capability scans |
| INV-K6-08 retry preserves K5 identity | PASS | no implicit mutation retry; response-loss explicit same-key convergence |
| INV-K6-09 no local fallback | PASS | transport failure test and forbidden-capability architecture scan |
| INV-K6-10 Product CLI uses client | PASS | client-package entrypoint/import boundary; root legacy commands separately classified |
| INV-K6-11 operator/worker/test paths explicit | PASS | exact machine contract and narrow allowlist |
| INV-K6-12 Product examples do not own Engine | PASS | AST gate over `examples/product`; old example relocated/internalized |
| INV-K6-13 no legacy Engine HTTP semantics | PASS | canonical contract unchanged; no API source change |
| INV-K6-14 K8 hard seal not performed | PASS | root exports and legacy CLI retained only as tracked K8 debt |
| INV-K6-15 no semantic identity contamination | PASS | no semantic source changes; client metadata remains transport-only |
| INV-K6-16 P9.0/K1-K5 authorities preserved | PASS | zero Core/Application/Research/Strategy/Runtime/Persistence diff |
| identity uniqueness chain | PASS | K5 Receipt path unchanged; same/different command identity client E2E |
| deterministic canonicalization | PASS | canonical OpenAPI and TS unchanged; Python projection reproducible |
| single/durable authority | PASS | client persists nothing; existing PostgreSQL/semantic authorities unchanged |
| architecture dependency direction | PASS | 492-test canonical Architecture Gate |
| persistence uniqueness/transactionality | PASS (unchanged) | no schema/adapter/migration delta; HTTP tests consume K5 path |
| fail-closed public contract | PASS | malformed responses rejected; server conflict/transport preserved |

## Reverse audit

```text
new semantic authority?               NO
new product mutation authority?       NO
new lifecycle authority?              NO
new persistence authority?            NO
new API contract authoring authority? NO
new external direct Kernel path?      NO
new fallback path?                    NO
new hidden client retry identity?     NO
```

Strategy authority, Research authority, Product Command Receipt, Kernel mutation admission and canonical OpenAPI remain unique. New
PostgreSQL migrations/tables are zero. P9.0 semantic delta, Strategy delta, Research authority delta, Kernel lifecycle delta and
Receipt/recovery delta are all zero.

## Verification evidence

Local PASS:

```text
focused client/API/K0/K6 architecture: 45 passed
client + complete API package:          42 passed
Research Command canonical lane:        57 passed
Architecture canonical lane:           492 passed
Web static:                             PASS
Web unit:                               17 files / 85 tests PASS
Web build:                              PASS
OpenAPI contract check:                 PASS
Python client freshness:                PASS
Ruff check / format:                    PASS; 1479 Python files formatted
Mypy:                                   PASS; 656 source files
Version graph 0.9.6:                    PASS
All-package source/wheel build:         PASS; includes onlyalpha-client
Project-state consistency (K6 verified, K7 ready): PASS
git diff --check:                       PASS
```

Budgeted local verification executed all 10 local static commands successfully and returned `LOCAL_PASS_CI_REQUIRED` (exit-code 3
semantics). Manifest:
`test-results/verification/local-budget/20260828T023500Z-39c8dbf6f78f-82789/manifest.json`.

CI REQUIRED / not claimed PASS by the budgeted plan:

```text
web-static, web-unit, web-build, web-e2e, build
kernel, strategy, research-definition, research-specification, research-run,
research-command, research-execution, research-product-closure, research-postgres,
research-runtime, research-query, research-artifact, research-result,
research-evaluation, research-sweep, research-factor, research-job,
research-calculation, calculation, research-dataset, core-full, recovery,
sim-recovery, ashare, miniqmt-contract
```

Some directly applicable deferred commands were also executed separately and passed as recorded above; this does not rewrite the
machine manifest or claim the remaining deferred plan as PASS. Full Web Playwright E2E, real PostgreSQL lanes, broad Core/Research/
recovery/market/provider lanes, Phase Gate and Final-SHA Certification were not executed locally.

## Convergent Task-Gate audit

- `AUDIT_BASE_SHA`: `39c8dbf6f78f174dfd896057b0490dedf432b5ea`
- `AUDIT_HEAD_SHA`: `WORKTREE — NOT YET IMMUTABLE`
- Scope: P9.K.6 Task Gate only
- Previous P9.K.6 findings: none

```text
BLOCKER:    0
MAJOR:      0
MINOR:      0
SUGGESTION: 0
```

No frozen-design, uniqueness, determinism, dependency-direction, retry/replay, public-contract or fail-closed violation was found in the
current K6 scope. Direct K6 acceptance evidence is sufficient; budget-deferred broader CI remains explicitly open and is not represented
as PASS or Final-SHA evidence.

Task Gate verdict: **GO**.

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
是否可进入下一阶段？ GO
```

## Remaining K8 debt

- remove/deprecate unsupported mutation-oriented root exports;
- remove or hard-seal `onlyalpha run/snapshot` as external Product UX;
- decide final removal of `onlyalpha-artifact-api` after compatibility consumers are closed.

K7 remote protocol work was not started.
