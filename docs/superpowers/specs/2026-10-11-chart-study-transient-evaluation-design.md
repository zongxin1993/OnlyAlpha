# Chart Study Transient Evaluation — Proposed Product and Boundary Design

Status: **Proposed / Owner Approval Required; DESIGN-ONLY / NOT_IMPLEMENTED.**
This supports [ADR 0138](../../adr/0138-chart-study-transient-evaluation-and-formal-research-separation.md), not an independent
Authority or task completion/quality report. Accepted rules remain in force until explicit owner adoption.
The [slice plan](../../plans/chart-study-transient-evaluation.md) contains future test obligations.

## 1. Normative constraint matrix

| Layer / reference | Existing obligation | Proposed relationship / owner action |
|---|---|---|
| L0 Constitution §§4.1–4.5, 4.7–4.9, 8–10 | Unique identity/Authority, deterministic canonical semantics, immutable formal Research, explicit APIs, recoverability, Web presentation, no Agent LIVE | Unchanged. Transient output is disposable observation, never important formal Evidence or trading truth. Source/versions remain explicit; no L0 exception requested. |
| L1 `architecture.md` §§16–17 | Research Artifact read plane; Core does not import concrete plugins; only Calculation SPI, immutable Provider/Catalog content | Preserve formal read plane and SPI. Non-publishing Application orchestration selects the same registered backend; no Provider-specific Core branch. |
| L1 `web-product-architecture.md` §§6.4, 7; ADR 0092 §§Browser authority / Immutable Result read boundary | Scientific visualizations follow verified Result/Artifact Query; JS cannot reconstruct scientific truth | W6 unchanged. Propose explicitly parallel non-scientific series; never call a transient curve scientific evidence. |
| L1 `chart-catalog-navigation-contract.md` §§Exact read / Financial display | Metadata/discovery is not permission; AVAILABLE currently means exact TIME_SERIES RESEARCH readiness1; only controlled-test series implemented | No current permission inferred. Approval-follow-up must add transient capability projection and source family, preserve Research witness and fixture restriction. |
| L1 `indicator.md` §RESEARCH batch readiness | Only SMA@1 readiness1, immutable closed Research inputs; Trading ready/Snapshot are distinct | Unchanged formal readiness scope; reuse backend output structurally for W3, not a Research seal. No EMA/MACD readiness claim. |
| L2 ADR 0135 §§3–6 / Web Product Mode §5 | Concrete user flow, formal API, minimal vertical slice, W3 separate from W6, renderer unchanged | Reinforce product separation; ADR 0135 alone does not authorize exception to later ADR 0136. |
| L2 ADR 0094 §§Financial Time-Series / Exact values | Verified Artifact -> Query recommended source, Lightweight Charts, exact-value admission, browser no recomputation | Propose explicit transient source alongside verified source; retain all renderer and non-recomputation rules. |
| L2 ADR 0136 §§Context / Lifecycle / Chart boundary / Rejected alternatives | Chart first SMA native15m/sealed/Engine-hosted Research; no Preview or HTTP evaluator bypass | Actual constraint, not already satisfied. Request limited W3 exception for Application/SPI batch display reads; W6 remains fully subject to original clauses. |
| L2 ADR 0137 §§Decision / Rejected alternatives | Exact RESEARCH backend produces values/readiness atomically; Evidence2 and Result2 provenance; no HTTP/browser evaluation | Keep publication/provenance/production support limits. Propose only non-publishing projection of same backend output, never Evidence2 or row-index annotation in Query. |
| L2 ADR 0114 §Decision | Core owns complete Decimal envelope; precision/rounding/quantum come from Definition; actual manifests bind policy dependency | SMA@1 CONTEXT is unresolved and current manifest lacks this dependency. Request explicit W3-only placeholder resolution clause; preserve Core envelope and require real manifest/version repair before A1. No current deterministic support inferred. |
| Proposed 2026-10-01 W3-B §§1, 5, 13 | Recommends CreateChartCalculationV1/preparation/Spec3/Research Run, Result4/Artifact2; excludes preview/incremental | Advisory, not Accepted. Propose W6-only positioning; its non-goals are not evidence W3 was cancelled. |

Concrete amendment wording is centralized in ADR 0138 §3. These relationships are proposed, not a silent reinterpretation.

## 2. Source-based product gap analysis

