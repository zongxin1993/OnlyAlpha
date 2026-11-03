"""Independent post-warmup decision literals for the actual native bridge runner.

No Python Strategy/Runtime evaluator or claimed historical identity equivalence.
"""

from __future__ import annotations

import json


def compare_reference(stdout: str) -> None:
    lines = [
        line.removeprefix("STRATEGY_DECISIONS_JSON ")
        for line in stdout.splitlines()
        if line.startswith("STRATEGY_DECISIONS_JSON ")
    ]
    if len(lines) != 1:
        raise ValueError("STRATEGY_COMPARISON_OUTPUT_MISSING")
    actual = json.loads(lines[0])
    expected = [{"minute": i, "eligibility": True, "entry": i > 3, "exit": False} for i in range(3, 7)]
    assert actual == expected
    print(
        "STRATEGY_NATIVE_INDEPENDENT_DECISIONS: PASS",
        flush=True,
    )
