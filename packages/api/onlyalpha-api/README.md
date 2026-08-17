# onlyalpha-api

Read-only HTTP transport for the versioned OnlyAlpha Research Query contract. The server consumes one explicitly configured
portable Research Artifact root and exposes exact-identity GET endpoints only.

The product contract is `/api/v2/research/artifacts/...`. Query Core remains schema version 1; HTTP independently uses schema version
2. Decimal values, event nanoseconds, and pagination cursors are JSON strings so browser consumers never pass exact values through
JavaScript `Number`. Request `from_ts_event_ns`, `to_ts_event_ns`, and `after_ts_event_ns` parameters are canonical decimal strings.

The deterministic machine contract is generated from FastAPI at `contracts/research-api/v2/openapi.json`; run
`uv run python scripts/export_research_openapi.py write|check`. The API remains GET-only and depends only on the portable Artifact
reader boundary. It does not enable CORS wildcard, read execution Stores, or expose Runtime control.
