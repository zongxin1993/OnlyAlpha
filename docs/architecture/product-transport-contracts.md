# Product transport contracts

The versioned HTTP Product API is authored by FastAPI routes and DTOs. Its sole
committed HTTP projection is `contracts/product-api/v2/openapi.json`; the
OpenAPI governance command checks freshness and compatibility.

The Market Data WebSocket contract is authored by
`packages/onlyalpha-http-server/src/onlyalpha_http_server/market_data/stream_schema.py`.
`scripts/market_data_stream_contract.py` projects it to the sole committed
WebSocket schema, `contracts/product-api/v2/market-data-stream.schema.json`,
and the Web Zod validator. CI checks both projections for freshness. Server
outbound events are validated against the same Pydantic models before sending.

The two transport contracts describe different protocols. Neither is a second
Authority for Market Data facts or resolution planning.
