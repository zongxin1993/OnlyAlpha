# OnlyAlpha — P9.K.7 Remote Protocol Foundation — Codex Implementation Prompt

## 0. Task Identity

**Repository:** `zongxin1993/OnlyAlpha`  
**Task:** `P9.K.7 — Remote Protocol Foundation`  
**Task type:** Architecture-bound protocol foundation / heterogeneous process-boundary freeze  
**Primary objective:** Establish one versioned, deterministic, provider-neutral Remote Infrastructure Protocol Foundation for future heterogeneous-process gateways such as Linux Kernel ↔ Windows QMT Gateway and Kernel ↔ CTP Gateway, without implementing real QMT/CTP trading and without creating a second Product API or business authority.

Planning baseline observed before this prompt was prepared:

```text
baa91014ec4e0197ac5c34f41138abc68c18471a
```

This SHA is **not** an implementation authority.

Before editing anything:

1. fetch/read the actual current `master`;
2. record the exact current HEAD as `TASK_BASE_SHA`;
3. current repository truth wins over this prompt;
4. read current `project-state.toml`;
5. run the project-state consistency check;
6. verify the repository still establishes:
   - `P9.K.6 = TASK COMPLETE / VERIFIED`;
   - `P9.K.7 = IMPLEMENTATION READY`;
7. if current source/docs/tests contradict those facts, stop implementation and report the conflict;
8. do not blindly patch paths, versions, hashes, scripts, package names, or assumptions from this prompt.

Expected conceptual start transition, only after repository state is verified:

```bash
uv run python scripts/project_state.py check
uv run python scripts/project_state.py transition start P9.K.7
uv run python scripts/project_state.py check
```

Use the actual current project-state command syntax if it has changed.

Do not manually edit generated project-state projections to fake progress.

---

# 1. Governing Design

Read and obey the **current** versions of:

```text
AGENTS.md
AGENTS.override.md                                  # if present

project-state.toml
scripts/project_state.py

docs/engineering/convergent-audit-policy.md
docs/engineering/quality-system.md
docs/engineering/project-state-authority.md

docs/adr/0101-stateful-kernel-and-protocol-boundary.md
docs/p9_k_stateful_kernel_protocol_boundary.md
docs/roadmap.md

docs/reports/p9_k6_external_client_migration.md     # or current K6 report path
docs/reports/p9_k5_idempotency_recovery_implementation.md

src/onlyalpha/kernel/**
src/onlyalpha/application/product_boundary.py
src/onlyalpha/runtime/**
src/onlyalpha/execution/**                          # inspect only; do not redesign

packages/api/onlyalpha-api/**
packages/client/onlyalpha-client/**

contracts/**
scripts/openapi_contract.py
scripts/openapi_clients.py

tests/architecture/**
tests/contracts/**
tests/integration/**
.github/workflows/**
pyproject.toml
uv.lock
```

The frozen K7 design is:

```text
Goal:
Freeze the future Gateway process boundary without implementing an unnecessary distributed platform.

Work:
- define Protobuf/gRPC versioning and error/identity rules;
- prove a minimal test Gateway if useful;
- separate unary command RPC from streaming event channels;
- establish reconnect/correlation/idempotency expectations;
- document QMT/CTP adapters as infrastructure rather than product APIs.

Non-goal:
Do not complete QMT/CTP trading here.

Exit:
Future heterogeneous OS gateways no longer need an ad-hoc protocol decision.
```

---

# 2. First-Principles Problem Statement

P9.K.1–P9.K.6 establish the Product side:

```text
External Product Actor
        ↓
HTTPS / JSON
        ↓
Canonical OpenAPI
        ↓
Product HTTP Adapter
        ↓
Command / Query Boundary
        ↓
Stateful Kernel
```

P9.K.7 addresses a fundamentally different problem:

```text
Stateful Kernel
        ↓
remote infrastructure process boundary
        ↓
QMT / CTP / future Broker Gateway
        ↓
external provider / venue
```

A remote Gateway is not a Product Actor.

A remote Gateway is not another Kernel.

A remote Gateway is not allowed to author Strategy, Portfolio, Risk or Product lifecycle truth.

The first-principles requirement is:

> Network/process/OS uncertainty must not become business-authority uncertainty.

The target architecture is:

```text
                      PRODUCT PLANE

Web / SDK / Agent / CLI / Automation
                │
          HTTPS / OpenAPI
                │
                ▼
┌──────────────────────────────────────────────┐
│             OnlyAlpha Kernel                 │
│                                              │
│ Strategy / Portfolio / Risk / Execution      │
│ Product Command / Query                      │
│ Kernel lifecycle / recovery                  │
└───────────────────┬──────────────────────────┘
                    │
              typed Kernel Port
                    │
                    ▼
             Infrastructure Adapter
                    │
              Protobuf / gRPC
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
 future QMT Gateway        future CTP Gateway
      Windows                    Linux
```

P9.K.7 must make that boundary explicit, versioned, mechanically governed, deterministic, and testable.

---

# 3. Governing Engineering Principles

OnlyAlpha engineering continues to optimize for:

```text
one fact
→ one authority

one semantic identity
→ one deterministic interpretation

one product transition
→ one legal path

same authoritative inputs
→ same authoritative logical result

unknown / ambiguous / incompatible
→ fail closed
```

