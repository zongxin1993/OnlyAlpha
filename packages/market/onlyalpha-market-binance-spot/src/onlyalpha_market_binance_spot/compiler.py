"""Pure provider-neutral 24x7 Spot policy compiler."""

from dataclasses import dataclass
from datetime import time
from decimal import Decimal

from onlyalpha.plugin.api import (
    OnlyCompiledDynamicPriceRequirement,
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyCompiledNotionalPolicy,
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductAuthorityIdentity,
    OnlyPositionAccountingModel,
    OnlyPriceBandRoundingMode,
    OnlySettlementModel,
    OnlySettlementRule,
    OnlySettlementTiming,
    OnlyShortSellingMode,
    OnlyShortSellingRule,
    OnlyTradingPhase,
    OnlyTradingSessionDefinition,
    OnlyTradingSessionModel,
    only_identity_fingerprint,
)
from onlyalpha_market_binance_spot.reference import OnlyBinanceSpotReference

_IMMEDIATE = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
_SESSION = OnlyTradingSessionModel(
    "CRYPTO_SPOT_24X7",
    "UTC",
    (OnlyTradingSessionDefinition("continuous", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
    True,
)
_SETTLEMENT = OnlySettlementModel("CRYPTO_SPOT_IMMEDIATE", _IMMEDIATE, _IMMEDIATE, _IMMEDIATE, _IMMEDIATE)
_POSITION = OnlyPositionAccountingModel()
_SHORT = OnlyShortSellingRule(OnlyShortSellingMode.DISABLED)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotPolicyCompiler:
    identity: OnlyMarketProductAuthorityIdentity = OnlyMarketProductAuthorityIdentity(
        "POLICY_COMPILER",
        "BINANCE_SPOT",
        "2",
        only_identity_fingerprint(
            ("CRYPTO_SPOT_24X7", "UTC", "IMMEDIATE", "NETTING", "SHORT_DISABLED", "NO_MARGIN", "REFERENCE_STATIC_RULES")
        ),
    )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day, as_of=request.as_of)
        if not isinstance(reference, OnlyBinanceSpotReference):
            raise TypeError("BINANCE_SPOT_REFERENCE_TYPE_REQUIRED")
        status = (
            OnlyInstrumentTradingStatus.TRADABLE
            if reference.market_product_eligible
            else (
                OnlyInstrumentTradingStatus.SUSPENDED
                if reference.provider_status in {"HALT", "BREAK"}
                else OnlyInstrumentTradingStatus.INACTIVE
            )
        )
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(reference.quote_currency, Decimal("1"), status),
            session_policy=_SESSION,
            price_policy=OnlyCompiledPriceBandPolicy(
                "BINANCE_SPOT_STATIC@1",
                reference.price_tick,
                None,
                None,
                reference.minimum_price,
                reference.maximum_price,
                OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                reference.minimum_quantity,
                reference.quantity_step,
                reference.minimum_quantity,
                reference.quantity_step,
                False,
                reference.maximum_quantity,
                True,
                reference.market_minimum_quantity,
                reference.market_quantity_step,
                reference.market_maximum_quantity,
            ),
            position_policy=_POSITION,
            short_policy=_SHORT,
            settlement_policy=_SETTLEMENT,
            margin_policy=None,
            notional_policy=OnlyCompiledNotionalPolicy(
                reference.minimum_notional,
                reference.maximum_notional,
                reference.minimum_notional_applies_to_market,
                reference.maximum_notional_applies_to_market,
                reference.notional_reference_window_minutes,
            ),
            dynamic_price_requirements=_dynamic_requirements(reference),
        )


def _dynamic_requirements(
    reference: OnlyBinanceSpotReference,
) -> tuple[OnlyCompiledDynamicPriceRequirement, ...]:
    requirements: list[OnlyCompiledDynamicPriceRequirement] = []
    for rule in reference.rules:
        if rule.rule_type not in {"PERCENT_PRICE", "PERCENT_PRICE_BY_SIDE", "PRICE_RANGE"}:
            continue
        values = dict(rule.values)
        names: tuple[str, ...]
        if rule.rule_type == "PERCENT_PRICE":
            names = ("multiplierDown", "multiplierUp")
            side_specific = False
            reference_kind = "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE"
            window = _integer(values, "avgPriceMins")
        elif rule.rule_type == "PERCENT_PRICE_BY_SIDE":
            names = ("askMultiplierDown", "askMultiplierUp", "bidMultiplierDown", "bidMultiplierUp")
            side_specific = True
            reference_kind = "VENUE_REFERENCE_PRICE_OR_TRADE_AVERAGE"
            window = _integer(values, "avgPriceMins")
        else:
            names = ("askLimitMultDown", "askLimitMultUp", "bidLimitMultDown", "bidLimitMultUp")
            side_specific = True
            reference_kind = "VENUE_REFERENCE_PRICE"
            window = None
        requirements.append(
            OnlyCompiledDynamicPriceRequirement(
                rule.rule_type,
                side_specific,
                reference_kind,
                window,
                tuple((name, Decimal(_text(values, name))) for name in names),
                "REALTIME_MARKET_REFERENCE",
            )
        )
    return tuple(sorted(requirements))


def _text(values: dict[str, str | bool | int], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str):
        raise ValueError(f"BINANCE_SPOT_DYNAMIC_RULE_{name.upper()}_INVALID")
    return value


def _integer(values: dict[str, str | bool | int], name: str) -> int:
    value = values.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"BINANCE_SPOT_DYNAMIC_RULE_{name.upper()}_INVALID")
    return value


__all__ = ["OnlyBinanceSpotPolicyCompiler"]