Source baseline: merged master `b3b99d99f76df41a19a36d48ef7c52988322204c`.
W6 comparison only: PR118 `a8144aa4467fa3a850b81d8d34b2241ca0ae950e`, OPEN/Draft at inspection; not merged capability.
The references below are source observations at those commits, not test executions or a persistent progress ledger.

### Market Data already has a real Product path

- `src/onlyalpha/application/market_data_product.py:533–709`: `query_bars` resolves exact runtime/source selection, plans a
  bounded window, reads owning range facts/revision evidence, checks complete coverage and projects closed Bars. Lines 563 and
  599–647 distinguish read-only DB-first Query from acquisition. Incomplete coverage yields no numeric Bars here; it must not be
  represented as a computed Study with missing input silently removed.
- `packages/onlyalpha-http-server/src/onlyalpha_http_server/market_data/routes.py:71–110`: GET bars delegates to that service;
  POST acquisitions separately calls `acquire_bars`. The route performs no Indicator evaluation.
- `packages/onlyalpha-web-console/src/features/workspace/useMarketDataChart.ts:187–243,332–406,423–480`: real Query feeds the
  admitted Bar ledger, history generation fences and a separate stream. `openMarketDataStream` supplies closed/preview observations
  under exact source/semantic checks. Lines 245–330 and 389–400 also show that the **existing chart loader** can explicitly issue
  acquisition Commands for gaps. The proposed Study Query must not reuse that acquisition loop as an implicit side effect;
  opening the existing main chart and evaluating a Study are distinct request chains.
- Current planner uses `only_plan_utc_24x7_bar_window` (service:577). This does not prove an equity-session calendar or stock
  source exists. An intended stock workflow needs a genuinely admitted source/calendar; absence is a visible capability failure,
  never silent substitution with BTC or invented provider Bars.

### P1 Missing W3 Product Query/Adapter

- `packages/onlyalpha-web-console/src/features/workspace/ChartStudies.tsx:190–209`: confirmation constructs a display instance
  and `connectionState: "CONFIGURED_NOT_EXECUTED"`; it does not request values.
- `.../features/workspace/WorkspacePage.tsx:398–411`: the actual `PriceChart` use-site supplies instances, selected ID,
  incarnation, Bars/context and history callback, but **no `studyEvidence`**.
- `.../charts/lightweight/PriceChart.tsx:45,73–85,111–132`: default `noEvidence`, optional presentation input and strict per-instance
  projection. Existing rendering resources are useful; no production numeric adapter is connected by this call chain.
- `.../charts/lightweight/studySeriesProjection.ts:5–23,35–78`: both TypeScript discriminant and strict Zod source allow only
  `CONTROLLED_TEST_EVIDENCE`. Lines 82–129 validate UTC/exact numeric text and segment gaps; they do not calculate SMA.
  `studySeriesRenderer.ts` consumes the admitted segments and presentation options rather than owning numerical semantics.
- `docs/chart-catalog-navigation-contract.md:121–126` explicitly confirms the production adapter gap. A controlled browser fixture
  rendering a line cannot prove a real user adds SMA and sees computed values.

### Trading implementation is not Research readiness or Chart availability

`plugs/onlyalpha-plugin-indicators/src/onlyalpha_plugin_indicators/registration.py:178–234,332–366,401–476` registers typed
Definitions/resolvers and both TRADING and RESEARCH backends. `standard.py:94–164` implements closed-Bar incremental Trading
Snapshots; `research.py:56–153,179–218` contains registered finite Decimal batch outputs. They are separate existing implementations
of the declared semantics; A1 reuses the latter, does not add a third formula or claim the repository already shares one code function.

| Capability visible in source | Actual output / limit | Consequence for proposed slices |
|---|---|---|
| SMA@1 / EMA@1 | Nullable Decimal `value`; period >=1 and price_field CLOSE/VOLUME; batch plus Trading | Only SMA has readiness1 registration; A1 proposes CLOSE/value only, no automatic EMA availability. |
| RSI@1 | Decimal `value` plus STRING `zone` | RSI support is not a scalar-only guess; typed nonnumeric member is not a line. |
| MACD@1 | Decimal dif/dea/histogram plus STRING cross_state; fast<slow and declared warmup | Three numeric members need explicit axes/panes; no readiness1 support inferred. |
| ATR | TRADING atr@1/@2; RESEARCH atr@2 high/low/close, not atr@1 | Exact version required; no silent upgrade from @1 to @2. |
| Bollinger / rolling_return / rolling_volatility / zscore | Explicit member/parameter contracts, some nullable or undefined values | Mathematical/financial Indicator names are not automatically predictive Factors (ADR 0110). |
| WMA/ROC/VWAP/OBV/Stochastic | Further registered typed financial implementations | Library membership is not new Chart support or readiness certification. |
| Factor | Separate admitted Factor type/provider and TIME_SERIES/CROSS_SECTION shape | No universal Factor support or private example injection; A3 needs exact Revision/scope/runtime proof. |

