# OnlyAlpha — P9.K.8 Seal Kernel — Codex Implementation Prompt

## 0. Task Identity

**Repository:** `zongxin1993/OnlyAlpha`  
**Task:** `P9.K.8 — Seal Kernel`  
**Parent milestone:** `P9.K — Stateful Kernel & Protocol Boundary`  
**Task type:** Architecture closure / hard-seal Task Gate  
**Expected release mapping:** `0.9.8`  
**Prerequisite:** `P9.K.7 Remote Protocol Foundation = TASK COMPLETE / VERIFIED`  
**After successful closure:** `P9.K = CLOSED`, then and only then may `P9.1` become implementation-ready.

This prompt is not a second repository authority.

At task start, read current repository truth and record:

```bash
TASK_BASE_SHA=$(git rev-parse HEAD)
git status --short
```

Then verify current project state using the repository-owned state tooling.

If current repository state does **not** authorize:

```text
P9.K.8 = IMPLEMENTATION READY
```

stop and report the state mismatch.

If the repository already contains a verified, closed P9.K.8 implementation satisfying the invariants below:

```text
STOP
P9.K.8 = ALREADY IMPLEMENTED / DO NOT DUPLICATE
```

Do not modify the repository merely to execute this prompt.

---

# 1. First-Principles Problem

P9.K.1–K7 have built the correct target architecture:

```text
External Product Actor
        ↓
HTTPS / JSON / canonical OpenAPI
        ↓
Product Command / Query
        ↓
Stateful Kernel
        ↓
typed internal/infrastructure ports
```

But the existence of a correct path does not prove it is the **only supported path**.

The current historical architecture still contains legacy Product-facing capabilities such as:

```text
root Python Engine / Runtime / Cluster constructors
root CLI commands that directly construct OnlyEngine
legacy compatibility HTTP surfaces
```

As long as these remain supported, OnlyAlpha can still be controlled through more than one mutation path.

That violates the target product model.

The K8 problem is therefore:

> eliminate every supported Product-space mutation bypass so that one external product intent has one authoritative interpretation path.

The first-principles invariant is:

```text
One Product Mutation
→ One Supported External Authority
→ Product Control Plane
→ Stateful Kernel
```

K8 is a **subtraction / sealing task**.

It is not a feature expansion milestone.

---

# 2. Task Purpose

P9.K.8 must convert the architecture from:

```text
correct Product path exists
+
legacy Product bypasses still exist
```

into:

```text
correct Product path
=
only supported external mutation path
```

The result must make these statements mechanically true:

```text
External Product Actor
-X→ OnlyEngine
-X→ Runtime
-X→ Cluster mutation constructor
-X→ Kernel mutation capability
-X→ raw persistence writer
-X→ semantic publisher
-X→ remote Gateway as Product API

External Product Actor
→ Product Control Plane only
```

This is necessary before P9.1+ introduces real Market, Broker, Execution, Risk and LIVE capabilities.

---

# 3. Governing Repository Truth

Before editing, read current versions of:

```text
AGENTS.md
project-state.toml

docs/engineering/quality-system.md
docs/engineering/convergent-audit-policy.md

docs/adr/0101-stateful-kernel-and-protocol-boundary.md
docs/p9_k_stateful_kernel_protocol_boundary.md

docs/reports/p9_k0_product_surface_inventory.md
docs/architecture/p9_k6_external_client_contract.toml
docs/reports/p9_k6_external_client_migration.md
docs/reports/p9_k7_remote_protocol_foundation.md

tests/architecture/test_p9_k0_product_surfaces.py
tests/architecture/test_p9_k6_external_client_boundary.py

src/onlyalpha/__init__.py
src/onlyalpha/cli.py

src/onlyalpha/engine/__init__.py
src/onlyalpha/runtime/__init__.py
src/onlyalpha/cluster/__init__.py

packages/client/onlyalpha-client/
packages/api/onlyalpha-api/
apps/onlyalpha-web/
```

Also inspect current repository references before removing any compatibility surface.

