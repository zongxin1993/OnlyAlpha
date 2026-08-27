# P9.K — Stateful Kernel & Protocol Boundary

> Status: **FROZEN TARGET DESIGN / IMPLEMENTATION PLAN**
>
> Planning baseline: `0e6d3f0b3408f7125d8ce68460c9a7df62f86708`
>
> Governing ADR: [ADR 0101](adr/0101-stateful-kernel-and-protocol-boundary.md)
>
> Execution order: **P9.0 closure → P9.K → existing P9.1+ production vertical**
>
> Implementation progress: **K0 DONE / VERIFIED; K1 DONE / VERIFIED; K2 DONE / VERIFIED; K3 DONE / VERIFIED; K4 CLOSURE DONE / VERIFIED; K5 IMPLEMENTATION READY**

---

## 1. Why P9.K exists

P9.0 establishes the semantic authority foundation required for a production strategy product:

```text
Research
→ exact Execution Evidence
→ Candidate
→ unique Freeze
→ immutable Strategy Revision
→ one Strategy execution identity/path
→ append-only Promotion
```

The next risk is no longer Strategy identity itself. The next risk is allowing future Portfolio, Risk, Execution, Broker and LIVE capabilities to grow behind multiple product-operation surfaces.

The repository already contains both sides of that transition:

### Already aligned with the target

- P8 created durable Research Run operational authority in PostgreSQL;
- Research long-running execution is detached from request lifetime through Worker/Attempt/Lease semantics;
- `packages/api/onlyalpha-api` already uses FastAPI/Pydantic/Uvicorn;
- Research submission already requires UUID4 idempotency and returns `202 Accepted` only after durable commit;
- a generated OpenAPI Research v2 contract already exists;
- Web is already a client of server-owned Research semantics;
- P9.0 has explicit Application authorities and read/write capability separation.

### Still incompatible with the final product shape

- `src/onlyalpha/__init__.py` publicly exports Engine/Runtime/Cluster construction types;
- the root `onlyalpha` console entry directly constructs and runs `OnlyEngine`;
- CLI operational commands directly instantiate PostgreSQL operational stores;
- external Python code can still treat OnlyAlpha as a framework it controls rather than a long-running product Kernel;
- there is no single Kernel lifecycle/readiness authority spanning product Commands;
- the current API package is Research-specific rather than the unique product Control Plane;
- the future QMT Windows process boundary needs a machine-to-machine protocol distinct from browser/public HTTP.

P9.K closes those boundaries before P9.1+ introduces real-market and real-execution capabilities.

---

# 2. Target product identity

OnlyAlpha becomes a **Stateful Quant Kernel**.

This does not mean one giant mutable object and does not mean all state lives in RAM.

It means the product process owns authoritative business lifecycle and accepts externally requested state transitions through one explicit boundary.

```text
OnlyAlpha Stateful Kernel
=
Identity Authority
+
State Transition Authority
+
Lifecycle Authority
+
Execution Orchestration Authority
+
Recovery Authority
+
Persistence Coordination Authority
```

The Kernel is a modular monolith first. It may later supervise remote workers/gateways, but deployment topology must not change business authority semantics.

---

# 3. Target architecture

```text
                         PRODUCT EXTERNAL ACTORS

              Web        Agent       SDK       Automation
               │           │          │            │
               └───────────┴────┬─────┴────────────┘
                                │
                           HTTPS / JSON
                                │
                         OpenAPI Contract
                                │
                                ▼
                 ┌────────────────────────────┐
                 │ Product HTTP Adapter       │
                 │                            │
                 │ FastAPI                    │
                 │ API DTO / validation       │
                 │ auth / actor context       │
                 │ idempotency                │
                 │ HTTP/error mapping         │
                 └─────────────┬──────────────┘
                               │
                        Command / Query
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                 ONLYALPHA STATEFUL KERNEL                        │
│                                                                  │
│ Kernel Lifecycle                                                 │
│ Command Dispatcher / Query Dispatcher                            │
│ Runtime Supervisor                                               │
│ Recovery / Reconciliation Coordinator                            │
│                                                                  │
│ Research     Calculation      Strategy                           │
│ Portfolio    Risk             Execution                          │
│ Runtime      Deployment       Promotion                          │
│                                                                  │
│             Explicit typed deterministic calls                  │
│                                                                  │
│                      Kernel-defined Ports                        │
└───────────────┬──────────────────────────────┬───────────────────┘
                │                              │
                ▼                              ▼
         Persistence                     Infrastructure Plane
                │                              │
       ┌────────┴────────┐             ┌────────┼────────┐
       ▼                 ▼             ▼        ▼        ▼
Immutable Store      PostgreSQL     Binance    CTP      QMT
                                                       Gateway
```

