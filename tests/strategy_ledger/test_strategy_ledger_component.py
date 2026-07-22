from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyDirection, OnlyOffset, OnlyOrderSide
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
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyMultiplier, OnlyPrice, OnlyQuantity
from onlyalpha.position import (
    OnlyPositionAllocationManager,
    OnlyPositionSide,
    OnlyPositionTrade,
    OnlySettlementBucket,
)
from onlyalpha.strategy_ledger.enums import (
    OnlyStrategyCashReservationState,
    OnlyStrategyFeeType,
    OnlyStrategyLedgerMutationStatus,
    OnlyStrategyLedgerReplayOperation,
    OnlyStrategyLedgerStatus,
)
from onlyalpha.strategy_ledger.exceptions import OnlyStrategyLedgerInsufficientCashError
from onlyalpha.strategy_ledger.identifiers import OnlyStrategyFeeEntryId
from onlyalpha.strategy_ledger.keys import OnlyStrategyLedgerKey
from onlyalpha.strategy_ledger.locator import OnlyStrategyLedgerLocator
from onlyalpha.strategy_ledger.manager import OnlyStrategyLedgerManager
from onlyalpha.strategy_ledger.models import (
    OnlyStrategyCashReservationCommand,
    OnlyStrategyFeeEntry,
    OnlyStrategyLedgerLifecycleCommand,
    OnlyStrategyLedgerReplayEntry,
    OnlyStrategyMarkPrice,
    OnlyStrategyTradeAccountingInput,
    OnlyStrategyValuation,
)
from onlyalpha.strategy_ledger.query import OnlyStrategyLedgerQueryService
from onlyalpha.strategy_ledger.replay import OnlyStrategyLedgerReplayService
from onlyalpha.strategy_ledger.valuation import OnlyStrategyValuationService
from onlyalpha.strategy_ledger.views import OnlyStrategyLedgerContextView, OnlyStrategyLedgerRiskView

RUNTIME = OnlyRuntimeId("ledger-runtime")
ACCOUNT = OnlyAccountId("account")
A = OnlyClusterId("a")
B = OnlyClusterId("b")
INSTRUMENT = OnlyInstrumentId(OnlySymbol("510300"), OnlyVenueId("XSHG"))
CNY = OnlyCurrency("CNY", 2)


def make_trade(
    sequence: int,
    side: OnlyOrderSide,
    quantity: str,
    price: str,
    fee: str,
    cluster: OnlyClusterId = A,
) -> OnlyPositionTrade:
    timestamp = OnlyTimestamp(sequence * 1_000)
    return OnlyPositionTrade(
        OnlyTradeId(f"trade-{cluster}-{sequence}"),
        OnlyVenueTradeId(f"venue-{cluster}-{sequence}"),
        OnlyOrderId(f"order-{cluster}-{sequence}"),
        cluster,
        RUNTIME,
        ACCOUNT,
        INSTRUMENT,
        side,
        OnlyDirection.BUY if side is OnlyOrderSide.BUY else OnlyDirection.SELL,
        OnlyOffset.OPEN if side is OnlyOrderSide.BUY else OnlyOffset.CLOSE,
        OnlyPositionSide.LONG,
        OnlyPrice(Decimal(price), 2),
        OnlyQuantity(Decimal(quantity), 0),
        OnlyMoney(Decimal(fee), CNY),
        timestamp,
        timestamp,
        sequence,
        settlement_bucket=OnlySettlementBucket.SETTLED,
        multiplier=OnlyMultiplier(Decimal("1"), 0),
    )


def setup_manager(cluster: OnlyClusterId = A) -> tuple[OnlyStrategyLedgerManager, OnlyStrategyLedgerKey]:
    manager = OnlyStrategyLedgerManager(RUNTIME)
    key = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, cluster, CNY)
    manager.create_ledger(key, OnlyMoney(Decimal("100000.00"), CNY), OnlyTimestamp(0))
    manager.activate_ledger(key, OnlyTimestamp(0))
    return manager, key