For K7 specifically:

```text
one Remote Protocol Contract
→ one canonical protocol authority

one remote command_id
→ one canonical command intent

one stream sequence
→ one ordering interpretation

one Gateway process instance
→ one explicit gateway_instance_id

one business authority
→ remains in Kernel / external Venue as already designed
```

---

# 4. Core Architecture Invariants

## INV-K7-01 — Gateway Is Infrastructure, Not Product API

A Gateway MUST be classified as:

```text
INFRASTRUCTURE ADAPTER / REMOTE PROCESS
```

and MUST NOT become:

```text
Product HTTP API
alternate user-facing API
second Product Command boundary
second Kernel
```

External Product Actors must never directly call a Gateway as the normal Product control path.

Forbidden:

```text
Web → QMT Gateway → Broker
```

Required:

```text
Web
→ Product API
→ Kernel
→ Execution/Port
→ Remote Adapter
→ Gateway
→ Broker
```

## INV-K7-02 — Kernel Business Core Has Zero gRPC Transport Dependency

The business/kernel path must remain transport-agnostic.

Kernel/core/domain/application modules MUST NOT directly import:

```text
grpc
grpc.aio
google.protobuf generated Gateway modules
generated *_pb2.py
generated *_pb2_grpc.py
```

The dependency direction is:

```text
Kernel-defined Port
        ↑
Remote Infrastructure Adapter
        ↓
Generated gRPC Client
```

NOT:

```text
Kernel business module
        ↓
gRPC Stub
```

Do not replace direct deterministic Kernel calls with RPC.

## INV-K7-03 — Protocol Package Has Zero Kernel Business Dependency

The shared protocol package must be independently installable by a remote Gateway.

Preferred conceptual package:

```text
onlyalpha-gateway-protocol
```

It MUST NOT depend on:

```text
onlyalpha
onlyalpha-api
onlyalpha-client
Strategy
Portfolio
Risk
Research
Kernel Host
Persistence
```

A future Windows QMT machine should be able to install conceptually:

```text
onlyalpha-gateway-protocol
onlyalpha-qmt-gateway
xtquant
```

without installing the full OnlyAlpha Kernel.

## INV-K7-04 — One Canonical Remote Protocol Authority

The canonical authoring authority is versioned `.proto` source.

Conceptual flow:

```text
canonical .proto source
        ↓
canonical descriptor / deterministic projection
        ↓
generated language bindings
```

Generated code is a projection, never a second contract authority.

Do not create:

```text
hand-written Python protocol DTO authority
parallel JSON schema for the same Gateway RPC
QMT-specific duplicate core protocol
```

## INV-K7-05 — Protocol Compatibility Major Is Unique

Preferred package namespace:

```protobuf
package onlyalpha.gateway.v1;
```

The major package version is the compatibility-major authority.

Do not create multiple competing protocol-version authorities.

Diagnostic metadata such as:

```text
implementation_version
contract_sha256
gateway_build
```

may exist, but they do not redefine compatibility semantics or business identity.

## INV-K7-06 — Unary Command and Streaming Event Semantics Are Separate

Do not create a universal bidirectional message bus.

Separate:

```text
Unary RPC:
- handshake
- point query/control
- side-effect command

Streaming RPC:
- remote infrastructure event stream
```

Forbidden design:

```text
OneUniversalMessage {
    COMMAND
    RESPONSE
    TICK
    FILL
    HEARTBEAT
    ERROR
}
```

K7 must not create a generic global EventBus.

## INV-K7-07 — One `command_id` Binds to Exactly One Canonical Intent

For every retryable remote mutation:

```text
command_id
+
canonical command fingerprint
→ one authoritative remote command identity
```

Rules:

```text
same command_id + same canonical command
→ replay/converge to the same outcome

same command_id + different canonical command
→ deterministic conflict
```

No silent overwrite.

No second execution.

No new identity on retry.

## INV-K7-08 — Correlation Identity Is Not Command Identity

Distinguish:

```text
command_id
→ logical side-effect identity

correlation_id
→ one transport attempt / trace identity
```

A retry may have:

```text
same command_id
different correlation_id
```

without changing command semantics.

## INV-K7-09 — Gateway Instance Identity Is Explicit

Distinguish:

```text
gateway_id
→ stable configured/logical Gateway identity

gateway_instance_id
→ one concrete Gateway process lifetime
```

Gateway process restart MUST produce a different `gateway_instance_id`.

A changed instance identity must force:

```text
re-handshake
capability revalidation
stream/recovery decision
```

A TCP reconnect is not sufficient evidence of semantic continuity.

## INV-K7-10 — Session/Transport Metadata Never Enters Business Semantic Identity

The following MUST NOT enter:

```text
Dataset fingerprint
Calculation identity
Candidate fingerprint
Strategy fingerprint
Strategy Revision identity
```

Metadata that must remain operational/transport-only includes:

```text
gateway_id
gateway_instance_id
session_id
correlation_id
command_id
protocol version
contract hash
remote address
TLS identity
retry count
RPC deadline
request arrival time
```

Do not modify P9.0 semantic identities.

## INV-K7-11 — K7 Does Not Claim Exactly-Once Delivery

Document explicitly:

```text
OnlyAlpha Remote Protocol does NOT claim exactly-once network delivery.
```

