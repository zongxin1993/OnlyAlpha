from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.account.enums import OnlyAccountStatus, OnlyAccountType
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.execution.execution_state import OnlyAccountExecutionState
from onlyalpha.execution.projection_targets import (
    OnlyFeeReconciliationAuthorityProjectionTarget,
    OnlyFeeReconciliationRiskGateProjectionTarget,
)
from onlyalpha.fee.adjustment import OnlyFeeDifferenceReason
from onlyalpha.fee.evidence import (
    OnlyExternalFeeEvidence,
    OnlyExternalFeeEvidenceMode,
    OnlyExternalFeeEvidenceScope,
)
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeEconomicDirection, OnlyFeeType
from onlyalpha.fee.reconciliation import (
    OnlyFeeReconciliationInput,
    OnlyFeeReconciliationPlanner,
    OnlyFeeReconciliationStatus,
    OnlyLocalFeeReconciliationComponent,
)
from onlyalpha.fee.reconciliation_authority import (
    OnlyExternalFeeEvidenceState,
    OnlyFeeReconciliationAuthority,
)
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.fee.transaction_planner import (
    OnlyFeeReconciliationPlanningContext,
    OnlyFeeReconciliationTransactionPlanner,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.transaction.applied_projection import (
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyRuntimeProjectionApplyContext,
)
from onlyalpha.transaction.codec import (
    only_decode_prepared_execution_transaction,
    only_encode_prepared_execution_transaction,
)
from onlyalpha.transaction.coordinator import (
    OnlyRuntimeTransactionCoordinationStatus,
    OnlyRuntimeTransactionCoordinator,
)
from onlyalpha.transaction.projection import (
    OnlyProjectionApplyResult,
    OnlyReferenceRuntimeProjectionTarget,
    OnlyRuntimeProjectionComponent,
)
from onlyalpha.transaction.projection_applier import OnlyRuntimeProjectionApplier

pytestmark = pytest.mark.recovery

_CURRENCY = OnlyCurrency("CNY", 2)
_ACCOUNT = OnlyAccountId("account")
_RUNTIME = OnlyRuntimeId("runtime")
_TIME = OnlyTimestamp.from_datetime(datetime(2026, 1, 1, tzinfo=UTC))


def _money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), _CURRENCY)


def _evidence(reported: str, *, version: str = "1") -> OnlyExternalFeeEvidence:
    return OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=OnlyExternalFeeEvidenceScope.STATEMENT,
        mode=OnlyExternalFeeEvidenceMode.ALL_IN,
        external_reference="statement-2026-01-01",
        report_version=version,
        trade_id=None,
        order_id=None,
        statement_scope="2026-01-01",
        reported_total=_money(reported),
        reported_components=(),
        effective_at=_TIME,
        received_at=_TIME,
    )


def _decision(
    reported: str,
    reason: OnlyFeeDifferenceReason = OnlyFeeDifferenceReason.ROUNDING,
    *,
    classification: str | None = None,
):
    evidence = _evidence(reported)
    return evidence, OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            (
                OnlyLocalFeeReconciliationComponent(
                    OnlyFeeType.BROKER_COMMISSION,
                    OnlyFeeAuthority.BROKER,
                    "commission",
                    OnlyFeeEconomicDirection.CHARGE,
                    _money("5.00"),
                ),
            ),
            _money("0.00"),
            None,
            None,
            None,
            reason,
            _money("0.10"),
            classification,
        )
    )


def _account() -> OnlyAccountExecutionState:
    cash = _money("100.00")
    zero = _money("0.00")
    return OnlyAccountExecutionState(
        _RUNTIME,
        _ACCOUNT,
        "gateway",
        OnlyAccountType.CASH,
        _CURRENCY,
        OnlyAccountStatus.ACTIVE,
        cash,
        cash,
        cash,
        zero,
        zero,
        zero,
        zero,
        zero,
        _money("5.00"),
        cash,
        _TIME,
        _TIME,
        _TIME,
        1,
        None,
        (),
        None,
        None,
        None,
        None,
    )


def only_test_fee_reconciliation_transaction(reported: str = "5.23"):
    evidence, decision = _decision(reported)
    return OnlyFeeReconciliationTransactionPlanner().prepare(
        OnlyFeeReconciliationPlanningContext(
            _RUNTIME,
            evidence,
            decision,
            _TIME,
            None,
            None,
            None,
            _account() if decision.adjustment is not None else None,
            None,
            None,
            None,
        )
    )


def test_reconciliation_planner_handles_match_charge_refund_and_material_block() -> None:
    _, matched = _decision("5.00")
    _, charge = _decision("5.23")
    _, refund = _decision("4.80")
    _, blocked = _decision("5.23", OnlyFeeDifferenceReason.UNKNOWN)

    assert matched.status is OnlyFeeReconciliationStatus.MATCHED and matched.adjustment is None
    assert charge.adjustment is not None and charge.adjustment.amount == _money("0.23")
    assert refund.adjustment is not None and refund.adjustment.amount == _money("0.20")
    assert blocked.status is OnlyFeeReconciliationStatus.TRADING_BLOCKED
    assert blocked.adjustment is None


def test_reconciliation_transaction_has_exact_order_and_codec_round_trip() -> None:
    prepared = only_test_fee_reconciliation_transaction()
    assert tuple(item.identity.component for item in prepared.projections) == (
        OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE,
        OnlyRuntimeProjectionComponent.FEE_RECONCILIATION,
        OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER,
        OnlyRuntimeProjectionComponent.ACCOUNT,
        OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE,
        OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE,
    )
    assert only_decode_prepared_execution_transaction(only_encode_prepared_execution_transaction(prepared)) == prepared


