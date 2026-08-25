# P9.K.0 Product Authority Surface Inventory

- Audit SHA: `35873d017576eb786976c22dfa7f3db375df6979`
- Audit date: `2026-08-25`
- Governing ADRs: ADR 0097, ADR 0100, ADR 0101
- P9.K design reference: `docs/p9_k_stateful_kernel_protocol_boundary.md`
- Scope: all current externally reachable product/control surfaces, direct Engine/Runtime construction, operational and semantic mutation capabilities, workers, operator tooling, examples, and test composition
- Method: current-source AST/import scan, all workspace `[project.scripts]` scan, public `__all__` inspection, route-to-application/store call tracing, writer ownership tracing, and existing architecture-test review
- Verdict: **COMPLETE**

## Audit result

```text
Total surfaces:                 31
Unclassified surfaces:          0
Unknown mutation authorities:   0
Known migration debts:          3
New architecture violations:    0
P9.0 semantic changes:           0
K1 implementation:              NOT STARTED
```

The current externally reachable surface is finite. Every mutation path below resolves to one named application, operational, semantic, runtime, or infrastructure authority. No audited API route, Web module, Runtime, or Research Worker owns Strategy publication authority.

## Vocabulary and dependency freeze

Actors use only `WEB`, `PUBLIC_PYTHON`, `CLI`, `AGENT`, `AUTOMATION`, `WORKER`, `OPERATOR`, `INFRASTRUCTURE`, `INTERNAL_APPLICATION`, `RUNTIME`, `TEST`, and `EXAMPLE`. Target classifications use only `KEEP INTERNAL`, `MIGRATE TO PRODUCT API`, `REMOVE`, `OPERATOR / INFRASTRUCTURE ONLY`, and `TEST ONLY`.

The frozen target direction is:

```text
External Product Actor
        ↓
OpenAPI Product Contract
        ↓
HTTP Adapter
        ↓
Application Command / Query
        ↓
Stateful Kernel / Application Authority
        ├──────────────→ Domain / Runtime
        └──────────────→ Ports → Infrastructure
```

K0 freezes this direction only. It does not introduce a Kernel Host, lifecycle state machine, dispatcher, supervisor, recovery coordinator, or new Product API.

## Surface inventory