The convergence model is:

```text
retryable transport
+
stable command identity
+
idempotent replay
+
later provider reconciliation where required
→ one authoritative logical outcome
```

Do not describe gRPC as exactly-once.

Do not interpret transport timeout as proof that a command did not execute.

## INV-K7-12 — Transport Timeout Is Not Business Rejection

A mutation RPC timeout means:

```text
outcome unknown to caller
```

not:

```text
business rejected
```

The legal next step is conceptually:

```text
retry same command_id
or
reconcile
```

not:

```text
generate a new command_id and re-execute
```

## INV-K7-13 — Stream Ordering Authority Is Explicit Sequence, Not Wall Clock

Every test stream must have an explicit sequence authority.

Example:

```text
101
102
103
104
```

Use timestamps as evidence/observability only.

Do not sort remote stream truth by wall-clock timestamps across OS/process boundaries.

## INV-K7-14 — Stream Gaps Are Explicit Facts

Example:

```text
103
105
```

must produce an explicit gap/resync outcome.

It must never silently continue as if `104` never existed.

Duplicates may be tolerated/replayed if the stream contract explicitly defines that behavior.

## INV-K7-15 — Reconnect Is Explicitly Governed

Reconnect must not imply continuity automatically.

Required conceptual sequence:

```text
DISCONNECTED
→ CONNECTING
→ HANDSHAKING
→ READY
→ STREAMING
```

After disconnect:

```text
reconnect
→ handshake
→ verify instance
→ verify protocol
→ verify capabilities
→ stream resume/reconciliation
→ ready for allowed side effects
```

## INV-K7-16 — Resume Has Explicit Failure Semantics

If a stream can resume from:

```text
resume_after = N
```

it may continue at:

```text
N+1
```

If history/state cannot support exact continuation:

```text
RESYNC_REQUIRED
```

must be explicit.

Never jump to “latest” silently.

## INV-K7-17 — Gateway Does Not Own Kernel Business Truth

Gateway may own:

```text
provider connection/session state
transport state
provider correlation
remote command receipt/replay support
stream sequence/history required for protocol testing
```

Gateway MUST NOT own/reimplement:

```text
Strategy authority
Portfolio authority
Risk authority
Research authority
Promotion authority
Kernel lifecycle authority
Product authorization authority
```

Future external order/fill facts remain Broker/Venue authority plus Kernel reconciliation/projection as governed by existing architecture.

## INV-K7-18 — Protocol Generation Is Deterministic

Define:

```text
GeneratedGatewayProtocol =
F(
    canonical proto sources,
    exact protoc/tool versions,
    exact generation configuration
)
```

Same inputs must produce the same committed generated projection.

Generated artifacts must not depend on:

```text
timestamp
hostname
absolute developer path
Git SHA
random UUID
filesystem accidental ordering
build number
```

## INV-K7-19 — Compatibility Changes Are Mechanical and Fail Closed

Mechanically detect at least:

```text
existing field number change
existing field type change
existing field removal/reuse
reserved number/name reuse
RPC removal
incompatible RPC input/output change
silent package-major change
```

When an old field is removed, reserve its number/name as appropriate.

Do not build a large custom Protobuf compatibility engine if a pinned mature tool can enforce the required rules.

## INV-K7-20 — K7 Introduces No Real QMT/CTP Trading Semantics

K7 must not implement:

```text
real SubmitOrder
real CancelOrder
real Account query
real Position query
real Market Data provider
QMT connection
CTP connection
Broker production adapter
LIVE permission
```

A test command MUST remain provider-neutral and explicitly test-only.

---

# 5. Product Plane vs Infrastructure Plane

Do not modify the K6 Product client model.

Product plane remains:

```text
External Product Actor
→ OpenAPI
→ Product HTTP Adapter
→ Product Command/Query
→ Kernel
```

Infrastructure plane becomes:

```text
Kernel Port
→ Remote Infrastructure Adapter
→ Protobuf/gRPC
→ Gateway
```

The two contracts serve different actors and authority models.

Do not expose Gateway gRPC methods as an alternative Product client interface.

---

# 6. Provider-Neutral Protocol Scope

K7 should freeze a foundation, not a QMT-specific API.

Preferred conceptual source layout:

```text
contracts/
└── gateway/
    └── v1/
        ├── common.proto
        ├── identity.proto
        ├── error.proto
        ├── gateway.proto
        └── stream.proto
```

Adapt the physical structure to current repository conventions if necessary.

Do NOT create a giant speculative `qmt.proto`.

Do NOT model hypothetical complete Broker APIs before their real milestone.

---

# 7. Minimum Protocol Semantics

K7 should implement/prove only the smallest semantics required to freeze the remote boundary.

## 7.1 Handshake

Implement a minimal handshake capable of proving:

```text
gateway logical identity
gateway process-instance identity
protocol major compatibility
contract/projection identity where useful
implementation version for diagnostics
advertised capabilities
```

The exact fields must remain minimal.

The handshake must answer:

```text
Who are you?
Which concrete process instance are you?
Are we protocol-compatible?
Which capabilities do you support?
Has the remote process restarted?
```

Do not put business state into handshake.

## 7.2 Capabilities

K7 test capabilities should be minimal and provider-neutral, for example:

```text
TEST_UNARY
TEST_STREAM
```

