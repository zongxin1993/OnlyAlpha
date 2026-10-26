# ADR 0138: Chart Study Transient Evaluation and Formal Research Separation

- Status: Accepted
- Date: 2026-10-11
- Decision maker: repository owner
- Constitution Impact: NO
- Related: ADR 0069, 0092, 0094, 0110, 0112, 0114, 0135, 0136, 0137
- Limited supersession: ADR 0136 Chart boundary and Rejected alternatives **only for non-Research W3 display evaluation**; clarification of ADR 0094's source direction and ADR 0137's scope; explicit ADR 0114 legacy-CONTEXT admission clause below. Formal Research publication and execution contracts are unchanged.

## Owner decision

On 2026-10-11 the repository owner explicitly approved D1–D9 of the decision packet and these limited amendments in the task conversation:

> 我批准裁决包 D1–D9 及 ADR0138 的限定修订，并授权按附件启动独立 W3-A1 Draft PR；不授权自动合并或部署。

This decision, not PR119's merge, authorizes adoption and an independent W3-A1 Draft PR. It does not certify implementation,
numeric provenance, authentication, resource bounds, browser usability or W6 completion. Deployment, automatic merge, production
Claim grants and changes to L0 remain outside that authorization. D8 requires a proved trusted caller/source-entitlement boundary;
absence of that proof blocks enabling the Query, rather than implying public access is acceptable.

The owner subsequently selected **minimal local authentication**, with design review before implementation. This authorizes
designing a real local human credential/subject and explicit Source grants; it does not establish a configured identity boundary
or permit reuse of Agent secrets. The concrete design and remaining proof obligations are specified in the accompanying design.

## Owner-approved registered-indicator extension (2026-10-16)

The owner approved the subsequent indicator plan and instructed execution in the task conversation. This extends the
original A1 SMA-only/closed-only sequencing below to the fourteen existing indicator families: SMA, EMA, WMA, RSI, ATR,
ROC, rolling return, rolling volatility, Z-score, OBV, VWAP, MACD, Bollinger Bands and Stochastic. The remaining A1 text
records its initial boundary; this section supersedes only that type/output/preview restriction. New indicator families,
private Factor/DAG execution and scientific Research readiness admission are not granted by this extension.

The same installed Calculation registry publishes an explicit Chart support projection: default variant/parameters,
numeric output roles, units, placement, colors and optional paired band fill. One Study owns its selected output members;
MACD lines/histogram, Bollinger lines/fill and Stochastic K/D remain grouped presentation. Web neither implements formulas
nor infers defaults or semantics from indicator names. Chart price-field selection remains CLOSE; volume inputs required
by OBV/VWAP come from their registered bindings. Existing semantic versions retain their mathematics. Wilder RSI/ATR,
standard MACD histogram, smoothed Stochastic and UTC-day VWAP use new explicit semantic versions. Provider-content changes
have their own Provider version. No highest-version or legacy fallback is an admission rule.

A structural Chart backend operation returns atomic values/readiness without granting formal Research readiness support
or issuing Research facts. The existing scientific readiness allowlist and publication requirements remain unchanged.
The invocation's registered numeric contract permits CONTEXT resolved by CONTEXT_HALF_EVEN_V1 or explicit ROUND_HALF_EVEN,
with the same exact precision/quantum and Core Decimal envelope. Its implementation closure includes this invocation,
Chart support metadata and the owning preview reader. Shared resource checks may be deduplicated within one verification
pass; no elapsed-time cache or cross-request stale proof is permitted. Each request revalidates its exact composition and
owning inputs before release.

