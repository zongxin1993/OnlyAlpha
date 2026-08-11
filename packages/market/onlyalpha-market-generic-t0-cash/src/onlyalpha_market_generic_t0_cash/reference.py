"""Generic-owned reference model and deterministic resolution authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from onlyalpha.plugin.api import (
    OnlyAssetClass,
    OnlyInstrumentId,
    OnlyMarketProductAuthorityIdentity,
    OnlyMarketProductResolutionError,
    OnlyTradingDay,
    only_canonical_fingerprint,
)


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashReference:
    instrument_id: OnlyInstrumentId
    asset_class: OnlyAssetClass
    settlement_currency: str
    contract_multiplier: Decimal
    tick_size: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal | None
    maximum_quantity: Decimal | None
    effective_from: date
    effective_to: date | None
    active: bool
    suspended: bool
    content_fingerprint: str

    @classmethod
    def create(
        cls,
        *,
        instrument_id: OnlyInstrumentId,
        asset_class: OnlyAssetClass,
        settlement_currency: str,
        contract_multiplier: Decimal,
        tick_size: Decimal,
        quantity_step: Decimal,
        minimum_quantity: Decimal | None = None,
        maximum_quantity: Decimal | None = None,
        effective_from: date = date(1970, 1, 1),
        effective_to: date | None = None,
        active: bool = True,
        suspended: bool = False,
    ) -> OnlyGenericT0CashReference:
        payload = (
            instrument_id,
            asset_class,
            settlement_currency,
            contract_multiplier,
            tick_size,
            quantity_step,
            minimum_quantity,
            maximum_quantity,
            effective_from,
            effective_to,
            active,
            suspended,
        )
        return cls(*payload, only_canonical_fingerprint(payload))

    def __post_init__(self) -> None:
        if self.asset_class not in {OnlyAssetClass.EQUITY, OnlyAssetClass.FUND}:
            raise ValueError("GENERIC_T0_CASH_REFERENCE_ASSET_CLASS_UNSUPPORTED")
        if not self.settlement_currency.strip():
            raise ValueError("settlement currency cannot be empty")
        if self.contract_multiplier <= 0 or self.tick_size <= 0 or self.quantity_step <= 0:
            raise ValueError("reference multiplier, tick, and quantity step must be positive")
        if self.minimum_quantity is not None and self.minimum_quantity <= 0:
            raise ValueError("minimum quantity must be positive")
        if self.maximum_quantity is not None and self.maximum_quantity <= 0:
            raise ValueError("maximum quantity must be positive")
        if (
            self.minimum_quantity is not None
            and self.maximum_quantity is not None
            and self.maximum_quantity < self.minimum_quantity
        ):
            raise ValueError("maximum quantity cannot be less than minimum quantity")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("reference effective range must increase")
        payload = (
            self.instrument_id,
            self.asset_class,
            self.settlement_currency,
            self.contract_multiplier,
            self.tick_size,
            self.quantity_step,
            self.minimum_quantity,
            self.maximum_quantity,
            self.effective_from,
            self.effective_to,
            self.active,
            self.suspended,
        )
        if self.content_fingerprint != only_canonical_fingerprint(payload):
            raise ValueError("GENERIC_T0_CASH_REFERENCE_FINGERPRINT_CONFLICT")


@dataclass(frozen=True, slots=True)
class OnlyGenericT0CashReferenceAuthority:
    authority_id: str
    authority_version: str
    references: tuple[OnlyGenericT0CashReference, ...]
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(
        cls,
        *,
        authority_id: str,
        authority_version: str,
        references: tuple[OnlyGenericT0CashReference, ...],
    ) -> OnlyGenericT0CashReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: (str(item.instrument_id), item.effective_from)))
        fingerprint = only_canonical_fingerprint(tuple(item.content_fingerprint for item in ordered))
        identity = OnlyMarketProductAuthorityIdentity(
            "REFERENCE",
            authority_id,
            authority_version,
            fingerprint,
        )
        return cls(authority_id, authority_version, ordered, identity)

    def __post_init__(self) -> None:
        expected = only_canonical_fingerprint(tuple(item.content_fingerprint for item in self.references))
        if self.identity.authority_kind != "REFERENCE":
            raise ValueError("GENERIC_T0_CASH_REFERENCE_AUTHORITY_KIND_INVALID")
        if (self.identity.authority_id, self.identity.authority_version) != (
            self.authority_id,
            self.authority_version,
        ):
            raise ValueError("GENERIC_T0_CASH_REFERENCE_AUTHORITY_IDENTITY_CONFLICT")
        if self.identity.authority_fingerprint != expected:
            raise ValueError("GENERIC_T0_CASH_REFERENCE_AUTHORITY_FINGERPRINT_CONFLICT")

    def resolve(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
    ) -> OnlyGenericT0CashReference:
        matches = tuple(
            item
            for item in self.references
            if item.instrument_id == instrument_id
            and item.effective_from <= trading_day.value
            and (item.effective_to is None or trading_day.value < item.effective_to)
        )
        if not matches:
            raise OnlyMarketProductResolutionError(
                "GENERIC_T0_CASH_REFERENCE_NOT_FOUND",
                f"no effective reference for {instrument_id} on {trading_day.value.isoformat()}",
            )
        if len(matches) > 1:
            raise OnlyMarketProductResolutionError(
                "GENERIC_T0_CASH_REFERENCE_AMBIGUOUS",
                f"multiple effective references for {instrument_id} on {trading_day.value.isoformat()}",
            )
        return matches[0]


__all__ = ["OnlyGenericT0CashReference", "OnlyGenericT0CashReferenceAuthority"]
