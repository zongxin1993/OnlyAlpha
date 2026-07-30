from onlyalpha.domain.identifiers import OnlyEngineId
from tests.integration.virtual_multi_fill_support import (
    OnlyPlanCursorCheckpointFailureStoreFactory,
    only_assert_multi_fill_recovery_equivalence,
    only_virtual_multi_fill_config,
)


def test_checkpoint_covering_fill_one_continues_from_fill_two(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-checkpoint-continuation"),
        factory=OnlyPlanCursorCheckpointFailureStoreFactory(1),
    )


def test_checkpoint_between_broker_execute_and_publish_restores_pending_fill(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-publish-continuation"),
        factory=OnlyPlanCursorCheckpointFailureStoreFactory(1),
        config=only_virtual_multi_fill_config(fill_latency_ns=60_000_000_000),
    )


def test_checkpoint_covering_fill_one_and_two_executes_only_final_fill(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-checkpoint-final-continuation"),
        factory=OnlyPlanCursorCheckpointFailureStoreFactory(2),
    )


def test_checkpoint_between_final_broker_execute_and_publish_restores_terminal_fill(tmp_path) -> None:  # type: ignore[no-untyped-def]
    only_assert_multi_fill_recovery_equivalence(
        tmp_path,
        OnlyEngineId("multi-fill-final-publish-continuation"),
        factory=OnlyPlanCursorCheckpointFailureStoreFactory(3),
        config=only_virtual_multi_fill_config(fill_latency_ns=60_000_000_000),
    )
