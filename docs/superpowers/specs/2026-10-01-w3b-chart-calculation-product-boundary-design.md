# Chart Calculation Product Boundary and Readiness

Status: **Proposed design for owner review**, not an Accepted ADR or implementation authorization.

## 1. Executive decision

Recommend a dedicated `CreateChartCalculationV1` Product Command in the Research namespace, backed by a small durable
input-preparation operation and an internally compiled calculation-only Research Specification V3. Reuse the existing Research Run,
exact Runtime Generation hosting, finite Engine lifecycle, Dataset, Calculation, Result and Artifact authorities. Do not extend
Research Definition V1, expose graph authoring to the chart, or evaluate in HTTP/Web.

The first supported selection is `onlyalpha.indicator.sma@1`, one instrument, **PROVIDER_NATIVE 15m**, already closed and sealed Bars,
server batch execution, output `value`. Require one exact sealed Revision whose scope covers the entire planned input range exactly.
Do not assume that several chart pages or several independently sealed Revisions constitute that Revision. No implicit acquisition.

Readiness is per output point, produced by the registered Calculation backend during execution, persisted in versioned Calculation
Result V2, composed by explicitly versioned Plan/Result V4 and copied into a new `RESEARCH_CALCULATION_V2` Artifact profile.
Query projects stored evidence; it never reconstructs
warmup. Existing numeric semantics and semantic fingerprints remain unchanged. Old Results/profiles do not acquire invented readiness.

Two architecture approvals are needed before implementation: typed calculation-only Run admission outside scientific Novelty
Read-to-Act, and the readiness-bearing publication versions. Sections 10 and 17 give the exact recommendation. This document neither
changes ADR 0128/0136 nor makes the existing production submission service ungated.

## 2. Current implementation truth

The table and test description below preserve the **2026-10-01 design-time inspection**, not a current absence claim about internal
readiness. ADR 0137 and `docs/indicator.md` describe the subsequently implemented atomic readiness execution, Calculation Result V2,
Execution Evidence V2 and Job Plan V2 foundation. Its tests prove internal point readiness and recovery, not chart Product admission,
authorization, Specification V3, Result V4, Artifact V2 or a Web indicator workflow. The future Product admission amendments in
sections 7–8 consume that foundation; the remaining chart contracts are still proposed.

The inspected implementation is the calculation-only publication foundation, not a chart Product workflow:

| Area | Actual capability and boundary |
|---|---|
| Result | `research/result/identity.py`, `plan.py`, `result.py`, `assembler.py`, `result_store.py`: Plan/Result V3 has exact Dataset, nonempty Calculation/Graph and series membership; forbids Statistics/Candidate/Signal. Assembly and verified load traverse upstream relations. |
| Artifact | `artifact/scientific_model.py`, `scientific_materializer.py`, `scientific_store.py`: `RESEARCH_CALCULATION_V1`, Artifact schema 1/Result schema 3, portable market/variable/graph rows; public calculation publication calls the canonical materializer rather than accepting caller-authored rows. No readiness fields. |
| Runtime | `research/workload.py`, `runtime/research/factory.py`, `runtime.py`: V3 closure, finite RESEARCH Jobs, verified Result and Artifact publication, exact re-entry; no operational chart admission. Runtime control signals escape failure mapping. |
| Authoring | `definition/model.py:OnlyResearchDefinition` requires calculations, targets and Statistics. `definition/resolver.py` resolves Dataset plus evaluation authoring; it is not a chart compiler. |
| Specification | `specification/model.py:OnlyResearchSpecification` accepts V1/V2, requires Statistics; V2 evidence requires a Candidate calculation. V3 Result support does not imply V3 Specification support. |
| Product | `application/product_boundary.py` dispatches typed commands through `kernel/command.py` mutation readiness. Run HTTP uses `/api/v2/research/runs`, `OnlyProductCommandId`, 202, receipt and Location. There is no chart-calculation command. |
| Production Run admission | `research/command/service.py:submit_research_run` and HTTP `main.py` require Novelty Decision/Memory/Runtime Generation authorities. `_OnlyHistoricalResearchRunSeeder` and `allow_legacy_ungated` are explicitly non-production. ADR 0128 does not authorize an empty subject set as ADMIT. |
| Materialization | `dataset/market_data_materializer.py:OnlySealedMarketDataDatasetMaterializer` verifies Revision/Seal, reads exact physical facts, validates Bars and commits Snapshot plus lineage. Its plan has one Revision per instrument, not arbitrary page composition. |
| Market selection | `application/market_data_product.py:resolve_runtime`, `_plan`, `_scope` resolve Integration binding, plugin-owned source identity, capabilities and construction. These latter helpers are private; a reusable typed selection method is needed, not calls into private methods from HTTP. |
| Exact reads | `market_data/durable/revision.py:resolve_latest`, `resolve_with_seal`, `read_exact` validate scope, manifest, Seal, segments and physical proofs. Metadata-only Seal resolution is not the full fact proof. |
| Numeric execution | `calculation/definition.py` declares warmup/missing/numeric semantics. `research/calculation/execution.py` calls backend `execute`, validates output arrays and produces module-sealed execution proof. Result currently stores values, not backend readiness. |
| First backend | Plugin `registration.py` declares SMA period >=1/default 20, CLOSE/VOLUME/default CLOSE, nullable DECIMAL `value`, EVENT_TIME, quantum `0.000000000001`, FAIL missing policy, PARTIAL_WINDOW initialization and PARTIAL pre-ready output. `research.py:_standard` returns partial means before full window. |
| Query | `query/model.py`, `service.py:get_variable_series` return typed numeric points without readiness. `list_published_series` exists. `get_candidate_graph` requires Candidate ownership, absent in Result V3. |
| HTTP/client | `research/routes.py`, `schema.py`, `run_schema.py` and Web `api/research/schemas.ts`, `contract.test.ts` are explicit versioned, strict transport boundaries. Adding fields is not automatically compatible with strict Zod. |

Existing calculation-publication tests demonstrate internal Engine execution, exact references, portable Artifact numeric query,
input immutability, failed publication/re-entry, cancellation and corruption rejection. They do **not** demonstrate chart admission,
point readiness, authorization or a Web indicator path. Query tests and HTTP/client contract tests remain the nearest consumer
boundaries for the proposed changes. This design makes no aggregate CI or delivery claim.

## 3. User goal and explicit non-goals

An operator chooses SMA from the registered catalog on the current chart, inspects official parameter definitions, submits normalized
parameters and an exact closed display range, receives a recoverable operation, observes its Run and displays the verified current-
context output. Agent clients may use the same authorized Research API; they do not get internal Python or database access.

Reference interaction: TradingView-style picker, parameter editing and indicator visibility only. Renderer remains behind ADR 0094.
Visible states are admitting/unknown, preparing input, queued, running, complete, failed, cancellation requested/cancelled after Run
admission, and explicit unsupported/unavailable evidence. Partial numeric observations are not ready observations.

Non-goals: Indicator UI implementation in this design, multi-Revision composition, Derived bars including 7m, performance budgets,
preview/incremental computation, automatic provider fetching, arbitrary code/custom indicators, Factor mining, general Research
authoring redesign, Strategy/Freeze/Qualification/Trading/LIVE, server-side workspace sessions, style/pane persistence or new topology.

## 4. Options A/B/C and trade-offs

