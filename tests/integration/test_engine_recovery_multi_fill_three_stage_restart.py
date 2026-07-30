from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.execution.support.execution_fault_injection import OnlyTestRuntimePersistenceFault
from tests.integration.virtual_multi_fill_support import (
    OnlyMultiFillFaultStoreFactory,
    only_virtual_multi_fill_config,
)


def test_multi_fill_a_b_c_restart_matches_no_fault_baseline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = only_virtual_multi_fill_config()
    engine_id = OnlyEngineId("multi-fill-three-stage")
    fault_factory = OnlyMultiFillFaultStoreFactory(OnlyTestRuntimePersistenceFault.AFTER_COMMIT)
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=fault_factory),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"
    engine_b = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyMultiFillFaultStoreFactory(
                OnlyTestRuntimePersistenceFault.AFTER_COMMIT
            )
        ),
    )
    engine_b.add_cluster(config)
    assert engine_b.run().status == "FAILED"
    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_c.add_cluster(config)
    recovered = engine_c.run()
    assert recovered.status == "COMPLETED", recovered.failures
    baseline = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    baseline.add_cluster(config)
    expected = baseline.run()
    assert expected.status == "COMPLETED", expected.failures
    assert recovered.runtime_results[0].result_fingerprint == expected.runtime_results[0].result_fingerprint
    assert recovered.runtime_results[0].orders == expected.runtime_results[0].orders
    assert recovered.runtime_results[0].trades == expected.runtime_results[0].trades
    assert only_backtest_business_projection(recovered.runtime_results[0]) == only_backtest_business_projection(
        expected.runtime_results[0]
    )
