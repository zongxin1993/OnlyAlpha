# Chart Catalog navigation

The chart's Indicator/Factor picker is metadata navigation, not Calculation admission or execution.
It submits no command, acquires no market data and publishes no numeric output, point readiness,
Research Run, Result or Artifact. A selected item is a browser-only configuration draft passed to
the workspace's parameter editor, not a persisted Study or execution permission.

## Registered discovery without Runtime activation

When the active Runtime query formally reports `RUNTIME_GENERATION_NOT_ACTIVE`, the picker reads
`GET /api/v2/research/catalog/calculations`. This existing current-process discovery query describes
registered Calculation types, versions, parameter defaults and input/output metadata. It is not an
exact immutable Catalog projection and grants no implementation binding, readiness or execution
permission. Calculation kind follows the server DTO; it is not a Provider-layer classification.

These entries remain searchable and selectable **as browser-only configuration drafts**. They are
shown as registered / execution not connected, never `AVAILABLE`. A discovery draft carries its
registered descriptor and type/version identity, but no Runtime/Catalog fingerprint, implementation
fingerprint or readiness witness. Selection re-reads the discovery descriptor and rejects removed,
changed, malformed or duplicate registrations. Refresh/focus invalidates the old draft.

Missing or invalid exact Catalog proof, stale Runtime and transport failures do not fall back to
discovery. Runtime disappearance at the final exact read fence is stale, not initial absence.
Typed discovery scalars preserve their exact tag/value relation; defaults are not browser-normalized
or admitted execution parameters. A known empty Factor discovery list means no registered Factor was returned by that
query; it does not certify absence of private Draft/Revision assets in other authorities. No example
Factor is injected to fill an empty list.

Parameter editing, Calculation admission/execution and overlay/pane rendering are separate product
capabilities. Neither discovery selection nor exact metadata availability creates a chart series.

## Non-publishing transient support

ADR 0138 defines a separate capability projection from the same immutable process-local Calculation/Provider/Catalog
composition: `GET /api/v2/chart/studies/capabilities`. This is not a second registry, Runtime activation or an upgrade of
discovery/exact Research metadata into permission. Capability admission proves the full descriptor, Definition resolver,
RESEARCH batch implementation manifest, Provider ID/version/content, Catalog generation, numeric policy and supported
shape/readiness/output/limits and the conditional `capability_projection.input_support` policy.
`capability_projection_fingerprint` binds the whole row, including that input policy, in the
`onlyalpha.chart-study.capability-projection` domain. Evaluation compares that entire binding, not only a type name or descriptor.

`POST /api/v2/chart/studies/evaluate` has strictly read-only Query semantics despite POST transport. Supported input is
the exact registered Chart-capable type/version and selected numeric output members from the capability projection,
one instrument from the exact Source catalog, a provider-native aligned fixed-duration BarSemantic and UTC 24x7 calendar
proved by the owning planner, plus a complete verified finite closed historical window. The fourteen-family extension and
its explicit semantic variants are governed by ADR 0138's owner-approved 2026-10-16 section. Default variants/parameters,
series roles/units, grouping and band fill are server metadata; a descriptor alone is not execution permission. Chart
price_field is CLOSE. Required volume/start-time inputs come from the exact registered Definition bindings.

The server verifies the same fixed BEFORE_TIME window and owning history fingerprint. Uploaded prices/scripts and implicit
Acquisition are forbidden. Optional preview references an existing owning stream and needs its exact subject/Source grant;
it never accepts browser Bars. Preview must immediately follow that closed window, remains a separate PREVIEW_UNCLOSED row,
and is discarded when its owner revokes or replaces it. Closed results retain independent closed-history proof.
Atomic backend values/readiness are CHART_STUDY_TRANSIENT / DISPLAY_ONLY / NOT_A_RESEARCH_RESULT. Incomplete historical
input returns explicit coverage and empty series without calculation; missing proof is unavailable, not certified absence
or a proved version change. The strict point relation is: PARTIAL/WARMUP_INCOMPLETE (nullable may be null), READY with a
value/NONE or nullable null/VALUE_UNDEFINED, UNAVAILABLE with null and INPUT_UNAVAILABLE or DEPENDENCY_UNAVAILABLE.