---

# 4. Protocol architecture

P9.K deliberately rejects "one transport everywhere".

## 4.1 Product Control Plane

Use:

```text
HTTPS + JSON
OpenAPI contract
FastAPI initial adapter
```

Consumers:

```text
Web
Python SDK
Agent
Automation
optional CLI client
```

Responsibilities:

```text
submit Command intent
query facts/projections
authentication/authorization context
idempotency
public schema/versioning
```

FastAPI is not imported by the Kernel and does not own business rules.

## 4.2 Internal Kernel protocol

Use:

```text
strongly typed Python calls
constructor-injected capabilities
explicit call ordering
```

Do not replace deterministic business paths with HTTP or generic events.

Reference path:

```text
Canonical Observation
→ Strategy Execution
→ StrategyDecision
→ Portfolio
→ Risk
→ Order Intent
→ Execution
```

## 4.3 Remote Infrastructure Plane

Preferred future contract:

```text
Protobuf + gRPC
```

Target use cases:

```text
Linux Kernel ↔ Windows QMT Gateway
Kernel ↔ CTP Gateway
Kernel ↔ remote Trading Runtime when process isolation becomes necessary
```

This protocol is machine-to-machine infrastructure and is not a second product API.

## 4.4 Async Data Plane

Potential future contract:

```text
AsyncAPI
```

Potential transport after proven need:

```text
NATS / another explicit stream transport
```

Do not introduce it during P9.K merely for architecture style. Introduce a durable event transport only when one event genuinely requires independent cross-process/multi-consumer delivery.

---

# 5. Product authority rule

The central P9.K rule is:

> **External actors submit intent/reference; the Kernel produces authoritative facts.**

Examples:

## Research

Allowed external request:

```text
Create Research using exact Specification
```

Kernel owns:

```text
Run identity
Run lifecycle
Attempt/lease
terminal outcome
Result references
```

## Strategy Freeze

Allowed external request:

```text
Research Run reference
Candidate fingerprint
```

Kernel owns:

```text
historical evidence resolution
Admission
Strategy Revision construction
Freeze relation publication
```

The client may not submit a fabricated Strategy Revision/equivalence verdict/implementation binding.

## Promotion

Allowed:

```text
request transition using exact Strategy/evidence references
```

Kernel owns legal predecessor-chain validation and immutable Promotion fact creation.

## Future LIVE

Allowed:

```text
request deployment / permission transition
```

Kernel and external Broker authorities produce runtime/execution facts. A Web/Agent/client never writes fill/order/position truth directly.

---

# 6. Command / Query model

P9.K standardizes two application contracts.

## Command

A Command asks for an authoritative transition.

Examples:

```text
CreateResearchRun
CancelResearchRun
CertifyCalculation
FreezeStrategy
PromoteStrategy
StartBacktest
StopBacktest
StartSimulation
StopSimulation
future CreateDeployment
future ChangeExecutionPermission
```

Commands are named domain intents, not CRUD patches.

Forbidden style:

```http
PATCH /strategies/{id}
{"status":"LIVE"}
```

Preferred style:

```http
POST /api/v1/strategies/{fingerprint}/promotions
```

## Query

A Query reads verified facts/projections and causes no hidden transition.

Examples:

```text
GetKernelStatus
GetResearchRun
ListResearchRuns
GetResearchResult
GetStrategy
GetPromotionHistory
GetBacktest
GetSimulation
```

P8's separation between Research Command and immutable Artifact Query is a valid existing specialization and should be preserved while the product-level contract is unified.

---

# 7. Schema boundary

Maintain three separate schema worlds:

```text
API Schema
→ public transport compatibility

Domain/Application Schema
→ Kernel semantics

Persistence Schema
→ storage implementation
```

Explicit mappers connect them.

```text
HTTP JSON
→ Pydantic API DTO
→ Command/Query
→ Domain Authority
```

and:

```text
Domain/Projection
→ API response mapper
→ versioned API DTO
```

Do not reuse a Domain object as a public transport contract simply because FastAPI can serialize it.

---

# 8. OpenAPI governance

P8 already generates `contracts/research-api/v2/openapi.json`. P9.K generalizes this discipline to the product contract.

Target flow:

```text
FastAPI routes + API DTO
        ↓
generated OpenAPI
        ↓
canonicalization
        ↓
contract fingerprint
        ↓
lint
        ↓
breaking-change comparison
        ↓
generated clients
```