Truth priority:

```text
current executable source / public interfaces
>
current tests / architecture gates / acceptance
>
active ADRs
>
current docs
>
reports
>
historical prompts
```

Do not treat this prompt as newer than repository truth.

---

# 4. Core Design Principle

P9.K.8 is a **hard seal**, not a soft deprecation.

Do not preserve a Product mutation bypass through a warning proxy such as:

```python
def OnlyEngine(...):
    warnings.warn("deprecated")
    return _real_engine(...)
```

That still leaves a second mutation path.

The rule is:

```text
unsupported legacy Product mutation path
→ removed / unavailable / fail closed
```

not:

```text
unsupported legacy Product mutation path
→ warning
→ still executes
```

K6 already migrated supported external clients.

K8 closes the old path.

---

# 5. Product Space vs Internal / Operator / Test Space

Do not confuse “remove Product bypasses” with “ban all direct internal construction”.

K8 must preserve three distinct categories.

## 5.1 Product Space

Examples:

```text
Web
Python Product SDK
Agent
Automation
Product CLI
external application integration
```

Rule:

```text
Product Space
→ Product Control Plane
→ Command / Query
→ Stateful Kernel
```

Product Space must NOT directly construct or mutate through:

```text
OnlyEngine
OnlyRuntime
OnlyBacktestRuntime
OnlyLiveRuntime
OnlyResearchRuntime
OnlyCluster
KernelHost
raw persistence writer
semantic publisher
Gateway protocol client
```

## 5.2 Operator / Infrastructure Space

Examples may include current repository-owned:

```text
database administration
operations diagnostics
research worker
provider doctor
infrastructure maintenance
```

These may have narrowly justified direct infrastructure access.

Do not accidentally force operator tooling through Product API when its semantics are not Product mutation.

But operator access must remain explicitly classified and bounded.

## 5.3 Test / Scenario / Internal Composition

Examples:

```text
scenario runner
test fixtures
runtime factories
research execution internals
integration tests
composition roots
```

These may construct Engine/Runtime directly when required for deterministic internal composition.

Do not destroy internal execution architecture just to make Python imports impossible.

The target is:

```text
no supported external Product construction
```

not:

```text
no internal construction anywhere
```

---

# 6. Mandatory Invariant Matrix

Before coding, write a K8 invariant matrix and map each invariant to:

```text
current evidence
required code change
required test/gate
acceptance evidence
```

The following invariants are mandatory.

## INV-K8-01 — Unique Product Mutation Path

All supported external Product mutations must enter through:

```text
Product Control Plane
→ Product Command Dispatcher
→ Stateful Kernel / Application Authority
```

No second supported Product mutation authority may remain.

## INV-K8-02 — Root Python Seal

The root package:

```python
import onlyalpha
```

must no longer expose mutation-oriented Engine/Runtime/Cluster constructors classified by K0/K6 as migration debt.

Historical debt set includes:

```text
OnlyBacktestRuntime
OnlyCluster
OnlyClusterConfig
OnlyClusterContext
OnlyClusterLoader
OnlyClusterRegistry
OnlyClusterRunConfig
OnlyDemoCluster
OnlyDemoRecord
OnlyEngine
OnlyLiveRuntime
OnlyResearchRuntime
OnlyRuntime
```

Use the current repository's K0 frozen migration-debt set as authority.

Required final property:

```text
ROOT_KNOWN_MIGRATION_DEBT = 0
```

Do not remove stable non-debt read-only/value/public utilities merely because they are root exports.

## INV-K8-03 — Root Product CLI Seal

The legacy root CLI must no longer offer direct Product mutation through:

```text
onlyalpha run
onlyalpha snapshot
```

These paths historically construct `OnlyEngine` directly.

Required final property:

```text
onlyalpha run      → absent
onlyalpha snapshot → absent
```

Do not replace them with hidden local compatibility behavior.

## INV-K8-04 — Product CLI Authority

The supported Product CLI must be:

```text
onlyalpha-client
```

or the current equivalent explicitly defined by K6.

