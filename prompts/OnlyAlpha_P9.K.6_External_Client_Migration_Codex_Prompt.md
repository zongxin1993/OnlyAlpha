# OnlyAlpha — P9.K.6 External Client Migration — Codex Implementation Prompt

## 0. Task Identity

**Repository:** `zongxin1993/OnlyAlpha`  
**Task:** `P9.K.6 — External Client Migration`  
**Task type:** Architecture-bound migration / authority convergence  
**Primary objective:** Migrate every supported external Product Actor to the governed Product Control Plane without expanding business semantics or creating a second authority.

Planning baseline observed when this task prompt was prepared:

```text
39c8dbf6f78f174dfd896057b0490dedf432b5ea
```

This SHA is **not** an implementation authority.

Before editing anything:

1. fetch/read the actual current `master`;
2. record exact current HEAD as `TASK_BASE_SHA`;
3. current repository truth wins over this prompt;
4. read current `project-state.toml`;
5. run the project-state consistency check;
6. verify the repository still establishes:
   - `P9.K.5 = TASK COMPLETE / VERIFIED`;
   - `P9.K.6 = IMPLEMENTATION READY`;
7. if current source/docs/tests contradict those facts, stop implementation and report the conflict;
8. do not blindly patch paths, imports, symbols, hashes, versions, or assumptions from this prompt.

Expected pre-task state transition, only after the repository state is verified:

```bash
uv run python scripts/project_state.py check
uv run python scripts/project_state.py transition start P9.K.6
uv run python scripts/project_state.py check
```

Do not manually edit README/roadmap/current-state projections to fake task progress.  
`project-state.toml` and the project-state tooling remain the current-state authority.

---

# 1. Why This Task Exists

P9.K.1–P9.K.5 establish the product-side authority chain:

```text
Kernel Lifecycle Authority
        ↓
Product Command / Query Boundary
        ↓
Single Product HTTP Adapter
        ↓
Governed Canonical OpenAPI
        ↓
Idempotent Product Command Receipt
        ↓
Durable Recovery / Reconciliation
```

However, the repository still contains transitional external-style surfaces where a user can treat OnlyAlpha as a directly controlled Python framework:

```text
External Python
    ↓
OnlyEngine / Runtime

CLI
    ↓
OnlyEngine / direct infrastructure

Public-style example
    ↓
OnlyEngine
```

This creates a structural contradiction:

```text
one Product Control Plane exists
but
more than one supported-looking Product Control Path still exists
```

That is unacceptable before Portfolio / Risk / Execution / Broker / LIVE work grows.

The first-principles problem is:

> A product cannot claim one authoritative state-transition boundary while supported external users can still bypass that boundary through direct Engine/Runtime control.

P9.K.6 must therefore migrate external clients to the Product Control Plane.

This task is **not**:

- a Kernel redesign;
- an HTTP redesign;
- a new business-capability milestone;
- a Broker / LIVE milestone;
- K7 remote protocol work;
- K8 hard sealing.

---

# 2. Governing First-Principles Rules

OnlyAlpha engineering must continue to optimize for:

```text
one fact
→ one authority

one semantic identity
→ one deterministic interpretation

one product transition
→ one legal path

same authoritative inputs
→ same authoritative result

unknown / ambiguous / partially verified
→ fail closed
```

P9.K.6 applies those principles specifically to external product control.

The target dependency direction is:

```text
SUPPORTED EXTERNAL PRODUCT ACTOR
              ↓
      OpenAPI-derived Client
              ↓
          HTTPS / JSON
              ↓
   Canonical Product HTTP Adapter
              ↓
      Product Command / Query
              ↓
        Stateful Kernel
              ↓
 Existing Application / Domain Authority
```

Forbidden end-state:

```text
External Actor
   ├── Product API → Kernel
   └── Python/CLI  → Engine/Runtime
```

---

# 3. Mandatory Reading Before Coding

Read the **current** versions of at least:

```text
AGENTS.md
AGENTS.override.md                     # if present

project-state.toml
scripts/project_state.py

docs/engineering/convergent-audit-policy.md
docs/engineering/quality-system.md
docs/engineering/project-state-authority.md

docs/adr/0097-strategy-revision-freeze-and-promotion-authority.md
docs/adr/0100-p9-0-evidence-soundness-and-publication-convergence.md
docs/adr/0101-stateful-kernel-and-protocol-boundary.md

docs/p9_k_stateful_kernel_protocol_boundary.md
docs/roadmap.md

docs/reports/p9_k0_product_surface_inventory.md
docs/reports/p9_k5_idempotency_recovery_implementation.md

src/onlyalpha/__init__.py
src/onlyalpha/cli.py

src/onlyalpha/kernel/**
src/onlyalpha/application/product_boundary.py
src/onlyalpha/application/product_command_receipt.py

packages/api/onlyalpha-api/**
contracts/research-api/v2/openapi.json

apps/onlyalpha-web/**
scripts/openapi_contract.py                  # or current equivalent
scripts/export_research_openapi.py           # if still present
scripts/web_suite.py
scripts/test_suite.py

examples/**
tests/architecture/**
.github/workflows/**
```