Recommended tooling may include Redocly CLI and `oasdiff`, but tooling is subordinate to the invariant: there is one generated/versioned public contract and breaking changes are explicit.

Do not hand-maintain a second OpenAPI YAML authority beside implementation unless a later ADR deliberately changes to spec-first development.

API contract fingerprint/version never enters Strategy semantic identity.

---

# 9. Long-running operation model

HTTP request lifetime never owns Research/Backtest/SIM/Deployment lifetime.

Reference pattern:

```text
POST Command
   ↓
durable admission
   ↓
202 Accepted / resource identity
   ↓
request ends

Kernel / Worker / Runtime continues
   ↓
Query returns current durable state
```

P8 Research Run is the existing reference implementation.

Do not add in-memory request queues as durable product authority.

---

# 10. Idempotency

Every externally retryable mutation must have deterministic retry semantics.

Conceptual binding:

```text
External Command ID / Idempotency-Key
+
Canonical Command Fingerprint
→ Authoritative Outcome
```

Rules:

```text
same key + same command
→ replay same outcome

same key + different command
→ conflict
```

These are operational identities only.

Never include:

```text
request_id
idempotency_key
actor
JWT
IP address
HTTP headers
API route/version
```

in Dataset/Calculation/Candidate/Strategy fingerprints.

---

# 11. Kernel lifecycle

Target lifecycle:

```text
CREATED
   ↓
BOOTING
   ↓
VERIFYING
   ↓
RECOVERING
   ↓
READY
   ↓
DRAINING
   ↓
STOPPED
```

Unrecoverable verification/recovery failure:

```text
FAILED
```

Before READY, mutation Commands fail closed.

Boot verification includes only what current configured product scope requires, but the ownership rules are stable:

```text
configuration validity
semantic namespace identity
PostgreSQL schema compatibility
implementation Registry uniqueness
semantic Store verification
unfinished durable lifecycle recovery
projection reconciliation
future external/Broker reconciliation where relevant
```

Application startup must not silently perform production migration or invent semantic repairs.

---

# 12. State ownership model

## Immutable Semantic State

Examples:

```text
Dataset Snapshot
Calculation Result
Research Result / Artifact
Execution Evidence
Equivalence Evidence
Strategy Revision
Freeze Relation
```

Authority:

```text
content-addressed immutable semantic stores
```

## Operational State

Examples:

```text
Research Run
Attempt
Worker lease
Runtime Session
future Deployment lifecycle
```

Authority:

```text
transactional operational stores, currently PostgreSQL where designed
```

## Runtime Mutable State

Examples:

```text
indicator state
streaming calculation state
runtime execution state
```

Authority:

```text
in-memory deterministic state
+
explicit checkpoints/durable transaction evidence where required
```

## External State

Examples:

```text
venue order status
fill
broker balance
broker position
```

Authority:

```text
external Broker/Venue
+
local canonical reconciliation evidence/projection
```

Do not serialize a whole Kernel object as recovery authority.

---

# 13. Process model

P9.K V1 deliberately chooses a modular monolith Control Plane.

```text
onlyalpha-server
├── FastAPI adapter
└── one mutation-capable Stateful Kernel Host

onlyalpha-research-worker × N
└── execution agents using existing Run/Attempt/lease authority
```

A first implementation must not create multiple independent mutation-capable Kernel instances behind `uvicorn --workers N`.

Reason:

```text
multiple in-process Kernel authorities
→ ambiguous ownership / split brain risk
```

High availability is a separate later architecture problem requiring leader/epoch/fencing semantics.

---

# 14. Runtime Supervisor

P9.K should introduce or formalize one runtime lifecycle supervision boundary rather than put lifecycle logic into HTTP routes.

Responsibilities:

```text
create
start
stop
drain
inspect
recover
fence
```

Potential supervised products:

```text
Backtest
SIM
future LIVE
```

Research Worker remains separately orchestrated where its existing durable worker model is already correct.

Runtime Supervisor does not author Strategy, Portfolio or Risk rules.

---

# 15. Control Plane vs Data Plane

## Control Plane

OpenAPI requests:

```text
create
cancel
freeze
promote
start
stop
deploy
query
```

## Data Plane

High-frequency facts:

```text
bar
tick
trade
quote
order-book delta
broker execution report
fill
```

Do not route every Data Plane event through public REST.

Data Plane enters through provider-neutral Kernel Ports / dedicated Gateway protocols.

---

# 16. QMT / CTP future boundary

Target topology:

```text
Linux
┌──────────────────────────────┐
│ OnlyAlpha Stateful Kernel    │
└───────────────┬──────────────┘
                │
        Protobuf / gRPC
                │
                ▼
Windows
┌──────────────────────────────┐
│ OnlyAlpha QMT Gateway        │
│ xtquant / MiniQMT            │
└──────────────────────────────┘
```

Gateway is an Infrastructure Adapter, not a public product endpoint and not a second trading authority.

P9.K only freezes this protocol direction. It does not require implementing the complete QMT/CTP gateway before P9.1.

---

# 17. External client model

## Web

Must depend on OpenAPI-derived client/contracts only.

## Python SDK

Target product package:

```text
onlyalpha-client
```

It communicates over the Product Control Plane and does not import mutation capabilities from `onlyalpha`.

## CLI

Two legal outcomes:

```text
remove product CLI
```

or:

```text
retain UX CLI
→ implement as OpenAPI client
```

The existing direct Engine/Store CLI is a migration surface, not the target architecture.

## Agent

Agent is an Author/Operator client with no privileged direct Kernel import path. It uses the same public contract and authorization/idempotency rules as other external actors.

---

# 18. Repository shape direction

Physical moves are not required in K0. Logical boundaries come first.

Long-term direction:

```text
OnlyAlpha/
├── src/onlyalpha/                 # Kernel/Core
│   ├── kernel/
│   │   ├── host.py
│   │   ├── lifecycle.py
│   │   ├── command.py
│   │   ├── query.py
│   │   ├── supervisor.py
│   │   └── recovery.py
│   ├── application/
│   ├── research/
│   ├── strategy/
│   ├── portfolio/
│   ├── risk/
│   ├── execution/
│   ├── runtime/
│   └── ports/
│
├── packages/api/onlyalpha-api/   # Product HTTP adapter (evolve existing package)
│
├── apps/onlyalpha-web/
│
├── clients/python/               # future public API client
│
└── gateways/                     # future process boundaries
    ├── qmt/
    └── ctp/
```

Do not perform a mass directory rewrite merely to match this picture. Introduce boundaries incrementally and move code only when ownership becomes clearer.

---

# 19. P9.K execution plan

## K0 — Architecture Freeze & Surface Inventory

### Goal

Freeze ownership before implementation.

### Work

- accept ADR 0101;
- inventory every current external/product path:
  - top-level exports;
  - console scripts;
  - direct Engine construction;
  - direct Runtime construction;
  - API package;
  - Web imports/contracts;
  - operator scripts;
  - direct Store writers/readers;
  - test-only/public helper leakage;
- classify each as:

```text
KEEP INTERNAL
MIGRATE TO PRODUCT API
RETAIN AS OPERATOR-ONLY
REMOVE
INFRASTRUCTURE PORT
```

- freeze allowed dependency directions;
- add initial architecture tests that prevent new violations while migration proceeds.

### Exit

No implementation work begins with an unknown external authority surface.

---

## K1 — Kernel Host & Lifecycle

### Goal

Create one long-lived composition/lifecycle authority without changing domain semantics.

### Work

- introduce minimal Kernel Host/Lifecycle state;
- compose existing Research/Strategy/Application capabilities rather than rewrite them;
- implement readiness/failure/drain semantics;
- separate liveness from readiness;
- make mutation dispatch impossible before READY;
- explicitly prevent HTTP adapter concerns from entering Kernel package.

### Exit

Kernel can boot, verify, recover required current authorities and become READY deterministically.

### K1 implementation and closure evidence (2026-08-26)

Implementation subject:

```text
TASK_BASE_SHA: 1c3be8823ba67c851b01e2c0c5ae93e39187f719
INITIAL_K1_IMPLEMENTATION_SHA: 7950af055213506685de72eada13c3ebc8f57c51
K1_CLOSURE_SHA:               80ca2027ca2e28d050c9b87326062ac52be60cfe
```

The minimal Product Kernel boundary is:

```text
src/onlyalpha/kernel/
├── __init__.py
├── lifecycle.py
└── host.py
```

`OnlyKernelLifecycle` owns the closed transition graph. `OnlyAlphaKernelHost` owns ordered boot, verification, recovery and drain
coordination. The current Research API composition root is the only production Host constructor. It composes the Calculation Registry in
`BOOTING`, consumes PostgreSQL server/schema compatibility, deployment namespace, required-root and Registry evidence in `VERIFYING`, has
an explicit empty K1 recovery sequence for the current API-owned scope, and enters `READY` before Uvicorn serves product traffic.