| Option | Benefit | Cost / authority problem | Decision |
|---|---|---|---|
| A: calculation-only Definition/Specification via existing Run POST | Reuses Run admission and familiar operational queries | Specification evolution alone leaves Web supplying a Snapshot and graph template. Definition evolution still needs durable source-to-Snapshot preparation. Existing Novelty gate cannot authorize a calculation-only intent. Changes general authoring unnecessarily. | Reuse Specification internally; do not extend Definition V1 or use generic POST for chart admission. |
| B: chart Product Command + internal Specification | Web sends source/range/selection, not computation internals; durable intent precedes input writes; explicit retry and source proof | Requires a pre-Run operation authority, typed Run admission, fenced preparation and versioned transport. These are needed for the actual crash windows, not for hypothetical workspaces. | Recommend, with the explicit approvals in section 17. |
| C: direct HTTP/browser calculation | Superficially short | HTTP evaluator bypasses Engine; browser SMA is a second numeric authority; renderer pages are not a Dataset and stream close is not a Seal. No exact execution/provenance/re-entry closure. | Reject. |

Do not add a synchronous materialize-and-submit handler with only a final receipt: a crash between file publication and Run creation
would lose the user intent and selected input. Do not create a generic workflow framework. The new operation exists only until the
single Research Run relation is committed, then delegates lifecycle entirely to that Run.

## 5. Chosen architecture

```text
Web/authorized Agent
  -> versioned chart-calculation HTTP DTO
  -> Product dispatcher / mutation readiness
  -> durable ChartCalculation intent + Product admission/receipt
  -> fenced input-preparation worker
       -> exact Runtime Generation/Catalog binding
       -> Integration/source/construction resolution
       -> immutable input-selection pin
       -> verified sealed Market Data -> existing Dataset materializer + lineage
       -> canonical Specification V3 compiler
       -> typed calculation-publication Run admission
  -> existing fenced Research worker -> exact generation host -> Engine RESEARCH
       -> numeric + readiness execution -> Calculation Result V2 / Execution Evidence
       -> readiness-bearing Result V4 -> RESEARCH_CALCULATION_V2 -> final verified publication
  -> read-only operation/Run projection
  -> Artifact-only catalog/graph/readiness series -> Web presentation
```

Application semantics belong in `src/onlyalpha/application`; Calculation/Research contracts in their existing canonical areas;
PostgreSQL adapters under existing persistence; HTTP DTOs/routes in `packages/onlyalpha-http-server`; plugin execution semantics in
`plugs/onlyalpha-plugin-indicators`. Reuse the existing worker hosting/lifecycle and explicit ports; add no plugin or deployment component.
Wire communication across nodes stays versioned. No consumer directly discovers another component's database rows as an integration API.

## 6. Authority / component table

| Component | Owns / does not own | Input -> output | Identity / persistence | Failure semantics / lifecycle |
|---|---|---|---|---|
| Chart Product Command | Exact admitted user intent and pre-Run relations; not numeric, market or Run truth | Source reference + range + registered selection -> operation | Global Product Command UUID4; canonical intent fingerprint; PostgreSQL immutable intent, receipt and fenced preparation events | Pre-admission rejection or committed ADMITTED; ambiguous commit = effect unknown. Preparation ends on linked Run or durable failure. |
| Market selection | Proven source/construction and exact Revision selection; not new market facts | Exact Integration reference + instrument/semantic/planned range -> scope and Revision/Seal pin | Existing Integration/binding/source, construction, scope and Revision/Seal identities; pin belongs to operation relation | Disabled/mismatched source, incomplete coverage or unavailable proof cannot become empty input. No provider session/fetch. |
| Dataset Authority | Immutable normalized input and materialization lineage; not progress | Frozen one-Revision plan -> Snapshot + materialization relation | Existing Snapshot fingerprint, `OnlyDatasetMaterialization` ID; existing files/lineage store | Canonical producer only; commit/re-entry verified, corruption never rebuilt over. |
| Compiler | Canonical registered intent -> resolved Calculation graph/publication; not formula evaluation | Snapshot + frozen exact Catalog + type/parameters/output -> Specification V3/workload | Specification fingerprint, Graph/node fingerprints; canonical Specification persisted with Run admission | Wrong type/backend/output/closure fails before queueing. No scientific Candidate or dummy Target. |
| Research Run admission | One queued Run and its exact operational origin/execution binding; not preparation progress | Verified operation + materialization + Specification -> one Run | Run UUID4, admission evidence, Runtime Work binding; existing PostgreSQL Run store with new typed origin relation | Atomic relation/queue commit; unknown is reconciled by exact ID. Production legacy seeder forbidden. |
| Calculation / Result / Artifact | Calculation owns numbers/readiness; Result owns members; Artifact owns portable projection; none owns user intent | Engine execution -> immutable publications | Calculation semantic/Result IDs, readiness-bearing content, Result V4, Artifact V2 content ID; existing immutable store families | Verified reuse or fail closed; final success requires all relevant proof. |
| Query | Read-only projections; not completion inference, warmup, acquisition or evaluation | Operation/Run ID or exact Result/profile/Artifact/member -> DTO | Exact selectors/cursors; no scientific persistence or browser session | Missing, wrong-profile, not-complete and corrupt/unavailable remain distinct. |
| Future Web | Display instance, incarnation, style and request generation; not any Authority above | DTO -> overlay/pane/status | Browser-only display identity | Reject stale responses; hiding/removing detaches presentation without restarting price Stream. |

## 7. Command request / response

Namespace: **Research**, because this creates finite calculation publication, not a market acquisition or persisted workspace.

```text
POST /api/v2/research/chart-calculations/commands
operationId: create_chart_calculation_command_v1
Idempotency-Key: canonical UUID4 (required OnlyProductCommandId)
Content-Type: application/json
```

Request DTO `ChartCalculationRequestV1`, exact fields:

```json
{
  "schema_version": 1,
  "source_reference": {
    "integration_id": "00000000-0000-4000-8000-000000000001",
    "integration_revision_fingerprint": "<lowercase-sha256>",
    "expected_type_id": "<registered-integration-type-id>"
  },
  "instrument_id": "<canonical-instrument-id>",
  "bar_semantic": {
    "schema_version": 2,
    "formation": {
      "schema_version": 1,
      "kind": "FIXED_DURATION",
      "window_minutes": 15,
      "stride_minutes": 15,
      "alignment": "SESSION_START"
    },
    "price_type": "LAST",
    "adjustment_policy": "RAW"
  },
  "display_range": {"start_ns": "<canonical-nonnegative-int64-text>", "end_ns": "<canonical-nonnegative-int64-text>"},
  "calculation": {
    "kind": "INDICATOR",
    "type_id": "onlyalpha.indicator.sma",
    "semantic_version": "1",
    "parameters": {"period": 20, "price_field": "CLOSE"},
    "output_name": "value"
  }
}
```

Angle-bracket strings illustrate values, not accepted literals. Use the existing `OnlyBarSemantic.to_dict()` V2 formation shape,
not the obsolete kind/step/basis shape or a display string `15m`. `expected_type_id` is required here; no secret/config/provider payload.
Bounds must fit nonnegative int64 and exact Dataset datetime precision (microsecond alignment), including planned warmup start.
Range is UTC half-open Bar support
`[start,end)`; returned Bar event times satisfy `start < ts_event_ns <= end`. See section 9 for precise planning.

Parameters object is required; omitted period/price_field within it receive registered defaults, and price_field is normalized by the
registered uppercase rule. No extra parameters, fractional/bool period or coercion from arbitrary text. Normalization uses the verified
registered contract; repeat recovery uses the originally admitted normalized intent, not the current catalog. No frontend-only fields
are accepted. The canonical intent hashes schema + exact source reference + instrument + semantic + display range + normalized selection.
The Product command fingerprint includes command kind and this intent. Command ID, audit time and display style are not in that hash.

