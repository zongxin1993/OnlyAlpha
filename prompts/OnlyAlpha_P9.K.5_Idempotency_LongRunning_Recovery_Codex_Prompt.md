# OnlyAlpha — P9.K.5 Idempotency, Long-running Operations & Recovery Closure

## Codex Engineering Task Prompt

---

# 0. Task Identity

Repository:

```text
https://github.com/zongxin1993/OnlyAlpha
```

Target milestone:

```text
P9.K.5 — Idempotency, Long-running Operations & Recovery Closure
```

Expected design baseline when this task was prepared:

```text
master
7ee4a6f3661802f8121d084f2836df02128dc372
```

The repository is authoritative. This prompt is an implementation specification derived from the frozen P9.K architecture, but it must never override newer accepted ADRs, frozen contracts, or current code.

This task must be implemented from first principles:

```text
one fact
→ one authority

same intent
→ deterministic identity

retry / restart
→ one converged authoritative outcome

conflict / corruption / ambiguity
→ fail closed

minimum sufficient mechanism
→ no speculative platform expansion
```

Primary governing documents include at minimum:

```text
AGENTS.md
docs/engineering/convergent-audit-policy.md
docs/engineering/quality-system.md

docs/roadmap.md

docs/adr/0090-research-execution-attempt-lease-fencing-and-recovery.md
docs/adr/0101-stateful-kernel-and-protocol-boundary.md
docs/adr/0103-public-api-contract-governance.md

docs/p9_k_stateful_kernel_protocol_boundary.md
```

Also inspect all current P9.K implementation reports, architecture contracts, relevant P8/P9 tests, migrations, Product Command/Query implementation, Research command/store implementation, Strategy Freeze authority/reconciliation implementation, Kernel Host/lifecycle implementation, API routes, and CI gates before making changes.

---

# 1. Hard Precondition — Freeze Actual Repository State

Before editing anything:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git log -1 --oneline
```

Record:

```text
TASK_BASE_SHA=<actual HEAD>
TASK_BRANCH=<actual branch>
```

Expected branch:

```text
master
```

Expected historical baseline at prompt creation:

```text
7ee4a6f3661802f8121d084f2836df02128dc372
```

Do not assume that SHA is still current.

If `master` has advanced:

1. use current `master`;
2. re-read all applicable ADRs/design documents;
3. verify that P9.K.5 is still the current authorized increment;
4. verify that the design assumptions in this prompt still match current architecture;
5. explicitly report deviations before implementation;
6. never mix evidence from different SHAs.

---

# 2. Mandatory Gate Precondition

P9.K.5 must not begin on top of an unresolved current blocking Gate.

The previous known issue was:

```text
F-QA-001 — Research Factor mandatory coverage ownership
```

A minimal implementation fix was committed before this prompt was prepared.

Before starting K5 implementation, inspect the **current exact-SHA CI** and repository audit state.

Proceed only if:

```text
BLOCKER == 0
MAJOR == 0

mandatory exact-SHA quality evidence is green

applicable core invariants PASS
```

If a previously known Gate is still pending, wait only in the sense of **do not modify K5 code in that repository state**; report the exact current evidence and stop the implementation task.

If a new unrelated BLOCKER/MAJOR exists:

```text
STOP K5
```

Do not hide or repair an unrelated blocking problem inside K5.

K5 must remain an independently auditable increment.

---

# 3. Frozen K5 Goal

The governing P9.K design defines K5 as:

> Make network retry and Kernel restart normal deterministic scenarios.

Required exit:

```text
restart/retry
→ converges to one outcome
→ does not produce duplicate semantic/business authority
```

K5 is complete only when external mutation retry, process loss, startup recovery and projection reconciliation are ordinary deterministic paths rather than ambiguous exceptional cases.

---

# 4. First-Principles Problem Definition

K5 exists to close three uncertainty windows.

## Window A — response loss

```text
client
→ mutation accepted
→ durable effect committed
→ HTTP response lost
→ client cannot know whether it succeeded
```

Correct solution:

```text
retry same external command identity
→ deterministic lookup
→ replay same authoritative resource/outcome
```

Not:

```text
guess
duplicate work
create a second business resource
```

---

## Window B — semantic fact committed before projection

```text
immutable semantic authority committed
→ process crashes
→ PostgreSQL/business projection missing
```

Correct solution:

```text
verified semantic authority
→ deterministic reconciliation
→ rebuild missing projection
```

Never:

```text
projection
→ rewrite semantic truth
```

---

## Window C — Kernel/Worker restart

```text
process dies
→ new process starts
→ durable facts remain
```

Correct solution:

```text
re-read the true authority
→ recover/reuse/reconcile/fail closed
```

Never recover from an opaque serialized whole-Kernel snapshot.

---

# 5. Non-Goals

Do **not** turn K5 into any of the following:

```text
generic workflow engine
generic ProductOperation state machine
Celery
Temporal
Kafka
NATS
Redis queue
Redis distributed lock
etcd
Consul
Raft
multi-master Kernel
automatic HA platform
distributed saga framework
event-sourced rewrite
mass directory restructuring
new generic async event bus
```

Do not implement K6 External Client Migration.

Do not implement K7 Remote Protocol / gRPC.

Do not implement K8 Kernel sealing.

Do not expose new Strategy/Promotion/Backtest/SIM public APIs merely to demonstrate K5.

Do not rewrite existing P8 Research worker recovery that is already correct.

---

# 6. Governing Invariants

Build an Invariant Matrix **before implementation**.

At minimum include the following.

---

## INV-K5-001 — One External Command Identity Authority

For product mutation retry identity:

```text
Product Command ID
→ exactly one active durable authority
```

After K5, do not allow both:

```text
research_run_submission
+
product_command_receipt
```

to remain active production retry authorities for CreateResearchRun.

Historical migration files remain immutable, but production readers/writers must converge on one active authority.

---

## INV-K5-002 — Product Command ID is global

A canonical Product Command ID identifies one external command globally.

Rules:

```text
same command_id
+ same command_kind
+ same command_fingerprint
→ replay same authoritative outcome