`research.py:27–54` expressly rejects readiness for non-SMA@1, invokes its numeric execution, and produces readiness in that
backend. `registration.py:438–440` advertises `(1,)` for SMA only. `src/onlyalpha/calculation/registry.py:92–127,164–224`
provides exact type/backend resolution and rejects duplicate/mismatched registrations; discovery descriptors are not permission.
`src/onlyalpha/research/calculation/backend.py:85–117` checks readiness support plus implementation manifest.
`execution.py:192–222` requires actual issued Research execution for Evidence: do not use this private issuance path for W3.

Two additional source gaps block deterministic exact capability admission: `registration.py:174` defaults to
`OnlyNumericDefinition.rounding="CONTEXT"` (`src/onlyalpha/calculation/definition.py:248–252`), and SMA arithmetic/quantization
at `research.py:109–110,227–240` uses ambient Decimal context. `src/onlyalpha/calculation/decimal_execution.py:125–128` rejects
CONTEXT rather than resolving it; SMA's manifest has no canonical Decimal policy dependency (`registration.py:390–397`).
Further, HTTP `main.py:693–736` / `composition.py:21–29` retain a discovered Calculation registry, not the proposed matching
process-local Provider/Catalog projection. A1 needs the context/provenance admission and startup retention below; neither is
an already implemented capability or an authorization to repair W6 in this document-only task.

### P0 Product Misalignment / P0 Accepted-ADR Constraint

The prior Proposed design (`2026-10-01-w3b-chart-calculation-product-boundary-design.md:5–16,124–182,323–343`) explicitly
chooses a Research Command, durable preparation, immutable Snapshot/Spec, Run and final Result4/Artifact2. This has real W6 value:
exact provenance, immutable re-entry and auditable scientific publication. Applying it to each ordinary line/period edit instead
imposes durable intent, sealed input preparation, worker/lease and publication/recovery cost on a display interaction.

This is a product/architecture P0, **not** an allegation that the incomplete UI is a security vulnerability. ADR 0136's explicit
Engine/no-preview rule is a separate governance P0: implementation cannot simply ignore it. ADR 0138 proposes a narrow owner-approved
scope separation; all current Accepted files stay unchanged.

### P1 W6 Draft Still Incomplete — read-only comparison with PR118

At the separate PR118 SHA, `database/postgres/migrations/0050_chart_native_execution_entry.sql:1–5,85–99,165–205,208–315`
provides narrow operational Claim/Heartbeat and owner relation checks. It ends with no Controller/reader/PUBLIC EXECUTE grant;
the Run constraint has QUEUED0/CANCELLED1/RUNNING1/CANCEL_REQUESTED2, no Chart COMPLETED publication state. SQL proves operational
relations, not Source/installed-byte/Work/scientific proof. `research_chart_native_execution_store.py:34–40,91–164` holds the
original Work proof through actual Claim COMMIT and checks fresh exact committed ACK, but is not a native consumer or terminal path.

Reusable W6 foundations include `packages/onlyalpha-runtime-generation-manager/src/onlyalpha_runtime_generation_manager/`
`chart_native_source.py`, `chart_native_publication_reader.py`, and `native_publication.py`: in-process original Source
issuance, exact installed implementation/scientific owning reads and guarded native Result2/Evidence2/Result4/Artifact2 publication.
Their tests and files do **not** by themselves connect an authorized same Run/ACTIVE Attempt to durable COMPLETED.
Installed Host capability/bootstrap/dispatch, whole operational owner validation, fenced terminal/expiry/retry, UNKNOWN terminal ACK,
no-ACTIVE cancellation/recovery and original Work release still require independent W6 closure. Source/file absence is not historical
absence. No PR118 code, tests, SQL, metadata or body is modified by this proposal; none is an A1 prerequisite.

## 3. User flows and visible states

**W3 reference:** ordinary chart indicator addition/editing, as an interaction reference only, not proprietary renderer/semantics reuse.
User goal: inspect a real source-bound SMA on a historical price chart without creating Research.

