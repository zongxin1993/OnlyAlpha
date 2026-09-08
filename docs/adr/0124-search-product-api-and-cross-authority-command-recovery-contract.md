# ADR 0124: Search Product API and Cross-Authority Command Recovery Contract

- Status: Accepted
- Date: 2026-09-08
- Decision maker: repository owner through the B3.4.1-A design authorization
- Related: ADR 0104, 0120, 0121, 0122, 0123

## Context

OnlyAlpha already has a transport-neutral Product Command/Query boundary for Research, one global UUID4
`OnlyProductCommandId`, and one PostgreSQL `product_command_receipt` retry-binding Authority. It also has immutable,
content-addressed Search Experiment provenance, deterministic Symbolic Search, and deterministic adaptive Parameter Search.
Parameter Search already submits its Research work through the normal Research Product Command with a stable Plan-derived
Product Command ID. Symbolic Search still depends on an abstract Research executor.

The versioned Product API has no Search command or query surface. Its current discovery operations describe the current process
and do not prove one exact historical Catalog Generation context. A future external deterministic client, including the Agent
described by ADR 0123, must be able to create and advance Search without importing Search implementation objects, reading Search
Store paths, touching PostgreSQL, or reconstructing scientific facts.

Search semantic facts and Product Command Receipts have different persistence authorities:

```text
Search Experiment / Space / Policy / Enumeration / Feedback / Plan / Result
-> immutable content-addressed Search Authorities

Product Command ID -> accepted outcome binding
-> PostgreSQL product_command_receipt
```

They cannot share one database transaction. This decision freezes deterministic semantic re-entry across those authorities. It
does not add two-phase commit, a transaction coordinator, a Saga/workflow Authority, a Search receipt Store, or a mutable Search
status database.

The permanent relationship is:

```text
Product API != Search Engine

Product API = typed external adapter over existing Search Authorities
```

## Decision

### Scope and compatibility

This decision is an additive Product boundary over existing Authorities. It does not reinterpret an existing identity, persisted
schema, Search algorithm, Research semantic, or Product receipt:

- ADR 0104 remains the Product Command identity and retry-binding contract.
- ADR 0120 remains the sole Search Experiment and Iteration provenance Authority.
- ADR 0121 remains the sole Symbolic Search Space, Proposal, enumeration, occurrence, and completion Authority.
- ADR 0122 remains the sole Parameter Search Space, Policy, Feedback Decision, frontier, adaptive transition, and STOP Authority.
- ADR 0123 remains the Agent orchestration and Model/Tool occurrence Authority.
- Research Run remains the Research operational Authority.
- Research Result and Research Statistics remain the scientific Evidence Authorities.

ADR 0104's same-database commands continue to commit their accepted business effect and Receipt in one PostgreSQL transaction.
Search facts are not in that database, so this decision adds the cross-authority semantic-re-entry rule below without weakening
the atomic path for Research, Backtest, Strategy, or Qualification commands.

This ADR freezes architecture only. It adds no Product code, route, DTO, OpenAPI operation, enum, migration, Search adapter, query
service, Catalog projection implementation, Agent provenance, Agent runtime, or model integration.

### Authority and identity matrix

| Fact | Sole Authority | Product representation |
|---|---|---|
| external command occurrence and retry binding | `OnlyProductCommandId` plus PostgreSQL `product_command_receipt` | command ID, kind, canonical operational fingerprint, outcome reference |
| Search hypothesis and Experiment/Iteration provenance | ADR 0120 Search Provenance | exact reference/projection only |
| Symbolic space, Proposal order, occurrence, and completion | ADR 0121 Symbolic Search | exact reference/projection only |
| Parameter policy, adaptive decision, frontier, and STOP | ADR 0122 Parameter Search | exact reference/projection only |
| Research operation | Research Product Command and Research Run | exact command receipt and Run reference |
| scientific metrics | Research Statistics | exact reference/projection only |
| Evidence membership | Research Result | exact reference/projection only |
| Catalog contents | Catalog Generation | exact verified projection only |
| Agent model/tool/decision lineage | ADR 0123 Agent provenance | never part of Search identity |
| LIVE authorization | explicit human LIVE Authority | unavailable to this Product surface |

There is no Product-owned Search fact and no generic Search-transition, Search-job, Search-score, or Search-status Authority.

The identities remain distinct:

```text
Product Command ID
!= Product Command Receipt
!= Search Experiment
!= Search Iteration Plan / Result
!= Symbolic Enumeration Result
!= Parameter Feedback Decision
!= Research Run / Result
```

An HTTP response is an observation of these facts, never an Authority.

### Transport-neutral Product vocabulary

