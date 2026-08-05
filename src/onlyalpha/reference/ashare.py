"""Versioned, fail-closed China A-share reference-data authority."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from onlyalpha.domain.identifiers import OnlyInstrumentId
from onlyalpha.domain.time import OnlyTradingDay
from onlyalpha.domain.value import OnlyPrice, OnlyQuantity


class OnlyAshareExchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"


class OnlyAshareSecurityType(StrEnum):
    COMMON_STOCK = "COMMON_STOCK"


class OnlyAshareBoard(StrEnum):
    SSE_MAIN = "SSE_MAIN"
    SZSE_MAIN = "SZSE_MAIN"
    CHINEXT = "CHINEXT"
    STAR = "STAR"


class OnlyReferenceDataSource(StrEnum):
    CONFIG = "CONFIG"
    MINIQMT = "MINIQMT"
    TUSHARE = "TUSHARE"
    GOLDEN_DATASET = "GOLDEN_DATASET"
    SCENARIO = "SCENARIO"


class OnlyAshareReferenceResolutionStatus(StrEnum):
    RESOLVED = "RESOLVED"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED_SECURITY_TYPE = "UNSUPPORTED_SECURITY_TYPE"
    UNSUPPORTED_EXCHANGE = "UNSUPPORTED_EXCHANGE"
    INVALID_REFERENCE = "INVALID_REFERENCE"


class OnlyAshareReferenceError(ValueError):
    """Stable diagnostic error raised at the reference authority boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class OnlyAshareInstrumentReference:
    """One immutable record effective on ``[effective_from, effective_to)``."""

    instrument_id: OnlyInstrumentId
    exchange: OnlyAshareExchange
    security_type: OnlyAshareSecurityType
    board: OnlyAshareBoard
    lot_size: OnlyQuantity
    price_tick: OnlyPrice
    st_status: bool
    suspended: bool
    previous_close: OnlyPrice
    effective_from: OnlyTradingDay
    effective_to: OnlyTradingDay | None
    source: OnlyReferenceDataSource
    source_version: str
    data_version: str
    record_fingerprint: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> OnlyAshareInstrumentReference:
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
        }
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise OnlyAshareReferenceError("REFERENCE_INVALID", f"unknown field: {unknown[0]}")

        def required_text(name: str, code: str = "REFERENCE_INVALID") -> str:
            value = raw.get(name)
            if not isinstance(value, str) or not value.strip():
                raise OnlyAshareReferenceError(code, f"{name} is required text")
            return value.strip()

        def required_bool(name: str) -> bool:
            value = raw.get(name)
            if not isinstance(value, bool):
                code = "REFERENCE_ST_STATUS_UNKNOWN" if name == "st_status" else "REFERENCE_SUSPENSION_STATUS_UNKNOWN"
                raise OnlyAshareReferenceError(code, f"{name} must be explicit boolean")
            return value

        def exact_decimal(name: str, code: str, missing_code: str | None = None) -> Decimal:
            value = raw.get(name)
            if value is None:
                raise OnlyAshareReferenceError(missing_code or code, f"{name} is required")
            if not isinstance(value, str):
                raise OnlyAshareReferenceError(code, f"{name} must be a quoted Decimal string")
            try:
                return Decimal(value)
            except ArithmeticError as exc:
                raise OnlyAshareReferenceError(code, f"{name} must be an exact Decimal") from exc

        effective_to = raw.get("effective_to")
        fingerprint = raw.get("record_fingerprint", "")
        if fingerprint is not None and not isinstance(fingerprint, str):
            raise OnlyAshareReferenceError("REFERENCE_FINGERPRINT_MISMATCH", "record_fingerprint must be text")
        try:
            exchange_text = required_text("exchange", "REFERENCE_EXCHANGE_UNSUPPORTED").upper()
            exchange_text = {"XSHG": "SSE", "XSHE": "SZSE"}.get(exchange_text, exchange_text)
            try:
                exchange = OnlyAshareExchange(exchange_text)
            except ValueError as exc:
                raise OnlyAshareReferenceError(
                    "REFERENCE_EXCHANGE_UNSUPPORTED", f"unsupported exchange: {exchange_text}"
                ) from exc
            board_text = required_text("board", "REFERENCE_BOARD_MISSING").upper()
            if board_text == "MAIN":
                board_text = "SSE_MAIN" if exchange_text == "SSE" else "SZSE_MAIN"
            try:
                board = OnlyAshareBoard(board_text)
            except ValueError as exc:
                raise OnlyAshareReferenceError(
                    "REFERENCE_BOARD_UNSUPPORTED", f"unsupported board: {board_text}"
                ) from exc
            security_text = required_text("security_type", "REFERENCE_SECURITY_TYPE_UNSUPPORTED").upper()
            try:
                security_type = OnlyAshareSecurityType(security_text)
            except ValueError as exc:
                raise OnlyAshareReferenceError(
                    "REFERENCE_SECURITY_TYPE_UNSUPPORTED", f"unsupported security_type: {security_text}"
                ) from exc
            return cls(
                OnlyInstrumentId.parse(required_text("instrument_id")),
                exchange,
                security_type,
                board,
                OnlyQuantity(exact_decimal("lot_size", "REFERENCE_LOT_SIZE_INVALID"), 18),
                OnlyPrice(exact_decimal("price_tick", "REFERENCE_PRICE_TICK_INVALID"), 18),
                required_bool("st_status"),
                required_bool("suspended"),
                OnlyPrice(
                    exact_decimal(
                        "previous_close",
                        "REFERENCE_PREVIOUS_CLOSE_INVALID",
                        "REFERENCE_PREVIOUS_CLOSE_MISSING",
                    ),
                    18,
                ),
                OnlyTradingDay(date.fromisoformat(required_text("effective_from"))),
                None if effective_to is None else OnlyTradingDay(date.fromisoformat(required_text("effective_to"))),
                OnlyReferenceDataSource(required_text("source").upper()),
                required_text("source_version", "REFERENCE_SOURCE_VERSION_MISSING"),
                required_text("data_version", "REFERENCE_DATA_VERSION_MISSING"),
                "" if fingerprint is None else fingerprint,
            )
        except OnlyAshareReferenceError:
            raise
        except (ArithmeticError, ValueError) as exc:
            raise OnlyAshareReferenceError("REFERENCE_INVALID", str(exc)) from exc

    def __post_init__(self) -> None:
        if self.lot_size.value <= 0:
            raise OnlyAshareReferenceError("REFERENCE_LOT_SIZE_INVALID", "lot_size must be positive")
        if self.price_tick.value <= 0:
            raise OnlyAshareReferenceError("REFERENCE_PRICE_TICK_INVALID", "price_tick must be positive")
        if self.previous_close.value <= 0:
            raise OnlyAshareReferenceError("REFERENCE_PREVIOUS_CLOSE_INVALID", "previous_close must be positive")
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise OnlyAshareReferenceError(
                "REFERENCE_EFFECTIVE_RANGE_INVALID", "effective_to must be after effective_from"
            )
        if not self.source_version.strip():
            raise OnlyAshareReferenceError("REFERENCE_SOURCE_VERSION_MISSING", "source_version is required")
        if not str(self.data_version).strip():
            raise OnlyAshareReferenceError("REFERENCE_DATA_VERSION_MISSING", "data_version is required")
        expected_exchange = {"XSHG": OnlyAshareExchange.SSE, "XSHE": OnlyAshareExchange.SZSE}.get(
            str(self.instrument_id.venue)
        )
        if expected_exchange is None or self.exchange is not expected_exchange:
            raise OnlyAshareReferenceError(
                "REFERENCE_EXCHANGE_UNSUPPORTED",
                f"{self.instrument_id} is incompatible with exchange {self.exchange.value}",
            )
        supported_boards = {
            OnlyAshareExchange.SSE: {OnlyAshareBoard.SSE_MAIN, OnlyAshareBoard.STAR},
            OnlyAshareExchange.SZSE: {OnlyAshareBoard.SZSE_MAIN, OnlyAshareBoard.CHINEXT},
        }
        if self.board not in supported_boards[self.exchange]:
            raise OnlyAshareReferenceError(
                "REFERENCE_BOARD_UNSUPPORTED",
                f"board {self.board.value} is incompatible with {self.exchange.value}",
            )
        expected = self.compute_fingerprint()
        if self.record_fingerprint and self.record_fingerprint != expected:
            raise OnlyAshareReferenceError(
                "REFERENCE_FINGERPRINT_MISMATCH", f"record fingerprint mismatch for {self.instrument_id}"
            )
        object.__setattr__(self, "record_fingerprint", expected)

    def canonical_payload(self) -> dict[str, str | bool | None]:
        return {
            "board": self.board.value,
            "data_version": str(self.data_version),
            "effective_from": self.effective_from.value.isoformat(),
            "effective_to": None if self.effective_to is None else self.effective_to.value.isoformat(),
            "exchange": self.exchange.value,
            "instrument_id": str(self.instrument_id),
            "lot_size": str(self.lot_size.value),
            "previous_close": str(self.previous_close.value),
            "price_tick": str(self.price_tick.value),
            "security_type": self.security_type.value,
            "source": self.source.value,
            "source_version": self.source_version,
            "st_status": self.st_status,
            "suspended": self.suspended,
        }

    def to_dict(self) -> dict[str, str | bool | None]:
        return {**self.canonical_payload(), "record_fingerprint": self.record_fingerprint}

    def compute_fingerprint(self) -> str:
        payload = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def is_effective_on(self, trading_day: OnlyTradingDay) -> bool:
        return self.effective_from <= trading_day and (self.effective_to is None or trading_day < self.effective_to)