Future concepts such as:

```text
MARKET_DATA
ORDER_SUBMISSION
ORDER_CANCEL
```

may be documented as future examples but MUST NOT require real implementation in K7.

A caller requiring an absent capability must fail closed before performing a side effect.

## 7.3 Test Unary Mutation

Use a deliberately non-business, test-only command, for example conceptually:

```text
ApplyTestMutation
```

It may carry:

```text
command_id
command_fingerprint
correlation_id
test payload
```

The test Gateway may maintain a deterministic in-memory receipt map:

```text
command_id
→ command_fingerprint + outcome
```

Purpose:

```text
prove remote mutation identity/replay/conflict semantics
```

Do not call this fake order submission.

Do not introduce Broker domain semantics.

## 7.4 Test Streaming Channel

Implement a minimal test stream, conceptually:

```text
WatchTestEvents
```

with explicit metadata:

```text
stream_id
gateway_instance_id
sequence
event_id
observed_at                # evidence only
```

The minimum behavioral contract must cover:

```text
monotonic sequence
duplicate recognition/replay
gap detection
resume_after
RESYNC_REQUIRED
```

Do not create a global event abstraction.

---

# 8. Error Model

Create a small stable Gateway protocol error taxonomy.

A reasonable direction:

```text
INVALID_REQUEST
PROTOCOL_MISMATCH
UNSUPPORTED_CAPABILITY
NOT_READY
COMMAND_CONFLICT
PROVIDER_UNAVAILABLE
PROVIDER_REJECTED
DEADLINE_EXCEEDED
RESYNC_REQUIRED
INTERNAL_ERROR
```

Do not add categories without a real K7 need.

Keep distinct:

```text
gRPC transport status
```

from:

```text
Gateway application/infrastructure result
```

For example:

```text
gRPC UNAVAILABLE / DEADLINE_EXCEEDED
→ transport outcome uncertain

Gateway COMMAND_CONFLICT
→ request understood; stable protocol result
```

Future provider-specific details may be mapped into diagnostic fields such as:

```text
provider_code
provider_message
```

but Kernel logic must not depend on provider exception strings.

---

# 9. Protocol Versioning Rules

Preferred:

```protobuf
package onlyalpha.gateway.v1;
```

Freeze compatibility rules.

Within `v1`, allow only backward-compatible changes according to the chosen pinned compatibility gate.

At minimum do not allow:

```text
field-number mutation
field-type mutation
removed field-number reuse
removed field-name reuse
incompatible RPC signature changes
silent semantic redefinition
```

Breaking protocol semantics require a new major namespace:

```text
v1
→ v2
```

Do not add another independent runtime `schema_version` authority unless current protocol tooling strictly requires one for a different purpose.

---

# 10. Protocol Contract Fingerprint

If useful, compute a deterministic SHA256 over the canonical protocol descriptor/projection.

Use it only for:

```text
diagnostics
handshake compatibility evidence
CI evidence
deployment evidence
```

It MUST NOT become a semantic/trading identity.

---

# 11. Deterministic Proto Toolchain

Select the smallest pinned toolchain satisfying:

```text
lint
generation
descriptor/canonical projection
breaking-change detection
Python stubs
gRPC stubs
```

A pinned `buf` + pinned Protobuf/gRPC toolchain may be used if it simplifies governance.

Do not require a remote registry/cloud service.

Prefer local repository authority:

```text
Git baseline
+
canonical .proto
+
pinned tools
```

Pin exact versions sufficiently to make regeneration reproducible.

---

# 12. Generation/Governance Command Surface

Prefer one explicit script or current equivalent, e.g.:

```text
scripts/gateway_protocol.py
```

Suggested conceptual commands:

```bash
python scripts/gateway_protocol.py write
python scripts/gateway_protocol.py check
python scripts/gateway_protocol.py verify --base <immutable-git-sha>
```

`write`:

```text
canonical proto
→ deterministic generated projection
→ committed generated files / descriptor
```

`check`:

```text
regenerate into temp location
→ compare exact committed projection
→ fail on drift
```

`verify --base`:

```text
load immutable historical Git baseline
→ run compatibility rules
→ lint current contract
→ verify generated freshness
```

Do not implement Git-baseline comparison by comparing two mutable worktree files.

Follow the same immutability philosophy already used by OpenAPI governance.

---

# 13. Independent Protocol Package

Preferred conceptual package:

```text
packages/protocol/onlyalpha-gateway-protocol/
```

Minimum responsibilities:

```text
generated protobuf messages
generated gRPC client/server stubs
minimal protocol constants/helpers where truly necessary
```

Forbidden responsibilities:

```text
Kernel orchestration
Business validation
Provider logic
QMT/CTP integration
Strategy/Portfolio/Risk logic
Persistence authority
```

Ensure it is included in workspace/build/type-check/test configuration only as needed.

Do not make the root `onlyalpha` package depend on it globally unless a narrow infrastructure adapter genuinely needs it.

---

# 14. Minimal Cross-Process Test Gateway

K7 MUST prove a real process boundary.

Use a minimal provider-neutral test Gateway, preferably under:

```text
tests/fixtures/remote_gateway/
```

or:

```text
packages/fake/onlyalpha-test-gateway/
```

according to repository conventions.

It must be clearly TEST/FIXTURE infrastructure.