Optional unclosed preview selects only an already-open owning Market Data stream by opaque stream identity. The server
checks the same human subject, exact Source/Revision/Instrument/BarSemantic and REALTIME_PREVIEW grant, reads its retained
snapshot, and computes against the same verified finite closed window. It neither opens a stream nor acquires history.
The preview must immediately follow the closed window and have the exact duration. An updated, closed, disconnected,
degraded or revoked snapshot cannot be released. Ordinary preview replacement discards only the preview; the independently
verified closed result remains usable. Authorization withdrawal still fails closed. Preview rows carry separate
PREVIEW_UNCLOSED/closed=false quality, never closed-history quality or scientific evidence. Browser preview events only
schedule a fresh bounded Query; they supply no price inputs.

The development-unfrozen HTTP schema evolves atomically to version 2 with exact type/version, bounded typed parameters,
selected output members and nullable owning stream identity. Error envelopes remain version 1. No compatibility loader,
persistent Study schema, database migration or additional Compose topology is introduced. Historical input stays bounded
to 2000 rows, integer parameters to 10000, one actual invocation at a time, and the registered backend enforces a finite
work budget before calculation. Authentication, the existing query deadline and all immutable-history/source fences remain.

## Owner-approved temporary chart input boundary (2026-10-23)

The owner explicitly approved ordinary chart display using only bounded in-memory
Provider input and instructed implementation. This changes the W3 input selection
restriction below: ordinary chart navigation, paging, realtime and reconnect do not
automatically read retained history or submit Acquisition Commands. They use a
separately typed, versioned temporary Product Query/subscription. Source grants,
exact installed implementations, canonical bar construction and registered
Calculation semantics remain mandatory. Temporary windows/results are DISPLAY_ONLY;
their fingerprints are not sealed history, Dataset or Research evidence.

Formal acquisition keeps its existing Recorder and real WAL append+fsync-before-release
contract. A distinct temporary Provider entry accepts no durable Recorder and issues
no durable receipt. Formal Research explicitly prepares/freezes immutable inputs;
it cannot promote an in-memory chart window into evidence. The lifetime and
non-persistence boundary is specified in `market_data_source.md`. Registration
composition, numeric provenance and outward authorization fences remain unchanged.

## Context

Adding SMA20, changing its period or displaying a momentum curve is an observation workflow, not implicit consent to durable Research.
Explicit Research has a different purpose: frozen inputs, exact execution provenance, recoverable Run/Attempt and scientific publication.
ADR 0135 and Web Product Development Mode distinguish W3 Indicator/Factor from W6 Research on chart, but ADR 0136's first Chart
integration expressly requires sealed inputs and Engine-hosted Research and rejects Preview/HTTP evaluation. A production transient
route therefore needs an explicit owner decision, recorded above, not an inference from a merge or a generic instruction to continue.

Current source relations and the normative constraint matrix are in the accompanying
[design](../superpowers/specs/2026-10-11-chart-study-transient-evaluation-design.md).
The [slice and acceptance plan](../plans/chart-study-transient-evaluation.md) specifies future proofs, not completion status.
Architecture adoption is distinct from implementation admission. Source observations below describe prerequisites, not availability.

## Decision

### 1. Two workflows, one set of canonical semantics

W3 is a bounded, read-only Chart Product Query. Its reference values are numerically correct, source-bound and explicitly
`DISPLAY_ONLY`, but not a persistent scientific publication. Failure to create Research is not an excuse for inaccurate numbers.
Cache loss and browser refresh may discard the projection; no critical durable truth is moved into that cache.

W6 starts only when the user explicitly submits a formal Research command. It owns frozen input preparation, immutable
Specification, original Runtime Work, Run/Attempt/lease, verified Calculation Result/Execution Evidence/Research Result/Artifact,
terminal acknowledgement and recovery. Chart display may consume that evidence through the existing verified Query boundary.
Adding/editing/hiding a Study does not submit this command.

