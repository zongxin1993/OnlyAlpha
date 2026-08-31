from dataclasses import replace

import pytest

from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyClusterId,
    OnlyEngineId,
    OnlyOrderRequestId,
    OnlyRuntimeId,
    OnlyVenueOrderId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.enums import OnlyOrderApplyResult
from onlyalpha.order.id_generator import OnlySequenceOrderIdGenerator
from onlyalpha.order.manager import OnlyOrderManager
from tests.order.fee_contract import only_test_zero_fee_contract


def test_indexes_and_open_orders_stay_consistent(order_manager: OnlyOrderManager, order_request, created_order) -> None:
    snapshot = created_order.snapshot
    assert order_manager.find_by_client_order_id(snapshot.client_order_id) == snapshot
    assert order_manager.list_by_cluster(OnlyClusterId("cluster-a")) == (snapshot,)
    assert order_manager.list_by_account(OnlyAccountId("account")) == (snapshot,)
    assert order_manager.list_by_instrument(order_request.instrument_id) == (snapshot,)
    assert order_manager.list_open_orders() == (snapshot,)


def test_request_id_deduplication_does_not_allocate_second_order(
    order_manager: OnlyOrderManager, order_request, created_order
) -> None:
    assert order_request.request_id == OnlyOrderRequestId("request-1")
    duplicate = order_manager.create_order(
        order_request,
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(2),
    )
    assert order_manager.snapshot_all() == (created_order.snapshot,)
    assert duplicate.order_id == created_order.order_id


class _ConstantClientOrderIdGenerator:
    def next_id(self) -> OnlyClientOrderId:
        return OnlyClientOrderId("same-client-id")

    def checkpoint_sequence(self) -> int:
        return 0

    def restore_checkpoint_sequence(self, sequence: int) -> None:
        if sequence != 0:
            raise ValueError("unexpected sequence")


def test_client_and_venue_identity_conflicts_fail_closed(order_request) -> None:
    runtime_id = OnlyRuntimeId("runtime")
    manager = OnlyOrderManager(
        OnlyEngineId("engine"),
        runtime_id,
        OnlySequenceOrderIdGenerator(runtime_id),
        _ConstantClientOrderIdGenerator(),
    )
    first = manager.create_order(
        order_request,
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(1),
        only_test_zero_fee_contract,
    )
    with pytest.raises(ValueError, match="CLIENT_ORDER_IDENTITY_CONFLICT"):
        manager.create_order(
            replace(order_request, request_id=OnlyOrderRequestId("request-2")),
            OnlyClusterId("cluster-a"),
            OnlyAccountId("account"),
            OnlyTimestamp.from_unix_nanos(2),
            only_test_zero_fee_contract,
        )

    other_runtime = OnlyRuntimeId("other-runtime")
    other = OnlyOrderManager(
        OnlyEngineId("engine"),
        other_runtime,
        OnlySequenceOrderIdGenerator(other_runtime),
        _ConstantClientOrderIdGenerator(),
    )
    conflicting = other.create_order(
        replace(order_request, request_id=OnlyOrderRequestId("request-3")),
        OnlyClusterId("cluster-a"),
        OnlyAccountId("account"),
        OnlyTimestamp.from_unix_nanos(2),
        only_test_zero_fee_contract,
    )
    conflict_snapshot = replace(
        conflicting.snapshot,
        runtime_id=runtime_id,
        client_order_id=first.snapshot.client_order_id,
    )
    with pytest.raises(ValueError, match="CLIENT_ORDER_IDENTITY_CONFLICT"):
        manager.restore_execution_authority(
            conflict_snapshot,
            external_event_ids=frozenset(),
            trade_ids=frozenset(),
            venue_trade_ids=frozenset(),
        )

    manager.mark_submitted(first.order_id, OnlyTimestamp.from_unix_nanos(3))
    accepted = manager.apply_accepted(
        first.order_id,
        OnlyTimestamp.from_unix_nanos(4),
        OnlyVenueOrderId("one-venue-order"),
    )
    assert accepted.apply_result is OnlyOrderApplyResult.APPLIED
    other.mark_submitted(conflicting.order_id, OnlyTimestamp.from_unix_nanos(3))
    other.apply_accepted(
        conflicting.order_id,
        OnlyTimestamp.from_unix_nanos(4),
        OnlyVenueOrderId("one-venue-order"),
    )
    venue_conflict = replace(
        other.require_snapshot(conflicting.order_id),
        runtime_id=runtime_id,
        client_order_id=OnlyClientOrderId("other-client-id"),
    )
    with pytest.raises(ValueError, match="VENUE_ORDER_IDENTITY_CONFLICT"):
        manager.restore_execution_authority(
            venue_conflict,
            external_event_ids=frozenset(),
            trade_ids=frozenset(),
            venue_trade_ids=frozenset(),
        )