It must not be published/documented as a production Gateway.

Minimum functions:

```text
Handshake
ApplyTestMutation
WatchTestEvents
```

Run it as a real subprocess bound to localhost.

Do not use Docker/Kubernetes for this Task Gate unless the current repository already has a significantly simpler established mechanism.

---

# 15. Gateway Lifecycle for Test Foundation

The test adapter/client should model the minimum explicit state:

```text
DISCONNECTED
CONNECTING
HANDSHAKING
READY
STREAMING
```

Do not create a second business lifecycle state machine.

This state only describes remote infrastructure connectivity.

A changed `gateway_instance_id` must invalidate old session assumptions.

---

# 16. Retry Semantics

## Queries / Read-only Calls

Limited transport retry may be acceptable if simple and explicit.

## Mutations

Prefer:

```text
NO hidden automatic mutation retry
```

unless the retry preserves the same `command_id` and canonical fingerprint by construction.

Caller-controlled retry is acceptable and clearer for K7.

Absolutely forbidden:

```text
retry
→ generate new command_id
```

---

# 17. Stream Semantics

The K7 foundation must explicitly define, for the test stream:

```text
ordering
duplicate behavior
gap behavior
resume behavior
resync behavior
```

Do not claim that all future streams have identical reliability semantics.

Document that future market-data and execution streams may have different recovery contracts.

For example only as future design guidance:

```text
Market Data:
gap detectable
resnapshot/re-subscribe may be acceptable

Execution Event:
gap must not be silently ignored
provider reconciliation likely required
```

Do not implement those production streams in K7.

---

# 18. Backpressure

K7 should define a bounded policy for the test stream.

Do not allow unbounded in-memory growth.

If a test stream cannot preserve required history because its bounded buffer is exceeded, make the result explicit, such as:

```text
RESYNC_REQUIRED
```

Do not silently drop events.

Keep the mechanism small.

---

# 19. Security Scope

K7 may document the production requirement:

```text
remote Gateway traffic must support authenticated encrypted transport
```

Future direction may use:

```text
TLS / mTLS
```

However, K7 Task Gate may use localhost insecure channels for deterministic local testing if clearly marked TEST ONLY.

Do not implement:

```text
PKI platform
certificate rotation service
Vault
SPIFFE
service mesh
```

during K7.

Authentication metadata remains transport/security context and must not enter business fingerprints.

---

# 20. Expected Repository Changes

K7 changes should primarily localize around:

```text
contracts/gateway/v1/**

packages/protocol/onlyalpha-gateway-protocol/**

scripts/gateway_protocol.py
or minimal current-equivalent tooling/config

tests/fixtures/remote_gateway/**
or packages/fake/onlyalpha-test-gateway/**

tests/contracts/test_gateway_protocol_contract.py

tests/architecture/test_p9_k7_remote_protocol_boundary.py

tests/integration/test_remote_gateway_protocol.py

docs/p9_k7_remote_gateway_protocol.md

docs/reports/p9_k7_remote_protocol_foundation.md

pyproject.toml
uv.lock
.github/workflows/**          # only minimal protocol gate integration if justified
```

Do not force these exact paths if current repository conventions provide a clearer equivalent.

---

# 21. Areas That Should Not Receive Broad Changes

Broad edits in the following are likely scope leakage:

```text
src/onlyalpha/strategy/**
src/onlyalpha/portfolio/**
src/onlyalpha/risk/**
src/onlyalpha/research/**
src/onlyalpha/application/product_boundary.py
packages/api/onlyalpha-api/**
packages/client/onlyalpha-client/**
```

Small architecture-guard adjustments may be valid.

Business-semantic rewrites are not.

If K7 appears to require a large redesign of these modules, stop and reassess.

---

# 22. Database/Persistence Rule

Expected K7 production persistence delta:

```text
new PostgreSQL business tables = 0
new Strategy tables            = 0
new Product Command tables     = 0
new Broker authority tables    = 0
```

The test Gateway may use deterministic in-memory receipts.

Do not create a production Gateway receipt database merely to make the protocol test realistic.

Document future provider-specific durability/reconciliation needs instead.

---

# 23. Required Architecture Tests

Add a focused K7 architecture suite.

Preferred conceptual location:

```text
tests/architecture/test_p9_k7_remote_protocol_boundary.py
```

At minimum prove:

## TEST-K7-A01 — Core Transport Independence

Core/business modules do not import:

```text
grpc
protobuf generated Gateway modules
protocol transport implementation
```

Use AST/import-aware checks where appropriate.

Avoid broad false-positive grep.

## TEST-K7-A02 — Protocol Package Independence

The protocol package does not depend/import:

```text
onlyalpha
onlyalpha_api
onlyalpha_client
```

except generated package-local modules.

## TEST-K7-A03 — Test Gateway Is Not Product Authority

The test Gateway must not import:

```text
Strategy publisher
Portfolio authority
Risk authority
Research Application mutation authority
Product Command Dispatcher
Kernel Host
```

Use exact allowlists rather than broad exceptions.

## TEST-K7-A04 — Product API Does Not Bypass Kernel to Gateway

Product HTTP/client modules must not directly call Gateway RPC as a Product mutation shortcut.

## TEST-K7-A05 — Protocol Major/Canonical Source Is Unique

