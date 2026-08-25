# OnlyAlpha Session Handoff — P9.0 Closure-3 → P9.K Stateful Kernel

- Date: 2026-08-25
- Repository: `zongxin1993/OnlyAlpha`
- P9.K architecture PR: #71, merged as `e5456e4dfb2e405b1471308c3dd97b25f61e33e5`
- Purpose: allow a new ChatGPT/Codex/engineering session to recover the current architecture context quickly without reconstructing the full conversation history.

---

## 1. Start here in the next session

Read these before proposing or implementing anything:

1. `AGENTS.md`
2. `docs/adr/0097-strategy-revision-freeze-and-promotion-authority.md`
3. `docs/adr/0100-p9-0-evidence-soundness-and-publication-convergence.md`
4. `docs/adr/0101-stateful-kernel-and-protocol-boundary.md`
5. `docs/p9_k_stateful_kernel_protocol_boundary.md`
6. `docs/roadmap.md`
7. `docs/p9_production_trading_vertical_architecture.md`
8. current `master`

This handoff is navigation/context only. Current source, tests and accepted ADRs remain authoritative. If `master` moved, re-audit the actual current repository before coding.

---

## 2. Engineering philosophy

OnlyAlpha repeatedly optimizes for:

```text
one fact
→ one authority

one semantic identity
→ one deterministic interpretation

one product transition
→ one legal path

unknown / ambiguous / partially verified
→ fail closed
```

Prefer explicit ownership, immutable semantic facts, append-only historical evidence, exact fingerprints, deterministic recovery, narrow changes and mechanical architecture guards.

Do not add generic frameworks, compatibility layers, workflow engines, message buses, service meshes or distributed systems unless a concrete requirement proves they are necessary.

---

## 3. P9.0 semantic foundation that P9.K must preserve

P9.0 establishes:

```text
Research
  ↓
exact Candidate
  ↓
Freeze + Trading Admission
  ↓
immutable Strategy Revision
  ↓
strategy_fingerprint
  ↓
Strategy Execution Resolver
  ↓
exact execution plan
  ↓
Calculation TRADING backend
  ↓
StrategyDecision
  ↓
future Portfolio / Risk / Order / Execution
```

### Strategy identity

`strategy_fingerprint` is the sole Strategy semantic/executable identity.

Do not introduce a second authoritative Strategy revision UUID/version, Runtime-specific identity, API-specific identity or deployment-specific Strategy identity.

### Candidate cannot execute

Only Freeze may perform:

```text
Candidate → Strategy
```

No Web/API/CLI/Runtime/operator path may bypass Freeze.

### Freeze callers submit references, not facts

Freeze callers may provide Research Run/Result/Candidate references. They must not author Strategy graph, implementation bindings, admission verdict, equivalence result, frozen Strategy object or execution plan.

### Market Input semantics remain Strategy semantics

Examples include BAR semantics, step/aggregation, price type, aggregation source, adjustment semantics/reference and FINAL/CLOSED admission.

Dataset snapshot and Research date range do not enter Strategy identity.

### Exact implementation identity matters

Research/Trading exact implementation fingerprints participate in Strategy admission. Git SHA is not implementation semantic identity by itself.

### StrategyDecision stays narrow

StrategyDecision owns Strategy signals such as ELIGIBILITY/ENTRY/EXIT plus exact observation facts. It must not become an Order, Portfolio, Position, Risk or Broker DTO.

### Legacy callback Strategy authority stays removed

Do not restore product-level arbitrary Python callback/class-path Strategy authoring/injection.

### Promotion remains append-only

Conceptual progression remains:

```text
RESEARCH → BACKTEST → SIM → LIVE_ELIGIBLE
```

`LIVE_ELIGIBLE` is admission, not active deployment permission.

---

## 4. P9.0 Closure-3 state

Planning baseline observed immediately before P9.K design:

```text
0e6d3f0b3408f7125d8ce68460c9a7df62f86708
P9.0 Closure-3 — Evidence Soundness & Publication Convergence
```

