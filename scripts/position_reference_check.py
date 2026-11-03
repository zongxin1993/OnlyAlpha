"""Compare native Position lifecycle output with independent exact-cost literals."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def compare_native_outputs(observed: list[dict[str, object]]) -> None:
    rows = [json.loads(line) for line in (ROOT / "test-data/position/lifecycle-v1.jsonl").read_text().splitlines()]
    expected = [{"case": row["case"], "observed": row["expected"]} for row in rows]
    assert observed == expected, "POSITION_NATIVE_LITERAL_MISMATCH"


if __name__ == "__main__":
    raise SystemExit("run the canonical onlyalpha-position Rust verification lane")
