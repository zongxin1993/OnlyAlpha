# ADR 0127: Novelty and Experiment Memory Authority, Identity, Projection and Decision Contract

- Status: Accepted
- Date: 2026-09-14
- Related: ADR 0072, 0088, 0089, 0095, 0112, 0115–0126; `docs/agentic_alpha_discovery_architecture.md`; `docs/agent_factor_mining_work_program.md`
- Constitution Impact: NO

## Context and problem

B3.5 seeks to avoid repeated expensive Research and retain useful failure history. Today Search, Agent, Research, Statistics and
Qualification already have different durable authorities. Search provenance is not an Experiment Memory index (ADR 0120), a Search
Proposal is not a Candidate (ADR 0121), and a Research Run UUID is not an immutable scientific result (ADR 0089). An index that
stores a mutable `failed_factor` or treats similarity as equality would create a second authority. Conversely, an unrecorded
process-local novelty check cannot explain a historical suppression after the index is rebuilt.

The three questions are distinct: **semantic novelty != evaluation novelty != search-region novelty**. The same Factor graph can be
evaluated on another Dataset Snapshot. A single failed grid point does not establish a failed neighborhood. This proposal freezes
the authority, proof and recovery contract before any B3.5 implementation; it does not assert that current stores already offer a
complete cross-authority enumeration or a Novelty Gate.

## Decision and authority map

Memory is a **derived, disposable structured projection** over exact verified source facts. It owns only index layout, searchable
derived keys, completeness metadata and optional similarity retrieval metadata. A separate OnlyAlpha **Novelty Policy authority**
owns immutable policy revisions, and **Novelty Decision authority** owns immutable decision occurrences. Neither owns Research
results, scientific rejection, Search transitions or permission for LIVE. The Product application admits the decision and enforces
its read-to-act binding at Research command admission; the Agent cannot publish it.

| Fact | Sole owning authority / canonical identity | Source contract | B3.5 ownership / projection |
|---|---|---|---|
| Hypothesis / Search context | Search Provenance / Hypothesis and Experiment fingerprints | 0120 | reference/index only |
| Agent Brief, Session, model/tool result, Agent decision | Agent Provenance / each typed immutable fingerprint | 0123 | reference/index only |
| Search Experiment, Iteration Plan/Result and failure code | Search Provenance / distinct Experiment, Plan, Result fingerprints | 0120 | reference/index only |
| Symbolic Space, Proposal and ordered occurrence | Symbolic Search / Space, Proposal, Enumeration Result fingerprints | 0121 | reference/index only |
| Parameter Space, Policy, Proposal, Feedback/STOP | Parameter Search / distinct fingerprints and durable frontier | 0122 | reference/index only |
| Candidate in Research request | Research Specification Resolver / ADR 0095 Candidate fingerprint | 0088, 0095 | reference/index only |
| Calculation/Factor semantic graph and exact output | Calculation/Quant Asset / canonical Graph, definition/type/version and output identity | 0088, 0110–0115, 0121 | reference/index only |
| Catalog Generation | Quant Asset Catalog / exact generation fingerprint | 0112, 0115 | reference/index only |
| Dataset Snapshot | Dataset authority / Snapshot fingerprint | 0072 | reference/index only |
| Authoring Execution / Runtime Generation and work binding | generation admission / Runtime Generation ledger / their exact fingerprints and work ID | 0116, 0117, 0125–0126 | reference/index only |
| Research Specification, Run/Attempt and command receipt | Resolver / Specification fingerprint; Run authority / UUID4; Attempt/Receipt authorities / their native identities | 0088–0091, 0124–0125 | reference/index only |
| Calculation/Statistics results and scalar Evidence | their immutable Calculation/Statistics authorities / typed logical and result fingerprints | 0119 | reference/index only |
| Research Result and Candidate/Evidence membership | Result authority / Plan locator plus exact Result fingerprint | 0083, 0095, 0119 | reference/index only |
| Qualification Policy and PASS/FAIL Decision | Qualification / exact policy revision and Decision fingerprints | 0118–0119 | reference/index only |
| Private source admission / Promotion / StrategyRevision / LIVE | respective existing authorities / their exact identities | 0115, 0118, Constitution | no ownership; typed reference only |
| Historical operational failure / cancellation | owning Run/Attempt, Search or Agent occurrence / native ID and revision/result fingerprint | 0089–0090, 0120, 0123 | classified projection only |
| Novelty Policy Revision | new OnlyAlpha Novelty Policy authority / ID, positive version and content fingerprint | this proposal | **yes**, new formal fact |
| Novelty Decision occurrence | new OnlyAlpha Novelty Decision authority / command occurrence ID and immutable decision fingerprint | this proposal | **yes**, new formal fact |
| Source-cut/query witness, Memory index, region coverage, similarity matches | source-cut witness is decision-bound immutable provenance; other values are derived projection/query identities | this proposal | witness in Decision authority; index/coverage/matches non-authoritative |