Repository state at that point:

```text
IMPLEMENTED
LOCAL DETERMINISTIC GATES PASS
REMOTE CERTIFICATION NOT RUN
```

The prior Closure-3 Codex task explicitly did **not** require triggering/waiting for GitHub Final-SHA Certification. Do not automatically run remote Final-SHA workflows unless the project owner explicitly asks.

Closure-3 froze three important rules:

1. admission-grade Research Execution Evidence must originate from actual authoritative Research backend execution, not a caller-constructed DTO claim;
2. Research/Trading equivalence certification must be exact-node and parameter/state-aware, crossing meaningful warmup/steady-state/transition horizons;
3. executable Strategy semantic truth includes verified Strategy Revision plus immutable verified Freeze relation(s), while PostgreSQL Strategy rows are operational/query projections that must converge from semantic truth.

Do not replace that model with filesystem/PostgreSQL 2PC/XA.

---

## 5. Why P9.K was inserted before P9.1

The owner decided to pause the original P9.1 Binance/production-market sequence and first establish the product boundary:

```text
P9.0
Strategy / Freeze / Promotion authority foundation
        ↓
P9.K
Stateful Kernel & Protocol Boundary
        ↓
original P9.1+
Market Product / Binance / Data / Broker / LIVE
```

Reason: P9.0 is now precise enough to standardize how the product is controlled before Portfolio/Risk/Broker/LIVE create many more external mutation paths.

---

## 6. P9.K target product identity

P9.K is **not** “add FastAPI”.

Target:

```text
OnlyAlpha = long-lived Stateful Quant Kernel
```

The Kernel owns:

```text
Identity Authority
State Transition Authority
Lifecycle Authority
Execution Authority
Recovery Authority
Persistence Coordination Authority
```

The control relationship changes from:

```text
user program
→ import onlyalpha
→ construct Engine/Runtime
→ call business functions
```

to:

```text
OnlyAlpha Kernel is running
↑
external actor submits Intent / Query
```

External actors no longer own business lifecycle.

---

## 7. External intent, Kernel fact

Product External Actors include:

```text
Web
Python SDK
Agent
Automation
Notebook
CLI if retained
external product service
```

They may submit Intent/Reference and query facts. They may not author authoritative facts directly.

Correct examples:

```text
CreateResearchRun(specification reference)
FreezeStrategy(research run reference, candidate fingerprint)
PromoteStrategy(strategy fingerprint, target stage, evidence references)
StartBacktest(strategy fingerprint, scenario/profile reference)
```

Incorrect examples:

```text
set Run.state = COMPLETED
publish caller-built StrategyRevision
submit admission verdict
submit implementation bindings
patch promotion status
write frozen Strategy directly
```

This principle must eventually be enforced mechanically, not just documented.

---

## 8. Protocol architecture

### Public Product Control Plane

Architecture contract:

```text
HTTPS / JSON
+
versioned OpenAPI
```

Initial adapter implementation:

```text
FastAPI
```

Important distinction:

```text
OpenAPI Product Boundary = architecture
FastAPI = replaceable adapter implementation
```

FastAPI/Starlette/Pydantic transport concerns must not become Core/Domain/Kernel dependencies.

### Kernel internal communication

Within a process/module boundary use:

```text
strongly typed Python interfaces
+
explicit direct calls
```

Do not convert Strategy → Portfolio → Risk → Execution into HTTP or internal pseudo-microservices.

### Future remote infrastructure protocol

Preferred future direction for real process/OS boundaries:

```text
Protobuf + gRPC
```

Examples:

```text
Linux Kernel ↔ Windows QMT Gateway
Kernel ↔ CTP Gateway
Kernel ↔ remote Runtime
```

This is not an early P9.K implementation requirement.

### Future asynchronous Data Plane

AsyncAPI/message infrastructure is deferred until a real multi-consumer/cross-node event-stream requirement exists.

Do not introduce NATS/Kafka now merely for architectural appearance.

---

## 9. Existing repository facts P9.K must build on