```text
W3: ChartStudy intent -> versioned Chart Product Query
    -> owning Market Data selection + verified bounded read
    -> exact registered canonical Calculation backend
    -> typed CHART_STUDY_TRANSIENT / DISPLAY_ONLY values + quality
    -> strict Web adapter -> Lightweight Charts

W6: explicit Create Research -> revalidated intent -> frozen inputs + Specification
    -> original Work + Run + owning Attempt -> installed Research execution
    -> verified Result/Evidence/Artifact + fenced terminal ACK
    -> exact Research Query -> optional RESEARCH_VERIFIED chart overlay
```

Strategy/Backtest/SIM/LIVE retain their own formal input, revision, execution and authorization boundaries. Neither transient
values nor a matching DTO/cache hash authorize any of them. A1 grants no Agent SIM/LIVE permission or new trading endpoint.

### 2. Authority and capability

| Responsibility | Owner | Forbidden substitution |
|---|---|---|
| Integration Revision, Market Source, facts, data corrections, range/quality | Existing Integration / Market Data authorities | Uploaded Bars, browser context key, provider clock or a stream close as a Seal |
| Definition, normalized typed parameters, output semantics, Decimal rules | Existing Calculation contracts and exact `onlyalpha.calculations` SPI registrations | HTTP/JS formulas, type-name heuristics, frontend defaults |
| Bounded transient execution and provenance/quality projection | Application Chart Query, using those authorities | Scientific store writes or fabricated execution seals |
| Study instance, visibility, style, pane, selection | Browser Workspace presentation owner | Calculation/Research identity or permission |
| Formal Research operational and scientific facts | Existing Research/Runtime/Scientific authorities | Transient series, caches or test fixtures |

A1 must pin one immutable server-process registration composition for each request: exact descriptor/Definition resolver,
backend, Provider content/version, implementation manifest and Decimal execution context. It reuses the installed registered
`onlyalpha.indicator.sma@1` RESEARCH **batch implementation**, including its value/readiness output. That backend label does
not itself create a Research Run. A narrow non-publishing Application adapter may validate and project its output; it must not
call the Research executor's issuance/private seals or materialize a Dataset/Result as a workaround.

This is an explicitly authorized non-publishing use of an existing SPI, not a claim that a production Product Query exists.
No new backend/runtime enum, duplicate SMA formula, generic evaluator or arbitrary code-loading endpoint is authorized.
The adapter is Core/Application orchestration, not a concrete plugin import. Installed manifests and Provider/Catalog relations
must agree before invocation. Changed content requires a new Provider version; changed semantics additionally require a new
Calculation semantic version. No `latest`, in-place reload, missing-version fallback or active-generation rebinding is allowed.
Process replacement admits new requests only; a request cannot mix old/new registrations.

Existing SMA@1 is **not yet eligible under this deterministic binding**: its Definition declares `rounding=CONTEXT`,
the batch kernel uses ambient Decimal state, and its implementation manifest lacks the canonical policy dependency. Reuse alone
does not solve this. The accompanying design §4 fixes a versioned resolution of CONTEXT to explicit ROUND_HALF_EVEN,
precision from the unchanged Definition and the existing Core envelope `onlyalpha.decimal.execution@1`. It is an explicit
execution input/binding, not a mutated Definition or a second Decimal policy. Admission requires actual implementation-manifest
closure over this context policy and invocation code; the old manifest must never be reported as if it already carries that proof.
Any new Provider content/manifest requires a new Provider version, and any Definition/algorithm semantic change additionally
requires a new Calculation semantic version. A1 must reject the current unproved binding until this separately authorized repair
and hostile-context validation exist. No historical Research output under unspecified CONTEXT is claimed equivalent or rewritten.

The current Research picker `AVAILABLE` witness remains a Research metadata witness, not transient permission. A1 requires a
separate **projection of transient support from the same registry**, not a second registry: exact type/version/output, descriptor
and implementation binding plus the bounded supported shape/readiness policy. Discovery alone stays `REGISTERED_NOT_CONNECTED`.
No active Research Runtime or PR118 Claim is a prerequisite for W3. Private Factor execution remains outside A1; later slices
must separately satisfy exact admitted Revision/Provider/Catalog/Runtime and sandbox boundaries, not reuse this public SMA exception.
HTTP startup must retain the verified process-local Provider/Catalog composition used to construct those same registrations;
today's retained registry alone is insufficient. Capabilities issue a projection fingerprint of the whole binding/support/numeric
policy tuple. Evaluation echoes it and compares full owning proof, even when descriptor/implementation fingerprints alone match.