same command_id
+ different command_kind
→ conflict

same command_id
+ same command_kind
+ different command_fingerprint
→ conflict
```

Do not use `(command_kind, command_id)` as a composite identity that permits reusing one command ID for multiple command kinds.

---

## INV-K5-003 — Command identity is operational only

Never include:

```text
Product Command ID
Idempotency-Key
request_id
actor
JWT
IP
HTTP header
HTTP method/route
API version
contract fingerprint
Git SHA
```

inside any semantic fingerprint for:

```text
Dataset
Calculation
Calculation Result
Execution Evidence
Candidate
Research Result
Artifact
Strategy Revision
Strategy fingerprint
Freeze semantic relation
Trading semantics
```

---

## INV-K5-004 — Preserve existing CreateResearchRun command fingerprint semantics

Current P8 CreateResearchRun semantics already define a canonical fingerprint from the strict Research Specification.

Do **not** silently change historical bytes from conceptually:

```python
SHA256(canonical({
    "specification": specification
}))
```

to a new shape that includes the command kind or HTTP metadata.

Product Command Receipt stores:

```text
command_kind
+
command_fingerprint
```

as separate fields.

This is required for exact migration/backfill compatibility with existing durable `research_run_submission` records.

---

## INV-K5-005 — Receipt is a binding, not a workflow state machine

`OnlyProductCommandReceipt` records:

```text
command identity
→ authoritative outcome/resource reference
```

It must not become another lifecycle authority with states such as:

```text
PENDING
RUNNING
SUCCESS
FAILED
RETRYING
```

Business lifecycle remains owned by the business resource:

```text
ResearchRun
future BacktestSession
future SimSession
future Deployment
...
```

---

## INV-K5-006 — ResearchRun remains the long-running operation resource

Do not create a generic ProductOperation resource for Research.

Correct:

```text
CreateResearchRun
→ ProductCommandReceipt
→ ResearchRun
```

Forbidden:

```text
CreateResearchRun
→ ProductOperation
→ ResearchRun
```

unless a newer accepted ADR explicitly authorizes such a second resource.

---

## INV-K5-007 — Command receipt and business effect commit atomically where same DB authority permits

Do not introduce:

```text
receipt=PENDING
→ business mutation
→ receipt=SUCCESS
```

for Create/Cancel Research Run.

Prefer a transaction that structurally has only:

```text
not committed
```

or:

```text
business authority + resolved command receipt committed
```

No intermediate durable command workflow state should be needed.

---

## INV-K5-008 — Receipt references current authoritative resource, not cached DTO

Receipt outcome stores only the authoritative resource reference, for example:

```text
outcome_kind = RESEARCH_RUN
outcome_id   = <run_id>
```

A retry reloads the current authoritative resource.

Do not persist the full old HTTP response or old mutable Run state as command truth.

---

## INV-K5-009 — Dangling/corrupt receipt fails closed

If:

```text
receipt K1
→ RESEARCH_RUN / R1
```

but `R1` is missing, corrupt, incompatible, or not the resource the receipt claims:

```text
fail closed
```

Never create R2 because R1 could not be loaded.

A durable Receipt is authority, not a hint.

---

## INV-K5-010 — Research physical execution is not exactly-once

Preserve ADR 0090:

```text
at most one authoritative ACTIVE Attempt
+
lease/fencing
+
deterministic semantic re-entry
+
eventual terminal convergence
```

Do not attempt to guarantee exactly-once physical calculation across crash/partition.

---

## INV-K5-011 — Research worker recovery remains Worker/Execution responsibility

Do not move Research Attempt/Lease execution recovery into Kernel Host.

Keep:

```text
Kernel Host
→ product control-plane lifecycle/recovery

