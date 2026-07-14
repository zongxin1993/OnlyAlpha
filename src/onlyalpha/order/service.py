"""Function-call Order command service; Event publication follows mutation."""

from collections.abc import Callable

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import (
    OnlyCancelOrderRequest,
    OnlyOrderFailure,
    OnlyOrderRequest,
)
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.order.enums import OnlyOrderFailureCode
from onlyalpha.order.execution.models import OnlyExecutionCancelRequest
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.manager import OnlyOrderManager
from onlyalpha.order.publisher import OnlyOrderEventPublisher
from onlyalpha.order.results import OnlyOrderCancelResult, OnlyOrderSubmitResult
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.enums import OnlyRiskReleaseReason
from onlyalpha.risk.service import OnlyRiskService


class OnlyOrderService:
    """Binds Scope, persists local truth and calls the external execution port."""

    def __init__(
        self,
        manager: OnlyOrderManager,
        execution: OnlyExecutionService,
        publisher: OnlyOrderEventPublisher,
        now: Callable[[], OnlyTimestamp],
        risk_service: OnlyRiskService,
        risk_context: Callable[[OnlyClusterId, OnlyAccountId, OnlyTimestamp], OnlyRiskEvaluationContext],
    ) -> None:
        self._manager = manager
        self._execution = execution
        self._publisher = publisher
        self._now = now
        self._risk_service = risk_service
        self._risk_context = risk_context

    def submit(
        self,
        request: OnlyOrderRequest,
        cluster_id: OnlyClusterId,
        default_account_id: OnlyAccountId,
    ) -> OnlyOrderSubmitResult:
        timestamp = self._now()
        if request.expire_time is not None and request.expire_time.unix_nanos <= timestamp.unix_nanos:
            raise ValueError("Order expire_time must be later than submission time")
        account_id = request.account_id or default_account_id
        risk_decision = self._risk_service.evaluate_order(
            request,
            self._risk_context(cluster_id, account_id, timestamp),
        )
        if not risk_decision.is_accepted:
            message = (
                risk_decision.rejection.message
                if risk_decision.rejection is not None
                else risk_decision.error.message
                if risk_decision.error is not None
                else "Risk evaluation failed"
            )
            return OnlyOrderSubmitResult(
                False,
                False,
                None,
                None,
                None,
                None,
                (),
                message,
                risk_decision,
            )
        created = self._manager.create_order(request, cluster_id, account_id, timestamp)
        if not created.changed:
            return OnlyOrderSubmitResult(
                False,
                created.snapshot.status is not OnlyOrderStatus.CREATED,
                None,
                created.order_id,
                created.snapshot.client_order_id,
                created.snapshot,
                (),
                created.error,
                risk_decision,
            )
        reservation = self._risk_service.reserve_order(created.snapshot, timestamp)
        if not reservation.changed and reservation.reservation is None:
            failed = self._manager.apply_failed(
                created.order_id,
                self._now(),
                OnlyOrderFailure(OnlyOrderFailureCode.EXECUTION.value, reservation.error or "Risk reservation failed"),
            )
            self._publisher.publish_many(created.events + failed.events)
            return OnlyOrderSubmitResult(
                True,
                False,
                None,
                created.order_id,
                created.snapshot.client_order_id,
                failed.snapshot,
                created.events + failed.events,
                reservation.error or "Risk reservation failed",
                risk_decision,
            )
        self._publisher.publish_many(created.events)
        execution_result = self._execution.submit_order(created.snapshot)
        if execution_result.received:
            submitted = self._manager.mark_submitted(created.order_id, self._now())
            self._publisher.publish_many(submitted.events)
            events = created.events + submitted.events
            return OnlyOrderSubmitResult(
                True,
                submitted.changed,
                None,
                created.order_id,
                created.snapshot.client_order_id,
                submitted.snapshot,
                events,
                submitted.error,
                risk_decision,
            )
        failed = self._manager.apply_failed(
            created.order_id,
            self._now(),
            OnlyOrderFailure(OnlyOrderFailureCode.EXECUTION.value, execution_result.message),
        )
        self._publisher.publish_many(failed.events)
        self._risk_service.release_order(
            created.order_id,
            cluster_id,
            account_id,
            OnlyRiskReleaseReason.EXECUTION_REJECTED,
            self._now(),
        )
        return OnlyOrderSubmitResult(
            True,
            False,
            None,
            created.order_id,
            created.snapshot.client_order_id,
            failed.snapshot,
            created.events + failed.events,
            execution_result.message,
            risk_decision,
        )

    def cancel(
        self,
        request: OnlyCancelOrderRequest,
        cluster_id: OnlyClusterId,
    ) -> OnlyOrderCancelResult:
        current = self._manager.require_snapshot(request.order_id)
        if current.cluster_id != cluster_id:
            raise PermissionError("Cluster cannot cancel another Cluster's Order")
        mutation = self._manager.request_cancel(request.order_id, self._now())
        if not mutation.changed:
            return OnlyOrderCancelResult(False, False, mutation.snapshot, (), mutation.error)
        self._publisher.publish_many(mutation.events)
        execution_result = self._execution.cancel_order(
            OnlyExecutionCancelRequest(
                current.runtime_id,
                current.order_id,
                current.client_order_id,
                current.venue_order_id,
                current.account_id,
                mutation.snapshot.cancel_requested_at or self._now(),
                request.reason,
            )
        )
        return OnlyOrderCancelResult(
            execution_result.received,
            False,
            mutation.snapshot,
            mutation.events,
            None if execution_result.received else execution_result.message,
        )
