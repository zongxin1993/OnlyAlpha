from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyCurrencyType, OnlyDirection, OnlyOffset, OnlyOrderSide, OnlyRuntimeMode
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClusterId,
    OnlyInstrumentId,
    OnlyOrderId,
    OnlyRuntimeId,
    OnlySymbol,
    OnlyTradeId,
    OnlyVenueId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp, OnlyTradingDay
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.position import (
    OnlyBrokerPositionSnapshot,
    OnlyGatewayId,
    OnlyPositionAllocationManager,
    OnlyPositionAuthorityPolicy,
    OnlyPositionManager,
    OnlyPositionMutationStatus,
    OnlyPositionOverSellError,
    OnlyPositionReconciliationService,
    OnlyPositionReservationManager,
    OnlyPositionReservationStage,
    OnlyPositionRestriction,
    OnlyPositionRestrictionId,
    OnlyPositionRestrictionSource,
    OnlyPositionRestrictionType,
    OnlyPositionSide,
    OnlyPositionStatus,
    OnlyPositionTrade,
    OnlyReconciliationSeverity,
    OnlyRecordingPositionEventPublisher,
    OnlySettlementBucket,
    OnlySettlementService,
)
from onlyalpha.runtime.live.runtime import OnlyLiveRuntime
from onlyalpha.runtime.paper.runtime import OnlyPaperRuntime
from onlyalpha.runtime.runtime import OnlyRuntimeAssemblyConfig

RUNTIME = OnlyRuntimeId("runtime-position")
ACCOUNT = OnlyAccountId("account-1")
CLUSTER_A = OnlyClusterId("cluster-a")
CLUSTER_B = OnlyClusterId("cluster-b")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("600000"), OnlyVenueId("XSHG"))
CNY = OnlyCurrency("CNY", 2, OnlyCurrencyType.FIAT)


def trade(
    sequence: int,
    side: OnlyOrderSide,
    quantity: str,
    price: str,
    *,
    cluster: OnlyClusterId | None = CLUSTER_A,
    bucket: OnlySettlementBucket = OnlySettlementBucket.UNSETTLED,
    runtime: OnlyRuntimeId = RUNTIME,
) -> OnlyPositionTrade:
    timestamp = OnlyTimestamp(sequence * 1_000)
    return OnlyPositionTrade(
        OnlyTradeId(f"trade-{sequence}"),
        OnlyVenueTradeId(f"venue-trade-{sequence}"),
        OnlyOrderId(f"order-{sequence}"),
        cluster,
        runtime,
        ACCOUNT,
        INSTRUMENT,
        side,
        OnlyDirection.BUY if side is OnlyOrderSide.BUY else OnlyDirection.SELL,
        OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
        OnlyPositionSide.LONG,
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyMoney(Decimal("0.00"), CNY),
        timestamp,
        timestamp,
        sequence,
        settlement_bucket=bucket,
    )


def apply_both(
    positions: OnlyPositionManager,
    allocations: OnlyPositionAllocationManager,
    item: OnlyPositionTrade,
) -> None:
    positions.apply_trade(item)
    allocations.apply_trade(item)


def test_average_cost_t1_realized_pnl_and_new_lifecycle() -> None:
    positions = OnlyPositionManager(RUNTIME)
    first = trade(1, OnlyOrderSide.BUY, "100", "10", bucket=OnlySettlementBucket.SETTLED)
    positions.apply_trade(first)
    positions.apply_trade(trade(2, OnlyOrderSide.BUY, "50", "12"))
    snapshot = positions.list_open()[0]
    assert snapshot.total_quantity.value == Decimal("150")
    assert snapshot.settled_quantity.value == Decimal("100")
    assert snapshot.unsettled_quantity.value == Decimal("50")
    assert snapshot.available_quantity.value == Decimal("100")
    assert snapshot.average_open_price == OnlyPrice(Decimal("10.67"), 2)

    reduced = positions.apply_trade(trade(3, OnlyOrderSide.SELL, "40", "15"))
    assert reduced.realized_pnl_delta.amount == Decimal("173.20")
    assert reduced.after is not None
    assert reduced.after.average_open_price == OnlyPrice(Decimal("10.67"), 2)

    positions.apply_trade(trade(4, OnlyOrderSide.SELL, "60", "10"))
    positions.settle(positions.list_open()[0].key, OnlyTradingDay(date(2026, 7, 16)))
    closed = positions.apply_trade(trade(5, OnlyOrderSide.SELL, "50", "11"))
    assert closed.after is not None and closed.after.status is OnlyPositionStatus.CLOSED
    old_id = closed.after.position_id
    reopened = positions.apply_trade(trade(6, OnlyOrderSide.BUY, "10", "9"))
    assert reopened.after is not None and reopened.after.position_id != old_id


