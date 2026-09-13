#!/usr/bin/env bash
set -euo pipefail

cd /workspace

set +e
parallel_results_dir="$(mktemp -d /tmp/onlyalpha-database-lanes.XXXXXX)"
trap 'rm -rf "$parallel_results_dir"' EXIT

python scripts/test_suite.py research-postgres >"${parallel_results_dir}/research-postgres.log" 2>&1 &
postgres_pid=$!
python scripts/test_suite.py market-data-clickhouse >"${parallel_results_dir}/market-data-clickhouse.log" 2>&1 &
clickhouse_pid=$!

parallel_failure=0
wait "$postgres_pid" || parallel_failure=1
wait "$clickhouse_pid" || parallel_failure=1
if test "$parallel_failure" -ne 0; then
    cat "${parallel_results_dir}/research-postgres.log"
    cat "${parallel_results_dir}/market-data-clickhouse.log"
    exit 1
fi
set -e

# The combined lane is deliberately serial: it proves the cross-database projection
# and restore semantics after both independent resource lanes have completed.
python scripts/test_suite.py database-acceptance
