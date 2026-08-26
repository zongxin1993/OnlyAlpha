# onlyalpha-api

HTTP transport for deliberately separate Research boundaries:

- `onlyalpha-api --user-data-root ...`: full local Research API. It reads `ONLYALPHA_POSTGRES_DSN`, checks migration compatibility,
  exposes read-only Discovery, authoritative Definition resolution, durable Run submit/get/list/cancellation plus Artifact GET routes, and binds
  loopback by default.
- `onlyalpha-artifact-api --artifact-root ...`: portable Artifact Query API. It needs no PostgreSQL and exposes only exact-identity
  Artifact GET routes.

Run submission requires a canonical UUID4 `Idempotency-Key`; `202 Accepted` is returned only after PostgreSQL commits the Run and
submission mapping. Run list pagination is deterministic keyset pagination. The API never starts a Worker/Engine, changes Attempt/lease
facts, returns Result/Artifact content, enables wildcard CORS, or performs database migration.

The deterministic contract is generated at `contracts/research-api/v2/openapi.json` with
`uv run python scripts/openapi_contract.py write|check`. Formal compatibility verification uses
`uv run python scripts/openapi_contract.py verify --base <immutable-git-sha>`; v2 breaking changes fail closed. Browser transport types
are generated only from that canonical file and admitted through strict Zod schemas before exact integers are converted to `bigint`.

Discovery endpoints are `GET /api/v2/research/catalog/calculations`, `/universes`, `/statistics`, and `/dataset-fields`.
`POST /api/v2/research/definitions/resolve` maps the strict JSON contract to `OnlyResearchDefinitionResolver` and returns exact Dataset,
Candidate, identity, published-variable and Specification evidence. It neither submits a Run nor persists a Definition/Resolution.
