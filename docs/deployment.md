# OnlyAlpha Deployment

This document describes how the OnlyAlpha dev stack is deployed through the single
authorized Docker Compose topology and how the independently deployed Agent node is
configured. It is the canonical deployment reference for `deploy/docker-compose.dev.yml`.

Per `AGENTS.md` §6, `deploy/docker-compose.dev.yml` is the **only** authorized OnlyAlpha
Compose topology. New deployment capability extends this file; a second OnlyAlpha-owned
Compose file requires explicit owner approval plus a governance/architecture update.

## Topology overview

```text
postgres ─┐
clickhouse ┼─(database, internal)─ bootstrap ─→ api ─→ web
          │                            │        │
agent-provider-fixture ────────────────┘        └─(application)─ agent
```

- `database` is an `internal: true` network: postgres, clickhouse, bootstrap, the workers,
  the api and `agent-provider-fixture` reach each other, with no host ingress.
- `application` is the host-facing network: `api` and `web` are published; `agent` and
  `agent-provider-fixture` also attach here so the agent can reach the api runtime
  authority and the provider fixture.
- The Agent node never attaches to `database`. It reaches durable product state only
  through the versioned Product API (`api`), never through a direct database connection.

## Canonical Agent deployment: INTEGRATION_REVISION

The canonical Agent node runs in `INTEGRATION_REVISION` model-configuration mode. It does
not carry a static model endpoint. Instead, the model provider is resolved at startup from
an immutable, READY-probed Integration Revision through the Product API runtime authority.

The authority chain in the dev stack is:

```text
agent-provider-fixture (deterministic OpenAI-compatible provider)
  → bootstrap: scripts/bootstrap.py provisions the dev Agent Provider authority
      (Integration draft → encrypted secret → published revision → READY probe),
      writes agent-control-token / agent-product-token / agent-runtime-token and
      agent/model-profile.json under the user-data volume, and prints a summary
      document that contains no secret values
  → api: onlyalpha-http-server is started with --agent-runtime-token-file, which mounts
      the /internal/v1/agent-provider-runtime router (the runtime authority)
  → agent: onlyalpha-agent serve --model-configuration-mode INTEGRATION_REVISION calls
      compose_from_integration → admit_new against that authority at startup, before the
      HTTP server binds
```

Because `admit_new` (current revision + READY probe) runs **before** `uvicorn.run`, a
healthy `agent` container is real evidence that the INTEGRATION_REVISION startup path
succeeded: the runtime authority resolved the published revision and the agent composed
its production runtime from it. The agent healthcheck (`GET /internal/v1/healthz`)
therefore proves the canonical integration path, not merely that a process is listening.

The exact canonical agent command (as wired in `deploy/docker-compose.dev.yml`):

```text
onlyalpha-agent serve \
  --model-configuration-mode INTEGRATION_REVISION \
  --durable-root /var/lib/onlyalpha-agent \
  --coordination-root /var/run/onlyalpha-agent \
  --product-api-url http://api:8000 \
  --product-api-contract /workspace/contracts/product-api/v2/openapi.json \
  --product-token-file /var/lib/onlyalpha/secrets/agent-product-token \
  --integration-runtime-authority-url http://api:8000/internal/v1/agent-provider-runtime \
  --integration-runtime-authority-token-file /var/lib/onlyalpha/secrets/agent-runtime-token \
  --model-profile-file /var/lib/onlyalpha/agent/model-profile.json \
  --allow-insecure-runtime-authority-transport \
  --control-token-file /var/lib/onlyalpha/secrets/agent-control-token \
  --host 0.0.0.0 --port 8010
```

The agent mounts the product `user-data` volume **read-only**
(`user-data:/var/lib/onlyalpha:ro`) so it can read the bootstrap-provisioned tokens and
`agent/model-profile.json`. It never gains write access to the product user-data
authority; its own writable state lives in `agent-state` and `agent-locks`.

`INTEGRATION_REVISION` mode requires the complete bootstrap configuration
(`--product-api-url`, `--product-api-contract`, `--product-token-file`,
`--control-token-file`) **and** the complete integration-model configuration
(`--integration-runtime-authority-url`, `--integration-runtime-authority-token-file`,
`--model-profile-file`), and forbids any LEGACY model flag (`--model-api-url`,
`--model-token-file`). Mixing the two families fails closed with
`CONFIGURATION_MODE_CONFLICT`.

### Dev model identity

The provisioned model profile must carry the same model identity as the production
semantic bundle invocation binding, because the agent's INTEGRATION_REVISION compose
binding check admits the resolved endpoint only when its `provider_id` / `model_id` /
`model_version` equal the bundle binding. The dev stack therefore pins:

```text
ONLYALPHA_AGENT_PROVIDER_MODEL_ID=onlyalpha-research-v1
ONLYALPHA_AGENT_PROVIDER_MODEL_VERSION=2026-09-01
```

on the `bootstrap` service. The provider base URL and credential defaults in
`scripts/bootstrap.py` already target `agent-provider-fixture`.

## Transport confidentiality

The runtime authority is reached over plain HTTP on the internal Compose network, so the
canonical dev agent command passes `--allow-insecure-runtime-authority-transport`. This is
an **explicit dev-only exception**: without it, an `http://` runtime-authority URL (or a
`verify_tls=false` provider) fails closed with `AGENT_PROVIDER_AUTHORITY_TRANSPORT_INSECURE`.

**Production deployments omit `--allow-insecure-runtime-authority-transport` and must serve
the runtime authority over HTTPS.** The flag exists so the internal dev topology can run
plain HTTP without weakening the transport guard everywhere else; it is not a general
license to disable transport confidentiality.

## Non-canonical LEGACY invocation (compatibility-only)

`LEGACY` model-configuration mode is **not** the canonical deployment. It is retained only
as an explicit, compatibility-only invocation that resolves a static OpenAI-compatible
model endpoint from `--model-api-url` / `--model-token-file` plus the production semantic
bundle binding, instead of admitting an immutable Integration Revision. Deletion of the
LEGACY path is owned by a separate lifecycle decision, not by this deployment.

The exact non-canonical LEGACY command line:

```text
onlyalpha-agent serve \
  --model-configuration-mode LEGACY \
  --durable-root /var/lib/onlyalpha-agent \
  --coordination-root /var/run/onlyalpha-agent \
  --product-api-url http://api:8000 \
  --product-api-contract /workspace/contracts/product-api/v2/openapi.json \
  --product-token-file /var/lib/onlyalpha/secrets/agent-product-token \
  --control-token-file /var/lib/onlyalpha/secrets/agent-control-token \
  --model-api-url https://<provider-host>/v1 \
  --model-token-file /var/lib/onlyalpha/secrets/agent-model-token \
  --host 0.0.0.0 --port 8010
```

LEGACY constraints (enforced by the agent process entrypoint):

- It requires the complete bootstrap configuration **and** both LEGACY model flags; an
  incomplete set fails closed with `AGENT_CONFIGURATION_INCOMPLETE`.
- It forbids `--allow-insecure-runtime-authority-transport` and any integration-model flag
  (`--integration-runtime-authority-url`, `--integration-runtime-authority-token-file`,
  `--model-profile-file`); presence of either fails closed with `CONFIGURATION_MODE_CONFLICT`.

The canonical dev Compose topology does **not** use LEGACY. Do not introduce LEGACY into
`deploy/docker-compose.dev.yml`; the architecture gate
`test_canonical_agent_deployment_selects_integration_revision` pins the compose agent to
`INTEGRATION_REVISION`.

## Bringing the stack up and collecting evidence

```bash
docker compose -f deploy/docker-compose.dev.yml up -d --build
docker compose -f deploy/docker-compose.dev.yml ps          # api healthy, agent healthy
docker compose -f deploy/docker-compose.dev.yml logs bootstrap   # provisioning summary (no secrets)
docker compose -f deploy/docker-compose.dev.yml logs agent       # INTEGRATION_REVISION startup
```

Exercise the runtime authority directly (a valid runtime token returns a binding; a wrong
token returns `401`):

```bash
TOKEN=$(docker compose -f deploy/docker-compose.dev.yml exec -T api \
  cat /var/lib/onlyalpha/secrets/agent-runtime-token)
PROFILE=$(docker compose -f deploy/docker-compose.dev.yml exec -T api \
  cat /var/lib/onlyalpha/agent/model-profile.json)
curl -s -H "Authorization: Bearer ${TOKEN}" \
  -X POST http://localhost:8000/internal/v1/agent-provider-runtime/admit-new \
  -H 'Content-Type: application/json' \
  -d "{\"schema_version\":1,\"model_profile\":${PROFILE}}"
```

## Teardown

```bash
docker compose -f deploy/docker-compose.dev.yml down       # keep volumes (default)
docker compose -f deploy/docker-compose.dev.yml down -v    # destroy postgres/clickhouse/user-data/agent state
```

The default `down` (without `-v`) is the documented choice for iterative development: it
preserves the provisioned authority state, databases and agent roots so a subsequent `up`
replays the stored Product command receipts instead of re-provisioning from scratch. Use
`down -v` only when you intend to discard all durable dev state. The web-e2e runner
(`deploy/run-web-e2e.sh`) uses an isolated namespace and always tears down with `-v`.
