"""Verify execution, cancellation and recovery through the installed Strategy NodePort."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from packages.backend.tests.workers.test_installed_trading_nodes import installed_trading_case  # noqa: E402


def main() -> int:
    if sys.platform != "linux":
        raise ValueError("STRATEGY_EXECUTION_LINUX_REQUIRED")
    artifacts = ROOT / "test-results/strategy-execution"
    artifacts.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="installed-", dir=artifacts) as directory:
        output = installed_trading_case(
            Path(directory),
            "installed_trading_algorithms::actual_installed_nodes_keep_native_predicates_and_restore_factory_state",
            release=True,
            build_timeout=None,
        )
        print(output, end="", flush=True)
        if "Strategy execution, original child cancellation and fresh continuation verified" not in output:
            raise RuntimeError("STRATEGY_EXECUTION_EVIDENCE_MISSING")
    print("STRATEGY_EXECUTION_CANCEL_RECOVER: PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
