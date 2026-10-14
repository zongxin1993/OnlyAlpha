# OnlyAlpha Deployment

This document describes how the OnlyAlpha dev stack is deployed through the single
authorized Docker Compose topology and how the independently deployed Agent node is
configured. It is the canonical deployment reference for `deploy/docker-compose.dev.yml`.

Per `AGENTS.md` §6, `deploy/docker-compose.dev.yml` is the **only** authorized OnlyAlpha
Compose topology. New deployment capability extends this file; a second OnlyAlpha-owned
Compose file requires explicit owner approval plus a governance/architecture update.

## Local Python debugging

Use one uv-managed environment at the workspace root. Point the IDE/debugger at
`.venv/bin/python`; workspace packages share this environment rather than creating
per-package, per-task or per-validation virtual environments.

```bash
uv sync --all-packages
uv run --no-sync python --version
```

Normal local Web/API debugging does not require a special read-only deployment,
`local-read.json`, or a separate operator project. Explicit API configuration still
determines which databases and user-data are used; debugging does not initialize,
reset or acquire data automatically. Keep local listeners on loopback.

Configure the source-run application's existing `--user-data-root` with an absolute
local directory, e.g. the gitignored workspace `user_data/`, or a directory outside
the source tree. API and Workers must use the same initialized semantic namespace
paired with their configured database. Custom runtime directories must stay outside
the source/build inventory. Do not create another uv environment for this storage.
Docker instead mounts the independent `user-data` volume at `/var/lib/onlyalpha`.
See [user_data](user_data.md) for contents and `AGENTS.md` §6.2 for the governing rule.

## Ordinary Shipping Web/API startup

```bash
python3 -m scripts.dev start
# Normal browser entry: http://127.0.0.1:5173/
python3 -m scripts.dev stop
```

The sole `dev` application service reuses `onlyalpha-browser-test:dev` dependencies,
not another uv environment or per-task image. It builds Shipping Web assets and
serves them through the real Product API on one host-loopback listener. This is a
Python-debugging composition, not a Vite preview or test backend. Source-only edits
do not rebuild images; explicitly stop before refreshing its frozen application
source. Subsequent verification refreshes a separate source view.

An already initialized, schema-compatible dev database/user-data pair and the
admitted dependency image are prerequisites. Startup does not initialize, migrate,
generate a master key, provision Sources, import assets, acquire history or start
Agent/workers. Existing databases must already be healthy. The same `user-data`
physical volume is referenced externally during this startup, so Compose cannot
create/reconcile/recreate it. No volume or data cleanup is performed.
The runner resolves the captured immutable bytes of the sole canonical Compose
input, with the original canonical path as the relative-path base, and references the
two observed dev networks externally, after checking their project, role and
internal/bridge boundary. It passes that resolved input through stdin without
creating another topology or file. Existing network label drift must not trigger
network replacement or disruption of database/validation endpoints.
Missing stores or changed source inputs refuse submission; they never authorize
initialization, volume recreation, historical-store adoption or a silent retry.

Guarded navigation automatically establishes a process-local developer session;
no `local-read.json` or manual credential input is required. Exact Source grants
are authorized by the explicitly selected developer-role policy and populated
with owning identities. Returning from Source management refreshes the chart list
and admits a new immutable exact grant snapshot without a service restart. Changed
grants withdraw the previous generation and close its streams; new reads/connections
must authenticate and prove the current exact selection. Unavailable/corrupt catalog
proof refuses startup or refresh, never becomes an empty catalog. Source reads/SMA
retain existing limits and exact ownership checks.
Integration configuration commands have a separate explicit dev-human policy;
Acquisition POST, Agent/internal, Strategy/LIVE and other mutations are denied.
Incomplete history is displayed and may be re-read without acquiring it.

The trusted boundary is this machine's OS users and sole dev project; the cookie
is not a production identity system. Exact Host/Origin/Fetch Metadata checks,
host-only HttpOnly SameSite=Strict cookies, frame denial, no forwarded identity
and no alternative API publication protect against foreign browser origins and
DNS rebinding. Do not publish this listener to LAN/internet. See the ordinary-dev
exception in the Chart Study design; optional private bearer mode is unchanged.
Standalone `--dev-web-root` startup admits only loopback binding. The internal
container composition permits all-interface binding only inside the mounted dev
container, whose canonical Compose publication is host-loopback. General Product
and Integration responses are also fenced on session withdrawal; already admitted
Commands are not rolled back or silently retried when their response is suppressed.
Signalled/unproved startup retains the lifecycle fence and requires explicit
reconciliation before another source refresh or startup submission.

Bootstrap, acquisition seeds, legacy API/Web, Agent fixtures and workers now require
explicit `integration`/`web-e2e` profiles. Unqualified default startup cannot trigger
those preparation chains. Controlled integration/CI retains its explicit topology;
do not select those profiles for daily development.

## Formal verification resource policy

