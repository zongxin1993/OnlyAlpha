from dataclasses import replace

from onlyalpha.fee.reconciliation import OnlyFeeReconciliationStatus
from onlyalpha.fee.risk_gate import OnlyFeeReconciliationRiskGate
from onlyalpha.fee.transaction_planner import (
    OnlyFeeReconciliationPlanningContext,
    OnlyFeeReconciliationTransactionPlanner,
)
from tests.fee.test_fee_reconciliation_transaction import _RUNTIME, _TIME, _decision


def _gate_after(decision, evidence, before=None):
    prepared = OnlyFeeReconciliationTransactionPlanner().prepare(
        OnlyFeeReconciliationPlanningContext(
            _RUNTIME, evidence, decision, _TIME, None, None, (), None, None, None, before
        )
    )
    return prepared.projections[-1].after


def test_unrelated_match_does_not_clear_blocker_and_lineage_revision_does() -> None:
    evidence_a, base = _decision("5.23")
    blocked = replace(base, status=OnlyFeeReconciliationStatus.TRADING_BLOCKED, adjustments=())
    gate_a = _gate_after(blocked, evidence_a)
    assert gate_a.blocked and len(gate_a.active_blockers) == 1

    evidence_b, matched_b = _decision("5.00", reference="independent")
    gate_b = _gate_after(matched_b, evidence_b, gate_a)
    assert gate_b.blocked and gate_b.active_blockers == gate_a.active_blockers

    revision, matched_a = _decision("5.00", sequence=2, supersedes=evidence_a.evidence_id)
    matched_a = replace(
        matched_a,
        evidence_family_fingerprint=evidence_a.family_identity.fingerprint,
        resolves_blocker_id=gate_a.active_blockers[0].blocker_id,
    )
    gate_resolved = _gate_after(matched_a, revision, gate_b)
    assert not gate_resolved.blocked


def test_multiple_blockers_resolve_one_lineage_at_a_time() -> None:
    evidence_a, decision_a = _decision("5.23")
    blocked_a = replace(decision_a, status=OnlyFeeReconciliationStatus.TRADING_BLOCKED, adjustments=())
    gate_a = _gate_after(blocked_a, evidence_a)
    evidence_b, decision_b = _decision("5.24", reference="family-b")
    blocked_b = replace(decision_b, status=OnlyFeeReconciliationStatus.TRADING_BLOCKED, adjustments=())
    gate_ab = _gate_after(blocked_b, evidence_b, gate_a)
    assert len(gate_ab.active_blockers) == 2
    authority = OnlyFeeReconciliationRiskGate()
    authority.restore(gate_ab)
    restored = OnlyFeeReconciliationRiskGate()
    restored.restore_checkpoint(authority.capture_checkpoint())
    gate_ab = restored.get(evidence_a.account_id)
    assert gate_ab is not None

    revision_a, resolved_a = _decision("5.00", sequence=2, supersedes=evidence_a.evidence_id)
    resolved_a = replace(resolved_a, resolves_blocker_id=gate_a.active_blockers[0].blocker_id)
    gate_b = _gate_after(resolved_a, revision_a, gate_ab)
    assert gate_b.blocked and len(gate_b.active_blockers) == 1
    assert gate_b.active_blockers[0].evidence_family_fingerprint == evidence_b.family_identity.fingerprint
