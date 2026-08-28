# P9.K.8 Seal Kernel — Implementation and Task-Gate Evidence

- Date: 2026-08-28
- Branch: `master`
- `TASK_BASE_SHA`: `f74ddd273f600ef076b459a500b6073d2ab0cb78`
- Implementation/worktree: `f74ddd273f600ef076b459a500b6073d2ab0cb78 + dirty K8 worktree`
- Expected release version: `0.9.8`
- Gate: P9.K.8 Task Gate; no Final-SHA Certification claim
- Governing design: ADR 0101, `docs/p9_k_stateful_kernel_protocol_boundary.md`, K8 frozen Prompt

## Task contract

Goal: remove every remaining supported external Product mutation bypass so the Product Control Plane is the sole supported external
mutation authority, while preserving legitimate internal, operator, scenario and composition paths.

Modification scope: root Python exports and broad constructor aggregators, root CLI, standalone Artifact compatibility executable/app,
K0/K6 architecture inventories, permanent K8 negative architecture gates, current documentation, release version and project state.

Impact scope: public Python/CLI/package metadata, API package composition and tests, architecture lane, client/Web boundary contracts,
OpenAPI/client freshness, import boundaries, typing/static/build/version/project-state checks.

Expansion triggers: any Product OpenAPI, Strategy/P9.0, Research authority, Gateway Proto, database migration/schema, semantic fingerprint,
business command/query, Runtime or execution-semantic delta. Such a delta must be explained and is not expected.

Out of scope: new Product commands/routes, QMT/CTP/Binance, Broker submission, LIVE, Portfolio/Risk redesign, persistence authority,
generic dependency injection, Engine/Runtime rewrites, mass private-package moves, Phase Gate and Final-SHA Certification.

## Pre-edit invariant matrix

| Invariant | Current evidence | Required change | Required proof |
|---|---|---|---|
| INV-K8-01 unique Product mutation path | K6 Product client/API exists; K0 records legacy bypasses | remove every supported external bypass | K0/K6/K8 architecture gates |
| INV-K8-02 root Python seal | root binds 13 migration-debt constructors | remove exact debt bindings/exports | import and AST public-surface assertions |
| INV-K8-03 root Product CLI seal | `run`/`snapshot` construct `OnlyEngine` | remove commands and Engine path | parser/help plus AST absence assertions |
| INV-K8-04 Product CLI authority | `onlyalpha-client` is K6 authority | preserve unchanged | client package/entrypoint tests |
| INV-K8-05 external client firewall | K6 client/Web guards pass | preserve and strengthen final seal | metadata/import AST checks |
| INV-K8-06 no local Product fallback | K6 transport failures fail closed | preserve zero fallback capability | client source/behavior checks |
| INV-K8-07 narrow HTTP route capability | routes dispatch through Product boundary | add permanent route capability firewall | decorator-discovered route AST gate |
| INV-K8-08 composition ownership | `main.py` explicitly wires Kernel/stores | preserve composition exception | exact API role/crossing inventory |
| INV-K8-09 constructor ownership | K0 has one Product CLI owner and root public holder | remove Product owners; retain internal/test/operator/composition | exact call/import owner inventory |
| INV-K8-10 compatibility closure | standalone `onlyalpha-artifact-api` is K8 debt; no active consumer evidence | remove executable and standalone app composition; retain main API routes | entrypoint/module/factory absence assertions |
| INV-K8-11 semantic identity preservation | no K8 semantic change required | do not touch identity sources | protected-path Git diff proof |
| INV-K8-12 determinism preservation | task is surface subtraction | introduce no implicit input | source/diff review and architecture gate |
| INV-K8-13 persistence preservation | no persistence change required | add zero schema/table/authority | migration/path diff proof |
| INV-K8-14 P9.0 preservation | Strategy/Research semantics are outside scope | no protected semantic edits | protected-path diff proof |
| INV-K8-15 fail-closed legacy removal | legacy paths currently execute | remove without alias/proxy/fallback | negative import/CLI/entrypoint tests |
| INV-K8-16 zero migration debt | K0/K6 explicitly record K8 debt | transition machine inventories to zero while preserving historical reports | `legacy_debts == []`, K6 debt counts zero |