Future typed Product commands are equivalent to:

```text
Submit Symbolic Search Experiment
Submit Parameter Search Experiment
Advance / Reconcile Search Experiment
```

Future typed Product queries are equivalent to:

```text
Exact Catalog Context Query
Search Experiment Query
Search Iteration Ledger Query
Search Terminal Decision / STOP Query
```

Existing operations remain reused:

```text
Research Definition Resolve
Research Run Submit
Research Run Query
Research Evidence Query
```

There is no `ExecuteSearch`, `SearchEngine.run`, `UniversalOptimizer`, or Agent-specific Search operation. HTTP path and method
spelling are deferred; URL, host, port, request ID, and transport verb never enter canonical identity.

### Product Command identity and outcome

Every mutating Search Product operation requires the existing canonical `OnlyProductCommandId`. There is no Search-specific
idempotency UUID. A later append-only Product vocabulary extension will add exactly these conceptual command kinds:

```text
CREATE_SYMBOLIC_SEARCH_EXPERIMENT
CREATE_PARAMETER_SEARCH_EXPERIMENT
ADVANCE_SEARCH_EXPERIMENT
```

and this outcome kind:

```text
SEARCH_EXPERIMENT
```

For all three kinds, the Receipt outcome is:

```text
outcome_kind = SEARCH_EXPERIMENT
outcome_id   = exact lower-case SHA-256 Search Experiment fingerprint
```

`ADVANCE_SEARCH_EXPERIMENT` deliberately points to the stable Experiment rather than an HTTP response fingerprint or a new
generic SearchTransition identity. Exact transition facts returned by an adapter are a verified response projection containing,
as applicable, Enumeration Result, Plan, Iteration Result, Product Receipt, Research Run, Feedback Decision, frontier, and STOP
references. Those references retain their owning Authorities.

A Receipt proves the accepted Product outcome binding. It does not make a running Search immutable, snapshot its complete ledger,
or authorize a second transition during replay.

### Canonical command fingerprint

Each command kind has a versioned, strict canonical intent schema. Its Product Command fingerprint is the existing canonical JSON
SHA-256 over the complete normalized operational intent. The Product Command ID and command kind are stored alongside the
fingerprint and are not silently injected into Search semantic objects.

Every fingerprint includes all fields capable of changing accepted work, including strict request schema version and the requested
bounded operation. It excludes:

```text
Product Command ID / HTTP Idempotency-Key
URL / HTTP method / headers / transport request ID
arrival or response time
actor display name / client identity
Agent Session / Model Call / Tool Call / Agent Decision fingerprint
host / PID / worker / path / log / UI metadata
```

The Symbolic Submit canonical intent includes:

```text
exact Search hypothesis
exact Catalog Generation fingerprint
exact Dataset Snapshot fingerprint
complete Symbolic Search Space reference and content identity
exact Research Evaluation Contract reference
exact Search Budget
exact algorithm ID, semantic version, implementation fingerprint, and source revision
exact workflow binding
exact deterministic decision-mode/engine binding
optional exact parent Experiment fingerprint
```

The Parameter Submit canonical intent includes:

```text
exact Search hypothesis
exact Catalog Generation fingerprint
exact Dataset Snapshot fingerprint
complete Parameter Search Space reference and content identity
exact Research Evaluation Contract reference
exact Search Policy reference and content identity
exact Search Budget
exact algorithm ID, semantic version, implementation fingerprint, and source revision
exact workflow binding
exact decision-mode/engine binding
optional exact parent Experiment fingerprint
```

The Advance canonical intent includes:

```text
exact Search Experiment fingerprint
exact method kind
method-specific requested bounded operation
complete method-specific expected durable state
request schema version
```

The adapter must normalize and validate the complete intent before looking up or creating a Receipt. A reused Product Command ID
with a different command kind or canonical command fingerprint is `SEARCH_PRODUCT_COMMAND_CONFLICT` and produces zero new work.

Product Command ID, HTTP idempotency key, route, timestamp, client/actor identity, and Agent lineage never enter the Search
Experiment, Plan, Result, Proposal, Enumeration, Feedback Decision, algorithm, or Search Policy fingerprint.

### Product Receipt is the sole retry-binding Authority

PostgreSQL `product_command_receipt` remains the only mapping from Product Command ID to accepted Search outcome. Search Stores own
semantic facts only and must not expose or persist a Product Command ID to Search result index.

The following are forbidden:

```text
search_submission_receipt
search_request_table
agent_search_receipt
Product Command ID field in a Search manifest
Search Store lookup by Product Command ID
```

Semantic re-entry by recomputing an exact Search identity from canonical intent is not a second retry Authority. It is verification
against the existing semantic Authority before the one Product Receipt is completed.

