from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyAssetClass, OnlyOrderSide, OnlyRuntimeMode
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.models import OnlyInstrumentReferenceSnapshot, OnlyMarketProfileId
from onlyalpha.market.profiles import only_builtin_market_profile_registry
from onlyalpha.market.registry import OnlyMarketProfileRequest
from onlyalpha.market.runtime_rules import (
    OnlyMarketRuleCompiler,
    OnlyMarketRuleEngine,
    OnlyPreTradeMarketContext,
    OnlyTradeApplicationRequest,
)


def _engine(profile: OnlyMarketProfileId) -> OnlyMarketRuleEngine:
    reference = OnlyInstrumentReferenceSnapshot(
        "TEST.VENUE",
        OnlyAssetClass.EQUITY,
        "VENUE",
        profile,
        "USD",
        datetime(2020, 1, 1, tzinfo=UTC),
        None,
        "test",
        "1",
        "reference-fingerprint",
        quantity_step=Decimal(1),
    )
    return OnlyMarketRuleEngine(
        registry=only_builtin_market_profile_registry(),
        compiler=OnlyMarketRuleCompiler(),
        request=OnlyMarketProfileRequest(profile),
        runtime_mode=OnlyRuntimeMode.BACKTEST,
        references={"TEST.VENUE": reference},
        advance_trading_day=lambda day, lag: OnlyTradingDay(date.fromordinal(day.value.toordinal() + lag)),
    )


def test_compiled_rules_are_deterministic_and_profile_does_not_escape() -> None:
    engine = _engine(OnlyMarketProfileId.GENERIC_T0_CASH)
    day = OnlyTradingDay(date(2026, 7, 17))
    first = engine.compiled_rules("TEST.VENUE", day)
    second = engine.compiled_rules("TEST.VENUE", day)
    assert first is second
    assert first.identity.compiled_rules_fingerprint == second.identity.compiled_rules_fingerprint
    assert not hasattr(first, "profile")


def test_pre_trade_and_trade_instruction_share_compiled_identity() -> None:
    engine = _engine(OnlyMarketProfileId.GENERIC_T0_CASH)
    day = OnlyTradingDay(date(2026, 7, 17))
    decision = engine.evaluate_pre_trade(
        OnlyPreTradeMarketContext(
            "TEST.VENUE",
            OnlyOrderSide.BUY,
            Decimal(2),
            Decimal(10),
            datetime(2026, 7, 17, 10, tzinfo=UTC),
            day,
            available_cash=Decimal(100),
        )
    )
    instruction = engine.build_trade_instruction(
        OnlyTradeApplicationRequest(
            "TEST.VENUE",
            "order-1",
            "trade-1",
            "account-1",
            OnlyOrderSide.BUY,
            Decimal(2),
            Decimal(10),
            datetime(2026, 7, 17, 10, tzinfo=UTC),
            day,
        )
    )
    assert decision.accepted
    assert decision.compiled_identity == instruction.compiled_identity
    assert instruction.settlement_instruction.asset_available_on == day
