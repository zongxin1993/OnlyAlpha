from datetime import UTC, date, datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyOrderSide
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.market.models import (
    OnlyLiquidityModelType,
    OnlyMarginState,
    OnlyMarketProfileId,
    OnlyMarketProfileResolver,
    only_next_calendar_day,
)
from onlyalpha.market.profiles import (
    only_builtin_market_profiles,
    only_cn_a_share_cash_profile,
    only_generic_crypto_spot_profile,
    only_generic_margin_futures_profile,
    only_generic_t0_cash_profile,
)
from onlyalpha.settlement.models import OnlySettlementScheduleRequest


def test_profile_resolver_is_versioned_and_fingerprinted() -> None:
    resolver = OnlyMarketProfileResolver(only_builtin_market_profiles())
    profile = resolver.resolve(OnlyMarketProfileId.CN_A_SHARE_CASH, datetime(2026, 1, 1).date())
    assert profile.version == "2025.1"
    assert len(profile.content_fingerprint) == 64
    assert profile.content_fingerprint != only_generic_t0_cash_profile().content_fingerprint


def test_t0_and_a_share_t1_use_same_settlement_model_boundary() -> None:
    day = OnlyTradingDay(datetime(2026, 1, 5).date())
    request = OnlySettlementScheduleRequest(OnlyOrderSide.BUY, day)
    t0 = only_generic_t0_cash_profile().settlement_model.schedule(request, only_next_calendar_day)
    t1 = only_cn_a_share_cash_profile("2025.1").settlement_model.schedule(request, only_next_calendar_day)
    assert t0.asset_trade_available_on == day
    assert t1.asset_trade_available_on.value.isoformat() == "2026-01-06"
    assert t1.cash_trade_available_on == day
    assert t1.legal_settlement_on.value.isoformat() == "2026-01-06"


def test_crypto_is_24x7_and_declares_fractional_quantity() -> None:
    profile = only_generic_crypto_spot_profile()
    weekend = datetime(2026, 7, 19, 23, 59, tzinfo=UTC)
    assert profile.session_model.state_at(weekend).allows_orders
    assert profile.quantity_rule.allow_fractional


def test_futures_margin_multiplier_and_short_mode() -> None:
    profile = only_generic_margin_futures_profile()
    assert profile.margin_model is not None
    requirement = profile.margin_model.requirement(Decimal(4000), Decimal(2), Decimal(300))
    assert requirement.notional == Decimal(2_400_000)
    assert requirement.initial_margin == Decimal(240_000)
    assert profile.margin_model.can_open(OnlyMarginState(Decimal(300_000), Decimal(0), Decimal(0)), requirement)
    assert not profile.margin_model.can_open(OnlyMarginState(Decimal(200_000), Decimal(0), Decimal(0)), requirement)
    assert profile.position_model.mode.value == "HEDGING"
    assert profile.short_selling_rule.mode.value == "ENABLED_UNRESTRICTED"


def test_a_share_profiles_freeze_regime_and_session_boundaries() -> None:
    old = only_cn_a_share_cash_profile("2025.1")
    current = only_cn_a_share_cash_profile("2026.07")
    assert old.effective_to == date(2026, 7, 6)
    assert current.effective_from == date(2026, 7, 6)
    assert old.price_rule.daily_limit_rate is None
    phases = tuple(item.phase.value for item in current.session_model.sessions)
    assert phases == (
        "OPENING_AUCTION",
        "PRE_OPEN",
        "CONTINUOUS",
        "MIDDAY_BREAK",
        "CONTINUOUS",
        "CLOSING_AUCTION",
    )


def test_shared_bar_liquidity_is_consumable_across_orders() -> None:
    liquidity = only_generic_crypto_spot_profile().liquidity_model
    assert liquidity.model_type is OnlyLiquidityModelType.BAR_VOLUME_PARTICIPATION
    assert liquidity.capacity(Decimal(1000), Decimal(30)) == Decimal(70)
    assert liquidity.maximum_participation_rate == Decimal("0.10")