Research Worker
→ Research execution claim/lease/fencing/re-entry
```

---

## INV-K5-012 — Semantic truth dominates projection

For Strategy Freeze:

```text
verified immutable Strategy Revision + Freeze Relation
→ PostgreSQL projection
```

Recovery may:

```text
reconstruct missing projection
reuse equal projection
```

but conflicting projection must:

```text
fail closed
```

Never repair semantic truth from PostgreSQL projection.

---

## INV-K5-013 — Recovery traversal is deterministic

Any startup inventory must have canonical ordering independent of:

```text
filesystem enumeration order
PYTHONHASHSEED
dict/set incidental order
process timing
```

Sort and verified-load authoritative identities explicitly.

---

## INV-K5-014 — Mutation is impossible before READY

During:

```text
CREATED
BOOTING
VERIFYING
RECOVERING
DRAINING
STOPPED
FAILED
```

mutation Commands must fail closed.

A test must prove both:

```text
request rejected
AND
no durable side effect
```

---

## INV-K5-015 — One unfenced mutation-capable Product Kernel

V1 deployment must reject two concurrently active mutation-capable Kernel authorities.

Do not solve with only:

```text
uvicorn --workers 1
```

because two separate processes may still be started.

Use the minimum durable coordination mechanism appropriate to the current architecture.

---

## INV-K5-016 — Kernel remains infrastructure-neutral

Kernel packages must not import:

```text
psycopg
FastAPI
Starlette
API Pydantic DTOs
```

Infrastructure implementations belong in adapter/persistence packages.

---

# 7. Phase K5.1 — Product Command Identity Contract

## Goal

Freeze the minimal Product Command retry identity model before persistence changes.

Recommended conceptual values:

```text
OnlyProductCommandId
OnlyProductCommandKind
OnlyProductCommandOutcomeRef
OnlyProductCommandReceipt
```

The exact physical module may be:

```text
src/onlyalpha/application/product_command_receipt.py
```

or another location that better fits current repository ownership.

Do not move unrelated code merely to match this suggestion.

---

## Product Command ID

Requirements:

```text
canonical UUID4
immutable value object
strict canonical string representation
```

The existing `OnlyResearchSubmissionKey` semantics should be carefully migrated/reused rather than creating two long-lived command-ID types for the same concept.

Avoid duplicate identity models.

---

## Product Command Kind

Initial K5 scope requires at least:

```text
CREATE_RESEARCH_RUN
CANCEL_RESEARCH_RUN
```

Do not add speculative kinds for commands not yet exposed through the current Product Control Plane.

---

## Product Command Outcome Reference

Concept:

```text
outcome_kind
outcome_id
```

Initial outcome kind:

```text
RESEARCH_RUN
```

Do not make the receipt depend on API DTOs.

---

## Product Command Receipt

Conceptually:

```text
command_id
command_kind
command_fingerprint
outcome_ref
accepted_at
schema_version
```

`accepted_at` is audit/operational metadata only.

It must never influence semantic identity.

---

## CreateResearchRun fingerprint

Preserve existing exact semantics.

---

## CancelResearchRun fingerprint

Define canonical intent from the true command target only, conceptually:

```python
SHA256(canonical({
    "run_id": run_id
}))
```

Do not include:

```text
command_id
actor
timestamp
HTTP route
API version
```

---

# 8. Phase K5.2 — PostgreSQL Product Command Receipt Authority

## Goal

Create the one durable external Product Command ID authority.

Expected next migration if current migration numbering has not advanced:

```text
database/postgres/migrations/0012_product_command_receipt.sql
```

If migration numbering has advanced, use the next correct immutable migration number.

Never edit historical published migrations.

---

## Recommended schema concept

```sql
CREATE TABLE product_command_receipt (
    command_id UUID PRIMARY KEY,
    command_kind TEXT NOT NULL,
    command_fingerprint TEXT NOT NULL,
    outcome_kind TEXT NOT NULL,
    outcome_id TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL,
    schema_version SMALLINT NOT NULL
);
```

Add the minimum sufficient constraints proving:

```text
command_fingerprint
→ exactly lowercase SHA256

command_kind
→ supported durable value

outcome_kind
→ supported durable value

outcome_id
→ non-empty canonical form required by the outcome type

schema_version
→ current exact supported value
```

Do not over-normalize into multiple tables unless current repository evidence proves it is required.

---

# 9. Existing P8 Submission Migration

Current P8 durable authority includes:

```text
research_run_submission
submission_key
command_fingerprint
run_id
```

K5 must migrate that authority into `product_command_receipt`.

Backfill conceptually:

```text
command_id
= research_run_submission.submission_key

command_kind
= CREATE_RESEARCH_RUN

command_fingerprint
= existing exact command_fingerprint

outcome_kind
= RESEARCH_RUN

outcome_id
= run_id

accepted_at
= authoritative ResearchRun queued_at

schema_version
= current receipt schema
```

The migration must be deterministic.

Verify referential integrity during migration.

If a legacy row cannot be translated exactly:

```text
migration/startup must fail closed
```

Do not invent or normalize away corrupt authority.

---

## Legacy table policy

Historical migration file remains.

Whether the physical table remains after K5 is an implementation decision, but after closure:

```text
production Product Command retry authority
= product_command_receipt only
```

Add architecture/code-search tests if appropriate so active code cannot silently return to `research_run_submission`.

Do not leave two active command identity authorities.

---

# 10. Store/Transaction Design

Transaction correctness has priority over superficial module symmetry.

If placing Receipt Store in a separate adapter would force:

```text
connection A → ResearchRun
connection B → Receipt
```

for one atomic operation, do not do that.

The business-shaped persistence API may remain colocated with the Research PostgreSQL transaction adapter if that is the cleanest way to guarantee atomicity.

A clean package layout is not worth a split transaction.

---

# 11. CreateResearchRun — Required K5 Semantics

Current flow should evolve to:

```text
Idempotency-Key K1
+
strict Research Specification S1
        ↓
canonical Create fingerprint F1
        ↓