def account_trade(
    manager: OnlyStrategyLedgerManager,
    key: OnlyStrategyLedgerKey,
    allocations: OnlyPositionAllocationManager,
    trade: OnlyPositionTrade,
) -> OnlyStrategyTradeAccountingInput:
    before_items = allocations.list_by_cluster(key.cluster_id)
    before = before_items[0] if before_items else None
    if trade.side is OnlyOrderSide.BUY:
        manager.reserve_cash(
            key,
            trade.order_id,
            OnlyMoney(trade.price.value * trade.quantity.value, CNY),
            trade.fee,
            trade.ts_event,
        )
        reservation = manager.require_snapshot(key).reservations[-1]
    else:
        reservation = None
    allocations.apply_trade(trade)
    after_items = allocations.list_by_cluster(key.cluster_id)
    after = after_items[0] if after_items else None
    before_realized = Decimal(0) if before is None else before.realized_pnl.amount
    after_realized = Decimal(0) if after is None else after.realized_pnl.amount
    before_cost = (
        Decimal(0)
        if before is None or before.average_open_price is None
        else before.average_open_price.value * before.total_quantity.value
    )
    after_cost = (
        Decimal(0)
        if after is None or after.average_open_price is None
        else after.average_open_price.value * after.total_quantity.value
    )
    fee_entry = OnlyStrategyFeeEntry(
        OnlyStrategyFeeEntryId(f"fee-{trade.trade_id}"),
        key,
        trade.fee,
        OnlyStrategyFeeType.COMMISSION,
        trade.trade_id,
        trade.order_id,
        trade.ts_event,
        trade.ts_init,
        trade.external_sequence or 0,
    )
    accounting = OnlyStrategyTradeAccountingInput(
        trade,
        None,
        before,
        after,
        OnlyMoney(after_realized - before_realized, CNY),
        OnlyMoney(after_cost - before_cost, CNY),
        (fee_entry,),
        reservation,
        trade.ts_event,
        trade.external_sequence or 0,
    )
    assert manager.apply_trade_accounting(key, accounting).changed
    assert manager.apply_trade_accounting(key, accounting).status is OnlyStrategyLedgerMutationStatus.DUPLICATE
    return accounting


def test_cash_trade_fee_pnl_equity_and_serialization() -> None:
    manager, key = setup_manager()
    allocations = OnlyPositionAllocationManager(RUNTIME)
    account_trade(manager, key, allocations, make_trade(1, OnlyOrderSide.BUY, "1000", "10.00", "5.00"))
    snapshot = manager.require_snapshot(key)
    assert snapshot.cash.cash_balance.amount == Decimal("89995.00")
    assert snapshot.cash.cash_reserved.amount == Decimal("0.00")
    assert snapshot.pnl.fees.amount == Decimal("5.00")
    assert snapshot.equity.equity.amount == Decimal("99995.00")
    assert snapshot.equity.equity_by_cash_view == snapshot.equity.equity_by_pnl_view
    valuation = OnlyStrategyValuationService().value(
        key,
        allocations.list_by_cluster(A),
        (OnlyStrategyMarkPrice(INSTRUMENT, OnlyPrice(Decimal("11.00"), 2), 1, "TEST"),),
        {INSTRUMENT: OnlyMultiplier(Decimal("1"), 0)},
        OnlyTimestamp(2_000),
        OnlyTimestamp(2_000),
        1,
    )
    manager.apply_valuation(valuation)
    snapshot = manager.require_snapshot(key)
    assert snapshot.pnl.unrealized_pnl.amount == Decimal("1000.00")
    assert snapshot.equity.equity.amount == Decimal("100995.00")
    assert snapshot == type(snapshot).from_json(snapshot.to_json())
    with pytest.raises(FrozenInstanceError):
        snapshot.version = 99  # type: ignore[misc]
    account_trade(manager, key, allocations, make_trade(3, OnlyOrderSide.SELL, "400", "12.00", "3.00"))
    sold = manager.require_snapshot(key)
    assert sold.pnl.realized_pnl.amount == Decimal("800.00")
    assert sold.cash.cash_balance.amount == Decimal("94792.00")
    assert sold.pnl.fees.amount == Decimal("8.00")


def test_cash_reservation_cluster_scope_and_risk_fail_closed() -> None:
    manager, key_a = setup_manager(A)
    key_b = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, B, CNY)
    manager.create_ledger(key_b, OnlyMoney(Decimal("100000.00"), CNY), OnlyTimestamp(0))
    manager.activate_ledger(key_b, OnlyTimestamp(0))
    manager.reserve_cash(
        key_a,
        OnlyOrderId("one"),
        OnlyMoney(Decimal("60000.00"), CNY),
        OnlyMoney(Decimal("0.00"), CNY),
        OnlyTimestamp(1),
    )
    with pytest.raises(OnlyStrategyLedgerInsufficientCashError):
        manager.reserve_cash(
            key_a,
            OnlyOrderId("two"),
            OnlyMoney(Decimal("60000.00"), CNY),
            OnlyMoney(Decimal("0.00"), CNY),
            OnlyTimestamp(2),
        )
    assert manager.require_snapshot(key_b).cash.cash_available.amount == Decimal("100000.00")
    manager.release_cash_reservation(key_a, OnlyOrderId("one"), OnlyTimestamp(3))
    assert manager.require_snapshot(key_a).reservations[0].state is OnlyStrategyCashReservationState.RELEASED
    query = OnlyStrategyLedgerQueryService(manager)
    context = OnlyStrategyLedgerContextView(key_a, query)
    assert context.cash_available.amount == Decimal("100000.00")
    assert not hasattr(context, "reserve_cash")
    risk = OnlyStrategyLedgerRiskView(query, OnlyStrategyLedgerLocator(manager), CNY)
    assert risk.allows_new_orders(ACCOUNT, A)
    manager._ledgers[key_a].status = OnlyStrategyLedgerStatus.RECONCILING  # noqa: SLF001
    assert not risk.allows_new_orders(ACCOUNT, A)


