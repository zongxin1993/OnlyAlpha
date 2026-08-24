from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.result import only_backtest_business_projection
from tests.integration.test_engine_continuous_restart import (
    _sqlite_config,
    only_assert_engine_restart_equivalence,
)


def test_stateful_macd_strategy_factor_and_indicator_restart(tmp_path: Path) -> None:
    only_assert_engine_restart_equivalence(tmp_path)
    config = _sqlite_config(tmp_path)
    engine_c = OnlyEngine(OnlyEngineConfig(OnlyEngineId("execution-restart"), tmp_path))
    engine_c.add_cluster(config)
    result_c = engine_c.run()
    assert result_c.status == "COMPLETED"
    baseline_root = tmp_path / "second-baseline"
    baseline = OnlyEngine(OnlyEngineConfig(OnlyEngineId("execution-restart"), baseline_root))
    baseline.add_cluster(_sqlite_config(baseline_root))
    baseline_result = baseline.run()
    assert baseline_result.status == "COMPLETED"
    assert result_c.runtime_results[0].facts.signals == baseline_result.runtime_results[0].facts.signals
    recovered_projection = only_backtest_business_projection(result_c.runtime_results[0])
    baseline_projection = only_backtest_business_projection(baseline_result.runtime_results[0])
    assert recovered_projection == baseline_projection
