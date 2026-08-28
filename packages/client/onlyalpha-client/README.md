# onlyalpha-client

`onlyalpha-client` is the official Python and CLI consumer of the OnlyAlpha Product Control Plane. It communicates only through
HTTPS/JSON and has no dependency on the `onlyalpha` Kernel/Core package.

Its generated transport projection comes exclusively from
`contracts/research-api/v2/openapi.json` via `scripts/openapi_clients.py write|check`. The hand-written facade owns transport concerns
only; Research lifecycle, identity, idempotency and business state remain server authorities.

Mutation calls are never retried implicitly. Callers must retain and explicitly reuse the same idempotency key when the outcome of a
request is uncertain.
