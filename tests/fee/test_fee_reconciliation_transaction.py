from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from onlyalpha.account.enums import OnlyAccountStatus, OnlyAccountType
from onlyalpha.domain.identifiers import OnlyAccountId, OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.execution.execution_state import OnlyAccountExecutionState
from onlyalpha.fee.evidence import (
    OnlyExternalFeeEvidence,
    OnlyExternalFeeEvidenceMode,
    OnlyFeeReconciliationComponentIdentity,
)
from onlyalpha.fee.evidence_scope import OnlyExternalFeeEvidenceScope, OnlyFeeStatementScope
from onlyalpha.fee.models import OnlyFeeAuthority, OnlyFeeEconomicDirection, OnlyFeeType
from onlyalpha.fee.reconciliation import (
    OnlyFeeReconciliationInput,
    OnlyFeeReconciliationPlanner,
    OnlyFeeReconciliationStatus,
    OnlyLocalFeeReconciliationComponent,
    OnlyPriorFeeAdjustment,
)
from onlyalpha.fee.reconciliation_policy import only_standard_fee_reconciliation_policy
from onlyalpha.fee.transaction_planner import (
    OnlyFeeReconciliationPlanningContext,
    OnlyFeeReconciliationTransactionPlanner,
)
from onlyalpha.runtime.persistence.store import OnlyInMemoryRuntimePersistenceStore
from onlyalpha.transaction.applied_projection import OnlyRuntimeProjectionApplyContext
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
_END = OnlyTimestamp.from_datetime(datetime(2026, 1, 2, tzinfo=UTC))


def _money(value: str) -> OnlyMoney:
    return OnlyMoney(Decimal(value), _CURRENCY)


def _component() -> OnlyFeeReconciliationComponentIdentity:
    return OnlyFeeReconciliationComponentIdentity(
        OnlyFeeType.BROKER_COMMISSION,
        OnlyFeeAuthority.BROKER,
        OnlyFeeEconomicDirection.CHARGE,
        "COMMISSION",
    )


def _evidence(
    reported: str,
    *,
    sequence: int = 1,
    supersedes: str | None = None,
    reference: str = "statement-1",
) -> OnlyExternalFeeEvidence:
    statement = OnlyFeeStatementScope.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        period_start=_TIME,
        period_end=_END,
        currency=_CURRENCY,
        statement_id="statement-1",
    )
    return OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=OnlyExternalFeeEvidenceScope.statement_period(statement),
        mode=OnlyExternalFeeEvidenceMode.COMMISSION_ONLY,
        external_reference=reference,
        report_version=str(sequence),
        revision_sequence=sequence,
        supersedes_evidence_id=supersedes,
        reported_total=_money(reported),
        reported_components=(),
        effective_at=_TIME,
        received_at=_TIME,
    )


def _decision(
    reported: str,
    *,
    sequence: int = 1,
    supersedes: str | None = None,
    reference: str = "statement-1",
):
    evidence = _evidence(reported, sequence=sequence, supersedes=supersedes, reference=reference)
    decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            evidence,
            (OnlyLocalFeeReconciliationComponent(_component(), _money("5.00")),),
            (),
            None,
            only_standard_fee_reconciliation_policy(_CURRENCY),
        )
    )
    return evidence, decision


def _account() -> OnlyAccountExecutionState:
    cash, zero = _money("100.00"), _money("0.00")
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
            tuple(None for _ in decision.adjustments),
            _account() if decision.adjustments else None,
            None,
            None,
            None,
        )
    )


def test_reconciliation_planner_handles_match_charge_and_refund() -> None:
    _, matched = _decision("5.00")
    _, charge = _decision("5.23")
    _, refund = _decision("4.80")
    assert matched.status is OnlyFeeReconciliationStatus.MATCHED and not matched.adjustments
    assert charge.adjustments[0].amount == _money("0.23")
    assert refund.adjustments[0].amount == _money("0.20")


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


class _FailOnceTarget:
    def __init__(self, target: OnlyReferenceRuntimeProjectionTarget) -> None:
        self._target, self._failed = target, False

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


def _revision_transactions():
    statement = OnlyFeeStatementScope.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        period_start=_TIME,
        period_end=_END,
        currency=_CURRENCY,
        statement_id="revision-statement",
    )
    scope = OnlyExternalFeeEvidenceScope.statement_period(statement)
    first = OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=scope,
        mode=OnlyExternalFeeEvidenceMode.ALL_IN,
        external_reference="revision-statement",
        report_version="1",
        revision_sequence=1,
        supersedes_evidence_id=None,
        reported_total=_money("10.00"),
        reported_components=(),
        effective_at=_TIME,
        received_at=_TIME,
    )
    policy = only_standard_fee_reconciliation_policy(_CURRENCY)
    local = (OnlyLocalFeeReconciliationComponent(_component(), _money("5.00")),)
    first_decision = OnlyFeeReconciliationPlanner().plan(OnlyFeeReconciliationInput(first, local, (), None, policy))
    first_prepared = OnlyFeeReconciliationTransactionPlanner().prepare(
        OnlyFeeReconciliationPlanningContext(
            _RUNTIME,
            first,
            first_decision,
            _TIME,
            None,
            None,
            (None,),
            _account(),
            None,
            None,
            None,
        )
    )
    first_adjustment = first_decision.adjustments[0]
    gate = first_prepared.projections[-1].after
    second = OnlyExternalFeeEvidence.create(
        broker_id="broker",
        account_id=_ACCOUNT,
        scope=scope,
        mode=OnlyExternalFeeEvidenceMode.ALL_IN,
        external_reference="revision-statement",
        report_version="2",
        revision_sequence=2,
        supersedes_evidence_id=first.evidence_id,
        reported_total=_money("7.00"),
        reported_components=(),
        effective_at=_TIME,
        received_at=_TIME,
    )
    second_decision = OnlyFeeReconciliationPlanner().plan(
        OnlyFeeReconciliationInput(
            second,
            local,
            (
                OnlyPriorFeeAdjustment(
                    first_adjustment.adjustment_id,
                    first_adjustment.component_identity,
                    _money("5.00"),
                ),
            ),
            None,
            policy,
            superseded_blocker_id=gate.active_blockers[0].blocker_id,
        )
    )
    account_after = next(
        item.after
        for item in first_prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.ACCOUNT
    )
    unallocated_after = next(
        item.after
        for item in first_prepared.projections
        if item.identity.component is OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE
    )
    second_prepared = OnlyFeeReconciliationTransactionPlanner().prepare(
        OnlyFeeReconciliationPlanningContext(
            _RUNTIME,
            second,
            second_decision,
            _TIME,
            None,
            None,
            (None,),
            account_after,
            None,
            unallocated_after,
            gate,
        )
    )
    return first_prepared, second_prepared


@pytest.mark.parametrize("failure_index", range(6))
def test_revision_forward_correction_recovers_exactly_once_and_resolves_own_blocker(
    failure_index: int,
) -> None:
    first, prepared = _revision_transactions()
    assert first.fact_draft.decision.adjustments[0].amount == _money("5.00")
    assert prepared.fact_draft.decision.adjustments[0].amount == _money("3.00")
    assert prepared.fact_draft.decision.adjustments[0].direction.value == "REFUND"
    assert not prepared.projections[-1].after.blocked
    account = next(
        item.after for item in prepared.projections if item.identity.component is OnlyRuntimeProjectionComponent.ACCOUNT
    )
    assert account.ledger_cash == _money("98.00")

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
