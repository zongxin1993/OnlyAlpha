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
deploy-production.sh         validate, pull, and converge production services
run-operator.sh              execute explicit operators on the private network
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
