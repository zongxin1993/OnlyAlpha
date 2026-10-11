# onlyalpha-http-server

HTTP transport for the unified Research Product boundary:

- `onlyalpha-http-server --user-data-root ... --backtest-product-config product.json`: full local Product API. Repeat
  `--backtest-product-config` for each operator-owned Market Product composition. It reads `ONLYALPHA_POSTGRES_DSN`, checks migration compatibility,
  exposes read-only Discovery, authoritative Definition resolution, durable Run submit/get/list/cancellation plus Artifact GET routes, and binds
  loopback by default. Artifact GET routes are served by this same Product API.

Run submission requires a canonical UUID4 `Idempotency-Key`; `202 Accepted` is returned only after PostgreSQL commits the Run and
submission mapping. Run list pagination is deterministic keyset pagination. The API never starts a Worker/Engine, changes Attempt/lease
facts, returns Result/Artifact content, enables wildcard CORS, or performs database migration.

The deterministic contract is generated at `contracts/product-api/v2/openapi.json` with
`uv run python scripts/openapi_contract.py write|check`. Formal compatibility verification uses
`uv run python scripts/openapi_contract.py verify --base <immutable-git-sha>`; v2 breaking changes fail closed. Browser transport types
are generated only from that canonical file and admitted through strict Zod schemas before exact integers are converted to `bigint`.

Discovery endpoints are `GET /api/v2/research/catalog/calculations`, `/universes`, `/statistics`, and `/dataset-fields`.
`POST /api/v2/research/definitions/resolve` maps the strict JSON contract to `OnlyResearchDefinitionResolver` and returns exact Dataset,
Candidate, identity, published-variable and Specification evidence. It neither submits a Run nor persists a Definition/Resolution.

## Local Source read ingress

`--local-read-auth-config /absolute/private/read-access.json` selects an intentionally **read-only** composition. It accepts only
literal loopback binds (`127.0.0.1` or `::1`), disables forwarded-header interpretation and WS compression, and limits WS messages
to 4096 bytes. Invalid configuration is fatal, never an anonymous fallback. Absent configuration retains the legacy composition,
**not** W3 admission. No Study calculation/API or SMA support is admitted by this switch.

Strict UTF-8 JSON configuration:

```json
{
  "schema_version": 1,
  "subject_id": "local-human",
  "bearer_sha256": "<64 lowercase hex SHA-256 characters>",
  "origin": "http://127.0.0.1:5173",
  "grants": [
    {
      "integration_id": "<exact Integration ID>",
      "integration_revision_fingerprint": "<exact 64 lowercase hex Revision fingerprint>",
      "expected_type_id": "<exact Integration type>",
      "source_id": "<owning canonical Source ID>",
      "environment": "<owning environment>",
      "permissions": ["CLOSED_HISTORY", "REALTIME_PREVIEW"]
    }
  ]
}
```

Provision an **independent random 256-bit** bearer encoded as 64 lowercase hexadecimal characters; store only SHA-256 of those
ASCII characters in configuration. Never reuse Agent credentials, put the bearer in environment variables/URLs, or log it.
The file must be a single-link regular file owned by root/the process user, mode `0600`/`0400`; every ancestor must be root/process-owned
and not writable by other users. Root-owned sticky shared ancestors such as `/tmp` require independently safe owner-created
descendants. Symlinks, duplicate keys/grants, wildcards, unknown fields/permissions, malformed revisions/digests and more than
32 grants are rejected. Configuration is read once. Owning Source/environment is reproved before provider, history or stream IO.

| Available path | Requirement |
|---|---|
| GET `/api/v2/market-data/sources` | Bearer; exact granted references only |
| GET `/api/v2/market/instruments`, `/api/v2/market-data/bars` | Bearer + `CLOSED_HISTORY` exact grant |
| GET `/api/v2/market-data/acquisitions/{id}` | Same historical grant; status only |
| WS `/api/v2/market-data/stream` | Exact Browser Origin + AUTH control frame + `REALTIME_PREVIEW` exact grant |
| GET `/health/live`, `/health/ready` | Non-sensitive health only |

Every other path/method—including redirects/docs, Acquisition POST, Integration/secrets/probes, Artifact aliases, internal Agent,
Research/Backtest and Trading—is denied **with or without** bearer. Manage/acquire through an independently protected management
ingress. Supplied read credentials make the shipping workspace show insufficient coverage as unavailable rather than attempt
automatic backfill; legacy acquisition behavior remains separate.

Expand **本地只读访问**, enter the password credential and select **连接只读行情**. The input clears; credential state is memory-only.
Clear/re-enter/replace creates a fresh Browser generation, closes prior sockets and discards old responses/presentation caches.
Refresh clears credentials. HTTP uses Authorization. Native WS sends
`{"schema_version":1,"operation":"AUTH","bearer":"..."}` first, waits for
`{"schema_version":1,"event":"AUTHENTICATED"}`, then sends one existing V2 Subscribe. ACK proves identity, not Source permission.
No token in query, subprotocol, cookies or storage. Each handshake phase has a 5-second resource deadline; 4 HTTP work slots and
4 WS slots have no waiting queue. Abandoned thread work retains its slot through actual disposal.

### Withdrawal and environment gate

File edits are **not** hot rotation or a global revocation acknowledgement. Withdraw old admission/response release, stop the old
process/ingress, prove old requests/streams terminated, then start the replacement immutable composition. A blocked Provider may
require process termination; cancellation of its HTTP/WS caller does not release its slot. A transport send already begun must
terminate before withdrawal's release fence acknowledges completion. Previously delivered bytes cannot be recalled.

Default canonical Compose API/Web publications are **not** an admitted local read deployment. Vite, container names, loopback
arguments and isolated test success do not prove LAN/TLS containment. W3 remains disabled until actual Web/API binding and every
management/alternate route are independently protected. No production migration, restart or deployment is performed by this slice.

The owner-authorized optional `ONLYALPHA_TEST_BUILD_TARGET=browser-test` reuses Node24/Playwright in the existing canonical Compose
`test` service; the default target stays unchanged. Run through `deploy/run-tests.sh`. Its loopback fixture uses real Product
services and isolated PostgreSQL/ClickHouse with deterministic external Provider/Integration fixtures, comparing all table counts
and content hashes before/after preview-only reads. This proves neither external-provider recording nor Unraid ingress security;
a normally recording live stream must never be represented as making zero market-fact writes.
