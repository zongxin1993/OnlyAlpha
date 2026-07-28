import pytest

from onlyalpha.execution import OnlyExecutionProjectionComponent
from tests.execution.targets.support import only_test_assert_component_applies


@pytest.mark.parametrize(
    "component",
    (
        OnlyExecutionProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyExecutionProjectionComponent.STRATEGY_CASH_RESERVATION,
    ),
)
def test_cash_reservation_projection_targets_apply_and_are_idempotent(
    component: OnlyExecutionProjectionComponent,
) -> None:
    only_test_assert_component_applies(component)
