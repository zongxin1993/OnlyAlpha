"""Binance USD-M reference authority and canonical policy compiler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarginMode, OnlyOrderType, OnlyTimeInForce
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.trading import (
    OnlyCloseScope,
    OnlyExposureConstraint,
    OnlyPositionEffect,
    OnlyPositionMode,
    OnlyReferencePriceKind,
)
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import (
    OnlyCompiledFundingPolicy,
    OnlyCompiledMarginPolicy,
    OnlyCompiledOrderCapabilityPolicy,
    OnlyCompiledValuationPolicy,
    OnlyEconomicModel,
    OnlyMarginIsolationScope,
    OnlyMarginRequirementTier,
)
from onlyalpha.market.models import (
    OnlyCompiledPriceBandPolicy,
    OnlyCompiledQuantityPolicy,
    OnlyMarketPositionMode,
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
)
from onlyalpha.market.product import (
    OnlyCompiledInstrumentMarketTerms,
    OnlyCompiledMarketPolicy,
    OnlyInstrumentTradingStatus,
    OnlyMarketPolicyCompilationRequest,
    OnlyMarketProductAuthorityIdentity,
)


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmReference:
    instrument_id: OnlyInstrumentId
    settlement_currency: str
    contract_multiplier: Decimal
    price_tick: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal | None
    margin_tiers: tuple[OnlyMarginRequirementTier, ...]
    observed_at: datetime
    content_fingerprint: str

    @classmethod
    def create(cls, **values: object) -> OnlyBinanceUsdmReference:
        observed_at = values.get("observed_at")
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            raise ValueError("BINANCE_USDM_REFERENCE_OBSERVED_AT_UTC_REQUIRED")
        values["observed_at"] = observed_at.astimezone(UTC)
        payload = tuple((name, str(value)) for name, value in sorted(values.items()) if name != "observed_at")
        values["content_fingerprint"] = only_identity_fingerprint(payload)
        return cls(**values)  # type: ignore[arg-type]

    def __post_init__(self) -> None:
        if (
            self.price_tick <= 0
            or self.quantity_step <= 0
            or self.minimum_quantity <= 0
            or self.contract_multiplier <= 0
            or not self.margin_tiers
        ):
            raise ValueError("BINANCE_USDM_REFERENCE_INVALID")


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmReferenceAuthority:
    references: tuple[OnlyBinanceUsdmReference, ...]
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(cls, references: tuple[OnlyBinanceUsdmReference, ...]) -> OnlyBinanceUsdmReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: str(item.instrument_id)))
        if len({item.instrument_id for item in ordered}) != len(ordered):
            raise ValueError("BINANCE_USDM_REFERENCE_DUPLICATE")
        fingerprint = only_identity_fingerprint(tuple(item.content_fingerprint for item in ordered))
        return cls(ordered, OnlyMarketProductAuthorityIdentity("REFERENCE", "BINANCE_USDM", "1", fingerprint))

    def resolve(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyBinanceUsdmReference:
        del trading_day
        matches = tuple(item for item in self.references if item.instrument_id == instrument_id)
        if len(matches) != 1:
            raise KeyError("BINANCE_USDM_REFERENCE_NOT_FOUND")
        reference = matches[0]
        if as_of is not None and as_of.astimezone(UTC) < reference.observed_at:
            raise ValueError("BINANCE_USDM_REFERENCE_HISTORICAL_COVERAGE_UNPROVEN")
        return reference


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmPolicyCompiler:
    identity: OnlyMarketProductAuthorityIdentity = OnlyMarketProductAuthorityIdentity(
        "POLICY_COMPILER",
        "BINANCE_USDM",
        "1",
        only_identity_fingerprint(("LINEAR_PERPETUAL", "MARGIN_TIERS", "MARK", "FUNDING", "24X7")),
    )

    def compile(self, request: OnlyMarketPolicyCompilationRequest) -> OnlyCompiledMarketPolicy:
        reference = request.reference_authority.resolve(request.instrument_id, request.trading_day, as_of=request.as_of)
        if not isinstance(reference, OnlyBinanceUsdmReference):
            raise TypeError("BINANCE_USDM_REFERENCE_REQUIRED")
        immediate = OnlySettlementRule(OnlySettlementTiming.IMMEDIATE)
        return OnlyCompiledMarketPolicy.create(
            instrument_id=request.instrument_id,
            trading_day=request.trading_day,
            reference_fingerprint=reference.content_fingerprint,
            compiler=self.identity,
            instrument_terms=OnlyCompiledInstrumentMarketTerms(
                reference.settlement_currency, reference.contract_multiplier, OnlyInstrumentTradingStatus.TRADABLE
            ),
            session_policy=OnlyTradingSessionModel(
                "BINANCE_USDM_24X7",
                "UTC",
                (OnlyTradingSessionDefinition("continuous", time(0), time(0), OnlyTradingPhase.CONTINUOUS),),
                True,
            ),
            price_policy=OnlyCompiledPriceBandPolicy(
                "BINANCE_USDM_STATIC@1",
                reference.price_tick,
                None,
                None,
                None,
                None,
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
            ),
            position_policy=OnlyPositionAccountingModel(OnlyMarketPositionMode.NETTING),
            short_policy=OnlyShortSellingRule(OnlyShortSellingMode.ENABLED_UNRESTRICTED),
            settlement_policy=OnlySettlementModel(
                "BINANCE_USDM_CONTINUOUS", immediate, immediate, immediate, immediate
            ),
            margin_policy=None,
            economic_model=OnlyEconomicModel.MARGINED_DERIVATIVE,
            order_capability_policy=OnlyCompiledOrderCapabilityPolicy(
                (OnlyOrderType.LIMIT,),
                (OnlyTimeInForce.GTC,),
                (OnlyPositionEffect.OPEN, OnlyPositionEffect.CLOSE),
                (OnlyCloseScope.ANY,),
                (OnlyExposureConstraint.NONE, OnlyExposureConstraint.REDUCE_ONLY),
                (OnlyPositionMode.NETTING, OnlyPositionMode.HEDGING),
            ),
            compiled_margin_policy=OnlyCompiledMarginPolicy(
                OnlyMarginMode.CROSS,
                reference.settlement_currency,
                OnlyMarginIsolationScope.ACCOUNT,
                OnlyReferencePriceKind.MARK,
                reference.margin_tiers,
            ),
            valuation_policy=OnlyCompiledValuationPolicy(OnlyReferencePriceKind.MARK, OnlyReferencePriceKind.MARK),
            funding_policy=OnlyCompiledFundingPolicy(8 * 60 * 60, OnlyReferencePriceKind.MARK),
        )


__all__ = [
    "OnlyBinanceUsdmPolicyCompiler",
    "OnlyBinanceUsdmReference",
    "OnlyBinanceUsdmReferenceAuthority",
]