1. Open an admitted Source/Instrument/BarSemantic; existing Market Data path supplies history and the independent main-chart stream.
2. Pick exact transient-supported SMA@1, period20; confirm typed intent and an overlay or separate pane.
3. Query already-stored closed history; display numeric/readiness/quality from server. No Run/Attempt/publication is created.
4. Change period20->30: preserve display instance, invalidate values/request generation, request new exact configuration.
5. Hide, change color/pane or select: presentation-only. Show restores current admitted values; if binding became stale, mark stale,
   do not calculate from the show handler. Source/instrument/timeframe change removes old curves and aborts/fences old responses.
6. Inspect exact Decimal and timestamps in hover, and a clear “参考计算 / 非研究结果” source label.

Visible state machine is display-only: CONFIGURED_NOT_CONNECTED -> LOADING -> DISPLAYABLE or INPUT_INCOMPLETE / UNSUPPORTED /
UNAVAILABLE / INVALID; replacement invalidates to STALE before another LOADING. Removal/unmount discards pending projection.
DISPLAYABLE may contain PARTIAL points; it is neither numeric READY for every point nor Research COMPLETED. Main-chart realtime
status remains separate; A1 Study is labeled closed historical as the price chart receives new live observations.

**W6 reference:** explicit “从当前指标创建 Research”, never automatically invoked by the W3 editor.

1. Review source/window/parameters as intent, confirm a separate Research action and its permission/idempotency scope.
2. Research re-resolves/freeze-checks source, input and registration under its own admission. Stale/unavailable intent is rejected.
3. Observe durable Run states from operational Authority, including UNKNOWN submission/terminal ACK where relevant; no invented progress.
4. Exact installed worker publishes and verifies all scientific facts, commits fenced terminal and releases original Work.
5. Open optional Research Verified overlay through exact Query; it stays labeled independently of transient output.

No preview values, cache object, StudyInstance ID or DTO fingerprint transfers as scientific fact. Browser closure does not cancel
a formal Run. Failure/cancellation can leave valid upstream facts but never imply COMPLETED. W6 does not depend on a successful W3 Query.

## 4. Candidate Product API — not an existing endpoint

| Candidate | Assessment |
|---|---|
| `POST /api/v2/chart/studies/evaluate` with strict JSON body | Recommended Query transport: bounded structured parameters/selection, explicit schema, no URL JSON ambiguity; must not invoke Command admission just because it is POST. |
| `GET /api/v2/chart/studies/evaluation?...` with encoded typed parameters | Also read semantics, but URL/log exposure, length limits, JSON/query encoding and cache vary keys are harder; rejected as primary A1 route, not for being GET. |

No 202 operation/polling, persistent receipt/idempotency record, queue or Research permission. Synchronous bounded work only; timeout
returns unavailable, never a durable business status. Existing authentication/authorization must enforce subject/source access; no
new role or unauthenticated public evaluator. Body limits and CPU/row/Decimal validation happen before backend work.
Use `Cache-Control: no-store` at HTTP intermediaries; later application/browser caches must obey the exact-key rules, never HTTP TTL.

The new exact request fields cannot be obtained from today's discovery-only picker. The same A1 slice therefore needs the candidate
read `GET /api/v2/chart/studies/capabilities`, projecting the **same process-lifetime registry/Provider/Catalog composition**, not a
new registry or Research active pointer. Strict V1 response: `{schema_version:1, capabilities:[{kind,type_id,semantic_version,
descriptor,descriptor_fingerprint,backend,implementation_fingerprint,provider_id,provider_version,provider_content_fingerprint,
catalog_generation_fingerprint,readiness_contract_version,execution_shape,output_members,limits,numeric_execution_binding,
capability_projection_fingerprint}]}`. Only full exact supported
rows are eligible for evaluation; A1 advertises SMA@1/CLOSE/value/TIME_SERIES/closed-batch support. Existing discovery remains
configuration metadata. Empty supported rows mean no eligible **transient capability in this composition**, not global asset absence.
Unavailable/malformed composition yields an error, never ambient fallback. Evaluation rechecks the captured descriptor/implementation
and full current Provider/Catalog relation; a process replacement cannot silently honor stale intent. This is also a candidate API,
not an implemented route. Its metadata does not reserve a computation or grant Research/Runtime permission.

