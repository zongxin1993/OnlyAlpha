"""Run one public Engine configuration and inspect committed execution projections."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path, help="One OnlyClusterRunConfig YAML/JSON file")
    parser.add_argument("--user-data", type=Path, default=Path("user_data"))
    args = parser.parse_args()

    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("committed-execution-example"), args.user_data))
    engine.add_cluster(OnlyClusterRunConfig.load(args.config))
    result = engine.run()
    if result.status != "COMPLETED":
        raise RuntimeError("; ".join(result.failures))

    for cluster in result.cluster_results:
        trades = cluster.get("trades", ())
        if not isinstance(trades, Sequence):
            continue
        for value in trades:
            if isinstance(value, Mapping):
                _print_execution(value)
    return 0


def _print_execution(execution: Mapping[str, object]) -> None:
    fields = (
        ("Trade ID", "execution_id"),
        ("Position Side", "position_side"),
        ("Position Effect", "position_effect"),
        ("Price", "price"),
        ("Quantity", "quantity"),
        ("Multiplier", "contract_multiplier"),
        ("Notional", "turnover"),
        ("Fee Breakdown", "fee_breakdown"),
        ("Slippage", "slippage"),
        ("Realized PnL Delta", "realized_pnl_delta"),
        ("Settlement", "settlement_status"),
        ("Margin", "margin_action"),
        ("Market Profile", "market_profile_id"),
    )
    print("Committed Execution")
    for label, key in fields:
        print(f"  {label}: {execution.get(key)}")


if __name__ == "__main__":
    raise SystemExit(main())
