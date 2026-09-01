"""Function-call Order command service; Event publication follows mutation."""

from collections.abc import Callable
from dataclasses import replace

from onlyalpha.domain.enums import OnlyOrderStatus
from onlyalpha.domain.execution import (
    OnlyCancelOrderRequest,
    OnlyOrderFailure,
    OnlyOrderRequest,
    OnlyOrderSnapshot,
)
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyClusterId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.trading import OnlyPositionEffect
from onlyalpha.domain.value import OnlyPrice
from onlyalpha.execution.reference import OnlyExecutionReferencePlanningService
from onlyalpha.fee.estimate import OnlyOrderFeeEstimate, OnlyOrderFundingPlan
from onlyalpha.fee.models import OnlyOrderFeePolicyBinding
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.order.cash_port import OnlyOrderCashReservationPort
from onlyalpha.order.enums import OnlyOrderFailureCode
from onlyalpha.order.execution.models import (
    OnlyExecutionCancelRequest,
    OnlyExecutionSubmissionOutcome,
    OnlyExecutionSubmitResult,
)
from onlyalpha.order.execution.service import OnlyExecutionService
from onlyalpha.order.intent import OnlyOrderIntentDurabilityPort, OnlyRuntimeIntentReferenceSink
from onlyalpha.order.manager import (
    OnlyOrderFeeContractFactory,
    OnlyOrderManager,
    OnlyOrderPlanningFeeContractFactory,
)
from onlyalpha.order.margin_port import OnlyOrderMarginReservationPort
from onlyalpha.order.position_port import OnlyOrderPositionReservationPort
from onlyalpha.order.publisher import OnlyOrderEventPublisher
from onlyalpha.order.results import OnlyOrderCancelResult, OnlyOrderSubmitResult
from onlyalpha.risk.contexts import OnlyRiskEvaluationContext
from onlyalpha.risk.decisions import OnlyRiskDecision, OnlyRiskRejection
from onlyalpha.risk.enums import (
    OnlyRiskRejectionCode,
    OnlyRiskReleaseReason,
    OnlyRiskRuleScope,
)
from onlyalpha.risk.identifiers import OnlyRiskRuleId
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
        position_reservations: OnlyOrderPositionReservationPort | None = None,
        cash_reservations: OnlyOrderCashReservationPort | None = None,
        margin_reservations: OnlyOrderMarginReservationPort | None = None,
        fee_contract_factory: OnlyOrderFeeContractFactory | None = None,
        fee_reconciliation_risk_gate: OnlyFeeReconciliationRiskGate | None = None,
        intent_durability: OnlyOrderIntentDurabilityPort | None = None,
        intent_reference_sink: OnlyRuntimeIntentReferenceSink | None = None,
        execution_reference_planning: OnlyExecutionReferencePlanningService | None = None,
        planning_fee_contract_factory: OnlyOrderPlanningFeeContractFactory | None = None,
    ) -> None:
        self._manager = manager
        self._execution = execution
        self._publisher = publisher
        self._now = now
        self._risk_service = risk_service
        self._risk_context = risk_context
        self._position_reservations = position_reservations
        self._cash_reservations = cash_reservations
        self._margin_reservations = margin_reservations
        self._fee_contract_factory = fee_contract_factory
        self._fee_reconciliation_risk_gate = fee_reconciliation_risk_gate
        self._intent_durability = intent_durability
        self._intent_reference_sink = intent_reference_sink
        self._execution_reference_planning = execution_reference_planning
        self._planning_fee_contract_factory = planning_fee_contract_factory
        if bool(getattr(execution, "requires_durable_intent", False)) and intent_durability is None:
            raise ValueError("REAL_EXECUTION_REQUIRES_DURABLE_ORDER_INTENT")

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
        risk_context = self._risk_context(cluster_id, account_id, timestamp)
        risk_change = self._risk_service.classify_order_change(request, risk_context)
        execution_reference = None
        planning_price: OnlyPrice | None = None
        if self._execution_reference_planning is not None:
            reference_plan = self._execution_reference_planning.plan(request, risk_change, timestamp)
            if not reference_plan.accepted:
                code = (
                    OnlyRiskRejectionCode.PRICE_LIMIT_EXCEEDED
                    if reference_plan.failure_code == "ORDER_PRICE_DEVIATION_EXCEEDED"
                    else OnlyRiskRejectionCode.REQUIRED_RISK_DATA_MISSING
                )
                decision = OnlyRiskDecision.rejected(
                    OnlyRiskRejection(
                        OnlyRiskRuleId("REALTIME_EXECUTION_REFERENCE"),
                        code,
                        reference_plan.message or "realtime execution reference was denied",
                        OnlyRiskRuleScope.RUNTIME,
                        details={
                            "reference_failure": reference_plan.failure_code or "REFERENCE_UNKNOWN",
                            "market_snapshot_fingerprint": reference_plan.snapshot.fingerprint,
                            "execution_profile_fingerprint": self._execution_reference_planning.profile.fingerprint,
                        },
                    )
                )
                return OnlyOrderSubmitResult(
                    False,
                    False,
                    None,
                    None,
                    None,
                    None,
                    (),
                    reference_plan.failure_code,
                    decision,
                )
            execution_reference = reference_plan.evidence
            if execution_reference is not None:
                planning_price = execution_reference.resolved_order_price
                risk_context = replace(
                    risk_context,
                    order_planning_price=planning_price,
                    market_snapshot_fingerprint=execution_reference.snapshot_fingerprint,
                    market_update_id=execution_reference.market_update_id,
                    execution_profile_fingerprint=execution_reference.profile_fingerprint,
                )
        if self._fee_reconciliation_risk_gate is not None:
            self._fee_reconciliation_risk_gate.require_order_allowed(account_id, risk_change)
        risk_decision = self._risk_service.evaluate_order(
            request,
            risk_context,
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
        if self._intent_durability is None:
            intent_token = None
        elif execution_reference is None:
            intent_token = self._intent_durability.begin(request, cluster_id, account_id, timestamp)
        else:
            intent_token = self._intent_durability.begin(
                request,
                cluster_id,
                account_id,
                timestamp,
                execution_reference=execution_reference,
            )
        fee_contract_factory = self._fee_contract_factory
        if self._planning_fee_contract_factory is not None:
            planning_fee_contract_factory = self._planning_fee_contract_factory

            def fee_contract_factory(
                order: OnlyOrderSnapshot,
                created_at: OnlyTimestamp,
            ) -> tuple[OnlyOrderFeePolicyBinding, OnlyOrderFeeEstimate, OnlyOrderFundingPlan]:
                return planning_fee_contract_factory(order, created_at, planning_price)

        created = self._manager.create_order(
            request,
            cluster_id,
            account_id,
            timestamp,
            fee_contract_factory,
        )
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
        reservation = self._risk_service.reserve_order(
            created.snapshot,
            timestamp,
            planning_price=planning_price,
        )
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
        uses_position_reservation = (
            request.execution_intent is not None
            and request.execution_intent.position_effect is OnlyPositionEffect.CLOSE
        )
        if self._margin_reservations is not None:
            try:
                if planning_price is None:
                    self._margin_reservations.reserve(created.snapshot, timestamp)
                else:
                    self._margin_reservations.reserve(
                        created.snapshot,
                        timestamp,
                        planning_price=planning_price,
                    )
            except Exception as exc:
                self._risk_service.release_order(
                    created.order_id,
                    cluster_id,
                    account_id,
                    OnlyRiskReleaseReason.EXECUTION_REJECTED,
                    self._now(),
                )
                failed = self._manager.apply_failed(
                    created.order_id,
                    self._now(),
                    OnlyOrderFailure(OnlyOrderFailureCode.EXECUTION.value, str(exc)),
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
                    str(exc),
                    risk_decision,
                )
        if self._position_reservations is not None and uses_position_reservation:
            try:
                self._position_reservations.reserve(created.snapshot, timestamp)
            except Exception as exc:
                self._risk_service.release_order(
                    created.order_id,
                    cluster_id,
                    account_id,
                    OnlyRiskReleaseReason.EXECUTION_REJECTED,
                    self._now(),
                )
                if self._margin_reservations is not None:
                    self._margin_reservations.release(created.order_id, self._now())
                failed = self._manager.apply_failed(
                    created.order_id,
                    self._now(),
                    OnlyOrderFailure(OnlyOrderFailureCode.EXECUTION.value, str(exc)),
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
                    str(exc),
                    risk_decision,
                )
        if self._cash_reservations is not None:
            try:
                if planning_price is None:
                    self._cash_reservations.reserve(created.snapshot, timestamp)
                else:
                    self._cash_reservations.reserve(
                        created.snapshot,
                        timestamp,
                        planning_price=planning_price,
                    )
            except Exception as exc:
                self._risk_service.release_order(
                    created.order_id,
                    cluster_id,
                    account_id,
                    OnlyRiskReleaseReason.EXECUTION_REJECTED,
                    self._now(),
                )
                if self._position_reservations is not None and uses_position_reservation:
                    self._position_reservations.release(created.order_id, self._now(), broker_confirmed=True)
                if self._margin_reservations is not None:
                    self._margin_reservations.release(created.order_id, self._now())
                failed = self._manager.apply_failed(
                    created.order_id,
                    self._now(),
                    OnlyOrderFailure(OnlyOrderFailureCode.EXECUTION.value, str(exc)),
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
                    str(exc),
                    risk_decision,
                )
        if self._intent_durability is not None:
            durability = self._intent_durability.commit(intent_token, created.snapshot)
            if not durability.ready or durability.reference is None:
                return OnlyOrderSubmitResult(
                    True,
                    False,
                    None,
                    created.order_id,
                    created.snapshot.client_order_id,
                    created.snapshot,
                    (),
                    durability.error or "ORDER_INTENT_NOT_PROJECTION_READY",
                    risk_decision,
                    OnlyExecutionSubmissionOutcome.NOT_DISPATCHED,
                )
            if self._intent_reference_sink is not None:
                self._intent_reference_sink.record_runtime_intent(created.order_id, durability.reference)
        self._publisher.publish_many(created.events)
        try:
            execution_result = self._execution.submit_order(created.snapshot)
        except Exception as exc:
            # Once control crosses the execution Port, a generic caller cannot
            # prove that an exception occurred before remote dispatch.
            execution_result = OnlyExecutionSubmitResult(
                True,
                f"SUBMISSION_OUTCOME_UNKNOWN: {type(exc).__name__}",
                OnlyExecutionSubmissionOutcome.UNKNOWN,
            )
        if execution_result.outcome is OnlyExecutionSubmissionOutcome.SUPPRESSED:
            self._manager.record_submission_outcome(created.order_id, OnlyExecutionSubmissionOutcome.SUPPRESSED)
            failed = self._manager.apply_failed(
                created.order_id,
                self._now(),
                OnlyOrderFailure(
                    OnlyOrderFailureCode.EXECUTION.value,
                    "EXECUTION_SUPPRESSED_BY_RUNTIME",
                ),
            )
            self._publisher.publish_many(failed.events)
            self._risk_service.release_order(
                created.order_id,
                cluster_id,
                account_id,
                OnlyRiskReleaseReason.EXECUTION_SUPPRESSED,
                self._now(),
            )
            if self._position_reservations is not None and uses_position_reservation:
                self._position_reservations.release(created.order_id, self._now(), broker_confirmed=True)
            if self._cash_reservations is not None:
                self._cash_reservations.release(created.order_id, self._now())
            if self._margin_reservations is not None:
                self._margin_reservations.release(created.order_id, self._now())
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
        if execution_result.outcome in {
            OnlyExecutionSubmissionOutcome.KNOWN_RESULT,
            OnlyExecutionSubmissionOutcome.UNKNOWN,
        }:
            self._manager.record_submission_outcome(created.order_id, execution_result.outcome)
            if self._position_reservations is not None and uses_position_reservation:
                self._position_reservations.sent(created.order_id, self._now())
            if self._cash_reservations is not None:
                self._cash_reservations.sent(created.order_id, self._now())
            if self._margin_reservations is not None:
                self._margin_reservations.sent(created.order_id, self._now())
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
                execution_result.outcome,
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
        if self._position_reservations is not None and uses_position_reservation:
            self._position_reservations.release(created.order_id, self._now(), broker_confirmed=True)
        if self._cash_reservations is not None:
            self._cash_reservations.release(created.order_id, self._now())
        if self._margin_reservations is not None:
            self._margin_reservations.release(created.order_id, self._now())
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
            execution_result.outcome,
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
