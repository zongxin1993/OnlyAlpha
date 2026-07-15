"""Small composable Broker boundary Ports."""

from typing import Protocol

from onlyalpha.broker.capabilities import OnlyBrokerCapabilities
from onlyalpha.broker.models import (
    OnlyBrokerAccountSnapshot,
    OnlyBrokerAuthenticationResult,
    OnlyBrokerBalanceSnapshot,
    OnlyBrokerCancelRequest,
    OnlyBrokerCancelResult,
    OnlyBrokerConnectionResult,
    OnlyBrokerConnectionSnapshot,
    OnlyBrokerDisconnectResult,
    OnlyBrokerOrderRequest,
    OnlyBrokerOrderSnapshot,
    OnlyBrokerOrderSubmitResult,
    OnlyBrokerPositionSnapshot,
    OnlyBrokerQuery,
    OnlyBrokerTradeSnapshot,
)
from onlyalpha.domain.identifiers import OnlyAccountId


class OnlyBrokerConnectionPort(Protocol):
    @property
    def capabilities(self) -> OnlyBrokerCapabilities: ...

    def connect(self) -> OnlyBrokerConnectionResult: ...

    def authenticate(self) -> OnlyBrokerAuthenticationResult: ...

    def disconnect(self) -> OnlyBrokerDisconnectResult: ...

    def connection_snapshot(self) -> OnlyBrokerConnectionSnapshot: ...


class OnlyBrokerTradingPort(Protocol):
    def submit_order(self, request: OnlyBrokerOrderRequest) -> OnlyBrokerOrderSubmitResult: ...

    def cancel_order(self, request: OnlyBrokerCancelRequest) -> OnlyBrokerCancelResult: ...


class OnlyBrokerAccountPort(Protocol):
    def query_account(self, account_id: OnlyAccountId) -> OnlyBrokerAccountSnapshot: ...

    def query_balances(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerBalanceSnapshot, ...]: ...


class OnlyBrokerPositionPort(Protocol):
    def query_positions(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerPositionSnapshot, ...]: ...


class OnlyBrokerOrderQueryPort(Protocol):
    def query_open_orders(self, account_id: OnlyAccountId) -> tuple[OnlyBrokerOrderSnapshot, ...]: ...

    def query_orders(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerOrderSnapshot, ...]: ...


class OnlyBrokerTradeQueryPort(Protocol):
    def query_trades(
        self, account_id: OnlyAccountId, query: OnlyBrokerQuery | None = None
    ) -> tuple[OnlyBrokerTradeSnapshot, ...]: ...


class OnlyBrokerGateway(
    OnlyBrokerConnectionPort,
    OnlyBrokerTradingPort,
    OnlyBrokerAccountPort,
    OnlyBrokerPositionPort,
    OnlyBrokerOrderQueryPort,
    OnlyBrokerTradeQueryPort,
    Protocol,
):
    pass
