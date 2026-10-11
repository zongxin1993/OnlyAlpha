# Chart Study Transient Evaluation — Product and Boundary Design

Status: **Design constrained by Accepted ADR 0138; not implementation or availability evidence.**
This supports [ADR 0138](../../adr/0138-chart-study-transient-evaluation-and-formal-research-separation.md), not an independent
Authority or task completion/quality report. The owner explicitly adopted ADR 0138's limited amendments on 2026-10-11;
formal W6 publication, numeric/provenance admission and L0 rules remain in force.
The [slice plan](../../plans/chart-study-transient-evaluation.md) contains future test obligations.

## 1. Normative constraint matrix

| Layer / reference | Existing obligation | Relationship under ADR 0138 |
|---|---|---|
| L0 Constitution §§4.1–4.5, 4.7–4.9, 8–10 | Unique identity/Authority, deterministic canonical semantics, immutable formal Research, explicit APIs, recoverability, Web presentation, no Agent LIVE | Unchanged. Transient output is disposable observation, never important formal Evidence or trading truth. Source/versions remain explicit; no L0 exception requested. |
| L1 `architecture.md` §§16–17 | Research Artifact read plane; Core does not import concrete plugins; only Calculation SPI, immutable Provider/Catalog content | Preserve formal read plane and SPI. Non-publishing Application orchestration selects the same registered backend; no Provider-specific Core branch. |
| L1 `web-product-architecture.md` §§6.4, 7; ADR 0092 §§Browser authority / Immutable Result read boundary | Scientific visualizations follow verified Result/Artifact Query; JS cannot reconstruct scientific truth | W6 unchanged. Explicitly parallel non-scientific series; never call a transient curve scientific evidence. |
| L1 `chart-catalog-navigation-contract.md` §§Exact read / Financial display | Metadata/discovery is not permission; AVAILABLE currently means exact TIME_SERIES RESEARCH readiness1; only controlled-test series implemented | Transient capability/source is a separate admitted projection; preserve Research witness and fixture restriction. No current execution permission inferred. |
| L1 `indicator.md` §RESEARCH batch readiness | Only SMA@1 readiness1, immutable closed Research inputs; Trading ready/Snapshot are distinct | Unchanged formal readiness scope; reuse backend output structurally for W3, not a Research seal. No EMA/MACD readiness claim. |
| L2 ADR 0135 §§3–6 / Web Product Mode §5 | Concrete user flow, formal API, minimal vertical slice, W3 separate from W6, renderer unchanged | Reinforce product separation; ADR 0135 alone does not authorize exception to later ADR 0136. |
| L2 ADR 0094 §§Financial Time-Series / Exact values | Verified Artifact -> Query for scientific sources, Lightweight Charts, exact-value admission, browser no recomputation | Explicit transient source alongside verified source; retain all renderer and non-recomputation rules. |
| L2 ADR 0136 §§Context / Lifecycle / Chart boundary / Rejected alternatives | Formal Chart Research uses native15m/sealed/Engine-hosted Research; no Preview or HTTP evaluator bypass | Limited W3 Application/SPI batch display-read exception only; W6 remains fully subject to original clauses. |
| L2 ADR 0137 §§Decision / Rejected alternatives | Exact RESEARCH backend produces values/readiness atomically; Evidence2 and Result2 provenance; no HTTP/browser formula evaluation | Non-publishing projection of same backend output only, never Evidence2 or row-index annotation in Query. Publication/provenance/support limits unchanged. |
| L2 ADR 0114 §Decision | Core owns complete Decimal envelope; exact Definition and actual manifests bind policy dependency | W3-only explicit legacy-CONTEXT resolution is permitted, but SMA@1's actual context/manifest/version closure must be repaired and proved before support. No current deterministic support inferred. |
| Proposed 2026-10-01 W3-B §§1, 5, 13 | Recommends CreateChartCalculationV1/preparation/Spec3/Research Run, Result4/Artifact2; excludes preview/incremental | Advisory, not Accepted; W6-only positioning. Its non-goals are not evidence W3 was cancelled. |

Concrete adopted amendment wording is centralized in ADR 0138 §3 and reflected in the corresponding Accepted/L1 documents.

