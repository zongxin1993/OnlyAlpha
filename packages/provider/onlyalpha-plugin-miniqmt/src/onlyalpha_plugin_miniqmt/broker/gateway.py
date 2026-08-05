from threading import Event, Lock, Thread, current_thread
from typing import Any

from onlyalpha.broker.capabilities import OnlyBrokerCapabilities
from onlyalpha.broker.enums import (
    OnlyBrokerCapability,
    OnlyBrokerConnectionState,
    OnlyBrokerOperationStatus,
)
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
from onlyalpha.domain.enums import OnlyOrderType
from onlyalpha.domain.identifiers import (
    OnlyAccountId,
    OnlyClientOrderId,
    OnlyOrderId,
    OnlyVenueOrderId,
)
from onlyalpha.plugin.broker import OnlyBrokerCreateRequest
from onlyalpha.plugin.lifecycle import OnlyPluginHealth, OnlyPluginLifecycleState

from ..config import OnlyMiniQmtConfig
from ..descriptor import BROKER_DESCRIPTOR
from ..lifecycle import OnlyMiniQmtLifecycle
from ..mapping.exchange import to_xt_symbol
from ..mapping.order import map_side, require_limit
from .callback import OnlyMiniQmtTraderCallback


class OnlyMiniQmtBrokerGateway:
    plugin_descriptor = BROKER_DESCRIPTOR
    _ready_state = OnlyBrokerConnectionState.READY
    _JOIN_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        request: OnlyBrokerCreateRequest,
        config: OnlyMiniQmtConfig,
        trader: Any,
        account: Any,
    ) -> None:
        self._request, self._config, self._trader, self._account = (
            request,
            config,
            trader,
            account,
        )
        self._life = OnlyMiniQmtLifecycle()
        self._connection_state = OnlyBrokerConnectionState.DISCONNECTED
        self._stopping = Event()
        self._reconnect_lock = Lock()
        self._reconnect_thread: Thread | None = None
        self._stop_attempted = False
        self._callback = OnlyMiniQmtTraderCallback(self)
        self._order_ids: dict[int, OnlyOrderId] = {}
        self._sysids: dict[OnlyOrderId, str] = {}
        self._client_order_ids: dict[OnlyOrderId, OnlyClientOrderId] = {}
        self._venue_order_ids: dict[OnlyOrderId, OnlyVenueOrderId] = {}

    @property
    def plugin_resource_id(self) -> str:
        return str(self._request.gateway_id)

    @property
    def state(self) -> OnlyPluginLifecycleState:
        return self._life.state

    @property
    def capabilities(self) -> OnlyBrokerCapabilities:
        return OnlyBrokerCapabilities(
            frozenset(
                {
                    OnlyBrokerCapability.CONNECT,
                    OnlyBrokerCapability.AUTHENTICATE,
                    OnlyBrokerCapability.SUBMIT_ORDER,
                    OnlyBrokerCapability.CANCEL_ORDER,
                    OnlyBrokerCapability.QUERY_ACCOUNT,
                    OnlyBrokerCapability.QUERY_BALANCES,
                    OnlyBrokerCapability.QUERY_POSITIONS,
                    OnlyBrokerCapability.QUERY_OPEN_ORDERS,
                    OnlyBrokerCapability.QUERY_ORDERS,
                    OnlyBrokerCapability.QUERY_TRADES,
                    OnlyBrokerCapability.PUSH_ORDER_UPDATES,
                    OnlyBrokerCapability.PUSH_TRADE_UPDATES,
                    OnlyBrokerCapability.PUSH_ACCOUNT_UPDATES,
                    OnlyBrokerCapability.PUSH_POSITION_UPDATES,
                    OnlyBrokerCapability.LIMIT_ORDER,
                    OnlyBrokerCapability.PARTIAL_FILL,
                }
            )
        )

    def initialize(self) -> None:
        self._trader.register_callback(self._callback)
        self._trader.start()
        self._life.initialize()

    def connect(self) -> OnlyBrokerConnectionResult:
        self._connection_state = OnlyBrokerConnectionState.CONNECTING
        result = self._trader.connect()
        if result == 0 and self._trader.subscribe(self._account) == 0:
            self._connection_state = OnlyBrokerConnectionState.READY
            self._life.state = OnlyPluginLifecycleState.CONNECTED
            self._synchronize()
        else:
            self._connection_state = OnlyBrokerConnectionState.FAILED
        return self._connection_result(result == 0)

    def authenticate(self) -> OnlyBrokerConnectionResult:
        return self._connection_result(self._connection_state is OnlyBrokerConnectionState.READY)

    def disconnect(self) -> OnlyBrokerConnectionResult:
        self.stop()
        return self._connection_result(True)

    def connection_snapshot(self) -> OnlyBrokerConnectionSnapshot:
        return self._connection_result(True).snapshot

    def start(self) -> None:
        self._life.start()

    def stop(self) -> None:
        if self._stop_attempted:
            return
        self._stop_attempted = True
        self._stopping.set()
        failure: Exception | None = None
        try:
            self._trader.stop()
        except Exception as exc:
            failure = exc
        self._connection_state = OnlyBrokerConnectionState.DISCONNECTED
        self._life.stop()
        reconnect = self._reconnect_thread
        if reconnect is not None and reconnect is not current_thread():
            reconnect.join(timeout=self._JOIN_TIMEOUT_SECONDS)
            if reconnect.is_alive():
                failure = failure or RuntimeError(
                    "MiniQMT reconnect worker did not stop: "
                    f"operation=join timeout_seconds={self._JOIN_TIMEOUT_SECONDS}"
                )
        if failure is not None:
            raise failure

    close = stop

    def health(self) -> OnlyPluginHealth:
        return self._life.health()

    def _connection_result(self, ok: bool) -> OnlyBrokerConnectionResult:
        from onlyalpha.domain.time import OnlyTimestamp

        stamp = OnlyTimestamp.from_datetime(self._request.clock.now())
        return OnlyBrokerConnectionResult(
            OnlyBrokerOperationStatus.RECEIVED if ok else OnlyBrokerOperationStatus.REJECTED,
            OnlyBrokerConnectionSnapshot(self._request.gateway_id, self._connection_state, stamp),
        )

    def submit_order(self, request: OnlyBrokerOrderRequest) -> OnlyBrokerOrderSubmitResult:
        try:
            if request.order_type is not OnlyOrderType.LIMIT:
                raise ValueError("LIMIT orders only")
            if request.price is None:
                raise ValueError("LIMIT order price is required")
            sequence = self._trader.order_stock_async(
                self._account,
                to_xt_symbol(request.instrument_id),
                map_side(request.side),
                int(request.quantity.value),
                require_limit(request.order_type),
                float(request.price.value),
                "OnlyAlpha",
                f"onlyalpha:{request.client_order_id}",
            )
            self._order_ids[int(sequence)] = request.order_id
            self._client_order_ids[request.order_id] = request.client_order_id
            return OnlyBrokerOrderSubmitResult(
                True,
                OnlyBrokerOperationStatus.RECEIVED,
                request.gateway_request_id,
                request.client_order_id,
            )
        except Exception as exc:
            return OnlyBrokerOrderSubmitResult(
                False,
                OnlyBrokerOperationStatus.REJECTED,
                request.gateway_request_id,
                request.client_order_id,
                str(exc),
            )

    def cancel_order(self, request: OnlyBrokerCancelRequest) -> OnlyBrokerCancelResult:
        try:
            sequence = self._trader.cancel_order_stock_async(self._account, int(str(request.venue_order_id)))
            return OnlyBrokerCancelResult(
                sequence >= 0,
                OnlyBrokerOperationStatus.RECEIVED,
                request.gateway_request_id,
            )
        except Exception as exc:
            return OnlyBrokerCancelResult(
                False,
                OnlyBrokerOperationStatus.REJECTED,
                request.gateway_request_id,
                str(exc),
            )

    def query_account(self, account_id: OnlyAccountId) -> OnlyBrokerAccountSnapshot:
        return self._callback.account_snapshot(self._trader.query_stock_asset(self._account))

    def query_balances(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerBalanceSnapshot, ...]:
        return (self._callback.balance_snapshot(self._trader.query_stock_asset(self._account)),)

    def query_positions(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerPositionSnapshot, ...]:
        return tuple(
            self._callback.position_snapshot(item) for item in (self._trader.query_stock_positions(self._account) or ())
        )

    def query_open_orders(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        return tuple(item for item in self.query_orders(account_id) if item.remaining_quantity.value > 0)

    def query_orders(
        self,
        account_id: OnlyAccountId,
        query: OnlyBrokerQuery | None = None,
    ) -> tuple[OnlyBrokerOrderSnapshot, ...]:
        return tuple(
            self._callback.order_snapshot(item) for item in (self._trader.query_stock_orders(self._account) or ())
        )

    def query_trades(
        self,
        account_id: OnlyAccountId,
        query: OnlyBrokerQuery | None = None,
    ) -> tuple[OnlyBrokerTradeSnapshot, ...]:
        return tuple(
            self._callback.trade_snapshot(item) for item in (self._trader.query_stock_trades(self._account) or ())
        )

    def resolve_order(self, remark: Any, xt_order_id: int) -> tuple[OnlyOrderId, OnlyClientOrderId]:
        text = str(remark or "")
        client = (
            OnlyClientOrderId(text.removeprefix("onlyalpha:"))
            if text.startswith("onlyalpha:")
            else OnlyClientOrderId(f"miniqmt-{xt_order_id}")
        )
        order = next(
            (key for key, value in self._client_order_ids.items() if value == client),
            None,
        )
        if order is None:
            order = self._order_ids.get(xt_order_id, OnlyOrderId(f"miniqmt-{xt_order_id}"))
        self._client_order_ids[order] = client
        return order, client

    def remember_venue_order(
        self,
        order_id: OnlyOrderId,
        venue_order_id: OnlyVenueOrderId,
        order_sysid: str,
    ) -> None:
        self._venue_order_ids[order_id] = venue_order_id
        if order_sysid:
            self._sysids[order_id] = order_sysid

    def _synchronize(self) -> None:
        self.query_account(self._request.account_id)
        self.query_positions(self._request.account_id)
        self.query_orders(self._request.account_id)
        self.query_trades(self._request.account_id)

    def on_disconnected(self) -> None:
        self._connection_state = OnlyBrokerConnectionState.DISCONNECTED
        with self._reconnect_lock:
            if self._stopping.is_set() or (self._reconnect_thread and self._reconnect_thread.is_alive()):
                return
            self._reconnect_thread = Thread(target=self._reconnect, name="onlyalpha-miniqmt-reconnect", daemon=False)
            self._reconnect_thread.start()

    def _reconnect(self) -> None:
        self._connection_state = OnlyBrokerConnectionState.RECONNECTING
        for attempt in range(self._config.reconnect_max_attempts):
            if self._stopping.wait(self._config.reconnect_initial_delay * (2**attempt)):
                return
            if self._trader.connect() == 0 and self._trader.subscribe(self._account) == 0:
                self._connection_state = OnlyBrokerConnectionState.READY
                self._synchronize()
                return
        self._connection_state = OnlyBrokerConnectionState.FAILED
