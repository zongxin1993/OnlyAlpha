#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/docker-compose.dev.yml"
export ONLYALPHA_COMPOSE_NAMESPACE="onlyalpha-web-e2e-$$"
export ONLYALPHA_POSTGRES_DB=onlyalpha_web_e2e
export ONLYALPHA_CLICKHOUSE_DATABASE=onlyalpha_web_e2e
export ONLYALPHA_HTTP_PORT="${ONLYALPHA_HTTP_PORT:-18000}"
export ONLYALPHA_WEB_PORT="${ONLYALPHA_WEB_PORT:-15173}"
export ONLYALPHA_WEB_E2E_ARTIFACTS_DIR="${ONLYALPHA_WEB_E2E_ARTIFACTS_DIR:-$ROOT/test-results/web-e2e}"
export ONLYALPHA_SSL_CERT_FILE=/var/lib/onlyalpha/probe-fixture/ca.crt
export ONLYALPHA_NO_PROXY=localhost,127.0.0.1,postgres,clickhouse,api,web,agent,agent-provider-fixture,api.binance.com,stream.binance.com,data-api.binance.vision,data-stream.binance.vision,binance-probe-fixture

mkdir -p "$ONLYALPHA_WEB_E2E_ARTIFACTS_DIR"

compose() {
    docker compose -p "$ONLYALPHA_COMPOSE_NAMESPACE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    # Capture service diagnostics before teardown; a capture error must not mask test failure.
    compose --profile web-e2e logs --no-color api postgres clickhouse binance-probe-fixture \
        > "$ONLYALPHA_WEB_E2E_ARTIFACTS_DIR/service-logs.txt" 2>&1 || true
    compose --profile web-e2e down -v --remove-orphans || true
    exit "$status"
}

trap cleanup EXIT INT TERM

compose config --quiet
compose up -d --build --wait

status=0
if compose --profile web-e2e run --build --rm playwright; then
    status=0
else
    status=$?
fi
exit "$status"
