from dataclasses import replace
from datetime import UTC, datetime

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyCommittedExecutionFactDraft,
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionBatchStatus,
    OnlyExecutionProjectionComponent,
    OnlyExecutionProjectionIdentity,
    OnlyInMemoryExecutionProjectionState,
    OnlyInMemoryExecutionTransactionStore,
    OnlyPreparedExecutionTransaction,
    OnlyProjectionApplyStatus,
    OnlySettlementExecutionProjection,
    only_with_execution_projection_hash,
)
from tests.execution.test_committed_execution_journal import _fact


def _projection(*, expected_version: int = 0, payload_hash: str = "a" * 64) -> OnlySettlementExecutionProjection:
    projection = OnlySettlementExecutionProjection(
        OnlyExecutionProjectionIdentity(
            OnlyExecutionProjectionComponent.SETTLEMENT,
            "settlement",
            expected_version,
            expected_version + 1,
            1,
            payload_hash,
        ),
        "instruction",
        "PENDING",
        "SETTLED",
        ("record",),
    )
    if payload_hash != "a" * 64:
        return replace(projection, identity=replace(projection.identity, payload_hash=payload_hash))
    result = only_with_execution_projection_hash(projection)
    assert isinstance(result, OnlySettlementExecutionProjection)
    return result


def test_projection_state_enforces_apply_idempotency_payload_and_version_contract() -> None:
    state = OnlyInMemoryExecutionProjectionState(OnlyExecutionProjectionComponent.SETTLEMENT)
    projection = _projection()

    assert state.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.APPLIED
    assert state.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.IDEMPOTENT
    assert (
        state.apply_execution_projection(
            1, replace(projection, identity=replace(projection.identity, payload_hash="b" * 64))
        ).status
        is OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
    )
    assert (
        state.apply_execution_projection(2, _projection(expected_version=0)).status
        is OnlyProjectionApplyStatus.VERSION_CONFLICT
    )

    wrong = OnlyInMemoryExecutionProjectionState(OnlyExecutionProjectionComponent.ORDER)
    assert wrong.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.INVALID_COMPONENT


def test_projection_applier_replay_is_fully_idempotent_and_does_not_mark_store_ready() -> None:
    fact = _fact()
    prepared = OnlyPreparedExecutionTransaction(
        "transaction",
        fact.runtime_id,
        fact.gateway_id,
        fact.account_id,
        fact.broker_update_id,
        fact.trade_id,
        fact.source_sequence,
        fact.ts_init,
        OnlyCommittedExecutionFactDraft.from_committed(fact),
        (_projection(),),
        (),
        (),
    )
    store = OnlyInMemoryExecutionTransactionStore()
    transaction = store.commit(
        prepared, committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    ).transaction
    target = OnlyInMemoryExecutionProjectionState(OnlyExecutionProjectionComponent.SETTLEMENT)
    applier = OnlyExecutionProjectionApplier({OnlyExecutionProjectionComponent.SETTLEMENT: target})

    first = applier.apply(transaction)
    replay = applier.apply(transaction)

    assert first.status is OnlyExecutionProjectionBatchStatus.COMPLETED
    assert len(first.applied) == 1
    assert replay.status is OnlyExecutionProjectionBatchStatus.COMPLETED
    assert len(replay.idempotent) == 1
    assert store.unprojected(fact.runtime_id) == (transaction,)