## Implementation evidence

### Removed Product bypasses

- removed all 13 historical root `onlyalpha` Engine/Runtime/Cluster migration-debt bindings and exports;
- removed concrete Engine/Runtime/Cluster mutation constructors from the broad `onlyalpha.engine/runtime/cluster` aggregators;
- removed root Product `onlyalpha run` and `onlyalpha snapshot` without alias, proxy, forwarding or local fallback;
- removed `onlyalpha-artifact-api`, `artifact_main.py` and `create_artifact_query_app` standalone composition;
- preserved Artifact query routes in the main `onlyalpha-api` Product app;
- transitioned K0 `legacy_debts`, K6 `LEGACY_K8_TARGET` and all K6 `k8_debt` values to zero.

### Retained legitimate owners

- Research Worker and internal Engine application adapters use `onlyalpha.engine.engine.OnlyEngine` directly;
- Scenario, deterministic fixture regeneration, internal examples and tests retain explicit concrete composition;
- root `scenario` remains `TEST / SCENARIO`; root `operations` and provider/worker tooling remain `OPERATOR / INFRASTRUCTURE`;
- `onlyalpha-api/main.py` remains the explicit composition root allowed to wire PostgreSQL, Kernel, Product Boundary and API app;
- root/broad aggregators retain stable non-mutation values, with lazy exports used only to avoid import-order side effects.

The K8 subtraction exposed a pre-existing import-order dependency in `runtime.checkpoint`: importing `checkpoint.codec` executed the
package initializer, which eagerly imported `checkpoint.service` back into the partially initialized persistence Store. The minimal fix
makes the existing `OnlyRuntimeCheckpointService` package export lazy. It changes no checkpoint model, schema, capture, restore,
persistence or recovery behavior; focused checkpoint tests and the Architecture lane pass.

## Final invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K8-01 unique Product mutation path | PASS | zero Product constructor/CLI/HTTP compatibility bypasses; Product Control Plane retained |
| INV-K8-02 root Python seal | PASS | historical debt set remains exact at 13; current root debt set is empty |
| INV-K8-03 root Product CLI seal | PASS | root parser/source has no Product `run/snapshot` or Engine capability |
| INV-K8-04 Product CLI authority | PASS | one `onlyalpha-client` entrypoint/package; client tests pass |
| INV-K8-05 external client firewall | PASS | client metadata/import AST and Web source firewall pass |
| INV-K8-06 no local Product fallback | PASS | K6/K8 source and transport behavior checks pass |
| INV-K8-07 narrow HTTP route capability | PASS | decorator-discovered route AST gate; Run mutation uses two Product dispatches |
| INV-K8-08 composition ownership | PASS | exact `main.py` capability inventory and one Kernel Host composition retained |
| INV-K8-09 constructor ownership | PASS | exact owners are only internal/test/operator/composition; Product owner count zero |
| INV-K8-10 compatibility closure | PASS | entrypoint/module/factory absent; main Artifact routes and OpenAPI unchanged |
| INV-K8-11 semantic identity preservation | PASS | Strategy/P9.0 protected source diff empty |
| INV-K8-12 determinism preservation | PASS | no clock/random/order/environment semantic input added |
| INV-K8-13 persistence preservation | PASS | migration/schema/table/authority diff empty |
| INV-K8-14 P9.0 preservation | PASS | Strategy authority and semantics source diff empty |
| INV-K8-15 fail-closed legacy removal | PASS | no compatibility shim, magic import or fallback exists |
| INV-K8-16 zero migration debt | PASS | K0/K6/K8 machine assertions all report zero debt |

## Semantic delta proof

```text
Product OpenAPI semantic delta:      0 files / canonical SHA unchanged
Strategy/P9.0 semantic source delta: 0 files
Research authority delta:           0 (Worker change is import ownership only)
Gateway Proto semantic delta:        0 files
database migration/schema delta:     0 files
semantic fingerprint delta:          0
new Product endpoint/command/query:  0
new durable authority/table/receipt: 0
```