The existing Research health DTO remains stable. The full Python app factory now requires a Kernel readiness projection, so a
Research-only probe cannot become a competing product mutation gate. Only `READY` admits product routes. A
verification failure moves the Host to `FAILED`, preserves the existing stable Research readiness reason, keeps the HTTP diagnostics
process live, and admits no mutation. `READY → DRAINING` closes admission before lifecycle-owned shutdown; `STOPPED` is not live or ready.
The OpenAPI exporter now obeys the same full-app composition contract through a dependency-free real `OnlyAlphaKernelHost` lifecycle and
is classified as non-production contract tooling. It does not add a second lifecycle authority or production holder.

K1 holds only `OnlyPostgresSchemaVerifier`-derived read capability. Migration remains operator-only. It creates no recovery Store, Kernel
snapshot, Product Command/Query dispatcher, HTTP route, persistence schema, Strategy/Research identity, or Trading Kernel semantic path.
`OnlyTradingKernel` remains at `src/onlyalpha/runtime/trading/kernel.py`.

Canonical local evidence:

```text
kernel:                    27 passed
architecture:              448 passed
research-command:          44 passed
research-postgres:         92 passed; coverage 82.39%
research-product-closure:  19 passed
export OpenAPI check:       PASS; canonical contract unchanged
web static:                 PASS; generated TypeScript unchanged
import-linter:              3 kept, 0 broken
Core mypy:                  614 source files, PASS
API/exporter mypy:          18 source files, PASS
ruff check .:               PASS
changed-file format check:  PASS
version graph 0.9.0:        PASS
git diff --check:           PASS
```

Evidence status is `DONE / VERIFIED` for the immutable K1 closure subject. No Final-SHA Certification was run, so this is not a
`CERTIFIED / ACCEPTED` claim.

---

## K2 — Product Command / Query Boundary

> Implementation status: **DONE / VERIFIED in the current worktree based on
> `14a5726839f013e7567a1c19edfecfef3f749518`**. The worktree has not been committed or Final-SHA certified.

### Goal

Define one internal product-facing application contract.

### First supported Commands

```text
Research submit/cancel
Calculation certification intent where product-exposed
Strategy Freeze
Strategy Promotion
Backtest start/stop where current semantics support it
SIM start/stop where current semantics support it
```

### First supported Queries

```text
Kernel status/readiness
Research Run/result references
Strategy Revision/Freeze provenance
Promotion history
Backtest/SIM lifecycle projections
```

### Work

- reuse existing P8 Research command/query services;
- create adapters rather than duplicate Research authority;
- establish canonical command identity where required;
- prohibit generic CRUD state mutation.

### Exit

All new product capabilities can be exposed through the Command/Query boundary without routes touching domain internals directly.

### Implemented K2 closure

The neutral Kernel now provides separate immutable-topology `OnlyProductCommandDispatcher` and
`OnlyProductQueryDispatcher` boundaries. Both resolve only `type(value)`; duplicate exact types fail during construction, unknown exact
types and unregistered subclasses fail closed, and no runtime registration surface exists. Command dispatch invokes the single narrow
`assert_mutation_ready()` admission capability before lookup or handler invocation. The Dispatcher owns no persistence, retry,
fingerprint, Research, Strategy, Engine, Runtime, or transport semantics.

The canonical Research proof vertical is composed only in `onlyalpha.application.product_boundary`:

```text
OnlyCreateResearchRun  → OnlyResearchCommandService.submit_research_run
OnlyCancelResearchRun  → OnlyResearchCommandService.request_research_run_cancellation
OnlyGetResearchRun     → OnlyResearchRunQueryService.get_run
OnlyListResearchRuns   → OnlyResearchRunQueryService.list_runs
```

Research submission identity/idempotency, cancellation CAS/state legality, Run persistence, query ordering and cursor semantics remain
owned by the existing authorities. `OnlyResearchRunQueryService` now receives the narrow read-only `OnlyResearchRunReader` Protocol,
not the mutation-capable command Store surface. `GetKernelStatus` is deliberately deferred: the current Host has not yet exposed a
narrow status-only capability, and capturing the full Host in a Query handler would violate the K2 read-only capability rule.

C18 `PRODUCT_COMMAND_DISPATCH` is active (`reserved=false`, privileged) and C19 `PRODUCT_QUERY_DISPATCH` is a distinct read-only
capability. Both Dispatcher constructors have exactly one approved production composition path. Kernel definitions and the canonical
Product composition are the only production holders; HTTP routes, Worker, Runtime, CLI and public root surfaces do not hold C18/C19.

