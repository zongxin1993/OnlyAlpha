from onlyalpha.execution import (
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyRuntimeProjectionApplier,
    OnlyRuntimeProjectionBatchStatus,
)
from tests.execution.support.manager_authority_digest import only_test_runtime_authority_digest
from tests.execution.targets.support import only_test_projection_target_bundle


def test_all_thirteen_targets_rebuild_a_lost_applied_projection_ledger() -> None:
    bundle = only_test_projection_target_bundle()
    assert bundle.apply_all().status is OnlyRuntimeProjectionBatchStatus.COMPLETED
    before = only_test_runtime_authority_digest(bundle.environment)
    ledger = OnlyInMemoryAppliedRuntimeProjectionLedger()
    recovered = OnlyRuntimeProjectionApplier(bundle.create_targets(ledger)).apply(bundle.transaction)
    assert recovered.status is OnlyRuntimeProjectionBatchStatus.COMPLETED
    assert len(recovered.recovered) == 13
    assert not recovered.applied
    assert not recovered.idempotent
    assert len(ledger.records()) == 13
    assert only_test_runtime_authority_digest(bundle.environment) == before