| ID | Exact location | Actor / current exposure | Capability | Authority reached / durable authority | Current call path | Target classification / stage | Known debt / mechanical guard |
|---|---|---|---|---|---|---|---|
| K0-S001 | `src/onlyalpha/__init__.py`; `src/onlyalpha/engine/__init__.py`; `src/onlyalpha/runtime/__init__.py`; `src/onlyalpha/cluster/__init__.py` | `PUBLIC_PYTHON` / public framework imports | `COMMAND`, `EXECUTION`, `LIFECYCLE` | Engine and Runtime mutable authorities; configured Runtime persistence | external Python → Engine/Runtime/Cluster construction → planning/factory → Runtime | `MIGRATE TO PRODUCT API` / K6 then K8; internal objects remain | Debt: direct public product control. Exact top-level exports and constructor sites are frozen by `test_p9_k0_product_surfaces.py`. |
| K0-S002 | `pyproject.toml: onlyalpha`; `src/onlyalpha/cli.py` `run` and `snapshot` | `CLI` / console | `COMMAND`, `EXECUTION`, `LIFECYCLE`, `QUERY` | Engine/Runtime authorities and configured persistence | CLI → `OnlyEngine` → application runner/Engine lifecycle → Runtime factory → Runtime | `MIGRATE TO PRODUCT API` / K6, seal K8 | Debt: direct CLI Engine control. Exact entrypoint and construction site frozen. |
| K0-S003 | `src/onlyalpha/cli.py` `scenario validate/run` | `OPERATOR`, `TEST` / console subcommand | `TEST_COMPOSITION`, `EXECUTION` | Scenario artifact plus Engine-owned test execution facts | CLI → parser/planner → `OnlyMarketScenarioRunner` → Engine → artifact | `OPERATOR / INFRASTRUCTURE ONLY` / K6 review | Not a Product Control Plane. Constructor site frozen. |
| K0-S004 | `src/onlyalpha/cli.py` `operations status/run` | `OPERATOR` / console subcommand | `PERSISTENCE_READ`, `QUERY` | PostgreSQL Research Run/Attempt/Worker operational authority, read-only | CLI → operations store → diagnostic service → JSON projection | `OPERATOR / INFRASTRUCTURE ONLY` / retained | No business mutation. Entrypoint surface frozen. |
| K0-S005 | `pyproject.toml: onlyalpha-research-worker`; `src/onlyalpha/research/worker_main.py` | `WORKER`, `INFRASTRUCTURE` / console | `EXECUTION`, `PERSISTENCE_WRITE`, `RECOVERY`, `RECONCILIATION` | PostgreSQL Run/Attempt/lease authority; immutable Research semantic authorities | worker main → scheduler/claim → fenced Worker → Engine/Research Runtime → semantic commit → Run/Attempt convergence | `OPERATOR / INFRASTRUCTURE ONLY` / retained | Execution agent, not Product or Strategy authority. Entrypoint and forbidden capabilities frozen. |
| K0-S006 | `packages/api/onlyalpha-api/pyproject.toml: onlyalpha-api`; `onlyalpha_api/main.py` | `INFRASTRUCTURE` / HTTP composition executable | `QUERY`, `COMMAND`, `PERSISTENCE_READ`, `PERSISTENCE_WRITE` | Application services; PostgreSQL operational store through composition | executable → verified composition → FastAPI app → routes → application services | `MIGRATE TO PRODUCT API` / generalize in K3/K4 | Existing Research Product API seed; not a second HTTP stack. Entrypoint set frozen. |
| K0-S007 | `packages/api/onlyalpha-api/pyproject.toml: onlyalpha-artifact-api`; `onlyalpha_api/artifact_main.py` | `INFRASTRUCTURE` / portable HTTP executable | `QUERY`, `SEMANTIC_READ` | verified portable Research Artifact only | executable → Artifact reader → query service → read-only routes | `MIGRATE TO PRODUCT API` / govern in K3/K4 | No PostgreSQL/Run dependency. Entrypoint set and existing Research boundary tests guard it. |
| K0-S008 | `packages/provider/onlyalpha-plugin-miniqmt/pyproject.toml: onlyalpha-miniqmt`; `packages/provider/onlyalpha-plugin-tushare/pyproject.toml: onlyalpha-tushare` | `OPERATOR`, `INFRASTRUCTURE` / doctor consoles | `QUERY` | provider environment/capability diagnostics only | console → provider-local doctor → environment report | `OPERATOR / INFRASTRUCTURE ONLY` / retained | Two additional audited console surfaces; exact entrypoint set frozen. |
| K0-S009 | `apps/onlyalpha-web/src/api/research/*`; feature callers under `apps/onlyalpha-web/src/features/research/*` | `WEB` / browser | `QUERY`, `COMMAND` | HTTP Research API only; no local durable authority | Web → generated/validated HTTP client → Research routes | `MIGRATE TO PRODUCT API` / retain and govern K3/K4/K6 | Already HTTP-only. TS import/symbol guard forbids Kernel mutation capability. |
| K0-S010 | `onlyalpha_api/research/run_routes.py`: `POST /api/v2/research/runs`, `POST .../cancellation` | `WEB`, `AGENT`, `AUTOMATION` / HTTP | `COMMAND`, `MUTATION` | `OnlyResearchCommandService`; PostgreSQL Research Run/submission mapping authority | route DTO → command service → admission/CAS → PostgreSQL commit | `MIGRATE TO PRODUCT API` / retain in K2/K3 | Route owns no Store/Worker/Engine/Strategy writer. Route ownership guard. |
| K0-S011 | `onlyalpha_api/research/run_routes.py`: `GET /api/v2/research/runs...` | `WEB`, `AGENT`, `AUTOMATION` / HTTP | `QUERY`, `PERSISTENCE_READ` | PostgreSQL Research Run projection | route → `OnlyResearchRunQueryService` → command-store read port | `MIGRATE TO PRODUCT API` / retain in K2/K3 | Read does not transition state. Route ownership guard. |
| K0-S012 | `onlyalpha_api/research/definition_routes.py` catalog and `/definitions/resolve` | `WEB`, `AGENT`, `AUTOMATION` / HTTP | `QUERY` | existing Calculation/Universe/Definition resolution authorities; no durable write | route → discovery/definition API service → resolver/registries | `MIGRATE TO PRODUCT API` / retain in K3/K4 | Deterministic projection/resolution, not semantic publication. Route ownership guard. |
| K0-S013 | `onlyalpha_api/research/routes.py` `/api/v2/research/artifacts/*` | `WEB`, `AGENT`, `AUTOMATION` / HTTP | `QUERY`, `SEMANTIC_READ` | verified portable Research Artifact | route → `OnlyResearchQueryService` → Artifact reader | `MIGRATE TO PRODUCT API` / retain in K3/K4 | Read-only portable boundary. Route ownership and existing query boundary guards. |
| K0-S014 | `onlyalpha_api/health.py` `/health/live`, `/health/ready` | `INFRASTRUCTURE` / HTTP | `QUERY` | process liveness and fail-closed readiness projection | route → readiness probe → schema/deployment/root verification | `MIGRATE TO PRODUCT API` / generalize in K1/K3 | No migration or semantic repair. Transport/ownership guards. |
| K0-S015 | `src/onlyalpha/application/engine_runner.py` | `INTERNAL_APPLICATION` | `EXECUTION`, `LIFECYCLE` | Engine-owned Runtime lifecycle and results | internal caller → runner → Engine run/start/wait/stop/close | `KEEP INTERNAL` / compose behind K1/K2 later | Current internal execution adapter, not target external contract. Direct construction freeze prevents new callers. |
| K0-S016 | `application/engine_inspection.py`; `runtime_inspection.py`; `stop_controller.py` | `INTERNAL_APPLICATION`, `OPERATOR` | `QUERY`, `LIFECYCLE` | read-only Engine/Runtime projections; process signal state | application → inspection views or stop request | `KEEP INTERNAL` / K1 composition | No durable business authority. Transport neutrality guard. |
| K0-S017 | `research/command/service.py` | `INTERNAL_APPLICATION` | `COMMAND`, `MUTATION`, `PERSISTENCE_WRITE` | sole Research submission/cancellation application path; PostgreSQL Run authority | command → admission or revision CAS → command-store port | `KEEP INTERNAL` / adapt in K2 | HTTP route delegates; existing command boundary and route ownership guards. |
| K0-S018 | `research/command/query.py`; `research/query/*` | `INTERNAL_APPLICATION` | `QUERY`, `PERSISTENCE_READ`, `SEMANTIC_READ` | PostgreSQL Run projection or verified Artifact authority | query service → narrow reader/store port → projection | `KEEP INTERNAL` / adapt in K2 | Query has no hidden transition. Transport neutrality and existing Research query tests. |
| K0-S019 | `research/execution/worker.py`; `research/execution/scheduler.py`; `research/execution/reconciliation.py` | `WORKER` | `EXECUTION`, `PERSISTENCE_WRITE`, `RECOVERY`, `RECONCILIATION`, `SEMANTIC_PUBLICATION` | PostgreSQL Attempt/lease; existing immutable Calculation/Statistics/Result/Artifact stores through Research Runtime | claim → fenced execution → Runtime → verified commit/reuse → fenced finalization | `OPERATOR / INFRASTRUCTURE ONLY` / retained | Worker cannot Freeze/Promote or publish Strategy. Worker authority guard. |
| K0-S020 | `application/strategy_authority.py: OnlyStrategyFreezeApplicationService`; `strategy/freeze.py` | `INTERNAL_APPLICATION` | `COMMAND`, `SEMANTIC_PUBLICATION`, `PERSISTENCE_WRITE` | sole Candidate→Strategy Freeze; immutable Freeze relation + frozen Revision semantic authority, PostgreSQL projection | exact references → verified evidence/admission → relation/revision publication → projection | `KEEP INTERNAL` / expose only through K2/K3 | Unique Strategy publisher owner. Existing P9 gate plus K0 exact capability allowlist. |
| K0-S021 | `application/strategy_authority.py: OnlyStrategyPromotionApplicationService`; `strategy/promotion.py` | `INTERNAL_APPLICATION` | `COMMAND`, `SEMANTIC_PUBLICATION`, `PERSISTENCE_WRITE` | append-only Promotion chain in PostgreSQL operational/evidence authority | exact Strategy/evidence intent → predecessor verification → append record | `KEEP INTERNAL` / expose only through K2/K3 | No mutable status and no Runtime/Worker access. Worker/route guards. |
| K0-S022 | `application/strategy_authority.py: OnlyStrategyFreezeProjectionReconciliationApplicationService`; `strategy/freeze.py: OnlyStrategyFreezeProjectionReconciler` | `OPERATOR`, `INTERNAL_APPLICATION` | `RECONCILIATION`, `SEMANTIC_READ`, `PERSISTENCE_WRITE` | immutable Strategy truth read; PostgreSQL projection write | exact fingerprint → verified Revision/relations → idempotent projection convergence | `OPERATOR / INFRASTRUCTURE ONLY` / explicit recovery composition in K1/K5 | Projection cannot repair semantic truth and is not a generic Product Command. Route/worker guards. |
| K0-S023 | `application/calculation_equivalence.py` | `INTERNAL_APPLICATION` | `COMMAND`, `SEMANTIC_PUBLICATION` | exact-node system-owned Equivalence Evidence V2 store | node intent → actual RESEARCH/TRADING execution → exact comparison → immutable evidence | `KEEP INTERNAL` / future K2 decision | Caller cannot inject runner/corpus/output. Existing P9 authority tests. |
| K0-S024 | `persistence/postgres/{research_run_store,research_execution_store,research_deployment_store,research_operations_store,strategy_store,migration}.py` | `INFRASTRUCTURE` / importable adapters | `PERSISTENCE_READ`, `PERSISTENCE_WRITE`, `MIGRATION` | PostgreSQL operational authorities and projections only | application/operator composition → narrow adapter → transaction/CAS/fencing | `KEEP INTERNAL` / K1/K2 composition | API composition root may construct adapters; routes may not. Route ownership guard. |
| K0-S025 | `research/dataset/parquet_store.py`; `research/calculation/result_store.py`; `research/evaluation/result_store.py`; `research/result/result_store.py`; `research/artifact/{store,scientific_store}.py`; `research/calculation/execution_evidence.py`; `calculation/equivalence.py`; `strategy/store.py` | `INTERNAL_APPLICATION`, `RUNTIME` / importable internals | `SEMANTIC_READ`, `SEMANTIC_PUBLICATION` | distinct immutable content-addressed semantic authorities | owning materializer/executor/Freeze → staged verified commit → verified load | `KEEP INTERNAL` / K1/K2 capability composition | No universal writer; Strategy publisher remains private and Freeze-owned. K0 ownership and existing semantic boundary tests. |
| K0-S026 | `scripts/database.py` | `OPERATOR`, `INFRASTRUCTURE` / explicit script | `MIGRATION`, `BACKUP_RESTORE`, `PERSISTENCE_READ`, `PERSISTENCE_WRITE` | PostgreSQL migration/deployment binding/backup authorities and local semantic root initialization | operator → explicit command → compatibility/migration/backup/restore authority | `OPERATOR / INFRASTRUCTURE ONLY` / retained | Never invoked by application startup; not a Product API. Inventory and report freeze. |
| K0-S027 | `runtime/backtest/factory.py`; `runtime/research/factory.py`; `runtime/sim/factory.py`; `engine/*`; `cluster/factory.py` | `RUNTIME`, `INTERNAL_APPLICATION` | `TEST_COMPOSITION`, `EXECUTION`, `LIFECYCLE`, `RECOVERY` | Runtime-owned mutable authorities and configured durable stores | Engine plan → factory → Runtime → Kernel/Research workload | `KEEP INTERNAL` / compose behind K1 | Exact direct Runtime construction sites frozen; no current `OnlyLiveRuntime(...)` construction. |
| K0-S028 | `src/onlyalpha/scenario/runner.py` | `TEST`, `OPERATOR` / importable tooling | `TEST_COMPOSITION`, `EXECUTION` | Engine-owned test facts and immutable scenario artifact | scenario → deterministic plan → Engine → assertions/artifact | `OPERATOR / INFRASTRUCTURE ONLY` / K6 review | Not promoted to Product Control Plane. Constructor site frozen. |
| K0-S029 | `examples/committed_execution_report.py` | `EXAMPLE`, `PUBLIC_PYTHON` | `EXECUTION`, `LIFECYCLE` | Engine/Runtime execution and example output | example → direct Engine → run → report | `MIGRATE TO PRODUCT API` / K6 | Debt: external-style direct Engine example. Exact construction site frozen. |
| K0-S030 | `scripts/regenerate_recovery_baselines.py`; `scripts/regenerate_result_fixtures.py` | `TEST`, `AUTOMATION` | `TEST_COMPOSITION`, `EXECUTION`, `PERSISTENCE_WRITE` | generated test baselines/fixtures from Engine authority | maintenance script → Engine → deterministic fixture generation | `TEST ONLY` / retained | Exact construction sites frozen; not product entrypoints. |
| K0-S031 | `tests/**`; `tests/fixtures/**`; `tests/integration_demo/**`; `onlyalpha.plugin.testing` | `TEST` | `TEST_COMPOSITION` | isolated test doubles, Engine/Runtime composition, fixtures | pytest → test composition → asserted authority behavior | `TEST ONLY` / retained | Excluded from product constructor allowlist; existing architecture/product gates prevent leakage. |