Both APIs require a proved trusted caller boundary and Source entitlement. The server process must enforce bounded body,
window/period, concurrency and deadline/resource protection before backend work. No support is enabled based solely on a
proposed error DTO, ambient Decimal context or assumed proxy protection. The current historical Query bound is 2000 Bars;
10000 is not a supported window or latency promise. The exact access-control prerequisites are in the
[design](superpowers/specs/2026-10-11-chart-study-transient-evaluation-design.md#actual-http-access-control-responsibility).

Transient support is an architectural contract, not a claim that these routes or a production adapter are implemented.
The Research metadata/revalidation and existing configuration-only behavior described below remain independent. Once admitted,
production transient values require a strict generated-DTO adapter plus context/incarnation/configuration/request-generation
and data/registration fences. Style, hide/show, pane and selection changes remain presentation-only and do not calculate or acquire.

### Closed-window readiness

The owning Market Data window planner preserves its explicit-clock minute-floor future-window guard.
For an otherwise valid BEFORE_TIME request beyond that floor, it reports `MARKET_DATA_WINDOW_NOT_CLOSED`.
`GET /api/v2/market-data/bars` and the same owning read through `POST /api/v2/chart/studies/evaluate`
return HTTP 503 with standard `Retry-After` delta-seconds. The service samples its explicit clock once:
`ready_ns = ceil(before_ns / MINUTE_NS) * MINUTE_NS`, then
`retry_after_seconds = ceil((ready_ns - clock_ns) / 1_000_000_000)`. Thus a non-minute-aligned anchor waits
until the next minute at which the existing guard accepts it. Malformed requests remain invalid;
a readiness hint proves neither coverage nor the requested immutable Source/history identity.
Other failures, including authentication, authorization and composition conflict, carry no readiness hint.

The strict browser adapters admit the hint only for this code, QUERY phase and HTTP 503, with a positive
canonical decimal integer that fits the platform's signed 32-bit millisecond timer (at most 2147483 seconds).
Missing, malformed, HTTP-date, zero or excessive values do not schedule a retry and are never clamped.
The chart's existing shared single-flight coordinator allows one server-directed re-observation per exact
closed-window intent. While waiting, `WAITING_FOR_CLOSED_WINDOW` is visible and all old numeric admissions
are retired. The timer only schedules a fresh formal query; elapsed time is never a validity proof.
Two SMA instances share the same deferral. A second not-ready result is terminal for automatic observation.
Context, new close, credential generation and unmount cancel/fence the old timer; presentation changes do
not query or reset its budget. Normal explicit UI recovery remains available. The requested anchor, 2000-bar
window, Source pins, authorization and fresh evidence admission are unchanged.

This is an intentional **development-unfrozen** behavioral contract change from generic HTTP 400
`MARKET_DATA_WINDOW_REQUEST_INVALID` to the distinct HTTP 503 readiness failure for valid future anchors.
The optional standard response header is additive; body schemas are unchanged. Repository consumers,
OpenAPI and generated TypeScript evolve atomically, with no old-version fallback or persisted-format change.
The standard header semantics follow [RFC 9110 section 10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#section-10.2.3).

### Exact catalog metadata batches

The owning durable Catalog exposes `load_sealed_revisions(ids)` and `load_coverage_manifests(ids)`
as ordered, all-or-error exact-ID reads. Empty input returns empty without storage IO; duplicate IDs
are invalid and any missing requested identity fails closed. Singular reads use the same canonical
batch implementation. These are additive development-unfrozen Python Catalog operations; repository
implementations and consumers evolve together. They change no HTTP, database schema or stored identity.

Current-range selection retains its exact family/scope filters and selected revision IDs. The range
reader re-observes those exact IDs in a batch and still compares each stored revision with its selected
value, verifies its Manifest/Seal binding, and checks every ordered Segment ID/content hash. Only those
explicit immutable Segment references are deduplicated for the existing bulk storage read; no overlapping
scope union, latest substitution or cache grants authority. Physical proofs, membership, coverage, native
calendar/Source pins and final history fingerprints remain independently verified. Metadata round-trip
counts are bounded by batch families rather than revision count; this does not change the 2000-bar window,
the 10-second protected query deadline, or establish a wall-clock latency guarantee.

### Internal numeric admission

The disposable Chart adapter retains the actual registrations from one installed Provider discovery and the Catalog built from
those objects. A copied descriptor or a separately discovered Catalog is not that occurrence. Provider factories, declared
implementation resources and Core invocation resources must belong to the declared installed distributions; wheel resources
are checked against RECORD. Editable installations prove only their current project/version/resource bytes, not immutable wheel
or deployment certification. Loaded Python functions, imported call bindings and the backend's numeric constants must agree
with that closure. These coherence checks do not sandbox arbitrary code already controlling the interpreter.

The admitted closed-history entry consumes an opaque handoff issued by the owning Market Data service after its authorized,
complete, fixed-window read. It rechecks the captured session before computation and before releasing values. Ordinary Bars
DTOs, asserted closed flags, browser arrays and raw Arrow arguments cannot manufacture that handoff. The private numeric kernel
exists for structural testing and is not a Product input route. The handoff is disposable: it neither creates a new data Authority
nor certifies earlier history absent. Transport-level cutoff and response fencing remain separate ingress obligations.

`CONTEXT_HALF_EVEN_V1` supplies an invocation-only effective numeric value to the existing Core Decimal context constructor;
the registered legacy Definition and algorithm are unchanged. Explicit ROUND_HALF_EVEN registrations retain that rounding. The real backend manifest binds the resolution, Core policy and
invocation closure. Missing proof is unavailable; only a complete different capability identity is changed. Neither the handoff,
capability identity nor the structural value/readiness carrier is a scientific execution seal or Research publication.

## Exact read relation

`GET /api/v2/research/runtime-generations/active` observes the Runtime Authority's current
`active_for_new_work`. Absence remains `503 RUNTIME_GENERATION_NOT_ACTIVE`.
`GET /api/v2/research/runtime-generations/{runtime_generation_fingerprint}` projects the verified
manifest's exact `catalog_generation_fingerprint` alongside its Runtime identity. These are
different identities and may not be substituted. Missing or malformed binding fails closed;
unknown Runtime remains 404. This additional response field migrates repository consumers and
the generated Product client together; it changes no persisted manifest or activation semantics.

The existing exact Catalog Context and exact Catalog readiness queries own registered descriptors
and backend capability witnesses. Their Catalog identities and context projection identities must
agree. Provider, calculation kind/type/semantic version, backend and implementation identity must
agree for every readiness row; ambiguous/duplicate or orphan identities are validation failures.
Missing readiness is incomplete proof, not successful availability or certified absence.

For the chart configuration entry, `AVAILABLE` means an unambiguous registered TIME_SERIES
RESEARCH capability has exact readiness-contract V1 support. It does not mean numeric values are
READY, that an execution host currently responds, or that later Chart admission will accept the
draft. Other backends/shapes/versions are shown as unsupported, not converted into supported ones.
Parameters and output previews come from exact registered descriptors; no frontend supported-type
allowlist, default parameter override, source-code publication or plugin introspection is allowed.

## Mutable active observation

Opening/refreshing the picker resolves the active relation or registered discovery again. Returning focus to the application
also refreshes an open picker or existing draft. A final active read fences both Catalog loading
and selection. A changed fingerprint invalidates the old results and draft; there is no elapsed-time
TTL, background retry or fallback to installed/current plugin code. These observations are not
an atomic Runtime reservation. Any future execution must separately obtain formal admission.

The renderer and market-data incarnation remain independent of this navigation lifecycle.

## Parameter configuration and display instances

The workspace owns the single pending selection and confirmed `ChartStudyInstance` collection.
The picker publishes a controlled handoff; it does not retain a second selection. The editor has
disposable field inputs separate from confirmed instances. Cancel/Escape discards only those inputs.
Confirm adds an independent browser instance identity; editing preserves that identity. Identical
calculation inputs can have distinct display instances. None of these identities is a Calculation,
Run, Result, Artifact, fingerprint or execution reservation.

The editor adapts exact untagged Descriptor scalars and discovery typed scalars into typed input
intent, preserving raw numeric STRING defaults and DECIMAL text. UI checks cover input shape,
safe INTEGER transport, exact decimal bounds/enum comparisons, required inputs and official output
names. They neither normalize through Core nor certify scientific validity/admission. A required
NULL default is displayed as missing input, not silently replaced with zero, false or empty text.
Malformed metadata/defaults, duplicate names and unavailable outputs block confirmation.

Each confirmation (including presentation-only edits) re-reads the original metadata family via
the formal GET APIs. Discovery requires the complete same descriptor; it is never upgraded using
ambient Runtime identity. Exact mode requires the same Runtime/Catalog/context projection identity and schema fingerprint and
complete selected capability/readiness relation through the existing strict reader and final active
fence. Disappearance, change, malformed proof or unavailable transport blocks confirmation and
marks an edited instance `STALE_CONFIG`. These reads are observations, not execution permission.

Configuration contains only typed parameter inputs and a real output name. Presentation independently
contains placement (`PRICE_OVERLAY` / `SEPARATE_PANE`), `#RRGGBB` color (initially the accent design
token), line width 1–5, opacity 0–1 and boolean visibility. Presentation changes do not alter
calculation inputs or issue commands. The configuration state `CONFIGURED_NOT_EXECUTED` is not numeric
readiness. Research metadata-only instances report “已配置，尚未接入后端计算”; transient instances report
configuration separately from the chart's current Query status. Selection and show/hide operate immediately without Catalog
or Market Data requests. An independent empty native Pane may represent the separate-pane preference;
no numeric Study series is created without a validated value projection.

Instances bind the exact Source reference, Instrument and BarSemantic, using the existing market-data
context key. Source/Instrument/BarSemantic changes retain instance identity, parameter intent and presentation,
close pending editing, discard prior numeric evidence and rotate the owner incarnation, including A→B→A.
An issued transient HTTP Query stays owned until completion; generation fences reject its old response and a
single latest pending intent replaces intermediate requests. A pending full closed-window batch takes priority
over a per-instance retry. Unmount, including the existing authentication-generation owner replacement, aborts
that owner and discards its volatile instances; context retention does not weaken that authentication boundary.
Returning application focus closes pending editing, rotates the incarnation and marks confirmed configurations
stale. Transient instances automatically re-observe current capabilities, Source grants and a complete verified
finite closed window, then admit exact current type/version/normalized-parameter evidence before returning the
fresh metadata binding to the presentation owner. Metadata-only instances require renewed confirmation.
Capacity, per-instance request and output failures preserve independently admitted siblings and expose instance retry.
Source/input/registration proof failures, authorization changes and unclassified formal Query failures withdraw all values
in the shared batch; missing failure-scope proof cannot authorize retaining a sibling. A malformed individual response or
transport failure rejects that response without claiming shared input invalidity.
Style/visibility/pane/selection changes do not calculate; a failed editor proof retains the invalidation fence.
No timer claims validity. Browser-session state is disposable; no LocalStorage/PostgreSQL persistence or
cross-refresh recovery is added. The market-data hook and Ledger receive no Study inputs. The presentation owner exposes its state
to the single chart through a local render callback; renderer resources are projections, not a second
mutable collection of configuration truth.

## Financial display controls and renderer input

`PriceChart` owns one Lightweight Charts instance and shared time axis/crosshair. Price and Volume
use stable native Pane references, and Volume is projected only from admitted Product Market Data
Bar `numeric.volume`. History and realtime preview/closed data share the same time identities; chart
mode changes replace only the price series. Volume is market data, not a Research Calculation output.

Each Study uses its browser instance identity for selected state, resource mapping and hover. Two
equal calculation configurations remain independent display instances. Placement is explicit user
input, never inferred from registered names or kinds. Separate-pane instances each own a private
native Pane; shared Study panes are not supported by this display policy. Indexes are resolved from
stable Pane references at each operation. Hidden/removed instances release only their display resources;
show restores the same validated projection rather than generating new values. Removing the selected
instance clears selection. Hidden and removed instances are absent from hover immediately.

`StudySeriesEvidence` is a readonly **Web presentation input**, not an HTTP schema, canonical scientific
model or Result admission API. `CONTROLLED_TEST_EVIDENCE` remains isolated-test-only; shipping Workspace
never supplies it. The distinct production `CHART_STUDY_TRANSIENT` branch requires the authenticated
Chart Query and strict generated-DTO adapter. A WeakMap admission binds that exact disposable evidence
occurrence to the current request/context/configuration/authentication generation; copying a response,
fixture or presentation object does not confer admission. The adapter checks the supplied owning
normalized Definition payload/fingerprint, Source/window/provenance relations and backend point metadata,
without resolving Definitions or computing values/readiness in the browser.

Initial incomplete history must pass exact owning Source/environment/Instrument/window/count and native
coverage validation before the chart reports shortage. A complete-to-incomplete evaluation has no history
fingerprint, resume cursor or numeric series; its absent cursor is not required to match the earlier complete
history. A conflicting closed Bar withdraws the history witness and fences pending/previous Study evidence.

No production scientific Result/Artifact series adapter exists here. A future verified adapter must supply
scientific authority before `RESEARCH_VERIFIED` values can be displayed. Transient values remain explicitly
`DISPLAY_ONLY / NOT_A_RESEARCH_RESULT` and cannot substitute for scientific publication or execution evidence.

The display input binds instance identity, full chart context key, owner incarnation, exact input
configuration representation and official output name. Those are stale-display fences, not canonical
Calculation fingerprints. Replaced/restored chart contexts have a fresh disposable owner incarnation.
Duplicate owners/evidence, mismatched identities, stale configuration, missing source, illegal point
metadata or unsafe projection fails closed as a display error; no missing proof grants execution,
numeric readiness or certified absence. No normalization, calculation, warmup or readiness inference
is performed. Point readiness/reason are copied opaque text/null fields from the supplied evidence.

UTC point identity must be strictly increasing, non-duplicate, whole-second nanosecond text with a
safe finite JS/Date representation; subsecond aliases are rejected. Numeric text is converted only
for explicitly lossy plotting; non-finite, overflow, unsafe magnitude or underflow-to-zero conversions
are rejected. Hover preserves original numeric text and matches exact timestamp and instance, never
array position or a preceding value. NULL and missing points remain gaps: the renderer separates
contiguous LineSeries segments with whitespace so native line connection cannot bridge unavailable
points. All-NULL/empty evidence produces no value series or final-value label. No interpolation,
resampling, guessed values or browser-generated scientific readiness is allowed.

Presentation options update the renderer without commands, acquisition, extra market subscriptions or
provider requests. Native stroke width is an explicitly rounded/clamped 1–4px display projection of
the stored 1–5 preference; selecting a real curve emphasizes that stroke without changing inputs.
Series addition/removal can change the union time-axis indexes; viewport rebasing uses UTC display
anchors and fractional offsets, not a fresh fitContent. Price, Volume and other instance resources
remain independent across pane compaction, movement, chart-mode switches and removal. Unmount releases
native series/panes, callbacks and pending paint work. These display resources are not persisted.

The legend uses compact, focusable display controls and a bounded scrollable instance list. On narrow
screens the inactive Research dock keeps its tabs and expand/collapse controls but takes less initial
height, preserving the primary K-line/Volume viewport. Browser acceptance checks usable native chart
height after multiple instances, not just populated point counters or absence of horizontal overflow.

## Native transient composition and retained metadata

The native Product composition uses one exact installed minimal algorithm artifact,
not a Runtime Generation or Trading worker registration. The canonical private
`calculation.proto` ChartBatch operation carries catalog, resolution and bounded
batch requests. All wire projections are generated from that canonical protocol.
The retained selected factory owns its declaration, normalization, implementation
resources, numeric policy and atomic value/readiness result. The Product owner
checks the installed resource bytes and full capability relation before admission.
An unavailable installation is unavailable, never an empty ready catalog.

The current composition offers the fourteen indicator families with their current
mathematical semantics. Exact older semantic versions that are absent are
unavailable; a family name cannot select another version. Definition2 identity
and lossless declaration remain separate from transient invocation and installation
identity. The minimal artifact uses existing distribution names and includes only
pure SDK values/normalizers, algorithms, exact generated protocol and the bounded
process entrypoint. It includes no Product service, database reader, Source grant,
Runtime scheduler or publication authority. Its Linux worker must establish
no-new-privileges, an architecture-checked syscall allowlist and hard CPU, address
space, process, descriptor and output-file limits before serving requests.

History enters calculation through the owning native Source Application window
read and its original authorization fence. The original retained preview from a
ProductStream may join a separately authorized history occurrence only by the
complete Source selection, qualified implementation, subject, context, plan and
immediate-successor relation. Resource pointer equality only constrains local
issuance and I/O; it is not canonical Source identity. Each original fence survives
through outward release. Replacement/disconnection discards only preview when
closed history remains authorized. Shared authentication or Source withdrawal
denies the affected response. One invocation permit remains held until its owned
process is joined; cancellation or uncertain protocol failure cannot retry another
process implicitly.

The normal Factor library reads the registered calculation catalog and private
asset registry separately. A current private Factor entry navigates to the exact
original revision/content pair; it does not substitute the current head at exact
read time. The read owner checks original payload/column, revision and source
fingerprints and retains the authenticated release fence. Private source, API,
revision, adapter and equivalence identities remain distinct. Metadata grants no
registration or execution authority. Research configuration, execution and
published-result actions are explicitly unavailable until their owning capability
is implemented; successful empty Run/Result fixtures cannot represent that state.
