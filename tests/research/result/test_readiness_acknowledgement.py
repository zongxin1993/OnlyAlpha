"""Independent Result4 acknowledgement retains the actual acquired lock FD."""

import json

import pytest

from tests.research.artifact.test_calculation_v2 import _publication

pytestmark = pytest.mark.contract


def test_independent_result_acknowledgement_and_first_artifact_publication(tmp_path):
    publish, _, _, _, results, _ = _publication(tmp_path)
    payload = json.loads(next(results._root.glob("sha256/*/*/manifest.json")).read_text())
    plan = payload["research_result_plan_fingerprint"]
    original = results.load_verified(plan)
    assert results.acknowledge_exact(plan, original.manifest.research_result_fingerprint) == original
    assert publish().manifest.result == original.manifest
