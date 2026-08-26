# P9.K.1 Kernel Host & Lifecycle — Immutable Task Gate Evidence

- Date: 2026-08-26
- Task base SHA: `1c3be8823ba67c851b01e2c0c5ae93e39187f719`
- Initial K1 implementation SHA: `7950af055213506685de72eada13c3ebc8f57c51`
- K1 closure SHA: `80ca2027ca2e28d050c9b87326062ac52be60cfe`
- Evidence status: `P9.K.1 DONE / VERIFIED`
- Release mapping: P9.K.1 retains the current `0.9.0` P9 architecture line; `version_sync.py check` passes. This task does not claim or
  allocate the later P9.1 release number.

## Task Contract

Goal:

```text
ONE Product Kernel lifecycle authority
+ ONE closed deterministic transition graph
+ READY-only product mutation admission
+ ordered coordination over existing authorities
+ ZERO duplicated business truth
```

Modification scope was limited to the minimal Core Kernel package, existing Research API startup/readiness composition, the K0 authority
contract activation for C17, direct tests/architecture guards, one canonical `kernel` lane, and implementation evidence documentation.

Out of scope remained K2 Command/Query dispatch, K3 Product HTTP redesign, K7 remote protocol, Runtime supervision expansion, LIVE,
Broker reconciliation, database migration/schema, P9.0 identity/semantics, and Trading Kernel changes.

The P9.K.1 release mapping is frozen locally as `0.9.0`: P9.K is an inserted architecture sequence under P9, while the current Roadmap has
not assigned a new release number to K increments. No version graph bytes changed.

## Implemented Authority

`OnlyKernelLifecycle` owns:

```text
CREATED → BOOTING → VERIFYING → RECOVERING → READY → DRAINING → STOPPED
BOOTING / VERIFYING / RECOVERING / READY / DRAINING → FAILED with exact phase evidence
```

Arbitrary public state assignment and illegal/restart transitions fail closed. `OnlyKernelStatus.ready` is true exactly in `READY`.
`FAILED` remains process-live for diagnostic HTTP projection but is never ready. `STOPPED` is neither live nor ready.

`OnlyAlphaKernelHost` receives explicitly ordered immutable tuples of named narrow callables. It does not receive a service locator or
mutable service bag. It performs ordered boot, verification, recovery and drain, rejects re-entrant lifecycle misuse, closes mutation
admission before drain work, and records stable failure phase/step/exception type without publishing exception detail.

The existing Research API composition root is the only production Host constructor. Current ordered startup is:

```text
BOOTING
  calculation_registry_composition
VERIFYING
  postgres_server_compatibility
  research_product_scope
    schema status
    deployment namespace
    required roots
    calculation Registry
RECOVERING
  explicit empty current API-owned recovery sequence
READY
  Uvicorn product traffic
```

The Host consumes `OnlyPostgresSchemaVerifier` through the existing Research readiness capability. It never receives
`OnlyPostgresMigrationAuthority`. Existing namespace mismatch semantics remain diagnostic and fail closed: Host state is `FAILED`, the
HTTP process stays live, `/health/ready` preserves the stable subsystem reason, and every product route remains rejected.

The exported full-application Python composition factory now requires an `OnlyKernelResearchReadinessProjection`; callers can no longer
install a Research-only probe as an independent product mutation gate. This is a deliberate K1 composition-contract change. It does not
change any HTTP path, method, request/response DTO, status code, OpenAPI schema, or Research business semantic.

The closure migrated the remaining OpenAPI exporter composition to the same contract. Contract rendering starts and drains a real,
dependency-free `OnlyAlphaKernelHost`, supplies deterministic static Research readiness evidence, and introduces no fake or second
lifecycle authority. The C17 contract records the exporter as non-production certification tooling while retaining the API composition
root as the only production Host constructor.

## Invariant Result

| Invariant | Result | Evidence |
|---|---|---|
| One Product lifecycle authority | PASS | C17 identifies one production API constructor plus one explicitly non-production contract-tooling constructor of the same real Host |
| Deterministic transition graph | PASS | lifecycle table plus legal/illegal/failure transition tests |
| READY-only mutation gate | PASS | lifecycle and Host tests cover every state, drain ordering and FAILED/STOPPED rejection |
| VERIFYING is read-only | PASS | API owns `OnlyPostgresSchemaVerifier`; migration surface remains operator-only |
| Recovery uses existing authorities | PASS | Host only invokes ordered injected recoverers; current API scope declares none and creates no Store/snapshot |
| Product Kernel is not a god object | PASS | Kernel package contains lifecycle/host only and imports no domain authority |
| Product Kernel != Trading Kernel | PASS | architecture guard preserves `runtime/trading/kernel.py` and forbids Kernel Runtime imports |
| Explicit deterministic ordering | PASS | only ordered tuples are accepted; duplicate step names and non-tuples fail closed |
| Failure is explainable/fail-closed | PASS | stable phase, step and exception type; no low-level exception detail in lifecycle evidence |
| P9.0 identity/determinism | PASS | no Strategy/Research identity implementation changed; affected canonical lanes pass |

## Verification Evidence

Final successful commands and outcomes:

```text
uv run python scripts/export_research_openapi.py check
→ PASS; canonical OpenAPI SHA-256 c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e unchanged

uv run python scripts/web_suite.py static
→ PASS; generated TypeScript SHA-256 7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd unchanged

uv run python scripts/test_suite.py kernel
→ 27 passed

uv run python scripts/test_suite.py architecture
→ 448 passed

uv run python scripts/test_suite.py research-command
→ 44 passed

uv run python scripts/test_suite.py research-postgres --coverage
→ 92 passed; total coverage 82.39%; lines 84.79%; branches 71.25%

uv run python scripts/test_suite.py research-product-closure
→ 19 passed; 0 failed; 0 skipped; runner manifest exit_code 0

uv run lint-imports
→ 3 contracts kept; 0 broken

uv run ruff check .
→ PASS

uv run ruff format --check <changed Python files>
→ 21 files already formatted

uv run mypy src/onlyalpha
→ 614 source files; no issues

uv run mypy --config-file packages/api/onlyalpha-api/pyproject.toml packages/api/onlyalpha-api/src/onlyalpha_api scripts/export_research_openapi.py
→ 18 source files; no issues

uv run python scripts/version_sync.py check
→ workspace release graph consistent at 0.9.0

git diff --check
→ PASS
```

The PostgreSQL lanes above are the initial K1 implementation evidence at `7950af055213506685de72eada13c3ebc8f57c51`. The closure changed
no PostgreSQL semantic, migration, schema, Store, or recovery path, so impact-aware closure verification did not repeat those heavy lanes.
A pre-existing ignored local `env/` build tree was temporarily moved out of repository traversal for the canonical Architecture Gate and
restored unchanged afterward.

## Scope Confirmation

```text
P9.0 semantic changes:                  0
Database schema/migration changes:      0
Public HTTP route/DTO semantic changes: 0
Public Python composition API change:    Host readiness projection is mandatory for create_research_app
K2 implementation:                     NOT STARTED
K3 implementation:                     NOT STARTED
K7 implementation:                     NOT STARTED
Final-SHA Certification:               NOT EXECUTED
Remote exact-SHA relevant gates:       NOT RUN; closure commit remains local and was not pushed
```

The immutable closure SHA supports `DONE / VERIFIED` under the Task Gate. This report does not claim `CERTIFIED` or `ACCEPTED`.