One explicit command creates one operation. `operation_id = command_id` is the client-supplied Product Command / Idempotency-Key UUID4.
`reserved_run_id` is an **independent server-generated `OnlyResearchRunId`**, selected and durably stored during initial T1 admission.
`runtime_work_id = reserved_run_id.value`, never the operation ID. A committed operation→Run relation, not equal UUID text, proves ownership.
An unrelated Run whose ID equals the client's command UUID does not collide with this Product Command. Reserved Run-ID collisions are
resolved during T1 admission by generating another independent Run ID; retries reuse the committed reservation, and T4 cannot select a new ID.
The receipt outcome kind is newly
`CHART_CALCULATION_OPERATION`; command kind `CREATE_CHART_CALCULATION`. They extend the existing global receipt domain, not a parallel
receipt system. Same ID under a different command kind conflicts globally.

The first response is **202 after intent/receipt/operation commit**, not after calculation completion. All successful POST replays use
202, even if the operation later completed. Headers: `Location: /api/v2/research/chart-calculations/{operation_id}` and exact key echo.
Response `ChartCalculationOperationV1` has these fields (unknown references are explicit null):

```text
schema_version=1, operation_id, product_command_id, intent_fingerprint,
submission_disposition=CREATED|REUSED, preparation_revision (integer text),
state, accepted_at (UTC ISO), intent (normalized ChartCalculationRequestV1),
input_selection_ref|null, materialization_ref|null, dataset_snapshot_fingerprint|null,
specification_fingerprint|null, run_id|null, run_revision|null, run_state|null,
research_result_fingerprint|null, artifact_profile|null, artifact_content_fingerprint|null,
failure|null
```

`failure` shape: `{phase,code,detail,recovery_class}`; details are sanitized. When complete, profile is exactly
`RESEARCH_CALCULATION_V2`. `run_id` is null until the authoritative queue relation commits, not the reserved ID. Scientific identity
is still Snapshot+Graph+RESEARCH, not intent or operation ID. Two commands may share verified immutable outputs, but have distinct
operation/Run occurrences. Identical numeric values alone do not prove reuse eligibility.

An unknown HTTP response is not FAILED. GET the same operation ID or retry exactly the same POST/key; never generate a fresh key to
resolve ambiguity. A definitive body/key conflict is 409 and never authorizes changing the existing operation.

### Exact Catalog readiness admission prerequisite

**W3-C2-CATALOG-READINESS-CAPABILITY:** Before Product admission, a versioned exact Catalog capability projection must advertise readiness
V1 for the exact `type_id + semantic_version + RESEARCH backend` in the selected immutable Catalog Generation. Persist that exact
capability/generation witness with the admitted operation and use it for parameter normalization and later generation hosting.
Matching POST retries return the existing receipt/operation before consulting a newer Catalog. Unsupported/missing capability rejects new
readiness requests; it is not permission to execute a numeric-only backend.

Runtime registration `readiness_contract_versions` alone is not public Product proof. Provider version or implementation fingerprint alone
is not a client-readable readiness capability contract. W3-C2 must version this Catalog projection explicitly, without silently redefining
legacy capability semantics; this design amendment does not implement a Catalog schema or grant admission authority.

W3-C2 consumes the internal readiness foundation documented in `docs/indicator.md` and accepted by ADR 0137. It must not reimplement
readiness, evaluate in HTTP/Web, mint Result/Evidence from public read models, or use V1 fallback for Job Plan V2. The future chart Product
contracts below remain proposed; internal publication is not evidence that chart admission, Result V4 or Artifact V2 already exists.

`GET /api/v2/research/chart-calculations/{operation_id}/input-selection` exposes the immutable pinned selection and materialization
relation described in section 9, with exact owner/intent/reference checks. Before the pin exists it returns 409
`CHART_INPUT_NOT_SELECTED`, not an empty proof. This is a stored operational-provenance read, not a fresh source selection or fact query.

## 8. Durable state machine and transaction boundaries

### 8.1 Minimum new authority

An existing Product Admission stores a fingerprint, not a recoverable source/range/selection payload. A Receipt stores an outcome
reference, not a pre-Run lifecycle. A Run requires an already resolved Snapshot/Specification. Therefore introduce one **ChartCalculation
input-preparation authority**, not another Run scheduler: immutable canonical intent, optional frozen execution/input selection,
materialization/Specification/Run relations, durable failure, revision and fenced ownership. Use PostgreSQL business-shaped ports,
CAS/transaction locks and append-only stage evidence; operational projections may be rebuilt from those facts.

Persistent preparation states are only `ADMITTED`, `MATERIALIZING_INPUT`, `RUN_LINKED`, `FAILED`. Once RUN_LINKED, never keep a mutable
copy of Run status. The public state derives from the exact relation plus a verified Run read:

| Public state | Mandatory authoritative witness | Forbidden inference |
|---|---|---|
| ADMITTED | Intent + global admission + receipt + operation committed; no selected input yet | Does not prove source coverage or queued work. |
| MATERIALIZING_INPUT | Fenced preparation-start fact; frozen generation/Catalog and input pin before any Snapshot write | No Run exists merely because a Snapshot exists. |
| QUEUED | Atomic RUN_LINKED relation + Run QUEUED | Not duplicate persisted operation progress. |
| RUNNING | Linked Run RUNNING | A live thread is not the witness. |
| CANCEL_REQUESTED | Linked Run CANCEL_REQUESTED | Not yet cancelled; completion/failure may still win. |
| COMPLETE | Linked Run COMPLETED with its committed final-verification witness and exact publication profile/refs | Shared Result/Artifact from another Run is insufficient; current Artifact availability is separately verified by the immutable read. |
| FAILED | Durable pre-Run failure, or linked Run FAILED | May contain valid Snapshot/Result; never a scientific negative or certified absence. |
| CANCELLED | Linked Run CANCELLED | Optional upstream facts may remain; never erases occurrence. |

No pre-Run cancel command in this slice. Hiding/removing is presentation only. After Run linkage, existing Research cancellation is
available to an authorized client with its own Product Command ID. The cancelled/complete race obeys existing Run transitions.

### 8.2 Transaction and publication order

1. **T1 admission, before any Market Data access:** authorization/mutation readiness, strict local shape and registered parameter
   validation using the exact versioned Catalog readiness witness above; lock global Command ID. Existing matching receipt returns the same
   operation *before* current-source or current-catalog checks. Atomically persist Product Admission/Receipt, canonical normalized chart intent,
   operation ADMITTED, the exact Catalog witness and an independent server-generated `reserved_run_id`. Resolve reserved Run-ID collision
   by regeneration inside admission, never by reusing the client UUID. Existing admission without
   matching operation/receipt is incomplete/corrupt proof, not permission to make a new operation.
2. A preparation worker claims a bounded lease with monotonically increasing fencing token. Resolve exact hosted Runtime Generation
   and the Catalog pinned during admission, and reserve `runtime_work_id = reserved_run_id.value` through the existing Runtime Generation
   authority. Persist its exact
   binding reference before input side effects. If activation changes before reservation, fail explicitly; never fall forward.
   Cross-authority binding is **not** assumed atomic with PostgreSQL. Reconcile by work ID, exact generation and active binding; do not
   release on ambiguous queue commit. Released bindings require recovery intervention, not silent reactivation.
3. **T2 input pin:** after durable intent, resolve Integration eligibility, canonical source, capability and native construction; plan
   display/input ranges; select one exact sealed Revision. Verify metadata and current physical facts via official readers. CAS-write
   one immutable selection record under the worker fence and preparation-start witness. Two racing workers may select different
   Revisions, but only the CAS winner is authorized to materialize; loser reloads the committed selection. No Snapshot writes before pin.
4. Outside the DB transaction, call `OnlySealedMarketDataDatasetMaterializer.materialize_with_lineage` using **only** the pinned plan.
   It rereads/validates exact proof. Snapshot file publication and lineage commit are separate effects; they are not a distributed
   transaction. Re-entry reconstructs the same plan, verified-reuses the same Snapshot and commits/loads the exact lineage.