It must communicate through the Product HTTP/OpenAPI boundary.

Do not add a second Product CLI implementation.

## INV-K8-05 — External Client Firewall

The Product client and Web must not import mutation-capable Core internals.

At minimum prohibit Product client/Web dependency on:

```text
onlyalpha.engine
onlyalpha.runtime
onlyalpha.kernel
onlyalpha.application
onlyalpha.persistence
onlyalpha.strategy mutation internals
onlyalpha_gateway_protocol
```

The exact package/import rules should follow current K6 architecture contract.

## INV-K8-06 — No Local Product Fallback

There must be no behavior equivalent to:

```text
Product API unavailable
→ silently construct local Engine/Runtime
→ continue mutation locally
```

Failure to reach the Product Control Plane must remain failure.

No hidden authority substitution.

## INV-K8-07 — HTTP Route Capability Narrowing

Mutation-capable API routes may depend on narrow Product Command/Query boundaries.

They must not directly obtain or construct:

```text
OnlyEngine
Runtime
KernelHost mutation capability
raw PostgreSQL writers
Strategy semantic publishers
Research command implementation services
provider Gateway clients
```

The route owns:

```text
transport validation
DTO mapping
actor/auth context
HTTP error mapping
Command / Query invocation
```

It does not own business or persistence authority.

## INV-K8-08 — Composition Root Ownership

Explicit composition roots are allowed to wire real capabilities.

For example, a composition root may legitimately build:

```text
PostgreSQL stores
Registry
Kernel Host
Command services
Product Boundary
FastAPI application
```

Do not create an invalid blanket rule like:

```text
"the API package may never import persistence"
```

Correct rule:

```text
Composition Root CAN wire capabilities.
HTTP Route CANNOT own capabilities.
```

Do not introduce a generic dependency-injection framework merely to hide explicit wiring.

## INV-K8-09 — Constructor Ownership

Direct Engine/Runtime construction must be limited to current explicitly classified:

```text
INTERNAL
TEST / SCENARIO
OPERATOR / INFRASTRUCTURE
COMPOSITION
```

No external Product caller may remain in the constructor-owner inventory.

The K0 architecture inventory currently knows the historical construction sites.

Update it so K8 debt disappears instead of deleting the inventory logic.

## INV-K8-10 — Compatibility Surface Closure

Review the standalone compatibility executable:

```text
onlyalpha-artifact-api
```

and its standalone composition path.

Current Product API already serves artifact queries.

Default K8 decision:

```text
if no concrete currently-supported active consumer exists
→ remove standalone executable
→ remove standalone compatibility app composition
→ retain artifact query routes in main onlyalpha-api
```

Do not retain it based only on hypothetical future users.

If concrete active repository/product evidence proves the surface is still intentionally supported, document the evidence and classify it explicitly. Do not silently keep debt.

## INV-K8-11 — Semantic Identity Preservation

K8 must not alter:

```text
Dataset identity
Calculation identity
Candidate identity
Strategy fingerprint
Strategy Revision identity
Freeze relation identity
Promotion identity
Execution Evidence identity
Research semantic identity
```

Expected semantic identity delta:

```text
0
```

## INV-K8-12 — Determinism Preservation

K8 must introduce no new semantic dependency on:

```text
clock time
random UUID
unordered iteration
filesystem order
environment order
hostname
request timing
network timing
transport metadata
```

Removal of legacy surfaces must not change deterministic business semantics.

## INV-K8-13 — Persistence Preservation

K8 should introduce:

```text
new DB tables          = 0
new durable authority  = 0
new receipt authority  = 0
new business schema    = 0
```

If a persistence change appears necessary, re-check task scope before proceeding.

## INV-K8-14 — P9.0 Preservation

Do not modify the semantics of:

```text
Research Evidence
Candidate
Freeze
Strategy Revision
Strategy publication
Promotion
```

K8 seals external authority; it does not redesign strategy semantics.

## INV-K8-15 — Fail Closed Legacy Removal

Removed legacy paths must fail clearly.