def test_conflicting_evidence_is_durable_without_overwriting_identity_authority() -> None:
    accepted = only_test_fee_reconciliation_transaction("5.00")
    conflict_evidence, conflict_decision = _decision("5.01", classification="EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT")
    conflict = OnlyFeeReconciliationTransactionPlanner().prepare(
        OnlyFeeReconciliationPlanningContext(
            _RUNTIME,
            conflict_evidence,
            conflict_decision,
            _TIME,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
        )
    )
    accepted_state = accepted.projections[0].after
    conflict_state = conflict.projections[0].after
    assert isinstance(accepted_state, OnlyExternalFeeEvidenceState)
    assert isinstance(conflict_state, OnlyExternalFeeEvidenceState)
    authority = OnlyFeeReconciliationAuthority()
    authority.restore_evidence(accepted_state)
    authority.restore_evidence(conflict_state)

    assert authority.classify(conflict_evidence) == "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
    restored = OnlyFeeReconciliationAuthority()
    restored.restore_checkpoint(authority.capture_checkpoint())
    assert restored.classify(conflict_evidence) == "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"


def test_real_reconciliation_targets_install_and_checkpoint_all_fee_authorities() -> None:
    prepared = only_test_fee_reconciliation_transaction()
    authority = OnlyFeeReconciliationAuthority()
    risk_gate = OnlyFeeReconciliationRiskGate()
    applied = OnlyInMemoryAppliedRuntimeProjectionLedger()
    targets = {
        component: OnlyFeeReconciliationAuthorityProjectionTarget(component, authority, applied)
        for component in (
            OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE,
            OnlyRuntimeProjectionComponent.FEE_RECONCILIATION,
            OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER,
            OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE,
        )
    }
    account_projection = prepared.projections[3]
    account_target = OnlyReferenceRuntimeProjectionTarget(OnlyRuntimeProjectionComponent.ACCOUNT)
    account_target.seed(
        account_projection.identity.entity_key,
        account_projection.identity.expected_version,
        account_projection.identity.expected_state_hash,
    )
    targets[OnlyRuntimeProjectionComponent.ACCOUNT] = account_target
    targets[OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE] = OnlyFeeReconciliationRiskGateProjectionTarget(
        risk_gate, applied
    )
    store = OnlyInMemoryRuntimePersistenceStore()
    coordinator = OnlyRuntimeTransactionCoordinator(
        commit_port=store,
        query_port=store,
        projection_state_port=store,
        projection_applier=OnlyRuntimeProjectionApplier(targets),
        now=lambda: _TIME,
    )

    result = coordinator.commit(prepared, committed_at=_TIME, projected_at=_TIME)

    assert result.status is OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED
    assert authority.evidence(prepared.fact_draft.evidence.evidence_id) is not None
    assert authority.decision(prepared.fact_draft.decision.reconciliation_id) is not None
    assert prepared.fact_draft.decision.adjustment is not None
    assert authority.adjustment(prepared.fact_draft.decision.adjustment.adjustment_id) is not None
    assert authority.unallocated(_ACCOUNT) is not None
    restored = OnlyFeeReconciliationAuthority()
    restored.restore_checkpoint(authority.capture_checkpoint())
    assert restored.capture_checkpoint() == authority.capture_checkpoint()


class _FailOnceTarget:
    def __init__(self, target: OnlyReferenceRuntimeProjectionTarget) -> None:
        self._target = target
        self._failed = False

    @property
    def component(self) -> OnlyRuntimeProjectionComponent:
        return self._target.component

    def apply_execution_projection(self, context: OnlyRuntimeProjectionApplyContext) -> OnlyProjectionApplyResult:
        if not self._failed:
            self._failed = True
            raise RuntimeError("injected reconciliation projection failure")
        return self._target.apply_execution_projection(context)


@pytest.mark.parametrize("failure_index", range(6))
def test_reconciliation_forward_recovers_after_each_projection_failure(failure_index: int) -> None:
    prepared = only_test_fee_reconciliation_transaction()
    targets = {}
    for index, projection in enumerate(prepared.projections):
        target = OnlyReferenceRuntimeProjectionTarget(projection.identity.component)
        if projection.identity.expected_version:
            target.seed(
                projection.identity.entity_key,
                projection.identity.expected_version,
                projection.identity.expected_state_hash,
            )
        targets[projection.identity.component] = _FailOnceTarget(target) if index == failure_index else target
    store = OnlyInMemoryRuntimePersistenceStore()
    coordinator = OnlyRuntimeTransactionCoordinator(
        commit_port=store,
        query_port=store,
        projection_state_port=store,
        projection_applier=OnlyRuntimeProjectionApplier(targets),
        now=lambda: _TIME,
    )

    failed = coordinator.commit(prepared, committed_at=_TIME, projected_at=_TIME)
    recovered = coordinator.recover_unprojected(_RUNTIME)

    assert failed.status is OnlyRuntimeTransactionCoordinationStatus.PROJECTION_FAILED
    assert recovered[-1].status is OnlyRuntimeTransactionCoordinationStatus.COMMITTED_AND_PROJECTED
    assert recovered[-1].transaction is not None and recovered[-1].transaction.projection_ready
