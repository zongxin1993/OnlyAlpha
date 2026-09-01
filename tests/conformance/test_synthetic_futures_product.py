from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.economics import OnlyEconomicModel
from onlyalpha.market.product import OnlyMarketPolicyCompilationRequest
from tests.conformance.support.synthetic_futures import (
    OnlySyntheticFuturesPolicyCompiler,
    OnlySyntheticFuturesReferenceAuthority,
)


def test_non_binance_futures_product_compiles_without_core_special_case() -> None:
    authority = OnlySyntheticFuturesReferenceAuthority()
    policy = OnlySyntheticFuturesPolicyCompiler().compile(
        OnlyMarketPolicyCompilationRequest(
            OnlyInstrumentId.parse("TEST.LINEAR-202612"),
            OnlyTradingDay(date(2026, 9, 1)),
            authority,
            datetime(2026, 9, 1, 10, tzinfo=UTC),
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
