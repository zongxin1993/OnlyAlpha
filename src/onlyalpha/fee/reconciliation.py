"""Pure durable fee-reconciliation planning decisions."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyClusterId, OnlyOrderId, OnlyTradeId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.adjustment import (
    OnlyFeeAdjustment,
    OnlyFeeAdjustmentDirection,
    OnlyFeeDifferenceReason,
)
from onlyalpha.fee.evidence import (
    OnlyExternalFeeEvidence,
    OnlyExternalFeeEvidenceMode,
    OnlyExternalFeeEvidenceScope,
)
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeEconomicDirection, OnlyFeeType, only_fee_fingerprint


class OnlyFeeReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    RECONCILED_WITH_ADJUSTMENT = "RECONCILED_WITH_ADJUSTMENT"
    INCOMPLETE_EXTERNAL_DATA = "INCOMPLETE_EXTERNAL_DATA"
    DUPLICATE_EVIDENCE = "DUPLICATE_EVIDENCE"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    UNEXPLAINED_DIFFERENCE = "UNEXPLAINED_DIFFERENCE"
    TRADING_BLOCKED = "TRADING_BLOCKED"


@dataclass(frozen=True, slots=True)
class OnlyLocalFeeReconciliationComponent(OnlyDomainModel):
    fee_type: OnlyFeeType
    authority: OnlyFeeAuthority
    external_component_id: str | None
    direction: OnlyFeeEconomicDirection
    amount: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationInput:
    evidence: OnlyExternalFeeEvidence
    local_components: tuple[OnlyLocalFeeReconciliationComponent, ...]
    prior_adjustments: OnlyMoney
    cluster_id: OnlyClusterId | None
    order_id: OnlyOrderId | None
    trade_id: OnlyTradeId | None
    reason: OnlyFeeDifferenceReason
    materiality_threshold: OnlyMoney
    evidence_classification: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationDecision(OnlyDomainModel):
    reconciliation_id: str
    evidence_id: str
    scope: OnlyExternalFeeEvidenceScope
    local_model_amount: OnlyMoney | None
    prior_adjustments: OnlyMoney
    current_effective_amount: OnlyMoney | None
    reported_authoritative_amount: OnlyMoney | None
    difference: OnlyMoney | None
    reason: OnlyFeeDifferenceReason | None
    status: OnlyFeeReconciliationStatus
    adjustment: OnlyFeeAdjustment | None


class OnlyFeeReconciliationPlanner:
    def plan(self, request: OnlyFeeReconciliationInput) -> OnlyFeeReconciliationDecision:
        evidence = request.evidence
        if request.evidence_classification == "DUPLICATE_EVIDENCE":
            return self._decision(request, OnlyFeeReconciliationStatus.DUPLICATE_EVIDENCE, None, None, None)
        if request.evidence_classification is not None:
            return self._decision(request, OnlyFeeReconciliationStatus.EVIDENCE_CONFLICT, None, None, None)
        local = self._local_amount(request)
        reported = self._reported_amount(request)
        if local is None or reported is None:
            return self._decision(request, OnlyFeeReconciliationStatus.INCOMPLETE_EXTERNAL_DATA, local, reported, None)
        if local.currency != reported.currency or local.currency != request.prior_adjustments.currency:
            return self._decision(request, OnlyFeeReconciliationStatus.UNEXPLAINED_DIFFERENCE, local, reported, None)
        current = OnlyMoney(local.amount + request.prior_adjustments.amount, local.currency)
        signed_difference = reported.amount - current.amount
        difference = OnlyMoney(abs(signed_difference), local.currency)
        if signed_difference == 0:
            return self._decision(request, OnlyFeeReconciliationStatus.MATCHED, local, reported, difference)
        if (
            request.reason is OnlyFeeDifferenceReason.UNKNOWN
            and difference.amount > request.materiality_threshold.amount
        ):
            return self._decision(request, OnlyFeeReconciliationStatus.TRADING_BLOCKED, local, reported, difference)
        reconciliation_id = self._identity(request, local, reported, difference)
        adjustment = OnlyFeeAdjustment(
            only_fee_fingerprint(("adjustment", reconciliation_id)),
            OnlyFeeAdjustmentDirection.SUPPLEMENTAL_CHARGE
            if signed_difference > 0
            else OnlyFeeAdjustmentDirection.REFUND,
            difference,
            evidence.account_id,
            request.cluster_id,
            request.order_id,
            request.trade_id,
            evidence.statement_scope,
            evidence.evidence_id,
            reconciliation_id,
            request.reason,
        )
        return OnlyFeeReconciliationDecision(
            reconciliation_id,
            evidence.evidence_id,
            evidence.scope,
            local,
            request.prior_adjustments,
            current,
            reported,
            difference,
            request.reason,
            OnlyFeeReconciliationStatus.RECONCILED_WITH_ADJUSTMENT,
            adjustment,
        )

    def _local_amount(self, request: OnlyFeeReconciliationInput) -> OnlyMoney | None:
        components = request.local_components
        mode = request.evidence.mode
        if mode is OnlyExternalFeeEvidenceMode.COMMISSION_ONLY:
            components = tuple(item for item in components if item.fee_type is OnlyFeeType.BROKER_COMMISSION)
        if not components:
            return None
        currency = components[0].amount.currency
        if any(item.amount.currency != currency for item in components):
            return None
        amount = sum(
            (
                item.amount.amount if item.direction is OnlyFeeEconomicDirection.CHARGE else -item.amount.amount
                for item in components
            ),
            Decimal(0),
        )
        return OnlyMoney(amount, currency)

    @staticmethod
    def _reported_amount(request: OnlyFeeReconciliationInput) -> OnlyMoney | None:
        evidence = request.evidence
        if evidence.mode is OnlyExternalFeeEvidenceMode.DETAILED:
            if not evidence.reported_components:
                return None
            currency = evidence.reported_components[0].amount.currency
            if any(item.amount.currency != currency for item in evidence.reported_components):
                return None
            return OnlyMoney(sum((item.amount.amount for item in evidence.reported_components), Decimal(0)), currency)
        return evidence.reported_total

    def _decision(
        self,
        request: OnlyFeeReconciliationInput,
        status: OnlyFeeReconciliationStatus,
        local: OnlyMoney | None,
        reported: OnlyMoney | None,
        difference: OnlyMoney | None,
    ) -> OnlyFeeReconciliationDecision:
        current = None if local is None else OnlyMoney(local.amount + request.prior_adjustments.amount, local.currency)
        return OnlyFeeReconciliationDecision(
            self._identity(request, local, reported, difference),
            request.evidence.evidence_id,
            request.evidence.scope,
            local,
            request.prior_adjustments,
            current,
            reported,
            difference,
            request.reason,
            status,
            None,
        )

    @staticmethod
    def _identity(
        request: OnlyFeeReconciliationInput,
        local: OnlyMoney | None,
        reported: OnlyMoney | None,
        difference: OnlyMoney | None,
    ) -> str:
        return only_fee_fingerprint(
            (
                request.evidence.evidence_id,
                None if local is None else local.to_dict(),
                request.prior_adjustments.to_dict(),
                None if reported is None else reported.to_dict(),
                None if difference is None else difference.to_dict(),
                request.reason.value,
                request.evidence_classification,
            )
        )


__all__ = [name for name in globals() if name.startswith("Only")]
