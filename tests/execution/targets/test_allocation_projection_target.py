from onlyalpha.execution import OnlyExecutionProjectionComponent
from tests.execution.targets.support import only_test_assert_component_applies


def test_allocation_projection_target_applies_and_is_idempotent() -> None:
    only_test_assert_component_applies(OnlyExecutionProjectionComponent.ALLOCATION)