`capability_projection_fingerprint` is the canonical hash of the complete schema1 capability row excluding that fingerprint,
in the explicit `onlyalpha.chart-study.capability-projection` domain. It binds descriptor/type/version/backend, exact Provider
ID/version/content, the full owning Catalog generation, implementation manifest, readiness/support shape/output/limits and the
numeric execution binding. It is a Query admission projection identity, **not** a Calculation/Result fingerprint or authority token.
Evaluation must carry the selected fingerprint below and echo/recompute it in the response; complete different Provider/Catalog
or numeric policy means REGISTRATION_CHANGED even with unchanged descriptor and implementation. Missing/unavailable complete
binding is unavailable, never stale by inference. Each response echoes `capability_projection_fingerprint` in `calculation`.

Startup must retain one verified `OnlyQuantAssetCatalogGeneration` and its exact registration relations from the same installed
composition used for the Product Calculation registry; it must not rediscover providers during evaluation or derive Catalog from
registry names. Full provider closure is verified against installed manifests/content before capabilities are published. Existing
non-provider registrations (such as predicates) cannot invent a Provider relation; the transient supported subset is explicitly
qualified. A1 construction must reject duplicate/missing/mismatched providers and hold that immutable composition for each request.

### Request V1 (exact proposed fields)

All objects are strict (unknown/missing fields rejected); integer fields reject booleans/coercion, time/Decimal use canonical text.

```text
schema_version: 1
source_reference: {integration_id, integration_revision_fingerprint, expected_type_id}
instrument_id: exact canonical Instrument key
bar_semantic: existing full canonical Market Data BarSemantic DTO
window: {anchor_kind: BEFORE_TIME, before_ns: UTC ns string, target_bar_count: integer}
expected_history_projection_fingerprint: 64-lowercase-hex server read identity
calculation: {
  kind: INDICATOR, type_id, semantic_version,
  typed_parameters: {period: {type: INTEGER, value: integer}, price_field: {type: STRING, value: CLOSE}},
  output_members: [value],
  expected_descriptor_fingerprint, expected_implementation_fingerprint,
  expected_capability_projection_fingerprint
}
include_unclosed_preview: false
```

A1 fixes SMA@1, CLOSE/value, one instrument, closed historical input, supported native15m selection under the owning planner.
The UI may select other contexts, but unsupported ones are honestly blocked, not coerced. Actual stock source/session support must
be admitted before promising stock availability; the current 24x7 planner must not be applied to exchange sessions by assumption.
`LATEST_CLOSED` / last-N is an alternative **initial market-window selection**, not an unresolved clock in evaluation:
first obtain its resolved end/window/fingerprint from Market Data; evaluate with fixed BEFORE_TIME/before_ns. Exact `[start,end)`
is representable for this fixed-grid A1 by exclusive end + count; do not add a general session-range API until required.

The window is the entire **evaluation** input, not the viewport. The Market Data history projection fingerprint must match the
server re-read using identical selection, BEFORE_TIME anchor/end/count/semantic. A fingerprint from a LATEST_CLOSED read is not
assumed interchangeable (current fingerprint includes anchor and requested fields). This extra exact read is read-only, not new data truth.
Historical/stream watermarks also are not interchangeable. Request does not supply trusted data revisions or Source identity.

Candidate finite bounds: `1 <= target_bar_count <= min(10000, MAX_TARGET_BAR_COUNT)`, `1 <= period <= 10000`, body <=64KiB,
one output, no DAG/universe/code; constant policies must be frozen in A1 admission tests, not configurable bypass switches.
These are proposed limits, not measured SLOs. Inherited source/semantic/time and Decimal validity rules still apply.

### Response V1