`AGENTS.md` §6.1 owns the local verification/debugging rules: use the single
`onlyalpha-dev` project and this topology, with one reusable collection of fixed
role-based dev image tags. Services using the same build target share an image;
do not create projects or image tags per commit, worktree, task or validation run.
Pinned database images remain separate services in that same collection.

Reuse the dev database services without sharing dev business data with tests:
PostgreSQL test DSNs retain the `_test` guard, and ClickHouse/immutable test roots
retain explicit test namespaces. This is not permission to seed fixtures into the
ordinary product database, reset user-data, rebind a semantic store or bypass
Product authentication. Local verification is serial/single-worker by default.

During development, mount a frozen, read-only view of current source into the fixed dev tool image first;
source-only edits do not rebuild that image. Rebuild only for changed dependencies,
Dockerfile/toolchain inputs or an incompatible environment. Linux dependencies stay
in the image, never in the host's macOS `.venv` or `node_modules`.

The isolated-project invocation patterns in `deploy/run-tests.sh` and
`deploy/run-web-e2e.sh` are not permitted local development entry points. Their
existence is not proof that a reusable dev validation entry point is implemented.
Use the source-mounted entry below instead. Controlled CI job isolation and release
artifact identity remain separate responsibilities.

### Source-mounted local verification

```bash
# Once: reuse the tool image if present, otherwise build its fixed :dev tag.
# Only postgres, clickhouse and the persistent validation service are selected.
python3 scripts/dev_verification.py prepare

# Ordinary runs: exec in that same service, with current source mounted.
python3 scripts/dev_verification.py run -- python -m pytest tests/tools/test_dev_verification.py
python3 scripts/dev_verification.py --web run -- npx playwright test --workers=1

# Only after build/dependency/toolchain inputs change or incompatibility is proved:
python3 scripts/dev_verification.py --rebuild prepare
```

This entry requires Docker Engine image mounts and Compose image subpaths
(Compose 2.35+). The fixed role tag is built/reused normally; preparation resolves
its immutable image ID and uses that ID for both dependency mounts. Admission
requires that both mounted dependencies belong to the exact base image, not merely
the same mutable tag. Read-only image mounts mask both host dependency directories.
Only explicitly declared artifacts/typecheck files and tool cache directories are writable.
No dependency cache volume is created or silently retained across tool rebuilds.
Unsupported mount semantics are an environment blocker, not permission to create
another project or use host dependencies.

The runner refuses non-dev namespaces and a validation container attached to a
different worktree. Each run refreshes the same managed `.test-cache/dev-source-cut`
view, which is mounted read-only; editing and restoring live source cannot change
the code actually executed. Hidden execution configuration is included. Credentials
and host dependencies are not copied. Writable artifact mounts do not alias this view.
Ordinary runs do not create/recreate containers or rebuild images.

The view also carries the actual Git HEAD, commit/tree objects and worktree index
for architecture/build provenance checks. It does not create a commit, copy remotes,
hooks or credential configuration, or treat HEAD alone as the uncommitted source
identity; the file fingerprint remains the exact verification input. Build output
uses a separate writable tmpfs, never the read-only source or host business data.

A machine-wide host lock plus an outstanding-operation fence serializes preparation
and execution, including launcher death while Compose or exec remains outstanding.
The lock also reaches the actual command through `compose_test.py`, not just its
intermediate wrapper. Missing completion proof leaves the lifecycle UNKNOWN and
blocks subsequent run/preparation—even from another worktree. No automatic stale
fence adoption, retry or removal is provided: an owner must establish that outstanding
host/daemon/container work has stopped before explicitly recovering that tool state.
This is not permission to reset product data or restart Docker globally.

Dependency/build input mismatches require explicit rebuild, including metadata for
both installed editable test-data distributions. Source fingerprints and
the command outcome are retained under ignored `test-results/dev-verification/`;
changing the live source so it differs from the verified view at completion invalidates
attribution to that live tree. PostgreSQL commands use the
canonical `compose_test.py` `_test` guard and a dedicated validation database.
ClickHouse fixtures must continue using their owning `onlyalpha_test_*` namespaces.
No business user-data mount, API, bootstrap, acquisition or Agent is selected.

The protected local-read and Chart Study Browser fixtures reset their disposable
preconditions before seeding in local dev: only the exact `onlyalpha_dev_validation_test`
PostgreSQL public schema and the selected `onlyalpha_test_local_read_browser` or
`onlyalpha_test_chart_study_browser` ClickHouse namespace. The helper refuses other
databases/endpoints and missing/mismatched frozen-operation lineage before connecting;
it additionally holds a PostgreSQL transaction advisory lock during initialization.
Before destructive submission it writes an operation-bound UNKNOWN fence to
`test-results/dev-verification/browser-reset.pending.json`. Only observed synchronous
ClickHouse completion plus PostgreSQL transaction commit clears that fence. Lost
transport/commit proof leaves it pending; an ordinary Browser nonzero exit cannot
settle it or release the runner's machine-wide lifecycle fence. Further run/prepare
requires explicit Owner reconciliation, never automatic deletion/retry/adoption.
The canonical runner's lifecycle locks serialize the entire suite. No business
database, historical operator namespace, volume or real Acquisition is reset.
Controlled CI retains its existing isolated-database preparation. These fixtures
establish declared read-only test conditions, not source-management user actions or
real product/market acceptance evidence.

