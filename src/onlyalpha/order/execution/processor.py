"""Runtime-thread application of standardized Gateway updates."""

from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.order.execution.models import (
    OnlyGatewayOrderAcceptedUpdate,
    OnlyGatewayOrderCancelledUpdate,
    OnlyGatewayOrderExpiredUpdate,
    OnlyGatewayOrderFailedUpdate,
    OnlyGatewayOrderFillUpdate,
    OnlyGatewayOrderRejectedUpdate,
    OnlyGatewayOrderUpdate,
)
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.position_port import OnlyOrderPositionReservationPort
from onlyalpha.order.publisher import OnlyOrderEventPublisher
from onlyalpha.order.results import OnlyOrderMutationResult
from onlyalpha.risk.enums import OnlyRiskReleaseReason
from onlyalpha.risk.service import OnlyRiskService


class OnlyOrderUpdateProcessor:
    def __init__(
        self,
        runtime_id: OnlyRuntimeId,
        manager: OnlyOrderManager,
        publisher: OnlyOrderEventPublisher,
        risk_service: OnlyRiskService | None = None,
        position_reservations: OnlyOrderPositionReservationPort | None = None,
    ) -> None:
        self._runtime_id = runtime_id
        self._manager = manager
        self._publisher = publisher
        self._risk_service = risk_service
        self._position_reservations = position_reservations

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
        elif isinstance(update, OnlyGatewayOrderExpiredUpdate):
            result = self._manager.apply_expired(
                update.order_id,
                update.ts_init,
                external_sequence=update.external_sequence,
                external_event_id=update.external_event_id,
            )
        elif isinstance(update, OnlyGatewayOrderFailedUpdate):
            result = self._manager.apply_failed(update.order_id, update.ts_init, update.failure)
        else:
            raise TypeError(f"unsupported Gateway update: {type(update).__name__}")
        if result.changed:
            self._publisher.publish_many(result.events)
            if self._position_reservations is not None:
                if isinstance(update, OnlyGatewayOrderAcceptedUpdate):
                    self._position_reservations.acknowledged(result.order_id, update.ts_init)
                elif isinstance(update, OnlyGatewayOrderFillUpdate):
                    self._position_reservations.consume(
                        result.order_id,
                        update.fill.quantity,
                        update.ts_init,
                    )
            release_reason = None
            if isinstance(update, OnlyGatewayOrderCancelledUpdate):
                release_reason = OnlyRiskReleaseReason.ORDER_CANCELLED
            elif isinstance(update, OnlyGatewayOrderRejectedUpdate):
                release_reason = OnlyRiskReleaseReason.ORDER_REJECTED
            elif isinstance(update, OnlyGatewayOrderFailedUpdate):
                release_reason = OnlyRiskReleaseReason.ORDER_FAILED
            elif isinstance(update, OnlyGatewayOrderExpiredUpdate):
                release_reason = OnlyRiskReleaseReason.ORDER_EXPIRED
            if release_reason is not None and self._risk_service is not None:
                self._risk_service.release_order(
                    result.order_id,
                    result.snapshot.cluster_id,
                    result.snapshot.account_id,
                    release_reason,
                    update.ts_init,
                )
            if release_reason is not None and self._position_reservations is not None:
                self._position_reservations.release(
                    result.order_id,
                    update.ts_init,
                    broker_confirmed=not isinstance(update, OnlyGatewayOrderCancelledUpdate),
                )
        return result
