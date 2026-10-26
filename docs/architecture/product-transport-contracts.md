# Product transport contracts

The versioned HTTP Product API is authored by the native HTTP adapter's
`packages/backend/src/transport/routes.rs` route declarations and
`packages/backend/src/transport/wire.rs` typed wire declarations, which
also drive actual serving. The native executable's pure `--export-openapi`
mode exports the contract without starting Product owners, opening stores,
loading configuration or issuing credentials. Its sole committed HTTP
projection is `contracts/product-api/v2/openapi.json`; the OpenAPI governance
command retains canonical versioning, freshness, immutable-baseline comparison
and breaking-change classification.

The Market Data WebSocket contract is authored by
`packages/backend/src/transport/stream_wire.rs`, shared by native ingress
and the executable's pure `--export-websocket` mode.
`scripts/market_data_stream_contract.py` projects this declaration to the sole
committed WebSocket schema,
`contracts/product-api/v2/market-data-stream.schema.json`, and the Web Zod
validator. CI checks both projections for freshness. Python and Node generation
tools are projection consumers; Python DTOs do not author either native wire
contract. Strict field validation, exact decimal and timestamp representation,
Source authorization and physical send fences remain owning transport
requirements; generation cannot grant permission or relax those requirements.

The two transport contracts describe different protocols. Neither is a second
Authority for Market Data facts or resolution planning.
