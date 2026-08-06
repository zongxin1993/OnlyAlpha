from dataclasses import replace
from decimal import Decimal

from onlyalpha.execution import (
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyProjectionApplyStatus,
    OnlyRuntimeProjectionComponent,
)
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


def _installed_fee_target():
    bundle = only_test_projection_target_bundle()
    component = OnlyRuntimeProjectionComponent.FEE_LEDGER
    context = only_test_projection_context(bundle, component)
    assert bundle.targets[component].apply_execution_projection(context).status is OnlyProjectionApplyStatus.APPLIED
    target = bundle.create_targets(OnlyInMemoryAppliedRuntimeProjectionLedger())[component]
    return bundle, context, target


def test_fee_application_authority_with_missing_projection_ledger_is_recovered() -> None:
    bundle, context, target = _installed_fee_target()
    before = bundle.environment.runtime.fee_application_ledger.get(context.projection.after.application.idempotency_key)
    result = target.apply_execution_projection(context)
    assert result.status is OnlyProjectionApplyStatus.RECOVERED
    assert (
        bundle.environment.runtime.fee_application_ledger.get(context.projection.after.application.idempotency_key)
        == before
    )


def test_fee_application_content_conflict_is_explicit() -> None:
    bundle, context, target = _installed_fee_target()
    manager = bundle.environment.runtime.fee_application_ledger
    key = context.projection.after.application.idempotency_key
    manager._instructions[key] = replace(
        manager._instructions[key], trade_id=type(manager._instructions[key].trade_id)("conflicting-trade")
    )
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_fee_record_content_conflict_is_explicit() -> None:
    bundle, context, target = _installed_fee_target()
    manager = bundle.environment.runtime.fee_application_ledger
    amount = manager._records[0].incremental_amount
    manager._records[0] = replace(
        manager._records[0],
        incremental_amount=type(amount)(amount.amount + Decimal("1"), amount.currency),
    )
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_fee_global_sequence_conflict_is_explicit() -> None:
    bundle, context, target = _installed_fee_target()
    manager = bundle.environment.runtime.fee_application_ledger
    manager._sequence += 1
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT
