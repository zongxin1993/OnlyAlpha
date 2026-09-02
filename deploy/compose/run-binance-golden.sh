#!/usr/bin/env bash
set -euo pipefail

deploy_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
environment_file="${ONLYALPHA_COMPOSE_ENV_FILE:-${deploy_dir}/.env}"
compose_files=(-f "${deploy_dir}/compose.yaml" -f "${deploy_dir}/compose.production.yaml")

if [[ ! -f "${environment_file}" ]]; then
  echo "deployment environment file not found: ${environment_file}" >&2
  exit 2
fi
if [[ "$#" -eq 0 ]]; then
  echo "usage: deploy/compose/run-binance-golden.sh capture-reference|provision [ARG ...]" >&2
  exit 2
fi

command_name="$1"
shift
case "${command_name}" in
  capture-reference)
    command=(python /workspace/deploy/compose/provision_a0_binance_golden.py capture-reference
      --output /var/lib/onlyalpha-product/binance-reference-capture.json "$@")
    ;;
  provision)
    command=(python /workspace/deploy/compose/provision_a0_binance_golden.py provision
      --capture /var/lib/onlyalpha-product/binance-reference-capture.json
      --user-data-root /var/lib/onlyalpha
      --output /var/lib/onlyalpha-product "$@")
    ;;
  *)
    echo "unknown Binance Golden command: ${command_name}" >&2
    exit 2
    ;;
esac

docker compose --env-file "${environment_file}" "${compose_files[@]}" \
  --profile binance-certification run --rm binance-golden-provisioner "${command[@]}"