Local cleanup starts with an exact ownership/reference inventory. During development,
the owner authorizes complete stop/removal/recreation of containers proved to belong
to `onlyalpha-dev`, when needed; repeated permission for those containers is not required.
Use the lifecycle lock, settle current work and preserve logs. Prefer routine reuse;
this permission does not mean rebuilding the environment for every task or test run.
Preserve data volumes, the fixed dev image set and unrelated projects. Container cleanup
does not authorize volume deletion, business-data reset, historical-store adoption or
initialization. Those data actions still require separate explicit authorization.
Do not use a global prune command. `AGENTS.md` §6.1 owns this policy.

Ordinary startup, shutdown/restart, engineering upgrades, image rebuilds and container
replacement preserve history. An explicitly selected **clear dev data and initialize
again** lifecycle is separate: first identify the exact dev database/file/key/namespace
set, settle outstanding work and retain logs. Never clear only user-data and rebind an
existing database; do not use a reset to demonstrate an upgrade or restart works.
This policy is not an instruction to reset the current deployment or clear UNKNOWN.
Production deletion needs explicit human authorization, protected coherent backups,
a verified restore path and a retention policy; dev permission does not apply there.
Validate retained history with current owning readers after migration/restart, and
keep process-restart evidence distinct from real service/deployment lifecycle evidence.

Active development maintains the current canonical contract, not old-version compatibility
shims or parallel historical schema/DTO behavior. Atomically update current consumers;
retain required exact identity, immutable history, replay/recovery and integrity. See
ADR 0130 and `AGENTS.md` §7; no unrelated compatibility-code sweep is authorized here.

## Topology overview

```text
postgres ─┐
clickhouse ┼─(database, internal)─ bootstrap ─→ api ─→ market-data-bootstrap ─→ web
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

## Default development chart

`market-data-bootstrap` runs `scripts/provision_dev_market_data.py` after the API is
healthy and before the Web starts. It automatically creates and publishes **Binance
Spot Market Data** with the installed plugin's public market-data defaults (GLOBAL /
PUBLIC_MARKET_DATA), using only `/api/v2/integrations` commands and durable idempotency
receipts. No manual source creation, API key or broker configuration is required.

An existing Binance Spot public source in `GLOBAL` is reused; multiple sources remain an explicit
Web selection. Restarting never re-enables a disabled/archived seed, overwrites an
operator-edited draft, or replaces a published revision. Interrupted creation resumes
with the same deployment seed and command identities. API failures stop provisioning
rather than guessing that no source exists.

The workspace resolves the server-reported source and exact `BTCUSDT.BINANCE` member,
then loads **15m / LAST / RAW / SESSION_START** history, automatically acquiring missing
ranges through the existing Product API and subscribing to its realtime stream. The
API needs real Binance HTTPS/WSS access (configure the documented API proxy/certificate
environment if needed). Publishing configuration is not a READY certification: loading,
acquisition failures and realtime degradation remain visible, without synthetic Bars.
This seed grants no trading LIVE Authority. Its HTTP-only container has no database
network, database credentials or shared Product volume.

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
export ONLYALPHA_COMPOSE_NAMESPACE=onlyalpha-dev
docker compose -p onlyalpha-dev -f deploy/docker-compose.dev.yml up -d --build
docker compose -p onlyalpha-dev -f deploy/docker-compose.dev.yml ps
docker compose -p onlyalpha-dev -f deploy/docker-compose.dev.yml logs bootstrap
docker compose -p onlyalpha-dev -f deploy/docker-compose.dev.yml logs agent
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
```

The default `down` (without `-v`) is the documented choice for iterative development: it
preserves the provisioned authority state, databases and agent roots so a subsequent `up`
replays the stored Product command receipts instead of re-provisioning from scratch. Use
`down -v` only after explicit owner authorization to discard the identified durable
state. It is never ordinary local debug/test cleanup. The isolated web-e2e runner's
`down -v` lifecycle belongs to its controlled CI namespace, not the shared dev stack.

The Bar semantic/construction schema is an intentional breaking development boundary. A
checkout containing pre-boundary Bar WAL, scope, revision, Dataset, or Strategy data must
fail closed; it is not migrated or reinterpreted. Export anything that must be retained,
obtain explicit owner authorization for discarding the affected state, then rebuild
the development authorities from current imports and provider facts. Schema
incompatibility does not itself authorize a dev reset.