ADR 0115's private authoring Experiment is not ADR 0120's Search Experiment. The Agent's Session/Decision is not the Novelty
Decision. A reference never transfers Authority. The Product Command Admission/Receipt remains the command identity and retry
authority (ADR 0124/0104); B3.5 adds neither a replacement receipt table nor a new Research Run identity.

## Identity domains and source facts versus projection

Semantic equivalence uses the **owning Calculation authority's canonical graph/definition and exact candidate node/output** (or an
admitted asset ID + semantic version with verified canonical content for registered L3), not an ADR 0095 Candidate fingerprint alone.
That Candidate fingerprint hashes the Specification, candidate calculation ID, assignment and Dataset-bound Calculation fingerprint;
it therefore identifies a candidate *in one Research request*. A Graph fingerprint alone is also insufficient when two distinct
outputs of the same graph are candidates. Normalization is only what the existing Calculation/Graph authority proves (including
supported parameter normalization and canonical graph equivalence); an algebraic, economic or textual equivalence that it does not
prove remains advisory, not exact. Cross-graph equivalence needs a separately versioned owning Calculation contract, not a Memory
alias. Existing Catalog capability reuse requires exact generation and registered asset/type/version/content proof.

The index may denormalize exact keys, ordered native locators, status classes, typed metric descriptors and even display values to
speed queries, but these are explicitly non-authoritative. A formal decision verifies the source through its exact reader and
records the source locator **and returned identity/revision**; a copied scalar is never independent Evidence. Do not persist a
parallel Factor status, Research Result, Qualification outcome or numeric-statistics authority. A cache may memoize index/query
work, but a cache hit alone proves neither a source fact nor completeness. Physical index rows, vector IDs and storage paths are
never scientific identities. Projections can be discarded without deleting any source truth.

## Semantic duplicate contract

An `EXACT_SEMANTIC_MATCH` requires exact verified Calculation/Graph and output identity, or the owning registered Factor's exact
admitted semantic identity; different surface text that normalizes to the *same authority-owned canonical identity* converges.
Same title, hypothesis statement, LLM verdict, graph shape without output, or embedding distance never suffices. A historical
Candidate may be retrieved by its ADR 0095 fingerprint, but cross-context semantic lookup resolves its authoritative graph/output
closure. A candidate that has not been resolved/verified is `UNPROVEN`, not `NOVEL`. A semantic match alone cannot block a new
scientific evaluation.

## Evaluation duplicate and comparability contract

An exact reusable evaluation is proven through a **resolved scientific evaluation closure**, not a second invented Candidate ID:

1. Exact semantic graph/output and the normal Resolver's Candidate binding; exact Specification V2 (including publication and
   signal membership), resolved Workload/Result Plan, Dataset Snapshot (including the specified Universe/time/adjustment/quality
   context), all Target/Statistics definitions, selectors and fixed evaluation contract where applicable.
2. Exact Catalog Generation and verified Calculation implementation/producer Evidence; exact authoring generation when applicable,
   exact bound Runtime Generation and derived Research work binding when Search-produced. Different generation identities are not
   silently interchangeable: reuse across them requires an existing explicit equivalence/admission proof applicable to that
   Evidence, otherwise no hard reuse. Search Algorithm/Policy/Experiment lineage stays occurrence provenance, not automatically
   Research semantics, but a policy whose interpretation depends on it must bind the exact Experiment, policy, budget and exposure
   context as additional comparability constraints.
