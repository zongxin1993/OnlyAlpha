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

cd "${repository_root}"
actual_revision="$(git -C "${repository_root}" rev-parse HEAD)"
if [[ -n "${ONLYALPHA_BUILD_SOURCE_REVISION:-}" && "${ONLYALPHA_BUILD_SOURCE_REVISION}" != "${actual_revision}" ]]; then
  echo "ONLYALPHA_BUILD_SOURCE_REVISION conflicts with the repository Git HEAD" >&2
  exit 2
fi
ONLYALPHA_BUILD_SOURCE_REVISION="${actual_revision}"
export ONLYALPHA_BUILD_SOURCE_REVISION
trap cleanup EXIT
docker compose --env-file "${environment_file}" "${compose_files[@]}" build acceptance
docker compose --env-file "${environment_file}" "${compose_files[@]}" up -d --wait \
  postgres clickhouse
docker compose --env-file "${environment_file}" "${compose_files[@]}" run --rm acceptance