Also inspect the actual current workspace configuration and current client-generation mechanisms.

Do not design from this prompt alone.

---

# 4. Current Known Migration Surfaces

Re-audit current `master`, but at planning time K0 identified these important K6 surfaces.

## 4.1 Public Python Core Surface

Current public/root exports historically include mutation/lifecycle-oriented types such as:

```text
OnlyEngine
OnlyRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
OnlyLiveRuntime
Cluster-related construction types
```

Classification:

```text
PUBLIC_PYTHON
→ MIGRATE TO PRODUCT API in K6
→ hard seal/remove/deprecate unsupported paths in K8
```

K6 does **not** need to delete internal Engine/Runtime implementation.

## 4.2 Root CLI

Current root CLI historically contains direct Engine paths such as:

```text
onlyalpha run
onlyalpha snapshot
```

and may contain operator/test commands.

K6 must classify each CLI capability as one of:

```text
PRODUCT_API_CLIENT
OPERATOR / INFRASTRUCTURE
TEST / SCENARIO
LEGACY_K8_TARGET
REMOVE
```

No CLI command may remain unclassified.

## 4.3 Web

Web is already largely aligned:

```text
Web
→ generated/validated HTTP contract
→ Product HTTP API
```

K6 should verify and mechanically guard this path, not rewrite Web architecture.

## 4.4 Public-style Examples / Documentation

Any product-facing example that teaches:

```python
OnlyEngine(...)
```

as normal product usage is a migration defect.

Examples are executable documentation and must be classified.

## 4.5 Artifact-only HTTP Executable

If an artifact-only HTTP executable still exists, K6 must classify it explicitly:

```text
REMOVE
or
READ_ONLY_COMPATIBILITY_SURFACE
```

It must never become a second Product Control Plane.

## 4.6 Worker / Operator / Test Paths

These are **not automatically Product Clients**.

Examples:

```text
Research Worker
database migration tooling
backup/restore
provider doctor
read-only operational diagnostics
scenario/test composition
```

They may retain explicitly justified infrastructure/internal access.

Do not force all internal operations through public REST merely for visual consistency.

---

# 5. Frozen K6 Core Invariants

## INV-K6-01 — Every Supported External Product Actor Has a Product API Path

Supported external actors include, where currently supported:

```text
WEB
PUBLIC_PYTHON
PRODUCT_CLI
AGENT
AUTOMATION
NOTEBOOK
```

For every currently supported operation:

```text
External Actor
→ Product API path exists
```

No supported operation may require direct Engine/Runtime construction.

---

## INV-K6-02 — External Python Does Not Own Product Lifecycle

Supported Python product usage must not require:

```python
OnlyEngine(...)
OnlyRuntime(...)
OnlyBacktestRuntime(...)
OnlyResearchRuntime(...)
OnlyLiveRuntime(...)
```

Target:

```text
Python Program
    ↓
onlyalpha-client
    ↓
HTTPS / JSON
    ↓
Product Control Plane
```

---

## INV-K6-03 — One Official Python Product Client Boundary

Create or establish one product client package in the direction:

```text
onlyalpha-client
```

Preferred physical location if consistent with current repository conventions:

```text
packages/client/onlyalpha-client/
```

Do not create multiple Python clients with overlapping authority.

---

## INV-K6-04 — `onlyalpha-client` Must Not Depend on Kernel/Core

The client package must have zero dependency on the `onlyalpha` core package unless current source proves an unavoidable transport-only reason and an accepted architecture decision already exists.

Preferred hard rule:

```text
onlyalpha-client dependency on onlyalpha = FORBIDDEN
```

Client source must not import:

```text
onlyalpha.engine
onlyalpha.runtime
onlyalpha.kernel
onlyalpha.application
onlyalpha.persistence
onlyalpha.strategy
```

The client is a remote product consumer, not an in-process compatibility wrapper.

---

## INV-K6-05 — Canonical OpenAPI Is the Sole Public Client Schema Authority

Authority chain:

```text
FastAPI Routes + API DTO
        ↓
Canonical OpenAPI
        ↓
Generated TypeScript Client
Generated Python Client
```

Do not create:

```text
hand-maintained Python SDK DTO authority
second OpenAPI source
parallel SDK schema
```

Generated client transport models must derive from the canonical committed OpenAPI artifact.

---

## INV-K6-06 — Generated Client Projection Is Deterministic

Define:

```text
GeneratedClientTree =
F(
  canonical OpenAPI bytes,
  exact generator version,
  exact generator config
)
```

Same inputs must produce the same generated result.

Generated code must not depend on:

```text
timestamp
hostname
absolute developer path
Git SHA
build number
random UUID
environment-specific ordering
```

Pin generator versions exactly enough to make formal checks reproducible.

---

## INV-K6-07 — Product Client Is a Thin Adapter, Not a New Business Layer

The client may own:

```text
base URL
HTTP transport
TLS configuration
credentials / auth headers
timeouts
request construction
transport error normalization
small UX facade
resource grouping
```

The client must not own:

```text
Research admission
Strategy fingerprint construction
Strategy Freeze legality
Promotion legality
business state machines
semantic publication
PostgreSQL writes
CAS
business retry authority
Kernel lifecycle truth
```

---

## INV-K6-08 — Client Retry Must Preserve K5 Command Identity Semantics

For externally retryable mutation:

```text
same external command identity
+
same canonical command
→ same authoritative outcome

same external command identity
+
different canonical command
→ deterministic conflict
```

Do not implicitly generate a new idempotency/command key on every retry.

Initial implementation should prefer:

```text
NO implicit mutation retry
```

unless current governed semantics already define a safe retry policy.

Queries may use a separate, explicit transport retry policy.

---

## INV-K6-09 — No Client Fallback to Local Engine

Forbidden:

```python
try:
    call_product_api(...)
except TransportError:
    OnlyEngine(...).run()
```

Also forbidden:

```text
API unsupported
→ direct local service fallback
```

Network/API failure must fail as a client/transport failure.

Compatibility must not recreate two Product authorities.

---

## INV-K6-10 — Product CLI, If Retained, Is an API Client

Any CLI capability classified as `PRODUCT_API_CLIENT` must follow:

```text
CLI
→ onlyalpha-client
→ Product API
```

It must not:

```text
construct OnlyEngine
construct Runtime
open Product mutation-capable PostgreSQL stores
invoke Application mutation services directly
```

---

## INV-K6-11 — Operator / Worker / Test Tooling Remains Explicitly Separate

Operator / Worker / Test capabilities may retain internal/infrastructure access when justified.

They must not be mislabeled as Product API clients.

Examples of potentially legal direct infrastructure access:

```text
database migration
backup / restore
provider doctor
read-only operational diagnostics
Research Worker Run/Attempt/Lease operations
scenario/test composition
```

Use explicit classification and narrow allowlists.

---

## INV-K6-12 — Public Product Examples Must Not Teach Direct Kernel Ownership

Product-facing examples/documentation must use:

```text
onlyalpha-client
or
HTTP Product API
```

Direct Engine examples may remain only when explicitly classified and located as:

```text
INTERNAL
TEST
OPERATOR
```

Do not preserve misleading public examples merely for compatibility.

---

## INV-K6-13 — Do Not Expand Product Semantics to Preserve Legacy Framework UX

Do not introduce endpoints such as:

```text
POST /engine/run
POST /engine/snapshot
```

merely to preserve old CLI/framework abstractions.

If a legacy command has no current Product semantic equivalent:

```text
classify it as LEGACY_K8_TARGET
or
internal/operator/test
or
remove it
```

Do not pollute the new Product API with old framework ownership semantics.

---

## INV-K6-14 — K6 Does Not Perform K8 Hard Seal

K6 migrates clients.

K8 seals/removes temporary direct product authorities.

Therefore K6 should not blindly remove all internal Engine/Runtime capabilities.

After K6 it is acceptable for temporary legacy direct paths to remain **only if** they are:

```text
explicitly classified
not documented as normal Product usage
not required by supported external actors
mechanically tracked as K8 targets
```

---

## INV-K6-15 — No Semantic Identity Contamination

The following remain transport/operational metadata:

```text
base_url
API major
OpenAPI hash
generated-client hash
request ID
idempotency key
actor
JWT
headers
CLI command syntax
```

They must never enter:

```text
Dataset fingerprint
Calculation identity
Research semantic identity
Candidate fingerprint
Strategy fingerprint
Strategy Revision identity
```

---

## INV-K6-16 — K6 Preserves P9.0 / K1–K5 Authorities

Expected K6 semantic delta:

```text
Strategy semantics        = 0
Freeze semantics          = 0
Promotion semantics       = 0
Research authority        = 0
Kernel lifecycle truth    = 0
Command Receipt authority = 0
Recovery authority        = 0
```

