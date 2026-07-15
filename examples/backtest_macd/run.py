"""Run the configuration-driven MACD product backtest."""

from __future__ import annotations

import argparse
from pathlib import Path

from onlyalpha.backtest import OnlyBacktestConfig
from onlyalpha.runtime import OnlyBacktestRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the OnlyAlpha synthetic MACD backtest")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = OnlyBacktestConfig.load(args.config)
    result = OnlyBacktestRuntime.from_config(config).run()
    result.save(args.output)
    print(f"status={result.status.value}")
    print(f"orders={result.execution.order_count} trades={result.execution.trade_count}")
    print(f"final_equity={result.performance.final_equity.amount}")
    print(f"fingerprint={result.determinism_fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
