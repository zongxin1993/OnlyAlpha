"""Physical native startup history/guard evidence, not Shipping business acceptance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from onlyalpha.canonical import only_canonical_json
from onlyalpha.strategy.freeze_relation import OnlyStrategyFreezeRelation
from onlyalpha.strategy.revision import OnlyStrategyRevision
from tests.support.frozen_strategy import call, pair

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.timeout(120)]


def test_actual_guard_complete_history_and_relation_first_crash(
    integration_http_probe: Path, postgres_dsn: str, tmp_path: Path
) -> None:
    root = tmp_path / "research"
    root.mkdir()
    empty = call(integration_http_probe, action="frozen-inventory", root=str(root))
    assert empty == {"revisions": [], "relations": [], "revision_tree_present": False, "relation_tree_present": False}
    repo = Path(__file__).resolve().parents[4]
    rows = [
        json.loads(line) for line in (repo / "test-data/strategy/product-sources-v1.jsonl").read_text().splitlines()
    ]
    source = next(row["record"] for row in rows if row["case"] == "sixty-five-nodes")
    assert len(only_canonical_json(source).encode()) > 32768
    identity, relation = pair(root, source)
    valid = call(integration_http_probe, action="frozen-inventory", root=str(root))
    assert valid == {
        "revisions": [identity],
        "relations": [relation],
        "revision_tree_present": True,
        "relation_tree_present": True,
    }
    assert (
        call(integration_http_probe, action="frozen-inventory", root=str(root), max_work=1024)["error"]
        == "STRATEGY_STORE_UNAVAILABLE"
    )
    assert (
        call(integration_http_probe, action="frozen-inventory", root=str(root), lose_guard=True)["error"]
        == "STRATEGY_AUTHORITY_UNAVAILABLE"
    )
    path = root / "strategy/frozen-revisions/sha256" / identity[:2] / identity / "manifest.json"
    path.unlink()
    path.parent.rmdir()
    orphan = call(integration_http_probe, action="frozen-inventory", root=str(root))
    assert orphan["revisions"] == [] and orphan["relations"] == [relation]
    assert not path.exists()


def test_current_freeze_relation_fixture_has_original_model_identity() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[4] / "packages/backend/tests/application/fixtures/frozen_strategy.json"
    )
    fixture = json.loads(fixture_path.read_text())
    relation = OnlyStrategyFreezeRelation.from_dict(fixture["relation"])
    assert relation.to_dict() == fixture["relation"]
    assert str(OnlyStrategyRevision.from_dict(fixture["source"]).strategy_fingerprint) == relation.strategy_fingerprint
