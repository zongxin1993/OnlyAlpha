from __future__ import annotations

import json
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.research.experiment import OnlySearchExperimentManifestV1, OnlySearchExperimentManifestV2


@pytest.mark.parametrize(
    ("name", "reader"),
    (
        ("search_experiment_v1.json", OnlySearchExperimentManifestV1.from_dict),
        ("search_experiment_v2.json", OnlySearchExperimentManifestV2.from_dict),
    ),
)
def test_at_25_26_frozen_historical_experiment_identity(name, reader) -> None:  # type: ignore[no-untyped-def]
    path = Path(__file__).parent / "fixtures" / name
    raw = path.read_text(encoding="utf-8")
    fixture = json.loads(raw)
    assert raw.strip() == only_canonical_json(fixture)
    payload = fixture["canonical_payload"]
    value = reader(payload)
    assert value.to_dict() == payload
    assert value.experiment_fingerprint == fixture["expected_fingerprint"]
