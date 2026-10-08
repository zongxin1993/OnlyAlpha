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
calculation inputs or issue commands. The compact list reports `CONFIGURED_NOT_EXECUTED` / “已配置，
尚未接入后端计算”, not numeric readiness. No renderer series, numeric values or pane are created.

Instances bind the exact Source reference, Instrument and BarSemantic, using the existing market-data
context key. A context-keyed workspace lifecycle discards all Study/draft state on any context
change, aborting old requests; old responses cannot attach to a new or restored context incarnation.
Returning application focus closes pending editing and conservatively marks confirmed configurations
stale until a new confirmation re-observes metadata. No timer claims validity. Browser-session
state is disposable; no LocalStorage/PostgreSQL persistence or cross-refresh recovery is added.
The market-data hook, Ledger and renderer are unchanged and receive no Study inputs.
