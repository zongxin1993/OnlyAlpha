from dataclasses import FrozenInstanceError

import pytest

from tests.support.engine_results import load_engine_result_fixture


@pytest.mark.parametrize(
    ("fixture_id", "minimum_fills"),
    (("minimal_round_trip", 2), ("multi_fill_round_trip", 6), ("multi_cluster_close", 4)),
)
def test_formal_engine_result_fixture_is_immutable_and_self_consistent(fixture_id: str, minimum_fills: int) -> None:
    fixture = load_engine_result_fixture(fixture_id)

    assert fixture.result.status == "COMPLETED"
    assert fixture.result_fingerprint
    assert fixture.expected_fill_count >= minimum_fills
    assert fixture.source_manifest["scenario"] == fixture_id
    with pytest.raises(TypeError):
        fixture.canonical_projection["changed"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        fixture.expected_fill_count = 0  # type: ignore[misc]
