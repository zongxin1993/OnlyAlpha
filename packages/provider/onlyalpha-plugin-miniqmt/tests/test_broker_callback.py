from datetime import UTC, datetime
from types import SimpleNamespace

from onlyalpha_plugin_miniqmt.broker.callback import OnlyMiniQmtTraderCallback

from onlyalpha.broker.identifiers import OnlyBrokerGatewayId
from onlyalpha.broker.updates import (
    OnlyBrokerAccountUpdate,
    OnlyBrokerOrderAcceptedUpdate,
    OnlyBrokerOrderRejectedUpdate,
    OnlyBrokerPositionUpdate,
    OnlyBrokerTradeUpdate,
)
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyOrderId,
    OnlyRuntimeId,
)


class OnlyFakeClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 5, 2, 0, tzinfo=UTC)


class OnlyFakeQueue:
    def __init__(self) -> None:
        self.items: list[object] = []

    def put(self, update: object) -> None:
        self.items.append(update)


class OnlyFakeGateway:
    _ready_state = "READY"

    def __init__(self) -> None:
        self.queue = OnlyFakeQueue()
        self._request = SimpleNamespace(
            gateway_id=OnlyBrokerGatewayId("miniqmt-test"),
            runtime_id=OnlyRuntimeId("runtime-test"),
            account_id=OnlyAccountId("account-test"),
            clock=OnlyFakeClock(),
            broker_inbound_queue=self.queue,
            logger=SimpleNamespace(error=lambda *args: None),
        )
        self._client_order_ids = {OnlyOrderId("order-1"): OnlyClientOrderId("client-1")}
        self._order_ids: dict[int, OnlyOrderId] = {}
        self._venue_order_ids: dict[OnlyOrderId, object] = {}
        self._sysids: dict[OnlyOrderId, str] = {}

    def resolve_order(self, remark: str, xt_order_id: int):
        client = OnlyClientOrderId(remark.removeprefix("onlyalpha:"))
        order = next(key for key, value in self._client_order_ids.items() if value == client)
        return order, client

    def remember_venue_order(self, order_id, venue_order_id, order_sysid: str) -> None:
        self._venue_order_ids[order_id] = venue_order_id
        self._sysids[order_id] = order_sysid

    def on_disconnected(self) -> None:
        pass


def _order(**changes: object) -> SimpleNamespace:
    values = dict(
        order_remark="onlyalpha:client-1",
        order_id=101,
        order_sysid="SYS-101",
        order_time=1_767_579_000,
        stock_code="600000.SH",
        order_type=23,
        price_type=11,
        price=10.1200,
        order_volume=100,
        traded_volume=0,
        order_status=50,
        status_msg="",
    )
    values.update(changes)
    return SimpleNamespace(**values)


def test_callbacks_normalize_deduplicate_and_enqueue() -> None:
    gateway = OnlyFakeGateway()
    callback = OnlyMiniQmtTraderCallback(gateway)

    asset = SimpleNamespace(
        account_id="account-test",
        total_asset="100000.00",
        cash="90000.00",
        frozen_cash="10000.00",
    )
    position = SimpleNamespace(stock_code="600000.SH", volume=100, can_use_volume=80, open_price="10.1200")
    trade = SimpleNamespace(
        order_remark="onlyalpha:client-1",
        order_id=101,
        traded_id="T-1",
        traded_price="10.1200",
        traded_volume=40,
        traded_time=1_767_579_000,
    )

    callback.on_stock_asset(asset)
    callback.on_stock_position(position)
    callback.on_stock_order(_order())
    callback.on_stock_trade(trade)
    callback.on_stock_trade(trade)

    assert [type(item) for item in gateway.queue.items] == [
        OnlyBrokerAccountUpdate,
        OnlyBrokerPositionUpdate,
        OnlyBrokerOrderAcceptedUpdate,
        OnlyBrokerTradeUpdate,
    ]
    fill = gateway.queue.items[-1].fill
    assert fill.order_id == OnlyOrderId("order-1")
    assert str(fill.venue_trade_id) == "T-1"
    assert fill.reported_fee is None
    assert fill.fee_reporting_mode.value == "NONE"
    assert fill.fee_external_reference is None


def test_order_error_becomes_structured_rejection() -> None:
    gateway = OnlyFakeGateway()
    callback = OnlyMiniQmtTraderCallback(gateway)
    callback.on_order_error(
        SimpleNamespace(
            order_remark="onlyalpha:client-1",
            order_id=101,
            error_id=42,
            error_msg="rejected",
        )
    )
    update = gateway.queue.items[0]
    assert isinstance(update, OnlyBrokerOrderRejectedUpdate)
    assert update.rejection.code == "42"