lookup ProductCommandReceipt(K1)
```

### If receipt exists and matches

```text
kind        = CREATE_RESEARCH_RUN
fingerprint = F1
outcome     = RESEARCH_RUN/R1
```

then:

```text
verified/load R1
→ return REUSED / current authoritative Run
```

### If receipt exists but does not match

Any difference in:

```text
command_kind
command_fingerprint
```

must produce a deterministic conflict.

No new Run.

---

## New admission

If no receipt exists:

```text
prepare deterministic/valid ResearchRun admission
        ↓
BEGIN
        ↓
INSERT research_run
INSERT product_command_receipt
        ↓
COMMIT
```

The transaction must establish one linearization point.

---

# 12. Concurrent Create Retry

Explicitly prove:

```text
Request A:
K1 + F1
→ prepares R1

Request B:
K1 + F1
→ prepares R2
```

Both may generate different operational UUIDs before transaction conflict.

Required database result:

```text
one transaction commits
one transaction loses command_id uniqueness
loser transaction fully rolls back
loser reloads winning Receipt
returns winning R1
```

Final authority:

```text
1 ProductCommandReceipt
1 ResearchRun
same authoritative outcome for both callers
```

Do not allow orphan R2.

---

# 13. Response-Loss Create Semantics

Test:

```text
request accepted
→ DB transaction commits
→ HTTP response intentionally lost
→ same client retries same key + same Specification
```

Required:

```text
same ResearchRun ID
same Location resource
one durable Receipt
one durable Run
no duplicate semantic/business authority
```

Use test-only failure injection at the HTTP/ASGI transport boundary.

Do not add production environment flags such as:

```text
ONLYALPHA_CRASH_AFTER_COMMIT
```

merely to create tests.

---

# 14. CancelResearchRun — Preserve v2 Compatibility

Current v2 cancellation request is valid without `Idempotency-Key`.

ADR 0103 requires old valid v2 clients to remain valid against the new v2 server.

Therefore do **not** make the header mandatory.

Required API evolution:

```text
POST /api/v2/research/runs/{run_id}/cancellation

Idempotency-Key: optional
```

Semantics:

```text
no key
→ preserve existing natural Run-state idempotency

key supplied
→ use strong Product Command Receipt semantics
```

This is a backward-compatible extension only if the current OpenAPI governance confirms it mechanically.

---

# 15. Keyed CancelResearchRun Semantics

Fingerprint:

```text
Fcancel(R1)
```

Lookup `command_id`.

### Existing matching receipt

```text
CANCEL_RESEARCH_RUN
+
same Fcancel
+
RESEARCH_RUN/R1
```

→ load current authoritative R1 and return it.

### Same command ID reused for another Run

```text
K2 + cancel R1
then
K2 + cancel R2
```

→ deterministic conflict.

### Same command ID reused for another command kind

```text
K2 + CREATE_RESEARCH_RUN
then
K2 + CANCEL_RESEARCH_RUN
```

→ deterministic conflict.

---

# 16. Keyed Cancellation Transaction

Current natural cancellation semantics must remain:

```text
QUEUED
→ CANCELLED

RUNNING
→ CANCEL_REQUESTED

CANCEL_REQUESTED
→ current Run

CANCELLED
→ current Run

COMPLETED
FAILED
→ conflict
```

For a keyed accepted cancellation:

```text
Run state validation / optional CAS transition
+
ProductCommandReceipt insert
```

must be in one PostgreSQL transaction.

Do not implement:

```text
UPDATE run
COMMIT
INSERT receipt
COMMIT
```

because that creates a new uncertainty window.

For an already `CANCEL_REQUESTED` or `CANCELLED` Run receiving its first new keyed command:

```text
re-prove exact authoritative Run state
+
insert Receipt
```

atomically.

For terminal incompatible states (`COMPLETED`, `FAILED`) where cancellation is rejected:

```text
no successful Receipt
```

unless current frozen command-error semantics explicitly require durable rejection receipts. Do not invent such a feature in K5 without evidence.

---

# 17. Receipt Replay Returns Current Resource State

Example:

```text
first keyed cancel
→ R1 = CANCEL_REQUESTED

Worker/recovery later
→ R1 = CANCELLED