K2 adds no HTTP route/DTO/OpenAPI change, database schema/migration, global idempotency/recovery ledger, remote protocol, Strategy/P9.0
semantic change, or second lifecycle/readiness authority. Canonical K2 verification and the reverse audit are recorded in
[`reports/p9_k2_product_command_query_boundary.md`](reports/p9_k2_product_command_query_boundary.md).

---

## K3 — Unified Product HTTP Control Plane

### Goal

Evolve the existing `onlyalpha-api` package into the unique product HTTP adapter.

### Work

- preserve existing Research v2 behavior or provide an explicit versioned migration;
- compose product routers around Command/Query services;
- isolate API DTOs from Domain models;
- centralize stable HTTP error mapping;
- add actor/idempotency context boundary;
- ensure routes never directly create Engine/Runtime/Store writers;
- ensure long-running work returns durable resource/operation identity rather than owning execution lifetime.

### Exit

Web/product clients can control the currently supported product scope through one HTTP adapter with no second business path introduced.

### K3 implementation and closure evidence (2026-08-26)

The existing Research v2 Product server now composes the K2 `OnlyResearchProductBoundary` from the same started
`OnlyAlphaKernelHost` that owns readiness and mutation admission. Create/Cancel construct explicit Product Commands; Get/List construct
explicit Product Queries. The Run router has no direct `OnlyResearchCommandService` or `OnlyResearchRunQueryService` dependency and has
no dispatcher-failure fallback. DTO, header, path, response and error mapping remain in the FastAPI adapter.

The production console remains `onlyalpha-api` with one Host and no multi-worker option. `onlyalpha-artifact-api` is retained as
read-only migration debt because it is an existing documented console contract; it has no Kernel Host, Product Command boundary, or
mutation capability and is not a second Product Control Plane. Canonical Research OpenAPI and generated Web client semantics remain
unchanged. Database schema/migrations and P9.0 Strategy semantics remain unchanged.

ADR 0102 records PostgreSQL 16.10 as the current verified baseline and PostgreSQL 18.x as the future target. The PostgreSQL 18 migration
is planned but not started or verified; K3 does not change CI images, client packages, SQL, migrations, or UUID semantics.

---

## K4 — OpenAPI Contract Governance

### Goal

Turn OpenAPI from generated documentation into an explicit product compatibility artifact.

### Work

- produce canonical versioned OpenAPI contract;
- deterministic generation/check command;
- lint contract;
- add breaking-change comparison against accepted contract baseline;
- generate external client types/client where useful;
- define API versioning rules;
- optionally compute contract fingerprint from canonical semantic document.

### Exit

Public compatibility changes are mechanical and reviewable.

### K4 implementation and closure evidence (2026-08-26)

FastAPI Routes + API DTO remain the one public authoring authority. The one committed v2 projection remains
`contracts/research-api/v2/openapi.json`; its exact revision is external SHA256 over deterministic canonical bytes. Historical accepted
baseline is loaded only from `<BASE_SHA>:contracts/research-api/v2/openapi.json`, so candidate and baseline cannot be changed together.

`scripts/openapi_contract.py` is the single governance implementation for write/check, structural and OnlyAlpha policy lint, immutable
Git baseline loading, explicit old-client→new-server compatibility comparison and pinned Web client freshness. The old exporter is a thin
delegating wrapper. v2 path/operation/request/response/`operationId`/strict response-enum breaks fail closed without a waiver flag. A
dedicated CI job uses PR base SHA or previous master SHA; manual dispatch uses the explicit parent bootstrap baseline.

The K4 Closure extends that same authority with direction-aware `const`/`enum` sets, normalized `additionalProperties` states and recursive
child comparison, referenced composition semantics, stable comparison-pair cycle protection, exact discriminator comparison and explicit
current-v2 schema vocabulary governance. Unknown compatibility-sensitive schema keywords fail closed instead of being assumed compatible.

K4 preserves canonical OpenAPI SHA256
`c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e` and generated TypeScript SHA256
`7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd`. It changes no HTTP, Research/P9.0, database or PostgreSQL
semantics and does not start v3 or K5/K6/K7. Task Gate and reverse-audit evidence is recorded in
[`reports/p9_k4_openapi_contract_governance.md`](reports/p9_k4_openapi_contract_governance.md).

The local Closure Task Gate and implementation SHA `47e12df6bb7119396bb3dcda4b3e4c8483efa066` direct remote
`openapi-contract`, architecture, static and Web gates passed. K4 is DONE / VERIFIED and K5 is IMPLEMENTATION READY.

