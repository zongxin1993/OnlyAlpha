# P9.K.7 Remote Protocol Foundation — Implementation and Task-Gate Evidence

- Date: 2026-08-28
- Branch: `master`
- `TASK_BASE_SHA`: `baa91014ec4e0197ac5c34f41138abc68c18471a`
- Implementation/worktree SHA: `baa91014ec4e0197ac5c34f41138abc68c18471a + dirty K7 worktree`
- Release version: `0.9.7`
- Environment: macOS 15.7.4 arm64, Python 3.12.12
- Gate: P9.K.7 Task Gate; no Phase Gate or Final-SHA Certification claim
- Governing design: ADR 0101, `docs/p9_k_stateful_kernel_protocol_boundary.md`,
  `docs/p9_k7_remote_gateway_protocol.md`, Convergent Audit Policy, Engineering Quality System

## Task contract and boundary graph

Goal: freeze one deterministic, versioned, provider-neutral Protobuf/gRPC infrastructure boundary for future heterogeneous-process
Gateways without implementing a provider, real trading, or another business authority.

Before K7:

```text
External Product Actor → OpenAPI → Product Command/Query → Stateful Kernel
Future remote Gateway boundary → not mechanically frozen
```

After K7:

```text
External Product Actor → OpenAPI → Product Command/Query → Stateful Kernel
                                                        → typed Kernel port
                                                        → remote infrastructure adapter
                                                        → onlyalpha.gateway.v1
                                                        → future provider Gateway
```

Modification scope is canonical proto, deterministic projection/compatibility governance, independent protocol package, explicit
infrastructure client lifecycle, real localhost subprocess fixture, focused tests, CI/static/build integration, documentation, version,
and project-state projections. Product API, Kernel business modules, Research/Strategy/P9.0 semantics, execution economics, databases,
QMT/CTP, real Broker submission, K8, and P9.1 are out of scope and unchanged.

## Canonical protocol and toolchain

Canonical authoring source:

```text
contracts/gateway/v1/onlyalpha_gateway_protocol/v1/common.proto
contracts/gateway/v1/onlyalpha_gateway_protocol/v1/error.proto
contracts/gateway/v1/onlyalpha_gateway_protocol/v1/identity.proto
contracts/gateway/v1/onlyalpha_gateway_protocol/v1/gateway.proto
contracts/gateway/v1/onlyalpha_gateway_protocol/v1/stream.proto
```

Compatibility-major authority: `package onlyalpha.gateway.v1`.

Committed projection:

```text
packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/v1/*_pb2.py
packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/v1/*_pb2.pyi
packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/v1/*_pb2_grpc.py
packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/v1/descriptor.pb
```

Descriptor SHA256:

```text
5cb5005475e24019669a8658a5189b9d6321488f3e3c675bdc0195b826dfd67e
```

This identity is compatibility/deployment diagnostics only and enters no business or semantic fingerprint.

Exact generation/runtime toolchain:

```text
grpcio-tools 1.73.1
grpcio       1.73.1
protobuf     6.31.0
```

`scripts/gateway_protocol.py` owns `write`, regenerate-and-compare `check`, and immutable Git baseline `verify --base`. Generation and
descriptor serialization use sorted paths and contain no timestamp, hostname, absolute source path, Git SHA, UUID, environment order, or
build number. Freshness and bootstrap compatibility against `TASK_BASE_SHA` are PASS. Focused fixtures prove field number/type change,
reserved name/number reuse, RPC removal, RPC signature change, and silent package-major drift fail closed.

## Independent package proof

Package: `packages/protocol/onlyalpha-gateway-protocol`.

Dependency graph:

```text
onlyalpha-gateway-protocol → grpcio==1.73.1
                           → protobuf==6.31.0

onlyalpha-gateway-protocol -X→ onlyalpha
                           -X→ onlyalpha-api
                           -X→ onlyalpha-client
                           -X→ Strategy / Portfolio / Risk / Research / Kernel / Runtime / Persistence
```

Architecture AST/metadata gates pass. The built `onlyalpha_gateway_protocol-0.9.7` wheel contains messages, grpc stubs, type projections,
client helpers, `py.typed`, and `descriptor.pb`; inspection confirms it contains no Core/API/client package. Strict package mypy passes.

