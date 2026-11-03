import builtins
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.backtest_result_reference_check import compare_native

ROOT = Path(__file__).resolve().parents[2]


def outputs() -> list[dict[str, Any]]:
    vectors = [
        json.loads(line) for line in (ROOT / "test-data/execution/backtest-result-v1.jsonl").read_text().splitlines()
    ]
    rows = []
    for vector in vectors:
        # The checker validates an emitted Result's identity; actual Rust
        # production of these vectors is exercised by the canonical runner.
        content = {"case": vector["case"], "status": vector["expected"]["status"]}
        fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        content.update(result_fingerprint=fingerprint, determinism_fingerprint=fingerprint)
        identity = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        rows.append(
            {"case": vector["case"], "observed": vector["expected"], "result": {**content, "id": "BTR-" + identity}}
        )
    return rows


def test_independent_result_literals_and_identities_do_not_load_legacy_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    original = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        assert name != "onlyalpha" and not name.startswith("onlyalpha."), name
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    compare_native(ROOT, outputs())


def test_missing_native_result_is_not_equivalence() -> None:
    with pytest.raises(ValueError, match="CARDINALITY"):
        compare_native(ROOT, [])


@pytest.mark.parametrize("mutation", ["reordered", "numeric", "content-id", "business-id"])
def test_wrong_native_values_and_identities_are_refused(mutation: str) -> None:
    rows = outputs()
    if mutation == "reordered":
        rows.reverse()
    elif mutation == "numeric":
        rows[0]["observed"]["final_equity"] = "999.00"
    elif mutation == "content-id":
        rows[0]["result"]["id"] = "BTR-" + "f" * 64
    else:
        result = rows[0]["result"]
        result["determinism_fingerprint"] = "f" * 64
        content = {key: value for key, value in result.items() if key != "id"}
        result["id"] = (
            "BTR-" + hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        )
    with pytest.raises(ValueError):
        compare_native(ROOT, rows)
