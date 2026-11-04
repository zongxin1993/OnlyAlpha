"""Verified operator resource document loader for Binance USD-M Backtest."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.trading import OnlyPositionMode, OnlyReferencePriceKind
from onlyalpha.market.economics import OnlyAccountEffectiveTradingInputs, OnlyMarginRequirementSegment

from .reference import (
    OnlyBinanceUsdmAccountReferenceAuthority,
    OnlyBinanceUsdmAccountTradingReference,
    OnlyBinanceUsdmFundingScheduleReference,
    OnlyBinanceUsdmPublicMarketReference,
    OnlyBinanceUsdmPublicReferenceAuthority,
)

_PUBLIC_FIELDS = {
    "instrument_id",
    "raw_symbol",
    "provider_status",
    "settlement_currency",
    "contract_multiplier",
    "price_tick",
    "minimum_price",
    "maximum_price",
    "quantity_step",
    "minimum_quantity",
    "maximum_quantity",
    "minimum_notional",
    "funding_schedule",
    "coverage_start",
    "coverage_end",
    "observed_at",
    "published_at",
    "provider_revision",
    "normalizer_semantic_version",
    "provider_schema_semantic_version",
    "source_raw_fingerprints",
    "content_fingerprint",
}
_ACCOUNT_FIELDS = {
    "instrument_id",
    "effective_inputs",
    "margin_segments",
    "coverage_start",
    "coverage_end",
    "observed_at",
    "provider_revision",
    "normalizer_semantic_version",
    "provider_schema_semantic_version",
    "source_raw_fingerprints",
    "content_fingerprint",
}


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmBacktestResourceProvider:
    provider_id: str = "onlyalpha-plugin-binance-usdm/reference@1"

    def load_reference(
        self, payload: Mapping[str, object]
    ) -> OnlyBinanceUsdmPublicReferenceAuthority | OnlyBinanceUsdmAccountReferenceAuthority:
        if set(payload) != {"kind", "authority_fingerprint", "references"}:
            raise ValueError("BINANCE_USDM_BACKTEST_RESOURCE_SCHEMA_INVALID")
        fingerprint = _text(payload, "authority_fingerprint")
        raw_references = payload["references"]
        if (
            not isinstance(raw_references, list)
            or not raw_references
            or not all(isinstance(item, dict) for item in raw_references)
        ):
            raise ValueError("BINANCE_USDM_BACKTEST_RESOURCE_REFERENCES_INVALID")
        authority: OnlyBinanceUsdmPublicReferenceAuthority | OnlyBinanceUsdmAccountReferenceAuthority
        if payload["kind"] == "PUBLIC":
            authority = OnlyBinanceUsdmPublicReferenceAuthority.create(tuple(_public(item) for item in raw_references))
        elif payload["kind"] == "ACCOUNT":
            authority = OnlyBinanceUsdmAccountReferenceAuthority.create(
                tuple(_account(item) for item in raw_references)
            )
        else:
            raise ValueError("BINANCE_USDM_BACKTEST_RESOURCE_KIND_INVALID")
        if authority.identity.authority_fingerprint != fingerprint:
            raise ValueError("BINANCE_USDM_BACKTEST_RESOURCE_FINGERPRINT_CONFLICT")
        return authority

    def dump_reference(
        self, authority: OnlyBinanceUsdmPublicReferenceAuthority | OnlyBinanceUsdmAccountReferenceAuthority
    ) -> dict[str, object]:
        if isinstance(authority, OnlyBinanceUsdmPublicReferenceAuthority):
            return {
                "kind": "PUBLIC",
                "authority_fingerprint": authority.identity.authority_fingerprint,
                "references": [_dump_public(item) for item in authority.references],
            }
        return {
            "kind": "ACCOUNT",
            "authority_fingerprint": authority.identity.authority_fingerprint,
            "references": [_dump_account(item) for item in authority.references],
        }


def _public(raw: Mapping[str, object]) -> OnlyBinanceUsdmPublicMarketReference:
    if set(raw) != _PUBLIC_FIELDS:
        raise ValueError("BINANCE_USDM_PUBLIC_RESOURCE_SCHEMA_INVALID")
    schedule = raw["funding_schedule"]
    if not isinstance(schedule, dict) or set(schedule) != {
        "interval_seconds",
        "boundary_offset_seconds",
        "valuation_price_kind",
        "provider_semantic_version",
    }:
        raise ValueError("BINANCE_USDM_FUNDING_SCHEDULE_RESOURCE_INVALID")
    reference = OnlyBinanceUsdmPublicMarketReference.create(
        instrument_id=OnlyInstrumentId.parse(_text(raw, "instrument_id")),
        raw_symbol=_text(raw, "raw_symbol"),
        provider_status=_text(raw, "provider_status"),
        settlement_currency=_text(raw, "settlement_currency"),
        contract_multiplier=_decimal(raw, "contract_multiplier"),
        price_tick=_decimal(raw, "price_tick"),
        minimum_price=_optional_decimal(raw, "minimum_price"),
        maximum_price=_optional_decimal(raw, "maximum_price"),
        quantity_step=_decimal(raw, "quantity_step"),
        minimum_quantity=_decimal(raw, "minimum_quantity"),
        maximum_quantity=_optional_decimal(raw, "maximum_quantity"),
        minimum_notional=_optional_decimal(raw, "minimum_notional"),
        funding_schedule=OnlyBinanceUsdmFundingScheduleReference(
            _integer(schedule, "interval_seconds"),
            _integer(schedule, "boundary_offset_seconds"),
            OnlyReferencePriceKind(_text(schedule, "valuation_price_kind")),
            _text(schedule, "provider_semantic_version"),
        ),
        coverage_start=_datetime(raw, "coverage_start"),
        coverage_end=_optional_datetime(raw, "coverage_end"),
        observed_at=_datetime(raw, "observed_at"),
        published_at=_datetime(raw, "published_at"),
        provider_revision=_text(raw, "provider_revision"),
        normalizer_semantic_version=_text(raw, "normalizer_semantic_version"),
        provider_schema_semantic_version=_text(raw, "provider_schema_semantic_version"),
        source_raw_fingerprints=_text_tuple(raw, "source_raw_fingerprints"),
    )
    if reference.content_fingerprint != _text(raw, "content_fingerprint"):
        raise ValueError("BINANCE_USDM_PUBLIC_RESOURCE_FINGERPRINT_CONFLICT")
    return reference


def _account(raw: Mapping[str, object]) -> OnlyBinanceUsdmAccountTradingReference:
    if set(raw) != _ACCOUNT_FIELDS:
        raise ValueError("BINANCE_USDM_ACCOUNT_RESOURCE_SCHEMA_INVALID")
    effective = raw["effective_inputs"]
    segments = raw["margin_segments"]
    if not isinstance(effective, dict) or set(effective) != {
        "position_mode",
        "margin_mode",
        "leverage",
        "source_fingerprint",
    }:
        raise ValueError("BINANCE_USDM_ACCOUNT_EFFECTIVE_RESOURCE_INVALID")
    if not isinstance(segments, list) or not segments or not all(isinstance(item, dict) for item in segments):
        raise ValueError("BINANCE_USDM_MARGIN_SEGMENT_RESOURCE_INVALID")
    reference = OnlyBinanceUsdmAccountTradingReference.create(
        instrument_id=OnlyInstrumentId.parse(_text(raw, "instrument_id")),
        effective_inputs=OnlyAccountEffectiveTradingInputs(
            OnlyPositionMode(_text(effective, "position_mode")),
            OnlyMarginMode(_text(effective, "margin_mode")),
            _decimal(effective, "leverage"),
            _text(effective, "source_fingerprint"),
        ),
        margin_segments=tuple(_segment(item) for item in segments),
        coverage_start=_datetime(raw, "coverage_start"),
        coverage_end=_optional_datetime(raw, "coverage_end"),
        observed_at=_datetime(raw, "observed_at"),
        provider_revision=_text(raw, "provider_revision"),
        normalizer_semantic_version=_text(raw, "normalizer_semantic_version"),
        provider_schema_semantic_version=_text(raw, "provider_schema_semantic_version"),
        source_raw_fingerprints=_text_tuple(raw, "source_raw_fingerprints"),
    )
    if reference.content_fingerprint != _text(raw, "content_fingerprint"):
        raise ValueError("BINANCE_USDM_ACCOUNT_RESOURCE_FINGERPRINT_CONFLICT")
    return reference


def _segment(raw: Mapping[str, object]) -> OnlyMarginRequirementSegment:
    fields = {
        "lower_bound",
        "upper_bound",
        "initial_slope",
        "initial_intercept",
        "maintenance_slope",
        "maintenance_intercept",
    }
    if set(raw) != fields:
        raise ValueError("BINANCE_USDM_MARGIN_SEGMENT_RESOURCE_INVALID")
    return OnlyMarginRequirementSegment(
        _decimal(raw, "lower_bound"),
        _optional_decimal(raw, "upper_bound"),
        _decimal(raw, "initial_slope"),
        _decimal(raw, "initial_intercept"),
        _decimal(raw, "maintenance_slope"),
        _decimal(raw, "maintenance_intercept"),
    )


def _dump_public(item: OnlyBinanceUsdmPublicMarketReference) -> dict[str, object]:
    schedule = item.funding_schedule
    return {
        "instrument_id": str(item.instrument_id),
        "raw_symbol": item.raw_symbol,
        "provider_status": item.provider_status,
        "settlement_currency": item.settlement_currency,
        "contract_multiplier": str(item.contract_multiplier),
        "price_tick": str(item.price_tick),
        "minimum_price": _decimal_text(item.minimum_price),
        "maximum_price": _decimal_text(item.maximum_price),
        "quantity_step": str(item.quantity_step),
        "minimum_quantity": str(item.minimum_quantity),
        "maximum_quantity": _decimal_text(item.maximum_quantity),
        "minimum_notional": _decimal_text(item.minimum_notional),
        "funding_schedule": {
            "interval_seconds": schedule.interval_seconds,
            "boundary_offset_seconds": schedule.boundary_offset_seconds,
            "valuation_price_kind": schedule.valuation_price_kind.value,
            "provider_semantic_version": schedule.provider_semantic_version,
        },
        "coverage_start": item.coverage_start.isoformat(),
        "coverage_end": None if item.coverage_end is None else item.coverage_end.isoformat(),
        "observed_at": item.observed_at.isoformat(),
        "published_at": item.published_at.isoformat(),
        "provider_revision": item.provider_revision,
        "normalizer_semantic_version": item.normalizer_semantic_version,
        "provider_schema_semantic_version": item.provider_schema_semantic_version,
        "source_raw_fingerprints": list(item.source_raw_fingerprints),
        "content_fingerprint": item.content_fingerprint,
    }


def _dump_account(item: OnlyBinanceUsdmAccountTradingReference) -> dict[str, object]:
    effective = item.effective_inputs
    return {
        "instrument_id": str(item.instrument_id),
        "effective_inputs": {
            "position_mode": effective.position_mode.value,
            "margin_mode": effective.margin_mode.value,
            "leverage": str(effective.leverage),
            "source_fingerprint": effective.source_fingerprint,
        },
        "margin_segments": [
            {
                "lower_bound": str(segment.lower_bound),
                "upper_bound": _decimal_text(segment.upper_bound),
                "initial_slope": str(segment.initial_slope),
                "initial_intercept": str(segment.initial_intercept),
                "maintenance_slope": str(segment.maintenance_slope),
                "maintenance_intercept": str(segment.maintenance_intercept),
            }
            for segment in item.margin_segments
        ],
        "coverage_start": item.coverage_start.isoformat(),
        "coverage_end": None if item.coverage_end is None else item.coverage_end.isoformat(),
        "observed_at": item.observed_at.isoformat(),
        "provider_revision": item.provider_revision,
        "normalizer_semantic_version": item.normalizer_semantic_version,
        "provider_schema_semantic_version": item.provider_schema_semantic_version,
        "source_raw_fingerprints": list(item.source_raw_fingerprints),
        "content_fingerprint": item.content_fingerprint,
    }


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _text(raw: Mapping[str, object], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"BINANCE_USDM_RESOURCE_{name.upper()}_INVALID")
    return value


def _integer(raw: Mapping[str, object], name: str) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"BINANCE_USDM_RESOURCE_{name.upper()}_INVALID")
    return value


def _decimal(raw: Mapping[str, object], name: str) -> Decimal:
    return Decimal(_text(raw, name))


def _optional_decimal(raw: Mapping[str, object], name: str) -> Decimal | None:
    value = raw.get(name)
    return None if value is None else Decimal(_text(raw, name))


def _datetime(raw: Mapping[str, object], name: str) -> datetime:
    return datetime.fromisoformat(_text(raw, name))


def _optional_datetime(raw: Mapping[str, object], name: str) -> datetime | None:
    value = raw.get(name)
    return None if value is None else datetime.fromisoformat(_text(raw, name))


def _text_tuple(raw: Mapping[str, object], name: str) -> tuple[str, ...]:
    value = raw.get(name)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"BINANCE_USDM_RESOURCE_{name.upper()}_INVALID")
    return tuple(value)


__all__ = ["OnlyBinanceUsdmBacktestResourceProvider"]