### Common cross-authority protocol

Every mutating Search adapter follows this order:

```text
1. validate and canonicalize complete Product intent
2. look up Product Receipt by OnlyProductCommandId
3. if Receipt exists, verify and replay without invoking a Search transition
4. if Receipt is absent, derive the exact pre-state and exact semantic effect admitted by the intent
5. commit or exact-verify immutable method resources
6. commit or exact-verify the Search Experiment/transition facts through owning Search APIs
7. exact-load and cross-verify the complete semantic outcome/effect
8. insert Product Receipt in PostgreSQL
9. on Receipt uniqueness loss, roll back only the Receipt transaction, reload the winner, and cross-verify it
10. return a typed projection over exact owning facts
```

Search Store commits are content-addressed, put-once, exact-load verified, and conflict detecting. A same-identity/same-content commit
is `REUSED`; a same locator or identity with different content fails closed. PostgreSQL Receipt insertion is unique by global Product
Command ID. No correctness step depends on process memory, time, filesystem order, or response delivery.

Two concurrent executions of the same canonical command may both reach semantic commit, but the owning put-once/CAS/ledger rules can
admit only the same deterministic effect. Exactly one Receipt row wins; every loser reloads and verifies the same row. Different
Product Command IDs with identical canonical intent may bind the same content-addressed Experiment or the same uniquely admitted
transition; they cannot create two semantic effects.

Before creating or replaying a Receipt, the adapter verifies all of:

```text
Receipt Product Command ID
Receipt command kind
Receipt canonical command fingerprint
Receipt outcome kind and exact Experiment fingerprint
exact Search Experiment manifest
method discriminant and schema
method-specific Search Space / Evaluation / Policy / Algorithm identities
method-specific expected-state and effect witnesses for Advance
```

Missing, corrupt, unsupported, dangling, or mismatched facts fail closed. Repair-by-replacement is forbidden.

### Submit crash and retry model

Submit derives the exact Search Experiment identity before publication from the complete canonical semantic inputs. It then follows:

```text
derive exact Experiment and method-resource identities
-> commit/verify immutable method-specific resources
-> commit/verify Search Experiment
-> commit Product Command Receipt
```

Method resources include, as applicable, Search Space, Evaluation Contract, Search Policy, historical Algorithm Manifest, and other
exact immutable inputs required by ADR 0121/0122. A Symbolic Enumeration Result is a post-Experiment execution fact and is not a
Submit input. The owning method determines which resources must precede Experiment contextual admission. The Product adapter cannot
weaken that ordering.

Crash cases are:

| Crash state | Retry behavior |
|---|---|
| no semantic fact and no Receipt | repeat deterministic admission, create/reuse one exact Experiment, then create one Receipt |
| some immutable method resources, no Experiment, no Receipt | exact-load/verify resources, finish the same Experiment, then create one Receipt |
| Experiment committed, Receipt absent | recompute exact intended Experiment identity, exact-load and fully verify it and its method context, then create the missing Receipt |
| Receipt exists | verify kind, command fingerprint, outcome, Experiment, and method context; return without creating semantic work |
| Receipt points to missing/corrupt/wrong-kind/wrong-Experiment fact | fail closed; never create a replacement Experiment |

Product Command ID is unnecessary to find the semantic Experiment in the critical third case because the complete canonical intent
deterministically recomputes the Experiment identity. Search remains semantic truth; the Receipt remains retry binding.

### Advance means one bounded canonical method action

Advance never grants arbitrary state mutation. The caller cannot supply a Proposal, Feedback Decision, Plan batch, score, Research
metric, qualification result, STOP reason, or next frontier. It asks the named canonical Search method to perform only the bounded
action admitted by exact durable facts.

The versioned operation vocabulary is method specific:

```text
SYMBOLIC:
  ADVANCE_ONE_SYMBOLIC_OCCURRENCE
  RECONCILE_ONE_SYMBOLIC_OCCURRENCE

PARAMETER:
  ADVANCE_ONE_PARAMETER_DECISION
  RECONCILE_OPEN_PARAMETER_BATCH
```

`ADVANCE_ONE_SYMBOLIC_OCCURRENCE` may commit at most the next exact ADR 0121 Plan occurrence admitted by the stored Enumeration
Result and deterministic prefix. It may submit at most that Plan's stable Research Product Command and may project an exact terminal
Result if the owning Run is terminal. `RECONCILE_ONE_SYMBOLIC_OCCURRENCE` names one exact already committed Plan and can only reconcile
that Plan's normal Research Run/Result/Qualification path.

