from decimal import Decimal

import pytest

from onlyalpha.fee import OnlyFeeCalculationScope
from tests.execution.support.order_fee_accrual import only_test_order_fee_accrual_steps


def test_order_cumulative_minimum_is_charged_once_then_only_the_difference() -> None:
    first, second, third = only_test_order_fee_accrual_steps(
        ("5.00", "5.00", "8.00"),
        raw_amounts=("0.30", "0.70", "8.00"),
    )
    assert tuple(item.incremental_total.amount for item in (first, second, third)) == (
        Decimal("5.00"),
        Decimal("0"),
        Decimal("3.00"),
    )
    assert third.after.cumulative_charged_fee.amount == Decimal("8.00")
    assert third.after.components[0].cumulative_raw_amount.amount == Decimal("8.00")
    assert third.after.fill_count == third.after.version == 3


def test_fill_scope_charges_each_fill_and_negative_cumulative_increment_fails_closed() -> None:
    fill = only_test_order_fee_accrual_steps(
        ("5.00", "5.00"),
        scope=OnlyFeeCalculationScope.FILL,
    )
    assert tuple(item.incremental_total.amount for item in fill) == (Decimal("5.00"), Decimal("5.00"))
    assert fill[-1].after.cumulative_charged_fee.amount == Decimal("10.00")
    with pytest.raises(ValueError, match="FEE_ACCRUAL_NEGATIVE_INCREMENT"):
        only_test_order_fee_accrual_steps(("5.00", "4.00"))