## Unique mutation ownership

| Fact or transition | Sole writer/owner | Read-only consumers | Failure boundary and recovery convergence |
|---|---|---|---|
| Research Run submission/cancellation | `OnlyResearchCommandService` through PostgreSQL command/run store | HTTP/Web/operator queries | PostgreSQL transaction/CAS; retry replays same command or conflicts, recovery reads Run authority. |
| Research Attempt/lease/finalization | PostgreSQL execution store under Scheduler/Worker fencing | diagnostics/readiness | exact Attempt/Worker/lease fence; expiry creates a new Attempt and semantic-fact-first reconciliation converges terminal state. |
| Research semantic results/evidence | owning Dataset/Calculation/Statistics/Result/Artifact executor/materializer and immutable store | Worker reuse, Query, Web | staged commit and verified load; corruption fails closed, deterministic re-entry reuses complete facts. |
| Candidate → Strategy | `OnlyStrategyFreezeApplicationService`/Freeze Service with private publisher | Runtime read-only Strategy reader; query/projection | immutable Freeze relation precedes readable Revision; partial/corrupt publication is non-executable; PostgreSQL projection reconciles from semantic truth. |
| Strategy Promotion | `OnlyStrategyPromotionApplicationService`/Promotion Service | product queries and later deployment admission | predecessor-chain append; conflicts fail closed, no mutable status repair. |
| Strategy projection convergence | Freeze Projection Reconciler | operator/query plane | verified semantic truth → idempotent PostgreSQL projection; projection never repairs semantic authority. |
| Runtime mutable trading state | each isolated Trading Runtime/Kernel | Engine inspection/result projection | checkpoint/durable execution facts; supported recovery converges to continuous-run semantics. |
| Database schema/deployment/backup | explicit `scripts/database.py` operator path | readiness/status probes | startup is compatibility-only; migration and restore are explicit and fail closed. |