def test_over_sell_duplicate_stale_and_immutable_snapshot() -> None:
    positions = OnlyPositionManager(RUNTIME)
    opening = trade(10, OnlyOrderSide.BUY, "100", "10", bucket=OnlySettlementBucket.SETTLED)
    result = positions.apply_trade(opening)
    duplicate = positions.apply_trade(opening)
    assert duplicate.status is OnlyPositionMutationStatus.DUPLICATE
    assert duplicate.after == result.after
    with pytest.raises(OnlyPositionOverSellError):
        positions.apply_trade(trade(11, OnlyOrderSide.SELL, "101", "11"))
    with pytest.raises(FrozenInstanceError):
        assert result.after is not None
        result.after.version = 99  # type: ignore[misc]
    stale = trade(9, OnlyOrderSide.BUY, "1", "10")
    stale_result = positions.apply_trade(stale)
    assert stale_result.status is OnlyPositionMutationStatus.STALE
    assert stale_result.after is not None
    assert stale_result.after.status is OnlyPositionStatus.RECONCILING


def test_multi_cluster_cost_and_pnl_are_independent() -> None:
    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    apply_both(positions, allocations, trade(1, OnlyOrderSide.BUY, "100", "10", bucket=OnlySettlementBucket.SETTLED))
    apply_both(
        positions,
        allocations,
        trade(2, OnlyOrderSide.BUY, "100", "12", cluster=CLUSTER_B, bucket=OnlySettlementBucket.SETTLED),
    )
    account = positions.list_open()[0]
    a = allocations.list_by_cluster(CLUSTER_A)[0]
    b = allocations.list_by_cluster(CLUSTER_B)[0]
    assert account.average_open_price == OnlyPrice(Decimal("11.00"), 2)
    assert a.average_open_price == OnlyPrice(Decimal("10.00"), 2)
    assert b.average_open_price == OnlyPrice(Decimal("12.00"), 2)

    apply_both(positions, allocations, trade(3, OnlyOrderSide.SELL, "40", "15"))
    assert allocations.list_by_cluster(CLUSTER_A)[0].realized_pnl.amount == Decimal("200.00")
    assert allocations.list_by_cluster(CLUSTER_B)[0].total_quantity.value == Decimal("100")


def test_cluster_cannot_sell_other_allocation_and_unknown_goes_unallocated() -> None:
    allocations = OnlyPositionAllocationManager(RUNTIME)
    allocations.apply_trade(
        trade(1, OnlyOrderSide.BUY, "100", "10", cluster=CLUSTER_B, bucket=OnlySettlementBucket.SETTLED)
    )
    with pytest.raises(OnlyPositionOverSellError):
        allocations.apply_trade(trade(2, OnlyOrderSide.SELL, "1", "11", cluster=CLUSTER_A))
    allocations.apply_trade(trade(3, OnlyOrderSide.BUY, "25", "10", cluster=None))
    assert allocations.unallocated()[0].total_quantity.value == Decimal("25")


def test_t1_freeze_release_and_settlement_example() -> None:
    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    apply_both(
        positions,
        allocations,
        trade(1, OnlyOrderSide.BUY, "1000", "10", bucket=OnlySettlementBucket.SETTLED),
    )
    apply_both(positions, allocations, trade(2, OnlyOrderSide.BUY, "500", "11"))
    key = positions.list_open()[0].key
    positions.freeze(key, OnlyQuantity(Decimal("600"), 0))
    assert positions.require_snapshot(key).available_quantity.value == Decimal("400")
    positions.apply_trade(trade(3, OnlyOrderSide.SELL, "200", "12"))
    assert positions.require_snapshot(key).available_quantity.value == Decimal("400")
    positions.release(key, OnlyQuantity(Decimal("400"), 0))
    assert positions.require_snapshot(key).available_quantity.value == Decimal("800")
    service = OnlySettlementService(positions, allocations)
    service.settle_account(
        ACCOUNT,
        OnlyTradingDay(date(2026, 7, 15)),
        OnlyTradingDay(date(2026, 7, 16)),
    )
    assert positions.require_snapshot(key).unsettled_quantity.value == 0


