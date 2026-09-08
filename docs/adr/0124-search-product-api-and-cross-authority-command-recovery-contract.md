# ADR 0124: Search Product API and Cross-Authority Command Recovery Contract

- Status: Accepted
- Date: 2026-09-08 (amended 2026-09-08 for immutable Admission and monotonic historical-effect recovery)
- Decision maker: repository owner through the B3.4.1-A design and final recovery authorization
- Related: ADR 0104, 0120, 0121, 0122, 0123

## Context

OnlyAlpha already has a transport-neutral Product Command/Query boundary for Research, one global UUID4
`OnlyProductCommandId`, and immutable PostgreSQL Product Command Receipt records. The ADR 0104 amendment now requires a distinct
immutable PostgreSQL Product Command Admission for identity binding and narrows Receipt to accepted-outcome/replay binding; its schema
migration and implementation remain deferred. OnlyAlpha also has immutable, content-addressed Search Experiment provenance,
deterministic Symbolic Search, and deterministic adaptive Parameter Search.
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

Product Command ID -> command kind + canonical fingerprint
-> PostgreSQL product_command_admission

exact admitted Product Command -> accepted outcome binding
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

- ADR 0104 remains the Product Command identity contract: immutable PostgreSQL Admission is the sole command ID/kind/fingerprint
  binding Authority, while immutable PostgreSQL Receipt is the sole accepted-outcome/replay binding Authority.
- ADR 0120 remains the sole Search Experiment and Iteration provenance Authority.
- ADR 0121 remains the sole Symbolic Search Space, Proposal, enumeration, occurrence, and completion Authority.
- ADR 0122 remains the sole Parameter Search Space, Policy, Feedback Decision, frontier, adaptive transition, and STOP Authority.
- ADR 0123 remains the Agent orchestration and Model/Tool occurrence Authority.
- Research Run remains the Research operational Authority.
- Research Result and Research Statistics remain the scientific Evidence Authorities.

ADR 0104's same-database commands continue to commit Admission, accepted business effect, and Receipt in one PostgreSQL transaction.
Search facts are not in that database, so Search commands commit Admission before semantic work and use the cross-authority
semantic-re-entry rule below without weakening the atomic path for Research, Backtest, Strategy, or Qualification commands.

This ADR freezes architecture only. It adds no Product code, route, DTO, OpenAPI operation, enum, migration, Search adapter, query
service, Catalog projection implementation, Agent provenance, Agent runtime, or model integration.

### Authority and identity matrix

| Fact | Sole Authority | Product representation |
|---|---|---|
| external command identity binding | `OnlyProductCommandId` plus PostgreSQL `product_command_admission` | command ID, kind, canonical operational fingerprint |
| accepted Product outcome and replay binding | PostgreSQL `product_command_receipt` | exact Admission reference plus outcome reference |
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
!= Product Command Admission
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

An Admission certifies the immutable binding between one Product Command ID, its command kind, and its canonical command fingerprint.
It does not certify that a semantic effect occurred. A Receipt certifies the accepted binding between that exact admitted Product
Command and its authoritative semantic outcome. It does not certify that the system is still at the command's immediate post-state,
make a running Search immutable, snapshot its complete ledger, or authorize a second transition during replay. Later legitimate Search
progress cannot invalidate recovery of an earlier missing Receipt whose exact effect remains durably and uniquely provable.

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

The adapter must normalize and validate the complete intent before looking up or creating an Admission or Receipt. A reused Product
Command ID with a different command kind or canonical command fingerprint is `SEARCH_PRODUCT_COMMAND_CONFLICT` and produces zero new
work, even when its Receipt is missing, because the immutable Admission retains the original binding.

Product Command ID, HTTP idempotency key, route, timestamp, client/actor identity, and Agent lineage never enter the Search
Experiment, Plan, Result, Proposal, Enumeration, Feedback Decision, algorithm, or Search Policy fingerprint.

### Product Admission and Receipt Authorities

PostgreSQL `product_command_admission` is the sole mapping from Product Command ID to command kind and canonical command fingerprint.
PostgreSQL `product_command_receipt` is the sole mapping from an exact admitted command to its accepted Search outcome. Admission owns
intent binding; Receipt owns outcome/replay binding. Neither duplicates the other's fact, and Search Stores own semantic facts only and
must not expose or persist a Product Command ID to Search result index.

