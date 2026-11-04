"""Pure compiler for versioned CN A-share cash economics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from decimal import ROUND_HALF_UP, Decimal, localcontext

from onlyalpha.plugin.api import (
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
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
from onlyalpha_plugin_cn_ashare.reference import OnlyCnAshareBoard, OnlyCnAshareInstrumentReference

_PRICE_LIMITS: dict[str, dict[tuple[OnlyCnAshareBoard, bool], Decimal]] = {
    "2025.1": {
        (OnlyCnAshareBoard.SSE_MAIN, False): Decimal("0.10"),
        (OnlyCnAshareBoard.SSE_MAIN, True): Decimal("0.05"),
        (OnlyCnAshareBoard.SZSE_MAIN, False): Decimal("0.10"),
        (OnlyCnAshareBoard.SZSE_MAIN, True): Decimal("0.05"),
        (OnlyCnAshareBoard.CHINEXT, False): Decimal("0.20"),
        (OnlyCnAshareBoard.CHINEXT, True): Decimal("0.20"),
        (OnlyCnAshareBoard.STAR, False): Decimal("0.20"),
        (OnlyCnAshareBoard.STAR, True): Decimal("0.20"),
    },
    "2026.07": {
        (OnlyCnAshareBoard.SSE_MAIN, False): Decimal("0.10"),
        (OnlyCnAshareBoard.SSE_MAIN, True): Decimal("0.10"),
        (OnlyCnAshareBoard.SZSE_MAIN, False): Decimal("0.10"),
        (OnlyCnAshareBoard.SZSE_MAIN, True): Decimal("0.10"),
        (OnlyCnAshareBoard.CHINEXT, False): Decimal("0.20"),
        (OnlyCnAshareBoard.CHINEXT, True): Decimal("0.20"),
        (OnlyCnAshareBoard.STAR, False): Decimal("0.20"),
        (OnlyCnAshareBoard.STAR, True): Decimal("0.20"),
    },
}
_T1 = OnlySettlementRule(OnlySettlementTiming.T_PLUS_ONE)
_IMMEDIATE = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
_POSITION = OnlyPositionAccountingModel()
_SHORT = OnlyShortSellingRule(OnlyShortSellingMode.DISABLED)


def _session(version: str) -> OnlyTradingSessionModel:
    return OnlyTradingSessionModel(
        f"CN_A_SHARE_DAY@{version}",
        "Asia/Shanghai",
        (
            OnlyTradingSessionDefinition(
                "opening_auction", time(9, 15), time(9, 25), OnlyTradingPhase.OPENING_AUCTION, False
            ),
            OnlyTradingSessionDefinition("pre_open", time(9, 25), time(9, 30), OnlyTradingPhase.PRE_OPEN, False),
            OnlyTradingSessionDefinition("morning", time(9, 30), time(11, 30), OnlyTradingPhase.CONTINUOUS),
            OnlyTradingSessionDefinition("midday_break", time(11, 30), time(13), OnlyTradingPhase.MIDDAY_BREAK, False),
            OnlyTradingSessionDefinition("afternoon", time(13), time(14, 57), OnlyTradingPhase.CONTINUOUS),
            OnlyTradingSessionDefinition(
                "closing_auction", time(14, 57), time(15), OnlyTradingPhase.CLOSING_AUCTION, False
            ),
        ),
    )


@dataclass(frozen=True, slots=True)
class OnlyCnAsharePolicyCompiler:
    product_version: str
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(cls, product_version: str) -> OnlyCnAsharePolicyCompiler:
        if product_version not in _PRICE_LIMITS:
            raise ValueError("UNSUPPORTED_CN_A_SHARE_PRODUCT_VERSION")
        session = _session(product_version)
        fingerprint = only_identity_fingerprint(
            (
                product_version,
                (
                    session.model_id,
                    session.timezone,
                    tuple(
                        (
                            item.name,
                            item.opens_at.isoformat(),
                            item.closes_at.isoformat(),
                            item.phase,
                            item.trading_day_offset,
                            item.allows_orders,
                        )
                        for item in session.sessions
                    ),
                    session.continuous_24x7,
                ),
                (_POSITION.allow_flip, "NETTING", "SHORT_DISABLED"),
                (_SHORT.mode,),
                "CN_A_SHARE_T1",
                tuple(
                    (board.value, st_status, rate)
                    for (board, st_status), rate in sorted(
                        _PRICE_LIMITS[product_version].items(), key=lambda item: (item[0][0].value, item[0][1])
                    )
                ),
            )
        )
        return cls(
            product_version,
            OnlyMarketProductAuthorityIdentity("POLICY_COMPILER", "CN_A_SHARE_CASH", product_version, fingerprint),
        )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day, as_of=request.as_of)
        if not isinstance(reference, OnlyCnAshareInstrumentReference):
            raise TypeError("CN_A_SHARE_REFERENCE_TYPE_REQUIRED")
        rate = _PRICE_LIMITS[self.product_version][reference.board, reference.st_status]
        upper = _round(reference.previous_close * (Decimal(1) + rate), reference.price_tick)
        lower = _round(reference.previous_close * (Decimal(1) - rate), reference.price_tick)
        if upper - reference.previous_close < reference.price_tick:
            upper = reference.previous_close + reference.price_tick
        if reference.previous_close - lower < reference.price_tick:
            lower = reference.previous_close - reference.price_tick
        minimum_buy = Decimal(200) if reference.board is OnlyCnAshareBoard.STAR else Decimal(100)
        buy_increment = Decimal(1) if reference.board is OnlyCnAshareBoard.STAR else Decimal(100)
        status = OnlyInstrumentTradingStatus.SUSPENDED if reference.suspended else OnlyInstrumentTradingStatus.TRADABLE
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms("CNY", Decimal(1), status),
            session_policy=_session(self.product_version),
            price_policy=OnlyCompiledPriceBandPolicy(
                f"CN_A_SHARE_CASH@{self.product_version}:{reference.board.value}:{'RISK_WARNING' if reference.st_status else 'NORMAL'}",
                reference.price_tick,
                reference.previous_close,
                rate,
                lower,
                upper,
                OnlyPriceBandRoundingMode.HALF_UP_TO_TICK,
            ),
            quantity_policy=OnlyCompiledQuantityPolicy(
                minimum_buy, buy_increment, Decimal(1), reference.lot_size, True, None, False
            ),
            position_policy=_POSITION,
            short_policy=_SHORT,
            settlement_policy=OnlySettlementModel("CN_A_SHARE_T1", _T1, _T1, _T1, _IMMEDIATE),
            margin_policy=None,
        )


def _round(value: Decimal, tick: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 34
        return (value / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick


__all__ = ["OnlyCnAsharePolicyCompiler"]
