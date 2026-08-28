"""Immutable Binance Spot semantic reference and exact authority."""

from __future__ import annotations

from collections.abc import Mapping
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
    minimum_notional_applies_to_market: bool
    maximum_notional_applies_to_market: bool
    notional_reference_window_minutes: int
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
        if self.notional_reference_window_minutes < 0:
            raise ValueError("BINANCE_SPOT_NOTIONAL_WINDOW_INVALID")
        if self.content_fingerprint != only_identity_fingerprint(self.semantic_payload()):
            raise ValueError("BINANCE_SPOT_REFERENCE_FINGERPRINT_CONFLICT")

    @property
    def venue_spot_supported(self) -> bool:
        """Public venue semantics only; this does not prove private-account eligibility."""

        return self.spot_trading_allowed

    @property
    def market_product_eligible(self) -> bool:
        return (
            self.compatibility_status is OnlyBinanceSpotCompatibilityStatus.COMPATIBLE
            and self.provider_status == "TRADING"
            and self.venue_spot_supported
        )

    def to_semantic_dict(self) -> dict[str, object]:
        return {
            "instrument_id": str(self.instrument_id),
            "raw_symbol": self.raw_symbol,
            "base_currency": self.base_currency,
            "quote_currency": self.quote_currency,
            "provider_status": self.provider_status,
            "spot_trading_allowed": self.spot_trading_allowed,
            "price_tick": str(self.price_tick),
            "minimum_price": _decimal_text(self.minimum_price),
            "maximum_price": _decimal_text(self.maximum_price),
            "quantity_step": str(self.quantity_step),
            "minimum_quantity": str(self.minimum_quantity),
            "maximum_quantity": _decimal_text(self.maximum_quantity),
            "market_quantity_step": _decimal_text(self.market_quantity_step),
            "market_minimum_quantity": _decimal_text(self.market_minimum_quantity),
            "market_maximum_quantity": _decimal_text(self.market_maximum_quantity),
            "minimum_notional": _decimal_text(self.minimum_notional),
            "maximum_notional": _decimal_text(self.maximum_notional),
            "minimum_notional_applies_to_market": self.minimum_notional_applies_to_market,
            "maximum_notional_applies_to_market": self.maximum_notional_applies_to_market,
            "notional_reference_window_minutes": self.notional_reference_window_minutes,
            "venue_order_types": list(self.venue_order_types),
            "time_in_force": list(self.time_in_force),
            "order_group_capabilities": list(self.order_group_capabilities),
            "default_stp_mode": self.default_stp_mode,
            "allowed_stp_modes": list(self.allowed_stp_modes),
            "permission_sets": [list(item) for item in self.permission_sets],
            "capabilities": [[name, supported] for name, supported in self.capabilities],
            "rules": [_rule_dict(item) for item in self.rules],
            "compatibility_status": self.compatibility_status.value,
            "content_fingerprint": self.content_fingerprint,
        }

    @classmethod
    def from_semantic_dict(cls, raw: Mapping[str, object], *, observed_at: datetime) -> OnlyBinanceSpotReference:
        expected = set(cls._semantic_field_names()) | {"content_fingerprint"}
        if set(raw) != expected:
            raise ValueError("BINANCE_SPOT_SEMANTIC_REFERENCE_SCHEMA_INVALID")
        reference = cls.create(
            instrument_id=OnlyInstrumentId.parse(_text(raw, "instrument_id")),
            raw_symbol=_text(raw, "raw_symbol"),
            base_currency=_text(raw, "base_currency"),
            quote_currency=_text(raw, "quote_currency"),
            provider_status=_text(raw, "provider_status"),
            spot_trading_allowed=_boolean(raw, "spot_trading_allowed"),
            price_tick=_decimal(raw, "price_tick"),
            minimum_price=_optional_decimal(raw, "minimum_price"),
            maximum_price=_optional_decimal(raw, "maximum_price"),
            quantity_step=_decimal(raw, "quantity_step"),
            minimum_quantity=_decimal(raw, "minimum_quantity"),
            maximum_quantity=_optional_decimal(raw, "maximum_quantity"),
            market_quantity_step=_optional_decimal(raw, "market_quantity_step"),
            market_minimum_quantity=_optional_decimal(raw, "market_minimum_quantity"),
            market_maximum_quantity=_optional_decimal(raw, "market_maximum_quantity"),
            minimum_notional=_optional_decimal(raw, "minimum_notional"),
            maximum_notional=_optional_decimal(raw, "maximum_notional"),
            minimum_notional_applies_to_market=_boolean(raw, "minimum_notional_applies_to_market"),
            maximum_notional_applies_to_market=_boolean(raw, "maximum_notional_applies_to_market"),
            notional_reference_window_minutes=_integer(raw, "notional_reference_window_minutes"),
            venue_order_types=_text_tuple(raw, "venue_order_types"),
            time_in_force=_text_tuple(raw, "time_in_force"),
            order_group_capabilities=_text_tuple(raw, "order_group_capabilities"),
            default_stp_mode=_text(raw, "default_stp_mode"),
            allowed_stp_modes=_text_tuple(raw, "allowed_stp_modes"),
            permission_sets=_nested_text_tuple(raw, "permission_sets"),
            capabilities=_capabilities(raw),
            rules=_rules(raw),
            source_raw_fingerprints=(),
            compatibility_status=OnlyBinanceSpotCompatibilityStatus(_text(raw, "compatibility_status")),
            observed_at=observed_at,
        )
        if reference.content_fingerprint != _text(raw, "content_fingerprint"):
            raise ValueError("BINANCE_SPOT_REFERENCE_FINGERPRINT_CONFLICT")
        return reference

    @staticmethod
    def _semantic_field_names() -> tuple[str, ...]:
        return tuple(
            name
            for name in OnlyBinanceSpotReference.__dataclass_fields__
            if name not in {"observed_at", "source_raw_fingerprints"}
        )