An Admission is immutable, insert-once, and committed before any cross-authority Search effect. Admission without Receipt means only
that one exact command intent was reserved; it is not a success record, mutable operation state, lease, execution permission, or proof
of an effect. A Receipt must exact-match the Admission's command ID, kind, and fingerprint before its outcome may be trusted.

The following are forbidden:

```text
search_submission_receipt
search_request_table
agent_search_receipt
Product Command ID field in a Search manifest
Search Store lookup by Product Command ID
mutable Product Command Admission state
```

Semantic re-entry by deriving an exact Search identity/effect from the admitted canonical intent is not a second Product Authority.
It verifies existing Search semantic Authority before the one Product Receipt is completed. Search history never binds Product Command
ID; only Admission does so.

### Common cross-authority protocol

Every mutating Search adapter follows this order:

```text
1. validate and canonicalize complete Product intent
2. insert-or-exact-load immutable Product Command Admission by OnlyProductCommandId
3. reject any Admission command-kind or canonical-fingerprint mismatch
4. look up Product Receipt and, if present, verify it against Admission and replay without a Search transition
5. if Receipt is absent, derive the exact pre-state and exact semantic effect admitted by the frozen Admission intent
6. commit or exact-verify immutable method resources
7. commit or exact-verify the Search Experiment/transition facts through owning Search APIs
8. exact-load and cross-verify the complete semantic outcome/effect
9. insert Product Receipt in PostgreSQL, requiring its exact Admission
10. on Receipt uniqueness loss, roll back only the Receipt transaction, reload the winner, and cross-verify Admission and outcome
11. return a typed projection over exact owning facts
```

Search Store commits are content-addressed, put-once, exact-load verified, and conflict detecting. A same-identity/same-content commit
is `REUSED`; a same locator or identity with different content fails closed. PostgreSQL Receipt insertion is unique by global Product
Command ID. No correctness step depends on process memory, time, filesystem order, or response delivery.

Two concurrent executions first converge on one immutable Admission. A different kind/fingerprint loser fails before semantic work.
Same-intent contenders may both reach semantic commit, but the owning put-once/CAS/ledger rules can admit only the same deterministic
effect. Exactly one Receipt row wins; every loser reloads and verifies the same Admission and Receipt. Different Product Command IDs
with identical canonical intent may bind the same content-addressed Experiment or the same uniquely admitted transition; they cannot
create two semantic effects.

Before creating or replaying a Receipt, the adapter verifies all of:

```text
Admission Product Command ID
Admission command kind
Admission canonical command fingerprint
Receipt exact match to Admission
Receipt outcome kind and exact Experiment fingerprint
exact Search Experiment manifest
method discriminant and schema
method-specific Search Space / Evaluation / Policy / Algorithm identities
method-specific expected-state and effect witnesses for Advance
```

Missing, corrupt, unsupported, dangling, or mismatched facts fail closed. Repair-by-replacement is forbidden.

### Exact cross-Authority fact clarification

Cross-Authority recovery proof terminates at the Authority that owns each claimed semantic fact. The following rules are normative:

1. Later legal Search descendants never invalidate an already exact-proven Submit Experiment effect. Submit historical proof ends
   after exact-loading the intended Experiment and verifying all method resources bound by that Experiment; the absence of later
   Plans, Enumeration, Feedback Decisions, frontier, or terminal facts is only a fresh-execution side-effect bound.
2. An optional fact is `ABSENT` only when its owning Authority returns the exact canonical `NOT_FOUND` result for the exact locator.
   Contextual verification failure, corruption, non-canonical bytes, unsafe paths, schema errors, dependency unavailability, and
   reference mismatch are `UNVERIFIABLE`, never absence, and fail closed.
3. A Product Receipt outcome reference is never sufficient semantic-effect proof by itself. Recovery must exact-load the referenced
   fact from its owning Authority and require exact identity equality. In particular, a Research Product Receipt used by Search must
   exact-resolve its referenced Research Run through the Research Run Authority before it may witness reconciliation.

### Submit crash and retry model