### 3. Exact adopted amendments

The owner approved the following limited wording. The corresponding Accepted ADRs and directly dependent L1 contracts carry
the same scope restriction; this decision does not amend their W6 publication, identity, Engine or recovery rules.

**ADR 0094, Financial Time-Series / Recommended data direction:**

> Verified Artifact -> Research Query remains mandatory for scientific Research overlays. A separately admitted Chart Study
> Product Query may provide `CHART_STUDY_TRANSIENT` display-only series through strict Web projection and the same Lightweight
> Charts adapter. The UI must distinguish them from `RESEARCH_VERIFIED`. Neither source permits browser semantic computation
> or renderer output to flow backward into scientific or execution Authority.

**ADR 0136, Context / Lifecycle and recovery / Chart boundary:**

> These Research lifecycle, immutable Dataset/Seal and publication requirements apply to formal Chart Research (W6), including
> calculation-only Result/Artifact publication. They are not a mandatory lifecycle for ordinary W3 Study configuration/display.
> Only the separately admitted W3 transient Query may execute a registered canonical backend over owning Market Data reads
> without creating Research facts. Its output is DISPLAY_ONLY, is not a Result, and cannot satisfy publication or promotion.
> A1 supports closed historical batch input only; unclosed Preview and incremental execution require a later approved slice.

**ADR 0136, Rejected alternatives:**

> HTTP handlers remain forbidden evaluators. The limited W3 exception is a thin schema/authorization adapter delegating to a
> bounded Application Chart Query and exact server-side Calculation SPI; it is not permission for HTTP to execute formulas,
> read stores directly, bypass Engine for W6, or counterfeit a sealed Research input/publication. Browser SMA and stream/page-as-Seal
> remain rejected. W6 identities, fingerprints, Result profiles, final-publication and recovery requirements remain unchanged.

**ADR 0137, Decision / Rejected alternatives:**

> Its Result2/Evidence2/readiness publication requirements and SMA-only production Research readiness scope remain unchanged.
> A non-publishing W3 adapter may project values/readiness produced atomically by the exact supported backend, but that structural
> projection is not Execution Evidence2, Research Result4 or Artifact2. Numeric-only output cannot be annotated by Web/Query with
> guessed warmup. The exception does not register readiness for EMA/RSI/MACD or approve arbitrary Factor/DAG/cross-section execution.

**ADR 0114, Per-Calculation numeric context / implementation dependency:**

> The Core Decimal envelope and manifest-dependency requirement remain unchanged. For a separately admitted non-publishing W3
> invocation of a legacy Definition declaring CONTEXT, a versioned binding may explicitly resolve that placeholder to
> ROUND_HALF_EVEN before constructing the Core context; precision and quantum still come from the exact Definition. The binding
> records both declared and effective rounding and the resolution policy, without rewriting Definition fingerprints. No caller
> context is copied. The effective invocation's actual manifest closure must bind the Core policy and resolution/invocation code;
> missing closure blocks support. This adds no Research publication exception or general permission to resolve other unspecified
> numerics. Any actual semantic change requires a new Calculation version; Provider-content changes require a new Provider version.

**Related L1/other documents:** ADR 0092 and `web-product-architecture.md` scientific Result read rules remain unchanged;
their scientific chart language must not be generalized to say transient values are scientific facts. The adopted amendment adds
the explicit parallel non-scientific source to `chart-catalog-navigation-contract.md` without changing test-fixture ownership or
claiming discovery is execution admission. Scope the 2026-10-01 W3-B Proposed design to W6 formal Chart Research; its Research
admission/preparation/Compilation contracts stay intact. ADR 0135 already supplies the product sequencing, not this exception.

