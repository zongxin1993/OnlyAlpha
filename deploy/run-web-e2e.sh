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
export ONLYALPHA_NO_PROXY=api.binance.com,stream.binance.com,binance-probe-fixture

mkdir -p "$ONLYALPHA_WEB_E2E_ARTIFACTS_DIR"

compose() {
    docker compose -p "$ONLYALPHA_COMPOSE_NAMESPACE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
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