Submit derives the exact Search Experiment identity before publication from the complete canonical semantic inputs. It then follows:

```text
commit/verify immutable Product Command Admission
->
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
| no Admission, semantic fact, or Receipt | commit one immutable Admission; create/reuse one exact Experiment; create one Receipt |
| Admission exists, no semantic fact and no Receipt | verify exact Admission; repeat deterministic semantic admission; create/reuse one exact Experiment; create one Receipt |
| Admission conflicts with retry kind/fingerprint | `SEARCH_PRODUCT_COMMAND_CONFLICT`; zero semantic work and no Receipt repair |
| some immutable method resources, no Experiment or Receipt | verify Admission and resources; finish the same Experiment; create one Receipt |
| Experiment committed, Receipt absent | verify Admission; recompute exact intended Experiment identity; exact-load and fully verify it and its method context; create the missing Receipt |
| Receipt exists | verify Admission, Receipt, outcome, Experiment, and method context; return without creating semantic work |
| Receipt lacks/mismatches Admission or points to missing/corrupt/wrong-kind/wrong-Experiment fact | fail closed; never create replacement truth |

Product Command ID is unnecessary to find the semantic Experiment after Search commit because the Admission's complete canonical intent
deterministically recomputes the Experiment identity. Search remains semantic truth; Admission remains command-intent binding; Receipt
remains accepted-outcome/replay binding.

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

Current-State Admission and Historical-Effect Proof are distinct:

```text
Current-State Admission
!=
Historical-Effect Proof

Current-State Admission
-> decides whether NEW semantic work may execute

Historical-Effect Proof
-> decides whether a MISSING Product Receipt may be reconstructed
   for an effect already durably present
```

Before new work, the adapter must prove that exact actual current state equals the expected pre-state. Immediate post-state or a later
state never admits new work for the old command. For an admitted command whose Receipt is missing, the adapter may conceptually evaluate
this ephemeral verifier over existing Authority-owned facts:

```text
HistoricalEffectIncluded(
    admitted_canonical_command_intent,
    expected_pre_state,
    durable_search_history
)
-> exact verified effect | NOT_PRESENT | CONFLICT
```

This verifier creates no persisted `SearchTransition`, `CommandEffect`, `EffectReceipt`, or `EffectIndex`, and Search Stores gain no
Product Command lookup. It derives the one effect uniquely admitted by the immutable Admission intent and expected pre-state, then
exact-loads existing history to prove that effect's occurrence and lineage.

Search history is append-only and the proof is monotonic: if exact immutable effect `E` is uniquely admitted from pre-state `P` and
intent `I`, and valid history `H'` is a verified extension of `H` containing `E`, then:

```text
HistoricalEffectIncluded(I, P, H)  = E
implies
HistoricalEffectIncluded(I, P, H') = E
```

unless `H'` reveals corruption or conflict in `E`'s own lineage. A newer current state is not stale by itself.
`SEARCH_PRODUCT_STALE_EXPECTED_STATE` means current state differs from the expected pre-state and the exact intended historical effect
cannot be uniquely proven. A different occupant, unproven gap, invalid descendant lineage, or conflicting Product/Research fact remains
stale or corrupt and fails closed with zero new work.

### Advance crash, retry, and concurrency

For an exact-admitted, Receipt-absent Advance command, exactly one of these branches applies:

```text
current == expected pre-state
-> execute exactly one admitted bounded action under the owning lock/CAS/put-once boundary
-> exact-verify its effect witnesses
-> commit Receipt(SEARCH_EXPERIMENT)

current != expected pre-state
+ exact historical effect is uniquely proven in immutable history
-> execute nothing
-> commit missing Receipt(SEARCH_EXPERIMENT)

otherwise
-> fail closed
-> zero new work
```

The historical branch includes both the immediate post-state and any later verified descendant state containing the exact effect. It
invokes no Search transition or Research submission and consumes no Plan, Feedback Decision, Research Run, attempt, or Search budget.
This permits command A's Receipt to be repaired after A's durable effect, a lost Receipt, and valid later command B progress; B's
Receipt and later descendants do not replace the exact proof required for A. Admission A preserves A's identity binding throughout.

