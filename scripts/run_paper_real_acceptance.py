"""CLI for the frozen Paper real-product acceptance profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onlyalpha.operations.acceptance import OnlyPaperAcceptancePlan, OnlyPaperAcceptanceRunner  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Paper real-product acceptance")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument(
        "--case",
        required=True,
        choices=("automated", "historical-snapshot", "live-handoff", "all"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--target-live-bars", type=int)
    args = parser.parse_args()
    plan = OnlyPaperAcceptancePlan.load(args.plan, output_override=args.output)
    if args.target_live_bars is not None:
        from dataclasses import replace

        plan = replace(plan, target_live_closed_bars=args.target_live_bars)
    result = OnlyPaperAcceptanceRunner().run(plan, args.case)
    print(f"verdict={result.verdict.value}")
    print(f"artifacts={result.artifacts.run_root}")
    return 0 if result.verdict.value == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
