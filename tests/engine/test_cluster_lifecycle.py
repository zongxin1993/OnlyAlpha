import json
from pathlib import Path

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.errors import OnlyDuplicateIdError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId
from onlyalpha.engine import OnlyClusterLoadError, OnlyClusterRemovalPolicy, OnlyEngine, OnlyEngineConfig
from onlyalpha.engine.infrastructure import OnlyResourceConfigurationConflict

CONFIG = "tests/fixtures/legacy_macd/cluster.json"
FAST_CONFIG = "tests/fixtures/legacy_macd/cluster_fast.json"


def _engine(tmp_path: Path) -> OnlyEngine:
    return OnlyEngine(OnlyEngineConfig(OnlyEngineId("test-engine"), tmp_path))


def test_add_duplicate_and_remove_cluster(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    handle = engine.add_cluster_from_file(CONFIG)
    assert str(handle.cluster_id) == "macd-demo"
    with pytest.raises(OnlyDuplicateIdError):
        engine.add_cluster_from_file(CONFIG)
    removed = engine.remove_cluster(handle.cluster_id, policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert removed.success
    assert not engine.snapshot().clusters


def test_shared_resources_are_reference_counted(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    first = engine.add_cluster_from_file(CONFIG)
    second = engine.add_cluster_from_file(FAST_CONFIG)
    counts = dict(engine.snapshot().resource_reference_counts)
    assert counts["broker:virtual-main"] == 2
    first_result = engine.remove_cluster(first.cluster_id, policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert "broker:virtual-main" not in first_result.released_resources
    second_result = engine.remove_cluster(second.cluster_id, policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert "broker:virtual-main" in second_result.released_resources


def test_resource_configuration_conflict_rolls_back(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.add_cluster_from_file(CONFIG)
    baseline = OnlyClusterRunConfig.load(FAST_CONFIG)
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["brokers"][0]["extensions"]["commission"]["fixed_amount"]["value"] = "2.00"
    conflicting = OnlyClusterRunConfig.from_mapping(payload, source_path=FAST_CONFIG)
    before = engine.snapshot()
    with pytest.raises(OnlyResourceConfigurationConflict, match="RESOURCE_CONFIGURATION_CONFLICT"):
        engine.add_cluster(conflicting)
    assert engine.snapshot() == before


def test_dynamic_import_failure_rolls_back_all_resource_references(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    baseline = OnlyClusterRunConfig.load(CONFIG)
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["strategy"]["class_path"] = "missing.plugin:OnlyMissingStrategy"
    invalid = OnlyClusterRunConfig.from_mapping(payload, source_path=CONFIG)
    before = engine.snapshot()
    with pytest.raises(ModuleNotFoundError):
        engine.add_cluster(invalid)
    assert engine.snapshot() == before


def test_running_backtest_dynamic_add_is_structured_error(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    engine.add_cluster_from_file(CONFIG)
    engine.state = engine.state.RUNNING
    with pytest.raises(OnlyClusterLoadError, match="DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED") as captured:
        engine.add_cluster_from_file(FAST_CONFIG)
    assert captured.value.code == "DYNAMIC_CLUSTER_LOAD_NOT_SUPPORTED_IN_CURRENT_RUNTIME_PHASE"


def test_missing_cluster_remove_is_non_destructive(tmp_path: Path) -> None:
    result = _engine(tmp_path).remove_cluster(OnlyClusterId("missing"), policy=OnlyClusterRemovalPolicy.STOP_ONLY)
    assert not result.success
    assert result.code == "CLUSTER_NOT_FOUND"