## 2. Source-based product gap analysis

Source baseline: merged master `b3b99d99f76df41a19a36d48ef7c52988322204c`.
W6 comparison only: PR118 `a8144aa4467fa3a850b81d8d34b2241ca0ae950e`, OPEN/Draft at inspection; not merged capability.
The references below are source observations at those commits, not test executions or a persistent progress ledger.

Historical comparison note: PR118 was subsequently merged as `9f5cbb637da5b235702392f1598305d2fd06424a` before PR119's
`3793eeb8c7a9f1ddfc905c972500a4cfe2b86e77`. That master contains 0050's default-closed Claim/Heartbeat foundation, not a
complete W6 installed-execution/terminal/recovery/Work-release lifecycle. The original SHAs/line references remain historical
source evidence; “OPEN/Draft at inspection” is not the current PR status or an assertion that master lacks migration 0050.

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
Engine/no-preview rule remains mandatory for W6: implementation cannot simply ignore it. ADR 0138 adopts only a narrow W3
scope separation; the corresponding Accepted/L1 amendments preserve formal Research publication/execution rules.

### P1 W6 lifecycle gap — historical read-only comparison with PR118

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
absence. No W6 code, tests, SQL or production grants are changed by this architecture adoption; none is an A1 prerequisite.

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

Finite A1 bounds: `1 <= target_bar_count <= MAX_TARGET_BAR_COUNT` (currently **2000**), `1 <= period <= 10000`, body <=64KiB,
one output, no DAG/universe/code; constant policies must be frozen in A1 admission tests, not configurable bypass switches.
The original 10000 window candidate is not an implemented limit or service SLO; A1 does not introduce 10k scanning or general
range planning. These are resource ceilings, not measured latency promises. Inherited source/semantic/time and Decimal validity
rules still apply. The first real source must prove provider-native closed 15m coverage: neither an A-share label nor a 24x7
crypto fixture proves equity calendar/session support. Stock/calendar, derived7m and preview remain separate slices.

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
- Decimal execution must satisfy the explicit approved binding below, not the current ambient CONTEXT assumption. Financial unit is explicit PRICE for A1 CLOSE;
  output member/nullability are validated against the Definition. Original numeric text is preserved for hover; lossy plotting only
  rejects unsafe/overflow/underflow/non-finite or timestamp-alias conversion. Scientific values are never rounded by the browser.

### Legacy Decimal context admission prerequisite

The approved `CONTEXT_HALF_EVEN_V1` resolves only declared SMA@1 CONTEXT to ROUND_HALF_EVEN; it does not mutate the
Definition or invent an implementation dependency on the old manifest. Precision=28 and quantum=0.000000000001 are asserted
against that exact registered Definition. All remaining context fields and the complete trap map use the existing Core policy
`onlyalpha.decimal.execution@1`: trapped signals above; FloatOperation, Underflow, Subnormal, Inexact, Rounded and Clamped untrapped.
Construct a fresh complete context using Core/native Decimal capabilities, never `getcontext()` / `DefaultContext` copying or
precision-only overrides. Clear all entry flags, isolate with localcontext, discard internal flags on exit and preserve caller flags.
Run values and backend readiness atomically within that context; deterministic Decimal/input/output failure is not converted to null.

This **explicit execution input** is carried in capability, response and future cache keys. It supplies the legacy
placeholder's invocation context without claiming all historical @1 CONTEXT executions were deterministic or equivalent. It is
not a second Core Decimal envelope and never substitutes for Definition identity or Research evidence. ADR 0114's limited
ADR 0138 amendment admits this resolution with actual provenance proof, rather than silently relaxing numeric requirements.
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

#### Actual HTTP access-control responsibility

Source observations at master `3793eeb8c7a9f1ddfc905c972500a4cfe2b86e77`:

- `packages/onlyalpha-http-server/src/onlyalpha_http_server/app.py` constructs FastAPI and includes the Market Data router
  without a demonstrated Product-user authentication dependency or unified caller middleware.
- `.../market_data/routes.py` delegates directly to the Product service. Its Integration reference is a Source locator,
  not caller identity or a subject entitlement. Candidate 401/403 DTOs do not supply either proof.
