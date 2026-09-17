# ADR 0129: Private L3/L4 Database-Native Architecture Freeze

- Status: Accepted
- Date: 2026-09-17
- Related: ADR 0110, 0111, 0112, 0115, 0116, 0117, 0118, 0120–0128
- Constitution Impact: NO

## Context

ADR 0110–0117 established the four-layer quant-asset model, private-repository/distribution loading, immutable Provider and Catalog
Generations, exact implementation identity, authoring execution generations, Runtime Generations and StrategyRevision Freeze. ADR
0120–0128 established the Search, Agent, Evidence, Novelty and Product-command boundaries that will consume private research assets.

That model is correct about identity, Evidence, admission and runtime binding, but it makes a mutable Git repository and a package/wheel
the default production authoring center for private L3 Factors and L4 Strategies. Private L3/L4 authoring is a product capability with
Web/Agent Drafts, immutable revisions, validation, Research, Evidence and admission. Its durable authoring Authority must therefore be
OnlyAlpha-owned and recoverable, not dependent on a repository checkout or package workflow.

The architecture must also keep two boundaries separate:

```text
Database Authoring Authority
!=
Runtime Execution Authority
```

PostgreSQL may durably own Drafts, immutable Revisions and their exact source/definition content. That does not grant an API process,
Web request, database client or ordinary application process permission to execute stored Python. Runtime execution remains an exact,
isolated, generation-bound capability governed by the existing Calculation, Catalog and Runtime authorities.

## Decision

Private L3/L4 are frozen as **product-native database authoring assets**. Git, source checkouts, wheels and package distributions remain
optional interoperability, import/export and provenance mechanisms; none is required production authoring Authority.

The existing quant-asset, Research, Qualification, Admission, Catalog, Runtime Generation and StrategyRevision authorities remain in
force. This ADR changes the private authoring/source-location boundary only and does not implement any of the deferred components below.

### Authority change

| Fact | Authority after ADR 0129 | Not an Authority |
|---|---|---|
| Private L3/L4 Asset, Draft and Revision authoring content | PostgreSQL-backed Private Asset Authority | Git repository, package, wheel, Web cache, Agent memory |
| L3 source identity | immutable Revision source fingerprint | filename, path, branch, package version |
| L3 API meaning | exact versioned L3 API Contract and fingerprint | adapter implementation or current installed code |
| L3/L4 scientific result | existing Research/Evidence authorities | Asset, Draft, Revision, Registry or Search Projection |
| Qualification | existing Qualification authority | Agent confidence or mutable asset status |
| admitted capability set | Factor Registry / Provider Snapshot and existing Catalog Generation authorities | Search Projection, current/latest lookup |
| executable bytes and process composition | existing Distribution/Runtime Generation authorities | database source text, Git checkout, active Catalog pointer |
| L4 runtime strategy identity | existing Strategy Freeze / StrategyRevision authority | L4 Draft, Revision, path, package or display name |

### Single-file L3 Source Contract

Private L3 V1 is:

```text
One Factor
= one Private L3 Asset
+ one immutable Private L3 Revision
+ exactly one canonical UTF-8 Python Source Unit
+ one exact L3 API Contract Version
```

The source unit is stateless, single-file, database-native, versioned and deterministically fingerprinted. It is executed only through
an isolated runtime binding. V1 does not require a Python package, Git repository, wheel or multi-file source tree.

The source entry point is exactly:

```python
def calculate(api, inputs, parameters):
    ...
```

The exact callable signature and return contract belong to L3 API Contract V1. The source unit does not duplicate authoritative Factor
ID, semantic version, schemas, descriptions, qualification state or admission state; those belong to the Asset/Revision and owning
OnlyAlpha authorities.

V1 is deliberately narrow. A Revision source unit:

- contains exactly one canonical `calculate` entry;
- is valid canonical UTF-8 source text with one exact source SHA-256/fingerprint;
- is stateless and deterministic for the declared API inputs;
- does not access PostgreSQL or another database directly;
- does not access the network, subprocesses, Docker control or arbitrary filesystem mutation;
- does not use `eval`, `exec` or dynamic-import authority;
- does not import unstable OnlyAlpha internal modules; and
- does not contain a second authoritative metadata or lifecycle contract.

The source text may be stored directly in PostgreSQL. The logical contract is one exact source unit per Revision; physical DDL, table,
index and large-value storage choices are deferred. Database storage is content persistence, not execution permission.

### L3 Asset, Draft and Revision

The conceptual objects are:

- `PrivateL3Asset` answers **what Factor is this?** It owns stable asset identity and semantic-version intent, not mutable source or
  Research outcome.
- `PrivateL3Draft` is a mutable authoring workspace for Web/Agent and human editing. It is not immutable scientific truth, admitted
  runtime content, a Factor Registry entry or a Strategy identity.
