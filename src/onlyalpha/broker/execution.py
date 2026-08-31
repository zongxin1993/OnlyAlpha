"""Adapter from the existing Runtime execution Port to a normalized Broker Port."""

from onlyalpha.broker.identifiers import OnlyBrokerRequestId
from onlyalpha.broker.models import OnlyBrokerCancelRequest, OnlyBrokerOrderRequest
from onlyalpha.broker.ports import OnlyBrokerTradingPort
from onlyalpha.core.clock import OnlyClock
from onlyalpha.domain.execution import OnlyOrderSnapshot
from onlyalpha.domain.identifiers import OnlyOrderId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelRequest,
    OnlyExecutionCancelResult,
    OnlyExecutionSubmissionOutcome,
    OnlyExecutionSubmitResult,
)
from onlyalpha.order.intent import OnlyRuntimeIntentReference


class OnlyBrokerExecutionService:
    requires_durable_intent = True

    def __init__(self, gateway: OnlyBrokerTradingPort, clock: OnlyClock) -> None:
        self._gateway = gateway
        self._clock = clock
        self._sequence = 0
        self._intent_references: dict[OnlyOrderId, OnlyRuntimeIntentReference] = {}

    def record_runtime_intent(self, order_id: OnlyOrderId, reference: OnlyRuntimeIntentReference) -> None:
        previous = self._intent_references.setdefault(order_id, reference)
        if previous != reference:
            raise ValueError("BROKER_RUNTIME_INTENT_REFERENCE_CONFLICT")

    def submit_order(self, order: OnlyOrderSnapshot) -> OnlyExecutionSubmitResult:
        reference = self._intent_references.get(order.order_id)
        if reference is None:
            return OnlyExecutionSubmitResult(
                False,
                "RUNTIME_ORDER_INTENT_REFERENCE_MISSING",
                OnlyExecutionSubmissionOutcome.NOT_DISPATCHED,
            )
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
                reference.transaction_id,
                reference.authority_hash,
            )
        )
        if result.status.value == "UNKNOWN":
            outcome = OnlyExecutionSubmissionOutcome.UNKNOWN
        elif result.request_received:
            outcome = OnlyExecutionSubmissionOutcome.KNOWN_RESULT
        else:
            outcome = OnlyExecutionSubmissionOutcome.NOT_DISPATCHED
        return OnlyExecutionSubmitResult(
            result.request_received,
            result.immediate_error or result.status.value,
            outcome,
        )

    def cancel_order(self, request: OnlyExecutionCancelRequest) -> OnlyExecutionCancelResult:
        self._sequence += 1
        result = self._gateway.cancel_order(
            OnlyBrokerCancelRequest(
                OnlyBrokerRequestId(f"cancel-{self._sequence:08d}"),
                request.account_id,
                request.order_id,
                request.venue_order_id,
                request.requested_at,
                request.client_order_id,
            )
        )
        return OnlyExecutionCancelResult(result.request_received, result.immediate_error or result.status.value)