`ADVANCE_ONE_PARAMETER_DECISION` delegates to the ADR 0122 Controller and may commit at most one exact next Feedback Decision and
that Decision's frozen Plan batch. It does not submit Research work. `RECONCILE_OPEN_PARAMETER_BATCH` delegates to
`reconcile_open_plans()` or the nearest canonical adapter and may reconcile only the exact open Plans already authorized by the
expected Feedback Decision batch. Its bound is the immutable batch and remaining durable Research budget; it cannot create another
Feedback Decision.

A later implementation may expose fewer calls by internally composing these actions only if the same bounds, effect witnesses, and
recovery proofs remain explicit. It must not expose one unbounded run-to-completion mutation.

### Method-specific expected durable state

There is no generic mutable `search_version`. Expected state is a canonical value made from existing method facts.

Symbolic expected state binds:

```text
exact Experiment fingerprint
exact Enumeration Result fingerprint
exact ordered committed Plan/terminal-Result prefix references
verified next iteration ordinal
durable Research and Qualification attempt counts derived from terminal Results
for reconciliation: exact target Plan and its observed Product Receipt / Run references or explicit absence
```

Parameter expected state binds:

```text
exact Experiment fingerprint
expected Feedback frontier fingerprint or explicit initial-null frontier
exact ordered Feedback Decision chain needed to prove that frontier
exact ordered Plan/terminal-Result barrier for the frontier batch
durable proposal/research/qualification budget consumption
for reconciliation: exact Product Receipt / Research Run references or explicit absence for each open Plan
```

Every collection is canonically ordered by semantic occurrence order. Filesystem enumeration, completion order, object insertion
order, and current process state are invalid inputs.

Before new work, the adapter compares expected state with exact actual state. If actual is neither the expected pre-state nor the
unique fully verified post-state/effect admitted from that pre-state and command intent, the result is
`SEARCH_PRODUCT_STALE_EXPECTED_STATE` with zero new work.

The post-state exception is essential for response-loss recovery. It is not a latest-state fallback: the adapter must prove the
exact effect that this immutable expected state and requested operation deterministically admit. A state that advanced past that
effect, contains a different occupant, has an unproven gap, or has a conflicting Receipt/Run remains stale or corrupt and fails
closed.

### Advance crash, retry, and concurrency

For a Receipt-absent Advance command:

```text
expected pre-state == actual
-> ask owning method for exactly one bounded action
-> exact-verify its effect witnesses
-> commit Receipt(SEARCH_EXPERIMENT)
```

If the Search effect commits but the Receipt is lost:

```text
retry same Product Command ID + kind + canonical intent
-> actual must equal the uniquely admitted verified post-state/effect
-> do not invoke the method again
-> commit missing Receipt
```

If the Receipt already exists, the adapter validates it and does not invoke `advance()`, `reconcile_open_plans()`, a Symbolic
workflow, or a Research submit operation. It exact-loads the Experiment and projects the authoritative transition facts identified
by the command's expected-state-to-effect proof.

For Symbolic Search, the exact Plan occupant at the expected next ordinal, its Proposal reference, and its terminal/Run facts are the
effect witnesses. For Parameter Search Advance, the exact Feedback Decision, predecessor frontier, and complete canonical Plan batch
are the effect witnesses. For Parameter reconciliation, the existing Plan-derived Product Command Receipts, Research Runs, and any
terminal Iteration Results are the effect witnesses.

Content addressing, the Symbolic contiguous-ledger lock, the Parameter frontier CAS, per-Plan terminal uniqueness, normal Product
Command Receipt uniqueness, and stable Plan-derived Research command identity provide the concurrency boundaries. A stale caller can
never create new work. Repeating one accepted Advance Product Command can never advance another ordinal, produce another Feedback
Decision, submit another Research Run identity, or consume more budget.

The expected precondition and exact proposed effect must cross the owning method's existing lock/CAS/put-once boundary together.
An adapter may not check state, release the concurrency boundary, and later ask the method to derive a new `next` value from a newer
snapshot. It must submit the exact effect derived from the command's expected state, so a race can only reuse that effect or fail
closed; it cannot turn a time-of-check/time-of-use race into the following transition.

### Symbolic Research Product Command closure

The current Symbolic workflow's abstract Research executor is not a production Product boundary. A future implementation must replace
that execution path at the application boundary with the normal Research Product Command and Research Run reconciliation path,
conceptually through an adapter such as `OnlySymbolicResearchCommandGatewayV1`.

Every Research submission identity is derived from the immutable Search Iteration Plan occurrence using the already deployed
Parameter Search derivation contract, frozen here as `SEARCH_PLAN_RESEARCH_COMMAND_ID_V1`:

```text
1. require a canonical lower-case SHA-256 iteration_plan_fingerprint
2. take its first 16 bytes
3. set the UUID version bits to 4
4. set the RFC 4122 variant bits
5. encode the canonical lower-case hyphenated UUID
```

The derivation is deterministic and contains no clock, random UUID generation, process counter, worker, or retry input. Because a
UUID4 encoding has fewer effective bits than SHA-256, collision safety is fail-closed rather than a false claim of mathematical
injectivity: the global Receipt stores the complete canonical Research submission fingerprint, and any derived UUID collision across
different Plans/specifications is a Product Command conflict that creates no second Run. Changing this derivation requires a new
explicit derivation version and cannot reinterpret existing Plan submissions.

The required chain is:

```text
immutable Symbolic Iteration Plan
-> SEARCH_PLAN_RESEARCH_COMMAND_ID_V1
-> normal Research Product Command
-> Product Command Receipt / Research Run
-> Run reconciliation
-> exact Research Result reference
-> terminal Search Iteration Result
```

Symbolic Product code cannot execute Research directly, invent a Candidate or Evidence, or use a random retry-time UUID. Parameter
Search continues to use the same existing derivation and Research Product path.

### Symbolic and Parameter adapter boundaries

The Symbolic Product adapter may validate intent, exact-resolve context, admit the current runtime, commit/verify method resources and
Experiment, invoke one bounded occurrence/reconciliation action, and project exact owning facts. It may not change enumeration order,
generate a Proposal outside ADR 0121, construct a Candidate, compute Evidence, or invent qualification.

The Parameter Product adapter delegates transitions to `OnlyParameterSearchControllerV1.advance()`,
`OnlyParameterSearchControllerV1.reconcile_open_plans()`, or the nearest stable canonical application adapter preserving those exact
semantics. It may not construct a Feedback Decision, Plan batch, Evidence score, or STOP.

HTTP is a thin adapter over the transport-neutral Product boundary and belongs only under `packages/onlyalpha-http-server/`. It may
not import Search persistence Stores, manipulate PostgreSQL Search data, or call method internals directly.

### Query operation classification

Product operations are classified by semantics, not HTTP verb:

| Operation | Class | Recovery meaning |
|---|---|---|
| Exact Catalog Context Query | `IMMUTABLE_EXACT_QUERY` | same exact request and contract version returns byte-equivalent canonical content |
| Search Experiment Query | `IMMUTABLE_EXACT_QUERY` | exact-load one immutable manifest and exact method references; no latest fallback |
| Search Iteration Ledger Query while a Search may grow | `MUTABLE_OBSERVATION_QUERY` | a later observation may differ and requires a new Agent Tool occurrence |
| Search Terminal Decision / STOP Query while non-terminal | `MUTABLE_OBSERVATION_QUERY` | later transition from non-terminal to terminal is legitimate and requires a new observation |
| Research Definition Resolve | `PURE_RESOLVE` | deterministic same input, no durable mutation |
| Search Submit / Advance / Reconcile | `IDEMPOTENT_COMMAND` | reconcile with the same Product Command identity and exact canonical intent |

An immutable exact query without a recorded ADR 0123 Tool Result may be replayed as the same Tool occurrence. A mutable observation
query may not: ambiguity fails closed and a later observation requires a new Tool Plan. This ADR freezes Product semantics only; Agent
Tool persistence remains later work.

### Search Experiment Query

Input is one exact Search Experiment fingerprint. Output contains the verified immutable Experiment manifest, exact method kind, and
exact method-authority references required to interpret it. It does not accept or resolve `current`, `latest`, nearest, equivalent, or
parent fallback. A missing, corrupt, unsupported, or contextually contradictory reference fails closed.

### Search Iteration Ledger Query

The ledger is a read projection over ADR 0120 occurrence facts and method-specific occurrence Authorities. It contains exact ordered
Plan/Result references and, as applicable, exact Symbolic Enumeration/Proposal or Parameter Feedback Decision/frontier references.
It contains no Product-owned status or copied scientific metric.

Ordering is semantic occurrence order: Symbolic Enumeration ordinal and contiguous Plan index for ADR 0121; Feedback Decision chain,
frozen batch order, and Plan index for ADR 0122. Filesystem traversal order is forbidden.

If paging is implemented, the cursor is versioned, canonical, and binds at least the exact Experiment, method kind, query schema,
last semantic occurrence position, and any immutable page-boundary identity needed to detect gaps or replacement. A cursor never
means current/latest. Gaps, duplicates, changed occupants, cursor mismatch, corruption, or unsupported versions fail closed.

### Search Terminal Decision / STOP Query

The query distinguishes exactly:

```text
NON_TERMINAL
TERMINAL_SYMBOLIC_COMPLETION
TERMINAL_PARAMETER_STOP
```

Symbolic completion and reason are derived only from the ADR 0121 Enumeration Result, canonical Plan/Result ledger, exact completion
flags, and durable budget facts. Parameter terminal status and reason are derived only from the ADR 0122 durable STOP Feedback
Decision. Absence of a terminal fact is `NON_TERMINAL`, never success. The Product layer cannot create a generic mutable terminal row
or synthesize a STOP reason.

### Exact Catalog Context

`OnlyExactCatalogContextProjectionV1` is a verified immutable-response projection over existing Authorities. Its conceptual envelope
contains:

```text
schema_version
catalog_generation_fingerprint
ordered_calculation_capabilities
ordered_registered_universes, only when an exact owning Authority is available
ordered_dataset_field_contracts, only when exact versioned source-contract Authority is available
ordered_statistics_capabilities, only when exact versioned capability Authority is available
projection_schema_fingerprint
projection_fingerprint
```

The request requires the exact Catalog Generation fingerprint and exact projection schema fingerprint/version. Only projection schemas
admitted by the versioned Product Contract are legal; the server derives and verifies the schema fingerprint from that complete
canonical contract rather than trusting a caller-supplied digest. The server exact-loads the generation and reconstructs every
included capability through its owning exact reader. Calculation capabilities are derived from the exact generation and its
Calculation registrations, never the active/current registry.

The optional capability families above are admitted only by a projection schema that defines their complete typed shape and only when
their owner can exact-load or reconstruct the requested historical version. A current process's module-level Dataset-field,
Statistics, or Universe enumeration is insufficient historical proof by itself. Unavailability is not represented as an empty set;
the query either uses a narrower admitted projection schema that omits the family or fails as
`SEARCH_PRODUCT_EXACT_CONTEXT_UNAVAILABLE`.

All collections use canonical semantic ordering. `projection_schema_fingerprint` identifies the complete field/type/order rules.
`projection_fingerprint` is canonical SHA-256 over the complete response excluding only itself. Under the same Product contract,
projection schema, exact authority roots/configuration, and exact Catalog Generation, the canonical response bytes are equivalent.

Catalog Generation remains the sole Catalog Authority. The projection owns no Calculation, Provider, Universe, Dataset field,
Statistics capability, activation, or historical reconstruction truth. It has no current/latest fallback. It may later be retained as
Agent observation provenance, but that does not transfer source Authority.

### Error model

The stable Product boundary categories are:

```text
SEARCH_PRODUCT_COMMAND_CONFLICT
SEARCH_PRODUCT_RECEIPT_CORRUPT
SEARCH_PRODUCT_CROSS_AUTHORITY_MISMATCH
SEARCH_PRODUCT_STALE_EXPECTED_STATE
SEARCH_PRODUCT_METHOD_UNSUPPORTED
SEARCH_PRODUCT_EXACT_CONTEXT_UNAVAILABLE
SEARCH_PRODUCT_RESULT_NOT_TERMINAL
```

They classify Product admission, consistency, concurrency, and recovery failures only. Owning ADR 0120/0121/0122, Research,
Catalog, Dataset, Result, Statistics, and Qualification errors remain intact and may be carried as typed causes. Product code must
not collapse corruption, stale state, unsupported method, and non-terminal observation into one generic error.

### REUSE path

ADR 0123's direct REUSE path remains:

```text
Exact Catalog Context
-> Research Definition Resolve
-> Research Run Submit
-> Research Run Query
-> Research Evidence Query
```

It creates no Search Experiment, Search Launch Record, Symbolic Proposal, Enumeration Result, Parameter Feedback Decision, or Search
Product Receipt. A capability that cannot be exactly reused follows the Router's frozen alternatives or fails closed; it is never
silently routed through Symbolic Search.

### No Product status or scientific Authority

Current Search state is projected only from exact Experiment, Space, Enumeration, Plans, Results, Feedback Decisions, Research Runs,
and budget facts. The following are forbidden as Authorities:

```text
search_status / search_current_state / search_job / agent_search_job table
mutable best candidate or current score field
Product-owned IC / RankIC / Sharpe / score / metric
Search-specific Candidate or Research Result Store
HTTP response-body fingerprint as business outcome identity
```

A future cache/read model must be explicitly non-authoritative, disposable, and verifiably reconstructible from owning facts.

### Future persistence and public-contract impact

The later implementation is HIGH risk because it changes public Product vocabulary, the versioned OpenAPI contract, HTTP DTOs,
generated clients, external consumers, Product receipt enums, and PostgreSQL constraints.

