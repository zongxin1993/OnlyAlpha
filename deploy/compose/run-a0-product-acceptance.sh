#!/usr/bin/env bash
set -euo pipefail

deploy_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
repository_root="$(CDPATH= cd -- "${deploy_dir}/../.." && pwd)"
environment_file="${ONLYALPHA_COMPOSE_ENV_FILE:-${deploy_dir}/.env.test.example}"
golden_root="${ONLYALPHA_A0_GOLDEN_ROOT:?set ONLYALPHA_A0_GOLDEN_ROOT to the guarded frozen bundle directory}"

case "${golden_root}" in
  /*) ;;
  *) echo "ONLYALPHA_A0_GOLDEN_ROOT must be absolute" >&2; exit 2 ;;
esac
if [[ "${golden_root}" == "/" || ! -f "${golden_root}/bundle-manifest.json" ]]; then
  echo "guarded A0 Golden bundle-manifest.json is required" >&2
  exit 2
fi
product_output="$(mktemp -d "${TMPDIR:-/tmp}/onlyalpha-a0-product.XXXXXX")"

compose_files=(-f "${deploy_dir}/compose.yaml" -f "${deploy_dir}/compose.production.yaml" -f "${deploy_dir}/compose.test.yaml")
set -a
# shellcheck disable=SC1090
source "${environment_file}"
set +a
bundle_sha="$(shasum -a 256 "${golden_root}/bundle-manifest.json" | awk '{print $1}')"
export ONLYALPHA_A0_GOLDEN_BUNDLE_PATH="${golden_root}"
export ONLYALPHA_PRODUCT_CONFIG_PATH="${product_output}"
export ONLYALPHA_BACKUP_PATH="${product_output}/backups"
export ONLYALPHA_USER_DATA_VOLUME="onlyalpha-a0-${bundle_sha:0:16}-user-data"
export ONLYALPHA_POSTGRES_DSN="postgresql://${ONLYALPHA_POSTGRES_USER}:${ONLYALPHA_POSTGRES_PASSWORD}@onlyalpha-postgres:5432/${ONLYALPHA_POSTGRES_DATABASE}"
mkdir -p "${ONLYALPHA_BACKUP_PATH}"

compose() {
  docker compose --env-file "${environment_file}" "${compose_files[@]}" "$@"
}

cleanup() {
  if [[ "${ONLYALPHA_KEEP_TEST_STACK:-0}" != "1" ]]; then
    compose stop
    rm -rf -- "${product_output}"
  else
    echo "retaining A0 Product output at ${product_output}" >&2
  fi
}
trap cleanup EXIT

cd "${repository_root}"
compose build operator acceptance-client
compose up -d --wait postgres clickhouse
compose --profile tools run --rm user-data-initializer
compose --profile tools run --rm operator python scripts/database.py migrate
compose --profile tools run --rm operator python scripts/database.py initialize-deployment --user-data-root /var/lib/onlyalpha
compose --profile tools run --rm operator python scripts/market_data_database.py migrate
compose --profile binance-certification run --rm binance-golden-provisioner \
  python /workspace/deploy/compose/provision_a0_binance_golden.py provision-offline \
  --bundle-manifest /var/lib/onlyalpha-golden/bundle-manifest.json \
  --archive-root /var/lib/onlyalpha-golden/archives \
  --user-data-root /var/lib/onlyalpha \
  --output /var/lib/onlyalpha-product
compose up -d --wait onlyalpha-http-server research-worker backtest-worker

run_case() {
  case_name="$1"
  extra_args=()
  if [[ "${case_name}" == "usdm" ]]; then
    extra_args=(-e ONLYALPHA_ACCEPTANCE_EXPECT_FUNDING=1)
  fi
  definition_json="$(python -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["definition"],separators=(",",":")))' "${product_output}/acceptance-${case_name}.json")"
  backtest_json="$(python -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1]))["backtest_request"],separators=(",",":")))' "${product_output}/acceptance-${case_name}.json")"
  compose --profile product-acceptance run --rm \
    -e "ONLYALPHA_ACCEPTANCE_DEFINITION_JSON=${definition_json}" \
    -e "ONLYALPHA_ACCEPTANCE_BACKTEST_JSON=${backtest_json}" \
    "${extra_args[@]}" \
    acceptance-client
}

spot_first="$(run_case spot)"
spot_replay="$(run_case spot)"
usdm_first="$(run_case usdm)"
usdm_replay="$(run_case usdm)"
python - "${spot_first}" "${spot_replay}" "${usdm_first}" "${usdm_replay}" <<'PY'
import json, sys
for name, first, replay in (("Spot", sys.argv[1], sys.argv[2]), ("USD-M", sys.argv[3], sys.argv[4])):
    left, right = json.loads(first), json.loads(replay)
    for field in ("result_fingerprint", "determinism_fingerprint"):
        if left[field] != right[field]:
            raise SystemExit(f"{name} deterministic replay mismatch: {field}")
PY

compose stop backtest-worker
export ONLYALPHA_BACKTEST_ACCEPTANCE_BARRIER_PATH="/var/lib/onlyalpha/a0-backtest-release-${bundle_sha:0:16}-$$"
compose up -d --force-recreate backtest-worker
definition_json="$(python -c 'import json; print(json.dumps(json.load(open("'"${product_output}/acceptance-spot.json"'"))["definition"],separators=(",",":")))')"
backtest_json="$(python -c 'import json; print(json.dumps(json.load(open("'"${product_output}/acceptance-spot.json"'"))["backtest_request"],separators=(",",":")))')"
running="$(compose --profile product-acceptance run --rm \
  -e "ONLYALPHA_ACCEPTANCE_DEFINITION_JSON=${definition_json}" \
  -e "ONLYALPHA_ACCEPTANCE_BACKTEST_JSON=${backtest_json}" \
  -e ONLYALPHA_ACCEPTANCE_PAUSE_AT_RUNNING=1 acceptance-client)"
restart_run_id="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["backtest_run_id"])' "${running}")"
compose kill -s KILL backtest-worker
unset ONLYALPHA_BACKTEST_ACCEPTANCE_BARRIER_PATH
compose up -d --force-recreate backtest-worker
recovered="$(compose --profile product-acceptance run --rm \
  -e "ONLYALPHA_ACCEPTANCE_RESUME_BACKTEST_RUN_ID=${restart_run_id}" acceptance-client)"
python - "${spot_first}" "${recovered}" <<'PY'
import json, sys
baseline, recovered = json.loads(sys.argv[1]), json.loads(sys.argv[2])
for field in ("result_fingerprint", "determinism_fingerprint"):
    if baseline[field] != recovered[field]:
        raise SystemExit(f"Worker restart changed {field}")
print("A0 Product Acceptance\nSpot: PASS\nUSD-M: PASS\nDeterministic Replay: PASS\nWorker Restart: PASS\nIdempotency: PASS\nEvidence Recovery: PASS")
PY
