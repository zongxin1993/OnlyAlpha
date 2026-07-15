"""Deterministic in-memory real-time and replay gateways."""

from onlyalpha.data.enums import (
    OnlyMarketDataCapability,
    OnlyMarketDataConnectionState,
    OnlyMarketDataRequestStatus,
)
from onlyalpha.data.identifiers import OnlyMarketDataGatewayId, OnlyMarketDataSourceId
from onlyalpha.data.models import (
    OnlyMarketDataConnectionResult,
    OnlyMarketDataConnectionSnapshot,
    OnlyMarketDataInboundUpdate,
    OnlyMarketDataSubscriptionRequest,
    OnlyMarketDataSubscriptionResult,
    OnlyMarketDataUnsubscriptionRequest,
)
from onlyalpha.data.ports import OnlyMarketDataCapabilities, OnlyMarketDataUpdateSink


class OnlyInMemoryMarketDataGateway:
    def __init__(
        self,
        gateway_id: OnlyMarketDataGatewayId,
        source_id: OnlyMarketDataSourceId,
        sink: OnlyMarketDataUpdateSink,
    ) -> None:
        self._gateway_id = gateway_id
        self._source_id = source_id
        self._sink = sink
        self._state = OnlyMarketDataConnectionState.DISCONNECTED
        self._subscriptions: dict[str, OnlyMarketDataSubscriptionRequest] = {}

    @property
    def source_id(self) -> OnlyMarketDataSourceId:
        return self._source_id

    @property
    def capabilities(self) -> OnlyMarketDataCapabilities:
        return frozenset(
            {
                OnlyMarketDataCapability.CONNECT,
                OnlyMarketDataCapability.AUTHENTICATE,
                OnlyMarketDataCapability.SUBSCRIBE_BAR,
                OnlyMarketDataCapability.SUBSCRIBE_QUOTE,
                OnlyMarketDataCapability.SUBSCRIBE_TRADE,
                OnlyMarketDataCapability.UNSUBSCRIBE,
                OnlyMarketDataCapability.PUSH_BAR,
                OnlyMarketDataCapability.PUSH_QUOTE,
                OnlyMarketDataCapability.PUSH_TRADE,
            }
        )

    def connect(self) -> OnlyMarketDataConnectionResult:
        self._state = OnlyMarketDataConnectionState.CONNECTED
        return self._connection_result()

    def authenticate(self) -> OnlyMarketDataConnectionResult:
        if self._state is not OnlyMarketDataConnectionState.CONNECTED:
            return OnlyMarketDataConnectionResult(
                OnlyMarketDataRequestStatus.REJECTED,
                self.connection_snapshot(),
                "gateway must be connected before authentication",
            )
        self._state = OnlyMarketDataConnectionState.READY
        return self._connection_result()

    def disconnect(self) -> OnlyMarketDataConnectionResult:
        self._state = OnlyMarketDataConnectionState.DISCONNECTED
        return self._connection_result()

    def connection_snapshot(self) -> OnlyMarketDataConnectionSnapshot:
        return OnlyMarketDataConnectionSnapshot(self._gateway_id, self._state)

    def subscribe(self, request: OnlyMarketDataSubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        if self._state is not OnlyMarketDataConnectionState.READY:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "gateway is not ready")
        if request.source_id != self._source_id:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "source mismatch")
        subscription_id = f"MDSUB-{request.request_id}"
        self._subscriptions[subscription_id] = request
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, subscription_id)

    def unsubscribe(self, request: OnlyMarketDataUnsubscriptionRequest) -> OnlyMarketDataSubscriptionResult:
        if request.subscription_id not in self._subscriptions:
            return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.REJECTED, None, "unknown subscription")
        del self._subscriptions[request.subscription_id]
        return OnlyMarketDataSubscriptionResult(OnlyMarketDataRequestStatus.ACCEPTED, request.subscription_id)

    def publish(self, update: OnlyMarketDataInboundUpdate) -> None:
        if self._state is not OnlyMarketDataConnectionState.READY:
            raise RuntimeError("market-data gateway is not ready")
        if update.source_id != self._source_id:
            raise ValueError("market-data Gateway source mismatch")
        self._sink(update)

    def _connection_result(self) -> OnlyMarketDataConnectionResult:
        return OnlyMarketDataConnectionResult(OnlyMarketDataRequestStatus.ACCEPTED, self.connection_snapshot())


class OnlyReplayMarketDataGateway(OnlyInMemoryMarketDataGateway):
    """Explicit adapter for replay-like push tests; ReplayService remains the backtest path."""
