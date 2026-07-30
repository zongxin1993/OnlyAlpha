import json
from dataclasses import replace
from datetime import UTC, datetime

from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.execution import (
    OnlyExecutionProjectionApplier,
    OnlyExecutionProjectionApplyContext,
    OnlyExecutionProjectionBatchStatus,
    OnlyExecutionProjectionComponent,
    OnlyProjectionApplyStatus,
    OnlyReferenceExecutionProjectionTarget,
    only_decode_execution_projection,
    only_decode_prepared_execution_transaction,
    only_encode_execution_projection,
    only_encode_prepared_execution_transaction,
    only_execution_state_hash,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from tests.execution.factories.transaction_factory import (
    only_test_generic_t0_cash_buy_open_projections,
    only_test_generic_t0_cash_buy_open_transaction,
    only_test_projection_codec_cases,
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


def test_projection_union_cases_round_trip_independently_and_schema_v2_is_rejected() -> None:
    projections = only_test_projection_codec_cases()
    assert len(projections) == len(OnlyExecutionProjectionComponent) == 16
    for projection in projections:
        payload = only_encode_execution_projection(projection)
        assert only_decode_execution_projection(payload) == projection
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    payload = only_encode_prepared_execution_transaction(prepared)
    assert only_decode_prepared_execution_transaction(payload) == prepared
    old = json.loads(payload)
    old["schema_version"] = 3
    try:
        only_decode_prepared_execution_transaction(json.dumps(old))
    except ValueError as exc:
        assert "schema version" in str(exc)
    else:
        raise AssertionError("schema v3 must not be decoded implicitly")


def test_projection_state_enforces_apply_idempotency_payload_and_version_contract() -> None:
    transaction = _committed_transaction()
    projection = only_test_generic_t0_cash_buy_open_projections()[3]
    state = OnlyReferenceExecutionProjectionTarget(OnlyExecutionProjectionComponent.SETTLEMENT)
    context = OnlyExecutionProjectionApplyContext(transaction.transaction_id, 1, transaction.fact, projection)
    assert state.apply_execution_projection(context).status is OnlyProjectionApplyStatus.APPLIED
    assert state.apply_execution_projection(context).status is OnlyProjectionApplyStatus.IDEMPOTENT
    conflicting = replace(projection, identity=replace(projection.identity, payload_hash="b" * 64))
    conflict_context = replace(context, projection=conflicting)
    assert state.apply_execution_projection(conflict_context).status is OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
    stale = replace(
        projection,
        identity=replace(projection.identity, projection_sequence=1, payload_hash=projection.identity.payload_hash),
    )
    stale_context = replace(
        context, execution_sequence=2, fact=replace(transaction.fact, execution_sequence=2), projection=stale
    )
    assert state.apply_execution_projection(stale_context).status is OnlyProjectionApplyStatus.VERSION_CONFLICT
    wrong = OnlyReferenceExecutionProjectionTarget(OnlyExecutionProjectionComponent.ORDER)
    assert wrong.apply_execution_projection(context).status is OnlyProjectionApplyStatus.INVALID_COMPONENT


def test_projection_state_distinguishes_state_hash_from_version_conflict() -> None:
    transaction = _committed_transaction()
    projection = only_test_generic_t0_cash_buy_open_projections()[3]
    state = OnlyReferenceExecutionProjectionTarget(OnlyExecutionProjectionComponent.SETTLEMENT)
    state.seed(projection.identity.entity_key, projection.identity.expected_version, "f" * 64)
    context = OnlyExecutionProjectionApplyContext(transaction.transaction_id, 1, transaction.fact, projection)
    assert state.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_projection_applier_replay_is_idempotent_and_does_not_mark_store_ready() -> None:
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    store = OnlyInMemoryRuntimePersistenceStore()
    transaction = store.commit(
        prepared, committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC))
    ).transaction
    targets = {
        component: OnlyReferenceExecutionProjectionTarget(component) for component in OnlyExecutionProjectionComponent
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
    assert first.status is OnlyExecutionProjectionBatchStatus.COMPLETED and len(first.applied) == 12
    assert replay.status is OnlyExecutionProjectionBatchStatus.COMPLETED and len(replay.idempotent) == 12
    assert store.unprojected(prepared.runtime_id) == (transaction,)


def _committed_transaction():
    prepared = only_test_generic_t0_cash_buy_open_transaction()
    return (
        OnlyInMemoryRuntimePersistenceStore()
        .commit(prepared, committed_at=OnlyTimestamp.from_datetime(datetime(2026, 1, 1, 0, 1, tzinfo=UTC)))
        .transaction
    )
