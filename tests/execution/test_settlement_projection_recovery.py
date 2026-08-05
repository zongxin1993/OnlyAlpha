from dataclasses import replace

import pytest

from onlyalpha.execution import (
    OnlyInMemoryAppliedRuntimeProjectionLedger,
    OnlyProjectionApplyStatus,
    OnlyRuntimeProjectionComponent,
)
from onlyalpha.settlement.models import OnlySettlementInstructionStatus
from tests.execution.targets.support import only_test_projection_context, only_test_projection_target_bundle


def _installed_settlement_target():
    bundle = only_test_projection_target_bundle()
    component = OnlyRuntimeProjectionComponent.SETTLEMENT
    context = only_test_projection_context(bundle, component)
    assert bundle.targets[component].apply_execution_projection(context).status is OnlyProjectionApplyStatus.APPLIED
    target = bundle.create_targets(OnlyInMemoryAppliedRuntimeProjectionLedger())[component]
    return bundle, context, target


def test_settlement_authority_with_missing_applied_ledger_is_recovered() -> None:
    bundle, context, target = _installed_settlement_target()
    instruction = context.projection.after.instruction
    assert instruction is not None
    manager = bundle.environment.runtime.settlement_authority
    before = manager.require(instruction.instruction_id)
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.RECOVERED
    assert manager.require(instruction.instruction_id) == before


def test_settlement_transition_conflict_is_explicit() -> None:
    bundle, context, target = _installed_settlement_target()
    instruction = context.projection.after.instruction
    assert instruction is not None
    manager = bundle.environment.runtime.settlement_authority
    current = manager.require(instruction.instruction_id)
    conflicting = replace(
        current,
        asset_trade_available=False,
        status=OnlySettlementInstructionStatus.PARTIALLY_EFFECTIVE,
    )
    with pytest.raises(ValueError, match="SETTLEMENT_INSTRUCTION_IDENTITY_CONFLICT"):
        manager.restore_runtime_authority(conflicting)


def test_settlement_version_conflict_is_explicit() -> None:
    bundle, context, target = _installed_settlement_target()
    instruction = context.projection.after.instruction
    assert instruction is not None
    manager = bundle.environment.runtime.settlement_authority
    current = manager.require(instruction.instruction_id)
    manager.restore_checkpoint({"instructions": [replace(current, version=current.version + 7).to_json()]})
    assert target.apply_execution_projection(context).status is OnlyProjectionApplyStatus.VERSION_CONFLICT
