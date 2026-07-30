from onlyalpha.domain.identifiers import OnlyRuntimeId
from onlyalpha.domain.time import OnlyTimestamp
from onlyalpha.fee import OnlyOrderFeeAccrualManager
from onlyalpha.runtime.checkpoint.model import (
    OnlyBacktestReplayCursor,
    OnlyCheckpointCaptureContext,
    OnlyCheckpointRestoreContext,
)
from onlyalpha.runtime.checkpoint.participant import OnlyJsonRuntimeCheckpointParticipant
from onlyalpha.runtime.checkpoint.registry import OnlyRuntimeCheckpointParticipantRegistry
from tests.execution.support.order_fee_accrual import only_test_order_fee_accrual_steps
from tests.runtime.checkpoint.test_checkpoint_contract import _cursor


def test_runtime_checkpoint_registry_restores_order_fee_accrual_authority() -> None:
    state = only_test_order_fee_accrual_steps(("5.00",))[0].after
    manager = OnlyOrderFeeAccrualManager()
    manager.restore(state)
    registry = OnlyRuntimeCheckpointParticipantRegistry()
    registry.register(
        OnlyJsonRuntimeCheckpointParticipant(
            "order_fee_accrual.authority",
            1,
            manager.capture_checkpoint,
            manager.restore_checkpoint,
        )
    )
    cursor: OnlyBacktestReplayCursor = _cursor()
    runtime_id = OnlyRuntimeId("runtime")
    components = registry.capture(OnlyCheckpointCaptureContext(runtime_id, OnlyTimestamp(2), cursor, 0))
    manager.restore_checkpoint([])
    registry.restore(components, OnlyCheckpointRestoreContext(runtime_id, cursor))
    assert manager.get(state.order_id) == state
