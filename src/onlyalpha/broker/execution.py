"""Adapter from the existing Runtime execution Port to a normalized Broker Port."""

from onlyalpha.broker.identifiers import OnlyBrokerRequestId
from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.broker.ports import OnlyBrokerTradingPort
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelRequest,
    OnlyExecutionCancelResult,
    OnlyExecutionSubmitResult,
)


class OnlyBrokerExecutionService:
    def __init__(self, gateway: OnlyBrokerTradingPort, clock: OnlyClock) -> None:
        self._gateway = gateway
        self._clock = clock
        self._sequence = 0

    def submit_order(self, order: OnlyOrderSnapshot) -> OnlyExecutionSubmitResult:
        self._sequence += 1
        result = self._gateway.submit_order(
            OnlyBrokerOrderRequest(
                OnlyBrokerRequestId(f"submit-{self._sequence:08d}"),
                order.order_id,
                order.client_order_id,
                order.account_id,
                order.instrument_id,
                order.side,
                order.offset,
                order.order_type,
                order.time_in_force,
                order.quantity,
                order.price,
                OnlyTimestamp.from_unix_nanos(self._clock.timestamp_ns()),
            )
        )
        return OnlyExecutionSubmitResult(result.request_received, result.immediate_error or result.status.value)

    def cancel_order(self, request: OnlyExecutionCancelRequest) -> OnlyExecutionCancelResult:
        self._sequence += 1
        result = self._gateway.cancel_order(
            OnlyBrokerCancelRequest(
                OnlyBrokerRequestId(f"cancel-{self._sequence:08d}"),
                request.account_id,
                request.order_id,
                request.venue_order_id,
                request.requested_at,
            )
        )
        return OnlyExecutionCancelResult(result.request_received, result.immediate_error or result.status.value)