3. An authoritative terminal Research Run/Result relation (or an exactly verified immutable Result with complete provenance under
   an expressly admitted reuse policy), its Plan **locator and Result identity**, unique Candidate membership, exact Statistics
   logical/result references, typed valid Evidence and required Artifact/producer provenance. A failed, cancelled, running or
   ambiguous Run is not a completed evaluation; an immutable Result published before a failed Artifact step is not silently treated
   as an accepted completed Product Run.

`EVALUATION_EXACT` is a proved predicate over these exact references and versioned policy, not a new global Research semantic
fingerprint. Same Graph with Dataset D1 and D2 is a semantic match but not an evaluation match. Different Specification publication,
Statistics, Target, Dataset, execution bytes or unresolved run state cannot be collapsed by a matching metric or similar output.
Research Result/Statistics Stores retain their own reuse semantics; the Novelty Gate cannot rewrite them. An exact match permits
`REUSE` only under the policy's explicit evidence-sufficiency rule and with exact Result/Run references; a new independent Run may
still be legitimate when the policy requires a repeat or new provenance. A historical Qualification REJECT remains a policy outcome,
not a universal scientific impossibility.

## Parameter-region history contract

Coverage is a derived set of **observed normalized assignments**, not a new Candidate or Research identity. The region query binds
the exact Search Space kind/schema/fingerprint, canonical dimension targets and values normalized by the owning Calculation parameter
schema, the exact Catalog and Dataset, Evaluation Contract/Specification context, Search Policy and Algorithm identity/version,
budget and, when outcome-sensitive, exact execution generation and scientific Evidence closure. For ADR 0122 finite spaces the
canonical grid ordinal and immutable Proposal/Plan/Result/Feedback references identify observed cells; for ADR 0121 use its
Enumeration Result and contiguous Plan ordinals. A broader geometric region has no inferred coverage until a separately versioned
region grammar and proof rule is admitted.

Each cell is `UNATTEMPTED`, `PLANNED`, `ATTEMPTED_INCOMPLETE`, `OPERATIONAL_FAILURE`, `COMPLETED_EVIDENCE` or
`EXPLICITLY_EXCLUDED` as a *projection* of the owning durable occurrences; this vocabulary cannot change the Search controller's
terminal states or budgets. Complete coverage requires an exact finite member set and an exact terminal, comparable outcome for
**every** required cell, plus authoritative completion/exhaustion proof and no unresolved Run/receipt. A durable STOP for budget or
convergence covers only its recorded prefix, not the unvisited grid. Operational failure, cancelled work, missing Evidence and a
single tested point never certify a neighboring region. Different Dataset/Evaluation/Policy context remains retrievable history,
but cannot hard-suppress without a separately admitted formal comparability proof; default is no cross-context suppression.

## Failure knowledge taxonomy and redundancy boundary

| Source outcome | Projected interpretation | Hard scientific suppression? |
|---|---|---|
| Run/Attempt execution, tool/provider or model failure; UNKNOWN submission | operational history / reconcile first | no |
| Invalid proposal/candidate, capability gap, policy-blocked input | exact scoped invalidity or missing capability under its original version | only identical versioned invalid input/policy if formally proved; never negative alpha Evidence |
| Budget exhaustion, Search STOP, cancellation, incomplete/recovery corruption | bounded workflow observation or fail-closed condition | no inference about unvisited hypotheses |
| Completed Research with weak/invalid typed Evidence | exact context-bound scientific observation, including explicit invalid scalar status | only a policy-proved same-evaluation reuse/suppression; not a family-wide hypothesis failure |
| Qualification REJECT | exact subject + policy + Evidence relation | only same exact qualification context; not a permanent Factor status |
| Formal factor-to-factor correlation/incremental evidence where supported | typed Evidence reference | only according to a separately versioned policy; never recalculated by Memory |

Memory retrieves ADR 0119's Factor-to-Factor Statistics and exact Candidate/Result membership; it never computes IC, Sharpe,
correlation, incremental contribution or a new redundancy score. Missing a requested authoritative metric is
`EVIDENCE_CAPABILITY_GAP`, not a plausible computed substitute. “Known failed hypothesis” is a search facet with explicit source
kind, exact context and policy, never a generalized claim that a prose hypothesis has been disproven.

