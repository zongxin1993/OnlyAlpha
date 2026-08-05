import pytest

from onlyalpha.execution import OnlyRuntimeProjectionComponent
from tests.execution.targets.support import only_test_assert_component_applies


@pytest.mark.parametrize(
    "component",
    (
        OnlyRuntimeProjectionComponent.ACCOUNT_CASH_RESERVATION,
        OnlyRuntimeProjectionComponent.STRATEGY_CASH_RESERVATION,
    ),
)
def test_cash_reservation_projection_targets_apply_and_are_idempotent(
    component: OnlyRuntimeProjectionComponent,
) -> None:
    only_test_assert_component_applies(component)