- `PrivateL3Revision` is immutable exact content. Any semantic source/definition/API-binding change creates a new Revision. Failed
  validation, Research or qualification does not delete the Revision or rewrite its history.

Draft-to-Revision publication is an immutable content transition. Revision creation does not imply validation, Qualification, Admission,
Catalog availability or Runtime availability.

### L3 identity separation

The following identities are distinct and must never be substituted for one another:

```text
Factor ID
Asset Semantic Version
Authoring Revision
Source Fingerprint
Implementation Fingerprint
L3 API Contract Version
L3 API Contract Fingerprint
L3 API Adapter Implementation Fingerprint
Catalog Generation
Runtime Generation
```

In particular:

```text
Revision != Semantic Version
API Version != Semantic Version
Source Fingerprint != Implementation Fingerprint
L3 API Contract Fingerprint != L3 API Adapter Implementation Fingerprint
Catalog Generation != Runtime Generation
```

An L3 Revision binds one exact API Contract version and fingerprint. Runtime work additionally binds the exact source fingerprint, API
contract identity, adapter implementation fingerprint and Runtime Generation. A bug fix that restores the declared API semantics may
retain the API version while changing the adapter implementation fingerprint; a logical API change requires a new API version.

### Stable L3 API Contract V1

Every immutable L3 Revision binds exactly:

```text
l3_api_version = 1
l3_api_contract_fingerprint = exact canonical contract identity
```

Version ranges such as `>=1`, `1.x` and `^1` are invalid. Same L3 API Contract Version means the same logical contract forever,
including operation meaning, input/output domain, missing-value policy, warmup policy, precision and numeric semantics,
division-by-zero behavior, ordering, error algebra and determinism. A breaking meaning change creates a new API version and new
Revisions; it never silently changes API V1.

The API is a narrow facade over existing authoritative Calculation/operator semantics. Its operation set is intentionally bounded and
may include existing lag/diff, arithmetic, rolling, rank/z-score and missing/conditional families as separately admitted contract
content. The exact exhaustive primitive list is deferred. The adapter delegates to existing Calculation/operator authorities and must
not become a second calculation engine.

### API, validation and runtime binding

The conceptual runtime path is:

```text
load exact Private L3 Revision
→ verify source fingerprint and immutable identity
→ verify exact API version and contract fingerprint
→ materialize one immutable source unit
→ apply static/policy validation
→ execute/import only across a dedicated isolated boundary
→ bind exact Catalog/Runtime Generation and adapter implementation
```

Production API/Web/application processes MUST NOT direct-`exec` or direct-`eval` raw database source. AST/static validation is a policy
gate, not a sandbox. Only a dedicated validation/runtime boundary may materialize or execute a Revision, and it must fail closed on
missing, corrupt, mismatched, unsupported or ambiguous inputs. The exact sandbox, process model and source-materialization path are
implementation questions, not this ADR's contract.

Historical work binds exact Revision/source/API/adapter/runtime identities. Runtime never resolves a `latest` Private L3 Revision or
falls forward to another source, API, adapter or generation.

### L4 Database-Native Structured Definition

Private L4 is database-native and declarative. The conceptual objects are `PrivateL4Asset`, `PrivateL4Draft` and immutable
`PrivateL4Revision`. An L4 Revision contains a canonical structured Strategy Definition with exact Calculation/Factor references,
parameters, eligibility, selection, entry/exit and other existing strategy-owned configuration.

Private L4 V1 does not require:

```text
strategy.py
Python package
Git repository
wheel
```

An L4 Draft is mutable authoring input, not runtime identity. An L4 Revision is immutable authoring content, not automatically a
StrategyRevision. The exact path remains:

```text
Private L4 Revision
→ validation and exact reference resolution
→ existing Strategy Freeze
→ immutable StrategyRevision
→ Backtest / SIM / LIVE through existing runtime contracts
```

`StrategyRevision` remains the sole exact runtime Strategy identity. L4 paths, packages, display names, Git commits and database row
locations never become runtime identity.

### Factor Registry and Search Projection

The future **Private L3 Factor Registry** is an authoritative query boundary for:

```text
What admitted Factors/capabilities do we have?
```

It may expose exact asset, Revision, semantic-version, API, capability and admission references. It does not own Research outcomes,
dynamic metrics, Qualification PASS/FAIL, Experiment Memory or Runtime activation. It is not implemented here.

A separate rebuildable **Factor Search Projection** is optimized for summary-first discovery. It may project category, description,
rationale, tags, input/output roles, parameter descriptors, operator/capability descriptors and exact admission/qualification
references. It may be rebuilt or discarded and is never Factor Authority. A missing or incomplete projection cannot certify absence,
equality, novelty or qualification.

