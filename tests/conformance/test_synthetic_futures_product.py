from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.trading import OnlyPositionMode
from onlyalpha.market.economics import OnlyEconomicModel
from onlyalpha.market.product import OnlyMarketPolicyCompilationRequest
from tests.conformance.support.synthetic_futures import (
    OnlySyntheticFuturesPolicyCompiler,
    OnlySyntheticFuturesReferenceAuthority,
    only_synthetic_futures_effective_profile,
)


def test_non_binance_futures_product_compiles_without_core_special_case() -> None:
    authority = OnlySyntheticFuturesReferenceAuthority()
    policy = OnlySyntheticFuturesPolicyCompiler().compile(
        OnlyMarketPolicyCompilationRequest(
            OnlyInstrumentId.parse("TEST.LINEAR-202612"),
            OnlyTradingDay(date(2026, 9, 1)),
            authority,
            datetime(2026, 9, 1, 10, tzinfo=UTC),
            only_synthetic_futures_effective_profile(),
        )
    )
    assert policy.economic_model is OnlyEconomicModel.MARGINED_DERIVATIVE
    assert policy.funding_policy is None
    assert policy.variation_margin_policy is not None
    assert policy.compiled_margin_policy is not None
    assert policy.compiled_margin_policy.requirement(Decimal("10000")) == (
        Decimal("1200.00"),
        Decimal("800.00"),
    )


@pytest.mark.parametrize("position_mode", tuple(OnlyPositionMode))
@pytest.mark.parametrize("margin_mode", (OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED))
def test_synthetic_futures_all_effective_mode_compositions_are_canonical(
    position_mode: OnlyPositionMode, margin_mode: OnlyMarginMode
) -> None:
    profile = only_synthetic_futures_effective_profile(position_mode, margin_mode)
    policy = OnlySyntheticFuturesPolicyCompiler().compile(
        OnlyMarketPolicyCompilationRequest(
            OnlyInstrumentId.parse("TEST.LINEAR-202612"),
            OnlyTradingDay(date(2026, 9, 1)),
            OnlySyntheticFuturesReferenceAuthority(),
            datetime(2026, 9, 1, 10, tzinfo=UTC),
            profile,
        )
    )
    assert policy.position_mode is position_mode
    assert policy.margin_mode is margin_mode
    assert policy.effective_trading_profile is profile
