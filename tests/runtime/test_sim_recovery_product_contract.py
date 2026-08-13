from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from onlyalpha.config import OnlyClusterRunConfig
from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.runtime.defaults import only_default_engine_services
from onlyalpha.runtime.planning import OnlyRuntimePlanner
from tests.runtime_support.market_product import only_generic_market_product

pytestmark = [pytest.mark.contract, pytest.mark.sim_recovery]


def _plan(change: object | None = None):  # type: ignore[no-untyped-def]
    baseline = OnlyClusterRunConfig.load("tests/fixtures/legacy_macd/cluster.json")
    payload: dict[str, Any] = json.loads(json.dumps(dict(baseline.normalized_payload)))
    payload["runtime"]["type"] = "SIM"
    payload["runtime"]["start_time"] = None
    payload["runtime"]["end_time"] = None
    payload["runtime"]["extensions"] = {"execution_capability": "SIMULATED"}
    payload["cluster"]["runtime_type"] = "SIM"
    payload["data_sources"][0]["plugin"] = "miniqmt"
    if callable(change):
        change(payload)
    config = OnlyClusterRunConfig.from_mapping(payload, source_path=baseline.source_path)
    binding = only_generic_market_product(config.reference_data.instruments[0])
    return (
        OnlyRuntimePlanner()
        .plan(
            OnlyEngineId("sim-durable-contract"),
            (config,),
            {config.cluster_id: binding},
        )
        .runtime_plans[0]
    )


@pytest.mark.parametrize(
    ("backend", "checkpoint"),
    (("MEMORY", False), ("SQLITE", False), ("SQLITE", True)),
)
def test_supported_sim_persistence_compositions(backend: str, checkpoint: bool, tmp_path: Path) -> None:
    def change(payload: dict[str, Any]) -> None:
        persistence: dict[str, object] = {
            "backend": backend,
            "checkpoint": {"enabled": checkpoint},
        }
        if backend == "SQLITE":
            persistence["path"] = "runtime.sqlite3"
        payload["runtime"]["persistence"] = persistence

    assert only_default_engine_services().assembler.validate(_plan(change), tmp_path).failure_code is None


def test_checkpoint_enabled_sim_without_stable_root_fails_closed() -> None:
    def change(payload: dict[str, Any]) -> None:
        payload["runtime"]["persistence"] = {
            "backend": "SQLITE",
            "path": "runtime.sqlite3",
            "checkpoint": {"enabled": True},
        }

    result = only_default_engine_services().assembler.validate(_plan(change))

    assert result.failure_code == "SIM_DURABLE_STATE_ROOT_REQUIRED"