The migration phase must use one new append-only PostgreSQL 18 migration that extends the existing
`product_command_receipt.command_kind`, `outcome_kind`, and SHA-256 `outcome_id` checks. It must preserve all old rows and old migration
files, retain schema-version compatibility or introduce an explicit forward-compatible receipt revision, and add no second Receipt
table. Preconditions, transactional failure behavior, retry/restart behavior, compatibility window, data-integrity checks, and
forward-fix/rollback policy must be explicit and tested.

OpenAPI/HTTP work must be introduced only with contract, compatibility, consumer, error-mapping, and generated-client validation. URL
spelling remains non-semantic. HTTP cannot be used as a Store integration API.

### Placement and dependency order

Future transport-neutral Product command/query values belong in `src/onlyalpha/application/search_product.py` or the nearest accepted
application boundary. Method-specific adapters may live under `src/onlyalpha/research/search/product/` or the nearest stable Search
application boundary. HTTP remains in `packages/onlyalpha-http-server/`; the first-class OpenAPI contract remains under `contracts/`.

The dependency map is:

```text
B3.4.1-A ADR 0124 contract freeze
-> B3.4.1-B Exact Catalog Context implementation
-> B3.4.1-C Product Command vocabulary and Receipt migration
-> B3.4.1-D Symbolic / Parameter Product adapters
-> B3.4.1-E HTTP / DTO / OpenAPI
-> B3.4.1-F fresh-process / concurrency / recovery closure
```

This map records dependencies only. It does not authorize a later phase.

## Required design proofs

1. **AT-01:** Product operations are typed adapters over ADR 0120/0121/0122; no Product-owned Search fact exists.
2. **AT-02:** Every mutating operation uses only `OnlyProductCommandId` as external command identity.
3. **AT-03:** PostgreSQL `product_command_receipt` is the sole retry-binding Authority.
4. **AT-04:** Search Stores contain no Product Command retry mapping.
5. **AT-05:** Search-commit/Receipt-loss retry recomputes, exact-loads, and verifies the same Experiment before creating one Receipt.
6. **AT-06:** A dangling, corrupt, wrong-kind, or wrong-Experiment Receipt fails closed and never causes replacement truth.
7. **AT-07:** Product Command ID and transport/Agent lineage are excluded from Search semantic identity.
8. **AT-08:** Symbolic Product code cannot alter enumeration, Proposal, Graph, or Candidate semantics.
9. **AT-09:** Parameter Product code delegates to ADR 0122 and cannot construct Feedback Decision or STOP.
10. **AT-10:** Symbolic Research execution must use the normal Research Product Command with `SEARCH_PLAN_RESEARCH_COMMAND_ID_V1`.
11. **AT-11:** Advance includes complete method-specific expected durable state; no generic mutable version is introduced.
12. **AT-12:** Any state other than the exact pre-state or unique verified post-effect is stale/conflicting and produces zero work.
13. **AT-13:** Receipt-first replay plus exact post-effect verification prevents the same command from performing another transition.
14. **AT-14:** Search Experiment Query is exact-addressed and has no current/latest fallback.
15. **AT-15:** Ledger order comes from Symbolic ordinal or Parameter decision/batch occurrence, never filesystem order.
16. **AT-16:** Terminal query distinguishes `NON_TERMINAL` from exact Symbolic completion and Parameter STOP.
17. **AT-17:** Every Exact Catalog field is derived from an exact/versioned Authority; unavailable current-only facts are excluded or fail.
18. **AT-18:** Exact Catalog Context is a verified projection and never a second Catalog Authority.
19. **AT-19:** No generic mutable Search status/job table is introduced.
20. **AT-20:** REUSE remains direct Research and does not submit Search.
21. **AT-21:** B3.4.1-A changes architecture documentation only and stops before implementation.

## Bounded independent review

