from __future__ import annotations

import json
from pathlib import Path

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.core.errors import OnlyLifecycleError
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig


def _sim_config() -> OnlyClusterRunConfig:
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = "SIM"
    payload["runtime"]["start_time"] = None
    payload["runtime"]["end_time"] = None
    payload["runtime"]["extensions"] = {"execution_capability": "SIMULATED"}
    payload["cluster"]["runtime_type"] = "SIM"
    payload["data_sources"][0]["plugin"] = "miniqmt"
    return OnlyClusterRunConfig.from_mapping(
        payload,
        source_path="tests/fixtures/legacy_macd/cluster.json",
    )


def _engine(root: Path) -> OnlyEngine:
    engine = OnlyEngine(OnlyEngineConfig(OnlyEngineId("sim-engine-contract"), root))
    engine.add_cluster(_sim_config())
    return engine


def test_engine_validation_accepts_operational_sim(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        validation = engine.validate()

        assert validation.valid
        assert validation.runtime_group_count == 1
        assert validation.errors == ()
    finally:
        engine.close()


def test_engine_run_remains_restricted_to_finite_backtest(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    try:
        with pytest.raises(
            OnlyLifecycleError,
            match=r"OnlyEngine\.run\(\) is restricted to finite BACKTEST execution",
        ):
            engine.run()
    finally:
        engine.close()