Thus `UNKNOWN MUTATION AUTHORITY = 0`. API routes and Web submit intent or query projections; they do not own these writers.

## Allowed known debt set

Only these three K0 migration debts may remain without constituting a new violation:

1. public framework exports permit direct Engine/Runtime/Cluster product control (`K0-S001`);
2. `onlyalpha run/snapshot` directly construct and control Engine (`K0-S002`);
3. the committed-execution example demonstrates direct Engine product use (`K0-S029`).

Equivalent new debt is forbidden. The console-entrypoint set, top-level export set, and all non-test direct Engine/Runtime construction locations are exact allowlists. Any addition fails CI until this architecture contract is explicitly reviewed and updated.

## P9.0 invariants and K1 exclusion

- `strategy_fingerprint` remains the sole Strategy semantic/executable identity.
- Candidate remains non-executable; Freeze remains the sole Candidate→Strategy transition.
- Runtime/Cluster retain only `OnlyStrategyRevisionReader` capability.
- the private frozen-Strategy publisher remains confined to `strategy/store.py`, `strategy/freeze.py`, and `application/strategy_authority.py`.
- Promotion remains append-only and predecessor-ordered.
- Research Execution Evidence and Equivalence Evidence semantics are unchanged.
- PostgreSQL Strategy rows remain operational/query projections of immutable semantic truth.
- Production Python behavior, persistence schema, semantic identity, and public HTTP routes changed by K0: **none**.
- Kernel Host/lifecycle/dispatcher/supervisor/recovery coordinator implemented by K0: **none**.

