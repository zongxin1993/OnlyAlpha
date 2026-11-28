# Research HTTP APIs V2

Research 产品接口由 [OpenAPI v2](../contracts/product-api/v2/openapi.json) 定义。服务端已经退役，以下路径用于说明保留的读取和控制契约。统计读取使用以下接口。

- `GET /api/v2/research/artifacts/{research_result_fingerprint}`
- `GET /api/v2/research/artifacts/{research_result_fingerprint}/statistics`
- `GET /api/v2/research/artifacts/{research_result_fingerprint}/statistics/{statistics_fingerprint}/series`

Series parameters are `from_ts_event_ns`, `to_ts_event_ns`, `after_ts_event_ns`, and `limit`. Ranges are `[from,to)`, cursors are
strictly greater-than, the default limit is 1000, and the maximum is 5000. HTTP `from/to/after`, `ts_event_ns`, and
`next_after_ts_event_ns` are canonical decimal strings. Decimal values
are canonical fixed strings or null. Query Core schema remains 1, while top-level HTTP DTO/error `schema_version` is independently 2.
Error bodies are `{schema_version, code, detail}` with invalid query=400, missing identity=404, and corrupt verified Artifact=500.

前端根据版本化契约生成传输类型，消费前严格校验字段和时间戳，再映射为 `bigint`。

Artifact 查询按精确身份只读，禁止经文件路径或执行存储绕过正式权限与读取验证。研究作业的受理、查询和取消遵循以下请求契约。

- `POST /api/v2/research/runs` with required canonical UUID4 `Idempotency-Key` (`202` + `Location`);
- `GET /api/v2/research/runs/{run_id}`;
- `GET /api/v2/research/runs?limit=&cursor=` using a versioned keyset cursor;
- `POST /api/v2/research/runs/{run_id}/cancellation`.

Run responses contain operational facts and exact Result/Artifact references, not their content or Attempt history. Command errors use
`{error:{phase,code,detail}}`. Artifact routes retain their independent `{schema_version,code,detail}` query error contract when they
are composed into the full API. Hosting both families must preserve their distinct error contracts and authorization checks.
