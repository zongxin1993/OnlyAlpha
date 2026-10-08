# Chart Catalog navigation

The chart's Indicator/Factor picker is metadata navigation, not Calculation admission or execution.
It submits no command, acquires no market data and publishes no numeric output, point readiness,
Research Run, Result or Artifact. A selected item is a browser-only configuration draft, not a
persisted ChartStudyInstance or execution permission.

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

Opening/refreshing the picker resolves the relation again. Returning focus to the application
also refreshes an open picker or existing draft. A final active read fences both Catalog loading
and selection. A changed fingerprint invalidates the old results and draft; there is no elapsed-time
TTL, background retry or fallback to installed/current plugin code. These observations are not
an atomic Runtime reservation. Any future execution must separately obtain formal admission.

The renderer and market-data incarnation remain independent of this navigation lifecycle.
