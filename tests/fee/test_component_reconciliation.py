from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.identifiers import OnlyAccountId, OnlyTradeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee.evidence import (
    OnlyExternalFeeComponent,
    OnlyExternalFeeEvidence,
    OnlyExternalFeeEvidenceMode,
    OnlyFeeReconciliationComponentIdentity,
)
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeEconomicDirection, OnlyFeeType
from onlyalpha.fee.reconciliation import (
    OnlyFeeComponentReconciliationStatus,
    OnlyFeeReconciliationInput,
    OnlyFeeReconciliationPlanner,
    OnlyFeeReconciliationStatus,
    OnlyLocalFeeReconciliationComponent,
    OnlyPriorFeeAdjustment,
)
from onlyalpha.fee.reconciliation_policy import only_standard_fee_reconciliation_policy

_CURRENCY = OnlyCurrency("CNY", 2)
_ACCOUNT = OnlyAccountId("account")
_TIME = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))


def _money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), _CURRENCY)


def _identity(fee_type: OnlyFeeType, source: str) -> OnlyFeeReconciliationComponentIdentity:
    return OnlyFeeReconciliationComponentIdentity(
        fee_type, OnlyFeeAuthority.BROKER, OnlyFeeEconomicDirection.CHARGE, source
    )


def _evidence(components: tuple[OnlyExternalFeeComponent, ...], total: str) -> OnlyExternalFeeEvidence:
    return OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=OnlyExternalFeeEvidenceScope.trade(OnlyTradeId("trade")),
        mode=OnlyExternalFeeEvidenceMode.DETAILED,
        external_reference="trade-fees",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=_money(total),
        reported_components=components,
        effective_at=_TIME,
        received_at=_TIME,
    )


def test_same_total_different_components_is_not_a_match_and_is_component_attributed() -> None:
    commission = _identity(OnlyFeeType.BROKER_COMMISSION, "commission")
    transfer = _identity(OnlyFeeType.TRANSFER_FEE, "transfer")
    evidence = _evidence(
        (
            OnlyExternalFeeComponent.create(commission, _money("4.00")),
            OnlyExternalFeeComponent.create(transfer, _money("2.00")),
        ),
        "6.00",
    )
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            (
                OnlyLocalFeeReconciliationComponent(commission, _money("5.00")),
                OnlyLocalFeeReconciliationComponent(transfer, _money("1.00")),
            ),
            (),
            None,
            only_standard_fee_reconciliation_policy(_CURRENCY),
        )
    )
    assert decision.status is OnlyFeeReconciliationStatus.RECONCILED_WITH_ADJUSTMENT
    assert len(decision.adjustments) == 2
    assert decision.aggregate_difference == _money("0.00")
    assert {row.status for row in decision.component_reconciliations} == {
        OnlyFeeComponentReconciliationStatus.DIFFERENT
    }
    reversed_evidence = _evidence(
        (
            OnlyExternalFeeComponent.create(transfer, _money("2.00")),
            OnlyExternalFeeComponent.create(commission, _money("4.00")),
        ),
        "6.00",
    )
    assert reversed_evidence.content_fingerprint == evidence.content_fingerprint


def test_missing_component_is_incomplete_and_external_total_conflict_fails_closed() -> None:
    commission = _identity(OnlyFeeType.BROKER_COMMISSION, "commission")
    evidence = _evidence((OnlyExternalFeeComponent.create(commission, _money("4.00")),), "4.00")
    transfer = _identity(OnlyFeeType.TRANSFER_FEE, "transfer")
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            (
                OnlyLocalFeeReconciliationComponent(commission, _money("4.00")),
                OnlyLocalFeeReconciliationComponent(transfer, _money("1.00")),
            ),
            (),
            None,
            only_standard_fee_reconciliation_policy(_CURRENCY),
        )
    )
    assert decision.status is OnlyFeeReconciliationStatus.TRADING_BLOCKED
    with pytest.raises(ValueError, match="INTERNAL_CONFLICT"):
        _evidence((OnlyExternalFeeComponent.create(commission, _money("4.00")),), "5.00")


def test_revision_uses_component_prior_adjustment_for_forward_correction() -> None:
    commission = _identity(OnlyFeeType.BROKER_COMMISSION, "commission")
    evidence = _evidence((OnlyExternalFeeComponent.create(commission, _money("5.50")),), "5.50")
    prior = OnlyPriorFeeAdjustment("adjustment-v1", commission, _money("1.00"))
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            (OnlyLocalFeeReconciliationComponent(commission, _money("5.00")),),
            (prior,),
            None,
            only_standard_fee_reconciliation_policy(_CURRENCY),
        )
    )
    assert decision.adjustments[0].amount == _money("0.50")
    assert decision.adjustments[0].direction.value == "REFUND"


def test_material_all_in_variance_adjusts_forward_and_blocks_risk_increase() -> None:
    evidence = OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=OnlyExternalFeeEvidenceScope.trade(OnlyTradeId("all-in-trade")),
        mode=OnlyExternalFeeEvidenceMode.ALL_IN,
        external_reference="all-in",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=_money("6.00"),
        reported_components=(),
        effective_at=_TIME,
        received_at=_TIME,
    )
    local = _identity(OnlyFeeType.BROKER_COMMISSION, "commission")
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            (OnlyLocalFeeReconciliationComponent(local, _money("5.00")),),
            (),
            None,
            only_standard_fee_reconciliation_policy(_CURRENCY),
        )
    )
    assert decision.status is OnlyFeeReconciliationStatus.TRADING_BLOCKED
    assert decision.adjustments[0].amount == _money("1.00")
