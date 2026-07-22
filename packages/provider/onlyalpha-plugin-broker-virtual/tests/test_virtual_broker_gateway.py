"""Virtual Broker Gateway contract tests owned by its distribution."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

from conftest import ACCOUNT, CNY, START, bar, order
from onlyalpha_plugin_broker_virtual import OnlyVirtualBrokerConfig, OnlyVirtualBrokerGateway

from onlyalpha.broker import (
    OnlyBrokerCancelRequest,
    OnlyBrokerGatewayId,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerRequestId,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.core.clock import OnlyBacktestClock
from onlyalpha.domain.enums import OnlyOffset, OnlyOrderSide, OnlyOrderStatus
from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney, OnlyQuantity
from onlyalpha.plugin.lifecycle import OnlyPluginHealthStatus


def test_submit_is_transport_only_and_fill_arrives_from_next_bar(virtual_broker) -> None:
    clock, gateway, updates = virtual_broker
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)

    result = gateway.submit_order(order(1))
    assert result.request_received is True
    assert updates == []
    gateway.run_due()
    assert isinstance(updates[0], OnlyBrokerOrderAcceptedUpdate)
    assert gateway.query_account(ACCOUNT).frozen_cash == OnlyMoney(Decimal("1000.00"), CNY)

    second = bar(date(2026, 1, 5), 1)
    clock.advance_to(second.ts_event)
    gateway.on_bar(second)

    assert any(isinstance(update, OnlyBrokerTradeUpdate) for update in updates)
    assert gateway.query_orders(ACCOUNT)[0].status is OnlyOrderStatus.FILLED
    assert gateway.query_account(ACCOUNT).cash_balance == OnlyMoney(Decimal("99000.00"), CNY)


def test_cancel_releases_independent_broker_reservation(virtual_broker) -> None:
    clock, gateway, updates = virtual_broker
    current = bar(date(2026, 1, 5), 0)
    clock.advance_to(current.ts_event)
    gateway.on_bar(current)
    request = order(1)
    gateway.submit_order(request)
    gateway.run_due()

    gateway.cancel_order(
        OnlyBrokerCancelRequest(
            OnlyBrokerRequestId("cancel-1"),
            ACCOUNT,
            request.order_id,
            None,
            OnlyTimestamp.from_datetime(current.ts_event),
        )
    )
    gateway.run_due()

    assert gateway.query_orders(ACCOUNT)[0].status is OnlyOrderStatus.CANCELLED
    assert gateway.query_account(ACCOUNT).frozen_cash == OnlyMoney(Decimal("0.00"), CNY)
    assert len(updates) == 2


def test_broker_projection_does_not_copy_runtime_t_plus_one_rules(virtual_broker) -> None:
    clock, gateway, _ = virtual_broker
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(order(1))
    gateway.run_due()
    second = bar(date(2026, 1, 5), 1)
    clock.advance_to(second.ts_event)
    gateway.on_bar(second)

    same_day_sell = order(2, OnlyOrderSide.SELL)
    gateway.submit_order(same_day_sell)
    gateway.run_due()
    assert gateway.query_orders(ACCOUNT)[1].status is OnlyOrderStatus.ACCEPTED

    next_day = bar(date(2026, 1, 6), 0)
    clock.advance_to(next_day.ts_event)
    gateway.on_bar(next_day)
    assert all("t-plus-one-settlement" not in str(update) for update in _)


def test_virtual_broker_does_not_hold_runtime_manager_objects(virtual_broker) -> None:
    _, gateway, _ = virtual_broker
    names = set(vars(gateway))
    assert "order_manager" not in names
    assert "position_manager" not in names
    assert "account_manager" not in names
    assert "strategy_ledger_manager" not in names


def test_descriptor_lifecycle_and_health_are_plugin_owned(virtual_broker) -> None:
    _, gateway, _ = virtual_broker
    assert gateway.plugin_descriptor.plugin_id == "virtual"
    gateway.start()
    assert gateway.health().status is OnlyPluginHealthStatus.HEALTHY
    gateway.stop()
    gateway.close()
    assert gateway.health().status is OnlyPluginHealthStatus.STOPPED


def test_maximum_fill_quantity_produces_deterministic_partial_fills() -> None:
    updates = []
    clock = OnlyBacktestClock(START)
    gateway = OnlyVirtualBrokerGateway(
        OnlyVirtualBrokerConfig(
            OnlyBrokerGatewayId("partial"),
            ACCOUNT,
            CNY,
            OnlyMoney(Decimal("100000.00"), CNY),
            maximum_fill_quantity=OnlyQuantity(Decimal("40"), 0),
        ),
        OnlyRuntimeId("partial-runtime"),
        clock,
        updates.append,
    )
    gateway.connect()
    gateway.authenticate()
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    gateway.submit_order(order(1))
    gateway.run_due()
    second = bar(date(2026, 1, 5), 1)
    clock.advance_to(second.ts_event)
    gateway.on_bar(second)

    snapshot = gateway.query_orders(ACCOUNT)[0]
    assert snapshot.status is OnlyOrderStatus.PARTIALLY_FILLED
    assert snapshot.filled_quantity == OnlyQuantity(Decimal("40"), 0)
    assert len(gateway.query_trades(ACCOUNT)) == 1


def test_short_open_and_close_update_external_broker_projection(virtual_broker) -> None:
    clock, gateway, _ = virtual_broker
    first = bar(date(2026, 1, 5), 0)
    clock.advance_to(first.ts_event)
    gateway.on_bar(first)
    short_open = replace(order(1, OnlyOrderSide.SELL), offset=OnlyOffset.OPEN)
    gateway.submit_order(short_open)
    gateway.run_due()
    second = bar(date(2026, 1, 5), 1)
    clock.advance_to(second.ts_event)
    gateway.on_bar(second)
    short_position = gateway.query_positions(ACCOUNT)[0]
    assert short_position.position_side.value == "SHORT"
    assert short_position.quantity.value == Decimal("100")

    short_close = replace(order(2), offset=OnlyOffset.CLOSE)
    gateway.submit_order(short_close)
    gateway.run_due()
    third = bar(date(2026, 1, 5), 2)
    clock.advance_to(third.ts_event)
    gateway.on_bar(third)
    closed_position = gateway.query_positions(ACCOUNT)[0]
    assert closed_position.position_side.value == "SHORT"
    assert closed_position.quantity.value == Decimal("0")
