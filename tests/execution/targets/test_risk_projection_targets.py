import pytest

from onlyalpha.execution import OnlyExecutionProjectionComponent
from tests.execution.targets.support import only_test_assert_component_applies


@pytest.mark.parametrize(
    "component",
    (OnlyExecutionProjectionComponent.RISK_RESERVATION, OnlyExecutionProjectionComponent.RISK),
)
def test_risk_projection_targets_apply_and_are_idempotent(component: OnlyExecutionProjectionComponent) -> None:
    only_test_assert_component_applies(component)