K6 consumes those authorities; it does not redesign them.

---

# 6. Current Product Capability Rule

Inspect current `src/onlyalpha/application/product_boundary.py` and current HTTP routes.

At planning time the canonical Research product proof vertical supports:

```text
OnlyCreateResearchRun
OnlyCancelResearchRun
OnlyGetResearchRun
OnlyListResearchRuns
```

Do not assume this remains exact; current source wins.

K6 client support must reflect **currently authoritative Product capabilities**.

Do not add hypothetical future APIs merely to make the SDK look complete.

Forbidden scope expansion examples:

```text
StartBacktest
StopBacktest
StartSimulation
DeployStrategy
SubmitOrder
CreateBroker
ChangeLivePermission
```

unless current `master` already establishes them as governed Product operations before K6 starts.

Rule:

```text
current authoritative Product capability
→ expose through client

future hypothetical capability
→ do not invent
```

---

# 7. Python Client Design

## 7.1 Preferred Shape

Use the smallest repository structure that preserves boundaries.

A reasonable direction:

```text
packages/
└── client/
    └── onlyalpha-client/
        ├── pyproject.toml
        ├── src/
        │   └── onlyalpha_client/
        │       ├── __init__.py
        │       ├── client.py
        │       ├── config.py
        │       ├── errors.py
        │       ├── research.py
        │       └── generated/
        └── tests/
```

Do not create files/modules merely to match this sketch.

Prefer fewer clear modules over an artificial framework.

## 7.2 Generated Layer + Thin Facade

Target:

```text
Canonical OpenAPI
      ↓
Generated Transport Layer
      ↓
Thin OnlyAlpha Product Facade
      ↓
User
```

Example desired UX, adapted to actual current schema:

```python
from onlyalpha_client import OnlyAlphaClient

client = OnlyAlphaClient(
    base_url="http://localhost:8000",
)

run = client.research.create(
    specification=specification,
    idempotency_key=command_key,
)

current = client.research.get(run.run_id)
page = client.research.list()
```

Do not force this exact API if current contract suggests a simpler deterministic interface.

## 7.3 Error Model

Prefer a small stable client error hierarchy, for example:

```text
OnlyAlphaClientError
├── OnlyAlphaTransportError
├── OnlyAlphaProtocolError
└── OnlyAlphaApiError
```

Preserve stable transport evidence such as:

```text
HTTP status
public API error code
detail
request/correlation identifier when contractually available
```

Do not pretend the SDK owns Domain exception semantics.

---

# 8. OpenAPI → Python Client Generation

## 8.1 Tool Selection

Evaluate a minimal pinned generator compatible with:

```text
canonical OpenAPI input
Python 3.12
deterministic output
small runtime footprint
repeatable CI
```

A tool such as pinned `openapi-python-client` may be evaluated, but the task is **not** “install this tool at all costs”.

The invariant is primary:

```text
same canonical OpenAPI
+
same exact toolchain
→ same client projection
```

If a candidate generator produces nondeterministic output:

1. characterize the source of nondeterminism;
2. prefer a different minimal tool if simpler;
3. do not build a large custom normalization framework to compensate for a bad generator.

## 8.2 One Client Projection Command Surface

Prefer one script/command surface such as:

```text
scripts/openapi_clients.py
```

or minimally extend an existing current script if that is clearer.

Recommended semantics:

```bash
python scripts/openapi_clients.py write
python scripts/openapi_clients.py check
```

`write`:

```text
canonical OpenAPI
→ generated clients
→ write deterministic projections
```

`check`:

```text
canonical OpenAPI
→ regenerate into temp location
→ compare committed projections
→ fail on drift
```

Do not combine this with K4 compatibility approval.

K4 remains responsible for:

```text
canonical contract
lint
contract SHA
breaking-change comparison
```

K6 tooling only consumes the accepted canonical contract.

---

# 9. Web Migration / Verification

Do not rewrite Web unnecessarily.

Verify current Web path is still:

```text
canonical OpenAPI
→ generated TypeScript contract/client
→ Product HTTP API
```

Mechanically ensure Web does not gain direct Kernel mutation capability.

Do not create a second handwritten Web transport-schema authority.

If Web is already compliant, record evidence and make the smallest changes necessary.

---

# 10. CLI Classification and Migration

Inventory every current CLI command.

Produce a deterministic table in the K6 report:

| Command | Actor | Current authority path | K6 classification | K6 action | K8 debt? |
|---|---|---|---|---|---|

Allowed classifications:

```text
PRODUCT_API_CLIENT
OPERATOR / INFRASTRUCTURE
TEST / SCENARIO
LEGACY_K8_TARGET
REMOVE
```

## 10.1 Product CLI

If retained:

```text
Product CLI
→ onlyalpha-client
→ Product API
```

No Engine/Runtime/Store mutation imports.

## 10.2 Operator CLI

Direct infrastructure access may remain only under an explicit operator identity.

If current CLI mixes Product and operator concerns, prefer a clear split such as an operator-specific entrypoint when it materially improves authority clarity.

Do not perform cosmetic splitting if current source already has a cleaner equivalent.

## 10.3 Scenario / Test CLI

Scenario/test execution may remain internal/test tooling.

Do not expose it as Product API merely for symmetry.

## 10.4 Legacy Engine CLI

Do not create `/engine/run` or `/engine/snapshot` API endpoints just to migrate old framework UX.

If there is no current Product-domain equivalent:

```text
mark as LEGACY_K8_TARGET
stop documenting as normal Product usage
preserve only as temporary explicit migration debt
```

K8 will make the final hard-cut decision.

---

# 11. Example / Documentation Migration

Scan at least:

```text
README.md
docs/**
examples/**
notebooks/**          # if present
active user-facing prompts/guides where relevant
```

Search for public-style usage of:

```text
OnlyEngine
OnlyRuntime
OnlyBacktestRuntime
OnlyResearchRuntime
OnlyLiveRuntime
direct persistence mutation
```

Classify each example/document as:

```text
PRODUCT
OPERATOR
INTERNAL
TEST
REMOVE
```

Rules:

```text
PRODUCT
→ use Product API / onlyalpha-client

INTERNAL / TEST
→ direct Engine may remain if explicitly identified

OPERATOR
→ may use narrow infrastructure capability

REMOVE
→ delete stale/no-value misleading example
```

Do not convert an internal execution example into a fake Product API endpoint merely to preserve it.

---

# 12. Artifact-only HTTP Surface Resolution

If an artifact-only executable still exists:

1. inventory actual current use/compatibility evidence;
2. decide explicitly:

```text
REMOVE
or
READ_ONLY_COMPATIBILITY_SURFACE
```

If `REMOVE`:

- remove only the unnecessary production executable/surface;
- preserve useful read-only internal factory/test capability if justified.

If retained temporarily:

```text
mutation capability = 0
```

Add mechanical evidence proving it cannot become a second Product mutation plane.

Record removal owner/stage if it remains temporary.

---

# 13. Operator / Worker / Test Boundaries

K6 must not confuse “one Product API” with “one protocol for every process”.

Preserve valid internal/infrastructure paths where current architecture requires them.

## Research Worker

Do not migrate Research Worker execution through public Product HTTP.

Worker remains an execution agent under existing durable:

```text
Run
Attempt
Lease
Fencing
Recovery
```

authority.

## Database / Backup / Migration

Keep explicit operator/infrastructure semantics.

Application startup must still not silently perform operator migration/repair work.

## Scenario / Testing

Direct Engine construction in tests and explicit scenario tooling is not a Product bypass.

Do not weaken internal testing merely to make source scans pass.

Use correct actor classification instead.

---

# 14. Required Architecture Tests

Add a focused K6 architecture suite, preferably:

```text
tests/architecture/test_p9_k6_external_client_boundary.py
```

or the current repository-equivalent location.

At minimum prove:

## TEST-K6-01 — Client Package Has No Core Dependency

Assert `onlyalpha-client` does not depend on `onlyalpha`.

Prefer package metadata verification plus source/import verification.

## TEST-K6-02 — Client Forbidden Imports

Client source must not import:

```text
onlyalpha.engine
onlyalpha.runtime
onlyalpha.kernel
onlyalpha.application
onlyalpha.persistence
onlyalpha.strategy
```

## TEST-K6-03 — Product CLI Has No Direct Engine/Runtime Construction

For commands classified as `PRODUCT_API_CLIENT`, mechanically prove absence of:

```text
OnlyEngine(...)
OnlyRuntime(...)
direct Product mutation-capable stores
direct mutation Application services
```

Use AST/import-aware tests where appropriate instead of fragile text grep.

## TEST-K6-04 — Generated Python Client Is Fresh

```text
canonical OpenAPI
→ regenerate
→ committed tree comparison
```

Fail on drift.

## TEST-K6-05 — Web Still Uses Governed Contract

Prove Web remains bound to canonical generated contract/client paths and has no Kernel imports.

## TEST-K6-06 — Product Examples Cannot Construct Engine

All examples classified as `PRODUCT` must not import/construct Engine/Runtime or mutation-capable persistence.

## TEST-K6-07 — Operator Direct Access Is Explicit