## Near-duplicate retrieval and context tiers

Near duplicates are **advisory candidates for exact follow-up verification**. The query distinguishes `RETRIEVABLE` (relevant
history), `COMPARABLE` (exact verified context), `HARD_REUSE_ELIGIBLE` / `HARD_SUPPRESSION_ELIGIBLE` (policy-proven), and
`ADVISORY_SIMILAR` (approximate). An embedding or LLM may populate only the last class. Its response binds retrieval algorithm,
model and version/content fingerprint if used, input representation version, index build revision/source cut, threshold policy,
ordered match IDs/scores and deterministic tie-break `(score, canonical source kind, native locator, source identity)`; if a backend
cannot reproduce ordering, retain its exact decision-time response as advisory provenance rather than claiming deterministic
recomputation. Similarity never determines exact equality or a hard block. If optional semantic search is down, report
`ADVISORY_UNAVAILABLE`, not “zero matches”; an exact-only policy can still proceed if its mandatory proof is complete.

## Novelty Decision, decision-time evidence and read-to-act contract

The proposed formal Decision is a **durable immutable occurrence** sealed by the Product/application evaluator. It binds its own
schema/version and fingerprint, Product Command ID and canonical intent fingerprint, subject type and exact resolved input
references, immutable Policy ID/version/content fingerprint, outcome (`ADMIT`, `REUSE`, `SUPPRESS`, `REVIEW`, `FAIL_CLOSED`), typed
reason codes, exact ordered proof references, source-cut/query-witness identity, and optional advisory-result reference and status.
Operational actor/time may be separately retained as audit provenance, never as semantic equality. UUID4 Product Command ID is an
occurrence/retry identity; the Decision fingerprint is content identity. They do not become Candidate/Research/Qualification IDs.
One Command ID with the same intent must converge to one exact Decision; changed intent conflicts. A Decision cannot be authored
directly by an Agent, HTTP handler or database client.

The decision-time **immutable query witness** is part of the Decision authority, not a snapshot of copied Research truth. It
records the exact canonical query/predicate and policy, deterministic ordered positive match references with their verified
identities/revisions, reason-driving typed facts, the complete source-cut manifest (source family, source schema, frontier,
enumeration/completeness proof and projection algorithm/schema versions), and explicit unavailable/partial families. Exact absence
is asserted only when the owning families prove a closed cut. A mere timestamp, row count, current index version, or SQL isolation
snapshot without durable source-frontier proof is insufficient. The witness is put-once, exact-loadable and independently
verifiable from retained authoritative facts; historical replay evaluates the frozen policy on the frozen witness and compares
the complete Decision, never requeries today's index. If an old source schema/reader or source fact is unavailable, historical
inspection reports `HISTORICAL_PROOF_UNAVAILABLE` rather than silently reinterpreting or fabricating it.

Existing independent stores do not yet guarantee a global ordered frontier. B3.5.1 must establish a versioned, source-owned
enumeration/frontier or equivalent **certified closed source cut** for each mandatory fact family, with no omitted late-arriving
records before the cut. It must test the cross-store snapshot/barrier and retention contract; Memory cannot self-issue a
completeness certificate by counting its own rows. Until proven, absence-based `ADMIT`/`SUPPRESS` cannot be formalized, and a
mandatory gate returns `FAIL_CLOSED`. Positive exact matches may be reported only after each required source is verified. A
decision cut is historical evidence, not permission to ignore concurrent new facts: admission of expensive Research must bind
the same decision/subject/intent and guard against a newer conflicting exact evaluation or in-flight command at an owning
admission/receipt boundary. Concurrent same-subject submissions converge/reconcile or fail closed; no check-then-submit race,
second Run identity or blind retry. `REVIEW` requires an explicit new authorized decision/intent before work; it is not automatic
Agent override. `SUPPRESS` and `REUSE` do not alter Research/Qualification history or grant progression.

## Projection rebuild, freshness, recovery and failure semantics

