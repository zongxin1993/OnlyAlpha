from decimal import Decimal

import pytest

from onlyalpha.fee import OnlyFeeCalculationScope
from tests.execution.support.order_fee_accrual import only_test_order_fee_accrual_steps


def test_order_cumulative_fee_applies_only_target_delta() -> None:
    first, second, third = only_test_order_fee_accrual_steps(("5.00", "5.00", "7.00"))
    assert first.application.total_charges.amount == Decimal("5.00")
    assert second.application.total_charges.amount == Decimal("0.00")
    assert third.application.total_charges.amount == Decimal("2.00")
    assert third.after.cumulative_charges.amount == Decimal("7.00")


def test_fill_fee_applies_each_fill_target() -> None:
    results = only_test_order_fee_accrual_steps(("1.00", "1.00", "1.00"), scope=OnlyFeeCalculationScope.FILL)
    assert tuple(item.application.total_charges.amount for item in results) == (
        Decimal("1.00"),
        Decimal("1.00"),
        Decimal("1.00"),
    )
    assert results[-1].after.cumulative_charges.amount == Decimal("3.00")


def test_order_cumulative_negative_increment_fails_closed() -> None:
    with pytest.raises(ValueError, match="FEE_ACCRUAL_NEGATIVE_INCREMENT"):
        only_test_order_fee_accrual_steps(("5.00", "4.00"))