Operator/infrastructure exceptions must be an exact allowlist, not a broad “CLI may import anything” exception.

Unknown new direct infrastructure paths fail closed.

## TEST-K6-08 — No Client Fallback

Mechanically prove Product client/CLI has no fallback path from HTTP failure into local Engine/Application/Store execution.

## TEST-K6-09 — External Actor Classification Is Complete

The migration inventory must contain no:

```text
UNKNOWN
UNCLASSIFIED
```

external Product surface.

Prefer a machine-readable architecture contract if it reduces ambiguity and matches existing K0 patterns.

Do not add a new metadata framework unless current architecture already has an appropriate mechanism.

---

# 15. Required Client ↔ Server Integration Evidence

Architecture tests are insufficient.

Prove the new supported external path works end-to-end through the actual Product HTTP boundary.

Use the current test composition and real Product app factory.

## E2E-K6-01 — Create Research

```text
onlyalpha-client
→ HTTP
→ Product Command
→ existing Research authority
→ expected accepted result
```

Verify current contract semantics exactly.

## E2E-K6-02 — Get Research

```text
client.research.get(run_id)
→ same authoritative Run projection
```

## E2E-K6-03 — List Research

Preserve current:

```text
ordering
pagination
cursor semantics
```

No SDK-specific reinterpretation.

## E2E-K6-04 — Cancel Research

```text
client
→ HTTP
→ Product Command Dispatcher
→ existing cancellation authority
```

## E2E-K6-05 — Response-Loss / Retry Convergence

Simulate or characterize:

```text
mutation accepted
response considered lost
same command retried with same identity
→ same authoritative outcome
```

Reuse K5 deterministic barriers/evidence mechanisms where applicable.

Do not add timing sleeps as correctness mechanisms.

## E2E-K6-06 — Same Key / Different Command Conflict

Prove:

```text
same external command identity
+
different canonical command
→ deterministic conflict
```

## E2E-K6-07 — Server Unavailable

Prove:

```text
server unavailable
→ client transport failure
```

and no local Engine/Runtime/Store fallback occurs.

---

# 16. Expected Code Change Locality

K6 changes should concentrate around:

```text
pyproject.toml / workspace metadata

packages/client/onlyalpha-client/**

OpenAPI client generation script/config

src/onlyalpha/cli.py
or new explicitly classified CLI entrypoints

README.md
docs/**
examples/**

tests/architecture/test_p9_k6_external_client_boundary.py
client tests
small HTTP integration tests

docs/reports/p9_k6_external_client_migration.md
```

Potentially small supporting changes may occur elsewhere if current source requires them.

---

# 17. Files / Areas That Should Usually Not Receive Large Business Changes

If K6 requires broad edits in:

```text
src/onlyalpha/kernel/**
src/onlyalpha/strategy/**
src/onlyalpha/research/execution/**
src/onlyalpha/runtime/**
src/onlyalpha/portfolio/**
src/onlyalpha/risk/**
src/onlyalpha/execution/**
```

stop and reassess scope.

K6 is a client/authority migration task.

A large semantic rewrite in these areas is likely scope leakage.

---

# 18. Database / Persistence Rule

Expected:

```text
new PostgreSQL migration = 0
new business table        = 0
new SDK/client authority table = 0
```

Do not create:

```text
client session authority
SDK command table
CLI request table
```

merely for the client.

K5 already owns durable Product Command Receipt/recovery semantics.

K6 consumes them.

---

# 19. OpenAPI Compatibility Rule

Strong target:

```text
canonical OpenAPI semantic delta = 0
```

Prefer exact canonical bytes unchanged if current source allows.

If K6 changes canonical OpenAPI:

1. stop;
2. explain why a client migration requires a public Product semantic change;
3. run the current K4 governance/compatibility gates;
4. do not modify the accepted contract merely to make generated Python easier.

“SDK convenience” is not sufficient justification for a breaking/public semantic change.

---

# 20. P9.0 Semantic Preservation

Do not change:

```text
strategy_fingerprint
Candidate identity
Freeze semantics
Strategy Revision semantics
Execution Evidence
Equivalence Evidence
StrategyDecision semantics
Promotion semantics
```

Do not introduce:

```text
SDK strategy ID
API strategy ID
client-side Strategy revision identity
transport identity in semantic fingerprint
```

---

# 21. Explicit Non-Goals

DO NOT implement during K6:

```text
Binance integration
QMT trading
CTP trading
real Broker submission
new Portfolio model
new Risk model
LIVE permission

gRPC
K7 remote protocol foundation
QMT Gateway protocol implementation

K8 full Kernel seal
global removal of Engine/Runtime internals

new Product business endpoints only for legacy CLI compatibility
/engine/run
/engine/snapshot

new CQRS framework
new event-sourcing framework
message bus
Kafka
NATS
Temporal
Celery
GraphQL
generic API gateway
service mesh
microservice decomposition
multi-master Kernel HA

new semantic identity
new lifecycle authority
new persistence authority
new contract authoring authority
```

---

# 22. Stop Conditions During Implementation

Stop and reassess if any of these appear necessary:

```text
"To migrate the CLI we need to expose Engine over HTTP."

"To keep the example we need a Runtime API."

"The Python client should import onlyalpha because it is easier."

"If HTTP fails, the client can run locally."

"We need a second handwritten SDK schema."

"We need to change Strategy fingerprint for API/client identity."

"We need a new DB table to track SDK calls."

"We need to redesign Kernel Host to support the client."

"We need gRPC before the Product client can work."
```

These indicate the implementation is preserving the old authority model instead of solving it.

---

# 23. Implementation Sequence

Perform the task in narrow, reviewable phases.

## Phase A — Revalidate K0 Surface Inventory Against Current HEAD

Re-scan all current external/control surfaces.

Create a K6 migration matrix from current source.

Required properties:

```text
all external surfaces classified
unknown mutation authorities = 0
unclassified external surfaces = 0
```

Do not rewrite historical K0 evidence as if it were current authority.

## Phase B — Establish Python Product Client

Create `onlyalpha-client` with the minimum current Product operations.

Do not touch CLI first.

First prove:

```text
Python client
→ Product HTTP
→ current Product Boundary
```

## Phase C — Add Deterministic Python Client Generation

Canonical OpenAPI becomes the only Python transport-schema input.

Pin generation toolchain.

Add `write` / `check` style generation flow.

## Phase D — Client E2E Proof

Add Create/Get/List/Cancel and retry/conflict/unavailable integration evidence.

## Phase E — Migrate External Python Documentation / Examples

Normal Product usage moves to `onlyalpha-client`.

Classify or remove misleading direct Engine examples.

## Phase F — CLI Classification / Migration

Classify all commands.

Create/retain Product CLI only through API client.

Separate operator/test/legacy responsibilities.

Do not invent business endpoints.

## Phase G — Artifact-only / Remaining Surface Resolution

Resolve all remaining K0 `MIGRATE TO PRODUCT API` / compatibility debts relevant to K6.

No unknown state remains.

## Phase H — Mechanical Closure

Add architecture guards, generation freshness checks, reverse audit, and K6 report.

Only after all Task Gate evidence passes should K6 be marked verified.

---

# 24. K6 Migration Report

Create:

```text
docs/reports/p9_k6_external_client_migration.md
```

The report must be evidence, not a second current-state authority.

Include at least:

```text
TASK_BASE_SHA
IMPLEMENTATION_SHA / WORKTREE SHA as applicable

governing ADR/design references

before/after authority graph

current external surface inventory
actor classifications
migration decisions
remaining K8 debt

Python client package boundary
client dependency graph
canonical OpenAPI source
exact generator version/config
generated-client reproducibility result

Web verification result

CLI command classification table

artifact-only API decision

example/documentation classification

architecture gate results

client/server E2E results
retry convergence result
same-key-different-command result
server-unavailable result

OpenAPI before/after canonical SHA
generated TypeScript before/after SHA if relevant
generated Python projection identity if useful

P9.0 semantic delta = 0 evidence

new authorities introduced = 0 reverse audit

Task Gate verdict
```

Do not claim Final-SHA Certification unless that exact higher-level workflow is actually run and accepted.

---

# 25. Required Reverse Audit

After implementation, do not only prove “new client works”.

Search for unintended authority growth.

Explicitly answer:

```text
new semantic authority?              MUST BE NO
new product mutation authority?      MUST BE NO
new lifecycle authority?             MUST BE NO
new persistence authority?           MUST BE NO
new API contract authoring authority? MUST BE NO
new external direct Kernel path?     MUST BE NO
new fallback path?                   MUST BE NO
new hidden client retry identity?     MUST BE NO
```

Also verify:

```text
Strategy authority remains unique
Research authority remains unique
Product Command Receipt remains unique
Kernel readiness/mutation admission remains unique
canonical OpenAPI remains unique public contract projection
```

---

# 26. Task Gate

P9.K.6 is complete only if all of the following are true.

## Gate 1 — Surface Completeness

```text
current external surfaces classified = 100%
unknown external mutation authority   = 0
unclassified product surface          = 0
```

## Gate 2 — Supported External Actors

Every supported Product External Actor has an API path for every currently supported operation.

