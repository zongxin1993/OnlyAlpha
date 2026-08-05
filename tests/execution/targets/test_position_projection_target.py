from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.targets.support import only_test_assert_component_applies


def test_position_projection_target_applies_and_is_idempotent() -> None:
    only_test_assert_component_applies(OnlyRuntimeProjectionComponent.POSITION)