```text
schema_version: 1
source_kind: CHART_STUDY_TRANSIENT
authority: DISPLAY_ONLY
publication_status: NOT_A_RESEARCH_RESULT
source_selection: owning {integration_id, integration_revision_fingerprint, type_id, source_id, environment}
instrument_id, bar_semantic
input: {
  anchor_kind: BEFORE_TIME, before_ns, target_bar_count, resolved_start_ns, resolved_end_ns,
  initialization: FINITE_WINDOW_START,
  revision_evidence: existing typed Market Data revision evidence,
  history_projection_fingerprint,
  resolution_mode, resolution_plan_fingerprint,
  derived_projection_fingerprint: null in A1, aggregation_semantics_version, calendar_fingerprint,
  resume_after_sequence, resume_plan_fingerprint
}
coverage: existing {status, expected_bar_count, actual_bar_count, issues, gaps, planned_acquisition_ranges}
query_status: DISPLAYABLE | INPUT_INCOMPLETE
calculation: {
  kind, type_id, semantic_version, normalized_typed_parameters, definition_fingerprint,
  descriptor_fingerprint, backend: RESEARCH, implementation_fingerprint,
  provider_id, provider_version, provider_content_fingerprint, catalog_generation_fingerprint,
  capability_projection_fingerprint,
  numeric: {representation: DECIMAL, precision, declared_rounding, output_quantum},
  numeric_execution_binding: {
    schema_version: 1, resolution_policy: CONTEXT_HALF_EVEN_V1,
    core_policy_id: onlyalpha.decimal.execution, core_policy_version: 1, core_policy_fingerprint,
    effective_rounding: ROUND_HALF_EVEN, precision: 28, output_quantum: 0.000000000001,
    Emin: -999999, Emax: 999999, capitals: 1, clamp: 0,
    trapped_signals: [DivisionByZero, InvalidOperation, Overflow], entry_flags: CLEAR,
    invocation_implementation_fingerprint
  },
  output_members: [{name: value, data_type: DECIMAL, nullable: true, unit: PRICE}]
}
series: [{output_name: value, points: [{
  time_ns, value: canonical Decimal string | null,
  readiness: PARTIAL | READY | UNAVAILABLE,
  reason: NONE | WARMUP_INCOMPLETE | VALUE_UNDEFINED | INPUT_UNAVAILABLE | DEPENDENCY_UNAVAILABLE,
  quality: CLOSED_COMPLETE, closed: true
}]}]
```

`input` is a projection of existing authoritative selection/revision proof, not a new Market Data `data_version` authority.
On INPUT_INCOMPLETE, coverage/gaps are explicit, history fingerprint/watermarks may be null exactly as the owning Query reports,
and `series=[]`; no backend invocation or fabricated per-point UNAVAILABLE observations. Registration proof must still be complete.
Response fields cannot claim frozen Dataset identity, execution issuance, Result/Evidence/Artifact refs, Run, percentage progress or
certified absence. No byte-equality or synthetic hash substitutes for owning relations. This JSON is not a Research input DTO.

### Time, warmup, value and quality rules

- Bar range membership is `[bar_start_ns,bar_end_ns)`; request range `[resolved_start_ns,resolved_end_ns)`; end is exclusive.
  Proposed output `time_ns = bar_start_ns`, the existing Product chart identity, not array position or an inferred close time.
  All Bars must be closed and complete for the evaluation window; ordered unique whole-second UTC ns are required by the renderer.
- Initialization is explicitly at evaluation-window start. SMA partial-window outputs from that start are valid backend-produced
  PARTIAL/WARMUP_INCOMPLETE; period1 is READY immediately, period20 is READY after 20 actual input observations, period>window length
  remains PARTIAL. This is canonical finite-series initialization, not a guess that history before the start never existed.
- To render a viewport beginning later, select a complete larger input window including up to `period-1` prior Bars before cropping
  in Web. A1 may truthfully show PARTIAL at its declared window start; insufficient intended prefix is INPUT_INCOMPLETE, not silent
  shortening of the request. Window extension creates a new input identity/re-evaluation; do not splice incompatible initialized series.
  EMA/MACD later need their own exact initialization/state-history contracts, not an SMA-style assumed fixed prefix.
- Current SMA missing-value policy FAIL means null input, an actual gap or malformed input rejects/returns incomplete rather than
  dropping rows, resetting at the gap or interpolating. No partial values are computed for an incomplete requested window in A1.
  No-data is an observed scoped input shortage, not historical certified absence or a scientific rejection.
- Structural state/reason/nullability uses the existing backend validator: READY/NONE nonnull including exact zero;
  PARTIAL/WARMUP_INCOMPLETE nonnull (null only when the output contract allows it); READY/VALUE_UNDEFINED null only for nullable
  output; UNAVAILABLE/INPUT_UNAVAILABLE or DEPENDENCY_UNAVAILABLE null. Unsupported combinations/extra or missing members fail.
  A1 SMA complete-input execution may yield only its supported subset; generic enum presence does not grant other backend capability.
- Data quality is independent of numeric readiness. Closed Market Data does not imply all points READY or a scientific Seal.
  A1 rejects `include_unclosed_preview=true`; independent price stream remains. Later preview is explicit PREVIEW_UNCLOSED, not
  CLOSED_COMPLETE. Missing/unavailable source and no-data UI states never manufacture point metadata.