## Gate 3 — Python Product Client

```text
one official onlyalpha-client boundary exists
client → server E2E passes
client dependency on onlyalpha core = 0
```

## Gate 4 — Contract Authority

```text
canonical OpenAPI
→ TypeScript projection
→ Python projection
```

No second client schema authority exists.

## Gate 5 — Deterministic Client Projection

Same canonical contract + exact toolchain produces the same generated client projection.

## Gate 6 — CLI Closure

Every CLI capability is explicitly classified:

```text
PRODUCT_API_CLIENT
OPERATOR / INFRASTRUCTURE
TEST / SCENARIO
LEGACY_K8_TARGET
REMOVE
```

No supported Product CLI command directly controls Engine/Runtime.

## Gate 7 — Example / Documentation Closure

Product-facing examples teach Product API/client usage, not direct Engine ownership.

## Gate 8 — Retry / Conflict Correctness

```text
same key + same command
→ same outcome

same key + different command
→ conflict
```

through the actual client/HTTP path.

## Gate 9 — No Fallback

HTTP/client failure cannot fall back to local Kernel/Engine mutation.

## Gate 10 — Semantic Preservation

```text
Strategy semantic delta = 0
Research authority delta = 0
Kernel lifecycle authority delta = 0
Receipt/recovery authority delta = 0
```

## Gate 11 — Public Contract Compatibility

Prefer:

```text
canonical OpenAPI unchanged
```

If changed, current K4 compatibility gate must pass with an explicit justified change.

## Gate 12 — Reverse Audit

No new competing authority exists.

---

# 27. Verification Commands

Use the **current repository-defined** scripts and CI commands.

At minimum inspect and run the current equivalents of:

```bash
uv run python scripts/project_state.py check

uv run ruff check .
uv run mypy

uv run pytest tests/architecture -q
uv run pytest packages/client/onlyalpha-client/tests -q

# current API tests / Product HTTP integration tests
uv run pytest packages/api/onlyalpha-api/tests -q

# current OpenAPI governance
uv run python scripts/openapi_contract.py check

# current generated-client freshness command
uv run python scripts/openapi_clients.py check

# current web suite
uv run python scripts/web_suite.py

git diff --check
```

Do not blindly use these exact commands if the current repository has renamed/replaced them.

Run the smallest high-signal gates during development.

Before Task Gate closure, run the repository's required K6-relevant local verification set.

Do not inflate a higher-level coverage/Final-SHA requirement into the K6 Task Gate unless the current Quality System explicitly says it is part of this gate.

Do not weaken existing gates to make K6 pass.

---

# 28. Project State Completion

Only after:

```text
K6 implementation complete
+
K6 Task Gate evidence passes
+
reverse audit passes
+
report is current
```

use the repository's current project-state tooling to verify P9.K.6.

Expected conceptual transition:

```text
P9.K.6 ACTIVE
→ P9.K.6 TASK COMPLETE / VERIFIED
→ P9.K.7 IMPLEMENTATION READY
```

Use the actual current script syntax.

Do not manually edit generated project-state projections.

After transition:

```bash
uv run python scripts/project_state.py check
```

must pass.

Do not start P9.K.7 implementation inside this task.

---

# 29. Required Final Codex Response

At task completion, report concisely but exactly:

```text
1. TASK_BASE_SHA
2. final implementation/worktree SHA
3. files changed
4. external surfaces reclassified
5. Python client package created/updated
6. canonical contract → Python generation mechanism
7. Web migration/verification result
8. CLI classifications and actions
9. example/documentation actions
10. artifact-only API decision
11. integration tests added
12. architecture tests added
13. retry/conflict evidence
14. OpenAPI before/after identity
15. P9.0 semantic-delta statement
16. reverse-audit result
17. Task Gate result
18. project-state result
19. remaining explicit K8 debt
20. confirmation that K7 was not started
```

If a gate fails, report the failure honestly and leave P9.K.6 unverified.

---

# 30. Final Engineering Intent

The success criterion is **not**:

```text
"we now have a Python SDK"
```

The success criterion is:

```text
all supported external Product Actors
        ↓
one governed Product Control Plane
        ↓
one Product Command / Query path
        ↓
existing unique business authorities
```

while preserving:

```text
internal typed Python execution
operator/infrastructure tooling
worker authority
test composition
```

where those are legitimate non-Product roles.

P9.K.6 must complete an **Authority Migration**, not an “API-everything” rewrite.

The final architecture after K6 should make K8 a small, mechanical hard-seal task rather than a late discovery of hidden external Engine dependencies.

Implement the smallest set of changes that proves this architecture mechanically, deterministically, and without introducing a second authority.