def test_restriction_is_derived_into_available_quantity() -> None:
    positions = OnlyPositionManager(RUNTIME)
    positions.apply_trade(trade(1, OnlyOrderSide.BUY, "100", "10", bucket=OnlySettlementBucket.SETTLED))
    key = positions.list_open()[0].key
    restriction = OnlyPositionRestriction(
        OnlyPositionRestrictionId("restriction-1"),
        key,
        OnlyQuantity(Decimal("30"), 0),
        OnlyPositionRestrictionType.SUSPENDED_INSTRUMENT,
        OnlyPositionRestrictionSource.MARKET,
        OnlyTimestamp(2_000),
        None,
        "instrument suspended",
    )
    positions.apply_restriction(restriction)
    assert positions.require_snapshot(key).available_quantity.value == Decimal("70")
    positions.remove_restriction(key, restriction.restriction_id)
    assert positions.require_snapshot(key).available_quantity.value == Decimal("100")


def test_multi_cluster_reservation_and_broker_ack_no_double_freeze() -> None:
    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    apply_both(
        positions,
        allocations,
        trade(1, OnlyOrderSide.BUY, "700", "10", bucket=OnlySettlementBucket.SETTLED),
    )
    apply_both(
        positions,
        allocations,
        trade(2, OnlyOrderSide.BUY, "300", "10", cluster=CLUSTER_B, bucket=OnlySettlementBucket.SETTLED),
    )
    reservations = OnlyPositionReservationManager(RUNTIME, positions, allocations)
    now = OnlyTimestamp(10_000)
    created = reservations.create(
        ACCOUNT, CLUSTER_A, INSTRUMENT, OnlyOrderId("sell-a"), OnlyQuantity(Decimal("700"), 0), now
    )
    assert created.changed
    duplicate = reservations.create(
        ACCOUNT, CLUSTER_A, INSTRUMENT, OnlyOrderId("sell-a"), OnlyQuantity(Decimal("700"), 0), now
    )
    assert not duplicate.changed
    with pytest.raises(ValueError):
        reservations.create(ACCOUNT, CLUSTER_B, INSTRUMENT, OnlyOrderId("sell-b"), OnlyQuantity(Decimal("700"), 0), now)
    reservations.advance_stage(OnlyOrderId("sell-a"), OnlyPositionReservationStage.SENT_TO_BROKER, now)
    assert reservations.active_quantity(INSTRUMENT, local_only=True).value == Decimal("700")
    reservations.advance_stage(OnlyOrderId("sell-a"), OnlyPositionReservationStage.BROKER_ACKNOWLEDGED, now)
    assert positions.list_open()[0].risk_reserved_quantity.value == 0
    assert allocations.list_by_cluster(CLUSTER_A)[0].risk_reserved_quantity.value == Decimal("700")
    pending = reservations.release(OnlyOrderId("sell-a"), now, broker_confirmed=False)
    assert pending.reservation.stage is OnlyPositionReservationStage.RELEASE_PENDING
    released = reservations.release(OnlyOrderId("sell-a"), now, broker_confirmed=True)
    assert released.reservation.stage is OnlyPositionReservationStage.RELEASED


def broker_snapshot(total: str, available: str, settled: str, unsettled: str) -> OnlyBrokerPositionSnapshot:
    return OnlyBrokerPositionSnapshot(
        OnlyGatewayId("gateway-test"),
        ACCOUNT,
        INSTRUMENT,
        OnlyPositionSide.LONG,
        OnlyQuantity(Decimal(total), 0),
        OnlyQuantity(Decimal(available), 0),
        OnlyQuantity(Decimal(total) - Decimal(available), 0),
        OnlyQuantity(Decimal(settled), 0),
        OnlyQuantity(Decimal(unsettled), 0),
        OnlyQuantity(Decimal(unsettled), 0),
        OnlyQuantity(Decimal(settled), 0),
        OnlyPrice(Decimal("10.00"), 2),
        OnlyMoney(Decimal("10000.00"), CNY),
        OnlyTimestamp(50_000),
        1,
    )


