import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.execution.support.execution_fault_injection import OnlyTestRuntimePersistenceFault
from tests.integration.test_engine_multi_cluster_close_cost_authority import _configs
from tests.integration.virtual_multi_fill_support import OnlyMultiFillFaultStoreFactory


def _add_configs(engine: OnlyEngine) -> None:
    for config in _configs():
        engine.add_cluster(config)


@pytest.mark.parametrize(
    "fault",
    (OnlyTestRuntimePersistenceFault.AFTER_COMMIT, OnlyTestRuntimePersistenceFault.MARK_READY),
)
def test_multi_cluster_close_recovery_matches_baseline(tmp_path, fault) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId(f"multi-cluster-close-{fault.value.lower()}")
    failed = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyMultiFillFaultStoreFactory(fault, fault_after=2)
        ),
    )
    _add_configs(failed)
    failed_result = failed.run()
    assert failed_result.status == "FAILED"

    recovered = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    _add_configs(recovered)
    recovered_result = recovered.run()
    assert recovered_result.status == "COMPLETED", recovered_result.failures

    baseline = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path / "baseline"))
    _add_configs(baseline)
    baseline_result = baseline.run()
    assert baseline_result.status == "COMPLETED", baseline_result.failures
    actual = recovered_result.runtime_results[0]
    expected = baseline_result.runtime_results[0]
    assert actual.trades == expected.trades
    assert actual.final_positions == expected.final_positions
    assert actual.final_allocations == expected.final_allocations
    assert actual.final_account == expected.final_account
    assert actual.final_ledgers == expected.final_ledgers
    assert actual.result_fingerprint == expected.result_fingerprint
    assert only_backtest_business_projection(actual) == only_backtest_business_projection(expected)


def test_completed_multi_cluster_close_checkpoint_restart_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId("multi-cluster-close-checkpoint")
    first = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    _add_configs(first)
    first_result = first.run()
    assert first_result.status == "COMPLETED", first_result.failures

    restarted = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    _add_configs(restarted)
    restarted_result = restarted.run()
    assert restarted_result.status == "COMPLETED", restarted_result.failures
    assert only_backtest_business_projection(first_result.runtime_results[0]) == only_backtest_business_projection(
        restarted_result.runtime_results[0]
    )
