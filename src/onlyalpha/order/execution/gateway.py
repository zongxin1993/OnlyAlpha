"""Abstract Trade Gateway boundary; no SDK implementation exists in this phase."""

from abc import ABC, abstractmethod

from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.order.execution.models import (
    OnlyGatewayCancelRequest,
    OnlyGatewayCancelResult,
    OnlyGatewayOrderRequest,
    OnlyGatewayOrderSnapshot,
    OnlyGatewaySubmitResult,
    OnlyGatewayTradeSnapshot,
)


class OnlyTradeGateway(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def submit_order(self, request: OnlyGatewayOrderRequest) -> OnlyGatewaySubmitResult: ...

    @abstractmethod
    def cancel_order(self, request: OnlyGatewayCancelRequest) -> OnlyGatewayCancelResult: ...

    @abstractmethod
    def query_orders(self, account_id: OnlyAccountId) -> tuple[OnlyGatewayOrderSnapshot, ...]: ...

    @abstractmethod
    def query_trades(self, account_id: OnlyAccountId) -> tuple[OnlyGatewayTradeSnapshot, ...]: ...
