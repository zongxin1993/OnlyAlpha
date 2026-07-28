from dataclasses import replace
from decimal import Decimal

from onlyalpha.execution import (
    OnlyExecutionProjectionComponent,
    OnlyInMemoryAppliedProjectionLedger,
    OnlyProjectionApplyStatus,
)
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


def _installed_fee_target():
    bundle = only_test_projection_target_bundle()
    component = OnlyExecutionProjectionComponent.FEE
    context = only_test_projection_context(bundle, component)
    assert bundle.targets[component].apply_execution_projection(context).status is OnlyProjectionApplyStatus.APPLIED
    target = bundle.create_targets(OnlyInMemoryAppliedProjectionLedger())[component]
    return bundle, context, target


def test_fee_manager_result_authority_with_missing_ledger_is_recovered() -> None:
    bundle, context, target = _installed_fee_target()
    before = bundle.environment.runtime.fee_manager.get_execution_authority(
        context.projection.after.instruction.idempotency_key
    )
    result = target.apply_execution_projection(context)
    assert result.status is OnlyProjectionApplyStatus.RECOVERED
    assert (
        bundle.environment.runtime.fee_manager.get_execution_authority(
            context.projection.after.instruction.idempotency_key
        )
        == before
    )


def test_fee_instruction_content_conflict_is_explicit() -> None:
    bundle, context, target = _installed_fee_target()
    manager = bundle.environment.runtime.fee_manager
    key = context.projection.after.instruction.idempotency_key
    manager._instructions_by_key[key] = replace(manager._instructions_by_key[key], trade_id="conflicting-trade")
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_fee_record_content_conflict_is_explicit() -> None:
    bundle, context, target = _installed_fee_target()
    manager = bundle.environment.runtime.fee_manager
    manager._records[0] = replace(manager._records[0], charged=manager._records[0].charged + Decimal("1"))
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_fee_global_sequence_conflict_is_explicit() -> None:
    bundle, context, target = _installed_fee_target()
    manager = bundle.environment.runtime.fee_manager
    manager._sequence += 1
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT
