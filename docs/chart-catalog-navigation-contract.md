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
calculation inputs or issue commands. The compact legend reports `CONFIGURED_NOT_EXECUTED` / “已配置，
尚未接入后端计算”, not numeric readiness. Selection and show/hide operate immediately without Catalog
or Market Data requests. An independent empty native Pane may represent the separate-pane preference;
no numeric Study series is created without a validated value projection.

Instances bind the exact Source reference, Instrument and BarSemantic, using the existing market-data
context key. A context-keyed workspace lifecycle discards all Study/draft state on any context
change, aborting old requests; old responses cannot attach to a new or restored context incarnation.
Returning application focus closes pending editing and conservatively marks confirmed configurations
stale until a new confirmation re-observes metadata. No timer claims validity. Browser-session
state is disposable; no LocalStorage/PostgreSQL persistence or cross-refresh recovery is added.
The market-data hook and Ledger receive no Study inputs. The context-keyed owner exposes its state
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
model or Result admission API. No production Result/Series adapter exists here. Its only implemented
source is explicitly `CONTROLLED_TEST_EVIDENCE`; the isolated Browser harness is not a production entry
point, and shipping Workspace never supplies this evidence or requests an unavailable Series Query.
A future verified Result/Artifact/Query adapter must supply scientific authority and extend the source
family explicitly before production values can be displayed.

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
