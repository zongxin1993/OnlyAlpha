"""Compare native Risk decisions and holds with independent literal vectors."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compare_native_outputs(native: list[dict[str, object]]) -> None:
    decisions = [json.loads(line) for line in (ROOT / "test-data/risk/decisions-v1.jsonl").read_text().splitlines()]
    reservations = [
        json.loads(line) for line in (ROOT / "test-data/risk/reservations-v1.jsonl").read_text().splitlines()
    ]
    expected = [
        *[{key: row[key] for key in ("case", "outcome", "observations")} for row in decisions],
        *[{"case": row["case"], **row["expected"]} for row in reservations],
    ]
    if native != expected:
        raise ValueError("RISK_NATIVE_LITERAL_CONFLICT")
