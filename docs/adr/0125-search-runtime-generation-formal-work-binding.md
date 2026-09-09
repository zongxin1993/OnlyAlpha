# ADR 0125: Search Runtime Generation Formal-Work Binding and Derived-Work Inheritance

- Status: Accepted
- Date: 2026-09-09 (amended 2026-09-09 for derived-work admission and historical-binding recovery)
- Decision maker: repository owner through the PRE-E.A implementation authorization
- Related: ADR 0104, 0116, 0117, 0120, 0121, 0122, 0123, 0124

## Context

ADR 0117 establishes one immutable Runtime Generation Work Authority whose append-only, hash-chained ledger owns
`work_id -> runtime_generation_fingerprint`. Research and Backtest are already formal work. Search Experiments are not yet bound to
that Authority, and Search-derived Research currently follows standalone Research admission and can therefore select a newer active
generation after the parent Search was admitted.

Search scientific identity, Product operational identity, and executable deployment identity are distinct:

```text
Search Experiment fingerprint != Product Command identity != Runtime Generation fingerprint
```

The generation must be frozen before Search semantic work, survive Product Receipt loss and activation changes, and be inherited by
independently scheduled Research derived from the Search. No Search Store or PostgreSQL relation may become a parallel execution-binding
Authority.

## Decision

### Search is formal Runtime work

One Search Experiment has the deterministic, domain-separated formal-work identity:

```text
search-experiment:<experiment_fingerprint>
```

The prefix is execution-work vocabulary only. It does not enter the Search Experiment fingerprint or create a Search semantic identity.
Search Plans remain descendants inside the Search root and receive no independent generation binding. Independently scheduled Research
Runs remain formal child work and receive their own inherited binding.

### Sole Authority and append-only ledger evolution

`OnlyRuntimeGenerationWorkAuthority`, durably implemented by `OnlyRuntimeGenerationRegistry`, remains the sole owner of every formal
`work -> generation` fact. It gains:

```text
bind_work_exact(work_id, runtime_generation_fingerprint, actor, occurred_at)
bind_derived_work(parent_work_id, child_work_id, actor, occurred_at)
```

The existing `RuntimeWorkBound` event retains its historical meaning: it binds new root work to the generation active at that event.
Exact and derived binding append the new `RuntimeExactWorkBound` event. Existing event bytes and replay semantics are unchanged.

Exact binding requires the requested generation manifest and its exact Validation Evidence, rejects unavailable or rejected/retired
generations, reuses an existing identical binding, and conflicts if the work already names another generation. Derived binding exact-loads
the active parent binding and gives the child that same generation without reading `ACTIVE_FOR_NEW_WORK`; a differently pre-bound child
conflicts.

### Forward-only Search Product Submit V2

`OnlySubmitSymbolicSearchExperimentV2` and `OnlySubmitParameterSearchExperimentV2` add exactly
`runtime_generation_fingerprint` to Product operational intent. Their canonical Product command fingerprints include it. V1 command
types, schemas, canonical payloads, and fingerprints remain unchanged.

The existing Search Experiment V2/V3 schemas remain unchanged. Runtime Generation is excluded from their fingerprints. For identical
scientific Search intent, changing only Runtime Generation therefore preserves the Experiment fingerprint and changes the Product
command fingerprint.

New executable Search admission uses Submit V2. Submit V1 remains readable as historical operational vocabulary but cannot create new
executable Search work.

### Submit ordering and recovery

The canonical V2 sequence is:

```text
strict command validation and canonicalization
-> derive exact Search Experiment from scientific inputs only
-> exact-verify requested Runtime Generation and Validation Evidence
-> for a new Product Admission, require requested generation == ACTIVE_FOR_NEW_WORK
-> commit or exact-load Product Admission containing the requested generation in its fingerprinted intent
-> exact-bind search-experiment:<E> -> admitted G
-> commit/exact-verify method resources and Experiment E
-> cross-verify Admission, binding, Experiment, and method context
-> commit Product Receipt -> E
```

An existing exact Admission freezes the command's generation. Retry never rereads current activation. If G was active at fresh admission
and becomes DRAINING before the binding or Receipt commits, retry exact-binds E to G. A prior E binding to another generation conflicts.
Receipt replay exact-verifies the binding and owning Search facts and performs no Search mutation.

Fresh admission may not request an arbitrary READY, DRAINING, RETIRED, REJECTED, missing, corrupt, or validation-mismatched generation.
Recovery of an already admitted command may use its still-available DRAINING generation. Activation and rollback affect future root work
only and never rebind an existing Search.

### Derived Research inheritance

Search-triggered Research continues through the normal Research Product Command, Research Run Authority, Receipt, Worker, Result, and
Evidence path. The Search adapter supplies only a verified parent formal-work ID as operational execution context:

```text
Search E -> G
normal Research Product Command prepares Run R
-> bind_derived_work(search-experiment:E, R)
-> R -> G
-> durable Research queue admission
```

The derived binding must exist before the Run becomes executable. Retry of the same Research Product command verifies the existing child
binding equals the parent generation. Standalone Research supplies no parent and retains `bind_new_work()` behavior.

Runtime Generation does not enter Research Specification, Research Result, Candidate, Search Plan, or Search Experiment scientific
identity.