@dataclass(frozen=True, slots=True)
class OnlyBinanceSpotReferenceAuthority:
    exchange_rules: tuple[OnlyBinanceSpotRule, ...]
    references: tuple[OnlyBinanceSpotReference, ...]
    compatibility_status: OnlyBinanceSpotCompatibilityStatus
    identity: OnlyMarketProductAuthorityIdentity

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.references, key=lambda item: str(item.instrument_id)))
        ordered_rules = tuple(sorted(self.exchange_rules))
        fingerprint = only_identity_fingerprint(
            (
                tuple(item.canonical_identity() for item in ordered_rules),
                tuple(item.content_fingerprint for item in ordered),
            )
        )
        status = (
            OnlyBinanceSpotCompatibilityStatus.COMPATIBLE
            if all(item.category != "UNKNOWN_CRITICAL" for item in ordered_rules)
            else OnlyBinanceSpotCompatibilityStatus.INCOMPATIBLE
        )
        if (
            self.references != ordered
            or self.exchange_rules != ordered_rules
            or self.compatibility_status is not status
            or self.identity != OnlyMarketProductAuthorityIdentity("REFERENCE", "BINANCE_SPOT", "2", fingerprint)
        ):
            raise ValueError("BINANCE_SPOT_REFERENCE_AUTHORITY_FINGERPRINT_CONFLICT")

    @classmethod
    def create(
        cls,
        references: tuple[OnlyBinanceSpotReference, ...],
        exchange_rules: tuple[OnlyBinanceSpotRule, ...] = (),
    ) -> OnlyBinanceSpotReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: str(item.instrument_id)))
        ordered_rules = tuple(sorted(exchange_rules))
        if len({item.instrument_id for item in ordered}) != len(ordered):
            raise ValueError("BINANCE_SPOT_REFERENCE_DUPLICATE_INSTRUMENT")
        fingerprint = only_identity_fingerprint(
            (
                tuple(item.canonical_identity() for item in ordered_rules),
                tuple(item.content_fingerprint for item in ordered),
            )
        )
        compatible = all(item.category != "UNKNOWN_CRITICAL" for item in ordered_rules)
        status = (
            OnlyBinanceSpotCompatibilityStatus.COMPATIBLE
            if compatible
            else OnlyBinanceSpotCompatibilityStatus.INCOMPATIBLE
        )
        return cls(
            ordered_rules,
            ordered,
            status,
            OnlyMarketProductAuthorityIdentity("REFERENCE", "BINANCE_SPOT", "2", fingerprint),
        )

    def resolve(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyBinanceSpotReference:
        if self.compatibility_status is OnlyBinanceSpotCompatibilityStatus.INCOMPATIBLE:
            raise OnlyMarketProductResolutionError(
                "BINANCE_SPOT_EXCHANGE_RULE_AUTHORITY_INCOMPATIBLE", "unknown exchange-level rule"
            )
        matches = tuple(item for item in self.references if item.instrument_id == instrument_id)
        if len(matches) != 1:
            raise OnlyMarketProductResolutionError("BINANCE_SPOT_REFERENCE_NOT_FOUND", str(instrument_id))
        reference = matches[0]
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise OnlyMarketProductResolutionError("BINANCE_SPOT_AS_OF_UTC_REQUIRED", str(as_of))
            if as_of.astimezone(UTC) < reference.observed_at:
                raise OnlyMarketProductResolutionError(
                    "BINANCE_SPOT_REFERENCE_HISTORICAL_COVERAGE_UNPROVEN", as_of.astimezone(UTC).isoformat()
                )
        elif trading_day.value <= reference.observed_at.date():
            raise OnlyMarketProductResolutionError(
                "BINANCE_SPOT_REFERENCE_HISTORICAL_COVERAGE_UNPROVEN", trading_day.value.isoformat()
            )
        return reference

    def to_semantic_dict(self) -> dict[str, object]:
        return {
            "semantic_schema_version": 1,
            "authority_fingerprint": self.identity.authority_fingerprint,
            "authority_version": self.identity.authority_version,
            "compatibility_status": self.compatibility_status.value,
            "exchange_rules": [_rule_dict(item) for item in self.exchange_rules],
            "references": [item.to_semantic_dict() for item in self.references],
        }

    @classmethod
    def from_semantic_dict(
        cls, raw: Mapping[str, object], *, observed_at: datetime
    ) -> OnlyBinanceSpotReferenceAuthority:
        if (
            set(raw)
            != {
                "semantic_schema_version",
                "authority_fingerprint",
                "authority_version",
                "compatibility_status",
                "exchange_rules",
                "references",
            }
            or raw["semantic_schema_version"] != 1
        ):
            raise ValueError("BINANCE_SPOT_SEMANTIC_AUTHORITY_SCHEMA_INVALID")
        references_raw = raw["references"]
        if not isinstance(references_raw, list) or not all(isinstance(item, dict) for item in references_raw):
            raise ValueError("BINANCE_SPOT_SEMANTIC_REFERENCES_INVALID")
        authority = cls.create(
            tuple(
                OnlyBinanceSpotReference.from_semantic_dict(item, observed_at=observed_at) for item in references_raw
            ),
            _rules_from_value(raw["exchange_rules"]),
        )
        if (
            authority.identity.authority_fingerprint != _text(raw, "authority_fingerprint")
            or authority.identity.authority_version != _text(raw, "authority_version")
            or authority.compatibility_status.value != _text(raw, "compatibility_status")
        ):
            raise ValueError("BINANCE_SPOT_AUTHORITY_FINGERPRINT_CONFLICT")
        return authority


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _text(raw: Mapping[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"BINANCE_SPOT_SEMANTIC_{name.upper()}_INVALID")
    return value


def _boolean(raw: Mapping[str, object], name: str) -> bool:
    value = raw.get(name)
    if not isinstance(value, bool):
        raise ValueError(f"BINANCE_SPOT_SEMANTIC_{name.upper()}_INVALID")
    return value


def _integer(raw: Mapping[str, object], name: str) -> int:
    value = raw.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"BINANCE_SPOT_SEMANTIC_{name.upper()}_INVALID")
    return value


def _decimal(raw: Mapping[str, object], name: str) -> Decimal:
    return Decimal(_text(raw, name))


def _optional_decimal(raw: Mapping[str, object], name: str) -> Decimal | None:
    value = raw.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"BINANCE_SPOT_SEMANTIC_{name.upper()}_INVALID")
    return Decimal(value)


