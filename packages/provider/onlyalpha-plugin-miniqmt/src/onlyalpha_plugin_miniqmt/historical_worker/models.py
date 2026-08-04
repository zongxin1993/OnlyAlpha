"""JSON-only transport model construction and validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .protocol import PROTOCOL_VERSION, fingerprint


class OnlyMiniQmtProtocolVersionMismatch(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class OnlyMiniQmtWorkerRequest:
    request_id: str
    userdata_mini_path: str
    instrument_id: str
    xt_symbol: str
    period: str
    required_bars: int
    requested_start: str
    requested_start_ns: int
    end_time: str
    end_time_ns: int
    bootstrap_observed_at: str
    bootstrap_observed_at_ns: int
    fields: tuple[str, ...]
    adjustment: str
    fill_data: bool
    price_precision: int
    quantity_precision: int
    compatibility_profile_id: str
    query_mode: str
    download_before_query: bool
    overlap_bars: int
    maximum_count: int

    def payload(self) -> dict[str, object]:
        return {
            "protocol_version": PROTOCOL_VERSION,
            "request_id": self.request_id,
            "userdata_mini_path": self.userdata_mini_path,
            "instrument_id": self.instrument_id,
            "xt_symbol": self.xt_symbol,
            "period": self.period,
            "required_bars": self.required_bars,
            "requested_start": self.requested_start,
            "requested_start_ns": self.requested_start_ns,
            "end_time": self.end_time,
            "end_time_ns": self.end_time_ns,
            "bootstrap_observed_at": self.bootstrap_observed_at,
            "bootstrap_observed_at_ns": self.bootstrap_observed_at_ns,
            "fields": list(self.fields),
            "adjustment": self.adjustment,
            "fill_data": self.fill_data,
            "price_precision": self.price_precision,
            "quantity_precision": self.quantity_precision,
            "compatibility_profile_id": self.compatibility_profile_id,
            "query_mode": self.query_mode,
            "download_before_query": self.download_before_query,
            "overlap_bars": self.overlap_bars,
            "maximum_count": self.maximum_count,
        }

    @property
    def request_fingerprint(self) -> str:
        return fingerprint(self.payload())

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> OnlyMiniQmtWorkerRequest:
        if raw.get("protocol_version") != PROTOCOL_VERSION:
            raise OnlyMiniQmtProtocolVersionMismatch("unsupported historical worker protocol version")
        fields = raw.get("fields")
        if not isinstance(fields, list) or not all(isinstance(item, str) for item in fields):
            raise ValueError("historical worker fields must be strings")
        result = cls(
            request_id=str(raw["request_id"]),
            userdata_mini_path=str(raw["userdata_mini_path"]),
            instrument_id=str(raw["instrument_id"]),
            xt_symbol=str(raw["xt_symbol"]),
            period=str(raw["period"]),
            required_bars=int(raw["required_bars"]),
            requested_start=str(raw["requested_start"]),
            requested_start_ns=int(raw["requested_start_ns"]),
            end_time=str(raw["end_time"]),
            end_time_ns=int(raw["end_time_ns"]),
            bootstrap_observed_at=str(raw["bootstrap_observed_at"]),
            bootstrap_observed_at_ns=int(raw["bootstrap_observed_at_ns"]),
            fields=tuple(fields),
            adjustment=str(raw["adjustment"]),
            fill_data=bool(raw["fill_data"]),
            price_precision=int(raw["price_precision"]),
            quantity_precision=int(raw["quantity_precision"]),
            compatibility_profile_id=str(raw["compatibility_profile_id"]),
            query_mode=str(raw["query_mode"]),
            download_before_query=bool(raw["download_before_query"]),
            overlap_bars=int(raw["overlap_bars"]),
            maximum_count=int(raw["maximum_count"]),
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.request_id.strip() or not self.instrument_id or not self.xt_symbol:
            raise ValueError("historical worker identifiers are required")
        if self.required_bars <= 0 or self.maximum_count < self.required_bars or self.overlap_bars < 0:
            raise ValueError("historical worker Bar counts are invalid")
        if self.requested_start_ns >= self.end_time_ns or self.end_time_ns > self.bootstrap_observed_at_ns:
            raise ValueError("historical worker frozen request boundaries are invalid")
        if self.price_precision < 0 or self.quantity_precision < 0:
            raise ValueError("historical worker precisions cannot be negative")
        if not Path(self.userdata_mini_path).is_dir():
            raise ValueError("userdata_mini_path is not a directory")