### Existing `onlyalpha-api`

The repository already contains:

```text
packages/api/onlyalpha-api
```

It already uses FastAPI/Pydantic/Uvicorn and generated OpenAPI.

Existing Research patterns already match much of the desired product boundary:

```text
UUID4 Idempotency-Key
202 Accepted after durable commit
long-running execution detached from HTTP request lifetime
deterministic pagination
strict HTTP DTO/error contracts
```

P9.K should generalize/reuse this platform. Do not casually build a parallel second API stack.

### Existing Research command/query concepts

Research already contains command/query/operations boundaries. Reuse correct semantics; do not introduce a generic enterprise CQRS/event-sourcing framework.

### Existing long-running execution authority

Research Run/Attempt/Lease/Worker/Recovery already separates durable lifecycle from HTTP request lifetime.

Do not replace it with Temporal/Celery lifecycle state.

### Current direct public Python surface

`src/onlyalpha/__init__.py` currently exposes Engine/Runtime/Cluster and other types. This is a P9.K migration surface.

Do not remove everything blindly before K0 inventory/classification.

### Current CLI direct paths

`src/onlyalpha/cli.py` directly constructs `OnlyEngine` and directly accesses operational infrastructure for some commands.

Long-term target:

```text
CLI removed
or
CLI → OpenAPI client
```

The CLI must not remain a second direct business mutation authority.

Operator infrastructure tooling may remain separate when its authority is explicitly operational/infrastructure rather than Product API.

---

## 10. Stateful Kernel state model

Stateful does not mean “everything in RAM” or “everything in PostgreSQL”.

Keep four categories explicit.

### Semantic State

Examples:

- Dataset Snapshot;
- Calculation/Research Result;
- Research Artifact;
- Execution Evidence;
- Equivalence Evidence;
- Strategy Revision;
- Freeze semantic relation.

Use existing immutable/verified authorities.

### Operational State

Examples:

- Run;
- Attempt;
- Lease;
- session lifecycle;
- command/idempotency mapping;
- query projections.

PostgreSQL is appropriate where already designed as operational authority.

### Runtime State

Examples:

- stateful calculation state;
- runtime session state;
- in-flight execution state;
- recoverable projections.

Use explicit checkpoint/ledger semantics where required.

### External State

Broker/exchange may be authoritative for external order/fill/account/position facts. OnlyAlpha must canonicalize/reconcile them; local persistence must not pretend to overwrite external truth.

---

## 11. Kernel lifecycle target

A Stateful Kernel needs an explicit lifecycle separate from “Uvicorn is running”.

Conceptual target:

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

Failure:

```text
FAILED
```

Mutation commands are admitted only when the Kernel is `READY`.

Critical mismatches such as semantic namespace incompatibility, required DB schema incompatibility, implementation registry conflicts, corrupt frozen Strategy authority or unrecoverable required checkpoint ambiguity must fail closed.

---

## 12. Command / Query boundary

P9.K should formalize:

```text
Command
→ requests an authoritative state transition

Query
→ reads existing authoritative facts/projections
```

Use explicit product commands, not a generic CQRS framework.

Potential commands:

```text
CreateResearchRunCommand
CancelResearchRunCommand
CertifyCalculationCommand
FreezeStrategyCommand
PromoteStrategyCommand
StartBacktestCommand
StartSimulationCommand
```

Potential queries:

```text
GetKernelStatusQuery
GetResearchRunQuery
GetStrategyQuery
GetPromotionQuery
GetBacktestQuery
GetSimulationQuery
```

HTTP adapters map DTOs to these boundaries and remain thin.

---

## 13. API design rules

### OpenAPI is the external product contract

Preferred governance:

```text
code-authoritative implementation
→ generated OpenAPI
→ canonical/versioned contract artifact
→ lint
→ breaking-change check
→ generated client
```

Do not hand-maintain a second independent OpenAPI YAML authority unless a later ADR intentionally adopts spec-first.

### FastAPI stays outside Kernel

Target:

```text
FastAPI route
→ API DTO
→ mapper
→ Command / Query
→ Application/Kernel authority
```

Routes must not own Strategy fingerprints, admission logic, domain state machines, semantic store publication or Broker business authority.

### Separate schemas

Keep distinct:

```text
API Schema
Domain Schema
Persistence Schema
```

Do not use one model as HTTP DTO + Domain Entity + DB schema.

### Avoid generic CRUD for domain transitions

Prefer explicit operations such as Freeze/Promotion/Cancellation over `PATCH status`.

---

## 14. Long-running operations and idempotency

Research/Backtest/SIM/future Deployment must not depend on a long-held HTTP request.

Preferred pattern:

```text
POST command
→ durable accept/commit
→ 202/operation identity
→ durable asynchronous lifecycle
→ GET/query status
```

Use deterministic retry semantics.

Existing Research `Idempotency-Key` behavior is the reference pattern:

```text
same key + same canonical command
→ same outcome

same key + different command
→ conflict
```

Transport/audit fields must not enter semantic fingerprints, including request id, idempotency key, actor, JWT, IP, API version and HTTP headers.

---

## 15. Process topology: avoid split brain

P9.K V1 should use one logical authoritative Control Kernel.

Do not accidentally create:

```text
FastAPI worker A → independent Kernel A
FastAPI worker B → independent Kernel B
```

Initial safe topology:

```text
one authoritative control-plane process
  ├── FastAPI adapter
  └── Stateful Kernel host

plus

Research workers × N
```

Workers are execution agents under durable authority, not second product lifecycle authorities.

Do not introduce multi-master HA/Raft/service mesh during P9.K. If HA is later required, design explicit ACTIVE/STANDBY + lease/epoch/fencing as a separate problem.

---

## 16. Recovery is first-class

Restart must be a normal supported lifecycle scenario.

Conceptual recovery:

```text
Boot
→ verify semantic authorities
→ load operational state
→ inspect unfinished sessions/attempts
→ load explicit checkpoints where required
→ reconcile projections
→ later reconcile external broker facts
→ READY
```

Do not pickle/restore a whole Kernel object.

Recover each authority from its own durable contract.

Target:

```text
crash + restart → deterministic convergence
```

within explicitly supported boundaries.

---

## 17. Control Plane vs Data Plane

Public REST/OpenAPI is the Control Plane, appropriate for create/start/stop/freeze/promote/deploy/query operations.

High-rate bars/ticks/execution reports/fills/order updates belong to Infrastructure/Runtime ports and future streaming protocols where necessary.

Do not POST every tick/bar through the public Product API merely to make the system “API-only”.

---

## 18. QMT / CTP / Binance direction

Long-term target platforms remain:

- China A-share via QMT;
- China futures via CTP;
- crypto via Binance.

P9.K is not their full implementation milestone.

QMT’s Windows constraint naturally fits:

```text
Linux OnlyAlpha Stateful Kernel
        │
        │ future Protobuf/gRPC internal infrastructure contract
        ▼
Windows OnlyAlpha QMT Gateway
        │
        ▼
MiniQMT / xtquant
```

The Gateway is Infrastructure, not a public Product API and not Strategy/Risk/Order authority.

---

## 19. External client target

Long-term public product usage should not rely on:

```python
from onlyalpha import OnlyEngine
```

for business operations.

Preferred external Python product surface:

```text
onlyalpha-client
→ generated/wrapped OpenAPI client
→ HTTPS
→ Product Control Plane
```

Web/Agent/Automation/CLI similarly become API clients.

Internal Python Application/Kernel interfaces remain valid internal contracts; the goal is to stop treating them as public product compatibility APIs.

---

## 20. Technology evaluation conclusion

Alternatives discussed included Litestar, Connexion/spec-first OpenAPI, gRPC everywhere, GraphQL, Django/DRF, AsyncAPI, NATS/Kafka, Temporal and Celery.

Current conclusions:

- **FastAPI**: retain as current HTTP adapter because it already exists and is sufficient when thin/replaceable;
- **OpenAPI**: retain as public product contract and generated-client basis; strengthen governance rather than replace it;
- **Litestar**: credible but no sufficient migration value while FastAPI is only an adapter;
- **Connexion/spec-first**: interesting but risks dual-maintenance authority in the current phase;
- **gRPC/Protobuf**: preferred future remote infrastructure/gateway protocol, not primary public API;
- **AsyncAPI**: useful later for real asynchronous cross-process contracts;
- **NATS/Kafka**: defer until demonstrated multi-consumer durable event distribution is needed;
- **Temporal/Celery**: do not introduce now because they would overlap Run/Attempt/Lease/Recovery lifecycle authority;
- **GraphQL/Django**: no material benefit for the current command/authority-oriented product boundary.

Potential future OpenAPI governance tools discussed: Redocly CLI and `oasdiff`.

---

## 21. P9.K implementation stages

Detailed design: `docs/p9_k_stateful_kernel_protocol_boundary.md`.

Agreed sequence:

```text
K0  Architecture Freeze & Surface Inventory
K1  Kernel Host & Lifecycle
K2  Product Command / Query Boundary
K3  Unified Product Control Plane / FastAPI adapter
K4  OpenAPI Contract Governance
K5  Long-running / Idempotency / Recovery closure
K6  External Client Migration
K7  Remote Protocol Foundation
K8  Seal Kernel
```

Do not skip K0 and jump directly to adding endpoints.

---

## 22. Next task: K0 Surface Inventory & Architecture Freeze

K0 should begin from a **fresh current-repository audit**.

Inventory every externally reachable product control/mutation surface, including at least:

- `src/onlyalpha/__init__.py` exports;
- `src/onlyalpha/cli.py`;
- project script entry points;
- `packages/api/onlyalpha-api`;
- Web transport usage;
- `src/onlyalpha/application/*`;
- Research command/query/operations packages;
- direct Engine construction in examples/tests/scripts;
- direct Runtime construction;
- semantic store writers;
- PostgreSQL operational writers;
- Strategy Freeze/publication capabilities;
- worker composition;
- scenario/operator tooling;
- test-only capabilities that must not leak into product surfaces.

Classify each surface:

```text
KEEP INTERNAL
MIGRATE TO PRODUCT API
REMOVE
OPERATOR/INFRASTRUCTURE ONLY
TEST ONLY
```

K0 should also establish mechanical import/capability architecture guards before broad migration.

Expected next output is an audit and narrow K0 implementation plan, not a large rewrite.

---

## 23. Intended architecture guards

Exact implementation must follow current repository truth, but target constraints include:

```text
Core/Domain/Kernel
MUST NOT import FastAPI/Starlette/API DTOs

Web/client packages
MUST NOT import Kernel mutation capabilities

public product clients
MUST NOT directly construct Engine/Runtime for business operations

API routes
MUST NOT author semantic facts

Runtime
MUST NOT obtain Strategy semantic publication capability

external product layer
MUST NOT obtain semantic store writers
```

Prefer capability/import ownership tests over brittle filename-pattern tests.

---

## 24. Important distinctions/warnings

### Stateful Product Kernel != existing `OnlyTradingKernel`

The broader P9.K Kernel Host owns product lifecycle/command/query/recovery composition.

`OnlyTradingKernel` remains the deterministic trading semantic core used by trading runtimes.

Do not collapse the two concepts into one God object.

### Avoid a God Kernel class

Kernel Host should compose focused existing authorities/services rather than absorbing all domain logic.

### Avoid EventBus-everywhere

Keep deterministic chains as explicit typed calls. Messaging is for genuinely asynchronous/cross-process/multi-consumer problems.

### Database != universal truth

Stateful Kernel does not mean “move everything to PostgreSQL”. Preserve semantic/operational/runtime/external authority boundaries.

### API identity != Strategy identity

OpenAPI version/contract fingerprint, request ID and user identity are product/transport identities and must not affect Strategy/Candidate/Calculation semantic fingerprints.

---