## Mechanical guards

- `tests/architecture/test_p9_k0_product_surfaces.py`: exact console entrypoints, top-level exports, and direct Engine/Runtime constructor locations.
- `tests/architecture/test_p9_k0_transport_boundary.py`: Core transport neutrality and Web HTTP-only behavior.
- `tests/architecture/test_p9_k0_authority_ownership.py`: thin API routes, Worker execution-only role, and exact Strategy publisher ownership.
- Existing `test_interface_uniqueness.py`, `test_research_command_boundaries.py`, and `test_p9_strategy_authority.py` remain authoritative and were not weakened.

## Local verification

```text
Targeted K0 + required existing regressions: 36 passed
Complete tests/architecture suite:           376 passed
import-linter contracts:                     3 kept, 0 broken
ruff check .:                                PASS
ruff format --check (new tests):             PASS
git diff --check:                            PASS
```

At the original K0 audit, the literal repository-root marker command aborted during global collection before marker selection because unrelated test directories contain duplicate non-package module names (`test_execution.py` and `test_historical.py`). The path-scoped run avoided that collection ambiguity and executed all 376 architecture tests successfully. K0.1 supersedes the ad-hoc invocation with the canonical lane below. No skip, xfail, retry, relaxed assertion, or test deletion was used.

The optional Semgrep self-test was not part of the K0 required gate and could not be executed because the local environment has no `semgrep` executable. The only Semgrep fixture change is Ruff's standard-library import ordering; all `ruleid`/`ok` annotations and tested expressions remain byte-for-byte unchanged.