def _text_tuple(raw: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = raw.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"BINANCE_SPOT_SEMANTIC_{name.upper()}_INVALID")
    return tuple(value)


def _nested_text_tuple(raw: Mapping[str, object], name: str) -> tuple[tuple[str, ...], ...]:
    value = raw.get(name)
    if not isinstance(value, list) or not all(
        isinstance(item, list) and all(isinstance(part, str) for part in item) for item in value
    ):
        raise ValueError(f"BINANCE_SPOT_SEMANTIC_{name.upper()}_INVALID")
    return tuple(tuple(item) for item in value)


def _capabilities(raw: Mapping[str, object]) -> tuple[tuple[str, bool], ...]:
    value = raw.get("capabilities")
    if not isinstance(value, list):
        raise ValueError("BINANCE_SPOT_SEMANTIC_CAPABILITIES_INVALID")
    result: list[tuple[str, bool]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], bool)
        ):
            raise ValueError("BINANCE_SPOT_SEMANTIC_CAPABILITIES_INVALID")
        result.append((item[0], item[1]))
    return tuple(result)


def _rule_dict(rule: OnlyBinanceSpotRule) -> dict[str, object]:
    return {"rule_type": rule.rule_type, "category": rule.category, "values": [list(item) for item in rule.values]}


def _rules(raw: Mapping[str, object]) -> tuple[OnlyBinanceSpotRule, ...]:
    return _rules_from_value(raw.get("rules"))


def _rules_from_value(value: object) -> tuple[OnlyBinanceSpotRule, ...]:
    if not isinstance(value, list):
        raise ValueError("BINANCE_SPOT_SEMANTIC_RULES_INVALID")
    result: list[OnlyBinanceSpotRule] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"rule_type", "category", "values"}:
            raise ValueError("BINANCE_SPOT_SEMANTIC_RULE_INVALID")
        values = item["values"]
        if not isinstance(values, list):
            raise ValueError("BINANCE_SPOT_SEMANTIC_RULE_VALUES_INVALID")
        pairs: list[tuple[str, str | bool | int]] = []
        for pair in values:
            if (
                not isinstance(pair, list)
                or len(pair) != 2
                or not isinstance(pair[0], str)
                or not isinstance(pair[1], (str, bool, int))
            ):
                raise ValueError("BINANCE_SPOT_SEMANTIC_RULE_VALUES_INVALID")
            pairs.append((pair[0], pair[1]))
        result.append(OnlyBinanceSpotRule(_text(item, "rule_type"), _text(item, "category"), tuple(pairs)))
    return tuple(result)


__all__ = [name for name in globals() if name.startswith("Only")]
