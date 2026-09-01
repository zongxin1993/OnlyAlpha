"""Normalize Binance USD-M public payloads into canonical immutable facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.market import OnlyFundingRateFact, OnlyReferencePriceFact
from onlyalpha.domain.trading import OnlyReferencePriceKind
from onlyalpha.domain.value import OnlyPrice


@dataclass(frozen=True, slots=True)
class OnlyBinanceUsdmHistoricalNormalizer:
    source: str = "BINANCE_USDM"

    def reference_price(
        self,
        raw: dict[str, object],
        *,
        instrument_id: OnlyInstrumentId,
        kind: OnlyReferencePriceKind,
        data_version: str,
        source_sequence: int,
        received_at: datetime,
    ) -> OnlyReferencePriceFact:
        if kind not in {OnlyReferencePriceKind.MARK, OnlyReferencePriceKind.INDEX}:
            raise ValueError("BINANCE_USDM_REFERENCE_KIND_UNSUPPORTED")
        price_field = "p" if kind is OnlyReferencePriceKind.MARK else "i"
        timestamp = _timestamp(raw, "T")
        value = _decimal(raw, price_field)
        exponent = value.as_tuple().exponent
        if not isinstance(exponent, int):
            raise ValueError(f"BINANCE_USDM_{price_field.upper()}_INVALID")
        fact_id = _fact_id("REFERENCE_PRICE", instrument_id, kind.value, timestamp, source_sequence, data_version)
        return OnlyReferencePriceFact(
            fact_id,
            instrument_id,
            kind,
            OnlyPrice(value, max(-exponent, 0)),
            timestamp,
            _utc(received_at),
            self.source,
            source_sequence,
            data_version,
        )

    def funding_rate(
        self,
        raw: dict[str, object],
        *,
        instrument_id: OnlyInstrumentId,
        data_version: str,
        source_sequence: int,
        received_at: datetime,
    ) -> OnlyFundingRateFact:
        timestamp = _timestamp(raw, "fundingTime")
        fact_id = _fact_id("FUNDING_RATE", instrument_id, "FUNDING", timestamp, source_sequence, data_version)
        return OnlyFundingRateFact(
            fact_id,
            instrument_id,
            _decimal(raw, "fundingRate"),
            timestamp,
            _utc(received_at),
            self.source,
            source_sequence,
            data_version,
        )


def _decimal(raw: dict[str, object], name: str) -> Decimal:
    value = raw.get(name)
    if not isinstance(value, str):
        raise ValueError(f"BINANCE_USDM_{name.upper()}_REQUIRED")
    result = Decimal(value)
    if not result.is_finite():
        raise ValueError(f"BINANCE_USDM_{name.upper()}_INVALID")
    return result


def _timestamp(raw: dict[str, object], name: str) -> datetime:
    value = raw.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"BINANCE_USDM_{name.upper()}_REQUIRED")
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("BINANCE_USDM_RECEIVED_AT_UTC_REQUIRED")
    return value.astimezone(UTC)


def _fact_id(
    family: str,
    instrument_id: OnlyInstrumentId,
    kind: str,
    timestamp: datetime,
    source_sequence: int,
    data_version: str,
) -> str:
    payload = "\x1f".join((family, str(instrument_id), kind, timestamp.isoformat(), str(source_sequence), data_version))
    return f"BINANCE-USDM-{family}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


__all__ = ["OnlyBinanceUsdmHistoricalNormalizer"]