Projection algorithm version + source-cut manifest + canonical ordered verified facts produce the same **logical** keys, membership
and statuses, regardless of ingestion/discovery order or physical index technology. Idempotent `(source kind, native locator,
source identity/revision)` ingestion detects conflicts; duplicate source replay creates no duplicate logical record. Out-of-order
discovery does not advance a complete frontier across gaps. Incremental rebuild checkpoints only verified contiguous source
frontiers. Fresh rebuild constructs a separate revision, verifies full source closure and logical digest, then atomically switches
new queries; crash/partial write keeps the old verified revision or blocks, never exposes a half-built one. Corrupt rows/frontier
quarantine the projection and rebuild from sources; **never** delete or repair authoritative source facts. Index schema or
algorithm upgrades create a new revision and retain historical Decision/witness readers and exact referenced facts; no rewrite of
old decisions. Physical cache can be recreated after loss.

| Condition | Mandatory novelty proof | Optional advisory query |
|---|---|---|
| Projection lag, incomplete result, gap or unknown source frontier | fail closed; no empty-result-as-novel | disclose partial/unavailable |
| Projection corruption / identity conflict | quarantine/rebuild; fail closed | unavailable |
| Source Authority missing/corrupt or exact reader unavailable | fail closed, preserve existing history | no false negative |
| Similarity backend down or model mismatch | exact gate can continue if policy does not require it | `ADVISORY_UNAVAILABLE` |
| Decision commit/response UNKNOWN, restart or concurrent command | exact command/receipt and Decision reconciliation before action | no blind new occurrence |

Fail-closed concerns *new expensive work*, not observation, reconciliation or exact history reads. A projected `NOVEL` status without
closed-cut proof is forbidden. An incomplete Search/Run may be exposed as incomplete and must be reconciled by its own Authority,
not reclassified as failed alpha.

## Versioning, compatibility, API, placement and security

Version independently: source-reader/query contract and typed cursor; Memory schema and projector algorithm; source-cut witness;
immutable Novelty Policy ID/version/content; Decision schema; similarity representation/model/index algorithm/threshold when used.
Policy/content drift requires a new revision; historical V1 bytes, fingerprints and outcome meanings remain exact-loadable under
their original readers. Unknown schemas or model identities fail closed; there is no `latest` policy or implicit migration of
historical Decisions. A new query can use a new projection version, but cannot retroactively change an old witness. Backward and
forward reader windows, retained source artifacts and any persistence migration must be explicitly specified and tested in the
implementation task; this ADR changes no existing public schema, OpenAPI, Result, Run or persistent bytes.

Future versioned Product API operations are conceptually exact semantic lookup, experiment/evidence history query, parameter
coverage query, advisory near-duplicate query, Novelty evaluation command, and exact Decision query. Commands use canonical
Product idempotency/receipt semantics and only owning application services may seal Decisions. Queries carry typed exact source
locators and versioned, source-cut-bound cursors; growing history is a mutable observation requiring a new Agent Tool occurrence
(ADR 0123/0124), while an exact Decision/witness is an immutable exact query. Product responses expose status, source-cut and
proof completeness, never raw index-table authority. Agent uses only the formal API—no PostgreSQL, JSON/Parquet paths, Core
object control, worker IPC or private mutable memory. Least privilege excludes policy administration, suppression override,
Promotion, admission and LIVE. Validate query input, tenant/user scope, source-reference access and size/cost bounds; historical
provenance can contain sensitive hypothesis/model/tool context. Embedding input must not export secrets or private source without
explicit authorized adapter/policy. No new independent microservice is justified by this design: canonical policy/decision and
query ports belong at the Research application/Product boundary, the disposable index alongside the Product query capability;
deployment separation requires a later fault/lifecycle/resource decision, never placement inside Agent-owned truth storage.

## External engineering evidence

