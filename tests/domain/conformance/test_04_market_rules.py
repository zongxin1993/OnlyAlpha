from dataclasses import replace
from datetime import date
from decimal import Decimal

from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.runtime_rules import OnlyMarketRuleEngine
from tests.runtime_support.market_product import only_generic_market_product


def test_generic_profile_compiles_instrument_quantity_semantics(equity) -> None:
    equity = replace(
        equity,
        quantity_precision=3,
        step_size=equity.step_size.__class__(Decimal("0.001"), 3),
        effective_from=None,
        effective_to=None,
    )
    binding = only_generic_market_product(equity)
    engine = OnlyMarketRuleEngine(
        binding=binding,
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
    )
    policy = engine.compiled_rules(str(equity.instrument_id), OnlyTradingDay(date(2026, 1, 5))).quantity_policy
    assert policy.allow_fractional
    assert policy.buy_quantity_increment == Decimal("0.001")
