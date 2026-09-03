# OnlyAlpha database deployment with Docker Compose

This deployment project owns the pinned PostgreSQL and ClickHouse service
topology used by P9.3. It follows the standard Compose pattern of one shared
service definition plus environment-specific override files:

```text
compose.yaml                 shared pinned database topology
compose.production.yaml      production lifecycle and log rotation
compose.test.yaml            isolated containerized acceptance override
.env.production.example      production configuration template
.env.test.example            deterministic local acceptance configuration
clickhouse/storage.xml       one HOT/COLD storage-policy definition
Dockerfile.acceptance        pinned Python/PostgreSQL-client test image
container-acceptance.sh      test process entrypoint inside Compose
product_acceptance_client.py isolated HTTP-only future-Agent acceptance client
certify_binance_golden_source.py verifies pinned provider archives before materialization
provision_a0_binance_golden.py captures provider authority and provisions real post-capture history
deploy-production.sh         validate, pull, and converge production services
run-operator.sh              execute explicit operators on the private network
run-binance-golden.sh        run online provisioning with isolated Binance egress
run-a0-product-acceptance.sh canonical offline Spot/USD-M Product acceptance
```

Database versions are intentionally exact:

```text
PostgreSQL 18.6
ClickHouse 26.3.x image family pinned as clickhouse/clickhouse-server:26.3
PostgreSQL 16.10 only in the test override as an upgrade source
```

## Production deployment

Create the ignored deployment environment and replace every placeholder:

```bash
cp deploy/compose/.env.production.example deploy/compose/.env
chmod 600 deploy/compose/.env
```

Validate the fully merged model before changing services:

```bash
docker compose \
  --env-file deploy/compose/.env \
  -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.production.yaml \
  config --quiet
```

Start or converge the deployment:

```bash
deploy/compose/deploy-production.sh
```

For an environment file stored outside the checkout, set
`ONLYALPHA_COMPOSE_ENV_FILE=/secure/path/onlyalpha.env`. The deployment entrypoint
always validates the merged model, pulls the exact configured images, converges
with `up -d --wait`, and prints final service status.

Production publishes no PostgreSQL or ClickHouse ports to the host. OnlyAlpha
application containers join the `${ONLYALPHA_DATABASE_NETWORK}` network and
use `onlyalpha-postgres:5432` and `onlyalpha-clickhouse:8123`. Named volumes
hold PostgreSQL state, ClickHouse metadata, and the HOT/COLD data paths.

`ONLYALPHA_PRODUCT_CONFIG_PATH` must be an operator-owned directory containing
the exact files mounted read-only by the Product API and Backtest Worker:

```text
binance-spot.json
binance-usdm.json
binance-spot-reference.json
binance-usdm-public-reference.json
binance-usdm-account-reference.json
```

The first two are validated `OnlyClusterRunConfig` Product compositions. The
remaining documents use schema version 1 and the plugin resource-provider IDs
`onlyalpha-plugin-binance-spot/reference@1` and
`onlyalpha-plugin-binance-usdm/reference@1`. Both processes load the same
read-only directory. Missing, malformed, fingerprint-mismatched, or conflicting
documents fail startup; Compose does not generate or silently substitute them.

Application startup verifies compatibility but never performs migration. The
pinned operator image joins the private Compose network under the opt-in
`tools` profile; databases remain unexposed to the host. Run explicit operators
before admitting a new deployment:

```bash
deploy/compose/run-operator.sh python scripts/database.py status
deploy/compose/run-operator.sh python scripts/database.py plan
deploy/compose/run-operator.sh python scripts/database.py migrate
deploy/compose/run-operator.sh python scripts/database.py initialize-deployment \
  --user-data-root /var/lib/onlyalpha
deploy/compose/run-operator.sh python scripts/database.py validate

deploy/compose/run-operator.sh python scripts/market_data_database.py status
deploy/compose/run-operator.sh python scripts/market_data_database.py plan
deploy/compose/run-operator.sh python scripts/market_data_database.py migrate
deploy/compose/run-operator.sh python scripts/market_data_database.py validate
```

Do not commit `deploy/compose/.env`. Keep backups outside database volumes and
set `ONLYALPHA_BACKUP_PATH` to a protected host path outside database volumes.
The operator sees it at `/var/lib/onlyalpha-backups`. Exercise restore into
isolated `onlyalpha_restore_*` targets before relying on a backup.

## P9.3 database acceptance

The test override is destructive only within guarded test databases. It uses
the same PostgreSQL and ClickHouse service definitions, exact images, private
networking, and storage policy as production, with separate test volumes. No
database port is published to the host. Run the complete acceptance entrypoint:

```bash
deploy/compose/run-acceptance.sh
```

The script builds the pinned acceptance image, starts the merged base/test
deployment, waits for health, and runs these lanes inside the Compose network:

```text
research-postgres
market-data-clickhouse
p9-3-real-database
```

and then stops the services while retaining named volumes. Set
`ONLYALPHA_KEEP_TEST_STACK=1` to leave the healthy test deployment running.

The `product-acceptance` profile additionally defines an isolated
`acceptance-client` image. That image contains only the Python standard library
and the HTTP client script: it has no OnlyAlpha package, database credentials,
Engine types, or shared Product storage. Its definition and Backtest command
payloads are injected as JSON environment values after the operator-owned
Golden Dataset and Product configuration have been provisioned. It validates
Definition → Research → Evidence → Freeze → Promotion → Backtest → Evidence,
including exact command replay and conflicting-payload rejection.

The Binance online certification lane starts from
`tests/fixtures/a0_binance_golden/source-manifest.json`. Download each official
archive to an operator-owned staging directory using `<source_id>.zip` as its
name, then verify archive/content hashes, record counts, and timestamp domains
before any ClickHouse ingestion or immutable Dataset materialization:

```bash
uv run python deploy/compose/certify_binance_golden_source.py \
  --manifest tests/fixtures/a0_binance_golden/source-manifest.json \
  --archive-root /secure/binance-golden-2024-01
```

The offline Product lane consumes the resulting immutable Dataset and economic
fact identities; it does not contact Binance or treat a mutable ClickHouse
query as semantic truth.

The canonical A0 lane consumes one operator-supplied, content-addressed frozen
bundle and performs materialization plus the complete HTTP-only Product proof:

```bash
ONLYALPHA_A0_GOLDEN_ROOT=/secure/a0-golden-2024-01 \
  deploy/compose/run-a0-product-acceptance.sh
```

`bundle-manifest.json` is strict schema version 1 with
`bundle_kind=A0_GOLDEN_V1`, exact SHA256 references to `source-manifest.json`
and `reference-capture.json`, and a minute-aligned `interval.start/end` that
contains a USD-M funding boundary. The bundle is mounted read-only and generated
Product configuration is written to an isolated temporary directory. Certified archives live below `archives/`
using `<source_id>.zip`. The lane verifies every archive before invoking the
same Binance Spot/USD-M normalizers used by provider ingestion, persists facts
through ClickHouse/PostgreSQL, seals immutable Dataset/economic bindings, then
runs Spot and USD-M twice and compares Result/determinism identities. Its final
fault phase holds a claimed Attempt at a deterministic operational barrier,
kills the Backtest Worker, restarts it after lease recovery, and compares the
recovered result to the uninterrupted baseline. The external client contains
no OnlyAlpha or database imports.

Online capture/certification remains a separate lane and is never invoked by
`run-a0-product-acceptance.sh`.

For an end-to-end online capture, the database network stays internal and only
the `binance-golden-provisioner` profile joins a separate egress network. USD-M
capture calls read-only signed account endpoints; it never changes account
settings or sends orders. Capture the authority first:

```bash
deploy/compose/run-binance-golden.sh capture-reference --products all
```

Then choose a closed, minute-aligned interval whose start is not earlier than
the captured provider time. USD-M certification must include a real BTCUSDT
funding boundary; an interval without one fails closed:

```bash
deploy/compose/run-binance-golden.sh provision \
  --products all \
  --start 2026-09-02T11:00:00+00:00 \
  --end 2026-09-02T16:01:00+00:00
```

The provisioner writes exact raw REST pages to ClickHouse, canonical 1m Bars
to ClickHouse, revision/seal authority to PostgreSQL, immutable Parquet Dataset
Snapshots and economic facts to the shared semantic volume, and Product/config
acceptance inputs to `ONLYALPHA_PRODUCT_CONFIG_PATH`. It refuses to backdate a
captured reference authority.

Manual equivalent:

```bash
set -a
source deploy/compose/.env.test.example
set +a

docker compose \
  --env-file deploy/compose/.env.test.example \
  -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.test.yaml \
  build acceptance

docker compose \
  --env-file deploy/compose/.env.test.example \
  -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.test.yaml \
  up -d --wait postgres postgres16-upgrade-source clickhouse

docker compose \
  --env-file deploy/compose/.env.test.example \
  -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.test.yaml \
  run --rm acceptance
```

Never point test DSNs at `onlyalpha`. PostgreSQL acceptance resets
`onlyalpha_test.public` and creates/drops `onlyalpha_restore_test`; ClickHouse
acceptance creates/drops only guarded `onlyalpha_test_*` and
`onlyalpha_restore_*` databases.

Stop without deleting data:

```bash
docker compose \
  --env-file deploy/compose/.env.test.example \
  -f deploy/compose/compose.yaml \
  -f deploy/compose/compose.test.yaml \
  stop
```

Deleting named volumes is deliberately not part of the normal workflow.
