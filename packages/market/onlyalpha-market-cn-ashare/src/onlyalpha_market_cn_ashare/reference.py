"""Versioned, fail-closed CN A-share reference authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from onlyalpha.plugin.api import (
    OnlyInstrumentId,
    OnlyMarketProductAuthorityIdentity,
    OnlyTradingDay,
)


class OnlyCnAshareExchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"


class OnlyCnAshareSecurityType(StrEnum):
    COMMON_STOCK = "COMMON_STOCK"


class OnlyCnAshareBoard(StrEnum):
    SSE_MAIN = "SSE_MAIN"
    SZSE_MAIN = "SZSE_MAIN"
    CHINEXT = "CHINEXT"
    STAR = "STAR"


class OnlyCnAshareReferenceSource(StrEnum):
    CONFIG = "CONFIG"
    MINIQMT = "MINIQMT"
    TUSHARE = "TUSHARE"
    GOLDEN_DATASET = "GOLDEN_DATASET"
    SCENARIO = "SCENARIO"


class OnlyCnAshareReferenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class OnlyCnAshareInstrumentReference:
    instrument_id: OnlyInstrumentId
    exchange: OnlyCnAshareExchange
    security_type: OnlyCnAshareSecurityType
    board: OnlyCnAshareBoard
    lot_size: Decimal
    price_tick: Decimal
    st_status: bool
    suspended: bool
    previous_close: Decimal
    effective_from: date
    effective_to: date | None
    source: OnlyCnAshareReferenceSource
    source_version: str
    data_version: str
    content_fingerprint: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> OnlyCnAshareInstrumentReference:
        allowed = {
            "instrument_id",
            "exchange",
            "security_type",
            "board",
            "lot_size",
            "price_tick",
            "st_status",
            "suspended",
            "previous_close",
            "effective_from",
            "effective_to",
            "source",
            "source_version",
            "data_version",
            "record_fingerprint",
            "content_fingerprint",
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise OnlyCnAshareReferenceError("REFERENCE_INVALID", f"unknown field: {unknown[0]}")

        def text(name: str) -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value.strip():
                code = {
                    "board": "REFERENCE_BOARD_MISSING",
                    "source_version": "REFERENCE_SOURCE_VERSION_MISSING",
                    "data_version": "REFERENCE_DATA_VERSION_MISSING",
                }.get(name, "REFERENCE_INVALID")
                raise OnlyCnAshareReferenceError(code, f"{name} is required text")
            return value.strip()

        def decimal(name: str) -> Decimal:
            value = raw.get(name)
            if not isinstance(value, str):
                if name == "previous_close" and value is None:
                    raise OnlyCnAshareReferenceError("REFERENCE_PREVIOUS_CLOSE_MISSING", "previous_close is required")
                code = {
                    "lot_size": "REFERENCE_LOT_SIZE_INVALID",
                    "price_tick": "REFERENCE_PRICE_TICK_INVALID",
                    "previous_close": "REFERENCE_PREVIOUS_CLOSE_INVALID",
                }[name]
                raise OnlyCnAshareReferenceError(code, f"{name} must be a quoted Decimal string")
            try:
                return Decimal(value)
            except InvalidOperation as exc:
                raise OnlyCnAshareReferenceError(
                    f"REFERENCE_{name.upper()}_INVALID", f"{name} must be an exact Decimal"
                ) from exc

        def boolean(name: str) -> bool:
            value = raw.get(name)
            if not isinstance(value, bool):
                code = "REFERENCE_ST_STATUS_UNKNOWN" if name == "st_status" else "REFERENCE_SUSPENSION_STATUS_UNKNOWN"
                raise OnlyCnAshareReferenceError(code, f"{name} must be an explicit boolean")
            return value

        exchange_text = {"XSHG": "SSE", "XSHE": "SZSE"}.get(text("exchange").upper(), text("exchange").upper())
        try:
            exchange = OnlyCnAshareExchange(exchange_text)
        except ValueError as exc:
            raise OnlyCnAshareReferenceError("REFERENCE_EXCHANGE_UNSUPPORTED", exchange_text) from exc
        board_text = text("board").upper()
        if board_text == "MAIN":
            board_text = "SSE_MAIN" if exchange is OnlyCnAshareExchange.SSE else "SZSE_MAIN"
        try:
            security_type = OnlyCnAshareSecurityType(text("security_type").upper())
        except ValueError as exc:
            raise OnlyCnAshareReferenceError(
                "REFERENCE_SECURITY_TYPE_UNSUPPORTED", str(raw.get("security_type"))
            ) from exc
        try:
            board = OnlyCnAshareBoard(board_text)
        except ValueError as exc:
            raise OnlyCnAshareReferenceError("REFERENCE_BOARD_UNSUPPORTED", board_text) from exc
        payload = (
            OnlyInstrumentId.parse(text("instrument_id")),
            exchange,
            security_type,
            board,
            decimal("lot_size"),
            decimal("price_tick"),
            boolean("st_status"),
            boolean("suspended"),
            decimal("previous_close"),
            date.fromisoformat(text("effective_from")),
            None if raw.get("effective_to") is None else date.fromisoformat(text("effective_to")),
            OnlyCnAshareReferenceSource(text("source").upper()),
            text("source_version"),
            text("data_version"),
        )
        canonical = {
            "board": payload[3].value,
            "data_version": payload[13],
            "effective_from": payload[9].isoformat(),
            "effective_to": None if payload[10] is None else payload[10].isoformat(),
            "exchange": payload[1].value,
            "instrument_id": str(payload[0]),
            "lot_size": str(payload[4]),
            "previous_close": str(payload[8]),
            "price_tick": str(payload[5]),
            "security_type": payload[2].value,
            "source": payload[11].value,
            "source_version": payload[12],
            "st_status": payload[6],
            "suspended": payload[7],
        }
        fingerprint = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        supplied = raw.get("content_fingerprint", raw.get("record_fingerprint", ""))
        if supplied not in {"", None, fingerprint}:
            raise OnlyCnAshareReferenceError("REFERENCE_FINGERPRINT_MISMATCH", str(payload[0]))
        return cls(*payload, fingerprint)

    def __post_init__(self) -> None:
        if self.lot_size <= 0:
            raise OnlyCnAshareReferenceError("REFERENCE_LOT_SIZE_INVALID", "lot size must be positive")
        if self.price_tick <= 0:
            raise OnlyCnAshareReferenceError("REFERENCE_PRICE_TICK_INVALID", "price tick must be positive")
        if self.previous_close <= 0:
            raise OnlyCnAshareReferenceError("REFERENCE_PREVIOUS_CLOSE_INVALID", "previous close must be positive")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise OnlyCnAshareReferenceError("REFERENCE_EFFECTIVE_RANGE_INVALID", str(self.instrument_id))
        expected_exchange = {"XSHG": OnlyCnAshareExchange.SSE, "XSHE": OnlyCnAshareExchange.SZSE}.get(
            str(self.instrument_id.venue)
        )
        if expected_exchange is not self.exchange:
            raise OnlyCnAshareReferenceError("REFERENCE_EXCHANGE_UNSUPPORTED", str(self.instrument_id))
        allowed = {
            OnlyCnAshareExchange.SSE: {OnlyCnAshareBoard.SSE_MAIN, OnlyCnAshareBoard.STAR},
            OnlyCnAshareExchange.SZSE: {OnlyCnAshareBoard.SZSE_MAIN, OnlyCnAshareBoard.CHINEXT},
        }
        if self.board not in allowed[self.exchange]:
            raise OnlyCnAshareReferenceError("REFERENCE_BOARD_UNSUPPORTED", self.board.value)

    def is_effective_on(self, day: OnlyTradingDay) -> bool:
        return self.effective_from <= day.value and (self.effective_to is None or day.value < self.effective_to)

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "instrument_id": str(self.instrument_id),
            "exchange": self.exchange.value,
            "security_type": self.security_type.value,
            "board": self.board.value,
            "lot_size": str(self.lot_size),
            "price_tick": str(self.price_tick),
            "st_status": self.st_status,
            "suspended": self.suspended,
            "previous_close": str(self.previous_close),
            "effective_from": self.effective_from.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.isoformat(),
            "source": self.source.value,
            "source_version": self.source_version,
            "data_version": self.data_version,
            "record_fingerprint": self.content_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class OnlyCnAshareReferenceAuthority:
    references: tuple[OnlyCnAshareInstrumentReference, ...]
    identity: OnlyMarketProductAuthorityIdentity

    @classmethod
    def create(cls, references: tuple[OnlyCnAshareInstrumentReference, ...]) -> OnlyCnAshareReferenceAuthority:
        ordered = tuple(sorted(references, key=lambda item: (str(item.instrument_id), item.effective_from)))
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if left.instrument_id != right.instrument_id:
                    break
                if (right.effective_to is None or left.effective_from < right.effective_to) and (
                    left.effective_to is None or right.effective_from < left.effective_to
                ):
                    raise OnlyCnAshareReferenceError("REFERENCE_EFFECTIVE_RANGE_OVERLAP", str(left.instrument_id))
        fingerprint = hashlib.sha256(
            json.dumps([item.to_dict() for item in ordered], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return cls(ordered, OnlyMarketProductAuthorityIdentity("REFERENCE", "CN_A_SHARE", "1", fingerprint))

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> OnlyCnAshareInstrumentReference:
        matches = tuple(
            item
            for item in self.references
            if item.instrument_id == instrument_id and item.is_effective_on(trading_day)
        )
        if not matches:
            raise OnlyCnAshareReferenceError("REFERENCE_NOT_FOUND", f"{instrument_id} on {trading_day.value}")
        if len(matches) != 1:
            raise OnlyCnAshareReferenceError("REFERENCE_AMBIGUOUS", f"{instrument_id} on {trading_day.value}")
        return matches[0]


__all__ = [
    "OnlyCnAshareBoard",
    "OnlyCnAshareExchange",
    "OnlyCnAshareInstrumentReference",
    "OnlyCnAshareReferenceAuthority",
    "OnlyCnAshareReferenceError",
    "OnlyCnAshareReferenceSource",
    "OnlyCnAshareSecurityType",
]