@dataclass(frozen=True, slots=True)
class OnlyAshareReferenceResolution:
    status: OnlyAshareReferenceResolutionStatus
    instrument_id: OnlyInstrumentId
    trading_day: OnlyTradingDay
    snapshot: OnlyAshareInstrumentReference | None = None
    failure_code: str | None = None

    def require_snapshot(self) -> OnlyAshareInstrumentReference:
        if self.status is not OnlyAshareReferenceResolutionStatus.RESOLVED or self.snapshot is None:
            raise OnlyAshareReferenceError(
                self.failure_code or "REFERENCE_INVALID",
                f"cannot resolve {self.instrument_id} on {self.trading_day.value.isoformat()}",
            )
        return self.snapshot


class OnlyAshareReferenceRegistry:
    """The sole indexed authority for versioned A-share records."""

    def __init__(self, records: tuple[OnlyAshareInstrumentReference, ...] = ()) -> None:
        self._records: dict[OnlyInstrumentId, list[OnlyAshareInstrumentReference]] = {}
        self._fingerprint_payloads: dict[str, str] = {}
        for record in records:
            self.register(record)

    def register(self, record: OnlyAshareInstrumentReference) -> None:
        payload = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
        known_payload = self._fingerprint_payloads.get(record.record_fingerprint)
        if known_payload is not None and known_payload != payload:
            raise OnlyAshareReferenceError(
                "REFERENCE_FINGERPRINT_MISMATCH", "one fingerprint identifies different payloads"
            )
        values = self._records.setdefault(record.instrument_id, [])
        for existing in values:
            if existing == record:
                return
            if (
                existing.source is record.source
                and existing.source_version == record.source_version
                and existing.effective_from == record.effective_from
                and existing.effective_to == record.effective_to
            ):
                raise OnlyAshareReferenceError(
                    "REFERENCE_RUNTIME_CONFLICT", "same source version identifies different content"
                )
            if _overlaps(existing, record):
                raise OnlyAshareReferenceError(
                    "REFERENCE_EFFECTIVE_RANGE_OVERLAP",
                    f"overlapping records for {record.instrument_id}",
                )
        values.append(record)
        values.sort(key=lambda item: (item.effective_from.value, item.record_fingerprint))
        self._fingerprint_payloads[record.record_fingerprint] = payload

    @property
    def records(self) -> tuple[OnlyAshareInstrumentReference, ...]:
        return tuple(
            sorted(
                (item for values in self._records.values() for item in values),
                key=lambda item: (str(item.instrument_id), item.effective_from.value, item.record_fingerprint),
            )
        )

    @property
    def fingerprint(self) -> str:
        payload = json.dumps([item.to_dict() for item in self.records], sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> OnlyAshareReferenceResolution:
        matches = tuple(item for item in self._records.get(instrument_id, ()) if item.is_effective_on(trading_day))
        if not matches:
            return OnlyAshareReferenceResolution(
                OnlyAshareReferenceResolutionStatus.NOT_FOUND,
                instrument_id,
                trading_day,
                failure_code="REFERENCE_NOT_FOUND",
            )
        if len(matches) != 1:
            return OnlyAshareReferenceResolution(
                OnlyAshareReferenceResolutionStatus.AMBIGUOUS,
                instrument_id,
                trading_day,
                failure_code="REFERENCE_AMBIGUOUS",
            )
        return OnlyAshareReferenceResolution(
            OnlyAshareReferenceResolutionStatus.RESOLVED, instrument_id, trading_day, matches[0]
        )


class OnlyAshareReferenceQuery:
    def __init__(self, registry: OnlyAshareReferenceRegistry) -> None:
        self._registry = registry

    @property
    def registry_fingerprint(self) -> str:
        return self._registry.fingerprint

    @property
    def records(self) -> tuple[OnlyAshareInstrumentReference, ...]:
        return self._registry.records

    def resolve(self, instrument_id: OnlyInstrumentId, trading_day: OnlyTradingDay) -> OnlyAshareReferenceResolution:
        return self._registry.resolve(instrument_id, trading_day)


def _overlaps(left: OnlyAshareInstrumentReference, right: OnlyAshareInstrumentReference) -> bool:
    left_end = left.effective_to.value if left.effective_to is not None else None
    right_end = right.effective_to.value if right.effective_to is not None else None
    return (right_end is None or left.effective_from.value < right_end) and (
        left_end is None or right.effective_from.value < left_end
    )