| Review | Answer | Blocking rationale |
|---|---|---|
| IR-01 Does Product API own a Search semantic fact? | No | all outputs are exact references/projections |
| IR-02 Is there more than one Search Product retry-binding Authority? | No | only PostgreSQL Receipt maps Product Command ID to outcome |
| IR-03 Can Product Command ID alter Experiment identity? | No | it is explicitly excluded |
| IR-04 Can Search-commit/Receipt-loss produce a duplicate Experiment? | No | deterministic identity plus put-once exact re-entry converges |
| IR-05 Can a dangling Receipt trigger replacement truth? | No | it is a fail-closed integrity error |
| IR-06 Does the design require 2PC/distributed transactions? | No | deterministic semantic re-entry closes the gap |
| IR-07 Can HTTP construct Symbolic Proposals or Parameter Feedback Decisions? | No | HTTP is a thin Product adapter |
| IR-08 Can Advance execute without exact method state? | No | expected durable state is mandatory |
| IR-09 Can stale caller state create work? | No | only exact pre-state can create; unique post-effect only repairs Receipt |
| IR-10 Can one Product Command perform two transitions? | No | existing Receipt short-circuits; post-effect retry never reinvokes method |
| IR-11 Can future Symbolic execution bypass Research Product Command? | No | normal Product Command and Plan-derived ID are mandatory |
| IR-12 Does Product own Research Result or metrics? | No | Result/Statistics remain sole Authorities |
| IR-13 Does Exact Catalog present current-only data as historical exact? | No | exact proof or narrower schema/failure is required |
| IR-14 Does an exact query use latest/current fallback? | No | exact identities are mandatory |
| IR-15 Is REUSE independent of Symbolic Search? | Yes | it remains direct Research |
| IR-16 Does the design modify ADR 0121/0122 semantics? | No | adapters delegate to them |
| IR-17 Did B3.4.1-A leak into implementation? | No | this ADR is the only repository change |
| IR-18 Is Constitution Impact NO? | Yes | the design strengthens existing invariants |

Bounded review result: Critical = 0; High = 0.

## Open-source design lessons

The design adopts only these general lessons:

- AlphaGen: proposal/search generation is separate from evaluation. OnlyAlpha Search proposes; normal OnlyAlpha Research/Evidence
  evaluates.
- RD-Agent: proposal, execution, and feedback are explicit stages. Agent session folders, logs, and model state are not recovery
  Authority.
- Qlib: loose coupling and workflow/interface separation motivate the Product boundary. Qlib workflow/task persistence is not an
  OnlyAlpha Authority.

AlphaGen score/RL/evaluator truth, RD-Agent runtime/session truth, and Qlib database/workflow authority are explicitly rejected.
These projects are design references, not normative or runtime dependencies.

## Rejected alternatives

- Product Command ID or Agent lineage inside Search identity.
- Search-specific idempotency key or second Receipt Store.
- Generic Search job/status/current-state database.
- HTTP response or cached response body as outcome Authority.
- A generic SearchTransition identity created only for transport.
- Product/HTTP construction of Proposal, Candidate, Feedback Decision, Evidence, score, qualification, or STOP.
- Direct HTTP access to Search Stores or direct PostgreSQL Search manipulation.
- Latest/current/fuzzy fallback for exact queries.
- Random or retry-time Research Product Command IDs.
- Two-phase commit, distributed transaction coordinator, Saga Authority, Redis workflow state, Celery, or Temporal as business truth.
- An Agent-specific Search engine, Research runtime, Candidate, Result Store, or scientific metric store.
- B3.2 `exact_graph_only` workaround or reinterpretation of ADR 0121/0122.

## Consequences

An external deterministic client can eventually create or advance one exact Search through a versioned Product boundary. Response
loss between Search commit and Receipt commit converges without a distributed transaction because canonical intent recomputes the
same semantic identity/effect. A corrupt cross-authority reference blocks instead of creating replacement truth. Method-specific
expected state prevents stale work and makes one Advance command incapable of consuming two transitions or budgets.

The approach requires later Product adapter logic to perform stronger cross-authority verification and requires a PostgreSQL Receipt
vocabulary migration. Exact Catalog Context can initially expose only capability families with genuine historical exact proof. These
costs preserve one Authority per fact, deterministic recovery, and the narrow Agent/API boundary.

## Out of scope

```text
Product API implementation, Search service classes, or query services
Exact Catalog Context projection implementation
HTTP routes, DTOs, OpenAPI, generated clients, or URL selection
Product enum changes or PostgreSQL migration
Symbolic Research Command Gateway implementation
Parameter adapter/controller changes
Search pagination implementation
Agent provenance/application services, Orchestrator, model/LLM, RAG, or tools
B3.4.1-B and every later phase
```

## Constitution consistency

Constitution Impact: **NO**.

This decision strengthens Uniqueness and Single Authority by retaining ADR 0104 and ADR 0120/0121/0122 ownership; Determinism by
canonical complete intents, exact expected state, and semantic re-entry; Recoverability by closing every Search/Receipt crash point;
Fail-Closed behavior by rejecting stale, dangling, corrupt, or mismatched cross-authority facts; Reproducibility and Traceability by
exact method, Experiment, Plan, Research, and Evidence references; and Explicit Boundaries by requiring the Product API while denying
HTTP, Agent, database, and Product projection semantic ownership. It changes no Trading Kernel semantics, remains market-agnostic,
grants no Agent or LIVE Authority, and requires no Constitution change.
