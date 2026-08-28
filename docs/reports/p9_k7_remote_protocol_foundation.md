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

## Post-Commit Closure Correction

- Original P9.K.7 Task Base SHA: `baa91014ec4e0197ac5c34f41138abc68c18471a`
- Original K7 implementation/verified SHA: `25077159ab50a42d5125195cf82731543f37a8f7`
- Closure-fix base SHA: `25077159ab50a42d5125195cf82731543f37a8f7`
- Closure-fix implementation/worktree SHA: `25077159ab50a42d5125195cf82731543f37a8f7 + dirty closure-fix worktree`
- Gate: P9.K.7 Closure Task Gate only; no Phase Gate or Final-SHA Certification claim

The original committed K7 HEAD exposed a post-commit evidence defect. The canonical shallow-checkout Architecture job failed after
`498 passed` because `test_product_openapi_and_p9_semantic_sources_are_unchanged_from_task_base` tried to resolve the historical K7 Task
Base Git object. The current architecture facts were correct, but their verdict accidentally depended on undeclared clone history.

The closure correction separates the two verification responsibilities:

```text
current-tree architecture invariants
→ tests/architecture/test_p9_k7_remote_protocol_boundary.py
→ shallow-checkout Architecture lane

historical K7 scope preservation
→ tests/contracts/test_p9_k7_task_delta.py
→ full-history gateway-protocol lane
```

The dedicated task-delta authority owns the sole `P9_K7_TASK_BASE_SHA` constant. It first requires the baseline with
`git cat-file -e <sha>^{commit}` and fails with an explicit assertion when unavailable; it never skips or xfails. With the baseline
available, exact verification records:

```text
Product OpenAPI byte delta:       0
protected P9 semantic path delta: 0 changed files
```

The stream client now maps only `GatewayErrorCode.RESYNC_REQUIRED` to `OnlyGatewayResyncRequired`. Every other specified non-zero stream
application code maps to `OnlyGatewayApplicationError(code, message)`; transport `grpc.RpcError` remains
`OnlyGatewayTransportError`, and code zero remains an unspecified protocol error. A deterministic TEST-ONLY `--stream-error` fixture
option proves `INTERNAL_ERROR` preserves the generic application-error type while the existing bounded-history test continues to prove
the exact RESYNC mapping.

The original exact Protobuf pin, `6.31.0`, produced two High findings in the committed-HEAD OSV-Scanner 2.5.0 artifact:

```text
CVE-2025-4565 / GHSA-8qvm-5x2c-j2w7
CVE-2026-0994 / GHSA-7gcm-g887-7qv7
```

The closure selects exact `protobuf==6.33.5`. It is the smallest compatible 6.x version that is outside both current affected ranges:
the first advisory is fixed by `6.31.1`, while the second affects `6.30.0rc1` through `6.33.4` and is fixed by `6.33.5`. A current direct
OSV API query for PyPI `protobuf` `6.33.5` returned no vulnerabilities. `grpcio-tools==1.73.1` and `grpcio==1.73.1` remain unchanged and
exactly pinned. `uv lock` updated only the Protobuf resolution from `6.31.0` to `6.33.5`.

Canonical `.proto` bytes and protocol v1 semantics remain unchanged. Regeneration under the secure exact runtime produced no generated
file delta and no descriptor delta:

```text
old descriptor SHA256: 5cb5005475e24019669a8658a5189b9d6321488f3e3c675bdc0195b826dfd67e
new descriptor SHA256: 5cb5005475e24019669a8658a5189b9d6321488f3e3c675bdc0195b826dfd67e
protocol package major: onlyalpha.gateway.v1
canonical Proto semantic delta: 0
```

### Closure verification evidence

Local PASS:

```text
project-state consistency:                         PASS
Gateway write/check:                               PASS; descriptor unchanged
Gateway compatibility vs original K7 Task Base:   PASS (bootstrap)
Gateway compatibility vs closure base:            PASS; no errors
fixed command-fingerprint vector:                  PASS; 1 passed
Gateway contract + historical task-delta:          11 passed
remote Gateway cross-process integration:          12 passed
canonical Architecture lane:                       498 passed
protocol-package strict mypy:                      PASS; 15 source files
repository Ruff check / format:                    PASS; 1491 files
Import Linter:                                     PASS; 3 kept, 0 broken
version graph:                                     PASS; 0.9.7
all-package source/wheel build:                    PASS
git diff --check:                                  PASS
OSV API query for protobuf 6.33.5:                 PASS; zero findings
```

Budgeted impact-aware verification passed all 10 locally scheduled static commands and returned exit code `3`
(`LOCAL_PASS_CI_REQUIRED`) because verification-infrastructure changes expand the required plan beyond the local budget. Manifest:

```text
test-results/verification/local-budget/20260828T041347Z-25077159ab50-1500/manifest.json
```

