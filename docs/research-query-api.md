# Research HTTP APIs V2

Artifact queries are served by the unique Product API. Configure it explicitly:

```bash
ONLYALPHA_POSTGRES_DSN='postgresql://...' onlyalpha-http-server --user-data-root /absolute/path/to/user-data
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
`scripts/openapi_contract.py`. `packages/onlyalpha-web-console` generates compile-time transport types from it and separately performs
strict Zod admission before mapping timestamps to `bigint`. There are no v1 product routes or compatibility wrapper.

The Artifact query family is read-only and exact-addressed. It has no catalog/search/latest endpoint, mutation, raw Parquet download, query cache,
semantic recomputation, authentication, Trading endpoint, or Runtime control. The read-only Research Web consumer uses only these
same-origin endpoints and never reads Artifact filesystem layout or execution Stores.

The full local control API uses `onlyalpha-http-server --user-data-root /absolute/user-data`, reads the PostgreSQL DSN only from
`ONLYALPHA_POSTGRES_DSN`, checks schema compatibility without migrating, and adds:

- `POST /api/v2/research/runs` with required canonical UUID4 `Idempotency-Key` (`202` + `Location`);
- `GET /api/v2/research/runs/{run_id}`;
- `GET /api/v2/research/runs?limit=&cursor=` using a versioned keyset cursor;
- `POST /api/v2/research/runs/{run_id}/cancellation`.

Run responses contain operational facts and exact Result/Artifact references, not their content or Attempt history. Command errors use
`{error:{phase,code,detail}}`. Artifact routes retain their independent `{schema_version,code,detail}` query error contract when they
are composed into the full API; sharing one FastAPI process does not merge the two transport error planes. The full API does not start
Scheduler, Worker, Runtime or Engine and defaults to `127.0.0.1` without permissive CORS.
