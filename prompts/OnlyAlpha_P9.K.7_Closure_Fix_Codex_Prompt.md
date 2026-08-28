# OnlyAlpha — P9.K.7 Closure Fix — Codex Implementation Prompt

## 0. Task Identity

**Repository:** `zongxin1993/OnlyAlpha`  
**Task:** `P9.K.7 Closure Fix`  
**Task classification:** Post-implementation Task-Gate closure correction  
**Parent increment:** `P9.K.7 — Remote Protocol Foundation`  
**Release version:** remain `0.9.7` unless current repository authority explicitly says otherwise  
**Next increment:** `P9.K.8 — Seal Kernel`  
**P9.1+:** remain blocked until P9.K closure

This is **NOT**:

- P9.K.7.1;
- a new feature increment;
- a redesign of K7;
- P9.K.8 work;
- QMT/CTP implementation;
- a new protocol version;
- a Phase Gate or Certification Gate.

This task exists only to make P9.K.7 closure evidence converge with the already-correct K7 implementation.

---

# 1. Baselines: Do Not Confuse These Two SHAs

At prompt preparation time, `master` was observed at:

```text
OBSERVED_CLOSURE_BASE_SHA
25077159ab50a42d5125195cf82731543f37a8f7
```

The original P9.K.7 implementation Task Base is:

```text
P9_K7_TASK_BASE_SHA
baa91014ec4e0197ac5c34f41138abc68c18471a
```

These SHAs have different meanings.

## 1.1 Closure Base

Before editing anything, fetch/read the actual current `master` and record:

```text
CLOSURE_BASE_SHA=<actual current HEAD>
```

If current `master` has moved beyond `25077159...`, current repository truth wins.

Do not blindly reset to the observed SHA.

## 1.2 Original K7 Task Base

`baa91014ec4e0197ac5c34f41138abc68c18471a` remains the immutable historical baseline for proving that P9.K.7 did not mutate protected Product/P9 semantic sources.

Do **not** replace this historical K7 Task Base merely because the closure-fix starting HEAD changes.

The intended relation is:

```text
P9_K7_TASK_BASE_SHA
      │
      └── proves original K7 scope preservation

CLOSURE_BASE_SHA
      │
      └── proves what this closure fix itself changed
```

---

# 2. Mandatory Repository Re-read Before Work

Before modifying files, read the current versions of:

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
docs/p9_k7_remote_gateway_protocol.md

docs/reports/p9_k7_remote_protocol_foundation.md

