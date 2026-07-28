from dataclasses import replace

from onlyalpha.execution import (
    OnlyExecutionProjectionComponent,
    OnlyInMemoryAppliedProjectionLedger,
    OnlyProjectionApplyStatus,
)
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


def _installed_settlement_target():
    bundle = only_test_projection_target_bundle()
    component = OnlyExecutionProjectionComponent.SETTLEMENT
    context = only_test_projection_context(bundle, component)
    assert bundle.targets[component].apply_execution_projection(context).status is OnlyProjectionApplyStatus.APPLIED
    target = bundle.create_targets(OnlyInMemoryAppliedProjectionLedger())[component]
    return bundle, context, target


def test_settlement_manager_result_authority_with_missing_ledger_is_recovered() -> None:
    bundle, context, target = _installed_settlement_target()
    manager = bundle.environment.runtime.settlement_manager
    before = manager.get_execution_authority(context.projection.after.instruction_id)
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.RECOVERED
    assert manager.get_execution_authority(context.projection.after.instruction_id) == before


def test_settlement_release_flag_conflict_is_explicit() -> None:
    bundle, context, target = _installed_settlement_target()
    pending = bundle.environment.runtime.settlement_manager._pending[context.projection.after.instruction_id]
    pending.asset_released = not pending.asset_released
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_settlement_missing_record_conflict_is_explicit() -> None:
    bundle, context, target = _installed_settlement_target()
    bundle.environment.runtime.settlement_manager._records.clear()
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_settlement_instruction_scope_conflict_is_explicit() -> None:
    bundle, context, target = _installed_settlement_target()
    pending = bundle.environment.runtime.settlement_manager._pending[context.projection.after.instruction_id]
    pending.instruction = replace(pending.instruction, account_id="conflicting-account")
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.STATE_CONFLICT


def test_settlement_version_conflict_is_explicit() -> None:
    bundle, context, target = _installed_settlement_target()
    pending = bundle.environment.runtime.settlement_manager._pending[context.projection.after.instruction_id]
    pending.version += 7
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.VERSION_CONFLICT