5. **T3 input-ready relation:** atomically persist the verified materialization/Snapshot relation and canonical Specification V3 under
   fence. Persist no fabricated readiness or numeric rows here. If T3 is ambiguous, reload by operation and compare complete exact refs.
6. Typed Run admission resolves the frozen Specification in the exact generation, verifies Dataset/lineage/Catalog/implementation and
   the active Runtime Work binding. **T4** locks operation and reserved Run ID; atomically writes Run QUEUED, admission-resolution
   evidence and the immutable operation→Run relation; marks preparation RUN_LINKED. T4 may only create/link the Run reserved at T1;
   it cannot mint a new Run ID or bind work to the operation ID. Research Run persistence and operation relation
   share this PostgreSQL transaction through an explicit composite admission port. No second CREATE_RESEARCH_RUN receipt or public
   raw Run insertion API is introduced. Queue visibility requires all relation/evidence constraints, not just existence of a Run row.
7. Existing Research worker alone claims/executes/reconciles the Run using Engine. Record operational COMPLETED only after verified
   Result, readiness-bearing Artifact, exact execution evidence and required profile check. Release generation ownership through the
   existing terminal-work lifecycle, not through HTTP or the preparation worker.

Dataset/Run APIs, not their tables, are the component seams. Long-running physical reads/evaluation are outside PostgreSQL locks.
Every preparation mutation requires the current fence; no correctness test uses sleeps. T4's PostgreSQL implementation may use one
connection internally, but this does not authorize components to query each other's persistence directly.

### 8.3 Crash, retry and ambiguity

| Interruption | Deterministic convergence |
|---|---|
| Before T1 commit / response lost | Retry same ID/payload. Authoritative exact read distinguishes no committed operation from unavailable storage; unknown does not mean rejected. |
| After intent, before binding/pin | Recover ADMITTED with same intent; bind/pin once. No provider/materialization side effect has occurred. |
| After work binding, before T2 | Load existing work binding by reserved ID; same exact generation only. Do not allocate another work ID. |
| After T2, before Snapshot | Resume only pinned Revision, never latest. A later Revision is irrelevant to this occurrence. |
| After Snapshot, before lineage/T3 | Verified-reuse Snapshot; reconstruct exact materialization relation, then commit T3. Never queue from orphan file discovery. |
| After T3, before/during T4 | Admission under reserved Run ID loads full relation and evidence. Same intent yields at most one Run; conflict/corruption fails closed. |
| After Result, before Artifact/Run terminal | Existing Research worker recovery and Engine re-entry reuse verified upstream facts, finish publication and terminal transition; operation does not infer completion. |
| Old worker continues after lease loss | Its CAS/queue mutation fails by fence. Equal immutable writes may be verified-reused; conflicts block. |

Temporary database/host unavailability is not terminal unless a durable failure fact is committed. Keep last proved state; observation
reports dependency unavailable. Bounded restart reconciliation may resume nonterminal preparation or a Run under its existing recovery
contract; it never retries an already terminal Run in place. Definitive input invalidity/corruption records pre-Run FAILED when possible.
If failure cannot be persisted, return unknown/unavailable, not a false FAILED. A new command after explicit acquisition or correction
is a new occurrence, not blind retry of an unknown effect.

## 9. Exact Market Data -> Dataset flow

Use the existing Integration runtime resolver/plugin capabilities through a new public typed **selection-only** application method.
Reuse `resolve_runtime`, bar-resolution and scope logic; do not duplicate `_plan`/`_scope` in the chart service. The method must not
create/connect/authenticate a provider session, open WAL, fetch instruments remotely, or acquire. Capability/reference proof must be
available from admitted local/plugin declarations and durable reference data; otherwise fail explicitly.

SMA has `minimum_observations = period`. For the first native UTC fixed grid, define `D = 900000000000` ns:

```text
display_support = [s,e) with increasing, grid-aligned boundaries
warmup_bars = registered minimum_observations - 1
materialization_support = [s - warmup_bars*D, e)
display output predicate = s < ts_event_ns <= e
```

The grid origin/alignment is plugin-owned construction evidence, not assumed from the string `15m`. V1 accepts only continuous UTC
fixed native 15m scope compatible with the current Product planner: LAST/RAW, window=stride=15, SESSION_START on the verified continuous
UTC calendar. Session holidays and other alignments are unsupported rather
than guessed with wall-clock subtraction. Server admission time is an explicit recorded UTC input; require e <= that time and all
facts closed. No implicit LATEST_CLOSED/default moving end in the command. Full support <=7 days/672 Bars, period 1..672, and
`display_bar_count + period - 1 <= 672`. These are Product resource policy, **not** a new SMA semantic maximum.

Materialization requires exactly one Revision for the one instrument with `scope.start_ns = input_start` and `scope.end_ns = e`.
It may own multiple already-durable segments, as existing Revision authority permits. It is not a composition of client pages or
independent Revisions. No cropping a larger Revision by pretending its scope is smaller, and no accepting an incomplete warmup prefix.

Persist input pin `ChartCalculationInputSelectionV1` with schema, operation/intent owner, normalized source selection and binding
fingerprint, complete scope, construction identity/recipe/data version/alignment, both ranges, exact Revision ID/fingerprint,
Coverage Manifest ID/fingerprint, Seal ID and checks, and frozen Runtime Generation/Catalog/definition/implementation references.
Its fingerprint hashes canonical content, excluding audit/lease timing. Preserve the exact Revision→segments→physical-proofs relation
through official readers; no row count or timestamp is a substitute. Materialization relation verifies Snapshot definition,
construction fingerprint, source/instrument/data version, Revision membership and Seal; source binding belongs in operational provenance,
not a provider-specific Calculation semantic hash.

`SEALED_REVISION_NOT_FOUND` with a valid exact catalog response becomes admitted `FAILED / CHART_SEALED_COVERAGE_UNAVAILABLE` plus the
planned input range. The user may explicitly use existing `POST /api/v2/market-data/acquisitions` for that native range, inspect its
completion, then submit a new chart command. This chart operation does not call acquisition or await provider progress. The planned
range is not fabricated gap proof: distinguish absence of the required exact Revision from coverage gap facts. Catalog/fact-store
outage, missing physical proofs, conflicting Bars or an invalid Seal are different failures, never reasons to fetch automatically.

A changed source/instrument/semantic/parameters or changed input range produces a new selection/semantic identity where applicable.
Same intent on a later command may select a revised historical input and thus a different Snapshot/Result; same command stays pinned.
Preview is not part of any Snapshot. Series display cropping does not change the full Snapshot identity. Query only filters stored
points; it cannot acquire, materialize or silently add warmup Bars.

## 10. Readiness model and schema/version decision

### 10.1 Choose point-level evidence

| Representation | Decision |
|---|---|
| Per-output PARTIAL/READY/UNAVAILABLE point evidence | Choose: aligned to exact output axis; can represent RESET, dependencies and non-monotonic readiness without query-side reconstruction. |
| One immutable readiness boundary per instrument | Reject as general representation: adequate only for monotonic SMA, not resets/gaps or changing dependency readiness. Adding interval algebra now would be more complex than point evidence. |
| Query/Web derives from Graph, period or row index | Reject: duplicates execution semantics, loses reset/dependency state, and makes an isolated page ambiguous. Graph is explanatory evidence, not permission to recompute readiness. |

The registered backend owns semantic readiness. An explicit versioned backend execution capability returns **values and readiness
atomically from the same execution**, not a second call to an independent evaluator. Executor validates type/shape/output set/axis
and seals the result; it does not contain `if type_id == sma` readiness rules. The SMA plugin emits PARTIAL for observed samples
1..period-1, READY from sample period, including period=1 immediately. This rule runs in the plugin alongside the existing partial
mean, per instrument. No numeric change or semantic-version change to SMA@1 is justified by adding already-declared readiness evidence.
Any implementation discovering a numeric/semantic difference must propose the appropriate semantic version instead.