If the Receipt already exists, the adapter validates Admission, Receipt, and their exact match and does not invoke `advance()`,
`reconcile_open_plans()`, a Symbolic workflow, or a Research submit operation. It exact-loads the Experiment and projects the
authoritative transition facts identified by the command's expected-state-to-effect proof.

For Symbolic Search, historical inclusion exact-verifies the Search Experiment, Enumeration Result, expected iteration ordinal, exact
Plan occupant, Proposal fingerprint admitted by the deterministic occurrence proof, Plan fingerprint, and all parent/decision fields
required by ADR 0121. If Research submission occurred, it also verifies the stable Plan-derived Research Product Command ID, exact
Product Admission/Receipt and Research Run references, and exact terminal Iteration Result when applicable. Later ordinals are valid
descendants only after the contiguous prefix and exact old occurrence verify. An absent or different ordinal occupant, Proposal or Plan
mismatch, failed deterministic occurrence proof, ledger gap, Research identity/reference conflict, corruption, or schema mismatch is
`NOT_PRESENT` or `CONFLICT`, never successful recovery.

For Parameter Search Advance, historical inclusion exact-verifies the expected predecessor/frontier, Policy, ordered Evidence and
Plan/Result barrier, algorithm/runtime binding, exact Feedback Decision, and its complete canonical Plan batch. The current V1 Decision
has no literal persisted `predecessor` field: predecessor/descendant lineage is derived and verified from the Experiment's
`start_iteration_index`, ordered input Iteration Result prefix, Plans grouped by `decision_output_fingerprint`, the exact batch from
`plans_for_feedback_decision`, and the terminal/latest frontier. A later frontier is acceptable only when this exact durable chain
contains the Decision and its batch; “the current frontier is newer” or ancestry alone is insufficient. Historical verification
exact-loads immutable facts and does not require current runtime execution admission when no new work is requested.

For Parameter reconciliation, witnesses are limited to the exact expected batch's Plan-derived Product Admissions/Commands, Product
Receipts, Research Runs, and terminal Iteration Results that the bounded reconciliation could legally produce. A later unrelated batch
cannot satisfy the old command. All missing, conflicting, or ambiguous witnesses fail closed.

Content addressing, the Symbolic contiguous-ledger lock, the Parameter frontier CAS, per-Plan terminal uniqueness, normal Product
Command Admission/Receipt uniqueness, and stable Plan-derived Research command identity provide the concurrency boundaries. A stale
caller can never create new work. Repeating one accepted Advance Product Command can never advance another ordinal, produce another
Feedback Decision, submit another Research Run identity, or consume more budget.

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
injectivity: the global Admission stores the complete canonical Research submission fingerprint and the Receipt must match it, so any
derived UUID collision across different Plans/specifications is a Product Command conflict that creates no second Run. Changing this
derivation requires a new explicit derivation version and cannot reinterpret existing Plan submissions.

The required chain is:

```text
immutable Symbolic Iteration Plan
-> SEARCH_PLAN_RESEARCH_COMMAND_ID_V1
-> normal Research Product Command
-> Product Command Admission
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
B3.4.1-A ADR 0104/0124 contract freeze
-> B3.4.1-B Exact Catalog Context implementation
-> B3.4.1-C Product Command vocabulary and Admission/Receipt migration
-> B3.4.1-D Symbolic / Parameter Product adapters
-> B3.4.1-E HTTP / DTO / OpenAPI
-> B3.4.1-F fresh-process / concurrency / recovery closure
```

This map records dependencies only. It does not authorize a later phase.

## Required design proofs

1. **AT-01:** Product operations are typed adapters over ADR 0120/0121/0122; no Product-owned Search fact exists.
2. **AT-02:** Every mutating operation uses only `OnlyProductCommandId` as external command identity.
3. **AT-03:** PostgreSQL Admission is the sole command ID/kind/fingerprint binding Authority; PostgreSQL Receipt is the sole
   accepted-outcome/replay binding Authority.
4. **AT-04:** Search Stores contain no Product Command Admission, Receipt, or Product Command retry mapping.
5. **AT-05:** Search-commit/Receipt-loss retry verifies immutable Admission, then recomputes, exact-loads, and verifies the same
   Experiment/effect before creating one Receipt.