## Test Gateway and protocol evidence

Fixture: `tests/fixtures/remote_gateway/server.py`.

Classification: **TEST ONLY / INFRASTRUCTURE FIXTURE**. It runs as a real subprocess on an insecure localhost ephemeral port, owns only
process identity, capability advertisement, deterministic in-memory test receipts, and bounded test stream history, and imports no
Kernel/Application/Strategy/Portfolio/Risk/Research authority.

| Evidence | Result |
|---|---|
| compatible handshake | gateway ID, unique instance ID, major 1, descriptor hash, implementation diagnostic, capabilities — PASS |
| protocol-major mismatch | application `PROTOCOL_MISMATCH`; never READY — PASS |
| missing capability | `UNSUPPORTED_CAPABILITY`; zero side effect — PASS |
| first unary mutation | one receipt/outcome; execution count 1 — PASS |
| same ID + same command | same outcome, replayed, execution count remains 1 — PASS |
| response lost after receipt | transport outcome unknown; client becomes DISCONNECTED; re-handshake + same ID/fingerprint converges — PASS |
| same ID + different intent | `COMMAND_CONFLICT`; no second execution — PASS |
| correlation separation | retry uses a different correlation ID without changing command outcome/fingerprint — PASS |
| stream ordering | explicit sequence `1,2,3`; timestamps unused for ordering — PASS |
| duplicate | `1,2,2,3` detects duplicate 2 and applies canonical events once — PASS |
| gap | `1,2,4` fails explicitly; no silent continuation — PASS |
| reconnect/resume | re-handshake, `resume_after=2`, exact `3,4` continuation — PASS |
| bounded history | unavailable continuation returns `RESYNC_REQUIRED` — PASS |
| process restart | new subprocess has a different `gateway_instance_id`; new handshake required — PASS |

The protocol and design explicitly make no exactly-once network claim. Transport timeout/UNAVAILABLE after mutation is unknown outcome,
not business rejection. The client has no hidden mutation retry and never creates a new command ID on retry.

## Architecture invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| one canonical remote protocol authority | PASS | exact canonical source set; generated projection freshness gate |
| protocol compatibility major unique | PASS | only `onlyalpha.gateway.v1`; package drift test |
| deterministic generation/fingerprint | PASS | two fresh projections byte-equal; descriptor SHA stable |
| Kernel/Core transport independence | PASS | K7 AST firewall plus canonical Architecture lane |
| protocol package independence | PASS | metadata/import AST and wheel inspection |
| Product plane vs infrastructure plane | PASS | API/client no grpc/protocol imports; OpenAPI unchanged |
| unary/stream separation | PASS | two services; mechanical topology validation; no bidi universal bus |
| remote command identity uniqueness | PASS | canonical domain-separated fingerprint + receipt replay/conflict |
| correlation vs command identity | PASS | changed correlation replays same logical outcome |
| explicit Gateway instance identity | PASS | UUID per process lifetime and restart test |
| transport metadata excluded from semantics | PASS | identity characterization; zero P9.0 semantic source diff |
| timeout is uncertainty | PASS | response-loss test and typed `outcome_unknown=True` |
| sequence is ordering authority | PASS | ordering/duplicate/gap tests; wall clock evidence only |
| resume failure fail closed | PASS | bounded history and instance mismatch return `RESYNC_REQUIRED` |
| bounded backpressure | PASS | finite fixture history; truncation never silently drops continuity |
| Gateway owns no Kernel business truth | PASS | fixture import firewall and in-memory test-only state |
| persistence uniqueness/transactionality | PASS (unchanged) | no production schema/table/store delta |
| public contract/schema preservation | PASS | Product OpenAPI exact bytes unchanged; Gateway v1 separately versioned |
| provider scope discipline | PASS | no xtquant/MiniQMT/CTP/provider/order/account production protocol |

## Verification evidence

Local PASS:

```text
K7 targeted architecture/contract/integration/identity: 27 passed
canonical Architecture lane:                         499 passed
Gateway generation freshness:                       PASS
immutable TASK_BASE compatibility/bootstrap:         PASS
Ruff check / Ruff format:                            PASS; 1490 files formatted
Mypy:                                                PASS; 671 source files
Import Linter:                                       PASS; 3 kept, 0 broken
version graph:                                       PASS; 0.9.7
project-state consistency:                           PASS; K7 VERIFIED, K8 IMPLEMENTATION READY
all-package source/wheel build:                      PASS; includes onlyalpha-gateway-protocol
protocol wheel content/dependency inspection:        PASS
git diff --check:                                    PASS
```

The real subprocess integration suite required authorized localhost binding because the default filesystem/network sandbox rejected
`127.0.0.1:0`. It used only loopback and made no external network/provider/account connection.

Budgeted local verification ran all 10 budgeted static commands successfully and returned `LOCAL_PASS_CI_REQUIRED` under exit-code 3
semantics. Manifest:

```text
test-results/verification/local-budget/20260828T032739Z-baa91014ec4e-93057/manifest.json
```

CI REQUIRED / not claimed PASS by the budgeted plan:

```text
release-static-11; web static/unit/build/E2E; kernel; strategy; all selected Research lanes;
research-product-closure; research-postgres; core-full; recovery; sim-recovery; ashare;
miniqmt-contract; budget-plan build
```

The directly applicable version check and all-package build were executed separately and passed, as recorded above. The remaining
budget-deferred commands, full Web E2E, real PostgreSQL lanes, broad business/recovery/market/provider lanes, Phase Gate, and exact-SHA
Final Certification were not executed locally and are not represented as PASS.

## Semantic and persistence deltas

```text
Product OpenAPI semantic delta: 0 bytes / 0 operations / 0 schemas
P9.0 semantic identity delta:   0
Kernel business source delta:   0
Research / Strategy delta:      0
execution economics delta:      0
new PostgreSQL tables:          0
new business persistence:       0
new Product command authority:  0
```

## Reverse audit

```text
new Product API authority?                    NO
new business mutation authority?              NO
new Strategy identity?                        NO
new Portfolio authority?                      NO
new Risk authority?                           NO
new lifecycle authority?                      NO (connectivity state only)
new persistence authority?                    NO
new second Kernel?                            NO
new generic event-bus authority?              NO
new provider-specific protocol?               NO
new semantic dependency on network timing?    NO
```

Product OpenAPI remains the external Product contract. Internal business calls remain typed/direct. Remote Gateway protocol remains
infrastructure-only. Broker/Venue facts remain external authority plus future Kernel reconciliation.

## Convergent Task-Gate audit

- `AUDIT_BASE_SHA`: `baa91014ec4e0197ac5c34f41138abc68c18471a`
- `AUDIT_HEAD_SHA`: `baa91014ec4e0197ac5c34f41138abc68c18471a + dirty K7 worktree`
- Scope: P9.K.7 Task Gate only
- Previous K7 findings: none

```text
BLOCKER:    0
MAJOR:      0
MINOR:      0
SUGGESTION: 0
```

No frozen-design, uniqueness, determinism, dependency-direction, replay/reconnect, public-contract, fail-closed, or scope violation was
found in the K7 implementation. Direct K7 required evidence is sufficient; broader budget-deferred CI remains explicitly open and is not
reclassified as K7 functional failure or PASS.

Task Gate verdict: **GO**.

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
是否可进入下一阶段？ GO
```

## Explicit non-start and future work

```text
QMT implementation:       0 / NOT STARTED
CTP implementation:       0 / NOT STARTED
real Broker submission:   0 / NOT STARTED
K8:                       NOT STARTED
P9.1:                     NOT STARTED
```

Future provider milestones still own production order/account/position RPCs, provider-specific durability and reconciliation, remote
adapter composition behind Kernel ports, authenticated TLS/mTLS deployment, production operations, and real-provider conformance.

Final project-state result:

```text
P9.K.7 Remote Protocol Foundation — TASK COMPLETE / VERIFIED
P9.K.8 Seal Kernel — IMPLEMENTATION READY
P9.1+ — BLOCKED until P9.K closure
```
