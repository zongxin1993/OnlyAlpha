"""XtQuant callbacks normalized into OnlyAlpha's broker boundary."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from onlyalpha.broker.identifiers import OnlyBrokerUpdateId
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerBalanceSnapshot,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.broker.updates import (
    OnlyBrokerAccountUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderCancelledUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerPositionUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.enums import (
    OnlyOffset,
    OnlyOrderSide,
    OnlyOrderStatus,
    OnlyOrderType,
)
from onlyalpha.domain.execution import OnlyOrderFill, OnlyOrderRejection
from onlyalpha.domain.identifiers import (
    OnlyOrderId,
    OnlyTradeId,
    OnlyVenueOrderId,
    OnlyVenueTradeId,
)
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney, OnlyPrice, OnlyQuantity
from onlyalpha.fee.models import OnlyBrokerFeeReportingMode
from onlyalpha.position.enums import OnlyPositionSide

from ..mapping.exchange import from_xt_symbol
from ..mapping.market_data import quantized_decimal
from ..mapping.order import STOCK_BUY
from ..mapping.status import map_order_status

if TYPE_CHECKING:
    from .gateway import OnlyMiniQmtBrokerGateway

_CHINA_STANDARD_TIME = timezone(timedelta(hours=8), "Asia/Shanghai")


class OnlyMiniQmtTraderCallback:
    """Callback threads only convert, deduplicate, and enqueue immutable updates."""

    def __init__(self, gateway: OnlyMiniQmtBrokerGateway) -> None:
        self.gateway = gateway
        self._seen: set[tuple[str, str]] = set()
        self._sequence = 0

    def on_connected(self) -> None:
        self.gateway._connection_state = self.gateway._ready_state

    def on_disconnected(self) -> None:
        self.gateway.on_disconnected()

    def account_snapshot(self, value: Any) -> OnlyBrokerAccountSnapshot:
        currency = OnlyCurrency("CNY", 2)
        stamp = self._stamp()
        return OnlyBrokerAccountSnapshot(
            self.gateway._request.gateway_id,
            self.gateway._request.account_id,
            self._money(value.total_asset, currency),
            self._money(value.cash, currency),
            self._money(value.frozen_cash, currency),
            self._money(value.total_asset, currency),
            stamp,
            self._sequence,
        )

    def balance_snapshot(self, value: Any) -> OnlyBrokerBalanceSnapshot:
        currency = OnlyCurrency("CNY", 2)
        return OnlyBrokerBalanceSnapshot(
            currency,
            self._money(value.total_asset, currency),
            self._money(value.cash, currency),
            self._money(value.frozen_cash, currency),
        )

    def position_snapshot(self, value: Any) -> OnlyBrokerPositionSnapshot:
        volume = Decimal(str(value.volume))
        available = Decimal(str(value.can_use_volume))
        average = Decimal(str(value.open_price))
        return OnlyBrokerPositionSnapshot(
            self.gateway._request.gateway_id,
            self.gateway._request.account_id,
            from_xt_symbol(value.stock_code),
            OnlyPositionSide.LONG,
            OnlyQuantity(volume, 0),
            OnlyQuantity(available, 0),
            OnlyQuantity(volume - available, 0),
            OnlyPrice(quantized_decimal(average, 4), 4) if average > 0 else None,
            self._stamp(),
            self._sequence,
        )

    def order_snapshot(self, value: Any) -> OnlyBrokerOrderSnapshot:
        order_id, client_order_id = self.gateway.resolve_order(value.order_remark, int(value.order_id))
        submitted = self._xt_time(value.order_time)
        updated = self._stamp()
        venue_order_id = OnlyVenueOrderId(str(value.order_id))
        self.gateway.remember_venue_order(order_id, venue_order_id, str(getattr(value, "order_sysid", "")))
        return OnlyBrokerOrderSnapshot(
            gateway_id=self.gateway._request.gateway_id,
            account_id=self.gateway._request.account_id,
            order_id=order_id,
            client_order_id=client_order_id,
            venue_order_id=venue_order_id,
            instrument_id=from_xt_symbol(value.stock_code),
            side=self._side(value.order_type),
            offset=self._offset(value.order_type),
            order_type=OnlyOrderType.LIMIT,
            quantity=OnlyQuantity(Decimal(str(value.order_volume)), 0),
            filled_quantity=OnlyQuantity(Decimal(str(value.traded_volume)), 0),
            price=OnlyPrice(quantized_decimal(value.price, 4), 4),
            status=map_order_status(int(value.order_status)),
            submitted_at=submitted,
            updated_at=updated if updated >= submitted else submitted,
            source_sequence=self._sequence,
        )

    def trade_snapshot(self, value: Any) -> OnlyBrokerTradeSnapshot:
        order_id, _ = self.gateway.resolve_order(value.order_remark, int(value.order_id))
        fill = self._fill(value, order_id)
        return OnlyBrokerTradeSnapshot(
            self.gateway._request.gateway_id,
            self.gateway._request.account_id,
            fill.trade_id,
            fill,
            self._sequence,
        )

    def on_stock_asset(self, value: Any) -> None:
        snapshot = self.account_snapshot(value)
        self._enqueue("asset", str(value.account_id), OnlyBrokerAccountUpdate, snapshot=snapshot)

    def on_stock_position(self, value: Any) -> None:
        snapshot = self.position_snapshot(value)
        identity = f"{value.stock_code}:{value.volume}:{value.can_use_volume}"
        self._enqueue("position", identity, OnlyBrokerPositionUpdate, snapshot=snapshot)

    def on_stock_order(self, value: Any) -> None:
        snapshot = self.order_snapshot(value)
        identity = f"{value.order_id}:{value.order_status}:{value.traded_volume}"
        common = {"order_id": snapshot.order_id}
        if snapshot.status is OnlyOrderStatus.REJECTED:
            self._enqueue(
                "order",
                identity,
                OnlyBrokerOrderRejectedUpdate,
                **common,
                rejection=OnlyOrderRejection(
                    "XT_ORDER_REJECTED",
                    str(getattr(value, "status_msg", "order rejected")),
                ),
            )
        elif snapshot.status is OnlyOrderStatus.CANCELLED:
            self._enqueue("order", identity, OnlyBrokerOrderCancelledUpdate, **common)
        else:
            self._enqueue(
                "order",
                identity,
                OnlyBrokerOrderAcceptedUpdate,
                **common,
                venue_order_id=snapshot.venue_order_id,
            )

    def on_stock_trade(self, value: Any) -> None:
        snapshot = self.trade_snapshot(value)
        self._enqueue(
            "trade",
            str(value.traded_id),
            OnlyBrokerTradeUpdate,
            order_id=snapshot.fill.order_id,
            fill=snapshot.fill,
        )

    def on_order_error(self, value: Any) -> None:
        order_id, _ = self.gateway.resolve_order(value.order_remark, int(getattr(value, "order_id", 0)))
        identity = f"{order_id}:{value.error_id}:{value.error_msg}"
        self._enqueue(
            "order_error",
            identity,
            OnlyBrokerOrderRejectedUpdate,
            order_id=order_id,
            rejection=OnlyOrderRejection(str(value.error_id), str(value.error_msg)),
        )

    def on_cancel_error(self, value: Any) -> None:
        self.gateway._request.logger.error("MiniQMT cancel failed: %s %s", value.error_id, value.error_msg)

    def _fill(self, value: Any, order_id: OnlyOrderId) -> OnlyOrderFill:
        event = self._xt_time(value.traded_time)
        initialized = self._stamp()
        if initialized < event:
            initialized = event
        return OnlyOrderFill(
            trade_id=OnlyTradeId(str(value.traded_id)),
            order_id=order_id,
            price=OnlyPrice(quantized_decimal(value.traded_price, 4), 4),
            quantity=OnlyQuantity(Decimal(str(value.traded_volume)), 0),
            ts_event=event,
            ts_init=initialized,
            venue_trade_id=OnlyVenueTradeId(str(value.traded_id)),
            venue_order_id=OnlyVenueOrderId(str(value.order_id)),
            reported_fee=None,
            fee_reporting_mode=OnlyBrokerFeeReportingMode.NONE,
            fee_external_reference=None,
            external_sequence=self._sequence + 1,
            external_event_id=str(value.traded_id),
        )

    def _enqueue(self, kind: str, identity: str, update_type: type, **payload: object) -> None:
        key = (kind, identity)
        if key in self._seen:
            return
        self._seen.add(key)
        self._sequence += 1
        stamp = self._stamp()
        correlation = str(payload.get("order_id", self.gateway._request.account_id))
        update = update_type(
            runtime_id=self.gateway._request.runtime_id,
            gateway_id=self.gateway._request.gateway_id,
            account_id=self.gateway._request.account_id,
            update_id=OnlyBrokerUpdateId(f"miniqmt-{kind}-{identity}"),
            source_sequence=self._sequence,
            ts_event=stamp,
            ts_init=stamp,
            correlation_id=correlation,
            causation_id=f"xtquant:{kind}",
            **payload,
        )
        self.gateway._request.broker_inbound_queue.put(update)

    def _stamp(self) -> OnlyTimestamp:
        return OnlyTimestamp.from_datetime(self.gateway._request.clock.now().astimezone(UTC))

    @staticmethod
    def _money(value: Any, currency: OnlyCurrency) -> OnlyMoney:
        return OnlyMoney(Decimal(str(value)).quantize(Decimal("0.01")), currency)

    @staticmethod
    def _side(value: Any) -> OnlyOrderSide:
        return OnlyOrderSide.BUY if int(value) == STOCK_BUY else OnlyOrderSide.SELL

    @staticmethod
    def _xt_time(value: Any) -> OnlyTimestamp:
        raw = int(value)
        if raw > 10_000_000_000:
            raw //= 1000
        return OnlyTimestamp.from_datetime(datetime.fromtimestamp(raw, tz=_CHINA_STANDARD_TIME).astimezone(UTC))

    def _offset(self, order_type: int) -> OnlyOffset:
        side = self._side(order_type)

        if side is OnlyOrderSide.BUY:
            return OnlyOffset.OPEN

        if side is OnlyOrderSide.SELL:
            return OnlyOffset.CLOSE

        raise ValueError(f"unsupported MiniQMT order type: {order_type}")