Search-derived Research uses a forward-only Product operational command schema whose canonical intent includes the exact parent formal
work ID. The parent must be the canonical `search-experiment:<experiment_fingerprint>` identity. Historical standalone Research command
bytes and fingerprints remain unchanged. Reusing one Product Command ID with another parent conflicts even when both parents bind the
same Runtime Generation; generation equality cannot substitute for causal lineage.

Before any derived Runtime binding, the complete Product intent is admitted by the existing Product Command Admission Authority. The
child Research Run ID is a domain-separated deterministic UUID4 derived only from that immutable Product Command ID. The normal Research
Run Admission service may receive this exact internally precomputed ID; standalone admission retains its existing Run-ID factory. Thus a
crash after `child -> generation` binding but before the atomic Research Run/Receipt commit retries the same child ID, exact-reuses the
same binding, and cannot strand a random alternate child.

The derived sequence is:

```text
canonical derived Product intent including parent work
-> immutable Product Admission
-> deterministic child Research Run ID
-> active parent verification for a new child
-> exact derived child binding
-> normal Research Run + Product Receipt commit
-> exact Product / Run / historical child binding / historical parent binding verification
```

An already admitted and already bound child may finish Run/Receipt recovery after its parent becomes inactive, provided both historical
bindings still name the same generation. A genuinely new child always requires an active parent.

### Historical binding and execution eligibility

`RuntimeWorkReleased` ends execution eligibility; it does not erase `work -> generation` history. Historical exact reads and identical
exact-bind replay return the immutable assignment with `active=false`. They never reactivate work, and a released work ID can never bind
another generation. Worker claim and execution continue to use active-only `work_ids_for_generation()` and
`require_work_generation()` fencing.

Derived Product Receipt replay exact-loads the Research Run and verifies historical child and parent bindings plus generation equality.
It does not require the terminal child to be active. Search reconciliation can therefore project a completed Research Result after the
Worker releases the child's execution eligibility.

### Historical Search Submit compatibility

Admission capability and historical replay capability are distinct. The canonical Product dispatcher recognizes Search Submit V1 and
V2. A V1 command without an existing exact Product Admission cannot create executable Search work. A V1 command with an exact Admission
and historical Search Runtime binding may recover or replay through the canonical Product boundary, including when that binding is
inactive. V2 remains the only normal new-Search admission path. Neither rule changes V1 command bytes or fingerprints.

### Legacy Search and retention

Exact Search Experiment, ledger, and terminal queries read scientific facts without requiring a Runtime binding. Advance and Reconcile
require an active exact Search work binding and fail as `SEARCH_RUNTIME_GENERATION_UNBOUND` when it is absent. No Catalog fingerprint,
algorithm/source revision, current generation, latest generation, or active generation may be used to guess or backfill a historical
binding.

A Search binding is retained while the Search may execute. Automatic release requires a later proof that the Search is terminal and no
derived executable work remains active. Until that proof exists, retention is safer than premature release; retained work therefore blocks
generation retirement through the existing Authority.

### Error boundary

Search Product maps the Runtime Authority's stable failure codes at one adapter boundary to typed Product errors including:

```text
SEARCH_RUNTIME_GENERATION_UNBOUND
SEARCH_RUNTIME_GENERATION_BINDING_CONFLICT
SEARCH_RUNTIME_GENERATION_NOT_FOUND
SEARCH_RUNTIME_GENERATION_UNAVAILABLE
SEARCH_RUNTIME_GENERATION_INVALID
SEARCH_RUNTIME_GENERATION_NOT_ELIGIBLE_FOR_NEW_WORK
SEARCH_RUNTIME_GENERATION_DERIVED_BINDING_CONFLICT
```

## Consequences

Search execution bytes are now durably explicit without changing Search scientific identity. Product Admission freezes deployment intent,
the existing Runtime ledger alone owns the binding, and Search-derived Research cannot drift to a newly activated generation. Existing
Runtime ledgers replay with their original event semantics. No PostgreSQL migration, Search runtime mapping Store, historical process host,
HTTP/OpenAPI surface, Agent runtime, LLM/RAG capability, or LIVE authority is introduced.

Retaining nonterminal Search bindings may retain a DRAINING generation longer than necessary. That resource retention is accepted until a
separate terminal-plus-derived-work release proof is designed.

## Rejected alternatives

- Runtime Generation in Search Experiment V2/V3 or a new Search Experiment V4 solely for deployment identity.
- A Search execution-binding table, database, Store, Receipt field, or PostgreSQL mirror.
- Binding an admitted retry or derived Research Run from current activation.
- Guessing a historical generation from Catalog, algorithm/source revision, package availability, latest, or active state.
- Reinterpreting `RuntimeWorkBound` so historical events no longer mean active-at-bind.
- Bypassing the normal Research Product Command for Search-derived Research.
- Premature Search binding release before terminal and descendant-work closure is proved.
- Random derived Research Run IDs followed by compensating orphan cleanup.
- Parent lineage inferred from generation equality or persisted in a new Work Lineage Authority.
- Treating release as deletion of historical binding or reactivating released work for replay.

## Constitution consistency

Constitution Impact: **NO**.

This decision preserves one Authority and identity for each fact, makes execution deployment an explicit durable input, keeps scientific
identities immutable, makes crash/activation timing deterministic, preserves append-only history and fail-closed recovery, and keeps Core
market-agnostic. It changes no Trading Kernel, Product HTTP, Agent, Promotion, or LIVE Authority and requires no Constitution change.
