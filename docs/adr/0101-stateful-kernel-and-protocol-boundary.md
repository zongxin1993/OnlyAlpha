# ADR 0101: Stateful Kernel and Protocol Boundary

- Status: Accepted
- Date: 2026-08-25
- Planning baseline: `0e6d3f0b3408f7125d8ce68460c9a7df62f86708`

## Context

P8 already established a durable Research control plane and an external HTTP surface. The current `onlyalpha-api` package uses FastAPI/Pydantic/Uvicorn, publishes a generated OpenAPI contract, requires UUID4 idempotency for Research submission, returns `202 Accepted` only after durable PostgreSQL commit, and keeps Worker/Engine execution outside the HTTP request lifecycle.

P9.0 then established a much stronger semantic authority chain: exact Research execution evidence, exact RESEARCH/TRADING equivalence evidence, unique Candidate Freeze, immutable Strategy Revision identity, read-only runtime Strategy authority, append-only Promotion, and deterministic publication/reconciliation rules.

At the same time the repository still exposes product-operation capabilities through multiple Python surfaces. The top-level `onlyalpha` package exports Engine/Runtime/Cluster types, the `onlyalpha` CLI directly constructs `OnlyEngine`, and some operator CLI paths directly access persistence/application objects. If Portfolio, Risk, Execution, Broker and LIVE product work grows on top of those surfaces, OnlyAlpha would accumulate multiple external mutation paths and make authorization, idempotency, audit, recovery and future Agent control harder to keep uniquely authoritative.

The project therefore needs an architecture gate between P9.0 and P9.1. The gate is not an HTTP rewrite and is not a microservice migration. It changes the product ownership model from "external code controls a Python framework" to "a long-lived OnlyAlpha Kernel owns business state transitions and external actors submit intent through one product boundary".

## Decision

### 1. Insert P9.K before P9.1

After P9.0 is fully closed under the project owner's chosen gate policy, the next architecture stage is:

```text
P9.0
Strategy / Evidence / Freeze authority foundation
        ↓
P9.K
Stateful Kernel & Protocol Boundary
        ↓
P9.1+
Market Product / Data / Broker / LIVE vertical
```

P9.K does not alter the certified P9.0 Strategy identity, Freeze, Execution Evidence, Equivalence Evidence, StrategyDecision or Promotion semantics.

### 2. OnlyAlpha becomes a Stateful Quant Kernel

The target product identity is a modular, long-running Stateful Quant Kernel that owns:

```text
identity authority
state-transition authority
lifecycle authority
execution orchestration authority
recovery authority
persistence coordination authority
```

A Kernel may be composed from multiple explicit domain/application authorities. `OnlyAlphaKernel`/Kernel Host, if introduced, is composition/lifecycle infrastructure and MUST NOT become a god object containing all business rules.

### 3. External actors submit intent; Kernel produces facts

Product external actors include Web, Python SDK, Agent, automation, notebook integrations and any retained CLI UX.

They may submit Commands/Queries and exact references. They MUST NOT author authoritative facts such as:

```text
Research terminal state
Strategy Revision content
implementation provenance
admission verdict
Promotion fact
Runtime internal state
Broker execution fact
```

The Kernel/Application authority resolves, validates, transitions and persists those facts.

### 4. There is one Product Control Plane contract

The architectural product boundary is a versioned OpenAPI contract over HTTPS/JSON.

The initial HTTP adapter remains FastAPI because the repository already has a working FastAPI/OpenAPI Research API. FastAPI is a replaceable adapter, not a Kernel dependency and not an architectural authority.

```text
External Actor
    ↓ HTTPS / JSON
OpenAPI Product Contract
    ↓
FastAPI Adapter
    ↓
Command / Query Boundary
    ↓
OnlyAlpha Kernel
```

`src/onlyalpha` MUST NOT depend on FastAPI, Starlette, HTTP request objects or API DTOs.

### 5. API DTO, Domain model and Persistence schema are distinct

HTTP/Pydantic models are transport contracts. Domain values remain framework-neutral. Persistence models remain infrastructure contracts.

Explicit mapping is required:

```text
API DTO
  ↓
Application Command / Query
  ↓
Domain / Authority
```

No public API DTO may become a second Strategy/Research/Execution semantic authority.

### 6. Command and Query are separate product semantics

A Command requests an authoritative state transition. A Query observes existing facts/projections.

HTTP resources MUST express domain intent rather than generic CRUD state mutation. For example, a client may request Freeze/Promotion/Cancellation; it may not PATCH a Strategy or Run into an arbitrary state.

Queries MUST NOT create hidden state transitions.

### 7. Long-running work is durable and detached from HTTP request lifetime

Research, Backtest, SIM and later Deployment are durable lifecycle resources. HTTP acceptance ends after the authoritative command is durably admitted; execution continues under Kernel/Worker/Runtime lifecycle authority.

P8 Research Run semantics are the reference pattern rather than a compatibility obstacle.

### 8. Product mutation is idempotent at the transport/application boundary

Network retry MUST NOT create duplicate authoritative mutations.

A retained `Idempotency-Key`/External Command identity binds to a canonical Command fingerprint and prior outcome. Same key + same command replays the same outcome; same key + different command conflicts.