## 25. Explicit P9.K non-goals

Do not expand P9.K into:

- full Binance implementation;
- QMT/CTP live trading;
- real Broker submission;
- LIVE production permission;
- Portfolio optimizer redesign;
- broad Risk redesign;
- Kubernetes/service mesh;
- microservices rewrite;
- multi-master Kernel;
- distributed scheduler rewrite;
- Kafka/NATS default infrastructure;
- Temporal/Celery lifecycle replacement;
- generic workflow/event-sourcing framework;
- Strategy DSL;
- Rust trading-kernel rewrite.

P9.K exists to establish product/kernel/protocol boundaries before original P9.1+ production trading work.

---

## 26. PR #71 outcome

PR #71 was merged during this session.

It added:

```text
docs/adr/0101-stateful-kernel-and-protocol-boundary.md
docs/p9_k_stateful_kernel_protocol_boundary.md
```

It is architecture/documentation only and deliberately does not change runtime behavior, dependencies, Strategy semantics or persistence behavior.

The merged design freezes:

1. P9.K occurs after P9.0 and before existing P9.1;
2. OnlyAlpha target product form is a long-lived Stateful Quant Kernel;
3. external actors submit intent/reference while Kernel authorities produce facts;
4. one versioned external Product Control Plane;
5. OpenAPI as public contract;
6. FastAPI as replaceable first HTTP adapter;
7. typed direct calls for deterministic Kernel internals;
8. API/Domain/Persistence schema separation;
9. durable long-running lifecycle independent of HTTP request lifetime;
10. idempotent external mutations;
11. transport identity excluded from semantic fingerprints;
12. one logical authoritative Control Kernel in V1;
13. explicit Semantic/Operational/Runtime/External state ownership;
14. recovery as first-class behavior;
15. Control Plane separated from high-rate Data Plane;
16. Protobuf/gRPC as future remote infrastructure direction;
17. AsyncAPI/message brokers deferred until justified;
18. P9.0 Strategy/Freeze/Evidence semantics preserved.

---

## 27. Project workflow preference

Typical workflow:

```text
fresh architecture/code audit
→ detailed design
→ Codex task prompt
→ Codex implementation
→ fresh audit of new master
```

Always prefer fresh repository reads before claiming that a current issue is fixed.

If the owner asks for the next Codex prompt, generate it from current repository truth and scope it to **K0** unless they explicitly request a later stage.

---

## 28. Suggested next-session opening task

A suitable next prompt/task is:

> Read current `master`, ADR 0100, ADR 0101 and `docs/p9_k_stateful_kernel_protocol_boundary.md`. Reconfirm repository truth and determine whether P9.K K0 can begin. Audit every current external product mutation/control surface and classify it before proposing the K0 closure. Do not implement K1/K3 yet.

---

## 29. Final direction at session end

```text
P9.0
Strategy Authority Foundation
        ↓
P9.K
Stateful Kernel & Protocol Boundary
        ↓
Original P9.1+
Production Trading Vertical
```

Target architecture:

```text
External Product Actors
        │
        │ Intent / Query
        ▼
Versioned OpenAPI Product Contract
        │
        ▼
FastAPI HTTP Adapter
        │
        ▼
Command / Query Application Boundary
        │
        ▼
OnlyAlpha Stateful Kernel Host
        │
        ├── lifecycle
        ├── state-transition orchestration
        ├── explicit authorities
        ├── runtime supervision
        ├── recovery coordination
        └── preserves P9.0 semantic identities
        │
        ▼
Kernel-defined Infrastructure Ports
        │
        ├── persistence
        ├── market data
        ├── broker
        └── future remote gateways
```

Future remote infrastructure:

```text
Kernel ↔ Protobuf/gRPC ↔ QMT/CTP/remote infrastructure
```

Future asynchronous Data Plane only after justified need:

```text
AsyncAPI + appropriate transport
```

The next implementation phase is **K0 Surface Inventory & Architecture Freeze** — not endpoint proliferation, not a broad package move and not P9.1 market integration.