Generic capability admits only registered backends that actually produce complete readiness; first chart admission is single-node
SMA with FAIL missing policy. RESET, dependent/multi-node and non-monotonic calculations are **not** newly admitted by this slice.
Their future producer must emit actual state per point; the representation can carry it but does not certify it. Old providers lacking
the capability fail readiness admission, never default to READY.

| State | Value rule | Meaning |
|---|---|---|
| PARTIAL | Nullable typed value allowed; SMA first samples have real partial Decimal mean | Producer has not met readiness; null partial and numeric partial are distinguishable. |
| READY | A nullable output may still be null with explicit reason VALUE_UNDEFINED; zero is a valid numeric value | Producer ready condition holds; readiness is not a truthiness/null test. For supported SMA finite complete input, require nonnull READY value. |
| UNAVAILABLE | Value must be null; explicit reason required | Producer cannot supply this observation; not missing evidence. FAIL input errors abort SMA execution, not fabricated UNAVAILABLE rows. |

Reason enum V1: `WARMUP_INCOMPLETE` for PARTIAL; `NONE` for nonnull READY; `VALUE_UNDEFINED` for null READY; `INPUT_UNAVAILABLE` or
`DEPENDENCY_UNAVAILABLE` for UNAVAILABLE. Reject contradictory combinations. Chart SMA uses only WARMUP_INCOMPLETE/NONE. Missing or
malformed readiness is a corruption/capability failure, not a synthetic UNAVAILABLE observation.

### 10.2 Persist at Calculation authority, copy at Artifact authority

Introduce **Calculation Result schema V2** within the existing Calculation Result authority. Retain exact value partitions and add
readiness partitions keyed `(node_fingerprint,output_name,instrument_id,ts_event_ns)` with `readiness` and `reason`. There must be exactly
one evidence row per output point, with no extra/missing/duplicate output or axis. The manifest declares readiness contract version 1,
section schemas/counts/logical fingerprints/byte hashes and exact Dataset/Graph identities. Versioned canonical content hashes include
values and readiness. Result V2 fingerprint is a domain/version-separated hash of Calculation semantic ID and complete V2 content.

Calculation semantic identity remains Snapshot+Graph+RESEARCH. Preserve every V1 payload/hash/storage path. New V2 is stored under an
explicit version namespace in the **same** authority; new commands request V2, not a competing value store. No lookup falls from V2 to
V1 and pretends readiness exists. Run/Job/Result readers select exact referenced result fingerprint/version.

The existing Result Store is keyed by Plan fingerprint. Replacing a numeric-only Calculation reference with V2 under an unchanged V3
Plan would give one Plan two different contents and trigger `DETERMINISTIC_RESULT_CONFLICT`. Therefore add **Plan/Result V4**, not an
alternate Result lookup or reinterpretation of V3. V4 has the unchanged calculation-only membership constraints plus mandatory
`publication` fields: `artifact_profile=RESEARCH_CALCULATION_V2`, `calculation_result_schema_version=2`,
`execution_evidence_schema_version=2`, `readiness_contract_version=1`. Plan fingerprint includes schema and this exact contract;
content fingerprint includes schema 4 and exact Calculation V2 references; Result fingerprint includes schema 4, Plan and content.
Execution occurrence identity remains provenance, not part of semantic Plan equality. Dataset/Graph/node/output relations are verified
as before. V1/V2/V3 payloads, requirements and identities are unchanged. A V4 Plan must never load a V3 Result as publication reuse.

Execution Evidence also needs an explicit **V2** binding including Calculation Result version and readiness contract version/content
reference, produced only from sealed execution by the canonical Job publication path. Reuse requires matching immutable numeric and
readiness Result plus exact execution implementation evidence. Legacy numeric-only cache may be reused as a comparison, not as the
readiness publication source: perform actual verified execution when readiness is absent and verify numeric parity; never annotate
cached values using a guessed boundary. Existing V1 Execution Evidence remains unchanged/readable.

Provider content changes require a new Provider version and rebuilt exact Catalog/Runtime Generation under existing quant-assets
contracts; do not mutate `onlyalpha.indicator.library@5` in place. Hosted admission must prove the new capability and exact byte identity;
no ambient/current fallback or modules reloaded in place. Numeric semantics remain SMA@1. Run lifecycle code is not a readiness producer.

### 10.3 New Artifact, old profiles unchanged

`RESEARCH_CALCULATION_V2`, Artifact schema 2, embedded Result schema **4**, readiness contract 1, mandatory Calculation Result schema 2
and Execution Evidence schema 2. Do not confuse Artifact V2 with Result V2 or existing Scientific V2/V3.

Reuse existing canonical Scientific materialization/physical integrity checks; add immutable `readiness.parquet` plus
`calculation_evidence.json`. The latter embeds exact Calculation V2 semantic manifest/logical partition evidence, graph/output contracts and
sealed Execution Evidence references/content sufficient to verify copied readiness/value membership and producer identity offline.
Existing `graphs.json`, `market.parquet`, `variables.parquet` remain; typed-empty `signals.parquet`/`statistics.parquet` remain because
Result V4 forbids their members. Manifest binds exact profile, Result, Calculation Result versions, execution/readiness evidence and
every section logical fingerprint/schema/byte hash. Neither style nor operation ownership is in Artifact content identity.
Copy canonical semantic manifest projections without audit timestamps; source identities/logical hashes retain their original exact
verification rules. Source physical byte hashes remain integrity evidence, not replacements for the logical content identity.

V2 also includes `sealed_input_evidence.json`: reusable Dataset definition/Snapshot/construction and materialization identities,
source/Integration binding provenance, Revision/Manifest/Seal and verified physical-segment proof references captured by the canonical
materialization/publication path. It excludes operation owner, display range and lease/audit timing. Artifact-only reads explain their
exact input without reopening upstream stores; operation→input ownership still requires the separate operational relation. These copied
proofs attest the selected sealed input at publication, not current health or physical presence in an external store forever.

V2 Artifact storage is content-addressed by **artifact_content_fingerprint**, under its exact profile namespace. A verified lookup
requires `(research_result_fingerprint,artifact_content_fingerprint)`; manifest equality binds both. This is necessary because the same
semantic Result can have different legitimate exact implementation evidence/projection content. Reusing V1's Result-only path for V2
would either conflict or silently substitute provenance. One existing Artifact authority owns these explicit projection identities;
no mutable latest pointer chooses the chart projection. Identical exact content is reused, different provenance is a new Artifact,
and the Run records the exact published content reference. Result semantic identity still excludes Catalog/implementation identity.

Canonical producer copies only verified upstream output/evidence. Public publication accepts exact source intent/references, not
caller-authored rows or caller-chosen readiness. Raw file write primitives remain internal. Verification checks exact membership,
axis equality, reason/value compatibility, content hashes, producer bindings and copied source partition fingerprints. A forged
self-consistent caller row with recomputed hashes must not be admissible through a public writer.

The Artifact can be fully queried after Dataset, Calculation, Result and execution stores are removed. Integrity/provenance verification
is self-contained; a hash does not independently prove mathematical correctness, which is established by canonical sealed production
and registered semantic conformance. Do not move the producer into the reader to “verify” by execution.

Old `RESEARCH_CALCULATION_V1` and Scientific profiles remain readable by their existing numeric APIs. A readiness request against them
returns `CHART_READINESS_NOT_AVAILABLE`, not reconstructed READY or a compatibility shim. An existing corrupt V2 cannot fall back to V1.
Explicit profile selection is required where the same Result has several projections; the chart always selects V2.

