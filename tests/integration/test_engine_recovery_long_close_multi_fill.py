import pytest

from onlyalpha.domain.identifiers import OnlyEngineId
from onlyalpha.engine import OnlyEngine, OnlyEngineConfig
from onlyalpha.runtime.defaults import only_default_engine_services
from tests.execution.support.execution_fault_injection import OnlyTestRuntimePersistenceFault
from tests.integration.virtual_multi_fill_support import (
    OnlyMultiFillFaultStoreFactory,
    OnlyOutboxCheckpointFailureStoreFactory,
    OnlyPlanCursorCheckpointFailureStoreFactory,
    only_assert_multi_fill_recovery_equivalence,
    only_virtual_multi_fill_config,
)
from tests.support.recovery_baselines import assert_recovery_equivalent, load_recovery_baseline


@pytest.mark.parametrize(
    "fault",
    (
        OnlyTestRuntimePersistenceFault.COMMIT,
        OnlyTestRuntimePersistenceFault.AFTER_COMMIT,
        OnlyTestRuntimePersistenceFault.MARK_READY,
    ),
)
def test_long_close_multi_fill_recovers_commit_and_projection_boundaries(tmp_path, fault) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId(f"long-close-{fault.value.lower()}"),
        factory=OnlyMultiFillFaultStoreFactory(fault, fault_after=3),
        config=only_virtual_multi_fill_config(tmp_path, long_close=True),
        baseline_id="long_close_multi_fill_baseline",
    )


@pytest.mark.parametrize("cursor", (1, 2))
def test_long_close_checkpoint_continues_after_exact_fill_cursor(tmp_path, cursor: int) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId(f"long-close-checkpoint-fill-{cursor}"),
        factory=OnlyPlanCursorCheckpointFailureStoreFactory(cursor, plan_index=1),
        config=only_virtual_multi_fill_config(tmp_path, long_close=True),
        baseline_id="long_close_multi_fill_baseline",
    )


def test_long_close_checkpoint_between_broker_execute_and_publish_restores_pending_fill(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("long-close-broker-publish"),
        factory=OnlyPlanCursorCheckpointFailureStoreFactory(1, plan_index=1),
        config=only_virtual_multi_fill_config(tmp_path, long_close=True, fill_latency_ns=60_000_000_000),
    )


def test_long_close_pending_outbox_recovers_without_double_projection(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("long-close-outbox"),
        factory=OnlyOutboxCheckpointFailureStoreFactory(minimum_execution_sequence=6),
        config=only_virtual_multi_fill_config(tmp_path, long_close=True),
        baseline_id="long_close_multi_fill_baseline",
    )


def test_long_close_a_b_c_restart_matches_no_fault_baseline(tmp_path) -> None:  # type: ignore[no-untyped-def]
    config = only_virtual_multi_fill_config(tmp_path, long_close=True)
    engine_id = OnlyEngineId("long-close-three-stage")
    fault = OnlyTestRuntimePersistenceFault.AFTER_COMMIT
    engine_a = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(
            runtime_persistence_store_factory=OnlyMultiFillFaultStoreFactory(fault, fault_after=3)
        ),
    )
    engine_a.add_cluster(config)
    assert engine_a.run().status == "FAILED"
    engine_b = OnlyEngine(
        OnlyEngineConfig(engine_id, tmp_path),
        services=only_default_engine_services(runtime_persistence_store_factory=OnlyMultiFillFaultStoreFactory(fault)),
    )
    engine_b.add_cluster(config)
    assert engine_b.run().status == "FAILED"
    engine_c = OnlyEngine(OnlyEngineConfig(engine_id, tmp_path))
    engine_c.add_cluster(config)
    recovered = engine_c.run()
    assert recovered.status == "COMPLETED", recovered.failures
    actual = recovered.runtime_results[0]
    assert_recovery_equivalent(load_recovery_baseline("long_close_multi_fill_baseline"), actual)