- Decimal execution must satisfy the explicit proposed binding below, not the current ambient CONTEXT assumption. Financial unit is explicit PRICE for A1 CLOSE;
  output member/nullability are validated against the Definition. Original numeric text is preserved for hover; lossy plotting only
  rejects unsafe/overflow/underflow/non-finite or timestamp-alias conversion. Scientific values are never rounded by the browser.

### Legacy Decimal context admission prerequisite

The proposed `CONTEXT_HALF_EVEN_V1` resolves only declared SMA@1 CONTEXT to ROUND_HALF_EVEN; it does not mutate the
Definition or invent an implementation dependency on the old manifest. Precision=28 and quantum=0.000000000001 are asserted
against that exact registered Definition. All remaining context fields and the complete trap map use the existing Core policy
`onlyalpha.decimal.execution@1`: trapped signals above; FloatOperation, Underflow, Subnormal, Inexact, Rounded and Clamped untrapped.
Construct a fresh complete context using Core/native Decimal capabilities, never `getcontext()` / `DefaultContext` copying or
precision-only overrides. Clear all entry flags, isolate with localcontext, discard internal flags on exit and preserve caller flags.
Run values and backend readiness atomically within that context; deterministic Decimal/input/output failure is not converted to null.

This **proposed explicit execution input** is carried in capability, response and future cache keys. It supplies the legacy
placeholder's invocation context without claiming all historical @1 CONTEXT executions were deterministic or equivalent. It is
not a second Core Decimal envelope and never substitutes for Definition identity or Research evidence. ADR 0114's current wording
does not define this placeholder resolution; ADR 0138 supplies the precise owner-approval clause rather than silently relaxing it.
This is the explicit numeric input required by the current invocation, not a compatibility loader/shim or a promise to preserve
arbitrary historical ambient behavior. If preserving @1 is incompatible with its authoritative semantics, version the semantics instead.

Implementation eligibility additionally requires an actual `OnlyCalculationImplementationManifest` closure over the effective
invocation code, existing backend bytes and Core/resolution policy dependency. Do not append a claimed dependency in the DTO to
the current unchanged manifest. If implementing that closure changes Provider content, publish a new Provider version; any actual
Definition/algorithm semantic change requires a new Calculation semantic version, not an unapproved @1 rewrite. Preferred SMA@1
admission is conditional on proving its unchanged declared semantics with explicit contextual input; if that cannot be proved,
fail unavailable and obtain a separately approved semantic-version migration before publishing support. No old W6 manifest, Result
or fingerprint is edited, replaced or claimed compatible. This prerequisite is inside future A1 correctness scope, not an A0 code fix.

Tests must vary hostile ambient precision, every rounding mode, Emin/Emax, clamp, traps and pre-set flags, in sequential/threaded
calls. Given the same explicit binding and ordered inputs, exact outputs/readiness or deterministic failure must match, source and
caller context remain unchanged, and a missing/mismatched policy/invocation manifest fails admission. Numeric comparison with legacy
execution uses the **same explicit fixed context**; it never asserts parity with arbitrary past ambient contexts.

### Failure envelope and authorization

Proposed error shape: `{schema_version:1,error:{phase:QUERY,code,detail}}`. Details are sanitized, no credentials/files/source code.
No values are returned with an error and no fallback type/source is selected.

| HTTP / candidate code | Meaning | Display / inference restriction |
|---|---|---|
| 400 CHART_STUDY_REQUEST_INVALID / WINDOW_UNSUPPORTED / PREVIEW_UNSUPPORTED | Wrong version/shape/params/output/bounds or unsupported A1 window | Invalid/unsupported, not coerced to defaults |
| 401/403 existing authentication/authorization failure | Subject/source not permitted | No data/credentials leaked; not proof Source absent |
| 404 existing owning source/instrument NOT_FOUND | Scoped lookup missing under owning rules | No global/historical absence conclusion |
| 409 CHART_STUDY_SOURCE_CHANGED / REGISTRATION_CHANGED / DATA_CHANGED | Exact requested binding differs from complete owning proof | STALE; discard prior values, fresh explicit query intent required |
| 503 CHART_STUDY_CAPABILITY_UNAVAILABLE / SOURCE_UNAVAILABLE / QUERY_TIMEOUT | Proof/read/compute unavailable, no matching admitted capability | UNAVAILABLE, never empty success or scientific non-match |
| 500 CHART_STUDY_INPUT_CORRUPT / OUTPUT_INVALID | Relevant mandatory proof/output corrupt | Fail closed, preserve diagnostics, never rebuild over owning corruption |
| 200 INPUT_INCOMPLETE | Valid owning read reports gaps/short window, registration complete | Explicit coverage and empty series; not READY, certified absence or calculation result |
| 200 DISPLAYABLE | Full source/registration/output proof | DISPLAY_ONLY; still no Research authority |

