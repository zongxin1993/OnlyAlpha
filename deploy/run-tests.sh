#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# == 0 )); then
    echo "usage: deploy/run-tests.sh <command> [args...]" >&2
    exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/deploy/docker-compose.dev.yml"
export ONLYALPHA_COMPOSE_NAMESPACE="onlyalpha-test-$$"
export ONLYALPHA_POSTGRES_DB=onlyalpha_test_environment
export ONLYALPHA_CLICKHOUSE_DATABASE=onlyalpha_test_environment

if [[ -L "$ROOT/test-results" ]]; then
    echo "test-results must not be a symlink" >&2
    exit 2
fi
mkdir -p "$ROOT/test-results"
# Linux bind mounts retain the host owner, unlike Docker Desktop mounts.
# Permit the non-root test user to create artifacts; the sticky bit prevents
# different users from deleting one another's entries. Never chmod recursively.
if [[ "$(LC_ALL=C ls -ld "$ROOT/test-results")" != drwxrwxrwt* ]]; then
    chmod 1777 "$ROOT/test-results"
fi

compose() {
    docker compose -p "$ONLYALPHA_COMPOSE_NAMESPACE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT INT TERM
    compose --profile test down -v --remove-orphans || true
    docker image rm "${ONLYALPHA_COMPOSE_NAMESPACE}-test" >/dev/null 2>&1 || true
    exit "$status"
}

trap cleanup EXIT INT TERM

compose config --quiet
compose --profile test run --build --rm \
    --volume "$ROOT/test-results:/workspace/test-results" \
    test "$@"
