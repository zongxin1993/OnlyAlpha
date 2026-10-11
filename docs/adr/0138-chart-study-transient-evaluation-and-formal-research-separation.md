# ADR 0138: Chart Study Transient Evaluation and Formal Research Separation

- Status: Proposed / Owner Approval Required
- Date: 2026-10-11
- Decision maker: repository owner (approval not recorded)
- Constitution Impact: NO
- Related: ADR 0069, 0092, 0094, 0110, 0112, 0114, 0135, 0136, 0137
- Proposed limited supersession: ADR 0136 Chart boundary and Rejected alternatives **only for non-Research W3 display evaluation**; clarification of ADR 0094's source direction and ADR 0137's scope; explicit ADR 0114 legacy-CONTEXT admission clause below. Nothing is superseded while this ADR remains Proposed.

## Context

Adding SMA20, changing its period or displaying a momentum curve is an observation workflow, not implicit consent to durable Research.
Explicit Research has a different purpose: frozen inputs, exact execution provenance, recoverable Run/Attempt and scientific publication.
ADR 0135 and Web Product Development Mode distinguish W3 Indicator/Factor from W6 Research on chart, but ADR 0136's first Chart
integration expressly requires sealed inputs and Engine-hosted Research and rejects Preview/HTTP evaluation. A production transient
route therefore needs an explicit owner decision, not an implementation interpretation of a conversation or an unaccepted design.

Current source relations and the normative constraint matrix are in the accompanying
[design](../superpowers/specs/2026-10-11-chart-study-transient-evaluation-design.md).
The [slice and acceptance plan](../plans/chart-study-transient-evaluation.md) specifies future proofs, not completion status.
This is DOC-ONLY / DESIGN-ONLY / NOT_APPROVED / NOT_IMPLEMENTED.

## Proposed decision

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
| Bounded transient execution and provenance/quality projection | Proposed Application Chart Query, using those authorities | Scientific store writes or fabricated execution seals |
| Study instance, visibility, style, pane, selection | Browser Workspace presentation owner | Calculation/Research identity or permission |
| Formal Research operational and scientific facts | Existing Research/Runtime/Scientific authorities | Transient series, caches or test fixtures |

A1 must pin one immutable server-process registration composition for each request: exact descriptor/Definition resolver,
backend, Provider content/version, implementation manifest and Decimal execution context. It reuses the installed registered
`onlyalpha.indicator.sma@1` RESEARCH **batch implementation**, including its value/readiness output. That backend label does
not itself create a Research Run. A narrow non-publishing Application adapter may validate and project its output; it must not
call the Research executor's issuance/private seals or materialize a Dataset/Result as a workaround.

This is an explicitly proposed new use of an existing SPI, not a claim that the current Product Query already permits it.
No new backend/runtime enum, duplicate SMA formula, generic evaluator or arbitrary code-loading endpoint is proposed.
The adapter is Core/Application orchestration, not a concrete plugin import. Installed manifests and Provider/Catalog relations
must agree before invocation. Changed content requires a new Provider version; changed semantics additionally require a new
Calculation semantic version. No `latest`, in-place reload, missing-version fallback or active-generation rebinding is allowed.
Process replacement admits new requests only; a request cannot mix old/new registrations.

Existing SMA@1 is **not yet eligible under this proposed deterministic binding**: its Definition declares `rounding=CONTEXT`,
the batch kernel uses ambient Decimal state, and its implementation manifest lacks the canonical policy dependency. Reuse alone
does not solve this. The accompanying design §4 fixes a proposed versioned resolution of CONTEXT to explicit ROUND_HALF_EVEN,
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

### 3. Exact owner-approval amendments

The following wording is proposed for formal adoption. It is **not** an amendment to the existing files in this PR.

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
their scientific chart language must not be generalized to say transient values are scientific facts. Upon approval, add the
explicit parallel non-scientific source to `chart-catalog-navigation-contract.md` without changing test-fixture ownership or
claiming discovery is execution admission. Scope the 2026-10-01 W3-B Proposed design to W6 formal Chart Research; its Research
admission/preparation/Compilation contracts stay intact. ADR 0135 already supplies the product sequencing, not this exception.

Owner approval must explicitly cover these limited scope changes, the non-publishing SPI invocation/composition policy and the
candidate API/quality semantics below, including this legacy Decimal resolution and its real provenance prerequisite.
Acceptance of W3 does not approve PR118 or amend W6. If implementation discovers a
Constitution or higher-level contract conflict that cannot be resolved within these boundaries, stop with `PLAN_CONFLICT`.

### 4. Product contract and display semantics

Recommend `POST /api/v2/chart/studies/evaluate` for bounded typed JSON **Query** input, not a durable Command. The candidate
request/response, strict error matrix and alternative GET assessment are specified in the accompanying design, not added to
OpenAPI here. No Research admission, idempotency receipt, queue, acquisition or persistent query-result store is created.
Authentication, subject/source authorization, input/CPU/memory bounds and failure diagnostics still apply to a POST Query.

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

A1 needs no server cache. Later non-authoritative caches key full Source/Integration Revision, Instrument, BarSemantic/plan/calendar,
resolved evaluation window/init policy, verified effective data revisions/history fingerprint/watermark, Definition/parameters/output,
Provider/Catalog/implementation binding and closed/preview mode. Style and instance ID are excluded. No TTL proves freshness.
Cache hits must verify the current owning data/registration binding; unknown/unavailable proof refuses reuse. Backfill, revision,
parameter or implementation changes invalidate; failures and incomplete proof are not negative scientific cache entries.
Eviction/restart recomputes from owning reads, never reconstructs or certifies durable history from local missing files.

Explicit Create Research transfers only revalidated **intent** (source selection, instrument, semantic, window, parameters/output).
The Research boundary re-resolves its own admission, freezes its own inputs and executes through its own original Work/Attempt.
No transient value/hash, success status or readiness carrier is accepted as scientific evidence, even with identical numbers.

## Consequences, alternatives and approval gate

- W3 can close a real SMA user flow independently of the unmerged W6 Draft; correctness and source validation remain essential.
- Preserve existing scientific identities, renderer family and Trading/GENERAL/PRIVATE_STRATEGY behavior; no compatibility shim,
  new database/Compose topology, trading capability or Chart production Claim grant is needed.
- Reject automatic Research per edit, browser formulas, untrusted input arrays, fixture leakage, HTTP store access, a second
  Calculation registry, numeric equality as execution permission, and expanding all indicators before one complete slice.
- Reject GET with serialized parameter JSON as the primary endpoint: complex structured semantics and bounded typed validation
  are clearer in JSON; URL length/logging and ambiguous encoding add avoidable risk. GET remains a viable read transport only
  with the same exact contract, not a separate evaluator. POST must not be wired into Command admission by verb alone.
- This proposal grants no implementation, acceptance, merge or deployment authority. Owner must approve it explicitly; any resulting
  Accepted ADR edits and API implementation require a separately authorized atomic consumer change.

**Approval boundary: AWAITING_OWNER_ADR_APPROVAL.** Neither real W3 numeric lines nor full W6/B2 completion are claimed here.