Expected data fingerprint mismatch can be determined only with complete current proof. If it is unavailable, return unavailable,
not DATA_CHANGED/non-match. Deadline/disconnect can discard computation safely because the Query has no durable business effect;
bounded repeat reads are new observations, not Command retries. No UNKNOWN Research reconciliation or Work release is invented here.

## 5. Proof-bearing display admission and lifecycle

Mandatory proof dimensions are Source selection relation, Instrument membership, full BarSemantic/plan/calendar, fixed complete
input/revision chain, exact registration/Definition/Provider/implementation, atomic output/value/readiness alignment, then display
owner/context/configuration/output/generation. Ownership relation is directional; sharing a timestamp/value/hash is not proof.

| Stage | Proved match | Proved non-match | Incomplete / unavailable |
|---|---|---|---|
| Applicability | Strict transient source family | Complete different source family routed separately | Missing/malformed discriminant rejected |
| Completeness | All mandatory fields/owning relations verified | Not inferred from missing fields | INVALID or UNAVAILABLE; never certified absence |
| Equality | Exact input/registration/current display tuple agrees | Complete different tuple -> STALE | No equality predicate success/non-match certified |

Response source family cannot be CONTROLLED_TEST_EVIDENCE in production. A `RESEARCH_VERIFIED` response must pass its own
Artifact Query admission; it cannot enter the transient branch to avoid missing scientific proof. Duplicate owners/output rows,
wrong nested relation, absent whole input/registration, wrong Source ref/leaf member, stale restored context and complete different
identity are adversarial mutations in the acceptance plan.

The request owner captures contextKey/incarnationKey/configurationKey/request generation and selected data/registration version.
Abort is useful but not proof: check these again after response, before attaching the projection. A1 does not compare JSON-stringified
UI config to canonical Calculation fingerprints. Style-only edits do not change calculation intent; duplicated instances may reuse
immutable admitted numeric values but receive distinct instance-scoped projections and resource mappings.

A1 cache is optional and default absent. A4 cache key follows ADR 0138 §5; absence/staleness/unavailable proof never grants reuse.
Data backfill produces an owning revision, invalidates the full window, and requires new values. Browser restart discards transient
state. Logs/metrics can record sanitized request and binding diagnostics; they are not a second Research history or progress Authority.

## 6. Bounded external engineering evidence

First-principles derivation: disposable output still needs exact source and algorithm semantics, while a formal scientific fact
needs the existing immutable publication chain. Hence preserve Market Data/Calculation owners and split **lifecycle**, not formulas.
Consulted curated `docs/engineering/reference_registry.md`, FP-DATA-002 and FP-RUNTIME-001 before bounded upstream comparison.

| Reference / historical failure | Applicable generalized lesson | OnlyAlpha invariant / planned protection |
|---|---|---|
| [RQAlpha #632](https://github.com/ricequant/rqalpha/issues/632), repeated history query changed cached adjusted data in place | Transform aliases can silently rewrite source/cache values | Repeated query and cache miss/hit must match; re-read source fingerprints unchanged; independent consumers order-invariant (plan W3-15). |
| [Lightweight Charts #568](https://github.com/tradingview/lightweight-charts/issues/568), misordered/duplicate timestamps produced renderer errors | Renderer tolerance is not exact point-identity admission | Reject duplicate/out-of-order/alias times before native setData, including zero time; exact timestamp hover and segmented gaps (W3-16). |
| FP-RUNTIME-001 generation contamination/fallback | Metadata name/version is not proof of exact executable binding | Pin immutable request composition; mismatch/unavailable manifest rejects; no ambient/historical fallback (W3-10/17). |

These upstream reports describe historical versions, not an assertion the installed lightweight-charts 5.2.1 has the same bug.
Reject upstream tolerance/sort-deduplicate, inverse transforms/cache-clearing as correctness fixes, sleeps/retry-until-green and
mutable evaluator truth. No dependency/patch/renderer replacement is imported. Executable regressions belong to the authorized
implementation slice; links here are proposed test derivation, not a claim those future tests ran.
