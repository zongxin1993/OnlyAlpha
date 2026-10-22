#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# One frozen source view, one canonical validation service, one browser worker.
# The native runner owns its isolated test namespace; this never provisions dev business state.
exec python scripts/dev_verification.py run -- python scripts/native_web_e2e.py "$@"
