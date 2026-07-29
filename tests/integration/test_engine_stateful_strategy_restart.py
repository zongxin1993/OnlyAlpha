from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from tests.integration.test_engine_continuous_restart import (
    _sqlite_config,
    only_assert_engine_restart_equivalence,
)


def test_stateful_macd_strategy_factor_and_indicator_restart(tmp_path: Path) -> None:
    only_assert_engine_restart_equivalence(tmp_path)
    config = _sqlite_config()
    engine_c = OnlyEngine(OnlyEngineConfig(OnlyEngineId("execution-restart"), tmp_path))
    engine_c.add_cluster(config)
    result_c = engine_c.run()
    assert result_c.status == "COMPLETED"
    baseline = OnlyEngine(OnlyEngineConfig(OnlyEngineId("execution-restart"), tmp_path / "second-baseline"))
    baseline.add_cluster(config)
    baseline_result = baseline.run()
    assert baseline_result.status == "COMPLETED"
    assert result_c.runtime_results[0].facts.signals == baseline_result.runtime_results[0].facts.signals
    assert result_c.runtime_results[0].result_fingerprint == baseline_result.runtime_results[0].result_fingerprint