The recorded owner approval covers these limited scope changes, the non-publishing SPI invocation/composition policy and the
API/quality semantics below, including legacy Decimal resolution and its real provenance prerequisite. API implementation and
support still require their respective admission proofs. Acceptance of W3 does not certify PR118 or amend W6. If implementation discovers a
Constitution or higher-level contract conflict that cannot be resolved within these boundaries, stop with `PLAN_CONFLICT`.

### 4. Product contract and display semantics

Recommend `POST /api/v2/chart/studies/evaluate` for bounded typed JSON **Query** input, not a durable Command. The candidate
request/response, strict error matrix and alternative GET assessment are specified in the accompanying design, not added to
OpenAPI here. No Research admission, idempotency receipt, queue, acquisition or persistent query-result store is created.
Authentication, subject/source authorization, input/CPU/memory bounds and failure diagnostics still apply to a POST Query.

Both capabilities and evaluation require a trusted caller identity. The HTTP adapter authenticates that identity; Source access
is checked against an explicit subject-to-Source entitlement before source lookup or computation. Integration IDs, browser
context keys, loopback addresses and the existing internal Agent bearer credential are not substitutes. An external proxy is
trusted only with proved authentication, header stripping, an inaccessible bypass path and exact subject propagation. A local
application boundary likewise needs explicit credential/session and Source authorization proof; same-origin routing alone is
not authentication. Without that boundary, no transient support or production compute endpoint may be enabled. Detailed source
observations and test ownership are in the accompanying design's access-control section.

Input selects exact Integration Revision, Instrument, BarSemantic, fixed closed historical window, registration type/version,
typed parameters and real output member. It cannot provide raw Bars, scripts, package paths, credentials, evidence or Run IDs.
The server resolves Source and reads the full pinned evaluation window, including explicit warmup scope; viewport only crops output.
The response binds source selection, exact verified data revision evidence/history projection, resolved window, backend/implementation
and normalized Definition, ordered UTC nanoseconds, exact Decimal text/null, point readiness/reason, quality and `closed=true`.
Every response states `source_kind=CHART_STUDY_TRANSIENT`, `authority=DISPLAY_ONLY`, `publication_status=NOT_A_RESEARCH_RESULT`.

Incomplete mandatory input or source proof never becomes a valid numeric series, certified absence or evidence of an invalid Factor.
A1 uses explicit finite-series initialization; PARTIAL can be a valid output at that known start, not a repair for an unknown gap.
Detailed bounds and these distinctions are in the design. Live market Bars may continue on the main chart, but no unclosed Study
values are returned in A1. A4 preview must carry a distinct `PREVIEW_UNCLOSED` quality, never implied by reusing A1's closed label.

The Web extends the presentation source discriminant explicitly; production responses cannot masquerade as
`CONTROLLED_TEST_EVIDENCE`. It must admit generated-client DTOs before renderer mapping and fence chartContextKey,
incarnationKey, configurationKey, request generation and current data/registration binding. Old asynchronous results cannot
attach after source/instrument/semantic change or A->B->A context restoration. Multiple identical configurations may share immutable
numeric projection, but retain distinct display instances. Hide/color/pane/selection never calculate or resubscribe.
No JS array-index warmup, numeric truthiness, interpolation, resampling or forward-filled missing values is permitted.
Only plotting uses explicit lossy number/seconds conversion; hover retains admitted exact Decimal/time text.

### 5. Cache, lifecycle and promotion

