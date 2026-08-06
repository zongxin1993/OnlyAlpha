from decimal import Decimal

import pytest

from onlyalpha.domain.value import OnlyCurrency, OnlyMoney
from onlyalpha.fee import (
    OnlyFeeBasisValues,
    OnlyFeeCalculationBasis,
    OnlyFeeCalculationPipeline,
    OnlyFeeFixedTerm,
    OnlyFeeFormula,
    OnlyFeePerUnitTerm,
    OnlyFeeRateTerm,
    OnlyFeeRoundingMode,
    OnlyFeeRoundingPolicy,
)
from onlyalpha.fee.rounding import only_apply_fee_pipeline


def _basis() -> OnlyFeeBasisValues:
    return OnlyFeeBasisValues(OnlyMoney(Decimal("1000.00"), OnlyCurrency("CNY", 2)), Decimal("100"), Decimal("5"))


def test_formula_composes_rate_per_unit_and_fixed_terms() -> None:
    formula = OnlyFeeFormula(
        (
            OnlyFeeRateTerm(OnlyFeeCalculationBasis.NOTIONAL, Decimal("0.001")),
            OnlyFeePerUnitTerm(OnlyFeeCalculationBasis.CONTRACTS, Decimal("2")),
            OnlyFeeFixedTerm(Decimal("3")),
        )
    )
    assert formula.evaluate(_basis()) == Decimal("14.00000")


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        (OnlyFeeRoundingMode.HALF_EVEN, "1.00"),
        (OnlyFeeRoundingMode.HALF_UP, "1.01"),
        (OnlyFeeRoundingMode.CEILING, "1.01"),
        (OnlyFeeRoundingMode.FLOOR, "1.00"),
    ),
)
def test_rounding_modes_are_explicit(mode: OnlyFeeRoundingMode, expected: str) -> None:
    policy = OnlyFeeRoundingPolicy(Decimal("0.01"), mode)
    _, target = only_apply_fee_pipeline(
        Decimal("1.005"),
        minimum=Decimal(0),
        maximum=None,
        rounding=policy,
        pipeline=OnlyFeeCalculationPipeline.ROUND_THEN_BOUNDS,
    )
    assert target == Decimal(expected)


def test_formula_rejects_empty_terms() -> None:
    with pytest.raises(ValueError, match="empty"):
        OnlyFeeFormula(())