Mechanically enforce the expected canonical `gateway/v1` authority.

No second competing remote protocol source.

## TEST-K7-A06 — Generated Protocol Freshness

Regenerate and compare exact committed projections.

Fail on drift.

## TEST-K7-A07 — No Provider-Specific Scope Leakage

K7 protocol foundation/test Gateway must not import/use:

```text
xtquant
MiniQMT
CTP SDK
production broker providers
```

Unknown provider-specific dependencies fail.

---

# 24. Required Contract Tests

Add contract/governance tests proving at least:

## TEST-K7-C01 — Stable Generation

Same canonical proto + pinned toolchain regenerates exact committed artifacts.

## TEST-K7-C02 — Field Number Change Fails

A compatibility fixture changing an existing field number fails.

## TEST-K7-C03 — Field Type Change Fails

A compatibility fixture changing type fails.

## TEST-K7-C04 — Removed Field Reuse Fails

Reusing a removed/reserved number/name fails.

## TEST-K7-C05 — RPC Removal Fails

Removing a previously accepted RPC fails.

## TEST-K7-C06 — Incompatible RPC Type Change Fails

Changing request/response incompatibly fails.

Keep fixtures minimal.

Do not build an oversized compatibility matrix beyond current invariant needs.

---

# 25. Required Cross-Process Integration Tests

Run the test Gateway as a real subprocess.

Avoid timing sleeps as correctness barriers; use readiness barriers, explicit ports, process pipes/files, or deterministic synchronization.

## E2E-K7-01 — Handshake Success

Prove:

```text
client process
→ gRPC
→ Gateway subprocess
→ compatible handshake
```

Verify:

```text
gateway_id
gateway_instance_id
protocol major
capabilities
```

as appropriate.

## E2E-K7-02 — Protocol Major Mismatch Fails Closed

An incompatible major must not become READY.

Do not silently negotiate unknown semantics.

## E2E-K7-03 — Missing Required Capability Fails Closed

If the client requires a capability that the Gateway does not advertise:

```text
no side effect
+
deterministic failure
```

## E2E-K7-04 — First Test Mutation Executes Once

Submit:

```text
command_id = A
fingerprint = F
```

Verify:

```text
mutation execution count = 1
```

## E2E-K7-05 — Response-Loss Retry Converges

Create a deterministic test barrier where:

```text
Gateway commits test mutation/receipt
→ response is considered lost / connection interrupted
→ caller retries same A + F
```

Verify:

```text
same authoritative outcome
mutation execution count remains 1
```

Do not use random timing to simulate correctness.

## E2E-K7-06 — Same ID / Different Intent Conflicts

Submit:

```text
A + F1
```

then:

```text
A + F2
```

where `F1 != F2`.

Verify:

```text
COMMAND_CONFLICT
no second mutation execution
```

## E2E-K7-07 — Correlation ID Can Change Without Changing Command Identity

Retry:

```text
same command_id
same canonical intent
different correlation_id
```

Verify same outcome.

## E2E-K7-08 — Stream Ordering

Test Gateway emits:

```text
1
2
3
4
```

Client applies explicit sequence authority.

## E2E-K7-09 — Duplicate Stream Event Is Detectable

Test replay/duplicate:

```text
1
2
2
3
```

Behavior must be deterministic and explicitly characterized.

## E2E-K7-10 — Stream Gap Fails Explicitly

Test:

```text
1
2
4
```

must produce an explicit gap/resync outcome.

Do not continue silently.

## E2E-K7-11 — Reconnect and Resume

Consume through sequence `N`.

Disconnect.

Reconnect.

Re-handshake.

Request:

```text
resume_after = N
```

When history exists, continue exactly at `N+1`.

## E2E-K7-12 — Resume Failure Is `RESYNC_REQUIRED`

When the Gateway can no longer provide exact continuation, return explicit `RESYNC_REQUIRED`.

Do not jump to latest.

## E2E-K7-13 — Gateway Restart Changes Instance Identity

Sequence:

```text
start Gateway
→ instance=A
→ handshake
→ kill process
→ restart Gateway
→ instance=B
```

Verify:

```text
A != B
```

and client/adapter requires new handshake/revalidation.

---

# 26. Identity Characterization Tests

At minimum prove:

```text
changing correlation_id
→ does not change canonical command fingerprint
```

```text
changing gateway_instance_id
→ does not change business command intent/fingerprint
```

```text
changing RPC deadline
→ does not change business command intent/fingerprint
```

```text
changing protocol metadata
→ does not alter existing P9.0 semantic fingerprints
```

Do not duplicate the full P9.0 test suite; add the smallest high-signal characterization.

---

# 27. Documentation Deliverable

Create a dedicated protocol design document, preferred:

```text
docs/p9_k7_remote_gateway_protocol.md
```

It must document:

```text
purpose/non-purpose
authority model
Product Plane vs Infrastructure Plane
protocol package authority
versioning
identity taxonomy
command idempotency
no exactly-once claim
timeout semantics
error taxonomy
handshake
capabilities
stream sequence
duplicates
gaps
resume/resync
Gateway restart
security scope
future QMT/CTP extension rules
```

This document is a design/protocol artifact, not the repository current-state authority.

---

# 28. K7 Implementation Report

Create:

```text
docs/reports/p9_k7_remote_protocol_foundation.md
```