Closure-2 repairs the previously hidden response traversal gaps in the same comparator. New-only named response properties are checked
against the old `additionalProperties` policy, including direction-aware reuse of the existing schema comparator for AP schema values;
new response statuses and media types are rejected under the frozen strict v2 policy. The AP=false/true/missing/schema matrix, existing
property regression, status/media add-remove rules and stable sorted evidence are characterized. Canonical OpenAPI and generated
TypeScript bytes remain unchanged, and no K5 or semantic source work started. The local Task Gate and implementation SHA
`7c25a3cc42c7ea6e189044b5b8d8c62dc8b78d5f` direct remote `openapi-contract`, architecture, static, Web, research-command and
research-query jobs passed. Evidence is recorded in
[`reports/p9_k4_closure_2_response_compatibility.md`](reports/p9_k4_closure_2_response_compatibility.md).

---

## K5 — Idempotency, Long-running Operations & Recovery Closure

Implementation status (2026-08-27): implemented in the current worktree. Product Command Receipt is the sole active external retry
authority; Create and keyed Cancel share atomic business-effect/Receipt transactions; optional v2 Cancel idempotency is projected into
the governed OpenAPI; Strategy semantic inventory and `reconcile_all()` make RECOVERING operational; and the production Kernel uses a
PostgreSQL session advisory guard. Local targeted evidence is recorded in the K5 implementation report. Real PostgreSQL and exact-SHA CI
evidence remain required before `DONE / VERIFIED` may be claimed.

### Goal

Make network retry and Kernel restart normal deterministic scenarios.

### Work

- generalize P8 idempotency principles for all externally retryable mutations;
- define/reuse durable operation resources where needed;
- prove response-loss retry does not duplicate authoritative work;
- recover incomplete commands/sessions from durable authorities;
- reconcile projections after crash;
- fail closed on command-id reuse with different canonical intent;
- add deterministic barriers for crash-boundary tests rather than timing guesses.

### Exit

Restart/retry converges to one outcome and does not produce duplicate semantic/business authority.

---

## K6 — External Client Migration

### Goal

Stop treating the Kernel package as the normal user control interface.

### Work

- migrate Web to the governed product contract;
- create/prepare Python API client contract;
- classify and migrate CLI UX;
- move operator-only diagnostics to explicit operator tooling where direct infrastructure access remains justified;
- update examples/documentation away from direct Engine mutation as product usage.

### Exit

Every supported product external actor has an API path for required operations.

---

## K7 — Remote Protocol Foundation

### Goal

Freeze future Gateway process boundary without implementing an unnecessary distributed platform.

### Work

- define Protobuf/gRPC versioning and error/identity rules;
- prove a minimal test Gateway if useful;
- separate unary command RPC from streaming event channels;
- establish reconnect/correlation/idempotency expectations;
- document QMT/CTP adapters as infrastructure rather than product APIs.

### Non-goal

Do not complete QMT/CTP trading here unless a later task explicitly starts those provider milestones.

### Exit

Future heterogeneous OS gateways no longer need an ad-hoc protocol decision.

---

## K8 — Seal Kernel

### Goal

Remove the temporary direct product authorities after clients have migrated.

### Work

- remove/deprecate unsupported top-level mutation-oriented exports;
- remove direct product CLI Engine/Runtime invocation or convert it to API client behavior;
- prevent Web/client packages from importing Kernel mutation capabilities;
- prevent API routes from obtaining persistence/semantic publishers directly;
- lock boundaries with import-linter/architecture tests;
- re-audit unique authority and determinism invariants.

### Exit

The Product Control Plane is the only supported external mutation path.

---

# 20. Architecture gates

P9.K should mechanically enforce at least:

```text
Core/Kernel MUST NOT import FastAPI/Starlette/Pydantic API DTO modules.

API adapter MUST NOT implement business fingerprint/admission/state-machine logic.

Web MUST NOT import Kernel.

External Python client MUST NOT import Kernel.

Retained CLI MUST NOT directly mutate Kernel after K8.

Runtime MUST NOT obtain Strategy publication authority.

Product API MUST NOT obtain raw semantic Store writers except through explicit Application authority.

Infrastructure adapters MUST NOT redefine Domain semantics.

Public HTTP retry identity MUST NOT enter semantic fingerprints.

One control-plane deployment MUST NOT host multiple unfenced mutation-capable Kernel authorities.
```

Existing P9.0 architecture tests remain mandatory and must not be weakened to make P9.K easier.

---

# 21. Required failure/recovery scenarios

