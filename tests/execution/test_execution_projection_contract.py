import json
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
    only_decode_prepared_execution_transaction,
    only_encode_prepared_execution_transaction,
    only_execution_state_hash,
)
from tests.execution.factories.transaction_factory import (
    only_test_all_projection_types_transaction,
    only_test_generic_t0_cash_buy_open_projections,
    only_test_generic_t0_cash_buy_open_transaction,
)


def test_canonical_state_hash_covers_authority_and_normalizes_mapping_order() -> None:
    order = only_test_generic_t0_cash_buy_open_projections()[0].before
    assert only_execution_state_hash(None) == "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"
    assert only_execution_state_hash(order) == only_execution_state_hash(order)
    left = replace(order, metadata={"b": "2", "a": "1"})
    right = replace(order, metadata={"a": "1", "b": "2"})
    assert only_execution_state_hash(left) == only_execution_state_hash(right)
    assert only_execution_state_hash(
        replace(order, updated_at=OnlyTimestamp(order.updated_at.unix_nanos + 1))
    ) != only_execution_state_hash(order)
    assert only_execution_state_hash(replace(order, tags=("authority-change",))) != only_execution_state_hash(order)


def test_all_projection_types_schema_v3_round_trip_and_v2_rejection() -> None:
    prepared = only_test_all_projection_types_transaction()
    assert len(prepared.projections) == len(OnlyExecutionProjectionComponent) == 15
    payload = only_encode_prepared_execution_transaction(prepared)
    assert only_decode_prepared_execution_transaction(payload) == prepared
    old = json.loads(payload)
    old["schema_version"] = 2
    try:
        only_decode_prepared_execution_transaction(json.dumps(old))
    except ValueError as exc:
        assert "schema version" in str(exc)
    else:
        raise AssertionError("schema v2 must not be decoded implicitly")


def test_projection_state_enforces_apply_idempotency_payload_and_version_contract() -> None:
    projection = only_test_generic_t0_cash_buy_open_projections()[3]
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


def test_projection_state_distinguishes_state_hash_from_version_conflict() -> None:
    projection = only_test_generic_t0_cash_buy_open_projections()[3]
    state = OnlyInMemoryExecutionProjectionState(OnlyExecutionProjectionComponent.SETTLEMENT)
    state.seed(projection.identity.entity_key, projection.identity.expected_version, "f" * 64)
    assert state.apply_execution_projection(1, projection).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_projection_applier_replay_is_idempotent_and_does_not_mark_store_ready() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlyInMemoryExecutionTransactionStore()
    transaction = store.commit(
        prepared, committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    ).transaction
    targets = {
        component: OnlyInMemoryExecutionProjectionState(component) for component in OnlyExecutionProjectionComponent
    }
    for projection in transaction.projections:
        if projection.identity.expected_version:
            targets[projection.identity.component].seed(
                projection.identity.entity_key,
                projection.identity.expected_version,
                projection.identity.expected_state_hash,
            )
    applier = OnlyExecutionProjectionApplier(targets)
    first = applier.apply(transaction)
    replay = applier.apply(transaction)
    assert first.status is OnlyExecutionProjectionBatchStatus.COMPLETED and len(first.applied) == 9
    assert replay.status is OnlyExecutionProjectionBatchStatus.COMPLETED and len(replay.idempotent) == 9
    assert store.unprojected(prepared.runtime_id) == (transaction,)
