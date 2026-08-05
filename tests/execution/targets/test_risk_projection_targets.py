import pytest

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.targets.support import only_test_assert_component_applies


@pytest.mark.parametrize(
    "component",
    (OnlyRuntimeProjectionComponent.RISK_RESERVATION, OnlyRuntimeProjectionComponent.RISK),
)
def test_risk_projection_targets_apply_and_are_idempotent(component: OnlyRuntimeProjectionComponent) -> None:
    only_test_assert_component_applies(component)