## Final verdict

All 31 surfaces have an exact location, actor, capability set, authority boundary, target classification, and migration/retention stage. Unclassified surfaces and unknown mutation authorities are both zero. Existing debt is finite and mechanically frozen. P9.K.0 verdict: **COMPLETE**.

## P9.K.0.1 Architecture Freeze Guard Closure

- Closure base SHA: `a67fd3a7e8388e32fdd77269b73f711f439586bf`
- K0.1 implementation subject: `aeced4b4e198ed2c3035eea5ab04a46785b00a26`
- Closure date: `2026-08-25`
- Scope: mechanical guard closure only; production semantic code, HTTP contract, and database schema are unchanged

K0.1 upgrades the original inventory into a fail-closed executable contract:

- root-package AST binding inspection freezes actual public/reachable names, including imports omitted from `__all__`, with explicit `PUBLIC CONTRACT`, `PUBLIC VALUE / READ-ONLY`, and `KNOWN MIGRATION DEBT` categories;
- Engine/Runtime construction detection resolves import ownership and aliases before comparing the exact classified construction-site allowlist;
- the exact current CLI `onlyalpha` capability import set is frozen, while the existing read-only operational diagnostics remain legal;
- HTTP route ownership is detected from FastAPI route decorators or `add_api_route`, independent of filenames, and the exact current route-module set is frozen;
- `worker_main.py` plus every module under `research/execution/` is checked as one execution-agent boundary without removing its legal Research execution/publication capabilities;
- K0-S022 is classified only as `OPERATOR / INFRASTRUCTURE ONLY`, never as a generic Product Command;
- the sole official repository Architecture Gate is:

```bash
uv run python scripts/test_suite.py architecture
```

This lane scopes collection to `tests/architecture`, uses importlib collection, and therefore removes the repository-wide marker ambiguity without renaming unrelated tests. K1 remains not started, and P9.1+ remains blocked until P9.K closure.

K0.1 local deterministic verification:

```text
Required targeted architecture files + lane contract: 65 passed
Complete canonical Architecture Gate:                  384 passed
import-linter contracts:                               3 kept, 0 broken
ruff check .:                                          PASS
ruff format --check (changed Python):                  PASS
git diff --check:                                      PASS
```

Impact-aware verification was also attempted because `scripts/test_suite.py` is verification infrastructure. Its first 20 gates passed,
including repository static checks, Core/API mypy, version sync, Web static/unit/build/E2E, and the reached canonical lanes. The next
`research-product-closure` gate stopped with 8 passed and 11 setup errors because `ONLYALPHA_TEST_POSTGRES_DSN` is not configured. That
real-PostgreSQL certification lane is **NOT EXECUTED / ENVIRONMENT BLOCKED**, not PASS, and is outside the K0.1 required gate.

Remote certification for K0.1 was **NOT RUN / NOT REQUIRED**. The local deterministic results above are not represented as remote
certification.

## P9.K.0.1.1 Capability Guard Completeness

- Implementation subject: K0.1 immutable commit `aeced4b4e198ed2c3035eea5ab04a46785b00a26`
- Guard closure base: `aeced4b4e198ed2c3035eea5ab04a46785b00a26`
- Closure date: `2026-08-25`
- Local verification: canonical Architecture Gate, import-linter, Ruff, changed-Python format check, and diff check all **PASS**
- Remaining unknown capability paths: `0`
- P9.0 semantic changes: `0`
- HTTP contract changes: `0`
- Database schema changes: `0`
- Production behavior changes: `0`
- K1 implementation state: **NOT STARTED**
- Remote certification: **NOT RUN / NOT REQUIRED**
- Verdict: **COMPLETE / LOCAL DETERMINISTIC GATES PASS**
- Next: **P9.K.1 — Kernel Host & Lifecycle**

K0.1.1 local deterministic verification:

```text
Required targeted architecture files: 72 passed
Complete canonical Architecture Gate: 391 passed
import-linter contracts:              3 kept, 0 broken
ruff check .:                         PASS
ruff format --check (changed Python): PASS
git diff --check:                     PASS
```

K0.1.1 closes capability acquisition rather than adding product behavior:

- one shared canonical scanner records both `ast.Import` module capability and alias-independent `ast.ImportFrom` symbol capability;
- the CLI `onlyalpha.*` set is an exact allowlist, so an ordinary module import or symbol alias changes the frozen set;
- each filename-independently discovered route module has an exact approved `onlyalpha.*` dependency set; unknown dependencies fail closed;
- `worker_main.py` and the full recursive `research/execution/**/*.py` subtree remain execution agents without Strategy Product authority;
- every non-test Engine/Runtime constructor capability import owner is exact and classified, in addition to the existing alias-aware
  constructor-call guard;
- the K0.1 evidence now names its existing immutable implementation subject instead of a stale pre-commit `WORKTREE` placeholder.

No `src/onlyalpha/kernel/` implementation, Product API endpoint, Strategy/Research/Runtime semantic change, persistence migration, or
production source modification is part of K0.1.1.

## P9.K.0.1.2 — Authority Guard Soundness & K1 Preflight Closure

- Baseline SHA: `45ba7eb4a2dc8b4d3f5a7d541ac573d26b135748`
- Implementation subject: `WORKTREE`
- Closure date: `2026-08-25`
- Relative import bypass: **CLOSED**
- Worker broad-package bypass: **CLOSED**
- Wildcard constructor bypass: **CLOSED**
- API helper authority bypass: **CLOSED**
- Unknown capability crossings: `0`
- Canonical Architecture Gate in normal CI: **PASS**
- P9.0 semantic changes: `0`
- HTTP contract changes: `0`
- Database schema changes: `0`
- Production behavior changes: `0`
- K1 implementation: **NOT STARTED**

The canonical scanner now derives module identity from each guarded repository path, resolves relative imports at every supported depth,
and raises on an unresolved guarded relative import. Worker guards reject the mixed `onlyalpha.application` aggregator, Strategy
Freeze/Promotion namespaces, future `onlyalpha.kernel`, LIVE/Broker mutation, migration, and Strategy projection-writing capabilities
while retaining the exact current Engine/Research execution dependencies. Constructor-owner metadata derives the protected module set;
wildcard import from any such namespace fails closed, while explicit aliases preserve the same constructor identity.

Every Python module in `onlyalpha_api` has an explicit role, and every direct API→Core crossing file has an exact canonical capability
set. A new or changed crossing therefore fails independently of filename or route decoration. Composition roots remain exact inventories,
not unrestricted exceptions; the current Definition Resolver adapter and all current routes remain admitted.

Real PostgreSQL root-cause classification: **E — test-lane baseline defect**. Migration `0011_p9_0_freeze_projection_convergence` was
already valid production/schema authority, but three migration-history assertions and the checksum-tamper fixture still ended at M10.
That made the real database appear `AHEAD`, prevented the M11 tamper case, and left deterministic Strategy projection conflict/unbound
branches outside the formal coverage owner. The correction changes only PostgreSQL tests: the exact baseline now includes M11 and the
missing fail-closed projection branches are exercised. No persistence implementation or migration changed. A local preflight first
exposed a separate environment mismatch (host `pg_dump` 14 versus required major 16); final proof used PostgreSQL server/client 16.10.

Local deterministic verification:

```text
Targeted guard and lane-contract tests: 64 passed
Canonical Architecture Gate:           413 passed
Strategy lane:                           96 passed
Research Execution lane:                 49 passed
Research Command lane:                   42 passed
Research Product Closure (PostgreSQL):    19 passed
Research PostgreSQL coverage:             92 passed; total 82.19%, lines 84.58%, branches 71.25%
import-linter contracts:                   3 kept, 0 broken
ruff check .:                              PASS
ruff format --check (changed Python):      PASS
git diff --check:                          PASS
```

Remote quality CI and exact-final-SHA certification were not run. Verdict: **COMPLETE / LOCAL DETERMINISTIC GATES PASS**. Next:
**P9.K.1 — Kernel Host & Lifecycle**.
