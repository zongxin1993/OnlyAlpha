"""Immutable Binance Spot semantic reference and exact authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.plugin.api import (
    OnlyInstrumentId,
    OnlyMarketProductAuthorityIdentity,
    OnlyMarketProductResolutionError,
    OnlyTradingDay,
    only_identity_fingerprint,
)
from onlyalpha_market_binance_spot.capability import OnlyBinanceSpotCompatibilityStatus


@dataclass(frozen=True, slots=True, order=True)
class OnlyBinanceSpotRule:
    rule_type: str
    category: str
    values: tuple[tuple[str, str | bool | int], ...]

    def canonical_identity(self) -> tuple[object, ...]:
        return (self.rule_type, self.category, self.values)


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReference:
    instrument_id: OnlyInstrumentId
    raw_symbol: str
    base_currency: str
    quote_currency: str
    provider_status: str
    spot_trading_allowed: bool
    price_tick: Decimal
    minimum_price: Decimal | None
    maximum_price: Decimal | None
    quantity_step: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal | None
    market_quantity_step: Decimal | None
    market_minimum_quantity: Decimal | None
    market_maximum_quantity: Decimal | None
    minimum_notional: Decimal | None
    maximum_notional: Decimal | None
    venue_order_types: tuple[str, ...]
    time_in_force: tuple[str, ...]
    order_group_capabilities: tuple[str, ...]
    default_stp_mode: str
    allowed_stp_modes: tuple[str, ...]
    permission_sets: tuple[tuple[str, ...], ...]
    capabilities: tuple[tuple[str, bool], ...]
    rules: tuple[OnlyBinanceSpotRule, ...]
    source_raw_fingerprints: tuple[str, ...]
    compatibility_status: OnlyBinanceSpotCompatibilityStatus
    observed_at: datetime
    content_fingerprint: str

    @classmethod
    def create(cls, **values: object) -> OnlyBinanceSpotReference:
        observed_at = values.pop("observed_at")
        if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
            raise ValueError("BINANCE_SPOT_OBSERVED_AT_UTC_REQUIRED")
        values["observed_at"] = observed_at.astimezone(UTC)
        payload = cls._semantic_payload(values)
        values["content_fingerprint"] = only_identity_fingerprint(payload)
        return cls(**values)  # type: ignore[arg-type]

    @staticmethod
    def _semantic_payload(values: dict[str, object]) -> tuple[object, ...]:
        return tuple(
            (name, str(values[name]) if name == "instrument_id" else values[name])
            for name in sorted(values)
            if name not in {"observed_at", "source_raw_fingerprints", "content_fingerprint"}
        )

    def semantic_payload(self) -> tuple[object, ...]:
        return self._semantic_payload({name: getattr(self, name) for name in self.__dataclass_fields__})

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("BINANCE_SPOT_OBSERVED_AT_UTC_REQUIRED")
        if self.price_tick <= 0 or self.quantity_step <= 0 or self.minimum_quantity <= 0:
            raise ValueError("BINANCE_SPOT_STATIC_RULE_INVALID")
        if self.content_fingerprint != only_identity_fingerprint(self.semantic_payload()):
            raise ValueError("BINANCE_SPOT_REFERENCE_FINGERPRINT_CONFLICT")

    @property
    def trade_eligible(self) -> bool:
        return (
            self.compatibility_status is OnlyBinanceSpotCompatibilityStatus.COMPATIBLE
            and self.provider_status == "TRADING"
            and self.spot_trading_allowed
            and any("SPOT" in alternatives for alternatives in self.permission_sets)
        )


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferenceAuthority:
    references: tuple[OnlyBinanceSpotReference, ...]
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(cls, references: tuple[OnlyBinanceSpotReference, ...]) -> OnlyBinanceSpotReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: str(item.instrument_id)))
        if len({item.instrument_id for item in ordered}) != len(ordered):
            raise ValueError("BINANCE_SPOT_REFERENCE_DUPLICATE_INSTRUMENT")
        fingerprint = only_identity_fingerprint(tuple(item.content_fingerprint for item in ordered))
        return cls(ordered, OnlyMarketProductAuthorityIdentity("REFERENCE", "BINANCE_SPOT", "1", fingerprint))

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> OnlyBinanceSpotReference:
        matches = tuple(item for item in self.references if item.instrument_id == instrument_id)
        if len(matches) != 1:
            raise OnlyMarketProductResolutionError("BINANCE_SPOT_REFERENCE_NOT_FOUND", str(instrument_id))
        reference = matches[0]
        # A day-only contract cannot prove observations earlier on the capture day.
        if trading_day.value <= reference.observed_at.date():
            raise OnlyMarketProductResolutionError(
                "BINANCE_SPOT_REFERENCE_HISTORICAL_COVERAGE_UNPROVEN", trading_day.value.isoformat()
            )
        return reference


__all__ = [name for name in globals() if name.startswith("Only")]
