from onlyalpha.fee.reconciliation_authority import OnlyExternalFeeEvidenceState, OnlyFeeReconciliationAuthority
from tests.fee.test_fee_reconciliation_transaction import _evidence


def test_evidence_family_duplicate_conflict_and_revision_lineage() -> None:
    authority = OnlyFeeReconciliationAuthority()
    first = _evidence("5.00")
    authority.restore_evidence(OnlyExternalFeeEvidenceState(first, True, 1))
    assert authority.classify(first) == "DUPLICATE_EVIDENCE"
    conflict = _evidence("5.01")
    assert authority.classify(conflict) == "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
    revision = _evidence("5.10", sequence=2, supersedes=first.evidence_id)
    assert authority.classify(revision) is None
    authority.restore_evidence(OnlyExternalFeeEvidenceState(revision, True, 1))
    assert authority.classify(revision) == "DUPLICATE_EVIDENCE"
    wrong_predecessor = _evidence("5.20", sequence=3, supersedes=first.evidence_id)
    assert authority.classify(wrong_predecessor) == "EXTERNAL_FEE_EVIDENCE_IDENTITY_CONFLICT"
    restored = OnlyFeeReconciliationAuthority()
    restored.restore_checkpoint(authority.capture_checkpoint())
    assert restored.capture_checkpoint() == authority.capture_checkpoint()
