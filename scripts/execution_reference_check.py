"""Independent native partial-close economics; no legacy Runtime implementation."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Controlled 0.001 fee input: 100*12*0.001=1.20; 300*12*0.001=3.60.
EXPECTED: list[dict[str, str]] = json.loads((ROOT / "test-data/execution/partial-close-v1.json").read_text())


def compare_native_outputs(native: list[dict[str, str]]) -> None:
    if native != EXPECTED:
        raise ValueError("EXECUTION_NATIVE_LITERAL_CONFLICT")


if __name__ == "__main__":
    raise SystemExit("run the canonical onlyalpha-execution Rust verification lane")