Do not add:

```text
deprecated aliases
lazy compatibility constructor proxies
magic fallback imports
auto-local execution
silent CLI forwarding to old Engine
```

unless repository truth explicitly requires a compatibility period—which would need a new accepted design decision, not an ad-hoc K8 implementation.

## INV-K8-16 — Zero Migration Debt

At K8 closure:

```text
KNOWN_MIGRATION_DEBT = 0
LEGACY_K8_TARGET     = 0
```

No currently supported Product surface may still be classified “migrate later”.

K8 is the migration closure.

---

# 7. Required Implementation Scope

Use the smallest coherent implementation.

Likely affected areas include:

```text
src/onlyalpha/__init__.py
src/onlyalpha/cli.py

possibly:
src/onlyalpha/engine/__init__.py
src/onlyalpha/runtime/__init__.py
src/onlyalpha/cluster/__init__.py

pyproject.toml
packages/api/onlyalpha-api/pyproject.toml

packages/api/onlyalpha-api/src/onlyalpha_api/artifact_main.py
packages/api/onlyalpha-api/src/onlyalpha_api/app.py
only if standalone artifact compatibility closure requires it

tests/architecture/test_p9_k0_product_surfaces.py
tests/architecture/test_p9_k6_external_client_boundary.py
tests/architecture/test_p9_k8_kernel_seal.py

current docs / reports / project-state projection
```

Not every listed file must change.

Do not churn files that are already correct.

---

# 8. Root Python Export Strategy

Primary requirement:

```text
src/onlyalpha/__init__.py
```

must stop binding/exporting the exact K8 migration-debt constructor surface.

Do not replace imports with compatibility shims.

Retain stable non-mutation public utilities defined by the current K0 public contract.

For aggregation modules such as:

```text
onlyalpha.engine
onlyalpha.runtime
onlyalpha.cluster
```

apply a conservative rule:

> remove constructor capabilities from broad “public API” aggregators where the current K0/K6 design clearly classifies them as external migration debt and the change can be made with low churn.

Do **not** perform a mass repository rename/move into `_internal` merely to create the illusion of privacy.

Concrete implementation modules may remain accessible to repository internals.

Python cannot provide true language-level privacy; K8 seals **supported public Product surfaces and repository ownership**, not every possible import string a malicious caller could type.

---

# 9. Root CLI Strategy

Inspect `src/onlyalpha/cli.py`.

Remove:

```text
run
snapshot
```

as Product-facing mutation commands.

Do not create replacement endpoints just to preserve the old CLI shape.

Do not implement:

```text
onlyalpha run
→ local Engine
```

or:

```text
onlyalpha run
→ hidden fallback
```

Retain legitimate non-Product surfaces if currently classified and justified, e.g.:

```text
scenario ...
operations ...
```

but preserve their explicit classification:

```text
TEST / SCENARIO
OPERATOR / INFRASTRUCTURE
```

Do not accidentally advertise them as Product Control Plane.

---

# 10. Official Product Client

Preserve the K6 contract:

```text
packages/client/onlyalpha-client
```

must remain transport-only.

Expected properties:

```text
depends on http client transport
does not depend on onlyalpha core
does not construct Engine/Runtime
does not import Kernel/Application/Persistence
does not implement local fallback
uses canonical generated Product contract
```

The CLI exposed by `onlyalpha-client` is the Product CLI.

Do not move business logic into the client.

---

# 11. Web Boundary

Preserve:

```text
apps/onlyalpha-web
→ canonical Product contract/client
→ HTTP
```

It must not import or recreate Kernel mutation semantics.

K8 should strengthen the existing K6 architecture test only as needed.

Do not redesign Web UI during K8.

---

# 12. API Route Boundary

Inspect mutation routes.

Correct structure:

```text
HTTP Route
→ ProductBoundary.commands.dispatch(...)
```

and:

```text
HTTP Route
→ ProductBoundary.queries.dispatch(...)
```

Preserve this.

Add permanent negative architecture assertions so future code cannot change a route into:

```text
route
→ Postgres writer
```

or:

```text
route
→ OnlyEngine
```

or:

```text
route
→ Strategy publisher
```

or:

```text
route
→ direct Research command implementation
```

Do not rewrite already-correct business flow.

---

# 13. Standalone Artifact Compatibility Decision

Before removal, search the repository for:

```text
onlyalpha-artifact-api
artifact_main
standalone artifact query app factory
deployment/docs consuming standalone artifact API
```

Use current executable/product evidence.

If no active supported consumer exists:

remove the duplicate compatibility surface.

Expected final architecture:

```text
onlyalpha-api
├── Product mutation routes
└── artifact query routes
```

not:

```text
onlyalpha-api
+
onlyalpha-artifact-api
```

unless current accepted repository evidence explicitly requires both.

Do not delete artifact query functionality itself.

---

# 14. Dedicated K8 Negative Architecture Gate

Create or finalize:

```text
tests/architecture/test_p9_k8_kernel_seal.py
```

This test should prove architectural absence/closure.

At minimum assert:

```text
root mutation constructor exports == 0
legacy root Product CLI commands == 0
external Product client Core imports == 0
Web Core imports == 0
external local fallback capability == 0
API mutation route raw capability ownership == 0
Product-space direct Engine/Runtime constructors == 0
known K0 migration-debt constructor owners == 0
standalone compatibility Product HTTP debt == 0
unknown/unclassified external Product mutation surfaces == 0
```

Do not duplicate business behavior tests already covered elsewhere.

This is an architecture seal test, not a second functional suite.

---

# 15. Update K0/K6 Contracts Correctly

The existing K0/K6 tests/contracts are useful historical migration authorities.

Do not delete them simply because migration is complete.

Instead:

```text
historical migration debt
→ transitions to zero
```

K0 inventory should prove:

```text
all previously known Product mutation debt is now closed
```

K6 client contract should prove:

```text
official external clients remain Product API clients
legacy K8 targets are gone
```

If a historical machine-readable K6 contract remains useful as historical evidence, preserve it.

Do not silently rewrite history.

If a new final K8 seal contract is added, it must have one clear ownership purpose and must not duplicate `project-state.toml` or K6 authorities unnecessarily.

Prefer tests as the final mechanical architecture gate unless a separate contract file is genuinely needed.

---

# 16. No Scope Expansion

P9.K.8 explicitly does NOT implement:

```text
new Product endpoint
new Product command
new Product query
Binance integration
QMT implementation
CTP implementation
Broker order submission
Account/Position RPC
Portfolio redesign
Risk redesign
LIVE mode
new Strategy model
new Research model
new database table
new receipt system
new Gateway protocol semantics
new Protobuf RPC
generic DI container
new message bus
microservice split
directory-wide private-package rewrite
Engine rewrite
Runtime rewrite
Cluster rewrite
```

If a change belongs to one of these categories, stop and reassess.

---

# 17. No Fake Privacy Refactor

Do not mass-move:

```text
src/onlyalpha/engine
src/onlyalpha/runtime
src/onlyalpha/cluster
```

under a new `_internal` hierarchy solely to make imports look private.

That creates:

```text
large diff
large import churn
high regression risk
little real authority gain
```

K8 must seal:

```text
supported Product surfaces
```

through:

```text
public exports
CLI
client dependencies
route capabilities
architecture ownership tests
```

That is sufficient and mechanically meaningful.

---

# 18. No Compatibility Shim That Preserves Mutation

Forbidden examples:

```python
class DeprecatedOnlyEngine:
    def __new__(...):
        warnings.warn(...)
        return OnlyEngine(...)
```

```python
try:
    call_product_api()
except ConnectionError:
    run_local_engine()
```

```text
onlyalpha run
→ hidden local execution
```

These preserve a second Product authority and therefore fail K8.

---

# 19. Implementation Order

Follow this sequence.

## Phase A — Freeze Current Surface

Record:

```text
TASK_BASE_SHA
current project state
root exports
root CLI commands
K0 constructor owner inventory
K6 external-client classifications
standalone artifact API references
```

Build the invariant matrix before edits.

## Phase B — Seal Root Python Surface

Remove exact root migration-debt exports.

Run focused import/public-surface tests immediately.

Do not change semantic business code.

## Phase C — Seal Legacy Root CLI

Remove `run` and `snapshot`.

Retain only correctly classified operator/test functionality.

Ensure help/argument parsing no longer advertises removed Product mutation commands.

## Phase D — Close Compatibility HTTP Debt

Use evidence-based decision on `onlyalpha-artifact-api`.

If unneeded, remove:

```text
console script
standalone composition entry
unneeded factory/path
```

while preserving artifact queries in main Product API.

## Phase E — Strengthen Route/Client Boundaries

Add only the negative gates necessary to prove:

```text
Product clients cannot import Core
routes cannot own raw mutation capabilities
composition roots may wire dependencies
```

Do not redesign correct routes.

## Phase F — Zero Migration Debt

Update K0/K6 migration architecture expectations.

The final machine state must show:

```text
KNOWN_MIGRATION_DEBT = 0
LEGACY_K8_TARGET = 0
```

## Phase G — Dedicated K8 Seal Gate

Implement the final negative architecture test.

Prefer static/AST/import metadata assertions over brittle source-string heuristics when practical.

Tests should fail if future code reintroduces a Product bypass.

## Phase H — Verification

Run impact-aware Task Gate.

Only after correctness:

```text
version → 0.9.8
project state → K8 verified / P9.K closed
```

Do not update state early.

---

# 20. Verification Requirements

Use current canonical repository scripts/lane names.

At minimum run targeted architecture tests equivalent to:

```bash
uv run pytest \
  tests/architecture/test_p9_k0_product_surfaces.py \
  tests/architecture/test_p9_k6_external_client_boundary.py \
  tests/architecture/test_p9_k8_kernel_seal.py \
  -q
```

Also run applicable current lanes for affected scope:

```text
canonical Architecture lane
onlyalpha-api package tests
onlyalpha-client tests
Research Product Command lane
OpenAPI contract generation/check
generated Python client freshness
Web static contract checks
Import Linter
affected mypy
Ruff check
Ruff format check
all-package build
version sync check
project-state check
git diff --check
```

Use repository-owned commands where available rather than ad-hoc replacements.

Do not automatically run unrelated repository-wide expensive certification unless required by current Impact Scope.

---

# 21. Mandatory Semantic Delta Proof

Before closure, prove and record:

```text
Product OpenAPI semantic delta
Strategy/P9.0 semantic source delta
Gateway Proto semantic delta
database migration delta
semantic fingerprint implementation delta
```

Expected K8 result:

```text
Product OpenAPI semantic delta        = 0
Strategy/P9.0 semantic delta          = 0
Gateway Proto semantic delta          = 0
database migration delta              = 0
semantic fingerprint implementation   = 0
```

If any non-zero delta appears, explain why it is necessary and verify it does not violate K8 scope.

Default expectation is zero.

---

# 22. Version Rule

Only after implementation and Task-Gate evidence are correct:

```bash
uv run python scripts/version_sync.py set 0.9.8
uv run python scripts/version_sync.py check
```

Use the actual repository-owned version command if the interface has changed.

Do not manually edit distributed version strings.

Do not bump version before correctness.

---

# 23. Project-State Closure Rule

`project-state.toml` remains the sole current project-control authoring authority if that is still repository policy.

After successful K8 closure, use official project-state tooling.

Expected semantic state:

```text
last_verified_increment = P9.K.8
P9.K.8 = TASK COMPLETE / VERIFIED

P9.K = CLOSED

next authorized increment = P9.1
P9.1 = IMPLEMENTATION READY
```

Only now may P9.1+ be unblocked.

Do not manually make README/roadmap/reports competing state authorities.

Reports are evidence/history.

Do not mark P9.K closed before all K8 invariants pass.

---