contracts/gateway/v1/**
scripts/gateway_protocol.py

packages/protocol/onlyalpha-gateway-protocol/**
tests/architecture/test_p9_k7_remote_protocol_boundary.py
tests/contracts/test_gateway_protocol_contract.py
tests/integration/test_remote_gateway_protocol.py
tests/fixtures/remote_gateway/server.py

.github/workflows/quality.yml
.github/workflows/certification.yml

pyproject.toml
uv.lock
```

Also inspect current CI evidence for the actual current HEAD where available.

Repository facts override this prompt if the repository has legitimately evolved.

If the current repository no longer matches the problem described below, stop and report the divergence rather than blindly applying stale patches.

---

# 3. Current Project-State Semantics

At prompt preparation time, `project-state.toml` declared:

```text
last_verified_increment = P9.K.7
last_verified_state = TASK COMPLETE / VERIFIED

next_authorized_increment = P9.K.8
next_authorized_state = IMPLEMENTATION READY
```

This closure fix was discovered **after** K7 was marked verified.

Therefore:

- do not hand-edit `project-state.toml`;
- do not invent `P9.K.7.1`;
- do not start P9.K.8;
- do not transition P9.K.8 ACTIVE;
- run the current project-state consistency check before and after the fix;
- if current tooling has a supported reopen/amend/correction mechanism, use it only if repository rules explicitly require it;
- otherwise keep state tooling untouched and repair the evidence/report around the existing P9.K.7 closure.

Expected initial check:

```bash
uv run python scripts/project_state.py check
```

Use current repository command syntax if it has changed.

---

# 4. First-Principles Problem Statement

P9.K.7's core implementation is already substantially correct.

It established:

```text
one canonical onlyalpha.gateway.v1 protocol
independent gateway protocol package
Unary / Streaming separation
remote command identity
idempotent replay
same-ID/different-intent conflict
explicit sequence authority
gap / resume / resync semantics
gateway process-instance identity
no exactly-once delivery claim
Core ↔ gRPC architecture firewall
provider-neutral test Gateway
```

The closure problem is different:

```text
correct implementation
≠
reliably reproducible proof of correctness
```

The primary observed failure was:

```text
same committed HEAD

full-history developer checkout
→ Architecture PASS

GitHub shallow checkout
→ Architecture FAIL
```

because a K7 architecture test implicitly requires an old Git commit object that the canonical Architecture CI job does not provide.

The verification function is currently effectively:

```text
VerificationResult =
F(
    repository content,
    undeclared Git-history availability
)
```

It must become:

```text
VerificationResult =
F(
    repository content,
    explicitly declared verification inputs
)
```

The closure fix also needs to correct:

1. a stream-error projection that maps every non-zero stream application error to `OnlyGatewayResyncRequired`;
2. a K7-introduced exact-pinned Protobuf version that current dependency-audit evidence has identified as vulnerable.

---

# 5. Fundamental Closure Goal

The closure fix must make these facts converge:

```text
implementation truth
verification truth
CI truth
documentation truth
project-state truth
```

The success criterion is:

> P9.K.7 remains semantically unchanged, but its Task-Gate evidence becomes reproducible, fail-closed, accurately typed, and free of the known K7-introduced Protobuf security finding.

---

# 6. Frozen K7 Semantics — MUST NOT CHANGE

The following are already-correct K7 decisions and are not redesign targets.

## 6.1 Product vs Infrastructure Boundary

Remain:

```text
Product Actor
→ HTTPS / canonical OpenAPI
→ Product Command / Query
→ Stateful Kernel
→ typed Kernel Port
→ Remote Infrastructure Adapter
→ Protobuf / gRPC
→ future Gateway
```

Never:

```text
Product Actor
→ Gateway directly
```

## 6.2 Kernel Transport Boundary

`src/onlyalpha/**` must remain free from direct:

```text
grpc
google.protobuf Gateway transport implementation
onlyalpha_gateway_protocol generated transport dependency
```

## 6.3 Protocol Authority

The canonical source remains the `.proto` set under current:

```text
contracts/gateway/v1/**
```

with compatibility-major authority:

```protobuf
package onlyalpha.gateway.v1;
```

Generated Python files and `descriptor.pb` remain deterministic projections, not authoring authorities.

## 6.4 Unary vs Streaming

Remain separate:

```text
GatewayService
- Handshake
- ApplyTestMutation

GatewayStreamService
- WatchTestEvents
```

Do not create a universal bidirectional message bus.

## 6.5 Remote Command Identity

Remain:

```text
command_id
command_fingerprint
correlation_id
```

with:

```text
same command_id + same canonical intent
→ replay one logical outcome

same command_id + different canonical intent
→ deterministic COMMAND_CONFLICT

correlation_id
→ transport-attempt identity only
```

## 6.6 No Exactly-Once Claim

Remain explicit:

```text
OnlyAlpha Remote Protocol does not claim exactly-once network delivery.
```

## 6.7 Stream Semantics

Remain:

```text
sequence == last + 1
→ accept

sequence <= last
→ duplicate/replay recognition

sequence > last + 1
→ explicit resync/gap

unavailable exact continuation
→ RESYNC_REQUIRED
```

Wall-clock timestamps remain evidence only, never ordering authority.

## 6.8 Gateway Instance

`gateway_instance_id` continues to identify one concrete Gateway process lifetime.

Gateway restart remains observable and requires re-handshake/revalidation.

## 6.9 Provider Scope

Do not implement:

```text
QMT
CTP
xtquant
MiniQMT
SubmitOrder
CancelOrder
real Account/Position RPC
LIVE execution
production Broker gateway
```

during this closure fix.

---

# 7. Closure Findings to Fix

The task has exactly three intended findings.

Do not expand the task simply to “find more things.”

---

## F-CF-01 — Architecture Verification Has an Undeclared Git-History Dependency

### Current behavior

`tests/architecture/test_p9_k7_remote_protocol_boundary.py` contains a historical check conceptually equivalent to:

```python
base = "baa91014ec4e0197ac5c34f41138abc68c18471a"

git show <base>:contracts/research-api/v2/openapi.json
git diff <base> -- protected_semantic_paths
```

The canonical `architecture` GitHub job currently uses normal shallow checkout.

Therefore the old object may not exist and the test fails even though the current source tree satisfies the architecture invariants.

Observed canonical failure at `25077159...`:

```text
498 passed
1 failed
```

with the failure caused by:

```text
git show baa91014... returned exit status 128
```

### Root cause

Two different verification responsibilities are mixed:

```text
Current-tree Architecture Verification
```

and:

```text
Historical Task-Scope Delta Verification
```

### Required correction

Separate them.

---

## F-CF-02 — Stream Application Errors Collapse Into RESYNC_REQUIRED

Current client logic conceptually does:

```python
if stream_item.error.code:
    raise OnlyGatewayResyncRequired(...)
```

This means:

```text
INTERNAL_ERROR
PROVIDER_UNAVAILABLE
NOT_READY
...
```

are misprojected as:

```text
RESYNC_REQUIRED
```

The current test fixture only emits `RESYNC_REQUIRED` on stream errors, so existing tests did not expose the semantic collapse.

### Required correction

Preserve the protocol error taxonomy in client semantics.

---

## F-CF-03 — K7-Introduced Protobuf Exact Pin Is Known Vulnerable

At prompt preparation time the protocol package used:

```text
protobuf==6.31.0
```

Current dependency-audit evidence identified Protobuf advisories affecting that exact version.

The exact safe replacement must be determined from **current** repository/OSV evidence when Codex executes this task.

Do not assume a stale fixed version merely from this prompt.

### Required correction

Upgrade to the smallest currently safe, compatible exact pin while preserving deterministic protocol generation and v1 semantics.

---

# 8. Closure Invariants

The implementation must enforce the following.

## CF-INV-01 — Architecture Verification Is a Current-Tree Property

Canonical Architecture tests must be decidable from explicitly available current repository content and declared runtime/tool inputs.

They must not silently depend on old Git objects.

---

## CF-INV-02 — Historical Task Delta Is a Separate Verification Authority

Historical comparison against `P9_K7_TASK_BASE_SHA` must exist separately from current-tree architecture verification.

---

## CF-INV-03 — One K7 Historical Task Base Authority Exists

Use exactly one test/script authority for:

```text
baa91014ec4e0197ac5c34f41138abc68c18471a
```

Do not scatter the SHA across unrelated production/test modules.

Do not place it in the runtime protocol package.

---

## CF-INV-04 — Missing Required Historical Baseline Fails Closed

If the task-delta verification requires the historical baseline and the Git object is unavailable:

```text
FAIL
```

Never:

```text
skip
xfail
silent pass
```

The CI lane responsible for this verification must explicitly provide full history.

---

## CF-INV-05 — Canonical Proto Semantics Remain Unchanged

Expected:

```text
contracts/gateway/v1/**
semantic delta = 0
```

Prefer byte-for-byte `.proto` equality across the closure fix.

If any canonical `.proto` source must change, stop and explain why before treating the task as complete.

---

## CF-INV-06 — Protocol Major Remains v1

Remain:

```protobuf
package onlyalpha.gateway.v1;
```

A toolchain/security dependency change does not justify `v2`.

---

## CF-INV-07 — Generation Toolchain Remains Exactly Pinned

The selected secure versions must be exact, reproducible pins.

No loose:

```text
protobuf>=...
```

for generation/runtime components where the deterministic K7 toolchain contract requires exact versions.

---

## CF-INV-08 — Toolchain Security Upgrade Does Not Change Protocol Semantics

A changed compiler/runtime may change generated bytes or descriptor bytes.

That is acceptable only if:

```text
canonical proto semantic source unchanged
+
compatibility check passes
+
all K7 cross-process semantics remain unchanged
```

---

## CF-INV-09 — RESYNC_REQUIRED Has One Special Client Interpretation

Only:

```text
GatewayErrorCode.RESYNC_REQUIRED
```

maps to:

```text
OnlyGatewayResyncRequired
```

---

## CF-INV-10 — Other Gateway Application Errors Remain Application Errors

Other non-zero Gateway application errors must map to:

```text
OnlyGatewayApplicationError(code, message)
```

or the current equivalent stable generic application-error type.

Do not create a broad exception-class hierarchy without real need.

---

## CF-INV-11 — Transport Errors Remain Separate

`grpc.RpcError` / transport failures remain:

```text
OnlyGatewayTransportError
```

They must not be collapsed into Gateway application errors.

Mutation transport timeout/UNAVAILABLE still means:

```text
outcome unknown
```

not business rejection.

---

## CF-INV-12 — No Business Semantic Identity Changes

Closure-fix metadata, dependency versions, descriptor SHA, CI configuration, transport error codes, task baseline SHA, etc. must not enter:

```text
Dataset fingerprint
Calculation identity
Candidate identity
Strategy fingerprint
Strategy Revision identity
```

---

## CF-INV-13 — No New Authority

The fix must create no new:

```text
Product API authority
business mutation authority
Strategy authority
Portfolio authority
Risk authority
Kernel authority
persistence authority
provider protocol authority
```

---

## CF-INV-14 — K8 Does Not Start

P9.K.8 remains untouched until this closure evidence passes.

---

# 9. Workstream A — Verification Responsibility Correction

This is the blocking part of the closure fix.

## 9.1 Keep Architecture Lane Current-Tree Only

`tests/architecture/test_p9_k7_remote_protocol_boundary.py` should continue to prove current architecture facts such as:

```text
Core/business modules have zero Gateway transport dependency
protocol package is independent of Core/Product/API
test Gateway remains fixture/infrastructure-only
Product API/client do not bypass Kernel to Gateway RPC
Gateway v1 Proto authority is unique/provider-neutral
generated protocol projection is fresh
```

However, remove/move the historical `TASK_BASE_SHA` comparison out of this current-tree architecture suite.

Do not weaken any real architecture invariant.

Do not simply skip the failing historical test.

---

## 9.2 Create a Dedicated K7 Task-Delta Verification

Preferred conceptual file:

```text
tests/contracts/test_p9_k7_task_delta.py
```

Adapt the exact filename to current repository conventions if necessary.

Its single purpose:

> Prove that original P9.K.7 did not mutate protected Product/P9 semantic sources relative to its immutable Task Base.

It should own one constant:

```python
P9_K7_TASK_BASE_SHA = "baa91014ec4e0197ac5c34f41138abc68c18471a"
```

Do not duplicate this constant elsewhere unless current repository architecture provides an existing single metadata authority.

---

## 9.3 Baseline Existence Guard

Before comparison, mechanically verify:

```bash
git cat-file -e "${P9_K7_TASK_BASE_SHA}^{commit}"
```

Equivalent Python subprocess is acceptable.

If missing:

```text
fail with a clear diagnostic
```

Never skip.

---

## 9.4 Product OpenAPI Scope Guard

Compare the exact canonical Product OpenAPI file at original K7 Task Base with current HEAD.

Expected:

```text
contracts/research-api/v2/openapi.json
byte delta = 0
```

This is **not** a second OpenAPI compatibility authority.

It answers only:

```text
Did K7 change the Product OpenAPI at all?
```

Existing `openapi-contract` remains the authority for OpenAPI compatibility/governance.

---

## 9.5 Protected P9 Semantic Source Guard

Compare current HEAD to the original K7 Task Base across the exact protected paths frozen by current K7 design.

The previous K7 test used conceptually:

```text
src/onlyalpha/research
src/onlyalpha/strategy
src/onlyalpha/application
src/onlyalpha/kernel
src/onlyalpha/runtime
src/onlyalpha/execution
```

Re-read current K7 task/report before finalizing the exact list.

Expected:

```text
git diff --name-only P9_K7_TASK_BASE_SHA -- <protected paths>
→ empty
```

This proves scope preservation only.

Do not turn this into a full business correctness certification.

---

## 9.6 Run Historical Task Delta in a Full-History Lane

Preferred placement:

```text
gateway-protocol GitHub job
```

because that job already legitimately requires:

```yaml
fetch-depth: 0
```

for immutable protocol compatibility checks.

Add the K7 task-delta test to that lane.

Conceptually:

```yaml
gateway-protocol:
  checkout:
    fetch-depth: 0

  steps:
    - gateway_protocol verify
    - gateway protocol contract tests
    - K7 task-delta test
    - remote gateway integration tests
```

Do not make the entire Architecture job history-dependent merely to satisfy this test unless current repository structure leaves no cleaner choice.

---

# 10. Why Moving the Test Is Better Than `fetch-depth: 0` on Architecture

A minimal patch could add full history to the Architecture job.

That would make the immediate test pass, but it would leave the responsibility model blurred.

Preferred model:

```text
Architecture state
→ current-tree Architecture lane

Historical Task Scope
→ immutable-baseline K7 contract/closure lane
```

This follows:

```text
one question
→ one verification authority
```

and keeps Architecture reproducible from the current source tree.

Use the smaller `fetch-depth: 0` Architecture fix only if current repository rules explicitly prefer it and no responsibility separation is practical.

If choosing that alternative, document why.

---

# 11. Workstream B — Stream Error Projection Correction

## 11.1 Required Client Behavior

Modify the stream error handling so it behaves conceptually as:

```python
if item.HasField("error"):
    code = item.error.code
    message = item.error.message

    if code == RESYNC_REQUIRED:
        raise OnlyGatewayResyncRequired(message)

    if code:
        raise OnlyGatewayApplicationError(code, message)

    raise OnlyGatewayProtocolError("stream returned an unspecified error")
```

Use current generated enum symbols/imports and current project naming.

Do not use magic numeric literals if an enum symbol exists.

---

## 11.2 Preserve Transport Error Behavior

Keep:

```text
grpc.RpcError
→ OnlyGatewayTransportError
```

Do not reinterpret:

```text
UNAVAILABLE
DEADLINE_EXCEEDED
```

transport results as business/application rejection.

Mutation `outcome_unknown=True` semantics must remain unchanged.

---

## 11.3 Test Fixture Error Injection

Add the smallest deterministic TEST-ONLY mechanism needed to emit a non-RESYNC stream application error.

Preferred conceptual CLI:

```text
--stream-error INTERNAL_ERROR
```

or equivalent deterministic fixture configuration.

Requirements:

- test-only;
- provider-neutral;
- no production code branch;
- no random failure timing;
- no new business semantics.

---

## 11.4 Required Error Mapping Tests

Add/adjust tests proving:

### RESYNC

```text
Gateway emits RESYNC_REQUIRED
→ client raises OnlyGatewayResyncRequired
```

### Non-RESYNC

For example:

```text
Gateway emits INTERNAL_ERROR
→ client raises OnlyGatewayApplicationError
→ error.code == INTERNAL_ERROR
```

and explicitly not:

```text
OnlyGatewayResyncRequired
```

### Unspecified Error

If current protocol permits error envelope with code zero, preserve/freeze the current fail-closed unspecified-error behavior.

Do not overbuild the test matrix.

---

# 12. Workstream C — Secure Deterministic Protobuf Toolchain

## 12.1 Re-read Current Security Evidence

Do not hard-code a security version based solely on this prompt.

At implementation time:

1. inspect current `uv.lock`;
2. inspect current protocol package pins;
3. inspect latest current CI dependency-audit evidence for the current HEAD;
4. identify all currently applicable Protobuf advisories affecting the selected version;
5. choose the **minimum safe compatible exact version** that clears all current K7-introduced Protobuf findings.

If current repository has already fixed the vulnerability, do not redo it.

---

## 12.2 Version Selection Principles

The selected version must satisfy:

```text
safe against current relevant OSV advisories
compatible with Python 3.12
compatible with selected grpcio/grpcio-tools
compatible with the repository's generated-code runtime
exactly pinned
```

Prefer:

```text
minimum safe compatible change
```

over:

```text
upgrade everything to latest
```

Do not turn this into dependency modernization.

---

## 12.3 Keep Toolchain Version Authority Coherent

At prompt preparation time, `scripts/gateway_protocol.py` explicitly enforced exact versions for:

```text
grpcio-tools
grpcio
protobuf
```

Continue to have one coherent exact toolchain authority.

If package metadata and script constants both require edits, keep them exactly aligned.

Do not create a third independent CI-only version definition.

Do not perform a broad framework refactor simply to deduplicate three constants.

---

## 12.4 Update Lockfile

Use normal repository dependency tooling.

Conceptually:

```bash
uv lock
```

or current repository-prescribed equivalent.

Do not manually edit `uv.lock`.

---

## 12.5 Regenerate Protocol Projection

After toolchain change:

```bash
uv run python scripts/gateway_protocol.py write
```

or current equivalent.

Then verify:

```bash
uv run python scripts/gateway_protocol.py check
```

Generated files may or may not change.

Do not manually edit generated `_pb2.py`, `_pb2.pyi`, `_pb2_grpc.py`, or descriptor bytes.

---

# 13. Protocol Semantic Preservation During Toolchain Upgrade

The following must remain true.

## 13.1 Canonical `.proto` Source

Expected:

```text
no semantic change
prefer byte-for-byte no change
```

## 13.2 Protocol Major

Remain:

```text
onlyalpha.gateway.v1
```

## 13.3 RPC Topology

Remain:

```text
Handshake                 unary
ApplyTestMutation         unary
WatchTestEvents           server-streaming
```

## 13.4 Error Taxonomy

Do not alter canonical error-code meanings as part of this closure fix.

## 13.5 Command Fingerprint

`canonical_test_mutation_fingerprint(payload)` must remain semantically identical.

Same known payload before/after the fix must produce the same SHA256.

If no fixed-vector regression currently exists, add one only if it is the smallest useful way to lock this invariant.

## 13.6 Receipt Semantics

Remain:

```text
same command ID + same fingerprint
→ replay

same command ID + different fingerprint
→ conflict
```

## 13.7 Stream Semantics

Ordering/gap/resume/restart semantics remain unchanged.

---

# 14. Descriptor SHA Handling

The descriptor SHA is diagnostic/deployment evidence, not business identity.

If the secure toolchain upgrade changes descriptor bytes:

1. compute the new deterministic descriptor SHA;
2. update exact expected SHA assertions/evidence where appropriate;
3. verify protocol compatibility;
4. record old/new SHA in the K7 closure report.

Do **not**:

```text
descriptor SHA changed
→ protocol v2
```

Do not propagate descriptor SHA into semantic fingerprints.

---

# 15. Protocol Compatibility Verification

Run compatibility against the immutable original K7 baseline where appropriate.

Because the original K7 Task Base contains no Gateway protocol, the current script may treat it as a bootstrap.

Also verify current protocol against the relevant existing protocol baseline/current parent according to the current `gateway-protocol` CI contract.

Do not weaken compatibility rules.

Expected:

```text
compatibility errors = none
```

---

# 16. Modification Scope

Expected changed files should be concentrated in:

```text
tests/architecture/test_p9_k7_remote_protocol_boundary.py

tests/contracts/test_p9_k7_task_delta.py
tests/contracts/test_gateway_protocol_contract.py        # only if necessary

tests/integration/test_remote_gateway_protocol.py
tests/fixtures/remote_gateway/server.py

packages/protocol/onlyalpha-gateway-protocol/pyproject.toml
packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/client.py
packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol/v1/**   # generated only

scripts/gateway_protocol.py                               # exact toolchain pin only if required

.github/workflows/quality.yml

uv.lock

docs/reports/p9_k7_remote_protocol_foundation.md
```

Optional small documentation clarification:

```text
docs/p9_k7_remote_gateway_protocol.md
```

only if current wording is inaccurate after the error-projection correction.

---

# 17. Forbidden Broad Changes

Broad edits in these paths are a strong scope-leak signal:

```text
src/onlyalpha/strategy/**
src/onlyalpha/portfolio/**
src/onlyalpha/risk/**
src/onlyalpha/research/**
src/onlyalpha/kernel/**
src/onlyalpha/runtime/**
src/onlyalpha/execution/**
packages/api/onlyalpha-api/**
packages/client/onlyalpha-client/**
contracts/research-api/**
```

The K7 historical delta guard should ensure protected Product/P9 semantic sources remain unchanged relative to the original K7 Task Base.

If this closure fix appears to require business-semantic edits, stop and report why.

---

# 18. No Database/Persistence Changes

Expected closure-fix persistence delta:

```text
new PostgreSQL tables        = 0
new migrations               = 0
new durable receipt storage  = 0
new broker state authority   = 0
```

The TEST Gateway remains allowed to use in-memory deterministic receipts/history for K7 proof.

Do not add SQLite/PostgreSQL just to make the fixture “more realistic.”

---

# 19. No New Protocol Surface

Expected:

```text
new production RPCs     = 0
new provider RPCs       = 0
new QMT messages        = 0
new CTP messages        = 0
new Product API routes  = 0
```

If generated files change due to the secure toolchain, that is a projection change, not a protocol-surface change.

---

# 20. Required Verification Tests

## CF-T01 — Architecture Lane Does Not Require Historical Git Objects

Canonical Architecture tests must pass in their declared CI checkout model.

No hidden dependency on `P9_K7_TASK_BASE_SHA`.

---

## CF-T02 — Historical K7 Delta Uses Immutable Baseline

The dedicated K7 task-delta test must compare against:

```text
baa91014ec4e0197ac5c34f41138abc68c18471a
```

as an immutable Git commit.

---

## CF-T03 — Missing Baseline Fails Closed

Test/helper behavior must fail clearly if the immutable baseline cannot be resolved.

Do not skip.

If practical, unit-test the helper directly without corrupting the real Git checkout.

---

## CF-T04 — Product OpenAPI Delta Is Zero

Relative to original K7 Task Base:

```text
contracts/research-api/v2/openapi.json
→ exact unchanged bytes
```

---

## CF-T05 — Protected P9 Semantic Source Delta Is Zero

Relative to original K7 Task Base, protected semantic paths have no changed files.

---

## CF-T06 — Canonical Proto Semantic Delta Is Zero

The closure fix must not introduce `.proto` semantics.

---

## CF-T07 — Generated Protocol Is Fresh

```text
gateway_protocol.py check
→ PASS
```

---

## CF-T08 — Gateway Compatibility Passes

All applicable compatibility checks pass.

---

## CF-T09 — RESYNC Mapping Is Exact

```text
RESYNC_REQUIRED
→ OnlyGatewayResyncRequired
```

---

## CF-T10 — Non-RESYNC Mapping Is Exact

For example:

```text
INTERNAL_ERROR
→ OnlyGatewayApplicationError
```

with preserved numeric/stable code.

---

## CF-T11 — Existing Remote Command Semantics Remain Green

Must still prove:

```text
first mutation executes once
same-ID/same-intent replay
response-loss retry converges
same-ID/different-intent conflicts
correlation ID may change
```

---

## CF-T12 — Existing Stream Semantics Remain Green

Must still prove:

```text
sequence ordering
duplicate detection
gap detection
resume
RESYNC_REQUIRED
Gateway restart / new instance identity
```

---

## CF-T13 — K7 Protobuf Security Finding Is Cleared

Current dependency audit must no longer report the K7-introduced Protobuf vulnerabilities that motivated this fix.

If unrelated historical vulnerabilities remain, classify them separately; do not expand this task automatically.

---

## CF-T14 — Core/Product Architecture Remains Unchanged

Must still prove:

```text
Core Gateway transport dependency = 0
Protocol package Core dependency = 0
Product API Gateway bypass = 0
provider-specific protocol leakage = 0
```

---

# 21. Recommended Local Verification Sequence

Use current repository-prescribed commands.

A reasonable sequence is:

```bash
uv run python scripts/project_state.py check
```

Then toolchain/protocol:

```bash
uv sync --frozen --all-packages --all-groups

uv run python scripts/gateway_protocol.py check

uv run python scripts/gateway_protocol.py verify \
  --base baa91014ec4e0197ac5c34f41138abc68c18471a
```

Then targeted contract tests:

```bash
uv run pytest \
  tests/contracts/test_gateway_protocol_contract.py \
  tests/contracts/test_p9_k7_task_delta.py \
  -q
```

Then cross-process integration:

```bash
uv run pytest \
  tests/integration/test_remote_gateway_protocol.py \
  -q
```

Then canonical Architecture:

```bash
uv run python scripts/test_suite.py architecture
```

Then protocol package typing:

```bash
uv run mypy \
  --config-file packages/protocol/onlyalpha-gateway-protocol/pyproject.toml \
  packages/protocol/onlyalpha-gateway-protocol/src/onlyalpha_gateway_protocol
```

Then repository boundary/build checks relevant to the change:

```bash
uv run ruff check src tests examples packages scripts
uv run ruff format --check src tests examples packages scripts

uv run lint-imports

uv run python scripts/version_sync.py check

uv build --all-packages

git diff --check
```

Use current exact commands if the repository has changed.

---

# 22. CI Evidence Required for This Closure

The following are the important committed-HEAD evidence targets:

```text
static            SUCCESS
architecture      SUCCESS
gateway-protocol  SUCCESS
build             SUCCESS
dependency-audit  K7 protobuf finding cleared
```

Do not require unrelated full repository certification merely because GitHub CI has many jobs.

However:

```text
known real regression introduced by this closure fix
→ must be fixed
```

Classify unrelated Phase/Certification debt according to the current Quality System rather than converting it into a Task blocker.

---

# 23. Dependency Audit Scope Discipline

Do not solve unrelated dependency modernization.

If the security scan after the Protobuf upgrade reports:

```text
A. K7 Protobuf finding cleared
B. unrelated pre-existing package finding remains
```

report:

```text
K7 security closure = PASS
unrelated higher-level debt = OPEN
```

unless current repository policy makes the unrelated finding directly mandatory for this Task Gate.

If the new version itself introduces another current advisory, the version selection is invalid and must be corrected.

---

# 24. Architecture CI Responsibility

Preferred final design:

```text
Architecture job
→ current-tree architecture invariants
→ can remain shallow checkout

Gateway Protocol/K7 Closure job
→ immutable historical comparisons
→ full history checkout
```

Do not make architecture tests depend on undeclared external history again.

---

# 25. Generated Code Rules

Generated protocol files:

```text
*_pb2.py
*_pb2.pyi
*_pb2_grpc.py
descriptor.pb
```

must only be produced by the canonical generation tool.

Never manually patch generated files to make tests pass.

If generated imports/types change due to toolchain version and expose a legitimate compatibility issue, fix the source/toolchain contract, not the generated output.

---

# 26. Error Model Rules

Keep the stable separation:

```text
Transport error
→ OnlyGatewayTransportError

Gateway application error
→ OnlyGatewayApplicationError

Stream continuity failure
→ OnlyGatewayResyncRequired
```

`OnlyGatewayResyncRequired` may continue to be a subtype of the current protocol error base if that is current design.

Do not use provider-native exception strings as client logic.

---

# 27. Do Not Change Release Version

This closure fix remains part of P9.K.7.

At prompt preparation time:

```text
version = 0.9.7
```

Expected after closure:

```text
version = 0.9.7
```

Do not call:

```text
version_sync.py set 0.9.8
```

unless current repository authority has explicitly changed milestone/version mapping before implementation starts.

A dependency lock update does not itself create a new semantic increment.

---

# 28. Documentation Closure

Update:

```text
docs/reports/p9_k7_remote_protocol_foundation.md
```

Add a clear section such as:

```text
Post-Commit Closure Correction
```

Record:

```text
original P9.K.7 Task Base SHA
original K7 implementation/verified SHA
closure-fix base SHA
closure-fix final SHA/worktree SHA

original Architecture CI failure
root cause
verification-responsibility fix

old Protobuf version
new exact Protobuf version
security evidence

old descriptor SHA
new descriptor SHA             # if changed

stream error projection fix

architecture result
gateway-protocol result
targeted contract result
cross-process integration result
mypy/import/build result
dependency-audit result

Product OpenAPI delta = 0
P9 protected semantic delta = 0
canonical Proto semantic delta = 0

reverse audit
final closure verdict
```

Do not delete the historical fact that the original committed K7 HEAD had a post-commit closure issue.

Explain it accurately.

---

# 29. Design Document

`docs/p9_k7_remote_gateway_protocol.md` should normally need no redesign.

Only adjust it if the current text incorrectly implies all Gateway stream errors are resync conditions.

Do not rewrite identity/version/retry/stream architecture.

---

# 30. Project-State Closure

After all targeted evidence passes:

```bash
uv run python scripts/project_state.py check
```

must pass.

Do not start P9.K.8 during this task.

Do not manually change README/roadmap projections that are generated from project-state authority.

The final Codex response may say:

```text
P9.K.8 may now be started
```

only if closure evidence passes, but must not actually start it.

---

# 31. Closure Task Gate

P9.K.7 Closure Fix is complete only if all applicable conditions below pass.

## Gate CF-01 — Architecture Verification Reproducibility

Canonical Architecture lane passes without undeclared historical Git dependency.

## Gate CF-02 — Historical Task Delta

Immutable K7 Task Base comparison passes.

## Gate CF-03 — Product Scope Preservation

```text
Product OpenAPI delta = 0
```

## Gate CF-04 — P9 Semantic Scope Preservation

```text
protected P9 semantic source delta = 0
```

## Gate CF-05 — Canonical Protocol Preservation

```text
canonical .proto semantic delta = 0
protocol major = v1
```

## Gate CF-06 — Deterministic Generation

Generated protocol projection is fresh and deterministic under the new exact toolchain.

## Gate CF-07 — Compatibility

Protocol compatibility verification passes.

## Gate CF-08 — Error Projection

```text
RESYNC_REQUIRED
→ OnlyGatewayResyncRequired

other Gateway application error
→ OnlyGatewayApplicationError
```

## Gate CF-09 — Existing K7 Remote Command Semantics

All replay/conflict/response-loss/correlation tests remain green.

## Gate CF-10 — Existing K7 Stream Semantics

Ordering/duplicate/gap/resume/resync/restart tests remain green.

## Gate CF-11 — Security Closure

The known K7-introduced Protobuf vulnerability finding is cleared by the selected exact safe version.

## Gate CF-12 — Architecture Boundary

Core/Product/protocol dependency firewalls remain green.

## Gate CF-13 — Static/Typing/Build

Relevant Ruff/format/mypy/import-linter/version/build checks pass.

## Gate CF-14 — Report/State Consistency

Closure report reflects committed evidence and `project_state.py check` passes.

---

# 32. Reverse Audit

Before declaring completion, explicitly answer:

```text
new Product API authority?                 MUST BE NO
new Product route?                         MUST BE NO
new Gateway production RPC?                MUST BE NO
new protocol major?                        MUST BE NO
canonical Proto semantic change?           MUST BE NO
new business mutation authority?           MUST BE NO
new Strategy identity?                     MUST BE NO
new Portfolio authority?                   MUST BE NO
new Risk authority?                        MUST BE NO
new persistence authority?                 MUST BE NO
new provider-specific protocol?            MUST BE NO
QMT implementation started?                MUST BE NO
CTP implementation started?                MUST BE NO
K8 started?                                MUST BE NO
P9.1 started?                              MUST BE NO
semantic dependency on Git clone depth?    MUST BE NO
semantic dependency on network timing?     MUST BE NO
```

If an unexpected answer is YES, do not mark closure complete.

---

# 33. Stop Conditions

Stop and reassess if implementation proposes any of the following:

```text
"Just skip the historical test in shallow CI."

"Architecture should always fetch the whole repository because one K7 test needs history."

"Let's add a general Git-history audit framework."

"Since we are touching the protocol package, add real SubmitOrder now."

"Let's add qmt.proto / ctp.proto."

"Let's make every GatewayErrorCode its own exception class."

"Upgrade all Python dependencies while fixing protobuf."

"Descriptor SHA changed, therefore protocol v2."

"Generated files can be patched manually."

"Move grpc directly into Kernel execution code."

"Create durable Gateway PostgreSQL receipts now."

"Start P9.K.8 while this closure fix is running."
```

These violate task scope or first-principles authority design.

---

# 34. Minimum-Sufficient Design Rule

For each fix ask:

```text
What is the smallest mechanism that repairs the violated invariant?
```

Expected answers:

```text
Architecture CI defect
→ move historical scope check to a full-history K7 verification lane

Stream error semantic defect
→ exact RESYNC branch + generic application-error branch

Protobuf security defect
→ minimum safe compatible exact pin + regenerate/reverify
```

Do not add abstractions for hypothetical future requirements.

---

# 35. Finding Severity / Audit Discipline

Follow `docs/engineering/convergent-audit-policy.md`.

Do not invent new BLOCKER/MAJOR findings simply because optional improvements exist.

The closure task is considered converged when:

```text
the three known findings are resolved
+
all Closure Task Gate invariants pass
+
no new concrete frozen-contract violation is introduced
```

At that point stop searching for architectural “improvements” and close K7.

---

# 36. Required Final Codex Response

At completion report exactly:

```text
1. CLOSURE_BASE_SHA
2. P9_K7_TASK_BASE_SHA
3. final implementation/worktree SHA
4. files changed

5. F-CF-01 status
   - original failure
   - root cause
   - final architecture-vs-history responsibility design

6. historical K7 task-delta verification
   - baseline existence behavior
   - Product OpenAPI delta
   - protected P9 semantic delta

7. F-CF-02 status
   - RESYNC mapping
   - non-RESYNC mapping
   - tests added

8. F-CF-03 status
   - old Protobuf version
   - selected safe exact version
   - why that version
   - current security evidence result

9. canonical Proto semantic delta
10. protocol major
11. old/new descriptor SHA if changed
12. gateway protocol generation result
13. compatibility result

14. remote command replay result
15. response-loss retry result
16. same-ID/different-intent conflict result
17. correlation identity result

18. stream ordering result
19. duplicate result
20. gap result
21. resume result
22. RESYNC_REQUIRED result
23. Gateway restart result

24. Architecture lane result
25. gateway-protocol lane/result
26. protocol-package mypy result
27. import-linter result
28. Ruff/format result
29. build result
30. dependency-audit K7 Protobuf result

31. Product OpenAPI semantic delta
32. P9 business semantic delta
33. database/persistence delta
34. release version result

35. reverse-audit result
36. closure Task Gate verdict
37. project-state check result

38. explicit confirmation:
    QMT not started
    CTP not started
    real Broker submission not started
    K8 not started
    P9.1 not started

39. whether P9.K.8 is now safe to start
```

If any mandatory closure gate fails, report:

```text
P9.K.7 Closure Fix = NOT CLOSED
P9.K.8 = DO NOT START
```

Do not hide failures behind local-only evidence.

---

# 37. Final Engineering Intent

This task is successful when P9.K.7 can be stated as:

```text
Implementation
→ correct

Protocol authority
→ unique

Remote command identity
→ deterministic

Stream continuity semantics
→ deterministic

Verification responsibility
→ unique

Historical baseline
→ immutable and explicit

Architecture verdict
→ independent of accidental clone depth

Gateway error interpretation
→ one code, one meaning

Generation toolchain
→ exact, secure, deterministic

Business semantics
→ unchanged

Provider implementation
→ not started
```

The closure fix should leave the system with:

```text
Current Architecture Verification
        │
        └── current tree only

Historical K7 Scope Verification
        │
        └── immutable full-history baseline

Canonical Gateway Protocol
        │
        └── unchanged v1 semantics

Secure Exact Toolchain
        │
        └── deterministic generated projection
```

The goal is not to add capability.

The goal is to ensure:

> **OnlyAlpha's proof of correctness is itself deterministic, every protocol fact has one authoritative interpretation, and security maintenance cannot silently change frozen protocol/business semantics.**

Once these conditions are mechanically proven, stop modifying P9.K.7 and leave P9.K.8 as the next authorized task.