or current-equivalent naming.

Include at least:

```text
TASK_BASE_SHA
implementation/worktree SHA

governing ADR/design references

before/after boundary graph

canonical proto source paths
protocol major
protocol contract/descriptor SHA if used
exact toolchain versions
generation freshness result
compatibility test result

protocol package dependency graph

test Gateway classification

handshake evidence
capability evidence
unary idempotency evidence
same-id-different-intent conflict evidence
correlation identity evidence

stream sequence evidence
duplicate evidence
gap evidence
resume evidence
RESYNC_REQUIRED evidence
Gateway restart evidence

architecture gate results

P9.0 semantic delta statement
Product API semantic delta statement

remaining future provider work
explicit confirmation:
QMT implementation = 0
CTP implementation = 0
real Broker submission = 0

reverse-audit result
Task Gate verdict
```

Do not claim Final-SHA Certification unless the exact certification workflow is run and accepted.

---

# 29. Explicit Non-Goals

DO NOT implement in K7:

```text
real QMT connection
real MiniQMT/xtquant transport
real CTP connection
real Binance provider work

SubmitOrder production RPC
CancelOrder production RPC
production account/position model
production broker reconciliation

Portfolio redesign
Risk redesign
Execution redesign
Strategy redesign
Research redesign

LIVE execution permission

generic distributed event bus
Kafka
NATS
Redis Streams
RabbitMQ
Temporal
Celery

service mesh
Kubernetes requirement
multi-master Kernel HA
leader election
generic workflow engine

Kernel internal gRPC
HTTP replacement
GraphQL

K8 Kernel sealing
P9.1 provider implementation
```

Do not start K8 inside K7.

---

# 30. Stop Conditions

Stop and reassess if implementation argues any of the following:

```text
"We should connect real QMT now to prove the protocol."

"Kernel can just import the generated gRPC stub directly."

"All commands and events should use one bidirectional stream."

"Gateway should keep its own Portfolio/Position truth for convenience."

"A timeout means the mutation failed."

"On reconnect we can just continue from the latest event."

"Each retry can use a fresh command_id."

"Let's create generic EventBus/Topic abstractions now."

"Let's add a production Gateway database for this foundation."

"Let's expose Gateway RPC directly to Product clients."
```

These are scope/authority violations.

---

# 31. Recommended Implementation Sequence

Perform work in narrow phases.

## Phase A — Revalidate Current Boundary

Re-read current HEAD and inventory:

```text
Product external boundary
Kernel ports/infrastructure abstractions
provider packages
existing protocol/generated-code tooling
architecture tests
```

Confirm no existing remote protocol authority already supersedes this plan.

## Phase B — Freeze K7 Protocol Invariants

Before server implementation, define:

```text
authority
identity
versioning
error
retry
stream
reconnect
restart
```

in the design document and tests/fixtures.

Do not start Provider semantics.

## Phase C — Canonical Proto + Governance

Add the smallest provider-neutral `gateway/v1` contract.

Add lint/generation/compatibility tooling.

Pin toolchain versions.

## Phase D — Independent Protocol Package

Add generated Python binding package.

Prove zero Core dependency.

## Phase E — Minimal Test Gateway

Implement the real subprocess test Gateway with only:

```text
Handshake
ApplyTestMutation
WatchTestEvents
```

## Phase F — Failure/Recovery Characterization

Prove:

```text
response loss + retry
same-ID conflict
correlation separation
disconnect
resume
gap
resync
Gateway restart
protocol mismatch
capability mismatch
```

## Phase G — Mechanical Closure

Run:

```text
architecture tests
contract tests
integration tests
generation check
compatibility check
static checks
reverse audit
```

Update report and project state only after evidence passes.

---

# 32. K7 Task Gate

P9.K.7 is complete only if every relevant gate below passes.

## Gate 1 — One Canonical Remote Protocol

There is one canonical versioned Gateway protocol authority.

No competing second remote contract exists.

## Gate 2 — Deterministic Generation

```text
same proto
+
same pinned toolchain
→ same generated projection
```

is mechanically proven.

## Gate 3 — Compatibility Governance

Breaking protocol changes fail closed against an immutable historical baseline.

## Gate 4 — Transport Independence

Kernel/business Core has zero gRPC/generated-protocol dependency.

## Gate 5 — Protocol Independence

Shared protocol package has zero Kernel/business dependency.

## Gate 6 — Handshake / Capability

A real cross-process test proves:

```text
protocol compatibility
Gateway identity
Gateway instance identity
capability admission
```

## Gate 7 — Unary Remote Command Identity

```text
same command_id + same canonical intent
→ same outcome / one test side effect
```

## Gate 8 — Command Conflict

```text
same command_id + different canonical intent
→ deterministic conflict
```

## Gate 9 — Correlation Separation

Transport attempt identity can change without changing remote command identity.

## Gate 10 — Streaming Semantics

The test stream has explicit deterministic behavior for:

```text
sequence
duplicate
gap
resume
resync
```

## Gate 11 — Gateway Restart

A real subprocess restart changes `gateway_instance_id` and forces re-handshake/revalidation.

## Gate 12 — Authority Preservation

```text
new Product API authority = 0
new Kernel authority      = 0
new Strategy authority    = 0
new Portfolio authority   = 0
new Risk authority        = 0
new persistence authority = 0
```