6. **AT-06:** A missing, dangling, corrupt, or mismatched Admission/Receipt pair fails closed and never causes replacement truth.
7. **AT-07:** Product Command ID and transport/Agent lineage are excluded from Search semantic identity.
8. **AT-08:** Symbolic Product code cannot alter enumeration, Proposal, Graph, or Candidate semantics.
9. **AT-09:** Parameter Product code delegates to ADR 0122 and cannot construct Feedback Decision or STOP.
10. **AT-10:** Symbolic Research execution must use the normal Research Product Command with `SEARCH_PLAN_RESEARCH_COMMAND_ID_V1`.
11. **AT-11:** Advance includes complete method-specific expected durable state; no generic mutable version is introduced.
12. **AT-12:** Only exact current pre-state admits new work; immediate or later verified history containing the exact effect permits
    only zero-execution Receipt repair; every other state is stale/conflicting.
13. **AT-13:** Admission-first identity validation, Receipt replay, and exact historical-effect verification prevent one command from
    changing intent or performing another transition.
14. **AT-14:** Search Experiment Query is exact-addressed and has no current/latest fallback.
15. **AT-15:** Ledger order comes from Symbolic ordinal or Parameter decision/batch occurrence, never filesystem order.
16. **AT-16:** Terminal query distinguishes `NON_TERMINAL` from exact Symbolic completion and Parameter STOP.
17. **AT-17:** Every Exact Catalog field is derived from an exact/versioned Authority; unavailable current-only facts are excluded or fail.
18. **AT-18:** Exact Catalog Context is a verified projection and never a second Catalog Authority.
19. **AT-19:** No generic mutable Search status/job table is introduced.
20. **AT-20:** REUSE remains direct Research and does not submit Search.
21. **AT-21:** This amendment changes architecture documentation only and stops before implementation.

### Final recovery closure scenarios

1. **Recovery AT-01 — immediate post-state:** effect `E1` is durable, its Receipt is lost, and no later progress exists. Retry
   verifies Admission and `E1`, commits the missing Receipt, and creates zero duplicate effect.
2. **Recovery AT-02 — later progress:** command A durably commits `E1`, loses Receipt A, and command B validly commits `E2` and
   Receipt B. Retrying A proves `E1` in immutable history, executes no Search work, and commits Receipt A.
3. **Recovery AT-03 — multiple descendants:** after `E1 -> E2 -> E3 -> E4`, retrying the command for `E1` proves the exact immutable
   occurrence and verified descendant lineage; later descendants do not invalidate it.
4. **Recovery AT-04 — Symbolic later ordinal:** after the exact ordinal `N` occurrence loses its Receipt and valid `N+1` and `N+2`
   occurrences exist, retry proves ordinal `N`'s exact Plan/Proposal occurrence and repairs the Receipt.
5. **Recovery AT-05 — Parameter later frontier:** after `F0 -> F1` loses its Receipt and valid `F1 -> F2 -> F3` progress exists,
   retry proves the exact derived predecessor relation, Decision, Plan batch, and descendant chain before repairing the Receipt.
6. **Recovery AT-06 — conflicting historical occupant:** a different occupant at the expected effect position is `CONFLICT`; the
   adapter creates no Receipt and performs no new work.
7. **Recovery AT-07 — missing effect:** a newer current state without proof of the exact intended effect fails closed.
8. **Recovery AT-08 — same Product ID, different intent:** the immutable Admission conflicts before historical proof, even when
   Receipt is missing and a semantic effect exists; no Receipt is repaired.
9. **Recovery AT-09 — no Search retry index:** Search Stores retain no `ProductCommandId -> effect` mapping. Admission and Receipt
   remain separate PostgreSQL Product Authorities for command identity and accepted outcome respectively.
10. **Recovery AT-10 — no extra budget:** historical Receipt recovery creates zero Plan, Feedback Decision, Research Run, attempt,
    Search transition, or additional budget consumption.

## Bounded independent review