Future Web returns/inspects partial values but draws the official continuous line only for READY nonnull points; PARTIAL is available
in an explicitly labelled readout and creates a line gap, never a ready line segment. UNAVAILABLE/null draws no numeric zero. Full
warmup normally makes every display-range SMA point ready; querying the full input prefix still exposes its legitimate partial points.
Each page includes readiness per point and immutable Artifact identity; it needs no prior page to interpret the state.

## 11. Query contract

Use additive endpoints with strict new DTOs; do not add fields to existing scientific-series DTOs that strict old clients reject.
Keep general Research API schema V2 untouched; new chart DTOs explicitly carry `schema_version:1`.

| Endpoint | Selector / returned projection |
|---|---|
| `GET /api/v2/research/chart-calculations/{operation_id}` | Exact UUID4; section 7 operation/linked Run view, no mutation. |
| Existing `GET /api/v2/research/runs/{run_id}` and execution-evidence read | Run operational authority; Run nullable until T4. |
| `GET /api/v2/research/chart-calculation-artifacts/{research_result_fingerprint}/summary` | Requires query `artifact_content_fingerprint`; fixed V2 profile; Result/Artifact/Snapshot IDs, version tuple, counts, instruments, full input bounds, readiness/evidence refs. |
| Same base `/input-evidence` | Copied `sealed_input_evidence.json` with exact Snapshot/materialization/source/Revision/Seal/proof identities; no operation progress or upstream read. |
| Same base `/series` | Canonical published catalog: Calculation/Result/Graph/node/output IDs, value kind, output/nullable/numeric/warmup descriptors, readiness contract, instrument IDs and row counts. No Candidate field required. |
| Same base `/calculations/{calculation_fingerprint}/graph` | Exact Artifact member; Graph fingerprint and full canonical Definition/Graph, embedded producer evidence. This is not Candidate Graph Query. |
| Same base `/variables/{calculation_fingerprint}/{node_fingerprint}/{output_name}/series` | Exact member + instrument; typed values and stored readiness/reason per point. |

For all immutable reads require the returned `artifact_content_fingerprint` to match the requested one. Fixed namespace profile is
not chosen from whichever reader succeeds first. Query uses only the portable Artifact reader; it cannot inspect operation/Run progress
to mint values. Conversely operation GET uses operational relation readers, not a scan of artifacts to infer progress. No chart-ready
aggregate that owns another calculation or hides input proof; the operation response and immutable catalog suffice.

Series query parameters: `artifact_content_fingerprint`, `instrument_id`, `start_ns`, `end_ns` (required support bounds),
`after_ts_event_ns` (optional exclusive cursor), `limit` (default 500, integer 1..2000). Result identity/member/instrument/profile/range
are part of the client query key. `start < ts <= end`, then `ts > after`. Cursor is last returned event time only when has_more=true;
it is valid solely for the unchanged exact selector/range. Server returns `has_more,next_after_ts_event_ns`; empty terminal page has
null cursor. No cursor guessed by timestamp arithmetic. Within one instrument/member event-time uniqueness is mandatory.

Point DTO exact fields: `instrument_id,ts_event_ns,value_kind,decimal_value,integer_value,boolean_value,string_value,readiness,reason`.
Unused scalar fields are null. Decimal and integer/nanosecond/revision/count transport uses canonical strings; JS uses BigInt or branded
exact text for identity/time, not Number. Small bounded `limit`, period and semantic window/stride use JSON integers. Renderer conversion is
explicitly lossy and never fed back to admission. Decimal quantum and rounding come from the embedded Definition, not UI tolerance.

Series page DTO `ChartCalculationSeriesPageV1` has exact fields: `schema_version=1,research_result_fingerprint,
artifact_content_fingerprint,artifact_profile=RESEARCH_CALCULATION_V2,calculation_fingerprint,calculation_result_fingerprint,
node_fingerprint,output_name,instrument_id,start_ns,end_ns,points,has_more,next_after_ts_event_ns`. Each point has the shape above.
Graph/catalog/summary/input-evidence DTOs similarly require schema 1 and both exact Result/Artifact identities. Catalog members are
canonical and unique, not inferred from the selected chart request. Summary and input-evidence expose server-produced content, not
caller-authored proof; the client verifies exact returned identities before presenting it.

No operation-list endpoint, server session or cancellation wrapper is needed. Missing operation/Artifact/member is 404 only after a
valid authoritative exact read. A missing instrument is SERIES_NOT_FOUND, not a successful empty series. A known valid member with
no points in a valid requested range may return an empty page; it asserts only that Artifact slice, not absent external history.
Incomplete operation has null result refs and its actual state; an attempt to request nonexistent publication is not “complete empty”.

## 12. Error taxonomy

Use `ChartCalculationErrorV1 = {schema_version:1,error:{phase,code,detail,effect,operation_id}}`. Effect discriminant is
`DEFINITIVE_PRE_ADMISSION_REJECTION`, `COMMITTED_OPERATION_FAILURE`, `EFFECT_UNKNOWN`, or `READ_FAILURE` for GET. No client infers effect
solely from arbitrary status text. Document Agent metadata for the new command as an idempotent Research operation with the operation
outcome reference, key transport and response-effect mapping, not a Run receipt before T4.

Phase enum: `ADMISSION,INPUT_SELECTION,DATASET_MATERIALIZATION,RUN_ADMISSION,EXECUTION,RESULT_COMMIT,ARTIFACT_COMMIT,QUERY,OPERATIONAL`.
Readiness absence is QUERY/capability failure, not a numeric point status. After T4, owning Run failure details are preserved as a typed
nested source failure rather than rewritten into a chart-specific success/failure fact.

| Condition / stable code | HTTP / effect |
|---|---|
| `CHART_REQUEST_INVALID`, `CHART_CALCULATION_UNSUPPORTED`, `CHART_PARAMETERS_INVALID`, `CHART_OUTPUT_UNSUPPORTED` | 400 pre-admission; no durable intent/effects. Wrong kind/type/version/output rejected; no resolver fallback. |
| `CHART_BAR_SEMANTIC_UNSUPPORTED`, `CHART_RANGE_INVALID`, `CHART_RANGE_NOT_CLOSED`, `CHART_RESOURCE_LIMIT` | 422 pre-admission for locally decidable validation; same codes as durable failure if an exact plugin-bound check fails after T1. |
| `PRODUCT_COMMAND_CONFLICT` | 409 definitive rejection of the attempted different payload/kind; existing command untouched. |
| `CHART_INTEGRATION_BINDING_MISMATCH`, `CHART_SOURCE_NOT_ELIGIBLE` | Durable admitted failure; observed via operation GET 200/FAILED. Never upgrade to another Revision or disabled source. |
| `CHART_SEALED_COVERAGE_UNAVAILABLE` | Durable admitted failure, separate explicit acquisition action; not fact-store outage. |
| `CHART_INPUT_EVIDENCE_CORRUPT`, `CHART_DATASET_MATERIALIZATION_FAILED`, `CHART_RUN_ADMISSION_CONFLICT` | Durable pre-Run failure if recording succeeds; no overwrite/second Run. Includes wrong scope/Seal/physical proof and lineage conflicts. |
| `CHART_EXECUTION_GENERATION_UNAVAILABLE`, `CHART_READINESS_CAPABILITY_UNAVAILABLE` | Admitted dependency/capability failure; no ambient execution or numeric-only fallback. Temporary unavailability may keep nonterminal state until reconciled. |
| Result/Artifact commit/execution failure | Existing linked Run failure phase/code remains owning fact; operation projects it without inventing a science result. |
| `CHART_OPERATION_NOT_FOUND`, `CHART_ARTIFACT_NOT_FOUND`, `CHART_SERIES_NOT_FOUND` | GET 404 READ_FAILURE after exact not-found only. |
| `CHART_ARTIFACT_IDENTITY_MISMATCH`, `CHART_READINESS_NOT_AVAILABLE`, `CHART_ARTIFACT_PROFILE_UNSUPPORTED` | GET 409 READ_FAILURE, never coercion to another profile/version. |
| `CHART_ARTIFACT_CORRUPT`, `CHART_OPERATION_RELATION_CORRUPT` | GET 500 READ_FAILURE; previously proved completion is not erased, but no chart data admitted now. |
| Authority/storage/host unavailable | GET 503 READ_FAILURE; POST 503 EFFECT_UNKNOWN if commit outcome cannot be established. |
| Timeout/disconnect/500/502/504 during POST | EFFECT_UNKNOWN unless a verified committed response/failure or proved pre-admission rejection is available. Retry same ID only. |

