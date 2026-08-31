#!/usr/bin/env bash
set -euo pipefail

deploy_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "${deploy_dir}/../.." && pwd)"
environment_file="${deploy_dir}/.env.test.example"
compose_files=(-f "${deploy_dir}/compose.yaml" -f "${deploy_dir}/compose.test.yaml")

set -a
# shellcheck disable=SC1090
source "${environment_file}"
set +a

cleanup() {
  if [[ "${ONLYALPHA_KEEP_TEST_STACK:-0}" != "1" ]]; then
    docker compose --env-file "${environment_file}" "${compose_files[@]}" stop
  fi
}
trap cleanup EXIT

cd "${repository_root}"
docker compose --env-file "${environment_file}" "${compose_files[@]}" build acceptance
docker compose --env-file "${environment_file}" "${compose_files[@]}" up -d --wait \
  postgres postgres16-upgrade-source clickhouse
docker compose --env-file "${environment_file}" "${compose_files[@]}" run --rm acceptance