The plan retains 31 `deferred_to_ci` commands. The directly applicable version check and all-package build were executed separately and
passed, but the impact manifest's remaining Web, Kernel, Research, Core, Recovery, A-share and MiniQMT commands stay `CI REQUIRED`; they
are not rewritten as PASS by those direct checks.

The cross-process integration test required authorized localhost binding after the default sandbox rejected `127.0.0.1:0`; no external
provider, account, or network service was contacted. The current GitHub run for the original committed SHA is retained as historical
evidence: `static`, `gateway-protocol`, and `build` succeeded, while `architecture` and `dependency-audit` failed for the two closure
findings above. The closure-fix worktree is not yet an immutable remote CI subject, so committed-HEAD closure CI remains `CI REQUIRED`
and is not represented as PASS.

### Closure invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| architecture is a current-tree property | PASS | history comparison removed; canonical Architecture 498 passed |
| historical K7 delta has one authority | PASS | dedicated contract test and sole baseline constant |
| missing required baseline fails closed | PASS | explicit negative helper test |
| Product OpenAPI and protected P9 semantics unchanged | PASS | exact bytes / empty protected-path diff |
| canonical Proto and v1 topology unchanged | PASS | zero source/generated/descriptor delta; compatibility PASS |
| command identity/replay remains deterministic | PASS | existing cross-process replay/conflict/response-loss tests PASS |
| stream continuity and error taxonomy are exact | PASS | ordering/duplicate/gap/resume/resync/restart and non-resync tests PASS |
| transport failures remain separate | PASS | response-loss transport uncertainty test PASS |
| toolchain is exact, deterministic, and clears known K7 Protobuf findings | PASS | exact pin, fresh generation, current OSV query |
| no new business or persistence authority | PASS | reverse audit and zero protected semantic/database delta |

### Closure reverse audit

```text
new Product API authority?                 NO
new Product route?                         NO
new Gateway production RPC?                NO
new protocol major?                        NO
canonical Proto semantic change?           NO
new business mutation authority?           NO
new Strategy identity?                     NO
new Portfolio authority?                   NO
new Risk authority?                        NO
new persistence authority?                 NO
new provider-specific protocol?            NO
QMT implementation started?                NO
CTP implementation started?                NO
K8 started?                                NO
P9.1 started?                              NO
semantic dependency on Git clone depth?    NO
semantic dependency on network timing?     NO
```

All three closure findings are resolved in the current worktree and all locally executable closure invariants pass. Final closure remains
`CI REQUIRED` until the correction is committed and the required committed-HEAD `static`, `architecture`, `gateway-protocol`, `build`,
and `dependency-audit` jobs succeed. Until then the strict closure verdict is:

```text
P9.K.7 Closure Fix = NOT CLOSED
P9.K.8 = DO NOT START
```

## Committed-HEAD Final Closure Verification

- Original P9.K.7 Task Base SHA: `baa91014ec4e0197ac5c34f41138abc68c18471a`
- Original K7 implementation SHA: `25077159ab50a42d5125195cf82731543f37a8f7`
- Closure-fix base SHA: `25077159ab50a42d5125195cf82731543f37a8f7`
- Closure-fix committed SHA: `dfebfd4eeafe8aaa187133e6437e97d879de9f13`
- Current documentation-closure task base SHA: `dfebfd4eeafe8aaa187133e6437e97d879de9f13`
- Current documentation-closure task final SHA/worktree: `dfebfd4eeafe8aaa187133e6437e97d879de9f13 + dirty documentation-closure worktree`
- Gate: P9.K.7 Final Evidence / Documentation Closure Task Gate only; no Phase Gate or Final-SHA Certification claim

The immutable closure-fix subject `dfebfd4eeafe8aaa187133e6437e97d879de9f13` passed the five required committed-HEAD CI jobs:

```text
static            PASS
architecture      PASS
gateway-protocol  PASS
build             PASS
dependency-audit  PASS
```

That committed evidence proves the three post-commit closure corrections:

1. Architecture current-tree verification no longer depends on undeclared clone history.
2. Historical K7 task delta has one explicit full-history authority and fails closed if its baseline is missing.
3. Stream application error taxonomy is exact and Protobuf is safely pinned to 6.33.5.

The closure preserves the frozen semantic boundaries:

```text
Product OpenAPI semantic delta = 0
protected P9 semantic delta    = 0
canonical Proto semantic delta = 0
protocol major                 = onlyalpha.gateway.v1
business persistence delta     = 0
```

Final Task-Gate verdict:

```text
P9.K.7 Final Evidence / Documentation Closure = CLOSED

BLOCKER = 0
MAJOR   = 0

P9.K.7 = TASK COMPLETE / VERIFIED
P9.K.8 = MAY START / IMPLEMENTATION READY
P9.1+  = remains blocked until P9.K closure
```
