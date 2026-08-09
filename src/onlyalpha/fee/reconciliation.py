"""Pure component-by-component fee reconciliation planner."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.base import OnlyDomainModel
from onlyalpha.domain.identifiers import OnlyClusterId
from onlyalpha.domain.value import OnlyMoney
from onlyalpha.fee.adjustment import OnlyFeeAdjustment, OnlyFeeAdjustmentDirection, OnlyFeeDifferenceReason
from onlyalpha.fee.evidence import (
    OnlyExternalFeeEvidence,
    OnlyExternalFeeEvidenceMode,
    OnlyFeeReconciliationComponentIdentity,
)
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeEconomicDirection, OnlyFeeType, only_fee_fingerprint
from onlyalpha.fee.reconciliation_policy import (
    OnlyFeeReconciliationAction,
    OnlyFeeReconciliationPolicy,
    OnlyFeeReconciliationPolicyIdentity,
)


class OnlyFeeReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    RECONCILED_WITH_ADJUSTMENT = "RECONCILED_WITH_ADJUSTMENT"
    INCOMPLETE_EXTERNAL_DATA = "INCOMPLETE_EXTERNAL_DATA"
    EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
    TRADING_BLOCKED = "TRADING_BLOCKED"


class OnlyFeeComponentReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    DIFFERENT = "DIFFERENT"
    MISSING_EXTERNAL = "MISSING_EXTERNAL"
    MISSING_LOCAL = "MISSING_LOCAL"


@dataclass(frozen=True, slots=True)
class OnlyLocalFeeReconciliationComponent(OnlyDomainModel):
    component_identity: OnlyFeeReconciliationComponentIdentity
    amount: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyPriorFeeAdjustment(OnlyDomainModel):
    adjustment_id: str
    component_identity: OnlyFeeReconciliationComponentIdentity
    signed_amount: OnlyMoney


@dataclass(frozen=True, slots=True)
class OnlyFeeComponentReconciliation(OnlyDomainModel):
    component_identity: OnlyFeeReconciliationComponentIdentity
    local_amount: OnlyMoney | None
    reported_amount: OnlyMoney | None
    prior_adjustment: OnlyMoney
    effective_local_amount: OnlyMoney
    difference: OnlyMoney
    status: OnlyFeeComponentReconciliationStatus
    fingerprint: str


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationInput:
    evidence: OnlyExternalFeeEvidence
    local_components: tuple[OnlyLocalFeeReconciliationComponent, ...]
    prior_adjustments: tuple[OnlyPriorFeeAdjustment, ...]
    cluster_id: OnlyClusterId | None
    policy: OnlyFeeReconciliationPolicy
    evidence_classification: str | None = None
    superseded_blocker_id: str | None = None


@dataclass(frozen=True, slots=True)
class OnlyFeeReconciliationDecision(OnlyDomainModel):
    schema_version = 2

    reconciliation_id: str
    evidence_id: str
    evidence_family_fingerprint: str
    scope_fingerprint: str
    supersedes_evidence_id: str | None
    local_facts_fingerprint: str
    prior_adjustments_fingerprint: str
    policy_identity: OnlyFeeReconciliationPolicyIdentity
    component_reconciliations: tuple[OnlyFeeComponentReconciliation, ...]
    aggregate_local: OnlyMoney
    aggregate_reported: OnlyMoney
    aggregate_prior_adjustment: OnlyMoney
    aggregate_difference: OnlyMoney
    reason: OnlyFeeDifferenceReason | None
    status: OnlyFeeReconciliationStatus
    adjustments: tuple[OnlyFeeAdjustment, ...]
    resolves_blocker_id: str | None


class OnlyFeeReconciliationPlanner:
    def plan(self, request: OnlyFeeReconciliationInput) -> OnlyFeeReconciliationDecision:
        evidence = request.evidence
        if evidence.currency != request.policy.currency:
            raise ValueError("FEE_RECONCILIATION_POLICY_CURRENCY_MISMATCH")
        if request.evidence_classification == "DUPLICATE_EVIDENCE":
            raise ValueError("DUPLICATE_EVIDENCE")
        if request.evidence_classification is not None:
            return self._build(request, (), OnlyFeeReconciliationStatus.EVIDENCE_CONFLICT, None, ())

        local = self._aggregate_local(request.local_components, evidence)
        reported = self._aggregate_reported(evidence, local)
        prior = self._aggregate_prior(request.prior_adjustments)
        identities = sorted(set(local) | set(reported) | set(prior), key=lambda item: item.sort_key)
        rows = tuple(
            self._row(identity, local.get(identity), reported.get(identity), prior.get(identity), evidence)
            for identity in identities
        )
        incomplete = any(
            row.status
            in {
                OnlyFeeComponentReconciliationStatus.MISSING_EXTERNAL,
                OnlyFeeComponentReconciliationStatus.MISSING_LOCAL,
            }
            for row in rows
        )
        nonzero = tuple(row for row in rows if row.difference.amount != 0)
        material = any(abs(row.difference.amount) > request.policy.materiality_threshold.amount for row in rows)
        action = (
            request.policy.incomplete_evidence_action
            if incomplete
            else request.policy.unknown_difference_action
            if evidence.mode
            in {
                OnlyExternalFeeEvidenceMode.ALL_IN,
                OnlyExternalFeeEvidenceMode.DEFERRED_STATEMENT,
            }
            and evidence.revision_sequence == 1
            else request.policy.component_mismatch_action
        )
        should_block = material and action is OnlyFeeReconciliationAction.BLOCK
        if should_block:
            reason = (
                OnlyFeeDifferenceReason.INCOMPLETE_EVIDENCE
                if incomplete
                else OnlyFeeDifferenceReason.UNKNOWN_COMPONENT
                if evidence.mode
                in {
                    OnlyExternalFeeEvidenceMode.ALL_IN,
                    OnlyExternalFeeEvidenceMode.DEFERRED_STATEMENT,
                }
                and evidence.revision_sequence == 1
                else OnlyFeeDifferenceReason.COMPONENT_MISMATCH
            )
            if incomplete:
                return self._build(
                    request,
                    rows,
                    OnlyFeeReconciliationStatus.TRADING_BLOCKED,
                    reason,
                    (),
                )
            draft = self._build(
                request,
                rows,
                OnlyFeeReconciliationStatus.TRADING_BLOCKED,
                reason,
                (),
            )
            adjustments = tuple(self._adjustment(request, draft.reconciliation_id, row) for row in nonzero)
            return self._build(
                request,
                rows,
                OnlyFeeReconciliationStatus.TRADING_BLOCKED,
                reason,
                adjustments,
            )
        if incomplete and action is OnlyFeeReconciliationAction.BLOCK:
            return self._build(
                request,
                rows,
                OnlyFeeReconciliationStatus.INCOMPLETE_EXTERNAL_DATA,
                OnlyFeeDifferenceReason.INCOMPLETE_EVIDENCE,
                (),
            )
        if not nonzero:
            return self._build(request, rows, OnlyFeeReconciliationStatus.MATCHED, None, ())
        draft = self._build(
            request,
            rows,
            OnlyFeeReconciliationStatus.RECONCILED_WITH_ADJUSTMENT,
            OnlyFeeDifferenceReason.REPORTED_VARIANCE,
            (),
        )
        adjustments = tuple(self._adjustment(request, draft.reconciliation_id, row) for row in nonzero)
        return self._build(
            request,
            rows,
            OnlyFeeReconciliationStatus.RECONCILED_WITH_ADJUSTMENT,
            OnlyFeeDifferenceReason.REPORTED_VARIANCE,
            adjustments,
        )

    @staticmethod
    def _aggregate_local(
        components: tuple[OnlyLocalFeeReconciliationComponent, ...], evidence: OnlyExternalFeeEvidence
    ) -> dict[OnlyFeeReconciliationComponentIdentity, OnlyMoney]:
        selected = components
        if evidence.mode is OnlyExternalFeeEvidenceMode.COMMISSION_ONLY:
            selected = tuple(
                item for item in components if item.component_identity.fee_type is OnlyFeeType.BROKER_COMMISSION
            )
        if evidence.mode is not OnlyExternalFeeEvidenceMode.DETAILED:
            identity = OnlyFeeReconciliationComponentIdentity(
                OnlyFeeType.BROKER_COMMISSION
                if evidence.mode is OnlyExternalFeeEvidenceMode.COMMISSION_ONLY
                else OnlyFeeType.PLATFORM_FEE,
                OnlyFeeAuthority.BROKER,
                OnlyFeeEconomicDirection.CHARGE,
                "COMMISSION" if evidence.mode is OnlyExternalFeeEvidenceMode.COMMISSION_ONLY else "ALL_IN",
            )
            if not selected:
                return {}
            currency = selected[0].amount.currency
            signed = sum(
                (
                    item.amount.amount
                    if item.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    else -item.amount.amount
                    for item in selected
                ),
                Decimal(0),
            )
            return {identity: OnlyMoney(signed, currency)}
        result: dict[OnlyFeeReconciliationComponentIdentity, OnlyMoney] = {}
        for item in selected:
            prior = result.get(item.component_identity)
            result[item.component_identity] = item.amount if prior is None else prior + item.amount
        return result

    @staticmethod
    def _aggregate_reported(
        evidence: OnlyExternalFeeEvidence,
        local: dict[OnlyFeeReconciliationComponentIdentity, OnlyMoney],
    ) -> dict[OnlyFeeReconciliationComponentIdentity, OnlyMoney]:
        if evidence.mode is OnlyExternalFeeEvidenceMode.DETAILED:
            return {item.component_identity: item.amount for item in evidence.reported_components}
        identity = next(iter(local), None)
        if identity is None:
            identity = OnlyFeeReconciliationComponentIdentity(
                OnlyFeeType.BROKER_COMMISSION
                if evidence.mode is OnlyExternalFeeEvidenceMode.COMMISSION_ONLY
                else OnlyFeeType.PLATFORM_FEE,
                OnlyFeeAuthority.BROKER,
                OnlyFeeEconomicDirection.CHARGE,
                "COMMISSION" if evidence.mode is OnlyExternalFeeEvidenceMode.COMMISSION_ONLY else "ALL_IN",
            )
        assert evidence.reported_total is not None
        return {identity: evidence.reported_total}

    @staticmethod
    def _aggregate_prior(
        values: tuple[OnlyPriorFeeAdjustment, ...],
    ) -> dict[OnlyFeeReconciliationComponentIdentity, OnlyMoney]:
        result: dict[OnlyFeeReconciliationComponentIdentity, OnlyMoney] = {}
        for item in values:
            prior = result.get(item.component_identity)
            result[item.component_identity] = item.signed_amount if prior is None else prior + item.signed_amount
        return result

    @staticmethod
    def _row(
        identity: OnlyFeeReconciliationComponentIdentity,
        local: OnlyMoney | None,
        reported: OnlyMoney | None,
        prior: OnlyMoney | None,
        evidence: OnlyExternalFeeEvidence,
    ) -> OnlyFeeComponentReconciliation:
        zero = OnlyMoney(Decimal(0), evidence.currency)
        prior = zero if prior is None else prior
        effective = (zero if local is None else local) + prior
        reported_value = zero if reported is None else reported
        difference = reported_value - effective
        status = (
            OnlyFeeComponentReconciliationStatus.MISSING_LOCAL
            if local is None
            else OnlyFeeComponentReconciliationStatus.MISSING_EXTERNAL
            if reported is None
            else OnlyFeeComponentReconciliationStatus.MATCHED
            if difference.amount == 0
            else OnlyFeeComponentReconciliationStatus.DIFFERENT
        )
        payload = (
            identity.to_dict(),
            None if local is None else local.to_dict(),
            None if reported is None else reported.to_dict(),
            prior.to_dict(),
            effective.to_dict(),
            difference.to_dict(),
            status.value,
        )
        return OnlyFeeComponentReconciliation(
            identity, local, reported, prior, effective, difference, status, only_fee_fingerprint(payload)
        )

    def _build(
        self,
        request: OnlyFeeReconciliationInput,
        rows: tuple[OnlyFeeComponentReconciliation, ...],
        status: OnlyFeeReconciliationStatus,
        reason: OnlyFeeDifferenceReason | None,
        adjustments: tuple[OnlyFeeAdjustment, ...],
    ) -> OnlyFeeReconciliationDecision:
        currency = request.policy.currency
        zero = OnlyMoney(Decimal(0), currency)
        aggregate_local = OnlyMoney(
            sum(
                (
                    row.local_amount.amount
                    if row.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    else -row.local_amount.amount
                    for row in rows
                    if row.local_amount is not None
                ),
                Decimal(0),
            ),
            currency,
        )
        aggregate_reported = OnlyMoney(
            sum(
                (
                    row.reported_amount.amount
                    if row.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    else -row.reported_amount.amount
                    for row in rows
                    if row.reported_amount is not None
                ),
                Decimal(0),
            ),
            currency,
        )
        aggregate_prior = OnlyMoney(
            sum(
                (
                    row.prior_adjustment.amount
                    if row.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    else -row.prior_adjustment.amount
                    for row in rows
                ),
                Decimal(0),
            ),
            currency,
        )
        aggregate_difference = OnlyMoney(
            sum(
                (
                    row.difference.amount
                    if row.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                    else -row.difference.amount
                    for row in rows
                ),
                Decimal(0),
            ),
            currency,
        )

        local_fp = only_fee_fingerprint(
            tuple(
                (item.component_identity.to_dict(), item.amount.to_dict())
                for item in sorted(request.local_components, key=lambda x: x.component_identity.sort_key)
            )
        )
        prior_fp = only_fee_fingerprint(
            tuple(
                (item.adjustment_id, item.component_identity.to_dict(), item.signed_amount.to_dict())
                for item in sorted(request.prior_adjustments, key=lambda x: x.adjustment_id)
            )
        )
        core = (
            request.evidence.evidence_id,
            local_fp,
            prior_fp,
            request.policy.identity.to_dict(),
            tuple(row.to_dict() for row in rows),
            status.value,
            None if reason is None else reason.value,
        )
        reconciliation_id = only_fee_fingerprint(core)
        return OnlyFeeReconciliationDecision(
            reconciliation_id,
            request.evidence.evidence_id,
            request.evidence.family_identity.fingerprint,
            request.evidence.scope.fingerprint,
            request.evidence.supersedes_evidence_id,
            local_fp,
            prior_fp,
            request.policy.identity,
            rows,
            aggregate_local if rows else zero,
            aggregate_reported if rows else zero,
            aggregate_prior if rows else zero,
            aggregate_difference if rows else zero,
            reason,
            status,
            adjustments,
            request.superseded_blocker_id
            if status in {OnlyFeeReconciliationStatus.MATCHED, OnlyFeeReconciliationStatus.RECONCILED_WITH_ADJUSTMENT}
            else None,
        )

    @staticmethod
    def _adjustment(
        request: OnlyFeeReconciliationInput,
        reconciliation_id: str,
        row: OnlyFeeComponentReconciliation,
    ) -> OnlyFeeAdjustment:
        difference = row.difference
        amount = OnlyMoney(abs(difference.amount), difference.currency)
        scope = request.evidence.scope
        return OnlyFeeAdjustment(
            only_fee_fingerprint(("adjustment", reconciliation_id, row.component_identity.to_dict())),
            row.component_identity,
            (
                OnlyFeeAdjustmentDirection.SUPPLEMENTAL_CHARGE
                if row.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                else OnlyFeeAdjustmentDirection.REFUND
            )
            if difference.amount > 0
            else (
                OnlyFeeAdjustmentDirection.REFUND
                if row.component_identity.economic_direction is OnlyFeeEconomicDirection.CHARGE
                else OnlyFeeAdjustmentDirection.SUPPLEMENTAL_CHARGE
            ),
            amount,
            request.evidence.account_id,
            request.cluster_id,
            scope.order_id,
            scope.trade_id,
            scope,
            request.evidence.evidence_id,
            reconciliation_id,
            request.policy.identity,
            OnlyFeeDifferenceReason.REPORTED_VARIANCE,
        )


__all__ = [name for name in globals() if name.startswith("Only")]
