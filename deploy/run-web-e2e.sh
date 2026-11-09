#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Each host invocation owns one frozen cut and the canonical lifecycle lock.
# The native runner owns isolated test data; no nested Docker invocation.
run_journey() {
    local verification=(python scripts/dev_verification.py)
    local argument
    for argument in "$@"; do
        if [[ "$argument" == "--controlled-source-https" ]]; then
            verification+=(--controlled-source-https)
            break
        fi
    done
    "${verification[@]}" run -- \
        python -m scripts.native_web_e2e "$@"
}

# This explicit functional selection retains the default performance gate.
# It is a complete functional plan, not an argument forwarded to the native runner.
functional_only=false
for argument in "$@"; do
    if [[ "$argument" == "--functional-only" ]]; then
        if (( $# != 1 )); then
            printf '%s\n' '--functional-only must be used alone' >&2
            exit 2
        fi
        functional_only=true
    fi
done
if [[ "$functional_only" == true ]]; then
    shift
fi

# Explicit selections are one user-selected invocation, never the full default plan.
if (( $# > 0 )); then
    run_journey "$@"
    exit 0
fi

# A: ordinary journeys, excluding owners with controlled input or restart evidence.
run_journey \
    e2e/analysis.spec.ts \
    e2e/chart-catalog.spec.ts \
    e2e/data-sources.spec.ts \
    e2e/factor-http-boundaries.spec.ts \
    e2e/factors.spec.ts \
    e2e/market-data-historical.spec.ts \
    e2e/market-data-realtime.spec.ts \
    e2e/metadata-errors.spec.ts \
    e2e/product-package-migration.spec.ts \
    e2e/product-workspaces.spec.ts \
    e2e/research.spec.ts \
    e2e/source-command-errors.spec.ts \
    e2e/study-renderer.spec.ts \
    e2e/workspace-toolbar.spec.ts

# B: every private-Factor case owns explicit restored-phase evidence.
run_journey --restart-check e2e/private-factor-authoring.spec.ts

# C: this indicator case has controlled input, but no restored-phase contract.
run_journey --controlled-source-https --retained-market-input --chart-sma-market-input \
    e2e/chart-native-sma.spec.ts

# D: the daily Source journey owns controlled input and original-operation restart evidence.
run_journey --controlled-source-https --retained-market-input --tushare-daily-market-input \
    --restart-check e2e/tushare-daily.spec.ts

# E: complete financial/result and same-Run restart evidence, independent of latency.
run_journey --controlled-source-https --retained-market-input --backtest-market-input \
    --restart-check e2e/backtest.spec.ts \
    --grep 'normal backtest functional (correctness reopens the same run|cancellation reopens the same cancelled run|running recovery completes the same run) after restart$'

if [[ "$functional_only" == true ]]; then
    exit 0
fi

# F: the existing fixed 120s performance gate remains mandatory in the default plan.
run_journey --controlled-source-https --retained-market-input --backtest-market-input \
    --restart-check e2e/backtest.spec.ts \
    --grep 'normal backtest works without Agent and reopens the same run after restart$'
