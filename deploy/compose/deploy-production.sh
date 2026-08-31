#!/usr/bin/env bash
set -euo pipefail

deploy_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
environment_file="${ONLYALPHA_COMPOSE_ENV_FILE:-${deploy_dir}/.env}"
compose_files=(-f "${deploy_dir}/compose.yaml" -f "${deploy_dir}/compose.production.yaml")

if [[ ! -f "${environment_file}" ]]; then
  echo "production environment file not found: ${environment_file}" >&2
  echo "copy deploy/compose/.env.production.example and replace every placeholder" >&2
  exit 2
fi

if grep -Eq '^ONLYALPHA_(POSTGRES|CLICKHOUSE)_PASSWORD=(change-me)?$' "${environment_file}"; then
  echo "production database passwords must replace every empty/change-me placeholder" >&2
  exit 2
fi
if grep -Eq '^ONLYALPHA_POSTGRES_DSN=.*<url-encoded-password>' "${environment_file}"; then
  echo "production PostgreSQL DSN must replace the URL-encoded password placeholder" >&2
  exit 2
fi

docker compose --env-file "${environment_file}" "${compose_files[@]}" config --quiet
docker compose --env-file "${environment_file}" "${compose_files[@]}" build operator
docker compose --env-file "${environment_file}" "${compose_files[@]}" pull postgres clickhouse
docker compose --env-file "${environment_file}" "${compose_files[@]}" up -d --wait
docker compose --env-file "${environment_file}" "${compose_files[@]}" ps
