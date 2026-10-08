# Chart Catalog navigation

The chart's Indicator/Factor picker is metadata navigation, not Calculation admission or execution.
It submits no command, acquires no market data and publishes no numeric output, point readiness,
Research Run, Result or Artifact. A selected item is a browser-only configuration draft, not a
persisted ChartStudyInstance or execution permission.

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
