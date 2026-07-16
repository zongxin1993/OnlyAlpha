"""Deterministic Virtual Broker implementing the normalized Broker Ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import date
from decimal import Decimal

from onlyalpha.broker.capabilities import OnlyBrokerCapabilities
from onlyalpha.broker.enums import OnlyBrokerCapability, OnlyBrokerConnectionState, OnlyBrokerOperationStatus
from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerBalanceSnapshot,
    OnlyBrokerCancelRequest,
    OnlyBrokerCancelResult,
    OnlyBrokerConnectionResult,
    OnlyBrokerConnectionSnapshot,
    OnlyBrokerOrderRequest,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerOrderSubmitResult,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerQuery,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.broker.updates import (
    OnlyBrokerAccountUpdate,
    OnlyBrokerConnectionUpdate,
    OnlyBrokerInboundUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerPositionUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.broker.virtual_broker.commission import OnlyCommissionModel, OnlyFixedCommissionModel
from onlyalpha.broker.virtual_broker.config import OnlyVirtualBrokerConfig
from onlyalpha.broker.virtual_broker.latency import OnlyLatencyModel, OnlyZeroLatencyModel
from onlyalpha.broker.virtual_broker.matching import OnlyMatchingEngine, OnlyNextBarMatchingEngine
from onlyalpha.broker.virtual_broker.scheduler import OnlyVirtualBrokerScheduler
from onlyalpha.broker.virtual_broker.slippage import OnlyNoSlippageModel, OnlySlippageModel
from onlyalpha.broker.virtual_broker.stores import (
    OnlyVirtualBrokerAccountStore,
    OnlyVirtualBrokerOrderStore,
    OnlyVirtualBrokerTradeStore,
)
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.enums import OnlyLiquiditySide, OnlyOrderSide, OnlyOrderStatus, OnlyOrderType
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyRuntimeId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.market import OnlyBar
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyMoney


class OnlyVirtualBrokerGateway:
    """Virtual external system; it never imports or shares a Runtime Manager."""

    def __init__(
        self,
        config: OnlyVirtualBrokerConfig,
        runtime_id: OnlyRuntimeId,
        clock: OnlyClock,
        inbound: Callable[[OnlyBrokerInboundUpdate], None],
        *,
        matching_engine: OnlyMatchingEngine | None = None,
        commission_model: OnlyCommissionModel | None = None,
        slippage_model: OnlySlippageModel | None = None,
        latency_model: OnlyLatencyModel | None = None,
        scheduler: OnlyVirtualBrokerScheduler | None = None,
    ) -> None:
        self.config = config
        self.runtime_id = runtime_id
        self._clock = clock
        self._inbound = inbound
        self._matching = matching_engine or OnlyNextBarMatchingEngine(config.maximum_fill_quantity)
        self._commission = (
            commission_model
            or config.commission_model
            or OnlyFixedCommissionModel(OnlyMoney(Decimal("0.00"), config.base_currency))
        )
        self._slippage = slippage_model or config.slippage_model or OnlyNoSlippageModel()
        self._latency = latency_model or config.latency_model or OnlyZeroLatencyModel()
        self.scheduler = scheduler or OnlyVirtualBrokerScheduler()
        self.account_store = OnlyVirtualBrokerAccountStore(
            config.gateway_id,
            config.account_id,
            config.base_currency,
            config.initial_cash,
        )
        self.order_store = OnlyVirtualBrokerOrderStore()
        self.trade_store = OnlyVirtualBrokerTradeStore()
        self._state = OnlyBrokerConnectionState.DISCONNECTED
        self._state_time = self._now()
        self._source_sequence = 0
        self._venue_order_sequence = 0
        self._trade_sequence = 0
        self._bar_sequence = 0
        self._accepted_bar: dict[object, int] = {}
        self._current_day: date | None = None
        self._latest_bars: dict[object, OnlyBar] = {}

    @property
    def capabilities(self) -> OnlyBrokerCapabilities:
        return OnlyBrokerCapabilities(frozenset(OnlyBrokerCapability))

    def connect(self) -> OnlyBrokerConnectionResult:
        self._state = OnlyBrokerConnectionState.CONNECTED
        self._state_time = self._now()
        self._emit(
            OnlyBrokerConnectionUpdate,
            self._state_time,
            str(self.config.gateway_id),
            "connect",
            state=self._state,
        )
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def authenticate(self) -> OnlyBrokerConnectionResult:
        if self._state is not OnlyBrokerConnectionState.CONNECTED:
            return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.NOT_READY, self.connection_snapshot())
        self._state = OnlyBrokerConnectionState.READY
        self._state_time = self._now()
        self._emit(
            OnlyBrokerConnectionUpdate,
            self._state_time,
            str(self.config.gateway_id),
            "authenticate",
            state=self._state,
        )
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def disconnect(self) -> OnlyBrokerConnectionResult:
        self._state = OnlyBrokerConnectionState.DISCONNECTED
        self._state_time = self._now()
        self._emit(
            OnlyBrokerConnectionUpdate,
            self._state_time,
            str(self.config.gateway_id),
            "disconnect",
            state=self._state,
        )
        return OnlyBrokerConnectionResult(OnlyBrokerOperationStatus.RECEIVED, self.connection_snapshot())

    def connection_snapshot(self) -> OnlyBrokerConnectionSnapshot:
        return OnlyBrokerConnectionSnapshot(self.config.gateway_id, self._state, self._state_time)

    def submit_order(self, request: OnlyBrokerOrderRequest) -> OnlyBrokerOrderSubmitResult:
        if self._state is not OnlyBrokerConnectionState.READY:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.NOT_READY,
                request.gateway_request_id,
                request.client_order_id,
                "Broker is not READY",
            )
        if request.account_id != self.config.account_id:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.REJECTED,
                request.gateway_request_id,
                request.client_order_id,
                "unknown Broker account",
            )
        self._venue_order_sequence += 1
        venue_order_id = OnlyVenueOrderId(f"virtual-order-{self._venue_order_sequence:08d}")
        order = OnlyBrokerOrderSnapshot(
            self.config.gateway_id,
            request.account_id,
            request.order_id,
            request.client_order_id,
            venue_order_id,
            request.instrument_id,
            request.side,
            request.order_type,
            request.quantity,
            type(request.quantity)(Decimal(0), request.quantity.precision),
            request.price,
            OnlyOrderStatus.SUBMITTED,
            request.submitted_at,
            request.submitted_at,
            self._next_sequence(),
        )
        self.order_store.save(order)
        due = request.submitted_at.unix_nanos + self._latency.submit_latency_ns + self._latency.acceptance_latency_ns
        self.scheduler.schedule(due, lambda: self._accept(order, request.gateway_request_id.value))
        return OnlyBrokerOrderSubmitResult(
            True,
            OnlyBrokerOperationStatus.RECEIVED,
            request.gateway_request_id,
            request.client_order_id,
        )

    def cancel_order(self, request: OnlyBrokerCancelRequest) -> OnlyBrokerCancelResult:
        if self._state is not OnlyBrokerConnectionState.READY:
            return OnlyBrokerCancelResult(
                False, OnlyBrokerOperationStatus.NOT_READY, request.gateway_request_id, "Broker is not READY"
            )
        try:
            order = self.order_store.require(request.order_id)
        except KeyError:
            return OnlyBrokerCancelResult(
                False, OnlyBrokerOperationStatus.REJECTED, request.gateway_request_id, "unknown Broker order"
            )
        if order.status in {OnlyOrderStatus.CANCELLED, OnlyOrderStatus.FILLED, OnlyOrderStatus.REJECTED}:
            return OnlyBrokerCancelResult(
                False, OnlyBrokerOperationStatus.REJECTED, request.gateway_request_id, "Broker order is terminal"
            )
        due = request.requested_at.unix_nanos + self._latency.cancel_latency_ns
        self.scheduler.schedule(due, lambda: self._cancel(request.order_id, request.gateway_request_id.value))
        return OnlyBrokerCancelResult(True, OnlyBrokerOperationStatus.RECEIVED, request.gateway_request_id)

    def on_bar(self, bar: OnlyBar) -> None:
        # Deliver cancellations/acceptances due at this Clock instant before matching.
        self.run_due()
        self._bar_sequence += 1
        self.account_store.mark(bar.instrument_id, bar.close)
        if self._current_day is None:
            self._current_day = bar.trading_day
        elif bar.trading_day > self._current_day:
            self.account_store.settle()
            self._current_day = bar.trading_day
            timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
            for position in self.account_store.position_snapshots(timestamp):
                self._emit(
                    OnlyBrokerPositionUpdate,
                    timestamp,
                    str(position.instrument_id),
                    "t-plus-one-settlement",
                    snapshot=position,
                )
            self._emit(
                OnlyBrokerAccountUpdate,
                timestamp,
                str(self.config.account_id),
                "t-plus-one-settlement",
                snapshot=self.account_store.account_snapshot(timestamp),
            )
        timestamp = OnlyTimestamp.from_datetime(bar.ts_event)
        for order in self.order_store.open(self.config.account_id):
            if order.status not in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}:
                continue
            if self._accepted_bar.get(order.order_id, self._bar_sequence) >= self._bar_sequence:
                continue
            result = self._matching.match(order, bar)
            if result.matched and result.price is not None and result.quantity is not None:
                self._execute(order, result.price, result.quantity, timestamp)
        self._latest_bars[bar.instrument_id] = bar
        self.run_due()

    def run_due(self) -> int:
        return self.scheduler.run_due(self._clock.timestamp_ns())

    def query_account(self, account_id: OnlyAccountId) -> OnlyBrokerAccountSnapshot:
        self._require_account(account_id)
        return self.account_store.account_snapshot(self._now())

    def query_balances(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerBalanceSnapshot, ...]:
        snapshot = self.query_account(account_id)
        return (
            OnlyBrokerBalanceSnapshot(
                self.config.base_currency,
                snapshot.cash_balance,
                snapshot.available_cash,
                snapshot.frozen_cash,
            ),
        )

    def query_positions(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerPositionSnapshot, ...]:
        self._require_account(account_id)
        return self.account_store.position_snapshots(self._now())

    def query_open_orders(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        self._require_account(account_id)
        return self.order_store.open(account_id)

    def query_orders(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        self._require_account(account_id)
        values = self.order_store.list(account_id)
        return (
            values
            if query is None or query.since_sequence is None
            else tuple(item for item in values if item.source_sequence >= query.since_sequence)
        )

    def query_trades(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        self._require_account(account_id)
        values = self.trade_store.list(account_id)
        return (
            values
            if query is None or query.since_sequence is None
            else tuple(item for item in values if item.source_sequence >= query.since_sequence)
        )

    def _accept(self, submitted: OnlyBrokerOrderSnapshot, causation_id: str) -> None:
        current = self.order_store.require(submitted.order_id)
        if current.status is not OnlyOrderStatus.SUBMITTED:
            return
        latest_bar = self._latest_bars.get(current.instrument_id)
        price = current.price if current.price is not None else latest_bar.close if latest_bar is not None else None
        if price is None:
            self._reject(current, causation_id, "MARKET order requires a reference Bar before acceptance")
            return
        required = price.value * current.remaining_quantity.value
        reservable = (
            self.account_store.reserve_buy(required)
            if current.side is OnlyOrderSide.BUY
            else self.account_store.reserve_sell(current.instrument_id, current.remaining_quantity.value)
        )
        if not reservable:
            self._reject(current, causation_id, "insufficient Broker cash or settled Position")
            return
        now = self._now()
        accepted = replace(
            current,
            price=price,
            status=OnlyOrderStatus.ACCEPTED,
            updated_at=now,
            source_sequence=self._next_sequence(),
        )
        self.order_store.save(accepted)
        self._accepted_bar[accepted.order_id] = self._bar_sequence
        self._emit(
            OnlyBrokerOrderAcceptedUpdate,
            now,
            str(accepted.order_id),
            causation_id,
            order_id=accepted.order_id,
            venue_order_id=accepted.venue_order_id,
        )

    def _reject(self, order: OnlyBrokerOrderSnapshot, causation_id: str, message: str) -> None:
        now = self._now()
        rejected = replace(
            order, status=OnlyOrderStatus.REJECTED, updated_at=now, source_sequence=self._next_sequence()
        )
        self.order_store.save(rejected)
        self._emit(
            OnlyBrokerOrderRejectedUpdate,
            now,
            str(order.order_id),
            causation_id,
            order_id=order.order_id,
            rejection=OnlyOrderRejection("BROKER_REJECTED", message),
        )

    def _cancel(self, order_id: object, causation_id: str) -> None:
        order = self.order_store.require(order_id)  # type: ignore[arg-type]
        if order.status not in {OnlyOrderStatus.ACCEPTED, OnlyOrderStatus.PARTIALLY_FILLED}:
            return
        self.account_store.release_order(order)
        now = self._now()
        cancelled = replace(
            order, status=OnlyOrderStatus.CANCELLED, updated_at=now, source_sequence=self._next_sequence()
        )
        self.order_store.save(cancelled)
        self._emit(
            OnlyBrokerOrderCancelledUpdate,
            now,
            str(order.order_id),
            causation_id,
            order_id=order.order_id,
        )

    def _execute(
        self, order: OnlyBrokerOrderSnapshot, raw_price: object, quantity: object, timestamp: OnlyTimestamp
    ) -> None:
        from onlyalpha.domain.value import OnlyPrice, OnlyQuantity

        assert isinstance(raw_price, OnlyPrice) and isinstance(quantity, OnlyQuantity)
        price = self._slippage.apply(order.side, raw_price)
        if order.order_type is OnlyOrderType.LIMIT and order.price is not None:
            price = OnlyPrice(
                min(price.value, order.price.value)
                if order.side is OnlyOrderSide.BUY
                else max(price.value, order.price.value),
                max(price.precision, order.price.precision),
            )
        fee = self._commission.calculate(order.side, price, quantity, self.config.base_currency)
        self._trade_sequence += 1
        trade_id = OnlyTradeId(f"virtual-trade-{self._trade_sequence:08d}")
        venue_trade_id = OnlyVenueTradeId(f"virtual-venue-trade-{self._trade_sequence:08d}")
        fill_sequence = self._next_sequence()
        fill = OnlyOrderFill(
            trade_id,
            order.order_id,
            price,
            quantity,
            timestamp,
            timestamp,
            venue_trade_id,
            order.venue_order_id,
            fee,
            OnlyLiquiditySide.TAKER,
            fill_sequence,
            f"virtual-fill-{self._trade_sequence:08d}",
        )
        reserved = (order.price.value if order.price is not None else price.value) * quantity.value
        if order.side is OnlyOrderSide.BUY:
            self.account_store.apply_buy(order.instrument_id, quantity.value, price, reserved, fee.amount)
        else:
            self.account_store.apply_sell(order.instrument_id, quantity.value, price, fee.amount)
        filled = type(order.filled_quantity)(
            order.filled_quantity.value + quantity.value, order.filled_quantity.precision
        )
        status = OnlyOrderStatus.FILLED if filled.value == order.quantity.value else OnlyOrderStatus.PARTIALLY_FILLED
        updated = replace(
            order,
            filled_quantity=filled,
            status=status,
            updated_at=timestamp,
            source_sequence=fill_sequence,
        )
        self.order_store.save(updated)
        trade = OnlyBrokerTradeSnapshot(self.config.gateway_id, self.config.account_id, trade_id, fill, fill_sequence)
        self.trade_store.save(trade)

        def publish() -> None:
            self._emit(
                OnlyBrokerTradeUpdate,
                timestamp,
                str(order.order_id),
                str(order.order_id),
                order_id=order.order_id,
                fill=fill,
            )
            positions = self.account_store.position_snapshots(timestamp)
            position = next(item for item in positions if item.instrument_id == order.instrument_id)
            self._emit(
                OnlyBrokerPositionUpdate,
                timestamp,
                str(order.order_id),
                str(trade_id),
                snapshot=position,
            )
            self._emit(
                OnlyBrokerAccountUpdate,
                timestamp,
                str(order.order_id),
                str(trade_id),
                snapshot=self.account_store.account_snapshot(timestamp),
            )

        self.scheduler.schedule(timestamp.unix_nanos + self._latency.fill_latency_ns, publish)

    def _emit(
        self,
        update_type: type[OnlyBrokerInboundUpdate],
        timestamp: OnlyTimestamp,
        correlation_id: str,
        causation_id: str,
        **payload: object,
    ) -> None:
        sequence = self._next_sequence()
        update = update_type(
            runtime_id=self.runtime_id,
            gateway_id=self.config.gateway_id,
            account_id=self.config.account_id,
            update_id=OnlyBrokerUpdateId(f"virtual-update-{sequence:08d}"),
            source_sequence=sequence,
            ts_event=timestamp,
            ts_init=timestamp,
            correlation_id=correlation_id,
            causation_id=causation_id,
            **payload,  # type: ignore[arg-type]
        )
        self._inbound(update)

    def _next_sequence(self) -> int:
        self._source_sequence += 1
        return self._source_sequence

    def _now(self) -> OnlyTimestamp:
        return OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns())

    def _require_account(self, account_id: OnlyAccountId) -> None:
        if account_id != self.config.account_id:
            raise KeyError(f"unknown Broker account: {account_id}")
