"""Runtime-thread application of standardized Gateway updates."""

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.order.execution.models import (
    OnlyGatewayOrderAcceptedUpdate,
    OnlyGatewayOrderCancelledUpdate,
    OnlyGatewayOrderFailedUpdate,
    OnlyGatewayOrderFillUpdate,
    OnlyGatewayOrderRejectedUpdate,
    OnlyGatewayOrderUpdate,
)
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyOrderEventPublisher
from onlyalpha.order.results import OnlyOrderMutationResult


class OnlyOrderUpdateProcessor:
    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        manager: OnlyOrderManager,
        publisher: OnlyOrderEventPublisher,
    ) -> None:
        self._runtime_id = runtime_id
        self._manager = manager
        self._publisher = publisher

    def process(self, update: OnlyGatewayOrderUpdate) -> OnlyOrderMutationResult:
        if update.runtime_id != self._runtime_id:
            raise ValueError("Gateway update belongs to another Runtime")
        if isinstance(update, OnlyGatewayOrderAcceptedUpdate):
            result = self._manager.apply_accepted(
                update.order_id,
                update.ts_init,
                update.venue_order_id,
                external_sequence=update.external_sequence,
                external_event_id=update.external_event_id,
                event_time=update.ts_event,
            )
        elif isinstance(update, OnlyGatewayOrderFillUpdate):
            result = self._manager.apply_fill(update.fill)
        elif isinstance(update, OnlyGatewayOrderCancelledUpdate):
            result = self._manager.apply_cancelled(
                update.order_id,
                update.ts_init,
                external_sequence=update.external_sequence,
                external_event_id=update.external_event_id,
                event_time=update.ts_event,
            )
        elif isinstance(update, OnlyGatewayOrderRejectedUpdate):
            result = self._manager.apply_rejected(
                update.order_id,
                update.ts_init,
                update.rejection,
                external_sequence=update.external_sequence,
                external_event_id=update.external_event_id,
                event_time=update.ts_event,
            )
        elif isinstance(update, OnlyGatewayOrderFailedUpdate):
            result = self._manager.apply_failed(update.order_id, update.ts_init, update.failure)
        else:
            raise TypeError(f"unsupported Gateway update: {type(update).__name__}")
        if result.changed:
            self._publisher.publish_many(result.events)
        return result
