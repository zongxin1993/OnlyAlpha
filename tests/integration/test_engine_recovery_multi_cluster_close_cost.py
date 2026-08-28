from pathlib import Path

import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngineConfig
from onlyalpha.engine.engine import OnlyEngine
from onlyalpha.result import only_backtest_business_projection
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.execution.support.execution_fault_injection import OnlyTestRuntimePersistenceFault
from tests.integration.test_engine_multi_cluster_close_cost_authority import _configs
from tests.integration.virtual_multi_fill_support import OnlyMultiFillFaultStoreFactory
from tests.support.recovery_baselines import assert_recovery_equivalent, load_recovery_baseline


def _add_configs(engine: OnlyEngine, user_data_root: Path) -> None:
    for config in _configs(user_data_root):
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
    _add_configs(failed, tmp_path)
    failed_result = failed.run()
    assert failed_result.status == "FAILED"

    recovered = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    _add_configs(recovered, tmp_path)
    recovered_result = recovered.run()
    assert recovered_result.status == "COMPLETED", recovered_result.failures

    actual = recovered_result.runtime_results[0]
    assert_recovery_equivalent(load_recovery_baseline("multi_cluster_close_baseline"), actual)


def test_completed_multi_cluster_close_checkpoint_restart_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    engine_id = OnlyEngineId("multi-cluster-close-checkpoint")
    first = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    _add_configs(first, tmp_path)
    first_result = first.run()
    assert first_result.status == "COMPLETED", first_result.failures

    restarted = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    _add_configs(restarted, tmp_path)
    restarted_result = restarted.run()
    assert restarted_result.status == "COMPLETED", restarted_result.failures
    assert only_backtest_business_projection(first_result.runtime_results[0]) == only_backtest_business_projection(
        restarted_result.runtime_results[0]
    )