- `.../agent_provider_runtime.py` authenticates a bearer credential only for its internal Agent runtime authority; that secret
  and its scope are not a human Chart session or a Source permission and must not be reused for W3.
- `packages/onlyalpha-web-console/vite.config.ts` proxies same-origin `/api` to the configured HTTP target. It authenticates
  no caller and asserts no Source entitlement. Same-origin/loopback routing does not establish a protected local application.
- The canonical Compose topology supplies internal Agent tokens, not a proved human Chart subject or subject-to-Source mapping.
  No reviewed external authenticating proxy configuration is supplied by these files. This is missing protection evidence,
  not proof that a particular deployment is publicly exposed.

Infrastructure owns the trusted ingress/session/credential boundary and prevention of direct bypass. HTTP owns authentication
and propagation of the verified subject; the Product boundary owns enforcement of its explicit Source entitlement before any
lookup/read/compute. Market Data still owns Source/revision/fact truth. Web consumes the credential/session through the formal
API client, never asserts that an Integration ID, `X-User` header or browser context confers permission.

Before implementation enables either Chart endpoint, the concrete caller mechanism and exact Source grant relation must be
selected and proved. A proxy integration needs authentication, removal of client-supplied identity headers, authenticated
subject propagation, and an inaccessible direct-API bypass. A local authenticated application needs an actual credential/session
boundary, appropriate origin/CSRF protection for its transport, and explicit Source grants. No default-public, hardcoded
`allow=true`, unbounded allowlist or reuse of internal Agent authority is admitted. If neither mechanism can be proved, keep
the compute surface disabled and identify the unmet gate in the Draft PR; do not fabricate an authentication architecture.

| Obligation | Owning implementation/test boundary | Required failure evidence |
|---|---|---|
| Trusted subject | Infrastructure ingress + HTTP adapter + real Browser credential/session flow | Missing/invalid/forged credential, identity-header injection, expired/revoked session as applicable; authentication failure before Source reads |
| Subject/Source relation | Explicit authorization policy enforced by Product/HTTP, not Integration discovery | Valid subject denied another Source or exact grant scope; 403 without data leakage or computation; multi-subject isolation |
| Input/resource budgets | HTTP bounded body before decode; Application window/period/Decimal validation; process/deployment CPU/memory guard | Oversized streamed/chunked body, rows/period, malformed/high-cost Decimal, concurrent saturation, reentry; rejection before work and a bounded queue |
| Deadline/cancellation | HTTP/Application disposable Query execution | Deadline/disconnect discards values, releases budget safely, does not admit replacement work while abandoned work consumes the slot, and changes no Research state |
| Browser integration | Generated Product client + Shipping Workspace E2E using the same admitted caller boundary | Successful authorized SMA20 path plus unauthenticated/forbidden path; no fixture family substitution, credentials in bundles/logs, or browser-auth bypass |

Concrete concurrency/deadline and deployment resource protection require executable evidence, not an unmeasured latency SLA.
The access-control mechanism is not established by ADR approval itself. The owner selected minimal local authentication with
design review first; the implementation design below does not claim it already exists. Absent executable identity/Source-grant
and containment evidence still blocks enabling production Query support.

#### Minimal local operator authentication — implementation design

This is the selected A1 implementation direction, not an installed authentication service or a general multi-tenant identity
platform. Infrastructure supplies one explicitly configured local human subject and its bounded exact Source grants. HTTP
authenticates the credential; Product enforces the grants. No login database, public registration, Agent token reuse, new LIVE
role or implicit authorization through Integration discovery is introduced.

The process reads an owner-provisioned private configuration once at startup; missing, malformed, duplicate or unsafe
configuration disables transient support. The configuration contains schema version 1, a nonempty subject ID, the SHA256
digest of an independently provisioned cryptographically random 256-bit bearer credential, and explicit Source grants. Each
grant binds Integration ID, exact Integration Revision fingerprint, expected type, canonical Source ID and environment; no
wildcard, newest-revision fallback or grant inferred from an observed Source is allowed. It grants only closed-history read and
display-only evaluation. Any material configuration/credential change replaces the process composition; never mutate an active
request's grants. Permission checks precede source lookup, and returned canonical Source ownership must match the exact grant
before numerical work or response release. A complete denied binding is forbidden, not Source absence.