same keyed cancel retry
→ same receipt
→ load R1
→ return CANCELLED
```

This is correct.

Do not persist and replay the stale first DTO.

The invariant is:

```text
same command
→ same authoritative resource/outcome identity
```

not:

```text
same mutable response bytes forever
```

unless an existing public contract explicitly says otherwise.

---

# 18. Receipt Integrity Verification

Implement strict decode/verification equivalent in rigor to existing Research and Strategy Stores.

At minimum fail closed for:

```text
invalid UUID
invalid lowercase SHA256
unsupported schema version
unknown command kind
unknown outcome kind
empty/malformed outcome ID
Receipt → missing ResearchRun
Receipt → wrong resource type
legacy backfill inconsistency
```

Do not silently repair malformed Receipt rows during application startup.

Production startup must not run migrations or invent semantic repairs.

---

# 19. Phase K5.4 — Strategy Projection Recovery

Existing Strategy Freeze ordering creates a legitimate crash window:

```text
immutable Strategy Revision / Freeze Relation committed
→ PostgreSQL strategy/freeze projection not yet committed
→ crash
```

Existing:

```text
OnlyStrategyFreezeProjectionReconciler
```

already owns the correct per-Strategy reconciliation semantics.

Reuse it.

Do not duplicate reconciliation rules in Kernel Host.

---

# 20. Deterministic Semantic Inventory

Kernel startup needs to discover current frozen Strategy semantic authorities without relying on a mutable projection.

Add the narrowest read-only capability needed to enumerate verified frozen Strategy identities.

Possible shape:

```python
frozen_strategy_fingerprints() -> tuple[str, ...]
```

Requirements:

```text
read immutable semantic namespace
canonical sorted traversal
strict validation
verified Strategy Revision
verified Freeze Relation
deduplicate only by proven exact identity
return sorted immutable tuple
```

Any unexpected file/directory/symlink/corrupt relation should fail closed according to existing Store integrity conventions.

Do not use unsorted filesystem enumeration as recovery order.

---

# 21. `reconcile_all()` Application Boundary

Prefer extending the current Strategy recovery application service with a narrow operation such as:

```python
reconcile_all()
```

Concept:

```text
verified frozen Strategy inventory
→ sorted fingerprints
→ existing reconcile(fingerprint)
```

Kernel Host should only see a lifecycle recovery capability.

Kernel Host must not know:

```text
Strategy SQL
Strategy semantic directory structure
Freeze business rules
projection table details
```

---

# 22. Projection Reconciliation Rules

For each verified semantic Strategy:

### Projection missing

```text
reconstruct
```

### Projection exactly equivalent

```text
reuse
```

### Projection partially missing but remaining facts are compatible

```text
deterministically converge
```

### Projection conflicts with semantic authority

```text
fail closed
Kernel must not become READY
```

Never choose PostgreSQL projection over verified immutable semantic truth.

---

# 23. Phase K5.4 — Real Kernel RECOVERING

Current Host lifecycle already contains:

```text
CREATED
BOOTING
VERIFYING
RECOVERING
READY
DRAINING
STOPPED
FAILED
```

K5 must make production `RECOVERING` meaningful.

Target current product composition conceptually:

```text
BOOTING
├─ calculation registry composition

VERIFYING
├─ PostgreSQL compatibility
├─ migration/schema compatibility
├─ semantic namespace identity
├─ required roots
├─ registry/product verification

RECOVERING
├─ Product Command authority verification where needed
├─ Strategy semantic → PostgreSQL projection reconciliation

READY
```

Do not move Worker Attempt recovery into this sequence.

---

# 24. Mutation During RECOVERING

Add deterministic test control/barrier so recovery can be held in `RECOVERING`.

While held:

```text
send CreateResearchRun
```

Required:

```text
HTTP/product mutation rejected
no ResearchRun inserted
no ProductCommandReceipt inserted
no hidden handler side effect
```

Do not merely assert the HTTP status.

The database must prove zero durable mutation.

---

# 25. Single Mutation-Capable Kernel Authority

K5 required failure matrix includes:

```text
attempt to run multiple unfenced mutation-capable Kernel instances
→ deployment/configuration gate rejects
```

Use minimum sufficient infrastructure.

A suitable V1 design is a PostgreSQL session-level advisory lock, provided current PostgreSQL compatibility and deployment model support it.

Do not introduce a distributed coordination platform.

---

# 26. Kernel Authority Guard Boundary

Kernel should know only a narrow capability, conceptually:

```python
class OnlyKernelAuthorityGuard(Protocol):
    def acquire(self) -> None: ...
    def assert_held(self) -> None: ...
    def release(self) -> None: ...
