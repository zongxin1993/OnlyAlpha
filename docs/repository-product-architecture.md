# Repository and product architecture

This is the target architecture derived from the Constitution and [ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md).
It defines ownership, not implementation progress. Existing paths in development maps describe current source until their
atomic migration; this document does not claim that target paths or release guards already exist.

## Repository structure

```text
Cargo.toml / Cargo.lock                 one root workspace and development lock
crates/
  onlyalpha-kernel/                     grouping directory, no additional crate
    domain/  predicates/  clock/  event/  calculation/  strategy/
    market_data/                       grouping directory, no additional crate
      state/  construction/  delivery/  pipeline/
    order/  position/  account/  strategy_ledger/  risk/
    fee/  settlement/  margin/  broker/  execution/
  onlyalpha-integration-contract/
  onlyalpha-metadata-json/
  onlyalpha-gateway-protocol/
  onlyalpha-runtime-persistence/
  onlyalpha-calculation-bridge/
  onlyalpha-backtest/
packages/
  backend/
    Cargo.toml
    src/
      main.rs  lib.rs
      application/                     Watchlist, Workspace, Integration, Research, Trading flows
      transport/                       HTTP/WebSocket and DTO mapping
      security/                        authentication, authorization and Source grants
      persistence/                     Product stores and schema migration integration
      execution/                       composition using reusable libraries
      runtime_generation/              exact environment/binding/activation lifecycle
      agent/                           Agent workflow and formal Product API client
      workers/                         task claim, supervision, shutdown and recovery
      bootstrap/                       explicit startup configuration and assembly
    python/                            minimal algorithm runtime/SDK sources and resources
    tests/
  frontend/                            Shipping Web UI
plugs/                                 concrete Provider/Market/Broker/algorithm plugins
contracts/                             canonical versioned Product and cross-boundary protocols
deploy/  scripts/                       deployment and engineering tools
```

The twenty Kernel crates retain their current functional and isolation boundaries. The six other libraries belong outside
Kernel; SQLite, Python process/transport and Provider dependencies do not become canonical trading semantics. Directory names
are not independent deployments. Do not add empty future modules, per-file crates, nested workspaces or a forwarding facade.
`predicates/` owns package `onlyalpha-predicates`; it replaces former `core/` / `onlyalpha-kernel`, not the entire Kernel.
Backend owns package/binary `onlyalpha-backend`; frontend owns package `onlyalpha-frontend`. Release metadata placement is in
[release versioning](release-versioning.md). This is target naming, not an assertion of current manifests.

## Library and module boundaries

| Boundary | Responsibilities and allowed direction |
|---|---|
| Domain | Canonical values; no Runtime, backend, DB, network or concrete plugin dependency |
| Predicates, Clock, Event, Calculation, Strategy | Retain their owning semantic contracts and explicit lower-layer dependency closures |
| Market Data State/Construction/Delivery/Pipeline | Preserve construction/value reuse without forcing plugin/Strategy consumers to import Pipeline or process code |
| Order/Position/Account/Ledger/Risk/Fee/Settlement/Margin/Broker | Separate component owners; no direct mutation of another owner's private state |
| Execution | Pure planning and ordered commit/recovery coordination through owning ports; no concrete persistence/venue driver |
| Integration/metadata/protocol libraries | Shared SPI, exact normalization/fingerprints and generated bindings; never depend on Product business |
| Runtime persistence | Concrete Trading store/replay implementation outside Kernel; not Product PostgreSQL ownership |
| Calculation bridge | Algorithm protocol/client and reusable Calculation/Strategy adapters; consumes an explicitly supplied process/transport boundary |
| Backtest | Immutable-input replay/run-loop using the same Kernel; no Product admission, user authorization or task queue ownership |
| Plugins | Concrete external rules and algorithms through public contracts; no backend-internal dependency |

Calculation parameters, graph, registry and recovery remain internal modules of Calculation. Allocation/reservations/valuation
remain with their appropriate Position/Account/Risk owners; performance remains with its owning Account/Ledger/Execution
contract. Do not extract generic reservation, checkpoint, recovery or worker-manager crates merely because names recur.

Backend's `transport` calls Application Commands/Queries; it does not bypass them to mutate DB/Kernel state. Product persistence
implements owning business storage without exposing databases as cross-node integration APIs. `execution` assembles library
ports; `workers` coordinates existing Run/Attempt/Generation authorities rather than creating another status or binding store.
Bootstrap owns configuration and construction, not business decisions. Agent remains a formal API consumer even in the same
product package. Reusable libraries never import backend modules. Internal library targets for binary reuse are not separate
release units or external Product-control APIs.