The owner's Rust workbench stabilization decision permits a process-local, fixed installed catalog declaration projection.
Its first publication requires the exact isolated worker handshake, complete catalog admission and successful worker termination.
The projection binds the complete observed declaration to the fixed installation and native invocation identities; a conflicting
declaration cannot replace it. Every metadata read still freshly verifies the complete installation, interpreter, runtime and
environment bytes, exact declared resources and capability projection. Missing, changed or unavailable proof rejects the read.
This retains declarations only: no freshness, worker availability, Source entitlement or scientific readiness proof is cached.
Metadata admission retains the same capacity, deadline, authorization and shutdown boundaries. Every actual calculation request
starts an isolated worker and freshly admits its observed catalog against the fixed declaration. Restart discards the projection;
there is no disk cache, TTL, latest substitution or fallback.

The owner additionally approved bounded temporary Chart Study batches of one to four calculations over one exact closed window.
Each batch owns one fresh isolated worker, retains each item's independent Definition, implementation, numeric binding and
value/readiness validation, and never reuses that worker for another request. Ordered request indexes correlate display intents;
they do not confer Calculation identity. Only per-item request rejections proved by Rust validation may preserve siblings; unclassified worker rejections refuse the whole response.
Missing, changed or unavailable shared Source, window, installation or registration proof rejects the entire batch. The response
is released only after all items are checked, the worker is joined and the original authorization/input fence and installation
are revalidated. Each request retains the ten-second budget and owns one fresh worker. The shared invocation gate admits at most two concurrent requests, including metadata reads, and holds each permit until its worker is joined. This adds no Research facts,
durable input, price persistence, fallback, browser mathematics or new registered indicator families.

A1 needs no server cache. Later non-authoritative caches key full Source/Integration Revision, Instrument, BarSemantic/plan/calendar,
resolved evaluation window/init policy, verified effective data revisions/history fingerprint/watermark, Definition/parameters/output,
Provider/Catalog/implementation binding and closed/preview mode. Style and instance ID are excluded. No TTL proves freshness.
Cache hits must verify the current owning data/registration binding; unknown/unavailable proof refuses reuse. Backfill, revision,
parameter or implementation changes invalidate; failures and incomplete proof are not negative scientific cache entries.
Eviction/restart recomputes from owning reads, never reconstructs or certifies durable history from local missing files.

Explicit Create Research transfers only revalidated **intent** (source selection, instrument, semantic, window, parameters/output).
The Research boundary re-resolves its own admission, freezes its own inputs and executes through its own original Work/Attempt.
No transient value/hash, success status or readiness carrier is accepted as scientific evidence, even with identical numbers.

## Consequences, alternatives and implementation admission

- W3 can close a real SMA user flow independently of W6. PR118's closed Claim/Heartbeat foundation was merged before PR119;
  it does not complete W6's installed execution, terminal acknowledgement, recovery or Work-release lifecycle. Historical source
  comparison SHAs remain in the design; correctness and source validation remain essential.
- Preserve existing scientific identities, renderer family and Trading/GENERAL/PRIVATE_STRATEGY behavior; no compatibility shim,
  new database/Compose topology, trading capability or Chart production Claim grant is needed.
- Reject automatic Research per edit, browser formulas, untrusted input arrays, fixture leakage, HTTP store access, a second
  Calculation registry, numeric equality as execution permission, and expanding all indicators before one complete slice.
- Reject GET with serialized parameter JSON as the primary endpoint: complex structured semantics and bounded typed validation
  are clearer in JSON; URL length/logging and ambiguous encoding add avoidable risk. GET remains a viable read transport only
  with the same exact contract, not a separate evaluator. POST must not be wired into Command admission by verb alone.
- The recorded owner decision authorizes an independent W3-A1 Draft PR and atomic contract/consumer implementation. Architecture
  acceptance is not numeric, security or product acceptance, and grants no automatic merge or deployment authority.

**Admission boundary:** numeric/manifest/composition, trusted caller/source entitlement, resource bounds, zero durable writes and
real Browser proofs must all hold before W3 is declared usable. Neither real W3 numeric lines nor full W6/B2 completion are
certified by this ADR.