```

Exact interface may differ based on current style.

PostgreSQL implementation belongs in persistence/infrastructure.

Kernel package must not import psycopg.

---

# 27. PostgreSQL Authority Guard

If advisory lock is selected:

```text
dedicated long-lived PostgreSQL session
+
frozen OnlyAlpha Product Kernel advisory-lock key
```

Required behavior:

### Kernel A

```text
acquire
→ success
```

### Kernel B

```text
same deployment DB
→ acquire fails
→ Kernel not READY / startup FAILED
```

### Kernel A process loss

```text
PostgreSQL session closes
→ lock released by PostgreSQL
```

New process may then acquire.

Do not claim this is multi-master HA or distributed fencing.

It is only the current V1 guard against two intentionally concurrent mutation-capable Product Kernels.

---

# 28. Guard Lifecycle

Recommended lifecycle:

```text
BOOTING
↓
VERIFYING
↓
acquire mutation authority guard
↓
RECOVERING
↓
READY
```

On verification/recovery/startup failure:

```text
release guard
→ FAILED
```

Shutdown:

```text
READY
↓
DRAINING
# mutation admission closes first
↓
drainers
↓
release guard
↓
STOPPED
```

`assert_mutation_ready()` should verify both:

```text
Kernel state == READY
```

and that mutation authority is still held, if the chosen guard can be lost independently.

Do not continue admitting new mutation after authority loss.

---

# 29. Research Worker Recovery — Explicitly Reuse Existing P8 Authority

Do not rewrite:

```text
ResearchRun
Attempt
lease
heartbeat
PostgreSQL clock authority
stale-worker fencing
lease expiry
Attempt retry
semantic re-entry
Result/Artifact verified reuse
cancel reconciliation
```

Consume existing ADR 0090 and P8.6 certification as required evidence.

K5 may add integration tests proving Product Command retry composes correctly with this recovery, but it must not create a second execution ownership protocol.

---

# 30. Required Crash / Retry Certification Matrix

Create a dedicated deterministic K5 certification suite.

At minimum implement/prove:

| ID | Scenario | Required Result |
|---|---|---|
| K5-C1 | Create committed, HTTP response lost, client retries | same ResearchRun |
| K5-C2 | same Create key, different Specification | conflict; no second Run |
| K5-C3 | API process killed after durable Create commit before response | restart/retry returns same Run |
| K5-C4 | keyed Cancel committed, response lost | one cancellation effect, same Run |
| K5-C5 | same Cancel key reused for different Run | conflict |
| K5-C6 | command ID reused across Create/Cancel kinds | conflict |
| K5-C7 | Strategy semantic Freeze committed before projection, process dies | startup rebuilds projection |
| K5-C8 | compatible partial Strategy projection exists | deterministic convergence |
| K5-C9 | Strategy projection conflicts with semantic authority | Kernel FAILED / not READY |
| K5-C10 | mutation sent while Kernel RECOVERING | rejected; zero durable side effect |
| K5-C11 | second mutation-capable Product Kernel starts | authority guard rejects |
| K5-C12 | filesystem/PYTHONHASHSEED ordering changes | same recovery result/order |
| K5-C13 | Receipt points to missing/corrupt business authority | fail closed |

Add any additional scenario required by current frozen K5 document.

---

# 31. Deterministic Crash Barriers

Reuse the established P8.6 pattern:

```text
child process
→ exact named barrier
→ parent verifies barrier
→ SIGKILL
```

Do not use:

```text
sleep(N)
kill
```

as the semantic crash linearization mechanism.

Polling may be used only to observe an exact durable/test barrier, not to guess when the critical state occurred.

---

# 32. Required Crash Points

Provide test-only barriers at meaningful boundaries such as:

```text
Create:
C-A
after DB commit
before HTTP response delivery

Cancel:
C-B
after Run+Receipt transaction commit
before response delivery

Strategy:
C-C
after immutable semantic Freeze authority commit
before PostgreSQL projection

Kernel:
C-D
while deterministic recovery step is blocked
```

Do not contaminate production semantics with general-purpose fault injection switches.

Keep failure injection test-only.

---

# 33. Public API / OpenAPI Governance

Adding optional `Idempotency-Key` to cancellation changes the public API contract.

Obey ADR 0103 exactly.

Required:

```text
FastAPI routes + DTOs
→ canonical OpenAPI
→ deterministic contract fingerprint
→ lint
→ immutable-baseline compatibility comparison
→ generated Web types freshness
```

Old v2 clients must continue to send cancellation without the new header.

Do not:

```text
change operationId unnecessarily
change existing route/method
break existing response schema
change old request requirements
hand-edit generated OpenAPI
hand-edit generated TypeScript transport types
```

Regenerate only through repository-authoritative tooling.

---

# 34. Error Semantics

Use stable business-shaped errors.

At minimum distinguish:

```text
invalid Product Command ID
command identity conflict
Receipt corruption/integrity failure
Kernel mutation unavailable/not READY
Kernel authority already held elsewhere
Strategy projection conflict
storage unavailable
```

Do not leak raw:

```text
psycopg exception text
filesystem exception
traceback
```

through public product API.

Preserve existing public v2 error compatibility rules.

---

# 35. Architecture Guards

Add/extend mechanical architecture tests for at least:

```text
Core/Kernel MUST NOT import FastAPI/Starlette/API DTOs.

Kernel MUST NOT import psycopg.

API route MUST NOT write ProductCommandReceipt directly.

Product dispatcher MUST NOT become persistence authority.

Research Worker MUST NOT own ProductCommandReceipt.

ProductCommandReceipt types MUST NOT enter semantic fingerprint modules.

research_run_submission MUST NOT remain an active production retry writer/reader after migration.

Strategy projection recovery MUST derive from immutable semantic authority.

PostgreSQL projection MUST NOT obtain Strategy publication authority.

Web/client code MUST NOT import Kernel mutation capabilities.

One Product deployment MUST NOT intentionally configure multiple unfenced mutation-capable Kernel authorities.
```

Do not weaken existing architecture tests.

---

# 36. Suggested Implementation Sequence

Implement as small auditable internal steps.

## K5.1 — Identity Contract

Deliver:

```text
Product Command ID
Command Kind
Command Fingerprint rules
Outcome Reference
Receipt model
unit/property tests
architecture identity guards
```

No unnecessary DB/API expansion.

---

## K5.2 — PostgreSQL Receipt Authority

Deliver:

```text
new immutable migration
legacy submission backfill
strict Receipt store verification
atomic Create Research Run + Receipt
concurrent Create convergence
legacy active-authority retirement
```

---

## K5.3 — Research Create / Cancel Closure

Deliver:

```text
Create fully uses Product Receipt

Cancel:
optional Idempotency-Key
keyed atomic Run+Receipt transaction
legacy no-key behavior preserved

