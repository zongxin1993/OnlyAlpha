"""Explicit non-trading placeholders; they never accept or fill an Order."""

from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyAccountId
from onlyalpha.order.execution.gateway import OnlyTradeGateway
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelRequest,
    OnlyExecutionCancelResult,
    OnlyExecutionSubmitResult,
    OnlyGatewayCancelRequest,
    OnlyGatewayCancelResult,
    OnlyGatewayOrderRequest,
    OnlyGatewayOrderSnapshot,
    OnlyGatewaySubmitResult,
    OnlyGatewayTradeSnapshot,
)


class OnlyPlaceholderExecutionService:
    """Records transport requests without fabricating venue acceptance or fills."""

    def __init__(self) -> None:
        self._submissions: list[OnlyOrderSnapshot] = []
        self._cancellations: list[OnlyExecutionCancelRequest] = []

    @property
    def submissions(self) -> tuple[OnlyOrderSnapshot, ...]:
        return tuple(self._submissions)

    @property
    def cancellations(self) -> tuple[OnlyExecutionCancelRequest, ...]:
        return tuple(self._cancellations)

    def submit_order(self, order: OnlyOrderSnapshot) -> OnlyExecutionSubmitResult:
        self._submissions.append(order)
        return OnlyExecutionSubmitResult(True, "Placeholder received submit request; venue state remains unknown")

    def cancel_order(self, request: OnlyExecutionCancelRequest) -> OnlyExecutionCancelResult:
        self._cancellations.append(request)
        return OnlyExecutionCancelResult(True, "Placeholder received cancel request; Order is not Cancelled")


class OnlyPlaceholderTradeGateway(OnlyTradeGateway):
    """Records normalized requests and returns no venue IDs, orders or trades."""

    def __init__(self) -> None:
        self._connected = False
        self._submissions: list[OnlyGatewayOrderRequest] = []
        self._cancellations: list[OnlyGatewayCancelRequest] = []

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def submit_order(self, request: OnlyGatewayOrderRequest) -> OnlyGatewaySubmitResult:
        self._submissions.append(request)
        return OnlyGatewaySubmitResult(True, "Placeholder Gateway received request", None)

    def cancel_order(self, request: OnlyGatewayCancelRequest) -> OnlyGatewayCancelResult:
        self._cancellations.append(request)
        return OnlyGatewayCancelResult(True, "Placeholder Gateway received cancel request")

    def query_orders(self, account_id: OnlyAccountId) -> tuple[OnlyGatewayOrderSnapshot, ...]:
        del account_id
        return ()

    def query_trades(self, account_id: OnlyAccountId) -> tuple[OnlyGatewayTradeSnapshot, ...]:
        del account_id
        return ()
