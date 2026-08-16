# Research Query/API V1

The only supported address is an exact lower-case Research Result SHA256. Configure the server explicitly:

```bash
onlyalpha-api --artifact-root /absolute/path/to/research-artifacts
```

It binds `127.0.0.1:8000` by default and exposes:

- `GET /api/v1/research/artifacts/{research_result_fingerprint}`
- `GET /api/v1/research/artifacts/{research_result_fingerprint}/statistics`
- `GET /api/v1/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series`

Series parameters are `from_ts_event_ns`, `to_ts_event_ns`, `after_ts_event_ns`, and `limit`. Ranges are `[from,to)`, cursors are
strictly greater-than, the default limit is 1000, and the maximum is 5000. Decimal values are strings or null; `ts_event_ns` remains
an exact integer. Error bodies are `{schema_version, code, detail}` with invalid query=400, missing identity=404, and corrupt verified
Artifact=500.

The API is read-only and exact-addressed. It has no catalog/search/latest endpoint, mutation, raw Parquet download, query cache,
semantic recomputation, authentication, Trading endpoint, Runtime control, or Web UI.