The permanent knowledge separation is:

```text
Factor Registry   → what assets/capabilities exist
Experiment Memory → what was tried (ADR 0127 projection)
Research Evidence → what scientifically happened
Qualification     → what formal policy decision was made
```

Similarity is advisory. Similarity is not equality, and a Search Projection is not a scientific or runtime authority.

### AI reuse-first retrieval and generation

Agent discovery is bounded by the formal Product API. Agents MUST NOT directly query PostgreSQL, private JSON stores, source paths or
internal Python objects as an authority path. Future versioned Product operations may provide exact summary, metadata and source reads,
as well as Draft/Revision lifecycle commands, but route names are deferred.

The retrieval order is fixed:

```text
REUSE
↓
COMPOSE
↓
PARAMETERIZE
↓
GENERATE_NEW_L3
```

Conceptual decisions are `REUSE_EXISTING`, `COMPOSE_EXISTING`, `PARAMETER_SEARCH` and `GENERATE_NEW_L3`. Generation requires positive
capability-gap evidence such as no existing Factor, no suitable symbolic composition and no suitable parameterized variant. The
planner does not generate code merely because a model can generate code.

Normal discovery is summary first, metadata second and source last. Source retrieval is exact and permission-checked; it is not a
bulk source dump or an execution path.

### L3 generation, validation, Evidence and Admission

The intended L3 lifecycle is:

```text
Hypothesis
→ exact Registry/Memory/Evidence retrieval
→ reuse / compose / parameter checks
→ capability-gap evidence
→ Factor Definition
→ generate one canonical source unit
→ PrivateL3Draft
→ immutable PrivateL3Revision
→ static/API/determinism validation
→ Research
→ Evidence
→ Qualification
→ Admission
→ Factor Registry / Provider Snapshot
→ Catalog Generation
→ exact Runtime Generation binding
```

L3 Definition precedes source generation and owns identity intent, category, economic rationale, inputs, outputs, parameters, required
API version and semantic description. The source implements that Definition; it does not redefine the metadata. Failed revisions remain
discoverable as exact failure knowledge through their owning Search/Experiment/Evidence/Qualification authorities where applicable.

No generated output jumps directly from Draft or Revision to Runtime. `Revision != Admission`, `Admission != Qualification`, and
`Qualification != Promotion`.

### Historical Replay and Migration

Historical Research, Evidence, Qualification, Catalog and Runtime references remain bound to exact immutable identities. A runtime must
resolve the exact Private L3 Revision/source fingerprint, API Contract version/fingerprint, adapter implementation fingerprint and
Runtime Generation; it must never select a latest or semantically nearest Revision.

An L3 API V1-to-V2 migration creates new immutable Revisions and never mutates historical source. It may retain the Factor semantic
version only when exact semantic equivalence is proven and the owning identity contract permits that change; a mathematical or
canonical input/output meaning change requires a new semantic version. A source or adapter bug fix that restores the declared API
meaning may change implementation identity while retaining API V1.

L4 Definition changes create a new immutable L4 Revision and go through a new Strategy Freeze when they change strategy semantics.
Existing StrategyRevisions, Evidence, Catalog Generations and Runtime Generations retain their exact historical references. Missing,
corrupt or ambiguous historical source/API/adapter/runtime closure fails closed; no fall-forward or silent migration is allowed.

### PostgreSQL, security and deployment scope

PostgreSQL is the intended Private L3/L4 authoring and Revision Authority. This ADR does not freeze DDL, table names, migrations,
indexes, FTS/JSONB/vector design, tenancy model or physical storage layout.

The following security boundary is permanent:

```text
DB read permission != code execution permission
```

Web/API ordinary request processes, Agent tools, SQL clients and database readers cannot execute arbitrary Draft or Revision source.
Static/AST checks are necessary policy gates but are not sandboxes. Execution needs a dedicated isolated validation/runtime boundary with
exact identity verification.

Official platform and external-market extensions remain distribution-based. HTTP server, Gateway Protocol, Runtime Generation Manager,
Agent Orchestrator, workers, Tushare, Binance, MiniQMT, Operators, Indicators and Targets are not converted into database-stored source
by this ADR:

```text
Extension Code != Private Research Asset Code
```

### Relationship to B3.6 and B3.5

This ADR is the intended foundation for future **B3.6 — Isolated L3 Code Generation / Admission**. The earlier assumption that B3.6
must culminate in a separate Git repository/package PR is superseded in part. Future B3.6 targets the DB Draft/Revision lifecycle,
isolated validation, Research/Evidence, Qualification/Admission and exact Catalog/Runtime binding. It does not receive implementation
authorization from this ADR.

