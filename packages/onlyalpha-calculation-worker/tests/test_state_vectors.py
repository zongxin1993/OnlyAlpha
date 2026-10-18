"""Independent common producer vectors, not Python as the Rust expected-value oracle."""

import json
from decimal import Decimal

from onlyalpha_calculation_worker.contracts import digest

from .test_backend import ROOT, bars, instance


def test_registered_python_sma_matches_independent_state_corpus():
    backend, binding = instance()
    vectors = [json.loads(line) for line in (ROOT / "test-data/calculation/state-v1.jsonl").read_text().splitlines()]
    for index, (raw, expected) in enumerate(zip(bars(), vectors, strict=True)):
        result = backend.update(binding["scope"], index, [raw], digest(raw))
        point = result["points"][0]
        assert point["samples"] == expected["samples"]
        assert point["ready"] is expected["ready"]
        assert Decimal(point["value"]) == Decimal(expected["value"])
