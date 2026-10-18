import json
from pathlib import Path

from scripts.strategy_reference_check import reference_decisions


def test_live_python_reference_matches_independent_post_warmup_signals() -> None:
    path = Path(__file__).resolve().parents[2] / "test-data/domain/fact-records-v1.jsonl"
    base = next(json.loads(line)["record"] for line in path.read_text().splitlines() if json.loads(line)["id"] == "bar")
    assert reference_decisions(base) == [
        {"minute": i, "eligibility": True, "entry": i > 3, "exit": False} for i in range(3, 7)
    ]