def test_reconciliation_blocks_without_overwrite_and_creates_unallocated() -> None:
    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    positions.apply_trade(trade(1, OnlyOrderSide.BUY, "1000", "10", bucket=OnlySettlementBucket.SETTLED))
    allocations.apply_trade(trade(1, OnlyOrderSide.BUY, "700", "10", bucket=OnlySettlementBucket.SETTLED))
    service = OnlyPositionReconciliationService(
        RUNTIME,
        positions,
        allocations,
        OnlyPositionAuthorityPolicy(OnlyRuntimeMode.LIVE),
    )
    equal = service.reconcile(broker_snapshot("1000", "1000", "1000", "0"))
    assert equal.reconciled
    assert allocations.unallocated()[0].total_quantity.value == Decimal("300")

    conflict = service.reconcile(broker_snapshot("800", "800", "800", "0"))
    assert conflict.severity is OnlyReconciliationSeverity.BLOCK_INSTRUMENT
    assert conflict.local is not None
    assert conflict.local.total_quantity.value == Decimal("1000")
    assert conflict.local.status is OnlyPositionStatus.RECONCILING
    assert positions.is_blocked(ACCOUNT, INSTRUMENT)


def test_available_conflict_is_conservative_but_not_silent() -> None:
    positions = OnlyPositionManager(RUNTIME)
    allocations = OnlyPositionAllocationManager(RUNTIME)
    opening = trade(1, OnlyOrderSide.BUY, "1000", "10", bucket=OnlySettlementBucket.SETTLED)
    apply_both(positions, allocations, opening)
    service = OnlyPositionReconciliationService(
        RUNTIME,
        positions,
        allocations,
        OnlyPositionAuthorityPolicy(OnlyRuntimeMode.LIVE),
    )
    result = service.reconcile(broker_snapshot("1000", "800", "1000", "0"))
    assert result.severity is OnlyReconciliationSeverity.WARNING
    assert result.effective_available_quantity.value == Decimal("800")
    assert result.differences[0].field_name == "available_quantity"
    assert positions.list_open()[0].available_quantity.value == Decimal("800")


def test_events_follow_success_and_serialization_is_exact() -> None:
    publisher = OnlyRecordingPositionEventPublisher()
    positions = OnlyPositionManager(RUNTIME, publisher=publisher)
    item = trade(1, OnlyOrderSide.BUY, "100", "10")
    result = positions.apply_trade(item)
    positions.apply_trade(item)
    assert [event.event_type for event in publisher.events] == ["POSITION_OPENED"]
    assert result.after is not None
    restored = type(result.after).from_json(result.after.to_json())
    assert restored == result.after
    assert OnlyPositionTrade.from_json(item.to_json()) == item


def test_runtime_isolation_and_100_replays_are_deterministic() -> None:
    outputs: list[tuple[str, str, str, int]] = []
    for _ in range(100):
        positions = OnlyPositionManager(RUNTIME)
        allocations = OnlyPositionAllocationManager(RUNTIME)
        for item in (
            trade(1, OnlyOrderSide.BUY, "100", "10", bucket=OnlySettlementBucket.SETTLED),
            trade(2, OnlyOrderSide.BUY, "50", "12", bucket=OnlySettlementBucket.SETTLED),
            trade(3, OnlyOrderSide.SELL, "20", "15"),
        ):
            apply_both(positions, allocations, item)
        account = positions.list_open()[0]
        allocation = allocations.list_by_cluster(CLUSTER_A)[0]
        outputs.append(
            (
                str(account.position_id),
                str(account.total_quantity.value),
                str(allocation.realized_pnl.amount),
                account.version,
            )
        )
    assert len(set(outputs)) == 1
    other = OnlyPositionManager(OnlyRuntimeId("other-runtime"))
    with pytest.raises(ValueError):
        other.apply_trade(trade(99, OnlyOrderSide.BUY, "1", "1"))


def test_every_runtime_mode_owns_distinct_position_domains() -> None:
    live = OnlyLiveRuntime(OnlyRuntimeAssemblyConfig("engine", "live", OnlyRuntimeMode.LIVE))
    paper = OnlyPaperRuntime(OnlyRuntimeAssemblyConfig("engine", "paper", OnlyRuntimeMode.PAPER))
    assert live.position_manager is not paper.position_manager
    assert live.allocation_manager is not paper.allocation_manager
    assert live.position_reservation_manager is not paper.position_reservation_manager
