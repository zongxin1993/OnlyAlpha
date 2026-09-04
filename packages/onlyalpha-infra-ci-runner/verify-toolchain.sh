#!/bin/sh
set -eu

test "$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')" = "3.12"
case "$(uv --version)" in
    "uv 0.10.5"*) ;;
    *) exit 1 ;;
esac
/opt/onlyalpha-ci/toolchain/bin/python -c "import pyarrow, psycopg, pytest, yaml"
/opt/onlyalpha-ci/toolchain/bin/mypy --version
/opt/onlyalpha-ci/toolchain/bin/ruff --version
git --version