## Processes and lifecycle

Default operator startup uses one `onlyalpha-backend` executable with `serve` and `worker` roles. Multiple processes are allowed
for actual fault/resource/security/lifecycle or exact Generation isolation; no package or service per worker. These startup
commands do not provide business operations around the Shipping UI/API. Deployment tools keep node/container lifecycle;
backend supervises its admitted workers/algorithm children without competing supervisors or duplicate Authority.

API/control remains responsive during bounded execution load. Execution workers claim only work admitted to their exact
implementation/Generation. Agent may run separately for model/network latency and credential isolation. Python runs as an
explicitly managed algorithm child; process isolation alone is not authentication, authorization or a security sandbox.
Native process spawning/supervision belongs in backend; the reusable bridge accepts the supplied channel/lifecycle port.

Cross-process interactions use explicit contracts and owning durable admission/claim APIs, not arbitrary DB integration.
On crash, recover from existing durable facts/leases/reconciliation. Preserve cancellation, observation, UNKNOWN and risk
reduction; no blind retry, second order identity or inferred success. Deterministic fault tests cover API restart, worker
termination, child failures and interrupted durable boundaries. Role/permission checks precede claim and execution.

All roles and base Python resources ship under one backend version. Old backend/worker artifacts can remain for already-bound
work; new activation/rollback changes only new-work selection under ADR 0117. Version equality is not permission to claim work,
and a process restart is not a valid handover protocol. Keep required historical artifacts, readers, facts and keys.

## Original package to target responsibility map

This maps the original package responsibilities, not automatic whole-directory moves or a completion checklist.

| Current `packages/onlyalpha-*` | Target |
|---|---|
| `web-console` | `packages/frontend` |
| `http-server` | backend transport/security/bootstrap and program entry |
| `product-runtime` | backend Application, Product persistence and execution composition modules |
| `integration-contract`, `metadata-json` | corresponding `crates/onlyalpha-*` libraries |
| `gateway-protocol` | Rust library, canonical protocol source in `contracts/`, Python bindings in backend resources |
| `runtime-persistence` | reusable non-Kernel Runtime persistence library |
| `backtest-driver` | reusable `onlyalpha-backtest`; admission/task/process entry belongs in backend |
| `calculation-worker` | reusable `onlyalpha-calculation-bridge`; native supervision in backend; minimal Python code in backend resources |
| `authoring-execution-worker` | backend authoring execution/worker modules; remaining Python business must migrate before retirement |
| `runtime-generation-manager` | backend Generation modules, preserving the sole existing ledger/binding Authority |
| `agent-orchestrator` | backend Agent modules/role with formal Product API access |

Moving Python business into `backend/python` is not Rust migration. A retained interim implementation must be explicitly
classified in task context and follow the existing official-writer binding. No general compatibility re-export is added.

## Python resources, releases and retirement

Backend ships a platform-specific minimal interpreter/environment, executor, authoring SDK, bindings, licenses and exact
dependency artifacts/provenance. Internal wheels may be build constituents; they are not worker product release lines.
Use one authoritative dependency description per actual installation closure; package metadata, SDK builder and deployment
must agree. Do not resolve latest packages on startup or use the host venv/node_modules as container dependencies.

Algorithm plugins and materialized immutable private Revisions enter exact isolated environments through existing artifact,
Catalog and Runtime Generation contracts. Changing a private Factor need not rebuild backend. Changing bundled executor/SDK
content requires a backend release. Python cannot own Product stores, Commands, trading state or Generation selection.

The library set, backend and frontend release independently; plugins have their own distribution versions. Build inputs bind
exact library/plugin content, locks, toolchain, features, target and relevant non-secret configuration. Frontend/backend
compatibility is API-contract evidence for declared combinations, not matching version numbers. See
[release versioning](release-versioning.md) for metadata, tags and refusal rules.

Every selected Rust migration includes removal of obsolete Python code when its actual callers and semantic/product/recovery
gates permit. Preserve independent expected vectors and fault/replay assertions; delete obsolete dual-implementation-only
wiring after replacing its useful assertions. Retain the minimal Python algorithm API where still genuinely needed, not an
entire second Kernel. Exact historical artifact/readers remain under their owning contracts, without new legacy loaders or
source shims. [The work program](repository-migration-work-program.md) defines sequencing and required proofs; it does not
declare a module migrated or authorize deletion by directory name.