Credential provisioning uses a cryptographically secure generator, not a human password whose entropy is merely asserted.
Configuration is bounded, owner-controlled, non-symlink and privately permissioned; startup rejects an unsafe file rather than
loading partial grants. Bearer syntax/size is checked before hashing, and digest comparison is constant-time. Failures and
diagnostics reveal neither the credential/digest nor private configuration paths. No credential is generated implicitly at
HTTP startup or embedded into a frontend build.

Revocation has an explicit Infrastructure cutoff: first remove the old composition from every admitted ingress and disable
its request admission and response release, then admit the replacement. Do not report revocation effective while an old
process remains reachable. In-flight old queries may finish internally but cannot release a protected response after the
cutoff; already released bytes cannot be recalled. Immutable grants are not edited to achieve this: the old process/request
composition is withdrawn. Abandoned work retains its concurrency/resource slot until it actually stops, even when HTTP has
disconnected or its deadline has expired. Deterministic barriers must test replacement before admission, during owning read,
during compute and immediately before response release.

The browser operator explicitly enters the provisioned credential through a password-type local access control. The generated
Product client sends it only in the standard Authorization bearer header to same-origin admitted Product endpoints. There is
no token in URLs, bundles, LocalStorage, SessionStorage, cookies, diagnostics or capability/numeric fingerprints. The browser
keeps it only in session-memory presentation state, discards it on reload/logout, aborts and invalidates pending Study values
on credential replacement, and never sends a caller-authored subject/grant in the evaluation DTO. No cookie/session-login API
is needed for this bounded bearer design; authority comes from the server's configured credential-to-subject relation.

The browser owns a disposable authentication generation in addition to chart incarnation/configuration/request generation.
Logout, replacement and reload invalidate the old authentication generation immediately. Every protected response, including
original Source/instrument/history reads, checks the captured generation before attaching; abort alone is insufficient.
An old credential restored after A→B→A receives a fresh generation, so an earlier delayed response cannot become current.

This local design requires an actually contained local transport: production access is loopback-only on the operator machine,
or separately proved encrypted/authenticated ingress with no direct bypass. Accepting an arbitrary Origin or forwarded header,
binding publicly over cleartext, or treating a Docker service name as local-trust evidence is not permitted. Browser Origin is
validated against the exact admitted origin, not reflected as a wildcard; bearer credentials are not ambient cookies, and
cross-origin credential-bearing requests must be denied. Isolated canonical test services may use synthetic credentials over
their controlled local test network; that proves behavior, not safe production transport or deployment authorization.

An absent Origin on a legitimate same-origin GET or a non-browser API request does not authenticate the caller: the exact
bearer and grant are still mandatory. A supplied `null`, malformed or different Origin is rejected. Origin/header checks are
transport defense, never substitutes for the credential. Tests cover ordinary Browser GETs that omit Origin as well as forged
or cross-origin requests, without silently accepting arbitrary forwarded identity/transport assertions.

Containment and Source access must be tested across the real Shipping Workspace's owning Source-list/instrument/history read
paths as well as both new Chart Queries. If an unprotected alternate read route can bypass the intended Source grants, the
identity boundary is not closed: implement the necessary same-source HTTP/client protection atomically within that impact
scope, or keep support disabled. Do not claim that protecting two new endpoints secures the entire existing Product API.
The new read/evaluation credential does not authorize Acquisition, W6 commands, Agent operations or any Trading mutation;
preserve their separate authorities rather than treating authentication as their execution permission.

Before implementation admission, independent design review must confirm the exact startup/credential/grant relation, local
transport assumptions, affected owning read routes, and resource enforcement. Executable tests then cover missing/wrong/revoked
credential, forged subject/header/origin, wrong Source/revision/environment, duplicate grants, config replacement and browser
logout/A→B→A. They must show no backend/source read on an unauthorized request, no credential leakage, no bypass through the
same-source read plane, no Research/Work writes, and no usable capabilities before numeric/composition admission. Configuration
file paths and credential digests are not API fields or market/numeric identities.

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