At minimum:

```text
API accepted mutation, response lost, client retries
→ one outcome

same Idempotency-Key, different canonical command
→ conflict

Kernel dies after durable command admission
→ deterministic recovery/replay

Kernel dies after semantic fact before projection
→ projection reconciliation

projection exists but conflicts with semantic authority
→ fail closed

Kernel startup with incompatible migration/namespace/semantic Store
→ not READY

API process receives mutation while RECOVERING
→ reject/fail closed

attempt to run multiple unfenced mutation-capable Kernel instances
→ deployment/configuration gate rejects
```

---

# 22. Major implementation risks

## Risk A — API wrapper without authority migration

Failure mode:

```text
FastAPI
→ direct imports everywhere
```

Result: HTTP becomes another path rather than the unique product boundary.

Mitigation: Command/Query boundary before broad endpoint expansion.

## Risk B — Kernel god object

Failure mode: every subsystem moves into `OnlyAlphaKernel`.

Mitigation: Kernel Host composes explicit authorities; domain rules remain in owning modules.

## Risk C — duplicate lifecycle state

Failure mode: API operation state, Worker state and Domain/Run state all claim the same truth.

Mitigation: operation resources reference authoritative lifecycle facts; do not create a second workflow engine.

## Risk D — multiple FastAPI workers create split brain

Mitigation: V1 single authoritative Kernel process; scale read/execution agents separately; HA is later fencing work.

## Risk E — over-distributed rewrite

Mitigation: modular monolith first; gRPC only where a real process/OS boundary exists.

## Risk F — compatibility preservation keeps direct mutation alive forever

Mitigation: K0 inventory + K6 migration + K8 hard cut. Compatibility is not a reason for two permanent product authorities.

## Risk G — protocol metadata contaminates strategy identity

Mitigation: explicit fingerprint tests proving actor/request/idempotency/API version do not change semantic identity.

---

# 23. Explicit non-goals

P9.K does not implement or require:

```text
Binance integration
QMT live trading
CTP live trading
real Broker submission
new Portfolio model
new Risk model
LIVE safety permission
ClickHouse Market Data Platform
Kafka
NATS
Redis task authority
Temporal
Celery lifecycle authority
GraphQL
Kubernetes
service mesh
multi-master HA
generic workflow DSL
full microservice decomposition
Rust Kernel rewrite
```

Those remain separate product/technology decisions after the control boundary is correct.

---

# 24. Definition of Done

P9.K is complete only when all of the following are true:

```text
[1] One supported Product Control Plane exists.

[2] External product mutation uses versioned OpenAPI/HTTP.

[3] FastAPI is a replaceable adapter and absent from Kernel dependencies.

[4] API DTO, Domain models and persistence schema are separate.

[5] Product mutations are explicit Commands.

[6] Product reads are Queries and do not hide state transitions.

[7] External clients submit intent/reference, not authority facts.

[8] Long-running work is durable and detached from HTTP request lifetime.

[9] Externally retryable mutation is idempotent.

[10] Transport/audit identity does not alter semantic fingerprints.

[11] Kernel lifecycle/readiness is explicit and fail closed.

[12] Restart/recovery converges from durable authorities.

[13] Semantic, operational, runtime and external state ownership is explicit.

[14] V1 has one logical mutation-capable Control Kernel authority.

[15] Research Workers remain execution agents rather than second lifecycle authorities.

[16] Kernel Trading pipelines remain explicit typed direct calls.

[17] High-frequency Data Plane is not forced through public REST.

[18] Web is only a Product API client.

[19] Python SDK is only a Product API client.

[20] CLI is removed, operator-only, or an API client; no supported direct business mutation remains.

[21] Agent has no privileged direct Kernel path.

[22] Remote Gateway protocol direction is explicit and provider-neutral.

[23] Architecture tests mechanically prevent boundary regression.

[24] P9.0 Strategy/Freeze/Evidence/Promotion invariants remain unchanged.
```

---

# 25. Relationship to P9.1+

P9.K is intentionally performed before Binance/real-market work.

After K8, P9.1+ features should grow like:

```text
External Actor
→ Product OpenAPI Command
→ Stateful Kernel Authority
→ Market/Broker Infrastructure Port
→ Provider Adapter/Gateway
```

not like:

```text
script / CLI / Web
→ import internal Runtime/Broker
→ direct execution
```

This is the central reason for doing P9.K immediately after P9.0: later real-market, real-account and LIVE capabilities enter a product boundary whose ownership, retry, lifecycle and recovery rules are already correct.
