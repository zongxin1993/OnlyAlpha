from dataclasses import replace
from datetime import UTC, datetime

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionBatchStatus,
    OnlyExecutionProjectionComponent,
    OnlyInMemoryExecutionProjectionState,
    OnlyInMemoryExecutionTransactionStore,
    OnlyProjectionApplyStatus,
)
from tests.execution.factories.transaction_factory import (
    only_test_execution_projections,
    only_test_prepared_execution_transaction,
)


def test_projection_state_enforces_apply_idempotency_payload_and_version_contract() -> None:
    projection = only_test_execution_projections()[3]
    state = OnlyInMemoryExecutionProjectionState(OnlyExecutionProjectionComponent.SETTLEMENT)
    assert state.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.APPLIED
    assert state.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.IDEMPOTENT
    conflicting = replace(projection, identity=replace(projection.identity, payload_hash="b" * 64))
    assert state.apply_execution_projection(1, conflicting).status is OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
    stale = replace(
        projection,
        identity=replace(projection.identity, projection_sequence=1, payload_hash=projection.identity.payload_hash),
    )
    assert state.apply_execution_projection(2, stale).status is OnlyProjectionApplyStatus.VERSION_CONFLICT
    wrong = OnlyInMemoryExecutionProjectionState(OnlyExecutionProjectionComponent.ORDER)
    assert wrong.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.INVALID_COMPONENT


def test_projection_applier_replay_is_idempotent_and_does_not_mark_store_ready() -> None:
    prepared = only_test_prepared_execution_transaction()
    store = OnlyInMemoryExecutionTransactionStore()
    transaction = store.commit(
        prepared, committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    ).transaction
    targets = {
        component: OnlyInMemoryExecutionProjectionState(component) for component in OnlyExecutionProjectionComponent
    }
    applier = OnlyExecutionProjectionApplier(targets)
    first = applier.apply(transaction)
    replay = applier.apply(transaction)
    assert first.status is OnlyExecutionProjectionBatchStatus.COMPLETED and len(first.applied) == 15
    assert replay.status is OnlyExecutionProjectionBatchStatus.COMPLETED and len(replay.idempotent) == 15
    assert store.unprojected(prepared.runtime_id) == (transaction,)
