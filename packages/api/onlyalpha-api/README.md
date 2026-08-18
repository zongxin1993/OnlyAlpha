# onlyalpha-api

HTTP transport for two deliberately separate Research boundaries:

- `onlyalpha-api --user-data-root ...`: full local Research API. It reads `ONLYALPHA_POSTGRES_DSN`, checks migration compatibility,
  exposes durable Run submit/get/list/cancellation plus Artifact GET routes, and binds loopback by default.
- `onlyalpha-artifact-api --artifact-root ...`: portable Artifact Query API. It needs no PostgreSQL and exposes only exact-identity
  Artifact GET routes.

Run submission requires a canonical UUID4 `Idempotency-Key`; `202 Accepted` is returned only after PostgreSQL commits the Run and
submission mapping. Run list pagination is deterministic keyset pagination. The API never starts a Worker/Engine, changes Attempt/lease
facts, returns Result/Artifact content, enables wildcard CORS, or performs database migration.

The deterministic contract is generated at `contracts/research-api/v2/openapi.json` with
`uv run python scripts/export_research_openapi.py write|check`. Browser transport types are generated from that file and admitted through
strict Zod schemas before exact integers are converted to `bigint`.
