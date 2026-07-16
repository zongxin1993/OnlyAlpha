"""Run the configuration-driven MACD product backtest."""

from __future__ import annotations

import argparse
from pathlib import Path

from onlyalpha.config import OnlyRunConfig
from onlyalpha.runtime.defaults import only_default_run_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a configuration-driven OnlyAlpha product workflow")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    config = OnlyRunConfig.load(args.config)
    result = only_default_run_service().run(config)
    print(f"status={result.status.value}")
    print(f"orders={result.execution.order_count} trades={result.execution.trade_count}")
    print(f"final_equity={result.performance.final_equity.amount}")
    print(f"fingerprint={result.determinism_fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
