"""Pure compiler for GENERIC_T0_CASH@1 market economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from onlyalpha.plugin.api import (
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketPositionMode,
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
from onlyalpha_market_generic_t0_cash.reference import OnlyGenericT0CashReference

_IMMEDIATE = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
_SESSION = OnlyTradingSessionModel(
    "GENERIC_DAY",
    "UTC",
    (OnlyTradingSessionDefinition("regular", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
)
_SETTLEMENT = OnlySettlementModel("GENERIC_T0", _IMMEDIATE, _IMMEDIATE, _IMMEDIATE, _IMMEDIATE)
_POSITION = OnlyPositionAccountingModel(OnlyMarketPositionMode.LONG_ONLY)
_SHORT = OnlyShortSellingRule(OnlyShortSellingMode.DISABLED)


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashPolicyCompiler:
    identity: OnlyMarketProductAuthorityIdentity = OnlyMarketProductAuthorityIdentity(
        "POLICY_COMPILER",
        "GENERIC_T0_CASH",
        "1",
        only_identity_fingerprint(
            (
                "GENERIC_T0_CASH",
                "1",
                (
                    _SESSION.model_id,
                    _SESSION.timezone,
                    tuple(
                        (
                            item.name,
                            item.opens_at.isoformat(),
                            item.closes_at.isoformat(),
                            item.phase,
                            item.trading_day_offset,
                            item.allows_orders,
                        )
                        for item in _SESSION.sessions
                    ),
                    _SESSION.continuous_24x7,
                ),
                (
                    _SETTLEMENT.model_id,
                    (_SETTLEMENT.asset_settlement.timing, _SETTLEMENT.asset_settlement.lag),
                    (_SETTLEMENT.cash_settlement.timing, _SETTLEMENT.cash_settlement.lag),
                    (_SETTLEMENT.asset_availability.timing, _SETTLEMENT.asset_availability.lag),
                    (_SETTLEMENT.cash_availability.timing, _SETTLEMENT.cash_availability.lag),
                ),
                (_POSITION.mode, _POSITION.allow_flip),
                (_SHORT.mode,),
                "REFERENCE_TICK_QUANTITY_AND_TERMS",
            )
        ),
    )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day, as_of=request.as_of)
        if not isinstance(reference, OnlyGenericT0CashReference):
            raise TypeError("GENERIC_T0_CASH_REFERENCE_TYPE_REQUIRED")
        if reference.instrument_id != request.instrument_id:
            raise ValueError("GENERIC_T0_CASH_REFERENCE_INSTRUMENT_CONFLICT")
        status = (
            OnlyInstrumentTradingStatus.INACTIVE
            if not reference.active
            else OnlyInstrumentTradingStatus.SUSPENDED
            if reference.suspended
            else OnlyInstrumentTradingStatus.TRADABLE
        )
        minimum = reference.minimum_quantity or reference.quantity_step
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(
                reference.settlement_currency,
                reference.contract_multiplier,
                status,
            ),
            session_policy=_SESSION,
            price_policy=OnlyCompiledPriceBandPolicy(
                "GENERIC@1",
                reference.tick_size,
                None,
                None,
                None,
                None,
                OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                minimum,
                reference.quantity_step,
                minimum,
                reference.quantity_step,
                False,
                reference.maximum_quantity,
                True,
            ),
            position_policy=_POSITION,
            short_policy=_SHORT,
            settlement_policy=_SETTLEMENT,
            margin_policy=None,
        )


__all__ = ["OnlyGenericT0CashPolicyCompiler"]