After T1, application errors cannot be labelled pre-admission rejection. Normal POST acceptance does not synchronously perform input
preparation; its response is 202. Async definitive failures appear in the operation record. Authorization failures are 401/403 before
admission; rejected cross-operator reads must not leak existence. Generic proxy/transport errors remain unknown to the client.

## 13. Authorization / security

Current Kernel Product dispatcher enforces mutation READY and exact typed handlers, **not a per-user permission system**. Current Run
routes use service-readiness dependencies; the inspected root does not demonstrate general Research RBAC. Agent operation metadata
describes tool/effect semantics, not authentication. Do not claim an already implemented `research` role.

V1 deployment assumption is one authenticated/trusted owner control-plane domain. Use the same protected Product entry boundary as
Research; this is not a new public Internet endpoint. Admission records the server-derived operator scope (never request-supplied tenant)
and authorizes `research.chart_calculation.submit`; read is `research.read`; cancellation remains existing Research cancellation.
For the single-user deployment these map to the owner, and explicitly delegated Research-capable Agent access. If composition cannot
establish that trusted scope, do not expose the new route. Authenticated gateway/transport enforcement and route authorization must be
proved before deployment; a localhost binding or tool descriptor alone is not proof. No general multi-tenant platform is added.

Reject untrusted/cross-origin mutation at the protected entry boundary, and preserve current same-origin Web transport/CSRF protections
where present; if absent, supply the smallest required protection for this route before exposure rather than claiming inherited safety.
Web and Agent use identical canonical commands/receipts/proof rules. Agent is never delegated LIVE activation, Strategy mutation or order
authority. Novelty admission versus actor permission are separate checks, neither substitutes for the other.

Resource policy: JSON body <=16 KiB, bounded ID strings <=256 UTF-8 bytes, exactly one instrument/node/output, no arbitrary graph or
code; period/full-range bounds from section 9; no unknown fields, path inputs, secrets or free configuration blobs. Verify Integration
published Revision, exact expected type, enabled/eligible status and requested instrument/source membership after durable intent;
recheck eligibility at T4 for new Run admission. An accepted Run remains pinned to immutable input/generation; later disable blocks new
work, not historical Artifact observation. No secret logged or embedded in Artifact.

Logs/metrics record command/operation/Run IDs, fingerprints, stage/fence, error class and durations; never raw configuration, secret,
body or arbitrary exception payload. Crash faults use deterministic barriers/fake clocks. Runtime time/random/selection choices are
explicit recorded inputs; no browser-derived operational clock becomes scientific truth.

## 14. Compatibility

| Domain | Strategy |
|---|---|
| Definition V1 | Unchanged shape, identity, Target/Statistics requirements and existing routes. No Definition V2 needed here. |
| Specification V1/V2 | Unchanged payloads/identities and Novelty route behavior. V3 is a distinct strict calculation-publication shape, below. |
| Result V1/V2/V3 | All existing payloads/validation/hash formulas unchanged. New V4 Plan carries explicit readiness publication contract and refers only to Calculation Result V2, still no Statistics/Candidate/Signal. |
| Calculation Result / Execution Evidence | Add explicit V2 schemas and exact readers; V1 remains readable with original identities. No readiness shim. |
| Scientific / calculation V1 Artifact | Existing profiles and APIs unchanged. New V2 namespace/reader explicitly selected by chart paths; no fallback on corruption or readiness request. |
| Run API | Existing POST accepts only existing authoring contract families; chart V3 is admitted via the new typed command, not made available as an ungated generic POST. Existing operational GET can serialize V3 payload as opaque canonical Specification with explicit version. |
| TS / Zod / OpenAPI | Add generated chart types/client functions and strict discriminated Zod schemas atomically. Existing DTOs remain exact; documented V3 Run payload validation is updated only in affected consumers, no catch-all permissive schema. |

Chosen internal **Specification V3** exact fields:

```text
schema_version:3
purpose:"CALCULATION_PUBLICATION"
dataset_snapshot_fingerprint:SHA256
calculations:[existing CalculationSpec with fixed parameters, required sweep_dimensions:[]]
published_series:[existing SeriesSelector, unique canonical order]
publication:{artifact_profile:"RESEARCH_CALCULATION_V2",calculation_result_schema_version:2,
             execution_evidence_schema_version:2,readiness_contract_version:1}
```

No `statistics`, `targets`, scientific `evidence`, `candidate_calculation_id`, eligibility or signals fields are permitted. Chart compiler
emits one SMA calculation/node/output using the registered neutral resolver and Snapshot; Publication selectors resolve to unowned
Result V4 series. Every Calculation has at least one series; all exact dependencies/outputs must resolve. V3 compiler/resolver reuses
existing template/graph validation but does not mint a Candidate for chart calculation. No fake scientific subject/empty ADMIT group.

PostgreSQL admission constraints, strict Specification parsers, hosted generation-resolution/execution DTOs, Run origin validation,
worker, Result-reference readers and Artifact readers must migrate atomically for Specification V3/Result V4/Calculation V2 use.
Unsupported schema fails before queueing,
not mid-Run. Add typed `CHART_CALCULATION` operational origin with required operation/materialization relation and forbidden Strategy
composition/Novelty subject claims. Runtime Generation workers that cannot resolve/execute V3 are not eligible for new chart work.

Migration must be forward additive with existing rows untouched: verify compatible schema/readers/host first, install new constraints
and relations transactionally, then enable admission. No rewrite of historical V1 output. Crash retries use unique Command/operation/Run
and exact relation keys plus CAS; invalid existing relations fail closed. Rollback disables new chart admission; binaries unable to read
new facts cannot be rolled back over their history without explicit forward-fix/compatible-reader strategy. Database is not a wire API.

## 15. Later implementation task decomposition

These are capability boundaries and dependencies for a later owner-authorized implementation contract, **not an implementation plan,
task checklist or authorization to start code**:

1. Canonical Specification/readiness/publication versions and registered SMA capability: makes the existing Engine path expressible
   without fake scientific facts; must include semantic parity and legacy contract consumers.
2. Durable chart input preparation and typed Run admission: connects user intent to exact sealed Snapshot, generation and one Run;
   includes PostgreSQL transaction/fencing/restart and approved admission-policy distinction.
3. Thin Product HTTP/OpenAPI/generated-client boundary: exposes idempotent command/status and Artifact-only readiness/Graph reads,
   including actor authorization and explicit effect semantics. No evaluator here.
4. Later Web vertical slice: picker, official parameters, status and current-context readiness presentation through those APIs;
   Browser acceptance, price Ledger independence, parameter/context-generation isolation and hide/remove behavior.

Only the current user slice's minimum complete capability should be built. No hypothetical generic scheduler, market composition engine,
incremental evaluator or workspace persistence is a prerequisite. Owner review and accepted boundary decisions precede any detailed plan.

## 16. Acceptance matrix and proof obligations

Future implementation acceptance is deterministic, hermetic and offline-first; formal Python/database validation uses canonical
`deploy/run-tests.sh` test profile with isolated PostgreSQL/ClickHouse as relevant. No sleeps/retry-until-green or unrelated full suite by
default. Do not claim these tests exist or passed merely because this design names them.

