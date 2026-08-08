import pytest

from onlyalpha.execution import (
    OnlyAppliedRuntimeProjectionRecord,
    OnlyExecutionRecoveryStatus,
    OnlyProjectionApplyStatus,
    OnlyRuntimeProjectionApplyContext,
    OnlyRuntimeProjectionComponent,
)
from tests.execution.support.real_execution_recovery_harness import OnlyRealExecutionRecoveryHarness
from tests.execution.targets.support import only_test_projection_context

_COMPONENTS = tuple(
    component
    for component in OnlyRuntimeProjectionComponent
    if component
    not in {
        OnlyRuntimeProjectionComponent.MARGIN,
        OnlyRuntimeProjectionComponent.POSITION_RESERVATION,
        OnlyRuntimeProjectionComponent.MARGIN_RESERVATION,
        OnlyRuntimeProjectionComponent.EXTERNAL_FEE_EVIDENCE,
        OnlyRuntimeProjectionComponent.FEE_RECONCILIATION,
        OnlyRuntimeProjectionComponent.FEE_ADJUSTMENT_LEDGER,
        OnlyRuntimeProjectionComponent.UNALLOCATED_EXTERNAL_FEE,
        OnlyRuntimeProjectionComponent.RECONCILIATION_RISK_GATE,
    }
)


@pytest.mark.parametrize("component", _COMPONENTS, ids=lambda item: item.value)
def test_real_target_payload_conflict_never_overwrites_installed_manager_authority(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    context = only_test_projection_context(harness.bundle, component)
    target = harness.targets[component]
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.APPLIED
    manager_before = harness.manager_digest()
    conflict = OnlyRuntimeProjectionApplyContext(
        f"{context.transaction_id}-conflict",
        context.execution_sequence,
        context.fact,
        context.projection,
    )

    result = target.apply_execution_projection(conflict)

    assert result.status is OnlyProjectionApplyStatus.PAYLOAD_CONFLICT
    assert harness.manager_digest() == manager_before
    assert harness.transaction_store.ready_count(harness.bundle.transaction.runtime_id) == 0


@pytest.mark.parametrize("conflict", ("version", "state"))
@pytest.mark.parametrize("component", _COMPONENTS, ids=lambda item: item.value)
def test_real_target_version_and_state_conflict_keep_manager_authority_unchanged(
    component: OnlyRuntimeProjectionComponent,
    conflict: str,
) -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    context = only_test_projection_context(harness.bundle, component)
    identity = context.projection.identity
    if conflict == "version":
        object.__setattr__(identity, "expected_version", identity.expected_version + 100)
        object.__setattr__(identity, "result_version", identity.result_version + 100)
        expected = OnlyProjectionApplyStatus.VERSION_CONFLICT
    else:
        object.__setattr__(identity, "expected_state_hash", "f" * 64)
        expected = OnlyProjectionApplyStatus.STATE_CONFLICT
    manager_before = harness.manager_digest()

    result = harness.targets[component].apply_execution_projection(context)

    assert result.status is expected
    assert harness.manager_digest() == manager_before
    assert harness.transaction_store.ready_count(harness.bundle.transaction.runtime_id) == 0


@pytest.mark.parametrize("conflict", ("payload", "version", "state"))
@pytest.mark.parametrize("component", _COMPONENTS, ids=lambda item: item.value)
def test_real_conflict_blocks_recovery_and_keeps_transaction_out_of_business_query(
    component: OnlyRuntimeProjectionComponent,
    conflict: str,
) -> None:
    harness = OnlyRealExecutionRecoveryHarness.create()
    projection = next(item for item in harness.bundle.transaction.projections if item.identity.component is component)
    identity = projection.identity
    if conflict == "payload":
        harness.applied_ledger.record(
            OnlyAppliedRuntimeProjectionRecord(
                "conflicting-transaction",
                harness.bundle.transaction.execution_sequence,
                component,
                identity.entity_key,
                identity.payload_hash,
                identity.result_state_hash,
            )
        )
    elif conflict == "version":
        object.__setattr__(identity, "expected_version", identity.expected_version + 100)
        object.__setattr__(identity, "result_version", identity.result_version + 100)
    else:
        object.__setattr__(identity, "expected_state_hash", "f" * 64)

    result = harness.recover()

    assert result.status is OnlyExecutionRecoveryStatus.FAILED
    assert result.failure_component is component
    assert harness.transaction_store.ready_records(harness.bundle.transaction.runtime_id) == ()
    assert harness.transaction_store.pending(harness.bundle.transaction.runtime_id, limit=100) == ()