response-loss tests
OpenAPI compatibility closure
generated client freshness
```

---

## K5.4 — Kernel Recovery Composition

Deliver:

```text
deterministic verified Strategy inventory
reconcile_all()
production Kernel recoverers
single mutation Kernel guard
RECOVERING mutation fail-closed proof
```

---

## K5.5 — Deterministic Crash Certification

Deliver full K5 failure matrix using:

```text
real PostgreSQL where invariant requires it
real process boundaries where required
deterministic barriers
SIGKILL
exact durable assertions
```

---

## K5.6 — Architecture / CI / Evidence Closure

Only after implementation and certification are green:

```text
new K5 ADR if required
implementation report
roadmap update
quality-system lane updates if required
Final exact-SHA evidence
```

Do not mark K5 `DONE / VERIFIED` before evidence exists.

---

# 37. ADR Requirement

If current repository governance requires an ADR for the new Product Command authority, create the next ADR number.

Suggested subject:

```text
Product Command Idempotency and Recovery Closure
```

It should freeze only decisions actually implemented, including:

```text
global Product Command ID
Receipt as binding, not lifecycle
Product Receipt as one active retry authority
legacy research_run_submission retirement
Create fingerprint backward compatibility
optional v2 cancellation idempotency
atomic business-effect + Receipt transaction
Receipt → current resource reference
Strategy semantic-to-projection recovery
single mutation Kernel authority guard
Research Worker recovery ownership remains unchanged
```

Do not use the ADR to authorize speculative K6/K7/K8 work.

---

# 38. Migration Safety

All existing migration files are immutable.

Before applying the new migration:

```text
verify schema version
verify PostgreSQL compatibility
verify legacy data integrity
```

Migration must be safe under:

```text
empty database upgraded from all migrations
existing database with valid P8/P9 data
existing Research submissions
```

Add migration tests for both fresh install and upgrade path where current quality system requires them.

Do not run production migration implicitly from Kernel startup.

Migration remains operator/deployment responsibility.

Kernel startup only verifies compatibility.

---

# 39. Required Tests by Layer

## Unit

At minimum:

```text
ProductCommandId canonical UUID4
Receipt validation
Create fingerprint stability
Cancel fingerprint determinism
same ID/different kind conflict
same ID/different fingerprint conflict
outcome ref validation
```

---

## PostgreSQL

At minimum:

```text
Receipt create/load
legacy backfill
atomic Create + Receipt
concurrent same-key Create
same-key different-command conflict
dangling/corrupt Receipt fail closed
atomic keyed cancellation
revision race handling
fresh migration chain
upgrade migration chain
```

Use real PostgreSQL.

---

## Kernel

At minimum:

```text
recovery ordered before READY
mutation rejected while RECOVERING
recovery conflict → FAILED
guard required for READY
second authority rejected
guard release on stop/failure
```

---

## Strategy Recovery

At minimum:

```text
missing projection rebuilt
existing equal projection reused
partial compatible projection converges
conflicting projection rejected
semantic enumeration deterministic
filesystem order does not change result
corrupt semantic inventory fails closed
```

---

## HTTP / Contract

At minimum:

```text
Create response-loss retry
Create key conflict
Cancel without header still valid
Cancel with header works
Cancel response-loss retry
Cancel key/re-target conflict
global Create-vs-Cancel key conflict
stable error envelope
OpenAPI compatibility
generated TypeScript freshness
```

---

## Crash Certification

Use subprocess/SIGKILL for true crash windows.

Do not replace process-crash invariants with mocks.

---

# 40. Property / Determinism Tests

Where useful, test:

```text
same canonical command
→ same command fingerprint

non-semantic transport metadata changes
→ same semantic fingerprints

different run_id for Cancel
→ different command fingerprint

random insertion/filesystem ordering
→ same recovery order/outcome

PYTHONHASHSEED changes
→ same durable result
```

Do not add property tests merely for volume; target true determinism invariants.

---

# 41. Quality Gates

Read current `docs/engineering/quality-system.md` and use the existing Task Gate rules.

At minimum expect affected lanes to include some combination of:

```text
kernel
research-command
research-run
research-postgres
research-product-closure
strategy
recovery
architecture
openapi-contract
web-static / web generated-client checks
static
version sync
```

If K5 introduces a dedicated lane, it must have a clear ownership reason; do not create redundant test-suite aliases.

Existing P8.6 recovery certification remains mandatory evidence where applicable.

Do not lower coverage thresholds.

Do not add `pragma: no cover` to avoid testing K5 failure branches.

---

# 42. Performance / Token / CI Discipline

Follow the repository's layered quality philosophy.

Fast deterministic unit/architecture checks may run frequently.

Slow PostgreSQL/process-crash certification belongs in the appropriate mandatory CI lane rather than being duplicated across every small local edit.

Do not create redundant copies of the same 8–10 minute recovery test in multiple lanes.

One invariant should have one primary proving test and be consumed by the correct formal Gate.

---

# 43. Explicit Forbidden Implementation Patterns

Do not:

```text
store whole Kernel snapshots
pickle Kernel for recovery
add a generic ProductOperation workflow table
add PENDING/RUNNING/SUCCESS states to ProductCommandReceipt
make Redis/Kafka/Celery/Temporal part of K5
introduce multi-master mutation Kernels
implement leader-election platform
change Strategy semantic fingerprint for idempotency
change Research semantic identity for idempotency
include actor/idempotency/API metadata in semantic hashes
use HTTP request lifetime as long-running work owner
move Research Attempt/Lease recovery into Kernel Host
let FastAPI route perform SQL business logic
let Kernel dispatcher become DB transaction authority
let PostgreSQL projection overwrite semantic Strategy truth
make cancellation Idempotency-Key mandatory in v2
change historical Create command fingerprint bytes
keep two active command retry authorities
cache stale mutable HTTP response as business authority
silently reconstruct missing resource behind a dangling Receipt
use timing sleeps as crash-boundary proof
add production-only fault flags for tests
weaken architecture or coverage gates
perform unrelated refactors
```

---

# 44. Expected File Impact

Exact files must be chosen from current repository evidence.

Likely impact may include:

```text
src/onlyalpha/application/
src/onlyalpha/kernel/
src/onlyalpha/research/command/
src/onlyalpha/strategy/
src/onlyalpha/persistence/postgres/