| Boundary | Required evidence at nearest stable seam |
|---|---|
| Identity | Omitted defaults/normalized enum match explicit defaults; same exact pinned Snapshot/Graph gives same semantic ID; style/incarnation changes do not affect it. Parameter/source/instrument/semantic/range changes alter the appropriate identities; repeated same command does not select later Revision. |
| Command | Real PostgreSQL same key/payload gives one operation/Run; different payload/kind conflicts; parallel submissions and lost responses converge; no Market catalog, provider session or Snapshot side effect before T1. |
| Command/Run identity | An unrelated existing Run ID equal to client command UUID does not prevent admission; a reserved Run-ID collision regenerates during T1; retry reuses the same committed reservation; Runtime Work ID equals reserved Run ID, not operation ID; T4 cannot mint another ID. |
| Catalog capability | Exact generation/type/version/RESEARCH projection advertises readiness V1; missing/wrong generation/family/version capability rejects before new admission. Runtime registration or provider fingerprint alone cannot substitute. Legacy Catalog capability semantics remain unchanged under an explicit new projection version. |
| Recovery | Inject crash at T1/binding/T2/Snapshot/lineage/T3/T4 and Result-before-Artifact; fresh worker resumes same pinned input/reserved Run. No release on unknown T4. Stale lease/fence cannot queue or overwrite selected relations. |
| Input | Renderer arrays, stream close, unsealed Revision, wrong Integration binding/environment/instrument/data version/construction/range, missing segment/physical proof/Seal fail closed. Full warmup included without moving display bounds. Required exact Revision absent produces explicit separate acquisition, never automatic fetch. |
| Producer | period=3 full input emits PARTIAL,PARTIAL,READY; period=1 immediately READY; CLOSE/VOLUME/default parity with registered SMA; partial and ready zero retain numeric zero. Execution leaves source input unchanged across repeats. |
| Publication | Canonical producer alone can persist readiness; caller-forged states/numbers with correct hashes rejected. V1 numeric cache cannot satisfy readiness. V2 reuse proves exact implementation and complete readiness; output axis/member/version mutations and physical corruption block. |
| Query | Pagination returns independently interpretable states, including pages beginning after warmup; empty slice vs missing member distinct; wrong profile/Artifact ID/corrupt readiness rejects. Artifact portable after all upstream stores removed. Backend/materializer/acquirer spies prove Query never calls them. |
| States | ADMITTED, materialization, linked QUEUED/RUNNING/CANCEL_REQUESTED, COMPLETE, failed-with/without-upstream-publication and CANCELLED have precise witnesses. Cancellation after publication may legally race to completion; missing outcome is not terminal failure/absence. |
| Authorization | Authorized owner/delegated Research Agent may submit; unauthenticated/untrusted/cross-scope/cross-origin rejects before durable effects. Mutation readiness required. No LIVE/Strategy/order capability reachable through chart payload or dispatcher. |
| Compatibility | Definition/Specification/Result V1/V2 identities and Result V3 membership unchanged; existing Research/Artifact routes retain strict contracts; OpenAPI compatibility and generated TS/Zod drift/static gates; public-package export contract regression is checked, not merely export-count changed without evidence. |
| Future Browser | Real command -> finite Run -> readiness Artifact -> overlay. Context, parameter, output, incarnation and request-generation changes reject stale responses; historical price revisions are not silently mixed with output; hide/remove leaves Stream and Ledger intact. |

Relation closure is mandatory:

```text
Command admission/receipt -> exact operation intent
operation -> frozen generation/source/input selection -> Revision/Manifest/Seal/physical facts
selection -> canonical materialization -> exact Snapshot
operation/materialization -> typed Run admission -> exact Specification and Runtime Work binding
Run -> actual sealed execution evidence -> Calculation Result values/readiness
Result publication membership -> exact Calculation/Graph/node/output
Artifact -> copied exact publication/evidence -> page/member/axis
```

Equal Result, Snapshot, timestamps or UUID text do not establish ownership. For each relevant predicate: first test owner/family,
then mandatory proof completeness, then equality. Complete same relation = proved match; complete different relation = proved
non-match; missing/malformed relevant proof = incomplete/error; unavailable reader = unavailable/error. None of the latter becomes
certified absence or permission to create another Run. Cancellation/failure is operational history, not scientific rejection.

Structural mutation coverage must remove whole context, owner ID, nested relation, source ref, leaf version/ID; duplicate a relation;
substitute wrong owner family and a complete valid-but-different identity. Each removal must fail closed rather than yield success or
absence. Test repeated restart, reverse discovery order, duplicates, later source growth and corrupt new projection preserving old
history. Runtime membership, readiness and operator ownership remain separate proofs.

Bounded Independent Review for implementation must rederive state space, mandatory identities, relation closure and the negative
invariants from Constitution/accepted contracts before comparing code, within these boundaries. This design's self-review does not
substitute for that review or certify future executable behavior.

### External engineering evidence

First-principles basis: durable intent must precede side effects; one owner per relation; output readiness is execution semantics, not
UI shape. Curated sources consulted: engineering reference registry and failure patterns FP-DATA-002 and FP-RUNTIME-001.
Upstream RQAlpha issue [#632](https://github.com/ricequant/rqalpha/issues/632) gives a concrete repeated `history_bars` reproduction of
cached historical data changed by adjustment. Applicable lesson: execution/projection must leave immutable source unchanged; derive
repeat-execution/hash/physical-proof regression, not a copied adjustment patch. FP-RUNTIME-001 derives exact generation isolation and
no ambient fallback tests. Reject cached mutable arrays, reload-in-place, provider retry/sleep and row-index readiness as shortcuts.
These references are evidence only, not OnlyAlpha authority or a requirement to adopt third-party runtimes.

## 17. Open questions requiring owner decision

Only these approval questions remain; the contracts above select one recommended design, not several unresolved endpoints/models:

1. **Approve typed calculation-publication admission?** Recommended: `CALCULATION_PUBLICATION`/`CHART_CALCULATION` purpose/origin has
   complete source/Dataset/Catalog/generation/execution proof and Research actor permission, but no Novelty scientific subject, Decision
   or suppression outcome. Evaluation/Search V1/V2 continue the unchanged ADR 0128 gate. This requires an explicit Accepted decision
   distinguishing the new action family before production composition changes. It must not be implemented as
   `allow_legacy_ungated=True`, public raw Run insertion, dummy subject, vacuous empty Decision Group or automatic Novelty policy creation.
   Until approved, calculation-only chart Run admission remains unavailable. The existing ADR does not already grant this exception.
2. **Approve readiness-bearing versions and resource defaults?** Recommended: backend readiness capability, Calculation Result V2,
   Execution Evidence V2, Plan/Result V4, Artifact `RESEARCH_CALCULATION_V2`/schema 2, internal Specification V3, legacy identities unchanged; first
   input exactly one sealed native Revision, max seven days/672 Bars including warmup, period 1..672, 16 KiB body, strict new DTOs.
   These are bounded chart admission policy, not a reduction of long-term Indicator or market scope. Provider/Runtime activation follows
   existing exact immutable generation rules; no package version/fingerprint is fabricated by this design.

Owner approval must separately authorize later planning/implementation. Creating or committing this spec is not such authorization.

## 18. Constitution impact = NO

The proposed design keeps market/provider variability in plugin/adapter boundaries, universal Calculation/Dataset/Research contracts
canonical, and Web/Agent on formal versioned APIs. Numeric/readiness truth comes from exact server execution; append-only market facts,
immutable inputs/publications, traceable relations and deterministic restart remain required. UNKNOWN is not rejection or blind retry.
Operational failure/cancellation cannot become science truth. No LIVE authority, parallel calculator, durable browser session or
Constitution change is proposed. No production work is authorized by this document.
