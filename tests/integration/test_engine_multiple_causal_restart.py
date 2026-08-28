from pathlib import Path

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.integration.test_engine_continuous_restart import (
    OnlyFaultInjectingRuntimePersistenceStoreFactory,
)
from tests.integration.virtual_multi_fill_support import only_virtual_multi_fill_config


def test_engine_a_b_c_restarts_preserve_complete_business_result(tmp_path: Path) -> None:
    config = only_virtual_multi_fill_config(tmp_path, long_close=True)
    engine_id = OnlyEngineId("three-causal-restarts")

    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyFaultInjectingRuntimePersistenceStoreFactory()
        ),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"

    engine_b = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyFaultInjectingRuntimePersistenceStoreFactory()
        ),
    )
    engine_b.add_cluster(config)
    result_b = engine_b.run()

    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_c.add_cluster(config)
    result_c = engine_c.run()
    assert result_c.status == "COMPLETED"

    baseline_root = tmp_path / "baseline"
    baseline = OnlyEngine(OnlyEngineConfig(engine_id, baseline_root))
    baseline.add_cluster(only_virtual_multi_fill_config(baseline_root, long_close=True))
    baseline_result = baseline.run()
    assert baseline_result.status == "COMPLETED"
    assert only_backtest_business_projection(result_c.runtime_results[0]) == only_backtest_business_projection(
        baseline_result.runtime_results[0]
    )
    assert result_b.status == "FAILED"
