# Research Query/API V2

The only supported address is an exact lower-case Research Result SHA256. Configure the server explicitly:

```bash
onlyalpha-api --artifact-root /absolute/path/to/research-artifacts
```

It binds `127.0.0.1:8000` by default and exposes:

- `GET /api/v2/research/artifacts/{research_result_fingerprint}`
- `GET /api/v2/research/artifacts/{research_result_fingerprint}/statistics`
- `GET /api/v2/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series`

Series parameters are `from_ts_event_ns`, `to_ts_event_ns`, `after_ts_event_ns`, and `limit`. Ranges are `[from,to)`, cursors are
strictly greater-than, the default limit is 1000, and the maximum is 5000. HTTP `from/to/after`, `ts_event_ns`, and
`next_after_ts_event_ns` are canonical decimal strings; routes parse request strings to Query Core Python integers. Decimal values
are canonical fixed strings or null. Query Core schema remains 1, while top-level HTTP DTO/error `schema_version` is independently 2.
Error bodies are `{schema_version, code, detail}` with invalid query=400, missing identity=404, and corrupt verified Artifact=500.

The deterministic OpenAPI contract is `contracts/research-api/v2/openapi.json`, generated from FastAPI by
`scripts/export_research_openapi.py`. `apps/onlyalpha-web` generates compile-time transport types from it and separately performs
strict Zod admission before mapping timestamps to `bigint`. There are no v1 product routes or compatibility wrapper.

The API is read-only and exact-addressed. It has no catalog/search/latest endpoint, mutation, raw Parquet download, query cache,
semantic recomputation, authentication, Trading endpoint, or Runtime control. The read-only Research Web consumer uses only these
same-origin endpoints and never reads Artifact filesystem layout or execution Stores.
