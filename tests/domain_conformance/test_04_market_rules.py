from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyAssetClass, OnlyRuntimeMode
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.models import OnlyInstrumentReferenceSnapshot, OnlyMarketProfileId
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.registry import OnlyMarketProfileRequest
from onlyalpha.market.runtime_rules import OnlyMarketRuleCompiler, OnlyMarketRuleEngine


def test_generic_profile_compiles_instrument_quantity_semantics(equity) -> None:
    reference = OnlyInstrumentReferenceSnapshot(
        str(equity.instrument_id),
        OnlyAssetClass.EQUITY,
        str(equity.venue),
        OnlyMarketProfileId.GENERIC_T0_CASH,
        str(equity.settlement_currency),
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        "test",
        "1",
        "fingerprint",
        quantity_step=Decimal("0.001"),
        lot_size=Decimal("100"),
    )
    engine = OnlyMarketRuleEngine(
        registry=only_builtin_market_profile_registry(),
        compiler=OnlyMarketRuleCompiler(),
        request=OnlyMarketProfileRequest(OnlyMarketProfileId.GENERIC_T0_CASH),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        references={reference.instrument_id: reference},
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
    )
    policy = engine.compiled_rules(reference.instrument_id, OnlyTradingDay(date(2026, 1, 5))).quantity_policy
    assert policy.allow_fractional
    assert policy.buy_quantity_increment == Decimal("0.001")
