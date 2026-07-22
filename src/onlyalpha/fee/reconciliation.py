"""Immutable broker-fee reconciliation and adjustment creation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.time import only_require_utc
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.models import OnlyFeeAdjustmentInstruction, OnlyFeeInstruction


class OnlyFeeReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    ADJUSTMENT_REQUIRED = "ADJUSTMENT_REQUIRED"
    RECONCILED_WITH_ADJUSTMENT = "RECONCILED_WITH_ADJUSTMENT"
    INCOMPLETE_EXTERNAL_DATA = "INCOMPLETE_EXTERNAL_DATA"
    DUPLICATE_REPORT = "DUPLICATE_REPORT"
    UNEXPLAINED_DIFFERENCE = "UNEXPLAINED_DIFFERENCE"
    TRADING_BLOCKED = "TRADING_BLOCKED"


class OnlyFeeDifferenceReason(StrEnum):
    MINIMUM_COMMISSION = "MINIMUM_COMMISSION"
    ROUNDING = "ROUNDING"
    BROKER_RATE_MISMATCH = "BROKER_RATE_MISMATCH"
    MARKET_SCHEDULE_OUTDATED = "MARKET_SCHEDULE_OUTDATED"
    ALL_IN_REPORT = "ALL_IN_REPORT"
    DEFERRED_FEE = "DEFERRED_FEE"
    REFUND = "REFUND"
    SUPPLEMENTAL_CHARGE = "SUPPLEMENTAL_CHARGE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationResult:
    reconciliation_id: str
    status: OnlyFeeReconciliationStatus
    trade_id: str | None
    account_id: str
    local_amount: OnlyMoney | None
    reported_amount: OnlyMoney | None
    difference: OnlyMoney | None
    reason: OnlyFeeDifferenceReason | None
    adjustment: OnlyFeeAdjustmentInstruction | None = None


class OnlyFeeReconciliationService:
    """Matches one external report to an applied local instruction exactly once."""

    def __init__(self) -> None:
        self._external_references: set[str] = set()

    def reconcile(
        self,
        instruction: OnlyFeeInstruction | None,
        *,
        reported_amount: OnlyMoney | None,
        external_reference: str | None,
        reason: OnlyFeeDifferenceReason,
        created_at: datetime,
        materiality_threshold: OnlyMoney | None = None,
    ) -> OnlyFeeReconciliationResult:
        only_require_utc(created_at, "fee reconciliation created_at")
        key = external_reference or ""
        if key and key in self._external_references:
            return self._result(
                OnlyFeeReconciliationStatus.DUPLICATE_REPORT, instruction, reported_amount, None, reason
            )
        if key:
            self._external_references.add(key)
        if instruction is None or reported_amount is None:
            return self._result(
                OnlyFeeReconciliationStatus.INCOMPLETE_EXTERNAL_DATA, instruction, reported_amount, None, reason
            )
        local = instruction.fee_breakdown.total
        if local.currency != reported_amount.currency:
            return self._result(
                OnlyFeeReconciliationStatus.UNEXPLAINED_DIFFERENCE, instruction, reported_amount, None, reason
            )
        difference = OnlyMoney(reported_amount.amount - local.amount, local.currency)
        if not difference.amount:
            return self._result(OnlyFeeReconciliationStatus.MATCHED, instruction, reported_amount, difference, reason)
        threshold = materiality_threshold or OnlyMoney(Decimal(0), local.currency)
        if abs(difference.amount) > threshold.amount and reason is OnlyFeeDifferenceReason.UNKNOWN:
            return self._result(
                OnlyFeeReconciliationStatus.TRADING_BLOCKED, instruction, reported_amount, difference, reason
            )
        adjustment = OnlyFeeAdjustmentInstruction(
            hashlib.sha256(
                f"fee-adjustment:{instruction.trade_id}:{external_reference}:{reported_amount.amount}".encode()
            ).hexdigest(),
            instruction.trade_id,
            None,
            instruction.account_id,
            instruction.cluster_id,
            local.currency,
            local,
            reported_amount,
            difference,
            reason.value,
            external_reference,
            created_at,
            f"fee-adjustment:{instruction.account_id}:{instruction.trade_id}:{external_reference}",
        )
        return self._result(
            OnlyFeeReconciliationStatus.ADJUSTMENT_REQUIRED,
            instruction,
            reported_amount,
            difference,
            reason,
            adjustment,
        )

    @staticmethod
    def _result(
        status: OnlyFeeReconciliationStatus,
        instruction: OnlyFeeInstruction | None,
        reported: OnlyMoney | None,
        difference: OnlyMoney | None,
        reason: OnlyFeeDifferenceReason | None,
        adjustment: OnlyFeeAdjustmentInstruction | None = None,
    ) -> OnlyFeeReconciliationResult:
        payload = f"{status}:{None if instruction is None else instruction.trade_id}:{None if reported is None else reported.amount}"
        return OnlyFeeReconciliationResult(
            hashlib.sha256(payload.encode()).hexdigest(),
            status,
            None if instruction is None else instruction.trade_id,
            "" if instruction is None else instruction.account_id,
            None if instruction is None else instruction.fee_breakdown.total,
            reported,
            difference,
            reason,
            adjustment,
        )
