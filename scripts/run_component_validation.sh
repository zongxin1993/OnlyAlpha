#!/usr/bin/env bash
set -euo pipefail

export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/onlyalpha-uv-cache}"

uv run pytest -q
uv run pytest -q tests/integration
uv run python -m tests.integration_demo.run_all
uv run pytest -q tests/integration/test_vertical_slice_replay.py
uv run ruff check .
uv run ruff format --check .
uv run mypy src/onlyalpha