def test_multi_cluster_uses_allocation_cost_not_account_average() -> None:
    manager, key_a = setup_manager(A)
    key_b = OnlyStrategyLedgerKey(RUNTIME, ACCOUNT, B, CNY)
    manager.create_ledger(key_b, OnlyMoney(Decimal("100000.00"), CNY), OnlyTimestamp(0))
    manager.activate_ledger(key_b, OnlyTimestamp(0))
    allocations = OnlyPositionAllocationManager(RUNTIME)
    account_trade(manager, key_a, allocations, make_trade(1, OnlyOrderSide.BUY, "100", "10.00", "0.00", A))
    account_trade(manager, key_b, allocations, make_trade(2, OnlyOrderSide.BUY, "100", "12.00", "0.00", B))
    account_trade(manager, key_a, allocations, make_trade(3, OnlyOrderSide.SELL, "40", "15.00", "0.00", A))
    assert manager.require_snapshot(key_a).pnl.realized_pnl.amount == Decimal("200.00")
    assert manager.require_snapshot(key_b).pnl.realized_pnl.amount == Decimal("0.00")


def test_drawdown_dual_view_reconciliation_and_replay() -> None:
    manager, key = setup_manager()
    allocations = OnlyPositionAllocationManager(RUNTIME)
    accounting = account_trade(
        manager,
        key,
        allocations,
        make_trade(1, OnlyOrderSide.BUY, "1000", "10.00", "0.00"),
    )
    valuations: list[OnlyStrategyValuation] = []
    for version, price in enumerate(("20.00", "9.00", "15.00"), 1):
        valuation = OnlyStrategyValuationService().value(
            key,
            allocations.list_by_cluster(A),
            (OnlyStrategyMarkPrice(INSTRUMENT, OnlyPrice(Decimal(price), 2), version, "TEST"),),
            {INSTRUMENT: OnlyMultiplier(Decimal("1"), 0)},
            OnlyTimestamp((version + 1) * 1_000),
            OnlyTimestamp((version + 1) * 1_000),
            version,
        )
        valuations.append(valuation)
        manager.apply_valuation(valuation)
    snapshot = manager.require_snapshot(key)
    assert snapshot.equity.high_water_mark.amount == Decimal("110000.00")
    assert snapshot.equity.drawdown.value == Decimal("-0.04545455")
    assert snapshot.equity.maximum_drawdown.value == Decimal("-0.10000000")

    last = valuations[-1]
    malformed = OnlyStrategyValuation(
        key,
        OnlyTimestamp(5_000),
        OnlyTimestamp(5_000),
        4,
        last.position_cost,
        last.position_market_value,
        OnlyMoney(Decimal("4999.00"), CNY),
        last.lines,
    )
    manager.apply_valuation(malformed)
    assert manager.require_snapshot(key).status is OnlyStrategyLedgerStatus.RECONCILING

    replayed = OnlyStrategyLedgerManager(RUNTIME)
    lifecycle = OnlyStrategyLedgerLifecycleCommand(key, OnlyTimestamp(0), OnlyMoney(Decimal("100000.00"), CNY))
    reserve = OnlyStrategyCashReservationCommand(
        key,
        accounting.trade.order_id,
        OnlyMoney(Decimal("10000.00"), CNY),
        OnlyMoney(Decimal("0.00"), CNY),
        accounting.ts_event,
    )
    entries = (
        OnlyStrategyLedgerReplayEntry(1, OnlyStrategyLedgerReplayOperation.CREATE, lifecycle.to_json()),
        OnlyStrategyLedgerReplayEntry(2, OnlyStrategyLedgerReplayOperation.ACTIVATE, lifecycle.to_json()),
        OnlyStrategyLedgerReplayEntry(3, OnlyStrategyLedgerReplayOperation.RESERVE_CASH, reserve.to_json()),
        OnlyStrategyLedgerReplayEntry(4, OnlyStrategyLedgerReplayOperation.APPLY_TRADE, accounting.to_json()),
        OnlyStrategyLedgerReplayEntry(5, OnlyStrategyLedgerReplayOperation.APPLY_VALUATION, valuations[0].to_json()),
    )
    serialized = tuple(OnlyStrategyLedgerReplayEntry.from_json(item.to_json()) for item in entries)
    OnlyStrategyLedgerReplayService().replay(replayed, serialized)
    original_at_first_mark = OnlyStrategyLedgerManager(RUNTIME)
    OnlyStrategyLedgerReplayService().replay(original_at_first_mark, entries)
    assert replayed.require_snapshot(key) == original_at_first_mark.require_snapshot(key)