Relevant advisory references: `docs/engineering/reference_registry.md` (RD-Agent, Vibe-Trading, Qlib, AlphaGen, AlphaEvo,
AlphaSift, research-integrity family), `docs/engineering/open_source_engineering_evidence.md`, and
`docs/engineering/failure_patterns/FP-RUNTIME-001-generation-contamination-and-fallback.md`. Bounded upstream issue reports:
[RD-Agent #1380](https://github.com/microsoft/RD-Agent/issues/1380) reports traces present on disk but empty after UI restart;
[RD-Agent #1276](https://github.com/microsoft/RD-Agent/issues/1276) reports a missing `qrun` executable as experiment failure;
[Qlib #1930](https://github.com/microsoft/qlib/issues/1930) reports indistinguishable backtest results despite model/parameter
changes. These are **issue reports, not confirmed OnlyAlpha defects or imported root-cause findings**.

Applicable lesson/failure pattern: a historical view must be reconstructible from durable exact facts; operational feedback must
not become negative scientific Evidence; a display/experiment name cannot prove a unique evaluation context. OnlyAlpha tests below
require fresh-process historical query after projection rebuild, explicit operational failure taxonomy and distinct Dataset/model/
generation closures. Rejected external approaches: mutable registries/status, session-local trace as truth, another project's
evaluator or retry loop, and vector retrieval as canonical identity. No external project owns an OnlyAlpha Authority.

## Rejected alternatives

- One generic vector DB as Agent memory: similarity cannot prove canonical identity, complete absence or scientific truth.
- Agent-owned mutable factor/result/failed-status DB: second truth and ambiguous recovery, outside the Product API.
- Today's index as historical Decision truth: new facts or rebuild change the old explanation.
- Same Factor/Graph implies same evaluation: Dataset, Target, Statistics, Specification and execution provenance can differ.
- Any failure implies hypothesis failed: missing tool/timeout/cancellation are operational, not negative alpha Evidence.
- LLM opinion or embedding threshold implies exact duplication: neither owns Calculation canonical semantics.
- Memory computes IC/Sharpe/correlation/incremental contribution: duplicates Research Statistics authority.
- Mutable projection row count, wall-clock freshness or best-effort scan as completeness certificate: cannot prove absence.
- A new Memory microservice or a new Candidate/Run/Receipt store by default: no independent authority/fault domain warrants one.

## Consequences and migration / implementation sequencing

This adds a proposed, independently versioned Policy/Decision fact boundary, not a second Research store. The cost is explicit
source enumeration/frontier and atomic read-to-act proof before absence-based suppression can be enabled. Existing ADR 0120–0126
facts and Product/Research/Statistics/Qualification schemas are unchanged by this proposal. No historical migration is performed.

After owner review and explicit ADR acceptance, B3.5.1 may design and implement source-owned closed-cut readers, structured
projection, rebuild/recovery, exact history queries and deterministic tests. Subsequent separately authorized work may add
Policy/Decision persistence, versioned Product API and guarded Novelty Gate; optional similarity is last and advisory. Each phase
must prove compatibility, migrations, public-example/private-asset impact where a public L3 contract actually changes, and
read-to-act concurrency at its stable boundary. Literature RAG/paper ingestion and all B3.6 L3 code generation, admission,
Catalog activation and automatic PRs are out of scope. This ADR implements no tables, migrations, indexer, API route, Agent tool,
statistics, Gate or B3.5.1 code.

## Acceptance / design gate for subsequent implementation

Deterministic offline tests must include: duplicate ingestion; crash mid-rebuild and same logical digest after restart; stale,
partial, corrupt and source-unavailable fail-closed; optional semantic backend down without false negative; same semantic output
with different Dataset not evaluation duplicate; operational failure not scientific rejection; historical Decision exact replay after
index upgrade/new records; embedding false positive not exact equality; canonical equivalent surface forms converge only through
the owning Graph authority; partially explored parameter grid not complete; exact Result locator/identity and unique Candidate
membership; differing execution generations without formal equivalence not reused; two concurrent same-evaluation submissions
converge or fail before duplicate Run admission; response loss reconciles the same command; source-cut gaps/late discovery block
absence proof. Use deterministic barriers/fault injection, not sleep or live services. Acceptance additionally checks bounded
source retention, API least privilege and historical reader compatibility. **No implementation starts solely because this ADR is
PROPOSED.**

## Constitution consistency

Uniqueness and Single Authority follow from typed exact source references and separate Policy/Decision identity; Determinism,
Reproducibility and Traceability follow from frozen inputs and query witness; Fail-Closed and Recoverability follow from certified
source cuts, source verification and rebuild; explicit Product/Agent and immutable/variable boundaries are preserved. This
proposal changes neither Trading Kernel nor LIVE Authority and requires no Constitution change.