Transport/audit identity (request ID, idempotency key, actor, HTTP metadata, API version) MUST NOT enter Dataset, Calculation, Candidate or Strategy semantic fingerprints.

### 9. Kernel lifecycle is explicit and fail-closed

The target lifecycle is conceptually:

```text
CREATED
→ BOOTING
→ VERIFYING
→ RECOVERING
→ READY
→ DRAINING
→ STOPPED

any unrecoverable verification failure
→ FAILED
```

Mutation Commands are rejected before `READY`. Startup validates semantic namespace, operational schema compatibility, registered implementations, durable state and required projections. Startup does not silently migrate or repair semantic truth.

### 10. First implementation uses one logical Control-Plane Authority

P9.K V1 is a modular monolith/control-plane service, not a multi-master system.

Running multiple independent FastAPI worker processes that each host a mutation-capable Kernel is forbidden unless a later ADR introduces explicit leader election, epoch/fencing and recovery semantics.

Research Workers may remain separate execution agents because they do not become the Research Run lifecycle authority.

### 11. Kernel state is partitioned by authority

Stateful does not mean serializing the whole process or placing all state in PostgreSQL.

```text
Immutable Semantic State
→ content-addressed semantic stores

Operational Lifecycle State
→ PostgreSQL authorities

Runtime Mutable State
→ deterministic memory state + explicit checkpoint/durable facts

External Execution State
→ Broker/Venue authority + reconciliation evidence
```

Recovery proceeds by authority. Pickling/restoring a complete Kernel object is not an accepted recovery model.

### 12. Internal Kernel communication remains direct and typed

The deterministic Trading chain remains explicit direct calls:

```text
Observation
→ Strategy
→ StrategyDecision
→ Portfolio
→ Risk
→ Order Intent
→ Execution
```

P9.K MUST NOT replace this chain with HTTP or a generic asynchronous event bus.

### 13. Control Plane and Data Plane are different

OpenAPI is the public product Control Plane. High-frequency market data and broker execution streams are Infrastructure/Data Plane concerns and are not forced through REST.

Provider adapters continue to enter stable Kernel-defined ports.

### 14. Remote infrastructure RPC uses a separate contract when required

For future process/OS boundaries such as Linux Kernel ↔ Windows QMT Gateway or Kernel ↔ CTP Gateway, the preferred direction is Protobuf + gRPC.

This is an infrastructure protocol, not a second public product API and not a P9.K requirement to implement every gateway.

### 15. AsyncAPI/message infrastructure is deferred until a proven need

If future Market/Broker/Runtime streams require multi-process, multi-consumer event contracts, AsyncAPI may describe that contract and a transport such as NATS may be evaluated.

P9.K MUST NOT introduce Kafka/NATS/Redis/event-bus infrastructure merely for architectural appearance. Deterministic in-process business pipelines remain direct typed calls.

### 16. Existing direct product paths are migration targets, not permanent authorities

Current top-level Engine/Runtime exports and direct Kernel-mutating CLI behavior may remain temporarily during staged migration, but P9.K must inventory them, migrate legitimate external use to the Product Control Plane, and mechanically seal unsupported direct mutation paths by the final P9.K increment.

If CLI UX is retained, it becomes an OpenAPI client. If a Python SDK is retained, it is a separate `onlyalpha-client` style API client rather than a package that imports mutation capabilities from `onlyalpha`.

### 17. OpenAPI is governed as a product contract

OnlyAlpha uses code-authoritative, contract-frozen API governance:

```text
FastAPI routes + API DTO
        ↓
generated OpenAPI
        ↓
canonical contract
        ↓
lint / breaking-change check / client generation
```

The generated contract is a versioned projection of the HTTP adapter, not a hand-maintained competing authority. Breaking public changes require an explicit compatibility decision or new API version.

API contract fingerprints/version metadata MUST NOT enter Strategy identity.

## Consequences

- P8 Research HTTP work is reused and generalized rather than replaced.
- FastAPI remains useful but becomes explicitly replaceable.
- Web, Agent, SDK and optional CLI converge on one product contract.
- Kernel internals remain network-free and strongly typed.
- P9.1+ Market/Broker/LIVE features grow behind an already-sealed product boundary instead of adding new direct Python control paths.
- Future QMT/CTP gateways can use a machine-to-machine protocol without polluting the public OpenAPI surface.
- P9.K increases architecture/recovery work before adding market features, but substantially reduces later LIVE authorization, retry, split-brain and bypass risk.

## Non-goals

P9.K does not by itself implement:

- Binance market integration;
- QMT or CTP live trading;
- real Broker submission;
- Portfolio/Risk redesign;
- LIVE execution permission;
- Kubernetes or service mesh;
- multi-master Kernel HA;
- generic workflow engine;
- Temporal/Celery as lifecycle authority;
- Kafka/NATS as mandatory infrastructure;
- GraphQL as product control plane;
- full microservice decomposition.

## Implementation plan

The normative execution plan is maintained in [`../p9_k_stateful_kernel_protocol_boundary.md`](../p9_k_stateful_kernel_protocol_boundary.md).