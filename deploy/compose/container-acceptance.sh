#!/usr/bin/env bash
set -euo pipefail

cd /workspace

python scripts/test_suite.py research-postgres
python scripts/test_suite.py market-data-clickhouse
python scripts/test_suite.py p9-3-real-database