ADR 0127 remains authoritative for Experiment Memory, novelty, source-cut/query witnesses, exact reuse/suppression decisions and
similarity semantics. Factor Registry/Search Projection is not Experiment Memory, and no B3.5 decision is copied into Factor Authority.

## Supersession and compatibility

This ADR does not delete or rewrite historical ADR bodies. It supersedes **in part** the following provisions:

```text
ADR 0110: private-repository placement as the required production L3/L4 authoring location
ADR 0111: source/editable or installed package as the required private L3/L4 authoring modes
ADR 0115: private-repository/Git workflow and Git/source location as required private authoring authority
```

For private L3/L4, these provisions now mean optional import/export/interoperability and provenance paths. They remain valid when a
private Revision is materialized into a distribution/provider/runtime artifact or when an external/private compatibility workflow
explicitly uses a package. The following remain preserved:

- the four-layer L1/L2/L3/L4 taxonomy and canonical Calculation/Graph semantics;
- Asset semantic identity and immutable semantic versions;
- exact implementation, Provider, Distribution, Catalog and Runtime Generation identities;
- Research Evidence, Qualification, Admission and Promotion authorities;
- immutable historical references, exact replay and no latest/fall-forward resolution;
- new-work-only Catalog/Runtime activation;
- `StrategyRevision` as the sole exact runtime Strategy identity; and
- distribution-based official/platform plugins and infrastructure components.

ADR 0116 and ADR 0117 remain the execution-generation and immutable-artifact contracts for any admitted executable materialization.
Their source Snapshot/artifact concepts may be satisfied by an exact database Revision/source fingerprint in a future implementation;
they do not require Git to be the production authoring Authority.

## Consequences

Private L3/L4 authoring becomes a first-class OnlyAlpha product capability with durable Draft/Revision recovery and one explicit
authoring Authority. Web and Agent can operate on the same canonical assets while Agents remain API-bound and never gain LIVE authority.

Runtime exactness is preserved because database source is never treated as executable authority: validation, adapter identity, Catalog
Generation and Runtime Generation remain explicit boundaries. Public examples can continue to prove the stable L3 API and L4
structured-definition contract without becoming private source mirrors.

The design intentionally adds future Product/API, persistence, validation and isolated execution work. It does not add tables, routes,
AST validators, sandboxes, loaders, Registry code, Search indexes, generation code or migration behavior here.

## Rejected alternatives

- Mandatory independent Git repository for every Private L3/L4 asset.
- One wheel/package per Private L3 as the mandatory authoring model.
- Direct `exec`/`eval` of database source inside an API or ordinary application process.
- Resolving the latest Private L3 Revision at runtime.
- Private L3 imports of unstable OnlyAlpha internal modules.
- An inheritance-heavy mutable Core base-class ABI for L3 V1.
- L3 API version ranges or silent API migration.
- A Python-source requirement for Private L4 V1.
- Agent direct SQL/PostgreSQL access as an authority path.
- Generation before reuse, composition and parameter checks.
- Search Projection as Factor Authority.
- Copying dynamic Research metrics into Factor Authority rows.
- Converting official or external platform plugins into database-native Private L3 assets.

## Deferred implementation questions

The following are intentionally deferred:

```text
exact PostgreSQL DDL/table names
migration numbering and compatibility windows
Product API route/DTO names and authorization details
Web Draft/Revision UX
AST/static policy allowlist implementation
validation/runtime sandbox mechanism
source materialization path and worker protocol
Factor Registry SQL/indexes and Provider Snapshot schema
FTS/JSONB/pgvector or other search projection design
exact exhaustive L3 API V1 primitive list and contract fingerprint construction
adapter class/module names
L3 Provider Snapshot and Catalog materialization details
L4 structured-definition schema additions beyond existing contracts
```

## Explicit invariant list

```text
Private L3 Authoring Authority != Git Repository
Private L3 Revision != Factor Semantic Version
Private L3 Source != Runtime Authority
Private L3 API Contract != L3 API Adapter Implementation
Same L3 API Version = Same Logical Contract Forever
Search Projection != Factor Authority
Factor Registry != Experiment Memory
Experiment Memory != Research Evidence
Similarity != Equality
Draft != Revision
Revision != Admission
Admission != Qualification
Catalog Generation != Runtime Generation
Current Runtime Compatibility != Historical Replay Compatibility
Latest != Authority
```

## Required proof direction for future implementation

Future implementation tasks must derive their Authority state space and proof matrix from this ADR plus the owning ADRs before freezing
schemas or code. They must distinguish applicability, completeness and exact equality; treat missing proof as incomplete rather than
non-match; and cover Draft/Revision, validation failure, Admission, Qualification, exact source/API/adapter/runtime binding, recovery,
historical replay and no-fall-forward mutations. No implementation task may claim this ADR's architecture is implemented merely because
the ADR is accepted.