## Gate 13 — Semantic Preservation

```text
P9.0 semantic identity delta = 0
Product OpenAPI semantic delta = 0 unless strictly required and separately governed
```

K7 should normally not require Product OpenAPI changes.

## Gate 14 — Scope Discipline

```text
QMT implementation = 0
CTP implementation = 0
real Broker submission = 0
generic event bus = 0
K8 work = 0
P9.1 work = 0
```

---

# 33. Required Reverse Audit

After implementation, explicitly answer:

```text
new Product API authority?         MUST BE NO
new business mutation authority?   MUST BE NO
new Strategy identity?             MUST BE NO
new Portfolio authority?           MUST BE NO
new Risk authority?                MUST BE NO
new lifecycle authority?           MUST BE NO
new persistence authority?         MUST BE NO
new second Kernel?                 MUST BE NO
new generic event-bus authority?   MUST BE NO
new provider-specific protocol?    MUST BE NO
new semantic dependency on network timing? MUST BE NO
```

Also verify:

```text
Product OpenAPI remains the Product external contract.
Internal business calls remain typed/direct.
Remote Gateway protocol remains Infrastructure-only.
Broker/Venue external facts remain external authority.
```

---

# 34. Verification Commands

Use the **current repository-defined** commands.

At minimum inspect/run the current equivalents of:

```bash
uv run python scripts/project_state.py check

uv sync --frozen --all-packages --all-groups

uv run ruff check .
uv run ruff format --check .
uv run mypy

uv run python scripts/test_suite.py architecture

uv run pytest tests/contracts/test_gateway_protocol_contract.py -q
uv run pytest tests/integration/test_remote_gateway_protocol.py -q

uv run python scripts/gateway_protocol.py check

# immutable baseline compatibility check
uv run python scripts/gateway_protocol.py verify --base <appropriate immutable base sha>

uv run lint-imports

git diff --check
```

Use narrower package-specific mypy/test commands if the current repository quality system prefers them.

Do not invent a Final-SHA Certification requirement if the current K7 Task Gate does not require it.

Do not weaken existing gates to make K7 pass.

---

# 35. Existing Higher-Level Evidence Debt

At planning time, a repository-wide/current CI PostgreSQL coverage debt existed separately from K6 correctness.

Do not silently redefine unrelated higher-level coverage debt as K7 implementation scope unless the current Quality System says it is a K7 acceptance criterion.

Likewise, do not ignore an actual K7-local regression by calling it historical debt.

Follow the current Convergent Audit Policy and Gate Hierarchy.

---

# 36. Project State Completion

Only after:

```text
K7 implementation complete
+
K7 Task Gate passes
+
reverse audit passes
+
report is current
```

use the current project-state tooling to transition/verify K7.

Expected conceptual state:

```text
P9.K.7 ACTIVE
→ P9.K.7 TASK COMPLETE / VERIFIED
→ P9.K.8 IMPLEMENTATION READY
```

Then:

```bash
uv run python scripts/project_state.py check
```

must pass.

Do not start P9.K.8 in this task.

---

# 37. Required Final Codex Response

At completion report exactly:

```text
1. TASK_BASE_SHA
2. final implementation/worktree SHA
3. files changed

4. canonical protocol source
5. protocol major/version authority
6. protocol contract/descriptor identity
7. pinned generation/compatibility toolchain

8. protocol package created/updated
9. protocol package dependency proof
10. Core transport-independence proof

11. test Gateway location/classification
12. handshake result
13. capability result

14. unary command identity result
15. response-loss retry result
16. same-ID-different-intent result
17. correlation-ID separation result

18. stream ordering result
19. duplicate result
20. gap result
21. resume result
22. RESYNC_REQUIRED result
23. Gateway restart result

24. architecture tests added
25. contract tests added
26. integration tests added

27. Product OpenAPI semantic delta
28. P9.0 semantic delta
29. database/persistence delta

30. reverse-audit result
31. Task Gate verdict
32. project-state result

33. explicit confirmation:
    QMT not started
    CTP not started
    real Broker submission not started
    K8 not started
    P9.1 not started

34. remaining future-provider work
```

If any required gate fails, leave P9.K.7 unverified and report the exact failing evidence.

---

# 38. Final Engineering Intent

The success criterion is NOT:

```text
"OnlyAlpha now supports gRPC."
```

The success criterion is:

```text
Product external control
→ remains OpenAPI

Internal business execution
→ remains direct typed Kernel calls

Remote heterogeneous infrastructure
→ has one canonical Protobuf/gRPC boundary
```

with deterministic identities and recovery semantics:

```text
same remote command identity + same canonical intent
→ one logical outcome

same remote command identity + different intent
→ conflict

stream gap
→ explicit gap/resync

Gateway restart
→ explicit new instance + re-handshake

network timeout
→ uncertainty, not fabricated business rejection
```

and with authority preserved:

```text
Gateway
≠ Product API
≠ Kernel
≠ Strategy authority
≠ Portfolio authority
≠ Risk authority
```

P9.K.7 must make future QMT/CTP implementation a matter of implementing an already-frozen Infrastructure contract, rather than inventing a new protocol during each provider milestone.

Implement the smallest complete mechanism that proves this boundary mechanically and deterministically. Do not build an unnecessary distributed platform.