# 24. K8 Acceptance Matrix

K8 is complete only when all applicable items are true:

```text
[1] Root `onlyalpha` exports no K8 migration-debt mutation constructors.

[2] `onlyalpha run` no longer exists.

[3] `onlyalpha snapshot` no longer exists.

[4] `onlyalpha-client` remains the supported Product Python/CLI client.

[5] Product client has no Core/Kernel/Application/Persistence dependency.

[6] Web has no Core/Kernel mutation dependency.

[7] No Product client has local Engine/Runtime fallback.

[8] Product API mutation routes depend only on narrow Product Command/Query boundary.

[9] Product API routes do not directly own raw writers, Engine/Runtime, semantic publishers or Gateway clients.

[10] Explicit composition root remains allowed to wire real stores/services/Kernel.

[11] Direct Engine/Runtime construction is restricted to internal/test/operator/composition owners.

[12] K0 known Product migration debt = 0.

[13] K6 LEGACY_K8_TARGET classifications = 0.

[14] Standalone artifact compatibility debt is closed unless concrete active support evidence requires it.

[15] No second Product HTTP mutation surface exists.

[16] No second Product CLI mutation surface exists.

[17] No second Product Python mutation surface exists.

[18] Product OpenAPI semantic delta = 0.

[19] Strategy/P9.0 semantic identity delta = 0.

[20] Research identity/authority delta = 0.

[21] Gateway Proto semantic delta = 0.

[22] Database schema/migration delta = 0.

[23] Semantic fingerprint implementation delta = 0.

[24] No new Product endpoint/command/query was created.

[25] No QMT/CTP/Binance/Broker/LIVE implementation was started.

[26] Permanent K8 negative architecture gate exists and passes.

[27] Canonical Architecture lane passes.

[28] Client/API/OpenAPI contract verification passes.

[29] Import Linter / typing / Ruff / build pass for applicable scope.

[30] Version graph is 0.9.8 and consistent.

[31] Project-state consistency passes.

[32] BLOCKER = 0.

[33] MAJOR = 0.
```

When all are true:

```text
P9.K.8 = TASK COMPLETE / VERIFIED
P9.K   = CLOSED
P9.1   = MAY START / IMPLEMENTATION READY
```

STOP.

---

# 25. Convergent Audit Requirements

Follow the repository's Convergent Audit Policy.

Before final verdict freeze:

```text
AUDIT_BASE_SHA = TASK_BASE_SHA
AUDIT_HEAD_SHA = final immutable implementation SHA or explicit worktree state
Audit Scope    = P9.K.8 Task Gate
Target         = Seal Kernel
Applicable frozen design
Previous findings
```

Finding severities:

```text
BLOCKER
MAJOR
MINOR
SUGGESTION
```

GO iff:

```text
BLOCKER = 0
MAJOR = 0
applicable core invariants PASS
no frozen design/ADR violation
current Task-Gate evidence sufficient
```

MINOR/SUGGESTION do not block.

Do not keep searching for optional improvements after GO conditions are satisfied.

---

# 26. What Counts as a BLOCKER / MAJOR

Examples of legitimate blocking findings:

```text
root Product mutation constructor still supported
legacy Product CLI still directly runs Engine
Product client imports Core mutation capability
Product client silently falls back to local Engine
API route directly owns raw mutation writer
second Product mutation HTTP surface remains
migration debt still classified as active after claimed closure
K8 change modifies Strategy identity unexpectedly
K8 change modifies Gateway Proto semantics unexpectedly
new persistence authority introduced
project state claims P9.K closed before K8 invariants pass
```

Do not create BLOCKER/MAJOR for:

```text
preference for another module name
wish to move all internals under `_internal`
future Broker design
future TLS/mTLS hardening
future QMT/CTP details
future P9.1 functionality
generic DI style preference
optional cleanup
comment wording
minor code aesthetics
```

---

# 27. Reverse Authority Audit

Before closing, explicitly answer:

```text
Can Web mutate without Product API?                     NO
Can Product Python client mutate without Product API?  NO
Can Product CLI mutate without Product API?            NO
Can root `onlyalpha` expose Engine mutation?            NO
Can root CLI directly construct Engine for Product use?NO
Can API route directly write business persistence?     NO
Can Gateway become a Product API?                      NO
Can client silently become local Kernel?               NO
Does any LEGACY_K8_TARGET remain?                       NO
Does any KNOWN_MIGRATION_DEBT remain?                   NO
```

Also verify:

```text
Can internal/test composition still construct what it legitimately needs? YES
Can composition root still wire stores/services/Kernel?                    YES
Can operator/test tooling remain explicitly classified?                    YES
```

K8 must remove external bypasses without breaking legitimate internal architecture.

---

# 28. Expected Diff Character

K8 should mostly be a subtraction task.

Healthy diff shape:

```text
- legacy exports
- legacy CLI branches
- duplicate compatibility executable
- migration-debt classifications

+ focused negative architecture assertions
+ closure evidence/docs
```

Suspicious diff shape:

```text
+ new framework
+ new protocol
+ new business service
+ new persistence model
+ new API endpoints
+ large Engine rewrite
```

If the second pattern appears, reassess scope.

---

# 29. Documentation and Report

Create/update a K8 implementation/evidence report.

It must distinguish:

```text
what was removed
what remains intentionally internal
what remains operator/test-only
what architecture gates now prevent
what semantic areas were unchanged
```

Do not rewrite historical K0/K6/K7 reports as if they were never true.

Historical reports remain evidence.

Current project state belongs to `project-state.toml`.

---

# 30. Final Response Format

Use a concise evidence-oriented Codex final response:

```text
P9.K.8 Seal Kernel

TASK_BASE_SHA:
FINAL_SHA / WORKTREE:

Removed Product bypasses:
- ...

Retained legitimate internal/operator/test paths:
- ...

Architecture seal:
- root mutation exports: 0
- legacy root Product CLI commands: 0
- Product client Core imports: 0
- local fallback: 0
- API route raw mutation capabilities: 0
- KNOWN_MIGRATION_DEBT: 0
- LEGACY_K8_TARGET: 0
- standalone compatibility debt: 0 / explicitly justified

Semantic deltas:
- Product OpenAPI: 0 / explain
- Strategy/P9.0: 0 / explain
- Research authority: 0 / explain
- Gateway Proto: 0 / explain
- DB schema: 0 / explain
- semantic fingerprints: 0 / explain

Verification:
- K0/K6/K8 architecture tests: PASS/FAIL
- canonical Architecture lane: PASS/FAIL
- API tests: PASS/FAIL
- client tests: PASS/FAIL
- OpenAPI/client freshness: PASS/FAIL
- Import Linter: PASS/FAIL
- mypy: PASS/FAIL
- Ruff: PASS/FAIL
- build: PASS/FAIL
- version sync: PASS/FAIL
- project-state: PASS/FAIL
- git diff --check: PASS/FAIL

Audit:
BLOCKER = N
MAJOR   = N
MINOR   = N
SUGGESTION = N

Verdict:
GO / NO-GO

If GO:
P9.K.8 = TASK COMPLETE / VERIFIED
P9.K   = CLOSED
P9.1   = MAY START / IMPLEMENTATION READY
```

---

# 31. Mandatory Stop Condition

When:

```text
BLOCKER = 0
MAJOR = 0
all applicable K8 core invariants = PASS
Task-Gate evidence = sufficient
```

STOP.

Do not continue with:

```text
P9.1 implementation
QMT
CTP
Binance
Broker
Risk
Portfolio
LIVE
generic refactoring
```

inside this task.

K8 ends when the Kernel's Product authority is sealed.

---

# 32. One-Sentence Engineering Definition

> P9.K.8 removes every remaining supported external Product mutation bypass, preserves legitimate internal/operator/test composition, and installs permanent negative architecture gates so that the Product Control Plane is the one and only supported external mutation authority without changing business semantics, identities, persistence or remote protocol behavior.