database/postgres/migrations/

packages/api/onlyalpha-api/

tests/application/
tests/kernel/
tests/research/
tests/strategy/
tests/architecture/
tests/certification/

contracts/research-api/v2/openapi.json
generated Web transport types

docs/adr/
docs/reports/
docs/roadmap.md
scripts/test_suite.py   # only if formal lane ownership requires change
```

Do not perform mass file movement merely because this list exists.

---

# 45. Required Implementation Report

Create a K5 implementation/closure report only after the implementation is actually verified.

At minimum include:

## A. Frozen Subject

```text
TASK_BASE_SHA
TASK_IMPLEMENTATION_SHA
branch
migration number
API compatibility baseline SHA
```

---

## B. Authority Map

Explicitly document:

```text
Product Command retry authority
ResearchRun operational authority
Research Attempt/Lease authority
immutable Research semantic authorities
immutable Strategy semantic authority
Strategy PostgreSQL projection
Kernel mutation authority guard
```

For every fact, identify exactly one authority.

---

## C. Identity Matrix

Document:

```text
Product Command ID
Command Kind
Command Fingerprint
ResearchRun ID
semantic fingerprints
Strategy fingerprint
```

and prove which identities are operational vs semantic.

---

## D. Transaction Linearization Points

Document exact transactions for:

```text
CreateResearchRun
keyed CancelResearchRun
```

Explain why no durable ambiguous intermediate state exists.

---

## E. Recovery Matrix

For every K5-C* scenario:

```text
boundary
authority before crash
authority after restart
recovery rule
final outcome
test evidence
```

---

## F. Compatibility

Include:

```text
OpenAPI old-v2 → new-v2 compatibility result
contract fingerprint
generated client freshness
legacy cancellation request proof
```

---

## G. Verification Evidence

List exact commands, counts and results.

Do not write only “tests pass”.

---

# 46. Final Audit Requirement

After implementation, perform a convergent audit against the exact implementation SHA.

Build the Invariant Matrix first.

Classify findings only as:

```text
BLOCKER
MAJOR
MINOR
SUGGESTION
```

For previous findings, only:

```text
RESOLVED
PARTIALLY_RESOLVED
NOT_RESOLVED
REGRESSED
```

Do not invent reviewer-preference MAJOR findings after the frozen contract is satisfied.

---

# 47. K5 GO Criteria

K5 may be declared:

```text
DONE / VERIFIED
```

only when all applicable conditions hold:

```text
BLOCKER == 0
MAJOR == 0

all K5 core invariants PASS

same key + same command
→ same authoritative resource/outcome

same key + different command
→ conflict

response loss
→ retry does not duplicate business authority

Create receipt + Run
→ atomic

keyed Cancel receipt + accepted state effect
→ atomic

Research physical crash
→ existing fenced P8 recovery remains valid

Strategy semantic fact before projection crash
→ deterministic projection reconciliation

conflicting projection
→ fail closed

mutation during RECOVERING
→ rejected with zero durable side effect

second unfenced mutation-capable Kernel
→ rejected

Receipt corruption/dangling reference
→ fail closed

OpenAPI v2 compatibility
→ PASS

required local Task Gate
→ PASS

required exact-SHA CI
→ PASS

required evidence
→ sufficient
```

---

# 48. Stop Condition

Once K5 satisfies the frozen contract:

```text
BLOCKER = 0
MAJOR = 0
all K5 core invariants PASS
required exact-SHA Gates PASS
```

stop.

Do not continue redesigning idempotency.

Do not generalize to unsupported product domains.

Do not begin K6 in the same task.

Correct terminal state:

```text
P9.K.5
Idempotency, Long-running Operations & Recovery Closure
        ↓
DONE / VERIFIED
        ↓
convergent audit
        ↓
GO → P9.K.6 External Client Migration
```

---

# 49. Engineering Decision Summary

The implementation should remain explainable in the following five rules:

```text
1. Product Command Receipt binds one external command identity to one authoritative resource.

2. Receipt and same-database business mutation commit in one transaction, so no generic incomplete-command workflow is needed.

3. ResearchRun remains the long-running Research operation; no duplicate ProductOperation authority is introduced.

4. Research execution crash recovery remains owned by existing Attempt/Lease/Fencing Worker protocol; Kernel RECOVERING owns control-plane authority and semantic→projection reconciliation.

5. Recovery always derives from the true authority, and ambiguity/conflict/corruption always fails closed.
```

If an implementation choice cannot be justified by one of these requirements, an accepted current ADR, or a concrete current invariant, it is probably unnecessary and should not be added.