Canonical OpenAPI SHA256 remains `6a66fde2dba23fe6770bc5b27031337d95bf4b987b0ca946903c1a7c89b95d1e` and generated Python
projection SHA256 remains `33f8dc35c843e5c375f5f6664286d101f85b0d835f2f5647ea3bffd68ca39fde`.

## Verification evidence

Local PASS:

```text
exact K0/K6/K8 architecture targets: 30 passed
canonical Architecture lane:         507 passed
API + Python client packages:          41 passed
Research Command canonical lane:       56 passed
checkpoint/K8/API focused regression:  34 passed
OpenAPI contract/client freshness:      PASS
Web static contract/lint/format/types:  PASS
Import Linter:                           3 kept, 0 broken; 655 files
Ruff check / format:                    PASS; 1495 files
Mypy Core/API/client:                   PASS; 642 source files
budgeted static plan:                   PASS; 10/10 local commands
all-package source/wheel build:         PASS; 12 packages at 0.9.8
version graph:                          PASS; 0.9.8
project-state consistency:              PASS; K8 VERIFIED, P9.K CLOSED, P9.1 READY
git diff --check:                       PASS
```

The all-package build was offline and used the already cached declared Hatchling backend through temporary `PYTHONPATH`; it changed no
dependency or project source.

Budgeted impact verification returned exit code `3` (`LOCAL_PASS_CI_REQUIRED`) because public/verification-infrastructure and shared-test
changes select a 130-unit broad plan. Final manifest:
`test-results/verification/local-budget/20260828T063950Z-f74ddd273f60-27230/manifest.json`.

The manifest retains 31 deferred checks/lanes. Directly applicable version, Web static, Research Command, Architecture and all-package
build proof were executed separately and passed as recorded above. Remaining Web unit/build/E2E, Kernel/Strategy/Research bundles,
PostgreSQL, Core full, Recovery/Sim-Recovery, A-share and MiniQMT lanes remain **CI REQUIRED**; they are not represented as local or CI
PASS. Phase Gate and Final-SHA Certification were **NOT EXECUTED**.

## Reverse authority audit

```text
Can Web mutate without Product API?                     NO
Can Product Python client mutate without Product API?  NO
Can Product CLI mutate without Product API?            NO
Can root onlyalpha expose Engine mutation?              NO
Can root CLI directly construct Engine for Product use?NO
Can API route directly write business persistence?     NO
Can Gateway become a Product API?                      NO
Can client silently become local Kernel?               NO
Does any LEGACY_K8_TARGET remain?                       NO
Does any KNOWN_MIGRATION_DEBT remain?                   NO

Can internal/test composition still construct required internals? YES
Can composition root still wire stores/services/Kernel?           YES
Can operator/test tooling remain explicitly classified?           YES
```

## Convergent Task-Gate audit

- `AUDIT_BASE_SHA`: `f74ddd273f600ef076b459a500b6073d2ab0cb78`
- `AUDIT_HEAD_SHA`: `f74ddd273f600ef076b459a500b6073d2ab0cb78 + dirty K8 worktree`
- Scope: P9.K.8 Task Gate / Seal Kernel
- Previous K8 findings: none

```text
BLOCKER:    0
MAJOR:      0
MINOR:      0
SUGGESTION: 0
```

No frozen-design, uniqueness, determinism, dependency-direction, public-contract, fail-closed, persistence or recovery violation was
found in the K8 scope. The applicable Task-Gate evidence is sufficient; the broad budget-deferred plan remains explicit CI_REQUIRED and
is not misrepresented as PASS or Certification evidence.

Task Gate verdict: **GO**.

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
是否可进入下一阶段？ GO

P9.K.8 = TASK COMPLETE / VERIFIED
P9.K   = CLOSED
P9.1   = MAY START / IMPLEMENTATION READY
```
