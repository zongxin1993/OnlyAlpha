from tests.execution.support.manager_authority_digest import _stable, only_test_runtime_authority_digest
from tests.execution.targets.support import only_test_assert_all_apply, only_test_projection_target_bundle


def test_projection_targets_do_not_publish_or_write_non_projection_authorities() -> None:
    bundle = only_test_projection_target_bundle()
    runtime = bundle.environment.runtime
    before = only_test_runtime_authority_digest(bundle.environment)
    risk_side_effects = _stable((runtime.risk_service._requests, runtime.risk_service._audits))
    only_test_assert_all_apply(bundle)
    after = only_test_runtime_authority_digest(bundle.environment)
    assert after.journal == before.journal
    assert after.event_buffer == before.event_buffer
    assert after.event_bus == before.event_bus
    assert after.reconciliation == before.reconciliation
    assert after.deduplication == before.deduplication
    assert after.sequences == before.sequences
    assert _stable((runtime.risk_service._requests, runtime.risk_service._audits)) == risk_side_effects
    assert len(bundle.applied_ledger.records()) == 13
