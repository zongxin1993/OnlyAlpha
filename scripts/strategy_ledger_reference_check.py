"""Compare native Strategy Ledger output with independent valuation literals."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compare_native_outputs(native: list[dict[str, object]]) -> None:
    rows = [
        json.loads(line) for line in (ROOT / "test-data/strategy-ledger/valuation-v1.jsonl").read_text().splitlines()
    ]
    expected = [
        {"case": row["case"], "cluster": trade["cluster"], **trade["expected"]}
        for row in rows
        for trade in row["trades"]
    ]
    if native != expected:
        raise ValueError("STRATEGY_LEDGER_NATIVE_LITERAL_CONFLICT")
