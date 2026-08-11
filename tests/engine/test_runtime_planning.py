from __future__ import annotations

import inspect
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

import pytest

from onlyalpha.config import (
    OnlyClusterCapitalConfig,
    OnlyClusterCapitalMode,
    OnlyClusterRunConfig,
)
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyEngineId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.market.product import OnlyResolvedMarketProductBinding
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.factory import OnlyRuntimeBuildResult
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from tests.runtime_support.market_product import only_generic_market_product

CONFIG = "tests/fixtures/legacy_macd/cluster.json"
FAST_CONFIG = "tests/fixtures/legacy_macd/cluster_fast.json"


def _bindings(
    configs: tuple[OnlyClusterRunConfig, ...],
) -> dict[OnlyClusterId, OnlyResolvedMarketProductBinding]:
    return {config.cluster_id: only_generic_market_product(config.reference_data.instruments[0]) for config in configs}


def _multi_configs() -> tuple[OnlyClusterRunConfig, OnlyClusterRunConfig]:
    configs = (OnlyClusterRunConfig.load(CONFIG), OnlyClusterRunConfig.load(FAST_CONFIG))
    return tuple(
        replace(
            config,
            cluster=replace(
                config.cluster,
                capital=OnlyClusterCapitalConfig(
                    OnlyClusterCapitalMode.FIXED_CAPITAL,
                    OnlyMoney(Decimal("500000.00"), config.accounts[0].initial_cash.currency),
                ),
            ),
        )
        for config in configs
    )  # type: ignore[return-value]


def test_runtime_planner_groups_compatible_clusters() -> None:
    configs = _multi_configs()
    plan = OnlyRuntimePlanner().plan(OnlyEngineId("planner"), configs, _bindings(configs))
    assert plan.cluster_count == 2
    assert len(plan.runtime_plans) == 1
    assert plan.runtime_plans[0].cluster_ids == tuple(item.cluster_id for item in configs)


def test_runtime_planner_separates_incompatible_clusters() -> None:
    first = OnlyClusterRunConfig.load(CONFIG)
    second = OnlyClusterRunConfig.load(FAST_CONFIG)
    changed = replace(second, runtime=replace(second.runtime, end_time=first.runtime.end_time.replace(day=7)))  # type: ignore[union-attr]
    configs = (first, changed)
    plan = OnlyRuntimePlanner().plan(OnlyEngineId("planner"), configs, _bindings(configs))
    assert len(plan.runtime_plans) == 2


def test_engine_add_cluster_does_not_build_or_close_runtime(tmp_path: Path) -> None:
    services = only_default_engine_services()
    assembler = services.assembler
    assembler.build = Mock()  # type: ignore[method-assign]
    assembler.validate = Mock()  # type: ignore[method-assign]
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId("no-build"), tmp_path),
        services=services,
    )
    engine.add_cluster_from_file(CONFIG)
    assembler.build.assert_not_called()
    assembler.validate.assert_not_called()


def test_engine_initialize_creates_runtime_and_cluster_sessions(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("sessions"), tmp_path))
    for config in _multi_configs():
        engine.add_cluster(config)
    engine.initialize()
    assert len(engine.runtime_sessions) == 1
    assert len(engine.cluster_sessions) == 2
    assert {item.runtime_id for item in engine.cluster_sessions} == {engine.runtime_sessions[0].runtime_id}
    assert all(item.cluster is not None and item.resource_references for item in engine.cluster_sessions)
    engine.stop()
    engine.stop()


def test_engine_initialize_preserves_primary_failure_when_partial_runtime_cleanup_fails(tmp_path: Path) -> None:
    runtime = Mock()
    runtime.initialize.side_effect = RuntimeError("runtime initialize failed")
    runtime.close.side_effect = RuntimeError("runtime cleanup failed")
    services = only_default_engine_services()
    assembler = services.assembler
    assembler.build = Mock(return_value=OnlyRuntimeBuildResult(runtime=runtime))  # type: ignore[method-assign]
    engine = OnlyEngine(
        OnlyEngineConfig(OnlyEngineId("initialize-primary-failure"), tmp_path),
        services=services,
    )
    engine.add_cluster_from_file(CONFIG)

    with pytest.raises(RuntimeError, match="runtime initialize failed") as raised:
        engine.initialize()

    runtime.close.assert_called_once_with()
    assert raised.value.__notes__ == [
        "Runtime initialization cleanup also failed: RuntimeError: runtime cleanup failed"
    ]


def test_engine_product_source_does_not_use_legacy_run_service() -> None:
    source = inspect.getsource(OnlyEngine)
    assert "OnlyEngineRunService" not in source
    assert "run_service" not in source
    assert "_merge_runtime_group" not in source


def test_engine_output_contains_runtime_plan_and_normalized_configs(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("outputs"), tmp_path))
    engine.add_cluster_from_file(CONFIG)
    result = engine.run()
    assert result.manifest_path is not None
    root = result.manifest_path.parent
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    runtime_id = manifest["clusters"][0]["runtime_id"]
    assert (root / f"runtimes/{runtime_id}/summary.json").is_file()
    reference = json.loads((root / f"runtimes/{runtime_id}/reference_snapshot.json").read_text(encoding="utf-8"))
    assert reference["composition_identity"]["fingerprint"]
    assert reference["reference_authority"]["authority_fingerprint"]
    assert reference["artifact_fingerprint"]
    assert (root / "clusters/macd-demo/normalized_config.json").is_file()
    assert not (tmp_path / "output").exists()


def test_engine_is_single_use_and_stop_is_idempotent(tmp_path: Path) -> None:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("single-use"), tmp_path))
    engine.add_cluster_from_file(CONFIG)
    assert engine.run().status == "COMPLETED"
    engine.stop()
    with pytest.raises(OnlyLifecycleError, match="ENGINE_ALREADY_TERMINATED"):
        engine.initialize()
    with pytest.raises(OnlyLifecycleError, match="ENGINE_ALREADY_TERMINATED"):
        engine.run()
