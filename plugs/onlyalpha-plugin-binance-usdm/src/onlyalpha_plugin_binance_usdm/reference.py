"""Immutable normalized Binance USD-M public and account-effective authorities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, time
from decimal import Decimal

from onlyalpha.domain.enums import OnlyMarginMode
from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.trading import OnlyPositionMode, OnlyReferencePriceKind
from onlyalpha.identity import only_identity_fingerprint
from onlyalpha.market.economics import OnlyAccountEffectiveTradingInputs, OnlyMarginRequirementSegment
from onlyalpha.market.product import OnlyMarketProductAuthorityIdentity, OnlyMarketProductResolutionError

_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _utc(value: datetime, code: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(code)
    return value.astimezone(UTC)


def _require_digest(value: str, code: str) -> None:
    if not _DIGEST.fullmatch(value):
        raise ValueError(code)


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmFundingScheduleReference:
    interval_seconds: int
    boundary_offset_seconds: int
    valuation_price_kind: OnlyReferencePriceKind
    provider_semantic_version: str

    def __post_init__(self) -> None:
        if (
            self.interval_seconds <= 0
            or not 0 <= self.boundary_offset_seconds < self.interval_seconds
            or self.valuation_price_kind is not OnlyReferencePriceKind.MARK
            or not self.provider_semantic_version.strip()
        ):
            raise ValueError("BINANCE_USDM_FUNDING_SCHEDULE_INVALID")

    def canonical_identity(self) -> tuple[object, ...]:
        return (
            self.interval_seconds,
            self.boundary_offset_seconds,
            self.valuation_price_kind,
            self.provider_semantic_version,
        )


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmPublicMarketReference:
    instrument_id: OnlyInstrumentId
    raw_symbol: str
    provider_status: str
    settlement_currency: str
    contract_multiplier: Decimal
    price_tick: Decimal
    minimum_price: Decimal | None
    maximum_price: Decimal | None
    quantity_step: Decimal
    minimum_quantity: Decimal
    maximum_quantity: Decimal | None
    minimum_notional: Decimal | None
    funding_schedule: OnlyBinanceUsdmFundingScheduleReference
    coverage_start: datetime
    coverage_end: datetime | None
    observed_at: datetime
    published_at: datetime
    provider_revision: str
    normalizer_semantic_version: str
    provider_schema_semantic_version: str
    source_raw_fingerprints: tuple[str, ...]
    content_fingerprint: str

    @classmethod
    def create(cls, **values: object) -> OnlyBinanceUsdmPublicMarketReference:
        for name in ("coverage_start", "observed_at", "published_at"):
            value = values.get(name)
            if not isinstance(value, datetime):
                raise ValueError(f"BINANCE_USDM_{name.upper()}_UTC_REQUIRED")
            values[name] = _utc(value, f"BINANCE_USDM_{name.upper()}_UTC_REQUIRED")
        coverage_end = values.get("coverage_end")
        if coverage_end is not None:
            if not isinstance(coverage_end, datetime):
                raise ValueError("BINANCE_USDM_COVERAGE_END_UTC_REQUIRED")
            values["coverage_end"] = _utc(coverage_end, "BINANCE_USDM_COVERAGE_END_UTC_REQUIRED")
        values["content_fingerprint"] = only_identity_fingerprint(cls._content_payload(values))
        return cls(**values)  # type: ignore[arg-type]

    @staticmethod
    def _content_payload(values: dict[str, object]) -> tuple[object, ...]:
        authority_fields = {
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
        return tuple(
            (name, str(value) if name == "instrument_id" else value)
            for name, value in sorted(values.items())
            if name not in authority_fields
        )

    def __post_init__(self) -> None:
        if (
            not self.raw_symbol.strip()
            or not self.settlement_currency.strip()
            or self.contract_multiplier <= 0
            or self.price_tick <= 0
            or self.quantity_step <= 0
            or self.minimum_quantity <= 0
            or self.coverage_end is not None
            and self.coverage_end <= self.coverage_start
        ):
            raise ValueError("BINANCE_USDM_PUBLIC_REFERENCE_INVALID")
        if not self.source_raw_fingerprints:
            raise ValueError("BINANCE_USDM_PUBLIC_REFERENCE_RAW_EVIDENCE_REQUIRED")
        for fingerprint in self.source_raw_fingerprints:
            _require_digest(fingerprint, "BINANCE_USDM_PUBLIC_REFERENCE_RAW_FINGERPRINT_INVALID")
        values = {name: getattr(self, name) for name in self.__dataclass_fields__}
        if self.content_fingerprint != only_identity_fingerprint(self._content_payload(values)):
            raise ValueError("BINANCE_USDM_PUBLIC_REFERENCE_CONTENT_FINGERPRINT_CONFLICT")

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.content_fingerprint,
            self.coverage_start,
            self.coverage_end,
            self.observed_at,
            self.published_at,
            self.provider_revision,
            self.normalizer_semantic_version,
            self.provider_schema_semantic_version,
            self.source_raw_fingerprints,
        )


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmPublicReferenceAuthority:
    references: tuple[OnlyBinanceUsdmPublicMarketReference, ...]
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(
        cls, references: tuple[OnlyBinanceUsdmPublicMarketReference, ...]
    ) -> OnlyBinanceUsdmPublicReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: (str(item.instrument_id), item.coverage_start)))
        if not ordered:
            raise ValueError("BINANCE_USDM_PUBLIC_REFERENCE_EMPTY")
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.instrument_id == current.instrument_id and (
                previous.coverage_end is None or previous.coverage_end > current.coverage_start
            ):
                raise ValueError("BINANCE_USDM_PUBLIC_REFERENCE_COVERAGE_AMBIGUOUS")
        fingerprint = only_identity_fingerprint(tuple(item.authority_payload() for item in ordered))
        return cls(ordered, OnlyMarketProductAuthorityIdentity("REFERENCE", "BINANCE_USDM_PUBLIC", "2", fingerprint))

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.references, key=lambda item: (str(item.instrument_id), item.coverage_start)))
        fingerprint = only_identity_fingerprint(tuple(item.authority_payload() for item in ordered))
        expected = OnlyMarketProductAuthorityIdentity("REFERENCE", "BINANCE_USDM_PUBLIC", "2", fingerprint)
        if self.references != ordered or self.identity != expected:
            raise ValueError("BINANCE_USDM_PUBLIC_AUTHORITY_FINGERPRINT_CONFLICT")

    def resolve(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyBinanceUsdmPublicMarketReference:
        point = (
            datetime.combine(trading_day.value, time.min, tzinfo=UTC)
            if as_of is None
            else _utc(as_of, "BINANCE_USDM_AS_OF_UTC_REQUIRED")
        )
        matches = tuple(
            item
            for item in self.references
            if item.instrument_id == instrument_id
            and item.coverage_start <= point
            and (item.coverage_end is None or point < item.coverage_end)
        )
        if len(matches) != 1:
            code = (
                "BINANCE_USDM_PUBLIC_REFERENCE_NOT_FOUND" if not matches else "BINANCE_USDM_PUBLIC_REFERENCE_AMBIGUOUS"
            )
            raise OnlyMarketProductResolutionError(code, f"{instrument_id}@{point.isoformat()}")
        return matches[0]


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmAccountTradingReference:
    instrument_id: OnlyInstrumentId
    effective_inputs: OnlyAccountEffectiveTradingInputs
    margin_segments: tuple[OnlyMarginRequirementSegment, ...]
    coverage_start: datetime
    coverage_end: datetime | None
    observed_at: datetime
    provider_revision: str
    normalizer_semantic_version: str
    provider_schema_semantic_version: str
    source_raw_fingerprints: tuple[str, ...]
    content_fingerprint: str

    @classmethod
    def create(cls, **values: object) -> OnlyBinanceUsdmAccountTradingReference:
        for name in ("coverage_start", "observed_at"):
            value = values.get(name)
            if not isinstance(value, datetime):
                raise ValueError(f"BINANCE_USDM_ACCOUNT_{name.upper()}_UTC_REQUIRED")
            values[name] = _utc(value, f"BINANCE_USDM_ACCOUNT_{name.upper()}_UTC_REQUIRED")
        coverage_end = values.get("coverage_end")
        if coverage_end is not None:
            if not isinstance(coverage_end, datetime):
                raise ValueError("BINANCE_USDM_ACCOUNT_COVERAGE_END_UTC_REQUIRED")
            values["coverage_end"] = _utc(coverage_end, "BINANCE_USDM_ACCOUNT_COVERAGE_END_UTC_REQUIRED")
        segments = values.get("margin_segments")
        if not isinstance(segments, tuple) or not all(
            isinstance(item, OnlyMarginRequirementSegment) for item in segments
        ):
            raise ValueError("BINANCE_USDM_ACCOUNT_MARGIN_SEGMENTS_REQUIRED")
        content = (
            str(values["instrument_id"]),
            values["effective_inputs"],
            tuple(item.canonical_identity() for item in segments),
        )
        values["content_fingerprint"] = only_identity_fingerprint(content)
        return cls(**values)  # type: ignore[arg-type]

    def authority_payload(self) -> tuple[object, ...]:
        return (
            self.content_fingerprint,
            self.coverage_start,
            self.coverage_end,
            self.observed_at,
            self.provider_revision,
            self.normalizer_semantic_version,
            self.provider_schema_semantic_version,
            self.source_raw_fingerprints,
        )

    def __post_init__(self) -> None:
        if (
            not self.margin_segments
            or self.coverage_end is not None
            and self.coverage_end <= self.coverage_start
            or not self.source_raw_fingerprints
        ):
            raise ValueError("BINANCE_USDM_ACCOUNT_REFERENCE_INVALID")
        for fingerprint in self.source_raw_fingerprints:
            _require_digest(fingerprint, "BINANCE_USDM_ACCOUNT_RAW_FINGERPRINT_INVALID")
        content = only_identity_fingerprint(
            (
                str(self.instrument_id),
                self.effective_inputs,
                tuple(item.canonical_identity() for item in self.margin_segments),
            )
        )
        if self.content_fingerprint != content:
            raise ValueError("BINANCE_USDM_ACCOUNT_CONTENT_FINGERPRINT_CONFLICT")


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmAccountReferenceAuthority:
    references: tuple[OnlyBinanceUsdmAccountTradingReference, ...]
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(
        cls, references: tuple[OnlyBinanceUsdmAccountTradingReference, ...]
    ) -> OnlyBinanceUsdmAccountReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: (str(item.instrument_id), item.coverage_start)))
        if not ordered:
            raise ValueError("BINANCE_USDM_ACCOUNT_REFERENCE_EMPTY")
        modes = {
            (
                item.effective_inputs.position_mode,
                item.effective_inputs.margin_mode,
                item.effective_inputs.leverage,
                item.effective_inputs.source_fingerprint,
            )
            for item in ordered
        }
        if len(modes) != 1:
            raise ValueError("BINANCE_USDM_ACCOUNT_EFFECTIVE_PROFILE_AMBIGUOUS")
        fingerprint = only_identity_fingerprint(tuple(item.authority_payload() for item in ordered))
        return cls(ordered, OnlyMarketProductAuthorityIdentity("ACCOUNT_REFERENCE", "BINANCE_USDM", "2", fingerprint))

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.references, key=lambda item: (str(item.instrument_id), item.coverage_start)))
        fingerprint = only_identity_fingerprint(tuple(item.authority_payload() for item in ordered))
        expected = OnlyMarketProductAuthorityIdentity("ACCOUNT_REFERENCE", "BINANCE_USDM", "2", fingerprint)
        if self.references != ordered or self.identity != expected:
            raise ValueError("BINANCE_USDM_ACCOUNT_AUTHORITY_FINGERPRINT_CONFLICT")

    @property
    def effective_inputs(self) -> OnlyAccountEffectiveTradingInputs:
        return self.references[0].effective_inputs

    def resolve(
        self,
        instrument_id: OnlyInstrumentId,
        trading_day: OnlyTradingDay,
        *,
        as_of: datetime | None = None,
    ) -> OnlyBinanceUsdmAccountTradingReference:
        point = (
            datetime.combine(trading_day.value, time.min, tzinfo=UTC)
            if as_of is None
            else _utc(as_of, "BINANCE_USDM_ACCOUNT_AS_OF_UTC_REQUIRED")
        )
        matches = tuple(
            item
            for item in self.references
            if item.instrument_id == instrument_id
            and item.coverage_start <= point
            and (item.coverage_end is None or point < item.coverage_end)
        )
        if len(matches) != 1:
            raise OnlyMarketProductResolutionError(
                "BINANCE_USDM_ACCOUNT_REFERENCE_NOT_FOUND", f"{instrument_id}@{point.isoformat()}"
            )
        return matches[0]


BINANCE_USDM_CAPABILITY = (
    (OnlyPositionMode.NETTING, OnlyPositionMode.HEDGING),
    (OnlyMarginMode.CROSS, OnlyMarginMode.ISOLATED),
)


__all__ = [name for name in globals() if name.startswith("Only") or name == "BINANCE_USDM_CAPABILITY"]
