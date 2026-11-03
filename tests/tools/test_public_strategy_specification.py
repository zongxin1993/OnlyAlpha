"""Independent public value reader; no admission or executable capability claim."""

import json
from pathlib import Path


def test_native_public2_vector_uses_existing_python_value_contract() -> None:
    from onlyalpha.research.specification.model import OnlyResearchSpecification

    vector = json.loads(Path("packages/backend/tests/application/fixtures/strategy_specification.json").read_text())
    value = OnlyResearchSpecification.from_dict(vector["specification"])
    assert value.to_dict() == vector["specification"]
    assert value.specification_fingerprint == vector["specification_fingerprint"]