| Review | Answer | Blocking rationale |
|---|---|---|
| IR-01 Does missing-Receipt recovery require current state to equal the immediate post-state? | No | immediate or verified later history containing the exact effect permits zero-execution repair |
| IR-02 Can later valid progress make an earlier durable exact effect unrecoverable? | No | monotonic inclusion preserves proof unless its own lineage conflicts |
| IR-03 Can an old retry execute a new transition after current state advances? | No | only exact current pre-state admits new work |
| IR-04 Does recovery prove the exact effect rather than mere ancestry? | Yes | admitted intent, pre-state, occurrence, and lineage all verify |
| IR-05 Is the exact Symbolic ordinal/Plan/Proposal occurrence verified? | Yes | ADR 0121 occurrence and contiguous-ledger witnesses are mandatory |
| IR-06 Is the exact Parameter predecessor Decision and Plan batch verified? | Yes | lineage is derived from existing facts and the complete batch is checked |
| IR-07 Are descendants accepted only after exact lineage verification? | Yes | a newer frontier or ledger alone proves nothing |
| IR-08 Can a conflicting historical occupant be successful recovery? | No | it is `CONFLICT` and fails closed |
| IR-09 Can historical proof bypass Product Command identity conflict? | No | immutable Admission is verified first, including when Receipt is missing |
| IR-10 Does the correction create a ProductCommandId index in Search Stores? | No | Admission is Product-side; Search history remains semantic evidence only |
| IR-11 Does Receipt recovery create Search/Research work or consume budget? | No | the historical branch has zero execution and budget effects |
| IR-12 Does the correction change ADR 0121 or ADR 0122 semantics? | No | it consumes their existing facts and verification rules |
| IR-13 Does historical repair require current runtime execution admission? | No | historical readability is separate from current execution eligibility |
| IR-14 Is exact current expected precondition mandatory before new work? | Yes | no other state admits execution |
| IR-15 Does the task remain design-only? | Yes | only ADR 0104 and ADR 0124 are amended |
| IR-16 Is Constitution Impact `NO`? | Yes | each distinct formal fact retains one explicit Authority |
| IR-17 Can Admission alone certify success or authorize blind retry? | No | only Receipt certifies outcome; execution still requires exact state proof |
| IR-18 Can Receipt disagree with Admission? | No | mismatch is an integrity conflict and fails closed |

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
- Mutable Product Command Admission, admission lifecycle state, or treating Admission as accepted outcome.
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

An external deterministic client can eventually create or advance one exact Search through a versioned Product boundary. Immutable
Admission preserves strict Product identity before Search work. Response loss between Search commit and Receipt commit converges
without a distributed transaction because the admitted canonical intent recomputes the same semantic identity/effect, including from
later verified descendant history. A corrupt cross-authority reference blocks instead of creating replacement truth. Method-specific
expected state prevents stale work and makes one Advance command incapable of consuming two transitions or budgets.

The approach requires later Product adapter logic to perform stronger cross-authority verification and requires a PostgreSQL
Admission/Receipt vocabulary migration. Exact Catalog Context can initially expose only capability families with genuine historical
exact proof. These costs preserve one Authority per distinct fact, deterministic recovery, and the narrow Agent/API boundary.

## Out of scope

```text
Product API implementation, Search service classes, or query services
Exact Catalog Context projection implementation
HTTP routes, DTOs, OpenAPI, generated clients, or URL selection
Product enum changes or PostgreSQL Admission/Receipt migration
Symbolic Research Command Gateway implementation
Parameter adapter/controller changes
Search pagination implementation
Agent provenance/application services, Orchestrator, model/LLM, RAG, or tools
B3.4.1-B and every later phase
```

## Constitution consistency

Constitution Impact: **NO**.

This decision strengthens Uniqueness and Single Authority by assigning Product command-intent binding only to Admission,
accepted-outcome binding only to Receipt, and Search semantics only to ADR 0120/0121/0122; Determinism by canonical complete intents,
exact expected state, and semantic re-entry; Recoverability by closing every Admission/Search/Receipt crash point; Fail-Closed behavior
by rejecting stale, dangling, corrupt, or mismatched cross-authority facts; Reproducibility and Traceability by exact method,
Experiment, Plan, Research, and Evidence references; and Explicit Boundaries by requiring the Product API while denying HTTP, Agent,
database, and Product projection Search-semantic ownership. It changes no Trading Kernel semantics, remains market-agnostic, grants no
Agent or LIVE Authority, and requires no Constitution change.
