"""Built-in Generic profiles and the first production A-share profile."""

from datetime import date, time
from decimal import Decimal

from onlyalpha.domain.enums import OnlyAssetClass
from onlyalpha.market.models import (
    OnlyLiquidityModel,
    OnlyLiquidityModelType,
    OnlyMarginModel,
    OnlyMarketPositionMode,
    OnlyMarketProfile,
    OnlyMarketProfileId,
    OnlyMatchingModel,
    OnlyMatchingModelType,
    OnlyPositionAccountingModel,
    OnlyPriceRule,
    OnlyQuantityRule,
    OnlySettlementModel,
    OnlySettlementRule,
    OnlySettlementTiming,
    OnlyShortSellingMode,
    OnlyShortSellingRule,
    OnlySlippageModel,
    OnlySlippageModelType,
    OnlyTradingPhase,
    OnlyTradingSessionDefinition,
    OnlyTradingSessionModel,
)
from onlyalpha.market.registry import (
    OnlyMarketCapabilitySet,
    OnlyMarketProfileOverridePolicy,
    OnlyMarketProfileRegistry,
    OnlyMarketProfileStatus,
    OnlyMarketProfileVersion,
)

_IMMEDIATE = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
_T1 = OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE)
_T0_SETTLEMENT = OnlySettlementModel("GENERIC_T0", _IMMEDIATE, _IMMEDIATE, _IMMEDIATE, _IMMEDIATE)
_DAY_SESSION = OnlyTradingSessionModel(
    "GENERIC_DAY", "UTC", (OnlyTradingSessionDefinition("regular", time(0), time(0), OnlyTradingPhase.CONTINUOUS),)
)
_CONTINUOUS = OnlyTradingSessionModel(
    "CONTINUOUS_24X7",
    "UTC",
    (OnlyTradingSessionDefinition("continuous", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
    True,
)
_NONE_SLIPPAGE = OnlySlippageModel(OnlySlippageModelType.NONE)
_NEXT_OPEN = OnlyMatchingModel(OnlyMatchingModelType.NEXT_BAR_OPEN)


def only_generic_t0_cash_profile() -> OnlyMarketProfile:
    return OnlyMarketProfile(
        OnlyMarketProfileId.GENERIC_T0_CASH,
        "GENERIC",
        None,
        (OnlyAssetClass.EQUITY, OnlyAssetClass.FUND),
        _DAY_SESSION,
        _T0_SETTLEMENT,
        OnlyPositionAccountingModel(OnlyMarketPositionMode.LONG_ONLY),
        OnlyShortSellingRule(OnlyShortSellingMode.DISABLED),
        None,
        OnlyPriceRule(Decimal("0.01")),
        OnlyQuantityRule(True),
        OnlyLiquidityModel(OnlyLiquidityModelType.UNLIMITED),
        _NONE_SLIPPAGE,
        _NEXT_OPEN,
        date(1970, 1, 1),
        None,
        "1",
        "OnlyAlpha",
    )


def only_generic_margin_futures_profile() -> OnlyMarketProfile:
    return OnlyMarketProfile(
        OnlyMarketProfileId.GENERIC_MARGIN_FUTURES,
        "GENERIC",
        None,
        (OnlyAssetClass.COMMODITY,),
        _DAY_SESSION,
        OnlySettlementModel("FUTURES_DAILY_MARK_TO_MARK", _IMMEDIATE, _IMMEDIATE, _IMMEDIATE, _IMMEDIATE),
        OnlyPositionAccountingModel(OnlyMarketPositionMode.HEDGING),
        OnlyShortSellingRule(OnlyShortSellingMode.ENABLED_UNRESTRICTED),
        OnlyMarginModel("GENERIC_FUTURES_MARGIN", Decimal("0.10"), Decimal("0.08")),
        OnlyPriceRule(Decimal("0.01")),
        OnlyQuantityRule(False),
        OnlyLiquidityModel(OnlyLiquidityModelType.UNLIMITED),
        _NONE_SLIPPAGE,
        _NEXT_OPEN,
        date(1970, 1, 1),
        None,
        "1",
        "OnlyAlpha",
    )


def only_generic_crypto_spot_profile() -> OnlyMarketProfile:
    return OnlyMarketProfile(
        OnlyMarketProfileId.GENERIC_24X7_CRYPTO_SPOT,
        "CRYPTO",
        None,
        (OnlyAssetClass.CRYPTOCURRENCY,),
        _CONTINUOUS,
        _T0_SETTLEMENT,
        OnlyPositionAccountingModel(OnlyMarketPositionMode.LONG_ONLY),
        OnlyShortSellingRule(OnlyShortSellingMode.DISABLED),
        None,
        OnlyPriceRule(Decimal("0.01")),
        OnlyQuantityRule(True),
        OnlyLiquidityModel(OnlyLiquidityModelType.BAR_VOLUME_PARTICIPATION, Decimal("0.10")),
        _NONE_SLIPPAGE,
        _NEXT_OPEN,
        date(1970, 1, 1),
        None,
        "1",
        "OnlyAlpha",
    )


def only_cn_a_share_cash_profile(version: str) -> OnlyMarketProfile:
    if version not in {"2025.1", "2026.07"}:
        raise ValueError("unsupported CN_A_SHARE_CASH profile version")
    sessions = OnlyTradingSessionModel(
        f"CN_A_SHARE_DAY@{version}",
        "Asia/Shanghai",
        (
            OnlyTradingSessionDefinition(
                "opening_auction", time(9, 15), time(9, 25), OnlyTradingPhase.OPENING_AUCTION, allows_orders=False
            ),
            OnlyTradingSessionDefinition(
                "pre_open", time(9, 25), time(9, 30), OnlyTradingPhase.PRE_OPEN, allows_orders=False
            ),
            OnlyTradingSessionDefinition("morning", time(9, 30), time(11, 30), OnlyTradingPhase.CONTINUOUS),
            OnlyTradingSessionDefinition(
                "midday_break", time(11, 30), time(13), OnlyTradingPhase.MIDDAY_BREAK, allows_orders=False
            ),
            OnlyTradingSessionDefinition("afternoon", time(13), time(14, 57), OnlyTradingPhase.CONTINUOUS),
            OnlyTradingSessionDefinition(
                "closing_auction", time(14, 57), time(15), OnlyTradingPhase.CLOSING_AUCTION, allows_orders=False
            ),
        ),
    )
    settlement = OnlySettlementModel("CN_A_SHARE_T1", _T1, _T1, _T1, _IMMEDIATE)
    return OnlyMarketProfile(
        OnlyMarketProfileId.CN_A_SHARE_CASH,
        "CN_A_SHARE",
        None,
        (OnlyAssetClass.EQUITY,),
        sessions,
        settlement,
        OnlyPositionAccountingModel(OnlyMarketPositionMode.LONG_ONLY),
        OnlyShortSellingRule(OnlyShortSellingMode.DISABLED),
        None,
        OnlyPriceRule(Decimal("0.01")),
        OnlyQuantityRule(False, True, True),
        OnlyLiquidityModel(OnlyLiquidityModelType.BAR_VOLUME_PARTICIPATION, Decimal("0.10")),
        _NONE_SLIPPAGE,
        _NEXT_OPEN,
        date(2025, 1, 1) if version == "2025.1" else date(2026, 7, 6),
        date(2026, 7, 6) if version == "2025.1" else None,
        version,
        "OnlyAlpha",
        True,
    )


def only_builtin_market_profiles() -> tuple[OnlyMarketProfile, ...]:
    return (
        only_generic_t0_cash_profile(),
        only_generic_margin_futures_profile(),
        only_generic_crypto_spot_profile(),
        only_cn_a_share_cash_profile("2025.1"),
        only_cn_a_share_cash_profile("2026.07"),
    )


def only_builtin_market_profile_registry() -> OnlyMarketProfileRegistry:
    """Return a fresh registry; profiles remain experimental until full Engine packs pass."""
    capabilities = {
        OnlyMarketProfileId.CN_A_SHARE_CASH: OnlyMarketCapabilitySet(
            supports_t_plus_n=True,
            supports_board_lot=True,
            supports_odd_lot=True,
            supports_multi_session=True,
            supports_daily_price_limit=True,
            supports_partial_fill=True,
        ),
        OnlyMarketProfileId.GENERIC_T0_CASH: OnlyMarketCapabilitySet(
            supports_intraday_resale=True,
            supports_fractional_quantity=True,
        ),
        OnlyMarketProfileId.GENERIC_MARGIN_FUTURES: OnlyMarketCapabilitySet(
            supports_intraday_resale=True,
            supports_short_selling=True,
            supports_margin=True,
            supports_hedging=True,
            supports_contract_multiplier=True,
        ),
        OnlyMarketProfileId.GENERIC_24X7_CRYPTO_SPOT: OnlyMarketCapabilitySet(
            supports_intraday_resale=True,
            supports_fractional_quantity=True,
            supports_minimum_notional=True,
            supports_24x7=True,
            supports_partial_fill=True,
        ),
    }
    policy = OnlyMarketProfileOverridePolicy()
    return OnlyMarketProfileRegistry(
        OnlyMarketProfileVersion(
            profile.profile_id,
            profile.version,
            OnlyMarketProfileStatus.EXPERIMENTAL,
            profile.effective_from,
            profile.effective_to,
            profile,
            capabilities[profile.profile_id],
            policy,
            profile.source,
        )
        for profile in only_builtin_market_profiles()
    )
